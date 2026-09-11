# -*- coding: utf-8 -*-
"""v2.9 截图：瘦身后的正在播放页（歌词校准行 + 无重复控制键）"""
import os, time
from playwright.sync_api import sync_playwright

WWW = os.path.abspath("app/assets/www/index.html")
LRC = "[00:01.00]霓虹淹没的街口\\n[00:05.50]信号灯在雨里闪烁\\n[00:10.00]你的名字被删除前\\n[00:14.50]我最后一次听见\\n[00:19.00]副歌：把这首歌投给音响\\n[00:23.50]让整条街都听见"

JS = """
async () => {
  S.out = 'phone';
  const lib = (S._libItems && S._libItems.length ? S._libItems : (await loadLib(), S._libItems)) || [];
  const t = lib[0] || { source: 'local', id: 'f:/x.mp3', title: '示例歌曲', artist: '示例歌手' };
  S.phone.queue = [t]; S.phone.idx = 0;
  S.lyricOff = 1500;
  switchTab('now');
  S.lyric = { key: trackKeyOf(t), lines: parseLrc('%s'), idx: 2, msg: '' };
  renderLyric();
}
""" % LRC

with sync_playwright() as p:
    b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security",
                                "--no-sandbox", "--disable-gpu"])
    pg = b.new_context(viewport={"width": 400, "height": 940}, device_scale_factor=2).new_page()
    pg.goto("file:///" + WWW.replace("\\", "/"), wait_until="load")
    for _ in range(40):
        if pg.evaluate("!!(S && S.state)"):
            break
        time.sleep(0.5)
    time.sleep(1)
    pg.evaluate(JS)
    time.sleep(0.8)
    pg.screenshot(path="build/shots/v29-now.png")
    print("saved v29-now.png")
    b.close()
