# -*- coding: utf-8 -*-
"""音乐目录源管理：本地路径 / SMB(CIFS) 网络共享，可动态添加，不再写死。

设计要点
--------
1. 配置持久化到 /data/music_sources.json（容器 /data 已挂到宿主持久化分区）。
2. SMB 挂载：容器没有 CAP_SYS_ADMIN，无法自己 mount，也不该在自己命名空间挂
   （另一个容器看不到）。做法是本服务通过 nsenter 进入 **宿主 PID 1 的挂载命名空间**
   执行 mount.cifs，挂载点因此落在宿主 /mnt/smb/<id> 上。
3. 两个容器都以 rslave 方式绑定宿主 /mnt → /hostmnt，宿主上新增的挂载会立即
   透传进容器，无需重建容器。
4. 路径换算：宿主 /mnt/smb/x  ⇄  容器 /hostmnt/smb/x
"""

import json
import logging
import os
import random
import shlex
import string
import subprocess
import threading
import time

log = logging.getLogger("dlna.sources")

HOST_MNT_ROOT = "/mnt/smb"            # 宿主挂载点根目录
CONTAINER_MNT_ROOT = "/hostmnt/smb"   # 容器内对应目录
DEFAULT_CONF = "/data/music_sources.json"
AUDIO_EXTS = {"mp3", "flac", "wav", "m4a", "aac", "ogg", "ape", "wma"}


def _gen_id(n=6):
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def _sh(script, timeout=45):
    """在宿主挂载命名空间里执行 shell（需要容器 pid:host + SYS_ADMIN）"""
    try:
        p = subprocess.run(
            ["nsenter", "-t", "1", "-m", "--", "sh", "-c", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "容器内没有 nsenter"
    except subprocess.TimeoutExpired:
        return 124, "", "执行超时"
    except Exception as e:  # pragma: no cover
        return 1, "", repr(e)



# 目录浏览器可见的"根"（容器内路径）。
# 只允许在这两处挑目录，避免一路翻到容器自己的 /（那是容器根，不是设备根）而选错。
BROWSER_ROOTS = [
    {"name": "设备存储", "path": "/hostmnt",
     "desc": "iStoreOS 本机磁盘 / U 盘（宿主 /mnt）"},
    {"name": "SMB 挂载点", "path": CONTAINER_MNT_ROOT,
     "desc": "已添加的 SMB 共享挂载目录"},
]


def browse_roots():
    return [dict(r) for r in BROWSER_ROOTS if os.path.isdir(r["path"])]


def clamp_browse_path(path):
    """把浏览路径夹在允许的根范围内，返回 (容器内路径, 根字典)"""
    roots = browse_roots()
    if not roots:
        return "", None
    path = (path or "").strip().rstrip("/")
    for r in roots:
        rp = r["path"].rstrip("/")
        if path == rp or path.startswith(rp + "/"):
            return (path if os.path.isdir(path) else rp), r
    return roots[0]["path"], roots[0]


def in_allowed_root(path):
    """路径是否落在允许的根之内（用于校验手动/接口传入的本地目录）"""
    path = (path or "").strip().rstrip("/")
    for r in BROWSER_ROOTS:
        rp = r["path"].rstrip("/")
        if path == rp or path.startswith(rp + "/"):
            return True
    return False


def nsenter_available():
    rc, _, _ = _sh("true", timeout=8)
    return rc == 0


def host_mounted(host_path):
    rc, _, _ = _sh(f"mountpoint -q {shlex.quote(host_path)} && echo YES", timeout=10)
    return rc == 0


def container_path_of(src):
    """源的容器内可见路径"""
    if src.get("type") == "smb":
        return CONTAINER_MNT_ROOT + "/" + src["id"]
    return (src.get("path") or "").rstrip("/")


def host_path_of(src):
    if src.get("type") == "smb":
        return HOST_MNT_ROOT + "/" + src["id"]
    return (src.get("path") or "").rstrip("/")


def _probe(path, limit=200):
    """轻量探测目录可读性与内容（不递归）"""
    if not path or not os.path.isdir(path):
        return {"readable": False, "files": 0, "dirs": 0}
    files = dirs = 0
    try:
        with os.scandir(path) as it:
            for i, e in enumerate(it):
                if i >= limit:
                    break
                try:
                    if e.is_dir():
                        dirs += 1
                    elif e.name.rsplit(".", 1)[-1].lower() in AUDIO_EXTS:
                        files += 1
                except OSError:
                    pass
    except OSError as e:
        return {"readable": False, "files": 0, "dirs": 0, "error": str(e)}
    return {"readable": True, "files": files, "dirs": dirs}


def _mount_opts(src, vers=None, credfile=None):
    opts = ["iocharset=utf8", "uid=0", "gid=0", "file_mode=0666",
            "dir_mode=0777", "noperm", "noserverino"]
    if src.get("guest"):
        opts.append("guest")
        opts.append("sec=none")
    elif credfile:
        opts.append("credentials=" + credfile)
    if vers:
        opts.append("vers=" + vers)
    return ",".join(opts)


def _build_unc(src):
    host = (src.get("host") or "").strip()
    share = (src.get("share") or "").strip().strip("/")
    unc = f"//{host}/{share}"
    sub = (src.get("subpath") or "").strip().strip("/")
    if sub:
        unc += "/" + sub
    return unc


def mount_smb(src, target=None, timeout=45):
    """挂载 SMB 源。返回 (ok, msg)。target 为宿主路径，默认源的正式挂载点。"""
    target = target or host_path_of(src)
    unc = _build_unc(src)
    if not unc.startswith("//") or unc == "//":
        return False, "缺少主机或共享名"

    credfile = None
    pre = ""
    if not src.get("guest"):
        user = src.get("user") or ""
        pwd = src.get("password") or ""
        credfile = f"/tmp/.smbcred_{src.get('id', 'x')}"
        pre = (f"umask 077; printf '%s\\n' "
               f"{shlex.quote('username=' + user)} "
               f"{shlex.quote('password=' + pwd)} > {shlex.quote(credfile)}; ")

    tq = shlex.quote(target)
    base = (f"mkdir -p {tq} && "
            f"umount {tq} 2>/dev/null; "
            + pre)

    last_err = ""
    for vers in ("3.0", "2.0", "1.0", None):
        opts = _mount_opts(src, vers, credfile)
        script = (base +
                  f"mount -t cifs {shlex.quote(unc)} {tq} -o {shlex.quote(opts)} && "
                  f"mountpoint -q {tq} && echo MOUNT_OK")
        rc, out, err = _sh(script, timeout=timeout)
        if rc == 0 and "MOUNT_OK" in out:
            ver_txt = vers or "默认"
            log.info(f"SMB 已挂载 [{src.get('name')}] {unc} -> {target} (vers={ver_txt})")
            return True, f"挂载成功（vers={ver_txt}）"
        last_err = err or out or "未知错误"
        # 认证类错误无需再试其它协议版本
        low = last_err.lower()
        if "permission" in low or "logon failure" in low or "password" in low:
            break
    log.warning(f"SMB 挂载失败 [{src.get('name')}] {unc}: {last_err}")
    return False, last_err[-300:]


def umount_smb(src):
    target = host_path_of(src)
    tq = shlex.quote(target)
    rc, out, err = _sh(f"umount {tq} 2>/dev/null || umount -l {tq} 2>/dev/null; "
                       f"rmdir {tq} 2>/dev/null; echo DONE", timeout=30)
    return rc == 0, (err or "已卸载")


def test_smb(src, timeout=45):
    """试挂到临时目录，探测内容后卸载"""
    tmp = HOST_MNT_ROOT + "/_test_" + _gen_id(4)
    ok, msg = mount_smb(src, target=tmp, timeout=timeout)
    if not ok:
        _sh(f"rmdir {shlex.quote(tmp)} 2>/dev/null", timeout=10)
        return False, msg, {}
    probe = _probe(CONTAINER_MNT_ROOT + "/" + tmp.rsplit("/", 1)[-1])
    # 临时目录名与正式 id 不同，直接按宿主路径换算探测
    probe = _probe(CONTAINER_MNT_ROOT + "/" + tmp[len(HOST_MNT_ROOT) + 1:])
    _sh(f"umount {shlex.quote(tmp)} 2>/dev/null || umount -l {shlex.quote(tmp)} 2>/dev/null; "
        f"rmdir {shlex.quote(tmp)} 2>/dev/null", timeout=20)
    return True, "连接成功", probe


class MusicSources:
    """音乐目录源注册表"""

    def __init__(self, conf_file=DEFAULT_CONF, fallback_dir=""):
        self.conf_file = conf_file
        self.fallback_dir = fallback_dir
        self.lock = threading.RLock()
        self.sources = []
        self.active = ""
        self.load()
        self.ensure_default()

    # ---- 持久化 ----
    def load(self):
        if not self.conf_file or not os.path.isfile(self.conf_file):
            return
        try:
            with open(self.conf_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.sources = [s for s in (data.get("sources") or []) if isinstance(s, dict)]
            self.active = data.get("active") or ""
            log.info(f"已加载音乐目录源: {len(self.sources)} 个")
        except Exception:
            log.exception("音乐目录源配置读取失败")

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.conf_file), exist_ok=True)
            tmp = self.conf_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"sources": self.sources, "active": self.active},
                          f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.conf_file)
            try:
                os.chmod(self.conf_file, 0o600)
            except OSError:
                pass
        except Exception:
            log.exception("音乐目录源配置保存失败")

    def ensure_default(self):
        """首次运行：把原来的固定目录登记为一个默认源"""
        with self.lock:
            if self.sources:
                if not self.active or not self.get(self.active):
                    self.active = self.sources[0]["id"]
                return
            candidates = [self.fallback_dir, "/hostmnt/mmc1-4/Music", "/music"]
            for c in candidates:
                if c and os.path.isdir(c):
                    src = {"id": _gen_id(), "name": "本地音乐", "type": "path",
                           "path": c.rstrip("/"), "enabled": True, "auto_mount": False}
                    self.sources = [src]
                    self.active = src["id"]
                    self.save()
                    log.info(f"已创建默认音乐目录源: {c}")
                    return
            self.active = ""

    # ---- 查询 ----
    def get(self, sid):
        for s in self.sources:
            if s["id"] == sid:
                return s
        return None

    def active_source(self):
        s = self.get(self.active)
        if s:
            return s
        for s in self.sources:
            if s.get("enabled", True):
                return s
        return None

    def active_dir(self):
        s = self.active_source()
        return container_path_of(s) if s else ""

    def status(self, src):
        path = container_path_of(src)
        mounted = os.path.isdir(path)
        st = _probe(path)
        out = dict(src)
        out.pop("password", None)
        out["has_password"] = bool(src.get("password"))
        out["container_path"] = path
        out["host_path"] = host_path_of(src)
        out["mounted"] = host_mounted(host_path_of(src)) if src.get("type") == "smb" else mounted
        out["readable"] = bool(st.get("readable"))
        out["writable"] = bool(st.get("readable")) and os.access(path, os.W_OK)
        out["audio_files"] = st.get("files", 0)
        out["sub_dirs"] = st.get("dirs", 0)
        out["active"] = (src["id"] == self.active)
        return out

    def public(self):
        with self.lock:
            return [self.status(s) for s in self.sources]

    # ---- 变更 ----
    def add(self, payload):
        name = (payload.get("name") or "").strip()
        stype = (payload.get("type") or "path").strip()
        if stype not in ("path", "smb"):
            return None, "类型只能是 path 或 smb"
        src = {
            "id": _gen_id(),
            "name": name or ("SMB 共享" if stype == "smb" else "本地目录"),
            "type": stype,
            "enabled": True,
            "auto_mount": bool(payload.get("auto_mount", True)),
        }
        if stype == "path":
            p = (payload.get("path") or "").strip().rstrip("/")
            if not p:
                return None, "缺少路径"
            if not os.path.isdir(p):
                return None, f"目录不存在或不可访问：{p}"
            if not in_allowed_root(p):
                return None, ("该路径不在可浏览范围内（只允许设备存储 /hostmnt "
                              "与 SMB 挂载点 /hostnmt/smb 之下）")
            src["path"] = p
        else:
            host = (payload.get("host") or "").strip()
            share = (payload.get("share") or "").strip().strip("/")
            if not host or not share:
                return None, "缺少主机或共享名"
            src.update({
                "host": host, "share": share,
                "subpath": (payload.get("subpath") or "").strip().strip("/"),
                "user": (payload.get("user") or "").strip(),
                "password": payload.get("password") or "",
                "guest": bool(payload.get("guest")),
                "host_mount": HOST_MNT_ROOT + "/" + "PENDING",
            })
            # 先定 id 再算挂载点
            src["host_mount"] = HOST_MNT_ROOT + "/" + src["id"]
        with self.lock:
            self.sources.append(src)
            if not self.active:
                self.active = src["id"]
            self.save()
        return src, ""

    def remove(self, sid):
        with self.lock:
            src = self.get(sid)
            if not src:
                return False, "源不存在"
            if src.get("type") == "smb":
                umount_smb(src)
            self.sources = [s for s in self.sources if s["id"] != sid]
            if self.active == sid:
                self.active = self.sources[0]["id"] if self.sources else ""
            self.save()
        return True, ""

    def set_active(self, sid):
        with self.lock:
            if not self.get(sid):
                return False, "源不存在"
            self.active = sid
            self.save()
        return True, ""

    def automount_all(self):
        """启动时自动挂载标记了 auto_mount 的 SMB 源（后台线程调用）"""
        for s in list(self.sources):
            if s.get("type") == "smb" and s.get("auto_mount", True):
                try:
                    if not host_mounted(host_path_of(s)):
                        mount_smb(s)
                except Exception:
                    log.exception("自动挂载失败")


_singleton = None


def get_sources(fallback_dir=""):
    global _singleton
    if _singleton is None:
        _singleton = MusicSources(os.environ.get("MUSIC_SOURCES_FILE", DEFAULT_CONF),
                                  fallback_dir=fallback_dir)
    return _singleton
