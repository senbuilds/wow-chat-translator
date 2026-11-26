"""生成程序图标 assets/icon.ico（简体「译」）和 assets/icon_hant.ico（繁体「譯」）：暗红圆盘、金色描边、金色的字。
自己画的，不用任何游戏素材。

运行：python tools/make_icon.py   （需要 Pillow）
"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 1024                                    # 先画大的再缩小，边缘才平滑


def load_font(size):
    for fname in ("msyhbd.ttc", "msjhbd.ttc", "simhei.ttf", "msyh.ttc"):
        try:
            return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", fname), size)
        except OSError:
            pass
    return None


def make(char, stem):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((24, 24, S - 24, S - 24), fill=(58, 42, 14, 255))                 # 外圈暗金
    d.ellipse((52, 52, S - 52, S - 52), fill=(214, 168, 62, 255))               # 金边
    d.ellipse((96, 96, S - 96, S - 96), fill=(40, 8, 8, 255))                   # 内圈暗线
    d.ellipse((116, 116, S - 116, S - 116), fill=(112, 18, 18, 255))            # 暗红底
    d.ellipse((116, 116, S - 116, S - 380), fill=(134, 26, 24, 255))            # 上半部稍亮一点，有点立体感
    d.ellipse((150, 190, S - 150, S - 116), fill=(112, 18, 18, 255))

    font = load_font(560)
    box = d.textbbox((0, 0), char, font=font)
    x, y = (S - (box[2] - box[0])) / 2 - box[0], (S - (box[3] - box[1])) / 2 - box[1] - 10
    d.text((x + 10, y + 12), char, font=font, fill=(30, 6, 6, 255))             # 字的阴影
    d.text((x, y), char, font=font, fill=(255, 214, 92, 255))

    out = os.path.join(ROOT, "assets", stem + ".ico")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(ROOT, "assets", stem + ".png"))
    print("saved", out)


make("译", "icon")
make("譯", "icon_hant")
