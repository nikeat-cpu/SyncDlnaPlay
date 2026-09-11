# -*- coding: utf-8 -*-
"""端到端验证自动续播：加 2 首在线歌 -> 选音响 -> 播第 0 首 -> seek 到曲尾 -> 确认自动切下一首。
测试完停止播放并恢复音量。"""
import json
import time
import urllib.parse
import urllib.request

BASE = "http://192.168.1.10:5000"
PROVIDER = "元力WY"


def api(path, data=None, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    body = None
    if data is not None:
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data).encode("utf-8")
    with urllib.request.urlopen(req, body, timeout=40) as r:
        return json.loads(r.read().decode())


def search(q, limit=3):
    u = (f"{BASE}/api/online/search?q={urllib.parse.quote(q)}"
         f"&provider={urllib.parse.quote(PROVIDER)}&limit={limit}")
    with urllib.request.urlopen(u, timeout=30) as r:
        return json.loads(r.read().decode()).get("items", [])


# 1. 选音响（斐讯 154）并调低音量；两台斐讯刷机后 UDN 相同，只能按 UDN 选一台
st = api("/api/state")
renderers = st.get("devices") or []
phicomm = [r for r in renderers if r.get("ip") == "192.168.1.154"]
print("音响:", [(r["ip"], r.get("name") or r.get("friendly_name") or "?") for r in phicomm])
if not phicomm:
    print("找不到斐讯音响")
    raise SystemExit(1)
udns = [r["udn"] for r in phicomm]
api("/api/targets", {"udns": udns}, "POST")
old_vol = {}
for r in phicomm:
    v = r.get("volume")
    old_vol[r["udn"]] = v
    api("/api/volume", {"volume": 12, "udns": [r["udn"]]}, "POST")

try:
    # 2. 加两首在线歌入队
    items = search("孤勇者")[:2] or search("周杰伦")[:2]
    if len(items) < 2:
        print("搜索结果不足"); raise SystemExit(1)
    payload = [{"provider": it["provider"], "id": it["id"], "title": it["title"],
                "artist": it["artist"], "album": it.get("album", ""),
                "artwork": it.get("artwork", ""), "duration_sec": it.get("duration") or 0}
               for it in items]
    r = api("/api/online/add", {"items": payload}, "POST")
    print("入队:", r)
    st = api("/api/state")["player"]
    print("队列:", [(t["title"][:16], t.get("duration_sec")) for t in st["queue"]])

    # 3. 播第 0 首
    r = api("/api/jump", {"index": 0}, "POST")
    print("jump:", r.get("ok"))
    time.sleep(5)
    st = api("/api/state")["player"]
    dur0 = st["queue"][0].get("duration_sec") or 0
    print(f"当前: [{st['index']}] {st['current']['title'][:20]} dur={dur0}")

    # 4. seek 到曲尾前 8 秒
    if dur0 > 15:
        api("/api/seek", {"position": dur0 - 8}, "POST")
        print(f"seek -> {dur0-8}s")
    else:
        print("曲长未知/太短，直接等自然播完")

    # 5. 等自动续播
    advanced = False
    for i in range(14):
        time.sleep(3)
        st = api("/api/state")["player"]
        cur = st.get("current") or {}
        print(f"  t+{(i+1)*3}s index={st.get('index')} playing={st.get('playing')} "
              f"cur={cur.get('title','')[:20]}")
        if st.get("index", 0) == 1:
            print("✅ 自动续播成功：已切到第 1 首 ->", cur.get("title"))
            advanced = True
            break
    if not advanced:
        print("❌ 自动续播未触发")
finally:
    api("/api/control", {"action": "stop"}, "POST")
    for udn, v in old_vol.items():
        if v:
            api("/api/volume", {"volume": v, "udns": [udn]}, "POST")
    print("已停止播放，音量恢复:", old_vol)
