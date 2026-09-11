# -*- coding: utf-8 -*-
"""把 aapt2 产出的资源 APK 与 d8 产出的 dex 组装成最终 APK。

关键点：targetSdk >= 30 时 resources.arsc 必须以「不压缩」方式存放并 4 字节对齐，
否则 Android 11+ 会拒绝安装（INSTALL_PARSE_FAILED_UNEXPECTED_EXCEPTION）。

用法: pack_apk.py <base.apk> <dex文件或dex目录> <输出apk>
     目录形态下会把 classes.dex / classes2.dex ... 全部打进去（引入 SMB 客户端后
     方法数超过单个 dex 上限，必须有 multidex）。
"""
import os
import sys
import zipfile

STORE_NAMES = {"resources.arsc"}


def collect_dex(src):
    """返回 [(apk 内名字, 本地路径)]，按 classes.dex / classes2.dex ... 排序"""
    if os.path.isdir(src):
        def order(n):
            if n == "classes.dex":
                return 0
            digits = "".join(c for c in n if c.isdigit())
            return int(digits) if digits else 999
        found = sorted([f for f in os.listdir(src) if f.endswith(".dex")], key=order)
        return [(n, os.path.join(src, n)) for n in found]
    return [("classes.dex", src)]


def main():
    base, dexsrc, out = sys.argv[1], sys.argv[2], sys.argv[3]
    if os.path.exists(out):
        os.remove(out)

    dexes = collect_dex(dexsrc)
    if not dexes:
        raise SystemExit("没有找到任何 dex: " + dexsrc)

    zin = zipfile.ZipFile(base, "r")
    zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)

    for item in zin.infolist():
        # 丢掉落进来的旧 dex，后面统一写
        if item.filename == "classes.dex" or (item.filename.startswith("classes") and item.filename.endswith(".dex")):
            continue
        data = zin.read(item.filename)
        need_store = (item.filename in STORE_NAMES) or item.filename.endswith(".so")
        zout.writestr(item.filename, data,
                      zipfile.ZIP_STORED if need_store else zipfile.ZIP_DEFLATED)

    total = 0
    for name, path in dexes:
        with open(path, "rb") as f:
            blob = f.read()
        total += len(blob)
        zout.writestr(name, blob, zipfile.ZIP_DEFLATED)
        print("  dex -> %-14s %8.1f KB  (源: %s)" % (name, len(blob) / 1024.0, os.path.basename(path)))

    zout.close()
    zin.close()

    names = zipfile.ZipFile(out).namelist()
    print("APK 条目: %d 个，dex 共 %d 个 / %.1f KB" % (
        len(names), len(dexes), total / 1024.0))
    for must in ("AndroidManifest.xml", "resources.arsc", "classes.dex"):
        if must not in names:
            raise SystemExit("缺少 " + must)
    if not any(n.startswith("assets/www/") for n in names):
        raise SystemExit("缺少 assets/www（手机版界面没打进去）")
    if "assets/www/plugins-runtime.js" not in names:
        raise SystemExit("缺少 assets/www/plugins-runtime.js（在线音源运行时没打进去）")
    n_plugins = len([n for n in names if n.startswith("assets/plugins/") and n.endswith(".js")])
    if n_plugins == 0:
        raise SystemExit("缺少 assets/plugins/*.js（内置音源插件没打进去）")
    print("内置音源插件: %d 个" % n_plugins)
    print("组装完成:", out)


if __name__ == "__main__":
    main()
