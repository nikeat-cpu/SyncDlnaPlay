#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
在线歌词能力实测（跨全部内置音源）
==================================
E2E 里「在线歌词接口」这一项是宽松判定（音源没提供也算通过），
所以它无法回答一个关键问题：**到底有没有音源能给出歌词？**

这个探针把 5 个音源逐个搜一遍「周杰伦」，各取前 3 首调 getLyric，
把「拿到多少字符 / 报什么错」如实打出来，用来判断歌词功能对在线曲目
是否真的可用（用户明确要求「播放时同步歌词显示」）。

用法：
    python tools/probe_lyric.py
前置：build/classes 与 build/livetest 已由 build.sh / run_e2e.sh 产出。
"""
import io
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, ".."))
WWW = os.path.join(PROJ, "app", "assets", "www")
JDK = "D:/android-toolchain/jdk17"

sys.path.insert(0, HERE)
from make_e2e_page import SHIM  # noqa: E402

DRIVER = """<script>
/* ==== 在线歌词探针 ==== */
(async function () {
  var out = [];
  function push(o) { out.push(o); }
  try {
    await loadProviders();
    var provs = (S.online.plugins || []).map(function (p) { return p.platform; });
    if (!provs.length) push({ provider: 'FATAL', err: '没有载入任何音源' });
    for (var i = 0; i < provs.length; i++) {
      var p = provs[i];
      var r = { provider: p, items: 0, lrcLen: 0, title: '', sample: '', err: '' };
      try {
        document.getElementById('onlineProvider').value = p;
        document.getElementById('onlineQ').value = '周杰伦';
        document.getElementById('onlineLimit').value = '3';
        await doOnlineSearch(1);
        var items = (S.online.items || []).slice(0, 3);
        r.items = items.length;
        if (!items.length) { r.err = '搜索无结果'; }
        for (var j = 0; j < items.length; j++) {
          try {
            var lr = await window.PluginHost.lyric({ provider: items[j].provider, id: items[j].id });
            if (lr && lr.lrc) {
              r.lrcLen = lr.lrc.length;
              r.title = items[j].title;
              r.sample = lr.lrc.replace(/\\s+/g, ' ').slice(0, 70);
              break;
            }
            r.err = (lr && lr.error) || '插件返回空';
          } catch (e) { r.err = '调用异常: ' + (e.message || e); }
        }
      } catch (e) { r.err = '搜索异常: ' + (e.message || e); }
      push(r);
    }
  } catch (e) { push({ provider: 'FATAL', err: String(e && e.message || e) }); }
  var pre = document.createElement('pre');
  pre.id = 'probe-out';
  pre.textContent = 'PROBE=' + JSON.stringify(out);
  document.body.appendChild(pre);
  document.title = 'PROBE-DONE';
})();
</script>"""


def build_page():
    src = io.open(os.path.join(WWW, "index.html"), "r", encoding="utf-8").read()
    marker = '<script src="plugins-runtime.js"></script>'
    if marker not in src:
        raise SystemExit("index.html 里没有找到 plugins-runtime.js 引用")
    src = src.replace(marker, SHIM + marker, 1)
    src = src.replace("</body>", DRIVER + "</body>", 1)
    out = os.path.join(WWW, "_lyricprobe.html")
    io.open(out, "w", encoding="utf-8", newline="").write(src)
    return out


def main():
    page = build_page()
    log = io.open(os.path.join(PROJ, "build", "lyricprobe.log"), "w", encoding="utf-8")
    srv = subprocess.Popen(
        [os.path.join(JDK, "bin", "java.exe"), "-Dfile.encoding=UTF-8",
         "-cp", "build/classes;build/livetest;libs/*", "LiveServer"],
        cwd=PROJ, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        ready = False
        for _ in range(60):
            try:
                if "READY" in io.open(os.path.join(PROJ, "build", "lyricprobe.log"),
                                      encoding="utf-8", errors="ignore").read():
                    ready = True
                    break
            except IOError:
                pass
            time.sleep(0.5)
        if not ready:
            print("桌面服务没起来，见 build/lyricprobe.log")
            return 2

        from playwright.sync_api import sync_playwright
        url = "file:///" + page.replace("\\", "/")
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=[
                "--allow-file-access-from-files", "--disable-web-security",
                "--no-sandbox", "--disable-gpu"])
            pg = b.new_context(viewport={"width": 420, "height": 900}).new_page()
            pg.goto(url, wait_until="load", timeout=60000)
            try:
                pg.wait_for_function("() => document.getElementById('probe-out')", timeout=180000)
            except Exception as e:
                print("等待探针超时:", e)
            raw = pg.eval_on_selector("#probe-out", "el => el.textContent")
            b.close()

        m = re.search(r"PROBE=(\[.*\])", raw or "", re.S)
        if not m:
            print("没拿到结果")
            return 1
        rows = json.loads(m.group(1))
        print("%-10s %5s %8s  %s" % ("音源", "结果数", "歌词字符", "说明"))
        print("-" * 74)
        any_ok = False
        for r in rows:
            ok = r.get("lrcLen", 0) > 0
            any_ok = any_ok or ok
            note = (r.get("title", "") + " | " + r.get("sample", "")) if ok else (r.get("err") or "")
            print("%-10s %5s %8s  %s" % (
                r.get("provider", "?"), r.get("items", 0),
                r.get("lrcLen", 0) or "-", note))
        print("-" * 74)
        print("结论：%s" % ("至少一个音源能提供歌词 ✓" if any_ok else "所有音源都没给出歌词 ✗"))
        return 0 if any_ok else 1
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
        log.close()
        try:
            os.remove(page)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
