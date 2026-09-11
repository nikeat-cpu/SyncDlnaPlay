#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSDP / UPnP 设备发现工具
扫描局域网内的 UPnP 设备，识别哪些是 DLNA MediaRenderer（可推送播放的音响/播放器）
"""
import socket
import sys
import re
import urllib.request
import xml.etree.ElementTree as ET

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900

SEARCH_TARGETS = [
    "upnp:rootdevice",
    "urn:schemas-upnp-org:device:MediaRenderer:1",
    "urn:schemas-upnp-org:device:MediaServer:1",
    "ssdp:all",
]

NS = {
    "d": "urn:schemas-upnp-org:device-1-0",
    "s": "urn:schemas-upnp-org:service-1-0",
}


def list_local_ips():
    """列出本机所有 IPv4 地址（Windows 用 ipconfig，Linux 用 ip addr）"""
    ips = []
    try:
        if sys.platform.startswith("win"):
            import subprocess
            out = subprocess.run(
                ["ipconfig"], capture_output=True, text=True,
                encoding="gbk", errors="replace"
            ).stdout
            ips = re.findall(r"IPv4[^:]*:\s*([\d.]+)", out)
        else:
            import subprocess
            out = subprocess.run(
                ["ip", "-4", "addr", "show"], capture_output=True, text=True
            ).stdout
            ips = re.findall(r"inet\s+([\d.]+)/", out)
    except Exception:
        pass
    # 过滤掉回环 / Tailscale CGNAT 段(100.64.0.0/10)
    return [ip for ip in ips if not ip.startswith("127.") and not ip.startswith("100.")]


def get_local_ip(target_prefixes=("192.168.", "10.", "172.16.")):
    """
    找出能用于局域网组播的本机 IP。
    注意：UDP connect 探测会按系统路由表走，可能选中 Tailscale 等虚拟网卡，
    因此这里优先挑选与目标同网段（私有网段）的物理网卡 IP。
    """
    candidates = list_local_ips()
    for prefix in target_prefixes:
        for ip in candidates:
            if ip.startswith(prefix):
                return ip
    # 兜底：路由表探测
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "0.0.0.0"


def ssdp_discover(local_ip, st, timeout=4):
    """发送 M-SEARCH 并收集响应"""
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {timeout}\r\n"
        f"ST: {st}\r\n"
        "\r\n"
    ).encode()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
    try:
        sock.bind((local_ip, 0))
    except Exception:
        pass
    sock.sendto(msg, (SSDP_ADDR, SSDP_PORT))
    sock.settimeout(timeout + 2)

    responses = {}
    while True:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            break
        except Exception:
            break
        responses[addr[0]] = data.decode("utf-8", errors="replace")
    sock.close()
    return responses


def fetch_description(url, timeout=5):
    """抓取设备描述 XML"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DLNA-Probe/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None


def parse_device(xml_text, source_ip):
    """解析设备描述，提取关键信息"""
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return None

    device = root.find("d:device", NS)
    if device is None:
        return None

    def txt(el, path):
        n = device.find(path, NS)
        return n.text.strip() if n is not None and n.text else ""

    info = {
        "ip": source_ip,
        "device_type": txt(device, "d:deviceType"),
        "friendly_name": txt(device, "d:friendlyName"),
        "manufacturer": txt(device, "d:manufacturer"),
        "model_name": txt(device, "d:modelName"),
        "udn": txt(device, "d:UDN"),
        "services": [],
    }

    svc_list = device.find("d:serviceList", NS)
    if svc_list is not None:
        for svc in svc_list.findall("d:service", NS):
            st = svc.find("d:serviceType", NS)
            cid = svc.find("d:controlURL", NS)
            eid = svc.find("d:eventSubURL", NS)
            if st is not None:
                info["services"].append({
                    "type": st.text.strip(),
                    "control": cid.text.strip() if cid is not None and cid.text else "",
                    "event": eid.text.strip() if eid is not None and eid.text else "",
                })
    return info


def main():
    local_ip = get_local_ip()
    print(f"[*] 本机 IP: {local_ip}")
    print(f"[*] 正在发送 SSDP M-SEARCH 到 {SSDP_ADDR}:{SSDP_PORT} ...\n")

    locations = {}
    for st in SEARCH_TARGETS:
        resp = ssdp_discover(local_ip, st, timeout=3)
        for ip, raw in resp.items():
            m = re.search(r"^LOCATION:\s*(.+)$", raw, re.M | re.I)
            if m and ip not in locations:
                locations[ip] = m.group(1).strip()
        # ssdp:all 已经覆盖，但保险起见都发一遍

    print(f"[+] 发现 {len(locations)} 个 UPnP 设备\n")
    print("=" * 70)

    renderers = []
    for ip, loc in sorted(locations.items()):
        xml_text = fetch_description(loc)
        if not xml_text:
            print(f"\n[{ip}] 无法抓取描述: {loc}")
            continue
        info = parse_device(xml_text, ip)
        if not info:
            print(f"\n[{ip}] 解析失败: {loc}")
            continue

        is_renderer = "MediaRenderer" in info["device_type"]
        tag = "★ MediaRenderer (可推送播放)" if is_renderer else "  MediaServer/其他"
        print(f"\n[{ip}] {tag}")
        print(f"    名称     : {info['friendly_name']}")
        print(f"    厂商     : {info['manufacturer']}")
        print(f"    型号     : {info['model_name']}")
        print(f"    类型     : {info['device_type']}")
        print(f"    描述URL  : {loc}")
        print(f"    UDN      : {info['udn']}")

        svc_types = [s["type"] for s in info["services"]]
        has_avt = any("AVTransport" in t for t in svc_types)
        has_rc = any("RenderingControl" in t for t in svc_types)
        print(f"    AVTransport服务 : {'✅ 有' if has_avt else '❌ 无'}")
        print(f"    RenderingControl: {'✅ 有' if has_rc else '❌ 无'}")

        if has_avt:
            for s in info["services"]:
                if "AVTransport" in s["type"]:
                    base = loc.rsplit("/", 1)[0] if "/" in loc.split("://", 1)[-1] else loc
                    print(f"      控制端点: {s['control']}")
        if is_renderer and has_avt:
            info["location"] = loc
            renderers.append(info)

    print("\n" + "=" * 70)
    print(f"[✓] 可用作播放目标（DLNA MediaRenderer）: {len(renderers)} 个")
    for r in renderers:
        print(f"    - {r['friendly_name']}  [{r['ip']}]")

    return renderers


if __name__ == "__main__":
    main()
