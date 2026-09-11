# -*- coding: utf-8 -*-
"""给桌面 E2E 测试页补充 v2.1 新功能的检查（歌词 / 音量面板 / 曲库管理）。"""
import io
import os
import sys

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_e2e_page.py")
s = io.open(P, encoding="utf-8").read()

ANCHOR = """    } catch (e) {
      log('异常', false, (e && e.message) || String(e));
    }
    finish();"""

NEW = """      /* ---------- v2.1 新增功能的检查 ---------- */

      var it0 = (S.online.items || [])[0] || null;

      /* 歌词：LRC 解析（纯函数，最该稳的一环） */
      try {
        var L = parseLrc('[00:12.34]第一行\\n[00:20.00]第二行\\n[01:05.5]第三行');
        var okLrc = L.length === 3
          && Math.abs(L[0].t - 12.34) < 0.02
          && Math.abs(L[1].t - 20) < 0.02
          && Math.abs(L[2].t - 65.5) < 0.02;
        log('歌词 LRC 解析', okLrc,
          L.length + ' 行 / ' + L.map(function (x) { return x.t; }).join(',') + ' 秒');
      } catch (e) { log('歌词 LRC 解析', false, e.message); }

      /* 歌词：向插件要歌词（音源可选能力，取不到不算失败） */
      try {
        if (it0 && window.PluginHost) {
          var lr = await window.PluginHost.lyric({ provider: it0.provider, id: it0.id });
          log('在线歌词接口', true, (lr && lr.lrc)
            ? ('拿到 ' + lr.lrc.length + ' 字符')
            : ('该音源未提供(' + ((lr && lr.error) || '无') + ')'));
        } else {
          log('在线歌词接口', false, '没有可用曲目');
        }
      } catch (e) { log('在线歌词接口', false, e.message); }

      /* 歌词：走完整 UI 链路（loadLyric -> renderLyric） */
      try {
        if (it0) {
          playerSheet();                                  // 真正的入口
          await loadLyric({ source: 'online', provider: it0.provider, id: it0.id, title: it0.title });
          var box = document.getElementById('lyricBox');
          log('歌词面板渲染', !!box,
            '行数=' + ((S.lyric.lines || []).length) + ' 提示=' + (S.lyric.msg || '无'));
          closeSheet();
        } else { log('歌词面板渲染', false, '没有可用曲目'); }
      } catch (e) { log('歌词面板渲染', false, e.message); }

      /* 音量面板：选中一台设备后应出现滑条 */
      try {
        var dev = (S.state && S.state.devices && S.state.devices[0]) || null;
        if (dev) {
          dev.selected = true;
          dev.volume = 40;
          S.out = 'dlna';
          volumeSheet();
          var body = document.getElementById('sheetBody').innerHTML;
          var hasRange = body.indexOf('type="range"') >= 0;
          var hasVolWord = body.indexOf('音量') >= 0;
          log('音量面板', hasRange && hasVolWord, '滑条=' + hasRange + ' 含音量字样=' + hasVolWord);
          closeSheet();
        } else { log('音量面板', false, '没发现设备'); }
      } catch (e) { log('音量面板', false, e.message); }

      /* 设备页音量滑条：已选设备应渲染出 range */
      try {
        var dev2 = (S.state && S.state.devices && S.state.devices[0]) || null;
        if (dev2) {
          dev2.selected = true;
          renderDevices();
          var html = document.getElementById('devList').innerHTML;
          var n = (html.match(/devVolSet\\(/g) || []).length;
          log('设备页音量滑条', n >= 1, '出现 ' + n + ' 个');
        } else { log('设备页音量滑条', false, '没发现设备'); }
      } catch (e) { log('设备页音量滑条', false, e.message); }

      /* 曲库管理面板：桌面没有 Android 桥，应优雅降级而不是报错 */
      try {
        await musicSourcesSheet();
        var sb = document.getElementById('sheetBody').innerHTML;
        var okDl = sb.indexOf('下载目录') >= 0;
        var okDir = sb.indexOf('音乐目录') >= 0;
        var okLog = sb.indexOf('运行日志') >= 0;
        log('曲库管理面板', okDl && okDir && okLog,
          '下载目录=' + okDl + ' 音乐目录=' + okDir + ' 运行日志=' + okLog);
        closeSheet();
      } catch (e) { log('曲库管理面板', false, e.message); }

      /* 迷你播放器的音量键应已绑定 */
      try {
        log('迷你播放器音量键', !!document.getElementById('miniVol'),
          document.getElementById('miniVol') ? '存在' : '缺失');
      } catch (e) { log('迷你播放器音量键', false, e.message); }

"""

n = s.count(ANCHOR)
print("锚点命中:", n)
if n != 1:
    raise SystemExit("锚点不唯一，放弃")

s = s.replace(ANCHOR, NEW + ANCHOR)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)

chk = io.open(P, encoding="utf-8").read()
for k in ["歌词 LRC 解析", "在线歌词接口", "歌词面板渲染", "音量面板",
          "设备页音量滑条", "曲库管理面板", "迷你播放器音量键"]:
    print("  %-18s %s" % (k, k in chk))
import ast
ast.parse(chk)
print("Python 语法 OK")
sys.exit(0)
