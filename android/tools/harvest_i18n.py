# -*- coding: utf-8 -*-
"""在真实前端（LiveServer :8765）上遍历所有界面，采集需要翻译的中文文案。

产出 build/i18n_harvest.json：{"ui": [...], "steps": {step: [...]}}
用法：先启动 LiveServer，再 NO_PROXY=127.0.0.1,localhost python tools/harvest_i18n.py
"""
import os, io, json, time
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WWW = os.path.join(ROOT, "app", "assets", "www", "index.html")
OUT = os.path.join(ROOT, "build", "i18n_harvest.json")

HARVEST = r"""
() => {
  const cn = /[\u4e00-\u9fff]/;
  const out = [];
  const seen = new Set();
  const push = (t) => { t = (t || '').trim(); if (t && cn.test(t) && !seen.has(t)) { seen.add(t); out.push(t); } };
  const walk = (root) => {
    if (!root) return;
    const it = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = it.nextNode())) push(n.nodeValue);
    if (root.querySelectorAll) {
      root.querySelectorAll('[placeholder],[title],[aria-label],[alt]').forEach(el => {
        ['placeholder', 'title', 'aria-label', 'alt'].forEach(a => push(el.getAttribute(a)));
      });
    }
  };
  walk(document.body);
  return out;
}
"""

# 每个界面：标签、注入/打开动作、等待毫秒
STEPS = [
    ("splash", "() => showSplash()", 300),
    ("devices", """() => {
        S.state = S.state || {};
        S.state.devices = [
          { udn: 'uuid:aaa', friendly_name: '客厅音响', name: '客厅音响', selected: true, online: true,
            state: 'PLAYING', volume: 30, position_sec: 12, duration_sec: 200, delay_ms: 120 },
          { udn: 'uuid:bbb', friendly_name: '书房音响', name: '书房音响', selected: false, online: false,
            state: 'STOPPED', volume: 0, delay_ms: 0 }
        ];
        S.state.scanning = false;
        renderDevices(); renderTopDev(); switchTab('devices');
      }""", 400),
    ("device-sheet", "() => devSheet(0)", 400),
    ("lib", """() => {
        switchTab('lib');
        S.lib = S.lib || { container: '1$4', crumbs: [{ name: '音乐库', id: '1$4' }] };
        renderLib({ folders: ['流行', '古典'], items: [
          { id: 'f:/a.mp3', title: '海阔天空', artist: 'Beyond', album: '乐与怒', duration_sec: 326, type: 'audio' },
          { id: 'f:/b.mp3', title: '未知', artist: '戴佩妮', duration_sec: 210, type: 'audio' }
        ], truncated: true });
      }""", 400),
    ("lib-more", "() => libMore()", 400),
    ("lib-search", "() => libSearch()", 300),
    ("music-sources", "() => musicSourcesSheet()", 1200),
    ("add-local", "() => srcAdd('local')", 600),
    ("add-smb", "() => srcAdd('smb')", 600),
    ("src-mgr", "() => srcMgrSheet()", 1200),
    ("src-install", "() => srcInstallSheet()", 600),
    ("dl-status", "() => dlStatus()", 1200),
    ("crash-logs", "() => showCrashLogs()", 600),
    ("settings", "() => settingsSheet()", 400),
    ("help", "() => helpSheet()", 600),
    ("volume-phone", "() => { closeSheet(); volumeSheet(-1); }", 400),
    ("volume-dlna", "() => { closeSheet(); volumeSheet(0); }", 400),
    ("queue", """() => {
        closeSheet();
        S.queue = [
          { source: 'local', id: 'f:/a.mp3', title: '海阔天空', artist: 'Beyond', duration_sec: 326 },
          { source: 'online', provider: '元力WY', oid: 'x1', title: '夜间飞行', artist: '未知歌手', duration_sec: 180 }
        ];
        S.idx = 0; S.playing = true;
        switchTab('queue'); renderQueue();
      }""", 400),
    ("online", """() => {
        switchTab('online');
        S.online = S.online || {};
        S.online.items = [{ id: 'o1', title: '夜间飞行', artist: '某某', album: '专辑名', duration_sec: 205 }];
        S.online.page = 2; S.online.isEnd = false; S.online.provider = '元力WY';
        S.online.plugins = [{ platform: '元力WY', name: 'yuanli-wy', enabled: true, builtin: true },
                            { platform: '自建音源', name: 'my-src', enabled: true, builtin: false }];
        try { fillProviders(); } catch (e) { }
        renderOnline();
      }""", 400),
    ("now", """() => {
        S.out = 'dlna';
        S.phone.queue = [{ source: 'local', id: 'f:/a.mp3', title: '海阔天空', artist: 'Beyond' }];
        S.phone.idx = 0;
        S.lyric = { key: 'k', idx: 1, msg: '', lines: [{ t: 1, text: '一' }, { t: 5, text: '二' }] };
        S.volPhone = 40; S.volIdx = 2;
        switchTab('now');
        renderLyric(); renderNowTab(); refreshNow();
      }""", 500),
    ("immersive", "() => { enterImmersive(); if ($('immLrc')) $('immLrc').scrollTop = 0; }", 600),
    ("toast", "() => { exitImmersive(); toast('已加入播放列表', 'ok'); }", 300),
]


def main():
    steps_out = {}
    ui = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security",
                                    "--no-sandbox", "--disable-gpu"])
        pg = b.new_context(viewport={"width": 400, "height": 900}, device_scale_factor=1).new_page()
        pg.goto("file:///" + WWW.replace("\\", "/"), wait_until="load")
        for _ in range(40):
            try:
                if pg.evaluate("!!(S && S.state)"):
                    break
            except Exception:
                pass
            time.sleep(0.5)
        time.sleep(1.5)

        for label, js, wait in STEPS:
            try:
                pg.evaluate(js)
            except Exception as e:
                steps_out[label] = {"error": str(e)[:200]}
                print("  [warn]", label, str(e)[:120])
                continue
            time.sleep(wait / 1000.0)
            try:
                got = pg.evaluate(HARVEST)
            except Exception as e:
                got = []
                print("  [warn-harvest]", label, str(e)[:120])
            steps_out[label] = got
            print("  %-14s -> %d" % (label, len(got)))
        b.close()

    seen = set()
    for label, v in steps_out.items():
        if not isinstance(v, list):
            continue
        for t in v:
            if t not in seen:
                seen.add(t)
                ui.append(t)
    ui.sort()
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump({"ui": ui, "steps": steps_out}, f, ensure_ascii=False, indent=1)
    print("unique UI strings:", len(ui))
    print("written:", OUT)


if __name__ == "__main__":
    main()
