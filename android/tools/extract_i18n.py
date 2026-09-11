# -*- coding: utf-8 -*-
"""抽出前端里所有需要翻译的中文文本片段，供人工/模型翻译成 i18n 字典。"""
import re, io, os, sys

WWW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "assets", "www")
LIT = re.compile(r"""(['"`])((?:(?!\1)[^\\]|\\.)*?)\1""", re.S)
CJK = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


def fragments(raw):
    """把字符串字面量切成纯文本片段（去掉标签与 ${} 表达式）。"""
    txt = re.sub(r"\$\{[^}]*\}", "\x00", raw)
    txt = re.sub(r"<[^>]*>", "\x00", txt)
    return [p.strip() for p in re.split(r"[\x00\n]+", txt)]


def main():
    frag = {}
    for name in ("app.js", "index.html", "i18n.js"):
        path = os.path.join(WWW, name)
        if not os.path.exists(path):
            continue
        s = io.open(path, encoding="utf-8").read()
        for m in LIT.finditer(s):
            raw = m.group(2)
            if not CJK.search(raw):
                continue
            for part in fragments(raw):
                if part and CJK.search(part) and len(part) <= 200:
                    frag.setdefault(part, name)
    out = sorted(frag)
    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "cn_frag.txt")
    with io.open(dst, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print("unique fragments:", len(out))
    print("written:", os.path.abspath(dst))


if __name__ == "__main__":
    main()
