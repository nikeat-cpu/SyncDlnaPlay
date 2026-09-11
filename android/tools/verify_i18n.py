# -*- coding: utf-8 -*-
"""英文模式覆盖率校验：强制 lang=en 遍历所有界面，列出未被翻译的中文文案。"""
import os, io, json, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harvest_i18n import HARVEST, STEPS, WWW, ROOT  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = os.path.join(ROOT, "build", "i18n_missing.json")

# 运行时产生的动态数据（设备名/曲目名/目录名/日志），不属于界面文案
SKIP = ("测试音", "测试专辑", "192.168.", "客厅音响", "书房音响", "小爱音箱",
        "夜间飞行", "某某", "DLNA-AirSound", "AirDlan", "ISTOREOS",
        # 刻意保留：下载目录实名、音源平台名
        "Music/音响管家", "元力")
# 精确匹配的忽略项（测试用歌词行 / 语言名本身）
SKIP_EXACT = {"一", "二", "首", "中文", "English"}


def is_noise(t):
    return t in SKIP_EXACT or any(s in t for s in SKIP)


def main():
    missing = {}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security",
                                    "--no-sandbox", "--disable-gpu"])
        ctx = b.new_context(viewport={"width": 400, "height": 900}, device_scale_factor=1)
        ctx.add_init_script("try{localStorage.setItem('dlna_lang','en')}catch(e){}")
        pg = ctx.new_page()
        pg.goto("file:///" + WWW.replace("\\", "/"), wait_until="load")
        for _ in range(40):
            try:
                if pg.evaluate("!!(S && S.state)"):
                    break
            except Exception:
                pass
            time.sleep(0.5)
        time.sleep(1.5)
        print("lang =", pg.evaluate("window.I18N && I18N.lang"))

        for label, js, wait in STEPS:
            try:
                pg.evaluate(js)
            except Exception as e:
                print("  [warn]", label, str(e)[:100])
                continue
            time.sleep(wait / 1000.0)
            # 关键：先同步补一次翻译，消除「应用重绘 → 观察器防抖」之间的时间窗误报
            try:
                pg.evaluate("window.I18N && I18N.apply()")
            except Exception:
                pass
            time.sleep(0.05)
            try:
                got = pg.evaluate(HARVEST)
            except Exception:
                got = []
            left = [t for t in got if not is_noise(t)]
            missing[label] = left
        b.close()

    allleft = sorted({t for v in missing.values() for t in v})
    # 分类：词典里到底有没有这条（区分「漏收录」与「时序误报」）
    classify = {}
    if allleft:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security",
                                        "--no-sandbox", "--disable-gpu"])
            ctx = b.new_context()
            ctx.add_init_script("try{localStorage.setItem('dlna_lang','en')}catch(e){}")
            pg = ctx.new_page()
            pg.goto("file:///" + WWW.replace("\\", "/"), wait_until="load")
            time.sleep(0.6)
            classify = pg.evaluate(
                "(list) => { const o = {}; list.forEach(s => { try { o[s] = I18N.t(s); } catch (e) { o[s] = null; } }); return o; }",
                allleft)
            b.close()

    gap = [t for t in allleft if classify.get(t) is None]
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump({"missing": allleft, "gap_in_dict": gap, "probe": classify, "by_step": missing},
                  f, ensure_ascii=False, indent=1)
    print("---- 仍显示中文:", len(allleft), " 其中词典缺失:", len(gap), "----")
    for t in allleft:
        mark = "缺失" if classify.get(t) is None else "时序"
        print("   [%s] %s" % (mark, t))
    print("written:", OUT)


if __name__ == "__main__":
    main()
