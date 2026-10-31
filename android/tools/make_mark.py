#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quiet-nocturne mark for SyncDlnaPlay.

One source of truth for:
  android/app/assets/www/logo.png
  res/drawable-xhdpi/tv_banner.png
  res/drawable/ic_stat.png
  res/mipmap-*/ic_launcher*.png

The mark is a teal-to-indigo disc, a white play triangle, and two
sound-arcs on each side (multi-room, not a HUD). No wordmark on the
icon — the name lives on the TV banner only.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
RES = os.path.join(ROOT, "app", "res")
WWW = os.path.join(ROOT, "app", "assets", "www")

INTER = "/usr/share/fonts/truetype/macos/Inter-SemiBold.ttf"
INTER_MED = "/usr/share/fonts/truetype/macos/Inter-Medium.ttf"

DENSITIES = [("mdpi", 1), ("hdpi", 1.5), ("xhdpi", 2), ("xxhdpi", 3), ("xxxhdpi", 4)]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def vgradient(size, c0, c1):
    im = Image.new("RGB", (size, size))
    px = im.load()
    for y in range(size):
        col = lerp(c0, c1, y / float(size - 1))
        for x in range(size):
            px[x, y] = col
    return im


def glow(size, cx, cy, radius, color, alpha):
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=color + (alpha,))
    return layer.filter(ImageFilter.GaussianBlur(radius * 0.42))


def master(size=1024):
    """Full-bleed icon. The disc sits inside the adaptive-icon safe circle."""
    bg = vgradient(size, (16, 26, 40), (9, 14, 24)).convert("RGBA")
    im = Image.alpha_composite(bg, glow(size, int(size * 0.28), int(size * 0.18),
                                        int(size * 0.46), (42, 196, 214), 78))
    im = Image.alpha_composite(im, glow(size, int(size * 0.82), int(size * 0.88),
                                        int(size * 0.40), (110, 124, 255), 64))

    cx = cy = size // 2
    R = int(size * 0.275)

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        [cx - R, cy - R + int(size * 0.018), cx + R, cy + R + int(size * 0.018)],
        fill=(0, 0, 0, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(size * 0.028)))
    im = Image.alpha_composite(im, shadow)

    # Disc: teal (top) → indigo (bottom), clipped to a circle.
    g = vgradient(size, (56, 214, 224), (124, 134, 255)).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
    g.putalpha(mask)
    im = Image.alpha_composite(im, g)

    # Soft top sheen inside the disc.
    sheen = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).ellipse(
        [cx - R, cy - R, cx + R, cy + int(R * 0.15)], fill=(255, 255, 255, 56))
    sheen = sheen.filter(ImageFilter.GaussianBlur(int(size * 0.02)))
    sm = Image.new("L", (size, size), 0)
    ImageDraw.Draw(sm).ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
    # Keep only pixels that are both in the sheen alpha and the disc.
    sa = sheen.getchannel("A")
    sa = Image.frombytes("L", (size, size), bytes(
        min(a, m) for a, m in zip(sa.tobytes(), sm.tobytes())))
    sheen.putalpha(sa)
    im = Image.alpha_composite(im, sheen)

    d = ImageDraw.Draw(im)
    # Play triangle, nudged right so it looks optically centered.
    s = size / 1024.0
    tri = [
        (cx - 78 * s, cy - 108 * s),
        (cx - 78 * s, cy + 108 * s),
        (cx + 132 * s, cy),
    ]
    d.polygon(tri, fill=(255, 255, 255, 255))

    # Sound arcs, left and right, inside the disc.
    def arcs(sign):
        # sign +1 = right side (arc bulges right), -1 = left
        for i, rad in enumerate((78, 118)):
            rad *= s
            # Box centered just outside the triangle.
            ox = (96 * s) * sign
            box = [cx + ox - rad, cy - rad, cx + ox + rad, cy + rad]
            width = int(max(6, 13 * s - i * 1))
            if sign > 0:
                d.arc(box, start=300, end=60, fill=(255, 255, 255, 235), width=width)
            else:
                d.arc(box, start=120, end=240, fill=(255, 255, 255, 235), width=width)

    arcs(1)
    arcs(-1)
    return im


def stat_icon(size=96):
    """Notification silhouette: white bars, transparent ground."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    heights = [0.46, 0.66, 0.92, 0.62, 0.42]
    n = len(heights)
    baseline = size * 0.78
    top_pad = size * 0.16
    span = baseline - top_pad
    bar_w = size * 0.10
    gap = size * 0.045
    total = n * bar_w + (n - 1) * gap
    x0 = (size - total) / 2.0
    for i, h in enumerate(heights):
        x = x0 + i * (bar_w + gap)
        y = baseline - span * h
        r = bar_w / 2.0
        d.rounded_rectangle([x, y, x + bar_w, baseline], radius=r, fill=(255, 255, 255, 255))
    return im


def banner(icon):
    W, H = 640, 360
    bg = Image.new("RGB", (W, H))
    px = bg.load()
    for y in range(H):
        col = lerp((14, 22, 34), (18, 26, 48), y / float(H - 1))
        for x in range(W):
            # slight indigo toward the right
            t = x / float(W - 1)
            colx = lerp(col, (28, 32, 64), t * 0.55)
            px[x, y] = colx
    im = bg.convert("RGBA")
    im = Image.alpha_composite(im, glow(W, 120, 80, 220, (42, 196, 214), 70).resize((W, H)))
    # glow() is square; rebuild glows at banner size
    im = bg.convert("RGBA")
    g1 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(g1).ellipse([20, -40, 340, 280], fill=(42, 196, 214, 70))
    g1 = g1.filter(ImageFilter.GaussianBlur(48))
    g2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(g2).ellipse([420, 140, 700, 420], fill=(110, 124, 255, 60))
    g2 = g2.filter(ImageFilter.GaussianBlur(50))
    im = Image.alpha_composite(im, g1)
    im = Image.alpha_composite(im, g2)

    # Paste the disc only — the master's square field would show as a box.
    disc = icon.copy()
    side = disc.size[0]
    cx = cy = side // 2
    R = int(side * 0.31)
    mask = Image.new("L", disc.size, 0)
    ImageDraw.Draw(mask).ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
    disc.putalpha(mask)
    ic = disc.resize((200, 200), Image.LANCZOS)
    im.paste(ic, (44, (H - 200) // 2), ic)

    draw = ImageDraw.Draw(im)
    title = ImageFont.truetype(INTER, 46)
    sub = ImageFont.truetype(INTER_MED, 22)
    draw.text((268, 124), "SyncDlnaPlay", font=title, fill=(242, 246, 250, 255))
    draw.rounded_rectangle([270, 180, 334, 184], radius=2, fill=(42, 212, 234, 255))
    draw.text((270, 198), "Multi-room DLNA", font=sub, fill=(168, 196, 208, 255))
    return im.convert("RGB")


def export_launcher(icon):
    """Adaptive + legacy densities. Foreground is the mark, background the field."""
    # Split: background = icon with the disc area softened to the field,
    # foreground = full icon (system mask crops it). Same approach as
    # make_icons_user.py so the adaptive layers stay aligned.
    side = icon.size[0]
    fg_ratio = 0.96
    for name, scale in DENSITIES:
        d = os.path.join(RES, "mipmap-" + name)
        os.makedirs(d, exist_ok=True)

        s = int(48 * scale)
        legacy = icon.resize((s, s), Image.LANCZOS).convert("RGBA")
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, s - 1, s - 1], radius=int(s * 0.225), fill=255)
        legacy.putalpha(mask)
        legacy.save(os.path.join(d, "ic_launcher.png"))

        s = int(108 * scale)
        icon.resize((s, s), Image.LANCZOS).convert("RGB").save(
            os.path.join(d, "ic_launcher_background.png"))

        canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        fs = int(s * fg_ratio)
        fg = icon.resize((fs, fs), Image.LANCZOS).convert("RGBA")
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

        # Monochrome: luminance → alpha, white fill.
        big = icon.resize((s, s), Image.LANCZOS).convert("L")
        mono = Image.new("RGBA", (s, s), (255, 255, 255, 0))
        mono.putalpha(big.point(lambda v: max(0, min(255, int((v - 40) * 1.7)))))
        mono.save(os.path.join(d, "ic_launcher_mono.png"))
        print("  mipmap-%s" % name)


def main():
    icon = master(1024)
    preview = os.path.join("/tmp", "syncdlna-mark.png")
    icon.save(preview)
    print("preview", preview)

    logo = icon.resize((384, 384), Image.LANCZOS)
    logo.save(os.path.join(WWW, "logo.png"))
    print("logo.png")

    export_launcher(icon)
    stat_icon(96).save(os.path.join(RES, "drawable", "ic_stat.png"))
    print("ic_stat.png")
    banner(icon).save(os.path.join(RES, "drawable-xhdpi", "tv_banner.png"), quality=95)
    print("tv_banner.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
