# -*- coding: utf-8 -*-
"""Patch: online search pagination (prev/next page buttons + isEnd passthrough)."""
import io

def patch(path, subs):
    with io.open(path, "r", encoding="utf-8") as f:
        s = f.read()
    done = 0
    for old, new in subs:
        if new in s:
            done += 1
            continue
        if old not in s:
            print("MISS in %s: %r..." % (path, old[:70]))
            continue
        s = s.replace(old, new, 1)
        done += 1
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    print("patched %s (%d/%d)" % (path, done, len(subs)))

# ---------- index.html ----------
pager_html = '''  <div id="onlinePager" style="display:none;justify-content:center;align-items:center;gap:12px;padding:8px 4px 2px">
    <button class="btn" id="btnOnlinePrev" onclick="onlinePage(-1)">‹ 上一页</button>
    <span id="onlinePageNo" style="font-size:13px;color:var(--tx3)">第 1 页</span>
    <button class="btn" id="btnOnlineNext" onclick="onlinePage(1)">下一页 ›</button>
  </div>
'''

js_state_old = "let curOnlineList = [];"
js_state_new = "let curOnlineList = [];\nlet curOnlinePage = 1, curOnlineQuery = '', curOnlineProvider = '';"

js_search_old = '''async function doOnlineSearch(){
  const q = $('onlineSearch').value.trim();
  const provider = $('onlineProvider').value;
  if(!q){$('onlineList').innerHTML='<div class="empty">请输入关键字</div>';return;}
  $('onlineList').innerHTML='<div class="empty">搜索中…</div>';
  const limit = getOnlineLimit();
  const r = await api(`/api/online/search?q=${encodeURIComponent(q)}${provider?`&provider=${encodeURIComponent(provider)}`:''}&limit=${limit}`);
  if(!r.ok){$('onlineList').innerHTML=`<div class="empty">${esc(r.msg||'搜索失败')}</div>`;return;}
  const items = r.items||[];
  curOnlineList = items;
  if(!items.length){$('onlineList').innerHTML='<div class="empty">无结果</div>';return;}
'''

js_search_new = '''async function doOnlineSearch(page){
  const q = $('onlineSearch').value.trim();
  const provider = $('onlineProvider').value;
  if(!q){$('onlineList').innerHTML='<div class="empty">请输入关键字</div>';return;}
  if(typeof page!=='number'||page<1)page=1;
  curOnlineQuery=q; curOnlineProvider=provider; curOnlinePage=page;
  $('onlineList').innerHTML='<div class="empty">搜索中…</div>';
  const limit = getOnlineLimit();
  const r = await api(`/api/online/search?q=${encodeURIComponent(q)}${provider?`&provider=${encodeURIComponent(provider)}`:''}&page=${page}&limit=${limit}`);
  if(!r.ok){$('onlineList').innerHTML=`<div class="empty">${esc(r.msg||'搜索失败')}</div>`;return;}
  const items = r.items||[];
  curOnlineList = items;
  renderOnlinePager(items.length, !!r.isEnd);
  if(!items.length){$('onlineList').innerHTML='<div class="empty">无结果（本页为空，可回上一页）</div>';return;}
'''

js_pager_funcs = '''
function renderOnlinePager(count, isEnd){
  const p = $('onlinePager');
  if(!curOnlineQuery){p.style.display='none';return;}
  p.style.display='flex';
  $('onlinePageNo').textContent = `第 ${curOnlinePage} 页` + (count?` · ${count} 首`:'');
  const prev = $('btnOnlinePrev'), next = $('btnOnlineNext');
  prev.disabled = curOnlinePage<=1;
  prev.style.opacity = curOnlinePage<=1 ? .45 : 1;
  next.disabled = isEnd||count===0;
  next.style.opacity = (isEnd||count===0) ? .45 : 1;
}

function onlinePage(delta){
  if(delta<0 && curOnlinePage<=1)return;
  doOnlineSearch(curOnlinePage+delta);
}
'''

patch("app/static/index.html", [
    # 1. pager HTML after onlineList div, before dlStatus
    ('  <div id="dlStatus" style="display:none;font-size:12px;color:var(--tx3);padding:4px 6px;line-height:1.7;white-space:pre-wrap;max-height:120px;overflow:auto"',
     pager_html + '  <div id="dlStatus" style="display:none;font-size:12px;color:var(--tx3);padding:4px 6px;line-height:1.7;white-space:pre-wrap;max-height:120px;overflow:auto'),
    # 2. page state vars
    (js_state_old, js_state_new),
    # 3. doOnlineSearch rewrite
    (js_search_old, js_search_new),
    # 4. pager helper functions appended after doOnlineSearch's closing (anchor: the end of its map/join block)
    ("  }).join('');\n}\n\nasync function addOnlineToQueue(i){",
     "  }).join('');\n}" + js_pager_funcs + "\nasync function addOnlineToQueue(i){"),
])

# ---------- bridge.js ----------
patch("musicfree-bridge/bridge.js", [
    ("  const targets = provider ? [provider] : Object.keys(plugins);\n  const items = [];",
     "  const targets = provider ? [provider] : Object.keys(plugins);\n  const items = [];\n  let isEnd = false;"),
    ("      const r = await p.mod.search(q, page, 'music');\n      const list = (r && r.data) || [];",
     "      const r = await p.mod.search(q, page, 'music');\n      const list = (r && r.data) || [];\n      if (targets.length === 1 && r && typeof r.isEnd === 'boolean') isEnd = r.isEnd;"),
    ("  res.json({ items: out, isEnd: true });",
     "  res.json({ items: out, isEnd: isEnd || out.length === 0 });"),
])

print("done")
