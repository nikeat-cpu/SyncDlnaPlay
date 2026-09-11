# -*- coding: utf-8 -*-
"""
v2.2 补丁：去掉「网页感」和「连接服务器」的痕迹
==============================================
用户的疑问：「为什么还是一个网页版的程序？127.0.0.1:8765 是啥东西？」

根因：独立版（后端跑在本进程内）却照搬了 v1.0「连 iStoreOS 客户端」的界面：
  - 启动页有「本机服务地址」输入框（placeholder=127.0.0.1:8765）+「扫描外部服务」按钮
  - 设置页有「内置服务地址：http://127.0.0.1:8765」和「高级：连接外部服务」
  - 后端异步启动 → /api/health 首探失败 → 用户被丢进上面这个"连接服务器"页
这三处让它看起来像个要填服务器地址的网页。

本次改动：
  1. index.html：连接页 → 纯启动页（logo + 转圈 + 「重新启动」，无地址无端口无扫描）
  2. app.js：startEngine() 重试等待后端就绪；删掉填地址/扫描/改地址的所有逻辑
  3. app.css：加一个大号转圈 + 禁止长按选中/文字缩放（更像原生）
  4. MainActivity：WebView 关掉长按选择、滚动条、边缘回弹、缩放，锁定字体大小
"""
import ast
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, ".."))
WWW = os.path.join(PROJ, "app", "assets", "www")

P_HTML = os.path.join(WWW, "index.html")
P_JS = os.path.join(WWW, "app.js")
P_CSS = os.path.join(WWW, "app.css")
P_JAVA = os.path.join(PROJ, "app", "java", "com", "dlna", "speaker", "MainActivity.java")


def sub(path, old, new, tag, count=1):
    s = io.open(path, encoding="utf-8").read()
    n = s.count(old)
    assert n == count, "%s: 匹配到 %d 处（期望 %d）" % (tag, n, count)
    s = s.replace(old, new, count)
    io.open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("  [OK] %s" % tag)


# =====================================================================
# 1. index.html：连接页 -> 启动页
# =====================================================================
OLD_HTML = """<!-- ============ 首次连接 / 设置 ============ -->
<div id="setup" class="setup">
  <div class="setup-card">
    <div class="logo">🎵</div>
    <h1>音响管家</h1>
    <p class="sub">独立运行版 · 无需连接任何服务器</p>

    <label class="fld">
      <span>本机服务地址（一般不用改）</span>
      <input id="setupAddr" type="text" inputmode="url" autocapitalize="off" autocorrect="off"
             spellcheck="false" placeholder="127.0.0.1:8765">
    </label>

    <div class="row gap8">
      <button class="btn pri grow" id="btnConnect">重试连接</button>
      <button class="btn" id="btnScan">扫描外部服务</button>
    </div>

    <div id="scanBox" class="scanbox" style="display:none"></div>
    <div id="setupMsg" class="msg"></div>
    <p class="hint">正常情况下会自动进入。若停在这一页，说明内置服务没起来，可点「重试连接」。</p>
  </div>
</div>"""

NEW_HTML = """<!-- ============ 启动页 ============
     注意：播控服务就跑在本 App 进程里，不存在"连接服务器"这回事，
     所以这里只有启动动画，没有任何地址 / 端口 / 扫描。 -->
<div id="setup" class="setup">
  <div class="setup-card">
    <div class="logo">🎵</div>
    <h1>音响管家</h1>
    <p class="sub" id="splashSub">正在启动…</p>
    <div class="spin lg" id="splashSpin"></div>
    <div class="msg" id="setupMsg"></div>
    <button class="btn pri" id="btnRetry" style="display:none">重新启动</button>
  </div>
</div>"""

sub(P_HTML, OLD_HTML, NEW_HTML, "index.html 连接页 -> 启动页")

# =====================================================================
# 2. app.js：启动逻辑
# =====================================================================
OLD_BOOT = """function showSetup(msg, isErr) {
  $('app').style.display = 'none';
  $('setup').style.display = '';
  const a = $('setupAddr');
  if (BASE && !a.value) a.value = BASE.replace(/^https?:\\/\\//, '');
  setMsg(msg, isErr);
}
function setMsg(m, isErr) {
  const el = $('setupMsg');
  el.textContent = m || '';
  el.className = 'msg' + (isErr ? ' err' : (m ? ' ok' : ''));
}

async function testAndEnter(addr) {
  const b = normBase(addr);
  if (!b) { setMsg('请填写服务器地址', true); return; }
  setMsg('正在连接…');
  const old = BASE; BASE = b;
  try {
    const h = await api('/api/health', { _timeout: 8000 });
    if (!h || !h.ok) throw new Error('服务未就绪');
    saveBase(b);
    setMsg('');
    await boot();
  } catch (e) {
    BASE = old;
    setMsg('连不上：' + (e.message || e) + '（检查地址、WiFi 是否同一网络）', true);
  }
}"""

NEW_BOOT = """/* 启动页。
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
}"""

sub(P_JS, OLD_BOOT, NEW_BOOT, "app.js 启动逻辑")

OLD_SCAN = """/* --- 局域网扫描（由原生端完成并发探测） --- */
window.__onScanResults = function (json) {
  let list = [];
  try { list = JSON.parse(json) || []; } catch (e) { list = []; }
  const box = $('scanBox');
  box.style.display = '';
  if (!list.length) {
    box.innerHTML = '<div class="empty" style="padding:16px">没扫到服务，可手动输入地址</div>';
    return;
  }
  box.innerHTML = list.map(h =>
    `<div class="scanitem" onclick="pickScan('${esc(h.url)}')">
       <span style="font-size:17px">🖥</span>
       <div class="txt" style="flex:1">
         <div class="t1">${esc(h.name || '音乐服务')}</div>
         <div class="t2">${esc(h.url)}</div>
       </div>
     </div>`).join('');
};
function pickScan(url) {
  $('setupAddr').value = String(url).replace(/^https?:\\/\\//, '');
  testAndEnter(url);
}
function doScan() {
  if (!AB || !AB.scanLan) { setMsg('App 内才支持自动扫描，请手动填地址', true); return; }
  const box = $('scanBox');
  box.style.display = '';
  box.innerHTML = '<div class="empty" style="padding:16px"><span class="spin"></span> 正在扫描局域网…</div>';
  $('btnScan').disabled = true;
  try { AB.scanLan(); } catch (e) { setMsg('扫描失败：' + e, true); }
  setTimeout(() => { $('btnScan').disabled = false; }, 12000);
}"""

NEW_SCAN = """/* 局域网扫描是 v1.0「连外部服务」客户端模式的东西，独立版已不需要。
   原生端也已移除 scanLan，这里留个空实现，避免旧调用打空指针。 */
window.__onScanResults = function () { };"""

sub(P_JS, OLD_SCAN, NEW_SCAN, "app.js 删除局域网扫描")

OLD_SET = """function settingsSheet() {
  openSheet('设置', `
    <div class="sec-title">本机服务</div>
    <div class="sm muted" style="margin-bottom:8px">内置服务地址：<b style="color:var(--tx)">${esc(BASE || '未启动')}</b></div>
    <div class="chips">
      <div class="chip" onclick="closeSheet();musicSourcesSheet()">🗂 曲库管理</div>
      <div class="chip" onclick="closeSheet();dlStatus()">⤓ 下载状态</div>
    </div>

    <div class="sec-title">高级：连接外部服务</div>
    <div class="sm muted" style="margin-bottom:8px">一般不需要填。只有当你想改用局域网里另一台服务时才填写。</div>
    <input id="setAddr" type="text" placeholder="192.168.1.10:5000" value="">
    <div class="row gap8" style="margin-top:10px">
      <button class="btn grow" onclick="applyAddr()">改用该地址</button>
    </div>
    <div class="msg" id="setMsg"></div>

    <div class="sec-title">关于</div>"""

NEW_SET = """function settingsSheet() {
  openSheet('设置', `
    <div class="chips">
      <div class="chip" onclick="closeSheet();musicSourcesSheet()">🗂 曲库管理</div>
      <div class="chip" onclick="closeSheet();dlStatus()">⤓ 下载状态</div>
    </div>

    <div class="sec-title">关于</div>"""

sub(P_JS, OLD_SET, NEW_SET, "app.js 设置页去掉地址项")

OLD_APPLY = """async function applyAddr() {
  const v = $('setAddr').value;
  const m = $('setMsg');
  m.className = 'msg'; m.textContent = '连接中…';
  try {
    const b = normBase(v); BASE = b;
    const h = await api('/api/health', { _timeout: 8000 });
    if (!h.ok) throw new Error('服务未就绪');
    saveBase(b);
    m.className = 'msg ok'; m.textContent = '已保存';
    closeSheet();
    await boot();
  } catch (e) { m.className = 'msg err'; m.textContent = '失败：' + e.message; }
}

"""
sub(P_JS, OLD_APPLY, "", "app.js 删除 applyAddr")

OLD_BIND = """  $('btnConnect').addEventListener('click', () => testAndEnter($('setupAddr').value));
  $('btnScan').addEventListener('click', doScan);
  $('setupAddr').addEventListener('keydown', e => { if (e.key === 'Enter') testAndEnter($('setupAddr').value); });"""

NEW_BIND = """  $('btnRetry').addEventListener('click', () => { setMsg(''); startEngine(); });"""

sub(P_JS, OLD_BIND, NEW_BIND, "app.js 重绑启动页按钮")

OLD_TAIL = """  // 自动进入 / 停留连接页
  if (BASE) {
    testAndEnter(BASE).catch(() => { });
  } else {
    showSetup('');
  }"""

NEW_TAIL = """  // 启动本机内置服务（它在 App 进程里，不存在"连不上服务器"）
  startEngine().catch(e => setMsg('启动异常：' + ((e && e.message) || e), true));"""

sub(P_JS, OLD_TAIL, NEW_TAIL, "app.js 开机流程")

# =====================================================================
# 3. app.css：大号转圈 + 去网页感
# =====================================================================
CSS_ADD = """
/* ---------------- 启动页大转圈 ---------------- */
.spin.lg{width:30px;height:30px;border-width:3px;display:block;margin:16px auto 2px;vertical-align:0}

/* ---------------- 去掉「网页感」 ----------------
   长按选中/放大镜、文字随系统字号缩放，都是网页才有的行为。 */
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;overscroll-behavior:none}
input,textarea,.lrc-box,.lrc-line{-webkit-user-select:text;user-select:text;-webkit-touch-callout:default}
"""
s = io.open(P_CSS, encoding="utf-8").read()
assert ".spin.lg" not in s, "app.css 已经有 .spin.lg 了"
io.open(P_CSS, "w", encoding="utf-8", newline="\n").write(s.rstrip("\n") + "\n" + CSS_ADD)
print("  [OK] app.css 追加启动页样式")

# =====================================================================
# 4. MainActivity：WebView 去掉网页行为
# =====================================================================
OLD_WV = """        if (Build.VERSION.SDK_INT >= 21) {
            ws.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }
"""
NEW_WV = """        if (Build.VERSION.SDK_INT >= 21) {
            ws.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        // 去掉「网页感」：不要长按选中/放大镜、不要滚动条、不要边缘回弹光效，
        // 字体也不随系统字号缩放（否则 5 档字体会把布局顶坏）。
        web.setLongClickable(false);
        web.setHapticFeedbackEnabled(false);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        ws.setTextZoom(100);
        ws.setSupportZoom(false);
        ws.setBuiltInZoomControls(false);
"""
sub(P_JAVA, OLD_WV, NEW_WV, "MainActivity WebView 去网页化")

print("\n全部改完。")
