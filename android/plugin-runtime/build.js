/**
 * 用 esbuild 把插件运行时打成单文件，供 Android WebView 直接 <script> 载入。
 * 产物：../app/assets/www/plugins-runtime.js
 */
const esbuild = require('esbuild');
const path = require('path');
const fs = require('fs');

const OUT = path.resolve(__dirname, '..', 'app', 'assets', 'www', 'plugins-runtime.js');

// buffer / node_modules 里的一些代码在模块初始化时就会读 global / process，
// 因此必须在 bundle 主体之前就把这两个全局补齐（ES import 会先于入口代码执行）。
const BANNER = `(function(){if(typeof globalThis.global==="undefined"){globalThis.global=globalThis;}
if(typeof globalThis.process==="undefined"){globalThis.process={env:{},argv:["node","plugin"],version:"v18.0.0",versions:{node:"18.0.0"},platform:"android",browser:true,nextTick:function(f){var a=[].slice.call(arguments,1);setTimeout(function(){f.apply(null,a);},0);},cwd:function(){return "/";},on:function(){},once:function(){},off:function(){},emit:function(){return false;},exit:function(){},uptime:function(){return 0;},hrtime:function(){return [0,0];},memoryUsage:function(){return {rss:0,heapTotal:0,heapUsed:0};}};}
if(typeof globalThis.setImmediate==="undefined"){globalThis.setImmediate=function(f){var a=[].slice.call(arguments,1);return setTimeout(function(){f.apply(null,a);},0);};globalThis.clearImmediate=function(id){clearTimeout(id);};}})();`;

(async () => {
  const t0 = Date.now();
  const result = await esbuild.build({
    entryPoints: [path.resolve(__dirname, 'src', 'entry.js')],
    bundle: true,
    format: 'iife',
    platform: 'browser',
    target: ['chrome70'],
    minify: true,
    sourcemap: false,
    legalComments: 'none',
    charset: 'utf8',
    banner: { js: BANNER },
    define: { 'process.env.NODE_ENV': '"production"' },
    outfile: OUT,
    metafile: true,
    logLevel: 'warning',
  });

  const size = fs.statSync(OUT).size;
  console.log('产出:', path.relative(process.cwd(), OUT));
  console.log('大小:', (size / 1024).toFixed(1), 'KB', '（耗时', Date.now() - t0, 'ms）');

  // 体积排行，便于发现意外被打进来的大依赖
  const out = result.metafile.outputs[Object.keys(result.metafile.outputs)[0]];
  const rows = Object.entries(out.inputs)
    .map(([k, v]) => [k, v.bytesInOutput])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12);
  console.log('主要贡献:');
  for (const [k, v] of rows) console.log('   ', (v / 1024).toFixed(1).padStart(8), 'KB ', k);
})().catch((e) => {
  console.error('打包失败:', e.message);
  process.exit(1);
});
