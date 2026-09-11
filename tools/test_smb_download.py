# -*- coding: utf-8 -*-
"""最终验证：下载到 SMB 源 -> 文件落地 -> 清理测试源"""
import json
import time
import urllib.parse
import urllib.request

BASE = "http://192.168.1.10:5000"


def api(path, data=None):
    req = urllib.request.Request(BASE + path, method="POST" if data is not None else "GET")
    body = None
    if data is not None:
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data).encode()
    with urllib.request.urlopen(req, body, timeout=90) as r:
        return json.loads(r.read().decode())


time.sleep(4)
d = api("/api/music/sources")
srcs = d["sources"]
print("源列表:")
for s in srcs:
    print(f"  [{s['type']}] {s['name']} mounted={s['mounted']} rw={s['writable']} active={s['active']}")

smb = [s for s in srcs if s["type"] == "smb" and s["share"] == "new"]
local = [s for s in srcs if s["type"] == "path"][0]
if not smb:
    print("找不到写入测试源；先手动添加")
    raise SystemExit(1)
smb = smb[0]

print(f"\n=== A. 设 SMB 源为当前目录：{smb['name']} ===")
r = api("/api/music/sources/active", {"id": smb["id"]})
print("  active_dir =", r.get("active_dir"))

print("\n=== B. 搜一首新歌并下载到 SMB ===")
q = urllib.parse.quote("起风了")
with urllib.request.urlopen(f"{BASE}/api/online/search?q={q}&provider={urllib.parse.quote('元力WY')}&limit=3", timeout=30) as rr:
    items = json.loads(rr.read().decode()).get("items", [])
if not items:
    print("  搜索无结果，跳过")
else:
    it = items[0]
    print("  选中:", it["title"], "-", it["artist"])
    r = api("/api/online/download", {"items": [{"provider": it["provider"], "id": it["id"],
                                               "title": it["title"], "artist": it["artist"],
                                               "duration_sec": it.get("duration") or 0}]})
    print("  下载请求:", r)
    time.sleep(12)
    dl = api("/api/online/downloads")
    for j in dl.get("jobs", [])[:3]:
        print(f"   job {j['status']:8s} {j['title'][:18]:20s} {j.get('error','') or j.get('file','')}")

print("\n=== C. 切回本地目录 ===")
r = api("/api/music/sources/active", {"id": local["id"]})
print("  active_dir =", r.get("active_dir"))
time.sleep(3)
d = api("/api/music/sources")
print("  本地源状态:",
      [(s["name"], s["readable"], s["audio_files"]) for s in d["sources"] if s["type"] == "path"])
