#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成语言变体 assets —— 给 build.sh 的 BUILD_LANG 用。

做法：把 app/assets 整棵树复制到 build/assets_<lang>，再对副本里的 www/i18n.js
做「默认语言」补丁。源目录保持原样，不会被改动。

用法（一般由 build.sh 调用）：
    python tools/make_lang_assets.py app/assets build/assets_en en

补丁点：i18n.js 的 detect() 末尾
    原文:  return /^zh/i.test(l) ? "zh" : "en";
    en 版: return "en";     ← 不看系统语言，默认英文
    zh 版: return "zh";     ← 不看系统语言，默认中文
已保存的用户选择（localStorage dlna_lang）优先级仍高于默认值，
所以两个版本里设置页的「语言 / Language」切换照常可用。
"""

import os
import shutil
import sys

OLD = 'return /^zh/i.test(l) ? "zh" : "en";'
NEW = {
    "en": 'return "en"; /* BUILD_LANG=en: 默认英文启动 */',
    "zh": 'return "zh"; /* BUILD_LANG=zh: 默认中文启动 */',
}


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src, dst, lang = sys.argv[1], sys.argv[2], sys.argv[3].lower()
    if lang not in NEW:
        sys.exit("不支持的语言变体：%s（可选 en / zh）" % lang)
    if not os.path.isdir(src):
        sys.exit("assets 源目录不存在：%s" % src)

    # 1) 复制整棵 assets 树（先删旧的，避免残留上一次变体）
    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)

    # 2) 打补丁
    target = os.path.join(dst, "www", "i18n.js")
    if not os.path.isfile(target):
        sys.exit("副本里找不到 www/i18n.js：%s" % target)
    with open(target, encoding="utf-8") as fh:
        s = fh.read()
    n = s.count(OLD)
    if n != 1:
        sys.exit("i18n.js 里默认语言那行匹配到 %d 次（应为 1），源码可能改过了" % n)
    s = s.replace(OLD, NEW[lang])
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(s)

    # 3) 落盘后复核，并确认源文件没被碰过
    with open(target, encoding="utf-8") as fh:
        assert NEW[lang] in fh.read()
    with open(os.path.join(src, "www", "i18n.js"), encoding="utf-8") as fh:
        assert OLD in fh.read(), "源 i18n.js 被改动了，必须还原！"

    files = sum(len(f) for _, _, f in os.walk(dst))
    print("    语言变体 %s：%d 个文件 → %s" % (lang, files, dst))
    print("    默认语言补丁已应用（源 assets 未改动）")


if __name__ == "__main__":
    main()
