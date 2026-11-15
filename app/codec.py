"""色块协议的编解码。必须和插件 ChatBridge.lua 里的协议保持一致。

网格 64 列 x 8 行，每格 4x4 物理像素，每个颜色通道 4 档 => 每格 6 bit。
第 0~3 格是识别标记，第 4~7 格是四档灰阶校准，其余是数据。
数据字节流：序号(1) 长度(2) 内容(n) 校验(2, Fletcher-16)，每 3 字节拆成 4 个符号。
"""

COLS, ROWS, CELL, HEADER = 64, 8, 4, 8
WIDTH, HEIGHT = COLS * CELL, ROWS * CELL
DATA_CELLS = COLS * ROWS - HEADER
MAX_PAYLOAD = DATA_CELLS * 6 // 8 - 5

# 每项是 r,g,b 的档位 0~3
FIXED = [(3, 0, 3), (0, 3, 0), (3, 3, 0), (0, 0, 3),
         (0, 0, 0), (1, 1, 1), (2, 2, 2), (3, 3, 3)]


def fletcher(data):
    s1 = s2 = 0
    for b in data:
        s1 = (s1 + b) % 255
        s2 = (s2 + s1) % 255
    return s1, s2


def build_symbols(payload: bytes, seq: int):
    payload = payload[:MAX_PAYLOAD]
    data = bytearray([seq % 256, len(payload) // 256, len(payload) % 256]) + payload
    data += bytes(fletcher(data))
    while len(data) % 3:
        data.append(0)
    syms = []
    for i in range(0, len(data), 3):
        v = data[i] << 16 | data[i + 1] << 8 | data[i + 2]
        syms += [v >> 18, (v >> 12) & 63, (v >> 6) & 63, v & 63]
    return syms


def encode_cells(payload: bytes, seq: int):
    """返回全部格子的颜色档位列表 [(r,g,b), ...]，供模拟器和测试使用。"""
    syms = build_symbols(payload, seq)
    cells = list(FIXED)
    for k in range(DATA_CELLS):
        s = syms[k] if k < len(syms) else 0
        cells.append((s >> 4, (s >> 2) & 3, s & 3))
    return cells


def cell_center(index):
    return (index % COLS) * CELL + CELL // 2, (index // COLS) * CELL + CELL // 2


def decode(pixel):
    """pixel(x, y) -> (r, g, b)，坐标相对色块左上角。成功返回 (seq, payload)，否则 None。"""
    def cell(i):
        return pixel(*cell_center(i))

    # 识别标记：高档位要明显亮，低档位要明显暗
    for i in range(4):
        rgb = cell(i)
        for ch in range(3):
            if FIXED[i][ch] == 3 and rgb[ch] < 150:
                return None
            if FIXED[i][ch] == 0 and rgb[ch] > 105:
                return None

    # 校准：每个通道四档的实际亮度，必须严格递增
    levels = [[cell(4 + lv)[ch] for lv in range(4)] for ch in range(3)]
    for ch in range(3):
        if any(levels[ch][k + 1] - levels[ch][k] < 20 for k in range(3)):
            return None

    def nearest(value, ch):
        table = levels[ch]
        return min(range(4), key=lambda lv: abs(table[lv] - value))

    def symbol(k):
        r, g, b = cell(HEADER + k)
        return nearest(r, 0) << 4 | nearest(g, 1) << 2 | nearest(b, 2)

    def read_bytes(count):
        groups = (count + 2) // 3
        if groups * 4 > DATA_CELLS:
            return None
        out = bytearray()
        for gi in range(groups):
            v = 0
            for k in range(4):
                v = v << 6 | symbol(gi * 4 + k)
            out += bytes([v >> 16, (v >> 8) & 255, v & 255])
        return out[:count]

    head = read_bytes(3)
    length = head[1] * 256 + head[2]
    if length > MAX_PAYLOAD:
        return None
    data = read_bytes(3 + length + 2)
    if data is None:
        return None
    if tuple(data[-2:]) != fletcher(data[:-2]):
        return None
    return data[0], bytes(data[3:-2])
