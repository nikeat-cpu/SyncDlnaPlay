# -*- coding: utf-8 -*-
"""v2.9 补丁：
1) 歌词快慢手动校准：±500ms，按钮「快 / 慢」，持久化 localStorage
2) 正在播放页瘦身：歌词区变矮、删边听边下载说明、手机说明缩成一行、删重复播放控制键
"""
import io

WWW = "app/assets/www/"

def patch(path, old, new):
    with io.open(path, encoding="utf-8") as f:
        s = f.read()
    assert old in s, "ANCHOR NOT FOUND in %s: %r" % (path, old[:80])
    assert s.count(old) == 1, "ambiguous anchor in %s" % path
    s = s.replace(old, new)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    print("ok:", old.strip().splitlines()[0][:56])

# ---------- 1. 歌词偏移：状态 + 进度应用 ----------
patch(WWW + "app.js",
      """/** 由播放进度驱动高亮；只在行变化时重绘，避免拖慢主循环 */
function updateLyricProgress(pos) {
  const L = S.lyric;
  if (!L.lines.length) return;
  let idx = -1;
  for (let i = 0; i < L.lines.length; i++) {
    if (L.lines[i].t <= pos + 0.25) idx = i; else break;
  }
  if (idx !== L.idx) { L.idx = idx; renderLyric(); }
}""",
      """/* ---- 歌词快慢校准（v2.9）：投音响有传输延时且因文件而异，让用户手动校 ----
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
}""")

# ---------- 2. nowHTML：校准行 + 删播放控制键 ----------
patch(WWW + "app.js",
      """      <div class="lrc-box np-lrc" id="lyricBox" style="display:none"><div class="empty sm" style="padding:18px">加载歌词…</div></div>
    </div>""",
      """      <div class="lrc-box np-lrc" id="lyricBox" style="display:none"><div class="empty sm" style="padding:18px">加载歌词…</div></div>
    </div>
    <div class="lrc-off">
      <span class="sm muted">歌词</span>
      <button class="btn sm" onclick="lyricOffShift(-500)">慢 0.5s</button>
      <span id="lrcOffVal" class="sm" style="color:var(--cy);min-width:70px;text-align:center">${lyricOffLabel()}</span>
      <button class="btn sm" onclick="lyricOffShift(500)">快 0.5s</button>
    </div>""")

patch(WWW + "app.js",
      """    <div class="np-ctl">
      <button class="iconbtn" onclick="ctl('prev')">⏮</button>
      <button class="iconbtn big" id="npPlay" onclick="ctl('${n.playing ? 'pause' : 'play'}')">${n.playing ? '⏸' : '▶'}</button>
      <button class="iconbtn" onclick="ctl('next')">⏭</button>
    </div>

    <div class="sec-title">输出方式</div>""",
      """    <div class="sec-title">输出方式</div>""")

# ---------- 3. 删边听边下载说明 + 缩短手机说明 ----------
patch(WWW + "app.js",
      """    <div class="sm muted" style="margin-top:6px">开启后，正在播放的在线歌曲会自动加入下载队列，存到下载目录（本地歌曲无需下载）。</div>
    <div class="sm muted" style="margin-top:10px">切到「手机本机」后，声音从手机的扬声器/耳机出，音响那边会自动停下。</div>""",
      """    <div class="sm muted" style="margin-top:8px">切「手机本机」＝声音从手机出，音响自动停。</div>""")

# ---------- 4. CSS：歌词区变矮 + 校准行 ----------
with io.open(WWW + "app.css", encoding="utf-8") as f:
    css = f.read()
css += """
/* ===== v2.9 歌词区变矮 + 快慢校准行 ===== */
.np-stage{aspect-ratio:auto;height:192px;margin:8px auto 10px}
.np-stage .np-art{margin:0 auto;max-width:none;width:auto;height:100%}
.lrc-off{display:flex;align-items:center;justify-content:center;gap:10px;margin:0 auto 12px}
.lrc-off .btn{padding:3px 12px;font-size:11.5px}
"""
with io.open(WWW + "app.css", "w", encoding="utf-8", newline="") as f:
    f.write(css)
print("ok: app.css appended")

print("ALL DONE")
