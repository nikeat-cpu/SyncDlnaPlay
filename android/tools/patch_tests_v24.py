# -*- coding: utf-8 -*-
"""v2.4 音量收敛：把 E2E 里过时的「设备页音量滑条」断言换成真正能失败的新断言。

旧断言只统计 `devVolSet(` 出现次数 —— 内联滑条被删后它就是空断言。
新增：
  · 音量面板：滑条 + 含「音量」字样 + − / + 两个按钮都在
  · 音量加减按钮：单击 − 精确 −1、单击 + 精确 +1（真跑一遍逻辑）
  · 音量入口唯一：设备卡片有入口、但没有旧的内联滑条
"""
import io
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
F = os.path.join(ROOT, "tools", "make_e2e_page.py")

old = """      /* \u97f3\u91cf\u9762\u677f\uff1a\u9009\u4e2d\u4e00\u53f0\u8bbe\u5907\u540e\u5e94\u51fa\u73b0\u6ed1\u6761 */
      try {
        var dev = (S.state && S.state.devices && S.state.devices[0]) || null;
        if (dev) {
          dev.selected = true;
          dev.volume = 40;
          S.out = 'dlna';
          volumeSheet();
          var body = document.getElementById('sheetBody').innerHTML;
          var hasRange = body.indexOf('type="range"') >= 0;
          var hasVolWord = body.indexOf('\u97f3\u91cf') >= 0;
          log('\u97f3\u91cf\u9762\u677f', hasRange && hasVolWord, '\u6ed1\u6761=' + hasRange + ' \u542b\u97f3\u91cf\u5b57\u6837=' + hasVolWord);
          closeSheet();
        } else { log('\u97f3\u91cf\u9762\u677f', false, '\u6ca1\u53d1\u73b0\u8bbe\u5907'); }
      } catch (e) { log('\u97f3\u91cf\u9762\u677f', false, e.message); }

      /* \u8bbe\u5907\u9875\u97f3\u91cf\u6ed1\u6761\uff1a\u5df2\u9009\u8bbe\u5907\u5e94\u6e32\u67d3\u51fa range */
      try {
        var dev2 = (S.state && S.state.devices && S.state.devices[0]) || null;
        if (dev2) {
          dev2.selected = true;
          renderDevices();
          var html = document.getElementById('devList').innerHTML;
          var n = html.split('devVolSet(').length - 1;
          log('\u8bbe\u5907\u9875\u97f3\u91cf\u6ed1\u6761', n >= 1, '\u51fa\u73b0 ' + n + ' \u4e2a');
        } else { log('\u8bbe\u5907\u9875\u97f3\u91cf\u6ed1\u6761', false, '\u6ca1\u53d1\u73b0\u8bbe\u5907'); }
      } catch (e) { log('\u8bbe\u5907\u9875\u97f3\u91cf\u6ed1\u6761', false, e.message); }
"""

new = """      /* \u97f3\u91cf\u9762\u677f\uff1a\u6ed1\u6761 + \u6587\u6848 + \u2212 / + \u7cbe\u8c03\u6309\u94ae\u90fd\u5e94\u5728 */
      try {
        var dev = (S.state && S.state.devices && S.state.devices[0]) || null;
        if (dev) {
          dev.selected = true;
          dev.volume = 40;
          S.out = 'dlna';
          volumeSheet();
          var body = document.getElementById('sheetBody').innerHTML;
          var hasRange = body.indexOf('type="range"') >= 0;
          var hasVolWord = body.indexOf('\u97f3\u91cf') >= 0;
          var hasBtns = !!document.getElementById('volDec') && !!document.getElementById('volInc');
          log('\u97f3\u91cf\u9762\u677f', hasRange && hasVolWord && hasBtns,
            '\u6ed1\u6761=' + hasRange + ' \u542b\u97f3\u91cf\u5b57\u6837=' + hasVolWord + ' \u52a0\u51cf\u6309\u94ae=' + hasBtns);
          closeSheet();
        } else { log('\u97f3\u91cf\u9762\u677f', false, '\u6ca1\u53d1\u73b0\u8bbe\u5907'); }
      } catch (e) { log('\u97f3\u91cf\u9762\u677f', false, e.message); }

      /* \u52a0\u51cf\u6309\u94ae\uff1a\u5355\u51fb\u5e94\u7cbe\u786e \u00b11\uff08\u771f\u8dd1\u4e00\u904d\u903b\u8f91\uff09 */
      try {
        var dev2 = (S.state && S.state.devices && S.state.devices[0]) || null;
        if (dev2) {
          dev2.selected = true;
          dev2.volume = 40;
          S.out = 'dlna';
          volumeSheet();
          var before = parseInt(document.getElementById('volNum').textContent, 10);
          var ev = { preventDefault: function () { } };
          volHold(-1, ev); volAutoStop();
          var down = parseInt(document.getElementById('volNum').textContent, 10);
          volHold(1, ev); volAutoStop();
          var up = parseInt(document.getElementById('volNum').textContent, 10);
          log('\u97f3\u91cf\u52a0\u51cf\u6309\u94ae', down === before - 1 && up === before,
            ' ' + before + ' \u2192\u51cf\u4e00 ' + down + ' \u2192\u52a0\u4e00 ' + up);
          closeSheet();
        } else { log('\u97f3\u91cf\u52a0\u51cf\u6309\u94ae', false, '\u6ca1\u53d1\u73b0\u8bbe\u5907'); }
      } catch (e) { log('\u97f3\u91cf\u52a0\u51cf\u6309\u94ae', false, e.message); }

      /* \u97f3\u91cf\u5165\u53e3\u552f\u4e00\uff1a\u8bbe\u5907\u5361\u7247\u6709\u5165\u53e3\uff0c\u4f46\u65e7\u7684\u5185\u8054\u6ed1\u6761\u5df2\u5220\u5e72\u51c0 */
      try {
        var dev3 = (S.state && S.state.devices && S.state.devices[0]) || null;
        if (dev3) {
          dev3.selected = true;
          renderDevices();
          var html = document.getElementById('devList').innerHTML;
          var entry = html.split('volumeSheet(').length - 1;
          var legacy = html.split('devVolSet(').length - 1;
          log('\u97f3\u91cf\u5165\u53e3\u552f\u4e00', entry >= 1 && legacy === 0,
            '\u5165\u53e3=' + entry + ' \u65e7\u6ed1\u6761=' + legacy);
        } else { log('\u97f3\u91cf\u5165\u53e3\u552f\u4e00', false, '\u6ca1\u53d1\u73b0\u8bbe\u5907'); }
      } catch (e) { log('\u97f3\u91cf\u5165\u53e3\u552f\u4e00', false, e.message); }
"""

s = io.open(F, encoding="utf-8").read()
n = s.count(old)
if n == 0 and "\u97f3\u91cf\u5165\u53e3\u552f\u4e00" in s:
    print("  [SKIP] E2E 音量断言（已应用过）")
else:
    assert n == 1, "命中 %d 次（应为 1）" % n
    io.open(F, "w", encoding="utf-8", newline="\n").write(s.replace(old, new, 1))
    print("  [OK] E2E 音量断言已更新")
