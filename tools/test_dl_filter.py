# -*- coding: utf-8 -*-
"""测试下载过滤：duration_sec < 60 的曲目应被 bridge 跳过（exists++）。"""
import json, urllib.request, urllib.parse

BASE = "http://192.168.1.10:5000"


def api(path, data=None):
    req = urllib.request.Request(BASE + path, method="POST")
    req.add_header("Content-Type", "application/json")
    body = json.dumps(data).encode()
    with urllib.request.urlopen(req, body, timeout=30) as r:
        return json.loads(r.read().decode())


# 构造一条 duration_sec=0（试听片段）+ 一条 duration_sec=240（正常歌曲）
items = [
    {"provider": "元力WY", "id": "test_short", "title": "测试短曲", "artist": "测试歌手", "duration_sec": 0},
    {"provider": "元力WY", "id": "test_long", "title": "测试长曲", "artist": "测试歌手", "duration_sec": 240},
]
r = api("/api/online/download", {"items": items})
print("下载请求结果:", r)
# duration_sec=0 → 被跳过（exists++），duration_sec=240 → 入队（queued=1）
assert r.get("queued") == 1, f"期望 queued=1，实际 {r}"
assert r.get("exists") == 1, f"期望 exists=1，实际 {r}"
print("✅ duration_sec < 60 的曲目被正确跳过")
