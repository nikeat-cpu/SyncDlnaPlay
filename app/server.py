#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DLNA 音响控制系统 - Web 服务
=============================
提供 REST API + Web 界面，用于控制局域网内的 DLNA 渲染器（音响）播放音乐。

音乐源支持两种：
  1. DLNA MediaServer（如 iStoreOS 上的 MiniDLNA）—— 通过 ContentDirectory 浏览
  2. 本地目录（挂载的 SMB/NFS 共享）—— 直接扫描并通过 HTTP 暴露给音响

环境变量：
  PREFER_NET    首选网段前缀，如 "192.168.1."（用于 SSDP 组播网卡选择）
  HTTP_PORT     监听端口，默认 5000
  MUSIC_DIR     本地音乐目录（挂载共享存储），如 /music
  HOST_IP       本机对外 IP（音响用它回拉音频），默认自动探测
  POLL_INTERVAL 状态轮询间隔（秒），默认 1.5
  SCAN_INTERVAL 设备重扫间隔（秒），默认 300
"""

import os
import sys
import json
import time
import threading
import logging
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import upnp
import music_sources

# 零依赖 Web 层（Flask 兼容子集），见 miniweb.py
from miniweb import MiniApp, jsonify, request, send_from_directory, Response

# ---------------------------------------------------------------- 配置

PREFER_NET = os.environ.get("PREFER_NET", "").strip() or None
HTTP_PORT = int(os.environ.get("HTTP_PORT", "5000"))
MUSIC_DIR = os.environ.get("MUSIC_DIR", "").strip()
HOST_IP = os.environ.get("HOST_IP", "").strip()
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1.5"))
SCHED_INTERVAL = float(os.environ.get("SCHED_INTERVAL", "0.25"))  # 切歌调度器高频轮询
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", "300"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
STATE_FILE = os.environ.get("STATE_FILE", "").strip()

# MusicFree 在线音源桥接服务（端口 5001，与 dlna-speaker 同机运行）
# BRIDGE_URL: 本服务访问 bridge 的地址（容器间用 127.0.0.1 即可）
# BRIDGE_PUBLIC: 回给音响拉流的公开基址；留空则自动用本机 IP:5001
BRIDGE_URL = os.environ.get("MUSICFREE_BRIDGE_URL", "http://127.0.0.1:5001").rstrip("/")
BRIDGE_PUBLIC = os.environ.get("MUSICFREE_BRIDGE_PUBLIC", "").strip()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("dlna")

app = MiniApp(__name__, static_folder=os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static"),
    static_url_path="/static")
app.json.ensure_ascii = False

AUDIO_EXTS = set(upnp.MIME_MAP.keys())


# ---------------------------------------------------------------- 工具

def host_ip():
    """本机对外 IP（供音响回拉音频用）"""
    if HOST_IP:
        return HOST_IP
    ips = upnp.pick_ips(PREFER_NET) if PREFER_NET else upnp.local_ips()
    return ips[0] if ips else ""


def norm_track(t: dict) -> dict:
    """统一曲目结构（兼容本地 DLNA/共享目录 与 在线 MusicFree 音源）"""
    raw_dur = t.get("duration", "")
    if raw_dur:
        duration = upnp.norm_duration(raw_dur)
        duration_sec = upnp.tsec_to_sec(duration)
    else:
        duration_sec = int(t.get("duration_sec") or 0)
        duration = ""
    return {
        "id": t.get("id", ""),
        "title": t.get("title") or (t.get("url", "").rsplit("/", 1)[-1] or "未知"),
        "artist": t.get("artist", ""),
        "album": t.get("album", ""),
        "url": t.get("url", ""),
        "duration": duration,
        "duration_sec": duration_sec,
        "source": t.get("source", "dlna"),
        # 在线音源需要保留 provider/oid，播放时才能拼出 bridge 的 /stream 地址
        "provider": t.get("provider", ""),
        "oid": t.get("oid", ""),
    }


def bridge_public():
    """回给音响拉流的 bridge 公开基址（同机，用本机对外 IP）"""
    if BRIDGE_PUBLIC:
        return BRIDGE_PUBLIC.rstrip("/")
    return f"http://{host_ip()}:5001"


def track_uri(track: dict) -> str:
    """在线曲目返回 bridge 的 /stream 代理地址；本地曲目原样返回 url"""
    if track.get("source") == "online":
        return (f"{bridge_public()}/stream"
                f"?provider={urllib.parse.quote(track.get('provider', ''))}"
                f"&id={urllib.parse.quote(track.get('oid', ''))}")
    return track.get("url", "")


# ---------------------------------------------------------------- 设备管理器

class DeviceManager:
    """维护已发现的渲染器与媒体服务器"""

    def __init__(self):
        self.lock = threading.RLock()
        self.renderers = {}     # udn -> Renderer
        self.servers = {}       # udn -> MediaServer
        self.status = {}        # udn -> status dict
        self.last_scan = 0
        self.scanning = False
        self.scan_error = None

    def refresh(self, force: bool = False):
        if self.scanning:
            return False, "正在扫描中"
        with self.lock:
            self.scanning = True
        try:
            log.info("开始扫描局域网设备 ...")
            rs = upnp.discover_renderers(prefer_net=PREFER_NET, timeout=3)
            ss = upnp.discover_servers(prefer_net=PREFER_NET, timeout=3)

            with self.lock:
                for info in rs:
                    udn = info.get("udn")
                    if not udn:
                        continue
                    if udn in self.renderers:
                        # 更新描述（端口/location 可能变化）
                        old = self.renderers[udn]
                        old.info.update(info)
                        old.services = info.get("services", {})
                        old.location = info.get("location", "")
                    else:
                        self.renderers[udn] = upnp.Renderer(info)
                        log.info(f"  发现音响: {info.get('friendly_name')} @ {info.get('ip')}")

                for s in ss:
                    if s.udn and s.udn not in self.servers:
                        self.servers[s.udn] = s
                        log.info(f"  发现媒体服务器: {s.name} @ {s.ip}")

                self.last_scan = time.time()
                self.scan_error = None
            log.info(f"扫描完成: {len(self.renderers)} 个音响, {len(self.servers)} 个媒体服务器")
            return True, "ok"
        except Exception as e:
            log.exception("扫描失败")
            with self.lock:
                self.scan_error = repr(e)
            return False, repr(e)
        finally:
            with self.lock:
                self.scanning = False

    def refresh_async(self):
        threading.Thread(target=self.refresh, daemon=True).start()

    def get(self, key: str):
        """按 UDN 或 IP 查找渲染器"""
        with self.lock:
            for r in self.renderers.values():
                if r.udn == key or r.ip == key:
                    return r
        return None

    def all_renderers(self):
        with self.lock:
            return list(self.renderers.values())

    def all_servers(self):
        with self.lock:
            return list(self.servers.values())


# ---------------------------------------------------------------- 本地音乐库（挂载共享目录）

class LocalLibrary:
    """扫描本地/挂载目录中的音频文件，按目录组织"""

    # 扫描保护：超大目录（如整个共享根/含 Docker 数据）不能拖死服务
    MAX_FILES = 30000
    MAX_DEPTH = 8
    MAX_SECONDS = 90          # 扫描墙钟上限，超大目录也不会无限拖
    SKIP_DIRS = {"Docker", "overlay2", "lost+found", "@eaDir", ".Trash",
                 "#recycle", "node_modules", ".git", "System Volume Information"}

    def __init__(self, root: str):
        self.root = root
        self.lock = threading.RLock()
        self.index = {}     # 目录相对路径 -> [曲目]
        self.dirs = set()
        self.last_scan = 0
        self.scanning = False
        self.truncated = False

    def set_root(self, root: str):
        """切换音乐目录根（源变更时调用），并清空旧索引"""
        root = (root or "").rstrip("/")
        with self.lock:
            if root == self.root:
                return False
            self.root = root
            self.index = {}
            self.dirs = set()
            self.last_scan = 0
        return True

    def enabled(self) -> bool:
        return bool(self.root) and os.path.isdir(self.root)

    def scan(self):
        if not self.enabled():
            return
        with self.lock:
            if self.scanning:
                return
            self.scanning = True
            self.truncated = False
        idx = {}
        dirs = set()
        total = 0
        truncated = False
        deadline = time.time() + self.MAX_SECONDS
        try:
            for dirpath, dirnames, filenames in os.walk(self.root):
                if time.time() > deadline:
                    truncated = True
                    break
                dirnames[:] = sorted(d for d in dirnames if d not in self.SKIP_DIRS)
                rel_dir = os.path.relpath(dirpath, self.root).replace("\\", "/")
                depth = 0 if rel_dir == "." else rel_dir.count("/") + 1
                if depth > self.MAX_DEPTH:
                    dirnames[:] = []
                    continue
                if rel_dir == ".":
                    rel_dir = ""
                dirs.add(rel_dir)
                if total >= self.MAX_FILES:
                    truncated = True
                    break
                tracks = []
                for fn in sorted(filenames):
                    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
                    if ext not in AUDIO_EXTS:
                        continue
                    full = os.path.join(dirpath, fn)
                    rel_file = os.path.relpath(full, self.root).replace("\\", "/")
                    tracks.append({
                        "id": "L:" + rel_file,
                        "title": fn.rsplit(".", 1)[0],
                        "artist": "",
                        "album": os.path.basename(dirpath) if rel_dir else "",
                        "url": f"http://{host_ip()}:{HTTP_PORT}/media/"
                               + urllib.parse.quote(rel_file),
                        "duration": "",
                        "source": "local",
                    })
                if tracks:
                    idx[rel_dir] = tracks
                    total += len(tracks)
            with self.lock:
                if not truncated:
                    self.index = idx
                    self.dirs = dirs
                self.last_scan = time.time()
                self.truncated = truncated
            log.info(f"本地音乐扫描完成: {len(idx)} 个目录, {total} 首"
                     + ("（已达上限，已截断）" if truncated else ""))
        except Exception:
            log.exception("本地音乐扫描失败")
        finally:
            with self.lock:
                self.scanning = False

    def list_dir(self, rel: str = ""):
        """列出指定目录下的子目录与曲目"""
        with self.lock:
            if not self.index:
                return [], []
            prefix = rel.rstrip("/")
            subs = set()
            for d in self.dirs:
                if not d:
                    continue
                if not prefix:
                    parts = d.split("/")
                    if parts:
                        subs.add(parts[0])
                elif d.startswith(prefix + "/"):
                    rest = d[len(prefix) + 1:]
                    if rest:
                        subs.add(rest.split("/")[0])
            tracks = self.index.get(prefix, [])
            return sorted(subs), tracks


# ---------------------------------------------------------------- 播放器（队列 + 同步 + 自动续播）

class Player:
    """管理播放目标、队列与自动续播"""

    def __init__(self, dm: DeviceManager):
        self.dm = dm
        self.lock = threading.RLock()
        self.queue = []          # 曲目列表（真实顺序）
        self.index = -1          # 当前曲目在 queue 中的下标
        self.order = []          # 播放顺序（queue 下标的序列，用于 shuffle/循环）
        self.playpos = 0         # 当前曲目在 order 中的位置
        self.targets = []        # 目标设备 UDN
        self.delays = {}         # udn -> delay_ms，按音响错峰下发 Play
        self.auto_advance = True
        self.playing = False
        self.repeat = "off"      # off / all / one
        self.shuffle = False
        self.last_cmd_ts = 0     # 上次下发播放指令的时间，用于宽限期
        self.executor = ThreadPoolExecutor(max_workers=24)
        self.grace = 3.0         # 播放指令后的宽限期（秒内不判定为"播完")
        # 预测式切歌调度所需状态
        self.track_start_ts = 0.0   # 当前曲目开始播放的墙钟时间
        self.track_dur_sec = 0      # 当前曲目时长（秒，来自元数据或设备回读）
        self.advance_fired = False  # 当前曲目是否已触发过续播（防重复）
        self.saw_playing = False    # 当前曲目是否确认开播过（见过 PLAYING）
        self.sched_stop = threading.Event()
        self.state_file = STATE_FILE
        self._load_state()

    # ---- 持久化 ----
    def _save_state(self):
        """把 targets 与 delays 持久化到 STATE_FILE（JSON）"""
        if not self.state_file:
            return
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({
                    "targets": self.targets,
                    "delays": self.delays,
                }, f, ensure_ascii=False)
        except Exception as e:
            log.warning(f"状态持久化失败: {e}")

    def _load_state(self):
        """从 STATE_FILE 恢复 targets 与 delays"""
        if not self.state_file or not os.path.isfile(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                udns = data.get("targets") or []
                self.targets = list(dict.fromkeys(udns))
                for u, d in (data.get("delays") or {}).items():
                    self.delays[u] = max(0, int(d or 0))
                log.info(f"已从 {self.state_file} 恢复状态: targets={len(self.targets)}, delays={len(self.delays)}")
        except Exception as e:
            log.warning(f"状态恢复失败: {e}")

    # ---- 目标设备 ----
    def set_targets(self, udns=None, targets=None):
        """两种调用格式：
           1. set_targets(udns=['uuid:...'])
           2. set_targets(targets=[{'udn':'...','delay_ms':200}, ...])
        """
        with self.lock:
            if targets is not None:
                udns = []
                for t in targets:
                    if isinstance(t, dict):
                        u = t.get("udn")
                        if u:
                            udns.append(u)
                            self.delays[u] = max(0, int(t.get("delay_ms", 0) or 0))
                    elif t:
                        udns.append(t)
                self.targets = list(dict.fromkeys(udns))
            elif udns is not None:
                self.targets = list(dict.fromkeys(udns))
            self._save_state()
            return self.targets

    def set_delay(self, udn: str, delay_ms: int):
        with self.lock:
            delay_ms = max(0, int(delay_ms or 0))
            self.delays[udn] = delay_ms
            self._save_state()
            return delay_ms

    def _target_renderers(self):
        out = []
        for u in self.targets:
            r = self.dm.get(u)
            if r:
                out.append(r)
        return out

    # ---- 播放顺序 ----
    def _rebuild_order(self):
        """依据 shuffle 重建播放顺序，并保持当前曲目在 order 中的位置"""
        import random
        n = len(self.queue)
        if n == 0:
            self.order = []
            self.playpos = 0
            return
        base = list(range(n))
        if self.shuffle:
            random.shuffle(base)
            if 0 <= self.index < n and self.index in base:
                base.remove(self.index)
                base.insert(0, self.index)
            self.playpos = 0
        else:
            self.playpos = base.index(self.index) if 0 <= self.index < n else 0
        self.order = base

    def set_mode(self, repeat=None, shuffle=None):
        with self.lock:
            if repeat in ("off", "all", "one"):
                self.repeat = repeat
            if shuffle is True or shuffle is False:
                changed = (shuffle != self.shuffle)
                self.shuffle = shuffle
                if changed:
                    self._rebuild_order()
        return self.repeat, self.shuffle

    # ---- 播放 ----
    def play_tracks(self, tracks, start_index=0):
        with self.lock:
            self.queue = [norm_track(t) for t in tracks]
            n = len(self.queue)
            self.index = max(0, min(start_index, n - 1)) if n else -1
            self.auto_advance = True
            self.playing = True
            self._rebuild_order()
        return self._push_current()

    def _push_current(self):
        """把当前曲目推送到所有目标。
        先并发 SetURI（不会出声），再按 delay_ms 分组错峰下发 Play，
        让较慢的音响晚一点启动，达到手动对齐的目的。
        """
        with self.lock:
            if not self.queue or self.index < 0 or self.index >= len(self.queue):
                return False, "队列为空或索引越界"
            track = self.queue[self.index]
            targets = self._target_renderers()
            if not targets:
                return False, "未选中任何音响"

        log.info(f"推送 [{self.index+1}/{len(self.queue)}] {track['title']} "
                 f"-> {len(targets)} 个音响")

        dur = track.get("duration", "")

        def seturi(r):
            uri = track_uri(track)
            return r.udn, r.set_uri(
                uri, title=track.get("title", ""), duration=dur,
                artist=track.get("artist", ""), album=track.get("album", ""),
            )

        # 1. 并发 SetURI（所有设备同时准备好，但不出声）
        results = {}
        futs = [self.executor.submit(seturi, r) for r in targets]
        for f in as_completed(futs):
            try:
                udn, res = f.result()
                results[udn] = res
            except Exception as e:
                log.exception("SetURI 异常")

        # 2. 按 delay_ms 分组，错峰 Play
        with self.lock:
            delay_map = {}
            for r in targets:
                d = self.delays.get(r.udn, 0)
                delay_map.setdefault(d, []).append(r)
        sorted_groups = sorted(delay_map.items(), key=lambda x: x[0])

        play_res = {}
        last_delay_ms = 0
        for delay_ms, rs in sorted_groups:
            if delay_ms > last_delay_ms:
                time.sleep((delay_ms - last_delay_ms) / 1000.0)
                last_delay_ms = delay_ms
            futs = {self.executor.submit(r.play): r for r in rs}
            for f in as_completed(futs):
                r = futs[f]
                try:
                    play_res[r.udn] = f.result()
                except Exception as e:
                    play_res[r.udn] = (False, repr(e))

        with self.lock:
            self.playing = True
            self.last_cmd_ts = time.time()
            # 记录开始时间与曲长，供预测式切歌调度使用
            self.track_start_ts = time.time()
            self.track_dur_sec = track.get("duration_sec") or 0
            self.advance_fired = False
            self.saw_playing = False

        ok = any(v[0] for v in results.values())
        errs = {u: v[1] for u, v in results.items() if not v[0]}
        delay_info = {r.udn: self.delays.get(r.udn, 0) for r in targets}
        return ok, {"set_uri": errs or "ok", "play": play_res, "track": track, "delays": delay_info}

    def resync(self):
        """重新同步：对所有目标重新下发当前曲目（修正两台音响的进度偏差）"""
        with self.lock:
            if self.index < 0:
                return False, "当前无播放曲目"
        return self._push_current()

    def _resync_prediction(self):
        """从设备实时位置重算预测式调度所需的开始时间/曲长。
        用于暂停后继续播放、或任何可能让 track_start_ts 过期的情况。"""
        rs = self._target_renderers()
        if not rs:
            return
        try:
            st = rs[0].quick_status()
        except Exception:
            return
        if not st.get("online"):
            return
        pos = st.get("position_sec", 0) or 0
        with self.lock:
            self.track_start_ts = time.time() - pos
            if st.get("duration_sec", 0) > 0:
                self.track_dur_sec = st["duration_sec"]
            self.advance_fired = False

    # ---- 队列内导航（上一曲 / 下一曲 / 自动续播）----
    def _next(self):
        """前进到 order 中的下一首；列表循环时回到开头；到末尾且非循环则停止"""
        with self.lock:
            n = len(self.order)
            if n == 0:
                return False, "队列为空"
            self.playpos += 1
            if self.playpos >= n:
                if self.repeat == "all":
                    self.playpos = 0
                else:
                    self.playing = False
                    self.auto_advance = False
                    return True, "队列播放完毕"
            self.index = self.order[self.playpos]
            self.auto_advance = True
            self.playing = True
        return self._push_current()

    def _prev(self):
        with self.lock:
            n = len(self.order)
            if n == 0:
                return False, "队列为空"
            self.playpos -= 1
            if self.playpos < 0:
                self.playpos = n - 1 if self.repeat == "all" else 0
            self.index = self.order[self.playpos]
            self.auto_advance = True
            self.playing = True
        return self._push_current()

    def _advance(self):
        """自动续播：单曲循环则重播当前；否则前进一首（含列表循环/停止）"""
        with self.lock:
            if self.repeat == "one":
                self.auto_advance = True
                self.playing = True
                idx = self.index
        if self.repeat == "one":
            return self._push_current()
        return self._next()

    # ---- 传输控制 ----
    def control(self, action: str, udns=None):
        action = action.lower()
        if action not in ("play", "pause", "stop", "next", "prev", "previous"):
            return False, f"不支持的动作: {action}"

        with self.lock:
            if action == "stop":
                self.playing = False
                self.auto_advance = False       # 手动停止后不自动续播
            elif action == "pause":
                self.playing = False
            elif action == "play":
                self.playing = True
                self._resync_prediction()   # 继续播放：用设备实时位置重算预测
            elif action in ("next", "prev", "previous"):
                self.playing = True
                self.auto_advance = True

        # 上一曲 / 下一曲：由我们的队列导航处理（不依赖设备自身 transport）
        if action == "next":
            return self._next()
        if action in ("prev", "previous"):
            return self._prev()

        rs = [self.dm.get(u) for u in (udns or self.targets)]
        rs = [r for r in rs if r]
        if not rs:
            return False, "未选中任何音响"

        def do(r):
            fn = getattr(r, action, None)
            if not fn:
                return r.udn, (False, "设备不支持该操作")
            return r.udn, fn()

        out = {}
        futs = [self.executor.submit(do, r) for r in rs]
        for f in as_completed(futs):
            try:
                udn, res = f.result()
                out[udn] = res
            except Exception as e:
                log.exception("控制异常")

        with self.lock:
            self.last_cmd_ts = time.time()
        ok = any(v[0] for v in out.values()) if out else False
        return ok, out

    def set_volume(self, volume: int, udns=None):
        rs = [self.dm.get(u) for u in (udns or self.targets)]
        rs = [r for r in rs if r]
        if not rs:
            return False, "未选中任何音响"
        out = {}
        futs = {self.executor.submit(r.set_volume, volume): r for r in rs}
        for f in as_completed(futs):
            r = futs[f]
            try:
                out[r.udn] = f.result()
            except Exception as e:
                out[r.udn] = (False, repr(e))
        return True, out

    def seek(self, position_sec: int, udns=None):
        """跳转到指定秒数（对所有目标同时下发）"""
        target_time = upnp.sec_to_tsec(max(0, int(position_sec)))
        rs = [self.dm.get(u) for u in (udns or self.targets)]
        rs = [r for r in rs if r]
        if not rs:
            return False, "未选中任何音响"
        out = {}
        futs = {self.executor.submit(r.seek, target_time): r for r in rs}
        for f in as_completed(futs):
            r = futs[f]
            try:
                out[r.udn] = f.result()
            except Exception as e:
                out[r.udn] = (False, repr(e))
        with self.lock:
            self.last_cmd_ts = time.time()
            # 跳转后重算开始时间，使预测式调度基于新位置
            self.track_start_ts = time.time() - max(0, int(position_sec))
        return True, out

    # ---- 队列 ----
    def queue_add(self, tracks):
        with self.lock:
            start = len(self.queue)
            self.queue.extend([norm_track(t) for t in tracks])
            for i in range(start, len(self.queue)):
                self.order.append(i)        # 新加入的排在播放顺序末尾
        return len(self.queue)

    def queue_remove(self, index: int):
        with self.lock:
            n = len(self.queue)
            if index < 0 or index >= n:
                return False, "索引越界"
            # 重建队列与顺序，保持其余曲目不变
            removed_is_current = (index == self.index)
            self.queue = [t for i, t in enumerate(self.queue) if i != index]
            self.order = [i if i < index else i - 1 for i in self.order if i != index]
            if removed_is_current:
                # 当前曲被删：停掉，跳到顺序中的下一首
                self.index = -1
                self.playing = False
                self.auto_advance = False
            else:
                if self.index > index:
                    self.index -= 1
                self.playpos = self.order.index(self.index) if 0 <= self.index < len(self.queue) and self.index in self.order else 0
            return True, len(self.queue)

    def queue_clear(self):
        with self.lock:
            self.queue = []
            self.order = []
            self.index = -1
            self.playpos = 0
            self.playing = False
            self.auto_advance = False

    def jump(self, index: int):
        with self.lock:
            if index < 0 or index >= len(self.queue):
                return False, "索引越界"
            self.index = index
            if index not in self.order:
                self.order.append(index)
            self.playpos = self.order.index(index)
            self.auto_advance = True
            self.playing = True
        return self._push_current()

    def snapshot(self):
        with self.lock:
            return {
                "queue": self.queue,
                "index": self.index,
                "order": list(self.order),
                "playpos": self.playpos,
                "targets": list(self.targets),
                "playing": self.playing,
                "auto_advance": self.auto_advance,
                "repeat": self.repeat,
                "shuffle": self.shuffle,
                "current": self.queue[self.index] if 0 <= self.index < len(self.queue) else None,
            }

    # ---- 后台轮询 + 自动续播 ----
    def poll_once(self):
        """刷新所有设备状态，并在曲目结束时自动续播"""
        rs = self.dm.all_renderers()
        if rs:
            futs = {self.executor.submit(r.status): r for r in rs}
            new_status = {}
            for f in as_completed(futs):
                try:
                    st = f.result()
                    new_status[st["udn"]] = st
                except Exception:
                    pass
            with self.dm.lock:
                self.dm.status = new_status
        else:
            new_status = getattr(self.dm, "status", {})

        # 注：自动续播判定已移至 scheduler_loop（高频、预测式），
        # 这里仅负责刷新 UI 状态，不再触发续播，避免与调度器重复触发。

    def monitor_loop(self):
        while True:
            try:
                self.poll_once()
            except Exception:
                log.exception("轮询异常")
            time.sleep(POLL_INTERVAL)

    # ---- 预测式切歌调度（消除切歌不同步）----
    def _quick_status(self, targets):
        """对目标设备做轻量状态查询（传输状态 + 进度 + 曲长）"""
        out = {}
        if not targets:
            return out
        futs = {self.executor.submit(r.quick_status): r for r in targets}
        for f in as_completed(futs):
            try:
                st = f.result()
                if st:
                    out[st["udn"]] = st
            except Exception:
                pass
        return out

    @staticmethod
    def _ended(st, dur):
        """一台音响是否"已到曲尾"。
        判定：离线(避免卡死) / 报 STOPPED / 处于 PLAYING 且进度已到尾端(容差 0.6s)。
        仅切掉最后 0.6s 的尾巴，远小于原先的 3s，避免两台被切长度不同导致偏移随机。"""
        if not st or not st.get("online"):
            return True
        s = st.get("state")
        if s in ("STOPPED", "NO_MEDIA_PRESENT"):
            return True
        pos = st.get("position_sec") or 0
        # 曲长未知时只能靠 STOPPED 判定
        if dur and dur > 0 and s == "PLAYING" and pos >= dur - 0.6:
            return True
        return False

    def _sched_tick(self):
        """调度器单步：临近曲尾时高频确认，两台都真正到尾端后再统一错峰续播。"""
        with self.lock:
            if not (self.playing and self.auto_advance and self.queue and self.index >= 0):
                return
            if self.advance_fired:
                return
            if time.time() - self.last_cmd_ts < self.grace:
                return                      # 宽限期内不判定（含刚切歌/手动操作）
            dur = self.track_dur_sec
            start = self.track_start_ts
            targets = [self.dm.get(u) for u in self.targets]
            targets = [r for r in targets if r]

        # 距预计结束还远 -> 不必高频轮询，交给 monitor 慢轮询刷新 UI 即可
        if dur > 0:
            tte = (start + dur) - time.time()
            if tte > 6:
                return

        statuses = self._quick_status(targets)
        if not statuses:
            return

        # 曲长未知时，趁机从设备回读真实时长，修正预测
        if dur == 0:
            for st in statuses.values():
                if st.get("duration_sec", 0) > 0:
                    with self.lock:
                        self.track_dur_sec = st["duration_sec"]
                    dur = self.track_dur_sec
                    break

        online = [s for s in statuses.values() if s.get("online")]
        if not online:
            return
        if any(s.get("state") == "PLAYING" for s in online):
            with self.lock:
                self.saw_playing = True

        with self.lock:
            saw = self.saw_playing
            elapsed = time.time() - self.track_start_ts

        if dur == 0 and not saw:
            # 尚未确认开播（可能还在缓冲/拉流）：不允许按 STOPPED 误判为播完；
            # 超过 120s 仍未开播才兜底跳下一首（拉流失败的极端情况）。
            if elapsed > 120:
                log.warning("曲目 120s 未确认开播，兜底跳下一首")
                with self.lock:
                    if not self.advance_fired:
                        self.advance_fired = True
                self._advance()
            return

        # 必须等所有在线音响都真正到尾端，再统一错峰下发下一首，
        # 使每首歌的起始偏移恒定 = 已校准的 delay_ms，而不是每首随机漂。
        if all(self._ended(s, dur) for s in online):
            with self.lock:
                if not self.advance_fired:
                    self.advance_fired = True
            log.info("曲目结束（预测式），自动续播下一首")
            self._advance()

    def scheduler_loop(self):
        while not self.sched_stop.is_set():
            try:
                self._sched_tick()
            except Exception:
                log.exception("调度异常")
            time.sleep(SCHED_INTERVAL)


# ---------------------------------------------------------------- 全局实例

dm = DeviceManager()
library = LocalLibrary(MUSIC_DIR)
player = Player(dm)

# 音乐目录源（可动态添加本地路径 / SMB 共享），旧的 MUSIC_DIR 作为默认源兜底
sources = music_sources.get_sources(fallback_dir=MUSIC_DIR)


def apply_active_source(rescan=True):
    """把"当前源"应用到本地曲库（并触发重扫）"""
    d = sources.active_dir()
    changed = library.set_root(d)
    if changed and rescan and d:
        threading.Thread(target=library.scan, daemon=True).start()
    return d


# ---------------------------------------------------------------- 路由：页面

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/media/<path:filename>")
def media(filename):
    """把本地/挂载的音乐目录通过 HTTP 暴露给音响"""
    if not library.enabled():
        return "MUSIC_DIR 未配置", 404
    return send_from_directory(library.root, filename, conditional=True)


# ---------------------------------------------------------------- 路由：API

@app.route("/api/health")
def api_health():
    return jsonify({
        "ok": True,
        "host_ip": host_ip(),
        "prefer_net": PREFER_NET,
        "music_dir": sources.active_dir() or None,
        "music_sources": len(sources.sources),
        "renderers": len(dm.renderers),
        "servers": len(dm.servers),
        "last_scan": dm.last_scan,
    })


@app.route("/api/state")
def api_state():
    """全局状态：设备 + 播放队列 + 各设备实时状态"""
    with dm.lock:
        status = dict(dm.status)
    devices = []
    for r in dm.all_renderers():
        d = r.to_dict()
        st = status.get(r.udn)
        if st:
            d.update({
                "online": st.get("online"),
                "state": st.get("state"),
                "volume": st.get("volume"),
                "mute": st.get("mute"),
                "position": st.get("position"),
                "duration": st.get("duration"),
                "title": st.get("title"),
                "uri": st.get("uri"),
            })
            d["position_sec"] = upnp.tsec_to_sec(st.get("position") or "")
            d["duration_sec"] = upnp.tsec_to_sec(st.get("duration") or "")
        else:
            d.update({"online": False, "state": "UNKNOWN"})
        d["selected"] = r.udn in player.targets
        d["delay_ms"] = player.delays.get(r.udn, 0)
        devices.append(d)

    return jsonify({
        "devices": devices,
        "servers": [s.to_dict() for s in dm.all_servers()],
        "player": player.snapshot(),
        "host_ip": host_ip(),
        "last_scan": dm.last_scan,
        "scanning": dm.scanning,
    })


@app.route("/api/scan", methods=["POST", "GET"])
def api_scan():
    force = request.args.get("async", "1") == "1"
    if force:
        dm.refresh_async()
        return jsonify({"ok": True, "async": True})
    ok, msg = dm.refresh()
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/targets", methods=["POST"])
def api_targets():
    data = request.get_json(force=True, silent=True) or {}
    if "targets" in data:
        t = player.set_targets(targets=data.get("targets", []))
    else:
        udns = data.get("udns", [])
        if isinstance(udns, str):
            udns = [udns]
        t = player.set_targets(udns=udns)
    return jsonify({"ok": True, "targets": t})


@app.route("/api/delay", methods=["POST"])
def api_delay():
    data = request.get_json(force=True, silent=True) or {}
    udn = data.get("udn")
    delay_ms = data.get("delay_ms", 0)
    if not udn:
        return jsonify({"ok": False, "msg": "缺少 udn"}), 400
    delay_ms = player.set_delay(udn, delay_ms)
    return jsonify({"ok": True, "udn": udn, "delay_ms": delay_ms})


@app.route("/api/library")
def api_library():
    """
    浏览音乐库。
    source=dlna  -> 浏览 MediaServer（container 为 DLNA ObjectID）
    source=local -> 浏览本地挂载目录（container 为相对路径）
    """
    source = request.args.get("source", "dlna")
    container = request.args.get("container", "0" if source == "dlna" else "")
    start = int(request.args.get("start", 0))
    count = int(request.args.get("count", 300))

    if source == "local":
        if not library.enabled():
            return jsonify({"ok": False, "msg": "当前音乐目录不可用，请在「音乐目录」中检查"}), 400
        if not library.index:
            # 大目录首次扫描可能很慢：后台扫，先返回"扫描中"，避免请求卡死
            if not library.scanning:
                threading.Thread(target=library.scan, daemon=True).start()
            return jsonify({"ok": True, "source": "local", "container": container,
                            "folders": [], "items": [], "total": 0,
                            "scanning": True, "scanning_dir": library.root})
        subs, tracks = library.list_dir(container)
        return jsonify({
            "ok": True,
            "source": "local",
            "container": container,
            "folders": subs,
            "items": [norm_track(t) for t in tracks],
            "total": len(tracks),
            "scanning": library.scanning,
            "truncated": library.truncated,
        })

    servers = dm.all_servers()
    if not servers:
        return jsonify({"ok": False, "msg": "未发现媒体服务器"}), 404
    ms = servers[0]
    ok, items, total = ms.browse(container, start=start, count=count)
    if not ok:
        return jsonify({"ok": False, "msg": str(items)}), 500

    out = []
    for it in items:
        if it["type"] == "container":
            out.append({
                "id": it["id"], "title": it["title"],
                "type": "container", "url": "",
                "duration": "", "duration_sec": 0,
                "artist": "", "album": "", "source": "dlna",
            })
        else:
            n = norm_track(it)
            n["source"] = "dlna"
            out.append(n)
    return jsonify({
        "ok": True, "source": "dlna", "container": container,
        "server": ms.name, "items": out, "total": total,
    })


@app.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": False, "msg": "缺少关键字"}), 400
    source = request.args.get("source", "dlna")

    if source == "local":
        if not library.enabled():
            return jsonify({"ok": False, "msg": "未配置 MUSIC_DIR"}), 400
        if not library.index:
            library.scan()
        ql = q.lower()
        hits = []
        for tracks in library.index.values():
            for t in tracks:
                if ql in t["title"].lower() or ql in (t.get("album") or "").lower():
                    hits.append(norm_track(t))
        return jsonify({"ok": True, "items": hits, "total": len(hits)})

    servers = dm.all_servers()
    if not servers:
        return jsonify({"ok": False, "msg": "未发现媒体服务器"}), 404
    ms = servers[0]
    ok, items, total = ms.search(q)
    if ok:
        return jsonify({
            "ok": True,
            "items": [norm_track(i) for i in items if i["type"] == "item"],
            "total": total,
        })

    # Search 不被支持时，退化为遍历 All Music 做本地过滤
    log.warning(f"服务端搜索不可用({items})，退化为遍历过滤")
    ok2, all_items, _ = ms.browse("1$4", count=100000)
    if not ok2:
        return jsonify({"ok": False, "msg": str(items)}), 500
    ql = q.lower()
    hits = [norm_track(i) for i in all_items
            if i["type"] == "item" and ql in (i.get("title") or "").lower()]
    return jsonify({"ok": True, "items": hits, "total": len(hits), "fallback": True})


# ---------------------------------------------------------------- 在线播放（MusicFree 桥接）
@app.route("/api/online/plugins")
def api_online_plugins():
    try:
        with urllib.request.urlopen(BRIDGE_URL + "/plugins", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        return jsonify({"ok": True, "plugins": data})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 502


@app.route("/api/online/search")
def api_online_search():
    q = (request.args.get("q") or "").strip()
    page = int(request.args.get("page", "1"))
    provider = (request.args.get("provider") or "").strip()
    limit = int(request.args.get("limit", "0") or 0)
    if not q:
        return jsonify({"ok": False, "msg": "缺少关键字"}), 400
    url = (f"{BRIDGE_URL}/search?q={urllib.parse.quote(q)}&page={page}"
           + (f"&provider={urllib.parse.quote(provider)}" if provider else "")
           + (f"&limit={limit}" if limit > 0 else ""))
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        return jsonify({"ok": True, "items": data.get("items", []),
                        "isEnd": bool(data.get("isEnd", False))})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 502


@app.route("/api/online/add", methods=["POST"])
def api_online_add():
    data = request.get_json(force=True, silent=True) or {}
    items = data.get("items") or []
    if not items:
        return jsonify({"ok": False, "msg": "没有曲目"}), 400
    tracks = []
    for it in items:
        tracks.append({
            "source": "online",
            "provider": it.get("provider", ""),
            "oid": it.get("id", "") or it.get("oid", ""),
            "title": it.get("title", ""),
            "artist": it.get("artist", ""),
            "album": it.get("album", ""),
            "artwork": it.get("artwork", ""),
            "duration_sec": int(it.get("duration_sec") or it.get("duration") or 0),
        })
    total = player.queue_add(tracks)
    return jsonify({"ok": True, "total": total})


# ---------------------------------------------------------------- 路由：音乐目录源

@app.route("/api/music/rescan", methods=["POST"])
def api_music_rescan():
    """重新扫描当前音乐目录"""
    d = apply_active_source(rescan=False)
    if not d:
        return jsonify({"ok": False, "msg": "没有可用的音乐目录"}), 400
    library.set_root("")          # 强制清索引，保证下次请求触发重扫
    library.set_root(d)
    threading.Thread(target=library.scan, daemon=True).start()
    return jsonify({"ok": True, "msg": "已开始扫描", "dir": d})


@app.route("/api/music/sources")
def api_music_sources():
    """列出所有音乐目录源（含挂载/可读状态）"""
    try:
        return jsonify({
            "ok": True,
            "sources": sources.public(),
            "active": sources.active,
            "active_dir": sources.active_dir(),
            "nsenter": music_sources.nsenter_available(),
            "host_mount_root": music_sources.CONTAINER_MNT_ROOT,
        })
    except Exception as e:
        log.exception("音乐源列表失败")
        return jsonify({"ok": False, "msg": repr(e)}), 500


@app.route("/api/music/browse")
def api_music_browse():
    """目录浏览器：列出子目录（用于挑选本地路径，避免手输）"""
    requested = (request.args.get("path") or "").strip()
    base, root = music_sources.clamp_browse_path(requested)
    if not base:
        return jsonify({"ok": False, "msg": "没有可浏览的目录"}), 400
    dirs = []
    audio_here = 0
    try:
        with os.scandir(base) as it:
            for e in it:
                try:
                    if e.is_dir():
                        if e.name.startswith("."):
                            continue
                        dirs.append({"name": e.name, "path": e.path})
                    elif e.name.rsplit(".", 1)[-1].lower() in AUDIO_EXTS:
                        audio_here += 1
                except OSError:
                    pass
    except OSError as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    dirs.sort(key=lambda d: d["name"].lower())
    root_path = root["path"].rstrip("/")
    parent = os.path.dirname(base.rstrip("/")) or root_path
    if not (parent == root_path or parent.startswith(root_path + "/")):
        parent = root_path
    return jsonify({
        "ok": True, "path": base, "parent": parent,
        "root": root_path, "root_name": root["name"],
        "roots": music_sources.browse_roots(),
        "dirs": dirs, "audio_files": audio_here,
        "writable": os.access(base, os.W_OK),
    })


@app.route("/api/music/sources/add", methods=["POST"])
def api_music_source_add():
    data = request.get_json(force=True, silent=True) or {}
    src, err = sources.add(data)
    if not src:
        return jsonify({"ok": False, "msg": err}), 400
    msg = "已添加"
    if src["type"] == "smb" and src.get("auto_mount", True):
        threading.Thread(target=_mount_and_rescan, args=(src["id"],), daemon=True).start()
        msg = "已添加，正在挂载…"
    apply_active_source()
    return jsonify({"ok": True, "msg": msg, "source": sources.status(src)})


@app.route("/api/music/sources/remove", methods=["POST"])
def api_music_source_remove():
    data = request.get_json(force=True, silent=True) or {}
    ok, msg = sources.remove((data.get("id") or "").strip())
    apply_active_source()
    return jsonify({"ok": bool(ok), "msg": msg}), (200 if ok else 400)


@app.route("/api/music/sources/mount", methods=["POST"])
def api_music_source_mount():
    data = request.get_json(force=True, silent=True) or {}
    src = sources.get((data.get("id") or "").strip())
    if not src:
        return jsonify({"ok": False, "msg": "源不存在"}), 400
    if src.get("type") != "smb":
        return jsonify({"ok": True, "msg": "本地路径无需挂载"})
    ok, msg = music_sources.mount_smb(src)
    apply_active_source()
    return jsonify({"ok": bool(ok), "msg": msg, "source": sources.status(src)})


@app.route("/api/music/sources/unmount", methods=["POST"])
def api_music_source_unmount():
    data = request.get_json(force=True, silent=True) or {}
    src = sources.get((data.get("id") or "").strip())
    if not src:
        return jsonify({"ok": False, "msg": "源不存在"}), 400
    if src.get("type") != "smb":
        return jsonify({"ok": True, "msg": "本地路径无需卸载"})
    ok, msg = music_sources.umount_smb(src)
    apply_active_source()
    return jsonify({"ok": bool(ok), "msg": msg, "source": sources.status(src)})


@app.route("/api/music/sources/active", methods=["POST"])
def api_music_source_active():
    data = request.get_json(force=True, silent=True) or {}
    sid = (data.get("id") or "").strip()
    ok, msg = sources.set_active(sid)
    d = apply_active_source()
    return jsonify({"ok": bool(ok), "msg": msg, "active_dir": d,
                    "sources": sources.public()}), (200 if ok else 400)


@app.route("/api/music/sources/test", methods=["POST"])
def api_music_source_test():
    """测试 SMB 连接：临时挂载 -> 探测 -> 卸载"""
    data = request.get_json(force=True, silent=True) or {}
    host = (data.get("host") or "").strip()
    share = (data.get("share") or "").strip().strip("/")
    if not host or not share:
        return jsonify({"ok": False, "msg": "缺少主机或共享名"}), 400
    fake = {
        "id": "test" + music_sources._gen_id(3),
        "name": "test", "type": "smb", "host": host, "share": share,
        "subpath": (data.get("subpath") or "").strip().strip("/"),
        "user": (data.get("user") or "").strip(),
        "password": data.get("password") or "",
        "guest": bool(data.get("guest")),
    }
    ok, msg, probe = music_sources.test_smb(fake)
    return jsonify({"ok": bool(ok), "msg": msg, "probe": probe})


def _mount_and_rescan(sid):
    src = sources.get(sid)
    if not src or src.get("type") != "smb":
        return
    try:
        mount_smb_ok, msg = music_sources.mount_smb(src)
        log.info(f"后台挂载 {src.get('name')}: {msg}")
        apply_active_source()
    except Exception:
        log.exception("后台挂载失败")


@app.route("/api/online/download", methods=["POST"])
def api_online_download():
    """把在线曲目交给 bridge 的下载队列（立即返回，后台串行下载）。"""
    data = request.get_json(force=True, silent=True) or {}
    items = data.get("items") or []
    if not items:
        return jsonify({"ok": False, "msg": "没有曲目"}), 400
    sid = (data.get("source_id") or "").strip()
    src = sources.get(sid) if sid else None
    target = music_sources.container_path_of(src) if src else sources.active_dir()
    if not target:
        return jsonify({"ok": False,
                        "msg": "没有可用的音乐目录，请先在「音乐目录」里添加"}), 400
    if not (os.path.isdir(target) and os.access(target, os.W_OK)):
        return jsonify({"ok": False,
                        "msg": f"当前音乐目录不可写：{target}（SMB 共享请确认挂载参数允许写入）"}), 400
    body = json.dumps({"items": items, "target_dir": target}).encode("utf-8")
    req = urllib.request.Request(BRIDGE_URL + "/download", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.loads(r.read().decode("utf-8"))
        return jsonify(out)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 502


@app.route("/api/online/downloads")
def api_online_downloads():
    """查询下载队列状态。"""
    try:
        with urllib.request.urlopen(BRIDGE_URL + "/downloads", timeout=5) as r:
            out = json.loads(r.read().decode("utf-8"))
        return jsonify({"ok": True, "active": out.get("active"), "jobs": out.get("jobs", [])})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 502


@app.route("/api/online/downloads/clear", methods=["POST"])
def api_online_downloads_clear():
    """清掉已完成/失败的下载记录。"""
    req = urllib.request.Request(BRIDGE_URL + "/downloads/clear", data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            out = json.loads(r.read().decode("utf-8"))
        return jsonify(out)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 502


@app.route("/api/play", methods=["POST"])
def api_play():
    """
    播放曲目列表。
    body: { udns: [...], tracks: [{url,title,duration,artist,album}], index: 0 }
    若 udns 省略则使用当前已选目标。
    """
    data = request.get_json(force=True, silent=True) or {}
    tracks = data.get("tracks") or []
    index = int(data.get("index", 0))
    udns = data.get("udns")

    if not tracks:
        return jsonify({"ok": False, "msg": "没有曲目"}), 400
    if udns is not None:
        if isinstance(udns, str):
            udns = [udns]
        player.set_targets(udns)

    ok, res = player.play_tracks(tracks, index)
    return jsonify({"ok": bool(ok), "result": str(res) if not ok else "ok",
                    "detail": res if ok else None})


def _gather_dlna_tracks(ms, container, depth=0, max_depth=6):
    """递归收集某个容器下所有曲目（含子文件夹），用于"播放本目录全部" """
    if depth > max_depth:
        return []
    out = []
    ok, items, total = ms.browse(container, start=0, count=100000)
    if not ok:
        return out
    for it in items:
        if it.get("type") == "item":
            out.append(norm_track(it))
        elif it.get("type") == "container":
            out.extend(_gather_dlna_tracks(ms, it["id"], depth + 1, max_depth))
    return out


@app.route("/api/play-container", methods=["POST"])
def api_play_container():
    """
    播放整个目录/专辑：服务端拉取该容器下全部曲目并作为队列播放。
    这样无论用户怎么导航，都能保证"整张专辑/文件夹"被完整续播。
    body: { source, container, index }
    """
    data = request.get_json(force=True, silent=True) or {}
    container = data.get("container", "0")
    source = data.get("source", "dlna")
    index = int(data.get("index", 0))

    if source == "local":
        if not library.enabled():
            return jsonify({"ok": False, "msg": "未配置 MUSIC_DIR"}), 400
        if not library.index:
            library.scan()
        prefix = container.rstrip("/")
        tracks = []
        for d, ts in library.index.items():
            if not prefix or d == prefix or d.startswith(prefix + "/"):
                tracks.extend(norm_track(t) for t in ts)
    else:
        servers = dm.all_servers()
        if not servers:
            return jsonify({"ok": False, "msg": "未发现媒体服务器"}), 404
        ms = servers[0]
        tracks = _gather_dlna_tracks(ms, container)

    if not tracks:
        return jsonify({"ok": False, "msg": "该目录没有可播放的曲目"}), 404

    ok, res = player.play_tracks(tracks, index)
    return jsonify({"ok": bool(ok), "result": str(res) if not ok else "ok",
                    "detail": res if ok else None, "total": len(tracks)})


@app.route("/api/mode", methods=["POST"])
def api_mode():
    """设置循环/随机模式。body: { repeat: off|all|one, shuffle: true|false }"""
    data = request.get_json(force=True, silent=True) or {}
    rep = data.get("repeat")
    shf = data.get("shuffle")
    r, s = player.set_mode(repeat=rep, shuffle=shf)
    return jsonify({"ok": True, "repeat": r, "shuffle": s})


@app.route("/api/control", methods=["POST"])
def api_control():
    """传输控制: play / pause / stop / next / prev"""
    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "")
    udns = data.get("udns")
    ok, res = player.control(action, udns)
    return jsonify({"ok": bool(ok), "result": res})


@app.route("/api/volume", methods=["POST"])
def api_volume():
    data = request.get_json(force=True, silent=True) or {}
    vol = int(data.get("volume", 50))
    udns = data.get("udns")
    ok, res = player.set_volume(vol, udns)
    return jsonify({"ok": bool(ok), "result": res})


@app.route("/api/seek", methods=["POST"])
def api_seek():
    """跳转到指定秒数"""
    data = request.get_json(force=True, silent=True) or {}
    pos = int(data.get("position", 0))
    udns = data.get("udns")
    ok, res = player.seek(pos, udns)
    return jsonify({"ok": bool(ok), "result": res})


@app.route("/api/resync", methods=["POST"])
def api_resync():
    ok, res = player.resync()
    return jsonify({"ok": bool(ok), "result": str(res) if not ok else "ok"})


@app.route("/api/queue", methods=["POST", "DELETE"])
def api_queue():
    if request.method == "DELETE":
        player.queue_clear()
        return jsonify({"ok": True})
    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "add")
    if action == "add":
        tracks = data.get("tracks") or []
        if tracks:
            player.queue_add(tracks)
        return jsonify({"ok": True, "total": len(player.queue)})
    if action == "remove":
        idx = int(data.get("index", -1))
        ok, res = player.queue_remove(idx)
        return jsonify({"ok": bool(ok), "total": len(player.queue),
                        "msg": res if not ok else ""})
    if action == "clear":
        player.queue_clear()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "未知 action"}), 400


@app.route("/api/jump", methods=["POST"])
def api_jump():
    data = request.get_json(force=True, silent=True) or {}
    index = int(data.get("index", 0))
    ok, res = player.jump(index)
    return jsonify({"ok": bool(ok), "result": str(res) if not ok else "ok"})


@app.route("/api/library/rescan", methods=["POST"])
def api_library_rescan():
    if not library.enabled():
        return jsonify({"ok": False, "msg": "未配置 MUSIC_DIR"}), 400
    library.scan()
    return jsonify({"ok": True, "last_scan": library.last_scan,
                    "dirs": len(library.index)})


# ---------------------------------------------------------------- 启动

def main():
    # 应用 TZ 环境变量（容器内无 tzdata 时靠它生效，保证日志时间为本地时区）
    try:
        time.tzset()
    except Exception:
        pass

    log.info("=" * 60)
    log.info("DLNA 音响控制系统启动")
    log.info(f"  本地时间 : {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    log.info(f"  首选网段 : {PREFER_NET or '(自动)'}")
    log.info(f"  监听端口 : {HTTP_PORT}")
    log.info(f"  本机 IP  : {host_ip()}")
    log.info(f"  音乐目录源: {len(sources.sources)} 个（网页「音乐目录」可添加本地路径 / SMB）")
    log.info("=" * 60)

    # 首轮扫描（阻塞，确保启动即有设备列表）
    dm.refresh()

    # 音乐目录源：应用当前源（本地曲库），并后台自动挂载 SMB 源
    d = apply_active_source(rescan=False)
    log.info(f"  音乐目录 : {d or '(未配置，可在网页里添加)'}")
    if d:
        threading.Thread(target=library.scan, daemon=True).start()
    threading.Thread(target=sources.automount_all, daemon=True).start()

    # 后台：状态轮询（慢，供 UI）+ 预测式切歌调度（快，专职续播同步）
    threading.Thread(target=player.monitor_loop, daemon=True).start()
    threading.Thread(target=player.scheduler_loop, daemon=True).start()

    # 后台：周期性重扫设备
    def rescan_loop():
        while True:
            time.sleep(SCAN_INTERVAL)
            dm.refresh()

    threading.Thread(target=rescan_loop, daemon=True).start()

    app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
