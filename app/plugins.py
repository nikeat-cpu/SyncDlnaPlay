# -*- coding: utf-8 -*-
"""
音源仓库（MusicFree 插件管理）—— Python 版
==========================================
与安卓独立版的 Plugins.java 行为一致，接口契约相同：

  GET  /api/plugins          列出全部音源（内置在前，自建在后）
  GET  /api/plugins/code     取出所有"启用中"的音源源码，交给前端插件运行时
  POST /api/plugins/install  安装（网址 / 插件源码 / 订阅 JSON / 分享码）
  POST /api/plugins/remove   删除
  POST /api/plugins/toggle   启用 / 停用

目录布局：

  <builtin_dir>/*.js             随包内置（只读）
  <plugins_dir>/*.js             用户自建、启用中
  <plugins_dir>-off/*.js         用户自建、已停用
  <plugins_dir>/state.json       {"disabled": ["内置文件名", ...]}  被停用的**内置**音源

「添加音源」要能吃下 MusicFree 生态里常见的几种分发形式：

  1. 单个 .js 插件源码                      → 直接存
  2. 订阅文件（JSON，可能被 base64 包裹）    → 拆出 url 再逐个下载
  3. 分享码（base64(JSON)，srcUrl 里塞源码） → 解出源码直接存
  4. 一个 http(s) 网址                      → 下载下来按上面三种猜

识别顺序：先看是不是源码 → 再看是不是 base64 → 最后当 JSON 拆。
任何一步失败都只记一条可读的错误，不抛异常（与 Java 版保持一致的稳定性底线）。
"""

import base64
import binascii
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request

log = logging.getLogger("dlna.plugins")

MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_PER_INSTALL = 8

# platform 字段（顺便当文件名）
_P_PLATFORM = re.compile(r"""platform\s*[:=]\s*["']([^"']{1,50})["']""")

_BAD_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _sanitize_name(name, fallback="plugin"):
    """把任意字符串变成安全的文件名主体（对应 Java 的 Util.sanitizeName）"""
    s = (name or "").strip()
    s = _BAD_FILENAME.sub("_", s)
    s = s.strip(". ")
    if not s:
        s = fallback
    return s[:80]


def _http_get(url, timeout=20, max_bytes=MAX_SOURCE_BYTES):
    """下载（跟随重定向），返回 (ok, body_bytes|error_str, status)"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; dlna-speaker/2.21)",
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = getattr(r, "status", 200) or 200
            data = r.read(max_bytes + 1)
            if len(data) > max_bytes:
                return False, "内容太大（超过 4MB）", status
            return True, data, status
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}", e.code
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}", 0


class PluginStore:
    """音源仓库"""

    def __init__(self, builtin_dir="", plugins_dir=""):
        self.builtin_dir = builtin_dir or ""
        self.plugins_dir = plugins_dir or ""

    # ------------------------------------------------------------ 路径
    def on_dir(self):
        return self.plugins_dir

    def off_dir(self):
        return self.plugins_dir + "-off" if self.plugins_dir else ""

    def state_file(self):
        return os.path.join(self.on_dir(), "state.json") if self.on_dir() else ""

    def dir_path(self):
        return os.path.abspath(self.on_dir()) if self.on_dir() else ""

    # ------------------------------------------------------------ 查询
    def builtin_names(self):
        d = self.builtin_dir
        if not d or not os.path.isdir(d):
            return []
        return sorted(n for n in os.listdir(d)
                      if n.endswith(".js") and os.path.isfile(os.path.join(d, n)))

    def is_builtin(self, name):
        return name in self.builtin_names()

    def _list_js(self, d):
        if not d or not os.path.isdir(d):
            return []
        out = [f for f in os.listdir(d)
               if f.endswith(".js") and os.path.isfile(os.path.join(d, f))]
        return sorted(out, key=lambda s: s.lower())

    def disabled_builtin(self):
        out = set()
        try:
            p = self.state_file()
            if not p or not os.path.isfile(p):
                return out
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            for x in (data.get("disabled") or []):
                out.add(str(x))
        except Exception:  # noqa: BLE001
            pass
        return out

    def _save_state(self, off):
        try:
            if not self.plugins_dir:
                return
            d = self.on_dir()
            os.makedirs(d, exist_ok=True)
            with open(self.state_file(), "w", encoding="utf-8") as f:
                json.dump({"disabled": sorted(off)}, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            log.warning(f"音源状态保存失败: {e}")

    def list(self):
        """列出全部音源：内置的在前，自建的在后"""
        out = []
        off = self.disabled_builtin()
        for n in self.builtin_names():
            size = 0
            try:
                size = os.path.getsize(os.path.join(self.builtin_dir, n))
            except OSError:
                pass
            out.append({"name": n, "builtin": True, "enabled": n not in off,
                        "size": size, "platform": _extract_platform(
                            _read_text(os.path.join(self.builtin_dir, n)) or "")})
        for n in self._list_js(self.on_dir()):
            p = os.path.join(self.on_dir(), n)
            out.append({"name": n, "builtin": False, "enabled": True,
                        "size": _size(p),
                        "platform": _extract_platform(_read_text(p) or "")})
        for n in self._list_js(self.off_dir()):
            p = os.path.join(self.off_dir(), n)
            out.append({"name": n, "builtin": False, "enabled": False,
                        "size": _size(p),
                        "platform": _extract_platform(_read_text(p) or "")})
        return out

    def load_enabled(self):
        """取出所有启用中的音源源码，交给前端插件运行时加载"""
        out = []
        off = self.disabled_builtin()
        for n in self.builtin_names():
            if n in off:
                continue
            code = _read_text(os.path.join(self.builtin_dir, n))
            if code is None:
                continue
            out.append({"name": n, "code": code, "builtin": True})
        for n in self._list_js(self.on_dir()):
            code = _read_text(os.path.join(self.on_dir(), n))
            if code is None:
                continue
            out.append({"name": n, "code": code, "builtin": False})
        return out

    # ------------------------------------------------------------ 安装
    def install(self, url="", code="", name_hint="", depth=0):
        if not self.plugins_dir:
            return _err("当前运行环境不支持安装音源")
        if depth > 3:
            return _err("订阅层级太深，已停止解析")
        added, errors = [], []

        if (url or "").strip():
            u = url.strip()
            if not u.startswith(("http://", "https://")):
                u = "https://" + u
            ok, body, status = _http_get(u)
            if not ok:
                return _err(f"下载失败：{body}")
            self._handle(body, name_hint, depth, added, errors)
        elif (code or "").strip():
            self._handle(code.encode("utf-8"), name_hint, depth, added, errors)
        else:
            return _err("请填写音源网址，或粘贴音源内容")

        return {"ok": bool(added), "added": added, "errors": errors,
                "msg": _summary(added, errors)}

    def _handle(self, data, hint, depth, added, errors):
        if not data:
            errors.append("内容为空")
            return
        if len(data) > MAX_SOURCE_BYTES:
            errors.append("内容太大（超过 4MB）")
            return
        text = data.decode("utf-8", "replace")
        t = text.strip()
        if not t:
            errors.append("内容为空")
            return

        # 1) 看着就是插件源码
        if _looks_like_js(t):
            self._save(t, hint, added, errors)
            return

        # 2) 可能是 base64（分享码 = base64 包了一层 JSON）
        b64 = _maybe_base64(t)
        if b64:
            try:
                dec = base64.b64decode(b64, validate=False)
                dt = dec.decode("utf-8", "replace").strip()
                if _looks_like_js(dt):
                    self._save(dt, hint, added, errors)
                    return
                if dt.startswith(("{", "[")):
                    self._unpack_json(dt, hint, depth, added, errors)
                    return
            except (binascii.Error, ValueError):
                pass

        # 3) JSON：订阅文件 / 分享对象
        if t.startswith(("{", "[")):
            self._unpack_json(t, hint, depth, added, errors)
            return

        errors.append("没认出这个格式（既不是插件源码，也不是订阅或分享码）")

    def _unpack_json(self, text, hint, depth, added, errors):
        try:
            o = json.loads(text)
        except Exception:  # noqa: BLE001
            errors.append("不是合法的 JSON")
            return
        urls, inline = [], []
        _collect(o, urls, inline, "", 0)

        n = 0
        for src in inline:
            if n >= MAX_PER_INSTALL:
                break
            n += 1
            self._save(src, hint, added, errors)
        for u in urls:
            if n >= MAX_PER_INSTALL:
                break
            n += 1
            ok, body, _ = _http_get(u)
            if not ok:
                errors.append(f"下载失败：{u}")
                continue
            self._handle(body, hint, depth + 1, added, errors)
        if not urls and not inline:
            errors.append("订阅里没找到可用的插件")

    def _save(self, code, hint, added, errors):
        try:
            platform = _extract_platform(code)
            base = (hint or "").strip() or platform
            if not base:
                base = "plugin-" + _b36(int(time.time() * 1000))
            base = re.sub(r"(?i)\.js$", "", base)
            fname = _sanitize_name(base, "plugin") + ".js"
            d = self.on_dir()
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            # 同名的话从「停用」里捞回来，重新安装即视为启用
            offp = os.path.join(self.off_dir(), fname)
            if os.path.isfile(offp):
                try:
                    os.remove(offp)
                except OSError:
                    pass
            added.append({"name": fname, "platform": platform,
                          "size": _size(path)})
        except Exception as e:  # noqa: BLE001
            errors.append(f"保存失败：{e}")

    # ------------------------------------------------------ 停用 / 删除
    def remove(self, name):
        if not (name or "").strip():
            return _err("没指定要删的音源")
        n = name.strip()
        if not n.endswith(".js"):
            n += ".js"
        if self.is_builtin(n):
            # 内置的删不掉（随包发布），改成停用
            return self.toggle(n, False)
        ok = False
        for d in (self.on_dir(), self.off_dir()):
            p = os.path.join(d, n) if d else ""
            if p and os.path.isfile(p):
                try:
                    os.remove(p)
                    ok = True
                except OSError:
                    pass
        return {"ok": ok, "msg": "已删除" if ok else "没找到这个音源"}

    def toggle(self, name, enabled=True):
        if not (name or "").strip():
            return _err("没指定音源")
        n = name.strip()
        if not n.endswith(".js"):
            n += ".js"
        try:
            if self.is_builtin(n):
                off = set(self.disabled_builtin())
                if enabled:
                    off.discard(n)
                else:
                    off.add(n)
                self._save_state(off)
                return {"ok": True, "enabled": enabled,
                        "msg": "已启用" if enabled else "已停用"}
            onp = os.path.join(self.on_dir(), n)
            offp = os.path.join(self.off_dir(), n)
            if enabled:
                if not os.path.isfile(offp):
                    return _err("没找到这个音源")
                os.makedirs(self.on_dir(), exist_ok=True)
                os.replace(offp, onp)
            else:
                if not os.path.isfile(onp):
                    return _err("没找到这个音源")
                os.makedirs(self.off_dir(), exist_ok=True)
                os.replace(onp, offp)
            return {"ok": True, "enabled": enabled,
                    "msg": "已启用" if enabled else "已停用"}
        except Exception as e:  # noqa: BLE001
            return _err(f"操作失败：{e}")


# ---------------------------------------------------------------- 工具

def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def _read_text(p):
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _b36(n):
    """十进制 → 36 进制（对应 Java 的 Long.toString(n, 36)）"""
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n <= 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out


def _summary(added, errors):
    parts = []
    if added:
        parts.append("已添加 %d 个音源：%s" % (
            len(added), "、".join(a.get("name", "") for a in added)))
    if errors:
        parts.append("部分失败：" + errors[0])
    return "；".join(parts) if parts else "没有任何变化"


def _err(msg):
    return {"ok": False, "msg": msg, "added": [], "errors": []}


def _looks_like_js(t):
    """判断一段文本是不是插件源码"""
    if not t or len(t) < 40:
        return False
    head = t[:6000]
    if "module.exports" in head:
        return True
    if "exports.platform" in head or "exports.default" in head:
        return True
    if _P_PLATFORM.search(head) and ("function" in head or "=>" in head):
        return True
    return False


def _maybe_base64(t):
    """base64 猜测：只由 base64 字符组成、长度够、且 padding 合理"""
    s = re.sub(r"\s+", "", t)
    if len(s) < 80 or len(s) > 1024 * 1024:
        return None
    if not re.fullmatch(r"[A-Za-z0-9+/=_-]+", s):
        return None
    s = s.replace("-", "+").replace("_", "/")
    if s.count("=") > 2:
        return None
    while len(s) % 4 != 0:
        s += "="
    return s


def _extract_platform(code):
    try:
        for m in _P_PLATFORM.finditer(code or ""):
            p = m.group(1)
            if p and not p.startswith("http"):
                return p
    except Exception:  # noqa: BLE001
        pass
    return ""


def _collect(o, urls, inline, key, depth):
    """从订阅 JSON / 分享对象里把插件挖出来"""
    if o is None or depth > 6:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            _collect(v, urls, inline, str(k), depth + 1)
    elif isinstance(o, list):
        for x in o:
            _collect(x, urls, inline, key, depth + 1)
    elif isinstance(o, str):
        v = o.strip()
        if not v:
            return
        if v.startswith(("http://", "https://")):
            urls.append(v)
            return
        if len(v) > 200 and _looks_like_js(v):
            inline.append(v)
            return
        keyish = key.lower() in ("srcurl", "source", "url", "script", "code")
        if keyish and len(v) > 80:
            b = _maybe_base64(v)
            if b:
                try:
                    d = base64.b64decode(b, validate=False).decode("utf-8", "replace").strip()
                    if _looks_like_js(d):
                        inline.append(d)
                except (binascii.Error, ValueError):
                    pass
