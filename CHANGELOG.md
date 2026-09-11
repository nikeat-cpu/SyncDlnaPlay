# Changelog

All notable changes to SyncDlnaPlay are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); versions are `X.Y` (Android standalone) unless noted.

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

## Docker flavor

The Docker control point evolves independently (zero-dependency Python, host networking,
multi-room delay alignment, SMB mounting via the host namespace). See [docs/DOCKER.zh-CN.md](docs/DOCKER.zh-CN.md).
