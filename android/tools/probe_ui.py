#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""UI 探针：确认关键元素是否真的渲染出来、尺寸多少、样式是否生效。
用法：python tools/probe_ui.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, ".."))
WWW = os.path.join(PROJ, "app", "assets", "www")

from playwright.sync_api import sync_playwright  # noqa: E402

JS = r"""
() => {
  playerSheet();
  const q = s => document.querySelector(s);
  const info = {};
  const art = q('.np-art');
  info.hasArt = !!art;
  if (art) {
    const r = art.getBoundingClientRect();
    const cs = getComputedStyle(art);
    info.artRect = {w: Math.round(r.width), h: Math.round(r.height),
                    top: Math.round(r.top), left: Math.round(r.left)};
    info.artStyle = {aspectRatio: cs.aspectRatio, display: cs.display,
                     maxWidth: cs.maxWidth, width: cs.width, height: cs.height,
                     background: cs.backgroundImage.slice(0, 60)};
  }
  const bd = q('#sheetBody');
  info.bodyLen = bd ? bd.innerHTML.length : -1;
  info.bodyHead = bd ? bd.innerHTML.slice(0, 260) : '';
  info.childCount = bd ? bd.children.length : -1;
  info.childClasses = bd ? [].map.call(bd.children, c => c.className || c.tagName).slice(0, 12) : [];
  const t = q('.np-title');
  if (t) { const r = t.getBoundingClientRect(); info.titleRect = {w: Math.round(r.width), h: Math.round(r.height)}; }
  info.sheetRect = (() => { const r = q('#sheet').getBoundingClientRect();
    return {w: Math.round(r.width), h: Math.round(r.height)}; })();
  info.bdScroll = bd ? {sh: bd.scrollHeight, ch: bd.clientHeight, st: bd.scrollTop} : null;
  // 样式是否加载：body 背景应当不是白色
  info.bodyBg = getComputedStyle(document.body).backgroundColor;
  info.sheetCount = document.styleSheets.length;
  try { info.cssRules = document.styleSheets[document.styleSheets.length-1].cssRules.length; }
  catch (e) { info.cssRules = 'err:' + e.message; }
  return info;
}
"""


def main():
    e2e = os.path.join(WWW, "_e2e.html")
    if not os.path.exists(e2e):
        print("缺少 _e2e.html")
        return 1
    url = "file:///" + e2e.replace("\\", "/")
    out = os.path.join(PROJ, "build", "shots")
    os.makedirs(out, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security",
                                    "--no-sandbox", "--disable-gpu"])
        for dsf in (1, 2):
            pg = b.new_context(viewport={"width": 400, "height": 820},
                               device_scale_factor=dsf).new_page()
            pg.goto(url, wait_until="load", timeout=60000)
            pg.wait_for_function("() => window.__e2eDone === true", timeout=120000)
            pg.evaluate("() => { var e=document.getElementById('e2e-out'); if(e) e.style.display='none'; }")
            info = pg.evaluate(JS)
            print("dsf=%d  art=%s  scroll=%s" % (dsf, info.get("artRect"), info.get("bdScroll")))
            if dsf == 2:
                pg.screenshot(path=os.path.join(out, "probe-player.png"))
                print("截图 -> build/shots/probe-player.png")
            print(json.dumps(info, ensure_ascii=False, indent=2))
            pg.close()
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
