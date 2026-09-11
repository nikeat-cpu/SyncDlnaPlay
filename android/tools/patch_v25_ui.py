# -*- coding: utf-8 -*-
"""v2.5 前端改造：
   1) SMB 面板：emoji 全部换成内联线性 SVG 图标（🖧 在手机上渲染成一团方块）；
      新增「扫描局域网」与「浏览共享」按钮，共享名/子目录都能点出来，不用手打。
   2) 在线音源：不再写死，加「音源管理」面板，可停用/删除/自己添加（网址、粘贴、选文件）。
   3) 顺手修掉密码框白底、textarea 无样式、sheet 关闭图标。
"""
import io
import os

WWW = os.path.join("app", "assets", "www")
JS = os.path.join(WWW, "app.js")
CSS = os.path.join(WWW, "app.css")
HTML = os.path.join(WWW, "index.html")


def sub(path, old, new, tag, count=1):
    s = io.open(path, encoding="utf-8").read()
    n = s.count(old)
    assert n == count, "[%s] 命中 %d 次（应为 %d）" % (tag, n, count)
    io.open(path, "w", encoding="utf-8", newline="\n").write(s.replace(old, new, count))
    print("  [OK] " + tag)


# ============================================================ 1. 图标集合
ICONS = r"""
/* 内联线性图标集合
   ------------------------------------------------------------------
   为什么不用 emoji：🖧 这类冷门 emoji 在不同 ROM 上有的渲染成方块、
   有的是彩色贴图，跟赛博朋克配色打架。统一用 currentColor 描边 SVG，
   颜色跟着文字走，任何设备上长得都一样。 */
const I = {
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
"""

sub(JS, "const TAB_TITLE = { devices:", ICONS + "\nconst TAB_TITLE = { devices:",
    "插入图标集合")

# ============================================================ 2. sheet 关闭按钮 → SVG
sub(HTML,
    '<button class="iconbtn" id="sheetClose">✕</button>',
    '<button class="iconbtn vi" id="sheetClose" title="关闭">'
    '<svg class="iv" viewBox="0 0 24 24"><path d="M6.2 6.2l11.6 11.6M17.8 6.2L6.2 17.8"/></svg></button>',
    "sheet 关闭图标改 SVG")

# ============================================================ 3. 曲库管理面板：图标 + 文案
sub(JS,
    """    return `<div class="item">
      <div class="ico">${s.type === 'smb' ? '🖧' : '📁'}</div>""",
    """    return `<div class="item">
      <div class="ico vi">${s.type === 'smb' ? I.net : I.folder}</div>""",
    "目录行图标 → SVG")

sub(JS,
    """        ${s.active ? '' : `<button class="iconbtn sm2" title="设为当前" onclick="setActiveSource('${s.id}')">✔</button>`}
        ${s.type === 'smb' ? (s.mounted
        ? `<button class="iconbtn sm2" title="卸载" onclick="srcCmd('unmount','${s.id}')">⏏</button>`
        : `<button class="iconbtn sm2" title="挂载" onclick="srcCmd('mount','${s.id}')">⛓</button>`) : ''}
        <button class="iconbtn sm2" title="删除" onclick="srcDel('${s.id}')">✕</button>""",
    """        ${s.active ? '' : `<button class="iconbtn sm2 vi" title="设为当前" onclick="setActiveSource('${s.id}')">${I.check}</button>`}
        ${s.type === 'smb' ? (s.mounted
        ? `<button class="iconbtn sm2 vi" title="卸载" onclick="srcCmd('unmount','${s.id}')">${I.unplug}</button>`
        : `<button class="iconbtn sm2 vi" title="挂载" onclick="srcCmd('mount','${s.id}')">${I.plug}</button>`) : ''}
        <button class="iconbtn sm2 vi" title="删除" onclick="srcDel('${s.id}')">${I.x}</button>""",
    "目录行操作图标 → SVG")

sub(JS,
    """        <div class="chip" onclick="AB&&AB.pickMusicFolder&&AB.pickMusicFolder()">📁 添加本机目录</div>
        <div class="chip" onclick="srcAdd('smb')">🖧 添加网络共享</div>""",
    """        <div class="chip vi" onclick="AB&&AB.pickMusicFolder&&AB.pickMusicFolder()">${I.folderAdd} 添加本机目录</div>
        <div class="chip vi" onclick="srcAdd('smb')">${I.net} 添加网络共享</div>""",
    "曲库管理 chips → SVG")

sub(JS,
    """      <div class="chip" onclick="srcAdd('path')">＋ 加本地文件夹</div>
      <div class="chip" onclick="srcAdd('smb')">＋ 加 SMB 共享</div>
      <div class="chip" onclick="rescanLib()">↻ 重扫</div>""",
    """      <div class="chip vi" onclick="srcAdd('path')">${I.folderAdd} 加本地文件夹</div>
      <div class="chip vi" onclick="srcAdd('smb')">${I.net} 加 SMB 共享</div>
      <div class="chip vi" onclick="rescanLib()">${I.refresh} 重扫</div>""",
    "目录管理 chips → SVG")

# ============================================================ 4. SMB 面板重写
OLD_SMB_FORM = """    openSheet('添加 SMB 共享', `
      <input id="srcName" type="text" placeholder="名称（如 NAS 音乐）">
      <div class="row gap8" style="margin-top:10px">
        <input id="smbHost" type="text" placeholder="主机 / IP，如 192.168.1.100" style="flex:2">
        <input id="smbShare" type="text" placeholder="共享名，如 music" style="flex:2">
      </div>
      <input id="smbSub" type="text" placeholder="子目录（可选）" style="margin-top:10px">
      <div class="row gap8" style="margin-top:10px">
        <input id="smbUser" type="text" placeholder="用户名" style="flex:1">
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
    `);"""

NEW_SMB_FORM = """    openSheet('添加 SMB 共享', `
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
    `);"""

sub(JS, OLD_SMB_FORM, NEW_SMB_FORM, "SMB 表单增加扫描/浏览")

# 扫描 + 浏览逻辑，插在 srcAddSmb 之后
SMB_BROWSE_CODE = r"""
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
"""

sub(JS, "\nlet _guest = false;", SMB_BROWSE_CODE + "\nlet _guest = false;",
    "插入 SMB 扫描/浏览逻辑")

# ============================================================ 5. 在线音源管理
sub(JS,
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
    const r = PH.loadAll(srcs);""",
    """async function loadProviders() {
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
    const r = PH.loadAll(srcs);""",
    "loadProviders 改为读服务端音源清单")

sub(JS,
    """    const list = PH.list();
    if (!list.length) { sel.innerHTML = '<option value="">（无可用音源）</option>'; return; }
    sel.innerHTML = list.map(p => `<option value="${esc(p.platform)}">${esc(p.platform)}</option>`).join('');
    S.online.provider = list[0].platform;""",
    """    const list = PH.list();
    const keep = sel.value;
    if (!list.length) {
      sel.innerHTML = '<option value="">（没有启用的音源，去「音源」里加一个）</option>';
      S.online.provider = '';
      return;
    }
    sel.innerHTML = list.map(p => `<option value="${esc(p.platform)}">${esc(p.platform)}</option>`).join('');
    if (keep && list.some(p => p.platform === keep)) sel.value = keep;
    else S.online.provider = list[0].platform;""",
    "音源下拉保留当前选择")

# 音源管理面板，插在 loadProviders 之前
SRC_MGR = r"""
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
  const rows = list.map(function (s) {
    const nm = String(s.name || '').replace(/\.js$/i, '');
    return '<div class="item">'
      + '<div class="ico vi">' + I.wave + '</div>'
      + '<div class="txt">'
      + '<div class="t1">' + esc(nm) + ' <span class="sm muted">[' + (s.builtin ? '内置' : '自建') + ']</span>'
      + (s.enabled ? '' : ' <span class="sm" style="color:#ff2d92">已停用</span>') + '</div>'
      + '<div class="t2">' + (s.builtin ? '随 App 内置' : '你添加的')
      + (s.size ? ' · ' + Math.max(1, Math.round(s.size / 1024)) + ' KB' : '') + '</div>'
      + '</div>'
      + '<div class="act">'
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

"""

sub(JS, "async function loadProviders() {", SRC_MGR + "async function loadProviders() {",
    "插入音源管理面板")

# ============================================================ 6. 在线页加「音源」按钮
sub(HTML,
    """        <select id="onlineProvider" class="grow"></select>
        <select id="onlineLimit">""",
    """        <select id="onlineProvider" class="grow"></select>
        <button class="btn sm" id="btnSrcMgr" title="音源管理">音源</button>
        <select id="onlineLimit">""",
    "在线页加音源管理入口")

# 绑定按钮
sub(JS,
    "  $('sheetClose').addEventListener('click', closeSheet);",
    "  $('sheetClose').addEventListener('click', closeSheet);\n"
    "  const _bsm = $('btnSrcMgr');\n"
    "  if (_bsm) _bsm.addEventListener('click', srcMgrSheet);",
    "绑定音源管理按钮")

# ============================================================ 7. CSS
sub(CSS,
    """.item .ico,.mini-ico,
.item .act .iconbtn,
.iconbtn:not(.big),
.scanitem,
.chip:not(.on),
.vrow span{filter:grayscale(1) sepia(1) hue-rotate(148deg) saturate(6) brightness(1.05)}""",
    """.item .ico:not(.vi),.mini-ico,
.item .act .iconbtn:not(.vi),
.iconbtn:not(.big):not(.vi),
.scanitem:not(.vi),
.chip:not(.vi):not(.on),
.vrow span{filter:grayscale(1) sepia(1) hue-rotate(148deg) saturate(6) brightness(1.05)}

/* 内联线性图标：颜色跟着 currentColor 走，不参与上面的 emoji 滤镜 */
.iv{
  width:15px;height:15px;flex:0 0 auto;display:inline-block;vertical-align:-2.5px;
  fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;
}
.iconbtn .iv{width:16px;height:16px;vertical-align:middle}
.item .ico .iv{width:19px;height:19px;vertical-align:middle}

/* 密码框之前漏了样式，在深色界面里是一片白 —— 必须和文本框一致 */
input[type=password],input[type=number],input[type=url],textarea{
  background:rgba(8,14,24,.9);border:1px solid var(--line);border-radius:3px;
  padding:10px 12px;outline:none;width:100%;color:var(--tx);
  box-shadow:inset 0 0 18px rgba(34,230,255,.05);
  font-family:inherit;font-size:inherit;
}
input[type=password]::placeholder,textarea::placeholder{color:var(--tx3)}
input[type=password]:focus,textarea:focus{
  border-color:var(--cy);
  box-shadow:0 0 0 1px rgba(34,230,255,.25),0 0 18px rgba(34,230,255,.22);
}
textarea.ta{resize:vertical;line-height:1.5;font-size:13px;min-height:110px}
/* 浏览/扫描结果内嵌在面板里，不要撑破圆角 */
.scanbox{margin-top:10px}""",
    "CSS：向量图标 + 密码框 + 文本域")

print("\n前端补丁全部应用完成。")
