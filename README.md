<div align="center">

<img src="android/app/res/mipmap-xxxhdpi/ic_launcher.png" width="96" alt="SyncDlnaPlay logo"/>

# SyncDlnaPlay

**Select several DLNA speakers on your Wi-Fi — they all play the same song, at the same time. Or just play on your phone.**
**No account. No cloud. No home server required.**

[![Platform](https://img.shields.io/badge/platform-Android%208%2B%20%7C%20Docker-22e6ff)](#install)
[![Size](https://img.shields.io/badge/APK-~3.7%20MB-ff2d92)](#android-app)
[![Deps](https://img.shields.io/badge/Android%20deps-none%20runtime%20perm.-22e6ff)](#android-app)
[![i18n](https://img.shields.io/badge/UI-English%20%7C%20中文-ff2d92)](#features)
[![License](https://img.shields.io/badge/license-MIT-cyan)](#license)

[English](#features) · [简体中文](README.zh-CN.md)

<img src="docs/screenshots/banner.png" width="880" alt="SyncDlnaPlay screenshots"/>

</div>

---

**SyncDlnaPlay** is a cyberpunk-styled music player and DLNA caster that runs *entirely on your phone*.
Play local files, search and download songs online, select several DLNA speakers on your LAN and they play
simultaneously in sync, and follow along with synced lyrics — including a full-screen immersive lyrics mode.

It ships in two independent flavors:

| | [📱 Android app](#android-app) | [🐳 Docker control point](#docker-control-point) |
|---|---|---|
| Runs on | Any Android 8.0+ phone | iStoreOS / OpenWrt / any NAS with Docker |
| Needs a server | **No** — everything is in-process | It *is* the server (web UI on :5000) |
| Online sources | ✅ MusicFree plugins | ➖ (browses DLNA / SMB libraries) |
| Best for | Phone → speakers, anywhere | Headless box → whole-home audio |

---

## Features

### 🔊 Cast to DLNA speakers — with real multi-room sync
- Auto-discovers DLNA/UPnP renderers on your LAN (smart speakers, old Android docks, TVs, AV receivers)
- Select **several speakers at once** and they play in sync
- **Per-speaker delay calibration** (0–5000 ms) compensates for devices that start late —
  measure automatically with *Sync calibration*, then the app staggers `Play` commands to line them up
- No AirPlay 2 / Chromecast needed; plain DLNA that works with cheap hardware

### 📱 Never stuck without a speaker
- If no DLNA device is found, playback **automatically falls back to the phone** —
  you get a toast, not an error dialog
- One tap switches output between **Speaker** and **This phone**; the other side stops automatically

### 💽 Local library that just works
- Phone music is auto-scanned via **MediaStore** (no manual refresh, no storage-permission gymnastics)
- Add **extra folders**: device storage, SD card, USB drive — via the system file picker (SAF)
- Add **SMB network shares**: scan your LAN for hosts with port 445 open, browse shares folder-by-folder,
  and pick a directory without ever typing a path

### 🌐 Online search & download — with sources you control
- Built on the [MusicFree](https://github.com/maotoumao/MusicFree) plugin ecosystem: several community
  sources are bundled, and you can **add your own** by URL, share code, subscription JSON, or a local `.js` file
- Disable any bundled source you don't want; set a **default source**; the app **remembers the last
  source you searched with**
- Keyword search with paging, per-song **download** (previews under one minute are skipped automatically)
- **Download while playing**: flip one switch and every online song you play is saved automatically
  to a public, file-manager-visible folder (`Music/…` by default)

### 📝 Lyrics done right
- Synced lyrics for local songs (same-name `.lrc`, UTF-8/GBK) and online songs (fetched from the source)
- Casting latency varies with file size, so you get a **manual ±0.5 s offset calibration** (up to ±10 s)
- **Immersive mode**: double-tap the lyrics for full-screen, glowing, auto-scrolling lyrics with
  playback and volume controls pinned at the bottom
- Tap any line to seek there

### 🎛 Polished playback
- **Progress smoothing**: casting progress is extrapolated on the phone clock and snapshot noise is
  filtered, so the seekbar doesn't jump around after you drag it
- Queue management: jump, remove, clear, shuffle / repeat-all / repeat-one / in-order
- Volume panel that targets either the speaker group or the phone, with ±1 steps and long-press repeat
- Cyberpunk HUD aesthetic, honest SVG icons, dark theme

### 🌍 Bilingual UI
- English and 简体中文, auto-detected from your system language, switchable in **Settings**

### 📺 Built for Android TV remotes
- **One APK for both**: install it on Android TV or a TV box and it registers as a TV app —
  it shows up in the TV launcher's app row with its own banner, and it is **not** filtered out
  for having no touchscreen
- TV mode turns on automatically on a TV; you can also toggle it in
  **Settings → TV mode (remote)** or force it with `?tv=1`
- **Remote only** — no mouse, no touch:

  | Key | What it does |
  |---|---|
  | ▲ ▼ ◀ ▶ | Move between visible controls (spatial navigation, no guessing the order) |
  | OK / Enter | Confirm; text fields raise the system keyboard, dropdowns cycle in place |
  | ◀ ▶ (while on a slider) | Adjust the value directly — **commits ~0.4 s after you stop**, no dragging |
  | Back | Step up one level: dismiss keyboard → close panel → return to the nav rail → exit |
  | ⏯ ⏭ ⏮ | Play / pause / next / previous |
  | CH+ / CH− | Volume up / down |

- Simpler than the phone UI: the left rail is the only entry point, content stays on the right,
  and **nothing needs a long-press or a drag**
- A clearly visible focus ring (readable from the couch), and **focus survives the list
  refreshing every second** — when speakers come and go the ring stays on the same row
  instead of jumping back to the top
- Hitting the end of a list wraps **inside the same region** (the rail wraps in the rail,
  the list wraps in the list) instead of leaping to another area
- A permanent key-hint bar at the bottom that updates as focus moves
- **Nothing is cut down**: discovery & multi-room sync, library, online source search and
  resolution, persistent queue, lyrics, playlist export, source management and SMB browsing are
  all identical to the phone build (TV mode is a shell — the business logic is untouched)

---

## Install

### Android app

Grab the latest APK from [**Releases**](../../releases) and sideload it (`minSdk 26` → Android 8.0+).

> The app is not on Google Play. You'll need to allow *install unknown apps* for your browser/file manager.
> No permissions are requested beyond what the features need (storage read for the library, notifications
> for the keep-alive notification while casting).

Two builds ship with every release — same features, different default language:

| APK | Language behaviour |
|---|---|
| `SyncDlnaPlay-standalone-v2.22.apk` | Follows your phone's language (English / 简体中文) |
| `SyncDlnaPlay-standalone-v2.22-en.apk` | Starts in **English** whatever your phone language is (still switchable in Settings → 语言 / Language) |

### Android TV / TV box

The **same APK** is a valid TV app — no separate build to hunt for:

```bash
adb connect <tv-ip>:5555      # or use a USB stick / file manager on the TV
adb install -r SyncDlnaPlay-standalone-v2.22.apk
```

- It appears in the **Android TV home screen** app row (own banner, `LEANBACK_LAUNCHER` entry)
  and starts straight into TV mode
- `android.hardware.touchscreen` is declared *not required*, so the app is offered on
  TV/box devices that report no touchscreen
- On a phone/tablet nothing changes: TV mode is off unless you turn it on
  (see the remote key map in [Features → Built for Android TV remotes](#-built-for-android-tv-remotes))

### Docker control point

For a headless box (NAS / router) that casts to your speakers without a phone in the loop:

```bash
git clone https://github.com/nikeat-cpu/SyncDlnaPlay.git
cd SyncDlnaPlay
docker compose up -d --build      # web UI on http://<host>:5000
```

> **`network_mode: host` is mandatory** — SSDP discovery is multicast-based and gets isolated by bridge networking.
> Full deployment notes, iStoreOS specifics and troubleshooting live in **[docs/DOCKER.zh-CN.md](docs/DOCKER.zh-CN.md)** (中文).

The image is `python:3.12-alpine` + **standard library only** (the web layer is a hand-rolled Flask
subset) → **59 MB**, second-level builds, tiny RAM footprint. Audio never passes through the container:
speakers pull streams straight from the source.

**The web UI and the Android app are the same front end.** The image serves the exact same
zero-dependency SPA from `android/app/assets/www`, so both builds always have identical screens and
features (bilingual UI, themes, immersive lyrics, persistent queue, source manager, SMB browsing…).
Nothing exists on the phone but not in the browser. The Python back end implements the SPA's API
contract, so a front-end change is made in exactly one place.

> The image bundles `samba-client` for "scan the LAN / list shares / browse folders".
> Running on a host instead? You need `smbclient` there — on macOS share *names* still work
> without it (falls back to the built-in `smbutil`).

> Local debugging: `./run-macos.sh` starts the server, detects your LAN IP, feeds it to `HOST_IP`
> and points you at `http://<your-ip>:5000`.

All mutable data (your own sources, the lyric store, exported playlists, the folder-source config)
lives under `DATA_DIR` — `/data` inside the container, i.e. the persistent volume already wired up
in `docker-compose.yml`.

---

## How it works

```
Android app                              Docker flavor
┌─────────────────────────────┐          ┌──────────────────────────┐
│ WebView UI (SPA, bilingual) │          │  the same SPA (browser)  │
│ ├─ HTTP server  :8765       │          │  ├─ Python HTTP  :5000   │
│ ├─ DLNA control point       │  SSDP    │  ├─ DLNA control point   │
│ ├─ SMB client (jcifs-ng)    │ ───────► │  ├─ SMB (smbclient)      │
│ ├─ MediaStore library       │          │  ├─ local/mounted scan   │
│ └─ MusicFree plugin runtime │          │  └─ /__proxy data relay  │
└──────────────┬──────────────┘          └────────────┬─────────────┘
               │ SetURI + Play                        │ SetURI + Play
               ▼                                      ▼
        ┌──────────────────┐                  ┌──────────────────┐
        │   DLNA speaker   │                  │   DLNA speaker   │
        │  (renders audio) │                  │  (renders audio) │
        └────────┬─────────┘                  └────────┬─────────┘
                 │ HTTP GET                            │ HTTP GET
                 ▼                                     ▼
      phone storage / SMB / online CDN     local dirs · /stream?sid= relay
```

The control side only *issues commands*. Audio streams flow **directly from the source to the speaker**,
so casting costs almost nothing on the phone or the container.

The two builds differ only in *where the front end runs*: in a WebView on Android, in your browser for
Docker. The plugin runtime (`plugins-runtime.js`) is plain JavaScript, so it runs in both.

---

## Building the Android app from source

No Gradle required — the build is a plain toolchain script (aapt2 → javac → d8 → zip → sign):

```bash
# 1) one-time: fetch JDK 17 + Android build-tools 34 + platform android-34
bash android/setup_toolchain.sh          # installs into ./android-toolchain (or D:\android-toolchain)

# 2) build
cd android
ANDROID_TOOLCHAIN=/path/to/android-toolchain bash build.sh
# → android/build/SyncDlnaPlay-standalone-vX.Y.apk
```

A desktop regression harness is included: `bash android/tools/run_e2e.sh` boots the real Java backend
on `127.0.0.1:8765` and drives the actual frontend in headless Chromium — **32 end-to-end checks**,
including online search, stream resolution, Range requests, lyrics parsing and every panel.

On macOS use `build-macos.sh` instead (extra patches for the BSD toolchain and Apple's JDK paths):

```bash
cd android
ANDROID_TOOLCHAIN=$HOME/android-toolchain PY=python3 bash build-macos.sh
```

TV mode ships with two more suites under `android/tools/tvtest/`, runnable in one command:

```bash
bash android/tools/tvtest/run.sh          # both suites
bash android/tools/tvtest/run.sh --nav    # remote-navigation assertions only
```

The script boots its own backend on a free port (`DATA_DIR` lands in a temp dir, the repo is never
touched), then drives the real frontend in headless Chrome over CDP. It only ever calls
`window.__tvKey()` — the very entry point the native `MainActivity` calls — so the key path is
identical to a physical remote:

- **33 TV navigation assertions** (`nav_checks.js`, 14 scenarios): initial focus, four-way spatial
  movement, rail entry/exit and in-rail wrapping, panel scoping, slider ◀▶, media keys,
  **focus surviving 4.5 s of continuous re-renders**, tiered Back, and no jump-to-top after a full
  table repaint
- **11 non-TV regression checks** (`regression_checks.js`): without `?tv=1` the phone/desktop layout
  and existing features are untouched

> It needs at least one DLNA speaker/TV discoverable on the LAN (focus has to move across real list
> rows). With none found it says so and exits with code 3 instead of pretending to pass.

---

## Project layout

```
SyncDlnaPlay/
├── README.md                  ← you are here
├── README.zh-CN.md            ← 中文说明
├── docs/
│   ├── DOCKER.zh-CN.md        ← Docker 版完整部署文档（中文，含 iStoreOS 踩坑记录）
│   └── screenshots/
├── Dockerfile                 ┐
├── docker-compose.yml         ├─ 🐳 Docker control point (stdlib-only Python)
├── app/                       │    server.py / upnp.py / miniweb.py / plugins.py / smbtool.py / lyricstore.py
├── musicfree-bridge/          ┘    optional standalone Node bridge for online sources
└── android/                       📱 Standalone Android app (no-Gradle toolchain)
    ├── app/  (java + assets/www + res)
    │   └── assets/www/            ← ⭐ the single front end: the Docker build serves this exact folder
    ├── libs/ (jcifs-ng, bcprov, slf4j-nop)
    ├── build.sh / setup_toolchain.sh
    └── tools/ (E2E, screenshots, icons, packaging)
```

Docker back-end modules:

```
app/
├── server.py        routes + global state (DLNA control point, playback scheduler, all REST endpoints)
├── upnp.py          SSDP discovery / SOAP / DIDL parsing (stdlib only)
├── miniweb.py       hand-rolled Flask-compatible subset (routing, Range, JSON)
├── music_sources.py folder sources (local path / SMB, mounted via the host namespace)
├── plugins.py       plugin store — add/remove/enable MusicFree sources (port of Android's Plugins.java)
├── smbtool.py       SMB discovery & browsing (socket scan of 445 + smbclient / smbutil)
├── lyricstore.py    sibling .lrc lookup and the title-keyed lyric store
run-macos.sh         (one level up) start the server on macOS with HOST_IP auto-detected
```

---

## FAQ

<details>
<summary><b>No speaker is found</b></summary>

Phone and speaker must be on the same Wi-Fi; some routers block discovery via **AP isolation**.
Either way, playback automatically falls back to the phone so you're never blocked.
</details>

<details>
<summary><b>Where do downloads go?</b></summary>

A public music folder on the phone (`Music/…` by default) — visible in any file manager and in your
music app. You can change it (SD card / USB drive included) in *Library Manager → Download folder*.
</details>

<details>
<summary><b>Lyrics are a bit late when casting</b></summary>

Casting latency varies per file. Open the Now Playing page and use the <b>Slower 0.5s / Faster 0.5s</b>
calibration buttons — the offset is remembered.
</details>

<details>
<summary><b>An online source fails to resolve</b></summary>

Sources are community-run third-party APIs and they do go down sometimes. Switch to another source,
or add your own plugin URL in *Source manager*.
</details>

<details>
<summary><b>Battery & background</b></summary>

The app only runs while you use it. A persistent notification keeps background playback alive while casting.
</details>

<details>
<summary><b>Is my data sent anywhere?</b></summary>

No analytics, no accounts, no telemetry. Everything stays on your LAN except the online music sources you
explicitly search.
</details>

---

## Roadmap

- [ ] Car / Bluetooth routing as an output target
- [ ] Per-source lyric providers & translation lines
- [ ] Optional F-Droid / Play publishing
- [x] ~~Docker flavor: queue persistence across restarts~~ — done 2026-09-14 (the web UI and the Android app now share one front end, which carries queue persistence with it)

PRs are welcome — the frontend is a dependency-free SPA (`android/app/assets/www`), so most UI changes
need nothing but a text editor — and **one change now lands in both builds** (the Docker image serves
that same folder).

## Contributing

1. Fork & branch
2. `bash android/tools/run_e2e.sh` must stay green (32/32)
3. Keep both UI languages in sync — add the string to `android/app/assets/www/i18n.js`
4. Open a PR describing the user-visible change

## License

[MIT](LICENSE) © SyncDlnaPlay contributors

> Online music sources are community-maintained third-party plugins. SyncDlnaPlay is a playback tool —
> please respect the copyright of the music you stream or download, and use it for personal purposes.
