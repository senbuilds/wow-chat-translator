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
import urllib.error
import urllib.request
from tkinter import filedialog

import app
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

class WowButton(tk.Frame):
    """平的按钮。primary=True：红底白字（每块里最主要的那个操作）；否则深棕底、细线边。"""

    def __init__(self, parent, text, command, width=9, primary=False):
        self.colors = (BTN, BTN_HOVER, BTN_DOWN, WHITE, BTN) if primary else (SEC, SEC_HOVER, SEC_DOWN, TEXT, EDGE)
        super().__init__(parent, bg=self.colors[4], padx=1, pady=1)
        self.command, self.enabled = command, True
        self.face = tk.Label(self, text=text, bg=self.colors[0], fg=self.colors[3], font=(FONT, 10, "bold"),
                             width=width, pady=5, cursor="hand2")
        self.face.pack()
        self.face.bind("<Enter>", lambda e: self._paint(self.colors[1]))
        self.face.bind("<Leave>", lambda e: self._paint(self.colors[0]))
        self.face.bind("<ButtonPress-1>", lambda e: self._paint(self.colors[2]))
        self.face.bind("<ButtonRelease-1>", self._click)

    def _paint(self, color):
        if self.enabled:
            self.face.configure(bg=color)

    def _click(self, event):
        if self.enabled:
            self.face.configure(bg=self.colors[1])
            inside = 0 <= event.x <= self.face.winfo_width() and 0 <= event.y <= self.face.winfo_height()
            if inside:
                self.command()

    def set(self, text=None, enabled=None):
        if text is not None:
            self.face.configure(text=text)
        if enabled is not None:
            self.enabled = enabled
            self.face.configure(bg=self.colors[0] if enabled else BTN_OFF, fg=self.colors[3] if enabled else OFF_TEXT,
                                cursor="hand2" if enabled else "arrow")
            self.configure(bg=self.colors[4] if enabled else OFF_EDGE)


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

class Launcher:
    def __init__(self):
        self.cfg = app.load_config()
        if not os.path.exists(app.CONFIG_PATH):
            app.save_config(self.cfg)
        self.settings = load_settings()
        self.relay = app.Relay(self.cfg)
        self.proc = None
        self.events = queue.Queue()
        self.service_ok = None

        root = self.root = tk.Tk()
        root.title(APP_NAME)
        dark_titlebar(root)
        root.configure(bg=BG)
        root.resizable(False, False)
        try:
            root.iconbitmap(resource("assets", "icon.ico"))
        except tk.TclError:
            pass
        k = self.k = max(1.0, root.winfo_fpixels("1i") / 96.0)
        wrap = int(400 * k)
        body = tk.Frame(root, bg=BG, padx=int(18 * k), pady=int(14 * k))
        body.pack(fill="both", expand=True)

        head = tk.Frame(body, bg=BG)
        head.pack(fill="x", pady=(0, 14))
        tk.Label(head, text=APP_NAME, bg=BG, fg=WHITE, font=(FONT, 18, "bold")).pack(side="left")
        tk.Label(head, text="ChatBridge Translator", bg=BG, fg=DIM, font=(FONT, 9, "bold")).pack(side="left",
                                                                                               padx=(10, 0), pady=(8, 0))

        # --- 游戏目录和插件 ---
        p = panel(body, "游戏目录")
        self.dir_label = tk.Label(p, text="", bg=PANEL, fg=TEXT, font=(FONT, 9), anchor="w", justify="left",
                                  wraplength=wrap)
        self.dir_label.pack(fill="x")
        row = tk.Frame(p, bg=PANEL)
        row.pack(fill="x", pady=(6, 0))
        self.flavor = tk.StringVar()
        self.flavor_menu = tk.OptionMenu(row, self.flavor, "")
        self.flavor_menu.configure(bg=SEC, fg=TEXT, activebackground=SEC_HOVER, activeforeground=WHITE, relief="flat",
                                   highlightthickness=1, highlightbackground=EDGE, font=(FONT, 9), width=14)
        self.flavor_menu["menu"].configure(bg=SEC, fg=TEXT, activebackground=BTN, activeforeground=WHITE, font=(FONT, 9))
        self.flavor_menu.pack(side="left")
        WowButton(row, "浏览…", self.browse, width=7).pack(side="right")
        row = tk.Frame(p, bg=PANEL)
        row.pack(fill="x", pady=(10, 0))
        self.addon_label = tk.Label(row, text="", bg=PANEL, fg=TEXT, font=(FONT, 9), anchor="w", justify="left",
                                    wraplength=int(250 * k))
        self.addon_label.pack(side="left", fill="x", expand=True)
        self.addon_button = WowButton(row, "安装插件", self.install_addon, width=9)
        self.addon_button.pack(side="right")

        # --- 翻译 ---
        p = panel(body, "翻译")
        row = tk.Frame(p, bg=PANEL)
        row.pack(fill="x")
        self.run_dot = tk.Label(row, text="●", bg=PANEL, fg=DIM, font=(FONT, 12))
        self.run_dot.pack(side="left")
        self.run_label = tk.Label(row, text="未启动", bg=PANEL, fg=TEXT, font=(FONT, 11), anchor="w")
        self.run_label.pack(side="left", padx=(6, 0))
        self.stop_button = WowButton(row, "停止", self.stop, width=7)
        self.stop_button.pack(side="right")
        self.start_button = WowButton(row, "启动", self.start, width=7, primary=True)
        self.start_button.pack(side="right", padx=(0, 8))
        self.run_hint = tk.Label(p, text="", bg=PANEL, fg=DIM, font=(FONT, 9), anchor="w", justify="left", wraplength=wrap)
        self.run_hint.pack(fill="x", pady=(6, 0))

        # --- 额度 ---
        p = panel(body, "额度")
        self.balance_label = tk.Label(p, text="余额 查询中…", bg=PANEL, fg=TEXT, font=(FONT, 16, "bold"), anchor="w")
        self.balance_label.pack(fill="x")
        row = tk.Frame(p, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        box = tk.Frame(row, bg=EDGE, padx=1, pady=1)
        box.pack(side="left", fill="x", expand=True)
        self.cdk = tk.Entry(box, bg=FIELD, fg=TEXT, insertbackground=GOLD, relief="flat", font=("Consolas", 11))
        self.cdk.pack(fill="x", ipady=5, padx=1)
        self.cdk.bind("<Return>", lambda e: self.redeem())
        self.redeem_button = WowButton(row, "兑换", self.redeem, width=7, primary=True)
        self.redeem_button.pack(side="right", padx=(8, 0))
        self.cdk_msg = tk.Label(p, text="粘贴兑换码或推广码后点「兑换」。剩余条数在游戏翻译页的「用量」里看。", bg=PANEL, fg=DIM,
                                font=(FONT, 9), anchor="w", justify="left", wraplength=wrap)
        self.cdk_msg.pack(fill="x", pady=(6, 0))
        row = tk.Frame(p, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))
        WowButton(row, "自带模型", self.open_own_model, width=9).pack(side="right")
        WowButton(row, "找回余额", self.open_recover, width=9).pack(side="right", padx=(0, 8))
        # 新电脑：领免费 200 条（服务器说没领过才显示）
        self.trial_row = tk.Frame(p, bg=PANEL)
        self.trial_button = WowButton(self.trial_row, "领取免费 200 条", self.claim_trial, width=14, primary=True)
        self.trial_button.pack(side="left")
        tk.Label(self.trial_row, text="每台电脑能领一次，网页上验证一下就到账", bg=PANEL, fg=DIM, font=(FONT, 9),
                 anchor="w").pack(side="left", padx=(8, 0))
        self.trial_polls = 0
        self.mode_label = tk.Label(row, text="", bg=PANEL, fg=DIM, font=(FONT, 9), anchor="w", justify="left",
                                   wraplength=int(200 * k))
        self.mode_label.pack(side="left", fill="x", expand=True)

        # --- 底部 ---
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(0, 4))
        self.update_button = WowButton(row, "检查更新", self.update_action, width=9)
        self.update_button.pack(side="right")
        WowButton(row, "反馈问题", self.open_feedback, width=9).pack(side="right", padx=(0, 8))
        self.update_label = tk.Label(row, text="版本 %s" % APP_VERSION, bg=BG, fg=DIM, font=(FONT, 9), anchor="w",
                                     justify="left", wraplength=int(300 * k))
        self.update_label.pack(side="left", fill="x", expand=True)
        self.pending_update = None
        self.footer = tk.Label(body, text="", bg=BG, fg=DIM, font=(FONT, 8), anchor="w", justify="left", wraplength=wrap)
        self.footer.pack(fill="x")
        self.device_label = None
        if not self.cfg.get("token"):
            self.device_label = tk.Label(body, text="设备编号 %s · 点击复制" % self.cfg.get("device_id", ""),
                                         bg=BG, fg=DIM, font=(FONT, 8), anchor="w", cursor="hand2", wraplength=wrap,
                                         justify="left")
            self.device_label.pack(fill="x")
            self.device_label.bind("<Button-1>", self.copy_device)

        game = self.settings.get("game_dir") or find_game_dir()
        self.set_game_dir(game, self.settings.get("flavor"))
        self.auto_update_addon()
        if "--autostart" in sys.argv:                 # 刚自动更新完：更新前在跑翻译，就接着跑
            root.after(800, self.start)
        if self.settings.get("auto_check_update", True):   # 安装时可以关掉；关了就只在点「检查更新」时联网
            root.after(1500, lambda: self.check_update(manual=False))
        self.flavor.trace_add("write", lambda *a: self.flavor_changed())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(200, self.tick)
        root.after(100, self.pump)
        self.refresh_account()
        self.refresh_service()

    # --- 游戏目录 ---
    def set_game_dir(self, game_dir, flavor=None):
        self.game_dir = game_dir if game_dir and game_flavors(game_dir) else ""
        flavors = game_flavors(self.game_dir) if self.game_dir else []
        menu = self.flavor_menu["menu"]
        menu.delete(0, "end")
        for name in flavors:
            menu.add_command(label=name, command=lambda n=name: self.flavor.set(n))
        if flavor not in flavors:
            flavor = "_forever_" if "_forever_" in flavors else (flavors[0] if flavors else "")
        self.flavor.set(flavor)
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
        self.settings["flavor"] = self.flavor.get()
        save_settings(self.settings)
        self.refresh_addon()

    # --- 插件 ---
    def refresh_addon(self):
        bundled = toc_version(resource("addon", ADDON, ADDON + ".toc")) or "?"
        if not self.game_dir or not self.flavor.get():
            self.addon_label.configure(text="插件：先选游戏目录", fg=DIM)
            self.addon_button.set("安装插件", enabled=False)
            return
        installed = toc_version(os.path.join(addon_dir(self.game_dir, self.flavor.get()), ADDON + ".toc"))
        if installed is None:
            self.addon_label.configure(text="插件：还没安装", fg=WARN)
            self.addon_button.set("安装插件", enabled=True)
        elif version_key(installed) < version_key(bundled):
            self.addon_label.configure(text="插件：已装 v%s，可以更新到 v%s" % (installed, bundled), fg=WARN)
            self.addon_button.set("更新插件", enabled=True)
        else:
            self.addon_label.configure(text="插件：已是最新 v%s" % installed, fg=GOOD)
            self.addon_button.set("重新安装", enabled=True)

    def auto_update_addon(self):
        """程序更新后，游戏里装的插件如果比程序自带的旧，就顺手更新（没装过的不动）。"""
        if not self.game_dir or not self.flavor.get():
            return
        installed = toc_version(os.path.join(addon_dir(self.game_dir, self.flavor.get()), ADDON + ".toc"))
        bundled = toc_version(resource("addon", ADDON, ADDON + ".toc"))
        if installed and bundled and version_key(installed) < version_key(bundled):
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
            self.addon_label.configure(text="没有权限写入游戏目录。请关掉本程序，右键图标选「以管理员身份运行」再试。", fg=BAD)
            return
        except OSError as e:
            self.addon_label.configure(text="安装失败：%s" % e, fg=BAD)
            return
        self.refresh_addon()
        tip = "完全退出游戏再重新进入" if first_time else "在游戏聊天框输入 /reload"
        self.addon_label.configure(text=self.addon_label.cget("text") + "\n已装好。游戏开着的话，" + tip + " 才生效。")

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
        self.start_button.set(enabled=not on)
        self.stop_button.set(enabled=on)
        if on:
            self.run_hint.configure(text="进游戏后点聊天框上的「翻译」看译文。这个窗口可以最小化，但别关。", fg=DIM)
        elif self.proc is not None:
            self.proc = None
            self.run_hint.configure(text="翻译已停止（游戏关掉一分钟后会自动停）。下次玩之前再点「启动」。", fg=DIM)
        elif not self.run_hint.cget("text"):
            self.run_hint.configure(text="每次玩之前点「启动」，然后进游戏。", fg=DIM)

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
        self.mode_label.configure(text="正在用：自带模型（不扣额度）" if self.relay.own else "正在用：线上翻译服务",
                                  fg=GOOD if self.relay.own else DIM)
        if self.relay.own:
            self.balance_label.configure(text="自带模型 · 不扣额度", fg=GOOD)
        elif self.relay.unlimited:
            self.balance_label.configure(text="余额 不限额", fg=GOOD)
        elif self.relay.balance is None:
            self.balance_label.configure(text="余额 查不到" if self.service_ok is False else "余额 查询中…", fg=DIM)
        else:
            left = int(max(self.relay.balance, 0) * 100) / 100
            text = "余额 %s%.2f" % (self.relay.currency, left)
            if self.relay.trial_left > 0:
                text += " · 免费试用剩 %d 条" % self.relay.trial_left
            self.balance_label.configure(text=text, fg=WHITE if self.relay.balance > 0 or self.relay.trial_left > 0 else BAD)
        # 「领取免费 200 条」：线上服务、没领过才显示
        show = (not self.relay.own and not self.relay.unlimited and self.relay.trial_claimed is False)
        if show and not self.trial_row.winfo_ismapped():
            self.trial_row.pack(fill="x", pady=(8, 0), before=self.cdk_msg)
        elif not show and self.trial_row.winfo_ismapped():
            self.trial_row.pack_forget()

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
        webbrowser.open(url)
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
        webbrowser.open(url)
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
        kind = tk.StringVar(value=FEEDBACK_KINDS[0][1])
        menu = tk.OptionMenu(body, kind, *[label for _, label in FEEDBACK_KINDS])
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
            code = next((c for c, label in FEEDBACK_KINDS if label == kind.get()), "other")
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
            win.iconbitmap(resource("assets", "icon.ico"))
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
                self.device_label.configure(text="设备编号 %s · 点击复制" % new)
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
                    else:
                        self.cdk_msg.configure(text="兑换失败：%s" % err, fg=BAD)
                    self.show_balance()
        except queue.Empty:
            pass
        service = {None: "翻译服务：连接中…", True: "翻译服务：正常", False: "翻译服务：连不上，请检查网络或稍后再试"}[self.service_ok]
        self.footer.configure(text=service, fg=BAD if self.service_ok is False else DIM)
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
