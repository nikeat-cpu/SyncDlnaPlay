#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把手机端 SPA 从「连 iStoreOS 服务」改造成「连本机内置服务 + WebView 内跑插件」。

改动要点：
  1. BASE 默认取原生注入的 http://127.0.0.1:8765
  2. 在线音源从「HTTP 调 /api/online/*」改为「直接调 window.PluginHost」
  3. 在线曲目播放/下载前，先在页面内解析直链并注册到本机服务
  4. 「音乐目录(SMB)」面板改为「曲库管理（本机）」
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.join(HERE, "..", "app", "assets", "www")


def patch(path, pairs):
    p = os.path.abspath(path)
    with io.open(p, "r", encoding="utf-8") as f:
        src = f.read()
    for i, (old, new) in enumerate(pairs):
        n = src.count(old)
        if n != 1:
            print("  [失败] 第 %d 处匹配 %d 次（应为 1 次）" % (i + 1, n))
            print("         片段开头: %s" % old[:80].replace("\n", "\\n"))
            return False
        src = src.replace(old, new, 1)
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print("  [完成] %s（%d 处）" % (os.path.basename(p), len(pairs)))
    return True


# ============================================================ app.js
APP_JS = [
    # ---- 1. BASE 默认指向本机服务 ----
    ("""    if (AB && AB.getServer) BASE = AB.getServer() || '';
    else BASE = localStorage.getItem('dlna_base') || '';
    if (!BASE && /^https?:/.test(location.protocol)) BASE = location.origin;
  } catch (e) { BASE = ''; }""",
     """    if (AB && AB.getBaseUrl) BASE = AB.getBaseUrl() || '';
    else BASE = localStorage.getItem('dlna_base') || '';
    if (!BASE && /^https?:/.test(location.protocol)) BASE = location.origin;
    if (!BASE) BASE = 'http://127.0.0.1:8765';
  } catch (e) { BASE = 'http://127.0.0.1:8765'; }"""),

    # ---- 2. 音源列表：改为载入内置插件运行时 ----
    ("""async function loadProviders() {
  try {
    const r = await api('/api/online/plugins', { _timeout: 12000 });
    const list = r.plugins || [];
    const sel = $('onlineProvider');
    if (!list.length) { sel.innerHTML = '<option value="">（无可用音源）</option>'; return; }
    sel.innerHTML = list.map(p => `<option value="${esc(p.platform)}">${esc(p.platform)}</option>`).join('');
    S.online.provider = list[0].platform;
  } catch (e) { $('onlineProvider').innerHTML = '<option value="">（音源不可用）</option>'; }
}""",
     """async function loadProviders() {
  const sel = $('onlineProvider');
  const PH = window.PluginHost;
  if (!PH) { sel.innerHTML = '<option value="">（插件运行时未加载）</option>'; return; }
  try {
    PH.configure({ proxyBase: BASE });
    let srcs = [];
    try { srcs = JSON.parse((AB && AB.getPlugins) ? (AB.getPlugins() || '[]') : '[]'); } catch (e) { srcs = []; }
    try {
      const mine = JSON.parse((AB && AB.getUserPlugins) ? (AB.getUserPlugins() || '[]') : '[]');
      if (mine.length) srcs = srcs.concat(mine);
    } catch (e) { }
    const r = PH.loadAll(srcs);
    if (r.failed && r.failed.length) console.warn('插件加载失败:', r.failed);
    const list = PH.list();
    if (!list.length) { sel.innerHTML = '<option value="">（无可用音源）</option>'; return; }
    sel.innerHTML = list.map(p => `<option value="${esc(p.platform)}">${esc(p.platform)}</option>`).join('');
    S.online.provider = list[0].platform;
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
}"""),

    # ---- 3. 搜索：改为调插件运行时 ----
    ("""  try {
    const r = await api('/api/online/search?q=' + q(kw) + '&provider=' + q(S.online.provider) +
      '&page=' + S.online.page + '&limit=' + limit, { _timeout: 30000 });
    S.online.items = r.items || [];
    S.online.isEnd = !!r.isEnd;
    renderOnline();
  } catch (e) {
    box.innerHTML = '<div class="empty">搜索失败：' + esc(e.message) + '</div>';
  }""",
     """  const PH = window.PluginHost;
  if (!PH) { box.innerHTML = '<div class="empty">插件运行时未加载，无法搜索</div>'; return; }
  try {
    const r = await PH.search({ q: kw, provider: S.online.provider, page: S.online.page, limit: limit });
    S.online.items = r.items || [];
    S.online.isEnd = !!r.isEnd;
    if (r.errors && r.errors.length) console.warn('部分音源出错:', r.errors);
    renderOnline();
  } catch (e) {
    box.innerHTML = '<div class="empty">搜索失败：' + esc(e.message) + '</div>';
  }"""),

    # ---- 4. playOne：在线曲目先解析 ----
    ("""async function playOne(kind, i, forcePhone) {
  const items = getItems(kind);
  const t = items[i];
  if (!t) return;
  buzz();
  if (forcePhone || S.out === 'phone') {""",
     """async function playOne(kind, i, forcePhone) {
  let items = getItems(kind);
  const t = items[i];
  if (!t) return;
  buzz();
  if (kind === 'online') {
    try {
      items = await resolveOnline(items);
      S.online.items = items;
    } catch (e) { toast('解析播放地址失败：' + e.message, 'err'); return; }
  }
  if (forcePhone || S.out === 'phone') {"""),

    # ---- 5. 加入播放列表：在线曲目先解析 ----
    ("""    const on = tracks.filter(t => t.source === 'online');
    const other = tracks.filter(t => t.source !== 'online');
    if (on.length) {
      await apiPost('/api/online/add', {
        items: on.map(t => ({
          provider: t.provider, id: t.oid || t.id, title: t.title,
          artist: t.artist, album: t.album, duration_sec: t.duration_sec || 0
        }))
      }, 40000);
    }
    if (other.length) await apiPost('/api/queue', { action: 'add', tracks: other });""",
     """    const on = tracks.filter(t => t.source === 'online');
    const other = tracks.filter(t => t.source !== 'online');
    if (on.length) {
      const resolved = await resolveOnline(on.map(t => ({
        id: t.oid || t.id, provider: t.provider, title: t.title, artist: t.artist,
        album: t.album, duration_sec: t.duration_sec || 0, source: 'online'
      })));
      await apiPost('/api/queue', { action: 'add', tracks: resolved }, 40000);
    }
    if (other.length) await apiPost('/api/queue', { action: 'add', tracks: other });"""),

    # ---- 6. 下载：先解析直链，再把直链+请求头交给原生下载器 ----
    ("""async function doDownload(items) {
  toast('已加入下载队列（' + items.length + ' 首）');
  try {
    const r = await apiPost('/api/online/download', { items: items }, 60000);
    if (r.ok === false) throw new Error(r.msg || '失败');
    toast('开始下载 ' + items.length + ' 首', 'ok');
  } catch (e) { toast('下载失败：' + e.message, 'err'); }
}""",
     """async function doDownload(items) {
  toast('正在解析下载地址…');
  let resolved;
  try {
    resolved = await resolveOnline(items);
  } catch (e) { toast('解析失败：' + e.message, 'err'); return; }
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
}"""),

    # ---- 7. 本机播放：支持单曲循环 / 列表循环 ----
    ("audio.addEventListener('ended', phoneNext);",
     """audio.addEventListener('ended', function () {
  const pl = (S.state && S.state.player) || {};
  if (pl.repeat === 'one') { try { audio.currentTime = 0; audio.play(); } catch (e) { } return; }
  if (S.phone.idx + 1 < S.phone.queue.length) { phoneNext(); return; }
  if (pl.repeat === 'all' && S.phone.queue.length) { phonePlayAt(0); return; }
  toast('播放列表已播完');
});"""),

    # ---- 8. 「音乐目录」面板 -> 「曲库管理（本机）」 ----
    ("""async function musicSourcesSheet() {
  openSheet('音乐目录', '<div class="empty"><span class="spin"></span> 读取中…</div>');
  try {
    const r = await api('/api/music/sources');
    renderSourcesSheet(r);
  } catch (e) { $('sheetBody').innerHTML = '<div class="empty">读取失败：' + esc(e.message) + '</div>'; }
}""",
     """async function musicSourcesSheet() {
  openSheet('曲库管理', '<div class="empty"><span class="spin"></span> 读取中…</div>');
  try {
    const info = (AB && AB.getLibraryInfo) ? JSON.parse(AB.getLibraryInfo() || '{}') : {};
    const perm = (AB && AB.getPermissionState) ? AB.getPermissionState() : 'granted';
    const dir = (AB && AB.getDownloadsDir) ? AB.getDownloadsDir() : '';
    const last = info.last_scan ? new Date(info.last_scan * 1000).toLocaleString() : '—';
    $('sheetBody').innerHTML = `
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
      <div class="sec-title">下载目录</div>
      <div class="sm muted" style="word-break:break-all">${esc(dir)}</div>
      <div class="chips" style="margin-top:10px">
        <div class="chip" onclick="AB&&AB.openDownloads&&AB.openDownloads()">打开下载目录</div>
      </div>
      <div class="sec-title">关于</div>
      <div class="sm muted">独立运行版：DLNA 控制、曲库扫描、在线音源全部在手机本机运行，不依赖家中服务器，换任何网络都能用。</div>`;
  } catch (e) { $('sheetBody').innerHTML = '<div class="empty">读取失败：' + esc(e.message) + '</div>'; }
}
async function rescanLibrary() {
  try {
    if (AB && AB.rescanLibrary) AB.rescanLibrary();
    else await apiPost('/api/library/rescan', {});
    toast('已开始重新扫描', 'ok');
    closeSheet();
    setTimeout(function () { loadLib(); tick(true); }, 2000);
  } catch (e) { toast('失败：' + e.message, 'err'); }
}"""),

    # ---- 9. 设置面板：去掉服务器地址语义，改为本机信息 ----
    ("""    <div class="sec-title">服务器</div>
    <div class="sm muted" style="margin-bottom:8px">当前：<b style="color:var(--tx)">${esc(BASE || '未设置')}</b></div>
    <input id="setAddr" type="text" placeholder="192.168.1.10:5000" value="${esc((BASE || '').replace(/^https?:\\/\\//, ''))}">
    <div class="row gap8" style="margin-top:10px">
      <button class="btn pri grow" onclick="applyAddr()">保存并重连</button>
      <button class="btn" onclick="doScan()">扫描</button>
    </div>
    <div class="msg" id="setMsg"></div>

    <div class="sec-title">音乐目录</div>
    <div class="chips">
      <div class="chip" onclick="closeSheet();musicSourcesSheet()">🗂 管理音乐目录</div>
    </div>

    <div class="sec-title">关于</div>
    <div class="sm muted">
      音响管家 · 手机端${AB && AB.getVersion ? ' v' + esc(AB.getVersion()) : ''}<br>
      通过局域网控制 DLNA 音响；在线音源由服务端提供。
    </div>""",
     """    <div class="sec-title">本机服务</div>
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

    <div class="sec-title">关于</div>
    <div class="sm muted">
      音响管家 · 独立运行版${AB && AB.getVersion ? ' v' + esc(AB.getVersion()) : ''}<br>
      DLNA 控制、曲库、在线音源全部在手机本机运行，无需家中服务器。
    </div>"""),

    # ---- 10. 原生回调 ----
    ("""/* --- 返回键（原生端会调用） --- */""",
     """/* --- 原生端回调 --- */
window.__onPermissionChanged = function () {
  toast('已获得读取权限，开始扫描音乐', 'ok');
  loadLib();
  tick(true);
};
window.__onLibraryChanged = function () { loadLib(); tick(true); };

/* --- 返回键（原生端会调用） --- */"""),
]

# ============================================================ index.html
INDEX_HTML = [
    ("""    <p class="sub">连接家里的音乐服务（iStoreOS / NAS）</p>

    <label class="fld">
      <span>服务器地址</span>
      <input id="setupAddr" type="text" inputmode="url" autocapitalize="off" autocorrect="off"
             spellcheck="false" placeholder="192.168.1.10:5000">
    </label>

    <div class="row gap8">
      <button class="btn pri grow" id="btnConnect">连接</button>
      <button class="btn" id="btnScan">扫描局域网</button>
    </div>

    <div id="scanBox" class="scanbox" style="display:none"></div>
    <div id="setupMsg" class="msg"></div>
    <p class="hint">填服务地址即可，默认端口 5000。手机和服务器要在同一个 WiFi 下。</p>""",
     """    <p class="sub">独立运行版 · 无需连接任何服务器</p>

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
    <p class="hint">正常情况下会自动进入。若停在这一页，说明内置服务没起来，可点「重试连接」。</p>"""),
]

if __name__ == "__main__":
    ok = patch(os.path.join(WWW, "app.js"), APP_JS)
    ok = patch(os.path.join(WWW, "index.html"), INDEX_HTML) and ok
    sys.exit(0 if ok else 1)
