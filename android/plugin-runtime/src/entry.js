/**
 * 插件运行时入口
 * ==============
 * 把 MusicFree 插件（CommonJS）跑在 Android WebView 里，替代原来服务器上的
 * Node 版 musicfree-bridge。对外只暴露一个 window.PluginHost。
 *
 * 行为对齐 bridge.js：
 *   - search(provider, q, page) -> { items:[{id,provider,title,artist,...}], isEnd }
 *   - 曲目原始对象缓存在内存，用 "provider::原始id" 作键，供 getMediaSource 回查
 *   - getMediaSource -> { url, headers }（headers 已含 User-Agent / Cookie）
 */

import { Buffer } from 'buffer';
import * as cheerioNS from 'cheerio';
import CryptoJS from 'crypto-js';
import he from 'he';
import qs from 'qs';
import dayjs from 'dayjs';
import bigInt from 'big-integer';
import pako from 'pako';
import * as jsBase64NS from 'js-base64';

import { createAxios, setProxyBase, transport } from './http.js';
import iconv from './iconv.js';

const RUNTIME_VERSION = '1.0.0';

/* ------------------------------------------------------------- 全局垫片 */

function installGlobals() {
  const g = globalThis;
  if (typeof g.Buffer === 'undefined') g.Buffer = Buffer;
  if (typeof g.global === 'undefined') g.global = g;

  if (typeof g.process === 'undefined') {
    const tick = (fn, ...a) => setTimeout(() => fn(...a), 0);
    g.process = {
      env: {}, argv: ['node', 'plugin'], version: 'v18.0.0', versions: { node: '18.0.0' },
      platform: 'android', arch: 'arm64', browser: true, title: 'webview',
      nextTick: tick, cwd: () => '/', chdir: () => {},
      on: () => {}, once: () => {}, off: () => {}, emit: () => false,
      exit: () => {}, uptime: () => 0, hrtime: () => [0, 0],
      memoryUsage: () => ({ rss: 0, heapTotal: 0, heapUsed: 0 }),
    };
  }
  // 少数插件会用 process.nextTick
  if (typeof g.process.nextTick !== 'function') {
    g.process.nextTick = (fn, ...a) => setTimeout(() => fn(...a), 0);
  }
  if (typeof g.setImmediate === 'undefined') {
    g.setImmediate = (fn, ...a) => setTimeout(() => fn(...a), 0);
    g.clearImmediate = (id) => clearTimeout(id);
  }
}

installGlobals();

/* --------------------------------------------------------- 模块注册表 */

const axios = createAxios();

function withDefault(mod) {
  if (mod == null || typeof mod !== 'object') return mod;
  if (mod.__esModule && mod.default) return mod;
  const out = Array.isArray(mod) ? mod.slice() : Object.assign({}, mod);
  try {
    Object.defineProperty(out, '__esModule', { value: true, enumerable: false });
    Object.defineProperty(out, 'default', { value: mod, enumerable: false });
  } catch (e) { /* 冻结对象则忽略 */ }
  return out;
}

const cheerioMod = withDefault(cheerioNS);
const base64Mod = withDefault(jsBase64NS);

const REGISTRY = {
  'axios': axios,
  'cheerio': cheerioMod,
  'cheerio/slim': withDefault(cheerioNS),
  'crypto-js': withDefault(CryptoJS),
  'he': withDefault(he),
  'qs': withDefault(qs),
  'dayjs': withDefault(dayjs),
  'big-integer': withDefault(bigInt),
  'pako': withDefault(pako),
  'js-base64': base64Mod,
  'buffer': withDefault({ Buffer, SlowBuffer: Buffer, INSPECT_MAX_BYTES: 50 }),
  'iconv-lite': iconv,
  'string_decoder': withDefault({
    StringDecoder: class StringDecoder {
      constructor(enc) { this.encoding = (enc || 'utf8').toLowerCase(); this._buf = new Uint8Array(0); }
      write(buf) { this._buf = iconv.toUint8(buf); return iconv.decode(this._buf, this.encoding); }
      end() { const s = iconv.decode(this._buf, this.encoding); this._buf = new Uint8Array(0); return s; }
    },
  }),
  'events': withDefault({
    EventEmitter: class EventEmitter {
      constructor() { this._e = {}; }
      on(n, f) { (this._e[n] = this._e[n] || []).push(f); return this; }
      once(n, f) { const w = (...a) => { this.off(n, w); f(...a); }; return this.on(n, w); }
      off(n, f) { const l = this._e[n] || []; const i = l.indexOf(f); if (i >= 0) l.splice(i, 1); return this; }
      removeListener(n, f) { return this.off(n, f); }
      emit(n, ...a) { (this._e[n] || []).slice().forEach((f) => f(...a)); return true; }
      setMaxListeners() { return this; }
    },
  }),
};

/* ---------------------------------------------------------- 插件加载 */

const plugins = new Map();      // platform -> { platform, version, methods, mod, file }
const itemCache = new Map();    // "platform::rawId" -> 原始曲目对象

function makeRequire(fileName) {
  return function require(name) {
    if (Object.prototype.hasOwnProperty.call(REGISTRY, name)) return REGISTRY[name];
    if (name.startsWith('.')) {
      throw new Error('插件 ' + fileName + ' 引用了相对路径模块 ' + name + '（App 内不支持多文件插件）');
    }
    throw new Error('插件 ' + fileName + ' 需要未内置的模块: ' + name);
  };
}

/** 载入一个插件源码，返回其 module.exports */
function runPluginSource(fileName, code) {
  const module = { exports: {} };
  const require = makeRequire(fileName);
  // 插件是 CommonJS：用 Function 包一层，注入 require/module/exports
  const factory = new Function(
    'require', 'module', 'exports', '__filename', '__dirname',
    code + '\n//# sourceURL=plugin://' + fileName + '\n'
  );
  factory(require, module, module.exports, fileName, '/plugins/' + (fileName || ''));
  return module.exports;
}

function describe(fileName, mod) {
  const platform = mod && (mod.platform || mod.name);
  if (!platform) return null;
  const methods = [];
  for (const m of ['search', 'getMediaSource', 'getLyric', 'getAlbumInfo',
                   'getTopLists', 'getTopListDetail', 'getArtistWorks',
                   'getMusicSheetInfo', 'getRecommendSheetsByTag']) {
    if (typeof mod[m] === 'function') methods.push(m);
  }
  return {
    file: fileName,
    platform: String(platform),
    version: String((mod && mod.version) || '?'),
    methods,
    mod,
  };
}

/* --------------------------------------------------------- 对外 API */

const host = {
  version: RUNTIME_VERSION,
  ready: false,

  /** 设定本地服务地址（代理出口） */
  configure(opts) {
    if (opts && opts.proxyBase) setProxyBase(opts.proxyBase);
    return host;
  },

  /**
   * 载入插件集合
   * @param {Array<{name:string, code:string}>} sources
   */
  loadAll(sources) {
    plugins.clear();
    itemCache.clear();
    const failed = [];
    const ok = [];
    for (const s of (sources || [])) {
      try {
        const mod = runPluginSource(s.name, s.code);
        const info = describe(s.name, mod);
        if (!info) { failed.push({ name: s.name, error: '没有 platform 字段' }); continue; }
        plugins.set(info.platform, info);
        ok.push({ platform: info.platform, version: info.version, methods: info.methods });
      } catch (e) {
        failed.push({ name: s.name, error: String((e && e.message) || e) });
      }
    }
    host.ready = true;
    return { ok, failed };
  },

  list() {
    return [...plugins.values()].map((p) => ({
      platform: p.platform, version: p.version, methods: p.methods, file: p.file,
    }));
  },

  has(platform) { return plugins.has(platform); },

  /**
   * 跨插件搜索（对齐 bridge.js 的 /search）
   * @returns {Promise<{items:Array, isEnd:boolean, errors:Array}>}
   */
  async search(opts) {
    const o = typeof opts === 'string' ? { q: opts } : (opts || {});
    const q = String(o.q || '').trim();
    const page = parseInt(o.page || 1, 10) || 1;
    const type = o.type || 'music';
    const limit = Math.max(0, parseInt(o.limit || 0, 10) || 0);
    if (!q) return { items: [], isEnd: true, errors: [] };

    const targets = o.provider ? [o.provider] : [...plugins.keys()];
    const items = [];
    const errors = [];
    let isEnd = false;

    for (const name of targets) {
      const p = plugins.get(name);
      if (!p || typeof p.mod.search !== 'function') continue;
      try {
        const r = await p.mod.search(q, page, type);
        const list = (r && r.data) || [];
        if (targets.length === 1 && r && typeof r.isEnd === 'boolean') isEnd = r.isEnd;
        for (const it of list) {
          if (!it || it.id === undefined) continue;
          const id = name + '::' + it.id;
          itemCache.set(id, it);
          items.push({
            id,
            provider: name,
            providerLabel: name,
            title: it.title || it.name || '未知',
            artist: it.artist || '',
            album: it.album || '',
            artwork: it.artwork || it.cover || '',
            duration: it.duration || 0,
            duration_sec: parseInt(it.duration || 0, 10) || 0,
          });
        }
      } catch (e) {
        errors.push({ provider: name, error: String((e && e.message) || e) });
      }
    }

    const out = limit > 0 ? items.slice(0, limit) : items;
    return { items: out, isEnd: isEnd || out.length === 0, errors };
  },

  /** 取回某条曲目的原始对象 */
  rawItem(id) { return itemCache.get(id) || null; },

  /** 记住一个原始曲目（供外部导入的曲目复用） */
  remember(id, raw) { itemCache.set(id, raw); },

  /**
   * 解析播放直链（对齐 bridge.js 的 /resolve）
   * @returns {Promise<{url:string, headers:Object}>}
   */
  async resolve(opts) {
    const o = opts || {};
    const provider = o.provider;
    const id = o.id;
    const quality = o.quality || 'standard';
    const p = plugins.get(provider);
    if (!p) throw new Error('未知音源: ' + provider);
    if (typeof p.mod.getMediaSource !== 'function') {
      throw new Error(provider + ' 不支持解析播放地址');
    }
    const raw = itemCache.get(id);
    if (!raw) throw new Error('曲目缓存已失效，请重新搜索');
    const ms = await p.mod.getMediaSource(raw, quality);
    if (!ms || !ms.url) throw new Error('未返回播放地址');
    const headers = Object.assign({}, ms.headers || {});
    if (ms.userAgent && !headers['User-Agent'] && !headers['user-agent']) {
      headers['User-Agent'] = ms.userAgent;
    }
    if (ms.cookie) {
      headers['Cookie'] = (headers['Cookie'] || headers['cookie'])
        ? (headers['Cookie'] || headers['cookie']) + '; ' + ms.cookie
        : ms.cookie;
    }
    return { url: ms.url, headers };
  },

  /**
   * 取歌词。这是**可选能力** —— 有的音源没实现 getLyric，返回空串即可，
   * 不能因此报错打断播放。
   * @returns {Promise<{lrc:string, error?:string}>}
   */
  async lyric(opts) {
    const o = opts || {};
    const p = plugins.get(o.provider);
    if (!p || typeof p.mod.getLyric !== 'function') return { lrc: '' };
    const raw = itemCache.get(o.id);
    if (!raw) return { lrc: '', error: '曲目缓存已失效' };
    try {
      const r = await p.mod.getLyric(raw, o.quality || 'standard');
      let lrc = (r && (r.rawLrc || r.lyric || r.lrc)) || '';
      if (typeof lrc !== 'string') lrc = '';
      return { lrc };
    } catch (e) {
      return { lrc: '', error: String((e && e.message) || e) };
    }
  },

  /** 透传调用插件的其它方法（专辑/歌手等） */
  async call(provider, method, ...args) {
    const p = plugins.get(provider);
    if (!p) throw new Error('未知音源: ' + provider);
    if (typeof p.mod[method] !== 'function') throw new Error(provider + ' 不支持 ' + method);
    return await p.mod[method](...args);
  },

  /** 诊断：检查各内置模块是否可用 */
  selfTest() {
    const checks = {};
    const probe = (name, fn) => {
      try { checks[name] = fn() ? 'ok' : 'fail'; }
      catch (e) { checks[name] = 'error: ' + e.message; }
    };
    probe('buffer', () => Buffer.from('风', 'utf8').length === 3);
    probe('axios', () => typeof axios.get === 'function');
    probe('cheerio', () => {
      const $ = cheerioNS.load('<div class="a">hi</div>');
      return $('.a').text() === 'hi';
    });
    probe('crypto-js', () => CryptoJS.MD5('a').toString().length === 32);
    probe('he', () => he.decode('&amp;') === '&');
    probe('qs', () => qs.stringify({ a: 1 }) === 'a=1');
    probe('dayjs', () => !!dayjs().format('YYYY'));
    probe('big-integer', () => bigInt(2).pow(10).toString() === '1024');
    probe('pako', () => pako.deflate('ab').length > 0);
    probe('iconv-gbk', () => {
      // "中文" 的 GBK 字节
      const gbk = new Uint8Array([0xD6, 0xD0, 0xCE, 0xC4]);
      return iconv.decode(gbk, 'gbk') === '中文';
    });
    probe('textdecoder', () => new TextDecoder('gbk') && true);
    return { version: RUNTIME_VERSION, checks, plugins: host.list() };
  },

  _internals: { transport, axios, REGISTRY, itemCache },
};

if (typeof window !== 'undefined') window.PluginHost = host;
if (typeof globalThis !== 'undefined') globalThis.PluginHost = host;

export default host;
