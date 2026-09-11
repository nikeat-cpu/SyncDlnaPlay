# -*- coding: utf-8 -*-
"""接入 i18n：index.html 引入 i18n.js；settingsSheet 增加语言切换。"""
import io, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.join(HERE, "..", "app", "assets", "www")


def rw(path, pairs):
    p = os.path.join(WWW, path)
    with io.open(p, encoding="utf-8") as f:
        s = f.read()
    for old, new, label in pairs:
        if new in s and old not in s:
            print("  skip (已应用):", label)
            continue
        assert old in s, "锚点缺失 " + label
        s = s.replace(old, new, 1)
        print("  ok:", label)
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


print("index.html:")
rw("index.html", [
    ('<script src="plugins-runtime.js"></script>\n<script src="app.js"></script>',
     '<script src="i18n.js"></script>\n<script src="plugins-runtime.js"></script>\n<script src="app.js"></script>',
     "引入 i18n.js"),
    ('<html lang="zh-CN">', '<html lang="zh-CN">', "lang 由 i18n 运行时覆盖"),
])

print("app.js:")
LANG_BLOCK = """
    <div class="sec-title">语言 / Language</div>
    <div class="chips">
      <div class="chip ${(window.I18N && I18N.lang) === 'zh' ? 'on' : ''}" onclick="I18N.set('zh')">中文</div>
      <div class="chip ${(window.I18N && I18N.lang) === 'en' ? 'on' : ''}" onclick="I18N.set('en')">English</div>
    </div>
"""
rw("app.js", [
    ("""      <div class="chip" onclick="closeSheet();dlStatus()">⤓ 下载状态</div>
    </div>
""",
     """      <div class="chip" onclick="closeSheet();dlStatus()">⤓ 下载状态</div>
    </div>
""" + LANG_BLOCK,
     "设置页语言切换"),
])

print("done")
