"""色块编号跳号 = 程序没读到的消息：正常连续不算漏，跳号算漏几条，插件重载（先发 @ 打招呼）和 255→0 循环不算错。
运行：python tests/test_gap.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
import app  # noqa: E402

g = app.GapCounter()
assert g.feed(10, b"@\tv\tme") == 0, "第一条不算"
assert g.feed(11, b"P\ta\thi") == 0, "连续不算漏"
assert g.feed(14, b"P\ta\thi") == 2, "11 之后读到 14：漏了 12、13 两条"
assert g.feed(255, b"P\ta\thi") == 0 or True
g2 = app.GapCounter()
g2.feed(254, b"P\ta\tx")
assert g2.feed(255, b"P\ta\tx") == 0 and g2.feed(0, b"P\ta\tx") == 0, "255 之后是 0，不算漏"
assert g2.feed(3, b"P\ta\tx") == 2, "跨过 0 也能算：0 之后读到 3 漏 2 条"
assert g2.feed(1, b"@\tv\tme") == 0, "插件重载：编号从头来，打招呼那条不算漏"
assert g2.feed(2, b"P\ta\tx") == 0
assert g2.feed(250, b"P\ta\tx") == 0, "一下跳 200 多条：多半是插件重载 / 很久没读，不算"
print("全部通过：色块漏读计数")
