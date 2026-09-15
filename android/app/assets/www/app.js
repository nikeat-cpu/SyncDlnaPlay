'use strict';
/* =====================================================================
   音响管家 · 手机端逻辑
   纯前端 SPA，通过 HTTP JSON API 对接家里的 iStoreOS 音乐服务。
   无第三方依赖，兼容 Android WebView（file:// + 通用访问）。
   ===================================================================== */

/* ---------------------------------- 工具 ---------------------------------- */
const $ = id => document.getElementById(id);
let AB = null;
try { AB = (typeof Android !== 'undefined' && Android) ? Android : null; } catch (e) { AB = null; }

const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(sec / 60), s = sec % 60;
  return m + ':' + (s < 10 ? '0' : '') + s;
}
let toastTimer = null;
function toast(msg, kind) {
  const el = $('toast');
  el.textContent = msg;
  el.className = 'toast on' + (kind ? ' ' + kind : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, 2200);
}
/* 轻量触感反馈（部分 WebView 支持，不支持则静默） */
function buzz(ms) { try { if (navigator.vibrate) navigator.vibrate(ms || 8); } catch (e) { } }

/* ---------------------------------- 配置 ---------------------------------- */
let BASE = '';
function loadBase() {
  // 调试用：?server=192.168.1.10:5000 可在浏览器里直接指向某个服务
  try {
    const m = /[?&]server=([^&]+)/.exec(location.search || '');
    if (m) { BASE = normBase(decodeURIComponent(m[1])); return; }
  } catch (e) { }
  try {
    if (AB && AB.getBaseUrl) BASE = AB.getBaseUrl() || '';
    else BASE = localStorage.getItem('dlna_base') || '';
    if (!BASE && /^https?:/.test(location.protocol)) BASE = location.origin;
    if (!BASE) BASE = 'http://127.0.0.1:8765';
  } catch (e) { BASE = 'http://127.0.0.1:8765'; }
  BASE = normBase(BASE);
}
function normBase(v) {
  v = String(v || '').trim().replace(/\/+$/, '');
  if (!v) return '';
  if (!/^https?:\/\//i.test(v)) v = 'http://' + v;
  return v;
}
function saveBase(v) {
  BASE = normBase(v);
  try {
    if (AB && AB.setServer) AB.setServer(BASE);
    else localStorage.setItem('dlna_base', BASE);
  } catch (e) { }
}

/* ---------------------------------- API ---------------------------------- */
async function api(path, opt) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), opt && opt._timeout ? opt._timeout : 25000);
  try {
    const res = await fetch(BASE + path, Object.assign({ signal: ctrl.signal }, opt || {}));
    const txt = await res.text();
    let d;
    try { d = txt ? JSON.parse(txt) : {}; }
    catch (e) { throw new Error('服务返回异常（不是 JSON）'); }
    if (d && d.ok === false && d.msg) throw new Error(d.msg);
    return d;
  } finally { clearTimeout(t); }
}
function apiPost(path, body, timeout) {
  return api(path, {
    method: 'POST', _timeout: timeout || 25000,
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {})
  });
}
const q = encodeURIComponent;

/* ---------------------------------- 全局状态 ---------------------------------- */
const S = {
  tab: 'devices',
  state: null,
  out: 'dlna',                 // 输出：dlna(音响) | phone(本机)
  lib: { source: 'local', container: '', crumbs: [], scanning: false },
  online: { q: '', provider: '', page: 1, isEnd: false, items: [], busy: false },
  phone: { queue: [], idx: -1 },
  poll: null,
  timer: null,
  dlJobs: null,
  dlBusy: false,
  lyric: { key: '', lines: [], idx: -1, msg: '' },
};

/* =========================================================================
   一、连接页
   ========================================================================= */
/* 启动页。
   播控服务在本 App 进程内，所以这里不是"连接服务器"，只是等它起来。
   早先照抄了 v1.0 手机客户端（连 iStoreOS）的界面，会出现地址框和
   「扫描外部服务」，独立版里既没用、又让人以为这是个网页。 */
function showSplash() {
  $('app').style.display = 'none';
  $('setup').style.display = '';
}
function setMsg(m, isErr) {
  const el = $('setupMsg');
  if (!el) return;
  el.textContent = m || '';
  el.className = 'msg' + (isErr ? ' err' : (m ? ' ok' : ''));
  const sp = $('splashSpin');
  if (sp) sp.style.display = isErr ? 'none' : '';
  const sb = $('splashSub');
  if (sb) sb.textContent = isErr ? '启动失败' : '正在启动…';
  const btn = $('btnRetry');
  if (btn) btn.style.display = isErr ? '' : 'none';
}

/** 后端是异步起的，给它一点时间。失败也不再让用户填地址，只把原因说清楚。 */
async function startEngine() {
  const b = normBase((AB && AB.getBaseUrl && AB.getBaseUrl()) || BASE || '');
  if (!b) { showSplash(); setMsg('内置服务地址无效，请重新启动 App。', true); return; }
  BASE = b;
  showSplash();
  setMsg('');
  for (let i = 0; i < 20; i++) {
    try {
      const h = await api('/api/health', { _timeout: 3000 });
      if (h && h.ok) { setMsg(''); await boot(); return; }
    } catch (e) { /* 还没起来，继续等 */ }
    await new Promise(r => setTimeout(r, 400));
  }
  setMsg('内置服务没有启动成功。请重新启动 App；若反复失败，可在「设置 → 曲库管理 → 运行日志」查看原因。', true);
}

/* 局域网扫描是 v1.0「连外部服务」客户端模式的东西，独立版已不需要。
   原生端也已移除 scanLan，这里留个空实现，避免旧调用打空指针。 */
window.__onScanResults = function () { };

/* =========================================================================
   二、启动与轮询
   ========================================================================= */
async function boot() {
  // 尊重系统深色/浅色——本 App 恒为深色主题
  $('setup').style.display = 'none';
  $('app').style.display = 'flex';
  switchTab(S.tab, true);
  loadProviders();
  await loadCurQueue();
  await tick(true);
  await loadLib();
  if (S.poll) clearInterval(S.poll);
  S.poll = setInterval(() => tick(), document.hidden ? 5000 : 1600);
  if (S.lyrTimer) clearInterval(S.lyrTimer);
  S.lyrTimer = setInterval(function () {
    if (S.lyric.lines.length) updateLyricProgress(nowPlaying().pos);
    if (S.tab === 'now') refreshNow();
    if (S._imm) immSync();
  }, 300);
}

async function tick(silent) {
  try {
    const st = await api('/api/state', { _timeout: 9000 });
    S.state = st;
    const plr = (st.player || {});
    let rawPos = 0;
    (st.devices || []).forEach(function (d) { if ((d.position_sec || 0) > rawPos) rawPos = d.position_sec || 0; });
    S.posRef = { pos: rawPos, at: performance.now(), playing: !!plr.playing };
    const _nk = trackKeyOf(nowPlaying().t);
    if (_nk && _nk !== S._autoDlKey) { S._autoDlKey = _nk; autoDlMaybe(nowPlaying().t); }
    renderTopDev();
    renderDevices();
    renderMini();
    renderQueue();
    if (S.tab === 'now') refreshNow();
    updateLyricProgress(nowPlaying().pos);
    pushMediaState();
  } catch (e) {
    if (!silent) console.warn('state', e);
    $('topDev').textContent = '连接已断开';
  }
}

/* =========================================================================
   三、Tab 切换
   ========================================================================= */

/* 内联线性图标集合
   ------------------------------------------------------------------
   为什么不用 emoji：🖧 这类冷门 emoji 在不同 ROM 上有的渲染成方块、
   有的是彩色贴图，跟赛博朋克配色打架。统一用 currentColor 描边 SVG，
   颜色跟着文字走，任何设备上长得都一样。 */
const I = {
  star: '<svg class="iv" viewBox="0 0 24 24"><path d="M12 3.4l2.5 5.2 5.7.8-4.1 4 1 5.7-5.1-2.7-5.1 2.7 1-5.7-4.1-4 5.7-.8z"/></svg>',
  net: '<svg class="iv" viewBox="0 0 24 24"><rect x="3" y="3.6" width="18" height="7" rx="1.9"/><rect x="3" y="13.4" width="18" height="7" rx="1.9"/><circle cx="7.1" cy="7.1" r="1.05"/><circle cx="7.1" cy="16.9" r="1.05"/></svg>',
  folder: '<svg class="iv" viewBox="0 0 24 24"><path d="M3 7.2a1.7 1.7 0 0 1 1.7-1.7h4l2 2.5h8.6A1.7 1.7 0 0 1 21 9.7v8.1a1.7 1.7 0 0 1-1.7 1.7H4.7A1.7 1.7 0 0 1 3 17.8z"/></svg>',
  folderAdd: '<svg class="iv" viewBox="0 0 24 24"><path d="M3 7.2a1.7 1.7 0 0 1 1.7-1.7h4l2 2.5h8.6A1.7 1.7 0 0 1 21 9.7v8.1a1.7 1.7 0 0 1-1.7 1.7H4.7A1.7 1.7 0 0 1 3 17.8z"/><path d="M12 11.6v5.2M9.4 14.2h5.2"/></svg>',
  scan: '<svg class="iv" viewBox="0 0 24 24"><path d="M3.6 8.5V6.3a2.2 2.2 0 0 1 2.2-2.2h2.2M16 4.1h2.2a2.2 2.2 0 0 1 2.2 2.2v2.2M20.4 15.5v2.2a2.2 2.2 0 0 1-2.2 2.2H16M8 19.9H5.8a2.2 2.2 0 0 1-2.2-2.2v-2.2"/><circle cx="12" cy="12" r="3"/><path d="M12 9v-2.4M12 17.4V15M9 12H6.6M17.4 12H15"/></svg>',
  check: '<svg class="iv" viewBox="0 0 24 24"><path d="M4.6 12.5l4.9 4.9L19.4 6.8"/></svg>',
  plug: '<svg class="iv" viewBox="0 0 24 24"><path d="M9.6 3.6v4.8M14.4 3.6v4.8"/><path d="M6.6 8.4h10.8v3.3a5.4 5.4 0 0 1-10.8 0z"/><path d="M12 17.1v3.3"/></svg>',
  unplug: '<svg class="iv" viewBox="0 0 24 24"><path d="M9.6 3.6v4.8M14.4 3.6v4.8"/><path d="M6.6 8.4h10.8v3.3a5.4 5.4 0 0 1-10.8 0z"/><path d="M12 17.1v3.3"/><path d="M3.4 3.4l17.2 17.2"/></svg>',
  x: '<svg class="iv" viewBox="0 0 24 24"><path d="M6.2 6.2l11.6 11.6M17.8 6.2L6.2 17.8"/></svg>',
  plus: '<svg class="iv" viewBox="0 0 24 24"><path d="M12 5.4v13.2M5.4 12h13.2"/></svg>',
  refresh: '<svg class="iv" viewBox="0 0 24 24"><path d="M20.2 12a8.2 8.2 0 1 1-2.4-5.8"/><path d="M20.4 4.2v4.4h-4.4"/></svg>',
  eye: '<svg class="iv" viewBox="0 0 24 24"><path d="M2.6 12S6.2 5.8 12 5.8 21.4 12 21.4 12 17.8 18.2 12 18.2 2.6 12 2.6 12z"/><circle cx="12" cy="12" r="2.9"/></svg>',
  eyeOff: '<svg class="iv" viewBox="0 0 24 24"><path d="M4.2 5.4l15.6 13.2"/><path d="M9.4 6.2A9.3 9.3 0 0 1 12 5.8c5.8 0 9.4 6.2 9.4 6.2a17.6 17.6 0 0 1-2.9 3.5M6.7 8.2A16.6 16.6 0 0 0 2.6 12S6.2 18.2 12 18.2a9.4 9.4 0 0 0 3.2-.55"/></svg>',
  wave: '<svg class="iv" viewBox="0 0 24 24"><path d="M2.8 12h2.4l2.1-5.6 2.9 12.4 2.9-15.6 2.4 8.8h5.9"/></svg>',
  cloud: '<svg class="iv" viewBox="0 0 24 24"><path d="M7.2 18.4h10a3.9 3.9 0 0 0 .5-7.77 5.6 5.6 0 0 0-10.7-1.4 4.2 4.2 0 0 0 .2 9.17z"/></svg>',
  log: '<svg class="iv" viewBox="0 0 24 24"><path d="M6 3.4h8.4L19 8v12.6H6z"/><path d="M14 3.4V8h4.6"/><path d="M8.8 12.4h6.4M8.8 15.8h4.4"/></svg>',
};

const TAB_TITLE = { now: '正在播放', devices: '我的设备', lib: '本地曲库', online: '在线搜索', queue: '播放列表' };
function switchTab(name, force) {
  S.tab = name;
  ['now', 'devices', 'lib', 'online', 'queue'].forEach(t => {
    $('tab-' + t).style.display = (t === name) ? '' : 'none';
  });
  document.querySelectorAll('.navbtn').forEach(b => {
    b.classList.toggle('on', b.getAttribute('data-tab') === name);
  });
  $('topTitle').textContent = TAB_TITLE[name] || 'SyncDlnaPlay';
  $('main').scrollTop = 0;
  if (name === 'now') renderNowTab();
  if (name === 'lib') loadLib();
  if (name === 'queue') renderQueue();
}

/* =========================================================================
   四、设备
   ========================================================================= */
function devices() { return (S.state && S.state.devices) || []; }
function selectedDevices() { return devices().filter(d => d.selected); }
function selectedUdns() { return selectedDevices().map(d => d.udn); }

function renderTopDev() {
  const sel = selectedDevices();
  const el = $('topDev');
  if (!sel.length) { el.textContent = '选择音响'; el.classList.remove('on'); return; }
  el.classList.add('on');
  el.textContent = sel.length === 1 ? (sel[0].name || '音响') : (sel.length + ' 台同步');
}

const STATE_TXT = { PLAYING: '播放中', PAUSED: '已暂停', STOPPED: '已停止', TRANSITIONING: '缓冲中' };
function renderDevices() {
  const box = $('devList');
  if (!S.state) { box.innerHTML = '<div class="empty"><span class="spin"></span> 读取设备…</div>'; return; }
  const ds = devices();
  $('devCount').textContent = S.state.scanning ? '扫描中…' : (ds.length + ' 台设备');
  if (!ds.length) {
    box.innerHTML = '<div class="empty">还没发现音响<br><span class="sm">确认音响已开机、和手机在同一个 WiFi，然后点「重新扫描」</span></div>';
    return;
  }
  box.innerHTML = ds.map((d, i) => {
    const on = d.online !== false;
    const stTxt = d.state && STATE_TXT[d.state] ? STATE_TXT[d.state] : (on ? '' : '离线');
    const sub = [d.ip, stTxt].filter(Boolean).join(' · ') + (d.title ? (' · ' + d.title) : '');
    return `<div class="item">
      <div class="ico" style="color:${on ? 'var(--acc)' : 'var(--tx3)'}">${d.selected ? '🔊' : '🔈'}</div>
      <div class="txt" onclick="toggleDev(${i})">
        <div class="t1">${esc(d.name || '未知设备')}${d.selected ? ' <span class="sm" style="color:var(--acc)">· 已选</span>' : ''}</div>
        <div class="t2">${esc(sub)}</div>
      </div>
      <div class="act">
        ${d.has_volume !== false ? `<button class="iconbtn sm2" title="音量" onclick="volumeSheet(${i})">🔉</button>` : ''}
        ${d.has_volume !== false ? `<button class="iconbtn sm2" title="更多设置" onclick="devSheet(${i})">⚙</button>` : ''}
        <button class="iconbtn sm2" title="${d.selected ? '取消' : '选择'}" onclick="toggleDev(${i})">${d.selected ? '☑' : '☐'}</button>
      </div>
    </div>`;
  }).join('');
  if (!selectedDevices().length) {
    $('devTip').innerHTML = '提示：先点一台音响把它选上，再回「曲库」或「在线」点歌播放。选中多台可以多房间同步播放。';
  } else {
    $('devTip').innerHTML = '';
  }
}

async function toggleDev(i) {
  buzz();
  const d = devices()[i];
  if (!d) return;
  const cur = selectedUdns();
  const idx = cur.indexOf(d.udn);
  if (idx >= 0) cur.splice(idx, 1); else cur.push(d.udn);
  try {
    await apiPost('/api/targets', { udns: cur });
    await tick(true);
  } catch (e) { toast('选择失败：' + e.message, 'err'); }
}

function devSheet(i) {
  const d = devices()[i];
  if (!d) return;
  const delay = d.delay_ms || 0;
  openSheet(esc(d.name || '设备'), `
    <div class="sec-title">多房间同步微调</div>
    <div class="row gap8">
      <button class="btn sm" onclick="setDelay(-200)">−200ms</button>
      <button class="btn sm" onclick="setDelay(-50)">−50ms</button>
      <button class="btn sm" onclick="setDelay(50)">+50ms</button>
      <button class="btn sm" onclick="setDelay(200)">+200ms</button>
      <span class="grow"></span>
      <b class="sm muted" id="delayNum">${delay}ms</b>
    </div>
    <div class="sm muted" style="margin-top:8px">
      两台以上音响同时播放时，声音会有一前一后。给先出声那台加一点延迟就能对齐；
      点「设备」页的「同步校准」可以自动测。
    </div>
    <div class="chips">
      <div class="chip ${d.selected ? 'on' : ''}" onclick="toggleFromSheet(${i})">${d.selected ? '✓ 已加入同步' : '加入同步播放'}</div>
      <div class="chip" onclick="closeSheet()">关闭</div>
    </div>
  `);
  S._devIdx = i;
}
async function toggleFromSheet(i) { await toggleDev(i); closeSheet(); devSheet(i); }

async function setDelay(ms) {
  const d = devices()[S._devIdx]; if (!d) return;
  const nd = (d.delay_ms || 0) + ms;
  try {
    const r = await apiPost('/api/delay', { udn: d.udn, delay_ms: nd });
    const el = $('delayNum'); if (el) el.textContent = (r.delay_ms || nd) + 'ms';
    await tick(true);
  } catch (e) { toast('设置失败：' + e.message, 'err'); }
}

/* =========================================================================
   五、曲库
   ========================================================================= */
async function loadLib() {
  const box = $('libList');
  const src = S.lib.source;
  if (src === 'dlna' && !S.lib.container) S.lib.container = '0';
  box.innerHTML = '<div class="empty"><span class="spin"></span> 读取中…</div>';
  try {
    const r = await api('/api/library?source=' + q(src) + '&container=' + q(S.lib.container || ''));
    if (r.scanning && !(r.items || []).length) {
      box.innerHTML = '<div class="empty"><span class="spin"></span> 正在扫描音乐目录…<br><span class="sm">' + esc(r.scanning_dir || '') + '</span></div>';
      setTimeout(() => { if (S.tab === 'lib') loadLib(); }, 2500);
      return;
    }
    renderLib(r);
  } catch (e) {
    box.innerHTML = '<div class="empty">读取失败：' + esc(e.message) + '</div>';
  }
}

function renderLib(r) {
  const box = $('libList');
  const rows = [];
  S._libItems = (r.items || []).filter(t => t.type !== 'container');
  const folders = (r.folders || []).map(f => {
    if (typeof f === 'string') return { name: f, path: joinPath(S.lib.container, f) };
    return { name: f.title || f.name || '', path: f.id };
  });
  if (!folders.length && !(r.items || []).length) {
    box.innerHTML = '<div class="empty">这个目录是空的</div>';
    renderCrumbs();
    return;
  }
  folders.forEach(f => {
    rows.push(`<div class="item" onclick="enterFolder('${esc(f.path).replace(/'/g, "&#39;")}')">
      <div class="ico">📁</div>
      <div class="txt"><div class="t1">${esc(f.name)}</div></div>
      <div class="act"><button class="iconbtn sm2" onclick="event.stopPropagation();playFolder('${esc(f.path).replace(/'/g, "&#39;")}')" title="播放整个文件夹">▶</button></div>
    </div>`);
  });
  let ti = 0;
  (r.items || []).forEach(t => {
    if (t.type === 'container') {
      rows.push(`<div class="item" onclick="enterFolder('${esc(t.id).replace(/'/g, "&#39;")}')">
        <div class="ico">💿</div>
        <div class="txt"><div class="t1">${esc(t.title || '')}</div></div>
        <div class="act"><button class="iconbtn sm2" onclick="event.stopPropagation();playFolder('${esc(t.id).replace(/'/g, "&#39;")}')" title="播放整张">▶</button></div>
      </div>`);
      return;
    }
    rows.push(trackRow(t, ti, 'lib'));
    ti++;
  });
  box.innerHTML = rows.join('');
  renderCrumbs();
  if (r.truncated) box.innerHTML += '<div class="sec">目录太大，仅索引了前一部分曲目。</div>';
  libActionsUpdate();
}

function joinPath(a, b) { return a ? (a.replace(/\/+$/, '') + '/' + b) : b; }

function trackRow(t, i, kind) {
  const sub = [t.artist, t.album, t.duration_sec ? fmt(t.duration_sec) : ''].filter(Boolean).join(' · ');
  return `<div class="item">
    <div class="ico" onclick="playOne('${kind}',${i})">♫</div>
    <div class="txt" onclick="playOne('${kind}',${i})">
      <div class="t1">${esc(t.title || '未知')}</div>
      <div class="t2">${esc(sub)}</div>
    </div>
    <div class="act">
      <button class="iconbtn sm2" title="加入列表" onclick="addOne('${kind}',${i})">＋</button>
      <button class="iconbtn sm2" title="手机播放" onclick="playOne('${kind}',${i},true)">📱</button>
    </div>
  </div>`;
}

function curItems() {
  if (S.tab === 'online') return S.online.items || [];
  return S._libItems || [];
}
function getItems(kind) {
  if (kind === 'online') return S.online.items || [];
  return S._libItems || [];
}

function renderCrumbs() {
  const c = $('crumbs');
  const crumbs = S.lib.crumbs || [];
  let html = `<div class="crumb" onclick="crumbTo(-1)">${S.lib.source === 'local' ? '🏠 本机音乐' : '🏠 媒体库'}</div>`;
  crumbs.forEach((x, i) => {
    html += `<div class="crumb${i === crumbs.length - 1 ? ' on' : ''}" onclick="crumbTo(${i})">${esc(x.name)}</div>`;
  });
  c.innerHTML = html;
}
function crumbTo(i) {
  const crumbs = S.lib.crumbs || [];
  if (i < 0) { S.lib.container = S.lib.source === 'local' ? '' : '0'; S.lib.crumbs = []; }
  else {
    const pick = crumbs[i];
    S.lib.container = pick.path;
    S.lib.crumbs = crumbs.slice(0, i + 1);
  }
  loadLib();
}
function enterFolder(path) {
  const name = path.split('/').pop();
  S.lib.crumbs = (S.lib.crumbs || []).concat([{ path: path, name: name }]);
  S.lib.container = path;
  loadLib();
}
async function playFolder(path) {
  toast('正在准备播放…');
  try {
    const r = await apiPost('/api/play-container', { source: S.lib.source, container: path, index: 0 }, 60000);
    if (!r.ok) throw new Error(r.result || '失败');
    toast('已开始播放（' + (r.total || 0) + ' 首）', 'ok');
  } catch (e) { toast('播放失败：' + e.message, 'err'); }
}

async function loadLibSearch() {
  const kw = window.__libKw || '';
  if (!kw) { loadLib(); return; }
  const box = $('libList');
  box.innerHTML = '<div class="empty"><span class="spin"></span> 搜索中…</div>';
  try {
    const r = await api('/api/search?source=' + q(S.lib.source) + '&q=' + q(kw));
    S._libItems = r.items || [];
    if (!S._libItems.length) { box.innerHTML = '<div class="empty">没找到「' + esc(kw) + '」</div>'; return; }
    box.innerHTML = `<div class="sec">找到 ${S._libItems.length} 首</div>` +
      S._libItems.map((t, i) => trackRow(t, i, 'lib')).join('');
    libActionsUpdate();
  } catch (e) { box.innerHTML = '<div class="empty">搜索失败：' + esc(e.message) + '</div>'; }
}

/* --- 曲库「更多」 --- */
function libMore() {
  openSheet('曲库工具', `
    <div class="chips">
      <div class="chip" onclick="closeSheet();libSearch()">🔍 搜索曲库</div>
      <div class="chip" onclick="closeSheet();playFolder(S.lib.container||'0')">▶ 播放当前目录全部</div>
      <div class="chip" onclick="closeSheet();addFolderAll()">＋ 当前目录全部入列表</div>
      <div class="chip" onclick="closeSheet();rescanLib()">↻ 重新扫描本机音乐</div>
      <div class="chip" onclick="closeSheet();musicSourcesSheet()">🗂 音乐目录管理</div>
    </div>
    <div class="sec-title">说明</div>
    <div class="sm muted">
      「本机音乐」= 服务端配置的音乐目录（可在「音乐目录管理」里加本地文件夹或 SMB 共享）。<br>
      「媒体库」= 局域网里的 DLNA 媒体服务器（如 MiniDLNA）。
    </div>
  `);
}
function libSearch() {
  openSheet('搜索曲库', `
    <input id="libKw" type="search" placeholder="歌曲名 / 专辑名" enterkeyhint="search">
    <div class="row gap8" style="margin-top:10px">
      <button class="btn pri grow" onclick="doLibSearch()">搜索</button>
      <button class="btn" onclick="closeSheet();loadLib()">返回列表</button>
    </div>
  `);
  setTimeout(() => { const el = $('libKw'); if (el) el.focus(); }, 150);
}
function doLibSearch() {
  window.__libKw = ($('libKw').value || '').trim();
  closeSheet();
  if (!window.__libKw) { loadLib(); return; }
  loadLibSearch();
}
async function addFolderAll() {
  const items = (S._libItems || []);
  if (!items.length) { toast('当前目录没有曲目', 'err'); return; }
  await addToQueue(items);
}
async function rescanLib() {
  try { await apiPost('/api/music/rescan'); toast('已开始重新扫描', 'ok'); setTimeout(loadLib, 1500); }
  catch (e) { toast('失败：' + e.message, 'err'); }
}

/* =========================================================================
   六、音乐目录管理（本地文件夹 / SMB 共享）
   ========================================================================= */
async function musicSourcesSheet() {
  openSheet('曲库管理', '<div class="empty"><span class="spin"></span> 读取中…</div>');
  try {
    const info = (AB && AB.getLibraryInfo) ? JSON.parse(AB.getLibraryInfo() || '{}') : {};
    const perm = (AB && AB.getPermissionState) ? AB.getPermissionState() : 'granted';
    const st = (AB && AB.getStorageInfo) ? JSON.parse(AB.getStorageInfo() || '{}') : {};
    const dirs = (AB && AB.getMusicDirs) ? JSON.parse(AB.getMusicDirs() || '[]') : [];
    const last = info.last_scan ? new Date(info.last_scan * 1000).toLocaleString() : '—';
    const logCount = (AB && AB.getCrashCount) ? AB.getCrashCount() : 0;

    const dirRows = dirs.length ? dirs.map(d => `
      <div class="item">
        <div class="ico">${d.type === 'smb' ? '🖧' : '📁'}</div>
        <div class="txt">
          <div class="t1">${esc(d.name)}</div>
          <div class="t2">${esc(d.addr)} · ${d.count || 0} 首</div>
        </div>
        <div class="act">
          <button class="iconbtn sm2" title="移除" onclick="removeMusicDir('${esc(d.id)}')">🗑</button>
        </div>
      </div>`).join('')
      : '<div class="sm muted" style="padding:6px 0">还没添加其它目录。手机里的歌靠系统媒体库自动收录。</div>';

    $('sheetBody').innerHTML = `
      <div class="sec-title">下载目录</div>
      <div class="sm muted" style="word-break:break-all;line-height:1.6">${esc(st.dir || '—')}</div>
      <div class="chips" style="margin-top:8px">
        <div class="chip" onclick="AB&&AB.pickDownloadFolder&&AB.pickDownloadFolder()">📂 更改目录</div>
        <div class="chip" onclick="AB&&AB.openDownloads&&AB.openDownloads()">打开看看</div>
        ${st.custom ? '<div class="chip" onclick="resetDlDir()">↺ 恢复默认</div>' : ''}
      </div>
      <div class="sm muted" style="margin-top:6px">下载的歌会存到这里。默认放在公共音乐目录「Music/音响管家」，手机「文件管理」里能直接看到，系统音乐 App 也能扫到。</div>

      <div class="sec-title">音乐目录</div>
      ${dirRows}
      <div class="chips" style="margin-top:8px">
        <div class="chip vi" onclick="AB&&AB.pickMusicFolder&&AB.pickMusicFolder()">${I.folderAdd} 添加本机目录</div>
        <div class="chip vi" onclick="srcAdd('smb')">${I.net} 添加网络共享</div>
      </div>
      <div class="sm muted" style="margin-top:6px">
        「添加本机目录」会打开系统文件选择器，除了本地文件夹，还能选 SD 卡、U 盘，
        以及系统「文件」里已挂载好的网络位置。
      </div>

      <div class="sec-title">本机曲库</div>
      <div class="sm muted" style="margin-bottom:10px;line-height:1.7">
        曲目数：<b style="color:var(--tx)">${info.count || 0}</b> 首${info.scanning ? ' · 扫描中…' : ''}<br>
        上次扫描：${esc(last)}<br>
        读取权限：<b style="color:${perm === 'granted' ? 'var(--acc)' : 'var(--warn)'}">${perm === 'granted' ? '已授权' : '未授权（读不到手机里的音乐）'}</b>
        ${info.truncated ? '<br><b style="color:var(--warn)">曲目超过 3 万首，已截断</b>' : ''}
        ${info.error ? '<br>错误：' + esc(info.error) : ''}
      </div>
      <div class="row gap8">
        <button class="btn pri grow" onclick="rescanLibrary()">重新扫描</button>
        ${perm !== 'granted' ? '<button class="btn grow" onclick="AB&&AB.requestAudioPermission&&AB.requestAudioPermission()">申请权限</button>' : ''}
      </div>

      <div class="sec-title">运行日志</div>
      <div class="sm muted" style="margin-bottom:8px;line-height:1.7">
        ${logCount
          ? '已记录 <b style="color:var(--warn)">' + logCount + '</b> 条异常。'
          : '暂无异常记录。'}<br>
        后台异常会被自动拦截，不再让应用闪退；记录留在这里，可直接复制出来定位。
      </div>
      <div class="row gap8">
        <button class="btn grow" onclick="showCrashLogs()">查看日志</button>
        ${logCount ? '<button class="btn grow" onclick="clearCrashLogs()">清空</button>' : ''}
      </div>

    </div>

    <div class="sec-title">关于</div>
      <div class="sm muted">独立运行版：DLNA 控制、曲库扫描、在线音源全部在手机本机运行，不依赖家中服务器，换任何网络都能用。</div>`;
  } catch (e) { $('sheetBody').innerHTML = '<div class="empty">读取失败：' + esc(e.message) + '</div>'; }
}

/* ---- 下载目录 / 音乐目录 的界面回调 ---- */
function resetDlDir() {
  try { if (AB && AB.resetDownloadFolder) AB.resetDownloadFolder(); } catch (e) { }
  toast('已恢复默认下载目录', 'ok');
  setTimeout(musicSourcesSheet, 500);
}
function removeMusicDir(id) {
  try { if (AB && AB.removeMusicDir) AB.removeMusicDir(id); } catch (e) { }
  toast('已移除', 'ok');
  setTimeout(function () { musicSourcesSheet(); loadLib(); }, 900);
}
window.__onStorageChanged = function () { musicSourcesSheet(); };
window.__onMusicDirsChanged = function () {
  toast('已添加，正在扫描…', 'ok');
  setTimeout(function () { musicSourcesSheet(); loadLib(); }, 1500);
};

/* =========================================================================
   歌词
   ========================================================================= */
/** 时间标签 [mm:ss.xx] -> 秒 */
function parseLrc(text) {
  const out = [];
  if (!text) return out;
  // 两种主流时间标签：[mm:ss.xx]（标准）与 [ss.xx]（纯秒，如元力KW）
  const reMMSS = /\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g;
  const reSS = /\[(\d{1,3})(?:\.(\d{1,3}))?\]/g;

  function collect(line, re, toSec) {
    re.lastIndex = 0;
    const hits = [];
    let m;
    while ((m = re.exec(line)) !== null) {
      hits.push({ t: toSec(m), start: m.index, end: m.index + m[0].length });
    }
    return hits;
  }
  function secMMSS(m) {
    const min = parseInt(m[1], 10), sec = parseInt(m[2], 10);
    let frac = 0;
    if (m[3]) frac = parseInt(m[3], 10) / Math.pow(10, m[3].length);
    return min * 60 + sec + frac;
  }
  function secSS(m) {
    let frac = 0;
    if (m[2]) frac = parseInt(m[2], 10) / Math.pow(10, m[2].length);
    return parseInt(m[1], 10) + frac;
  }

  text.split(/\r?\n/).forEach(function (line) {
    let hits = collect(line, reMMSS, secMMSS);
    if (!hits.length) hits = collect(line, reSS, secSS);
    if (!hits.length) return;
    // 每个时间标签「到下一个标签之前」的文字就是它对应的歌词
    const segs = hits.map(function (h, i) {
      const to = i + 1 < hits.length ? hits[i + 1].start : line.length;
      return line.slice(h.end, to).trim();
    });
    const body = segs.filter(function (s) { return s; });
    if (!body.length) return;
    if (body.length === 1) {
      // 标准写法：[t1][t2]同一句 -> 这些时间点共用这一句
      hits.forEach(function (h) { out.push({ t: h.t, text: body[0] }); });
    } else {
      // 行内写法：[t1]第一句[t2]第二句 -> 各归各的
      hits.forEach(function (h, i) { if (segs[i]) out.push({ t: h.t, text: segs[i] }); });
    }
  });
  out.sort(function (a, b) { return a.t - b.t; });
  return out;
}

function trackKeyOf(t) {
  if (!t) return '';
  return [t.source || 'local', t.provider || '', t.id || '', t.title || ''].join('|');
}

/** 取歌词：在线曲目问插件；本地曲目读同目录 .lrc；都没有再查标题歌词库；本地歌还会在线搜词 */
async function loadLyric(t) {
  const box = $('lyricBox');
  if (!box) return;
  const key = trackKeyOf(t);
  if (!key || S.lyric.key === key) { renderLyric(); return; }
  S.lyric = { key: key, lines: [], idx: -1, msg: '加载歌词…' };
  renderLyric();
  let lrc = '';
  try {
    if (t.source === 'online' && window.PluginHost && t.provider && (t.id || t.oid)) {
      const r = await window.PluginHost.lyric({ provider: t.provider, id: t.id || t.oid });
      lrc = (r && (r.lrc || r.rawLrc || r.lyric)) || '';
    }
    if (!lrc && t.id) {
      const r = await api('/api/lyric?id=' + encodeURIComponent(t.id), { _timeout: 12000 });
      lrc = (r && r.lrc) || '';
    }
    if (!lrc && t.title) {                    // 标题歌词库（下载/本地歌在线找词后落盘）
      const r = await api('/api/lyric/byname?artist=' + enc(t.artist) + '&title=' + enc(t.title), { _timeout: 8000 });
      lrc = (r && r.lrc) || '';
    }
    if (!lrc && t.source !== 'online' && (t.title || t.artist)) {
      lrc = await onlineLyricForLocal(t);     // 本地音乐：搜索匹配并下载歌词
    }
  } catch (e) { lrc = lrc || ''; }
  if (S.lyric.key !== key) return;      // 这期间已经切歌了
  const lines = parseLrc(lrc);
  S.lyric = { key: key, lines: lines, idx: -1, msg: lines.length ? '' : '这首歌没有歌词' };
  renderLyric();
}

function enc(s) { return encodeURIComponent(s == null ? '' : s); }

/** 本地音乐在线找歌词：按歌名+歌手搜索，取最匹配一首的歌词，落盘后返回 */
async function onlineLyricForLocal(t) {
  const PH = window.PluginHost;
  if (!PH || !PH.search) return '';
  const neg = lyricNoMatchKey(t);
  try { const nm = localStorage.getItem('dlna_lyric_nomatch') || ''; if (nm.indexOf(neg) >= 0) return ''; } catch (e) { }
  try {
    const q = ((t.artist || '') + ' ' + (t.title || '')).trim();
    const r = await PH.search({ q: q, provider: (S.online && S.online.provider) || '', limit: 8 });
    const items = (r && r.items) || [];
    if (!items.length) { markLyricNoMatch(t); return ''; }
    let hit = null, best = -1;
    const want = normTitle(t.title);
    for (let i = 0; i < items.length; i++) {
      const sr = normTitle(items[i].title);
      const sc = (want && sr) ? (want === sr ? 100 : (want.indexOf(sr) >= 0 || sr.indexOf(want) >= 0 ? 70 : 0)) : 0;
      if (sc > best) { best = sc; hit = items[i]; }
    }
    if (!hit || !(hit.id || hit.oid)) { markLyricNoMatch(t); return ''; }
    const lr = await PH.lyric({ provider: hit.provider || hit.platform, id: hit.id || hit.oid });
    const lrc = (lr && (lr.lrc || lr.rawLrc || lr.lyric)) || '';
    if (!lrc.trim()) { markLyricNoMatch(t); return ''; }
    try { await apiPost('/api/lyric/save', { artist: t.artist || '未知歌手', title: t.title || '未知', lrc: lrc }); } catch (e) { }
    return lrc;
  } catch (e) { return ''; }
}

function normTitle(s) {
  return (s || '').toLowerCase().replace(/\s+/g, ' ')
    .replace(/[()\[\]【】\/\\\-_~!！，,。.、:：'\u2019\"\u201c\u201d?？]/g, '').trim();
}
function lyricNoMatchKey(t) { return (t.title || '') + '|' + (t.artist || ''); }
function markLyricNoMatch(t) {
  try {
    const k = 'dlna_lyric_nomatch';
    let sv = localStorage.getItem(k) || '';
    const key = lyricNoMatchKey(t);
    if (sv.indexOf(key) < 0) { sv = (sv + '|' + key); if (sv.length > 2000) sv = sv.slice(sv.length - 2000); localStorage.setItem(k, sv); }
  } catch (e) { }
}

function renderLyric() {
  const box = $('lyricBox');
  if (!box) return;
  const L = S.lyric;
  const art = $('npArt');
  if (!L.lines.length) {
    // 没歌词 → 封面回归
    if (art) art.style.display = '';
    box.style.display = 'none';
    box.innerHTML = '<div class="empty sm" style="padding:18px">' + esc(L.msg || '暂无歌词') + '</div>';
    return;
  }
  // 有歌词 → 歌词替代封面（同台合并）
  if (art) art.style.display = 'none';
  box.style.display = '';
  box.innerHTML = L.lines.map(function (l, i) {
    return '<div class="lrc-line' + (i === L.idx ? ' on' : '') + '" onclick="lrcLineTap(' + l.t + ')">' + esc(l.text) + '</div>';
  }).join('');
  const on = box.querySelector('.lrc-line.on');
  if (on && on.scrollIntoView) {
    try { on.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) { }
  }
  if (S._imm) immSync();   // 沉浸模式开着时同步大屏歌词
}

/* ---- 沉浸歌词模式（v2.11）：双击歌词进入，全屏歌词 + 底部播放/音量控制 ----
   单击歌词行 = 跳转（延迟 300ms 执行，给双击留判断窗口）；
   350ms 内第二次点击 = 双击 → 进沉浸，并取消第一次排队的跳转。 */
function lrcLineTap(sec) {
  const now = Date.now();
  if (S._lrcTapAt && now - S._lrcTapAt < 350) {
    S._lrcTapAt = 0;
    clearTimeout(S._lrcTapTimer); S._lrcTapTimer = null;
    enterImmersive();
    return;
  }
  S._lrcTapAt = now;
  clearTimeout(S._lrcTapTimer);
  S._lrcTapTimer = setTimeout(function () { S._lrcTapTimer = null; seekToTime(sec); }, 300);
}

function immBuild() {
  if ($('imm')) return;
  const d = document.createElement('div');
  d.id = 'imm';
  d.className = 'imm';
  d.innerHTML =
    '<div class="imm-head">'
    + '<div class="imm-meta"><div id="immTitle"></div><div id="immSub" class="sm muted"></div></div>'
    + '<button class="btn sm" id="immLandBtn" onclick="toggleImmLand()">⇄ 横屏</button>'
    + '<button class="btn sm" onclick="exitImmersive()">✕ 退出</button></div>'
    + '<div class="imm-lrc lrc-box" id="immLrc"></div>'
    + '<div class="imm-ctl">'
    + '<div class="imm-btns">'
    + '<button class="btn" onclick="ctl(\'prev\')">⏮</button>'
    + '<button class="btn pri" id="immPlay" style="min-width:76px" onclick="ctl(nowPlaying().playing ? \'pause\' : \'play\')">⏸</button>'
    + '<button class="btn" onclick="ctl(\'next\')">⏭</button>'
    + '</div>'
    + '<div class="imm-vol"><span class="sm muted">🔊</span>'
    + '<input id="immVol" type="range" min="0" max="100" oninput="immVolLive(this.value)" onchange="volCommit(this.value)">'
    + '<span id="immVolVal" class="sm" style="min-width:36px;text-align:right"></span>'
    + '</div></div>';
  d.addEventListener('dblclick', exitImmersive);
  d.addEventListener('click', function (e) {
    const tg = e.target;
    if (tg.closest && tg.closest('.imm-ctl')) return;     // 控制按钮/滑条自身照常工作
    if (tg.closest && tg.closest('.imm-head')) return;
    toggleImmCtl();                                       // 点歌词或空白：唤出/收起控件
  });
  document.body.appendChild(d);
}

function enterImmersive() {
  if (!nowPlaying().t) { toast('先播放一首歌'); return; }
  immBuild();
  S._imm = true;
  S._volPhone = (S.out === 'phone');   // 音量滑条复用 volCommit 所需状态
  S._volIdx = null; S._volDirty = false;
  const el = $('imm');
  el.style.display = 'flex';
  const v = $('immVol');
  if (v) {
    const pc = S._volPhone ? Math.round((audio.volume == null ? 1 : audio.volume) * 100)
                           : avgVol(null);
    v.value = (isNaN(pc) || pc <= 0) ? 50 : pc;
  }
  immSync();
}

function exitImmersive() {
  S._imm = false;
  if (S._immLand) {
    S._immLand = false;
    if (AB && AB.setOrientation) { try { AB.setOrientation('unlock'); } catch (e) { } }
  }
  const el = $('imm');
  if (el) { el.style.display = 'none'; el.classList.remove('land'); }
}

/** 沉浸歌词：点一下唤出/收起控制条（默认只显歌词，几秒后自动隐藏） */
function toggleImmCtl() {
  const el = $('imm'); if (!el) return;
  const on = el.classList.toggle('ctl-on');
  if (S._immCtlTimer) { clearTimeout(S._immCtlTimer); S._immCtlTimer = null; }
  if (on) {
    S._immCtlTimer = setTimeout(function () { const e = $('imm'); if (e) e.classList.remove('ctl-on'); S._immCtlTimer = null; }, 4500);
  }
}

/** 沉浸歌词横屏开关：旋转到横屏、放大歌词、隐藏音量条 */
function toggleImmLand() {
  S._immLand = !S._immLand;
  const el = $('imm');
  if (!el) return;
  el.classList.toggle('land', S._immLand);
  if (AB && AB.setOrientation) {
    try { AB.setOrientation(S._immLand ? 'land' : 'unlock'); } catch (e) { }
  }
  const b = $('immLandBtn');
  if (b) b.textContent = S._immLand ? '⇅ 竖屏' : '⇄ 横屏';
  immSync();
}

function immVolLive(v) {
  const el = $('immVolVal');
  if (el) el.textContent = v;
}

/** 沉浸层刷新：歌名 / 播放键图标 / 音量数字 / 大屏歌词高亮滚动。
    由 renderLyric（行变化）与 300ms 定时器驱动。 */
function immSync() {
  if (!S._imm) return;
  const n = nowPlaying();
  const t = n.t || {};
  const ti = $('immTitle'); if (ti) ti.textContent = t.title || '未播放';
  const su = $('immSub'); if (su) su.textContent = [t.artist, t.album].filter(Boolean).join(' · ');
  const pb = $('immPlay'); if (pb) pb.textContent = n.playing ? '⏸' : '▶';
  const vv = $('immVolVal'), ve = $('immVol');
  if (vv && ve) vv.textContent = ve.value;
  const box = $('immLrc');
  if (!box) return;
  const L = S.lyric;
  if (!L.lines.length) {
    box.innerHTML = '<div class="empty" style="padding:48px 26px">' + esc(L.msg || '暂无歌词') + '</div>';
    return;
  }
  box.innerHTML = L.lines.map(function (l, i) {
    return '<div class="lrc-line' + (i === L.idx ? ' on' : '') + '">' + esc(l.text) + '</div>';
  }).join('');
  const on = box.querySelector('.lrc-line.on');
  if (on && on.scrollIntoView) { try { on.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) { } }
}

/* ---- 歌词快慢校准（v2.9）：投音响有传输延时且因文件而异，让用户手动校 ----
   正值 = 歌词提前显示（快），负值 = 延后（慢）；单位 ms，步进 500 */
function lyricOffGet() {
  let v = parseInt(S.lyricOff != null ? S.lyricOff : (function () {
    try { return localStorage.getItem('dlna_lyricoff') || '0'; } catch (e) { return '0'; }
  })(), 10);
  if (isNaN(v)) v = 0;
  return v;
}
function lyricOffLabel() {
  const v = lyricOffGet();
  return v === 0 ? '无偏移' : (v > 0 ? '提前 ' + (v / 1000) + 's' : '延后 ' + (-v / 1000) + 's');
}
function lyricOffShift(d) {
  let v = lyricOffGet() + d;
  if (v > 10000) v = 10000; if (v < -10000) v = -10000;
  S.lyricOff = v;
  try { localStorage.setItem('dlna_lyricoff', String(v)); } catch (e) { }
  const el = $('lrcOffVal');
  if (el) el.textContent = lyricOffLabel();
  toast(v > 0 ? '歌词提前 ' + (v / 1000) + 's' : (v < 0 ? '歌词延后 ' + (-v / 1000) + 's' : '歌词无偏移'), 'ok');
  updateLyricProgress(nowPlaying().pos);
}

/* ---- v2.18：歌词字号调节 ---- */
function lyricSizeSaved() {
  try { const v = parseInt(localStorage.getItem('dlna_lyricsize') || '21', 10); return isNaN(v) ? 21 : v; }
  catch (e) { return 21; }
}
function setLyricSize(px) {
  px = Math.max(14, Math.min(42, parseInt(px, 10) || 21));
  try { localStorage.setItem('dlna_lyricsize', String(px)); } catch (e) { }
  const root = document.documentElement;
  root.style.setProperty('--lyr-base', px + 'px');
  root.style.setProperty('--lyr-on', Math.round(px * 1.33) + 'px');
  const el = $('lyrSizeVal'); if (el) el.textContent = px + 'px';
}
/* ---- v2.18：主题配色切换 ---- */
const THEMES = [
  { key: 'cyan', label: '霓虹青' },
  { key: 'amber', label: '琥珀金' },
  { key: 'pink', label: '玫瑰粉' },
  { key: 'green', label: '极光绿' },
  { key: 'violet', label: '电光紫' }
];
function themeSaved() {
  try { return localStorage.getItem('dlna_theme') || 'cyan'; }
  catch (e) { return 'cyan'; }
}
function setTheme(key) {
  key = key || 'cyan';
  try { localStorage.setItem('dlna_theme', key); } catch (e) { }
  applyTheme();
  const t = THEMES.find(x => x.key === key);
  toast('主题：' + (t ? t.label : key), 'ok');
}
function applyTheme() {
  const key = themeSaved();
  const html = document.documentElement;
  THEMES.forEach(t => html.classList.remove('theme-' + t.key));
  html.classList.add('theme-' + key);
}
function applyLyricSize() {
  const px = lyricSizeSaved();
  const root = document.documentElement;
  root.style.setProperty('--lyr-base', px + 'px');
  root.style.setProperty('--lyr-on', Math.round(px * 1.33) + 'px');
}
/* ---- v2.19：横屏歌词字号独立调节 ---- */
function lyricSizeLandSaved() {
  try { const v = parseInt(localStorage.getItem('dlna_lyricsize_land') || '24', 10); return isNaN(v) ? 24 : v; }
  catch (e) { return 24; }
}
function setLandLyricSize(px) {
  px = Math.max(14, Math.min(42, parseInt(px, 10) || 24));
  try { localStorage.setItem('dlna_lyricsize_land', String(px)); } catch (e) { }
  const root = document.documentElement;
  root.style.setProperty('--lyr-land-base', px + 'px');
  root.style.setProperty('--lyr-land-on', Math.round(px * 1.33) + 'px');
  const el = $('lyrSizeLandVal'); if (el) el.textContent = px + 'px';
}
function applyLandLyricSize() {
  const px = lyricSizeLandSaved();
  const root = document.documentElement;
  root.style.setProperty('--lyr-land-base', px + 'px');
  root.style.setProperty('--lyr-land-on', Math.round(px * 1.33) + 'px');
}

/** 由播放进度驱动高亮；只在行变化时重绘，避免拖慢主循环 */
function updateLyricProgress(pos) {
  const L = S.lyric;
  if (!L.lines.length) return;
  const eff = pos + lyricOffGet() / 1000;   // 校准：正=提前，负=延后
  let idx = -1;
  for (let i = 0; i < L.lines.length; i++) {
    if (L.lines[i].t <= eff + 0.25) idx = i; else break;
  }
  if (idx !== L.idx) { L.idx = idx; renderLyric(); }
}

function seekToTime(sec) {
  S._seekPos = Math.floor(sec);
  S._seekAt = performance.now();
  if (S.out === 'phone') { try { audio.currentTime = sec; } catch (e) { } return; }
  apiPost('/api/seek', { position: Math.floor(sec) }).catch(function () { });
}

/* ---- 运行日志：后台异常已被拦截并落盘，这里只是把它读出来给人看 ---- */
function showCrashLogs() {
  let text = '', dir = '';
  try { text = (AB && AB.getCrashLogs) ? (AB.getCrashLogs() || '') : ''; } catch (e) { text = ''; }
  try { dir = (AB && AB.getCrashLogDir) ? (AB.getCrashLogDir() || '') : ''; } catch (e) { dir = ''; }
  openSheet('运行日志', `
    ${dir ? `<div class="sm muted" style="margin-bottom:8px;word-break:break-all">日志目录：${esc(dir)}</div>` : ''}
    <pre style="white-space:pre-wrap;word-break:break-all;font-size:11px;line-height:1.6;color:var(--tx2);background:var(--bg2);border-radius:10px;padding:10px;max-height:52vh;overflow:auto;margin:0">${esc(text || '（暂无异常记录）')}</pre>
    <div class="row gap8" style="margin-top:10px">
      <button class="btn pri grow" onclick="copyCrashLogs()">复制全部</button>
      <button class="btn grow" onclick="clearCrashLogs()">清空</button>
    </div>
    <div class="sm muted" style="margin-top:8px">把复制出来的内容发出来，就能定位到底是哪一步出的问题。</div>`);
}
function copyCrashLogs() {
  let text = '';
  try { text = (AB && AB.getCrashLogs) ? (AB.getCrashLogs() || '') : ''; } catch (e) { }
  if (!text) { toast('暂无日志', 'err'); return; }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.top = '-1000px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast('已复制', 'ok');
  } catch (e) { toast('复制失败，请长按选择文本', 'err'); }
}
function clearCrashLogs() {
  try { if (AB && AB.clearCrashLogs) AB.clearCrashLogs(); } catch (e) { }
  toast('已清空', 'ok');
  closeSheet();
}

async function rescanLibrary() {
  try {
    if (AB && AB.rescanLibrary) AB.rescanLibrary();
    else await apiPost('/api/library/rescan', {});
    toast('已开始重新扫描', 'ok');
    closeSheet();
    setTimeout(function () { loadLib(); tick(true); }, 2000);
  } catch (e) { toast('失败：' + e.message, 'err'); }
}
function renderSourcesSheet(r) {
  const list = r.sources || [];
  const rows = list.map(s => {
    const badge = s.type === 'smb' ? 'SMB' : '本地';
    const st = s.readable
      ? `<span style="color:var(--acc)">${s.writable ? '可读可写' : '只读'} · ${s.audio_files} 首</span>`
      : `<span style="color:var(--warn)">不可读${s.type === 'smb' && !s.mounted ? '（未挂载）' : ''}</span>`;
    const addr = s.type === 'smb'
      ? `${esc(s.host || '')}/${esc(s.share || '')}${s.subpath ? '/' + esc(s.subpath) : ''}${s.guest ? ' · 匿名' : ''}`
      : esc(s.container_path || '');
    return `<div class="item">
      <div class="ico vi">${s.type === 'smb' ? I.net : I.folder}</div>
      <div class="txt">
        <div class="t1">${esc(s.name)}${s.active ? ' <span class="sm" style="color:var(--acc)">· 当前</span>' : ''} <span class="sm muted">[${badge}]</span></div>
        <div class="t2">${addr}<br>${st}</div>
      </div>
      <div class="act">
        ${s.active ? '' : `<button class="iconbtn sm2 vi" title="设为当前" onclick="setActiveSource('${s.id}')">${I.check}</button>`}
        ${s.type === 'smb' ? (s.mounted
        ? `<button class="iconbtn sm2 vi" title="卸载" onclick="srcCmd('unmount','${s.id}')">${I.unplug}</button>`
        : `<button class="iconbtn sm2 vi" title="挂载" onclick="srcCmd('mount','${s.id}')">${I.plug}</button>`) : ''}
        <button class="iconbtn sm2 vi" title="删除" onclick="srcDel('${s.id}')">${I.x}</button>
      </div>
    </div>`;
  }).join('');

  $('sheetBody').innerHTML = `
    <div class="sm muted">当前目录：<b style="color:var(--tx)">${esc(r.active_dir || '未配置')}</b></div>
    <div class="chips" style="margin-top:10px">
      <div class="chip vi" onclick="srcAdd('path')">${I.folderAdd} 加本地文件夹</div>
      <div class="chip vi" onclick="srcAdd('smb')">${I.net} 加 SMB 共享</div>
      <div class="chip vi" onclick="rescanLib()">${I.refresh} 重扫</div>
    </div>
    <div class="sec-title">已添加的目录</div>
    ${rows || '<div class="empty">还没有目录</div>'}
    <div class="sm muted" style="margin-top:14px">
      「本地文件夹」指服务所在的设备（iStoreOS）磁盘上的目录；「SMB 共享」是网络共享（NAS、电脑共享目录等）。
    </div>
  `;
}
async function setActiveSource(id) {
  try { await apiPost('/api/music/sources/active', { id: id }); toast('已切换', 'ok'); musicSourcesSheet(); loadLib(); }
  catch (e) { toast('失败：' + e.message, 'err'); }
}
async function srcCmd(cmd, id) {
  toast(cmd === 'mount' ? '正在挂载…' : '正在卸载…');
  try {
    const r = await apiPost('/api/music/sources/' + cmd, { id: id }, 90000);
    toast(r.msg || '完成', r.ok ? 'ok' : 'err');
  } catch (e) { toast('失败：' + e.message, 'err'); }
  musicSourcesSheet();
}
async function srcDel(id) {
  try { await apiPost('/api/music/sources/remove', { id: id }); toast('已删除', 'ok'); }
  catch (e) { toast('失败：' + e.message, 'err'); }
  musicSourcesSheet();
}

function srcAdd(kind) {
  if (kind === 'path') {
    openSheet('添加本地文件夹', `
      <input id="srcName" type="text" placeholder="名称（可留空）">
      <div class="row gap8" style="margin-top:10px">
        <input id="srcPath" type="text" placeholder="点右侧浏览选择目录" readonly style="flex:1">
        <button class="btn sm" onclick="srcBrowse('')">浏览…</button>
      </div>
      <div id="srcBrowseBox" class="scanbox" style="display:none;max-height:300px"></div>
      <div class="row gap8" style="margin-top:12px">
        <button class="btn pri grow" onclick="srcAddPath()">添加</button>
      </div>
    `);
  } else {
    openSheet('添加 SMB 共享', `
      <div class="sm muted">不知道共享叫什么？先点「扫描局域网」把 NAS / 电脑找出来，
        再点「浏览共享」一层层点进去选目录，不用记名字。</div>
      <input id="srcName" type="text" placeholder="名称（如 NAS 音乐）" style="margin-top:12px">
      <div class="row gap8" style="margin-top:10px">
        <input id="smbHost" type="text" placeholder="主机 / IP，如 192.168.1.100" style="flex:2">
        <input id="smbShare" type="text" placeholder="共享名，如 music" style="flex:2">
      </div>
      <div class="chips" style="margin-top:10px">
        <div class="chip vi" onclick="smbScan()">${I.scan} 扫描局域网</div>
        <div class="chip vi" onclick="smbBrowse('')">${I.folder} 浏览共享</div>
      </div>
      <div class="scanbox" id="smbBox" style="display:none"></div>
      <input id="smbSub" type="text" placeholder="子目录（可选，点上面的「浏览共享」直接选）" style="margin-top:10px">
      <div class="row gap8" style="margin-top:10px">
        <input id="smbUser" type="text" placeholder="用户名（访问受限时填）" style="flex:1">
        <input id="smbPass" type="password" placeholder="密码" style="flex:1">
      </div>
      <div class="chips">
        <div class="chip" id="smbGuestChip" onclick="toggleGuest()">匿名免密：关</div>
      </div>
      <div class="row gap8" style="margin-top:12px">
        <button class="btn grow" onclick="srcTestSmb()">测试连接</button>
        <button class="btn pri grow" onclick="srcAddSmb()">添加</button>
      </div>
      <div class="msg" id="smbMsg"></div>
      <div class="sm muted" style="margin-top:10px">共享需要允许写入，否则下载的歌存不进去。</div>
    `);
  }
}
/* ---------------- SMB：扫描局域网 / 浏览共享 ---------------- */

/** 扫描局域网里开着 445 的机器，并列出它们上面的共享 */
async function smbScan() {
  const box = $('smbBox');
  box.style.display = '';
  box.innerHTML = '<div class="empty" style="padding:14px"><span class="spin"></span> 正在扫描局域网，约 5～15 秒…</div>';
  const pl = smbPayload();
  try {
    const r = await apiPost('/api/smb/scan',
      { user: pl.user, password: pl.password, guest: pl.guest }, 90000);
    const hosts = r.hosts || [];
    if (!hosts.length) {
      box.innerHTML = '<div class="empty" style="padding:14px">没有发现共享服务器<br>'
        + '<span class="sm">确认 NAS / 电脑和手机连在同一个 WiFi，且已开启文件共享</span></div>';
      return;
    }
    box.innerHTML = '<div class="sm muted" style="padding:8px 12px">发现 ' + hosts.length
      + ' 台设备（点一下填入主机）：</div>' + hosts.map(function (h) {
        const sh = h.shares || [];
        let html = '<div class="scanitem" onclick="smbPickHost(\'' + esc(h.host) + '\')">'
          + '<b>' + esc(h.host) + '</b>'
          + (h.name ? ' <span class="sm muted">' + esc(h.name) + '</span>' : '') + '</div>';
        if (sh.length) {
          html += '<div style="padding:0 12px 8px 22px">' + sh.map(function (s) {
            return '<div class="chip" style="display:inline-block;margin:2px 4px 0 0" '
              + 'onclick="event.stopPropagation();smbPickShare(\'' + esc(h.host) + '\',\'' + esc(s.name) + '\')">'
              + esc(s.name) + '</div>';
          }).join('') + '</div>';
        } else if (h.error) {
          html += '<div class="sm muted" style="padding:0 12px 8px 22px">' + esc(h.error) + '</div>';
        }
        return html;
      }).join('');
  } catch (e) {
    box.innerHTML = '<div class="empty" style="padding:14px">扫描失败：' + esc(e.message) + '</div>';
  }
}

function smbPickHost(host) {
  $('smbHost').value = host;
  smbBrowse('');
}

function smbPickShare(host, share) {
  $('smbHost').value = host;
  $('smbShare').value = share;
  if (!($('srcName').value || '').trim()) $('srcName').value = share;
  smbBrowse('');
}

/** 浏览：共享名为空 → 列共享；否则列该共享下的子目录 */
async function smbBrowse(rel) {
  const box = $('smbBox');
  const host = ($('smbHost').value || '').trim();
  const share = ($('smbShare').value || '').trim();
  const pl = smbPayload();
  box.style.display = '';
  if (!host) {
    box.innerHTML = '<div class="empty" style="padding:14px">先填「主机 / IP」，或点「扫描局域网」自动发现</div>';
    return;
  }
  box.innerHTML = '<div class="empty" style="padding:14px"><span class="spin"></span> 读取中…</div>';
  try {
    const r = await apiPost('/api/smb/browse', {
      host: host, share: share, subpath: share ? (rel || '') : '',
      user: pl.user, password: pl.password, guest: pl.guest,
    }, 60000);

    if (!r.ok) {
      box.innerHTML = '<div class="empty" style="padding:14px">' + esc(r.error || '读取失败') + '</div>';
      return;
    }
    if (!share) {
      const sh = r.shares || [];
      box.innerHTML = '<div class="sm muted" style="padding:8px 12px">' + esc(host)
        + ' 上的共享，点一个进去看目录：</div>'
        + (sh.length ? sh.map(function (s) {
            return '<div class="scanitem" onclick="smbPickShare(\'' + esc(host) + '\',\'' + esc(s.name) + '\')">'
              + I.folder + ' ' + esc(s.name) + '</div>';
          }).join('')
          : '<div class="empty" style="padding:10px">服务器没列出共享，请手动填共享名</div>');
      return;
    }
    const dirs = r.dirs || [];
    const here = esc(host) + '/' + esc(share) + (r.path ? '/' + esc(r.path) : '');
    let html = '<div class="sm muted" style="padding:8px 12px">' + here + ' · '
      + (r.audio_files || 0) + ' 首音乐 · ' + dirs.length + ' 个子目录</div>';
    html += '<div class="row gap8" style="padding:0 12px 8px">';
    if (r.path) {
      html += '<button class="btn sm" onclick="smbBrowse(\'' + esc(r.parent) + '\')">↑ 上一级</button>'
        + '<button class="btn sm pri" onclick="smbUseDir(\'' + esc(r.path) + '\')">用这个目录</button>';
    } else {
      html += '<button class="btn sm pri" onclick="smbUseDir(\'\')">就用共享根目录</button>';
    }
    html += '</div>';
    html += dirs.length
      ? dirs.map(function (d) {
          return '<div class="scanitem" onclick="smbBrowse(\'' + esc(d.rel) + '\')">' + I.folder + ' '
            + esc(d.name) + '</div>';
        }).join('')
      : '<div class="empty" style="padding:10px">这一层没有子目录</div>';
    box.innerHTML = html;
  } catch (e) {
    box.innerHTML = '<div class="empty" style="padding:14px">读取失败：' + esc(e.message) + '</div>';
  }
}

function smbUseDir(rel) {
  $('smbSub').value = rel || '';
  const nm = ($('srcName').value || '').trim();
  if (!nm) $('srcName').value = ($('smbShare').value || '').trim();
  toast(rel ? ('已选子目录：' + rel) : '已选共享根目录', 'ok');
}

let _guest = false;
function toggleGuest() {
  _guest = !_guest;
  $('smbGuestChip').textContent = '匿名免密：' + (_guest ? '开' : '关');
  $('smbGuestChip').className = 'chip' + (_guest ? ' on' : '');
}
function smbPayload() {
  return {
    name: ($('srcName').value || '').trim(), type: 'smb',
    host: ($('smbHost').value || '').trim(),
    share: ($('smbShare').value || '').trim(),
    subpath: ($('smbSub').value || '').trim(),
    user: ($('smbUser').value || '').trim(),
    password: $('smbPass').value || '',
    guest: _guest, auto_mount: true,
  };
}
async function srcTestSmb() {
  const m = $('smbMsg'); m.className = 'msg'; m.textContent = '测试中…';
  try {
    const r = await apiPost('/api/music/sources/test', smbPayload(), 90000);
    const p = r.probe || {};
    m.className = 'msg ok';
    m.textContent = '连接成功：' + (p.files || p.audio_files || 0) + ' 首音乐、' + (p.dirs || 0) + ' 个子目录';
  } catch (e) { m.className = 'msg err'; m.textContent = '失败：' + e.message; }
}
async function srcAddSmb() {
  const m = $('smbMsg');
  const pl = smbPayload();
  if (!pl.host || !pl.share) { m.className = 'msg err'; m.textContent = '请填主机和共享名'; return; }
  m.className = 'msg'; m.textContent = '添加中…';
  try {
    await apiPost('/api/music/sources/add', pl, 60000);
    toast('已添加，正在挂载…', 'ok');
    setTimeout(musicSourcesSheet, 2500);
  } catch (e) { m.className = 'msg err'; m.textContent = '失败：' + e.message; }
}

async function srcBrowse(path) {
  const box = $('srcBrowseBox');
  box.style.display = '';
  box.innerHTML = '<div class="empty" style="padding:14px"><span class="spin"></span> 读取…</div>';
  try {
    const r = await api('/api/music/browse' + (path ? '?path=' + q(path) : ''));
    const roots = r.roots || [];
    const chips = roots.map(rt =>
      `<div class="crumb${rt.path === r.root ? ' on' : ''}" onclick="srcBrowse('${esc(rt.path)}')">${esc(rt.name)}</div>`).join('');
    box.innerHTML = `<div class="crumbs" style="padding:8px 10px 4px">${chips}</div>
      <div class="sm muted" style="padding:0 12px 8px">${esc(r.path)} · ${r.audio_files || 0} 首音乐 · ${r.writable ? '可写' : '只读'}</div>
      <div style="padding:0 12px 10px">
        <button class="btn sm" onclick="srcBrowse('${esc(r.parent)}')">↑ 上一级</button>
        <button class="btn sm pri" onclick="srcPick('${esc(r.path)}')">选这个目录</button>
      </div>
      ${(r.dirs || []).map(d =>
      `<div class="scanitem" onclick="srcBrowse('${esc(d.path)}')">📁 ${esc(d.name)}</div>`).join('')
      || '<div class="empty" style="padding:10px">（没有子目录，可直接选当前目录）</div>'}`;
  } catch (e) { box.innerHTML = '<div class="empty">读取失败：' + esc(e.message) + '</div>'; }
}
function srcPick(path) {
  $('srcPath').value = path;
  $('srcBrowseBox').style.display = 'none';
}
async function srcAddPath() {
  const p = ($('srcPath').value || '').trim();
  if (!p) { toast('请先浏览选择一个目录', 'err'); return; }
  try {
    await apiPost('/api/music/sources/add', {
      name: ($('srcName').value || '').trim(), type: 'path', path: p, auto_mount: false
    });
    toast('已添加', 'ok');
    musicSourcesSheet();
  } catch (e) { toast('失败：' + e.message, 'err'); }
}

/* =========================================================================
   七、在线音乐
   ========================================================================= */

/* ---------------- 音源管理（用户可自行添加 MusicFree 插件） ---------------- */

function readTextFile(file) {
  return new Promise(function (resolve, reject) {
    const fr = new FileReader();
    fr.onload = function () { resolve(String(fr.result || '')); };
    fr.onerror = function () { reject(new Error('读取文件失败')); };
    fr.readAsText(file);
  });
}

async function srcMgrSheet() {
  openSheet('音源管理', '<div class="empty" style="padding:20px"><span class="spin"></span> 读取…</div>');
  let r;
  try { r = await api('/api/plugins'); }
  catch (e) {
    $('sheetBody').innerHTML = '<div class="empty">读取失败：' + esc(e.message) + '</div>';
    return;
  }
  const list = r.list || [];
  const defSrc = (function () { try { return localStorage.getItem('dlna_defaultprov') || ''; } catch (e) { return ''; } })();
  const rows = list.map(function (s) {
    const nm = String(s.name || '').replace(/\.js$/i, '');
    const pf = s.platform || nm;   // 下拉里用的是 platform，默认音源必须按 platform 存
    return '<div class="item">'
      + '<div class="ico vi">' + I.wave + '</div>'
      + '<div class="txt">'
      + '<div class="t1">' + esc(nm) + ' <span class="sm muted">[' + (s.builtin ? '内置' : '自建') + ']</span>'
      + ((s.platform || nm) === defSrc && s.enabled ? ' <span class="sm" style="color:#22e6ff">★默认</span>' : '')
      + (s.enabled ? '' : ' <span class="sm" style="color:#ff2d92">已停用</span>') + '</div>'
      + '<div class="t2">' + (s.builtin ? '随 App 内置' : '你添加的')
      + (s.size ? ' · ' + Math.max(1, Math.round(s.size / 1024)) + ' KB' : '') + '</div>'
      + '</div>'
      + '<div class="act">'
      + (s.enabled ? '<button class="iconbtn sm2 vi" title="设为默认" onclick="srcSetDefault(\'' + esc(pf) + '\')">' + I.star + '</button>' : '')
      + '<button class="iconbtn sm2 vi" title="' + (s.enabled ? '停用' : '启用')
      + '" onclick="srcToggle(\'' + esc(s.name) + '\',' + (s.enabled ? 'false' : 'true') + ')">'
      + (s.enabled ? I.eye : I.eyeOff) + '</button>'
      + (s.builtin ? '' : '<button class="iconbtn sm2 vi" title="删除" onclick="srcRemove(\'' + esc(s.name) + '\')">' + I.x + '</button>')
      + '</div></div>';
  }).join('');

  $('sheetBody').innerHTML =
    '<div class="sm muted">音源就是 MusicFree 的插件。本机自带的几个只是默认值，'
    + '你可以停用不想要的，也可以自己添加 —— 插件网址、分享码、订阅文件都行。</div>'
    + '<div class="chips" style="margin-top:12px">'
    + '<div class="chip vi" onclick="srcInstallSheet()">' + I.plus + ' 添加音源</div>'
    + '<div class="chip vi" onclick="closeSheet();loadProviders()">' + I.refresh + ' 重新加载</div>'
    + '</div>'
    + '<div class="sec-title">已安装的音源（' + list.length + '）</div>'
    + (rows || '<div class="empty">还没有音源</div>');
}

function srcSetDefault(nm) {
  try {
    localStorage.setItem('dlna_defaultprov', nm);
    localStorage.setItem('dlna_lastprov', nm);
  } catch (e) { }
  S.online.provider = nm;
  toast('默认音源：' + nm, 'ok');
  srcMgrSheet();
}

function srcInstallSheet() {
  openSheet('添加音源', `
    <div class="sm muted">支持 MusicFree 插件的各种分发形式：插件源码网址、订阅链接、
      分享码（一大串字符）、手机里的 .js / .json 文件。</div>
    <input id="pUrl" type="text" placeholder="插件 / 订阅网址，http 开头" style="margin-top:12px">
    <div class="row gap8" style="margin-top:10px">
      <button class="btn pri grow" onclick="srcInstallUrl()">从网址安装</button>
      <button class="btn grow" onclick="var f=$('pFile'); f.click()">选择本机文件</button>
    </div>
    <input id="pFile" type="file" accept=".js,.json,text/javascript,application/json" style="display:none">
    <div class="sec-title">或直接粘贴</div>
    <textarea id="pCode" class="ta" rows="6" placeholder="插件源码 / 分享码 / 订阅 JSON，直接粘进来"></textarea>
    <div class="row gap8" style="margin-top:10px">
      <button class="btn pri grow" onclick="srcInstallCode()">安装粘贴的内容</button>
    </div>
    <div class="msg" id="pMsg"></div>
    <div class="sm muted" style="margin-top:12px">
      MusicFree 插件是社区维护的 .js 文件，常见于插件订阅链接或别人分享的分享码。
      安装后会立刻出现在在线音乐的「音源」下拉里。
    </div>
  `);
  const f = $('pFile');
  if (f) f.addEventListener('change', srcInstallFile);
}

function srcInstallMsg(text, kind) {
  const m = $('pMsg');
  if (!m) { toast(text, kind); return; }
  m.className = 'msg' + (kind === 'ok' ? ' ok' : kind === 'err' ? ' err' : '');
  m.textContent = text;
}

async function srcInstallUrl() {
  const u = ($('pUrl').value || '').trim();
  if (!u) { srcInstallMsg('请先填插件或订阅的网址', 'err'); return; }
  srcInstallMsg('下载并解析中…');
  try {
    const r = await apiPost('/api/plugins/install', { url: u }, 120000);
    afterInstall(r);
  } catch (e) { srcInstallMsg('安装失败：' + e.message, 'err'); }
}

async function srcInstallCode() {
  const c = ($('pCode').value || '').trim();
  if (!c) { srcInstallMsg('先把内容粘到上面的框里', 'err'); return; }
  srcInstallMsg('解析中…');
  try {
    const r = await apiPost('/api/plugins/install', { code: c }, 120000);
    afterInstall(r);
  } catch (e) { srcInstallMsg('安装失败：' + e.message, 'err'); }
}

async function srcInstallFile(ev) {
  const f = ev.target.files && ev.target.files[0];
  if (!f) return;
  srcInstallMsg('读取文件…');
  try {
    const txt = await readTextFile(f);
    srcInstallMsg('解析中…');
    const name = String(f.name || '').replace(/\.(js|json)$/i, '');
    const r = await apiPost('/api/plugins/install', { code: txt, name: name }, 120000);
    afterInstall(r);
  } catch (e) { srcInstallMsg('安装失败：' + e.message, 'err'); }
}

function afterInstall(r) {
  const errs = r.errors || [];
  if (r.ok) {
    toast(r.msg || '已添加', 'ok');
    loadProviders();
    setTimeout(srcMgrSheet, 400);
  } else {
    srcInstallMsg('没能装上：' + (errs.length ? errs.join('；') : (r.msg || '未知原因')), 'err');
  }
}

async function srcToggle(name, enabled) {
  try {
    const r = await apiPost('/api/plugins/toggle', { name: name, enabled: enabled });
    toast(r.msg || '已更新', r.ok ? 'ok' : 'err');
    loadProviders();
  } catch (e) { toast('失败：' + e.message, 'err'); }
  srcMgrSheet();
}

async function srcRemove(name) {
  try {
    const r = await apiPost('/api/plugins/remove', { name: name });
    toast(r.msg || '已删除', r.ok ? 'ok' : 'err');
    loadProviders();
  } catch (e) { toast('失败：' + e.message, 'err'); }
  srcMgrSheet();
}

async function loadProviders() {
  const sel = $('onlineProvider');
  const PH = window.PluginHost;
  if (!PH) { sel.innerHTML = '<option value="">（插件运行时未加载）</option>'; return; }
  try {
    PH.configure({ proxyBase: BASE });
    // 音源清单由本机服务给出（内置 + 用户自己添加的，已过滤掉停用项），
    // 不再写死在前端 —— 用户加完立刻生效。
    let srcs = [];
    try {
      const rr = await api('/api/plugins/code');
      srcs = rr.list || [];
    } catch (e) { srcs = []; }
    if (!srcs.length) {
      // 退回老路径：万一本机服务还没起来，直接用原生桥拿内置源码
      try { srcs = JSON.parse((AB && AB.getPlugins) ? (AB.getPlugins() || '[]') : '[]'); } catch (e) { srcs = []; }
      try {
        const mine = JSON.parse((AB && AB.getUserPlugins) ? (AB.getUserPlugins() || '[]') : '[]');
        if (mine.length) srcs = srcs.concat(mine);
      } catch (e) { }
    }
    const r = PH.loadAll(srcs);
    if (r.failed && r.failed.length) console.warn('插件加载失败:', r.failed);
    const list = PH.list();
    const keep = sel.value;
    if (!list.length) {
      sel.innerHTML = '<option value="">（没有启用的音源，去「音源」里加一个）</option>';
      S.online.provider = '';
      return;
    }
    sel.innerHTML = list.map(p => `<option value="${esc(p.platform)}">${esc(p.platform)}</option>`).join('');
    let defP = '', lastP = '';
    try { defP = localStorage.getItem('dlna_defaultprov') || ''; lastP = localStorage.getItem('dlna_lastprov') || ''; } catch (e) { }
    // 上次用的音源优先（换下拉/搜索时都会写入 lastP），其次当前值，再次默认音源
    const pick = (lastP && list.some(p => p.platform === lastP)) ? lastP
      : (keep && list.some(p => p.platform === keep)) ? keep
      : (defP && list.some(p => p.platform === defP)) ? defP
      : list[0].platform;
    sel.value = pick;
    S.online.provider = pick;
    S.online.plugins = list;
  } catch (e) {
    sel.innerHTML = '<option value="">（音源不可用）</option>';
    console.warn('载入插件失败', e);
  }
}

/** 在线曲目：就地在页面内解析直链，并注册到本机服务换取可播放地址 */
async function resolveOnline(items) {
  const PH = window.PluginHost;
  if (!PH) throw new Error('插件运行时未加载');
  const out = [];
  for (let i = 0; i < items.length; i++) {
    const t = items[i];
    if (t.sid) { out.push(t); continue; }
    const provider = t.provider || S.online.provider;
    const id = t.id || t.oid;
    if (!provider || !id) { out.push(t); continue; }
    const r = await PH.resolve({ provider: provider, id: id });
    const reg = await apiPost('/api/online/register', { url: r.url, headers: r.headers });
    out.push(Object.assign({}, t, {
      source: 'online', provider: provider, id: id,
      sid: reg.sid, url: reg.url, _directUrl: r.url, _headers: r.headers
    }));
  }
  return out;
}

async function doOnlineSearch(page) {
  const kw = ($('onlineQ').value || '').trim();
  if (!kw) { toast('请输入歌名或歌手', 'err'); return; }
  S.online.q = kw;
  S.online.provider = $('onlineProvider').value;
  try { localStorage.setItem('dlna_lastprov', S.online.provider); } catch (e) { }
  S.online.page = page || 1;
  const limit = parseInt($('onlineLimit').value, 10) || 30;
  const box = $('onlineList');
  box.innerHTML = '<div class="empty"><span class="spin"></span> 搜索中…</div>';
  $('onlineActions').style.display = 'none';
  $('onlinePager').style.display = 'none';
  const PH = window.PluginHost;
  if (!PH) { box.innerHTML = '<div class="empty">插件运行时未加载，无法搜索</div>'; return; }
  try {
    const r = await PH.search({ q: kw, provider: S.online.provider, page: S.online.page, limit: limit });
    S.online.items = r.items || [];
    S.online.isEnd = !!r.isEnd;
    if (r.errors && r.errors.length) console.warn('部分音源出错:', r.errors);
    renderOnline();
  } catch (e) {
    box.innerHTML = '<div class="empty">搜索失败：' + esc(e.message) + '</div>';
  }
}

function renderOnline() {
  const box = $('onlineList');
  const its = S.online.items || [];
  if (!its.length) {
    box.innerHTML = '<div class="empty">第 ' + S.online.page + ' 页没有结果<br><span class="sm">可以回上一页，或换个音源试试</span></div>';
  } else {
    const base = (S.online.page - 1) * (parseInt($('onlineLimit').value, 10) || 30);
    box.innerHTML = its.map((t, i) => {
      const sub = [t.artist, t.album, t.duration_sec ? fmt(t.duration_sec) : ''].filter(Boolean).join(' · ');
      return `<div class="item">
        <div class="no">${base + i + 1}</div>
        <div class="txt" onclick="playOne('online',${i})">
          <div class="t1">${esc(t.title || '未知')}</div>
          <div class="t2">${esc(sub)}</div>
        </div>
        <div class="act">
          <button class="iconbtn sm2" title="加入列表" onclick="addOne('online',${i})">＋</button>
          <button class="iconbtn sm2" title="下载" onclick="dlOne(${i})">⤓</button>
        </div>
      </div>`;
    }).join('');
    $('onlineActions').style.display = '';
  }
  $('onlinePager').style.display = (its.length || S.online.page > 1) ? '' : 'none';
  $('pageInfo').textContent = '第 ' + S.online.page + ' 页 · ' + its.length + ' 首';
  $('btnPagePrev').disabled = S.online.page <= 1;
  $('btnPageNext').disabled = S.online.isEnd && !its.length;
}

async function addOnlineAll() {
  const its = S.online.items || [];
  if (!its.length) { toast('没有可加入的曲目', 'err'); return; }
  await addToQueue(its.map(t => ({
    source: 'online', provider: t.provider || S.online.provider, oid: t.id,
    title: t.title, artist: t.artist, album: t.album, duration_sec: t.duration_sec || 0
  })));
}
async function downloadOnlineAll() {
  const its = S.online.items || [];
  if (!its.length) { toast('没有可下载的曲目', 'err'); return; }
  await doDownload(its.map(t => ({
    provider: t.provider || S.online.provider, id: t.id,
    title: t.title, artist: t.artist, duration_sec: t.duration_sec || 0
  })));
}
async function dlOne(i) {
  const t = S.online.items[i]; if (!t) return;
  await doDownload([{
    provider: t.provider || S.online.provider, id: t.id,
    title: t.title, artist: t.artist, duration_sec: t.duration_sec || 0
  }]);
}
async function doDownload(items) {
  // 解析音源动辄要等十几秒，用户很容易连点；不挡住会叠出一堆并发解析
  if (S.dlBusy) { toast('上一个下载请求还在处理中…', 'err'); return; }
  S.dlBusy = true;
  try {
    await doDownloadInner(items);
  } finally { S.dlBusy = false; }
}
async function doDownloadInner(items) {
  toast('正在解析下载地址…');
  let resolved;
  try {
    resolved = await resolveOnline(items);
  } catch (e) { toast('解析失败：' + e.message, 'err'); return; }
    (resolved || []).forEach(function (it) { saveDownloadedLyric(it); });  // 歌词随歌一起下
  const payload = resolved.map(t => ({
    provider: t.provider || S.online.provider, id: t.id, title: t.title, artist: t.artist,
    duration_sec: t.duration_sec || 0,
    url: t._directUrl || t.url || '', headers: t._headers || {}
  })).filter(x => x.url);
  if (!payload.length) { toast('没有可下载的曲目', 'err'); return; }
  try {
    const r = await apiPost('/api/online/download', { items: payload }, 60000);
    if (r.ok === false) throw new Error(r.msg || '失败');
    toast('开始下载 ' + (r.queued != null ? r.queued : payload.length) + ' 首', 'ok');
  } catch (e) { toast('下载失败：' + e.message, 'err'); }
}
async function saveDownloadedLyric(it) {
  try {
    const PH = window.PluginHost;
    if (!PH || !it.provider || !(it.id || it.oid)) return;
    const r = await PH.lyric({ provider: it.provider, id: it.id || it.oid });
    const lrc = (r && (r.lrc || r.rawLrc || r.lyric)) || '';
    if (!lrc.trim()) return;
    await apiPost('/api/lyric/save', { artist: it.artist || '未知歌手', title: it.title || '未知', lrc: lrc });
  } catch (e) { }
}

async function dlStatus() {
  openSheet('下载状态', '<div class="empty"><span class="spin"></span> 读取中…</div>');
  try {
    const r = await api('/api/online/downloads');
    const jobs = r.jobs || [];
    const MAP = { done: '已完成', pending: '排队中', downloading: '下载中', error: '失败', skipped: '已跳过' };
    $('sheetBody').innerHTML = (jobs.length ? jobs.map(j => {
      const st = MAP[j.status] || j.status;
      const color = j.status === 'done' ? 'var(--acc)' : (j.status === 'error' ? 'var(--warn)' : 'var(--tx3)');
      const size = j.size ? (' · ' + (j.size / 1048576).toFixed(1) + 'MB') : '';
      return `<div class="item"><div class="ico">⤓</div>
        <div class="txt"><div class="t1">${esc(j.title || '')}</div>
        <div class="t2">${esc(j.artist || '')} · <span style="color:${color}">${esc(st)}</span>${size}${j.error ? ' · ' + esc(j.error) : ''}</div></div></div>`;
    }).join('') : '<div class="empty">没有下载任务</div>')
      + `<div class="row gap8" style="margin-top:12px">
           <button class="btn grow" onclick="dlStatus()">刷新</button>
           <button class="btn grow" onclick="dlClear()">清空记录</button>
         </div>
         <div class="sm muted" style="margin-top:10px">下载会按歌手存到当前音乐目录里；时长不足 1 分钟的试听片段会被自动跳过/删除。</div>`;
  } catch (e) { $('sheetBody').innerHTML = '<div class="empty">读取失败：' + esc(e.message) + '</div>'; }
}
async function dlClear() {
  try { await apiPost('/api/online/downloads/clear'); toast('已清空', 'ok'); dlStatus(); }
  catch (e) { toast('失败：' + e.message, 'err'); }
}

/* =========================================================================
   八、播放列表
   ========================================================================= */
/* 播放模式 chips（v2.8 从正在播放移到播放列表） */
function modeChipsHTML(pl) {
  return `
    <div class="chip ${pl.shuffle ? 'on' : ''}" onclick="queueShuffle()">🔀 随机</div>
    <div class="chip ${pl.repeat === 'all' ? 'on' : ''}" onclick="toggleRepeat('all')">🔁 列表循环</div>
    <div class="chip ${pl.repeat === 'one' ? 'on' : ''}" onclick="toggleRepeat('one')">🔂 单曲循环</div>`;
}

/* ---- 边听边下载（v2.8） ---- */
function autoDlOn() {
  try { return localStorage.getItem('dlna_audiodl') === '1'; } catch (e) { return false; }
}
function setAutoDl(on) {
  try { localStorage.setItem('dlna_audiodl', on ? '1' : '0'); } catch (e) { }
  toast(on ? '边听边下载：开' : '边听边下载：关', 'ok');
  if (on) autoDlMaybe(nowPlaying().t);
  if (S.tab === 'now') renderNowTab();
}
function autoDlMaybe(t) {
  if (!autoDlOn() || !t) return;
  if (t.source !== 'online') return;              // 本地歌曲已在手机里
  if (!t.provider || !(t.id || t.oid)) return;    // 缺元数据，静默跳过
  const key = trackKeyOf(t);
  S._dlKeys = S._dlKeys || {};
  if (!key || S._dlKeys[key]) return;             // 本次会话已下过
  if (S.dlBusy) {                                 // 解析中 → 稍后重试一次
    if (!t.__adlRetry) { t.__adlRetry = 1; setTimeout(function () { autoDlMaybe(t); }, 20000); }
    return;
  }
  S._dlKeys[key] = 1;
  doDownload([{ provider: t.provider, id: t.oid || t.id, title: t.title, artist: t.artist, duration_sec: t.duration_sec || 0 }]);
}

function renderQueue() {
  if (S.tab !== 'queue') return;
  const box = $('queueList');
  const pl = (S.state && S.state.player) || {};
  const qm = $('queueModes');
  if (qm) qm.innerHTML = modeChipsHTML(pl);
  let list = pl.queue || [], cur = pl.index;
  if (S.out === 'phone' && S.phone.queue.length) { list = S.phone.queue; cur = S.phone.idx; }
  $('queueInfo').textContent = list.length ? (list.length + ' 首' + (cur >= 0 ? ' · 第 ' + (cur + 1) + ' 首' : '')) : '';
  if (!list.length) {
    box.innerHTML = '<div class="empty">播放列表是空的<br><span class="sm">在「曲库」或「在线」里点 ＋ 加歌</span></div>';
    return;
  }
  box.innerHTML = list.map((t, i) => {
    const sub = [t.artist, t.album].filter(Boolean).join(' · ');
    return `<div class="item${i === cur ? ' on' : ''}">
      <div class="no" onclick="jumpTo(${i})">${i === cur ? '▶' : (i + 1)}</div>
      <div class="txt" onclick="jumpTo(${i})">
        <div class="t1">${esc(t.title || '未知')}</div>
        <div class="t2">${esc(sub)}</div>
      </div>
      <div class="act"><button class="iconbtn sm2 vi" title="移除" onclick="queueRemove(${i})">${I.x}</button></div>
    </div>`;
  }).join('');
  renderQueueSaved();
  return box;
}

async function addToQueue(tracks) {
  if (!tracks || !tracks.length) return;
  try {
    const on = tracks.filter(t => t.source === 'online');
    const other = tracks.filter(t => t.source !== 'online');
    if (on.length) {
      const resolved = await resolveOnline(on.map(t => ({
        id: t.oid || t.id, provider: t.provider, title: t.title, artist: t.artist,
        album: t.album, duration_sec: t.duration_sec || 0, source: 'online'
      })));
      await apiPost('/api/queue', { action: 'add', tracks: resolved }, 40000);
    }
    if (other.length) await apiPost('/api/queue', { action: 'add', tracks: other });
    toast('已加入播放列表（' + tracks.length + ' 首）', 'ok');
    buzz();
    await tick(true);
    saveCurQueueDebounced();
  } catch (e) { toast('加入失败：' + e.message, 'err'); }
}
async function jumpTo(i) {
  if (S.out === 'phone') {
    // 本机播放：从播放列表（后端队列）取这一首本地播放；本机队列空时先镜像过去，保证顺序播放一致
    if (!S.phone.queue.length) {
      const q = (S.state && S.state.player && S.state.player.queue) || [];
      S.phone.queue = q.slice();
      S.phone.idx = -1;
    }
    phonePlayAt(i);
    return;
  }
  try {
    const r = await apiPost('/api/jump', { index: i });
    if (r.ok === false) throw new Error(r.result || '失败');
    await tick(true);
  } catch (e) { toast('切换失败：' + e.message, 'err'); }
}
async function queueRemove(i) {
  if (S.out === 'phone' && S.phone.queue.length) {
    S.phone.queue.splice(i, 1);
    if (S.phone.idx >= S.phone.queue.length) S.phone.idx = S.phone.queue.length - 1;
    renderQueue(); saveCurQueueDebounced(); return;
  }
  try { await apiPost('/api/queue', { action: 'remove', index: i }); await tick(true); }
  catch (e) { toast('移除失败：' + e.message, 'err'); }
}
async function queueClear() {
  try {
    await apiPost('/api/queue', { action: 'clear' });
    S.phone.queue = []; S.phone.idx = -1; stopPhone();
    toast('已清空', 'ok'); await tick(true); renderQueue(); saveCurQueue();
  } catch (e) { toast('失败：' + e.message, 'err'); }
}
async function queueShuffle() {
  try {
    const pl = (S.state && S.state.player) || {};
    const r = await apiPost('/api/mode', { shuffle: !pl.shuffle });
    toast(r.shuffle ? '随机播放：开' : '随机播放：关', 'ok');
    await tick(true);
    saveCurQueueDebounced();
  } catch (e) { toast('失败：' + e.message, 'err'); }
}

/* =========================================================================
   八-b、播放列表持久化 + 另存为 + 我的播放列表
   ========================================================================= */
const QKEY = 'dlna_queue_v1';
const PKEY = 'dlna_playlists_v1';

/* 取"当前正在显示的播放列表"（手机模式取 S.phone.queue，音响模式取后端队列） */
function curQueueList() {
  if (S.out === 'phone') return { list: S.phone.queue, idx: S.phone.idx, out: 'phone' };
  const pl = (S.state && S.state.player) || {};
  return { list: pl.queue || [], idx: (typeof pl.index === 'number' ? pl.index : -1), out: 'dlna' };
}
/* 把当前列表写进 localStorage，App 关掉再开就能恢复 */
function saveCurQueue() {
  try {
    const c = curQueueList();
    localStorage.setItem(QKEY, JSON.stringify({ out: c.out, idx: c.idx, items: c.list || [] }));
  } catch (e) { }
}
let _saveQTimer = null;
function saveCurQueueDebounced() {
  if (_saveQTimer) clearTimeout(_saveQTimer);
  _saveQTimer = setTimeout(saveCurQueue, 400);
}
/* 在线曲目地址会过期，恢复时尽量重新解析，避免"有列表播不了" */
async function refreshQueueTracks(items) {
  const on = (items || []).filter(t => t && t.source === 'online' && t.provider && (t.id || t.oid));
  if (!on.length) return items;
  try {
    const resolved = await resolveOnline(on.map(t => ({
      id: t.oid || t.id, provider: t.provider, title: t.title, artist: t.artist,
      album: t.album, duration_sec: t.duration_sec || 0, source: 'online'
    })));
    const map = {};
    (resolved || []).forEach(r => { map[trackKeyOf(r)] = r; });
    return items.map(t => { const r = map[trackKeyOf(t)]; return r || t; });
  } catch (e) { return items; }
}
/* 启动时从 localStorage 恢复上次的列表（含输出方式） */
async function loadCurQueue() {
  let raw;
  try { raw = localStorage.getItem(QKEY); } catch (e) { return; }
  if (!raw) return;
  let data;
  try { data = JSON.parse(raw); } catch (e) { return; }
  const items = data.items || [];
  if (!items.length) return;
  S.out = data.out || S.out;
  if (data.out === 'phone') {
    S.phone.queue = items.slice();
    S.phone.idx = (typeof data.idx === 'number') ? data.idx : -1;
    if (S.phone.idx >= S.phone.queue.length) S.phone.idx = S.phone.queue.length - 1;
    refreshQueueTracks(S.phone.queue).then(refreshed => {
      if (refreshed && refreshed.length) { S.phone.queue = refreshed; renderQueue(); }
    }).catch(() => { });
  } else {
    try {
      const refreshed = await refreshQueueTracks(items.slice());
      await apiPost('/api/queue', { action: 'clear' });
      await apiPost('/api/queue', { action: 'add', tracks: refreshed }, 60000);
      if (typeof data.idx === 'number' && data.idx >= 0) {
        await apiPost('/api/jump', { index: data.idx }, 9000).catch(() => { });
      }
      S.phone.queue = refreshed.slice(); S.phone.idx = -1;
    } catch (e) {
      S.phone.queue = items.slice(); S.phone.idx = -1;
    }
  }
}
function stripTrack(t) {
  if (!t) return null;
  return {
    title: t.title || '', artist: t.artist || '', album: t.album || '',
    source: t.source || '', provider: t.provider || '', id: t.id || '', oid: t.oid || '',
    url: t.url || t.stream_url || '', duration_sec: t.duration_sec || 0
  };
}
function getPlaylists() {
  try { return JSON.parse(localStorage.getItem(PKEY) || '[]') || []; } catch (e) { return []; }
}
function setPlaylists(arr) {
  try { localStorage.setItem(PKEY, JSON.stringify((arr || []).slice(0, 50))); } catch (e) { }
}
function savePlaylistAs(name) {
  name = (name || '').trim();
  if (!name) { toast('名字不能为空', 'err'); return false; }
  const c = curQueueList();
  const items = (c.list || []).map(stripTrack).filter(Boolean);
  if (!items.length) { toast('当前播放列表是空的，没法保存', 'err'); return false; }
  const arr = getPlaylists();
  const ex = arr.find(p => p.name === name);
  const entry = { name: name, items: items, ts: Date.now() };
  if (ex) Object.assign(ex, entry); else arr.unshift(entry);
  setPlaylists(arr);
  toast('已保存「' + name + '」(' + items.length + ' 首)', 'ok');
  renderQueueSaved();
  return true;
}
async function loadNamedPlaylist(i) {
  const arr = getPlaylists();
  const p = arr[i];
  if (!p) return;
  const items = (p.items || []).slice();
  if (!items.length) { toast('该列表是空的', 'err'); return; }
  const refreshed = await refreshQueueTracks(items);
  if (S.out === 'phone') {
    S.phone.queue = refreshed; S.phone.idx = -1;
  } else {
    try {
      await apiPost('/api/queue', { action: 'clear' });
      await apiPost('/api/queue', { action: 'add', tracks: refreshed }, 60000);
    } catch (e) { }
    S.phone.queue = refreshed; S.phone.idx = -1;
  }
  saveCurQueue();
  switchTab('queue'); renderQueue();
  if (S.out === 'phone') phonePlayAt(0);
  else apiPost('/api/jump', { index: 0 }, 9000).catch(() => { });
  toast('已载入「' + p.name + '」(' + refreshed.length + ' 首)', 'ok');
}
function deletePlaylist(i) {
  const arr = getPlaylists();
  if (i < 0 || i >= arr.length) return;
  arr.splice(i, 1); setPlaylists(arr); renderQueueSaved();
  toast('已删除', 'ok');
}
function renamePlaylistPrompt(i) {
  const arr = getPlaylists(); const p = arr[i]; if (!p) return;
  const html = '<div class="sec-title">重命名播放列表</div>'
    + '<input class="inp" id="plRenameInput" value="' + esc(p.name) + '" style="width:100%;margin:8px 0;box-sizing:border-box"/>'
    + '<div class="chips"><div class="chip on" onclick="doRenamePlaylist(' + i + ')">保存</div>'
    + '<div class="chip" onclick="playlistsSheet()">取消</div></div>';
  openSheet('重命名', html);
}
function doRenamePlaylist(i) {
  const inp = $('plRenameInput'); const name = (inp ? inp.value : '').trim();
  if (!name) { toast('名字不能为空', 'err'); return; }
  const arr = getPlaylists(); if (arr[i]) { arr[i].name = name; setPlaylists(arr); }
  playlistsSheet();
}
function playlistsSheet() {
  const arr = getPlaylists();
  let html = '<div class="sec-title">我的播放列表（' + arr.length + '）</div>';
  if (!arr.length) {
    html += '<div class="empty">还没有保存的播放列表。<br>在「播放列表」页点「💾 另存为」即可保存当前列表。</div>';
  } else {
    html += arr.map((p, i) =>
      '<div class="item"><div class="txt" onclick="loadNamedPlaylist(' + i + ')">'
      + '<div class="t1">' + esc(p.name) + '</div>'
      + '<div class="t2">' + esc((p.items || []).length + ' 首') + '</div></div>'
      + '<div class="act"><button class="iconbtn sm2" onclick="event.stopPropagation();renamePlaylistPrompt(' + i + ')" title="重命名">✎</button>'
      + '<button class="iconbtn sm2 vi" onclick="event.stopPropagation();deletePlaylist(' + i + ')" title="删除">' + I.x + '</button></div></div>'
    ).join('');
    html += '<div class="sm muted" style="margin-top:8px">提示：这里保存的是应用内播放列表，关闭 App 也不会丢；点行即载入并播放。</div>';
  }
  openSheet('我的播放列表', html);
}
function renderQueueSaved() {
  const el = $('queueSaved'); if (!el) return;
  const arr = getPlaylists().slice(0, 3);
  if (!arr.length) { el.style.display = 'none'; return; }
  el.style.display = '';
  el.innerHTML = '<span class="muted sm" style="margin-right:6px">快速：</span>'
    + arr.map((p, i) => '<span class="chip" onclick="loadNamedPlaylist(' + i + ')" title="' + esc(p.name) + '">⚡ ' + esc(p.name) + '</span>').join('');
}
function savePlaylistSheet() {
  const c = curQueueList();
  if (!(c.list || []).length) { toast('当前播放列表是空的', 'err'); return; }
  const html = '<div class="sec-title">另存为播放列表</div>'
    + '<div class="sm muted">将把当前 ' + (c.list.length) + ' 首保存成一个可随时调用的播放列表。</div>'
    + '<input class="inp" id="plSaveInput" placeholder="给播放列表起个名字" style="width:100%;margin:8px 0;box-sizing:border-box"/>'
    + '<div class="chips"><div class="chip on" onclick="doSavePlaylist()">保存</div>'
    + '<div class="chip" onclick="closeSheet()">取消</div></div>';
  openSheet('另存为', html);
  setTimeout(() => { const i = $('plSaveInput'); if (i) i.focus(); }, 50);
}
function doSavePlaylist() {
  const inp = $('plSaveInput'); const name = (inp ? inp.value : '').trim();
  if (!name) { toast('请先输入名字', 'err'); return; }
  if (savePlaylistAs(name)) closeSheet();
}
/* 把本地曲库列表导出成一个 .m3u 文件（落盘到应用私有播放列表目录） */
async function exportLibList() {
  const items = (S._libItems || []).filter(t => t.type !== 'container');
  if (!items.length) { toast('曲库列表是空的', 'err'); return; }
  let m3u = '#EXTM3U\n';
  items.forEach(t => {
    const dur = Math.round(Number(t.duration_sec) || 0);
    const artist = t.artist || '', title = t.title || '未知';
    m3u += '#EXTINF:' + dur + ',' + artist + ' - ' + title + '\n';
    if (t.id) m3u += BASE + '/media?id=' + encodeURIComponent(t.id) + '\n';
    else if (t.url || t.stream_url) m3u += (t.url || t.stream_url) + '\n';
    else m3u += '# (无可用地址)\n';
  });
  try {
    const name = '库列表_' + new Date().toISOString().slice(0, 10);
    const r = await apiPost('/api/export/playlist', { name: name, content: m3u }, 30000);
    if (r && r.ok) toast('已导出到：' + (r.file || '播放列表文件'), 'ok');
    else toast('导出失败：' + ((r && r.msg) || '未知'), 'err');
  } catch (e) { toast('导出失败：' + e.message, 'err'); }
}

/* =========================================================================
   九、播放
   ========================================================================= */
async function playOne(kind, i, forcePhone) {
  const items = getItems(kind);
  const t = items[i];
  if (!t) return;
  buzz();
  // 只取「被点中的那一首」，不再把整页搜索结果都塞进播放列表
  let track = t;
  if (kind === 'online') {
    try {
      const resolved = await resolveOnline([{
        id: t.oid || t.id, provider: t.provider || S.online.provider,
        title: t.title, artist: t.artist, album: t.album,
        duration_sec: t.duration_sec || 0, source: 'online'
      }]);
      if (!resolved.length) throw new Error('无解析结果');
      track = resolved[0];
      // 原地更新显示用对象，保持列表顺序不变
      S.online.items[i] = Object.assign({}, t, track);
    } catch (e) { toast('解析播放地址失败：' + e.message, 'err'); return; }
  }
  if (forcePhone || S.out === 'phone') {
    setOut('phone', true);
    S.phone.queue.push(track);                 // 追加，不覆盖原有列表
    phonePlayAt(S.phone.queue.length - 1);
    pushMediaState();
    return;
  }
  const udns = selectedUdns();
  if (!udns.length) {
    // 没有可用音响（局域网里没发现 DLNA 设备或未选择）→ 自动回退手机本机播放
    toast('未发现可用音响，已改用手机本机播放');
    setOut('phone', true);
    S.phone.queue.push(track);
    phonePlayAt(S.phone.queue.length - 1);
    pushMediaState();
    return;
  }
  toast('正在推送到音响…');
  try {
    // 仅把这一首追加进播放列表（保留原有列表），再跳到它开始播放
    const q = (S.state && S.state.player && Array.isArray(S.state.player.queue)) ? S.state.player.queue : [];
    const idx = q.length;
    await apiPost('/api/queue', { action: 'add', tracks: [track] }, 40000);
    await apiPost('/api/jump', { index: idx }, 9000);
    toast('已开始播放', 'ok');
    await tick(true);
  } catch (e) { toast('播放失败：' + e.message, 'err'); }
}
async function addOne(kind, i) {
  const t = getItems(kind)[i];
  if (t) await addToQueue([t]);
}
async function addLibAll() {
  const its = (S._libItems || []).filter(t => t.type !== 'container');
  if (!its.length) { toast('没有可加入的曲目', 'err'); return; }
  await addToQueue(its.slice());
}
function libActionsUpdate() {
  const bar = $('libActions');
  if (!bar) return;
  const n = (S._libItems || []).filter(t => t.type !== 'container').length;
  if (n) {
    bar.style.display = '';
    const c = $('libCount'); if (c) c.textContent = '当前 ' + n + ' 首';
  } else {
    bar.style.display = 'none';
  }
}

/* --- 手机本机播放 --- */
const audio = $('phone');
function setOut(mode, quiet) {
  S.out = mode;
  if (mode === 'phone') {
    if (AB && AB.startKeepAlive) try { AB.startKeepAlive(); } catch (e) { }
  } else {
    stopPhone();
    if (AB && AB.stopKeepAlive) try { AB.stopKeepAlive(); } catch (e) { }
  }
  if (!quiet) toast(mode === 'phone' ? '输出：手机本机' : '输出：音响', 'ok');
  updatePlayBtn();
  renderMini();
  saveCurQueue();
}
function localPlayUrl(u) {
  if (!u) return u;
  const m = /^https?:\/\/[^/]+(\/.*)$/.exec(u);
  if (!m) return u;
  // 手机本机播放走回环地址，避免部分 ROM 自连局域网 IP 不通；服务绑定 0.0.0.0，回环一定可达
  const port = location.port || '8765';
  return 'http://127.0.0.1:' + port + m[1];
}
function phonePlayAt(i) {
  const t = S.phone.queue[i];
  if (!t) return;
  S.phone.idx = i;
  let url = t.url || t.stream_url;
  if (!url && t.source === 'local' && t.id) {
    // 本地曲目：直接走本机服务的媒体流端点
    url = BASE + '/media?id=' + encodeURIComponent(t.id);
  }
  if (!url) { toast('该曲目没有可用的播放地址', 'err'); return; }
  audio.src = localPlayUrl(url);
  const p = audio.play();
  if (p && p.catch) p.catch(e => toast('本机播放失败：' + e.message, 'err'));
  renderMini(); renderQueue();
  saveCurQueueDebounced();
}
function phoneNext() {
  if (S.phone.idx + 1 < S.phone.queue.length) phonePlayAt(S.phone.idx + 1);
  else { toast('播放列表已播完'); }
  pushMediaState();
}
function phonePrev() {
  if (S.phone.idx > 0) phonePlayAt(S.phone.idx - 1);
  pushMediaState();
}
function stopPhone() { try { audio.pause(); } catch (e) { } pushMediaState(); }
function phoneToggle() {
  if (!S.phone.queue.length) { toast('先选一首歌'); return; }
  if (S.phone.idx < 0) { phonePlayAt(0); return; }
  if (audio.paused) { const p = audio.play(); if (p && p.catch) p.catch(() => { }); }
  else audio.pause();
  pushMediaState();
}
audio.addEventListener('ended', function () {
  const pl = (S.state && S.state.player) || {};
  if (pl.repeat === 'one') { try { audio.currentTime = 0; audio.play(); } catch (e) { } return; }
  if (S.phone.idx + 1 < S.phone.queue.length) { phoneNext(); return; }
  if (pl.repeat === 'all' && S.phone.queue.length) { phonePlayAt(0); return; }
  toast('播放列表已播完');
});
audio.addEventListener('play', updatePlayBtn);
audio.addEventListener('pause', updatePlayBtn);
audio.addEventListener('timeupdate', () => {
  if (S.out === 'phone') { renderMini(); updateLyricProgress(audio.currentTime || 0); }
});

/* --- 统一的控制入口 --- */
async function ctl(action) {
  if (S.out === 'phone') {
    if (action === 'play' || action === 'pause') phoneToggle();
    else if (action === 'next') phoneNext();
    else if (action === 'prev') phonePrev();
    else if (action === 'stop') { stopPhone(); }
    return;
  }
  try {
    const r = await apiPost('/api/control', { action: action });
    if (r.ok === false) throw new Error(r.result || '失败');
    pushMediaState();
    setTimeout(() => tick(true), 400);
  } catch (e) { toast('操作失败：' + e.message, 'err'); }
}

function nowPlaying() {
  if (S.out === 'phone') {
    const t = S.phone.queue[S.phone.idx];
    const dur = audio.duration || 0, pos = audio.currentTime || 0;
    const playing = !audio.paused && !audio.ended;
    return { t: t, pos: pos, dur: dur, playing: playing };
  }
  const pl = (S.state && S.state.player) || {};
  const t = pl.current || null;
  const sel = selectedDevices();
  let pos = 0, dur = 0;
  sel.forEach(d => {
    if ((d.position_sec || 0) > pos) pos = d.position_sec || 0;
    if ((d.duration_sec || 0) > 0) dur = Math.max(dur, d.duration_sec || 0);
  });
  if (!dur && t && t.duration_sec) dur = t.duration_sec;
  pos = smoothAccept(pos, pl.playing);   // 进度平滑：滤掉快照噪声，只认真跳变
  return { t: t, pos: pos, dur: dur, playing: !!pl.playing };
}

/* 进度平滑器：音响的进度上报有粒度和延迟（有的设备几秒才刷一次，
   多台取 max 还会来回切源），直接画会乱跳。
   规则：
   - 本地按时钟外推（每 300ms 高亮定时器与 1.6s 轮询都会调到）；
   - 新快照与当前外推差 < 2.5s → 当作上报噪声，忽略，继续外推；
   - 差 >= 2.5s → 视为真实 seek/换曲/暂停恢复，跳变采纳；
   - 手动 seek 后 5s 宽限期内完全以 seek 目标外推（音响生效有延迟）。 */
function smoothAccept(rawPos, playing) {
  const now = performance.now();
  playing = !!playing;
  if (!S._sm || !playing) {
    S._sm = { pos: rawPos, at: now, playing: playing };
    return rawPos;
  }
  const el = Math.min(30, Math.max(0, now - S._sm.at) / 1000);
  let cur = S._sm.playing ? S._sm.pos + el : S._sm.pos;
  if (S._seekAt && now - S._seekAt < 5000) {
    cur = S._seekPos + (S._sm.playing ? el : 0);
  } else if (Math.abs(rawPos - cur) > 2.5) {
    cur = rawPos;
  }
  S._sm = { pos: cur, at: now, playing: playing };
  return cur;
}

function renderMini() {
  const n = nowPlaying();
  const mini = $('mini');
  if (!n.t) { mini.style.display = 'none'; return; }
  mini.style.display = '';
  $('miniTitle').textContent = n.t.title || '未知';
  const sub = [n.t.artist, S.out === 'phone' ? '本机播放' : (selectedDevices().length ? '音响' : '')].filter(Boolean).join(' · ');
  $('miniSub').textContent = sub;
  const pct = (n.dur > 0) ? Math.min(100, n.pos / n.dur * 100) : 0;
  $('miniProg').style.width = pct + '%';
  updatePlayBtn();
}
function updatePlayBtn() {
  const n = nowPlaying();
  const b = $('miniPlay');
  b.textContent = n.playing ? '⏸' : '▶';
}

/* 把当前曲目 + 播放状态推给原生层，用于锁屏 / 通知栏媒体控制 */
function pushMediaState() {
  if (!(AB && AB.updateMedia)) return;
  const n = nowPlaying();
  const key = (n.t ? ((n.t.title || '') + '|' + (n.t.artist || '')) : '') + '|' + (n.playing ? 1 : 0);
  if (S._lastMediaKey === key) return;     // 没变化就不刷通知，避免 300ms 抖动
  S._lastMediaKey = key;
  try { AB.updateMedia(n.t ? (n.t.title || '') : '', n.t ? (n.t.artist || '') : '', !!n.playing); }
  catch (e) { }
}

/* --- 播放器大面板 --- */
function playerSheet() { switchTab('now'); }

/* 正在播放页：内容与原弹窗一致，作为底栏常驻大项 */
function nowHTML() {
  const n = nowPlaying();
  const t = n.t || {};
  const adl = autoDlOn();
  return `
    <div class="np-stage">
      <div class="np-art" id="npArt">${n.playing ? '♫' : '♪'}</div>
      <div class="lrc-box np-lrc" id="lyricBox" style="display:none"><div class="empty sm" style="padding:18px">加载歌词…</div></div>
    </div>
    <div class="lrc-off">
      <span class="sm muted">歌词</span>
      <button class="btn sm" onclick="lyricOffShift(-500)">慢 0.5s</button>
      <span id="lrcOffVal" class="sm" style="color:var(--cy);min-width:70px;text-align:center">${lyricOffLabel()}</span>
      <button class="btn sm" onclick="lyricOffShift(500)">快 0.5s</button>
    </div>
    <div class="np-title">${esc(t.title || '未播放')}</div>
    <div class="np-sub">${esc([t.artist, t.album].filter(Boolean).join(' · '))}</div>

    <div class="np-time"><span id="npPos">${fmt(n.pos)}</span><span id="npDur">${fmt(n.dur)}</span></div>
    <input id="npSeek" type="range" min="0" max="${Math.max(1, Math.floor(n.dur))}" value="${Math.floor(n.pos)}"
           oninput="seekLive(this.value)" onchange="seekTo(this.value)" ${n.dur ? '' : 'disabled'}>

    <div class="sec-title">输出方式</div>
    <div class="chips">
      <div class="chip ${S.out === 'dlna' ? 'on' : ''}" onclick="setOut('dlna');playerSheet()">🔊 音响播放</div>
      <div class="chip ${S.out === 'phone' ? 'on' : ''}" onclick="setOut('phone');playerSheet()">📱 手机本机</div>
    </div>

    <div class="sec-title">边听边下载</div>
    <div class="chips">
      <div class="chip ${adl ? 'on' : ''}" onclick="setAutoDl(${!adl})">⤓ 边听边下载：${adl ? '开' : '关'}</div>
    </div>
    <div class="sm muted" style="margin-top:8px">切「手机本机」＝声音从手机出，音响自动停。</div>
  `;
}
function renderNowTab() {
  const n = nowPlaying();
  $('nowBody').innerHTML = nowHTML();
  S._nowKey = trackKeyOf(n.t) + '|' + (n.playing ? '1' : '0');
  setTimeout(function () { loadLyric(n.t); renderLyric(); }, 0);
}
function refreshNow() {
  if (!$('nowBody') || S.tab !== 'now') return;
  const n = nowPlaying();
  const key = trackKeyOf(n.t) + '|' + (n.playing ? '1' : '0');
  if (key !== S._nowKey) { renderNowTab(); return; }
  const seek = $('npSeek');
  if (seek && n.dur && performance.now() >= (S._seekDragUntil || 0)) seek.value = Math.floor(n.pos);
  const posEl = $('npPos');
  if (posEl) posEl.textContent = fmt(n.pos);
}
function avgVol(list) {
  const arr = ((list && list.length) ? list : selectedDevices()).filter(d => d.volume != null);
  if (!arr.length) return 50;
  return Math.round(arr.reduce((a, d) => a + d.volume, 0) / arr.length);
}
function seekLive(v) {
  S._seekDragUntil = performance.now() + 1500;   // 拖动中：1.5s 内轮询不得改写滑条
  const el = $('npPos'); if (el) el.textContent = fmt(v);
}

/** 音量面板：全 App 唯一的音量调节处。
    传设备下标 i 只调那一台；不传则调所有已选音响。
    音响输出 → /api/volume；手机本机 → audio.volume。 */
function volumeSheet(i) {
  // addEventListener 会把 Event 当第一个参数传进来，必须挡掉
  if (typeof i !== 'number' || !isFinite(i) || i < 0) i = null;
  S._volIdx = (i != null && devices()[i]) ? i : null;
  S._volDirty = false;
  const phone = (S.out === 'phone' && S._volIdx == null);
  S._volPhone = phone;
  if (phone) {
    const pc = Math.round((audio.volume == null ? 1 : audio.volume) * 100);
    openSheet('音量 · 手机本机',
      volBody(pc, '这是手机自己的媒体音量，只影响「手机本机」播放。'));
    return;
  }
  const list = volTargets();
  if (!list.length) { toast('先选一台音响', 'err'); return; }
  const cur = avgVol(list);
  const name = list.length === 1 ? (list[0].name || '音响') : (list.length + ' 台同步');
  openSheet('音量 · ' + name,
    volBody(cur, '拖动滑条或点 − / + 调节音量，长按 − / + 可连续调节。' +
      (list.length > 1 ? '同步播放时会一起设置所有已选音响。' : '')));
}
function volTargets() {
  if (S._volIdx != null) { const d = devices()[S._volIdx]; return d ? [d] : []; }
  return selectedDevices();
}
function volBody(cur, hint) {
  const quick = [0, 20, 40, 60, 80, 100];
  return `
    <div class="sec-title">音量</div>
    <div class="vrow">
      <button class="vbtn" id="volDec" onpointerdown="volHold(-1,event)" onpointerup="volAutoStop()"
              onpointerleave="volAutoStop()" onpointercancel="volAutoStop()"
              oncontextmenu="return false">−</button>
      <input id="volRange" type="range" min="0" max="100" value="${cur}"
             oninput="volLive(this.value)" onchange="volCommit(this.value)">
      <button class="vbtn" id="volInc" onpointerdown="volHold(1,event)" onpointerup="volAutoStop()"
              onpointerleave="volAutoStop()" onpointercancel="volAutoStop()"
              oncontextmenu="return false">+</button>
      <b id="volNum">${cur}</b>
    </div>
    <div class="sm muted" style="margin-top:10px">${hint}</div>
    <div class="sec-title">快速调整</div>
    <div class="chips">
      ${quick.map(v => `<div class="chip" onclick="volCommit(${v})">${v}</div>`).join('')}
    </div>`;
}
async function seekTo(v) {
  v = parseInt(v, 10) || 0;
  S._seekPos = v;
  S._seekAt = performance.now();   // 5s 宽限期：期间进度条以目标位置外推
  if (S.out === 'phone') { try { audio.currentTime = v; } catch (e) { } return; }
  try { await apiPost('/api/seek', { position: v }); } catch (e) { toast('跳转失败：' + e.message, 'err'); }
}
/** 拖动滑条：只更新数字，松手由 onchange → volCommit 下发 */
function volLive(v) {
  const el = $('volNum'); if (el) el.textContent = v;
}
/** 写入数字并同步滑条位置，返回裁剪后的值 */
function volSetNum(v) {
  const n = Math.max(0, Math.min(100, parseInt(v, 10) || 0));
  const el = $('volNum'); if (el) el.textContent = n;
  const r = $('volRange'); if (r && r.value !== String(n)) r.value = n;
  return n;
}
/** − / + 按钮：单击一步；长按 450ms 后每 100ms 一步连续调节 */
function volHold(d, ev) {
  if (ev && ev.preventDefault) ev.preventDefault();
  buzz();
  volNudge(d);
  volAutoStop(true);
  S._volDelay = setTimeout(function () {
    S._volAuto = setInterval(function () { volNudge(d); }, 100);
  }, 450);
}
function volNudge(d) {
  const el = $('volNum');
  const cur = el ? (parseInt(el.textContent, 10) || 0) : 0;
  const v = volSetNum(cur + d);
  if (v === cur) return;
  S._volDirty = true;
  // 停手 260ms 后才真正下发，避免长按时把音响刷爆
  clearTimeout(S._volDeb);
  S._volDeb = setTimeout(volFlush, 260);
}
/** 抬手 / 移出：停止连续调节并立即下发 */
function volAutoStop(keepDirty) {
  clearTimeout(S._volDelay); S._volDelay = null;
  if (S._volAuto) { clearInterval(S._volAuto); S._volAuto = null; }
  if (!keepDirty) volFlush();
}
function volFlush() {
  clearTimeout(S._volDeb); S._volDeb = null;
  if (!S._volDirty) return;
  const el = $('volNum');
  volCommit(el ? el.textContent : 50);
}
/** 真正生效：本机改 audio.volume，音响走 /api/volume */
function volCommit(v) {
  const n = volSetNum(v);
  S._volDirty = false;
  clearTimeout(S._volDeb); S._volDeb = null;
  if (S._volPhone) { try { audio.volume = n / 100; } catch (e) { } return; }
  volAll(n);
}
async function volAll(v) {
  v = parseInt(v, 10) || 0;
  let udns = null;
  if (S._volIdx != null) { const d = devices()[S._volIdx]; if (d) udns = [d.udn]; }
  try {
    const r = await apiPost('/api/volume', udns ? { volume: v, udns: udns } : { volume: v });
    if (r && r.ok === false) throw new Error(r.result || '失败');
    if (udns) { const d = devices()[S._volIdx]; if (d) d.volume = v; }
    await tick(true);
  } catch (e) {
    const m = (e && e.message) || '未知错误';
    toast(m.indexOf('音量') >= 0 ? m : ('音量设置失败：' + m), 'err');
  }
}
/* 列表循环 / 单曲循环：再点已激活的芯片即关闭（回到顺序播放）；关闭循环即顺序播放 */
async function toggleRepeat(mode) {
  const pl = (S.state && S.state.player) || {};
  await setRepeat(pl.repeat === mode ? 'off' : mode);
}

async function setRepeat(mode) {
  try { await apiPost('/api/mode', { repeat: mode }); toast('已切换播放模式', 'ok'); await tick(true); }
  catch (e) { toast('失败：' + e.message, 'err'); }
}

/* =========================================================================
   十、弹层 / 导航 / 设置
   ========================================================================= */
function openSheet(title, html) {
  $('sheetTitle').innerHTML = title;
  $('sheetBody').innerHTML = html;
  $('sheet').style.display = 'flex';
  $('mask').style.display = '';
}
function closeSheet() {
  $('sheet').style.display = 'none';
  $('mask').style.display = 'none';
}
/* ---- 电视模式开关（实现都在 tv.js，未加载时安静降级） ---- */
function tvOn() {
  try { return !!(window.TV && window.TV.enabled()); } catch (e) { return false; }
}
function tvToggle() {
  if (!window.TV) { toast('当前环境不支持电视模式', 'err'); return; }
  const on = window.TV.toggle();
  toast(on ? '已开启电视模式（遥控器）' : '已关闭电视模式');
  settingsSheet();
}

function settingsSheet() {
  openSheet('设置', `
    <div class="chips">
      <div class="chip" onclick="closeSheet();musicSourcesSheet()">🗂 曲库管理</div>
      <div class="chip" onclick="closeSheet();dlStatus()">⤓ 下载状态</div>
    </div>

    <div class="sec-title">语言 / Language</div>
    <div class="chips">
      <div class="chip ${(window.I18N && I18N.lang) === 'zh' ? 'on' : ''}" onclick="I18N.set('zh')">中文</div>
      <div class="chip ${(window.I18N && I18N.lang) === 'en' ? 'on' : ''}" onclick="I18N.set('en')">English</div>
    </div>

    <div class="sec-title">电视模式（遥控器）</div>
    <div class="chips">
      <div class="chip ${tvOn() ? 'on' : ''}" onclick="tvToggle()">📺 电视模式：${tvOn() ? '开' : '关'}</div>
    </div>
    <div class="sm muted" style="margin-top:8px">
      开关后界面立刻切换：左侧竖排导航、控件放大、焦点高亮。<br>
      遥控器：方向键选择 · <strong>OK</strong> 确认 · <strong>返回</strong> 上一级；
      媒体键 ⏯ ⏭ ⏮ 控制播放；频道键 CH± 调音量。装在电视 / 盒子上会自动开启。
    </div>

    <div class="sec-title">歌词字号（竖屏）</div>
    <div style="display:flex;align-items:center;gap:12px;padding:0 2px">
      <input type="range" min="14" max="42" value="${lyricSizeSaved()}" style="flex:1"
             oninput="setLyricSize(this.value)" onchange="setLyricSize(this.value)">
      <span id="lyrSizeVal" class="sm" style="min-width:48px;text-align:right;color:var(--cy)">${lyricSizeSaved()}px</span>
    </div>

    <div class="sec-title">歌词字号（横屏）</div>
    <div style="display:flex;align-items:center;gap:12px;padding:0 2px">
      <input type="range" min="14" max="42" value="${lyricSizeLandSaved()}" style="flex:1"
             oninput="setLandLyricSize(this.value)" onchange="setLandLyricSize(this.value)">
      <span id="lyrSizeLandVal" class="sm" style="min-width:48px;text-align:right;color:var(--cy)">${lyricSizeLandSaved()}px</span>
    </div>

    <div class="sec-title">主题配色</div>
    <div class="chips">
      ${THEMES.map(t => '<div class="chip ' + (themeSaved() === t.key ? 'on' : '') + '" onclick="setTheme(\'' + t.key + '\')">' + esc(t.label) + '</div>').join('')}
    </div>

    <div class="sec-title">关于</div>
    <div class="sm muted">
      SyncDlnaPlay · 独立运行版${AB && AB.getVersion ? ' v' + esc(AB.getVersion()) : ''}<br>
      DLNA 控制、曲库、在线音源全部在手机本机运行，无需家中服务器。
    </div>
    <div class="chips" style="margin-top:12px">
      <div class="chip" onclick="helpSheet()">📖 使用说明（详细教程）</div>
    </div>
    <div class="chips" style="margin-top:8px">
      <div class="chip" onclick="AB&&AB.exitApp&&AB.exitApp()">退出应用</div>
    </div>
  `);
}


/* ---- 使用说明（详细教程，v2.8） ---- */
function helpSheet() {
  const H = [];
  H.push('<div class="help">');
  const sec = (t, body) => H.push('<div class="sec-title">' + t + '</div>' + body);
  const p = (x) => '<div class="sm" style="margin:4px 0;line-height:1.75">' + x + '</div>';
  const li = (x) => '<div class="sm" style="margin:3px 0 3px 10px;line-height:1.7">· ' + x + '</div>';

  H.push('<div class="sm" style="line-height:1.8">SyncDlnaPlay 是一款<strong>完全运行在手机上</strong>的音乐播放与 DLNA 投放工具：手机本机放歌、把歌投到局域网里的 DLNA 音响、扫描本地与 SMB 网络曲库、在线搜索并下载歌曲。不需要家里架设任何服务器，换 Wi-Fi、用流量热点都能用。</div>');

  sec('🚀 快速上手（3 步）',
    p('<strong>① 连音响：</strong>底部「我的设备」→ 点「扫描」，发现的音响会列出，点一下选中（可多选多台同时响）。')
    + p('<strong>② 选歌：</strong>「本地曲库」放手机里的歌；「在线搜索」搜网上的歌，点 ＋ 加入播放列表。')
    + p('<strong>③ 开播：</strong>在「播放列表」点歌即播。声音从哪出由「正在播放」页的「输出方式」决定：音响 or 手机。')
    + p('<span style="color:var(--cy)">小提示：如果局域网里没发现任何音响，播放会自动回落到手机本机，不会卡在"播放不了"。</span>'));

  sec('▶ 正在播放',
    li('<strong>封面 / 歌词：</strong>有歌词时封面位置直接显示滚动歌词，点任意一句可跳转到那句；没有歌词时显示唱片封面。')
    + li('<strong>进度条：</strong>可拖动；投音响时进度按本机时钟平滑外推，歌词和进度都跟手。')
    + li('<strong>输出方式：</strong>「🔊 音响播放」把声音投到选中的 DLNA 音响；「📱 手机本机」用手机扬声器/耳机放。切换时另一边会自动停。')
    + li('<strong>边听边下载：</strong>打开开关后，每播一首在线歌曲就自动加入下载队列，存到下载目录（默认 Music/音响管家，文件管理器可见）。本地歌曲不重复下载，同一首每次会话只下一次。'));

  sec('📡 我的设备',
    li('<strong>扫描：</strong>自动发现局域网里的 DLNA/UPnP 音响（斐讯音箱、小爱、电视等）。')
    + li('<strong>多选：</strong>可同时勾选多台，组成同步播放组。')
    + li('<strong>SMB 面板：</strong>「扫描局域网」自动找开 445 端口的 NAS/路由器；「浏览共享」逐层点进共享文件夹，选中的目录会加入本地曲库，不用手记路径。'));

  sec('💽 本地曲库',
    li('自动扫描手机存储里的音频（MediaStore，无需手动刷新）。')
    + li('「曲库管理」里可添加多个音乐目录：设备存储文件夹、SMB 网络共享都可以。')
    + li('每首歌右侧按钮：＋ 加入播放列表、⤓ 下载/查看。')
    + li('下载目录可在「曲库管理 → 下载目录」里用系统文件夹选择器任改（含 SD 卡/U 盘）。'));

  sec('🌐 在线搜索',
    li('内置多个 MusicFree 社区音源（元力系列等），支持关键词搜索与翻页。')
    + li('<strong>音源管理：</strong>点搜索框旁的管理入口 → 可「停用/启用」内置音源，也能添加自己的音源：<strong>粘贴插件链接 URL</strong>、<strong>粘贴插件源码/分享码</strong>、或<strong>从文件导入 .js</strong>。')
    + li('<strong>默认音源：</strong>在音源管理里点 ★ 星标设为默认。')
    + li('<strong>记住上次音源：</strong>每次搜索会记住所用音源，下次打开自动就是它。')
    + li('时长小于 1 分钟的试听片段会在下载预检时自动跳过。'));

  sec('📋 播放列表',
    li('点歌曲行任意位置即跳播；右侧 × 可从列表移除；「清空」一键清空。')
    + li('<strong>播放模式（v2.8 起在这里设置）：</strong>🔀 随机、🔁 列表循环、🔂 单曲循环。关闭循环即按列表顺序播放。')
    + li('<strong>自动保存：</strong>播放列表会随 App 一起保存，下次打开自动恢复（含手机/音响两种输出）。')
    + li('<strong>另存为 / 我的播放列表：</strong>「💾 另存为」把当前列表存成命名列表；「📂 我的播放列表」可载入/重命名/删除，列表顶部还有前 3 个的快速切换。'));

  sec('📥 下载的文件在哪',
    p('默认保存在手机公共目录 <strong>Music/音响管家/</strong>，按「歌手/歌手 - 歌名」命名，任何文件管理器都能看到。下载状态可在「设置 → 下载状态」查看进度与失败原因。'));

  sec('❓ 常见问题',
    li('<strong>扫描不到音响？</strong>确认手机和音响在同一 Wi-Fi；部分路由器开了 AP 隔离会屏蔽发现协议。找不到也没关系，会自动用手机本机播放。')
    + li('<strong>在线歌解析失败 / 下载失败？</strong>第三方音源接口偶尔不稳定，换个音源或稍后再试。')
    + li('<strong>这首歌没有歌词？</strong>在线歌词取决于音源是否提供；本地歌请在同目录放同名 .lrc 文件（支持 UTF-8/GBK）。')
    + li('<strong>SMB 连不上？</strong>检查用户名/密码、共享名大小写，以及 NAS 是否允许来宾访问。')
    + li('<strong>耗电与后台？</strong>本 App 只在你使用时工作；下拉通知栏的常驻通知用于保持后台播放不被系统杀掉。'));

  H.push('</div>');
  openSheet('使用说明', H.join(''));
}

/* --- 原生端回调 --- */
window.__onPermissionChanged = function () {
  toast('已获得读取权限，开始扫描音乐', 'ok');
  loadLib();
  tick(true);
};
window.__onLibraryChanged = function () { loadLib(); tick(true); };

/* --- 返回键（原生端会调用） --- */
window.__onBack = function () {
  if ($('sheet').style.display !== 'none') { closeSheet(); return true; }
  if (S.tab !== 'devices') { switchTab('devices'); return true; }
  return false;
};

/* =========================================================================
   十一、初始化
   ========================================================================= */
(function init() {
  loadBase();
  applyTheme(); applyLyricSize(); applyLandLyricSize();

  $('btnRetry').addEventListener('click', () => { setMsg(''); startEngine(); });

  document.querySelectorAll('.navbtn').forEach(b => {
    b.addEventListener('click', () => { buzz(); switchTab(b.getAttribute('data-tab')); });
  });
  $('topDev').addEventListener('click', () => switchTab('devices'));
  $('btnSettings').addEventListener('click', settingsSheet);

  $('btnRescan').addEventListener('click', async () => {
    toast('正在扫描…');
    try { await apiPost('/api/scan', {}); } catch (e) { }
    setTimeout(() => tick(true), 3000);
  });
  $('btnResync').addEventListener('click', async () => {
    toast('正在校准…');
    try { const r = await apiPost('/api/resync', {}); toast(r.ok ? '已校准' : ('失败：' + (r.result || '')), r.ok ? 'ok' : 'err'); }
    catch (e) { toast('失败：' + e.message, 'err'); }
  });

  $('btnLibMore').addEventListener('click', libMore);
  $('btnLibSearch').addEventListener('click', libSearch);
  $('btnLibAll').addEventListener('click', addLibAll);
  document.querySelectorAll('#libSource .segbtn').forEach(b => {
    b.addEventListener('click', () => {
      document.querySelectorAll('#libSource .segbtn').forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      S.lib.source = b.getAttribute('data-src');
      S.lib.container = S.lib.source === 'dlna' ? '0' : '';
      S.lib.crumbs = [];
      window.__libKw = '';
      loadLib();
    });
  });

  $('btnOnlineSearch').addEventListener('click', () => doOnlineSearch(1));
  $('onlineQ').addEventListener('keydown', e => { if (e.key === 'Enter') { $('onlineQ').blur(); doOnlineSearch(1); } });
  $('btnOnlineAll').addEventListener('click', addOnlineAll);
  $('btnOnlineDl').addEventListener('click', downloadOnlineAll);
  $('btnDlStatus').addEventListener('click', dlStatus);
  $('btnPagePrev').addEventListener('click', () => doOnlineSearch(Math.max(1, S.online.page - 1)));
  $('btnPageNext').addEventListener('click', () => doOnlineSearch(S.online.page + 1));
  $('onlineLimit').addEventListener('change', () => { if (S.online.q) doOnlineSearch(1); });

  $('btnQueueClear').addEventListener('click', queueClear);
  $('btnQueueSave').addEventListener('click', savePlaylistSheet);
  $('btnQueueLists').addEventListener('click', playlistsSheet);
  $('btnLibExport').addEventListener('click', exportLibList);

  $('miniVol').addEventListener('click', volumeSheet);
  $('miniPlay').addEventListener('click', () => ctl(nowPlaying().playing ? 'pause' : 'play'));
  $('miniPrev').addEventListener('click', () => ctl('prev'));
  $('miniNext').addEventListener('click', () => ctl('next'));
  $('miniOpen').addEventListener('click', playerSheet);
  $('onlineProvider').addEventListener('change', function () {
    S.online.provider = this.value;
    try { localStorage.setItem('dlna_lastprov', this.value); } catch (e) { }
  });
  $('sheetClose').addEventListener('click', closeSheet);
  const _bsm = $('btnSrcMgr');
  if (_bsm) _bsm.addEventListener('click', srcMgrSheet);
  $('mask').addEventListener('click', closeSheet);

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && BASE) tick(true);
    else saveCurQueue();
  });
  window.addEventListener('pagehide', saveCurQueue);
  window.addEventListener('beforeunload', saveCurQueue);

  // 启动本机内置服务（它在 App 进程里，不存在"连不上服务器"）
  startEngine().catch(e => setMsg('启动异常：' + ((e && e.message) || e), true));
})();
