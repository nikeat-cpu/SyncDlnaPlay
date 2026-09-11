# 宣传文案 / Promotion Kit

> 发布时把 `<your-username>` 替换成实际 GitHub 用户名。
> 所有文案均与实际功能一致，不夸大（第三方音源稳定性已在文中如实说明）。

---

## 1. GitHub Release 说明（v2.12）

**Title:** SyncDlnaPlay v2.12 — Bilingual UI, immersive lyrics, smoother casting

**Body:**

### Highlights

- 🌍 **The whole UI is now bilingual** — English & 简体中文, auto-detected from your system language
  and switchable in Settings. Every screen, sheet and toast is covered.
- 📝 **Immersive lyrics**: double-tap the lyrics for a full-screen, glowing, auto-scrolling view with
  playback + volume pinned at the bottom.
- 🎛 **No more jumpy seekbar** while casting: progress is extrapolated on the phone clock and
  snapshot noise is filtered; manual lyric offset calibration (±0.5 s) is available too.
- ⤓ **Download while playing**, SMB share browsing, LAN speaker discovery with multi-room delay
  calibration, and phone playback fallback — all in a ~3.7 MB APK with **no account and no server**.

### The Docker control point

Prefer a headless box to run the whole thing? The repo also ships a **zero-dependency Docker
control point** (59 MB image, Python stdlib only) for iStoreOS / OpenWrt / NAS:

```bash
docker compose up -d --build   # web UI on :5000
```

### Quality

Every release is verified by a desktop E2E harness that boots the real backend and drives the real
frontend in headless Chromium — **32/32 checks green** for this build.

### Install

Download `SyncDlnaPlay-standalone-v2.12.apk` below (Android 8.0+), sideload, done.
Full docs: [README](../../#readme) · [中文说明](../../blob/main/README.zh-CN.md)

---

## 2. X / Twitter（英文，可作推文串首条）

> I wanted my music on the cheap DLNA speakers around my house — without an account, a subscription,
> or a home server. So I built SyncDlnaPlay.
>
> 📱 ~3.7 MB Android app, runs 100% on-device
> 🔊 Casts to any DLNA speaker, multi-room sync w/ delay calibration
> 🌐 Online search & download via MusicFree plugins
> 📝 Synced lyrics + full-screen immersive mode
> 🐳 Bonus: a 59 MB zero-dependency Docker control point for NAS/router
>
> MIT, no telemetry: https://github.com/<your-username>/SyncDlnaPlay

**跟推（串第二条）**

> Details worth mentioning:
> – no speaker found? playback falls back to the phone automatically, never an error dialog
> – seekbar stays smooth while casting (snapshot noise is filtered, progress extrapolated)
> – manual lyric offset calibration because casting latency varies per file
> – SMB shares & SD-card folders as library sources
> – EN/中文 UI, auto-detected
> https://github.com/<your-username>/SyncDlnaPlay

---

## 3. Reddit — r/selfhosted

**Title:** SyncDlnaPlay — self-hosted DLNA music casting: a 59 MB zero-dependency Docker control point (+ an Android app that needs no server at all)

**Body:**

I've been running a small DLNA setup at home (cheap Android-based speakers) and got tired of the
options: either heavyweight media servers, or apps that want an account. So I built two small tools
and put them in one repo:

**1. Docker control point** — pure Python stdlib (the web layer is a tiny Flask-compatible subset I
wrote), `python:3.12-alpine` base, **59 MB image**, runs on iStoreOS/OpenWrt/anything with Docker.
Web UI on :5000. It only sends UPnP commands; speakers pull audio straight from the source, so the
container idles at almost nothing.

- SSDP discovery (must run with `network_mode: host` — multicast gets isolated in bridge mode)
- Multi-room: select several speakers, play in sync, per-speaker delay alignment (0–5000 ms) with
  automatic measurement
- Browse DLNA media servers or local/SMB folders

**2. Android app (SyncDlnaPlay)** — if you'd rather not keep a box running: DLNA casting, local
library, SMB shares, online search & download via MusicFree plugins, synced lyrics with immersive
full-screen mode. ~3.7 MB, no account, no telemetry. If no speaker is on the LAN it just plays on
the phone instead of erroring out.

Repo (MIT): https://github.com/<your-username>/SyncDlnaPlay

Happy to answer questions about the UPnP details — the multi-speaker sync part was the interesting
problem (DLNA has no native sync; the app staggers `Play` commands and calibrates per-speaker delay).

---

## 4. Reddit — r/Android（短版）

**Title:** [Dev] I made SyncDlnaPlay — a 3.7 MB offline-first music player that casts to DLNA speakers, with online search via plugins and synced lyrics. No account, no server, MIT.

**Body:**

Features: cast to any DLNA speaker on your Wi-Fi (multi-room sync + delay calibration), local
library with SD card & SMB folders, online search/download through community MusicFree plugins
(you can add/remove sources), synced lyrics with manual offset calibration and an immersive
full-screen mode, download-while-playing, EN/中文 UI.

If it can't find a speaker it falls back to playing on the phone, so it always works.

APK + source: https://github.com/<your-username>/SyncDlnaPlay

There's also a Docker control-point flavor in the same repo if you'd rather drive speakers from a NAS.

---

## 5. V2EX（分享创造节点）

**标题：** 写了个开源的音乐投放工具 SyncDlnaPlay：手机投 DLNA 音响 + 多房间同步，不要账号不要服务器

**正文：**

起因是家里有几台便宜的斐讯刷机音箱，只支持 DLNA。市面上的方案要么是重 media server，要么
App 要登录账号还要会员，干脆自己写了一个，现在整理开源出来（MIT）。

仓库：https://github.com/<your-username>/SyncDlnaPlay

两个部分，互相独立：

**1. Android 独立版（约 3.7MB）**
- DLNA 投放，支持多台音响同播；每台可做延时校准（0~5000ms），缓解多房间不同步
- 发现不到音响时自动回落手机本机播放，不会卡在「播放失败」
- 本地曲库（MediaStore 自动扫 + 任意文件夹 + SMB 共享，扫描局域网/逐层浏览，不用手填路径）
- 在线搜歌/下载，基于 MusicFree 插件生态，音源可自己加（网址/分享码/订阅/本地 js），可停用可设默认，会记住上次用的音源
- 歌词：本地 .lrc（UTF-8/GBK）+ 在线歌词；手动 ±0.5s 快慢校准（投屏延时随文件大小浮动）；
  双击歌词进全屏沉浸模式
- 边听边下载；进度条做了平滑处理，投屏时不会乱跳
- 中英双语界面

**2. Docker 控制点（给 NAS / 路由器）**
- 纯 Python 标准库（Web 层是自研的 Flask 兼容子集），镜像 59MB
- 只发 UPnP 指令，音频流由音响直接向音乐源拉取，容器几乎零负载
- 需 host 网络（SSDP 组播会被 bridge 隔离），iStoreOS 上实测稳定跑了几个月

构建没有用 Gradle，是一个纯工具链脚本（aapt2 → javac → d8 → 打包签名），仓库里带了一套
桌面 E2E（真实后端 + 无头 Chromium 跑真实前端，32 项检查）。

欢迎围观、提 issue、点 star。第三方音源接口偶尔不稳定属于音源本身的问题，换个音源即可。

---

## 6. 少数派 / 即刻（短文案）

> 【开源】SyncDlnaPlay：把手机里的歌投到家里的 DLNA 音响。
> 3.7MB 的安卓 App，不要账号、不要服务器：本地曲库 + SMB 共享 + 在线搜歌下载（MusicFree 插件生态，
> 音源自己说了算）+ 滚动歌词与全屏沉浸模式 + 多房间同步（可做延时校准）。附带一个 59MB 的
> Docker 控制点版本，可以扔在 NAS 上常驻。MIT 开源，无任何遥测。
> https://github.com/<your-username>/SyncDlnaPlay

---

## 7. Hacker News（标题候选）

- `Show HN: SyncDlnaPlay – cast music to DLNA speakers from a 59MB zero-dependency Docker image`
- `Show HN: A 3.7MB Android app that casts music to DLNA speakers, no account or server needed`

**首评（自己补的背景）：**

> The interesting part was multi-room sync: DLNA has no native sync protocol, so the app staggers
> the `Play` commands across devices and lets you calibrate a per-speaker delay (measured
> automatically). Audio never touches the control point — speakers pull the stream straight from
> the source — so the Docker image can be 59 MB of Python stdlib and still run on a router.
> Source (MIT): https://github.com/<your-username>/SyncDlnaPlay

---

## 发布检查清单

- [ ] 替换所有 `<your-username>`
- [ ] Release 附上 `SyncDlnaPlay-standalone-v2.12.apk`（与 CHANGELOG 版本一致）
- [ ] README 顶部徽章链接可点
- [ ] 截图为最新版本界面
- [ ] V2EX 发在「分享创造」，HN 选 `Show HN`，Reddit 遵守各版自荐规则
