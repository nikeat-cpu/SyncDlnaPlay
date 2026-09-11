/**
 * 插件运行时本地验证器
 * ====================
 * 在 PC 上用真实网络跑一遍插件运行时（不经过 Android），验证：
 *   1. 内置模块垫片是否齐备（cheerio / crypto-js / qs / he / big-integer / iconv-gbk ...）
 *   2. 上游音源插件能否被载入
 *   3. search() 能否真的搜出结果
 *   4. resolve() 能否解析出带 Header 的播放直链
 *
 * 传输层用 Node 的 http/https 直连（Node 没有 CORS 限制），
 * 行为与 App 内经本地代理一致：跟随跳转、解压 gzip、原样返回字节。
 */
'use strict';
const http = require('http');
const https = require('https');
const zlib = require('zlib');
const fs = require('fs');
const path = require('path');

const BUNDLE = path.resolve(__dirname, '..', '..', 'app', 'assets', 'www', 'plugins-runtime.js');
const PLUGIN_DIR = path.resolve(__dirname, 'plugins');

/* --------------------------------------------- 注入 Node 版传输层 */
function nodeRequest(req, depth = 0) {
  return new Promise((resolve, reject) => {
    let u;
    try { u = new URL(req.url); } catch (e) { return reject(new Error('URL 非法: ' + req.url)); }
    const lib = u.protocol === 'https:' ? https : http;
    const headers = {};
    for (const k of Object.keys(req.headers || {})) {
      if (req.headers[k] !== undefined && req.headers[k] !== null) headers[k] = String(req.headers[k]);
    }
    headers['accept-encoding'] = 'gzip, deflate';

    const r = lib.request(u, { method: req.method || 'GET', headers, timeout: req.timeout || 20000 }, (res) => {
      const code = res.statusCode || 0;
      const loc = res.headers.location;
      if (loc && code >= 300 && code < 400 && depth < 6) {
        res.resume();
        const next = new URL(loc, u).toString();
        const nextMethod = (code === 303 || ((code === 301 || code === 302) && req.method === 'POST')) ? 'GET' : req.method;
        return resolve(nodeRequest(Object.assign({}, req, {
          url: next, method: nextMethod, body: nextMethod === 'GET' ? null : req.body,
        }), depth + 1));
      }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        let buf = Buffer.concat(chunks);
        const enc = String(res.headers['content-encoding'] || '').toLowerCase();
        try {
          if (enc.includes('gzip')) buf = zlib.gunzipSync(buf);
          else if (enc.includes('deflate')) buf = zlib.inflateSync(buf);
          else if (enc.includes('br')) buf = zlib.brotliDecompressSync(buf);
        } catch (e) { /* 保持原样 */ }
        const h = Object.assign({}, res.headers);
        delete h['content-encoding'];
        delete h['content-length'];
        delete h['transfer-encoding'];
        delete h['connection'];
        resolve({
          status: code,
          statusText: res.statusMessage || '',
          headers: h,
          bodyBase64: buf.toString('base64'),
          finalUrl: u.toString(),
        });
      });
    });
    r.on('error', (e) => reject(e));
    r.on('timeout', () => { r.destroy(new Error('请求超时: ' + req.url)); });
    if (req.body) r.write(Buffer.from(req.body));
    r.end();
  });
}
globalThis.__PH_TRANSPORT__ = nodeRequest;

/* --------------------------------------------- 载入打包产物 */
if (!fs.existsSync(BUNDLE)) {
  console.error('找不到打包产物，请先执行:  node build.js');
  process.exit(1);
}
const code = fs.readFileSync(BUNDLE, 'utf8');
// eslint-disable-next-line no-new-func
new Function(code)();
const HOST = globalThis.PluginHost;
if (!HOST) {
  console.error('产物里没有暴露 PluginHost');
  process.exit(1);
}

/* --------------------------------------------- 开始验证 */
const KEYWORD = process.env.Q || '周杰伦';
const PROVIDER = process.env.PROVIDER || '';

(async () => {
  console.log('='.repeat(66));
  console.log('插件运行时自检');
  console.log('='.repeat(66));
  const st = HOST.selfTest();
  for (const [k, v] of Object.entries(st.checks)) {
    console.log('  ', (v === 'ok' ? '[ok]  ' : '[!!]  ') + k.padEnd(14), v === 'ok' ? '' : v);
  }

  console.log('\n载入插件 ...');
  const sources = fs.readdirSync(PLUGIN_DIR)
    .filter((f) => f.endsWith('.js'))
    .map((f) => ({ name: f, code: fs.readFileSync(path.join(PLUGIN_DIR, f), 'utf8') }));
  console.log('  待载入:', sources.length, '个文件');
  const r = HOST.loadAll(sources);
  for (const p of r.ok) console.log('  [ok]  ', p.platform, 'v' + p.version, '->', p.methods.join(','));
  for (const f of r.failed) console.log('  [失败]', f.name, '->', f.error);

  if (!r.ok.length) { console.log('\n没有可用插件，退出'); process.exit(2); }

  console.log('\n搜索 "' + KEYWORD + '"' + (PROVIDER ? ' （限 ' + PROVIDER + '）' : '') + ' ...');
  const t0 = Date.now();
  const res = await HOST.search({ q: KEYWORD, page: 1, provider: PROVIDER, limit: 40 });
  console.log('  耗时', Date.now() - t0, 'ms  -> ', res.items.length, '条  isEnd =', res.isEnd);
  for (const e of (res.errors || [])) console.log('  [音源报错]', e.provider, '->', e.error);
  for (const it of res.items.slice(0, 8)) {
    console.log('   -', '[' + it.provider + ']', it.title, '-', it.artist, '(' + it.duration + 's)');
  }

  const first = res.items.find((x) => x.provider);
  if (first) {
    console.log('\n解析直链:', '[' + first.provider + ']', first.title);
    try {
      const ms = await HOST.resolve({ provider: first.provider, id: first.id, quality: 'standard' });
      console.log('  url     :', String(ms.url).slice(0, 120));
      console.log('  headers :', Object.keys(ms.headers).join(',') || '(无)');
      if (ms.headers['Referer'] || ms.headers['referer']) console.log('  Referer :', ms.headers['Referer'] || ms.headers['referer']);
    } catch (e) {
      console.log('  解析失败:', e.message);
    }
  }
  console.log('\n完成。');
})().catch((e) => {
  console.error('验证异常:', e && e.stack || e);
  process.exit(1);
});
