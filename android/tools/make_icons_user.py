# -*- coding: utf-8 -*-
"""用用户提供的设计图生成全套启动图标。

输入：一张方形设计图（可先用水印清理处理）。
输出：
  mipmap-*/ic_launcher.png            legacy 图标（圆角 + 透明角）
  mipmap-*/ic_launcher_background.png 自适应背景（取图角部深色纯色）
  mipmap-*/ic_launcher_foreground.png 自适应前景（图缩放到 72% 居中，内容落在 66dp 安全区）
  mipmap-*/ic_launcher_mono.png       单色主题图标（亮度→alpha 的白色剪影）

用法： python tools/make_icons_user.py <设计图路径>
"""
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(os.path.dirname(HERE), "app", "res")

DENSITIES = [("mdpi", 1), ("hdpi", 1.5), ("xhdpi", 2), ("xxhdpi", 3), ("xxxhdpi", 4)]
LEGACY_DP = 48
ADAPTIVE_DP = 108
FG_RATIO = 0.96          # 前景占 108dp 画布比例（全出血 + 边缘羽化）
LEGACY_RADIUS = 0.225    # legacy 圆角比例


def build(src):
    im = Image.open(src).convert("RGB")
    side = min(im.size)
    im = im.crop(((im.width - side) // 2, (im.height - side) // 2,
                  (im.width + side) // 2, (im.height + side) // 2))

    # 背景纯色：取四角中位点
    px = im.load()
    corners = [px[3, 3], px[side - 4, 3], px[3, side - 4], px[side - 4, side - 4]]
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    print("背景色: #%02x%02x%02x" % bg)

    # 单色模板（一次性生成 432px 母版）：亮度 → alpha，白色填充
    big = im.resize((432, 432), Image.LANCZOS).convert("L")
    mono_master = Image.new("RGBA", (432, 432), (255, 255, 255, 0))
    mono_master.putalpha(big.point(lambda v: max(0, min(255, int((v - 60) * 1.6)))))

    for name, scale in DENSITIES:
        d = os.path.join(RES, "mipmap-" + name)
        if not os.path.isdir(d):
            os.makedirs(d)

        # legacy：圆角方形
        s = int(LEGACY_DP * scale)
        legacy = im.resize((s, s), Image.LANCZOS).convert("RGBA")
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, s - 1, s - 1], radius=int(s * LEGACY_RADIUS), fill=255)
        legacy.putalpha(mask)
        legacy.save(os.path.join(d, "ic_launcher.png"))

        # 自适应背景：整图全出血铺满（与前景对齐，无缝）
        s = int(ADAPTIVE_DP * scale)
        im.resize((s, s), Image.LANCZOS).save(os.path.join(d, "ic_launcher_background.png"))

        # 自适应前景：整图放大居中，边缘 8% 羽化融入背景
        canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        fs = int(s * FG_RATIO)
        fg = im.resize((fs, fs), Image.LANCZOS).convert("RGBA")
        feather = Image.new("L", (fs, fs), 255)
        fp = feather.load()
        m = max(2, int(fs * 0.08))
        for y in range(fs):
            for x in range(fs):
                d0 = min(x, y, fs - 1 - x, fs - 1 - y)
                if d0 < m:
                    fp[x, y] = int(255 * d0 / m)
        fg.putalpha(feather)
        canvas.paste(fg, ((s - fs) // 2, (s - fs) // 2), fg)
        canvas.save(os.path.join(d, "ic_launcher_foreground.png"))

        # 单色
        mono_master.resize((s, s), Image.LANCZOS).save(os.path.join(d, "ic_launcher_mono.png"))
        print("  mipmap-%s 完成" % name)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    build(sys.argv[1])
