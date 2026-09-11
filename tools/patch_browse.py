# -*- coding: utf-8 -*-
"""让"添加自定义目录"真正通用：目录选择器锚定在设备存储 / SMB 挂载点两个根上。

- music_sources.py: 新增 BROWSER_ROOTS / browse_roots() / clamp_browse_path()
- server.py:        /api/music/browse 返回 roots、夹住路径、给出可写状态
- index.html:       选项文案改清楚 + 浏览器显示根切换按钮、默认从设备存储开始
"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def patch(path, pairs):
    p = os.path.join(ROOT, path)
    s = io.open(p, encoding="utf-8").read()
    for old, new in pairs:
        assert old in s, f"[{path}] 未找到锚点:\n{old[:120]}"
        s = s.replace(old, new, 1)
    io.open(p, "w", encoding="utf-8", newline="").write(s)
    print("patched:", path)


# ---------------------------------------------------------------- music_sources.py
ms_roots = '''
# 目录浏览器可见的"根"（容器内路径）。
# 只允许在这两处挑目录，避免一路翻到容器自己的 /（那是容器根，不是设备根）而选错。
BROWSER_ROOTS = [
    {"name": "设备存储", "path": "/hostmnt",
     "desc": "iStoreOS 本机磁盘 / U 盘（宿主 /mnt）"},
    {"name": "SMB 挂载点", "path": CONTAINER_MNT_ROOT,
     "desc": "已添加的 SMB 共享挂载目录"},
]


def browse_roots():
    return [dict(r) for r in BROWSER_ROOTS if os.path.isdir(r["path"])]


def clamp_browse_path(path):
    """把浏览路径夹在允许的根范围内，返回 (容器内路径, 根字典)"""
    roots = browse_roots()
    if not roots:
        return "", None
    path = (path or "").strip().rstrip("/")
    for r in roots:
        rp = r["path"].rstrip("/")
        if path == rp or path.startswith(rp + "/"):
            return (path if os.path.isdir(path) else rp), r
    return roots[0]["path"], roots[0]


def in_allowed_root(path):
    """路径是否落在允许的根之内（用于校验手动/接口传入的本地目录）"""
    path = (path or "").strip().rstrip("/")
    for r in BROWSER_ROOTS:
        rp = r["path"].rstrip("/")
        if path == rp or path.startswith(rp + "/"):
            return True
    return False


'''
patch("app/music_sources.py", [
    ("def nsenter_available():", ms_roots + "def nsenter_available():"),
    # add(): 本地路径做存在性 + 范围校验，避免加进不可访问的目录
    ('''            if not p:
                return None, "缺少路径"
            src["path"] = p''',
     '''            if not p:
                return None, "缺少路径"
            if not os.path.isdir(p):
                return None, f"目录不存在或不可访问：{p}"
            if not in_allowed_root(p):
                return None, ("该路径不在可浏览范围内（只允许设备存储 /hostmnt "
                              "与 SMB 挂载点 /hostnmt/smb 之下）")
            src["path"] = p'''),
])

# ---------------------------------------------------------------- server.py
patch("app/server.py", [
    ('''    base = (request.args.get("path") or music_sources.CONTAINER_MNT_ROOT).strip()
    if not os.path.isdir(base):
        base = music_sources.CONTAINER_MNT_ROOT''',
     '''    requested = (request.args.get("path") or "").strip()
    base, root = music_sources.clamp_browse_path(requested)
    if not base:
        return jsonify({"ok": False, "msg": "没有可浏览的目录"}), 400'''),
    ('''    dirs.sort(key=lambda d: d["name"].lower())
    parent = os.path.dirname(base.rstrip("/")) or "/"
    return jsonify({"ok": True, "path": base, "parent": parent,
                    "dirs": dirs, "audio_files": audio_here})''',
     '''    dirs.sort(key=lambda d: d["name"].lower())
    root_path = root["path"].rstrip("/")
    parent = os.path.dirname(base.rstrip("/")) or root_path
    if not (parent == root_path or parent.startswith(root_path + "/")):
        parent = root_path
    return jsonify({
        "ok": True, "path": base, "parent": parent,
        "root": root_path, "root_name": root["name"],
        "roots": music_sources.browse_roots(),
        "dirs": dirs, "audio_files": audio_here,
        "writable": os.access(base, os.W_OK),
    })'''),
])

# ---------------------------------------------------------------- index.html
old_browse = """async function msBrowse(path){
  const p = path || $('msPath').value.trim();
  msMsg('浏览中…');
  const r = await api('/api/music/browse' + (p ? `?path=${encodeURIComponent(p)}` : ''));
  if(!r.ok){ msMsg('浏览失败：'+(r.msg||''), true); return; }
  msMsg('');
  msCurPath = r.path;
  const dirs = r.dirs || [];
  $('msBrowser').style.display = '';
  $('msBrowser').innerHTML =
    `<div class="bar" style="gap:6px;flex-wrap:wrap;padding:2px 0 6px">
       <button class="btn sm" onclick="msBrowse(${_q(r.parent)})">↑ 上一级</button>
       <button class="btn sm pri" onclick="msChoose()">选这个目录</button>
       <span style="font-size:11.5px;color:var(--tx3)">${esc(r.path)} · ${r.audio_files} 首音乐</span>
     </div>` +
    (dirs.length
      ? dirs.map(d=>`<div style="padding:4px 2px;cursor:pointer;font-size:13px" onclick="msBrowse(${_q(d.path)})">📁 ${esc(d.name)}</div>`).join('')
      : '<div class="empty" style="padding:6px">（没有子目录）</div>');
}"""

new_browse = """let msRoots = [];
async function msBrowse(path){
  const p = path || $('msPath').value.trim();
  msMsg('浏览中…');
  const r = await api('/api/music/browse' + (p ? `?path=${encodeURIComponent(p)}` : ''));
  if(!r.ok){ msMsg('浏览失败：'+(r.msg||''), true); return; }
  msMsg('');
  msCurPath = r.path;
  msRoots = r.roots || msRoots;
  const dirs = r.dirs || [];
  const chips = msRoots.map(rt =>
    `<button class="btn sm${rt.path===r.root?' pri':''}" title="${esc(rt.desc||'')}" onclick="msBrowse(${_q(rt.path)})">${esc(rt.name)}</button>`
  ).join('');
  $('msBrowser').style.display = '';
  $('msBrowser').innerHTML =
    `<div class="bar" style="gap:6px;flex-wrap:wrap;padding:2px 0 6px">
       ${chips}
       <button class="btn sm" onclick="msBrowse(${_q(r.parent)})">↑ 上一级</button>
       <button class="btn sm pri" onclick="msChoose()">选这个目录</button>
       <span style="font-size:11.5px;color:var(--tx3)">${esc(r.path)} · ${r.audio_files} 首音乐 · ${r.writable?'可写':'只读'}</span>
     </div>` +
    (dirs.length
      ? dirs.map(d=>`<div style="padding:4px 2px;cursor:pointer;font-size:13px" onclick="msBrowse(${_q(d.path)})">📁 ${esc(d.name)}</div>`).join('')
      : '<div class="empty" style="padding:6px">（没有子目录，可直接点「选这个目录」）</div>');
}"""

patch("app/static/index.html", [
    ('<option value="path">本地 / 已挂载路径</option>',
     '<option value="path">本机文件夹 / 已挂载目录</option>'),
    ("""        <input type="text" id="msPath" placeholder="点右侧「浏览」选择目录" style="flex:1;min-width:220px" readonly>""",
     """        <input type="text" id="msPath" placeholder="点右侧「浏览」，从设备存储里选一个文件夹" style="flex:1;min-width:220px" readonly>"""),
    (old_browse, new_browse),
])

# 校验
for f in ("app/music_sources.py", "app/server.py"):
    p = os.path.join(ROOT, f)
    compile(io.open(p, encoding="utf-8").read(), p, "exec")
print("python syntax OK")
