# -*- coding: utf-8 -*-
"""
本地歌词 —— Python 版
=====================
对应安卓独立版的 Lyrics.java + Api.lyricApi / lyricSave / lyricByName。

两类歌词：

  1. **同目录同名 .lrc**（也支持放在 `lyrics/` 子目录里）
     → GET /api/lyric?id=<track_id>
     在线曲目的歌词不走这里 —— 那由浏览器里的插件运行时直接向音源要。

  2. **标题歌词库**（`<data_dir>/lyrics/<歌手> - <歌名>.lrc`）
     → GET  /api/lyric/byname?artist=&title=
       POST /api/lyric/save   {artist, title, lrc}
     本地/下载的歌在线找到词之后落盘到这里，下次按「歌手 - 歌名」直接命中。

歌词文件在中文环境常见 GBK 编码，所以先按 UTF-8 解，出现替换字符再退回 GBK。
"""

import os
import re

MAX_LRC = 512 * 1024

_BAD_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_name(name, fallback="track"):
    s = _BAD_FILENAME.sub("_", (name or "").strip()).strip(". ")
    return (s or fallback)[:120]


def decode_text(data):
    """先按 UTF-8 解；有替换字符则退回 GBK（默认代码页）"""
    if not data:
        return ""
    try:
        s = data.decode("utf-8")
        if "\ufffd" not in s:
            return s[1:] if s.startswith("\ufeff") else s
    except UnicodeDecodeError:
        pass
    for enc in ("gbk", "gb18030", "big5", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def brother(path, ext):
    """把 xxx.mp3 变成 xxx.lrc"""
    if not path:
        return ""
    dot = path.rfind(".")
    slash = max(path.rfind("/"), path.rfind("\\"))
    base = path[:dot] if dot > slash else path
    return base + "." + ext


def read_file_text(path):
    try:
        with open(path, "rb") as f:
            return decode_text(f.read(MAX_LRC))
    except OSError:
        return ""


class LyricStore:
    """标题歌词库（`<data_dir>/lyrics/`）"""

    def __init__(self, data_dir=""):
        self.data_dir = data_dir or ""

    def lyrics_dir(self):
        return os.path.join(self.data_dir, "lyrics") if self.data_dir else ""

    def store_file(self, artist, title):
        name = sanitize_name(f"{artist or ''} - {title or ''}", "track") + ".lrc"
        d = self.lyrics_dir()
        return os.path.join(d, name) if d else ""

    def find_by_name(self, artist, title):
        p = self.store_file(artist, title)
        if p and os.path.isfile(p):
            return read_file_text(p)
        return ""

    def save(self, artist, title, lrc):
        if not (lrc or "").strip():
            return {"ok": False, "msg": "空歌词"}
        p = self.store_file(artist, title)
        if not p:
            return {"ok": False, "msg": "当前环境不支持保存歌词"}
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(lrc)
            return {"ok": True, "file": p}
        except OSError as e:
            return {"ok": False, "msg": str(e)}

    # -------------------------------------------------- 同目录 .lrc
    def find_for_path(self, media_path):
        """找同目录同名的 .lrc（也支持 lyrics/ 子目录）"""
        if not media_path:
            return ""
        lrc = brother(media_path, "lrc")
        if not os.path.isfile(lrc):
            alt = os.path.join(os.path.dirname(lrc), "lyrics", os.path.basename(lrc))
            if os.path.isfile(alt):
                lrc = alt
            else:
                return ""
        return read_file_text(lrc)
