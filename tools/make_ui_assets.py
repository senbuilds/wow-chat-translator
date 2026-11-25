"""生成启动器界面用的图：顶部横幅背景（渐变）和 Logo，按几种屏幕缩放比例各出一份（Tk 不能平滑缩放图片）。
用法：python tools/make_ui_assets.py   → assets/ui/hero_<百分比>.png、logo_<百分比>.png
"""
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "ui")
SCALES = (100, 125, 150, 175, 200, 225, 250, 300)
W, H = 480, 190          # 横幅的逻辑尺寸（100% 缩放时的像素）
LOGO = 46


def radial(size, cx, cy, rx, ry, color, alpha):
    """一个椭圆形的柔光：中心 alpha，往外渐隐。"""
    w, h = size
    layer = Image.new("RGBA", size, color + (0,))
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    steps = 60
    for i in range(steps, 0, -1):
        t = i / steps
        a = int(alpha * 255 * (1 - t) ** 1.6)
        d.ellipse([cx - rx * t, cy - ry * t, cx + rx * t, cy + ry * t], fill=a)
    layer.putalpha(mask)
    return layer


def hero(scale):
    w, h = int(W * scale), int(H * scale)
    top, bottom = (0x2a, 0x16, 0x0c), (0x14, 0x0c, 0x08)
    im = Image.new("RGBA", (w, h))
    px = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        px.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    im = Image.alpha_composite(im, radial((w, h), w * 0.85, h * 0.10, w * 0.75, h * 1.0, (0xaa, 0x24, 0x09), 0.55))
    im = Image.alpha_composite(im, radial((w, h), 0, h, w * 0.6, h * 0.85, (0xed, 0xaf, 0x00), 0.14))
    return im.convert("RGB")


def main():
    os.makedirs(OUT, exist_ok=True)
    icon = Image.open(os.path.join(ROOT, "assets", "icon.png")).convert("RGBA")
    for pct in SCALES:
        s = pct / 100
        hero(s).save(os.path.join(OUT, "hero_%d.png" % pct), optimize=True)
        n = int(LOGO * s)
        icon.resize((n, n), Image.LANCZOS).save(os.path.join(OUT, "logo_%d.png" % pct), optimize=True)
    total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
    print("ui assets:", len(os.listdir(OUT)), "files", total // 1024, "KB")


if __name__ == "__main__":
    main()
