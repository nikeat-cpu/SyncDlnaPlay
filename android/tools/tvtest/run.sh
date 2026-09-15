#!/usr/bin/env bash
# =====================================================================
# 电视模式一键验证 · run.sh
# =====================================================================
# 起项目自带的 Python 服务端（就是 run-macos.sh 起的那个，同一套前端），
# 再用无头 Chrome 跑两组断言：
#
#   1) nav_checks.js         33 项遥控器导航断言（?tv=1）
#   2) regression_checks.js  11 项非电视模式回归（不带 ?tv=1）
#
# 为什么需要真服务端：电视模式的焦点要在**真实的设备列表**里移动，
# 所以这批断言要求局域网里至少有一台 DLNA 音响 / 电视能被扫到。
# 扫不到设备时会明确提示并以退出码 3 结束，不会假装通过。
#
# 用法：
#   bash run.sh                 # 跑两组，用空闲端口，DATA_DIR 落在临时目录
#   bash run.sh --nav           # 只跑遥控器导航断言
#   bash run.sh --reg           # 只跑非电视模式回归
#   HTTP_PORT=5055 bash run.sh  # 指定端口
#   PYTHON=python3 TV_CHROME=/path/to/chrome bash run.sh
#
# 依赖：python3、Node 22+（全局 fetch / WebSocket，无需 npm install）、Google Chrome
# =====================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HERE="$ROOT/android/tools/tvtest"
PY="${PYTHON:-python3}"
NODE="${NODE:-node}"
PORT="${HTTP_PORT:-5055}"

DO_NAV=0
DO_REG=0
for a in "$@"; do
  [ "$a" = "--nav" ] && DO_NAV=1
  [ "$a" = "--reg" ] && DO_REG=1
done
if [ "$DO_NAV" = "0" ] && [ "$DO_REG" = "0" ]; then DO_NAV=1; DO_REG=1; fi

command -v "$PY"   >/dev/null 2>&1 || { echo "找不到 ${PY}（可用 PYTHON=... 指定）" >&2; exit 1; }
command -v "$NODE" >/dev/null 2>&1 || { echo "找不到 ${NODE}（需要 Node 22+，可用 NODE=... 指定）" >&2; exit 1; }

# DATA_DIR 指到临时目录：测试不该往仓库的 data/ 里写东西
TMPDATA="$(mktemp -d "${TMPDIR:-/tmp}/dlna-tvtest.XXXXXX")"
LOG="$TMPDATA/server.log"

cleanup() {
  if [ -n "${SRV_PID:-}" ] && kill -0 "$SRV_PID" 2>/dev/null; then
    kill "$SRV_PID" 2>/dev/null
    wait "$SRV_PID" 2>/dev/null
  fi
  # 失败时把临时目录留下来（截图 + 服务端日志），方便排查
  if [ "${KEEP:-0}" = "1" ]; then
    echo
    echo "（保留了现场：服务端日志与截图在 ${TMPDATA}）"
  else
    rm -rf "$TMPDATA"
  fi
}
trap cleanup EXIT INT TERM

# 注意：变量后面紧跟中文全角字符时必须写成 ${VAR}，
# 否则 bash 会把全角括号的首字节算进变量名（set -u 下直接报 unbound variable）。
echo "==> 启动服务端 :${PORT} （前端目录 android/app/assets/www，DATA_DIR=${TMPDATA}）"
HTTP_PORT="$PORT" DATA_DIR="$TMPDATA" HOST_IP=127.0.0.1 \
  "$PY" "$ROOT/app/server.py" >"$LOG" 2>&1 &
SRV_PID=$!

# 等端口真的在监听（curl 对未监听端口也可能被代理糊成 502，不能只看 curl）
for _ in $(seq 1 60); do
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && break
  elif command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -q ":$PORT " && break
  else
    "$PY" -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)" && break
  fi
  kill -0 "$SRV_PID" 2>/dev/null || { echo "服务端启动失败，日志："; tail -20 "$LOG"; exit 1; }
  sleep 0.5
done
echo "    服务端已就绪（首次扫描局域网设备需 5~10 秒，随后的就绪检查会等它）"
echo

FAIL=0
if [ "$DO_NAV" = "1" ]; then
  echo "########## 1/2  电视模式遥控器导航断言 ##########"
  "$NODE" "$HERE/tv_cdp.js" "http://127.0.0.1:$PORT/?tv=1" "$TMPDATA/tv_nav.png" "$HERE/nav_checks.js"
  RC=$?
  [ "$RC" != "0" ] && FAIL=1
  echo
fi

if [ "$DO_REG" = "1" ]; then
  echo "########## 2/2  非电视模式回归 ##########"
  "$NODE" "$HERE/tv_cdp.js" "http://127.0.0.1:$PORT/" "$TMPDATA/tv_regression.png" "$HERE/regression_checks.js"
  RC=$?
  [ "$RC" != "0" ] && FAIL=1
  echo
fi

if [ "$FAIL" = "0" ]; then
  echo "✅ 全部通过"
else
  echo "❌ 有失败项（上面每项都有 ❌ 标记；退出码 1）"
  KEEP=1
fi
exit "$FAIL"
