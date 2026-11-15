"""截屏幕上一块区域存成 PNG（物理像素坐标）。运行：python tests/shot.py x y w h out.png"""
import ctypes
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
ctypes.windll.shcore.SetProcessDpiAwareness(2)
import app  # noqa: E402

x, y, w, h = map(int, sys.argv[1:5])
g = app.Grabber(w, h)
g.grab(x, y)
buf = bytes(g.buf)
raw = bytearray()
for row in range(h):
    raw.append(0)
    line = buf[row * w * 4:(row + 1) * w * 4]
    for i in range(0, len(line), 4):
        raw += bytes((line[i + 2], line[i + 1], line[i]))


def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


png = (bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
       + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(bytes(raw)))
       + chunk(b"IEND", b""))
with open(sys.argv[5], "wb") as f:
    f.write(png)
print("saved", sys.argv[5])
