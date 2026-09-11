# -*- coding: utf-8 -*-
"""v2.4 音量入口收敛：全 App 只保留「音量面板」一个调节处，并在面板内加 − / + 精调。

删除的调节处：
  1. 设备卡片内联滑条        devVolLive / devVolSet / #dvol{i}
  2. 设备详情弹层 devSheet    setVolLive / setVol
  3. 播放面板 playerSheet     内联滑条 + #volNum2

保留的唯一调节处：volumeSheet()（即用户截图那个面板），新增：
  · #volDec / #volInc 加减按钮，单击 ±1，长按 450ms 后连续调节（100ms/步）
  · 停手 260ms 后再下发，避免长按时把音响刷爆
入口（只开面板、不是第二处调节）：设备卡片 🔉 按钮 + 迷你播放器 🔉 按钮。
"""
import io
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
JS = os.path.join(ROOT, "app", "assets", "www", "app.js")
CSS = os.path.join(ROOT, "app", "assets", "www", "app.css")


def sub(path, old, new, tag):
    s = io.open(path, encoding="utf-8").read()
    n = s.count(old)
    if n == 0 and new in s:
        print("  [SKIP] %s（已应用过）" % tag)
        return
    assert n == 1, "[%s] 命中 %d 次（应为 1）" % (tag, n)
    io.open(path, "w", encoding="utf-8", newline="\n").write(s.replace(old, new, 1))
    print("  [OK] " + tag)


J = io.open(JS, encoding="utf-8").read()

# ---------------------------------------------------------------- 1. 设备卡片
sub(JS, """    const vol = (d.volume == null ? '' : d.volume);
    const sub = [d.ip, stTxt].filter(Boolean).join(' · ') + (d.title ? (' · ' + d.title) : '');""",
    """    const sub = [d.ip, stTxt].filter(Boolean).join(' · ') + (d.title ? (' · ' + d.title) : '');""",
    "设备卡片：移除未用的 vol 变量")

sub(JS, """      <div class="act">
        ${d.has_volume !== false ? `<button class="iconbtn sm2" title="更多设置" onclick="devSheet(${i})">\u2699</button>` : ''}
        <button class="iconbtn sm2" title="${d.selected ? '\u53d6\u6d88' : '\u9009\u62e9'}" onclick="toggleDev(${i})">${d.selected ? '\u2611' : '\u2610'}</button>
      </div>
    </div>
    ${d.selected && d.has_volume !== false && on ? `
    <div class="vrow" style="margin:0;padding:0 12px 10px 44px">
      <span>\U0001f509</span>
      <input type="range" min="0" max="100" value="${vol === '' ? 50 : vol}"
             oninput="devVolLive(${i},this.value)" onchange="devVolSet(${i},this.value)">
      <b id="dvol${i}">${vol === '' ? 50 : vol}</b>
    </div>` : ''}`;""",
    """      <div class="act">
        ${d.has_volume !== false ? `<button class="iconbtn sm2" title="\u97f3\u91cf" onclick="volumeSheet(${i})">\U0001f509</button>` : ''}
        ${d.has_volume !== false ? `<button class="iconbtn sm2" title="\u66f4\u591a\u8bbe\u7f6e" onclick="devSheet(${i})">\u2699</button>` : ''}
        <button class="iconbtn sm2" title="${d.selected ? '\u53d6\u6d88' : '\u9009\u62e9'}" onclick="toggleDev(${i})">${d.selected ? '\u2611' : '\u2610'}</button>
      </div>
    </div>`;""",
    "设备卡片：内联滑条 → 音量入口按钮")

# ------------------------------------------------------- 2. devSheet 去掉滑条
sub(JS, """  const vol = d.volume == null ? 50 : Math.round(d.volume);
  const delay = d.delay_ms || 0;
  openSheet(esc(d.name || '\u8bbe\u5907'), `
    <div class="vrow">
      <span>\U0001f509</span>
      <input type="range" min="0" max="100" value="${vol}" oninput="setVolLive(this.value)" onchange="setVol(this.value)">
      <b id="volNum">${vol}</b>
    </div>
    <div class="sm muted" style="margin-top:6px">\u62d6\u52a8\u8c03\u6574\u97f3\u91cf\uff0c\u677e\u624b\u751f\u6548</div>

    <div class="sec-title">\u591a\u623f\u95f4\u540c\u6b65\u5fae\u8c03</div>""",
    """  const delay = d.delay_ms || 0;
  openSheet(esc(d.name || '\u8bbe\u5907'), `
    <div class="sec-title">\u591a\u623f\u95f4\u540c\u6b65\u5fae\u8c03</div>""",
    "设备详情弹层：删除音量滑条")

sub(JS, """async function toggleFromSheet(i) { await toggleDev(i); closeSheet(); devSheet(i); }
async function setVolLive(v) { const n = $('volNum'); if (n) n.textContent = v; }
async function setVol(v) {
  const d = devices()[S._devIdx]; if (!d) return;
  try { await apiPost('/api/volume', { volume: parseInt(v, 10), udns: [d.udn] }); toast('\u97f3\u91cf ' + v, 'ok'); }
  catch (e) { toast('\u8bbe\u7f6e\u5931\u8d25\uff1a' + e.message, 'err'); }
}
/** \u8bbe\u5907\u5217\u8868\u4e0a\u7684\u97f3\u91cf\u6ed1\u6761\uff1a\u62d6\u52a8\u53ea\u6539\u6570\u5b57\uff0c\u677e\u624b\u624d\u53d1\u6307\u4ee4\uff0c\u907f\u514d\u628a\u8bbe\u5907\u5237\u7206 */
function devVolLive(i, v) { const el = $('dvol' + i); if (el) el.textContent = v; }
async function devVolSet(i, v) {
  const d = devices()[i];
  if (!d) return;
  buzz();
  const n = parseInt(v, 10) || 0;
  try {
    await apiPost('/api/volume', { volume: n, udns: [d.udn] });
    d.volume = n;
  } catch (e) { toast('\u97f3\u91cf\u8bbe\u7f6e\u5931\u8d25\uff1a' + e.message, 'err'); }
}""",
    """async function toggleFromSheet(i) { await toggleDev(i); closeSheet(); devSheet(i); }""",
    "移除 setVolLive / setVol / devVolLive / devVolSet")

# ------------------------------------------- 3. playerSheet 去掉音量滑条
sub(JS, """    <div class="sec-title">\u8f93\u51fa\u65b9\u5f0f</div>
    <div class="chips">
      <div class="chip ${S.out === 'dlna' ? 'on' : ''}" onclick="setOut('dlna');closeSheet();playerSheet()">\U0001f50a \u97f3\u54cd\u64ad\u653e</div>
      <div class="chip ${S.out === 'phone' ? 'on' : ''}" onclick="setOut('phone');closeSheet();playerSheet()">\U0001f4f1 \u624b\u673a\u672c\u673a</div>
    </div>

    ${S.out === 'dlna' ? `
      <div class="sec-title">\u97f3\u91cf</div>
      <div class="vrow">
        <span>\U0001f509</span>
        <input type="range" min="0" max="100" value="${avgVol()}" oninput="volLive(this.value)" onchange="volAll(this.value)">
        <b id="volNum2">${avgVol()}</b>
      </div>` : `
      <div class="sec-title">\u97f3\u91cf</div>
      <div class="vrow">
        <span>\U0001f509</span>
        <input type="range" min="0" max="100" value="${Math.round((audio.volume || 1) * 100)}" onchange="audio.volume=this.value/100">
        <b id="volNum2">${Math.round((audio.volume || 1) * 100)}</b>
      </div>`}

    <div class="sec-title">\u6b4c\u8bcd</div>""",
    """    <div class="sec-title">\u8f93\u51fa\u65b9\u5f0f</div>
    <div class="chips">
      <div class="chip ${S.out === 'dlna' ? 'on' : ''}" onclick="setOut('dlna');closeSheet();playerSheet()">\U0001f50a \u97f3\u54cd\u64ad\u653e</div>
      <div class="chip ${S.out === 'phone' ? 'on' : ''}" onclick="setOut('phone');closeSheet();playerSheet()">\U0001f4f1 \u624b\u673a\u672c\u673a</div>
    </div>

    <div class="sec-title">\u6b4c\u8bcd</div>""",
    "播放面板：删除音量滑条")

# ------------------------------------------- 4. 重写音量面板（唯一的调节处）
sub(JS, """function avgVol() {
  const sel = selectedDevices().filter(d => d.volume != null);
  if (!sel.length) return 50;
  return Math.round(sel.reduce((a, d) => a + d.volume, 0) / sel.length);
}""",
    """function avgVol(list) {
  const arr = ((list && list.length) ? list : selectedDevices()).filter(d => d.volume != null);
  if (!arr.length) return 50;
  return Math.round(arr.reduce((a, d) => a + d.volume, 0) / arr.length);
}""",
    "avgVol 支持指定设备列表")

sub(JS, """/** \u97f3\u91cf\u9762\u677f\uff1a\u97f3\u54cd\u8f93\u51fa\u8c03\u8bbe\u5907\u97f3\u91cf\uff0c\u672c\u673a\u8f93\u51fa\u8c03\u624b\u673a\u5a92\u4f53\u97f3\u91cf */
function volumeSheet() {
  if (S.out === 'phone') {
    const cur = Math.round((audio.volume == null ? 1 : audio.volume) * 100);
    openSheet('\u97f3\u91cf \u00b7 \u624b\u673a\u672c\u673a', `
      <div class="vrow">
        <span>\U0001f509</span>
        <input type="range" min="0" max="100" value="${cur}" oninput="phoneVol(this.value)">
        <b id="volNum">${cur}</b>
      </div>
      <div class="sm muted" style="margin-top:10px">\u8fd9\u662f\u624b\u673a\u81ea\u5df1\u7684\u5a92\u4f53\u97f3\u91cf\uff0c\u53ea\u5f71\u54cd\u300c\u624b\u673a\u672c\u673a\u300d\u64ad\u653e\u3002</div>`);
    return;
  }
  const sel = selectedDevices();
  if (!sel.length) { toast('\u5148\u9009\u4e00\u53f0\u97f3\u54cd', 'err'); return; }
  const cur = avgVol();
  openSheet(sel.length === 1 ? ('\u97f3\u91cf \u00b7 ' + (sel[0].name || '\u97f3\u54cd')) : ('\u97f3\u91cf \u00b7 ' + sel.length + ' \u53f0\u540c\u6b65'), `
    <div class="sec-title">\u97f3\u91cf</div>
    <div class="vrow">
      <span>\U0001f509</span>
      <input type="range" min="0" max="100" value="${cur}" oninput="volLive(this.value)" onchange="volAll(this.value)">
      <b id="volNum">${cur}</b>
    </div>
    <div class="sm muted" style="margin-top:10px">\u62d6\u52a8\u8c03\u6574\u97f3\u54cd\u97f3\u91cf\uff0c\u677e\u624b\u540e\u751f\u6548\u3002\u540c\u6b65\u64ad\u653e\u65f6\u4f1a\u4e00\u8d77\u8bbe\u7f6e\u6240\u6709\u5df2\u9009\u97f3\u54cd\u3002</div>
    <div class="sec-title">\u5feb\u901f\u8c03\u6574</div>
    <div class="chips">
      ${[0, 20, 40, 60, 80, 100].map(v => `<div class="chip" onclick="volAll(${v});closeSheet()">${v}</div>`).join('')}
    </div>`);
}
function phoneVol(v) {
  const n = parseInt(v, 10) || 0;
  try { audio.volume = Math.min(1, Math.max(0, n / 100)); } catch (e) { }
  const el = $('volNum'); if (el) el.textContent = v;
}""",
    """/** \u97f3\u91cf\u9762\u677f\uff1a\u5168 App \u552f\u4e00\u7684\u97f3\u91cf\u8c03\u8282\u5904\u3002
    \u4f20\u8bbe\u5907\u4e0b\u6807 i \u53ea\u8c03\u90a3\u4e00\u53f0\uff1b\u4e0d\u4f20\u5219\u8c03\u6240\u6709\u5df2\u9009\u97f3\u54cd\u3002
    \u97f3\u54cd\u8f93\u51fa \u2192 /api/volume\uff1b\u624b\u673a\u672c\u673a \u2192 audio.volume\u3002 */
function volumeSheet(i) {
  // addEventListener 会把 Event 当第一个参数传进来，必须挡掉
  if (typeof i !== 'number' || !isFinite(i) || i < 0) i = null;
  S._volIdx = (i != null && devices()[i]) ? i : null;
  S._volDirty = false;
  const phone = (S.out === 'phone' && S._volIdx == null);
  S._volPhone = phone;
  if (phone) {
    const pc = Math.round((audio.volume == null ? 1 : audio.volume) * 100);
    openSheet('\u97f3\u91cf \u00b7 \u624b\u673a\u672c\u673a',
      volBody(pc, '\u8fd9\u662f\u624b\u673a\u81ea\u5df1\u7684\u5a92\u4f53\u97f3\u91cf\uff0c\u53ea\u5f71\u54cd\u300c\u624b\u673a\u672c\u673a\u300d\u64ad\u653e\u3002'));
    return;
  }
  const list = volTargets();
  if (!list.length) { toast('\u5148\u9009\u4e00\u53f0\u97f3\u54cd', 'err'); return; }
  const cur = avgVol(list);
  const name = list.length === 1 ? (list[0].name || '\u97f3\u54cd') : (list.length + ' \u53f0\u540c\u6b65');
  openSheet('\u97f3\u91cf \u00b7 ' + name,
    volBody(cur, '\u62d6\u52a8\u6ed1\u6761\u6216\u70b9 \u2212 / + \u8c03\u8282\u97f3\u91cf\uff0c\u957f\u6309 \u2212 / + \u53ef\u8fde\u7eed\u8c03\u8282\u3002' +
      (list.length > 1 ? '\u540c\u6b65\u64ad\u653e\u65f6\u4f1a\u4e00\u8d77\u8bbe\u7f6e\u6240\u6709\u5df2\u9009\u97f3\u54cd\u3002' : '')));
}
function volTargets() {
  if (S._volIdx != null) { const d = devices()[S._volIdx]; return d ? [d] : []; }
  return selectedDevices();
}
function volBody(cur, hint) {
  const quick = [0, 20, 40, 60, 80, 100];
  return `
    <div class="sec-title">\u97f3\u91cf</div>
    <div class="vrow">
      <button class="vbtn" id="volDec" onpointerdown="volHold(-1,event)" onpointerup="volAutoStop()"
              onpointerleave="volAutoStop()" onpointercancel="volAutoStop()"
              oncontextmenu="return false">\u2212</button>
      <input id="volRange" type="range" min="0" max="100" value="${cur}"
             oninput="volLive(this.value)" onchange="volCommit(this.value)">
      <button class="vbtn" id="volInc" onpointerdown="volHold(1,event)" onpointerup="volAutoStop()"
              onpointerleave="volAutoStop()" onpointercancel="volAutoStop()"
              oncontextmenu="return false">+</button>
      <b id="volNum">${cur}</b>
    </div>
    <div class="sm muted" style="margin-top:10px">${hint}</div>
    <div class="sec-title">\u5feb\u901f\u8c03\u6574</div>
    <div class="chips">
      ${quick.map(v => `<div class="chip" onclick="volCommit(${v})">${v}</div>`).join('')}
    </div>`;
}""",
    "重写 volumeSheet（加 − / + 与 volBody）")

sub(JS, """function volLive(v) {
  // \u64ad\u653e\u9762\u677f\u7528 volNum2\uff0c\u72ec\u7acb\u97f3\u91cf\u9762\u677f\u7528 volNum\uff1b\u4e24\u4e2a\u9762\u677f\u4e0d\u4f1a\u540c\u65f6\u5b58\u5728\uff0c\u8c01\u5728\u5c31\u66f4\u65b0\u8c01
  ['volNum2', 'volNum'].forEach(function (id) {
    const el = $(id); if (el) el.textContent = v;
  });
}
async function volAll(v) {
  v = parseInt(v, 10) || 0;
  try {
    const r = await apiPost('/api/volume', { volume: v });
    if (r.ok === false) throw new Error(r.result || '\u5931\u8d25');
    await tick(true);
  } catch (e) { toast('\u97f3\u91cf\u8bbe\u7f6e\u5931\u8d25\uff1a' + e.message, 'err'); }
}""",
    """/** \u62d6\u52a8\u6ed1\u6761\uff1a\u53ea\u66f4\u65b0\u6570\u5b57\uff0c\u677e\u624b\u7531 onchange \u2192 volCommit \u4e0b\u53d1 */
function volLive(v) {
  const el = $('volNum'); if (el) el.textContent = v;
}
/** \u5199\u5165\u6570\u5b57\u5e76\u540c\u6b65\u6ed1\u6761\u4f4d\u7f6e\uff0c\u8fd4\u56de\u88c1\u526a\u540e\u7684\u503c */
function volSetNum(v) {
  const n = Math.max(0, Math.min(100, parseInt(v, 10) || 0));
  const el = $('volNum'); if (el) el.textContent = n;
  const r = $('volRange'); if (r && r.value !== String(n)) r.value = n;
  return n;
}
/** \u2212 / + \u6309\u94ae\uff1a\u5355\u51fb\u4e00\u6b65\uff1b\u957f\u6309 450ms \u540e\u6bcf 100ms \u4e00\u6b65\u8fde\u7eed\u8c03\u8282 */
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
/** \u62ac\u624b / \u79fb\u51fa\uff1a\u505c\u6b62\u8fde\u7eed\u8c03\u8282\u5e76\u7acb\u5373\u4e0b\u53d1 */
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
/** \u771f\u6b63\u751f\u6548\uff1a\u672c\u673a\u6539 audio.volume\uff0c\u97f3\u54cd\u8d70 /api/volume */
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
    if (r && r.ok === false) throw new Error(r.result || '\u5931\u8d25');
    if (udns) { const d = devices()[S._volIdx]; if (d) d.volume = v; }
    await tick(true);
  } catch (e) { toast('\u97f3\u91cf\u8bbe\u7f6e\u5931\u8d25\uff1a' + e.message, 'err'); }
}""",
    "重写 volLive / volAll 并新增加减按钮逻辑")

# ------------------------------------------------------------------- 5. CSS
sub(CSS, """.vrow{display:flex;align-items:center;gap:10px;margin-top:14px}""",
    """.vrow{display:flex;align-items:center;gap:8px;margin-top:14px}
/* 音量面板的 − / + 精调按钮 */
.vbtn{
  flex:0 0 36px;width:36px;height:36px;display:flex;align-items:center;justify-content:center;
  background:rgba(34,230,255,.06);border:1px solid var(--line2);border-radius:4px;
  color:var(--cy);font-size:21px;font-weight:600;line-height:1;font-family:var(--mono);
  cursor:pointer;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;
  touch-action:manipulation;box-shadow:inset 0 0 12px rgba(34,230,255,.10);
  transition:background .12s,box-shadow .12s,transform .06s;
}
.vbtn:active{
  background:linear-gradient(140deg,rgba(34,230,255,.34),rgba(255,45,146,.24));
  color:#f0feff;box-shadow:0 0 14px rgba(34,230,255,.55);transform:scale(.94);
}""",
    "CSS：新增 .vbtn 加减按钮样式")

print("\napp.js / app.css 音量收敛补丁已应用。")
