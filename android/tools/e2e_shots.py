#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
UI 巡览截图：把 _e2e.html 当 WebView，逐个 Tab 截图，用于人工确认界面没崩。
前置：LiveServer 在 127.0.0.1:8765 运行；_e2e.html 已生成。

用法： python tools/e2e_shots.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, ".."))
PAGE = os.path.join(PROJ, "app", "assets", "www", "_e2e.html")
OUT = os.path.join(PROJ, "build", "shots")

from playwright.sync_api import sync_playwright  # noqa: E402

TABS = [
    ("devices", "device", "设备"),
    ("lib", "lib", "曲库"),
    ("online", "online", "在线"),
    ("queue", "queue", "列表"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    url = "file:///" + PAGE.replace("\\", "/")
    shots = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--allow-file-access-from-files", "--disable-web-security",
                  "--no-sandbox", "--disable-gpu"],
        )
        ctx = browser.new_context(viewport={"width": 400, "height": 820},
                                  device_scale_factor=2)
        page = ctx.new_page()
        page.goto(url, wait_until="load", timeout=60000)
        page.wait_for_function("() => window.__e2eDone === true", timeout=120000)
        page.evaluate("() => { var e = document.getElementById('e2e-out'); if (e) e.style.display = 'none'; }")
        page.evaluate("() => { var t = document.getElementById('toast'); if (t) t.className = 'toast'; }")

        for key, fname, label in TABS:
            try:
                page.evaluate("k => switchTab(k, true)", key)
                page.wait_for_timeout(900)
                path = os.path.join(OUT, "%s.png" % fname)
                page.screenshot(path=path)
                shots.append((label, path))
                print("截图 %s -> %s" % (label, path))
            except Exception as e:
                print("Tab %s 截图失败: %s" % (label, e))

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
