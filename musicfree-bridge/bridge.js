'use strict';
/**
 * musicfree-bridge
 * ----------------
 * 在服务器端加载 MusicFree 插件（CommonJS .js），把"在线播放"能力暴露给
 * dlna-speaker。因为 DLNA 渲染器（斐讯音响）无法在请求里带自定义 Header，
 * 而各音源直链常需要 Referer/Cookie/UA，所以这里必须做一层代理：
 *   - /search   跨插件搜索，返回统一结构的曲目列表
 *   - /resolve  解析某首歌的直链 + 所需 Header（带 TTL 缓存）
 *   - /stream   音响真正拉取的地址：本服务带 Header 去抓真实音频再回灌
 *
 * 曲目缓存落盘（DATA_DIR/items.json），即使本服务重启，已搜索过的歌仍能解析。
 */

const express = require('express');
const path = require('path');
const fs = require('fs');
const axios = require('axios');

const PLUGINS_DIR = process.env.PLUGINS_DIR || '/plugins';
const DATA_DIR = process.env.DATA_DIR || '/data';
const MUSIC_DIR = process.env.MUSIC_DIR || '/music';   // 下载保存目录（按歌手分文件夹）
const PORT = parseInt(process.env.PORT || '5001', 10);
const RESOLVE_TTL = (parseInt(process.env.RESOLVE_TTL || '300', 10)) * 1000; // 直链缓存 5 分钟
const ITEMS_FILE = path.join(DATA_DIR, 'items.json');

// Node 18 兼容性：部分 MusicFree 插件使用浏览器全局 File（Node 20+ 才内置）
if (typeof globalThis.File === 'undefined') {
  const NodeBlob = globalThis.Blob || require('buffer').Blob;
  globalThis.File = class File extends NodeBlob {
    constructor(bits, name, options = {}) {
      super(bits, options);
      this.name = String(name);
      this.lastModified = options.lastModified ?? Date.now();
    }
    get [Symbol.toStringTag]() { return 'File'; }
  };
}

// 让 /plugins 下的插件能解析到 /app/node_modules 的依赖（宿主机挂载卷里没有 node_modules）
try {
  const nmLink = path.join(PLUGINS_DIR, 'node_modules');
  if (!fs.existsSync(nmLink)) fs.symlinkSync(path.join(process.cwd(), 'node_modules'), nmLink);
} catch (e) { /* 已存在或权限不足则忽略 */ }


const app = express();
app.use(express.json());

let plugins = {};                 // platform -> { mod, platform, version, methods }
const itemCache = new Map();      // "provider::id" -> musicItem（内存 + 磁盘双写）
const resolveCache = new Map();   // "provider::id::quality" -> { url, headers, expires }

// ---------------------------------------------------------------- 磁盘缓存
function loadItems() {
  try {
    if (fs.existsSync(ITEMS_FILE)) {
      const arr = JSON.parse(fs.readFileSync(ITEMS_FILE, 'utf8'));
      for (const [k, v] of Object.entries(arr)) itemCache.set(k, v);
      console.log('已从磁盘恢复', itemCache.size, '条曲目缓存');
    }
  } catch (e) { console.log('items load err', e.message); }
}
function saveItems() {
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    const obj = {};
    for (const [k, v] of itemCache) obj[k] = v;
    fs.writeFileSync(ITEMS_FILE, JSON.stringify(obj));
  } catch (e) { console.log('items save err', e.message); }
}

// ---------------------------------------------------------------- 插件加载
async function loadOne(full) {
  // 优先 CommonJS；遇到 ESM 则回退到动态 import（兼容少数 ESM 插件）
  try {
    delete require.cache[require.resolve(full)];
    return require(full);
  } catch (e) {
    if (e && e.code === 'ERR_REQUIRE_ESM') {
      const m = await import(full);
      return (m.default && (m.default.platform || m.default.name)) ? m.default : m;
    }
    throw e;
  }
}

async function loadPlugins() {
  plugins = {};
  if (!fs.existsSync(PLUGINS_DIR)) { console.log('插件目录不存在:', PLUGINS_DIR); return; }
  for (const f of fs.readdirSync(PLUGINS_DIR)) {
    if (!f.endsWith('.js')) continue;
    const full = path.join(PLUGINS_DIR, f);
    try {
      const mod = await loadOne(full);
      const platform = mod && (mod.platform || mod.name);
      if (!platform) { console.log('跳过(无 platform):', f); continue; }
      const methods = [];
      if (typeof mod.search === 'function') methods.push('search');
      if (typeof mod.getMediaSource === 'function') methods.push('getMediaSource');
      if (typeof mod.getLyric === 'function') methods.push('getLyric');
      if (typeof mod.getAlbumInfo === 'function') methods.push('getAlbumInfo');
      plugins[platform] = { mod, platform, version: mod.version || '?', methods };
      console.log('已加载插件:', platform, '(' + methods.join(',') + ')');
    } catch (e) {
      console.log('加载失败', f, '->', e.message);
    }
  }
}

// ---------------------------------------------------------------- 路由
app.get('/plugins', (req, res) => {
  res.json(Object.values(plugins).map(p => ({
    platform: p.platform, version: p.version, methods: p.methods,
  })));
});

app.get('/search', async (req, res) => {
  const q = (req.query.q || '').trim();
  const page = parseInt(req.query.page || '1', 10);
  const provider = req.query.provider || '';
  const limit = Math.max(0, parseInt(req.query.limit || '0', 10) || 0);
  if (!q) return res.json({ items: [] });
  const targets = provider ? [provider] : Object.keys(plugins);
  const items = [];
  let isEnd = false;
  for (const name of targets) {
    const p = plugins[name];
    if (!p || typeof p.mod.search !== 'function') continue;
    try {
      const r = await p.mod.search(q, page, 'music');
      const list = (r && r.data) || [];
      if (targets.length === 1 && r && typeof r.isEnd === 'boolean') isEnd = r.isEnd;
      for (const it of list) {
        const id = name + '::' + it.id;
        itemCache.set(id, it);
        items.push({
          id, provider: name,
          title: it.title || it.name || '未知',
          artist: it.artist || '',
          album: it.album || '',
          artwork: it.artwork || it.cover || '',
          duration: it.duration || 0,
          providerLabel: name,
        });
      }
    } catch (e) { console.log('search err', name, e.message); }
  }
  if (items.length) saveItems();
  const out = limit > 0 ? items.slice(0, limit) : items;
  res.json({ items: out, isEnd: isEnd || out.length === 0 });
});

async function resolve(provider, id, quality) {
  // id 已是 "provider::rawid" 形式的完整缓存键（由 /search 返回）
  const key = id;
  const cacheKey = key + '::' + (quality || 'standard');
  const cached = resolveCache.get(cacheKey);
  if (cached && cached.expires > Date.now()) return cached;
  const p = plugins[provider];
  if (!p) throw new Error('未知音源: ' + provider);
  let item = itemCache.get(key);
  if (!item) { // 内存没有则尝试磁盘
    try {
      const arr = JSON.parse(fs.readFileSync(ITEMS_FILE, 'utf8'));
      item = arr[key];
    } catch (e) {}
  }
  if (!item) throw new Error('未找到曲目缓存(请先搜索): ' + key);
  const ms = await p.mod.getMediaSource(item, quality || 'standard');
  if (!ms || !ms.url) throw new Error('未返回播放地址');
  const headers = Object.assign({}, ms.headers || {});
  if (ms.userAgent && !headers['User-Agent']) headers['User-Agent'] = ms.userAgent;
  if (ms.cookie) headers['Cookie'] = (headers['Cookie'] ? headers['Cookie'] + '; ' : '') + ms.cookie;
  const out = { url: ms.url, headers, expires: Date.now() + RESOLVE_TTL };
  resolveCache.set(cacheKey, out);
  return out;
}

app.get('/resolve', async (req, res) => {
  try {
    const r = await resolve(req.query.provider, req.query.id, req.query.quality);
    res.json(r);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// 音响真正拉取的音频流：带 Header 抓取真实音频再回灌，并透传 Range
app.get('/stream', async (req, res) => {
  const { provider, id, quality } = req.query;
  if (!provider || !id) return res.status(400).send('missing provider/id');
  try {
    const { url, headers } = await resolve(provider, id, quality);
    const upstreamHeaders = Object.assign({}, headers);
    if (req.headers.range) upstreamHeaders['Range'] = req.headers.range;
    const upstream = await axios({
      method: 'get', url, headers: upstreamHeaders,
      responseType: 'stream', timeout: 30000,
    });
    const out = {};
    const ct = upstream.headers['content-type'];
    if (ct) out['Content-Type'] = ct;
    if (upstream.headers['content-length']) out['Content-Length'] = upstream.headers['content-length'];
    if (upstream.headers['accept-ranges']) out['Accept-Ranges'] = upstream.headers['accept-ranges'];
    if (upstream.headers['content-range']) out['Content-Range'] = upstream.headers['content-range'];
    out['Cache-Control'] = 'no-cache';
    out['Connection'] = 'close';
    res.status(upstream.status);
    for (const k in out) res.setHeader(k, out[k]);
    upstream.data.pipe(res);
    req.on('close', () => { try { upstream.data.destroy(); } catch (e) {} });
  } catch (e) {
    console.log('stream err', provider, id, e.message);
    if (!res.headersSent) res.status(502).send('stream error: ' + e.message);
    else try { res.destroy(); } catch (_) {}
  }
});

app.post('/reload', async (req, res) => {
  await loadPlugins();
  res.json({ ok: true, plugins: Object.keys(plugins) });
});

// ---------------------------------------------------------------- 下载（按歌手分目录，落盘到 MUSIC_DIR）
const dlJobs = [];        // 最近任务列表（新的在前，最多保留 200 条）
const dlKeys = new Map(); // key(provider::rawid) -> job，去重（进行中/已完成不再重复下）
let dlActive = null;      // 当前正在下载的任务（串行，避免打爆音源）

function sanitizeName(s, fallback) {
  let n = String(s || '').replace(/[\\/:*?"<>|\x00-\x1f]/g, ' ').replace(/\s+/g, ' ').trim();
  if (!n) n = fallback || '未知';
  return n.slice(0, 80);
}

function pickExt(url, contentType) {
  const m = String(url).split('?')[0].match(/\.(mp3|flac|m4a|aac|ogg|wav|ape)$/i);
  if (m) return m[1].toLowerCase();
  const ct = String(contentType || '').toLowerCase();
  if (ct.includes('flac')) return 'flac';
  if (ct.includes('mp4') || ct.includes('m4a')) return 'm4a';
  if (ct.includes('ogg')) return 'ogg';
  if (ct.includes('wav')) return 'wav';
  if (ct.includes('aac')) return 'aac';
  return 'mp3';
}

async function runDlQueue() {
  if (dlActive) return;
  for (;;) {
    const job = dlJobs.find(j => j.status === 'pending');
    if (!job) break;
    dlActive = job;
    job.status = 'downloading';
    try {
      const { url, headers } = await resolve(job.provider, job.id, 'standard');
      const artist = sanitizeName(job.artist, '未知歌手');
      const baseDir = job.target_dir || MUSIC_DIR;   // 由 dlna-speaker 按"当前音乐源"下发
      const dir = path.join(baseDir, artist);
      fs.mkdirSync(dir, { recursive: true });
      const upstream = await axios({ method: 'get', url, headers, responseType: 'stream', timeout: 30000 });
      const ext = pickExt(url, upstream.headers['content-type']);
      const file = path.join(dir, sanitizeName(artist + ' - ' + job.title) + '.' + ext);
      job.file = file;
      if (fs.existsSync(file)) {   // 已下载过：跳过
        job.status = 'exists'; job.size = fs.statSync(file).size;
        upstream.data.destroy();
      } else {
        const tmp = file + '.part';
        await new Promise((res2, rej2) => {
          const ws = fs.createWriteStream(tmp);
          let bytes = 0;
          upstream.data.on('data', c => { bytes += c.length; job.size = bytes; });
          upstream.data.on('error', rej2);
          ws.on('error', rej2);
          upstream.data.pipe(ws);
          ws.on('finish', res2);
        });
        fs.renameSync(tmp, file);
        job.status = 'done';
        job.size = fs.statSync(file).size;
        // 下载完成后检查：文件 < 1MB（约 128kbps × 60s）视为试听片段，自动删除
        if (job.size < 1 * 1024 * 1024) {
          fs.unlinkSync(file);
          job.status = 'exists';  // 复用 exists 表示"已处理但文件太小"
          console.log('试听片段（<1MB），已删除:', file, job.size, 'bytes');
        } else {
          console.log('已下载:', file, job.size, 'bytes');
        }
      }
    } catch (e) {
      job.status = 'error'; job.error = e.message;
      console.log('下载失败', job.key, '->', e.message);
      if (job.file) { try { fs.unlinkSync(job.file + '.part'); } catch (_) {} }
    } finally { dlActive = null; }
  }
}

// 批量加入下载队列：body { items: [{provider,id,title,artist}] }
app.post('/download', async (req, res) => {
  const items = (req.body && req.body.items) || [];
  if (!items.length) return res.status(400).json({ error: 'no items' });
  const targetDir = ((req.body && req.body.target_dir) || '').trim();
  let queued = 0, exists = 0;
  for (const it of items) {
    if (!it.provider || !it.id) continue;
    const key = it.id;   // 已是 provider::rawid 完整键
    const prev = dlKeys.get(key);
    if (prev && prev.status !== 'error') { exists++; continue; }  // 排队中/已完成/已存在 → 跳过；失败可重试
    const dur = parseInt(it.duration_sec || it.duration || 0, 10) || 0;
    if (dur > 0 && dur < 60) { exists++; continue; }  // 时长已知且 < 60s：跳过（试听片段/广告）
    const job = { key, provider: it.provider, id: it.id, title: it.title || '未知', artist: it.artist || '', status: 'pending', size: 0, ts: Date.now() };
    if (targetDir) job.target_dir = targetDir;
    dlKeys.set(key, job);
    dlJobs.unshift(job);
    queued++;
  }
  if (dlJobs.length > 200) {
    for (const old of dlJobs.splice(200)) if (dlKeys.get(old.key) === old) dlKeys.delete(old.key);
  }
  res.json({ ok: true, queued, exists });
  runDlQueue().catch(e => console.log('dl queue err', e.message));
});

app.get('/downloads', (req, res) => {
  res.json({ ok: true, active: dlActive ? dlActive.title : null, jobs: dlJobs.slice(0, 50) });
});

app.post('/downloads/clear', (req, res) => {
  const keep = dlJobs.filter(j => j.status === 'pending' || j.status === 'downloading');
  dlKeys.clear();
  for (const j of keep) dlKeys.set(j.key, j);
  dlJobs.length = 0;
  dlJobs.push(...keep);
  res.json({ ok: true, kept: keep.length });
});

// ---------------------------------------------------------------- 启动
(async () => {
  loadItems();
  await loadPlugins();
  app.listen(PORT, '0.0.0.0', () => console.log('musicfree-bridge listening on', PORT));
})();
