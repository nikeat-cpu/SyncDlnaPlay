# DLNA 音响控制系统

在局域网内通过 DLNA/UPnP 协议，控制斐讯音响等 DLNA 渲染器播放音乐。
音乐源为 iStoreOS 上的共享存储（MiniDLNA 媒体服务器或直接挂载目录）。

## 架构

```
┌─────────────────┐         ┌──────────────────────────┐         ┌─────────────────┐
│  iStoreOS       │  浏览    │  Docker 容器（控制点）     │  推送   │  斐讯音响        │
│  MiniDLNA       │ ──────> │  零依赖 HTTP + UPnP CP    │ ─────> │  192.168.1.154  │
│  192.168.1.10   │  曲库    │  192.168.1.10:5000      │  URI    │  192.168.1.196  │
│  :8200          │         │  (镜像仅 59MB)           │         │                 │
└─────────────────┘         └──────────────────────────┘         └────────┬────────┘
         │                                                                 │
         └──────────────── 音响直接从 MiniDLNA 拉取音频流 ───────────────────┘
```

控制点只负责"发号施令"，音频流不经过容器，音响直接从音乐源拉取，性能开销极低。

**零第三方依赖**：Web 层由 `app/miniweb.py` 自研（Flask 兼容子集），
全部使用 Python 标准库。因此在 ARM 路由器上无需编译、无需 `pip install`，
镜像基于 `python:3.12-alpine` 仅 **59MB**，构建秒级完成，内存占用极低。
（对比：Flask 方案在 aarch64 上需拉取 7 个包并可能触发 MarkupSafe 编译。）

## 已验证环境

| 角色 | 设备 | 地址 |
|------|------|------|
| 控制点 | iStoreOS 24.10.5 (aarch64, Docker 27.3.1) | 192.168.1.10:5000 |
| 音乐源 | MiniDLNA (OpenWrt DLNA Server)，1560 首音频 | 192.168.1.10:8200 |
| 音乐目录 | `/mnt/mmc1-4/Music/` | 存储余量 53.4G |
| 音响 A | 斐讯 DLNA-AirSound (Amlogic) | 192.168.1.154:38520 |
| 音响 B | 斐讯 DLNA-AirDlan2 (Amlogic) | 192.168.1.196:38520 |

**已实测通过**（全部经由 iStoreOS 上的容器）：
设备发现（4 个渲染器）、曲库浏览、搜索、双音响同步播放、暂停/恢复、
音量调节、进度跳转、播放结束自动续播下一首、容器 HEALTHCHECK 正常。

## 功能特性（按常规播放器规格）

- **整目录/专辑一键播放全部**：在任意文件夹或专辑点「▶ 播放本目录全部」（接口 `/api/play-container`），
  服务端**递归**收集该目录下所有曲目建为队列并播放（含多层子文件夹）。
- **自动续播下一首**：当前曲目结束自动播放队列中的下一首。判定做了多音响兼容——
  等待全部在线音响都"结束"（报 `STOPPED` 或进度已到尾端），避免两台音响进度差导致漏判。
- **可见播放列表**：右侧面板显示队列，高亮当前曲目，点击任意曲目可跳转播放，可单独移除、可一键清空。
- **上一曲 / 下一曲**：在队列内导航（不再依赖设备自身 transport，避免与队列脱节）。
- **循环模式**：关 / 列表循环 / 单曲循环（点循环按钮循环切换）。
- **随机播放**：开启后按打乱顺序播放，当前曲目保持在播放顺序首位。
- **播放控制条**：播放/暂停、停止、进度条拖动跳转、音量调节，状态每 1.5 秒自动刷新。
- **单音响延时对齐**：每个音响卡片上可调 `delay_ms`（0~5000ms，步进 50ms）。
  播放时控制点会先对所有设备并发 `SetURI`，再按延时从小到大错峰下发 `Play`，
  让反应慢/网络慢的音响晚一点启动，从物理上减小两台之间的声差。
  `targets`（已选音响）和 `delays`（延时）会持久化到 `/mnt/mmc1-4/dlna-speaker-state/state.json`，
  容器重启后自动恢复。

### 后端关键接口
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/play` | 以曲目数组建队列并从 `index` 开始播放 |
| POST | `/api/play-container` | 递归收集某容器全部曲目并播放 |
| POST | `/api/control` | `play`/`pause`/`stop`/`next`/`prev` |
| POST | `/api/mode` | 设置 `repeat`(off/all/one) 与 `shuffle`(true/false) |
| POST | `/api/queue` | `action`: `add`/`remove`/`clear` 管理队列 |
| POST | `/api/jump` | 跳转到队列指定下标 |
| POST | `/api/seek` | 跳转到指定秒数 |
| POST | `/api/volume` | 设置音量 |
| POST | `/api/delay` | 设置某音响的启动延时 `delay_ms` |

## 部署到 iStoreOS

### 方式一：docker compose（推荐）

把整个 `dlna-speaker` 目录上传到 iStoreOS（如 `/root/dlna-speaker` 或挂载的磁盘目录）：

```bash
cd /root/dlna-speaker
docker compose up -d --build
```

访问 `http://192.168.1.10:5000`

### 方式二：docker run

```bash
cd /root/dlna-speaker
docker build -t dlna-speaker .

docker run -d \
  --name dlna-speaker \
  --network host \
  --restart unless-stopped \
  -e PREFER_NET=192.168.1. \
  -e HTTP_PORT=5000 \
  -e HOST_IP=192.168.1.10 \
  -e TZ=Asia/Shanghai \
  dlna-speaker
```

> **`--network host` 是必须的。** SSDP 组播发现被 bridge 网络隔离，用默认网络会发现不到任何音响。

> **不要挂载 `/etc/localtime`。** OpenWrt 上它是符号链接，Docker 会尝试
> `mkdir /etc/localtime` 并直接报 `file exists` 导致容器无法启动。
> 时区请用 `-e TZ=Asia/Shanghai`（镜像已尽力安装 tzdata，失败会自动回退）。

## 音乐源配置

系统支持两种音乐源，可在 Web 界面左上角切换。

### 1. DLNA 媒体服务器（默认，开箱即用）

iStoreOS 上已运行的 MiniDLNA 会被自动发现，直接浏览其曲库，音频 URL 形如
`http://192.168.1.10:8200/MediaItems/35.mp3`，由音响直接拉取。

无需任何额外配置。

### 2. 本地共享目录（可选）

如果音乐放在 SMB/NFS 共享里而 MiniDLNA 没有索引到，可把共享挂载到容器内：

1. 在 iStoreOS 上把共享挂载到本机路径（如 `/mnt/music`）
2. 修改 `docker-compose.yml`，取消这两行注释：

```yaml
      - MUSIC_DIR=/music
    volumes:
      - /mnt/music:/music:ro
```

3. 重启容器：`docker compose up -d`

此时容器会通过 `http://192.168.1.10:5000/media/歌曲.mp3` 把目录暴露给音响，
Web 界面切换到"本地共享目录"即可浏览。

## 配置参数

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `PREFER_NET` | 自动 | SSDP 使用的网段前缀，如 `192.168.1.`。多网卡时必填，否则可能选错网卡（如 Tailscale） |
| `HTTP_PORT` | 5000 | Web 服务端口 |
| `HOST_IP` | 自动探测 | 本机对外 IP，用于生成本地音乐的访问 URL |
| `MUSIC_DIR` | 空 | 本地音乐目录；留空则只用 DLNA 媒体服务器 |
| `POLL_INTERVAL` | 1.5 | 状态轮询间隔（秒） |
| `SCAN_INTERVAL` | 300 | 设备重新扫描间隔（秒） |
| `LOG_LEVEL` | INFO | 日志级别 |

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/state` | 全局状态（设备、队列、实时播放状态） |
| GET/POST | `/api/scan` | 重新扫描设备（默认异步） |
| POST | `/api/targets` | 设置目标音响 `{"udns":[...]}` |
| GET | `/api/library?source=dlna&container=1$4` | 浏览曲库 |
| GET | `/api/search?q=关键词` | 搜索歌曲 |
| POST | `/api/play` | 播放 `{"tracks":[...],"index":0}` |
| POST | `/api/control` | 传输控制 `{"action":"play\|pause\|stop\|next\|prev"}` |
| POST | `/api/volume` | 音量 `{"volume":30}` |
| POST | `/api/seek` | 跳转 `{"position":60}` |
| POST | `/api/resync` | 重新同步所有音响 |
| POST | `/api/jump` | 跳到队列指定曲目 |

## 关于双音响同步

DLNA 没有 AirPlay 2 / Chromecast 那种原生多房间同步机制。本系统的做法是
**先并发下发 URI、再并发下发 Play 指令**，把指令时间差压到最小。

实测两台斐讯音响进度差在 1 秒以内（且其中大部分是状态轮询的时间差，真实偏差更小）。
如果两个音响放在同一房间，细微偏差可能形成轻微回声感；放在不同房间则完全无感。

若发现偏差变大，点界面右上角"重新同步"按钮，会重新下发当前曲目对齐两者。

## 故障排查

**发现不到音响**
- 确认容器用了 host 网络：`docker inspect dlna-speaker | grep NetworkMode`
- 确认 `PREFER_NET` 与实际网段一致
- 进入容器手动测试：`docker exec dlna-speaker python -c "import sys;sys.path.insert(0,'app');import upnp;print([d['friendly_name'] for d in upnp.discover_renderers(prefer_net='192.168.1.')])"`

**能发现但播放没声音**
- 检查音响能否访问音乐 URL：在容器内 `wget -O /dev/null http://192.168.1.10:8200/MediaItems/35.mp3`
- 查看日志：`docker logs -f dlna-speaker`

**Web 界面打不开**
- 确认端口未被占用：`netstat -tlnp | grep 5000`
- iStoreOS 防火墙可能需要放行该端口

## 目录结构

```
dlna-speaker/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt          # 空：本项目零第三方依赖
├── app/
│   ├── upnp.py               # UPnP/DLNA 核心库（纯标准库）
│   ├── miniweb.py            # 极简 Web 层（Flask 兼容子集，纯标准库）
│   ├── server.py             # REST API + 播放控制逻辑
│   └── static/index.html     # Web 控制界面（无外部资源，单文件）
└── tools/                    # 开发与排查脚本
    ├── discover.py           # 扫描局域网 UPnP 设备
    ├── probe_minidlna.py     # 探测 MiniDLNA 曲库
    ├── test_lib.py           # 核心库测试
    ├── test_play.py          # 实机播放测试
    ├── e2e_test.py           # 端到端测试（API_BASE 可指向远程）
    └── ssh_run.py            # SSH 远程执行/上传（部署用）
```

## 常用运维命令

```bash
docker logs -f dlna-speaker                    # 看日志
docker restart dlna-speaker                    # 重启
docker compose up -d --build                   # 改代码后重新构建
docker inspect --format '{{.State.Health.Status}}' dlna-speaker   # 健康状态
```
