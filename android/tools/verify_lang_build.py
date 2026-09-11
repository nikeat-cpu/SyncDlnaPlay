#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证语言变体 APK 的「默认语言」行为。

思路：把 assets/www 复制两份（一份原样、一份按 BUILD_LANG 打补丁），
用一个临时静态服务器同时伺服，再开**locale=zh-CN** 的无头 Chromium 分别加载。
如果补丁生效，中文环境下也应该得到 I18N.lang == "en"；原版则应为 "zh"。

用法：
    python tools/verify_lang_build.py            # 默认验证 en
    python tools/verify_lang_build.py zh

需要：playwright（envs/default 里已装）。
注意：必须带 NO_PROXY=127.0.0.1,localhost，否则本机 Clash 代理会把 127.0.0.1 劫持成 502。
"""

import functools
import http.server
import os
import shutil
import socketserver
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.abspath(os.path.join(HERE, "..", "app", "assets", "www"))
PORT = 8799
OLD = 'return /^zh/i.test(l) ? "zh" : "en";'
NEW = 'return "%s"; /* BUILD_LANG=%s: 默认%s启动 */'


def probe(browser, url, label):
    # 关键：模拟中文手机（locale=zh-CN），这样「原版跟随系统语言」才表现为 zh
    ctx = browser.new_context(locale="zh-CN", viewport={"width": 390, "height": 844})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url, wait_until="load")
    pg.wait_for_timeout(700)
    out = pg.evaluate("""() => ({
        lang: (window.I18N && I18N.lang) || null,
        docLang: document.documentElement.getAttribute('lang'),
        sample: (window.I18N && I18N.t) ? I18N.t('我的设备') : null,
        localStorage: (() => { try { return localStorage.getItem('dlna_lang'); } catch (e) { return 'ERR'; } })()
    })""")
    ctx.close()
    print("  %-28s I18N.lang=%-4s  html[lang]=%-6s  t('我的设备')=%-14s  localStorage=%s"
          % (label, out["lang"], out["docLang"], out["sample"], out["localStorage"]))
    if errs:
        print("      !! 页面报错：%s" % errs[:2])
    return out


def main():
    lang = (sys.argv[1] if len(sys.argv) > 1 else "en").lower()
    if lang not in ("en", "zh"):
        sys.exit("语言只支持 en / zh")

    src = open(os.path.join(WWW, "i18n.js"), encoding="utf-8").read()
    if src.count(OLD) != 1:
        sys.exit("源 i18n.js 里默认语言那行匹配 %d 次（应为 1），可能已被改动" % src.count(OLD))

    root = tempfile.mkdtemp(prefix="langcheck_")
    try:
        for name, patch in (("orig", False), (lang, True)):
            dst = os.path.join(root, name)
            shutil.copytree(WWW, dst)
            if patch:
                p = os.path.join(dst, "i18n.js")
                s = open(p, encoding="utf-8").read().replace(OLD, NEW % (lang, lang, lang))
                open(p, "w", encoding="utf-8", newline="\n").write(s)

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a, **k):     # 关掉逐请求日志，只留结论
                pass

        handler = functools.partial(Quiet, directory=root)
        httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        from playwright.sync_api import sync_playwright
        print("  模拟环境：无头 Chromium，locale = zh-CN（中文手机）")
        print("  服务器  ：http://127.0.0.1:%d/  （orig = 原版，%s = 打过补丁）" % (PORT, lang))
        print()
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            a = probe(b, "http://127.0.0.1:%d/orig/" % PORT, "原版（跟随系统语言）")
            c = probe(b, "http://127.0.0.1:%d/%s/" % (PORT, lang), "补丁版（BUILD_LANG=%s）" % lang)
            b.close()

        print()
        expect_orig = "zh"          # 中文环境下原版应当选中文
        expect_new = lang           # 补丁版应当固定为变体语言
        ok = (a["lang"] == expect_orig and c["lang"] == expect_new)
        print("  判定：原版应为 %s（实际 %s）／ 补丁版应为 %s（实际 %s） → %s"
              % (expect_orig, a["lang"], expect_new, c["lang"], "通过 ✓" if ok else "不通过 ✗"))
        return 0 if ok else 1
    finally:
        shutil.rmtree(root, ignore_errors=True)
        try:
            httpd.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
