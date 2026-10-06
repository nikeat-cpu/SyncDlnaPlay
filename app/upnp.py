#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UPnP / DLNA 控制点核心库
=========================
纯标准库实现（只依赖 Python 标准库），无需编译，可直接在任意架构的容器中运行。

职责：
  1. SSDP 设备发现（多网卡并发，自动避开 Tailscale / docker0 等虚拟网卡）
  2. UPnP SOAP 调用封装
  3. MediaRenderer 控制（播放/暂停/停止/音量/进度查询）
  4. MediaServer 内容浏览（MiniDLNA ContentDirectory）
  5. DIDL-Lite 元数据生成（推送 URI 时渲染器需要它才能正确识别音频）
"""

import socket
import struct
import subprocess
import re
import threading
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------- 常量

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900

AVT = "urn:schemas-upnp-org:service:AVTransport:1"
RC = "urn:schemas-upnp-org:service:RenderingControl:1"
CM = "urn:schemas-upnp-org:service:ConnectionManager:1"
CD = "urn:schemas-upnp-org:service:ContentDirectory:1"

DEV_NS = "urn:schemas-upnp-org:device-1-0"
SVC_NS = "urn:schemas-upnp-org:service-1-0"

DIDL_NS = "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
DC_NS = "http://purl.org/dc/elements/1.1/"
UPNP_NS = "urn:schemas-upnp-org:metadata-1-0/upnp/"

DEFAULT_TIMEOUT = 6

# 音频扩展名 -> (mime, DLNA.ORG_PN)
MIME_MAP = {
    "mp3":  ("audio/mpeg",          "MP3"),
    "flac": ("audio/flac",          "FLAC"),
    "wav":  ("audio/wav",           "WAV"),
    "m4a":  ("audio/mp4",           "AAC_ISO_320"),
    "aac":  ("audio/aac",           "AAC_ISO"),
    "ogg":  ("audio/ogg",           "OGG"),
    "oga":  ("audio/ogg",           "OGG"),
    "opus": ("audio/ogg",           "OPUS"),
    "wma":  ("audio/x-ms-wma",      "WMAFULL"),
    "ape":  ("audio/x-ape",         None),
    "aiff": ("audio/aiff",          "AIFF"),
    "aif":  ("audio/aiff",          "AIFF"),
    "mp4":  ("audio/mp4",           "AAC_ISO_320"),
    "m3u8": ("application/x-mpegURL", None),
}


def guess_mime(url: str):
    """根据 URL 扩展名推断 mime 与 DLNA PN"""
    ext = url.split("?")[0].rstrip("/").rsplit(".", 1)[-1].lower() if "." in url else ""
    mime, pn = MIME_MAP.get(ext, ("audio/mpeg", "MP3"))
    return mime, pn


# ---------------------------------------------------------------- 网卡 / IP 工具

def _linux_ips():
    """Linux: 通过 ioctl(SIOCGIFADDR) 枚举网卡 IPv4（不依赖 ip 命令，slim 镜像也能跑）"""
    ips = []
    try:
        import fcntl
        SIOCGIFADDR = 0x8915
        for _idx, name in socket.if_nameindex():
            if name == "lo":
                continue
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                buf = fcntl.ioctl(
                    s.fileno(), SIOCGIFADDR,
                    struct.pack("256s", name[:15].encode("utf-8"))
                )
                ips.append(socket.inet_ntoa(buf[20:24]))
                s.close()
            except Exception:
                try:
                    s.close()
                except Exception:
                    pass
    except Exception:
        pass
    return ips


def _win_ips():
    """Windows: 解析 ipconfig 输出"""
    try:
        out = subprocess.run(
            ["ipconfig"], capture_output=True, text=True,
            encoding="gbk", errors="replace", timeout=10
        ).stdout
        return re.findall(r"IPv4[^:]*:\s*([\d.]+)", out)
    except Exception:
        return []


def _is_cgnat(ip: str) -> bool:
    """Tailscale / CGNAT 段 100.64.0.0/10"""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return a == 100 and 64 <= b <= 127


def local_ips():
    """
    获取所有可用于局域网组播的本机 IPv4。
    排除：回环 127.*、链路本地 169.254.*、Tailscale CGNAT 100.64/10。
    """
    import platform
    ips = _linux_ips() if not platform.system().lower().startswith("win") else _win_ips()
    if not ips:
        ips = _win_ips() + _linux_ips()

    out, seen = [], set()
    for ip in ips:
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        if _is_cgnat(ip):
            continue
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def pick_ips(prefer: str = None):
    """
    选择用于发 SSDP 的网卡 IP 列表。
    prefer: 形如 "192.168.1." 的网段前缀；命中则只用它（更快更准），
            否则返回全部候选。
    """
    ips = local_ips()
    if prefer:
        hit = [ip for ip in ips if ip.startswith(prefer)]
        if hit:
            return hit
    return ips or ["0.0.0.0"]


# ---------------------------------------------------------------- HTTP / XML 工具

def http_get(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "DLNA-Controller/1.0",
        "Connection": "close",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_ns(tag: str) -> str:
    """去掉 XML 命名空间前缀"""
    return tag.split("}")[-1] if "}" in tag else tag


def find_child(parent, name: str):
    """按本地名查找子元素（忽略命名空间）"""
    if parent is None:
        return None
    for ch in parent:
        if strip_ns(ch.tag) == name:
            return ch
    return None


def findall_child(parent, name: str):
    if parent is None:
        return []
    return [ch for ch in parent if strip_ns(ch.tag) == name]


def text_of(parent, name: str, default: str = "") -> str:
    n = find_child(parent, name)
    return n.text.strip() if n is not None and n.text else default


# ---------------------------------------------------------------- SOAP

def soap_call(control_url: str, service_type: str, action: str,
              args: dict = None, timeout: int = DEFAULT_TIMEOUT):
    """
    通用 UPnP SOAP 调用。
    成功返回 (True, {参数名: 值})
    失败返回 (False, 错误字符串)
    """
    args = args or {}
    body = "".join(
        f"<{k}>{v if isinstance(v, str) and v.startswith('<') else xml_escape(str(v))}</{k}>"
        for k, v in args.items()
    )

    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{service_type}">{body}</u:{action}>'
        "</s:Body></s:Envelope>"
    ).encode("utf-8")

    req = urllib.request.Request(
        control_url,
        data=envelope,
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{service_type}#{action}"',
            "User-Agent": "DLNA-Controller/1.0",
            "Connection": "close",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:300]
        except Exception:
            pass
        return False, f"HTTP {e.code}: {detail}"
    except Exception as e:
        return False, repr(e)

    return parse_soap_response(raw, action)


def parse_soap_response(raw: str, action: str):
    """解析 SOAP 响应体（含 UPnP 错误码解析）"""
    try:
        root = ET.fromstring(raw)
    except Exception as e:
        return False, f"XML 解析失败: {e}"

    # UPnP 错误
    body = find_child(root, "Body")
    fault = find_child(body, "Fault") if body is not None else None
    if fault is None:
        fault = find_child(root, "Fault")
    if fault is not None:
        detail = find_child(fault, "detail")
        if detail is None:
            detail = fault
        err = find_child(detail, "UPnPError")
        code = text_of(err, "errorCode", "?")
        desc = text_of(err, "errorDescription", "")
        return False, f"UPnP 错误 {code}: {desc}"

    resp = find_child(body, f"{action}Response")
    if resp is None:
        resp = body if body is not None else root

    out = {}
    if resp is not None:
        for ch in resp:
            out[strip_ns(ch.tag)] = ch.text if ch.text else ""
    return True, out


# ---------------------------------------------------------------- DIDL-Lite

def build_didl(title: str, url: str, duration: str = "",
               artist: str = "", album: str = "",
               mime: str = None, pn: str = None,
               rich: bool = True) -> str:
    """
    构造 SetAVTransportURI 需要的 DIDL-Lite 元数据。
    渲染器靠它识别标题/时长/类型；rich=False 时生成精简版（兼容挑剔的设备）。
    """
    if mime is None:
        mime, pn = guess_mime(url)

    if rich and pn:
        protocol = (
            f"http-get:*:{mime}:"
            f"DLNA.ORG_PN={pn};DLNA.ORG_OP=01;DLNA.ORG_CI=0;"
            f"DLNA.ORG_FLAGS=01700000000000000000000000000000"
        )
    else:
        protocol = f"http-get:*:{mime}:*"

    dur_attr = f' duration="{duration}"' if duration else ""

    parts = [
        f'<DIDL-Lite xmlns="{DIDL_NS}" xmlns:dc="{DC_NS}" '
        f'xmlns:upnp="{UPNP_NS}">',
        '<item id="0" parentID="-1" restricted="1">',
        f'<dc:title>{xml_escape(title)}</dc:title>',
        '<upnp:class>object.item.audioItem.musicTrack</upnp:class>',
    ]
    if artist:
        parts.append(f'<upnp:artist role="Performer">{xml_escape(artist)}</upnp:artist>')
        parts.append(f'<dc:creator>{xml_escape(artist)}</dc:creator>')
    if album:
        parts.append(f'<upnp:album>{xml_escape(album)}</upnp:album>')
    parts.append(
        f'<res protocolInfo="{protocol}"{dur_attr}>{xml_escape(url)}</res>'
    )
    parts.append("</item></DIDL-Lite>")
    return "".join(parts)


def parse_didl(didl_text: str):
    """解析 DIDL-Lite，返回条目列表"""
    items = []
    if not didl_text:
        return items
    text = (didl_text.replace("&lt;", "<").replace("&gt;", ">")
                     .replace("&quot;", '"').replace("&apos;", "'"))
    # &amp; 最后处理，避免二次反转
    text = text.replace("&amp;", "&")

    try:
        root = ET.fromstring(text)
    except Exception:
        return items

    for node in root:
        tag = strip_ns(node.tag)
        if tag not in ("item", "container"):
            continue
        res = find_child(node, "res")
        url = res.text.strip() if res is not None and res.text else ""
        dur = res.get("duration", "") if res is not None else ""
        size = None
        if res is not None and res.get("size"):
            try:
                size = int(res.get("size"))
            except ValueError:
                size = None

        items.append({
            "id": node.get("id", ""),
            "parent_id": node.get("parentID", ""),
            "type": tag,
            "title": text_of(node, "title", ""),
            "artist": text_of(node, "artist", "") or text_of(node, "creator", ""),
            "album": text_of(node, "album", ""),
            "class": text_of(node, "class", ""),
            "url": url,
            "duration": dur,
            "size": size,
            "protocol": res.get("protocolInfo", "") if res is not None else "",
        })
    return items


# ---------------------------------------------------------------- 设备描述解析

def fetch_description(location: str, timeout: int = DEFAULT_TIMEOUT):
    """
    抓取并解析设备描述 XML。
    返回 (info_dict, base_url) 或 (None, None)
    """
    try:
        xml_text = http_get(location, timeout)
    except Exception:
        return None, None

    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return None, None

    base = location
    ub = find_child(root, "URLBase")
    if ub is not None and ub.text and ub.text.strip():
        base = ub.text.strip()

    dev = find_child(root, "device")
    if dev is None:
        return None, None

    info = {
        "location": location,
        "device_type": text_of(dev, "deviceType"),
        "friendly_name": text_of(dev, "friendlyName"),
        "manufacturer": text_of(dev, "manufacturer"),
        "model_name": text_of(dev, "modelName"),
        "model_description": text_of(dev, "modelDescription"),
        "udn": text_of(dev, "UDN"),
        "services": {},
    }

    sl = find_child(dev, "serviceList")
    for svc in findall_child(sl, "service"):
        st = text_of(svc, "serviceType")
        ct = text_of(svc, "controlURL")
        et = text_of(svc, "eventSubURL")
        if not st:
            continue
        if ct and not ct.startswith("http"):
            m = re.match(r"(https?://[^/]+)", base)
            origin = m.group(1) if m else base
            ct = origin + ("" if ct.startswith("/") else "/") + ct
        info["services"][st] = {"control": ct, "event": et}

    return info, base


# ---------------------------------------------------------------- SSDP 发现

def ssdp_search(local_ip: str, st: str, timeout: int = 3, mx: int = 2):
    """从指定网卡 IP 发送一次 M-SEARCH，返回 {ip: location}"""
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {mx}\r\n"
        f"ST: {st}\r\n"
        "\r\n"
    ).encode()

    found = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception:
            pass
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        sock.bind((local_ip, 0))
        sock.sendto(msg, (SSDP_ADDR, SSDP_PORT))
        sock.settimeout(timeout)

        while True:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                break
            except Exception:
                break
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                continue
            m = re.search(r"^LOCATION:\s*(\S+)", text, re.M | re.I)
            if m:
                found[addr[0]] = m.group(1).strip()
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return found


def discover(search_targets=None, prefer_net: str = None,
             timeout: int = 3, workers: int = 8):
    """
    多网卡并发 SSDP 发现，返回去重后的设备列表（已抓取描述）。
    返回: [info_dict, ...]
    """
    if search_targets is None:
        search_targets = ["upnp:rootdevice",
                          "urn:schemas-upnp-org:device:MediaRenderer:1"]

    ips = pick_ips(prefer_net)
    locations = {}
    tasks = [(ip, st) for ip in ips for st in search_targets]

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(tasks)))) as ex:
        futs = {ex.submit(ssdp_search, ip, st, timeout): (ip, st)
                for ip, st in tasks}
        for f in as_completed(futs):
            try:
                for ip, loc in f.result().items():
                    if ip not in locations:
                        locations[ip] = loc
            except Exception:
                pass

    devices = []
    seen_udn = set()
    with ThreadPoolExecutor(max_workers=min(16, max(1, len(locations)))) as ex:
        futs = {ex.submit(fetch_description, loc): ip
                for ip, loc in locations.items()}
        for f in as_completed(futs):
            ip = futs[f]
            try:
                info, _base = f.result()
            except Exception:
                continue
            if not info:
                continue
            info["ip"] = ip
            if info["udn"] in seen_udn:
                continue
            seen_udn.add(info["udn"])
            devices.append(info)

    devices.sort(key=lambda d: d.get("ip", ""))
    return devices


def discover_renderers(prefer_net: str = None, timeout: int = 3):
    """只返回可作为播放目标的 MediaRenderer（含 AVTransport 服务）"""
    out = []
    for d in discover(prefer_net=prefer_net, timeout=timeout):
        if "MediaRenderer" in d["device_type"] and AVT in d["services"]:
            out.append(d)
    return out


# ---------------------------------------------------------------- Renderer（音响）

class Renderer:
    """一个 DLNA 渲染器（音响）的控制封装"""

    def __init__(self, info: dict):
        self.info = info
        self.ip = info.get("ip", "")
        self.name = info.get("friendly_name", self.ip)
        self.udn = info.get("udn", "")
        self.location = info.get("location", "")
        self.manufacturer = info.get("manufacturer", "")
        self.model = info.get("model_name", "")
        self.services = info.get("services", {})
        self._lock = threading.RLock()
        # Amlogic 类渲染器对精简 metadata 兼容性更好，按厂商给默认值
        self.rich_metadata = not (
            "amlogic" in self.manufacturer.lower() or "amlogic" in self.model.lower()
        )

    def __repr__(self):
        return f"<Renderer {self.name}@{self.ip}>"

    # ---- 内部 ----
    def _ctrl(self, svc: str):
        s = self.services.get(svc)
        return s["control"] if s else None

    def _action(self, svc: str, action: str, args: dict = None, timeout: int = DEFAULT_TIMEOUT):
        url = self._ctrl(svc)
        if not url:
            return False, f"设备不支持服务 {svc}"
        return soap_call(url, svc, action, args, timeout)

    # ---- 播放控制 ----
    def set_uri(self, url: str, title: str = "", duration: str = "",
                artist: str = "", album: str = "",
                mime: str = None, pn: str = None, timeout: int = 8):
        """设置播放地址（不自动播放）"""
        meta = build_didl(
            title or url.rsplit("/", 1)[-1], url,
            duration=duration, artist=artist, album=album,
            mime=mime, pn=pn, rich=self.rich_metadata,
        )
        return self._action(AVT, "SetAVTransportURI", {
            "InstanceID": 0,
            "CurrentURI": url,
            "CurrentURIMetaData": meta,
        }, timeout)

    def set_next_uri(self, url: str, title: str = "", duration: str = "",
                     artist: str = "", mime: str = None, pn: str = None):
        """预置下一曲（部分设备支持，用于无缝续播）"""
        meta = build_didl(
            title or url.rsplit("/", 1)[-1], url,
            duration=duration, artist=artist,
            mime=mime, pn=pn, rich=self.rich_metadata,
        )
        return self._action(AVT, "SetNextAVTransportURI", {
            "InstanceID": 0,
            "NextURI": url,
            "NextURIMetaData": meta,
        })

    def play(self, speed: str = "1"):
        return self._action(AVT, "Play", {"InstanceID": 0, "Speed": speed})

    def pause(self):
        return self._action(AVT, "Pause", {"InstanceID": 0})

    def stop(self):
        return self._action(AVT, "Stop", {"InstanceID": 0})

    def next_track(self):
        return self._action(AVT, "Next", {"InstanceID": 0})

    def prev_track(self):
        return self._action(AVT, "Previous", {"InstanceID": 0})

    def seek(self, target: str):
        """target: 形如 '00:01:30' 或 'REL_TIME'"""
        return self._action(AVT, "Seek", {
            "InstanceID": 0, "Unit": "REL_TIME", "Target": target,
        })

    def play_uri(self, url: str, title: str = "", **kw):
        """一步到位：设置 URI 并播放"""
        ok, err = self.set_uri(url, title, **kw)
        if not ok:
            return False, err
        # 部分渲染器 SetURI 后需要极短间隔才接受 Play
        import time
        time.sleep(0.12)
        return self.play()

    # ---- 音量 ----
    def set_volume(self, volume: int):
        volume = max(0, min(100, int(volume)))
        return self._action(RC, "SetVolume", {
            "InstanceID": 0, "Channel": "Master", "DesiredVolume": volume,
        })

    def get_volume(self):
        ok, res = self._action(RC, "GetVolume", {
            "InstanceID": 0, "Channel": "Master",
        })
        if ok and "CurrentVolume" in res:
            try:
                return True, int(res["CurrentVolume"])
            except ValueError:
                pass
        return ok, res

    def set_mute(self, mute: bool):
        return self._action(RC, "SetMute", {
            "InstanceID": 0, "Channel": "Master",
            "DesiredMute": 1 if mute else 0,
        })

    def get_mute(self):
        ok, res = self._action(RC, "GetMute", {
            "InstanceID": 0, "Channel": "Master",
        })
        if ok:
            return True, str(res.get("CurrentMute", "0")) in ("1", "True", "true")
        return ok, res

    # ---- 状态 ----
    def get_transport_info(self):
        """返回 (ok, state) state: PLAYING / PAUSED_PLAYBACK / STOPPED / TRANSITIONING"""
        ok, res = self._action(AVT, "GetTransportInfo", {"InstanceID": 0}, timeout=4)
        if ok:
            return True, res.get("CurrentTransportState", "UNKNOWN")
        return ok, res

    def get_position_info(self):
        """
        返回 (ok, dict) 含 Track / TrackDuration / RelTime / AbsTime / TrackMetaData
        """
        ok, res = self._action(AVT, "GetPositionInfo", {"InstanceID": 0}, timeout=4)
        if not ok:
            return ok, res

        track_meta = res.get("TrackMetaData", "")
        title, artist = "", ""
        if track_meta:
            items = parse_didl(track_meta)
            if items:
                title = items[0].get("title", "")
                artist = items[0].get("artist", "")

        return True, {
            "track": res.get("Track", "0"),
            "duration": res.get("TrackDuration", "00:00:00"),
            "position": res.get("RelTime", "00:00:00"),
            "abs_time": res.get("AbsTime", "00:00:00"),
            "uri": res.get("TrackURI", ""),
            "title": title,
            "artist": artist,
        }

    def get_media_info(self):
        ok, res = self._action(AVT, "GetMediaInfo", {"InstanceID": 0}, timeout=4)
        return ok, res

    def status(self):
        """综合状态快照"""
        out = {
            "ip": self.ip,
            "name": self.name,
            "udn": self.udn,
            "model": self.model,
            "manufacturer": self.manufacturer,
            "online": False,
            "state": "UNKNOWN",
            "volume": None,
            "mute": None,
            "position": None,
            "duration": None,
            "position_sec": 0,
            "duration_sec": 0,
            "title": None,
            "artist": None,
            "uri": None,
        }
        ok, st = self.get_transport_info()
        if not ok:
            return out
        out["online"] = True
        out["state"] = st

        ok_v, vol = self.get_volume()
        if ok_v:
            out["volume"] = vol

        ok_p, pos = self.get_position_info()
        if ok_p:
            out.update({
                "position": pos.get("position"),
                "duration": pos.get("duration"),
                "title": pos.get("title"),
                "artist": pos.get("artist"),
                "uri": pos.get("uri"),
                "position_sec": tsec_to_sec(pos.get("position") or ""),
                "duration_sec": tsec_to_sec(pos.get("duration") or ""),
            })
        return out

    def quick_status(self):
        """轻量状态快照（调度器高频调用用，只取传输状态 + 进度 + 曲长）。
        比 status() 少一次 GetVolume 调用，降低轮询开销。"""
        out = {
            "ip": self.ip,
            "udn": self.udn,
            "online": False,
            "state": "UNKNOWN",
            "position_sec": 0,
            "duration_sec": 0,
            "uri": None,
            "title": None,
        }
        ok, st = self.get_transport_info()
        if not ok:
            return out
        out["online"] = True
        out["state"] = st
        ok2, pos = self.get_position_info()
        if ok2:
            out["position_sec"] = tsec_to_sec(pos.get("position") or "")
            out["duration_sec"] = tsec_to_sec(pos.get("duration") or "")
            out["uri"] = pos.get("uri")
            out["title"] = pos.get("title")
        return out

    def to_dict(self):
        return {
            "ip": self.ip,
            "name": self.name,
            "udn": self.udn,
            "model": self.model,
            "manufacturer": self.manufacturer,
            "location": self.location,
            "has_volume": RC in self.services,
        }


# ---------------------------------------------------------------- MediaServer（音乐库）

class MediaServer:
    """DLNA 媒体服务器（如 MiniDLNA）内容浏览封装"""

    def __init__(self, info: dict):
        self.info = info
        self.ip = info.get("ip", "")
        self.name = info.get("friendly_name", self.ip)
        self.udn = info.get("udn", "")
        self.services = info.get("services", {})
        self._ctrl = self.services.get(CD, {}).get("control")

    def __repr__(self):
        return f"<MediaServer {self.name}@{self.ip}>"

    def browse(self, object_id: str = "0", start: int = 0, count: int = 200,
               sort: str = ""):
        """浏览目录，返回 (ok, items|err, total)"""
        if not self._ctrl:
            return False, "该设备没有 ContentDirectory 服务", 0

        ok, res = soap_call(self._ctrl, CD, "Browse", {
            "ObjectID": object_id,
            "BrowseFlag": "BrowseDirectChildren",
            "Filter": "*",
            "StartingIndex": start,
            "RequestedCount": count,
            "SortCriteria": sort,
        }, timeout=10)

        if not ok:
            return False, res, 0

        items = parse_didl(res.get("Result", ""))
        try:
            total = int(res.get("TotalMatches", len(items)))
        except ValueError:
            total = len(items)
        return True, items, total

    def search(self, keyword: str, container: str = "0", count: int = 100):
        """关键字搜索（MiniDLNA 支持 Search）"""
        if not self._ctrl:
            return False, "无 ContentDirectory 服务", 0
        ok, res = soap_call(self._ctrl, CD, "Search", {
            "ContainerID": container,
            "SearchCriteria": f'(dc:title contains "{keyword}")',
            "Filter": "*",
            "StartingIndex": 0,
            "RequestedCount": count,
            "SortCriteria": "",
        }, timeout=10)
        if not ok:
            return False, res, 0
        items = parse_didl(res.get("Result", ""))
        try:
            total = int(res.get("TotalMatches", len(items)))
        except ValueError:
            total = len(items)
        return True, items, total

    def browse_metadata(self, object_id: str, timeout: int = 10):
        """按 ObjectID 取单个对象的元数据（用于把曲目 id 解析回资源地址）"""
        if not self._ctrl or not object_id:
            return None
        ok, res = soap_call(self._ctrl, CD, "Browse", {
            "ObjectID": object_id,
            "BrowseFlag": "BrowseMetadata",
            "Filter": "*",
            "StartingIndex": 0,
            "RequestedCount": 1,
            "SortCriteria": "",
        }, timeout=timeout)
        if not ok:
            return None
        items = parse_didl(res.get("Result", ""))
        for it in items:
            if it.get("url"):
                return it
        return items[0] if items else None

    def to_dict(self):
        return {
            "ip": self.ip,
            "name": self.name,
            "udn": self.udn,
            "control": self._ctrl,
        }


def discover_servers(prefer_net: str = None, timeout: int = 3):
    """发现局域网内的 MediaServer"""
    out = []
    for d in discover(
        search_targets=["urn:schemas-upnp-org:device:MediaServer:1", "upnp:rootdevice"],
        prefer_net=prefer_net, timeout=timeout,
    ):
        if "MediaServer" in d["device_type"] and CD in d["services"]:
            out.append(MediaServer(d))
    return out


# ---------------------------------------------------------------- 工具

def tsec_to_sec(t: str) -> int:
    """'01:02:03' -> 3723"""
    if not t or t in ("NOT_IMPLEMENTED", "0"):
        return 0
    try:
        parts = [int(x) for x in t.split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 1:
            return parts[0]
    except Exception:
        pass
    return 0


def sec_to_tsec(s: int) -> str:
    """3723 -> '01:02:03'"""
    s = max(0, int(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def norm_duration(d) -> str:
    """
    把各种时长写法规范化成 DLNA 要求的 H:MM:SS。
    MiniDLNA 常返回 '0:03:24.097' -> '0:03:24'
    """
    if not d:
        return ""
    s = str(d).strip()
    if s in ("NOT_IMPLEMENTED", "0", "00:00:00", "-1"):
        return ""
    s = s.split(".")[0]          # 去掉毫秒
    s = s.split(",")[0]
    parts = s.split(":")
    try:
        if len(parts) == 3:
            h, m, sec = (int(x) for x in parts)
            return f"{h}:{m:02d}:{sec:02d}"
        if len(parts) == 2:
            m, sec = (int(x) for x in parts)
            return f"0:{m:02d}:{sec:02d}"
        if len(parts) == 1:
            return f"0:{int(parts[0]) // 60:02d}:{int(parts[0]) % 60:02d}"
    except Exception:
        pass
    return s
