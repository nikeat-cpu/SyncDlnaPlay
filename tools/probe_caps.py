#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探测两台斐讯音响的 DLNA/AVTransport 能力（不改任何播放状态）。
- 列出 AVTransport 支持的全部 SOAP 动作（重点看 SetNextAVTransportURI）
- 读取当前传输/进度状态，确认曲长是否准确
"""
import sys, re
sys.path.insert(0, "/tmp")
import upnp

AVT = upnp.AVT

def find_service(xml_text, svc_type):
    """从设备描述 XML 中找出指定 service 的 controlURL 与 SCPDURL"""
    # 用正则粗略定位 <service>...</service> 块
    blocks = re.findall(r"<service>(.*?)</service>", xml_text, re.S)
    for b in blocks:
        if svc_type in b:
            ctrl = re.search(r"<controlURL>(.*?)</controlURL>", b)
            scpd = re.search(r"<SCPDURL>(.*?)</SCPDURL>", b)
            return (ctrl.group(1) if ctrl else None,
                    scpd.group(1) if scpd else None)
    return None, None

def list_actions(scpd_xml):
    names = re.findall(r"<action>\s*<name>(.*?)</name>", scpd_xml, re.S)
    return names

def main():
    print("=" * 70)
    print("发现渲染器 ...")
    rs = upnp.discover_renderers(prefer_net="192.168.1.", timeout=4)
    print(f"发现 {len(rs)} 个音响\n")

    base_re = re.compile(r"(https?://[^/]+)")
    for info in rs:
        ip = info.get("ip", "?")
        name = info.get("friendly_name", ip)
        udn = info.get("udn", "?")
        loc = info.get("location", "")
        print("=" * 70)
        print(f"音响: {name}  IP={ip}  UDN={udn}")
        if not loc:
            print("  [跳过] 无 location"); continue
        try:
            desc = upnp.http_get(loc, timeout=6)
        except Exception as e:
            print(f"  [跳过] 设备描述抓取失败: {e}"); continue

        ctrl, scpd = find_service(desc, "AVTransport:1")
        if not ctrl:
            print("  [跳过] 未找到 AVTransport 控制地址"); continue
        m = base_re.match(loc)
        origin = m.group(1) if m else loc
        if not ctrl.startswith("http"):
            ctrl = origin + ("" if ctrl.startswith("/") else "/") + ctrl
        if scpd and not scpd.startswith("http"):
            scpd = origin + ("" if scpd.startswith("/") else "/") + scpd

        print(f"  AVT 控制地址: {ctrl}")
        print(f"  AVT SCPD 地址: {scpd}")

        # 列出支持的动作
        try:
            scpd_xml = upnp.http_get(scpd, timeout=6)
            actions = list_actions(scpd_xml)
            print(f"  AVTransport 支持的动作 ({len(actions)}):")
            for a in actions:
                print(f"    - {a}")
            cap_next = "SetNextAVTransportURI" in actions
            print(f"  >>> 支持 SetNextAVTransportURI(无缝续播预置): {cap_next}")
        except Exception as e:
            print(f"  [警告] SCPD 抓取失败: {e}")

        # 只读状态查询
        ok, st = upnp.soap_call(ctrl, AVT, "GetTransportInfo", {"InstanceID": 0}, timeout=5)
        print(f"  GetTransportInfo: ok={ok} state={st.get('CurrentTransportState') if ok else st}")
        ok2, pos = upnp.soap_call(ctrl, AVT, "GetPositionInfo", {"InstanceID": 0}, timeout=5)
        if ok2:
            print(f"  GetPositionInfo: dur={pos.get('TrackDuration')} "
                  f"rel={pos.get('RelTime')} uri={pos.get('TrackURI','')[:60]}")
        else:
            print(f"  GetPositionInfo: {pos}")
        print()

if __name__ == "__main__":
    main()
