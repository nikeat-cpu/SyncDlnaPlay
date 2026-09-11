#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v2.3 收尾补丁：版本号 2.2 -> 2.3，系统配色同步为赛博朋克。
（本项目的 Edit 工具偶尔会「假成功」，所以机械替换统一走脚本 + 计数校验。）
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))


def sub(rel, old, new, tag, count=1):
    p = os.path.join(ROOT, rel)
    s = io.open(p, encoding="utf-8").read()
    n = s.count(old)
    if n != count:
        print("  [跳过] %-46s 命中 %d 次（期望 %d）" % (tag, n, count))
        return False
    io.open(p, "w", encoding="utf-8", newline="\n").write(s.replace(old, new))
    print("  [OK]   %s" % tag)
    return True


def main():
    ok = True
    # ---- 版本号 ----
    ok &= sub("app/AndroidManifest.xml", 'android:versionCode="5"',
              'android:versionCode="6"', "Manifest versionCode 5 -> 6")
    ok &= sub("app/AndroidManifest.xml", 'android:versionName="2.2">',
              'android:versionName="2.3">', "Manifest versionName 2.2 -> 2.3")
    ok &= sub("build.sh", 'APK_NAME="yinxiang-guanjia-standalone-v2.2.apk"',
              'APK_NAME="yinxiang-guanjia-standalone-v2.3.apk"', "build.sh 产物名 -> v2.3")
    ok &= sub("app/java/com/dlna/speaker/MainActivity.java", 'return "2.2-standalone";',
              'return "2.3-standalone";', "MainActivity getVersion -> 2.3-standalone")

    # ---- 系统配色（状态栏 / 导航栏 / 强调色）----
    colors = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <!-- 赛博朋克配色，与 app/assets/www/app.css 的 :root 保持一致 -->
    <color name="bg">#FF04060C</color>
    <color name="bg2">#FF080E18</color>
    <color name="accent">#FF22E6FF</color>
    <color name="accent2">#FFFF2D92</color>
    <color name="ic_launcher_bg">#FF070E1A</color>
</resources>
"""
    io.open(os.path.join(ROOT, "app/res/values/colors.xml"), "w",
            encoding="utf-8", newline="\n").write(colors)
    print("  [OK]   colors.xml -> 赛博朋克配色")

    styles = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="AppTheme" parent="@android:style/Theme.Material.NoActionBar">
        <item name="android:windowBackground">@color/bg</item>
        <item name="android:statusBarColor">@color/bg</item>
        <item name="android:navigationBarColor">@color/bg</item>
        <item name="android:colorAccent">@color/accent</item>
        <item name="android:textColorPrimary">#FFD2EEF8</item>
        <item name="android:windowLightStatusBar">false</item>
        <item name="android:windowLightNavigationBar">false</item>
    </style>
</resources>
"""
    io.open(os.path.join(ROOT, "app/res/values/styles.xml"), "w",
            encoding="utf-8", newline="\n").write(styles)
    print("  [OK]   styles.xml -> 深色状态栏/导航栏")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
