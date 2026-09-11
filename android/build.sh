#!/usr/bin/env bash
# =====================================================================
# 音响管家 APK 构建脚本（不使用 Gradle / Android Studio）
#   aapt2 编译资源 -> javac 编译 -> d8 转 dex -> 组装 -> 对齐 -> 签名
#
# 依赖：D:\android-toolchain\{jdk17, sdk/build-tools/34.0.0, sdk/platforms/android-34}
# 用法： bash build.sh
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"

PROJ="$(pwd -W)"                                   # Windows 风格路径，供 .exe 使用
# 工具链位置可用环境变量覆盖：ANDROID_TOOLCHAIN=/path/to/android-toolchain ./build.sh
TOOLCHAIN="${ANDROID_TOOLCHAIN:-D:/android-toolchain}"
JDK="$TOOLCHAIN/jdk17"
BT="$TOOLCHAIN/sdk/build-tools/34.0.0"
AJAR="$TOOLCHAIN/sdk/platforms/android-34/android.jar"
APP="$PROJ/app"
OUT="$PROJ/build"

JAVA="$JDK/bin/java.exe"
JAVAC="$JDK/bin/javac.exe"
KEYTOOL="$JDK/bin/keytool.exe"
KS="$PROJ/keystore/debug.keystore"

# 清理旧产物。注意：本机 shell 对 rm -rf 有 safe-delete 包装器，删除整个 build 目录
# 时会半途失败并残留脏状态，因此改用 Python 逐个删除子项，并保留 uitest 等无关目录。
python - "$OUT" <<'PY'
import os, shutil, sys
out = sys.argv[1]
keep = {"uitest"}
if os.path.isdir(out):
    for name in os.listdir(out):
        if name in keep:
            continue
        p = os.path.join(out, name)
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except OSError:
            pass
else:
    os.makedirs(out, exist_ok=True)
PY
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"

echo "[0/8] 预处理第三方依赖 (去 module-info / 多版本类)"
python tools/prep_libs.py

# 打包前必须清掉 assets 里的临时测试页：_e2e.html 由 tools/make_e2e_page.py 生成，
# _splash.html 由截图脚本生成。它们都属于「打包前的残留」。
# 已踩过：构建时 _e2e.html 恰好还在，测试页被一起塞进了正式 APK。
echo "[1/8] 清理 assets 中的临时测试页"
python - "$APP/assets/www" <<'PY'
import os, sys
d = sys.argv[1]
removed = []
for name in ("_e2e.html", "_splash.html"):
    p = os.path.join(d, name)
    if os.path.exists(p):
        os.remove(p)
        removed.append(name)
left = [n for n in os.listdir(d) if n.startswith("_") and n.endswith(".html")]
if left:
    sys.exit("！！assets/www 里仍有临时页面：%s（会被打进 APK）" % left)
print("    已清理 %s；assets/www 干净" % (removed or "（无需清理）"))
PY

# 语言变体：BUILD_LANG=en|zh 时复制一份 assets 并改掉 i18n.js 的默认语言。
# 源目录不动；不设该变量 = 原版（跟随系统语言自动选择）。
ASSETS="$APP/assets"
APK_SUFFIX=""
if [ -n "${BUILD_LANG:-}" ]; then
  echo "[1b/8] 生成语言变体 assets (BUILD_LANG=$BUILD_LANG)"
  python tools/make_lang_assets.py "$APP/assets" "$OUT/assets_$BUILD_LANG" "$BUILD_LANG"
  ASSETS="$OUT/assets_$BUILD_LANG"
  APK_SUFFIX="-$BUILD_LANG"
fi

echo "[2/8] 编译资源 (aapt2 compile)"
"$BT/aapt2.exe" compile --dir "$APP/res" -o "$OUT/res.zip"

echo "[3/8] 链接资源并生成 R.java (aapt2 link)"
"$BT/aapt2.exe" link \
  -o "$OUT/base.apk" \
  -I "$AJAR" \
  --manifest "$APP/AndroidManifest.xml" \
  -A "$ASSETS" \
  --java "$OUT/gen" \
  --min-sdk-version 26 --target-sdk-version 34 \
  --auto-add-overlay \
  "$OUT/res.zip"

echo "[4/8] 编译 Java (javac)"
python - "$OUT/sources.txt" <<'PY'
import os, sys
out = []
for root in ("app/java", "build/gen"):
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(".java"):
                out.append(os.path.abspath(os.path.join(dp, fn)).replace("\\", "/"))
with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("    java 源文件:", len(out))
PY
"$JAVAC" -encoding UTF-8 -source 8 -target 8 -nowarn \
  -bootclasspath "$AJAR" -classpath "$AJAR;$PROJ/libs/*" \
  -d "$OUT/classes" "@$OUT/sources.txt"

echo "[5/8] 转换 dex (d8) —— 含 SMB 客户端依赖，方法数超限会自动分包"
CLASSES=$(python -c "
import os
out=[]
for dp,_,fns in os.walk('build/classes'):
    for fn in fns:
        if fn.endswith('.class'):
            out.append(os.path.abspath(os.path.join(dp,fn)).replace(chr(92),'/'))
print(' '.join(out))")
LIBS=$(ls "$PROJ"/libs/dexin/*.jar | tr '\n' ' ')
echo "    依赖 jar: $(ls "$PROJ"/libs/dexin/ | tr '\n' ' ')"
"$JAVA" -cp "$BT/lib/d8.jar" com.android.tools.r8.D8 \
  --release --min-api 26 --lib "$AJAR" \
  --output "$OUT/dex" $CLASSES $LIBS
echo "    dex 数量: $(ls "$OUT/dex" | grep -c '\.dex$' || echo 0)"

echo "[6/8] 组装 APK"
python tools/pack_apk.py "$OUT/base.apk" "$OUT/dex" "$OUT/unsigned.apk"

echo "[7/8] 对齐 (zipalign)"
"$BT/zipalign.exe" -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

echo "[8/8] 签名 (apksigner)"
if [ ! -f "$KS" ]; then
  mkdir -p "$(dirname "$KS")"
  "$KEYTOOL" -genkeypair -v \
    -keystore "$KS" -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=CN" >/dev/null 2>&1
  echo "    已生成调试证书"
fi
APK_NAME="SyncDlnaPlay-standalone-v2.12${APK_SUFFIX}.apk"
"$JAVA" -jar "$BT/lib/apksigner.jar" sign \
  --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --out "$OUT/$APK_NAME" "$OUT/aligned.apk"

"$JAVA" -jar "$BT/lib/apksigner.jar" verify --verbose "$OUT/$APK_NAME" | head -8

echo
echo "完成 → $OUT/$APK_NAME"
ls -lh "$OUT/$APK_NAME" | awk '{print "大小:", $5}'
