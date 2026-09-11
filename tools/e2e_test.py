#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""端到端测试：选中两台斐讯音响 -> 播放 -> 控制 -> 自动续播"""
import json
import time
import urllib.request
import urllib.error

import os

# 默认测本机，设 API_BASE 可测远程（如 http://192.168.1.10:5000）
API = os.environ.get("API_BASE", "http://127.0.0.1:5000").rstrip("/")
TARGET_IPS = ("192.168.1.154", "192.168.1.196")


def req(path, data=None, method=None, timeout=30):
    url = API + path
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=body, headers=headers,
                               method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw)
            except Exception:
                return raw
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "body": e.read().decode("utf-8", "replace")[:200]}
    except Exception as e:
        return {"_error": repr(e)}


def state():
    return req("/api/state", timeout=20)


def show(tag):
    d = state()
    cur = d.get("player", {}).get("current")
    print(f"\n--- {tag} ---")
    print("  当前曲目:", cur["title"] if cur else "无",
          "| 队列索引:", d.get("player", {}).get("index"))
    for x in d.get("devices", []):
        if x.get("selected"):
            print(f"  [{x['ip']}] {x['name']}: {x.get('state')} | "
                  f"{x.get('position')} / {x.get('duration')} | 音量 {x.get('volume')}")
    return d


print("=" * 62)
print("端到端测试（零依赖版本）")
print("=" * 62)

d = state()
udns = [x["udn"] for x in d.get("devices", []) if x.get("ip") in TARGET_IPS]
print(f"\n发现斐讯音响 {len(udns)} 台: {udns}")

print("\n[1] 选中目标")
print("   ->", req("/api/targets", {"udns": udns}))

print("\n[2] 播放队列: [4秒短音频] -> [我是一只鱼]")
r = req("/api/play", {"tracks": [
    {"url": "http://192.168.1.10:8200/MediaItems/2869.mp3",
     "title": "4秒测试音频", "duration": "0:00:04"},
    {"url": "http://192.168.1.10:8200/MediaItems/35.mp3",
     "title": "我是一只鱼", "duration": "0:03:24", "artist": "侯湘婷"},
], "index": 0})
print("   ->", str(r)[:160])

time.sleep(5)
show("播放 5 秒后")

print("\n[3] 等待自动续播（4 秒短音频结束后应跳到第 2 首）")
time.sleep(18)
d = show("续播检查后")
idx = d.get("player", {}).get("index")
print("  判定:", "✅ 自动续播成功" if idx == 1 else f"❌ 未切换（索引={idx}）")

print("\n[4] 控制测试")
print("  暂停 ->", req("/api/control", {"action": "pause"}))
time.sleep(1.5); show("暂停后")

print("  恢复 ->", req("/api/control", {"action": "play"}))
time.sleep(1.5); show("恢复后")

print("  音量30 ->", req("/api/volume", {"volume": 30}))
time.sleep(1.5); show("调音量后")

print("  跳转到60秒 ->", req("/api/seek", {"position": 60}))
time.sleep(3); show("跳转后")

print("\n[5] 音乐库浏览（专辑容器 1$7）")
lib = req("/api/library?source=dlna&container=1$7&count=5", timeout=25)
if isinstance(lib, dict) and lib.get("ok"):
    print(f"  曲目总数: {lib.get('total')} | 服务器: {lib.get('server')}")
    for it in (lib.get("items") or [])[:5]:
        print(f"    - {it.get('title')}")

print("\n[6] 搜索测试（关键词：周杰伦）")
s = req("/api/search?q=%E5%91%A8%E6%9D%B0%E4%BC%A6&source=dlna", timeout=40)
if isinstance(s, dict) and s.get("ok"):
    print(f"  命中 {s.get('total')} 首（fallback={s.get('fallback', False)}）")
    for it in (s.get("items") or [])[:3]:
        print(f"    - {it.get('title')} | {it.get('artist')}")
else:
    print("  ->", str(s)[:150])

print("\n[7] 停止播放")
print("   ->", req("/api/control", {"action": "stop"}))
time.sleep(1.5); show("停止后")

print("\n" + "=" * 62)
print("测试结束")
