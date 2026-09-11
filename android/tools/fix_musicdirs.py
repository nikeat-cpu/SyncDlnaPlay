# -*- coding: utf-8 -*-
"""修正 MusicDirs.java 里的几处 API 误用。"""
import io
import os
import sys

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "java", "com", "dlna", "speaker"))

p = "MusicDirs.java"
s = io.open(p, encoding="utf-8").read()

fixes = [
    ('e.guest = Json.b(m, "guest");', 'e.guest = Json.b(m, "guest", false);'),
    ('m.put("size", Json.l(f, "size"));', 'm.put("size", Json.l(f, "size", -1));'),
    ('            if ("sms".equals(n.type)) continue;\n', ''),
]
for old, new in fixes:
    n = s.count(old)
    print("[%d] %s" % (n, old.strip()[:48]))
    s = s.replace(old, new)

io.open(p, "w", encoding="utf-8", newline="\n").write(s)

chk = io.open(p, encoding="utf-8").read()
print("Json.b ok :", 'Json.b(m, "guest", false)' in chk)
print("Json.l ok :", 'Json.l(f, "size", -1)' in chk)
print("笔误已删  :", '"sms"' not in chk)
sys.exit(0)
