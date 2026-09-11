#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
界面巡览（面板级）：启动页 + 播放器面板 + 音量面板 + 曲库管理面板。
=================================================================
e2e_shots.py 只截四个 Tab，但「播放器 UI」的核心其实在底部弹出面板里，
所以单独补一套截图，用于人工确认赛博朋克改造效果。

踩过的坑（别改回去）：
  1. 启动页不能用 page.set_content() —— 那样基准 URL 是 about:blank，
     <link href="app.css"> 相对路径解析失败，页面会变成白底无样式的裸 HTML。
     必须落一个临时文件到 www 下用 file:// 打开。
  2. 面板截图不要在一次 evaluate 里先 switchTab 再开面板 —— 会截到重渲染的
     中间态（曾出现圆盘整块缺失）。统一用「导航一次 -> 每个面板 evaluate
     一次 -> 立刻截图」的流程，与 tools/probe_ui.py 保持一致。

前置：build/classes 已构建；_e2e.html 已生成；LiveServer 在 127.0.0.1:8765。
用法：python tools/shots_sheets.py
"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, ".."))
WWW = os.path.join(PROJ, "app", "assets", "www")
OUT = os.path.join(PROJ, "build", "shots")

from playwright.sync_api import sync_playwright  # noqa: E402

# (标签, 页面内 JS；None 表示启动页)
SHEETS = [
    ("volume", "(()=>{var d=S.state.devices[0];d.selected=true;d.volume=45;S.out='dlna';volumeSheet();})()"),
    ("sources", "musicSourcesSheet()"),
    ("dlstatus", "dlStatus()"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    e2e = os.path.join(WWW, "_e2e.html")
    if not os.path.exists(e2e):
        print("缺少 _e2e.html，请先跑 bash tools/run_e2e.sh")
        return 1

    # 前置：桌面服务必须活着。否则 S.state 为 null，面板会静默截成空壳
    # （曾因 LiveServer 已退出而截出「无数据」的界面图，却没有任何报错）。
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=5) as r:
            st = json.loads(r.read().decode("utf-8"))
        print("桌面服务在线，设备 %d 台" % len(st.get("devices") or []))
    except Exception as e:
        print("桌面服务不可达（http://127.0.0.1:8765）：%s" % e)
        print("请先启动 LiveServer 再截图，例如：")
        print('  JDK="D:/android-toolchain/jdk17"')
        print('  "$JDK/bin/java.exe" -cp "build/classes;build/livetest;libs/*" LiveServer &')
        return 1

    # 启动页：落临时文件，保证 app.css 相对路径能解析
    splash = os.path.join(WWW, "_splash.html")
    html = open(os.path.join(WWW, "index.html"), encoding="utf-8").read()
    open(splash, "w", encoding="utf-8", newline="").write(
        re.sub(r"<script[^>]*></script>", "", html))

    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--allow-file-access-from-files", "--disable-web-security",
                  "--no-sandbox", "--disable-gpu"])
        ctx = browser.new_context(viewport={"width": 400, "height": 820},
                                  device_scale_factor=2)

        # ---- 启动页 ----
        try:
            pg = ctx.new_page()
            pg.goto("file:///" + splash.replace("\\", "/"), wait_until="load", timeout=60000)
            pg.wait_for_timeout(800)
            path = os.path.join(OUT, "sheet-splash.png")
            pg.screenshot(path=path)
            shots.append(("启动页", path))
            print("截图 启动页   ->", path)
            pg.close()
        except Exception as e:
            print("启动页截图失败:", e)

        # ---- 各面板 ----
        pg = ctx.new_page()
        pg.goto("file:///" + e2e.replace("\\", "/"), wait_until="load", timeout=60000)
        pg.wait_for_function("() => window.__e2eDone === true", timeout=120000)
        pg.evaluate("() => { var e=document.getElementById('e2e-out'); if(e) e.style.display='none'; }")
        pg.evaluate("() => { var t=document.getElementById('toast'); if(t) t.className='toast'; }")

        # 播放器面板：与 probe_ui.py 相同的顺序，先渲染再截图
        try:
            pg.evaluate("() => playerSheet()")
            pg.wait_for_timeout(1500)
            path = os.path.join(OUT, "sheet-player.png")
            pg.screenshot(path=path)
            shots.append(("播放器", path))
            print("截图 播放器   ->", path)
            # 再截一张滚到底部的（播放模式 chips + 歌词下半）
            pg.evaluate("() => { var b=document.getElementById('sheetBody'); if(b) b.scrollTop=b.scrollHeight; }")
            pg.wait_for_timeout(500)
            path = os.path.join(OUT, "sheet-player2.png")
            pg.screenshot(path=path)
            shots.append(("播放器下半", path))
            print("截图 播放器下半 ->", path)
            pg.evaluate("() => closeSheet()")
            pg.wait_for_timeout(300)
        except Exception as e:
            print("播放器面板截图失败:", e)

        for label, js in SHEETS:
            try:
                pg.evaluate("() => closeSheet()")
                pg.wait_for_timeout(200)
                pg.evaluate("() => { %s }" % js)
                pg.wait_for_timeout(700)
                path = os.path.join(OUT, "sheet-%s.png" % label)
                pg.screenshot(path=path)
                shots.append((label, path))
                print("截图 %-8s -> %s" % (label, path))
            except Exception as e:
                print("面板 %s 截图失败: %s" % (label, e))
        pg.close()
        browser.close()

    try:
        os.remove(splash)
    except OSError:
        pass
    print("共 %d 张" % len(shots))
    return 0 if shots else 1


if __name__ == "__main__":
    sys.exit(main())
