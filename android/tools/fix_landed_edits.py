# -*- coding: utf-8 -*-
"""补上几处未落盘的编辑（Edit 工具对本项目偶发"假成功"）。"""
import io
import os
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "java", "com", "dlna", "speaker")

def patch(fname, pairs):
    p = os.path.join(BASE, fname)
    s = io.open(p, encoding="utf-8").read()
    for old, new in pairs:
        n = s.count(old)
        tag = "OK " if n == 1 else "!! "
        print("%s %-20s 命中 %d :: %s" % (tag, fname, n, old.strip().splitlines()[0][:52]))
        if n == 1:
            s = s.replace(old, new)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)

# 1) MediaScanner.Opener 的双参构造
patch("MediaScanner.java", [(
'''    public static class Opener implements Library.Opener {
        private final Context ctx;

        public Opener(Context ctx) {
            this.ctx = ctx;
        }
''',
'''    public static class Opener implements Library.Opener {
        private final Context ctx;
        private final MusicDirs dirs;

        public Opener(Context ctx) {
            this(ctx, new MusicDirs(ctx));
        }

        public Opener(Context ctx, MusicDirs dirs) {
            this.ctx = ctx;
            this.dirs = dirs;
        }
''')])

# 2) MainActivity：悬空的 @Override 与 getDownloadsDir
patch("MainActivity.java", [
(
'''    /* ------------------------------------------------------- 文件选择回调 */

    @Override
    /**
     * 打开系统目录选择器（SAF）。''',
'''    /* ------------------------------------------------------- 文件选择回调 */

    /**
     * 打开系统目录选择器（SAF）。'''
),
(
'''        @JavascriptInterface
        public String getDownloadsDir() {
            return downloadsDir().getAbsolutePath();
        }''',
'''        @JavascriptInterface
        public String getDownloadsDir() {
            return storage == null ? "" : storage.describe();
        }'''
),
])

# 3) 复核
ms = io.open(os.path.join(BASE, "MediaScanner.java"), encoding="utf-8").read()
ma = io.open(os.path.join(BASE, "MainActivity.java"), encoding="utf-8").read()
print()
print("Opener 双参构造 :", "public Opener(Context ctx, MusicDirs dirs)" in ms)
print("Opener.dirs 字段:", "private final MusicDirs dirs;" in ms)
print("悬空 @Override  :", "@Override\n    /**\n     * 打开系统目录选择器" not in ma)
print("getDownloadsDir :", "storage == null ? \"\" : storage.describe()" in ma)
print("残留 downloadsDir():", ma.count("downloadsDir()"))
sys.exit(0)
