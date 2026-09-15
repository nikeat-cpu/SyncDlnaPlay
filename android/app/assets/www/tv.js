'use strict';
/* =====================================================================
   电视模式（Android TV / 机顶盒 / 遥控器）· tv.js
   ---------------------------------------------------------------------
   本文件是「外壳层」：app.js 的业务逻辑一行都不改，功能 100% 保留，
   只把「手指点」换成「遥控器选」——

     · 电视判定：原生端 isTv() / UA 特征 / ?tv=1 / 设置里手动开关
     · 焦点引擎：方向键在可见控件之间做空间导航，OK = click()
     · 遥控器语义（比触屏更直白）：
         滑条   ◀ ▶ 直接调值，松手后自动提交（不用拖）
         下拉框 OK 循环切换选项
         输入框 OK 弹出系统输入法
         返回   一级一级往上退，退到导航栏再按就退出
     · 列表每秒重绘也不会丢焦点（按元素签名恢复）
     · 底部按键提示条，文案随当前焦点变化

   原生侧（MainActivity）把 DPAD / OK / 媒体键转成 window.__tvKey()，
   返回 '1' 表示已处理，'0' 交回系统默认行为。
   ===================================================================== */
(function () {

  var $ = function (id) { return document.getElementById(id); };

  /* ------------------------------------------------------------ 1. 判定 */
  var FORCE = /[?&]tv=([01])/.exec(String(location.search || ''));

  function bridge(fn, a) {
    try {
      if (typeof Android !== 'undefined' && Android && typeof Android[fn] === 'function') {
        return a === undefined ? Android[fn]() : Android[fn](a);
      }
    } catch (e) { }
    return null;
  }
  function uaIsTv() {
    return /Android ?TV|Google ?TV|AFT[A-Z]|BRAVIA|SHIELD|MiBOX|MiTV|Mi TV|SmartTV|NetCast|Web0S|Tizen|TV ?Box/i
      .test(navigator.userAgent || '');
  }
  function auto() { return bridge('isTv') === '1' || uaIsTv(); }

  var on;
  if (FORCE) {
    on = (FORCE[1] === '1');
  } else {
    var sv = null;
    try { sv = localStorage.getItem('dlna_tv'); } catch (e) { }
    on = (sv === '1') ? true : (sv === '0' ? false : auto());
  }

  /* ------------------------------------------------------- 2. 状态变量 */
  var focused = null;      // 当前焦点元素
  var lastKey = '';        // 焦点签名（列表重绘后按它找回）
  var lastIdx = 0;         // 签名失效时的兜底下标
  var armed = false;       // 用户开始用遥控器后才接管焦点
  var userMoved = false;   // 用户是否已经按过键（没按之前允许自动落焦）
  var editing = false;     // 正在用输入法打字（把按键让给系统）
  var restoreTimer = null;
  var cueEl = null;
  var lastCue = null;      // 提示条上次渲染的文案（没变就不写 DOM）
  var curScope = null;     // 作用域变化跟踪（弹层 进/出）
  var appKey = '', appIdx = 0;

  var SEL = 'button,input,select,textarea,a[href],[onclick],.tvf';

  /* --------------------------------------------------------- 3. 工具 */
  function scope() {
    var sh = $('sheet');
    if (sh && sh.style.display !== 'none' && sh.getBoundingClientRect().height > 4) return sh;
    var su = $('setup');
    if (su && su.style.display !== 'none' && su.getBoundingClientRect().height > 4) return su;
    var ap = $('app');
    if (ap && ap.style.display !== 'none') return ap;
    return document.body;
  }
  function scopeIsSheet() { var sh = $('sheet'); return !!sh && scope() === sh; }

  function usable(el, r) {
    if (!el || el.disabled || el.hidden) return false;
    if (r.width < 2 || r.height < 2) return false;
    try { if (el.closest('.mask,.toast,.fx-hud,#tvcue')) return false; } catch (e) { }
    var cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    if (parseFloat(cs.opacity || '1') === 0) return false;
    return cs.pointerEvents !== 'none';
  }

  /* 快照：一次按键只量一次布局（电视盒子 CPU 弱，省着用） */
  var snap = null, snapAt = 0;
  function snapshot(force) {
    var now = Date.now();
    if (!force && snap && (now - snapAt) < 60) return snap;
    var sc = scope();
    var all = Array.prototype.slice.call(sc.querySelectorAll(SEL));
    if (sc.matches && sc.matches(SEL)) all.unshift(sc);
    var items = Array.prototype.slice.call(sc.querySelectorAll('.item'));
    var list = [], seen = {}, i, el, r;
    for (i = 0; i < all.length; i++) {
      el = all[i];
      r = el.getBoundingClientRect();
      if (!usable(el, r)) continue;
      var item = el.closest ? el.closest('.item') : null;
      var oc = el.getAttribute ? el.getAttribute('onclick') : null;
      if (item && oc) {
        // 同一行里指向同一动作的区域合并成一个焦点（如 图标区/标题区 都是 playOne(i)）
        var key = 'r' + items.indexOf(item) + ':' + oc;
        var prev = seen[key];
        if (prev) {
          if (r.width * r.height > prev.r.width * prev.r.height) {
            var at = list.indexOf(prev);
            if (at >= 0) list[at] = { el: el, r: r };
            seen[key] = { el: el, r: r };
          }
          continue;
        }
        var rec = { el: el, r: r };
        seen[key] = rec;
        list.push(rec);
        continue;
      }
      list.push({ el: el, r: r });
    }
    snap = { scope: sc, list: list, els: list.map(function (x) { return x.el; }) };
    snapAt = now;
    return snap;
  }
  function candidates(force) { return snapshot(force).els; }

  function keyOf(el) {
    var oc = el.getAttribute && el.getAttribute('onclick');
    if (oc) return 'oc:' + oc;
    if (el.id) return 'id:' + el.id;
    var t = (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 28);
    return 'tx:' + el.tagName + ':' + t;
  }

  /* 滚动容器（main / .sheet-bd 竖滚，.crumbs 横滚） */
  function scrollParent(el, axis) {
    var p = el.parentElement;
    while (p && p !== document.documentElement) {
      var cs = getComputedStyle(p);
      var ov = (axis === 'x') ? cs.overflowX : cs.overflowY;
      var big = (axis === 'x') ? (p.scrollWidth > p.clientWidth + 2)
        : (p.scrollHeight > p.clientHeight + 2);
      if (/(auto|scroll)/.test(ov) && big) return p;
      p = p.parentElement;
    }
    return null;
  }
  function ensureVisible(el) {
    var p = scrollParent(el, 'y');
    if (p) {
      var a = p.getBoundingClientRect(), b = el.getBoundingClientRect(), m = 16;
      if (b.top < a.top + m) p.scrollTop += (b.top - a.top) - m;
      else if (b.bottom > a.bottom - m) p.scrollTop += (b.bottom - a.bottom) + m;
    }
    var q = scrollParent(el, 'x');
    if (q) {
      var a2 = q.getBoundingClientRect(), b2 = el.getBoundingClientRect(), m2 = 24;
      if (b2.left < a2.left + m2) q.scrollLeft += (b2.left - a2.left) - m2;
      else if (b2.right > a2.right - m2) q.scrollLeft += (b2.right - a2.right) + m2;
    }
  }

  /* 「焦点组」：绕回时只在同一组内打转。
     不能只看「是否在滚动容器里」——导航栏和顶栏都不滚动，会被归成一组，
     结果在导航栏底部按一下会跳到顶栏，非常跳。 */
  var GRP = '.nav, .topbar, main, .sheet-bd, .sheet-hd, .crumbs, .pager';
  function group(el) {
    var g = (el && el.closest) ? el.closest(GRP) : null;
    return g || $('app') || document.body;
  }

  function focusEl(el, noScroll) {
    if (!el) return;
    if (focused && focused !== el) focused.classList.remove('tv-focus');
    focused = el;
    try { if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1'); } catch (e) { }
    try { el.focus({ preventScroll: true }); } catch (e) { try { el.focus(); } catch (e2) { } }
    try { el.classList.add('tv-focus'); } catch (e) { }
    lastKey = keyOf(el);
    var list = candidates();
    lastIdx = list.indexOf(el);
    if (!noScroll) { ensureVisible(el); snap = null; }
    drawCue();
  }

  /* ------------------------------------------------- 4. 空间导航算法 */
  function move(dir) {
    var s = snapshot();
    if (!s.list.length) return false;
    var act = document.activeElement;
    var cur = null, i;
    for (i = 0; i < s.list.length; i++) { if (s.list[i].el === act) { cur = s.list[i]; break; } }
    if (!cur) for (i = 0; i < s.list.length; i++) { if (s.list[i].el === focused) { cur = s.list[i]; break; } }
    if (!cur) {
      /* 列表刚重绘完、被替换掉的节点丢了焦点（activeElement 短暂变成 body），
         用户恰好在这个空窗里按了键。绝不能兜底跳回第一项——遥控器上会表现为
         「按一下就莫名弹回顶部」。按记住的签名 / 下标把原位置找回来。 */
      for (i = 0; i < s.list.length; i++) {
        if (keyOf(s.list[i].el) === lastKey) { cur = s.list[i]; break; }
      }
      if (cur) {
        focusEl(cur.el, true);
      } else {
        cur = s.list[Math.max(0, Math.min(s.list.length - 1, lastIdx))];
        focusEl(cur.el, true);
      }
    }

    var a = cur.r;
    var ax = a.left + a.width / 2, ay = a.top + a.height / 2;

    /* 左侧导航栏是纯竖排列表：上下键只在栏内循环。
       否则从最后一项按「下」会掉进底部的迷你播放条，栏内就再也回不来了。 */
    var rail = document.querySelector('.nav');
    var pool = s.list;
    if (rail && rail.contains(cur.el) && (dir === 'up' || dir === 'down')) {
      pool = [];
      for (i = 0; i < s.list.length; i++) { if (rail.contains(s.list[i].el)) pool.push(s.list[i]); }
    }

    var best = null, bestScore = Infinity;
    for (i = 0; i < pool.length; i++) {
      var rec = pool[i];
      if (rec === cur) continue;
      var b = rec.r;
      var bx = b.left + b.width / 2, by = b.top + b.height / 2;
      var dx = bx - ax, dy = by - ay, primary, secondary;
      // 主方向必须为正（留 4px 容差，容忍同一行内的轻微错位）
      if (dir === 'left') { if (dx > -4) continue; primary = -dx; secondary = Math.abs(dy); }
      else if (dir === 'right') { if (dx < 4) continue; primary = dx; secondary = Math.abs(dy); }
      else if (dir === 'up') { if (dy > -4) continue; primary = -dy; secondary = Math.abs(dx); }
      else { if (dy < 4) continue; primary = dy; secondary = Math.abs(dx); }

      // 投影重叠（同一行/同一列）优先，其余按「主向距离 + 横向偏移 × 权重」打分
      var ov = (dir === 'left' || dir === 'right')
        ? Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
        : Math.min(a.right, b.right) - Math.max(a.left, b.left);
      /* 上下移动时，若横向已有重叠，横向偏移的权重必须让位给纵向距离。
         否则「旁边一行小按钮」会因为更横向对齐，抢走「正下方但很宽的滑条」
         ——实测就是滑条被跳过、遥控器走不到。 */
      var w = ((dir === 'up' || dir === 'down') && ov > 0) ? 0.4 : 2.4;
      var score = primary + secondary * w + (ov > 0 ? 0 : 3000);
      if (score < bestScore) { bestScore = score; best = rec; }
    }

    /* 走到头就绕回同一滚动容器内的另一端。
       遥控器上没有「滑动」，到尽头若毫无反应，用户会以为界面卡住了。 */
    if (!best && (dir === 'up' || dir === 'down')) {
      var holder = group(cur.el);
      var pick = null, pickY = 0;
      for (i = 0; i < pool.length; i++) {
        var rc = pool[i];
        if (rc === cur) continue;
        if (group(rc.el) !== holder) continue;
        var cy = rc.r.top + rc.r.height / 2;
        if (!pick || (dir === 'down' ? cy < pickY : cy > pickY)) { pick = rc; pickY = cy; }
      }
      if (pick) { focusEl(pick.el); return true; }
    }

    if (!best) return false;
    focusEl(best.el);
    return true;
  }

  /* --------------------------------------------------- 5. 遥控器语义 */
  var commitTimer = null;

  function inRail(el) {
    var n = document.querySelector('.nav');
    return !!(n && el && n.contains(el));
  }

  function adjustRange(el, d) {
    var min = parseFloat(el.min); if (isNaN(min)) min = 0;
    var max = parseFloat(el.max); if (isNaN(max)) max = 100;
    var step = parseFloat(el.step);
    if (!step || step <= 0) step = Math.max(1, Math.round((max - min) / 100));  // 一次约 1%
    var v = (parseFloat(el.value) || 0) + d * step;
    v = Math.max(min, Math.min(max, Math.round(v * 100) / 100));
    el.value = v;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    // 停手 420ms 后才提交，避免连续按键把服务器刷爆
    clearTimeout(commitTimer);
    commitTimer = setTimeout(function () {
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }, 420);
    drawCue();
    return true;
  }

  function activate(el) {
    if (!el) return false;
    var tag = el.tagName;
    if (tag === 'INPUT') {
      if (el.type === 'range') return adjustRange(el, 1);
      if (el.type === 'checkbox' || el.type === 'radio' || el.type === 'button' || el.type === 'submit') {
        el.click(); return true;
      }
      // 文本输入：电视上不会自动弹键盘，这里主动唤起
      try { el.focus(); } catch (e) { }
      editing = true;
      sink();
      try { el.setSelectionRange && el.setSelectionRange(el.value.length, el.value.length); } catch (e) { }
      bridge('showKeyboard');
      drawCue();
      return true;
    }
    if (tag === 'SELECT') {
      // 电视上按 OK 循环切换，比「弹出列表再选」少一步
      var n = el.options.length;
      if (n > 1) {
        el.selectedIndex = (el.selectedIndex + 1) % n;
        el.dispatchEvent(new Event('change', { bubbles: true }));
      }
      return true;
    }
    try { el.click(); } catch (e) { }
    return true;
  }

  function blurEditing() {
    editing = false;
    sink();
    var a = document.activeElement;
    if (a && a.tagName === 'INPUT' && a.type !== 'range') { try { a.blur(); } catch (e) { } }
    bridge('hideKeyboard');
    setTimeout(function () { focusEl(focused || firstFocusable()); }, 0);
  }

  function firstFocusable() {
    var list = candidates(true);
    if (!list.length) return null;
    // 优先落在当前这张 Tab 的内容区，否则落到第一个（通常是左侧导航栏）
    var nb = document.querySelector('.navbtn.on');
    var tab = nb && nb.getAttribute('data-tab');
    var sec = tab ? $('tab-' + tab) : null;
    if (sec) {
      // 再优先落在列表第一行：一上来最想做的就是选设备 / 选曲目，而不是去点工具栏
      for (var k = 0; k < list.length; k++) {
        if (sec.contains(list[k]) && list[k].closest && list[k].closest('.item')) return list[k];
      }
      for (var i = 0; i < list.length; i++) { if (sec.contains(list[i])) return list[i]; }
    }
    return list[0];
  }

  /* 媒体键：直接驱动播放控制（电视遥控器上通常有一排） */
  function ctlAction(what) {
    if (typeof ctl !== 'function') return;
    if (what === 'playpause') {
      var playing = false;
      try { playing = !!(typeof nowPlaying === 'function' && nowPlaying().playing); } catch (e) { }
      ctl(playing ? 'pause' : 'play');
      return;
    }
    ctl(what);
  }
  /* 频道键 CH± 当音量键用（电视遥控器上就这两个最顺手） */
  function volumeStep(d) {
    if (typeof volAll !== 'function') return;
    var cur = 50;
    try {
      if (typeof avgVol === 'function' && typeof selectedDevices === 'function') cur = avgVol(selectedDevices());
    } catch (e) { }
    var v = Math.max(0, Math.min(100, Math.round(cur) + d));
    if (typeof toast === 'function') toast('音量 ' + v);
    volAll(v);
  }

  /* ------------------------------------------------- 6. 按键统一入口 */
  function handle(k) {
    if (!on) return false;
    k = String(k || '');
    if (!k) return false;
    armed = true;
    userMoved = true;                   // 用户一旦按键，就再也不自动改焦点

    if (editing) {
      // 打字期间只接管「返回」（收起键盘），其余交给系统输入法
      if (k === 'back') { blurEditing(); return true; }
      return false;
    }

    syncScope();                        // 进来的这一刻：弹层可能刚被打开 / 刚被关掉
    var _r = dispatch(k);
    syncScope();                        // 处理完再看一次：OK 点到的按钮可能刚开/关弹层
    return _r;
  }

  /* 真正的按键语义分发（handle 只负责前后各同步一次作用域） */
  function dispatch(k) {
    if (k === 'back') {
      if (scopeIsSheet()) { try { $('sheetClose').click(); } catch (e) { } return true; }
      var a = document.activeElement;
      if (!inRail(a)) { focusEl(document.querySelector('.navbtn.on') || firstFocusable()); return true; }
      return false;                       // 已在导航栏 → 交回原生退出 App
    }

    var el = document.activeElement;
    var list = candidates();
    if (!el || list.indexOf(el) < 0) el = focused;

    if (k === 'ok') return activate(el);
    if (k === 'togglePlay') { ctlAction('playpause'); return true; }
    if (k === 'next') { ctlAction('next'); return true; }
    if (k === 'prev') { ctlAction('prev'); return true; }
    if (k === 'stop') { ctlAction('stop'); return true; }
    if (k === 'volUp' || k === 'volDown') { volumeStep(k === 'volUp' ? 5 : -5); return true; }

    // 滑条：◀▶ 直接调值（比拖拽好用得多）
    if (el && el.tagName === 'INPUT' && el.type === 'range' && (k === 'left' || k === 'right')) {
      return adjustRange(el, (k === 'right') ? 1 : -1);
    }
    if (k === 'left' || k === 'right' || k === 'up' || k === 'down') return move(k);
    return false;
  }

  /* ---------------------------------------------------- 7. 底部提示条 */
  function drawCue() {
    if (!on) return;
    if (cueEl && !document.contains(cueEl)) cueEl = null;
    if (!cueEl) {
      cueEl = $('tvcue');
      if (!cueEl) {
        cueEl = document.createElement('div');
        cueEl.id = 'tvcue';
        cueEl.className = 'tvcue';
        var host = ($('app') && $('app').style.display !== 'none') ? $('app') : document.body;
        host.appendChild(cueEl);
      }
    }
    var el = document.activeElement;
    if (!el || candidates().indexOf(el) < 0) el = focused;
    var main = '◀ ▶ ▲ ▼ 移动 · OK 确认';
    if (el) {
      if (el.tagName === 'INPUT') {
        main = (el.type === 'range') ? '◀ ▶ 调节 · 停手即生效' : 'OK 输入文字 · 返回 收起键盘';
      } else if (el.tagName === 'SELECT') {
        main = 'OK 切换选项';
      } else if (scopeIsSheet()) {
        main = '◀ ▶ ▲ ▼ 移动 · OK 确认';
      }
    }
    var html = '<span>' + main + '</span><span class="sep">|</span>' +
      '<span>返回 <b>上一级</b></span><span class="sep">|</span>' +
      '<span>媒体键 <b>⏯ ⏭ ⏮</b> 控制播放</span><span class="sep">|</span>' +
      '<span>频道键 <b>CH±</b> 调音量</span>';
    /* 文案没变就别写：写 innerHTML 会触发 MutationObserver，
       而观察者现在会同步补焦点，无谓的写入等于白白多算几次布局。 */
    if (html === lastCue) return;
    lastCue = html;
    cueEl.innerHTML = html;
  }

  /* --------------------------------------------- 8. 重绘后恢复焦点 */

  /* 作用域切换（主界面 ↔ 弹层/启动页）：把焦点带进去、送回原位。
     必须「每次按键开始时」同步判断，不能只靠 restore() 的 90ms 防抖——
     一旦「开弹层 + 关弹层」落在同一个防抖窗口里，切换就会被整个漏掉，
     焦点会停在已经隐藏的弹层元素上。 */
  function syncScope() {
    var sc = scope();
    if (sc === curScope) return;
    var prev = curScope;
    curScope = sc;

    var isPop = (sc.id === 'sheet' || sc.id === 'setup');
    var wasPop = !!(prev && (prev.id === 'sheet' || prev.id === 'setup'));

    if (isPop) {
      if (prev && prev.id === 'app') { appKey = lastKey; appIdx = lastIdx; }
      var l1 = candidates(true);
      if (l1.length) {
        // 焦点直接落在弹层「内容」的第一项，而不是右上角的关闭按钮：
        // 打开面板就是要操作内容，少按一次；也避免从右上角往下斜跳进行中间。
        var body = $('sheetBody'), first = null;
        if (body) {
          for (var b = 0; b < l1.length; b++) { if (body.contains(l1[b])) { first = l1[b]; break; } }
        }
        focusEl(first || l1[0], true);
      }
      return;
    }
    if (!wasPop) return;
    if (prev.id === 'setup') { focusEl(firstFocusable(), true); return; }   // 启动页 → 主界面
    var l2 = candidates(true);
    if (!l2.length) return;
    for (var j = 0; j < l2.length; j++) {
      if (keyOf(l2[j]) === appKey) { focusEl(l2[j], true); return; }
    }
    var idx = (typeof appIdx === 'number' && appIdx >= 0) ? appIdx : 0;
    focusEl(l2[Math.max(0, Math.min(l2.length - 1, idx))], true);
  }

  function restore() {
    if (!on || !armed) return;
    layout();
    syncScope();
    var list = candidates(true);
    if (!list.length) return;

    if (editing) return;                             // 打字中不打扰
    var cur = document.activeElement;
    if (cur && document.contains(cur) && list.indexOf(cur) >= 0) return;   // 焦点还在，不用管

    var hit = null, i;
    for (i = 0; i < list.length; i++) { if (keyOf(list[i]) === lastKey) { hit = list[i]; break; } }
    if (!hit && lastKey) {                           // 元素被换掉了 → 停在原位置
      hit = list[Math.max(0, Math.min(list.length - 1, lastIdx))];
    }
    if (hit) focusEl(hit, true);
  }
  function scheduleRestore() {
    clearTimeout(restoreTimer);
    restoreTimer = setTimeout(restore, 90);
  }

  /* 列表重绘会把被替换掉的节点连同焦点一起丢掉（activeElement → body）。
     MutationObserver 的回调是**微任务**，在本轮渲染任务结束后、浏览器绘制之前执行，
     所以在这里同步补一次焦点，用户根本看不到闪烁，
     「空窗期按键」的窗口也从 ~150ms 缩到近乎 0。尾部的 90ms 防抖保留：
     万一遇到「先清空、后异步填充」的两段式渲染，第一拍是补不上的。 */
  function onMutate() {
    if (!on || !armed) return;
    restore();
    scheduleRestore();
  }

  /* ----------------------------------------------------- 9. 启动 */
  /** 告诉原生端当前该由谁处理按键（0 不接管 / 1 全接管 / 2 正在输入） */
  function sink() {
    bridge('setKeySink', on ? (editing ? 2 : 1) : 0);
  }
  function mark() {
    var de = document.documentElement;
    if (on) de.classList.add('tv'); else de.classList.remove('tv');
  }

  /* #app 的 display 是 app.js 用**行内样式**写死的 flex，而行内样式压过任何 CSS
     选择符（ID 选择符也不行）——所以 tv.css 里的网格骨架不可能靠 CSS 落地，
     必须在这里翻转。只动 flex ↔ grid，绝不碰 none，因此不影响显示/隐藏。 */
  function layout() {
    var a = $('app');
    if (!a || !a.style) return;
    if (on) {
      if (a.style.display === 'flex') a.style.display = 'grid';
    } else if (a.style.display === 'grid') {
      a.style.display = 'flex';
    }
  }

  function arm() {
    if (!on) return;
    layout();
    if ($('app') && $('app').style.display !== 'none') {
      if (!armed) { armed = true; snap = null; focusEl(firstFocusable(), true); }
      else if (!userMoved) {
        /* 刚启动时列表还没渲染出来，焦点只能先落在工具栏按钮上。
           列表一出现就自动挪到第一行——前提是用户还没动过遥控器，
           动过就绝不再抢焦点。 */
        var want = firstFocusable();
        if (want && want !== focused && want.closest && want.closest('.item')) {
          snap = null; focusEl(want, true);
        }
      }
      drawCue();
    }
  }

  function boot() {
    mark();
    layout();
    sink();
    if (!on) return;

    if (window.MutationObserver) {
      try {
        new MutationObserver(onMutate).observe(document.body,
          { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] });
      } catch (e) { }
    }
    setInterval(function () { if (on) { arm(); restore(); } }, 700);

    // 有实体键盘 / 蓝牙遥控器时 DOM 层也能收到键
    document.addEventListener('keydown', function (e) {
      if (!on) return;
      if (editing && e.key !== 'Escape') return;
      var map = {
        37: 'left', 38: 'up', 39: 'right', 40: 'down', 13: 'ok', 32: 'ok',
        ArrowLeft: 'left', ArrowUp: 'up', ArrowRight: 'right', ArrowDown: 'down',
        Enter: 'ok', ' ': 'ok', Escape: 'back', BrowserBack: 'back'
      };
      var k = map[e.keyCode] || map[e.key];
      if (!k) return;
      if (handle(k)) { e.preventDefault(); e.stopPropagation(); }
    }, true);

    document.addEventListener('contextmenu', function (e) { if (on) e.preventDefault(); });

    // 回到前台时重新同步「谁处理按键」，避免输入法状态残留
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) editing = false;
      sink();
    });
  }

  /* ------------------------------------- 10. 对外接口（原生 / 设置面板） */
  window.__tvKey = function (k) { return handle(k) ? '1' : '0'; };
  window.__tvMode = function () { return on ? '1' : '0'; };
  window.TV = {
    enabled: function () { return on; },
    set: function (v) {
      on = !!v;
      try { localStorage.setItem('dlna_tv', on ? '1' : '0'); } catch (e) { }
      armed = false; focused = null; editing = false; lastKey = ''; lastIdx = 0;
      userMoved = false;
      curScope = null; appKey = ''; snap = null; lastCue = null;
      mark();
      layout();                          // 关掉电视模式时也要把网格还原成 flex
      sink();
      var c = $('tvcue');
      if (!on) {
        if (focused && focused.classList) focused.classList.remove('tv-focus');
        if (c && c.parentNode) c.parentNode.removeChild(c);
        cueEl = null;
        snap = null;
      } else {
        snap = null;
        setTimeout(arm, 60);
      }
      return on;
    },
    toggle: function () { return window.TV.set(!on); },
    /* 返回键：原生调用；返回 'exit' 表示可以退出 App */
    back: function () {
      if (!on) return false;
      if (scopeIsSheet()) { try { $('sheetClose').click(); } catch (e) { } return true; }
      var a = document.activeElement;
      if (!inRail(a)) { focusEl(document.querySelector('.navbtn.on') || firstFocusable()); return true; }
      return 'exit';
    },
    refresh: function () { armed = true; snap = null; focusEl(focused || firstFocusable()); }
  };

  /* 覆盖 app.js 的返回键：电视上「先退焦点，再退页面」
     —— 原生端只认返回值里有没有 'exit' */
  var origBack = window.__onBack;
  window.__onBack = function () {
    if (!on) return (typeof origBack === 'function') ? origBack() : false;
    return window.TV.back();
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
