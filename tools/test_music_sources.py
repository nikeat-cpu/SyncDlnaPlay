# -*- coding: utf-8 -*-
"""音乐目录源（本地 / SMB）端到端验证"""
import json
import time
import urllib.parse
import urllib.request

BASE = "http://192.168.1.10:5000"


def api(path, data=None, method=None):
    m = method or ("POST" if data is not None else "GET")
    req = urllib.request.Request(BASE + path, method=m)
    body = None
    if data is not None:
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data).encode()
    with urllib.request.urlopen(req, body, timeout=60) as r:
        return json.loads(r.read().decode())


print("=== 1. 重启后源状态（SMB 是否自动挂载）===")
time.sleep(3)
d = api("/api/music/sources")
print("  nsenter:", d.get("nsenter"), "| 当前目录:", d.get("active_dir"))
for s in d["sources"]:
    print(f"  [{s['type']:4s}] {s['name']:14s} mounted={s['mounted']} readable={s['readable']} "
          f"writable={s['writable']} files={s['audio_files']} dirs={s['sub_dirs']} active={s['active']}")

smb = [s for s in d["sources"] if s["type"] == "smb"]
if not smb:
    print("没有 SMB 源，跳过后续测试")
    raise SystemExit(0)
smb = smb[0]
local = [s for s in d["sources"] if s["type"] == "path"][0]

print("\n=== 2. 浏览 SMB 源目录 ===")
r = api("/api/music/browse?path=" + urllib.parse.quote(smb["container_path"]))
print("  ok:", r.get("ok"), "| 子目录:", [x["name"] for x in (r.get("dirs") or [])][:8])

print("\n=== 3. 切换到 SMB 源作为当前目录 ===")
r = api("/api/music/sources/active", {"id": smb["id"]})
print("  ok:", r.get("ok"), "| active_dir:", r.get("active_dir"))
time.sleep(10)
lib = api("/api/library?source=local&container=")
print("  本地曲库:", lib.get("ok"), "| 文件夹:", (lib.get("folders") or [])[:6], "| 曲目:", lib.get("total"))

print("\n=== 4. 下载到只读 SMB 源（应被拒）===")
r = api("/api/online/download", {"items": [{"provider": "元力WY", "id": "x", "title": "t", "artist": "a"}]})
print("  ok:", r.get("ok"), "| msg:", r.get("msg"))

print("\n=== 5. 切回本地目录并下载（应放行）===")
api("/api/music/sources/active", {"id": local["id"]})
time.sleep(2)
r = api("/api/music/sources")
print("  当前目录:", r.get("active_dir"))
q = urllib.parse.quote("孤勇者")
with urllib.request.urlopen(f"{BASE}/api/online/search?q={q}&provider={urllib.parse.quote('元力WY')}&limit=1", timeout=30) as rr:
    items = json.loads(rr.read().decode()).get("items", [])
if items:
    it = items[0]
    r = api("/api/online/download", {"items": [{"provider": it["provider"], "id": it["id"],
                                                "title": it["title"], "artist": it["artist"],
                                                "duration_sec": it.get("duration") or 0}]})
    print("  下载请求:", r)
