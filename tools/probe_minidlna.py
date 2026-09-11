#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
探测 iStoreOS 上的 MiniDLNA 媒体服务器：
浏览其内容目录（ContentDirectory），确认能否拿到音乐文件的可播放 URL。
"""
import urllib.request
import urllib.error
import re
import xml.etree.ElementTree as ET

ROOT_DESC = "http://192.168.1.10:8200/rootDesc.xml"

NS = {
    "d": "urn:schemas-upnp-org:device-1-0",
    "s": "urn:schemas-upnp-org:service-1-0",
}
DIDL = "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
DC = "http://purl.org/dc/elements/1.1/"
UPNP = "urn:schemas-upnp-org:metadata-1-0/upnp/"


def http_get(url, timeout=5):
    req = urllib.request.Request(url, headers={"User-Agent": "DLNA-Probe/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def get_service_control(location):
    """解析 rootDesc，返回 {serviceType: (controlURL, baseURL)}"""
    xml_text = http_get(location)
    root = ET.fromstring(xml_text)

    url_base = location
    ub = root.find("d:URLBase", NS)
    if ub is not None and ub.text:
        url_base = ub.text.strip()

    dev = root.find("d:device", NS)
    out = {}
    sl = dev.find("d:serviceList", NS)
    if sl is not None:
        for svc in sl.findall("d:service", NS):
            st = svc.find("d:serviceType", NS)
            ct = svc.find("d:controlURL", NS)
            if st is not None and ct is not None:
                ctrl = ct.text.strip()
                if not ctrl.startswith("http"):
                    # 相对路径 -> 拼到 url_base 的 origin
                    m = re.match(r"(https?://[^/]+)", url_base)
                    origin = m.group(1) if m else url_base
                    ctrl = origin + ("" if ctrl.startswith("/") else "/") + ctrl
                out[st.text.strip()] = ctrl
    return out, url_base


def soap_call(control_url, service_type, action, args, timeout=8):
    """通用 UPnP SOAP 调用"""
    body_args = "".join(f"<{k}>{v}</{k}>" for k, v in args.items())
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{service_type}">'
        f"{body_args}"
        f"</u:{action}></s:Body></s:Envelope>"
    ).encode("utf-8")

    req = urllib.request.Request(
        control_url,
        data=envelope,
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{service_type}#{action}"',
            "User-Agent": "DLNA-Probe/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return f"__HTTPERROR__{e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
    except Exception as e:
        return f"__ERROR__{repr(e)}"


def parse_didl(result_xml):
    """解析 Browse 返回的 DIDL-Lite，返回 [(id, title, class, res_url, meta)]"""
    items = []
    if result_xml.startswith("__"):
        return items, result_xml

    m = re.search(r"<Result>(.*?)</Result>", result_xml, re.S)
    if not m:
        return items, "(无 Result 字段)"

    didl_text = m.group(1).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    try:
        didl = ET.fromstring(didl_text)
    except Exception as e:
        return items, f"(DIDL 解析失败: {e})"

    for node in didl:
        tag = node.tag.split("}")[-1]
        cid = node.get("id", "")
        title = node.findtext(f"{{{DC}}}title", "")
        cls = node.findtext(f"{{{UPNP}}}class", "")
        res = node.find(f"{{{DIDL}}}res")
        url = res.text if res is not None and res.text else ""
        items.append({
            "id": cid, "title": title, "class": cls, "url": url,
            "type": "container" if "container" in cls else "item",
        })
    return items, None


def main():
    print(f"[*] 读取设备描述: {ROOT_DESC}")
    try:
        services, url_base = get_service_control(ROOT_DESC)
    except Exception as e:
        print(f"[!] 失败: {e}")
        return

    print(f"[+] URLBase: {url_base}")
    print("[+] 可用服务:")
    for k, v in services.items():
        print(f"      {k}")
        print(f"         -> {v}")

    cd = None
    for k, v in services.items():
        if "ContentDirectory" in k:
            cd = (k, v)
            break

    if not cd:
        print("\n[!] 没有 ContentDirectory 服务，无法浏览")
        return

    svc_type, ctrl = cd
    print(f"\n[*] 使用 ContentDirectory: {ctrl}")

    # 1. 浏览根
    print("\n" + "=" * 70)
    print("[1] 浏览根目录 (ObjectID=0)")
    r = soap_call(ctrl, svc_type, "Browse", {
        "ObjectID": "0",
        "BrowseFlag": "BrowseDirectChildren",
        "Filter": "*",
        "StartingIndex": "0",
        "RequestedCount": "50",
        "SortCriteria": "",
    })
    items, err = parse_didl(r)
    if err:
        print(f"    错误: {err}")
        if r.startswith("__"):
            print(f"    原始: {r[:500]}")
        return

    for it in items:
        kind = "📁" if it["type"] == "container" else "🎵"
        print(f"    {kind} [{it['id']:>4}] {it['title']:<30} {it['class']}")

    # 2. 深入每个容器找音频
    containers = [it for it in items if it["type"] == "container"]
    found_audio = []

    for c in containers:
        print(f"\n[2] 深入容器 [{c['id']}] {c['title']}")
        r2 = soap_call(ctrl, svc_type, "Browse", {
            "ObjectID": c["id"],
            "BrowseFlag": "BrowseDirectChildren",
            "Filter": "*",
            "StartingIndex": "0",
            "RequestedCount": "100",
            "SortCriteria": "",
        })
        sub, err2 = parse_didl(r2)
        if err2:
            print(f"    错误: {err2}")
            continue

        audios = [s for s in sub if s["type"] == "item" and "audio" in s["class"]]
        subs = [s for s in sub if s["type"] == "container"]

        for s in subs:
            print(f"    📁 [{s['id']:>4}] {s['title']}")
        for a in audios[:5]:
            print(f"    🎵 {a['title']}")
            print(f"        URL: {a['url']}")
        if len(audios) > 5:
            print(f"    ... 共 {len(audios)} 个音频文件")

        found_audio.extend(audios)

        # 再深一层（音乐库常见结构是 音乐/专辑/歌曲）
        for s in subs[:3]:
            r3 = soap_call(ctrl, svc_type, "Browse", {
                "ObjectID": s["id"],
                "BrowseFlag": "BrowseDirectChildren",
                "Filter": "*",
                "StartingIndex": "0",
                "RequestedCount": "30",
                "SortCriteria": "",
            })
            sub3, _ = parse_didl(r3)
            a3 = [x for x in sub3 if x["type"] == "item" and "audio" in x["class"]]
            for a in a3[:3]:
                print(f"        🎵 {a['title']}")
                print(f"            URL: {a['url']}")
            found_audio.extend(a3)

    print("\n" + "=" * 70)
    print(f"[✓] 共发现 {len(found_audio)} 个音频文件")
    if found_audio:
        print("\n[✓] 样例 URL（音响将用这个地址拉取音频）:")
        for a in found_audio[:3]:
            print(f"    {a['title']}")
            print(f"    -> {a['url']}")


if __name__ == "__main__":
    main()
