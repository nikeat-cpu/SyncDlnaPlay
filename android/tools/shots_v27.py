# -*- coding: utf-8 -*-
"""v2.7 交付截图：启动页（新名）/ 正在播放底栏大项 / 音源管理（默认星标）/ 按钮立体特写。

需要先启动 LiveServer :8765（build.sh 会清掉编译产物，记得先重新 javac）。
"""
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
WWW = os.path.join(PROJ, "app", "assets", "www")
OUT = os.path.join(PROJ, "build", "shots")


def main():
    os.makedirs(OUT, exist_ok=True)
    url = "file:///" + os.path.join(WWW, "index.html").replace("\\", "/")
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security",
                                    "--no-sandbox", "--disable-gpu"])
        ctx = b.new_context(viewport={"width": 400, "height": 900}, device_scale_factor=2)
        pg = ctx.new_page()

        # 1) 启动页：屏蔽后端让启动动画停留
        pg.route("**://127.0.0.1:8765/**", lambda r: r.abort())
        pg.goto(url, wait_until="load")
        pg.wait_for_timeout(1200)
        pg.screenshot(path=os.path.join(OUT, "v27-splash.png"))
        print("截图 v27-splash")
        pg.unroute("**://127.0.0.1:8765/**")

        # 重新加载，连真后端进主界面
        pg.goto(url, wait_until="load")
        pg.wait_for_function("() => document.getElementById('app') && document.getElementById('app').style.display !== 'none'", timeout=30000)
        pg.wait_for_timeout(800)

        # 2) 正在播放大项
        pg.evaluate("() => switchTab('now')")
        pg.wait_for_timeout(900)
        pg.screenshot(path=os.path.join(OUT, "v27-now-tab.png"))
        print("截图 v27-now-tab")

        # 3) 音源管理（默认星标）
        pg.evaluate("() => srcMgrSheet()")
        pg.wait_for_timeout(1200)
        pg.screenshot(path=os.path.join(OUT, "v27-srcmgr.png"))
        print("截图 v27-srcmgr")
        pg.evaluate("() => closeSheet()")

        # 4) 按钮立体特写（音量面板里的 ± 键与主按钮）
        pg.evaluate("() => volumeSheet()")
        pg.wait_for_timeout(700)
        pg.screenshot(path=os.path.join(OUT, "v27-buttons.png"))
        print("截图 v27-buttons")

        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
