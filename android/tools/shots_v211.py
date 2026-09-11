# -*- coding: utf-8 -*-
"""v2.11 沉浸歌词模式截图：进沉浸 → 截全屏效果。"""
import os, time
from playwright.sync_api import sync_playwright

WWW = os.path.abspath("app/assets/www/index.html")
OUT = "build/shots"
os.makedirs(OUT, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security",
                                "--no-sandbox", "--disable-gpu"])
    pg = b.new_context(viewport={"width": 400, "height": 860}, device_scale_factor=2).new_page()
    pg.goto("file:///" + WWW.replace("\\", "/"), wait_until="load")
    for _ in range(40):
        try:
            if pg.evaluate("!!(S && S.state)"):
                break
        except Exception:
            pass
        time.sleep(0.5)
    time.sleep(1)
    pg.evaluate("""() => {
      S.out = 'phone';
      S.phone.queue = [{ source: 'local', id: 'f:/x.mp3', title: '时间它太匆匆', artist: '戴佩妮' }];
      S.phone.idx = 0;
      S.lyric = { key: 'k', idx: 3, msg: '', lines: [
        { t: 2,  text: '可以决定我的去留' },
        { t: 6,  text: '为了什么牵拖那么久' },
        { t: 10, text: '时间它太匆匆' },
        { t: 14, text: '不喜欢犹豫的穿梭' },
        { t: 18, text: '关系太难题摸' },
        { t: 22, text: '带走我' },
        { t: 26, text: '去宇宙的尽头' },
        { t: 30, text: '把这首歌投给音响' },
        { t: 34, text: '让整条街都听见' }
      ] };
      switchTab('now');
      renderLyric();
      enterImmersive();
      const box = document.getElementById('immLrc');
      if (box) box.scrollTop = 0;
    }""")
    time.sleep(1.2)
    pg.screenshot(path=OUT + "/v211-immersive.png")
    print("saved v211-immersive.png")
    b.close()
