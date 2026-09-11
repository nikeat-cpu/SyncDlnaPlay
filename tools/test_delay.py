#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 per-device delay_ms 是否生效"""
import json
import time
import urllib.request

API = "http://127.0.0.1:5011"


def api(path, data=None, method="GET"):
    url = API + path
    if data is not None:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=method)
    else:
        req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def main():
    state = api("/api/state")
    devices = [d for d in state["devices"] if d["ip"] in ("192.168.1.154", "192.168.1.196")]
    if len(devices) < 2:
        print("未找到两台斐讯音响")
        return
    u154 = [d for d in devices if d["ip"] == "192.168.1.154"][0]["udn"]
    u196 = [d for d in devices if d["ip"] == "192.168.1.196"][0]["udn"]
    print(f"154: {u154[:40]}...")
    print(f"196: {u196[:40]}...")

    # 选中双音响
    api("/api/targets", {"udns": [u154, u196]}, "POST")

    # 给 196 加 600ms 延时
    api("/api/delay", {"udn": u196, "delay_ms": 600}, "POST")
    print("已给 196 设置 600ms delay")

    # 播放 4 秒短音频
    api("/api/play", {
        "tracks": [{
            "url": "http://192.168.1.10:8200/MediaItems/2869.mp3",
            "title": "4秒测试音频",
            "duration": "0:00:04"
        }]
    }, "POST")
    print("已播放，等待 2 秒后读取进度...")
    time.sleep(2.0)

    state = api("/api/state")
    for x in state["devices"]:
        if x["ip"] in ("192.168.1.154", "192.168.1.196"):
            print(f"  [{x['ip']}] {x['name']}: state={x['state']} pos={x.get('position_sec')}s delay={x.get('delay_ms')}ms")

    # 停止并复位
    api("/api/control", {"action": "stop"}, "POST")
    api("/api/delay", {"udn": u196, "delay_ms": 0}, "POST")
    print("已停止并复位 196 延时")


if __name__ == "__main__":
    main()
