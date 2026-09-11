# -*- coding: utf-8 -*-
"""生成 README 用的中英文界面截图（含一张横幅拼图）。

要点：
 · PREP 里冻结 S.poll / S.lyrTimer，防止真实轮询把演示数据冲掉（也会泄局域网设备名）；
 · 每张截图分两段：pre（等异步落定）+ post（紧贴截图执行，防 async 歌词加载覆盖）。
"""
import os, time, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harvest_i18n import WWW, ROOT  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = os.path.join(ROOT, "docs", "screenshots")
os.makedirs(OUT, exist_ok=True)

LYRIC = ("[00:00.00]霓虹淹没的街口\\n"
         "[00:04.50]信号灯在雨里闪烁\\n"
         "[00:09.00]你的名字被删除前\\n"
         "[00:13.50]我最后一次听见\\n"
         "[00:18.00]把这首歌投给音响\\n"
         "[00:22.50]让整条街都听见\\n"
         "[00:27.00]SyncDlnaPlay · 独立运行版")

PREP = """
() => {
  try { clearInterval(S.poll); } catch (e) { }
  try { clearInterval(S.lyrTimer); } catch (e) { }
  S.state = S.state || {};
  S.state.devices = [
    { udn:'uuid:a', friendly_name:'Living Room', name:'Living Room', selected:true, online:true,
      state:'PLAYING', volume:42, position_sec:12, duration_sec:214, delay_ms:0 },
    { udn:'uuid:b', friendly_name:'Bedroom', name:'Bedroom', selected:true, online:true,
      state:'PLAYING', volume:38, position_sec:12, duration_sec:214, delay_ms:120 },
    { udn:'uuid:c', friendly_name:'Kitchen', name:'Kitchen', selected:false, online:true, state:'STOPPED', volume:20 }
  ];
  S.state.scanning = false;
  S.state.player = {
    queue: [
      { title:'Neon Rain', artist:'Aurora Wave', album:'Night Drive', duration_sec:214 },
      { title:'Signal Lost', artist:'Aurora Wave', album:'Night Drive', duration_sec:198 },
      { title:'Deleted', artist:'Kite', album:'Ghost', duration_sec:232 }
    ],
    index: 0, state: 'PLAYING', playing: true, position_sec: 12, duration_sec: 214,
    current: { title:'Neon Rain', artist:'Aurora Wave', album:'Night Drive', duration_sec:214 }
  };
  S.queue = S.state.player.queue.slice();
  S.idx = 0; S.playing = true;
  S.out = 'dlna';
  S._libItems = [
    { source:'local', id:'f:/m/1.mp3', title:'Neon Rain', artist:'Aurora Wave', album:'Night Drive', duration_sec:214 },
    { source:'local', id:'f:/m/2.mp3', title:'Signal Lost', artist:'Aurora Wave', album:'Night Drive', duration_sec:198 },
    { source:'local', id:'f:/m/3.mp3', title:'Deleted', artist:'Kite', album:'Ghost', duration_sec:232 },
    { source:'local', id:'f:/m/4.mp3', title:'Midnight Drive', artist:'Kite', album:'Ghost', duration_sec:186 }
  ];
  S.lib = { container:'1$4', crumbs:[{name:'Music', id:'1$4'}] };
  S.online = S.online || {};
  S.online.page = 1; S.online.isEnd = false; S.online.provider = '元力WY';
  S.online.plugins = [
    { platform:'元力WY', name:'yuanli-wy', enabled:true, builtin:true },
    { platform:'元力KG', name:'yuanli-kg', enabled:true, builtin:true },
    { platform:'元力KW', name:'yuanli-kw', enabled:true, builtin:true }
  ];
  S.online.items = [
    { id:'o1', title:'Neon Rain', artist:'Aurora Wave', album:'Night Drive', duration_sec:214 },
    { id:'o2', title:'Signal Lost', artist:'Aurora Wave', album:'Night Drive', duration_sec:198 },
    { id:'o3', title:'Deleted', artist:'Kite', album:'Ghost', duration_sec:232 },
    { id:'o4', title:'Midnight Drive', artist:'Kite', album:'Ghost', duration_sec:186 },
    { id:'o5', title:'Ghost Wire', artist:'Nova', album:'Static', duration_sec:205 }
  ];
  window.__setLyric = function () {
    S.lyric = { key: 'k', idx: 3, msg: '', lines: parseLrc('%s') };
    renderLyric();
  };
}
""" % LYRIC

# (名称, pre[等异步落定], post[紧贴截图])
SHOTS = [
    ("now", """() => { switchTab('now'); renderNowTab(); refreshNow(); }""",
     "() => __setLyric()"),
    ("devices", """() => { switchTab('devices'); renderDevices(); renderTopDev(); }""", ""),
    ("lib", """() => { switchTab('lib'); renderLib({ folders:['Albums','Singles'], items: S._libItems }); }""", ""),
    ("online", """() => { switchTab('online'); renderOnline(); }""", ""),
    ("queue", """() => { switchTab('queue'); renderQueue(); }""", ""),
    ("settings", """() => { settingsSheet(); }""", ""),
    ("immersive", """() => { closeSheet(); switchTab('now'); renderNowTab(); }""",
     "() => { __setLyric(); enterImmersive(); }"),
]


def run(lang):
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files", "--disable-web-security",
                                    "--no-sandbox", "--disable-gpu"])
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        ctx.add_init_script("try{localStorage.setItem('dlna_lang','%s')}catch(e){}" % lang)
        pg = ctx.new_page()
        pg.goto("file:///" + WWW.replace("\\", "/"), wait_until="load")
        for _ in range(40):
            try:
                if pg.evaluate("!!(S && S.state)"):
                    break
            except Exception:
                pass
            time.sleep(0.4)
        time.sleep(1.2)

        for name, pre, post in SHOTS:
            try:
                pg.evaluate(PREP)
                pg.evaluate(pre)
            except Exception as e:
                print("  [warn]", name, str(e)[:120])
                continue
            time.sleep(0.5)
            try:
                if post:
                    pg.evaluate(post)
                pg.evaluate("window.I18N && I18N.apply()")
            except Exception as e:
                print("  [warn-post]", name, str(e)[:120])
            pg.screenshot(path=os.path.join(OUT, "%s-%s.png" % (lang, name)))
            print("  saved", lang + "-" + name)
        b.close()


for lg in ("en", "zh"):
    print("== 语言:", lg)
    run(lg)

try:
    from PIL import Image, ImageDraw
    names = ["en-immersive.png", "en-now.png", "en-devices.png", "en-online.png"]
    ims = [Image.open(os.path.join(OUT, n)) for n in names if os.path.exists(os.path.join(OUT, n))]
    if ims:
        scale = 0.62
        h = int(ims[0].height * scale)
        ims = [im.resize((int(im.width * scale), h), Image.LANCZOS) for im in ims]
        gap, pad = 26, 46
        W = pad * 2 + sum(im.width for im in ims) + gap * (len(ims) - 1)
        H = h + pad * 2
        sheet = Image.new("RGB", (W, H), (7, 10, 20))
        dr = ImageDraw.Draw(sheet)
        for i in range(H):
            t = i / float(H - 1)
            dr.line([(0, i), (W, i)], fill=(int(7 + 16 * t), int(10 + 10 * t), int(20 + 34 * t)))
        x = pad
        for im in ims:
            sheet.paste(im, (x, pad))
            x += im.width + gap
        sheet.save(os.path.join(OUT, "banner.png"))
        print("banner:", sheet.size)
except Exception as e:
    print("banner failed:", e)
print("OUT:", OUT)
