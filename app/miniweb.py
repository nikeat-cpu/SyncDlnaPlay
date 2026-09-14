#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
miniweb —— 零依赖的极简 Web 层
==============================
提供 Flask 兼容的最小 API 子集（route / request / jsonify /
send_from_directory / Response），目的是让容器镜像不依赖任何第三方包。

仅使用标准库，适用于资源受限的设备（路由器 / NAS / ARM 开发板）。

支持的返回类型：
    dict / list              -> JSON, 200
    (dict|list, int)         -> JSON, 指定状态码
    str                      -> text/html, 200
    (str, int)               -> text/html, 指定状态码
    Response                 -> 原样输出
"""
import io
import os
import json
import mimetypes
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

__all__ = ["MiniApp", "Request", "Response", "jsonify", "_Headers",
           "send_from_directory", "request"]

_THREAD_LOCAL = threading.local()

# URL 解码后的非法路径片段（防目录穿越）
_BAD_PARTS = {"..", ""}


# --------------------------------------------------------------- Request

class _Headers(dict):
    """HTTP 头容器：头名不区分大小写（发音响的 Range 请求依赖这一点）"""

    def __init__(self, items=()):
        super().__init__()
        for k, v in (items.items() if hasattr(items, "items") else items):
            dict.__setitem__(self, str(k).lower(), v)

    def get(self, key, default=None):
        return dict.get(self, str(key or "").lower(), default)

    def __contains__(self, key):
        return dict.__contains__(self, str(key or "").lower())

    def __getitem__(self, key):
        return dict.__getitem__(self, str(key or "").lower())


class _Args(dict):
    """查询参数容器，兼容 Flask 的 request.args.get(k, default)"""

    def get(self, key, default=None, type=None):
        v = dict.get(self, key)
        if v is None:
            return default
        if type is not None:
            try:
                return type(v)
            except (TypeError, ValueError):
                return default
        return v

    def getint(self, key, default=0):
        return self.get(key, default, type=int)


class Request:
    """线程绑定的请求对象，兼容 Flask 常用属性"""

    def __init__(self):
        self.method = "GET"
        self.path = "/"
        self.args = _Args()
        self.headers = {}
        self.data = b""
        self.remote_addr = ""

    def get_json(self, force=False, silent=False):
        try:
            raw = self.data.decode("utf-8").strip()
            return json.loads(raw) if raw else None
        except Exception:
            if silent or not force:
                return None
            raise

    @property
    def json(self):
        return self.get_json(force=True, silent=True)


def _current_request() -> Request:
    r = getattr(_THREAD_LOCAL, "request", None)
    if r is None:
        r = Request()
        _THREAD_LOCAL.request = r
    return r


class _RequestProxy:
    """让模块级 `request` 始终指向当前线程的请求"""

    def __getattr__(self, name):
        return getattr(_current_request(), name)

    def __setattr__(self, name, value):
        setattr(_current_request(), name, value)


request = _RequestProxy()


# -------------------------------------------------------------- Response

class Response:
    def __init__(self, body=b"", status=200, mimetype=None, headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.body = body
        self.status = status
        self.mimetype = mimetype or "text/html; charset=utf-8"
        self.headers = headers or {}

    @property
    def content_type(self):
        return self.mimetype

    @content_type.setter
    def content_type(self, v):
        self.mimetype = v


def jsonify(*args, **kwargs):
    """与 Flask 一致的 JSON 响应（ensure_ascii=False 保留中文）"""
    if args and kwargs:
        payload = args[0]
        if isinstance(payload, dict):
            payload = dict(payload)
            payload.update(kwargs)
        else:
            payload = payload
    elif args:
        payload = args[0] if len(args) == 1 else list(args)
    else:
        payload = kwargs
    body = json.dumps(payload, ensure_ascii=False, default=str)
    return Response(body, 200, "application/json; charset=utf-8")


def _safe_join(directory, filename):
    """拼接路径并阻断目录穿越"""
    parts = [p for p in filename.split("/") if p not in _BAD_PARTS]
    target = os.path.abspath(os.path.join(directory, *parts))
    root = os.path.abspath(directory)
    if target != root and not target.startswith(root + os.sep):
        return None
    return target


def send_from_directory(directory, filename, conditional=False, **kwargs):
    """
    发送目录下的文件。conditional=True 时支持 HTTP Range 请求
    （音响拖动进度条会发 Range，必须支持）。
    """
    path = _safe_join(directory, filename)
    if not path or not os.path.isfile(path):
        return Response("Not Found", 404)

    size = os.path.getsize(path)
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"

    rng = request.headers.get("Range") if conditional else None
    start, end, partial = 0, size - 1, False

    if rng and rng.lower().startswith("bytes="):
        spec = rng[6:].split(",")[0].strip()
        if "-" in spec:
            a, _, b = spec.partition("-")
            try:
                if a:
                    start = int(a)
                if b:
                    end = min(int(b), size - 1)
                else:
                    end = size - 1
                if start < 0 or start > end or start >= size:
                    raise ValueError
                partial = True
            except ValueError:
                start, end, partial = 0, size - 1, False

    length = end - start + 1
    with open(path, "rb") as f:
        f.seek(start)
        body = f.read(length)

    headers = {
        "Content-Type": ctype,
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return Response(body, 206, ctype, headers)
    return Response(body, 200, ctype, headers)


# ------------------------------------------------------------ 路由与 App

def _compile(rule):
    """把 '/media/<path:filename>' 编译成 (正则, 参数名列表)"""
    import re
    names = []
    pattern = ""
    i = 0
    while i < len(rule):
        if rule[i] == "<":
            j = rule.index(">", i)
            inner = rule[i + 1:j]
            conv = "string"
            if ":" in inner:
                conv, inner = inner.split(":", 1)
            names.append(inner)
            if conv == "path":
                pattern += "(?P<%s>.+)" % inner
            elif conv == "int":
                pattern += r"(?P<%s>[0-9]+)" % inner
            else:
                pattern += r"(?P<%s>[^/]+)" % inner
            i = j + 1
        else:
            pattern += re.escape(rule[i])
            i += 1
    return re.compile("^" + pattern + "$"), names


class _JsonCfg:
    ensure_ascii = False


class MiniApp:
    def __init__(self, name=None, static_folder=None, static_url_path=""):
        self.name = name
        self.static_folder = static_folder
        self.static_url_path = static_url_path
        self.json = _JsonCfg()
        self.routes = []          # [(regex, names, methods, view)]

    def route(self, rule, methods=None):
        regex, names = _compile(rule)
        methods = [m.upper() for m in (methods or ["GET"])]

        def deco(fn):
            self.routes.append((regex, names, methods, fn))
            return fn

        return deco

    # 兼容 Flask 的 get/post 快捷方式
    def get(self, rule):
        return self.route(rule, ["GET"])

    def post(self, rule):
        return self.route(rule, ["POST"])

    # ---------------------------------------------------------- 调度

    def dispatch(self, path, method, headers, body, remote_addr=""):
        req = _current_request()
        req.method = method
        req.path = path
        req.headers = _Headers(headers)
        req.data = body
        req.remote_addr = remote_addr
        base, _, qs = path.partition("?")
        # 路由路径必须 URL 解码：中文文件名 / 带空格的曲名经 percent-encoding 传输，
        # 不解码会导致 /media/xxx.mp3 匹配不到文件（本地音乐取流 404）。
        base = urllib.parse.unquote(base)
        req.args = _Args()
        for k, v in urllib.parse.parse_qsl(qs, keep_blank_values=True):
            req.args[k] = v

        # 静态文件
        if self.static_folder and self.static_url_path and \
                base.startswith(self.static_url_path.rstrip("/") + "/"):
            rel = base[len(self.static_url_path.rstrip("/")) + 1:]
            return send_from_directory(self.static_folder, rel, conditional=True)

        # HEAD 视为 GET（只回响应头，不回实体），否则健康检查/缓存校验会拿到 405
        eff_method = "GET" if method == "HEAD" else method

        for regex, names, methods, view in self.routes:
            m = regex.match(base)
            if not m:
                continue
            if eff_method not in methods:
                return Response("Method Not Allowed", 405,
                                headers={"Allow": ", ".join(methods)})
            try:
                out = view(**m.groupdict())
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                return jsonify({"ok": False, "msg": f"{type(e).__name__}: {e}"}), 500
            return self._finalize(out)
        return Response("Not Found", 404)

    @staticmethod
    def _finalize(out):
        # 兼容 (body, status) / (body, status, headers) 元组：
        # 注意 status 必须在这里就解出来并一直带下去，早先的实现会在下面
        # 重新赋成 200，导致 `return "xxx", 404` 这类纯文本错误响应状态码丢失。
        status = 200
        if isinstance(out, tuple):
            if len(out) >= 2 and isinstance(out[0], Response):
                if isinstance(out[1], int):
                    out[0].status = out[1]
                return out[0]
            if len(out) == 3:
                out, status = out[0], out[1]
            elif len(out) == 2:
                out, status = out
            else:
                out = out[0]
            if isinstance(out, Response):
                if isinstance(status, int):
                    out.status = status
                return out
        if isinstance(out, Response):
            return out
        if isinstance(out, (dict, list)):
            return Response(json.dumps(out, ensure_ascii=False, default=str),
                            status, "application/json; charset=utf-8")
        if isinstance(out, (str, bytes)):
            return Response(out, status, "text/html; charset=utf-8")
        return Response(str(out), status, "text/plain; charset=utf-8")

    # ---------------------------------------------------------- 运行

    def run(self, host="0.0.0.0", port=5000, threaded=True, debug=False):
        app = self
        srv_cls = ThreadingHTTPServer if threaded else __import__(
            "http.server", fromlist=["HTTPServer"]).HTTPServer

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "miniweb/1.0"

            def _read_body(self):
                n = self.headers.get("Content-Length")
                if not n:
                    return b""
                try:
                    return self.rfile.read(int(n))
                except Exception:
                    return b""

            def _handle(self):
                # 跨域：手机 App / 其它前端可能从别的源调用本服务（file:// 或其它端口）
                if self.command == "OPTIONS":
                    self.send_response(204)
                    self.send_header("Content-Length", "0")
                    self._cors()
                    self.end_headers()
                    return
                body = self._read_body()
                resp = app.dispatch(self.path, self.command,
                                    self.headers, body,
                                    self.client_address[0])
                buf = io.BytesIO()
                buf.write(resp.body if isinstance(resp.body, bytes)
                          else resp.body.encode("utf-8"))
                data = buf.getvalue()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.mimetype)
                self.send_header("Content-Length", str(len(data)))
                self._cors()
                for k, v in (resp.headers or {}).items():
                    # 这三个头上面已统一发送，避免重复
                    if k.lower() not in ("content-length", "connection", "content-type"):
                        self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    try:
                        self.wfile.write(data)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods",
                                 "GET, POST, PUT, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers",
                                 "Content-Type, Range, Authorization")
                self.send_header("Access-Control-Expose-Headers",
                                 "Content-Range, Content-Length, Accept-Ranges")

            do_GET = _handle
            do_POST = _handle
            do_PUT = _handle
            do_DELETE = _handle
            do_PATCH = _handle
            do_HEAD = _handle
            do_OPTIONS = _handle      # 跨域预检（不注册会被 http.server 直接 501）

            def log_message(self, fmt, *args):
                pass  # 静音，避免刷日志

        srv_cls.allow_reuse_address = True
        httpd = srv_cls((host, port), Handler)
        return httpd.serve_forever()
