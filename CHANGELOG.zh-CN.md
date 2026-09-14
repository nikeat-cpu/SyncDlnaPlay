# 更新日志 / Changelog

SyncDlnaPlay 的所有重要变更记录于此。
格式参考 [Keep a Changelog](https://keepachangelog.com/)；版本号 `X.Y` 指安卓独立版（除非另有说明）。

## [2.21] — 2026-09-14

### 变更
- **简化播放模式工具栏**：移除了与「随机播放」语义重复的「顺序播放」按钮——关闭随机即等于顺序播放。现在「列表循环」「单曲循环」改为可切换：再点一次已激活的循环按钮即关闭循环、回到顺序播放。

## [2.20] — 2026-09-14

### 新增
- **播放列表持久化**：当前播放列表（曲目、播放模式、选中位置）自动保存，下次打开自动恢复。在线曲目地址过期会在恢复时重新解析，保证列表始终可播。
- **播放列表「另存为」**：「💾 另存为」可把当前列表存为命名列表（最多 50 个）。
- **前 3 个最近列表快速切换**：播放列表页顶部直接显示最近 3 个已保存列表的一键 chip；「📂 我的」打开管理器，可载入 / 重命名 / 删除。
- **曲库列表导出**：本地曲库页可把当前列表导出为 `.m3u` 文件，保存到应用私有 `playlists/` 目录，不会在媒体库里变成幽灵曲目。

## Docker 控制端 — 2026-09-14

### 变更：网页与安卓独立版**合并为同一套前端**
Docker 版原先是一页单独的桌面版混淆页面（`app/static/index.html`，56KB），功能长期落后于安卓版。
现在改为**直接托管安卓那套零依赖 SPA**（`android/app/assets/www`）——两端共用一份代码，
安卓端有的功能在 Docker 版天然一致，以后也不再需要分别维护。

### 新增（补齐 SPA 需要、Docker 端原先缺失的接口）
- **音源管理**：`/api/plugins`、`/api/plugins/code`、`/api/plugins/install`、`/api/plugins/remove`、`/api/plugins/toggle`
  —— 支持网址 / 插件源码 / 订阅 JSON / 分享码四种添加方式，内置音源可停用、自建音源可增删。
- **在线音源取流**：`/api/online/register` + `/stream?sid=` —— 浏览器里用插件解析出直链后交给服务端，
  由服务端带 Referer/Cookie 代理回拉，音响拿到的地址才不会 403。
- **插件取数代理**：`/__proxy` —— 绕过第三方音源接口的 CORS 与其要求、浏览器禁止 JS 设置的请求头。
- **SMB 局域网**：`/api/smb/scan`、`/api/smb/browse` —— 扫描开着 445 的机器、列共享、逐级浏览子目录。
- **歌词**：`/api/lyric`（同目录同名 `.lrc`）、`/api/lyric/byname`、`/api/lyric/save`（标题歌词库）。
- **播放列表导出**：`/api/export/playlist` —— 落盘为 `<DATA_DIR>/playlists/*.m3u`。
- **按 id 取音频**：`/media?id=` —— 支持本地曲库 `L:`、绝对路径 `f:`，以及媒体服务器 ObjectID（解析后 302）。

### 新增模块
- `app/plugins.py` —— 音源仓库（对应安卓的 `Plugins.java`）
- `app/smbtool.py` —— SMB 发现与浏览（纯 socket 扫 445 + `smbclient`，macOS 自动回退 `smbutil`）
- `app/lyricstore.py` —— 本地歌词与标题歌词库（UTF-8 → GBK 自动回退）

### 新增环境变量
`WEB_DIR`、`DATA_DIR`、`PLUGINS_DIR`、`BUILTIN_PLUGINS_DIR`、`STREAM_TTL_MS`

### 修复
- **`miniweb` 会丢掉纯文本响应的状态码**：`return "xxx", 404` 这类返回的状态一直是 200。
  现在 `(body, status)` / `(body, status, headers)` 元组的状态码会被正确沿用。
- `music_sources` 的配置文件路径原先写死 `/data/music_sources.json`，非容器环境会报错；
  现在跟随 `DATA_DIR`（容器内仍是 `/data`）。
- Docker 镜像新增 `samba-client`（列共享名用），与 `tzdata` 一样是「尽力安装」，缺了不阻断构建。

### 顺带完成的 Roadmap 项
- [x] Docker 版队列持久化 —— 队列持久化本就是纯前端功能（localStorage），
      前端统一之后 Docker 版自动获得。

### 变更（构建）
- `Dockerfile` 现在会把 `android/app/assets/www` 与 `android/app/assets/plugins`
  一并打进镜像（`/app/web`、`/app/builtin-plugins`），因此构建上下文需要包含 `android/`。

## Docker 版本

Docker 控制端与安卓独立版**共用同一套前端**；后端为零依赖 Python（host 网络、多房间延迟对齐、
通过主机 namespace 挂载 SMB）。详见 [docs/DOCKER.zh-CN.md](docs/DOCKER.zh-CN.md)。
