# -*- coding: utf-8 -*-
"""录制宣传视频用的两段真实 UI 演示（playwright record_video）。

A 段（设备）：扫描中 → 三台设备逐台出现 → 点选第三台 → 顶部出现已选数 → 投放（切正在播放）
B 段（音源/歌词）：在线搜索结果 → 点歌 → 正在播放歌词逐行滚动 → 双击进沉浸歌词
复用 shots_readme.py 的 PREP 演示数据（冻结轮询、注入演示设备/曲库）。
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from harvest_i18n import WWW, ROOT  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = os.path.abspath(os.path.join(ROOT, "..", "..", "promo_shots"))
os.makedirs(OUT, exist_ok=True)

LYRIC = ("[00:00.00]霓虹淹没的街口\\n"
         "[00:04.50]信号灯在雨里闪烁\\n"
         "[00:09.00]你的名字被删除前\\n"
         "[00:13.50]我最后一次听见\\n"
         "[00:18.00]把这首歌投给音响\\n"
         "[00:22.50]让整条街都听见\\n"
         "[00:27.00]SyncDlnaPlay · 独立运行版")

PREP = """
() => {
  try { clearInterval(S.poll); } catch (e) { }
  try { clearInterval(S.lyrTimer); } catch (e) { }
  S.state = S.state || {};
  S.state.devices = [];
  S.state.scanning = true;
  S.state.player = { queue: [], index: 0, state: 'STOPPED', playing: false,
    position_sec: 0, duration_sec: 214 };
  S.queue = []; S.playing = false;
  S.out = 'dlna';
  S._libItems = [];
  S.online = S.online || {};
  S.online.page = 1; S.online.isEnd = false; S.online.provider = '元力WY';
  S.online.plugins = [
    { platform:'元力WY', name:'yuanli-wy', enabled:true, builtin:true },
    { platform:'元力KG', name:'yuanli-kg', enabled:true, builtin:true },
    { platform:'元力KW', name:'yuanli-kw', enabled:true, builtin:true }
  ];
  S.online.items = [
    { id:'o1', title:'Neon Rain', artist:'Aurora Wave', album:'Night Drive', duration_sec:214 },
    { id:'o2', title:'Signal Lost', artist:'Aurora Wave', album:'Night Drive', duration_sec:198 },
    { id:'o3', title:'Deleted', artist:'Kite', album:'Ghost', duration_sec:232 },
    { id:'o4', title:'Midnight Drive', artist:'Kite', album:'Ghost', duration_sec:186 },
    { id:'o5', title:'Ghost Wire', artist:'Nova', album:'Static', duration_sec:205 }
  ];
  window.__dev = function (udn, name, sel) {
    return { udn:udn, friendly_name:name, name:name, selected:!!sel, online:true,
             state:'STOPPED', volume:40 };
  };
  window.__playingDev = function () {
    S.state.devices.forEach(function (d) { if (d.selected) d.state = 'PLAYING'; });
  };
  window.__setLyricIdx = function (i) {
    S.lyric = { key: 'k', idx: i, msg: '', lines: parseLrc('%s') };
    renderLyric();
  };
  window.__lyricTick = function () {
    var i = 0;
    S._lyrInt && clearInterval(S._lyrInt);
    S._lyrInt = setInterval(function () {
      i = Math.min(i + 1, 6);
      try { __setLyricIdx(i); } catch (e) { }
    }, 1400);
  };
}
""" % LYRIC

SET_LYRIC = "() => __setLyricIdx(0)"


def new_ctx(b, rec_dir):
    # dsf=1 且不设 record_video_size：视频尺寸=视口尺寸，画面铺满无灰边
    ctx = b.new_context(viewport={"width": 390, "height": 844},
                        device_scale_factor=1,
                        record_video_dir=rec_dir)
    ctx.add_init_script("try{localStorage.setItem('dlna_lang','zh')}catch(e){}")
    return ctx


def wait_ready(pg):
    # 走真 LiveServer（127.0.0.1:8765），boot 握手才能成功、启动页才会揭开
    pg.goto("http://127.0.0.1:8765/", wait_until="load", timeout=60000)
    for _ in range(60):
        try:
            if pg.evaluate("!!(S && S.state)"):
                break
        except Exception:
            pass
        pg.wait_for_timeout(300)
    pg.wait_for_timeout(1200)


def seg_devices(pg):
    """扫描 → 设备逐台出现 → 多选 → 投放。"""
    pg.evaluate(PREP)
    pg.evaluate("() => { switchTab('devices'); renderDevices(); renderTopDev(); }")
    pg.wait_for_timeout(1500)
    # 三台设备逐台出现
    for i, js in enumerate([
        "S.state.devices.push(__dev('uuid:a','客厅 Living Room',true)); renderDevices(); renderTopDev();",
        "S.state.devices.push(__dev('uuid:b','卧室 Bedroom',true)); renderDevices(); renderTopDev();",
        "S.state.devices.push(__dev('uuid:c','书房 Study',false)); renderDevices(); renderTopDev();",
    ]):
        pg.evaluate(js)
        pg.wait_for_timeout(900)
    pg.evaluate("S.state.scanning = false; renderDevices(); renderTopDev();")
    pg.wait_for_timeout(700)
    # 点选书房
    pg.evaluate("var d=S.state.devices[2]; d.selected=!d.selected; renderDevices(); renderTopDev();")
    pg.wait_for_timeout(900)
    # 投放：全部 PLAYING + 切正在播放
    pg.evaluate("""() => {
      S.state.scanning = false;
      S.state.player = { queue:[
        { title:'Neon Rain', artist:'Aurora Wave', album:'Night Drive', duration_sec:214 }],
        index:0, state:'PLAYING', playing:true, position_sec:0, duration_sec:214,
        current:{ title:'Neon Rain', artist:'Aurora Wave', album:'Night Drive', duration_sec:214 } };
      S.queue = S.state.player.queue.slice(); S.idx = 0; S.playing = true;
      __playingDev(); renderDevices(); renderTopDev();
      switchTab('now'); renderNowTab(); refreshNow();
    }""")
    pg.evaluate(SET_LYRIC)
    pg.wait_for_timeout(1600)


def seg_online(pg):
    """在线搜索 → 点歌 → 歌词滚动 → 沉浸歌词。"""
    pg.evaluate(PREP)
    pg.evaluate("() => { switchTab('online'); renderOnline(); }")
    pg.wait_for_timeout(1500)
    pg.evaluate("() => { S.online.items.unshift({ id:'o0', title:'Neon Rain', artist:'Aurora Wave', album:'Night Drive', duration_sec:214 }); renderOnline(); }")
    pg.wait_for_timeout(900)
    # 点第一首 → 正在播放
    pg.evaluate("""() => {
      S.state.player = { queue:[
        { title:'Neon Rain', artist:'Aurora Wave', album:'Night Drive', duration_sec:214 },
        { title:'Signal Lost', artist:'Aurora Wave', album:'Night Drive', duration_sec:198 }],
        index:0, state:'PLAYING', playing:true, position_sec:0, duration_sec:214,
        current:{ title:'Neon Rain', artist:'Aurora Wave', album:'Night Drive', duration_sec:214 } };
      S.queue = S.state.player.queue.slice(); S.idx = 0; S.playing = true;
      switchTab('now'); renderNowTab(); refreshNow(); __setLyricIdx(0); __lyricTick();
    }""")
    pg.wait_for_timeout(3200)
    # 双击 → 沉浸歌词
    pg.evaluate("() => { try{clearInterval(S._lyrInt);}catch(e){} enterImmersive(); __setLyricIdx(2); __lyricTick(); }")
    pg.wait_for_timeout(4600)


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files",
                                    "--disable-web-security", "--no-sandbox",
                                    "--disable-gpu"])
        for name, fn in (("ui-devices", seg_devices), ("ui-online", seg_online)):
            ctx = new_ctx(b, OUT)
            pg = ctx.new_page()
            wait_ready(pg)
            try:
                fn(pg)
            except Exception as e:
                print("  [warn]", name, str(e)[:200])
            path = pg.video.path()
            ctx.close()
            dst = os.path.join(OUT, name + ".webm")
            os.replace(path, dst)
            print("  saved", dst)
        b.close()
    print("OUT:", OUT)


main()
