#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心库实机测试：网卡选择 -> 设备发现 -> 状态查询"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import upnp


def main():
    print("=" * 72)
    print("[1] 网卡选择（应避开 Tailscale 100.x）")
    print("=" * 72)
    ips = upnp.local_ips()
    print(f"    候选 IP: {ips}")
    picked = upnp.pick_ips("192.168.1.")
    print(f"    选用(优先 192.168.1.): {picked}")

    print()
    print("=" * 72)
    print("[2] 发现 MediaRenderer")
    print("=" * 72)
    t0 = time.time()
    devs = upnp.discover_renderers(prefer_net="192.168.1.", timeout=3)
    print(f"    耗时 {time.time()-t0:.1f}s，找到 {len(devs)} 个可用播放设备：")
    for d in devs:
        print(f"      - {d['friendly_name']:<22} {d['ip']:<16} "
              f"{d['manufacturer']} / {d['model_name']}")

    if not devs:
        print("    [!] 未发现渲染器，终止")
        return

    print()
    print("=" * 72)
    print("[3] 逐个查询状态（验证 SOAP 控制通路）")
    print("=" * 72)
    for info in devs:
        r = upnp.Renderer(info)
        print(f"\n    >>> {r.name}  [{r.ip}]")
        print(f"        厂商: {r.manufacturer} | 型号: {r.model}")
        print(f"        精简元数据模式: {not r.rich_metadata} "
              f"(Amlogic 类设备建议 True)")

        ok, st = r.get_transport_info()
        print(f"        传输状态: {'✅ ' + st if ok else '❌ ' + str(st)}")

        ok_v, vol = r.get_volume()
        print(f"        当前音量: {'✅ ' + str(vol) if ok_v else '❌ ' + str(vol)}")

        ok_p, pos = r.get_position_info()
        if ok_p:
            print(f"        曲目    : {pos['title'] or '(空)'}")
            print(f"        进度    : {pos['position']} / {pos['duration']}")
            print(f"        URI     : {pos['uri'][:70] if pos['uri'] else '(无)'}")
        else:
            print(f"        进度    : ❌ {pos}")

    print()
    print("=" * 72)
    print("[4] 发现 MediaServer（音乐库）")
    print("=" * 72)
    servers = upnp.discover_servers(prefer_net="192.168.1.", timeout=3)
    for s in servers:
        print(f"    - {s.name:<22} {s.ip}")
        ok, items, total = s.browse("0", count=30)
        if ok:
            print(f"        根目录 {total} 项:")
            for it in items[:8]:
                kind = "📁" if it["type"] == "container" else "🎵"
                print(f"          {kind} [{it['id']}] {it['title']}")
        else:
            print(f"        ❌ 浏览失败: {items}")


if __name__ == "__main__":
    main()
