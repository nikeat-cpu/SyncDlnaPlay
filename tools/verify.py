#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 dlna-speaker 容器内运行：端到端验证在线音源链路。"""
import urllib.request, json, time

BASE = "http://127.0.0.1:5000"
BRIDGE = "http://127.0.0.1:5001"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode())


def post(path, data):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode(),
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


print("== 1) bridge /stream 直连（带 Range） ==")
try:
    req = urllib.request.Request(BRIDGE + "/stream?provider=Demo&id=Demo::s1",
                                  headers={"Range": "bytes=0-1023"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
        print("  stream status:", r.status, "bytes:", len(data),
              "ct:", r.headers.get("Content-Type"),
              "accept-ranges:", r.headers.get("Accept-Ranges"))
except Exception as e:
    print("  stream err:", repr(e))

print("== 2) dlna 代理搜索 ==")
sr = get("/api/online/search?q=Demo")
items = sr.get("items", [])
print("  items:", len(items))
if not items:
    print("  NO ITEMS -> abort")
    raise SystemExit(1)
it = items[0]
print("  first:", it["id"], it["title"], "provider=", it["provider"])

print("== 3) 加入在线曲目到队列 ==")
ad = post("/api/online/add", {"items": [{
    "provider": it["provider"], "id": it["id"],
    "title": it["title"], "artist": it.get("artist", ""),
    "album": it.get("album", ""), "duration_sec": it.get("duration", 0)}]})
print("  add total:", ad.get("total"))

print("== 4) 选定斐讯音响 192.168.1.154 并跳转播放 ==")
st = get("/api/state")
target_udn = None
for d in st.get("devices", []):
    if d.get("ip") == "192.168.1.154":
        target_udn = d["udn"]
print("  target udn:", target_udn)
if not target_udn:
    print("  speaker not found -> abort")
    raise SystemExit(1)
post("/api/targets", {"udns": [target_udn]})
idx = (ad.get("total") or 1) - 1
post("/api/jump", {"index": idx})
time.sleep(3)

print("== 5) 检查音响当前 URI / 状态 ==")
st2 = get("/api/state")
for d in st2.get("devices", []):
    if d.get("ip") == "192.168.1.154":
        print("  device keys:", sorted(d.keys()))
        print("  uri:", d.get("uri"))
        print("  state:", d.get("state"), "title:", d.get("title"))

print("== 6) 立即停止 ==")
post("/api/control", {"action": "stop"})
time.sleep(1)
st3 = get("/api/state")
for d in st3.get("devices", []):
    if d.get("ip") == "192.168.1.154":
        print("  after-stop state:", d.get("state"))
print("VERIFY_DONE")
