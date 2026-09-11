#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
生成浏览器端到端测试页 _e2e.html
=================================
以真实的 index.html 为模板，只在 app.js 之前插入一个「原生桥」替身，
再在 app.js 之后追加一段测试驱动，用来在无头浏览器里验证：

  1. 页面能 boot（BASE 指到本机 8765，/api/state 拿到数据）
  2. 插件运行时能载入 5 个内置音源
  3. 本机曲库能列出扫描到的曲目
  4. 在线搜索能出结果（真网络）
  5. 在线曲目能解析出直链 + 注册出 /stream 地址
  6. /stream 支持 Range（206）

产物是临时文件，测完即删。
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.abspath(os.path.join(HERE, "..", "app", "assets", "www"))

SHIM = """<script>
/* ==== 测试用原生桥替身（真机上这段由 MainActivity.Bridge 提供） ==== */
window.__PLUGIN_NAMES__ = ['bili.js','yuanli-kg.js','yuanli-kw.js','yuanli-qq.js','yuanli-wy.js'];
window.Android = {
  getBaseUrl: function () { return 'http://127.0.0.1:8765'; },
  getVersion: function () { return 'e2e-2.0'; },
  getPlugins: function () {
    var out = [];
    for (var i = 0; i < window.__PLUGIN_NAMES__.length; i++) {
      var n = window.__PLUGIN_NAMES__[i];
      try {
        var x = new XMLHttpRequest();
        x.open('GET', '../plugins/' + n, false);
        x.send();
        if (x.responseText && x.responseText.length > 100) out.push({ name: n, code: x.responseText });
      } catch (e) { }
    }
    return JSON.stringify(out);
  },
  getUserPlugins: function () { return '[]'; },
  getDownloadsDir: function () { return 'C:/e2e/downloads'; },
  getLibraryInfo: function () { return JSON.stringify(window.__libInfo || {}); },
  getPermissionState: function () { return 'granted'; },
  rescanLibrary: function () { },
  requestAudioPermission: function () { },
  startKeepAlive: function () { },
  exitApp: function () { },
  openDownloads: function () { },
  toast: function (m) { console.log('[native-toast] ' + m); }
};
</script>
"""

DRIVER = """<script>
/* ==== 测试驱动 ==== */
(function () {
  var steps = [];
  function log(name, ok, detail) {
    steps.push({ name: name, ok: !!ok, detail: String(detail == null ? '' : detail) });
  }
  function finish() {
    var pre = document.createElement('pre');
    pre.id = 'e2e-out';
    pre.textContent = 'E2E_RESULT=' + JSON.stringify(steps);
    document.body.appendChild(pre);
    var allOk = steps.length > 0 && steps.every(function (s) { return s.ok; });
    document.title = allOk ? 'E2E-PASS' : 'E2E-FAIL';
    window.__e2eDone = true;
  }
  function waitFor(fn, ms, label) {
    return new Promise(function (resolve, reject) {
      var t0 = Date.now();
      (function poll() {
        var v;
        try { v = fn(); } catch (e) { v = null; }
        if (v) return resolve(v);
        if (Date.now() - t0 > ms) return reject(new Error('等待超时: ' + label));
        setTimeout(poll, 250);
      })();
    });
  }
  function pickProvider() {
    var sel = document.getElementById('onlineProvider');
    var opts = [].slice.call(sel.options).map(function (o) { return o.value; });
    for (var i = 0; i < opts.length; i++) if (/WY|网易|wy/i.test(opts[i])) return opts[i];
    return opts[0] || '';
  }

  /* 音源的解析接口由第三方提供，时有故障。这里跨音源、逐条尝试，
     只要能解析出一条，就说明「解析 -> 注册 -> 拉流」这条链路是通的。 */
  async function resolveAny(startProv) {
    var all = (S.online.plugins || []).map(function (p) { return p.platform; });
    var order = [startProv].concat(all.filter(function (p) { return p !== startProv; }));
    var budget = 4;   /* 最多尝试 4 次，避免音源全挂时把测试拖太久 */
    for (var pi = 0; pi < order.length && budget > 0; pi++) {
      if (pi > 0) {
        document.getElementById('onlineProvider').value = order[pi];
        try { await doOnlineSearch(1); } catch (e) { continue; }
      }
      var items = (S.online.items || []).slice(0, 2);
      for (var i = 0; i < items.length && budget > 0; i++) {
        budget--;
        try {
          var r = await resolveOnline([items[i]]);
          if (r && r[0] && r[0].sid) {
            window.__resolvedVia = order[pi] + ' / ' + items[i].title;
            return r;
          }
        } catch (e) { /* 这条不行，继续下一条 */ }
      }
    }
    return [];
  }

  (async function () {
    try {
      /* 1. boot：BASE 指向本机服务，/api/state 有数据 */
      await waitFor(function () { return S && S.state; }, 30000, 'boot /api/state');
      log('boot(base=' + BASE + ')', /127\\.0\\.0\\.1:8765$/.test(BASE) && S.state && S.state.ok !== false, 'BASE=' + BASE);

      /* 2. 插件运行时 */
      await loadProviders();
      var pl = (S.online.plugins || []);
      log('loadProviders', pl.length >= 3, pl.length + ' 个: ' + pl.map(function (p) { return p.platform; }).join(','));

      /* 3. 本机曲库 */
      S.lib.source = 'local';
      S.lib.container = '';
      await loadLib();
      var lib = S._libItems || [];
      log('本机曲库', lib.length >= 3, lib.length + ' 首');
      window.__libInfo = { count: lib.length, scanning: false, truncated: false, last_scan: Math.floor(Date.now() / 1000) };

      /* 4. 在线搜索（真网络） */
      var prov = pickProvider();
      document.getElementById('onlineProvider').value = prov;
      document.getElementById('onlineQ').value = '周杰伦';
      document.getElementById('onlineLimit').value = '10';
      await doOnlineSearch(1);
      var oi = S.online.items || [];
      log('在线搜索[' + prov + ']', oi.length > 0, oi.length + ' 条' +
        (oi.length ? '  首条=' + oi[0].title + ' / ' + oi[0].artist : ''));

      /* 5. 解析直链 + 注册到本机服务 */
      var resolved = [];
      if (oi.length) {
        resolved = await resolveAny(prov);
        var r0 = resolved[0] || {};
        log('解析+注册', !!r0.sid && !!r0.url && /\\/stream\\?sid=/.test(r0.url),
          'sid=' + (r0.sid || '-') + ' url=' + (r0.url || '-'));
      } else {
        log('解析+注册', false, '没有搜索结果，跳过');
      }

      /* 5.5 本机回退播放：无音响时本地曲目应能拼出 /media 流地址并可取流 */
      if (lib.length) {
        var lt = lib[0];
        var fallbackUrl = lt.url || lt.stream_url
          || ((lt.source === 'local' && lt.id) ? BASE + '/media?id=' + encodeURIComponent(lt.id) : '');
        try {
          var mr = await fetch(fallbackUrl, { headers: { Range: 'bytes=0-1023' } });
          var mb = await mr.arrayBuffer();
          log('本机回退流', mr.status === 206 && mb.byteLength === 1024,
            'status=' + mr.status + ' bytes=' + mb.byteLength);
        } catch (e) { log('本机回退流', false, String(e && e.message || e)); }
      } else {
        log('本机回退流', false, '曲库为空，跳过');
      }

      /* 6. /stream 直连（带 Range，模拟音响来拉流） */
      if (resolved.length && resolved[0].url) {
        var rr = await fetch(resolved[0].url, { headers: { Range: 'bytes=0-2047' } });
        var buf = await rr.arrayBuffer();
        log('/stream Range', rr.status === 206 && buf.byteLength === 2048,
          'status=' + rr.status + ' bytes=' + buf.byteLength);
      } else {
        log('/stream Range', false, '无可用流地址');
      }

      /* 7. 加入播放列表（走 /api/queue） */
      if (resolved.length) {
        try {
          var qr = await apiPost('/api/queue', { action: 'add', tracks: resolved }, 40000);
          log('/api/queue add', qr && qr.ok === true, 'total=' + (qr && qr.total));
        } catch (e) { log('/api/queue add', false, e.message); }
      } else {
        log('/api/queue add', false, '跳过');
      }

      /* 8. 本机下载链路（真下载一首，验证直链+请求头可用） */
      if (resolved.length) {
        try {
          var payload = [{
            provider: resolved[0].provider, id: resolved[0].id, title: resolved[0].title,
            artist: resolved[0].artist, duration_sec: resolved[0].duration_sec || 0,
            url: resolved[0]._directUrl, headers: resolved[0]._headers || {}
          }];
          var dr = await apiPost('/api/online/download', { items: payload }, 60000);
          log('下载排队', dr && dr.ok !== false && dr.queued === 1, 'queued=' + (dr && dr.queued));
          // 等下载器跑一会儿再查状态
          await new Promise(function (r) { setTimeout(r, 6000); });
          var st = await api('/api/online/downloads');
          var job = (st.jobs || [])[0] || {};
          log('下载状态可查', !!st.ok, 'status=' + (job.status || '?') + ' size=' + (job.size || 0));
        } catch (e) { log('下载排队', false, e.message); }
      } else {
        log('下载排队', false, '跳过');
      }

      /* ---------- v2.1 新增功能的检查 ---------- */

      var it0 = (S.online.items || [])[0] || null;

      /* 歌词：LRC 解析（纯函数，最该稳的一环；覆盖标准/纯秒/共句三种写法） */
      try {
        var L = parseLrc('[00:12.34]第一行\\n[00:20.00]第二行\\n[01:05.5]第三行');
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

      /* 歌词：走完整 UI 链路（loadLyric -> renderLyric） */
      try {
        var useItem = lyricItem || it0;
        if (useItem) {
          playerSheet();                                  // 真正的入口
          await loadLyric({ source: 'online', provider: useItem.provider, id: useItem.id, title: useItem.title });
          var box = document.getElementById('lyricBox');
          log('歌词面板渲染', !!box,
            '行数=' + ((S.lyric.lines || []).length) + ' 提示=' + (S.lyric.msg || '无'));
          closeSheet();
        } else { log('歌词面板渲染', false, '没有可用曲目'); }
      } catch (e) { log('歌词面板渲染', false, e.message); }

      /* 音量面板：滑条 + 文案 + − / + 精调按钮都应在 */
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
          var hasBtns = !!document.getElementById('volDec') && !!document.getElementById('volInc');
          log('音量面板', hasRange && hasVolWord && hasBtns,
            '滑条=' + hasRange + ' 含音量字样=' + hasVolWord + ' 加减按钮=' + hasBtns);
          closeSheet();
        } else { log('音量面板', false, '没发现设备'); }
      } catch (e) { log('音量面板', false, e.message); }

      /* 加减按钮：单击应精确 ±1（真跑一遍逻辑） */
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
          log('音量加减按钮', down === before - 1 && up === before,
            ' ' + before + ' →减一 ' + down + ' →加一 ' + up);
          closeSheet();
        } else { log('音量加减按钮', false, '没发现设备'); }
      } catch (e) { log('音量加减按钮', false, e.message); }

      /* 音量入口唯一：设备卡片有入口，但旧的内联滑条已删干净 */
      try {
        var dev3 = (S.state && S.state.devices && S.state.devices[0]) || null;
        if (dev3) {
          dev3.selected = true;
          renderDevices();
          var html = document.getElementById('devList').innerHTML;
          var entry = html.split('volumeSheet(').length - 1;
          var legacy = html.split('devVolSet(').length - 1;
          log('音量入口唯一', entry >= 1 && legacy === 0,
            '入口=' + entry + ' 旧滑条=' + legacy);
        } else { log('音量入口唯一', false, '没发现设备'); }
      } catch (e) { log('音量入口唯一', false, e.message); }

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

      /* ---------- v2.5：SMB 扫描 / 浏览 ---------- */

      /* SMB 面板：必须有「扫描局域网」「浏览共享」，且方块图标已换成矢量图标 */
      try {
        closeSheet();
        srcAdd('smb');
        var smbHtml = document.getElementById('sheetBody').innerHTML;
        var hasScan = smbHtml.indexOf('smbScan(') >= 0;
        var hasBrowse = smbHtml.indexOf('smbBrowse(') >= 0;
        var boxGlyph = String.fromCharCode(0xD83D) + String.fromCharCode(0xDDA7);
        var noBox = smbHtml.indexOf(boxGlyph) < 0;
        var hasSvg = smbHtml.indexOf('<svg') >= 0;
        log('SMB 面板扫描/浏览', hasScan && hasBrowse && noBox && hasSvg,
          '扫描=' + hasScan + ' 浏览=' + hasBrowse + ' 无方块图标=' + noBox + ' 矢量图标=' + hasSvg);
        closeSheet();
      } catch (e) { log('SMB 面板扫描/浏览', false, e.message); }

      /* SMB 浏览接口：主机为空要给出可读提示，而不是抛异常 */
      try {
        var rb = await apiPost('/api/smb/browse', { host: '' }, 30000);
        log('SMB 浏览接口', rb.ok === false && typeof rb.error === 'string' && rb.error.length > 0,
          rb.error || '(没有错误信息)');
      } catch (e) { log('SMB 浏览接口', false, e.message); }

      /* SMB 局域网扫描：真跑一遍，必须限时返回且结构正确 */
      try {
        var t0 = Date.now();
        var rs = await apiPost('/api/smb/scan', { guest: true, user: '', password: '' }, 90000);
        var dt = Date.now() - t0;
        var okShape = rs && ((rs.ok === true && rs.hosts instanceof Array)
          || (rs.ok === false && typeof rs.error === 'string'));
        log('SMB 局域网扫描', okShape && dt < 45000,
          '耗时 ' + Math.round(dt / 1000) + 's · '
          + (rs.ok ? ('发现 ' + (rs.hosts || []).length + ' 台') : ('跳过：' + rs.error)));
      } catch (e) { log('SMB 局域网扫描', false, e.message); }

      /* ---------- v2.5：音源可自行添加 ---------- */

      /* 音源清单来自本机服务，不是前端写死的 */
      try {
        var rp = await api('/api/plugins');
        var lp = rp.list || [];
        var builtins = lp.filter(function (x) { return x.builtin; }).length;
        log('音源清单', lp.length >= 5 && builtins >= 5,
          '共 ' + lp.length + ' 个，内置 ' + builtins + ' 个');
      } catch (e) { log('音源清单', false, e.message); }

      /* 安装一个临时音源 —— 要真的进清单、进插件运行时、进在线音源下拉，删掉后完全还原 */
      try {
        var before = ((await api('/api/plugins')).list || []).length;
        var testCode = '"use strict";module.exports={platform:"E2E测试音源",version:"0.0.1",'
          + 'search:async function(q,p,t){return {isEnd:true,data:[]};},'
          + 'getMediaSource:async function(i){return {url:""};}};';
        var ri = await apiPost('/api/plugins/install',
          { code: testCode, name: 'e2e-test-src' }, 60000);
        var midList = (await api('/api/plugins')).list || [];
        var hasIt = midList.some(function (x) { return x.name === 'e2e-test-src.js'; });
        var codeList = (await api('/api/plugins/code')).list || [];
        var inRuntime = codeList.some(function (x) { return x.name === 'e2e-test-src.js'; });
        await loadProviders();
        var inDropdown = document.getElementById('onlineProvider').innerHTML.indexOf('E2E测试音源') >= 0;
        var rd = await apiPost('/api/plugins/remove', { name: 'e2e-test-src.js' }, 30000);
        var after = ((await api('/api/plugins')).list || []).length;
        await loadProviders();
        log('音源安装往返',
          ri.ok === true && hasIt && inRuntime && inDropdown && rd.ok === true && after === before,
          '前 ' + before + ' → 中 ' + midList.length + ' → 后 ' + after
          + ' 运行时=' + inRuntime + ' 下拉=' + inDropdown);
      } catch (e) { log('音源安装往返', false, e.message); }

      /* 音源管理面板能渲染出来 */
      try {
        await srcMgrSheet();
        var mgr = document.getElementById('sheetBody').innerHTML;
        var okAdd = mgr.indexOf('srcInstallSheet(') >= 0;
        var okLists = mgr.indexOf('已安装的音源') >= 0;
        log('音源管理面板', okAdd && okLists, '添加入口=' + okAdd + ' 列表=' + okLists);
        closeSheet();
      } catch (e) { log('音源管理面板', false, e.message); }

      /* 正在播放：底栏大项，位于设备前 */
      try {
        var navs = [].slice.call(document.querySelectorAll('.navbtn')).map(function (b) { return b.getAttribute('data-tab'); });
        var firstOk = navs[0] === 'now' && navs[1] === 'devices';
        switchTab('now');
        var nb = document.getElementById('nowBody');
        var okNow = !!nb && nb.innerHTML.indexOf('np-title') >= 0 && !!document.getElementById('lyricBox');
        var titleOk = document.getElementById('topTitle').textContent === '正在播放';
        log('正在播放大项', firstOk && okNow && titleOk,
          '首位=' + navs[0] + ' 内容=' + !!okNow + ' 标题=' + titleOk);
        switchTab('devices');
      } catch (e) { log('正在播放大项', false, e.message); }

      /* v2.8：底栏 4 字命名 + 模式迁移 + 边听边下载 + 封面歌词同台 */
      try {
        var labels = [].slice.call(document.querySelectorAll('.navbtn span')).map(function (x) { return x.textContent; });
        var want = ['正在播放', '我的设备', '本地曲库', '在线搜索', '播放列表'];
        var labOk = JSON.stringify(labels) === JSON.stringify(want);
        switchTab('queue');
        var qm = document.getElementById('queueModes');
        var qOk = !!qm && qm.innerHTML.indexOf('queueShuffle') >= 0 && qm.innerHTML.indexOf('setRepeat') >= 0;
        var barOk = !document.getElementById('btnQueueShuffle');
        switchTab('now');
        var nb8 = document.getElementById('nowBody');
        var noMode = nb8.innerHTML.indexOf('播放模式') < 0;
        var adlOk = nb8.innerHTML.indexOf('setAutoDl') >= 0;
        var stageOk = !!document.getElementById('npArt') && !!document.getElementById('lyricBox');
        log('v2.8 界面改版', labOk && qOk && barOk && noMode && adlOk && stageOk,
          '栏名=' + labOk + ' 模式在列表=' + (qOk && barOk) + ' 已从正在播放移除=' + noMode
          + ' 边听边下载=' + adlOk + ' 封面歌词同台=' + stageOk);
        /* 边听边下载开关：真开一次再关掉 */
        var adl0 = autoDlOn();
        setAutoDl(!adl0);
        var adl1 = autoDlOn();
        setAutoDl(adl0);
        var adl2 = autoDlOn();
        log('边听边下载开关', adl1 === !adl0 && adl2 === adl0, '开=' + adl1 + ' 关=' + adl2);
      } catch (e) { log('v2.8 界面改版', false, e.message); }

      /* v2.9：歌词快慢校准 + 正在播放页瘦身 */
      try {
        var nb9 = document.getElementById('nowBody');
        var noCtl = nb9.innerHTML.indexOf('np-ctl') < 0;
        var noHint = nb9.innerHTML.indexOf('自动加入下载队列') < 0;
        var hasOff = !!document.getElementById('lrcOffVal')
          && nb9.innerHTML.indexOf('lyricOffShift(500)') >= 0
          && nb9.innerHTML.indexOf('lyricOffShift(-500)') >= 0;
        var off0 = lyricOffGet();
        lyricOffShift(500);
        var off1 = lyricOffGet();
        lyricOffShift(-1000);
        var off2 = lyricOffGet();
        try { localStorage.setItem('dlna_lyricoff', String(off0)); } catch (e2) { }
        S.lyricOff = off0;
        var offOk = off1 === off0 + 500 && off2 === off0 - 500;
        /* 校准真的影响高亮：pos=10s、偏移+2s 时 12s 的行应被点亮 */
        S.lyric = { key: 't', lines: [{ t: 5, text: 'a' }, { t: 12, text: 'b' }, { t: 20, text: 'c' }], idx: -1, msg: '' };
        S.lyricOff = 2000;
        updateLyricProgress(10);
        var idxOff = S.lyric.idx;      // 期望 = 1（12s 的行被提前点亮）
        S.lyricOff = 0;
        updateLyricProgress(10);
        var idxRaw = S.lyric.idx;      // 期望 = 0
        S.lyricOff = off0;
        try { localStorage.setItem('dlna_lyricoff', String(off0)); } catch (e2) { }
        var effOk = idxOff === 1 && idxRaw === 0;
        log('v2.9 歌词校准与瘦身', noCtl && noHint && hasOff && offOk && effOk,
          '控制键已删=' + noCtl + ' 说明已删=' + noHint + ' 快慢按钮=' + hasOff
          + ' 步进=' + offOk + ' 校准生效=' + effOk + '(' + idxRaw + '→' + idxOff + ')');
      } catch (e) { log('v2.9 歌词校准与瘦身', false, e.message); }

      /* v2.10：进度平滑器 —— 噪声忽略 / 大跳采纳 / seek 宽限期 */
      try {
        S._sm = null; S._seekAt = 0; S._seekPos = 0;
        var s1 = smoothAccept(10, true);            // 初始化基点
        var s2 = smoothAccept(10.4, true);          // +0.4s 噪声 → 应忽略（继续外推而非跳回）
        var noiseOk = Math.abs(s2 - s1) < 1.0;
        var s3 = smoothAccept(50, true);            // 大跳 → 应采纳
        var jumpOk = Math.abs(s3 - 50) < 1.0;
        S._seekPos = 120; S._seekAt = performance.now();
        S._sm = { pos: 10, at: performance.now(), playing: true };
        var s4 = smoothAccept(10, true);            // 宽限期内旧快照 → 应以 seek 目标为准
        var graceOk = s4 > 110;
        S._seekAt = 0; S._sm = null;
        var pauseOk = smoothAccept(33, false) === 33;  // 暂停 → 直接用快照
        log('v2.10 进度平滑器', noiseOk && jumpOk && graceOk && pauseOk,
          '噪声忽略=' + noiseOk + ' 大跳采纳=' + jumpOk + ' 宽限期=' + graceOk + ' 暂停直通=' + pauseOk);
      } catch (e) { log('v2.10 进度平滑器', false, e.message); }

      /* v2.11：沉浸歌词模式 —— 双击进、控件齐、高亮同步、双击退 */
      try {
        S.out = 'phone';
        S.phone.queue = [{ source: 'local', id: 'f:/imm-test.mp3', title: '沉浸测试', artist: 'E2E' }];
        S.phone.idx = 0;
        S.out = 'phone';
        S.phone.queue = [{ source: 'local', id: 'f:/imm-test.mp3', title: '沉浸测试', artist: 'E2E' }];
        S.phone.idx = 0;
        S.lyric = { key: 't-imm', lines: [{ t: 1, text: '一线' }, { t: 5, text: '二线' }, { t: 9, text: '三线' }], idx: 0, msg: '' };
        switchTab('now'); renderLyric();
        lrcLineTap(1);
        var notYet = !S._imm;
        lrcLineTap(1);
        var immOk = S._imm === true && $('imm') && $('imm').style.display === 'flex';
        var ctlOk = !!$('immPlay') && !!$('immVol') && $('immLrc').innerHTML.indexOf('lrc-line') >= 0;
        var volOk = !isNaN(parseInt($('immVol').value, 10));
        S.lyric.idx = 2; immSync();
        var hlOk = $('immLrc').querySelectorAll('.lrc-line.on').length === 1;
        exitImmersive();
        var exitOk = !S._imm && $('imm').style.display === 'none';
        log('v2.11 沉浸模式', notYet && immOk && ctlOk && volOk && hlOk && exitOk,
          '单击不进=' + notYet + ' 双击进=' + immOk + ' 控件=' + ctlOk + ' 音量=' + volOk
          + ' 高亮=' + hlOk + ' 退出=' + exitOk);
      } catch (e) { log('v2.11 沉浸模式', false, e.message); }

      /* v2.12：i18n —— 词典覆盖率 + 设置页语言切换入口 */
      try {
        var hasI18N = !!window.I18N;
        var pairs = [
          ['正在播放', 'Now Playing'], ['我的设备', 'My Devices'], ['本地曲库', 'Local Library'],
          ['在线搜索', 'Online Search'], ['播放列表', 'Queue'], ['设置', 'Settings'],
          ['扫描局域网', 'Scan LAN'], ['边听边下载', 'Download while playing']
        ];
        var hit = 0, miss = [];
        pairs.forEach(function (p) {
          if (I18N.t(p[0]) === p[1]) hit++; else miss.push(p[0]);
        });
        var dyn = I18N.t('3 台设备') === '3 devices' && I18N.t('第 2 页 · 1 首') === 'Page 2 · 1 tracks';
        settingsSheet();
        var sheetTxt = document.getElementById('sheetBody').innerHTML;
        var langUi = sheetTxt.indexOf("I18N.set('en')") >= 0 && sheetTxt.indexOf("I18N.set('zh')") >= 0;
        closeSheet();
        log('v2.12 中英双语', hasI18N && hit === pairs.length && dyn && langUi,
          '引擎=' + hasI18N + ' 词典=' + hit + '/' + pairs.length + ' 动态=' + dyn + ' 切换入口=' + langUi
          + (miss.length ? ' 缺失:' + miss.join(',') : ''));
      } catch (e) { log('v2.12 中英双语', false, e.message); }

      /* 音源记忆：设默认 + 记住上次搜索音源 */
      try {
        var plats = (S.online.plugins || []).map(function (x) { return x.platform; });
        var want = plats[0] || '';
        try { localStorage.removeItem('dlna_lastprov'); } catch (e2) { }
        srcSetDefault(want);
        var defGot = localStorage.getItem('dlna_defaultprov') || '';
        try { localStorage.removeItem('dlna_lastprov'); } catch (e2) { }
        document.getElementById('onlineProvider').value = '';
        await loadProviders();
        var got = document.getElementById('onlineProvider').value;
        var okDef = defGot === want && got === want;
        var lastP = plats[1] || want;
        try { localStorage.setItem('dlna_lastprov', lastP); } catch (e2) { }
        await loadProviders();
        var got2 = document.getElementById('onlineProvider').value;
        var okLast = got2 === lastP;
        log('音源默认与记忆', okDef && okLast,
          '默认=' + (defGot === want) + '/' + got + ' 上次=' + (got2 === lastP) + '/' + got2);
      } catch (e) { log('音源默认与记忆', false, e.message); }

    } catch (e) {
      log('异常', false, (e && e.message) || String(e));
    }
    finish();
  })();
})();
</script>
"""


def main():
    src = io.open(os.path.join(WWW, "index.html"), "r", encoding="utf-8").read()

    # 测试页强制中文：断言全部基于中文文案，且无头浏览器默认 en-US
    src = src.replace('<link rel="stylesheet" href="app.css">',
                      '<script>try{localStorage.setItem("dlna_lang","zh")}catch(e){}</script>\n'
                      '<link rel="stylesheet" href="app.css">', 1)

    # 在 plugins-runtime.js 之前插入桥替身
    marker = '<script src="plugins-runtime.js"></script>'
    if marker not in src:
        raise SystemExit("index.html 里没有找到 plugins-runtime.js 引用")
    src = src.replace(marker, SHIM + marker, 1)

    # 在 </body> 之前插入测试驱动
    src = src.replace("</body>", DRIVER + "</body>", 1)

    out = os.path.join(WWW, "_e2e.html")
    io.open(out, "w", encoding="utf-8", newline="").write(src)
    print("已生成:", out)


if __name__ == "__main__":
    main()
