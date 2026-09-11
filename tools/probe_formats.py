#!/usr/bin/env python3
"""Probe DLNA renderers' supported sink protocols (audio codecs) via
ConnectionManager.GetProtocolInfo. Run on a host in the same LAN as the speakers.
"""
import socket
import urllib.request
import xml.etree.ElementTree as ET
import re

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 3\r\n"
    "ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
    "\r\n"
)


def discover():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(4)
    locations = set()
    try:
        sock.sendto(SEARCH.encode(), (SSDP_ADDR, SSDP_PORT))
        while True:
            try:
                data, _ = sock.recvfrom(1024)
            except socket.timeout:
                break
            for line in data.decode(errors="ignore").splitlines():
                if line.lower().startswith("location:"):
                    locations.add(line.split(":", 1)[1].strip())
    finally:
        sock.close()
    return locations


def get_xml(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read().decode(errors="ignore")


def ns(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def find_service(device_xml, service_type_sub):
    root = ET.fromstring(device_xml)
    for svc in root.iter():
        if ns(svc.tag) == "service":
            st = ""
            ctrl = ""
            scpd = ""
            for c in svc:
                if ns(c.tag) == "serviceType":
                    st = c.text or ""
                elif ns(c.tag) == "controlURL":
                    ctrl = c.text or ""
                elif ns(c.tag) == "SCPDURL":
                    scpd = c.text or ""
            if service_type_sub in st:
                return ctrl, scpd
    return None, None


def find_action(scpd_xml, action):
    root = ET.fromstring(scpd_xml)
    for a in root.iter():
        if ns(a.tag) == "action":
            name = ""
            for c in a:
                if ns(c.tag) == "name":
                    name = c.text or ""
            if name == action:
                return True
    return False


def soap_call(base_url, ctrl, action, svc_type):
    body = (
        f'<?xml version="1.0"?>'
        f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{svc_type}"></u:{action}></s:Body>'
        f"</s:Envelope>"
    )
    req = urllib.request.Request(ctrl, data=body.encode(), method="POST")
    req.add_header("Content-Type", 'text/xml; charset="utf-8"')
    req.add_header("SOAPAction", f'"{svc_type}#{action}"')
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode(errors="ignore")


def get_protocol_info(base, ctrl, scpd):
    from urllib.parse import urljoin
    scpd_url = urljoin(base, scpd)
    ctrl_url = urljoin(base, ctrl)
    scpd_xml = get_xml(scpd_url)
    if not find_action(scpd_xml, "GetProtocolInfo"):
        return None
    svc_type = "urn:schemas-upnp-org:service:ConnectionManager:1"
    resp = soap_call(ctrl_url, ctrl_url, "GetProtocolInfo", svc_type)
    m = re.search(r"<Sink>(.*?)</Sink>", resp, re.S)
    return m.group(1) if m else None


def main():
    print("Discovering MediaRenderers...")
    locs = discover()
    if not locs:
        print("  none found")
        return
    for loc in sorted(locs):
        try:
            dev = get_xml(loc)
            # device friendly name
            name = ""
            m = re.search(r"<friendlyName>(.*?)</friendlyName>", dev, re.S)
            if m:
                name = m.group(1)
            ctrl, scpd = find_service(dev, "ConnectionManager")
            if not ctrl:
                print(f"\n{loc} ({name}): no ConnectionManager")
                continue
            sink = get_protocol_info(loc, ctrl, scpd)
            print(f"\n=== {name} ===")
            print(f"  location: {loc}")
            if not sink:
                print("  GetProtocolInfo Sink: (empty / unsupported)")
                continue
            # parse audio formats only
            profiles = [p for p in sink.split(",") if p.strip()]
            print(f"  total protocols: {len(profiles)}")
            audio = []
            for p in profiles:
                parts = p.split(":")
                if len(parts) >= 4 and parts[2]:  # protocolInfo: proto:net: mime : extras
                    mime = parts[2]
                    if mime.startswith("audio/") or mime in ("",) or "audio" in mime:
                        audio.append(p)
            print("  AUDIO sinks:")
            seen = set()
            for p in audio:
                if p in seen:
                    continue
                seen.add(p)
                print("   ", p)
        except Exception as e:
            print(f"\n{loc}: ERROR {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
