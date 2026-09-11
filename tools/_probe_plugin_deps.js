'use strict';
/*
 * 探针：在 bridge 容器里加载全部 MusicFree 插件，记录它们 require 了哪些模块。
 * 目的：确定要打包到安卓 App 的 npm 依赖清单（这些插件是混淆的，静态 grep 看不到）。
 * 用法（容器内）：  node /tmp/_probe_plugin_deps.js
 */
const Module = require('module');
const fs = require('fs');
const path = require('path');

const PLUGINS_DIR = process.env.PLUGINS_DIR || '/plugins';

const seen = new Map();          // request -> 次数
const natives = new Set(Module.builtinModules);
const origLoad = Module._load;
Module._load = function (request, parent, isMain) {
  seen.set(request, (seen.get(request) || 0) + 1);
  return origLoad.apply(this, arguments);
};

function report(tag) {
  const rows = [...seen.entries()].sort((a, b) => b[1] - a[1]);
  console.log('\n===== require 统计 (' + tag + ') =====');
  for (const [name, n] of rows) {
    const kind = natives.has(name) ? 'builtin' : (name.startsWith('.') ? 'relative' : 'npm');
    console.log(String(n).padStart(5), kind.padEnd(8), name);
  }
}

(async () => {
  for (const f of fs.readdirSync(PLUGINS_DIR)) {
    if (!f.endsWith('.js')) continue;
    if (f === 'demo.js') continue;
    const full = path.join(PLUGINS_DIR, f);
    try {
      delete require.cache[require.resolve(full)];
      const mod = require(full);
      const platform = mod && (mod.platform || mod.name);
      console.log('OK   ', f, '-> platform =', platform, '| methods =',
        ['search', 'getMediaSource', 'getLyric', 'getAlbumInfo'].filter(m => typeof mod[m] === 'function').join(','));
      // 触发一次真实搜索，逼出懒加载的 require
      if (platform && typeof mod.search === 'function') {
        try {
          const r = await mod.search('周杰伦', 1, 'music');
          const list = (r && r.data) || [];
          console.log('     search ok, 返回', list.length, '条; isEnd =', r && r.isEnd);
          // 再解析第一首，逼出 getMediaSource 里的依赖
          if (list[0] && typeof mod.getMediaSource === 'function') {
            try {
              const ms = await mod.getMediaSource(list[0], 'standard');
              console.log('     getMediaSource ok -> url:', String(ms && ms.url).slice(0, 90),
                '| headers:', Object.keys((ms && ms.headers) || {}).join(','));
            } catch (e) { console.log('     getMediaSource 失败:', e.message); }
          }
        } catch (e) { console.log('     search 失败:', e.message); }
      }
    } catch (e) {
      console.log('FAIL ', f, '->', e.message);
    }
  }
  report('全部');
})();
