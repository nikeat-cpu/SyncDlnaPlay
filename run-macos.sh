#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 在 macOS 上启动 SyncDlnaPlay 服务端（网页控制台 http://<本机IP>:5000）
#
# 背景：macOS 上 upnp.local_ips() 不工作 —— 它用 Linux 专属的
#       ioctl(SIOCGIFADDR=0x8915) 加 Linux 的 ifreq 内存布局，在 BSD/macOS 上
#       取不到网卡 IP，导致 host_ip() 返回空串、音响回拉音频的地址变成
#       http://:5001，在线音源（MusicFree 桥）会失效。
#       本脚本自动探测本机局域网 IP 并通过 HOST_IP 环境变量喂给服务端，
#       无需修改任何源码。Docker/Linux 部署不受此问题影响。
#
# 用法：
#   ./run-macos.sh                        # 自动探测 IP 后启动
#   HOST_IP=192.168.1.50 ./run-macos.sh   # 手动指定
#   HTTP_PORT=8080 ./run-macos.sh         # 换端口
#   PYTHON=/path/to/python3 ./run-macos.sh
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HERE/app"
PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "找不到 python3；可用 PYTHON=/path/to/python3 ./run-macos.sh 指定" >&2
  exit 1
fi

detect_ip() {
  local iface ip
  iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')" || true
  if [ -n "${iface:-}" ]; then
    ip="$(ipconfig getifaddr "$iface" 2>/dev/null)" || true
  fi
  if [ -z "${ip:-}" ]; then
    for iface in $(ifconfig -l 2>/dev/null); do
      case "$iface" in
        lo*|utun*|gif*|stf*|awdl*|llw*|p2p*|bridge*) continue ;;
      esac
      ip="$(ipconfig getifaddr "$iface" 2>/dev/null)" || true
      [ -n "${ip:-}" ] && break
    done
  fi
  printf '%s' "${ip:-}"
}

if [ -z "${HOST_IP:-}" ]; then
  HOST_IP="$(detect_ip)"
  export HOST_IP
fi

PORT="${HTTP_PORT:-5000}"

echo "==> SyncDlnaPlay (macOS 服务端)"
echo "    工作目录   : $APP_DIR"
echo "    HOST_IP    : ${HOST_IP:-<未探测到 —— 在线音源回拉地址会失效，请用 HOST_IP=... 指定>}"
echo "    网页控制台 : http://${HOST_IP:-127.0.0.1}:${PORT}"
echo "    提示       : 启动时扫描局域网设备约需 5~10 秒，扫完再打开上面的地址"
echo "    停止       : Ctrl+C"
echo

cd "$APP_DIR"
exec "$PY" server.py
