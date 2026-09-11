#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2 综合实测：自动续播 / 上下曲 / 循环随机 / 播放列表增删 / 整目录播放"""
import json, time, urllib.request, urllib.error

BASE = "http://127.0.0.1:5010"
SPEAKER_IPS = ("192.168.1.154", "192.168.1.196")
PASS = []
FAIL = []

def call(method, path, body=None, timeout=20):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data,
          headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_state():
    return call("GET", "/api/state")

def speaker_udns():
    st = get_state()
    return [d["udn"] for d in st["devices"] if d["ip"] in SPEAKER_IPS]

def snap():
    return get_state()["player"]

def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'✅' if cond else '❌'}] {name} {extra}")

print("=" * 64)
print("v2 综合实测")
print("=" * 64)

# ---- 1. 选中两个斐讯音响 ----
udns = speaker_udns()
print(f"[1] 选中音响: {udns}")
r = call("POST", "/api/targets", {"udns": udns})
check("选中两个音响", r.get("ok") and len(r.get("targets", [])) == 2)

# 复位模式与队列，确保测试不受历史状态影响
call("POST", "/api/mode", {"repeat": "off", "shuffle": False})
call("POST", "/api/queue", {"action": "clear"})

# ---- 2. 默认模式 ----
s0 = snap()
check("默认 repeat=off", s0.get("repeat") == "off", f"(repeat={s0.get('repeat')})")
check("默认 shuffle=false", s0.get("shuffle") == False)
check("snapshot 含 order 字段", "order" in s0)

# ---- 3. 播放队列 [4秒短音频, 歌A, 歌B] ----
print("[3] 播放队列 [4s短音频, 歌A, 歌B]")
tracks = [
    {"url": "http://192.168.1.10:8200/MediaItems/2869.mp3", "title": "4秒测试音频", "duration": "0:00:04"},
    {"url": "http://192.168.1.10:8200/MediaItems/35.mp3", "title": "我是一只鱼", "duration": "0:03:24", "artist": "侯湘婷"},
    {"url": "http://192.168.1.10:8200/MediaItems/39.mp3", "title": "一个人的星期天", "duration": "0:03:29", "artist": "侯湘婷"},
]
r = call("POST", "/api/play", {"tracks": tracks, "index": 0})
s = snap()
check("队列长度=3", len(s["queue"]) == 3, f"(len={len(s['queue'])})")
check("播放顺序 [0,1,2]", s["order"] == [0, 1, 2], f"(order={s['order']})")
check("当前索引=0", s["index"] == 0)
check("当前曲目=短音频", s["current"] and s["current"]["title"] == "4秒测试音频")

# ---- 4. 自动续播：等短音频结束应跳到歌A(index1) ----
print("[4] 等待自动续播 (4秒短音频 -> 歌A)...")
t0 = time.time()
advanced = False
while time.time() - t0 < 18:
    s = snap()
    if s["index"] == 1:
        advanced = True
        break
    time.sleep(1)
s = snap()
check("自动续播到下一首(index=1)", advanced, f"(index={s['index']}, 当前={s['current']['title'] if s['current'] else None})")

# ---- 5. 下一曲 ----
print("[5] 下一曲")
call("POST", "/api/control", {"action": "next"})
s = snap()
check("下一曲 -> index=2", s["index"] == 2, f"(index={s['index']})")

# ---- 6. 上一曲 ----
print("[6] 上一曲")
call("POST", "/api/control", {"action": "prev"})
s = snap()
check("上一曲 -> index=1", s["index"] == 1, f"(index={s['index']})")

# ---- 7. 循环=列表 + 随机=开 ----
print("[7] 设置 列表循环 + 随机")
r = call("POST", "/api/mode", {"repeat": "all", "shuffle": True})
s = snap()
check("repeat=all", s["repeat"] == "all", f"({s['repeat']})")
check("shuffle=true", s["shuffle"] is True)
check("order 长度=3", len(s["order"]) == 3, f"({s['order']})")
# 当前曲应被移到 order 首位
check("当前曲在顺序首位", s["order"][0] == s["index"], f"(order={s['order']}, idx={s['index']})")

# ---- 8. 随机下 shuffled 下一曲 ----
print("[8] 随机模式下一曲")
before = s["order"]
call("POST", "/api/control", {"action": "next"})
s2 = snap()
check("随机下一曲有效推进", s2["index"] in before, f"(index={s2['index']}, order={s2['order']})")

# ---- 9. 播放列表移除 ----
print("[9] 移除队列第0项")
call("POST", "/api/queue", {"action": "remove", "index": 0})
s = snap()
check("移除后队列=2", len(s["queue"]) == 2, f"(len={len(s['queue'])})")

# ---- 10. 清空队列 ----
print("[10] 清空队列")
call("POST", "/api/queue", {"action": "clear"})
s = snap()
check("清空后队列为空", len(s["queue"]) == 0, f"(len={len(s['queue'])})")

# ---- 11. 整目录播放 (play-container) ----
print("[11] 整目录播放：定位一个含曲目的容器")
def find_leaf_container(cid, depth=0, max_depth=4):
    r = call("GET", f"/api/library?source=dlna&container={urllib.parse.quote(cid)}")
    if not r.get("ok"):
        return None
    items = r.get("items", [])
    # 先检查本层是否直接含曲目（音乐库 API 中曲目不带 type 字段，仅容器带 type=container）
    if any(it.get("type") != "container" for it in items):
        return cid
    if depth >= max_depth:
        return None
    # 否则向下递归一层层寻找含曲目的容器
    for it in items:
        if it.get("type") == "container":
            f = find_leaf_container(it["id"], depth + 1, max_depth)
            if f:
                return f
    return None

import urllib.parse
cid = find_leaf_container("0")
if cid:
    r = call("POST", "/api/play-container", {"source": "dlna", "container": cid, "index": 0})
    s = snap()
    check("play-container 返回成功", r.get("ok"), f"(total={r.get('total')})")
    check("整目录队列>0", len(s["queue"]) > 0, f"(len={len(s['queue'])})")
else:
    check("找到含曲目容器", False, "(未找到)")

# 停止，清理
call("POST", "/api/control", {"action": "stop"})
call("POST", "/api/queue", {"action": "clear"})

print("\n" + "=" * 64)
print(f"结果: ✅ 通过 {len(PASS)} 项 | ❌ 失败 {len(FAIL)} 项")
if FAIL:
    print("失败项:", FAIL)
print("=" * 64)
