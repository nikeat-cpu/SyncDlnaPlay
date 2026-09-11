# -*- coding: utf-8 -*-
"""v2.8 补丁：
1) 底栏统一 4 字命名
2) 播放模式从正在播放移到播放列表（并删除播放列表 bar 里重复的"随机"按钮）
3) 歌词与封面同台：有歌词显示歌词，无歌词显示封面
4) 边听边下载开关（正在播放页，自动下载当前在线曲目）
5) 关于页加"使用说明（详细教程）"
"""
import io

WWW = "app/assets/www/"

def patch(path, old, new, must=True):
    with io.open(path, encoding="utf-8") as f:
        s = f.read()
    if old not in s:
        if must:
            raise SystemExit("ANCHOR NOT FOUND in %s: %r" % (path, old[:80]))
        print("skip:", path, old[:40])
        return
    assert s.count(old) == 1, "ambiguous anchor in %s: %r" % (path, old[:60])
    s = s.replace(old, new)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    print("ok:", path, "|", old.strip().splitlines()[0][:50])

# ---------- 1. 底栏 4 字命名 ----------
patch(WWW + "index.html", "<span>设备</span>", "<span>我的设备</span>")
patch(WWW + "index.html", "<span>曲库</span>", "<span>本地曲库</span>")
patch(WWW + "index.html", "<span>在线</span>", "<span>在线搜索</span>")
patch(WWW + "index.html", "<span>列表</span>", "<span>播放列表</span>")

# ---------- 2. 播放列表：删重复随机按钮，加模式 chips 容器 ----------
patch(WWW + "index.html",
      '        <button class="btn sm" id="btnQueueShuffle">随机</button>\n',
      "")
patch(WWW + "index.html",
      '      <div id="queueList" class="list"></div>',
      '      <div id="queueModes" class="chips" style="padding:10px 14px 0"></div>\n'
      '      <div id="queueList" class="list"></div>')

# ---------- 3. app.js：TAB_TITLE 4 字 ----------
patch(WWW + "app.js",
      "const TAB_TITLE = { now: '正在播放', devices: '设备', lib: '曲库', online: '在线音乐', queue: '播放列表' };",
      "const TAB_TITLE = { now: '正在播放', devices: '我的设备', lib: '本地曲库', online: '在线搜索', queue: '播放列表' };")

# ---------- 4. nowHTML：封面/歌词同台 + 边听边下载，去掉播放模式 ----------
patch(WWW + "app.js",
      """function nowHTML() {
  const n = nowPlaying();
  const pl = (S.state && S.state.player) || {};
  const t = n.t || {};
  return `
    <div class="np-art">${n.playing ? '♫' : '♪'}</div>""",
      """function nowHTML() {
  const n = nowPlaying();
  const t = n.t || {};
  const adl = autoDlOn();
  return `
    <div class="np-stage">
      <div class="np-art" id="npArt">${n.playing ? '♫' : '♪'}</div>
      <div class="lrc-box np-lrc" id="lyricBox" style="display:none"><div class="empty sm" style="padding:18px">加载歌词…</div></div>
    </div>""")

patch(WWW + "app.js",
      """    <div class="sec-title">歌词</div>
    <div class="lrc-box" id="lyricBox"><div class="empty sm" style="padding:18px">加载中…</div></div>

    <div class="sec-title">播放模式</div>
    <div class="chips">
      <div class="chip ${pl.shuffle ? 'on' : ''}" onclick="queueShuffle()">🔀 随机</div>
      <div class="chip ${pl.repeat === 'all' ? 'on' : ''}" onclick="setRepeat('all')">🔁 列表循环</div>
      <div class="chip ${pl.repeat === 'one' ? 'on' : ''}" onclick="setRepeat('one')">🔂 单曲循环</div>
      <div class="chip ${(!pl.repeat || pl.repeat === 'off') ? 'on' : ''}" onclick="setRepeat('off')">➡ 顺序播放</div>
    </div>
    <div class="sm muted" style="margin-top:10px">切到「手机本机」后，声音从手机的扬声器/耳机出，音响那边会自动停下。</div>""",
      """    <div class="sec-title">边听边下载</div>
    <div class="chips">
      <div class="chip ${adl ? 'on' : ''}" onclick="setAutoDl(${!adl})">⤓ 边听边下载：${adl ? '开' : '关'}</div>
    </div>
    <div class="sm muted" style="margin-top:6px">开启后，正在播放的在线歌曲会自动加入下载队列，存到下载目录（本地歌曲无需下载）。</div>
    <div class="sm muted" style="margin-top:10px">切到「手机本机」后，声音从手机的扬声器/耳机出，音响那边会自动停下。</div>""")

# ---------- 5. renderLyric：无词显示封面 ----------
patch(WWW + "app.js",
      """function renderLyric() {
  const box = $('lyricBox');
  if (!box) return;
  const L = S.lyric;
  if (!L.lines.length) {
    box.innerHTML = '<div class="empty sm" style="padding:18px">' + esc(L.msg || '暂无歌词') + '</div>';
    return;
  }
  box.innerHTML = L.lines.map(function (l, i) {""",
      """function renderLyric() {
  const box = $('lyricBox');
  if (!box) return;
  const L = S.lyric;
  const art = $('npArt');
  if (!L.lines.length) {
    // 没歌词 → 封面回归
    if (art) art.style.display = '';
    box.style.display = 'none';
    box.innerHTML = '<div class="empty sm" style="padding:18px">' + esc(L.msg || '暂无歌词') + '</div>';
    return;
  }
  // 有歌词 → 歌词替代封面（同台合并）
  if (art) art.style.display = 'none';
  box.style.display = '';
  box.innerHTML = L.lines.map(function (l, i) {""")

# ---------- 6. 模式 chips + 边听边下载逻辑 ----------
patch(WWW + "app.js",
      "function renderQueue() {",
      """/* 播放模式 chips（v2.8 从正在播放移到播放列表） */
function modeChipsHTML(pl) {
  return `
    <div class="chip ${pl.shuffle ? 'on' : ''}" onclick="queueShuffle()">🔀 随机</div>
    <div class="chip ${pl.repeat === 'all' ? 'on' : ''}" onclick="setRepeat('all')">🔁 列表循环</div>
    <div class="chip ${pl.repeat === 'one' ? 'on' : ''}" onclick="setRepeat('one')">🔂 单曲循环</div>
    <div class="chip ${(!pl.repeat || pl.repeat === 'off') ? 'on' : ''}" onclick="setRepeat('off')">➡ 顺序播放</div>`;
}

/* ---- 边听边下载（v2.8） ---- */
function autoDlOn() {
  try { return localStorage.getItem('dlna_audiodl') === '1'; } catch (e) { return false; }
}
function setAutoDl(on) {
  try { localStorage.setItem('dlna_audiodl', on ? '1' : '0'); } catch (e) { }
  toast(on ? '边听边下载：开' : '边听边下载：关', 'ok');
  if (on) autoDlMaybe(nowPlaying().t);
  if (S.tab === 'now') renderNowTab();
}
function autoDlMaybe(t) {
  if (!autoDlOn() || !t) return;
  if (t.source !== 'online') return;              // 本地歌曲已在手机里
  if (!t.provider || !(t.id || t.oid)) return;    // 缺元数据，静默跳过
  const key = trackKeyOf(t);
  S._dlKeys = S._dlKeys || {};
  if (!key || S._dlKeys[key]) return;             // 本次会话已下过
  if (S.dlBusy) {                                 // 解析中 → 稍后重试一次
    if (!t.__adlRetry) { t.__adlRetry = 1; setTimeout(function () { autoDlMaybe(t); }, 20000); }
    return;
  }
  S._dlKeys[key] = 1;
  doDownload([{ provider: t.provider, id: t.oid || t.id, title: t.title, artist: t.artist, duration_sec: t.duration_sec || 0 }]);
}

function renderQueue() {""")

patch(WWW + "app.js",
      """  const box = $('queueList');
  const pl = (S.state && S.state.player) || {};""",
      """  const box = $('queueList');
  const pl = (S.state && S.state.player) || {};
  const qm = $('queueModes');
  if (qm) qm.innerHTML = modeChipsHTML(pl);""")

# 删除已失效的 btnQueueShuffle 监听
patch(WWW + "app.js",
      "  $('btnQueueShuffle').addEventListener('click', queueShuffle);\n", "")

# ---------- 7. tick：切歌时触发自动下载 ----------
patch(WWW + "app.js",
      "    S.posRef = { pos: rawPos, at: performance.now(), playing: !!plr.playing };",
      """    S.posRef = { pos: rawPos, at: performance.now(), playing: !!plr.playing };
    const _nk = trackKeyOf(nowPlaying().t);
    if (_nk && _nk !== S._autoDlKey) { S._autoDlKey = _nk; autoDlMaybe(nowPlaying().t); }""")

# ---------- 8. 关于页：使用说明入口 + helpSheet ----------
patch(WWW + "app.js",
      """    <div class="chips" style="margin-top:12px">
      <div class="chip" onclick="AB&&AB.exitApp&&AB.exitApp()">退出应用</div>
    </div>""",
      """    <div class="chips" style="margin-top:12px">
      <div class="chip" onclick="helpSheet()">📖 使用说明（详细教程）</div>
    </div>
    <div class="chips" style="margin-top:8px">
      <div class="chip" onclick="AB&&AB.exitApp&&AB.exitApp()">退出应用</div>
    </div>""")

patch(WWW + "app.js",
      "/* --- 原生端回调 --- */",
      """/* ---- 使用说明（详细教程，v2.8） ---- */
function helpSheet() {
  const H = [];
  H.push('<div class="help">');
  const sec = (t, body) => H.push('<div class="sec-title">' + t + '</div>' + body);
  const p = (x) => '<div class="sm" style="margin:4px 0;line-height:1.75">' + x + '</div>';
  const li = (x) => '<div class="sm" style="margin:3px 0 3px 10px;line-height:1.7">· ' + x + '</div>';

  H.push('<div class="sm" style="line-height:1.8">SyncDlnaPlay 是一款<strong>完全运行在手机上</strong>的音乐播放与 DLNA 投放工具：手机本机放歌、把歌投到局域网里的 DLNA 音响、扫描本地与 SMB 网络曲库、在线搜索并下载歌曲。不需要家里架设任何服务器，换 Wi-Fi、用流量热点都能用。</div>');

  sec('🚀 快速上手（3 步）',
    p('<strong>① 连音响：</strong>底部「我的设备」→ 点「扫描」，发现的音响会列出，点一下选中（可多选多台同时响）。')
    + p('<strong>② 选歌：</strong>「本地曲库」放手机里的歌；「在线搜索」搜网上的歌，点 ＋ 加入播放列表。')
    + p('<strong>③ 开播：</strong>在「播放列表」点歌即播。声音从哪出由「正在播放」页的「输出方式」决定：音响 or 手机。')
    + p('<span style="color:var(--cy)">小提示：如果局域网里没发现任何音响，播放会自动回落到手机本机，不会卡在"播放不了"。</span>'));

  sec('▶ 正在播放',
    li('<strong>封面 / 歌词：</strong>有歌词时封面位置直接显示滚动歌词，点任意一句可跳转到那句；没有歌词时显示唱片封面。')
    + li('<strong>进度条：</strong>可拖动；投音响时进度按本机时钟平滑外推，歌词和进度都跟手。')
    + li('<strong>输出方式：</strong>「🔊 音响播放」把声音投到选中的 DLNA 音响；「📱 手机本机」用手机扬声器/耳机放。切换时另一边会自动停。')
    + li('<strong>边听边下载：</strong>打开开关后，每播一首在线歌曲就自动加入下载队列，存到下载目录（默认 Music/音响管家，文件管理器可见）。本地歌曲不重复下载，同一首每次会话只下一次。'));

  sec('📡 我的设备',
    li('<strong>扫描：</strong>自动发现局域网里的 DLNA/UPnP 音响（斐讯音箱、小爱、电视等）。')
    + li('<strong>多选：</strong>可同时勾选多台，组成同步播放组。')
    + li('<strong>SMB 面板：</strong>「扫描局域网」自动找开 445 端口的 NAS/路由器；「浏览共享」逐层点进共享文件夹，选中的目录会加入本地曲库，不用手记路径。'));

  sec('💽 本地曲库',
    li('自动扫描手机存储里的音频（MediaStore，无需手动刷新）。')
    + li('「曲库管理」里可添加多个音乐目录：设备存储文件夹、SMB 网络共享都可以。')
    + li('每首歌右侧按钮：＋ 加入播放列表、⤓ 下载/查看。')
    + li('下载目录可在「曲库管理 → 下载目录」里用系统文件夹选择器任改（含 SD 卡/U 盘）。'));

  sec('🌐 在线搜索',
    li('内置多个 MusicFree 社区音源（元力系列等），支持关键词搜索与翻页。')
    + li('<strong>音源管理：</strong>点搜索框旁的管理入口 → 可「停用/启用」内置音源，也能添加自己的音源：<strong>粘贴插件链接 URL</strong>、<strong>粘贴插件源码/分享码</strong>、或<strong>从文件导入 .js</strong>。')
    + li('<strong>默认音源：</strong>在音源管理里点 ★ 星标设为默认。')
    + li('<strong>记住上次音源：</strong>每次搜索会记住所用音源，下次打开自动就是它。')
    + li('时长小于 1 分钟的试听片段会在下载预检时自动跳过。'));

  sec('📋 播放列表',
    li('点歌曲行任意位置即跳播；右侧 × 可从列表移除；「清空」一键清空。')
    + li('<strong>播放模式（v2.8 起在这里设置）：</strong>🔀 随机、🔁 列表循环、🔂 单曲循环、➡ 顺序播放。'));

  sec('📥 下载的文件在哪',
    p('默认保存在手机公共目录 <strong>Music/音响管家/</strong>，按「歌手/歌手 - 歌名」命名，任何文件管理器都能看到。下载状态可在「设置 → 下载状态」查看进度与失败原因。'));

  sec('❓ 常见问题',
    li('<strong>扫描不到音响？</strong>确认手机和音响在同一 Wi-Fi；部分路由器开了 AP 隔离会屏蔽发现协议。找不到也没关系，会自动用手机本机播放。')
    + li('<strong>在线歌解析失败 / 下载失败？</strong>第三方音源接口偶尔不稳定，换个音源或稍后再试。')
    + li('<strong>这首歌没有歌词？</strong>在线歌词取决于音源是否提供；本地歌请在同目录放同名 .lrc 文件（支持 UTF-8/GBK）。')
    + li('<strong>SMB 连不上？</strong>检查用户名/密码、共享名大小写，以及 NAS 是否允许来宾访问。')
    + li('<strong>耗电与后台？</strong>本 App 只在你使用时工作；下拉通知栏的常驻通知用于保持后台播放不被系统杀掉。'));

  H.push('</div>');
  openSheet('使用说明', H.join(''));
}

/* --- 原生端回调 --- */""")

# ---------- 9. app.css：舞台样式 ----------
with io.open(WWW + "app.css", encoding="utf-8") as f:
    css = f.read()
css += """
/* ===== v2.8 封面/歌词同台 ===== */
.np-stage{position:relative;width:100%;max-width:272px;aspect-ratio:1/1;margin:8px auto 20px}
.np-stage .np-art{margin:0;max-width:none;width:100%;height:100%}
.np-lrc{
  position:absolute;inset:0;width:100%;height:100%;overflow-y:auto;border-radius:18px;
  background:linear-gradient(160deg,rgba(12,23,38,.94),rgba(6,11,20,.94));
  box-shadow:0 0 0 1px rgba(34,230,255,.35),0 0 26px rgba(34,230,255,.16),inset 0 0 40px rgba(34,230,255,.05);
  padding:16px 14px;text-align:center;scrollbar-width:none;
}
.np-lrc::-webkit-scrollbar{width:0}
"""
with io.open(WWW + "app.css", "w", encoding="utf-8", newline="") as f:
    f.write(css)
print("ok: app.css appended")

print("ALL DONE")
