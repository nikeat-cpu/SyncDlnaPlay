#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
音响管家 · 赛博朋克图标生成器
==============================
设计：「切角八边形 + 五柱频谱」，青(#22e6ff) → 紫(#a071ff) → 品红(#ff2d92) 渐变。
标志几何与 app/assets/www/index.html 里启动页的内联 SVG 同源。

为什么要自适应图标（adaptive icon）
-----------------------------------
minSdk = 26，意味着所有设备都是 Android 8+。从 Android 8 起，
**传统 PNG 图标会被系统塞进一个白色圆角底板**里显示（legacy icon treatment），
观感很差。所以必须提供 mipmap-anydpi-v26/ic_launcher.xml（前景 + 背景），
让系统按各厂商的形状蒙版自行裁切。

安全区
------
自适应图标画布 108dp，官方保证可见的核心安全区是**直径 66dp 的圆**（半径 33dp）。
标志外接圆半径约 58.1（120 坐标系），故取缩放 0.58 → 外接圆半径 33.7，勉强贴边；
配合切角八边形的圆润外廓，圆形蒙版下不会被切到实体。

产出
----
  mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher_foreground.png
  mipmap-*/ic_launcher_background.png
  mipmap-*/ic_launcher_mono.png          （Android 13+ 主题图标用）
  mipmap-*/ic_launcher.png               （传统图标，兜底）
  drawable/ic_stat.png                   （通知栏，纯白剪影）
  mipmap-anydpi-v26/ic_launcher.xml
  mipmap-anydpi-v33/ic_launcher.xml

用法：python tools/make_icons.py
"""
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
RES = os.path.join(ROOT, "app", "res")

# ---- 几何常量（120 坐标系）----
OCT = "34,8 86,8 112,34 112,86 86,112 34,112 8,86 8,34"          # 切角八边形
OCT_IN = "40,16 82,16 104,38 104,82 82,104 40,104 16,82 16,38"   # 内层细线
BARS = [(36, 44, 76), (48, 33, 87), (60, 22, 98), (72, 35, 85), (84, 46, 74)]

CY = "#22e6ff"
VI = "#a071ff"
MG = "#ff2d92"

ADAPT_SCALE = 0.58    # 自适应前景：压进 66dp 安全圆
LEGACY_SCALE = 0.80   # 传统图标：可以铺得满一些

DENSITIES = [
    ("mipmap-mdpi", 1.0),
    ("mipmap-hdpi", 1.5),
    ("mipmap-xhdpi", 2.0),
    ("mipmap-xxhdpi", 3.0),
    ("mipmap-xxxhdpi", 4.0),
]

DEFS = f"""<defs>
    <!-- 必须用 userSpaceOnUse：<line> 是零宽度元素，objectBoundingBox 会退化成
         空盒，渐变解析失败 → 整根线不渲染（踩过）。 -->
    <linearGradient id="gBars" gradientUnits="userSpaceOnUse" x1="8" y1="8" x2="112" y2="112">
      <stop offset="0%" stop-color="{CY}"/>
      <stop offset="48%" stop-color="{VI}"/>
      <stop offset="100%" stop-color="{MG}"/>
    </linearGradient>
    <radialGradient id="gPlate" cx="50%" cy="34%" r="78%">
      <stop offset="0%" stop-color="#0e1c2e"/>
      <stop offset="100%" stop-color="#04070d"/>
    </radialGradient>
    <radialGradient id="gBg" cx="50%" cy="38%" r="82%">
      <stop offset="0%" stop-color="#0d2135"/>
      <stop offset="62%" stop-color="#070e1a"/>
      <stop offset="100%" stop-color="#03050a"/>
    </radialGradient>
    <radialGradient id="gCy" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{CY}" stop-opacity="0.55"/>
      <stop offset="100%" stop-color="{CY}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="gMg" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{MG}" stop-opacity="0.50"/>
      <stop offset="100%" stop-color="{MG}" stop-opacity="0"/>
    </radialGradient>
    <pattern id="gGrid" width="9" height="9" patternUnits="userSpaceOnUse">
      <path d="M9 0H0V9" fill="none" stroke="{CY}" stroke-opacity="0.13" stroke-width="0.5"/>
    </pattern>
  </defs>"""


def mark(scale, cx=54.0, cy=54.0, mono=False):
    """标志本体。mono=True 输出纯白剪影（monochrome 层由系统着色）。"""
    if mono:
        plate_fill, plate_stroke, bar_stroke, inner = "none", "#ffffff", "#ffffff", ""
    else:
        plate_fill, plate_stroke, bar_stroke = "url(#gPlate)", CY, "url(#gBars)"
        inner = (f'<polygon points="{OCT_IN}" fill="none" stroke="{CY}" '
                 f'stroke-width="1" stroke-linejoin="round" opacity="0.22"/>')
    bars = "".join(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}"/>' for x, y1, y2 in BARS)
    return (f'<g transform="translate({cx} {cy}) scale({scale}) translate(-60 -60)">'
            f'<polygon points="{OCT}" fill="{plate_fill}" stroke="{plate_stroke}" '
            f'stroke-width="2.6" stroke-linejoin="round" opacity="0.98"/>'
            f'{inner}'
            f'<g stroke="{bar_stroke}" stroke-width="9" stroke-linecap="round">{bars}</g>'
            f'</g>')


def svg(size, body, box=108):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {box} {box}" '
            f'width="{size}" height="{size}" style="display:block">{DEFS}{body}</svg>')


def bg_body():
    return (f'<rect width="108" height="108" fill="url(#gBg)"/>'
            f'<rect width="108" height="108" fill="url(#gGrid)"/>'
            f'<circle cx="12" cy="10" r="46" fill="url(#gCy)"/>'
            f'<circle cx="98" cy="98" r="46" fill="url(#gMg)"/>')


def svg_stat(size):
    """通知栏小图标：只留五柱频谱，纯白、透明底。
    24dp 下八边形描边会糊成一团，所以果断去掉。"""
    s = size / 96.0
    bars96 = [(16, 38, 58), (32, 30, 66), (48, 22, 74), (64, 32, 64), (80, 39, 57)]
    bars = "".join(f'<line x1="{x*s:.2f}" y1="{y1*s:.2f}" x2="{x*s:.2f}" y2="{y2*s:.2f}"/>'
                   for x, y1, y2 in bars96)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
            f'width="{size}" height="{size}" style="display:block">'
            f'<g stroke="#ffffff" stroke-width="{10*s:.2f}" stroke-linecap="round">{bars}</g></svg>')


ADAPT_XML = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@mipmap/ic_launcher_background" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
</adaptive-icon>
"""

ADAPT_XML_V33 = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@mipmap/ic_launcher_background" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
    <monochrome android:drawable="@mipmap/ic_launcher_mono" />
</adaptive-icon>
"""


def build_jobs():
    jobs = []       # (svg, size, out_path, transparent)
    for dens, mul in DENSITIES:
        d = os.path.join(RES, dens)
        os.makedirs(d, exist_ok=True)
        for name, body, transp in (
            ("ic_launcher_foreground", mark(ADAPT_SCALE), True),
            ("ic_launcher_background", bg_body(), False),
            ("ic_launcher_mono", mark(ADAPT_SCALE, mono=True), True),
        ):
            n = int(108 * mul)
            jobs.append((svg(n, body), n, os.path.join(d, name + ".png"), transp))
        n = int(48 * mul)
        jobs.append((svg(n, bg_body() + mark(LEGACY_SCALE)), n,
                     os.path.join(d, "ic_launcher.png"), False))
    jobs.append((svg_stat(96), 96, os.path.join(RES, "drawable", "ic_stat.png"), True))
    return jobs


def main():
    from playwright.sync_api import sync_playwright

    for sub, xml in (("mipmap-anydpi-v26", ADAPT_XML), ("mipmap-anydpi-v33", ADAPT_XML_V33)):
        d = os.path.join(RES, sub)
        os.makedirs(d, exist_ok=True)
        io.open(os.path.join(d, "ic_launcher.xml"), "w",
                encoding="utf-8", newline="\n").write(xml)

    jobs = build_jobs()
    print("用 Chromium 渲染 %d 个 PNG …" % len(jobs))
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-gpu",
                                          "--force-device-scale-factor=1", "--hide-scrollbars"])
        page = browser.new_page(device_scale_factor=1)
        for svg_text, size, out, transp in jobs:
            page.set_viewport_size({"width": size, "height": size})
            page.set_content("<!doctype html><html><body style='margin:0;padding:0;"
                             "background:transparent'>" + svg_text + "</body></html>")
            page.screenshot(path=out, omit_background=transp)
        browser.close()

    bad = 0
    for _, size, out, _ in jobs:
        w, h = struct.unpack(">II", open(out, "rb").read(33)[16:24])
        if (w, h) != (size, size):
            print("  [尺寸异常] %s = %dx%d（期望 %d）" % (out, w, h, size))
            bad += 1
    print("已写 mipmap-anydpi-v26/ic_launcher.xml（前景+背景）")
    print("已写 mipmap-anydpi-v33/ic_launcher.xml（+monochrome，Android 13 主题图标）")
    print("完成：%d 个 PNG，%s" % (len(jobs), "有 %d 个尺寸异常" % bad if bad else "尺寸全部正确"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
