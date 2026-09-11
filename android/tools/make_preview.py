#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
生成「赛博朋克 UI 改版」设计交付预览页（自包含 HTML，图片全部内嵌 base64）。
用法：python tools/make_preview.py   ->  build/preview.html
"""
import base64
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "build", "preview.html")

ICON = os.path.join(ROOT, "app", "res", "mipmap-xxxhdpi")
SHOTS = os.path.join(ROOT, "build", "shots")

LOGO_SVG = """<svg viewBox="0 0 120 120" width="150" height="150" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="pg" gradientUnits="userSpaceOnUse" x1="8" y1="8" x2="112" y2="112">
      <stop offset="0%" stop-color="#22e6ff"/><stop offset="48%" stop-color="#a071ff"/><stop offset="100%" stop-color="#ff2d92"/>
    </linearGradient>
    <radialGradient id="pp" cx="50%" cy="34%" r="78%">
      <stop offset="0%" stop-color="#0e1c2e"/><stop offset="100%" stop-color="#04070d"/>
    </radialGradient>
  </defs>
  <polygon points="34,8 86,8 112,34 112,86 86,112 34,112 8,86 8,34" fill="url(#pp)" stroke="#22e6ff" stroke-width="2.6" stroke-linejoin="round"/>
  <polygon points="40,16 82,16 104,38 104,82 82,104 40,104 16,82 16,38" fill="none" stroke="#22e6ff" stroke-width="1" stroke-linejoin="round" opacity="0.22"/>
  <g stroke="url(#pg)" stroke-width="9" stroke-linecap="round">
    <line x1="36" y1="44" x2="36" y2="76"/><line x1="48" y1="33" x2="48" y2="87"/>
    <line x1="60" y1="22" x2="60" y2="98"/><line x1="72" y1="35" x2="72" y2="85"/>
    <line x1="84" y1="46" x2="84" y2="74"/>
  </g>
</svg>"""

PALETTE = [
    ("--cy", "#22E6FF", "霓虹青 · 主色"),
    ("--mg", "#FF2D92", "品红 · 辅色"),
    ("--vi", "#A071FF", "紫罗兰 · 过渡"),
    ("--yl", "#E6FF4A", "酸性黄 · 提示"),
    ("--bg", "#04060C", "深空黑蓝 · 底色"),
    ("--bg3", "#0E1826", "面板面"),
    ("--tx", "#D2EEF8", "主文字"),
    ("--tx3", "#4D7484", "次文字"),
]

SHOT_LIST = [
    ("sheet-splash.png", "启动页", "标志 + 故障字效 + HUD 角标"),
    ("sheet-player.png", "播放器面板", "全息唱片 + 频谱标志 + 菱形滑块"),
    ("sheet-player2.png", "播放模式 / 歌词", "霓虹 chip + 歌词逐行高亮"),
    ("sheet-volume.png", "音量面板", "霓虹导轨 + 快捷档位"),
    ("sheet-sources.png", "曲库管理", "切角主按钮 + 分节标题"),
]


def b64(path):
    return base64.b64encode(open(path, "rb").read()).decode("ascii")


def main():
    for f in ["ic_launcher.png", "ic_launcher_foreground.png", "ic_launcher_background.png"]:
        if not os.path.exists(os.path.join(ICON, f)):
            print("缺少图标:", f, "→ 先跑 tools/make_icons.py")
            return 1

    legacy = b64(os.path.join(ICON, "ic_launcher.png"))
    fg = b64(os.path.join(ICON, "ic_launcher_foreground.png"))
    bg = b64(os.path.join(ICON, "ic_launcher_background.png"))

    cards = []
    for fn, title, desc in SHOT_LIST:
        p = os.path.join(SHOTS, fn)
        if not os.path.exists(p):
            continue
        cards.append(
            '<figure class="phone"><img src="data:image/png;base64,%s" alt="%s">'
            '<figcaption><b>%s</b><span>%s</span></figcaption></figure>'
            % (b64(p), title, title, desc))

    swatches = "".join(
        '<div class="sw"><i style="background:%s"></i><div><b>%s</b><span>%s</span></div></div>'
        % (hexv, name, label) for name, hexv, label in PALETTE)

    # 自适应图标：外层裁成 72/108（即放大 1.5 倍后裁切）来模拟系统蒙版
    def adaptive(mask_css, label):
        return ('<div class="icoWrap"><div class="icoBox" style="%s">'
                '<div class="icoInner">'
                '<img class="icoBg" src="data:image/png;base64,%s">'
                '<img class="icoFg" src="data:image/png;base64,%s">'
                '</div></div><span>%s</span></div>' % (mask_css, bg, fg, label))

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>音响管家 · 赛博朋克改版</title>
<style>
:root{--cy:#22e6ff;--mg:#ff2d92;--vi:#a071ff;--bg:#04060c;--panel:#0a1220;--tx:#d2eef8;--tx3:#4d7484}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
  font:15px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background-image:
    radial-gradient(120% 60% at 10% -8%,rgba(34,230,255,.14),transparent 60%),
    radial-gradient(120% 60% at 96% 2%,rgba(255,45,146,.12),transparent 58%),
    linear-gradient(rgba(34,230,255,.045) 1px,transparent 1px),
    linear-gradient(90deg,rgba(34,230,255,.045) 1px,transparent 1px);
  background-size:auto,auto,36px 36px,36px 36px;background-attachment:fixed}
.wrap{max-width:1120px;margin:0 auto;padding:52px 26px 90px}
.hero{display:flex;align-items:center;gap:26px;flex-wrap:wrap;margin-bottom:8px}
.hero h1{margin:0;font-size:38px;font-weight:800;letter-spacing:.24em;color:#fff;
  text-shadow:0 0 18px rgba(34,230,255,.7),0 0 52px rgba(34,230,255,.32)}
.hero .sv{filter:drop-shadow(0 0 20px rgba(34,230,255,.5)) drop-shadow(0 0 48px rgba(255,45,146,.25))}
.tag{display:inline-block;margin-top:10px;padding:5px 13px;font-size:12px;letter-spacing:.2em;
  color:var(--cy);border:1px solid rgba(34,230,255,.4);border-radius:3px;
  box-shadow:0 0 16px rgba(34,230,255,.2)}
h2{font-size:13px;letter-spacing:.28em;color:var(--tx3);margin:56px 0 20px;
  display:flex;align-items:center;gap:10px;font-weight:600}
h2::before{content:'';width:3px;height:13px;background:var(--cy);box-shadow:0 0 12px var(--cy)}
.icons{display:flex;gap:34px;flex-wrap:wrap;align-items:flex-start}
.icoWrap{text-align:center}
.icoWrap>span{display:block;margin-top:12px;font-size:12px;color:var(--tx3);letter-spacing:.1em}
.icoBox{width:132px;height:132px;overflow:hidden;position:relative;
  box-shadow:0 0 0 1px rgba(34,230,255,.22),0 0 30px rgba(34,230,255,.14)}
.icoInner{position:absolute;width:150%;height:150%;left:-25%;top:-25%}
.icoInner img{position:absolute;inset:0;width:100%;height:100%}
.icoFg{z-index:2}
.sw{display:flex;align-items:center;gap:12px;padding:11px 14px;
  border:1px solid rgba(34,230,255,.16);background:rgba(10,18,32,.6)}
.sw i{width:34px;height:34px;border-radius:3px;flex:0 0 34px;
  box-shadow:inset 0 0 0 1px rgba(255,255,255,.16)}
.sw b{display:block;font-size:13px;font-family:ui-monospace,Consolas,monospace;letter-spacing:.06em}
.sw span{font-size:11.5px;color:var(--tx3)}
.pal{display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:10px}
.shots{display:flex;gap:22px;flex-wrap:wrap;padding-bottom:16px}
.phone{margin:0;flex:0 0 auto}
.phone img{width:246px;display:block;border-radius:8px;
  border:1px solid rgba(34,230,255,.28);box-shadow:0 0 34px rgba(34,230,255,.16),0 20px 50px rgba(0,0,0,.6)}
.phone figcaption{margin-top:11px;text-align:center}
.phone b{display:block;font-size:13.5px;color:var(--cy)}
.phone span{font-size:11.5px;color:var(--tx3)}
.note{margin-top:14px;padding:14px 16px;border-left:2px solid var(--vi);
  background:rgba(160,113,255,.07);font-size:13px;color:var(--tx3);line-height:1.75}
.shots::-webkit-scrollbar{height:8px}
.shots::-webkit-scrollbar-thumb{background:rgba(34,230,255,.3)}
</style></head><body><div class="wrap">

<div class="hero">
  <div class="sv">__LOGO__</div>
  <div>
    <h1>音响管家</h1>
    <div class="tag">CYBERPUNK UI · v2.3</div>
  </div>
</div>

<h2>APP 图标 · 自适应图标（含蒙版预览）</h2>
<div class="icons">
  __ADAPT__
  <div class="icoWrap">
    <div class="icoBox" style="border-radius:0"><img src="data:image/png;base64,__LEGACY__" style="width:100%;height:100%"></div>
    <span>传统图标 · 方形</span>
  </div>
</div>
<div class="note">minSdk 26 意味着所有设备都是 Android 8+。若只提供 PNG，系统会把它塞进
<b>白色圆角底板</b>里显示，非常丑。所以这里做成了<b>自适应图标</b>（前景 + 背景 + 单色），
由系统按各厂商形状蒙版裁切；右侧还额外带了 Android 13 主题图标（monochrome）层。</div>

<h2>配色</h2>
<div class="pal">__PAL__</div>

<h2>界面实拍</h2>
<div class="shots">__SHOTS__</div>

</div></body></html>"""

    html = (html
            .replace("__LOGO__", LOGO_SVG)
            .replace("__ADAPT__",
                     adaptive("border-radius:50%", "圆形蒙版")
                     + adaptive("border-radius:30%", "方形圆角蒙版")
                     + adaptive("border-radius:16px", "原生 108dp 全幅"))
            .replace("__LEGACY__", legacy)
            .replace("__PAL__", swatches)
            .replace("__SHOTS__", "".join(cards)))

    io.open(OUT, "w", encoding="utf-8", newline="\n").write(html)
    print("已生成 %s  (%.2f MB)" % (OUT, os.path.getsize(OUT) / 1048576.0))

    # 自检：渲染一张长图，确认预览页本身没写坏（元素是否都在、有没有报错）
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--no-sandbox", "--disable-gpu", "--hide-scrollbars"])
            pg = b.new_context(viewport={"width": 1180, "height": 900}).new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto("file:///" + OUT.replace("\\", "/"), wait_until="load", timeout=60000)
            pg.wait_for_timeout(1200)
            n = pg.evaluate("""() => ({
                phones: document.querySelectorAll('.phone').length,
                sw: document.querySelectorAll('.sw').length,
                ico: document.querySelectorAll('.icoWrap').length,
                imgs: [].slice.call(document.images).filter(i => !i.complete || i.naturalWidth === 0).length
            })""")
            shot = os.path.join(ROOT, "build", "shots", "preview.png")
            pg.screenshot(path=shot, full_page=True)
            b.close()
        print("  自检: 界面图=%d 色卡=%d 图标=%d 加载失败图片=%d JS错误=%d"
              % (n["phones"], n["sw"], n["ico"], n["imgs"], len(errs)))
        for e in errs:
            print("  [JS 错误]", e)
        print("  预览长图 ->", shot)
    except Exception as e:
        print("  自检截图跳过:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
