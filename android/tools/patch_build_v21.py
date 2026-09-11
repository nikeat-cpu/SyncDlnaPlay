# -*- coding: utf-8 -*-
"""build.sh 升级到 v2.1：接入 SMB 依赖（jcifs-ng + bcprov + slf4j），启用 multidex。"""
import io
import os
import sys

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build.sh")
s = io.open(P, encoding="utf-8").read()


def rep(old, new, label):
    global s
    n = s.count(old)
    print(("OK  " if n == 1 else "!!  ") + "%-30s 命中 %d" % (label, n))
    if n == 1:
        s = s.replace(old, new)


# 1) minSdk 24 -> 26（jcifs-ng 用到 API 26 的 java.util.Base64）
rep("  --min-sdk-version 24 --target-sdk-version 34 \\",
    "  --min-sdk-version 26 --target-sdk-version 34 \\", "aapt2 minSdk=26")

# 2) 预处理依赖
rep("""echo "[1/7] 编译资源 (aapt2 compile)\"""",
    """echo "[0/7] 预处理第三方依赖 (去 module-info / 多版本类)"
python tools/prep_libs.py

echo "[1/7] 编译资源 (aapt2 compile)\"""", "插入 prep_libs 步骤")

# 3) javac classpath 带上 libs
rep("""  -bootclasspath "$AJAR" -classpath "$AJAR" \\
  -d "$OUT/classes" "@$OUT/sources.txt\"""",
    """  -bootclasspath "$AJAR" -classpath "$AJAR;$PROJ/libs/*" \\
  -d "$OUT/classes" "@$OUT/sources.txt\"""", "javac classpath")

# 4) d8 把依赖 jar 一起转（并启用 multidex 输出）
rep("""echo "[4/7] 转换 dex (d8)"
CLASSES=$(python -c "
import os
out=[]
for dp,_,fns in os.walk('build/classes'):
    for fn in fns:
        if fn.endswith('.class'):
            out.append(os.path.abspath(os.path.join(dp,fn)).replace(chr(92),'/'))
print(' '.join(out))")
"$JAVA" -cp "$BT/lib/d8.jar" com.android.tools.r8.D8 \\
  --release --min-api 24 --lib "$AJAR" \\
  --output "$OUT/dex" $CLASSES""",
    """echo "[4/7] 转换 dex (d8) —— 含 SMB 客户端依赖，方法数超限会自动分包"
CLASSES=$(python -c "
import os
out=[]
for dp,_,fns in os.walk('build/classes'):
    for fn in fns:
        if fn.endswith('.class'):
            out.append(os.path.abspath(os.path.join(dp,fn)).replace(chr(92),'/'))
print(' '.join(out))")
LIBS=$(ls "$PROJ"/libs/dexin/*.jar | tr '\\n' ' ')
echo "    依赖 jar: $(ls "$PROJ"/libs/dexin/ | tr '\\n' ' ')"
"$JAVA" -cp "$BT/lib/d8.jar" com.android.tools.r8.D8 \\
  --release --min-api 26 --lib "$AJAR" \\
  --output "$OUT/dex" $CLASSES $LIBS
echo "    dex 数量: $(ls "$OUT/dex" | grep -c '\\.dex$' || echo 0)\"""", "d8 含依赖 + multidex")

# 5) 组装：传 dex 目录
rep("""python tools/pack_apk.py "$OUT/base.apk" "$OUT/dex/classes.dex" "$OUT/unsigned.apk\"""",
    """python tools/pack_apk.py "$OUT/base.apk" "$OUT/dex" "$OUT/unsigned.apk\"""", "pack_apk 传目录")

# 6) 产物名
rep('APK_NAME="yinxiang-guanjia-standalone-v2.0.1.apk"',
    'APK_NAME="yinxiang-guanjia-standalone-v2.1.apk"', "APK 名 v2.1")

io.open(P, "w", encoding="utf-8", newline="\n").write(s)

chk = io.open(P, encoding="utf-8").read()
print()
for k in ("prep_libs.py", "libs/dexin", "--min-api 26", "min-sdk-version 26",
          '"$OUT/dex" "$OUT/unsigned.apk"', "v2.1.apk"):
    print("%-34s %s" % (k, k in chk))
sys.exit(0)
