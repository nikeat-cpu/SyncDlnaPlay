# -*- coding: utf-8 -*-
"""
v2.1 前端补丁
=============
1) 音量入口前置：设备卡片上直接给音量滑条；迷你播放器加音量键
2) 曲库管理重写：下载目录可改、音乐目录可加（SAF / SMB）
3) 歌词：播放面板内显示并随时间轴高亮
"""
import io
import os
import sys

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "assets", "www")


def load(n):
    return io.open(os.path.join(D, n), encoding="utf-8").read()


def save(n, s):
    io.open(os.path.join(D, n), "w", encoding="utf-8", newline="\n").write(s)


def rep(s, old, new, label):
    n = s.count(old)
    print(("OK  " if n == 1 else "!!  ") + "%-30s 命中 %d" % (label, n))
    if n != 1:
        return s
    return s.replace(old, new)


js = load("app.js")

# ---------------------------------------------------------------- 1. S 状态

js = rep(js, """  poll: null,
  timer: null,
  dlJobs: null,
};""", """  poll: null,
  timer: null,
  dlJobs: null,
  dlBusy: false,
  lyric: { key: '', lines: [], idx: -1, msg: '' },
};""", "S.lyric 初始化")

# ------------------------------------------------- 2. 设备卡片内嵌音量滑条

js = rep(js, """      <div class="act">
        ${d.has_volume !== false ? `<button class="iconbtn sm2" title="音量" onclick="devSheet(${i})">🔉</button>` : ''}
        <button class="iconbtn sm2" title="${d.selected ? '取消' : '选择'}" onclick="toggleDev(${i})">${d.selected ? '☑' : '☐'}</button>
      </div>
    </div>`;
  }).join('');""", """      <div class="act">
        ${d.has_volume !== false ? `<button class="iconbtn sm2" title="更多设置" onclick="devSheet(${i})">⚙</button>` : ''}
        <button class="iconbtn sm2" title="${d.selected ? '取消' : '选择'}" onclick="toggleDev(${i})">${d.selected ? '☑' : '☐'}</button>
      </div>
    </div>
    ${d.selected && d.has_volume !== false && on ? `
    <div class="vrow" style="margin:0;padding:0 12px 10px 44px">
      <span>🔉</span>
      <input type="range" min="0" max="100" value="${vol === '' ? 50 : vol}"
             oninput="devVolLive(${i},this.value)" onchange="devVolSet(${i},this.value)">
      <b id="dvol${i}">${vol === '' ? 50 : vol}</b>
    </div>` : ''}`;
  }).join('');""", "设备卡片音量滑条")

# ------------------------------- 3. devVolLive / devVolSet（跟在 setVol 后）

js = rep(js, """async function setDelay(ms) {""", """/** 设备列表上的音量滑条：拖动只改数字，松手才发指令，避免把设备刷爆 */
function devVolLive(i, v) { const el = $('dvol' + i); if (el) el.textContent = v; }
async function devVolSet(i, v) {
  const d = devices()[i];
  if (!d) return;
  buzz();
  const n = parseInt(v, 10) || 0;
  try {
    await apiPost('/api/volume', { volume: n, udns: [d.udn] });
    d.volume = n;
  } catch (e) { toast('音量设置失败：' + e.message, 'err'); }
}

async function setDelay(ms) {""", "devVolLive/devVolSet")

# --------------------------------------------- 4. 音量面板（迷你播放器入口）

js = rep(js, """function seekLive(v) { const el = $('npPos'); if (el) el.textContent = fmt(v); }""",
"""function seekLive(v) { const el = $('npPos'); if (el) el.textContent = fmt(v); }

/** 音量面板：音响输出调设备音量，本机输出调手机媒体音量 */
function volumeSheet() {
  if (S.out === 'phone') {
    const cur = Math.round((audio.volume == null ? 1 : audio.volume) * 100);
    openSheet('音量 · 手机本机', `
      <div class="vrow">
        <span>🔉</span>
        <input type="range" min="0" max="100" value="${cur}" oninput="phoneVol(this.value)">
        <b id="volNum">${cur}</b>
      </div>
      <div class="sm muted" style="margin-top:10px">这是手机自己的媒体音量，只影响「手机本机」播放。</div>`);
    return;
  }
  const sel = selectedDevices();
  if (!sel.length) { toast('先选一台音响', 'err'); return; }
  const cur = avgVol();
  openSheet(sel.length === 1 ? ('音量 · ' + (sel[0].name || '音响')) : ('音量 · ' + sel.length + ' 台同步'), `
    <div class="vrow">
      <span>🔉</span>
      <input type="range" min="0" max="100" value="${cur}" oninput="volLive(this.value)" onchange="volAll(this.value)">
      <b id="volNum">${cur}</b>
    </div>
    <div class="sm muted" style="margin-top:10px">松手后生效。同步播放时会一起设置所有已选音响。</div>
    <div class="sec-title">快速调整</div>
    <div class="chips">
      ${[0, 20, 40, 60, 80, 100].map(v => `<div class="chip" onclick="volAll(${v});closeSheet()">${v}</div>`).join('')}
    </div>`);
}
function phoneVol(v) {
  const n = parseInt(v, 10) || 0;
  try { audio.volume = Math.min(1, Math.max(0, n / 100)); } catch (e) { }
  const el = $('volNum'); if (el) el.textContent = v;
}""", "volumeSheet/phoneVol")

# --------------------------------------------------------- 5. 曲库管理重写

start = js.index("async function musicSourcesSheet() {")
end = js.index("/* ---- 运行日志", start)
NEW_SRC = r"""async function musicSourcesSheet() {
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
        <div class="chip" onclick="AB&&AB.pickMusicFolder&&AB.pickMusicFolder()">📁 添加本机目录</div>
        <div class="chip" onclick="srcAdd('smb')">🖧 添加网络共享</div>
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
  const re = /\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g;
  text.split(/\r?\n/).forEach(function (line) {
    re.lastIndex = 0;
    const times = [];
    let m;
    while ((m = re.exec(line)) !== null) {
      const min = parseInt(m[1], 10), sec = parseInt(m[2], 10);
      let frac = 0;
      if (m[3]) frac = parseInt(m[3], 10) / (m[3].length === 3 ? 1000 : 100);
      times.push(min * 60 + sec + frac);
    }
    if (!times.length) return;
    const content = line.replace(re, '').trim();
    if (!content) return;
    times.forEach(function (tt) { out.push({ t: tt, text: content }); });
  });
  out.sort(function (a, b) { return a.t - b.t; });
  return out;
}

function trackKeyOf(t) {
  if (!t) return '';
  return [t.source || 'local', t.provider || '', t.id || '', t.title || ''].join('|');
}

/** 取歌词：在线曲目问插件，本地曲目读同目录 .lrc */
async function loadLyric(t) {
  const box = $('lyricBox');
  if (!box) return;
  const key = trackKeyOf(t);
  if (!key || S.lyric.key === key) { renderLyric(); return; }
  S.lyric = { key: key, lines: [], idx: -1, msg: '加载歌词…' };
  renderLyric();
  let lrc = '';
  try {
    if (t.source === 'online' && window.PluginHost && t.provider && t.id) {
      const r = await window.PluginHost.lyric({ provider: t.provider, id: t.id });
      lrc = (r && r.lrc) || '';
    }
    if (!lrc && t.id) {
      const r = await api('/api/lyric?id=' + encodeURIComponent(t.id), { _timeout: 12000 });
      lrc = (r && r.lrc) || '';
    }
  } catch (e) { lrc = ''; }
  if (S.lyric.key !== key) return;      // 这期间已经切歌了
  const lines = parseLrc(lrc);
  S.lyric = { key: key, lines: lines, idx: -1, msg: lines.length ? '' : '这首歌没有歌词' };
  renderLyric();
}

function renderLyric() {
  const box = $('lyricBox');
  if (!box) return;
  const L = S.lyric;
  if (!L.lines.length) {
    box.innerHTML = '<div class="empty sm" style="padding:18px">' + esc(L.msg || '暂无歌词') + '</div>';
    return;
  }
  box.innerHTML = L.lines.map(function (l, i) {
    return '<div class="lrc-line' + (i === L.idx ? ' on' : '') + '" onclick="seekToTime(' + l.t + ')">' + esc(l.text) + '</div>';
  }).join('');
  const on = box.querySelector('.lrc-line.on');
  if (on && on.scrollIntoView) {
    try { on.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) { }
  }
}

/** 由播放进度驱动高亮；只在行变化时重绘，避免拖慢主循环 */
function updateLyricProgress(pos) {
  const L = S.lyric;
  if (!L.lines.length) return;
  let idx = -1;
  for (let i = 0; i < L.lines.length; i++) {
    if (L.lines[i].t <= pos + 0.25) idx = i; else break;
  }
  if (idx !== L.idx) { L.idx = idx; renderLyric(); }
}

function seekToTime(sec) {
  if (S.out === 'phone') { try { audio.currentTime = sec; } catch (e) { } return; }
  apiPost('/api/seek', { position: Math.floor(sec) }).catch(function () { });
}

"""
js = js[:start] + NEW_SRC + js[end:]
print("OK  musicSourcesSheet + 歌词模块 已整段替换")

# ------------------------------------------------- 6. tick / timeupdate 驱动

js = rep(js, """    renderMini();
    renderQueue();
  } catch (e) {""", """    renderMini();
    renderQueue();
    updateLyricProgress(nowPlaying().pos);
  } catch (e) {""", "tick 驱动歌词")

js = rep(js, """audio.addEventListener('timeupdate', () => { if (S.out === 'phone') renderMini(); });""",
"""audio.addEventListener('timeupdate', () => {
  if (S.out === 'phone') { renderMini(); updateLyricProgress(audio.currentTime || 0); }
});""", "本机播放驱动歌词")

# ------------------------------------------------------- 7. 播放面板加歌词区

js = rep(js, """    <div class="sec-title">播放模式</div>""",
"""    <div class="sec-title">歌词</div>
    <div class="lrc-box" id="lyricBox"><div class="empty sm" style="padding:18px">加载中…</div></div>

    <div class="sec-title">播放模式</div>""", "播放面板歌词区")

js = rep(js, """    <div class="sm muted" style="margin-top:10px">切到「手机本机」后，声音从手机的扬声器/耳机出，音响那边会自动停下。</div>
  `);
}""", """    <div class="sm muted" style="margin-top:10px">切到「手机本机」后，声音从手机的扬声器/耳机出，音响那边会自动停下。</div>
  `);
  setTimeout(function () { loadLyric(n.t); renderLyric(); }, 0);
}""", "打开面板即加载歌词")

# --------------------------------------------------------- 8. 迷你播放器绑定

js = rep(js, """  $('miniPlay').addEventListener('click', () => ctl(nowPlaying().playing ? 'pause' : 'play'));""",
"""  $('miniVol').addEventListener('click', volumeSheet);
  $('miniPlay').addEventListener('click', () => ctl(nowPlaying().playing ? 'pause' : 'play'));""", "迷你播放器音量键")

save("app.js", js)

# ---------------------------------------------------------------- index.html

html = load("index.html")
html = rep(html, """    <div class="mini-ctl">
      <button class="iconbtn" id="miniPrev">⏮</button>""",
"""    <div class="mini-ctl">
      <button class="iconbtn" id="miniVol" title="音量">🔉</button>
      <button class="iconbtn" id="miniPrev">⏮</button>""", "迷你播放器音量按钮")
save("index.html", html)

# --------------------------------------------------------------------- app.css

css = load("app.css")
if ".lrc-box" not in css:
    css += """
/* ---------------- 歌词 ---------------- */
.lrc-box{
  margin-top:8px;max-height:38vh;overflow-y:auto;
  background:var(--bg2);border:1px solid var(--line);border-radius:var(--r);
  padding:10px 4px;scroll-behavior:smooth;
}
.lrc-line{
  padding:7px 12px;text-align:center;font-size:13.5px;line-height:1.5;
  color:var(--tx3);transition:color .2s,transform .2s;
}
.lrc-line.on{color:var(--acc);font-size:15px;font-weight:600;transform:scale(1.03)}
"""
    save("app.css", css)
    print("OK  app.css 已追加歌词样式")
else:
    print("--  app.css 已含歌词样式，跳过")

# --------------------------------------------------------------------- 复核

js2 = load("app.js")
checks = {
    "devVolSet": "function devVolSet(",
    "volumeSheet": "function volumeSheet(",
    "phoneVol": "function phoneVol(",
    "getStorageInfo 用": "AB.getStorageInfo",
    "pickDownloadFolder 用": "pickDownloadFolder",
    "pickMusicFolder 用": "AB.pickMusicFolder",
    "getMusicDirs 用": "AB.getMusicDirs",
    "loadLyric": "async function loadLyric(",
    "updateLyricProgress": "function updateLyricProgress(",
    "lrc-box": "lrc-box",
    "miniVol 绑定": "$('miniVol').addEventListener",
    "回调 __onStorageChanged": "window.__onStorageChanged",
    "残留旧 dir 读取": "AB.getDownloadsDir)",
}
print()
for k, v in checks.items():
    print("%-26s %s" % (k, v in js2))
print("app.js 行数:", len(js2.splitlines()))
sys.exit(0)
