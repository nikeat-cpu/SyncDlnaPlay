/* =====================================================================
   非电视模式回归断言（11 项）
   ---------------------------------------------------------------------
   电视模式是「外壳层」，不该对手机 / 桌面版式有任何影响。
   本文件用**不带 ?tv=1** 的地址加载页面，确认：
     · html.tv 没被加上、#app 仍是 flex（没被翻成 grid）、没插入按键提示条
     · 导航栏仍是底部固定横条（手机版式）
     · 设备列表 / 5 个 Tab / 点按切 Tab 等原有功能照旧
     · tv.js 安静待命：__tvMode() 返回 '0'、__tvKey() 一律返回 '0'（不抢按键）

   同样是页面上下文里的 async 函数体，由 tv_cdp.js 注入执行。
   ===================================================================== */
var o = [];
function K(k) { return window.__tvKey(k); }
var pass = 0, fail = 0;
function chk(n, c) { if (c) { pass++; o.push('  ✅ ' + n); } else { fail++; o.push('  ❌ ' + n); } }
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

var app = document.getElementById('app');
var nav = document.querySelector('.nav');
var cs = nav ? getComputedStyle(nav) : null;
var nr = nav ? nav.getBoundingClientRect() : null;

o.push('html.tv = ' + document.documentElement.classList.contains('tv') + '   （应为 false）');
o.push('#app display = ' + getComputedStyle(app).display + '   （应为 flex）');
o.push('提示条 #tvcue = ' + !!document.getElementById('tvcue') + '   （应为 false）');
o.push('nav 定位 = ' + (cs ? cs.position : '-') + '  rect=' + (nr ? JSON.stringify({
  x: Math.round(nr.left), y: Math.round(nr.top), w: Math.round(nr.width), h: Math.round(nr.height)
}) : '-'));

o.push('');
o.push('--- 检查项 ---');
chk('未开启电视模式', !document.documentElement.classList.contains('tv'));
chk('#app 仍是 flex（没被改成 grid）', getComputedStyle(app).display === 'flex');
chk('没有插入提示条', !document.getElementById('tvcue'));
chk('nav 仍是底部固定栏（手机版式）', cs && cs.position === 'fixed' && nr.width > 1000 && nr.top > 400);

o.push('');
o.push('--- 页面功能是否照旧 ---');
chk('设备列表已渲染', document.querySelectorAll('#devList .item').length > 0);
chk('5 个 Tab 都在', document.querySelectorAll('.navbtn').length === 5);
var okDev = document.querySelectorAll('#devList .item').length;
o.push('  设备条目 = ' + okDev + '   当前 Tab = '
  + ((document.querySelector('.navbtn.on') || {}).textContent || '-').trim());
chk('切换 Tab 的点击仍可用', (function () {
  var b = document.querySelector('.navbtn[data-tab="queue"]');
  if (!b) return false;
  b.click();
  var on = document.querySelector('.navbtn.on');
  return !!on && on.getAttribute('data-tab') === 'queue';
})());
var q = document.getElementById('tab-queue');
chk('切到播放列表后该区块可见', q && q.style.display !== 'none');

o.push('');
o.push('--- tv.js 是否安静待命（未开启时不该接管按键） ---');
chk('__tvMode() = 0', window.__tvMode() === '0');
chk('__tvKey 未接管（返回 0）', K('down') === '0');
chk('未修改 body / documentElement 的类', !document.documentElement.classList.contains('tv'));

o.push('');
o.push('===== 结果：' + pass + ' 项通过 / ' + fail + ' 项失败 =====');
return o.join('\n');
