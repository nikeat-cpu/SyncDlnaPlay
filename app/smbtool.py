# -*- coding: utf-8 -*-
"""
SMB 局域网发现 / 共享浏览 —— Python 版
=====================================
对应安卓独立版的 Smb.java（那一侧用 jcifs-ng 走原生 SMB 协议）。
这一侧刻意**不引入第三方依赖**（项目一直坚持纯标准库），所以：

  1. 「扫描局域网」——纯 socket 并行探 445 端口，无外部依赖，任何环境都能跑；
  2. 「列共享名 / 浏览目录」——调用 `smbclient` 命令行（Samba 客户端）。
     没装时返回明确的 error 文案，前端会照原样显示，不会崩。

必要时在 Dockerfile / 宿主上安装：
    Alpine : apk add samba-client
    Debian : apt-get install smbclient
    macOS  : brew install samba
"""

import ipaddress
import logging
import os
import re
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger("dlna.smb")

SMB_PORT = 445
AUDIO_EXTS = {
    "mp3", "flac", "wav", "m4a", "aac", "ogg", "oga", "opus", "wma",
    "ape", "alac", "aif", "aiff", "mka", "mp4", "m4b", "dsf", "dff",
}


# ---------------------------------------------------------------- 工具

def smbclient_path():
    return shutil.which("smbclient") or ""


def available():
    return bool(smbclient_path())


def local_prefixes(extra_ips=None):
    """本机所在的 /24 网段前缀，例如 ['192.168.1']。

    与 Java 版等价，但**不依赖 Linux 专属 ioctl**（那正是本项目在
    macOS 上踩过的坑），改用纯 stdlib 的几个来源做并集。
    """
    ips = []

    def _add(ip):
        ip = (ip or "").strip()
        if not ip or ip in ips:
            return
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return
        if a.version != 4 or a.is_loopback or a.is_link_local or a.is_unspecified:
            return
        ips.append(ip)

    for ip in (extra_ips or []):
        _add(ip)

    # 1) 主机名解析（多网卡时可能给出多个）
    try:
        _, _, addrs = socket.gethostbyname_ex(socket.gethostname())
        for ip in addrs:
            _add(ip)
    except Exception:  # noqa: BLE001
        pass

    # 2) 借 U 盘路由的 connect 技巧拿默认出口 IP
    for probe in (("8.8.8.8", 53), ("223.5.5.5", 53)):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(probe)
                _add(s.getsockname()[0])
            finally:
                s.close()
        except Exception:  # noqa: BLE001
            pass

    out = []
    for ip in ips:
        p = ip.rsplit(".", 1)[0]
        if p not in out:
            out.append(p)
    return out


def _auth_args(user, password, guest):
    """拼 smbclient 的认证参数"""
    if guest or not (user or "").strip():
        return ["-N"]                       # 匿名 / 访客
    cred = user.strip()
    if password:
        cred = f"{cred}%{password}"
    return ["-U", cred]


def _run(args, timeout=20):
    """跑 smbclient，返回 (ok, stdout, error)"""
    exe = smbclient_path()
    if not exe:
        return False, "", "未安装 smbclient（Alpine: apk add samba-client）"
    try:
        p = subprocess.run([exe] + args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "", "连接超时"
    except Exception as e:  # noqa: BLE001
        return False, "", f"{type(e).__name__}: {e}"
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    if p.returncode != 0:
        return False, out, _clean_err(err) or f"smbclient 退出码 {p.returncode}"
    return True, out, ""


def _clean_err(err):
    """从 smbclient 的 stderr 里挑出人话"""
    for line in (err or "").splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("session setup failed") or "nt_status_" in low:
            return s
    return (err or "").strip().splitlines()[-1] if (err or "").strip() else ""


# ---------------------------------------------------------------- 发现

def _probe_445(ip, timeout=0.45):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, SMB_PORT))
        return ip
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            s.close()
        except OSError:
            pass


def discover(user="", password="", guest=False, budget_ms=12000, extra_ips=None):
    """扫描局域网里开着 445 的机器，并尽量枚举它们的共享名。

    返回 {ok, hosts:[{host,name,shares:[{name}],error}], prefixes, ms, error}
    """
    t0 = time.time()
    prefixes = local_prefixes(extra_ips)
    if not prefixes:
        return {"ok": False, "hosts": [], "prefixes": prefixes,
                "error": "没有找到可扫描的局域网网段，请确认已连上 WiFi"}

    ips = [f"{p}.{i}" for p in prefixes for i in range(1, 255)]

    # 第一步：并行探 445（连得上就算 SMB 服务器）
    alive = []
    workers = min(128, max(32, len(ips) // 8))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_probe_445, ip) for ip in ips]
            deadline = time.time() + max(3.0, budget_ms / 1000.0)
            for f in as_completed(futs, timeout=max(3.0, budget_ms / 1000.0)):
                if time.time() > deadline:
                    break
                try:
                    r = f.result()
                except Exception:  # noqa: BLE001
                    r = None
                if r:
                    alive.append(r)
    except Exception:  # noqa: BLE001
        pass

    alive.sort(key=lambda x: int(x.rsplit(".", 1)[-1]))

    # 第二步：对前 16 台枚举共享（多了拖时间，意义也不大）
    hosts = []
    cap = min(len(alive), 16)
    if cap > 0:
        def _one(ip):
            nm = ""
            try:
                nm = socket.getfqdn(ip)
                if nm == ip:
                    nm = ""
            except Exception:  # noqa: BLE001
                nm = ""
            sh = shares(ip, user, password, guest)
            return {"host": ip, "name": nm,
                    "shares": sh.get("shares") or [],
                    "error": sh.get("error") or ""}

        try:
            with ThreadPoolExecutor(max_workers=min(16, cap)) as pool:
                futs = [pool.submit(_one, ip) for ip in alive[:cap]]
                for f in as_completed(futs, timeout=max(4.0, budget_ms / 1000.0)):
                    try:
                        hosts.append(f.result())
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            pass

    by_ip = {h["host"]: h for h in hosts}
    out = []
    for ip in alive:
        h = by_ip.get(ip)
        if h:
            out.append(h)
        else:
            # 没赶上枚举的也列出来，让用户至少能点进去看
            out.append({"host": ip, "name": "", "shares": [],
                        "error": "枚举共享超时，可直接点进去浏览"})

    return {"ok": True, "hosts": out, "prefixes": prefixes,
            "ms": int((time.time() - t0) * 1000)}


# ---------------------------------------------------------------- 共享

_SHARE_LINE = re.compile(r"^(Disk|IPC)\|([^|]*)\|?(.*)$")


def shares(host, user="", password="", guest=False, timeout=15):
    """列出某台服务器上的共享名（相当于「网络邻居」里点开一台电脑）"""
    if not host:
        return {"ok": False, "shares": [], "error": "请先填写主机名或 IP"}

    ok, out, err = _run(["-L", f"//{host}", "-g"] + _auth_args(user, password, guest),
                        timeout=timeout)
    if ok:
        found = _parse_shares_g(out)
    else:
        # 没装 smbclient（macOS 常见）时，退回系统自带的 smbutil
        found, err2 = _shares_via_smbutil(host, user, password, guest, timeout)
        if found is None:
            return {"ok": False, "shares": [], "error": err or err2}

    if not found:
        return {"ok": False, "shares": [],
                "error": "服务器不允许列出共享名，请手动填写共享名"}
    return {"ok": True, "shares": found}


def _parse_shares_g(out):
    """解析 `smbclient -L ... -g` 的输出（Disk|name|comment）"""
    found = []
    for line in out.splitlines():
        m = _SHARE_LINE.match(line.strip())
        if not m:
            continue
        kind, raw = m.group(1), (m.group(2) or "").strip()
        if kind.lower() != "disk" or not raw:
            continue
        if raw.lower() in ("ipc$", "print$"):
            continue
        if raw not in [s["name"] for s in found]:
            found.append({"name": raw})
    found.sort(key=lambda s: s["name"].lower())
    return found


def _shares_via_smbutil(host, user, password, guest, timeout):
    """macOS 自带 smbutil 的回退路径。返回 (shares|None, error)"""
    exe = shutil.which("smbutil")
    if not exe:
        return None, "未安装 smbclient（Alpine: apk add samba-client）"
    if guest or not (user or "").strip():
        auth = f"guest@{host}"
    else:
        auth = f"{user}@{host}"
    try:
        p = subprocess.run([exe, "view", f"//{auth}"],
                           capture_output=True, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    out = p.stdout.decode("utf-8", "replace")
    err = _clean_err(p.stderr.decode("utf-8", "replace"))
    if p.returncode != 0 and not out.strip():
        return None, err or f"smbutil 退出码 {p.returncode}"

    found = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, kind = parts[0], parts[1].lower()
        if kind != "disk":
            continue
        if name.lower() in ("ipc$", "print$"):
            continue
        if name not in [s["name"] for s in found]:
            found.append({"name": name})
    found.sort(key=lambda s: s["name"].lower())
    return found, ""


# 行格式：  名称(可能含空格)  属性(D/A/...)  大小  日期时间
_LS_LINE = re.compile(r"^\s*(.+?)\s+([A-Z]{1,6})\s+(\d+)\s+\w{3}\s+\w{3}\s+.*$")


def browse_dir(host, share, subpath="", user="", password="", guest=False,
               timeout=20):
    """浏览共享里的子目录（逐级往下点）。subpath 为空表示共享根。

    返回 {ok, path, parent, dirs:[{name,rel}], audio_files, files}
    """
    if not host:
        return {"ok": False, "error": "请先填写主机名或 IP"}
    if not share:
        return {"ok": False, "error": "请先选择或填写共享名"}

    r = (subpath or "").replace("\\", "/").strip("/")
    r = re.sub(r"/{2,}", "/", r)

    # smbclient 的 -c 不支持 cd 到不存在的目录，先把路径转义好
    ls_cmd = f'ls "{r}"' if r else "ls"
    ok, out, err = _run(
        [f"//{host}/{share}", "-c", ls_cmd] + _auth_args(user, password, guest),
        timeout=timeout)
    if not ok:
        return {"ok": False, "error": err or "目录不存在或没有权限"}

    dirs = []
    audio = 0
    files = 0
    for line in out.splitlines():
        s = line.strip()
        if not s or s.startswith("."):
            continue
        m = _LS_LINE.match(line)
        if not m:
            continue
        name, attrs = m.group(1).strip(), m.group(2).upper()
        if name in (".", "..") or name.startswith("."):
            continue
        child = f"{r}/{name}" if r else name
        # 目录行的属性里含 D；smbclient 目录大小固定为 0
        if "D" in attrs:
            dirs.append({"name": name, "rel": child})
        else:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in AUDIO_EXTS:
                audio += 1
            else:
                files += 1
    dirs.sort(key=lambda d: d["name"].lower())

    parent = ""
    if r:
        parent = r.rsplit("/", 1)[0] if "/" in r else ""

    return {"ok": True, "path": r, "parent": parent,
            "dirs": dirs, "audio_files": audio, "files": files}
