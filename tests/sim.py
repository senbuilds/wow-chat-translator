"""色块模拟器：不开游戏，在屏幕指定位置画出和插件一样的色块，用来测小程序的读屏和翻译。

运行：python tests/sim.py <x> <y> [gamma]
gamma 不为 1 时模拟显示器伽马/亮度调整，验证校准格能扛住。
"""
import ctypes
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
import codec  # noqa: E402

MESSAGES = [
    "@\t1.3\tSenhu",
    "W\t1,300,20,900,400\t",       # 翻译页的位置（相对色块原点）
    "P\tAllin\tlfm 1 healer for deadmines, pst",
    "P\tBrakk\tcan u brez me after this pull",
    "S\tMira\thi",
    "G\tTorv\twts [Glowing Brightwood Staff] 50g obo",
    "H\tZed\tty for the run, wanna do another one?",
    "P\t队友\t我也说中文",
    "!\tI\t",
    "R\tLeader\tdont stand in the fire lol, who has lust",
    "U\t\t",                         # 查用量
    "W\t0\t",                      # 收起翻译页：小程序应该立刻藏起来
]


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    x, y = int(sys.argv[1]), int(sys.argv[2])
    keep = "keep" in sys.argv        # keep：不发最后那条「收起」，方便截图
    args = [v for v in sys.argv if v != "keep"]
    gamma = float(args[3]) if len(args) > 3 else 1.0
    messages = MESSAGES[:-1] if keep else MESSAGES
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry("%dx%d+%d+%d" % (codec.WIDTH, codec.HEIGHT, x, y))
    canvas = tk.Canvas(root, width=codec.WIDTH, height=codec.HEIGHT, highlightthickness=0, bg="black")
    canvas.pack()

    def shade(level):
        return int(round(255 * (level / 3) ** gamma * (0.9 if gamma != 1.0 else 1.0) + (12 if gamma != 1.0 else 0)))

    state = {"i": 0}

    def step():
        canvas.delete("all")
        if state["i"] >= len(messages):
            root.destroy()
            return
        cells = codec.encode_cells(messages[state["i"]].encode("utf-8"), state["i"] + 1)
        for idx, (r, g, b) in enumerate(cells):
            cx, cy = (idx % codec.COLS) * codec.CELL, (idx // codec.COLS) * codec.CELL
            canvas.create_rectangle(cx, cy, cx + codec.CELL, cy + codec.CELL, width=0,
                                    fill="#%02x%02x%02x" % (shade(r), shade(g), shade(b)))
        state["i"] += 1
        root.after(700, step)

    root.after(1500, step)
    root.mainloop()


if __name__ == "__main__":
    main()
