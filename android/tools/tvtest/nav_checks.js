/* =====================================================================
   电视模式遥控器导航断言（33 项）
   ---------------------------------------------------------------------
   本文件是**页面上下文里的 async 函数体**，由 tv_cdp.js 注入执行，
   必须 return 一个报告字符串。

   全程只调 window.__tvKey(k) —— 也就是原生 MainActivity 真正调用的那个入口，
   走的是和遥控器按键完全相同的一条路，不绕开任何逻辑。

   13 个场景：
     1  初始焦点落在内容区第一行（不是工具栏）
     2  下移逐条走动
     3  右移进同行动作 / 左移回原行
     4  上移可爬回顶部工具栏
     5  左移进导航栏 + 栏内循环 + OK 切 Tab
     6  打开设置弹层，焦点被圈进弹层内容首项
     7  弹层内上下探索，焦点不逃出弹层
     8  滑条 ◀▶ 调值且焦点不跑丢
     9  返回键关弹层并把焦点送回打开前的按钮
     10 媒体键（⏯ ⏭ ⏮）被接管
     11 列表每秒重绘，连续 4.5s 监测焦点不丢
     12 DOM 键盘事件（蓝牙遥控器 / 实体键盘路径）
     13 返回键在导航栏上应「交回原生退出」
     14 强制整表重绘，焦点不许跳回第一项
   ===================================================================== */
var log = [];
function out(s) { log.push(s); }
function nm(el) {
  if (!el) return '(none)';
  var oc = el.getAttribute && el.getAttribute('onclick');
  var t = (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 24);
  return el.tagName + (el.id ? '#' + el.id : (el.className ? '.' + String(el.className).split(' ')[0] : ''))
    + (oc ? ' {' + oc + '}' : '') + ' "' + t + '"';
}
/* 元素身份签名：navbtn / 行内图标按钮都没有 id，必须带上祖先路径才分得清 */
function sig(el) {
  if (!el) return '';
  var path = [], n = el, d = 0;
  while (n && n !== document.body && d < 7) {
    var p = n.parentElement;
    path.unshift((p ? [].indexOf.call(p.children, n) : 0) + ':' + n.tagName);
    n = p; d++;
  }
  return path.join('/');
}
function cur() { return nm(document.activeElement); }
function K(k) { return window.__tvKey(k); }
function step(label, fn) {
  var r = '?';
  try { r = fn(); } catch (e) { out('  ' + label + '  !! ' + e.message); return; }
  out('  ' + label + '  [ret=' + r + ']  ' + cur());
}
function sheetOpen() { var s = document.getElementById('sheet'); return !!s && s.style.display !== 'none'; }
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function tabOf() { return ((document.querySelector('.navbtn.on') || {}).textContent || '-').replace(/\s+/g, ' ').trim(); }
function inRail(el) { var n = document.querySelector('.nav'); return !!(n && el && n.contains(el)); }
function inSheet(el) { var s = document.getElementById('sheet'); return !!(s && el && s.contains(el)); }
var pass = 0, fail = 0;
function chk(name, cond) { if (cond) { pass++; out('  ✅ ' + name); } else { fail++; out('  ❌ ' + name); } }

/* 用遥控器（纯方向键 + OK）走到导航栏并切到指定 Tab */
function goTab(key) {
  for (var i = 0; i < 12; i++) { if (inRail(document.activeElement)) break; K('left'); }
  for (var j = 0; j < 14; j++) {
    var nb = document.activeElement;
    if (nb && nb.getAttribute && nb.getAttribute('data-tab') === key) { K('ok'); return true; }
    K('down');
  }
  return false;
}
/* 用遥控器走到右上角的设置按钮 */
function goSettings() {
  for (var i = 0; i < 4; i++) K('left');            // 先甩到最左
  for (var u = 0; u < 8; u++) K('up');              // 一路向上（到顶会绕回/停住）
  for (var r = 0; r < 8; r++) {
    if (document.activeElement.id === 'btnSettings') return true;
    K('right');
  }
  return document.activeElement.id === 'btnSettings';
}

out('TV模式 = ' + window.__tvMode() + '    html.tv = ' + document.documentElement.classList.contains('tv'));
out('#app display = ' + getComputedStyle(document.getElementById('app')).display
  + '   提示条 = ' + !!document.getElementById('tvcue')
  + '   导航栏条目 = ' + document.querySelectorAll('.navbtn').length);
out('当前 Tab = ' + tabOf() + '    设备条目 = ' + document.querySelectorAll('#devList .item').length);

out('');
out('=== 1. 初始焦点应落在内容区第一行（不是工具栏） ===');
out('  ' + cur());
chk('初始焦点在列表行内', !!(document.activeElement.closest && document.activeElement.closest('.item')));

out('');
out('=== 2. 下移：列表内逐条走动（步数按实际行数取，不写死） ===');
/* 局域网上有几台音响是变的（4~6 台都见过），所以不能写死「按 4 下」：
   否则设备少的时候第 4 下会走到列表尽头、在同一区域内绕回工具栏，
   测试会把一个正常行为报成失败。 */
function rowIdx() {
  var rows = document.querySelectorAll('#devList .item');
  var it = document.activeElement.closest && document.activeElement.closest('.item');
  return it ? [].indexOf.call(rows, it) : -1;
}
var rows0 = document.querySelectorAll('#devList .item').length;
var startIdx = rowIdx();
var steps2 = Math.max(1, Math.min(4, rows0 - 1 - startIdx));
out('  列表共 ' + rows0 + ' 行，从第 ' + startIdx + ' 行起走 ' + steps2 + ' 步');
var stayed = true;
for (var i2 = 1; i2 <= steps2; i2++) {
  step('down #' + i2, function () { return K('down'); });
  if (rowIdx() < 0) stayed = false;
}
out('  落点 = 第 ' + rowIdx() + ' 行');
chk('下移过程中焦点始终在列表行内', stayed);
chk('下移确实逐条前进', rowIdx() > startIdx);

out('');
out('=== 3. 右移进入行内动作 / 左移返回 ===');
/* 焦点得先在列表行里，「行内动作」才有意义；万一被上面的用例带出列表就先爬回来 */
for (var b3 = 0; b3 < 6 && rowIdx() < 0; b3++) K('up');
var inRow3 = rowIdx() >= 0;
var rowSig = sig(document.activeElement);
step('right', function () { return K('right'); });
var actInRow = inRow3 && !!(document.activeElement.closest && document.activeElement.closest('.item'));
step('left ', function () { return K('left'); });
out('  回到原行 = ' + (sig(document.activeElement) === rowSig));
chk('右移进入行内动作按钮', actInRow);
chk('左移能回到原行', sig(document.activeElement) === rowSig);

out('');
out('=== 4. 上移：应能爬到顶部工具栏 ===');
var topHit = false;
for (var j = 1; j <= 12; j++) {
  K('up');
  var ae = document.activeElement;
  if (ae && ae.closest && !ae.closest('.item') && !inRail(ae)) topHit = true;
}
out('  ' + cur());
chk('上移可离开列表回到工具栏', topHit);

out('');
out('=== 5. 左移进入左侧导航栏（电视模式的关键路径） ===');
var inRailNow = false;
for (var m = 1; m <= 10 && !inRailNow; m++) { K('left'); inRailNow = inRail(document.activeElement); }
out('  已进入导航栏 = ' + inRailNow + '  →  ' + cur());
chk('左键能进入导航栏', inRailNow);
out('  --- 导航栏内上下移动（到底应绕回栏内，而不是掉进底部播放条） ---');
var railSeen = [];
for (var r2 = 1; r2 <= 8; r2++) {
  K('down');
  if (inRail(document.activeElement)) {
    var tx = (document.activeElement.textContent || '').replace(/\s+/g, ' ').trim();
    if (railSeen.indexOf(tx) < 0) railSeen.push(tx);
  }
}
out('  导航栏可达 Tab: ' + railSeen.join(' / '));
chk('上下可走遍全部 5 个 Tab（含绕回）', railSeen.length === 5);
chk('焦点始终留在导航栏内', inRail(document.activeElement));
var tabBefore = tabOf();
for (var s2 = 0; s2 < 6; s2++) { if (tabOf() !== tabBefore) break; K('down'); }
step('ok（切换 Tab）', function () { return K('ok'); });
out('  Tab: ' + tabBefore + ' → ' + tabOf() + '   可见区块 = '
  + [].filter.call(document.querySelectorAll('.tab'), function (t) { return t.style.display !== 'none'; })
    .map(function (t) { return t.id; }).join(','));
chk('OK 在导航栏上可切换 Tab', tabOf() !== tabBefore);

out('');
out('=== 6. 打开设置弹层：焦点应被圈进弹层内容的第一个条目 ===');
out('  切回「我的设备」Tab = ' + goTab('devices'));
var found = goSettings();
out('  命中设置按钮 = ' + found + '  →  ' + cur());
step('ok（打开设置）', function () { return K('ok'); });
out('  弹层已打开 = ' + sheetOpen() + '    标题 = ' + ((document.getElementById('sheetTitle') || {}).textContent || '-'));
out('  焦点 = ' + cur());
chk('设置弹层已打开', sheetOpen());
chk('焦点已进入弹层', inSheet(document.activeElement));
chk('焦点落在弹层内容项（不是右上角关闭按钮）',
  inSheet(document.activeElement) && document.activeElement.id !== 'sheetClose'
  && !!(document.getElementById('sheetBody') && document.getElementById('sheetBody').contains(document.activeElement)));

out('');
out('=== 7. 弹层内上下探索（焦点必须留在弹层内） ===');
var seen = [];
for (var p = 0; p < 18; p++) {
  K('down');
  var sv = (document.activeElement.textContent || document.activeElement.tagName || '').replace(/\s+/g, ' ').trim().slice(0, 18);
  if (sv && seen.indexOf(sv) < 0) seen.push(sv);
}
out('  弹层内可达条目 ' + seen.length + ' 个：' + seen.join(' | '));
chk('焦点始终留在弹层内', inSheet(document.activeElement));
chk('弹层内可访问多个条目', seen.length >= 6);

out('');
out('=== 8. 滑条 ◀▶ 调值（电视上比拖拽好用） ===');
/* 从弹层内容的第一个条目往下走，滑条应很快出现（歌词字号那两条） */
var kr = false;
for (var q = 0; q < 14 && !kr; q++) {
  K('down');
  var a3 = document.activeElement;
  if (a3 && a3.tagName === 'INPUT' && a3.type === 'range') kr = true;
}
out('  走到滑条 = ' + kr + (kr ? '   当前值 = ' + document.activeElement.value : ''));
if (kr) {
  var el = document.activeElement;
  var v0 = parseFloat(el.value);
  K('right'); K('right'); K('right');
  var v1 = parseFloat(el.value);
  out('  按 3 次 ▶ : ' + v0 + ' → ' + v1);
  K('left'); K('left'); K('left');
  var v2 = parseFloat(el.value);
  out('  再按 3 次 ◀ : → ' + v2);
  chk('▶ 增大滑条值', v1 > v0);
  chk('◀ 减小滑条值', v2 < v1);
  chk('调滑条时焦点没跑丢', document.activeElement === el);
}
chk('弹层内容里能走到滑条', kr);

out('');
out('=== 9. 返回键分级：关弹层 → 焦点回到弹层外 ===');
var wasOpen = sheetOpen();
var backRet = K('back');
out('  关闭前弹层开=' + wasOpen + '  back ret=' + backRet + '  关闭后=' + !sheetOpen());
chk('返回键可关闭弹层', wasOpen && !sheetOpen());
await sleep(400);            // 给 restore 的 90ms 防抖留时间
out('  关闭后焦点 = ' + cur());
chk('关闭弹层后焦点回到主界面', !inSheet(document.activeElement));
chk('关闭弹层后焦点回到打开前的设置按钮', document.activeElement.id === 'btnSettings');

out('');
out('=== 10. 媒体键（遥控器硬键）是否被接管 ===');
var r1 = K('togglePlay'), r2 = K('volUp'), r3 = K('volDown'), r4 = K('next');
out('  togglePlay=' + r1 + '  volUp=' + r2 + '  volDown=' + r3 + '  next=' + r4);
chk('媒体键全部被接管', r1 === '1' && r2 === '1' && r3 === '1' && r4 === '1');

out('');
out('=== 11. 列表重绘后焦点是否保持（连续监测 4.5 秒） ===');
K('down'); K('down');
var before = sig(document.activeElement);
var beforeInRow = !!(document.activeElement.closest && document.activeElement.closest('.item'));
out('  重绘前 = ' + cur() + '   （在列表行内 = ' + beforeInRow + '）');
/* 单点采样会「撞运气」：重绘空窗只有百来毫秒，采到就是失败、没采到就是通过。
   改成每 100ms 采一次，测的是「焦点到底丢没丢、丢了多久」这个真实行为。 */
var dropMs = 0, dropCount = 0, bodySeen = false, wasOk = true;
for (var t11 = 0; t11 < 45; t11++) {
  await sleep(100);
  var ae = document.activeElement;
  if (ae === document.body || ae === document.documentElement) bodySeen = true;
  var inRow = !!(ae && ae.closest && ae.closest('.item'));
  if (!inRow) { dropMs += 100; if (wasOk) { dropCount++; wasOk = false; } }
  else wasOk = true;
}
var after = sig(document.activeElement);
out('  重绘后 = ' + cur());
out('  监测 4.5 秒：焦点离开列表累计 ' + dropMs + 'ms / ' + dropCount + ' 次，曾落到 body = ' + bodySeen);
chk('重绘后焦点仍在列表行内', !!(document.activeElement.closest && document.activeElement.closest('.item')));
chk('重绘后焦点保持在同一元素', before === after);
chk('重绘的瞬间焦点也不丢失（累计 < 100ms）', dropMs < 100);
chk('焦点从未掉到 body', !bodySeen);

out('');
out('=== 12. DOM 键盘事件（蓝牙遥控器 / 实体键盘路径） ===');
var k0el = document.activeElement;
k0el.setAttribute('data-tvtest-src', '1');
var t0 = sig(k0el);
document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
await sleep(60);
var moved = !document.activeElement.hasAttribute('data-tvtest-src');
out('  ArrowDown 前 = ' + nm(k0el));
out('  ArrowDown 后 = ' + nm(document.activeElement));
try { k0el.removeAttribute('data-tvtest-src'); } catch (e) { }
chk('DOM ArrowDown 被接管且焦点确实移动', moved);
chk('移动后不是同一个元素', sig(document.activeElement) !== t0);

out('');
out('=== 13. 返回键在导航栏上应「交回原生退出」 ===');
for (var z = 0; z < 12; z++) { K('left'); if (inRail(document.activeElement)) break; }
var onRail = inRail(document.activeElement);
out('  当前在导航栏 = ' + onRail + '  →  ' + cur());
var br = window.__onBack();
out('  __onBack() = ' + JSON.stringify(br) + '   （原生端只认字符串 "exit"）');
chk('在导航栏上返回键交出 "exit"', onRail && br === 'exit');

out('');
out('=== 14. 强制整表重绘：焦点不许跳回第一项 ===');
/* app.js 每次轮询就是「整段 innerHTML 替换」，被替换掉的节点会把焦点一起带走。
   这里原样复刻一次，验证焦点会落回原位置——而不是遥控器上最恼人的「莫名弹回顶部」。 */
var devList14 = document.getElementById('devList');
/* 测试 13 把焦点留在了左侧导航栏里，先横向走回内容区 */
for (var esc14 = 0; esc14 < 8 && inRail(document.activeElement); esc14++) K('right');
out('  已离开导航栏 = ' + !inRail(document.activeElement) + '  →  ' + cur());
var rowsBefore = document.querySelectorAll('#devList .item');
/* 同样不能写死「第 3 行」：设备少时列表可能只有 4 行。取「尽可能靠后」为目标，
   只要不是第一行，就能验出「重绘后有没有跳回顶部」这件事。 */
var tgt14 = Math.max(1, Math.min(3, rowsBefore.length - 1));
var itBefore = document.activeElement.closest && document.activeElement.closest('.item');
var idxBefore = itBefore ? [].indexOf.call(rowsBefore, itBefore) : -1;
for (var g14 = 0; g14 < 14 && idxBefore < tgt14; g14++) {
  K('down');
  rowsBefore = document.querySelectorAll('#devList .item');
  itBefore = document.activeElement.closest && document.activeElement.closest('.item');
  idxBefore = itBefore ? [].indexOf.call(rowsBefore, itBefore) : -1;
}
out('  重绘前所在行 = ' + idxBefore + ' / ' + document.querySelectorAll('#devList .item').length
  + '（目标 ≥ ' + tgt14 + '）   ' + cur());
devList14.innerHTML = devList14.innerHTML;      // 与 app.js 相同的重绘方式
await sleep(0);                                 // 让 MutationObserver 的微任务跑完
var rowsAfter = document.querySelectorAll('#devList .item');
var itAfter = document.activeElement.closest && document.activeElement.closest('.item');
var idxAfter = itAfter ? [].indexOf.call(rowsAfter, itAfter) : -1;
out('  重绘后所在行 = ' + idxAfter + '   ' + cur());
chk('重绘前确实停在靠后的行', idxBefore >= tgt14);
chk('整表重绘后焦点还在列表里', idxAfter >= 0);
chk('整表重绘后焦点没跳回第一项', idxAfter >= tgt14);

out('');
out('===== 结果：' + pass + ' 项通过 / ' + fail + ' 项失败 =====');
out('__TVTEST_DONE__');
return log.join('\n');
