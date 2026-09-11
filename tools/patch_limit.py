# -*- coding: utf-8 -*-
"""Patch: online search limit select + seq column (retry for edits that failed to persist)."""
import io, sys

def patch(path, subs):
    with io.open(path, "r", encoding="utf-8") as f:
        s = f.read()
    changed = 0
    for old, new in subs:
        if new in s:
            changed += 1  # already applied
            continue
        if old not in s:
            print("MISS in %s: %r..." % (path, old[:60]))
            continue
        s = s.replace(old, new, 1)
        changed += 1
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    print("patched %s (%d/%d)" % (path, changed, len(subs)))

# ---------- index.html ----------
sel_html = '''    <select id="onlineLimit" style="min-width:86px" onchange="onLimitChange()" title="每次搜索显示条数">
      <option value="20">20 首</option>
      <option value="30" selected>30 首</option>
      <option value="50">50 首</option>
      <option value="100">100 首</option>
      <option value="custom">自定义…</option>
    </select>
    <input type="number" id="onlineLimitCustom" min="1" max="200" placeholder="条数" style="display:none;width:76px" onkeydown="if(event.key==='Enter')doOnlineSearch()">
'''

js_new = '''function onLimitChange(){
  const sel=$('onlineLimit'), ci=$('onlineLimitCustom');
  ci.style.display = sel.value==='custom' ? '' : 'none';
  if(sel.value==='custom') ci.focus();
}
function getOnlineLimit(){
  const sel=$('onlineLimit').value;
  if(sel==='custom'){
    const n=parseInt($('onlineLimitCustom').value,10);
    return (n>0&&n<=200)?n:30;
  }
  return parseInt(sel,10)||30;
}

async function doOnlineSearch(){
  const q = $('onlineSearch').value.trim();
  const provider = $('onlineProvider').value;
  if(!q){$('onlineList').innerHTML='<div class="empty">请输入关键字</div>';return;}
  $('onlineList').innerHTML='<div class="empty">搜索中…</div>';
  const limit = getOnlineLimit();
  const r = await api(`/api/online/search?q=${encodeURIComponent(q)}${provider?`&provider=${encodeURIComponent(provider)}`:''}&limit=${limit}`);'''

js_old = '''async function doOnlineSearch(){
  const q = $('onlineSearch').value.trim();
  const provider = $('onlineProvider').value;
  if(!q){$('onlineList').innerHTML='<div class="empty">请输入关键字</div>';return;}
  $('onlineList').innerHTML='<div class="empty">搜索中…</div>';
  const r = await api(`/api/online/search?q=${encodeURIComponent(q)}${provider?`&provider=${encodeURIComponent(provider)}`:''}`);'''

patch("app/static/index.html", [
    ('    <button class="btn" onclick="doOnlineSearch()" data-page-node-id="on8EsYOw6TQ73Gt2Fp6tAr">搜索</button>\n',
     '    <button class="btn" onclick="doOnlineSearch()" data-page-node-id="on8EsYOw6TQ73Gt2Fp6tAr">搜索</button>\n' + sel_html),
    (js_old, js_new),
])

# ---------- bridge.js ----------
patch("musicfree-bridge/bridge.js", [
    ("  const provider = req.query.provider || '';\n  if (!q) return res.json({ items: [] });\n  const targets",
     "  const provider = req.query.provider || '';\n  const limit = Math.max(0, parseInt(req.query.limit || '0', 10) || 0);\n  if (!q) return res.json({ items: [] });\n  const targets"),
])

print("done")
