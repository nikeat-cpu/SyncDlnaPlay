# -*- coding: utf-8 -*-
"""
v2.2 补丁：把 E2E 里「形同虚设」的歌词检查换成真检查
=====================================================
改动前的问题：
  1) '在线歌词接口' 是无条件 log(true)，音源不给歌词也算通过 —— 假绿。
     而且它只试 it0（解析阶段切过音源后，it0 可能是 bilibili —— 本来就没有歌词），
     所以永远只能打印「该音源未提供」。
  2) '歌词 LRC 解析' 只覆盖 [mm:ss.xx]，覆盖不到元力KW 的 [ss.xx] 纯秒格式。

改动后：
  - LRC 解析覆盖 标准 / 纯秒 / 共句 三种写法，任一不达标即失败。
  - 在线歌词逐个音源找，至少要有一个音源能给出歌词，否则失败；
    找到的那首同时留给后面的「歌词面板渲染」用，避免面板检查也测到 bilibili。
"""
import ast
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "make_e2e_page.py")

s = io.open(P, encoding="utf-8").read()

# ---------- 1) 歌词 LRC 解析 + 在线歌词接口 ----------
OLD = """      /* 歌词：LRC 解析（纯函数，最该稳的一环） */
      try {
        var L = parseLrc('[00:12.34]第一行\\\\n[00:20.00]第二行\\\\n[01:05.5]第三行');
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
"""

NEW = """      /* 歌词：LRC 解析（纯函数，最该稳的一环；覆盖标准/纯秒/共句三种写法） */
      try {
        var L = parseLrc('[00:12.34]第一行\\\\n[00:20.00]第二行\\\\n[01:05.5]第三行');
        var okStd = L.length === 3
          && Math.abs(L[0].t - 12.34) < 0.02
          && Math.abs(L[1].t - 20) < 0.02
          && Math.abs(L[2].t - 65.5) < 0.02;
        /* 元力KW 用的是 [秒.百分秒] 且「一行一句」的行内写法 */
        var L2 = parseLrc('[0.0]夜曲 - 周杰伦 [4.99]词：方文山 [9.98]曲：周杰伦');
        var okSec = L2.length === 3
          && Math.abs(L2[0].t - 0) < 0.02
          && Math.abs(L2[1].t - 4.99) < 0.02
          && Math.abs(L2[2].t - 9.98) < 0.02
          && L2[1].text === '词：方文山';
        /* 标准写法里一行多个时间戳共用同一句 */
        var L3 = parseLrc('[00:10.00][01:20.00]副歌');
        var okShare = L3.length === 2 && L3[0].text === '副歌'
          && Math.abs(L3[1].t - 80) < 0.02;
        log('歌词 LRC 解析', okStd && okSec && okShare,
          '标准=' + okStd + ' 纯秒=' + okSec + ' 共句=' + okShare);
      } catch (e) { log('歌词 LRC 解析', false, e.message); }

      /* 歌词：向插件要歌词（逐个音源找，至少要有一个音源能给出歌词） */
      var lyricItem = null;
      try {
        var provs = (S.online.plugins || []).map(function (p) { return p.platform; });
        var got = null, tried = [];
        for (var pi = 0; pi < provs.length && !got; pi++) {
          try {
            document.getElementById('onlineProvider').value = provs[pi];
            document.getElementById('onlineQ').value = '周杰伦';
            document.getElementById('onlineLimit').value = '3';
            await doOnlineSearch(1);
            var cand = (S.online.items || []).slice(0, 3);
            for (var ci = 0; ci < cand.length && !got; ci++) {
              var lr = await window.PluginHost.lyric({ provider: cand[ci].provider, id: cand[ci].id });
              if (lr && lr.lrc) {
                got = { provider: provs[pi], len: lr.lrc.length, title: cand[ci].title };
                lyricItem = cand[ci];
              }
            }
            tried.push(provs[pi] + ':' + ((S.online.items || []).length));
          } catch (e) { tried.push(provs[pi] + ':err'); }
        }
        log('在线歌词接口', !!got, got
          ? (got.provider + ' / ' + got.title + ' 拿到 ' + got.len + ' 字符')
          : ('所有音源均未提供 [' + tried.join(' ') + ']'));
      } catch (e) { log('在线歌词接口', false, e.message); }
"""

n = s.count(OLD)
assert n == 1, "歌词检查块没找到或不唯一: %d" % n
s = s.replace(OLD, NEW, 1)

# ---------- 2) 歌词面板渲染：用真的拿到过歌词的那首 ----------
OLD2 = """        if (it0) {
          playerSheet();                                  // 真正的入口
          await loadLyric({ source: 'online', provider: it0.provider, id: it0.id, title: it0.title });"""
NEW2 = """        var useItem = lyricItem || it0;
        if (useItem) {
          playerSheet();                                  // 真正的入口
          await loadLyric({ source: 'online', provider: useItem.provider, id: useItem.id, title: useItem.title });"""
n2 = s.count(OLD2)
assert n2 == 1, "歌词面板渲染块没找到或不唯一: %d" % n2
s = s.replace(OLD2, NEW2, 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(s)

chk = io.open(P, encoding="utf-8").read()
for k in ["歌词 LRC 解析", "在线歌词接口", "歌词面板渲染", "lyricItem", "okSec", "okShare"]:
    print("  %-16s %s" % (k, k in chk))
ast.parse(chk)
print("Python 语法 OK")
