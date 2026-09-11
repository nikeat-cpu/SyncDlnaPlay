# -*- coding: utf-8 -*-
"""把「添加 SMB 共享」面板和曲库管理面板截下来，看清楚图标到底哪里不对。

用真实前端 + 真实桌面后端（LiveServer :8765）渲染，不是凭空想象。
"""
import os
import sys
import json
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
WWW = os.path.join(PROJ, "app", "assets", "www")
OUT = os.path.join(PROJ, "build", "shots")


def main():
    e2e = os.path.join(WWW, "_e2e.html")
    if not os.path.exists(e2e):
        print("缺少 _e2e.html，请先跑 tools/make_e2e_page.py")
        return 1
    os.makedirs(OUT, exist_ok=True)
    url = "file:///" + e2e.replace("\\", "/")
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security",
                                    "--no-sandbox", "--disable-gpu"])
        pg = b.new_context(viewport={"width": 400, "height": 900},
                           device_scale_factor=2).new_page()
        pg.goto(url, wait_until="load", timeout=60000)
        pg.wait_for_function("() => window.__e2eDone === true", timeout=180000)
        pg.evaluate("() => { var e=document.getElementById('e2e-out'); if(e) e.style.display='none'; }")
        pg.wait_for_timeout(400)

        for name, js in [("before-smb", "() => { closeSheet(); srcAdd('smb'); }"),
                         ("before-sources", "() => { closeSheet(); musicSourcesSheet(); }")]:
            pg.evaluate(js)
            pg.wait_for_timeout(700)
            path = os.path.join(OUT, name + ".png")
            pg.screenshot(path=path)
            print("截图", name, "->", path)

        info = pg.evaluate("""() => {
            srcAdd('smb');
            var b = document.getElementById('sheetBody');
            return {
              bodyText: (b.innerText || '').slice(0, 400),
              html: b.innerHTML.slice(0, 1400)
            };
        }""")
        print(json.dumps(info, ensure_ascii=False, indent=1)[:2200])
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
