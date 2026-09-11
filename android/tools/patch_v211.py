# -*- coding: utf-8 -*-
"""v2.11：双击歌词进入沉浸模式 —— 歌词全屏，底部保留播放控制 + 音量控制。
- 单击歌词行仍是跳转（延迟 300ms 执行）；350ms 内第二击 = 双击 → 进沉浸（并取消排队的跳转）
- 沉浸层：全屏渐变背景 + 大号歌词自动滚动高亮；顶部歌名/歌手 + 退出按钮
- 底部：上一曲 / 播放暂停 / 下一曲 + 音量滑条（手机=media 音量，音响=设备平均音量，复用 volCommit）
- 退出：✕ 按钮、双击沉浸层任意处
"""
import io

JS = "app/assets/www/app.js"
with io.open(JS, encoding="utf-8") as f:
    s = f.read()

# 1) 歌词行点击改为 lrcLineTap（支持双击进沉浸）
old = """  box.innerHTML = L.lines.map(function (l, i) {
    return '<div class="lrc-line' + (i === L.idx ? ' on' : '') + '" onclick="seekToTime(' + l.t + ')">' + esc(l.text) + '</div>';
  }).join('');
  const on = box.querySelector('.lrc-line.on');
  if (on && on.scrollIntoView) {
    try { on.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) { }
  }
}"""
new = """  box.innerHTML = L.lines.map(function (l, i) {
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
    + '<button class="btn sm" onclick="exitImmersive()">✕ 退出</button></div>'
    + '<div class="imm-lrc lrc-box" id="immLrc"></div>'
    + '<div class="imm-ctl">'
    + '<div class="imm-btns">'
    + '<button class="btn" onclick="ctl(\\'prev\\')">⏮</button>'
    + '<button class="btn pri" id="immPlay" style="min-width:76px" onclick="ctl(nowPlaying().playing ? \\'pause\\' : \\'play\\')">⏸</button>'
    + '<button class="btn" onclick="ctl(\\'next\\')">⏭</button>'
    + '</div>'
    + '<div class="imm-vol"><span class="sm muted">🔊</span>'
    + '<input id="immVol" type="range" min="0" max="100" oninput="immVolLive(this.value)" onchange="volCommit(this.value)">'
    + '<span id="immVolVal" class="sm" style="min-width:36px;text-align:right"></span>'
    + '</div></div>';
  d.addEventListener('dblclick', exitImmersive);
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
  const el = $('imm');
  if (el) el.style.display = 'none';
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
}"""
assert s.count(old) == 1, "renderLyric anchor"
s = s.replace(old, new)

# 2) 300ms 定时器里同步沉浸层（播放键图标、音量数字实时跟手）
old = """  S.lyrTimer = setInterval(function () {
    if (S.lyric.lines.length) updateLyricProgress(nowPlaying().pos);
    if (S.tab === 'now') refreshNow();
  }, 300);"""
new = """  S.lyrTimer = setInterval(function () {
    if (S.lyric.lines.length) updateLyricProgress(nowPlaying().pos);
    if (S.tab === 'now') refreshNow();
    if (S._imm) immSync();
  }, 300);"""
assert s.count(old) == 1, "timer anchor"
s = s.replace(old, new)

with io.open(JS, "w", encoding="utf-8", newline="") as f:
    f.write(s)

# 3) CSS：沉浸层样式（沿用现有配色变量）
CSS = "app/assets/www/app.css"
with io.open(CSS, encoding="utf-8") as f:
    c = f.read()
c += """
/* ================= v2.11 沉浸歌词模式 ================= */
.imm{position:fixed;inset:0;z-index:90;display:none;flex-direction:column;
  padding:18px 16px calc(16px + env(safe-area-inset-bottom));
  background:linear-gradient(180deg,#05070f 0%,#0a1224 55%,#05070f 100%)}
.imm::before{content:'';position:absolute;inset:0;pointer-events:none;
  background:
    radial-gradient(60% 40% at 20% 0%,rgba(34,230,255,.10),transparent 70%),
    radial-gradient(50% 35% at 85% 100%,rgba(255,45,146,.08),transparent 70%)}
.imm>*{position:relative}
.imm-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.imm-meta>div:first-child{font-size:19px;font-weight:700;color:var(--tx);
  text-shadow:0 0 14px rgba(34,230,255,.35);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:70vw}
.imm-lrc{flex:1;overflow-y:auto;margin:12px 0;
  -webkit-mask-image:linear-gradient(180deg,transparent 0,#000 10%,#000 90%,transparent 100%);
  mask-image:linear-gradient(180deg,transparent 0,#000 10%,#000 90%,transparent 100%)}
.imm-lrc .lrc-line{font-size:21px;line-height:1.55;padding:10px 4px;opacity:.36;
  transition:opacity .25s,font-size .25s,color .25s}
.imm-lrc .lrc-line.on{font-size:26px;opacity:1;color:var(--cy);
  text-shadow:0 0 20px rgba(34,230,255,.55)}
.imm-ctl{border-top:1px solid rgba(34,230,255,.18);padding-top:12px;
  display:flex;flex-direction:column;gap:12px}
.imm-btns{display:flex;justify-content:center;gap:26px}
.imm-btns .btn{min-width:64px;font-size:17px}
.imm-vol{display:flex;align-items:center;gap:10px}
.imm-vol input[type=range]{flex:1}
"""
with io.open(CSS, "w", encoding="utf-8", newline="") as f:
    f.write(c)
print("patch ok")
