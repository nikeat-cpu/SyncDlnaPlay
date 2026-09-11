# -*- coding: utf-8 -*-
"""
把 libs/ 下的第三方 jar 预处理成 d8 能直接吃的形态。

bcprov / jcifs-ng 都是多版本 jar，带 module-info.class 与 META-INF/versions/，
d8 对这些会报错或产生重复类；签名文件在重新打包后也必然失效。
这里统一剔除，只保留真正的业务类与 META-INF/services（ServiceLoader 要用）。
"""
import os
import shutil
import sys
import zipfile

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(BASE, "libs")
DST = os.path.join(SRC, "dexin")

KEEP_META_PREFIX = "META-INF/services/"


def keep(name):
    if name == "module-info.class" or name.endswith("/module-info.class"):
        return False
    if name.startswith("META-INF/versions/"):
        return False
    if name.startswith("META-INF/") and not name.startswith(KEEP_META_PREFIX):
        return False
    if name.endswith("/package-info.class"):
        return False
    return not name.endswith("/")


def main():
    if os.path.isdir(DST):
        shutil.rmtree(DST, ignore_errors=True)
    os.makedirs(DST)

    jars = sorted(f for f in os.listdir(SRC) if f.endswith(".jar"))
    if not jars:
        raise SystemExit("libs/ 下没有 jar")

    for j in jars:
        src = os.path.join(SRC, j)
        dst = os.path.join(DST, j)
        zin = zipfile.ZipFile(src, "r")
        n_in = n_out = 0
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for it in zin.infolist():
                n_in += 1
                if not keep(it.filename):
                    continue
                zout.writestr(it, zin.read(it.filename))
                n_out += 1
        zin.close()
        print("  %-28s %5d -> %5d 项   %6.1f KB" % (
            j, n_in, n_out, os.path.getsize(dst) / 1024.0))
    print("预处理完成 ->", os.path.relpath(DST, BASE))


if __name__ == "__main__":
    main()
