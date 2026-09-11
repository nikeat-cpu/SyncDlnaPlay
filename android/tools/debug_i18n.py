# -*- coding: utf-8 -*-
"""i18n 调试：检查词典命中与页面控制台报错。"""
import os, time, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harvest_i18n import WWW  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

PROBE = ["音量", "选择音响", "已停止", "播放中", "更多设置", "返回列表", "同步校准", "中文",
         "3 台设备", "第 2 页 · 1 首", "正在播放", "设置", "关闭"]

with sync_playwright() as p:
    b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security",
                                "--no-sandbox", "--disable-gpu"])
    ctx = b.new_context(viewport={"width": 400, "height": 900})
    ctx.add_init_script("try{localStorage.setItem('dlna_lang','en')}catch(e){}")
    pg = ctx.new_page()
    pg.on("console", lambda m: print("  [console:%s] %s" % (m.type, m.text[:200])))
    pg.on("pageerror", lambda e: print("  [pageerror] %s" % str(e)[:300]))
    pg.goto("file:///" + WWW.replace("\\", "/"), wait_until="load")
    for _ in range(30):
        try:
            if pg.evaluate("!!(S && S.state)"):
                break
        except Exception:
            pass
        time.sleep(0.4)
    time.sleep(1)
    res = pg.evaluate("""(probe) => {
        const out = {};
        out.hasI18N = !!window.I18N;
        out.lang = window.I18N && I18N.lang;
        out.n = {};
        probe.forEach(s => { try { out.n[s] = I18N.t(s); } catch (e) { out.n[s] = 'THROW:' + e.message; } });
        /* 直接看 renderTopDev 那个节点 */
        const td = document.getElementById('topDev');
        out.topDev = td ? td.textContent : null;
        const sheetTitle = document.getElementById('sheetTitle');
        out.sheetTitle = sheetTitle ? sheetTitle.textContent : null;
        return out;
    }""", PROBE)
    print("hasI18N:", res["hasI18N"], "lang:", res["lang"])
    for k, v in res["n"].items():
        print("   t(%-12s) = %s" % (k, v))
    print("topDev节点:", res["topDev"])
    print("sheetTitle节点:", res["sheetTitle"])
    b.close()
