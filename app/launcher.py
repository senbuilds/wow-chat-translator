"""魔兽聊天翻译 · 启动器。

每次玩之前先开它：选游戏目录、装/更新插件、启动和停止翻译、看余额、兑换 CDK。
翻译本身由同一个程序以 --overlay 方式另起一个进程来跑（就是以前 start.bat 干的事）。
"""
import ctypes
import hashlib
import json
import os
import platform
import queue
import re
import shutil
import string
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.error
import urllib.request
from tkinter import filedialog

import app
import i18n
import version

APP_NAME = "魔兽聊天翻译"
APP_VERSION = os.environ.get("WOWTR_VERSION_OVERRIDE") or version.VERSION     # 环境变量只给测试用
UPDATE_BASE = app.PUBLIC_ENDPOINT + "/download/"
UPDATE_MANIFEST = UPDATE_BASE + "latest.json"
ADDON = "ChatBridge"
FONT = "Microsoft YaHei UI"

DEVICE_RE = re.compile(r"^d_[0-9a-f]{32}$")
PROMO_RE = re.compile(r"^(?!WOW-)[A-Z]{2,8}-[A-Z2-9]{5}$")    # 推广码，例如 ZAC-7KQ2M（兑换码都是 WOW- 开头）
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
FEEDBACK_KINDS = [("no_translate", "装好了但不翻译 / 看不到译文"), ("connect", "连不上游戏或翻译服务"),
                  ("billing", "充值、兑换码、余额"), ("wrong_translation", "翻译不对 / 黑话翻错"),
                  ("suggestion", "功能建议"), ("other", "其他")]

# 配色和官网一致（参考国服官网）：深棕底、金色只给小标题、羊皮纸色正文、细线分隔、平的按钮
BG, PANEL, EDGE = "#170e09", "#170e09", "#4a3b30"        # PANEL 和底色一样：分区靠细线，不靠框
FIELD = "#120b07"                                        # 输入框底色
GOLD, GOLD_DIM, TEXT, DIM, WHITE = "#edaf00", "#edaf00", "#ebdec2", "#b1997f", "#ffffff"
BTN, BTN_HOVER, BTN_DOWN = "#aa2409", "#c22c0c", "#8a1d07"   # 主按钮：红底白字
SEC, SEC_HOVER, SEC_DOWN = "#2a1e15", "#3a2a1d", "#22170f"   # 次按钮：深棕底
BTN_OFF, OFF_TEXT, OFF_EDGE = "#211710", "#6f604f", "#2e241c"
GOOD, BAD, WARN = "#8fc46a", "#e8664f", "#edaf00"
CARD, CARD_LINE, LINE_SOFT = "#24170f", "#3d2c20", "#2e2119"     # 卡片底色、卡片描边、分隔线
UI_SCALES = (100, 125, 150, 175, 200, 225, 250, 300)            # assets/ui 里预先生成的缩放比例
FLAVOR_NAMES = {"_forever_": "魔兽世界「无限」", "_retail_": "魔兽世界 正式服", "_classic_": "魔兽世界 怀旧服",
                "_classic_era_": "魔兽世界 经典怀旧服", "_classic_beta_": "怀旧服测试服", "_ptr_": "正式服测试服",
                "_beta_": "测试服"}


def dark_titlebar(win):
    """Windows 10/11 的标题栏改成深色，和窗口里面一致。不支持的系统什么也不做。"""
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        on = ctypes.c_int(1)
        for attr in (20, 19):                    # DWMWA_USE_IMMERSIVE_DARK_MODE（新 / 旧编号）
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
    except Exception:
        pass


def resource(*parts):
    """打包后资源在 _MEIPASS 里，开发时在项目根目录。"""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


LAUNCHER_CFG = os.path.join(os.path.dirname(app.CONFIG_PATH), "launcher.json")


def load_settings():
    try:
        with open(LAUNCHER_CFG, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def save_settings(settings):
    os.makedirs(os.path.dirname(LAUNCHER_CFG) or ".", exist_ok=True)
    with open(LAUNCHER_CFG, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 游戏目录和插件
# ---------------------------------------------------------------------------

def game_flavors(game_dir):
    """游戏目录下的各个版本文件夹（_retail_、_forever_ 这种），有 Interface 目录或游戏程序的才算。"""
    found = []
    try:
        for name in sorted(os.listdir(game_dir)):
            path = os.path.join(game_dir, name)
            if name.startswith("_") and name.endswith("_") and os.path.isdir(path):
                has_exe = any(f.lower().startswith("wow") and f.lower().endswith(".exe") for f in os.listdir(path))
                if has_exe or os.path.isdir(os.path.join(path, "Interface")):
                    found.append(name)
    except OSError:
        pass
    return found


def find_game_dir():
    """自动找魔兽的安装目录：先查注册表，再扫各个盘的常见位置。"""
    candidates = []
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key in (r"SOFTWARE\WOW6432Node\Blizzard Entertainment\World of Warcraft",
                        r"SOFTWARE\Blizzard Entertainment\World of Warcraft"):
                try:
                    with winreg.OpenKey(root, key) as k:
                        candidates.append(winreg.QueryValueEx(k, "InstallPath")[0])
                except OSError:
                    pass
    except ImportError:
        pass
    for drive in string.ascii_uppercase:
        root = drive + ":\\"
        if os.path.isdir(root):
            for sub in ("World of Warcraft", r"Program Files (x86)\World of Warcraft", r"Program Files\World of Warcraft",
                        r"Games\World of Warcraft", r"Battle.net\World of Warcraft"):
                candidates.append(os.path.join(root, sub))
    for path in candidates:
        path = os.path.normpath(path)
        if path.lower().endswith("_"):                  # 注册表里有时记的是 ...\_retail_\
            path = os.path.dirname(path)
        if game_flavors(path):
            return path
    return ""


def toc_version(toc_path):
    try:
        with open(toc_path, encoding="utf-8") as f:
            for line in f:
                if line.lower().startswith("## version:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def addon_dir(game_dir, flavor):
    return os.path.join(game_dir, flavor, "Interface", "AddOns", ADDON)


def version_key(v):
    return [int(p) if p.isdigit() else 0 for p in (v or "0").split(".")]


# ---------------------------------------------------------------------------
# 检查更新：服务器上的 latest.json 写着最新版本号、安装包地址和它的 SHA-256。
# 下载完先核对 SHA-256，对不上就丢掉；地址只认我们自己域名下的 /download/。
# ---------------------------------------------------------------------------

def fetch_latest():
    """返回 (更新信息, 错误说明)。"""
    try:
        req = urllib.request.Request(UPDATE_MANIFEST, headers={"Cache-Control": "no-cache",
                                                               "User-Agent": "WoWTranslator/" + APP_VERSION})
        with urllib.request.urlopen(req, timeout=10) as r:
            info = json.loads(r.read(65536).decode("utf-8"))
    except Exception:
        return None, "连不上更新服务器"
    ok = (isinstance(info, dict) and re.fullmatch(r"\d+(\.\d+){1,3}", str(info.get("version", "")))
          and str(info.get("url", "")).startswith(UPDATE_BASE) and ".." not in str(info.get("url", ""))
          and re.fullmatch(r"[0-9a-f]{64}", str(info.get("sha256", ""))))
    return (info, None) if ok else (None, "更新信息格式不对")


def download_update(info, progress):
    """下载安装包到临时目录并核对 SHA-256。返回 (文件路径, 错误说明)。"""
    path = os.path.join(tempfile.gettempdir(), "WoWTranslatorSetup-%s.exe" % info["version"])
    part, digest, done = path + ".part", hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(info["url"], timeout=30) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or info.get("size") or 0)
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                progress(done, total)
    except Exception:
        return None, "下载失败，请检查网络后再试"
    if digest.hexdigest() != info["sha256"]:
        os.remove(part)
        return None, "下载的文件校验不对，已经丢掉了。请稍后再试"
    os.replace(part, path)
    return path, None


def desktop_dir():
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)      # CSIDL_DESKTOPDIRECTORY
    return buf.value


# ---------------------------------------------------------------------------
# 小部件
# ---------------------------------------------------------------------------

def _scale_of(widget):
    return max(1.0, widget.winfo_fpixels("1i") / 96.0)


def round_rect(cv, x0, y0, x1, y1, r, **kw):
    """Canvas 上画圆角矩形（平滑多边形）。"""
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1,
           x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, splinesteps=16, **kw)


class WowButton(tk.Canvas):
    """圆角平按钮。primary=True：红底白字（每块里最主要的那个操作）；否则深棕底、细线边。
    width 按字符数算（和以前的 Label 按钮一样），pack(fill="x") 时会跟着撑满。"""

    def __init__(self, parent, text, command, width=9, primary=False, height=34):
        k = _scale_of(parent)
        self.font = tkfont.Font(family=FONT, size=10, weight="bold")
        self.colors = (BTN, BTN_HOVER, BTN_DOWN, WHITE, BTN) if primary else (SEC, SEC_HOVER, SEC_DOWN, TEXT, EDGE)
        w = max(self.font.measure("0") * width + int(16 * k), self.font.measure(text) + int(28 * k))
        super().__init__(parent, width=w, height=int(height * k), bg=parent.cget("bg"), highlightthickness=0, bd=0,
                         cursor="hand2")
        self.k, self.text, self.command, self.enabled, self.state = k, text, command, True, 0
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._paint(1))
        self.bind("<Leave>", lambda e: self._paint(0))
        self.bind("<ButtonPress-1>", lambda e: self._paint(2))
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), int(self.cget("width"))), int(self.cget("height"))
        if self.winfo_width() > 1:
            w = self.winfo_width()
        fill = self.colors[self.state] if self.enabled else BTN_OFF
        edge = self.colors[4] if self.enabled else OFF_EDGE
        round_rect(self, 1, 1, w - 2, h - 2, int(6 * self.k), fill=fill, outline=edge)
        self.create_text(w // 2, h // 2, text=self.text, font=self.font,
                         fill=self.colors[3] if self.enabled else OFF_TEXT)

    def _paint(self, state):
        if self.enabled:
            self.state = state
            self._draw()

    def _click(self, event):
        if self.enabled:
            self._paint(1)
            if 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
                self.command()

    def set(self, text=None, enabled=None):
        if text is not None:
            self.text = text
        if enabled is not None:
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
            self.state = 0
        self._draw()


class Card(tk.Canvas):
    """圆角卡片。往 card.inner 里放东西；高度跟着内容走，宽度跟着外面。"""

    def __init__(self, parent, fill=CARD, outline=CARD_LINE, radius=10, pad=16):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0, height=10, width=1)
        k = _scale_of(parent)
        self.r, self.p, self.fill, self.outline, self.min_h = int(radius * k), int(pad * k), fill, outline, 0
        self.inner = tk.Frame(self, bg=fill)
        self.win = self.create_window(self.p, self.p, window=self.inner, anchor="nw")
        self.bind("<Configure>", self._layout)
        self.inner.bind("<Configure>", lambda e: self.fit())

    def need(self):
        return self.inner.winfo_reqheight() + 2 * self.p

    def fit(self):
        h = max(self.need(), self.min_h)
        if int(float(self.cget("height"))) != h:
            self.configure(height=h)

    def _layout(self, e):
        self.itemconfigure(self.win, width=max(1, e.width - 2 * self.p))
        self.delete("bg")
        round_rect(self, 1, 1, e.width - 2, e.height - 2, self.r, fill=self.fill, outline=self.outline, tags="bg")
        self.tag_lower("bg")


class Link(tk.Label):
    """文字按钮（底部那排）。和 WowButton 一样有 set(text, enabled)。"""

    def __init__(self, parent, text, command, **kw):
        super().__init__(parent, text=text, bg=parent.cget("bg"), fg=TEXT, font=(FONT, 10), cursor="hand2", **kw)
        self.command, self.enabled = command, True
        self.bind("<Enter>", lambda e: self.enabled and self.configure(fg=GOLD))
        self.bind("<Leave>", lambda e: self.configure(fg=TEXT if self.enabled else OFF_TEXT))
        self.bind("<ButtonRelease-1>", lambda e: self.enabled and self.command())

    def set(self, text=None, enabled=None):
        if text is not None:
            self.configure(text=text)
        if enabled is not None:
            self.enabled = enabled
            self.configure(fg=TEXT if enabled else OFF_TEXT, cursor="hand2" if enabled else "arrow")


class Echo:
    """一句提示同时写到两个地方（主窗口的提示行、兑换小窗口），主窗口那行没字就收起来。"""

    def __init__(self, *labels, on_change=None):
        self.labels, self.on_change = labels, on_change

    def configure(self, text=None, fg=None, **_):
        for lb in self.labels:
            kw = {}
            if text is not None:
                kw["text"] = text
            if fg is not None:
                kw["fg"] = fg
            lb.configure(**kw)
        if self.on_change:
            self.on_change()

    config = configure

    def cget(self, key):
        return self.labels[0].cget(key)


def panel(parent, title):
    """一块内容：上面一条细线，金色小标题。返回里面可以放东西的 Frame。"""
    tk.Frame(parent, bg=EDGE, height=1).pack(fill="x")
    inner = tk.Frame(parent, bg=PANEL, pady=10)
    inner.pack(fill="x", pady=(0, 8))
    tk.Label(inner, text=title, bg=PANEL, fg=GOLD_DIM, font=(FONT, 10, "bold"), anchor="w").pack(fill="x", pady=(0, 6))
    return inner


# ---------------------------------------------------------------------------
# 启动器窗口
# ---------------------------------------------------------------------------

def icon_name():
    """窗口 / 任务栏图标：繁体模式用「譯」字的那个。"""
    name = "icon_hant.ico" if i18n.mode() == "hant" else "icon.ico"
    return name if os.path.exists(resource("assets", name)) else "icon.ico"


def hant_url(url):
    """服务器给的领取 / 验证链接：繁体模式下换成官网繁体版的同一页。"""
    if i18n.mode() == "hant" and url.startswith("https://wow.husen.ca/") and not url.startswith("https://wow.husen.ca/hant/"):
        return "https://wow.husen.ca/hant/" + url[len("https://wow.husen.ca/"):]
    return url


class Launcher:
    def __init__(self):
        self.cfg = app.load_config()
        if not os.path.exists(app.CONFIG_PATH):
            app.save_config(self.cfg)
        i18n.set_mode(self.cfg.get("lang", "auto"))      # 简体 / 繁体：界面文字在 Tk 这一层统一转换
        i18n.install_tk_hook()
        self.settings = load_settings()
        self.relay = app.Relay(self.cfg)
        self.proc = None
        self.events = queue.Queue()
        self.service_ok = None

        root = self.root = tk.Tk()
        root.title("ChatBridge " + APP_NAME)
        dark_titlebar(root)
        root.configure(bg=BG)
        root.resizable(False, False)
        try:
            root.iconbitmap(resource("assets", icon_name()))
        except tk.TclError:
            pass
        k = self.k = max(1.0, root.winfo_fpixels("1i") / 96.0)
        pct = min(UI_SCALES, key=lambda v: abs(v - k * 100))
        self.hero_img = tk.PhotoImage(file=resource("assets", "ui", "hero_%d.png" % pct))
        self.logo_img = tk.PhotoImage(file=resource("assets", "ui", ("logo_hant_%d.png" if i18n.mode() == "hant" else "logo_%d.png") % pct))
        W, HH = self.hero_img.width(), self.hero_img.height()
        P = int(24 * k)                                       # 左右留白
        wrap = W - 2 * P

        # --- 顶部横幅：Logo、英文名（主）、中文名（副）、广告语 ---
        hero = self.hero = tk.Canvas(root, width=W, height=HH + int(40 * k), bg=BG, highlightthickness=0, bd=0)
        hero.pack(fill="x")
        hero.create_image(0, 0, image=self.hero_img, anchor="nw")
        hero.create_image(P, int(22 * k), image=self.logo_img, anchor="nw")
        tx = P + self.logo_img.width() + int(12 * k)
        hero.create_text(tx, int(18 * k), text="ChatBridge", fill=WHITE, anchor="nw", font=("Segoe UI", 21, "bold"))
        hero.create_text(tx, int(52 * k), text="魔兽聊天翻译 · Translator", fill=DIM, anchor="nw", font=(FONT, 10))
        x, y = P, HH - int(62 * k)
        for piece, color in (("别只会打 ", TEXT), ("ty", GOLD), (" 和 ", TEXT), ("gg", GOLD), ("。", TEXT)):
            item = hero.create_text(x, y, text=piece, fill=color, anchor="nw", font=(FONT, 10))
            x = hero.bbox(item)[2]

        # --- 运行状态条（压在横幅下沿）---
        play = Card(hero, fill="#1f150e", outline="#4f3a2a", radius=8, pad=10)
        hero.create_window(P, HH - int(26 * k), window=play, anchor="nw", width=W - 2 * P)
        row = play.inner
        self.run_dot = tk.Label(row, text="●", bg=play.fill, fg=DIM, font=(FONT, 11))
        self.run_dot.pack(side="left", padx=(int(6 * k), 0))
        self.run_label = tk.Label(row, text="未启动", bg=play.fill, fg=WHITE, font=(FONT, 12, "bold"))
        self.run_label.pack(side="left", padx=(int(6 * k), 0))
        self.run_hint = tk.Label(row, text="", bg=play.fill, fg=DIM, font=(FONT, 9))
        self.run_hint.pack(side="left", padx=(int(10 * k), 0))
        self.stop_button = WowButton(row, "停止", self.stop, width=6)
        self.start_button = WowButton(row, "启动", self.start, width=6, primary=True)
        self.start_button.pack(side="right")

        self.play, self.hero_h = play, HH

        body = tk.Frame(root, bg=BG, padx=P)
        body.pack(fill="both", expand=True)

        # --- 两块：余额 / 游戏 ---
        tiles = tk.Frame(body, bg=BG)
        tiles.pack(fill="x", pady=(int(12 * k), 0))
        tiles.grid_columnconfigure(0, weight=115, uniform="tile")
        tiles.grid_columnconfigure(1, weight=100, uniform="tile")
        bal = Card(tiles, pad=16)
        bal.grid(row=0, column=0, sticky="new", padx=(0, int(6 * k)))
        game = Card(tiles, pad=16)
        game.grid(row=0, column=1, sticky="new", padx=(int(6 * k), 0))
        self.tiles = (bal, game)

        b = bal.inner
        tk.Label(b, text="余额", bg=CARD, fg=DIM, font=(FONT, 9), anchor="w").pack(fill="x")
        self.balance_label = tk.Label(b, text="查询中…", bg=CARD, fg=WHITE, font=("Segoe UI", 20, "bold"), anchor="w")
        self.balance_label.pack(fill="x")
        self.balance_sub = tk.Label(b, text="", bg=CARD, fg=GOLD, font=(FONT, 9), anchor="w", justify="left",
                                    wraplength=int(170 * k))
        self.balance_sub.pack(fill="x")
        self.bal_buttons = tk.Frame(b, bg=CARD)
        self.bal_buttons.pack(fill="x", side="bottom", pady=(int(12 * k), 0))
        self.trial_button = WowButton(self.bal_buttons, "领取免费 200 条", self.claim_trial, width=12, primary=True)
        self.redeem_open = WowButton(self.bal_buttons, "兑换 / 推广码", self.open_redeem, width=12, primary=True)
        self.redeem_link = tk.Label(self.bal_buttons, text="已有兑换码 / 推广码 ›", bg=CARD, fg=GOLD, font=(FONT, 9),
                                    cursor="hand2", anchor="w")
        self.redeem_link.bind("<ButtonRelease-1>", lambda e: self.open_redeem())
        self.redeem_open.pack(fill="x")
        self.trial_polls = 0

        g = game.inner
        tk.Label(g, text="游戏", bg=CARD, fg=DIM, font=(FONT, 9), anchor="w").pack(fill="x")
        self.game_name = tk.Label(g, text="", bg=CARD, fg=TEXT, font=(FONT, 10), anchor="w", justify="left",
                                  wraplength=int(150 * k))
        self.game_name.pack(fill="x", pady=(int(4 * k), 0))
        self.game_status = tk.Label(g, text="", bg=CARD, fg=GOOD, font=(FONT, 10), anchor="w", justify="left",
                                    wraplength=int(150 * k))
        self.game_status.pack(fill="x")
        self.game_buttons = tk.Frame(g, bg=CARD)
        self.game_buttons.pack(fill="x", side="bottom", pady=(int(12 * k), 0))
        self.addon_action = WowButton(self.game_buttons, "安装插件", self.install_addon, width=10, primary=True)
        self.game_open = WowButton(self.game_buttons, "游戏设置", self.open_game, width=10)
        self.game_open.pack(fill="x")


        # 提示行：兑换、领取试用、装插件的结果（没字时收起来）
        self.notice = tk.Label(body, text="", bg=BG, fg=DIM, font=(FONT, 9), anchor="w", justify="left", wraplength=wrap)
        self.notice_anchor = tk.Frame(body, bg=BG, height=1)
        self.notice_anchor.pack(fill="x")

        # --- 底部一排文字按钮 ---
        tk.Frame(body, bg=LINE_SOFT, height=1).pack(fill="x", pady=(int(14 * k), 0))
        bar = tk.Frame(body, bg=BG)
        bar.pack(fill="x", pady=(int(8 * k), int(6 * k)))
        self.update_button = None
        items = (("找回余额", self.open_recover), ("自带模型", self.open_own_model), ("反馈问题", self.open_feedback),
                 ("检查更新", self.update_action),
                 ("简体中文" if i18n.mode() == "hant" else "繁體中文", self.toggle_lang))
        for n, (label, cmd) in enumerate(items):
            bar.grid_columnconfigure(n * 2, weight=1, uniform="bar")
            link = Link(bar, label, cmd, pady=int(4 * k))
            link.grid(row=0, column=n * 2, sticky="ew")
            if n < len(items) - 1:
                tk.Frame(bar, bg=LINE_SOFT, width=1, height=int(16 * k)).grid(row=0, column=n * 2 + 1)
            if label == "检查更新":
                self.update_button = link

        # --- 页脚：服务状态、版本 / 设备编号 ---
        foot = tk.Frame(body, bg=BG)
        foot.pack(fill="x", pady=(0, int(12 * k)))
        self.footer = tk.Label(foot, text="", bg=BG, fg=DIM, font=(FONT, 8), anchor="w")
        self.footer.pack(side="left")
        self.update_label = tk.Label(foot, text="v%s" % APP_VERSION, bg=BG, fg=DIM, font=(FONT, 8), anchor="w",
                                     justify="left", wraplength=int(200 * k))
        self.update_label.pack(side="left", padx=(int(6 * k), 0))
        self.pending_update = None
        self.device_label = None
        if not self.cfg.get("token"):
            self.device_label = tk.Label(foot, text=self.device_text(), bg=BG, fg=DIM, font=(FONT, 8), cursor="hand2")
            self.device_label.pack(side="right")
            self.device_label.bind("<Button-1>", self.copy_device)

        # --- 两个小窗口：兑换 / 推广码、游戏设置（先建好藏起来，点了再出来）---
        self.redeem_win, rb = self.panel_window("兑换 / 推广码")
        tk.Label(rb, text="粘贴兑换码（WOW- 开头）或推广码，点「兑换」。", bg=BG, fg=DIM, font=(FONT, 9),
                 anchor="w").pack(fill="x")
        row = tk.Frame(rb, bg=BG)
        row.pack(fill="x", pady=(int(10 * k), 0))
        box = tk.Frame(row, bg=EDGE, padx=1, pady=1)
        box.pack(side="left", fill="x", expand=True)
        self.cdk = tk.Entry(box, bg=FIELD, fg=TEXT, insertbackground=GOLD, relief="flat", font=("Consolas", 11), width=26)
        self.cdk.pack(fill="x", ipady=int(5 * k), padx=1)
        self.cdk.bind("<Return>", lambda e: self.redeem())
        self.redeem_button = WowButton(row, "兑换", self.redeem, width=6, primary=True)
        self.redeem_button.pack(side="right", padx=(int(8 * k), 0))
        redeem_msg = tk.Label(rb, text="", bg=BG, fg=DIM, font=(FONT, 9), anchor="w", justify="left",
                              wraplength=int(360 * k))
        redeem_msg.pack(fill="x", pady=(int(8 * k), 0))
        self.cdk_msg = Echo(self.notice, redeem_msg, on_change=self.sync_notice)

        self.game_win, gb = self.panel_window("游戏设置")
        tk.Label(gb, text="游戏目录", bg=BG, fg=DIM, font=(FONT, 9), anchor="w").pack(fill="x")
        self.dir_label = tk.Label(gb, text="", bg=BG, fg=TEXT, font=(FONT, 9), anchor="w", justify="left",
                                  wraplength=int(360 * k))
        self.dir_label.pack(fill="x", pady=(int(2 * k), 0))
        row = tk.Frame(gb, bg=BG)
        row.pack(fill="x", pady=(int(8 * k), 0))
        self.flavor = tk.StringVar()                          # 游戏里的文件夹名（_forever_ 等），程序用这个
        self.flavor_label = tk.StringVar()                    # 下拉框里给人看的名字
        self.flavor_menu = tk.OptionMenu(row, self.flavor_label, "")
        self.flavor_menu.configure(bg=SEC, fg=TEXT, activebackground=SEC_HOVER, activeforeground=WHITE, relief="flat",
                                   highlightthickness=1, highlightbackground=EDGE, font=(FONT, 9), width=16)
        self.flavor_menu["menu"].configure(bg=SEC, fg=TEXT, activebackground=BTN, activeforeground=WHITE, font=(FONT, 9))
        self.flavor_menu.pack(side="left")
        WowButton(row, "浏览…", self.browse, width=6).pack(side="right")
        tk.Frame(gb, bg=LINE_SOFT, height=1).pack(fill="x", pady=(int(14 * k), int(10 * k)))
        row = tk.Frame(gb, bg=BG)
        row.pack(fill="x")
        self.addon_label = tk.Label(row, text="", bg=BG, fg=TEXT, font=(FONT, 9), anchor="w", justify="left",
                                    wraplength=int(250 * k))
        self.addon_label.pack(side="left", fill="x", expand=True)
        self.addon_button = WowButton(row, "安装插件", self.install_addon, width=8)
        self.addon_button.pack(side="right")

        game = self.settings.get("game_dir") or find_game_dir()
        self.set_game_dir(game, self.settings.get("flavor"))
        self.auto_update_addon()
        self.write_addon_lang()                       # 插件里的文字跟程序的简体 / 繁体一致
        if "--autostart" in sys.argv:                 # 刚自动更新完：更新前在跑翻译，就接着跑
            root.after(800, self.start)
        if self.settings.get("auto_check_update", True):   # 安装时可以关掉；关了就只在点「检查更新」时联网
            root.after(1500, lambda: self.check_update(manual=False))
        self.flavor.trace_add("write", lambda *a: self.flavor_changed())
        self.started = True
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(200, self.tick)
        root.after(100, self.pump)
        self.refit()
        self.refresh_account()
        self.refresh_service()

    # --- 小窗口（兑换 / 游戏设置）：一直存在，关掉只是藏起来 ---
    def panel_window(self, title):
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.title(title)
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        try:
            win.iconbitmap(resource("assets", icon_name()))
        except tk.TclError:
            pass
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        body = tk.Frame(win, bg=BG, padx=int(20 * self.k), pady=int(16 * self.k))
        body.pack(fill="both", expand=True)
        tk.Label(body, text=title, bg=BG, fg=WHITE, font=(FONT, 13, "bold"), anchor="w").pack(fill="x", pady=(0, int(6 * self.k)))
        return win, body

    def show_window(self, win):
        dark_titlebar(win)
        win.deiconify()
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + int(120 * self.k)
        win.geometry("+%d+%d" % (max(0, x), max(0, y)))
        win.lift()
        win.focus_set()

    def open_redeem(self):
        self.show_window(self.redeem_win)
        self.cdk.focus_set()

    def open_game(self):
        self.show_window(self.game_win)

    def refit(self):
        """卡片高度跟着内容走：状态条、两块卡片（等高）、横幅高度。内容变了就调一次。"""
        if getattr(self, "_refit_pending", False):
            return
        self._refit_pending = True

        def run():
            self._refit_pending = False
            self.root.update_idletasks()
            self.play.fit()
            self.hero.configure(height=self.hero_h - int(26 * self.k) + self.play.need() + int(4 * self.k))
            bal, game = self.tiles
            h = max(bal.need(), game.need())
            for c in (bal, game):
                c.min_h = h
                c.fit()
        self.root.after_idle(run)

    def say(self, text, fg=DIM):
        self.cdk_msg.configure(text=text, fg=fg)

    def sync_notice(self):
        self.refit()
        if self.notice.cget("text") and not self.notice.winfo_ismapped():
            self.notice.pack(fill="x", pady=(int(10 * self.k), 0), after=self.notice_anchor)
        elif not self.notice.cget("text") and self.notice.winfo_ismapped():
            self.notice.pack_forget()

    def device_text(self):
        d = self.cfg.get("device_id", "")
        return "设备编号 %s…%s · 复制" % (d[:6], d[-5:]) if len(d) > 12 else "设备编号 %s · 复制" % d

    def sync_game_tile(self, state):
        """游戏卡片：游戏名、插件状态；插件没装 / 要更新时按钮变成红色的「安装 / 更新插件」。"""
        flavor = self.flavor.get()
        if not self.game_dir:
            self.game_name.configure(text="没找到魔兽世界", fg=WARN)
            self.game_status.configure(text="点「游戏设置」选目录", fg=DIM)
        else:
            self.game_name.configure(text=FLAVOR_NAMES.get(flavor, flavor), fg=TEXT)
            self.game_status.configure(text=state[0], fg=state[1])
        need = state[2]
        self.refit()
        self.addon_action.pack_forget()
        self.game_open.pack_forget()
        if need:
            self.addon_action.set(need)
            self.addon_action.pack(fill="x")
        else:
            self.game_open.pack(fill="x")

    # --- 游戏目录 ---
    def set_game_dir(self, game_dir, flavor=None):
        self.game_dir = game_dir if game_dir and game_flavors(game_dir) else ""
        flavors = game_flavors(self.game_dir) if self.game_dir else []
        menu = self.flavor_menu["menu"]
        menu.delete(0, "end")
        for name in flavors:
            menu.add_command(label=FLAVOR_NAMES.get(name, name), command=lambda n=name: self.flavor.set(n))
        if flavor not in flavors:
            flavor = "_forever_" if "_forever_" in flavors else (flavors[0] if flavors else "")
        self.flavor.set(flavor)
        self.flavor_label.set(i18n.t(FLAVOR_NAMES.get(flavor, flavor) if flavor else "（没有找到）"))
        if self.game_dir:
            self.dir_label.configure(text=self.game_dir, fg=TEXT)
        else:
            self.dir_label.configure(text="没找到魔兽世界的安装目录。点「浏览…」选到 World of Warcraft 这个文件夹。", fg=WARN)
        self.settings.update(game_dir=self.game_dir, flavor=flavor)
        save_settings(self.settings)
        self.refresh_addon()

    def browse(self):
        chosen = filedialog.askdirectory(parent=self.root, title="选择 World of Warcraft 文件夹",
                                         initialdir=self.game_dir or "C:\\")
        if not chosen:
            return
        chosen = os.path.normpath(chosen)
        # 选深了（选到了 _forever_ 或更里面）就往上找
        probe = chosen
        for _ in range(4):
            if game_flavors(probe):
                return self.set_game_dir(probe)
            probe = os.path.dirname(probe)
        self.dir_label.configure(text="%s\n这个文件夹里没有找到魔兽世界，请选 World of Warcraft 文件夹本身。" % chosen, fg=BAD)

    def flavor_changed(self):
        self.flavor_label.set(i18n.t(FLAVOR_NAMES.get(self.flavor.get(), self.flavor.get())))
        self.settings["flavor"] = self.flavor.get()
        save_settings(self.settings)
        self.refresh_addon()
        if getattr(self, "started", False):   # 用户自己选了目录或换了版本：这个版本还没装插件就直接装上
            self.install_if_missing()

    def install_if_missing(self):
        if not self.game_dir or not self.flavor.get():
            return
        if toc_version(os.path.join(addon_dir(self.game_dir, self.flavor.get()), ADDON + ".toc")) is None \
                and toc_version(resource("addon", ADDON, ADDON + ".toc")):
            self.install_addon()

    # --- 插件 ---
    def refresh_addon(self):
        bundled = toc_version(resource("addon", ADDON, ADDON + ".toc")) or "?"
        if not self.game_dir or not self.flavor.get():
            self.addon_label.configure(text="插件：先选游戏目录", fg=DIM)
            self.addon_button.set("安装插件", enabled=False)
            self.sync_game_tile(("", DIM, None))
            return
        installed = toc_version(os.path.join(addon_dir(self.game_dir, self.flavor.get()), ADDON + ".toc"))
        if installed is None:
            self.addon_label.configure(text="插件：还没安装", fg=WARN)
            self.addon_button.set("安装插件", enabled=True)
            self.sync_game_tile(("插件还没安装", WARN, "安装插件"))
        elif version_key(installed) < version_key(bundled):
            self.addon_label.configure(text="插件：已装 v%s，可以更新到 v%s" % (installed, bundled), fg=WARN)
            self.addon_button.set("更新插件", enabled=True)
            self.sync_game_tile(("插件可以更新到 v%s" % bundled, WARN, "更新插件"))
        else:
            self.addon_label.configure(text="插件：已是最新 v%s" % installed, fg=GOOD)
            self.addon_button.set("重新安装", enabled=True)
            self.sync_game_tile(("✓ 插件 v%s 已就绪" % installed, GOOD, None))

    def auto_update_addon(self):
        """打开启动器时自动处理插件：
        - 找到游戏、插件还没装、以前也没自动装过：自动装好（只做一次，用户后来自己删了插件就不再硬塞）；
        - 已经装了但比程序自带的旧：顺手更新。"""
        if not self.game_dir or not self.flavor.get():
            return
        installed = toc_version(os.path.join(addon_dir(self.game_dir, self.flavor.get()), ADDON + ".toc"))
        bundled = toc_version(resource("addon", ADDON, ADDON + ".toc"))
        if installed is None and bundled and not self.settings.get("addon_auto_installed"):
            self.install_addon()
            if toc_version(os.path.join(addon_dir(self.game_dir, self.flavor.get()), ADDON + ".toc")):
                self.settings["addon_auto_installed"] = True
                save_settings(self.settings)
        elif installed and bundled and version_key(installed) < version_key(bundled):
            self.install_addon()

    def install_addon(self):
        target = addon_dir(self.game_dir, self.flavor.get())
        first_time = not os.path.isdir(target)
        try:
            os.makedirs(target, exist_ok=True)
            source = resource("addon", ADDON)
            for name in os.listdir(source):
                shutil.copy2(os.path.join(source, name), os.path.join(target, name))
        except PermissionError:
            msg = "没有权限写入游戏目录。请关掉本程序，右键图标选「以管理员身份运行」再试。"
            self.addon_label.configure(text=msg, fg=BAD)
            self.say(msg, BAD)
            return
        except OSError as e:
            self.addon_label.configure(text="安装失败：%s" % e, fg=BAD)
            self.say("插件安装失败：%s" % e, BAD)
            return
        self.write_addon_lang()
        self.refresh_addon()
        if first_time:
            self.settings["addon_auto_installed"] = True     # 装过一次（手动或自动），以后就不再自动装
            save_settings(self.settings)
        tip = "完全退出游戏再重新进入" if first_time else "在游戏聊天框输入 /reload"
        self.addon_label.configure(text=self.addon_label.cget("text") + "\n已装好。游戏开着的话，" + tip + " 才生效。")
        name = FLAVOR_NAMES.get(self.flavor.get(), self.flavor.get())
        self.say("插件已装进%s。游戏开着的话，%s 才生效。" % (name, tip), GOOD)

    def write_addon_lang(self):
        """把简体 / 繁体的选择写进已装插件的 ChatBridge_Lang.lua，游戏里插件的文字跟程序一致（游戏开着要 /reload）。
        返回 True 表示文件有改动。"""
        if not self.game_dir or not self.flavor.get():
            return False
        target = os.path.join(addon_dir(self.game_dir, self.flavor.get()), "ChatBridge_Lang.lua")
        if not os.path.isdir(os.path.dirname(target)):
            return False
        text = ('-- 简体 / 繁体：电脑上的启动器装插件时会改写这一行（"hans" 或 "hant"）。nil = 跟游戏客户端语言。\n'
                'ChatBridgeLang = "%s"\n' % i18n.mode())
        try:
            with open(target, encoding="utf-8") as f:
                if f.read() == text:
                    return False
        except OSError:
            pass
        try:
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            return True
        except OSError:
            return False

    def toggle_lang(self):
        """简体 ↔ 繁体：存进 config，改插件的语言文件，然后重新打开启动器（翻译在跑就接着跑）。"""
        self.cfg = app.load_config()
        self.cfg["lang"] = "hans" if i18n.mode() == "hant" else "hant"
        app.save_config(self.cfg)
        i18n.set_mode(self.cfg["lang"])
        self.write_addon_lang()
        args = [sys.executable] if app.FROZEN else [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")]
        if self.running():
            args.append("--autostart")
        subprocess.Popen(args, close_fds=True)
        self.stop()
        self.root.destroy()

    # --- 启动和停止 ---
    def overlay_command(self):
        if app.FROZEN:
            return [sys.executable, "--overlay"]
        return [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"), "--overlay"]

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running():
            return
        self.proc = subprocess.Popen(self.overlay_command(), cwd=os.path.dirname(app.CONFIG_PATH) or None,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.tick_once()

    def stop(self):
        if self.running():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.tick_once()

    def tick_once(self):
        on = self.running()
        self.run_dot.configure(fg=GOOD if on else DIM)
        self.run_label.configure(text="翻译运行中" if on else "未启动")
        if on != getattr(self, "_shown_on", None):          # 启动 / 停止只显示一个
            self._shown_on = on
            self.refit()
            (self.start_button if on else self.stop_button).pack_forget()
            (self.stop_button if on else self.start_button).pack(side="right")
        if on:
            self.run_hint.configure(text="窗口可以最小化，别关")
        elif self.proc is not None:
            self.proc = None
            self.run_hint.configure(text="已停止，下次玩之前再点「启动」")
        elif not self.run_hint.cget("text") or self.run_hint.cget("text") == i18n.t("窗口可以最小化，别关"):
            self.run_hint.configure(text="每次玩之前点「启动」")

    def tick(self):
        self.tick_once()
        self.root.after(1000, self.tick)

    # --- 额度 ---
    def background(self, kind, fn):
        threading.Thread(target=lambda: self.events.put((kind,) + tuple(fn())), daemon=True).start()

    def read_status(self):
        """翻译进程写的状态（几秒一次）。翻译没在跑或者状态太旧就返回 None。"""
        if not self.running():
            return None
        try:
            with open(app.STATUS_PATH, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            return None
        return st if time.time() - st.get("at", 0) < 60 else None

    def state_header(self):
        """顺带报给服务器的匿名连接状态：只有版本和几个数字，用来统计「装了但没连上」的有多少。"""
        st = self.read_status()
        parts = ["v=" + APP_VERSION, "run=%d" % (1 if st else 0)]
        if st:
            parts += ["win=%d" % bool(st.get("win")), "addon=%d" % bool(st.get("addon")),
                      "chat=%d" % int(st.get("chat", 0)), "tr=%d" % int(st.get("tr", 0)),
                      "err=%d" % int(st.get("err", 0)), "nobal=%d" % int(st.get("nobal", 0))]
        return ";".join(parts)

    def refresh_account(self):
        self.background("account", lambda: self.relay.account(self.state_header()))
        self.root.after(60000, self.refresh_account)

    def refresh_service(self):
        self.background("service", lambda: (self.relay.healthy(),))
        self.root.after(30000, self.refresh_service)

    # --- 检查更新 ---
    def update_action(self):
        if self.pending_update:
            self.start_update()
        else:
            self.check_update(manual=True)

    def check_update(self, manual):
        self.update_button.set(enabled=False)
        if manual:
            self.update_label.configure(text="正在检查更新…", fg=DIM)
        self.background("update_info", lambda: fetch_latest() + (manual,))

    def on_update_info(self, info, err, manual):
        self.update_button.set(enabled=True)
        if err:
            self.update_label.configure(text=("版本 %s · 检查更新失败：%s" % (APP_VERSION, err)) if manual
                                        else "版本 %s" % APP_VERSION, fg=BAD if manual else DIM)
        elif version_key(info["version"]) > version_key(APP_VERSION):
            self.pending_update = info
            notes = str(info.get("notes", ""))[:80]
            self.update_label.configure(text="发现新版本 %s%s" % (info["version"], ("：" + notes) if notes else ""), fg=GOLD)
            self.update_button.set("立即更新")
        else:
            self.update_label.configure(text=("版本 %s · 已是最新" % APP_VERSION) if manual else "版本 %s" % APP_VERSION,
                                        fg=GOOD if manual else DIM)

    def start_update(self):
        info = self.pending_update
        self.update_button.set("下载中", enabled=False)
        self.update_label.configure(text="正在下载 %s…" % info["version"], fg=GOLD)

        def progress(done, total):
            self.events.put(("update_progress", done, total))

        self.background("update_ready", lambda: download_update(info, progress))

    def on_update_ready(self, path, err):
        if err:
            self.update_label.configure(text=err, fg=BAD)
            self.update_button.set("立即更新", enabled=True)
            return
        if not app.FROZEN:
            self.update_label.configure(text="开发版不自动安装。安装包已下载到 %s" % path, fg=WARN)
            self.update_button.set("立即更新", enabled=True)
            return
        install_dir = os.path.dirname(os.path.abspath(sys.executable))
        args = [path, "--silent", "--dir", install_dir, "--launch"]
        if self.running():
            args.append("--autostart")
        if not os.path.exists(os.path.join(desktop_dir(), "魔兽聊天翻译.lnk")):
            args.append("--no-shortcut")              # 用户删掉了桌面图标，就别再给他建回来
        self.update_label.configure(text="正在安装新版本，马上会自动重新打开…", fg=GOLD)
        self.root.update()
        subprocess.Popen(args, cwd=tempfile.gettempdir(), close_fds=True,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0x8) | 0x200)   # 0x200 新进程组
        self.stop()
        self.root.destroy()

    def show_balance(self):
        if self.relay.own:
            self.balance_label.configure(text="自带模型", fg=GOOD)
            self.balance_sub.configure(text="翻译走你自己的模型，不扣额度", fg=DIM)
        elif self.relay.unlimited:
            self.balance_label.configure(text="不限额", fg=GOOD)
            self.balance_sub.configure(text="", fg=DIM)
        elif self.relay.balance is None:
            self.balance_label.configure(text="查不到" if self.service_ok is False else "查询中…", fg=DIM)
            self.balance_sub.configure(text="", fg=DIM)
        else:
            left = int(max(self.relay.balance, 0) * 100) / 100
            self.balance_label.configure(text="%s%.2f" % (self.relay.currency, left),
                                         fg=WHITE if self.relay.balance > 0 or self.relay.trial_left > 0 else BAD)
            if self.relay.trial_left > 0:
                self.balance_sub.configure(text="+ 免费试用 %d 条" % self.relay.trial_left, fg=GOLD)
            elif self.relay.balance <= 0 and self.relay.trial_claimed is False:
                self.balance_label.configure(fg=WHITE)          # 新电脑：还没领试用，别一上来就标红
                self.balance_sub.configure(text="新电脑先免费领 200 条", fg=GOLD)
            elif self.relay.balance <= 0:
                self.balance_sub.configure(text="额度用完了，充值后才能接着翻", fg=BAD)
            else:
                self.balance_sub.configure(text="中文消息不扣钱", fg=DIM)
        # 「领取免费 200 条」：线上服务、没领过才显示；这时兑换变成下面一行小字
        show = (not self.relay.own and not self.relay.unlimited and self.relay.trial_claimed is False)
        self.refit()
        if show != getattr(self, "_trial_shown", None):
            self._trial_shown = show
            for w in (self.trial_button, self.redeem_open, self.redeem_link):
                w.pack_forget()
            if show:
                self.trial_button.pack(fill="x")
                self.redeem_link.pack(fill="x", pady=(int(6 * self.k), 0))
            else:
                self.redeem_open.pack(fill="x")

    def claim_trial(self):
        self.trial_button.set(enabled=False)
        self.cdk_msg.configure(text="正在申请免费试用…", fg=DIM)
        self.background("trial_started", self.relay.start_trial)

    def on_trial_started(self, url, err):
        self.trial_button.set(enabled=True)
        if not url:
            self.cdk_msg.configure(text="领不了：%s" % err, fg=BAD)
            return
        import webbrowser
        webbrowser.open(hant_url(url))
        self.cdk_msg.configure(text="已在浏览器打开领取页面：点一下「确认你是真人」就到账（15 分钟内有效）。", fg=GOLD)
        self.trial_polls = 36                       # 接下来 3 分钟每 5 秒查一次余额，到账了马上显示
        self.root.after(5000, self.poll_trial)

    def poll_trial(self):
        if self.trial_polls <= 0:
            return
        self.trial_polls -= 1
        if self.relay.trial_left > 0:
            self.trial_polls = 0
            self.cdk_msg.configure(text="免费试用已到账：%d 条，30 天内有效。" % self.relay.trial_left, fg=GOOD)
            self.restart_overlay()                  # 翻译在跑的话重启一下：它可能记着「额度用完了」
            return
        self.background("account", self.relay.account)
        self.root.after(5000, self.poll_trial)

    def redeem(self):
        code = self.cdk.get().strip()
        if not code:
            return
        if self.cfg.get("token"):
            self.cdk_msg.configure(text="你用的是不限额口令，不需要兑换。", fg=DIM)
            return
        if PROMO_RE.match(code.upper()):
            self.redeem_button.set(enabled=False)
            self.cdk_msg.configure(text="正在核对推广码…", fg=DIM)
            self.background("promo_started", lambda: self.relay.start_promo(code.upper()))
            return
        self.cdk_msg.configure(text="兑换中…", fg=DIM)
        self.redeem_button.set(enabled=False)
        self.background("redeemed", lambda: self.relay.redeem(code))

    def on_promo_started(self, url, err):
        self.redeem_button.set(enabled=True)
        if not url:
            self.cdk_msg.configure(text="推广码用不了：%s" % err, fg=BAD)
            return
        import webbrowser
        webbrowser.open(hant_url(url))
        self.cdk.delete(0, "end")
        self.cdk_msg.configure(text="已在浏览器打开验证页面，验证一下就到账（15 分钟内有效）。", fg=GOLD)
        self.promo_polls = 36                       # 接下来 3 分钟每 5 秒查一次，到账了马上显示
        self.root.after(5000, self.poll_promo)

    def poll_promo(self):
        if getattr(self, "promo_polls", 0) <= 0:
            return
        self.promo_polls -= 1
        if self.relay.promo_bound:
            self.promo_polls = 0
            self.cdk_msg.configure(text="推广码已生效，送你的额度已到账。", fg=GOOD)
            self.restart_overlay()
            return
        self.background("account", self.relay.account)
        self.root.after(5000, self.poll_promo)

    # --- 对话框：找回余额、自带模型 ---
    # --- 反馈 ---
    def diagnostics(self):
        """反馈时附带的诊断信息：版本、游戏和插件状态、各频道收到几条。没有聊天内容、没有角色名。"""
        flavor = self.flavor.get()
        installed = (toc_version(os.path.join(addon_dir(self.game_dir, flavor), ADDON + ".toc"))
                     if self.game_dir and flavor else None)
        d = {"app": APP_VERSION, "os": ("%s %s" % (platform.system(), platform.version()))[:40],
             "game_dir_found": bool(self.game_dir), "flavor": flavor[:20], "addon_installed": installed or "",
             "addon_bundled": toc_version(resource("addon", ADDON, ADDON + ".toc")) or "",
             "overlay_running": self.running(), "service_ok": bool(self.service_ok), "own_model": bool(self.relay.own),
             "has_balance": bool((self.relay.balance or 0) > 0), "trial_left": int(self.relay.trial_left or 0),
             "trial_claimed": bool(self.relay.trial_claimed), "scale": round(self.k, 2)}
        st = self.read_status()
        if st:
            d.update(game_window=bool(st.get("win")), addon_signal=bool(st.get("addon")),
                     addon_version=str(st.get("addon_ver", ""))[:12], chats_seen=int(st.get("chat", 0)),
                     translated=int(st.get("tr", 0)), errors=int(st.get("err", 0)), secret=int(st.get("secret", 0)),
                     docked=bool(st.get("docked")), dock_shown=bool(st.get("dock_shown")),
                     minutes_running=int((time.time() - st.get("started", time.time())) / 60),
                     minutes_since_chat=int((time.time() - st["last_chat"]) / 60) if st.get("last_chat") else -1,
                     by_channel=st.get("chan") or {}, by_error=st.get("errs") or {})
        return d

    def open_feedback(self):
        win, body = self.dialog("反馈问题")
        wrap = int(380 * self.k)
        tk.Label(body, text="说说遇到的问题，或者想要的功能。", bg=BG, fg=DIM, font=(FONT, 9),
                 anchor="w").pack(fill="x")
        tk.Label(body, text="问题类型", bg=BG, fg=TEXT, font=(FONT, 9), anchor="w").pack(fill="x", pady=(8, 2))
        kind = tk.StringVar(value=i18n.t(FEEDBACK_KINDS[0][1]))
        menu = tk.OptionMenu(body, kind, *[i18n.t(label) for _, label in FEEDBACK_KINDS])
        menu.configure(bg=SEC, fg=TEXT, activebackground=SEC_HOVER, activeforeground=WHITE, relief="flat",
                       highlightthickness=1, highlightbackground=EDGE, font=(FONT, 9), anchor="w")
        menu["menu"].configure(bg=SEC, fg=TEXT, activebackground=BTN, activeforeground=WHITE, font=(FONT, 9))
        menu.pack(fill="x")
        tk.Label(body, text="具体情况（什么时候、在做什么、看到了什么）", bg=BG, fg=TEXT, font=(FONT, 9),
                 anchor="w").pack(fill="x", pady=(8, 2))
        box = tk.Frame(body, bg=EDGE, padx=1, pady=1)
        box.pack(fill="x")
        text = tk.Text(box, bg=FIELD, fg=TEXT, insertbackground=GOLD, relief="flat", font=(FONT, 10),
                       width=46, height=6, wrap="word")
        text.pack(fill="x", padx=1, pady=1)
        contact = self.field(body, "邮箱（选填，方便我们回复你）")
        with_diag = tk.BooleanVar(value=True)
        tk.Checkbutton(body, text="附带诊断信息：版本、游戏和插件的连接情况、各频道收到的消息数。不含聊天内容和角色名。",
                       variable=with_diag, bg=BG, fg=TEXT, selectcolor=FIELD, activebackground=BG,
                       activeforeground=GOLD, font=(FONT, 9), anchor="w", wraplength=wrap,
                       justify="left").pack(fill="x", pady=(8, 0))
        msg = tk.Label(body, text="", bg=BG, fg=DIM, font=(FONT, 9), anchor="w", justify="left", wraplength=wrap)
        msg.pack(fill="x", pady=(6, 0))
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(10, 0))

        def send():
            content = text.get("1.0", "end").strip()
            if len(content) < 2:
                msg.configure(text="请写一下遇到了什么问题。", fg=BAD)
                return
            email = contact.get().strip()
            if email and not EMAIL_RE.match(email):
                msg.configure(text="邮箱格式不对（不想留可以空着）。", fg=BAD)
                return
            code = next((c for c, label in FEEDBACK_KINDS if i18n.t(label) == kind.get()), "other")
            payload = {"kind": code, "text": content[:2000], "contact": email[:120],
                       "version": APP_VERSION}
            if with_diag.get():
                payload["diag"] = self.diagnostics()
            send_button.set(enabled=False)
            msg.configure(text="正在发送…", fg=DIM)
            self.background("feedback_sent", lambda: self.relay.feedback(payload) + (win, msg, send_button))

        send_button = WowButton(row, "发送", send, width=7, primary=True)
        send_button.pack(side="right")
        WowButton(row, "取消", win.destroy, width=7).pack(side="right", padx=(0, 8))
        tk.Label(row, text="网页版：wow.husen.ca/feedback", bg=BG, fg=DIM, font=(FONT, 8),
                 anchor="w").pack(side="left")
        self.center(win)
        text.focus_set()
        self.feedback_win = win
        return win, text, contact, msg

    def on_feedback_sent(self, fid, err, win, msg, button):
        if not win.winfo_exists():
            return
        if fid:
            msg.configure(text="已收到，编号 %s。留了邮箱的话，我们会回复你。" % fid, fg=GOOD)
            win.after(3000, win.destroy)
        else:
            button.set(enabled=True)
            msg.configure(text="没发出去：%s" % err, fg=BAD)

    def dialog(self, title):
        k = self.k
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        dark_titlebar(win)
        try:
            win.iconbitmap(resource("assets", icon_name()))
        except tk.TclError:
            pass
        body = tk.Frame(win, bg=BG, padx=int(18 * k), pady=int(14 * k))
        body.pack(fill="both", expand=True)
        tk.Label(body, text=title, bg=BG, fg=WHITE, font=(FONT, 14, "bold"), anchor="w").pack(fill="x", pady=(0, 6))
        return win, body

    def field(self, parent, label, value="", show=None):
        tk.Label(parent, text=label, bg=BG, fg=TEXT, font=(FONT, 9), anchor="w").pack(fill="x", pady=(8, 2))
        box = tk.Frame(parent, bg=EDGE, padx=1, pady=1)
        box.pack(fill="x")
        e = tk.Entry(box, bg=FIELD, fg=TEXT, insertbackground=GOLD, relief="flat", font=("Consolas", 10),
                     width=46, show=show or "")
        e.pack(fill="x", ipady=4, padx=1)
        e.insert(0, value)
        return e

    def center(self, win):
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - win.winfo_reqheight()) // 3)
        win.geometry("+%d+%d" % (max(0, x), max(0, y)))
        win.grab_set()

    def restart_overlay(self):
        """改了设备编号或翻译来源：翻译进程正在跑就重启一下，让它读到新配置。"""
        if self.running():
            self.stop()
            self.root.after(500, self.start)

    def open_recover(self):
        win, body = self.dialog("找回余额")
        wrap = int(460 * self.k)
        tk.Label(body, text="余额记在「设备编号」名下。重装系统或换了电脑，把原来那台的设备编号填进来，就能接着用原来的余额。"
                            "设备编号就等于余额凭证，别发给别人。", bg=BG, fg=DIM, font=(FONT, 9), anchor="w",
                 justify="left", wraplength=wrap).pack(fill="x")
        tk.Label(body, text="现在这台的编号：%s" % self.cfg.get("device_id", ""), bg=BG, fg=DIM, font=("Consolas", 9),
                 anchor="w").pack(fill="x", pady=(6, 0))
        entry = self.field(body, "原来的设备编号（d_ 开头）")
        msg = tk.Label(body, text="", bg=BG, fg=DIM, font=(FONT, 9), anchor="w", justify="left", wraplength=wrap)
        msg.pack(fill="x", pady=(8, 0))
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(10, 0))
        state = {"checked": None}

        def check():
            new = entry.get().strip().lower()
            state["checked"] = None
            switch.set(enabled=False)
            if not DEVICE_RE.match(new):
                msg.configure(text="格式不对：应该是 d_ 开头，后面 32 位数字和 a-f 字母。", fg=BAD)
                return
            if new == self.cfg.get("device_id"):
                msg.configure(text="这就是现在这台的编号，不用换。", fg=DIM)
                return
            msg.configure(text="查询中…", fg=DIM)

            def ask():
                probe = app.Relay(dict(self.cfg, device_id=new, token="", own_model={}))
                info, err = probe.account()
                return info, err, new
            threading.Thread(target=lambda: self.events.put(("recover_checked",) + ask() + (msg, switch, state)),
                             daemon=True).start()

        def do_switch():
            new = state["checked"]
            if not new:
                return
            old = self.cfg.get("device_id")
            history = [d for d in self.cfg.get("previous_device_ids", []) if d != new]
            if old and old not in history:
                history.insert(0, old)
            self.cfg["previous_device_ids"] = history[:5]       # 万一换错了还能换回来
            self.cfg["device_id"] = new
            app.save_config(self.cfg)
            self.relay.balance, self.relay.no_balance = None, False
            if self.device_label is not None:
                self.device_label.configure(text=self.device_text())
            self.refresh_account_now()
            self.restart_overlay()
            self.cdk_msg.configure(text="已换成原来的设备编号。之前这台的编号存在配置里，换错了可以再换回来：%s" % old, fg=GOOD)
            win.destroy()

        switch = WowButton(row, "换成这个编号", do_switch, width=11, primary=True)
        switch.pack(side="right")
        switch.set(enabled=False)
        WowButton(row, "查询余额", check, width=9).pack(side="right", padx=(0, 8))
        entry.bind("<Return>", lambda e: check())
        self.center(win)
        entry.focus_set()

    def on_recover_checked(self, info, err, new, msg, switch, state):
        if not msg.winfo_exists():
            return
        if info is None:
            msg.configure(text="查不到：%s" % (err or "连不上翻译服务"), fg=BAD)
            return
        cur = info.get("currency", "US$")
        if not info.get("topped_up") and not info.get("balance"):
            msg.configure(text="这个编号没有充值记录，余额是 0。确认没填错再换。", fg=WARN)
        else:
            msg.configure(text="这个编号余额 %s%.2f（累计充值 %s%.2f）。确认是你的，就点「换成这个编号」。" % (
                cur, max(info.get("balance", 0), 0), cur, info.get("topped_up", 0)), fg=GOOD)
        state["checked"] = new
        switch.set(enabled=True)

    def refresh_account_now(self):
        self.background("account", self.relay.account)

    def open_own_model(self):
        win, body = self.dialog("自带模型")
        wrap = int(380 * self.k)
        m = self.cfg.get("own_model") or {}
        tk.Label(body, text="用你自己的模型翻译（OpenAI 兼容接口：OpenAI、DeepSeek、本机 Ollama 等都行）。\n"
                            "打开后翻译不经过线上服务、不扣额度；密钥只存在这台电脑上。\n"
                            "注意：线上服务专门调教过魔兽黑话，自带模型没有这部分。",
                 bg=BG, fg=DIM, font=(FONT, 9), anchor="w", justify="left", wraplength=int(520 * self.k)).pack(fill="x")
        url = self.field(body, "接口地址（例如 https://api.openai.com/v1 或 http://127.0.0.1:11434/v1）", m.get("base_url", ""))
        key = self.field(body, "密钥（本机模型可以不填）", m.get("api_key", ""), show="•")
        model = self.field(body, "模型名（例如 gpt-4o-mini、deepseek-chat、qwen2.5:7b）", m.get("model", ""))
        on = tk.BooleanVar(value=bool(m.get("enabled")))
        tk.Checkbutton(body, text="使用自带模型（取消勾选就回到线上翻译服务）", variable=on, bg=BG, fg=TEXT,
                       selectcolor=FIELD, activebackground=BG, activeforeground=GOLD, font=(FONT, 9),
                       anchor="w").pack(fill="x", pady=(10, 0))
        msg = tk.Label(body, text="", bg=BG, fg=DIM, font=(FONT, 9), anchor="w", justify="left", wraplength=wrap)
        msg.pack(fill="x", pady=(8, 0))
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(10, 0))

        def current():
            return {"enabled": bool(on.get()), "base_url": url.get().strip(), "api_key": key.get().strip(),
                    "model": model.get().strip()}

        def valid(c, need_enabled=False):
            if not c["base_url"].startswith(("http://", "https://")):
                msg.configure(text="接口地址要以 http:// 或 https:// 开头。", fg=BAD)
                return False
            if not c["model"]:
                msg.configure(text="模型名不能空。", fg=BAD)
                return False
            return True

        def test():
            c = dict(current(), enabled=True)
            if not valid(c):
                return
            msg.configure(text="测试中：翻译一句「need a tank for the dungeon, pst」…", fg=DIM)
            threading.Thread(target=lambda: self.events.put(
                ("own_tested",) + app.OwnModel({"own_model": c}).translate("need a tank for the dungeon, pst", "en2zh")
                + (msg,)), daemon=True).start()

        def save():
            c = current()
            if c["enabled"] and not valid(c):
                return
            self.cfg["own_model"] = c
            app.save_config(self.cfg)
            self.relay.balance, self.relay.no_balance = None, False
            self.show_balance()
            self.refresh_account_now()
            self.restart_overlay()
            win.destroy()

        WowButton(row, "保存", save, width=7, primary=True).pack(side="right")
        WowButton(row, "测试", test, width=7).pack(side="right", padx=(0, 8))
        self.center(win)

    def copy_device(self, _):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.cfg.get("device_id", ""))
        self.device_label.configure(fg=GOOD)
        self.root.after(1200, lambda: self.device_label.configure(fg=DIM))

    def pump(self):
        try:
            while True:
                item = self.events.get_nowait()
                if item[0] == "account":
                    self.show_balance()
                elif item[0] == "update_info":
                    self.on_update_info(*item[1:])
                elif item[0] == "update_progress":
                    done, total = item[1], item[2]
                    pct = (" %d%%" % (done * 100 // total)) if total else ""
                    self.update_label.configure(text="正在下载%s（%.1f MB）" % (pct, done / 1e6), fg=GOLD)
                elif item[0] == "update_ready":
                    self.on_update_ready(item[1], item[2])
                elif item[0] == "recover_checked":
                    self.on_recover_checked(*item[1:])
                elif item[0] == "own_tested":
                    text, err, msg = item[1], item[2], item[3]
                    if msg.winfo_exists():
                        msg.configure(text=("能用：%s" % text) if text else ("不能用：%s" % err), fg=GOOD if text else BAD)
                elif item[0] == "promo_started":
                    self.on_promo_started(item[1], item[2])
                elif item[0] == "feedback_sent":
                    self.on_feedback_sent(*item[1:])
                elif item[0] == "trial_started":
                    self.on_trial_started(item[1], item[2])
                elif item[0] == "service":
                    self.service_ok = item[1]
                    self.show_balance()
                elif item[0] == "redeemed":
                    result, err = item[1], item[2]
                    self.redeem_button.set(enabled=True)
                    if result:
                        self.cdk.delete(0, "end")
                        self.restart_overlay()      # 翻译在跑的话重启一下：它记着「额度用完了」，要重新查
                        self.cdk_msg.configure(text="兑换成功：+%s%.2f" % (result.get("currency", "US$"), result["added"]), fg=GOOD)
                        self.root.after(1500, self.redeem_win.withdraw)
                    else:
                        self.cdk_msg.configure(text="兑换失败：%s" % err, fg=BAD)
                    self.show_balance()
        except queue.Empty:
            pass
        service = {None: "● 连接中…", True: "● 翻译服务正常", False: "● 翻译服务连不上"}[self.service_ok]
        self.footer.configure(text=service, fg={None: DIM, True: GOOD, False: BAD}[self.service_ok])
        self.root.after(200, self.pump)

    def close(self):
        self.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    Launcher().run()


if __name__ == "__main__":
    main()
