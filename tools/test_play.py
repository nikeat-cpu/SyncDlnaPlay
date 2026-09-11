#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实机播放测试
从 MiniDLNA 取一首歌 -> 推送到斐讯音响 -> 检查是否真在播 -> 停止
注意：本测试会让音响真实出声数秒。
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import upnp

TARGETS = ["192.168.1.154", "192.168.1.196"]


def pick_a_song(ms, container="1$4", want=1):
    """从 MiniDLNA 取几首歌"""
    ok, items, total = ms.browse(container, count=60)
    if not ok:
        return []
    audios = [i for i in items if i["type"] == "item" and i["url"]]
    return audios[:want], total


def main():
    print("=" * 72)
    print("[1] 连接 MiniDLNA 音乐库")
    print("=" * 72)
    servers = upnp.discover_servers(prefer_net="192.168.1.", timeout=3)
    if not servers:
        print("    [!] 未发现媒体服务器")
        return
    ms = servers[0]
    print(f"    使用: {ms.name} [{ms.ip}]")

    songs, total = pick_a_song(ms, "1$4", want=3)
    if not songs:
        print("    [!] 没取到歌曲")
        return
    print(f"    曲库总数: {total}")
    for s in songs:
        print(f"      🎵 {s['title']}")
        print(f"         时长 {s['duration']}  URL {s['url']}")

    print()
    print("=" * 72)
    print("[2] 发现斐讯音响")
    print("=" * 72)
    devs = upnp.discover_renderers(prefer_net="192.168.1.", timeout=3)
    targets = {d["ip"]: d for d in devs if d["ip"] in TARGETS}
    print(f"    目标音响: {list(targets.keys())}")
    if not targets:
        print("    [!] 未发现目标音响")
        return

    print()
    print("=" * 72)
    print("[3] 推送播放测试（音响将会出声）")
    print("=" * 72)
    song = songs[0]
    print(f"    推送: {song['title']}")
    print(f"          {song['url']}")
    print()

    renderers = {}
    for ip, info in targets.items():
        r = upnp.Renderer(info)
        renderers[ip] = r
        ok, err = r.play_uri(
            song["url"],
            title=song["title"],
            duration=song["duration"],
            artist=song.get("artist", ""),
        )
        print(f"    [{ip}] {r.name}")
        print(f"          推送结果: {'✅ 成功' if ok else '❌ 失败 ' + str(err)}")

    print()
    print("    等待 6 秒后检查播放状态 ...")
    time.sleep(6)

    print()
    print("=" * 72)
    print("[4] 播放状态检查")
    print("=" * 72)
    for ip, r in renderers.items():
        ok, st = r.get_transport_info()
        print(f"\n    [{ip}] {r.name}")
        print(f"          传输状态: {st if ok else '查询失败 ' + str(st)}")
        if ok:
            ok_p, pos = r.get_position_info()
            if ok_p:
                print(f"          正在播放: {pos['title'] or '(无标题)'}")
                print(f"          进度    : {pos['position']} / {pos['duration']}")
                print(f"          当前URI : {pos['uri'][:70]}")
                print(f"          进度秒数: {upnp.tsec_to_sec(pos['position'])}s")

    print()
    print("=" * 72)
    print("[5] 停止播放")
    print("=" * 72)
    for ip, r in renderers.items():
        ok, err = r.stop()
        print(f"    [{ip}] {'✅ 已停止' if ok else '❌ ' + str(err)}")

    print("\n[✓] 播放测试完成")


if __name__ == "__main__":
    main()
