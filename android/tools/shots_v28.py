# -*- coding: utf-8 -*-
"""v2.8 交付截图：正在播放(歌词同台+边听边下载) / 播放列表(模式chips) / 使用说明"""
import os, sys, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
WWW = os.path.abspath("app/assets/www/index.html")
OUT = "build/shots"
os.makedirs(OUT, exist_ok=True)

def shot(pg, name):
    pg.screenshot(path=os.path.join(OUT, name))
    print("saved", name)

with sync_playwright() as p:
    b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security",
                                "--no-sandbox", "--disable-gpu"])
    pg = b.new_context(viewport={"width": 400, "height": 940}, device_scale_factor=2).new_page()
    pg.goto("file:///" + WWW.replace("\\", "/"), wait_until="load")
    # 等启动引擎就绪
    for _ in range(40):
        if pg.evaluate("!!(S && S.state)"):
            break
        time.sleep(0.5)
    time.sleep(1)

    # 1) 正在播放：模拟播放中曲目 + 有歌词 → 歌词同台
    pg.evaluate("""async () => {
      S.out = 'phone';
      const lib = (S._libItems && S._libItems.length ? S._libItems : (await loadLib(), S._libItems)) || [];
      const t = lib[0] || { source: 'local', id: 'f:/x.mp3', title: '示例歌曲', artist: '示例歌手' };
      S.phone.queue = [t]; S.phone.idx = 0;
      switchTab('now');
      // 塞一份真实 LRC 走渲染链路
      S.lyric = { key: trackKeyOf(t), lines: parseLrc('[00:01.00]霓虹淹没的街口\\n[00:05.50]信号灯在雨里闪烁\\n[00:10.00]你的名字被删除前\\n[00:14.50]我最后一次听见\\n[00:19.00]副歌：把这首歌投给音响\\n[00:23.50]让整条街都听见'), idx: 2, msg: '' };
      renderLyric();
    }""")
    time.sleep(0.8)
    shot(pg, "v28-now-lyric.png")

    # 2) 同页滚动到边听边下载区域
    pg.evaluate("document.querySelector('.np-lrc') && window.scrollTo(0, 400)")
    pg.evaluate("""() => { const el = [...document.querySelectorAll('.sec-title')].find(e => e.textContent.indexOf('边听边下载') >= 0); if (el) el.scrollIntoView({block:'start'}); }""")
    time.sleep(0.4)
    shot(pg, "v28-adl.png")

    # 3) 播放列表：模式 chips
    pg.evaluate("""async () => {
      switchTab('queue');
      if (!(S.state && S.state.player && S.state.player.queue && S.state.player.queue.length)) {
        S.state = S.state || {}; S.state.player = S.state.player || {};
        S.state.player.queue = [{ title: '晴天', artist: '周杰伦' }, { title: '七里香', artist: '周杰伦' }, { title: '夜曲', artist: '周杰伦' }];
        S.state.player.index = 0;
      }
      renderQueue();
    }""")
    time.sleep(0.6)
    shot(pg, "v28-queue.png")

    # 4) 使用说明
    pg.evaluate("helpSheet()")
    time.sleep(0.6)
    shot(pg, "v28-help.png")

    b.close()
print("ALL SHOTS DONE")
