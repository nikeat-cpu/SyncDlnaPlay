# -*- coding: utf-8 -*-
"""桌面测试脚手架跟随 v2.1 的 Api 签名（Storage / MusicDirs）更新。"""
import io
import os
import sys

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "javatest")


def patch(name, pairs):
    p = os.path.join(D, name)
    s = io.open(p, encoding="utf-8").read()
    for old, new in pairs:
        n = s.count(old)
        print(("OK  " if n == 1 else "!!  ") + "%-16s 命中 %d :: %s" % (name, n, old.strip().splitlines()[0][:46]))
        if n == 1:
            s = s.replace(old, new)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)


patch("LiveServer.java", [(
"""        }, new Downloader.DirProvider() {
            @Override public File downloadsDir() { return dl; }
        });""",
"""        }, new com.dlna.speaker.Storage.Simple(dl, new File(work, "tmp")), null);"""
)])

patch("ServerProbe.java", [
(
"""        }, new Downloader_Dir(dl));""",
"""        }, new com.dlna.speaker.Storage.Simple(dl, new File(work, "tmp")), null);"""
),
(
"""    /** Downloader 的目录提供者 */
    static class Downloader_Dir implements com.dlna.speaker.Downloader.DirProvider {
        private final File dir;
        Downloader_Dir(File d) { this.dir = d; }
        @Override public File downloadsDir() { return dir; }
    }

""",
""
),
])

for f in ("LiveServer.java", "ServerProbe.java"):
    s = io.open(os.path.join(D, f), encoding="utf-8").read()
    print(f, "-> 残留 DirProvider:", s.count("DirProvider"), "| Storage.Simple:", s.count("Storage.Simple"))
sys.exit(0)
