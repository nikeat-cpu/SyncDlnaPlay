# -*- coding: utf-8 -*-
"""端到端测试：搜"孤勇者"，全部下载，检查哪些被跳过（时长 < 60s）。"""
import json, time, urllib.request, urllib.parse

BASE = "http://192.168.1.10:5000"


def api(path, data=None):
    req = urllib.request.Request(BASE + path, method="POST")
    req.add_header("Content-Type", "application/json")
    body = json.dumps(data).encode()
    with urllib.request.urlopen(req, body, timeout=30) as r:
        return json.loads(r.read().decode())


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return json.loads(r.read().decode())


# 搜"孤勇者"（limit=10）
q = urllib.parse.quote("孤勇者")
with urllib.request.urlopen(f"{BASE}/api/online/search?q={q}&provider={urllib.parse.quote('元力WY')}&limit=10", timeout=30) as r:
    search = json.loads(r.read().decode())

items = search.get("items", [])
print(f"搜索结果: {len(items)} 首")
for i, it in enumerate(items):
    print(f"  {i+1}. [{it['title'][:24]}] dur={it.get('duration', it.get('duration_sec', '?'))}")

# 全部下载
payload = [{"provider": it["provider"], "id": it["id"], "title": it["title"],
            "artist": it["artist"], "duration_sec": it.get("duration") or it.get("duration_sec") or 0}
           for it in items]
r = api("/api/online/download", {"items": payload})
print(f"\n下载请求: queued={r.get('queued')}, exists={r.get('exists')}")

# 等下载完成（最多 60s）
time.sleep(5)
dl = get("/api/online/downloads")
jobs = dl.get("jobs", [])
done = [j for j in jobs if j["status"] == "done"]
skipped = [j for j in jobs if j["status"] == "exists"]
errors = [j for j in jobs if j["status"] == "error"]
pending = [j for j in jobs if j["status"] in ("pending", "downloading")]

print(f"\n下载结果:")
print(f"  ✅ 完成: {len(done)}")
for j in done:
    print(f"     {j['title'][:24]} -> {j.get('file','')[-40:]} ({j.get('size',0)} bytes)")
print(f"  ⏭ 跳过(<60s): {len(skipped)}")
for j in skipped:
    print(f"     {j['title'][:24]}")
if errors:
    print(f"  ❌ 失败: {len(errors)}")
    for j in errors:
        print(f"     {j['title'][:24]}: {j.get('error','')}")
if pending:
    print(f"  ⏳ 还在下载: {len(pending)}")
