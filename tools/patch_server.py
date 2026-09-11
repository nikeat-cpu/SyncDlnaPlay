#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性补丁：确保 server.py 已包含 bridge 所需的 import 与配置。"""
import io, sys

p = r"C:\Users\TaoPC\WorkBuddy\2026-09-03-10-57-01\dlna-speaker\app\server.py"
s = open(p, encoding="utf-8").read()
changed = []

# 1) import urllib.request
if "import urllib.request" not in s:
    assert "import urllib.parse\n" in s, "找不到 import urllib.parse"
    s = s.replace("import urllib.parse\n",
                  "import urllib.parse\nimport urllib.request\n", 1)
    changed.append("import urllib.request")

# 2) BRIDGE_URL / BRIDGE_PUBLIC 配置
if "BRIDGE_URL =" not in s:
    anchor = 'STATE_FILE = os.environ.get("STATE_FILE", "").strip()\n'
    assert anchor in s, "找不到 STATE_FILE 配置锚点"
    block = (anchor +
             "\n"
             "# MusicFree 在线音源桥接服务（端口 5001，与 dlna-speaker 同机运行）\n"
             "# BRIDGE_URL: 本服务访问 bridge 的地址（容器间用 127.0.0.1 即可）\n"
             "# BRIDGE_PUBLIC: 回给音响拉流的公开基址；留空则自动用本机 IP:5001\n"
             'BRIDGE_URL = os.environ.get("MUSICFREE_BRIDGE_URL", "http://127.0.0.1:5001").rstrip("/")\n'
             'BRIDGE_PUBLIC = os.environ.get("MUSICFREE_BRIDGE_PUBLIC", "").strip()\n')
    s = s.replace(anchor, block, 1)
    changed.append("BRIDGE_URL/BRIDGE_PUBLIC config")

open(p, "w", encoding="utf-8").write(s)
print("changed:", changed if changed else "nothing (already present)")
