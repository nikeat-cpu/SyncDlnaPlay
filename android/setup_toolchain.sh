#!/usr/bin/env bash
# 一次性搭建精简 Android 构建工具链（不用 Gradle / Android Studio）
set -e
TC=/d/android-toolchain
SDK=$TC/sdk

mkdir -p "$TC/dl" "$SDK/cmdline-tools"
[ -f "$TC/dl/cmdline-tools.zip" ] || mv "/c/Users/TaoPC/WorkBuddy/2026-09-03-10-57-01/cmdline-tools.zip" "$TC/dl/"
ls -lh "$TC/dl/"

echo "=== 解压 JDK ==="
python - <<'PY'
import zipfile, os, shutil
tc = "D:/android-toolchain"
if not os.path.isdir(tc + "/jdk17"):
    zipfile.ZipFile(tc + "/dl/jdk17.zip").extractall(tc + "/_jdk_tmp")
    inner = [d for d in os.listdir(tc + "/_jdk_tmp") if d.startswith("jdk")][0]
    shutil.move(tc + "/_jdk_tmp/" + inner, tc + "/jdk17")
    os.rmdir(tc + "/_jdk_tmp")
print("jdk ok")
PY

echo "=== 解压 cmdline-tools ==="
python - <<'PY'
import zipfile, os, shutil
tc = "D:/android-toolchain"
if not os.path.isdir(tc + "/sdk/cmdline-tools/latest"):
    zipfile.ZipFile(tc + "/dl/cmdline-tools.zip").extractall(tc + "/_cl_tmp")
    shutil.move(tc + "/_cl_tmp/cmdline-tools", tc + "/sdk/cmdline-tools/latest")
    os.rmdir(tc + "/_cl_tmp")
print("cmdline-tools ok")
PY

export JAVA_HOME="D:\\android-toolchain\\jdk17"
export PATH="$TC/jdk17/bin:$PATH"
"$TC/jdk17/bin/java" -version

echo "=== 安装 SDK 组件 ==="
SDKM="D:\\android-toolchain\\sdk\\cmdline-tools\\latest\\bin\\sdkmanager.bat"
yes | "$SDKM" --sdk_root="D:\\android-toolchain\\sdk" "platform-tools" "platforms;android-34" "build-tools;34.0.0" 2>&1 | tail -25

echo "=== 结果 ==="
ls "$SDK/build-tools/" "$SDK/platforms/" 2>&1
echo "TOOLCHAIN_READY"
