# -*- coding: utf-8 -*-
"""v2.7 补丁：
1. 改名 SynclDlnaDlayer -> SyncDlnaPlay
2. 「正在播放」独立为底栏大项（放在设备前），playerSheet 变为切换到该 tab
3. 音源：默认音源设置 + 记住上次搜索音源（localStorage）
4. 歌词滞后修复：进度按本机时钟外推 + 300ms 高亮定时器
5. 按钮立体化（保持配色，追加 CSS 块）
"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
WWW = os.path.join(PROJ, "app", "assets", "www")


def rd(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def wr(p, s):
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def sub(s, old, new, tag):
    assert old in s, "anchor missing: " + tag
    return s.replace(old, new, 1)


# ---------- 1. 改名 ----------
for p in [os.path.join(WWW, "index.html"), os.path.join(WWW, "app.js"),
          os.path.join(PROJ, "app", "res", "values", "strings.xml"),
          os.path.join(PROJ, "app", "java", "com", "dlna", "speaker", "KeepAliveService.java")]:
    s = rd(p)
    n = s.count("SynclDlnaDlayer")
    if n:
        wr(p, s.replace("SynclDlnaDlayer", "SyncDlnaPlay"))
        print("改名 %s: %d 处" % (os.path.basename(p), n))

# ---------- 2. index.html：nav + tab-now ----------
p = os.path.join(WWW, "index.html")
s = rd(p)
s = sub(s, '''  <nav class="nav">
    <button class="navbtn on" data-tab="devices">''', '''  <nav class="nav">
    <button class="navbtn" data-tab="now">
      <i><svg class="ni" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.8"/><circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none"/><path d="M12 3.2v6.4" opacity=".5"/><path d="M19.5 17.5a8.8 8.8 0 0 1-3 2.6" opacity=".5"/></svg></i>
      <span>正在播放</span>
    </button>
    <button class="navbtn on" data-tab="devices">''', "nav-now")
s = sub(s, '''    <section class="tab" id="tab-devices">''', '''    <section class="tab" id="tab-now" style="display:none">
      <div id="nowBody"></div>
    </section>
    <section class="tab" id="tab-devices">''', "tab-now")
wr(p, s)
print("index.html: nav + tab-now 完成")

# ---------- 3. app.js ----------
p = os.path.join(WWW, "app.js")
s = rd(p)

# 3a. TAB_TITLE + switchTab
s = sub(s, "const TAB_TITLE = { devices: '设备', lib: '曲库', online: '在线音乐', queue: '播放列表' };",
        "const TAB_TITLE = { now: '正在播放', devices: '设备', lib: '曲库', online: '在线音乐', queue: '播放列表' };",
        "TAB_TITLE")
s = sub(s, "  ['devices', 'lib', 'online', 'queue'].forEach(t => {",
        "  ['now', 'devices', 'lib', 'online', 'queue'].forEach(t => {", "switchTab-list")
s = sub(s, """  if (name === 'lib') loadLib();
  if (name === 'queue') renderQueue();""", """  if (name === 'now') renderNowTab();
  if (name === 'lib') loadLib();
  if (name === 'queue') renderQueue();""", "switchTab-now")

# 3b. playerSheet -> now tab
old_sheet_start = s.index("function playerSheet() {")
old_sheet_end = s.index("  setTimeout(function () { loadLyric(n.t); renderLyric(); }, 0);\n}", old_sheet_start)
old_sheet_end = s.index("}", old_sheet_end) + 1  # 该 setTimeout 块结束的 }
new_player = '''function playerSheet() { switchTab('now'); }

/* 正在播放页：内容与原弹窗一致，作为底栏常驻大项 */
function nowHTML() {
  const n = nowPlaying();
  const pl = (S.state && S.state.player) || {};
  const t = n.t || {};
  return `
    <div class="np-art">${n.playing ? '♫' : '♪'}</div>
    <div class="np-title">${esc(t.title || '未播放')}</div>
    <div class="np-sub">${esc([t.artist, t.album].filter(Boolean).join(' · '))}</div>

    <div class="np-time"><span id="npPos">${fmt(n.pos)}</span><span id="npDur">${fmt(n.dur)}</span></div>
    <input id="npSeek" type="range" min="0" max="${Math.max(1, Math.floor(n.dur))}" value="${Math.floor(n.pos)}"
           oninput="seekLive(this.value)" onchange="seekTo(this.value)" ${n.dur ? '' : 'disabled'}>

    <div class="np-ctl">
      <button class="iconbtn" onclick="ctl('prev')">⏮</button>
      <button class="iconbtn big" id="npPlay" onclick="ctl('${n.playing ? 'pause' : 'play'}')">${n.playing ? '⏸' : '▶'}</button>
      <button class="iconbtn" onclick="ctl('next')">⏭</button>
    </div>

    <div class="sec-title">输出方式</div>
    <div class="chips">
      <div class="chip ${S.out === 'dlna' ? 'on' : ''}" onclick="setOut('dlna');playerSheet()">🔊 音响播放</div>
      <div class="chip ${S.out === 'phone' ? 'on' : ''}" onclick="setOut('phone');playerSheet()">📱 手机本机</div>
    </div>

    <div class="sec-title">歌词</div>
    <div class="lrc-box" id="lyricBox"><div class="empty sm" style="padding:18px">加载中…</div></div>

    <div class="sec-title">播放模式</div>
    <div class="chips">
      <div class="chip ${pl.shuffle ? 'on' : ''}" onclick="queueShuffle()">🔀 随机</div>
      <div class="chip ${pl.repeat === 'all' ? 'on' : ''}" onclick="setRepeat('all')">🔁 列表循环</div>
      <div class="chip ${pl.repeat === 'one' ? 'on' : ''}" onclick="setRepeat('one')">🔂 单曲循环</div>
      <div class="chip ${(!pl.repeat || pl.repeat === 'off') ? 'on' : ''}" onclick="setRepeat('off')">➡ 顺序播放</div>
    </div>
    <div class="sm muted" style="margin-top:10px">切到「手机本机」后，声音从手机的扬声器/耳机出，音响那边会自动停下。</div>
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
  if (seek && document.activeElement !== seek && n.dur) seek.value = Math.floor(n.pos);
  const posEl = $('npPos');
  if (posEl) posEl.textContent = fmt(n.pos);
}'''
s = s[:old_sheet_start] + new_player + s[old_sheet_end:]
print("app.js: playerSheet -> now tab 完成")

# 3c. tick：记录进度快照 + 刷新正在播放页
s = sub(s, """    S.state = st;
    renderTopDev();""", """    S.state = st;
    const plr = (st.player || {});
    let rawPos = 0;
    (st.devices || []).forEach(function (d) { if ((d.position_sec || 0) > rawPos) rawPos = d.position_sec || 0; });
    S.posRef = { pos: rawPos, at: performance.now(), playing: !!plr.playing };
    renderTopDev();""", "tick-posref")
s = sub(s, """    renderMini();
    renderQueue();
    updateLyricProgress(nowPlaying().pos);
  } catch (e) {""", """    renderMini();
    renderQueue();
    if (S.tab === 'now') refreshNow();
    updateLyricProgress(nowPlaying().pos);
  } catch (e) {""", "tick-refreshnow")

# 3d. nowPlaying() 外推
s = sub(s, """  if (!dur && t && t.duration_sec) dur = t.duration_sec;
  return { t: t, pos: pos, dur: dur, playing: !!pl.playing };""", """  if (!dur && t && t.duration_sec) dur = t.duration_sec;
  // 歌词/进度平滑：服务端进度是轮询快照，两次轮询之间按本机时钟外推
  if (pl.playing && S.posRef && S.posRef.playing) {
    const el = Math.min(30, Math.max(0, performance.now() - S.posRef.at) / 1000);
    pos = Math.max(pos, S.posRef.pos + el);
  }
  return { t: t, pos: pos, dur: dur, playing: !!pl.playing };""", "nowplaying-extrap")

# 3e. 启动 300ms 歌词/进度定时器
s = sub(s, "  S.poll = setInterval(() => tick(), document.hidden ? 5000 : 1600);",
        """  S.poll = setInterval(() => tick(), document.hidden ? 5000 : 1600);
  if (S.lyrTimer) clearInterval(S.lyrTimer);
  S.lyrTimer = setInterval(function () {
    if (S.lyric.lines.length) updateLyricProgress(nowPlaying().pos);
    if (S.tab === 'now') refreshNow();
  }, 300);""", "lyr-timer")

# 3f. 音源默认 + 记住上次
s = sub(s, """    sel.innerHTML = list.map(p => `<option value="${esc(p.platform)}">${esc(p.platform)}</option>`).join('');
    if (keep && list.some(p => p.platform === keep)) sel.value = keep;
    else S.online.provider = list[0].platform;
    S.online.plugins = list;""", """    sel.innerHTML = list.map(p => `<option value="${esc(p.platform)}">${esc(p.platform)}</option>`).join('');
    let defP = '', lastP = '';
    try { defP = localStorage.getItem('dlna_defaultprov') || ''; lastP = localStorage.getItem('dlna_lastprov') || ''; } catch (e) { }
    const pick = (keep && list.some(p => p.platform === keep)) ? keep
      : (lastP && list.some(p => p.platform === lastP)) ? lastP
      : (defP && list.some(p => p.platform === defP)) ? defP
      : list[0].platform;
    sel.value = pick;
    S.online.provider = pick;
    S.online.plugins = list;""", "loadproviders-pick")
s = sub(s, """  S.online.provider = $('onlineProvider').value;
  S.online.page = page || 1;""", """  S.online.provider = $('onlineProvider').value;
  try { localStorage.setItem('dlna_lastprov', S.online.provider); } catch (e) { }
  S.online.page = page || 1;""", "dosearch-save")

# 音源管理面板：默认徽标 + 设默认按钮
s = sub(s, """  const list = r.list || [];
  const rows = list.map(function (s) {
    const nm = String(s.name || '').replace(/\\.js$/i, '');
    return '<div class="item">'
      + '<div class="ico vi">' + I.wave + '</div>'
      + '<div class="txt">'
      + '<div class="t1">' + esc(nm) + ' <span class="sm muted">[' + (s.builtin ? '内置' : '自建') + ']</span>'""",
        """  const list = r.list || [];
  const defSrc = (function () { try { return localStorage.getItem('dlna_defaultprov') || ''; } catch (e) { return ''; } })();
  const rows = list.map(function (s) {
    const nm = String(s.name || '').replace(/\\.js$/i, '');
    return '<div class="item">'
      + '<div class="ico vi">' + I.wave + '</div>'
      + '<div class="txt">'
      + '<div class="t1">' + esc(nm) + ' <span class="sm muted">[' + (s.builtin ? '内置' : '自建') + ']</span>'
      + (nm === defSrc && s.enabled ? ' <span class="sm" style="color:#22e6ff">★默认</span>' : '')""", "srcmgr-badge")
s = sub(s, """      + '<div class="act">'
      + '<button class="iconbtn sm2 vi" title="' + (s.enabled ? '停用' : '启用')""",
        """      + '<div class="act">'
      + (s.enabled ? '<button class="iconbtn sm2 vi" title="设为默认" onclick="srcSetDefault(\\'' + esc(nm) + '\\')">' + I.star + '</button>' : '')
      + '<button class="iconbtn sm2 vi" title="' + (s.enabled ? '停用' : '启用')""", "srcmgr-starbtn")

# I.star 图标
s = sub(s, "const I = {",
        """const I = {
  star: '<svg class="iv" viewBox="0 0 24 24"><path d="M12 3.4l2.5 5.2 5.7.8-4.1 4 1 5.7-5.1-2.7-5.1 2.7 1-5.7-4.1-4 5.7-.8z"/></svg>',""",
        "I-star")

# srcSetDefault 函数（放在 srcInstallSheet 前）
s = sub(s, "function srcInstallSheet() {",
        """function srcSetDefault(nm) {
  try {
    localStorage.setItem('dlna_defaultprov', nm);
    localStorage.setItem('dlna_lastprov', nm);
  } catch (e) { }
  S.online.provider = nm;
  toast('默认音源：' + nm, 'ok');
  srcMgrSheet();
}

function srcInstallSheet() {""", "srcsetdefault")

# 音源下拉 change 即记住
s = sub(s, "  $('miniOpen').addEventListener('click', playerSheet);",
        """  $('miniOpen').addEventListener('click', playerSheet);
  $('onlineProvider').addEventListener('change', function () {
    S.online.provider = this.value;
    try { localStorage.setItem('dlna_lastprov', this.value); } catch (e) { }
  });""", "prov-change")

wr(p, s)
print("app.js: 全部补丁完成")

# ---------- 4. app.css 立体化 ----------
p = os.path.join(WWW, "app.css")
s = rd(p)
s += """

/* ================= v2.7 拟物增强：保持配色，增加立体感 ================= */
/* 通用按钮：上亮下暗 + 投影，按压下沉 */
.btn{
  background:linear-gradient(180deg,rgba(34,230,255,.17),rgba(34,230,255,.05) 46%,rgba(2,10,20,.35));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.16),inset 0 -2px 5px rgba(0,0,0,.42),
             0 4px 10px rgba(0,0,0,.5),0 1px 2px rgba(0,0,0,.55);
}
.btn:active{
  transform:translateY(1px) scale(.985);
  box-shadow:inset 0 2px 6px rgba(0,0,0,.5),0 1px 3px rgba(0,0,0,.4);
}
.btn.pri{
  background:linear-gradient(180deg,#6cf1ff 0%,var(--cy) 40%,#1fa9cb 76%,#2a7ea8 100%);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.55),inset 0 -3px 7px rgba(0,45,60,.45),
             0 5px 14px rgba(34,230,255,.38),0 2px 4px rgba(0,0,0,.5),
             0 0 34px rgba(160,113,255,.18);
}
.btn.pri::after{
  content:'';position:absolute;inset:1px 1px 52% 1px;border-radius:2px;pointer-events:none;
  background:linear-gradient(180deg,rgba(255,255,255,.35),rgba(255,255,255,0));
}
/* 图标按钮：微浮起 */
.iconbtn{
  background:linear-gradient(180deg,rgba(255,255,255,.055),rgba(0,0,0,.24));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.09),0 3px 7px rgba(0,0,0,.4);
}
.iconbtn:active{transform:translateY(1px);box-shadow:inset 0 2px 5px rgba(0,0,0,.45)}
/* 主播放键：凸起大按钮 */
.iconbtn.big{
  background:linear-gradient(180deg,#7df3ff 0%,var(--cy) 42%,#22a7c9 74%,#8a5fe0 100%);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.55),inset 0 -3px 7px rgba(0,45,60,.45),
             0 6px 16px rgba(34,230,255,.42),0 2px 4px rgba(0,0,0,.55);
}
.iconbtn.big::after{
  content:'';position:absolute;inset:2px 2px 52% 2px;border-radius:2px;pointer-events:none;
  background:linear-gradient(180deg,rgba(255,255,255,.4),rgba(255,255,255,0));
}
.iconbtn.big:active{transform:translateY(1px) scale(.97)}
/* 音量 ± 键：实体按键感 */
.vbtn{
  background:linear-gradient(180deg,rgba(34,230,255,.14),rgba(34,230,255,.04) 50%,rgba(0,0,0,.3));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.14),inset 0 -2px 5px rgba(0,0,0,.4),
             0 3px 8px rgba(0,0,0,.45);
}
.vbtn:active{transform:translateY(1px) scale(.96);box-shadow:inset 0 2px 6px rgba(0,0,0,.5)}
/* chips：浮起 + 选中态高光 */
.chip{
  background:linear-gradient(180deg,rgba(34,230,255,.10),rgba(34,230,255,.03) 55%,rgba(0,0,0,.22));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 3px 6px rgba(0,0,0,.35);
}
.chip:active{transform:translateY(1px)}
.chip.on{
  box-shadow:inset 0 1px 0 rgba(255,255,255,.3),inset 0 -2px 5px rgba(0,0,0,.3),
             0 4px 10px rgba(34,230,255,.35),0 0 24px rgba(160,113,255,.2);
}
.chip.on::after{
  content:'';position:absolute;inset:1px 1px 50% 1px;border-radius:2px;pointer-events:none;
  background:linear-gradient(180deg,rgba(255,255,255,.22),rgba(255,255,255,0));
}
.chip{position:relative;transition:transform .06s ease,box-shadow .15s}
/* 卡片 / 列表项微立体 */
.item{box-shadow:0 2px 8px rgba(0,0,0,.28),inset 0 1px 0 rgba(255,255,255,.04)}
/* 底栏：选中项凸起 */
.navbtn{transition:color .18s,transform .1s}
.navbtn.on{transform:translateY(-1px)}
"""
wr(p, s)
print("app.css: 立体化完成")

print("ALL DONE")
