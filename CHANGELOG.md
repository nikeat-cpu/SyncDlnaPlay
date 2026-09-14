# Changelog

All notable changes to SyncDlnaPlay are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); versions are `X.Y` (Android standalone) unless noted.

## [2.21] — 2026-09-14

### Changed
- **Simplified the playback-mode toolbar**: removed the redundant "In order" (顺序播放) chip — turning shuffle off already means sequential playback. The "Repeat all" and "Repeat one" chips are now toggleable: tapping an already-active loop chip turns the loop off and returns to sequential playback.

## [2.20] — 2026-09-14

### Added
- **Persistent play queue**: the current queue (tracks, play mode and position) is saved automatically and restored on next launch. Online tracks whose stream URLs have expired are re-resolved on restore, so the queue is always playable.
- **Save queue as a named playlist**: "💾 Save as" stores the current queue under a name (up to 50 playlists).
- **Quick switch to your 3 most recent playlists**: the Queue page shows the last 3 saved playlists as one-tap chips; "📂 My lists" opens a manager to load / rename / delete.
- **Export library list**: the Local Library page can export the current list as an `.m3u` file, saved to the app-private `playlists/` folder so it never appears as a phantom track in the media scanner.

## [2.12] — 2026-09-11

### Added
- **Bilingual UI (English / 简体中文)** — auto-detected from the system language, switchable in Settings.
  Full dictionary covers every screen, sheet, toast and dynamic string (`assets/www/i18n.js`).
- Settings → Language toggle.

### Changed
- Bottom navigation labels use a compact font in English so long labels fit on one line.
- Build script: toolchain path overridable via `ANDROID_TOOLCHAIN` env var.

## [2.11] — 2026-09-11

### Added
- **Immersive lyrics mode**: double-tap the lyrics area for full-screen glowing lyrics with
  playback controls and a volume slider pinned at the bottom. Double-tap anywhere to exit.

### Fixed
- Immersive lyrics area was capped by the normal-mode `max-height:40vh` rule.

## [2.10] — 2026-09-11

### Fixed
- **Seekbar jumping while casting**: a progress smoother now filters snapshot noise (< 2.5 s
  deviation ignored), seek actions get a 5 s grace period, and a drag window guards the slider.

## [2.9] — 2026-09-11

### Added
- **Manual lyric offset calibration**: ±0.5 s steps, ±10 s range, persisted; because casting
  latency varies with file size.

### Changed
- Now Playing page slimmed down to fit one screen (smaller lyric stage, duplicate transport
  controls removed — the mini player bar already has them).

## [2.8] — 2026-09-11

### Added
- **Download-while-playing** switch: online songs are queued for download automatically.
- Play-mode selector moved to the Queue page (duplicate random button removed).
- Cover/lyrics share the same stage: lyrics replace the cover when available.
- Bottom navigation renamed to uniform 4-character labels (正在播放 / 我的设备 / 本地曲库 / 在线搜索 / 播放列表).
- In-app user guide (Settings → About).

## [2.7] — 2026-09-11

### Added
- **Now Playing** became a first-class tab (first position).
- Source manager: set a **default source** (star) and the app **remembers the last source** used.
- Buttons gained a tactile 3D treatment (highlights, gradients, press states).

### Fixed
- Lyric highlight lag while casting: progress is now extrapolated on the phone clock and a
  300 ms timer drives highlighting.

## [2.6] — 2026-09-10

### Changed
- Renamed to **SyncDlnaPlay**; new app icon (adaptive + monochrome), watermark removed from the artwork.

### Fixed
- No-DLNA-device playback now **falls back to the phone** instead of erroring; local tracks
  resolve their stream URL automatically.

## [2.5] — 2026-09-10

### Added
- SMB panel: **Scan LAN** (parallel port-445 probe) and **Browse shares** (walk folders, pick one).
- Online sources are no longer hard-coded: install via URL / share code / file, disable or delete
  any source (`Plugins.java`).

### Changed
- Panel icons replaced with consistent SVG line icons.

## [2.4] — 2026-09-10

### Changed
- Single volume surface (the volume sheet) with ±1 buttons and long-press repeat; all other
  volume sliders removed.

### Fixed
- Test pages could leak into release APKs — build now aborts on leftover `_*.html` assets.

## [2.3] — 2026-09-10

### Changed
- Cyberpunk theme (neon cyan/magenta, HUD corners, scanlines) and a new logo with adaptive icons.

## [2.2] — 2026-09-10

### Changed
- De-webified: removed the “connect to server” flow, address inputs and scroll bars; the app now
  boots straight into the player.

## [2.1] — 2026-09-10

### Added
- Download folder selectable via SAF (default: public `Music/…`, visible to file managers).
- Volume sheet.
- SMB network shares as music folders (jcifs-ng, SMB1/2/3).
- Synced lyrics: local `.lrc` (UTF-8/GBK fallback) and online lyrics via plugins.

### Fixed
- “Download failed” was actually “download missing”: Android 11+ hides app-private folders.

## [2.0] — 2026-09-10

### Added
- **Standalone rewrite**: the DLNA control point, library scanner, HTTP server and plugin runtime
  all run inside the app — no home server required.

## Docker control point — 2026-09-14

### Changed: the web UI and the Android standalone app now share **one** front end
The Docker image used to ship its own desktop-oriented minified page (`app/static/index.html`, 56 KB) which
had drifted behind the Android app. It now serves the Android zero-dependency SPA (`android/app/assets/www`)
directly — one codebase for both, so every Android feature is available in the Docker build by construction
and there is no second UI to maintain.

### Added (endpoints the SPA needs that the Docker back end was missing)
- **Source management**: `/api/plugins`, `/api/plugins/code`, `/api/plugins/install`, `/api/plugins/remove`,
  `/api/plugins/toggle` — accepts a URL, raw plugin source, subscription JSON or a share code.
- **Online playback**: `/api/online/register` + `/stream?sid=` — the browser resolves a direct link with the
  plugin runtime, the server stores it and proxies the pull with the right Referer/Cookie so the speaker
  never hits a 403.
- **Plugin data proxy**: `/__proxy` — works around third-party CORS and the headers browsers forbid JS to set.
- **SMB**: `/api/smb/scan`, `/api/smb/browse` — scan for hosts with port 445 open, list shares, browse folders.
- **Lyrics**: `/api/lyric` (sibling `.lrc`), `/api/lyric/byname`, `/api/lyric/save` (title-keyed store).
- **Playlist export**: `/api/export/playlist` — writes `<DATA_DIR>/playlists/*.m3u`.
- **Audio by id**: `/media?id=` — local library (`L:`), absolute path (`f:`), or a DLNA ObjectID (resolved, 302).

### Added (modules)
- `app/plugins.py` — plugin store (port of Android's `Plugins.java`)
- `app/smbtool.py` — SMB discovery and browsing (socket scan of port 445 + `smbclient`, with a `smbutil` fallback on macOS)
- `app/lyricstore.py` — local lyrics and the title-keyed lyric store (UTF-8 → GBK fallback)

### Added (env vars)
`WEB_DIR`, `DATA_DIR`, `PLUGINS_DIR`, `BUILTIN_PLUGINS_DIR`, `STREAM_TTL_MS`

### Fixed
- **`miniweb` dropped the status code of plain-text responses**: `return "xxx", 404` was served as 200.
  `(body, status)` / `(body, status, headers)` tuples now keep their status.
- `music_sources` hard-coded `/data/music_sources.json`, which broke outside a container; it now follows
  `DATA_DIR` (still `/data` inside the image).
- The image installs `samba-client` (needed to list share names). Like `tzdata` this is best-effort and
  will not fail the build.

### Roadmap item completed
- [x] Persistent queue for the Docker build — queue persistence is a pure front-end feature (localStorage),
  so unifying the front end delivers it for free.

### Changed (build)
- `Dockerfile` now copies `android/app/assets/www` and `android/app/assets/plugins` into the image
  (`/app/web`, `/app/builtin-plugins`), so the build context must include `android/`.

## Docker flavor

The Docker control point shares the Android standalone app's front end; the back end is dependency-free
Python (host networking, multi-room delay alignment, SMB mounting via the host namespace). See
[docs/DOCKER.zh-CN.md](docs/DOCKER.zh-CN.md).

