# -*- coding: utf-8 -*-
"""v2.5 交付截图：SMB 面板（含真实局域网扫描 + 浏览共享）与音源管理面板。

用真实前端 + 真实桌面后端 :8765 渲染，扫描是真的去扫局域网。
"""
import os
import sys
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
WWW = os.path.join(PROJ, "app", "assets", "www")
OUT = os.path.join(PROJ, "build", "shots")


def check_server():
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=5) as r:
            r.read(64)
        return True
    except Exception as e:
        print("本机服务不可达（%s），请先启动 LiveServer" % e)
        return False


def main():
    e2e = os.path.join(WWW, "_e2e.html")
    if not os.path.exists(e2e):
        print("缺少 _e2e.html，请先跑 tools/make_e2e_page.py")
        return 1
    if not check_server():
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

        # 1) SMB 面板初始状态
        pg.evaluate("() => { closeSheet(); srcAdd('smb'); }")
        pg.wait_for_timeout(600)
        pg.screenshot(path=os.path.join(OUT, "v25-smb-empty.png"))
        print("截图 v25-smb-empty")

        # 2) 真扫描局域网
        pg.evaluate("() => smbScan()")
        pg.wait_for_timeout(9000)
        pg.screenshot(path=os.path.join(OUT, "v25-smb-scan.png"))
        print("截图 v25-smb-scan")
        print(pg.evaluate("() => document.getElementById('smbBox').innerText.slice(0,300)"))

        # 3) 点进一个共享看目录（用扫描结果里的第一台有共享的机器）
        pg.evaluate("""() => {
            var items = document.querySelectorAll('#smbBox .chip');
            for (var i = 0; i < items.length; i++) {
                var t = items[i].innerText.trim();
                if (t && t !== 'IPC$') { items[i].click(); return t; }
            }
            return '(没有共享可点)';
        }""")
        pg.wait_for_timeout(3500)
        pg.screenshot(path=os.path.join(OUT, "v25-smb-browse.png"))
        print("截图 v25-smb-browse")
        print(pg.evaluate("() => document.getElementById('smbBox').innerText.slice(0,300)"))

        # 4) 音源管理
        pg.evaluate("() => { closeSheet(); srcMgrSheet(); }")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=os.path.join(OUT, "v25-srcmgr.png"))
        print("截图 v25-srcmgr")

        # 5) 添加音源面板
        pg.evaluate("() => srcInstallSheet()")
        pg.wait_for_timeout(700)
        pg.screenshot(path=os.path.join(OUT, "v25-srcinstall.png"))
        print("截图 v25-srcinstall")

        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
