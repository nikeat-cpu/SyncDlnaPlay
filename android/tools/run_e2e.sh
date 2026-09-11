#!/usr/bin/env bash
# =====================================================================
# 一键端到端验证（不需要真机 / 不需要 Android）
# =====================================================================
# 把 Android 上要跑的那套后端原样跑在 PC 的 8765 端口，再让无头 Chromium
# 当 WebView 加载真实前端，把「boot -> 载插件 -> 本机曲库 -> 在线搜索 ->
# 解析直链 -> /stream Range -> 入队 -> 下载」整条链路打一遍。
#
# 用法：
#   bash tools/run_e2e.sh           # 只跑浏览器端到端
#   bash tools/run_e2e.sh --probe   # 额外先跑一遍 ServerProbe（含真实投屏，会出声）
#   bash tools/run_e2e.sh --shots   # 额外生成各 Tab 界面截图
#
# 依赖：D:\android-toolchain\jdk17, build/classes(由 build.sh 产出)
# =====================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

PROJ="$(pwd -W)"
JDK="D:/android-toolchain/jdk17"
PY="C:/Users/TaoPC/.workbuddy/binaries/python/versions/3.13.12/python.exe"
PYV="C:/Users/TaoPC/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

DO_PROBE=0
DO_SHOTS=0
for a in "$@"; do
  [ "$a" = "--probe" ] && DO_PROBE=1
  [ "$a" = "--shots" ] && DO_SHOTS=1
done

if [ ! -d build/classes ]; then
  echo "缺少 build/classes，请先运行 bash build.sh"
  exit 1
fi

echo "[1/5] 编译桌面服务与探针"
mkdir -p build/livetest build/probe
"$JDK/bin/javac.exe" -encoding UTF-8 -nowarn -cp "build/classes;libs/*" -d build/livetest javatest/LiveServer.java
"$JDK/bin/javac.exe" -encoding UTF-8 -nowarn -cp "build/classes;libs/*" -d build/probe javatest/ServerProbe.java

if [ "$DO_PROBE" = "1" ]; then
  echo "[2/5] 跑 ServerProbe（含真实投屏，约 20 秒）"
  "$JDK/bin/java.exe" -Dfile.encoding=UTF-8 -cp "build/classes;build/probe;libs/*" ServerProbe --cast | tail -25
else
  echo "[2/5] 跳过 ServerProbe（加 --probe 可开启）"
fi

echo "[3/5] 启动桌面常驻服务 :8765"
"$JDK/bin/java.exe" -Dfile.encoding=UTF-8 -cp "build/classes;build/livetest;libs/*" LiveServer > build/live.log 2>&1 &
SRV=$!
# 等 READY
for i in $(seq 1 30); do
  grep -q READY build/live.log 2>/dev/null && break
  sleep 0.5
done
grep -q READY build/live.log && echo "    服务就绪" || { echo "    服务未起来："; cat build/live.log; kill $SRV 2>/dev/null; exit 1; }

cleanup() {
  echo "[5/5] 清理"
  kill $SRV 2>/dev/null
  wait $SRV 2>/dev/null
  rm -f app/assets/www/_e2e.html
}
trap cleanup EXIT

echo "[4/5] 生成测试页并在无头 Chromium 里跑端到端"
"$PY" tools/make_e2e_page.py
"$PYV" tools/e2e_browser.py
RC=$?

if [ "$DO_SHOTS" = "1" ]; then
  "$PY" tools/make_e2e_page.py >/dev/null
  "$PYV" tools/e2e_shots.py
fi

exit $RC
