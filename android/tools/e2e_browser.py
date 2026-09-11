#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
用无头 Chromium 当 WebView，跑 app/assets/www/_e2e.html 做端到端验证。
前置：LiveServer 已在 127.0.0.1:8765 跑起来（javatest/LiveServer.java）。

用法：
    python tools/e2e_browser.py
"""
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, ".."))
PAGE = os.path.join(PROJ, "app", "assets", "www", "_e2e.html")
SHOT = os.path.join(PROJ, "build", "e2e-browser.png")

from playwright.sync_api import sync_playwright  # noqa: E402


def main():
    if not os.path.isfile(PAGE):
        print("缺少测试页，请先运行 tools/make_e2e_page.py")
        return 2

    url = "file:///" + PAGE.replace("\\", "/")
    logs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--allow-file-access-from-files",
                "--disable-web-security",
                "--no-sandbox",
                "--disable-gpu",
            ],
        )
        ctx = browser.new_context(viewport={"width": 420, "height": 900})
        page = ctx.new_page()
        page.on("console", lambda m: logs.append("[%s] %s" % (m.type, m.text)))
        page.on("pageerror", lambda e: logs.append("[pageerror] %s" % e))

        page.goto(url, wait_until="load", timeout=60000)
        try:
            page.wait_for_function("() => window.__e2eDone === true", timeout=120000)
        except Exception as e:
            print("等待测试完成超时:", e)

        title = page.title()
        try:
            raw = page.eval_on_selector("#e2e-out", "el => el.textContent")
        except Exception:
            raw = ""
        try:
            page.screenshot(path=SHOT, full_page=True)
        except Exception:
            pass
        browser.close()

    print("页面标题:", title)
    print("截图:", SHOT)
    print("-" * 68)
    m = re.search(r"E2E_RESULT=(\[.*\])", raw or "", re.S)
    if not m:
        print("没有拿到测试结果。页面 console 日志：")
        for l in logs[-30:]:
            print("  ", l)
        return 1

    steps = json.loads(m.group(1))
    ok = 0
    for s in steps:
        mark = "PASS" if s["ok"] else "FAIL"
        if s["ok"]:
            ok += 1
        print("  [%s] %-22s %s" % (mark, s["name"], s["detail"]))
    print("-" * 68)
    print("通过 %d/%d" % (ok, len(steps)))

    fails = [l for l in logs if "error" in l.lower() and "native-toast" not in l]
    if fails:
        print("\n浏览器错误日志:")
        for l in fails[:12]:
            print("  ", l)
    return 0 if ok == len(steps) and steps else 1


if __name__ == "__main__":
    sys.exit(main())
