/* =====================================================================
   电视模式测试驱动 · tv_cdp.js
   ---------------------------------------------------------------------
   用 Chrome DevTools Protocol 直接驱动无头 Chrome：
   加载页面 → 等电视模式真正就绪 → 在页面里执行 <checks.js> → 截图。

   为什么不用 `--virtual-time-budget --dump-dom`：
   页面有两个常驻 setInterval（app.js 的 1.6s 轮询、tv.js 的 0.7s 焦点恢复），
   虚拟时间会在每次网络请求上暂停，Chrome 几乎不会自己结束。
   这里改用真实时间 + CDP，结果确定、不会挂住。

   依赖：Node 22+（用到全局 fetch / WebSocket，无需 npm install）。
        可用 TV_CHROME 指定 Chrome 路径。

   用法：
     node tv_cdp.js <url> <截图路径> <checks.js>
   退出码：0 通过 / 1 失败 / 3 页面未就绪
   ===================================================================== */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.TV_CHROME
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = Number(process.env.TV_CDP_PORT || 9333);
const READY_TIMEOUT_MS = Number(process.env.TV_READY_TIMEOUT_MS || 30000);

const TARGET = process.argv[2] || 'http://127.0.0.1:5000/?tv=1';
const SHOT = process.argv[3] || path.join(__dirname, 'tv_shot.png');
let bodyArg = process.argv[4] || path.join(__dirname, 'nav_checks.js');
if (!path.isAbsolute(bodyArg)) bodyArg = path.join(__dirname, bodyArg);
const BODY = fs.readFileSync(bodyArg, 'utf8');

/* 目标 URL 带 ?tv=1 就要求落在电视模式，否则要求电视模式安静待命 */
const WANT_TV = /[?&]tv=1/.test(TARGET);

const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  if (typeof fetch !== 'function' || typeof WebSocket !== 'function') {
    console.error('需要 Node 22+（用到全局 fetch / WebSocket）');
    process.exit(1);
  }
  if (!fs.existsSync(CHROME)) {
    console.error('找不到 Chrome：' + CHROME + '\n可用 TV_CHROME=<路径> 指定');
    process.exit(1);
  }

  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + path.join(require('os').tmpdir(), 'chrome-tvcdp-' + PORT),
    '--window-size=1280,720',
    '--no-first-run', '--no-default-browser-check',
    'about:blank'
  ], { stdio: 'ignore' });

  let ws = null, idc = 0;
  const pending = new Map();
  const pageErrors = [];

  function send(method, params) {
    const id = ++idc;
    return new Promise((res, rej) => {
      pending.set(id, { res, rej });
      ws.send(JSON.stringify({ id, method, params: params || {} }));
    });
  }
  async function ev(expr, awaitPromise) {
    const r = await send('Runtime.evaluate', {
      expression: expr, returnByValue: true, awaitPromise: !!awaitPromise
    });
    if (r.exceptionDetails) {
      throw new Error('页面 JS 异常: ' + JSON.stringify(r.exceptionDetails).slice(0, 600));
    }
    return r.result.value;
  }

  try {
    let version = null;
    for (let i = 0; i < 80; i++) {
      try {
        const r = await fetch('http://127.0.0.1:' + PORT + '/json/version');
        if (r.ok) { version = await r.json(); break; }
      } catch (e) { }
      await sleep(250);
    }
    if (!version) throw new Error('DevTools 端点未就绪');
    console.log('浏览器: ' + version.Browser);

    let page = null;
    for (let i = 0; i < 40; i++) {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      page = list.find(t => t.type === 'page');
      if (page) break;
      await sleep(250);
    }
    if (!page) throw new Error('未找到页面目标');

    ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true });
      ws.addEventListener('error', () => rej(new Error('WebSocket 连接失败')), { once: true });
    });
    ws.addEventListener('message', e => {
      const m = JSON.parse(e.data);
      if (m.id && pending.has(m.id)) {
        const p = pending.get(m.id); pending.delete(m.id);
        if (m.error) p.rej(new Error(JSON.stringify(m.error)));
        else p.res(m.result);
      } else if (m.method === 'Runtime.exceptionThrown') {
        const d = (m.params && m.params.exceptionDetails) || {};
        pageErrors.push((d.exception && d.exception.description) || d.text || '未知异常');
      }
    });

    await send('Page.enable');
    await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1280, height: 720, deviceScaleFactor: 1, mobile: false
    });

    console.log('导航到: ' + TARGET);
    await send('Page.navigate', { url: TARGET });

    // 等页面真正启动完（电视布局已落地、启动页已隐藏、设备列表已渲染）
    let st = null, ok = false;
    const tries = Math.ceil(READY_TIMEOUT_MS / 300);
    for (let i = 0; i < tries; i++) {
      await sleep(300);
      try {
        const raw = await ev(
          "(function(){try{var a=document.getElementById('app');var su=document.getElementById('setup');" +
          "return JSON.stringify({tv:(window.__tvMode&&window.__tvMode())||null," +
          "app:a?a.style.display:null,setup:su?su.style.display:null," +
          "cue:!!document.getElementById('tvcue')," +
          "items:document.querySelectorAll('#devList .item').length," +
          "tab:((document.querySelector('.navbtn.on')||{}).textContent||'-').trim()})" +
          "}catch(e){return JSON.stringify({err:String(e.message)})}})()");
        st = JSON.parse(raw);
        if (WANT_TV) {
          if (st.tv === '1' && st.items > 0 && st.app === 'grid'
              && st.cue && st.setup !== 'flex') { ok = true; break; }
        } else {
          if (st.tv === '0' && st.items > 0 && st.app === 'flex'
              && !st.cue && st.setup !== 'flex') { ok = true; break; }
        }
      } catch (e) { st = { err: e.message }; }
    }
    console.log('就绪检查: ' + JSON.stringify(st) + (ok ? '  ✅' : '  ⚠️ 未达预期'));

    if (!ok) {
      /* 设备列表为空是最常见的「跑不起来」原因：SSDP 组播没扫到音响。
         这种情况不该报成断言失败，否则看日志的人会去翻 tv.js。 */
      if (st && st.items === 0) {
        console.error('\n❌ 页面上没有任何 DLNA 设备，无法进行电视模式测试。');
        console.error('   电视模式的焦点测试需要设备列表非空（焦点要在真实列表行里移动）。');
        console.error('   请确认：');
        console.error('     · 本机与至少一台 DLNA 音响 / 电视在同一局域网');
        console.error('     · 服务端启动后等 5~10 秒扫描完成再跑测试');
        process.exitCode = 3;
        return;
      }
      throw new Error('页面未就绪，无法继续');
    }

    // 电视模式是「内容就绪后自动落焦」的，给它一拍时间稳定下来
    await sleep(1000);

    console.log('');
    const report = await ev('(async function(){' + BODY + '})()', true);
    console.log(report);

    /* 断言失败必须体现在退出码上 —— 否则 run.sh 会在有 ❌ 的情况下报「全部通过」。
       checks 文件统一以「===== 结果：N 项通过 / M 项失败 =====」收尾。 */
    const m = /结果：(\d+)\s*项通过\s*\/\s*(\d+)\s*项失败/.exec(String(report));
    if (!m) {
      console.error('\n⚠️ 报告里没有找到「结果：N 项通过 / M 项失败」汇总行，无法判定成败');
      process.exitCode = 1;
    } else if (Number(m[2]) > 0) {
      console.error('\n❌ ' + m[2] + ' 项断言失败（通过 ' + m[1] + ' 项）');
      process.exitCode = 1;
    } else {
      console.log('\n✅ ' + m[1] + ' 项断言全部通过');
    }

    if (pageErrors.length) {
      console.log('\n⚠️ 页面抛出 ' + pageErrors.length + ' 个 JS 异常：');
      pageErrors.slice(0, 8).forEach((t, i) => console.log('  [' + (i + 1) + '] ' + String(t).split('\n')[0]));
      process.exitCode = 1;
    } else {
      console.log('\n✅ 整个流程无 JS 异常');
    }

    await sleep(400);
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(SHOT, Buffer.from(shot.data, 'base64'));
    console.log('\n截图已保存: ' + SHOT);
  } catch (e) {
    console.error('❌ 测试失败: ' + e.message);
    process.exitCode = 1;
  } finally {
    try { ws && ws.close(); } catch (e) { }
    try { chrome.kill('SIGKILL'); } catch (e) { }
  }
})();
