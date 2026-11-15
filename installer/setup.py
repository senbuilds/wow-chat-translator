"""魔兽聊天翻译 · 安装程序。

把程序解压到当前用户的程序目录（不需要管理员权限），在桌面和开始菜单建快捷方式，
并登记到「设置 → 应用」里方便卸载。重复运行就是升级：余额和设置存在别处，不会丢。

命令行参数（启动器自动更新时用，也方便测试）：
  --silent  --dir <目录>  --no-shortcut  --no-registry
  --launch       装完直接打开程序
  --autostart    打开后自动点「启动」（更新前翻译在跑时用）
"""
import ctypes
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import zipfile
from tkinter import filedialog

APP_NAME = "魔兽聊天翻译"
try:
    from version import VERSION as APP_VERSION       # 打包时从 app/version.py 带进来
except ImportError:
    APP_VERSION = "dev"
EXE = "WoWTranslator.exe"
REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\WoWChatTranslator"
FONT = "Microsoft YaHei UI"
BG, PANEL, EDGE = "#100c09", "#1c1510", "#7a5f24"
GOLD, GOLD_DIM, TEXT, DIM = "#ffd100", "#c9a44c", "#eadfc6", "#8d8268"
BTN, BTN_HOVER, BTN_OFF = "#6b1010", "#8c1818", "#2b2520"
GOOD, BAD = "#4fd15a", "#ff5f4d"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def resource(name):
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), name)


def default_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", "WoWChatTranslator")


def powershell(script):
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True, creationflags=NO_WINDOW)


def make_shortcuts(target_dir):
    """桌面和开始菜单各建一个快捷方式。桌面可能被 OneDrive 接管，所以让系统自己报路径。"""
    exe = os.path.join(target_dir, EXE)
    script = (
        "$w = New-Object -ComObject WScript.Shell; "
        "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { "
        "$s = $w.CreateShortcut((Join-Path $d '%s.lnk')); $s.TargetPath = '%s'; $s.WorkingDirectory = '%s'; "
        "$s.IconLocation = '%s,0'; $s.Description = '%s'; $s.Save() }"
    ) % (APP_NAME, exe, target_dir, exe, APP_NAME)
    result = powershell(script)
    return result.returncode == 0, result.stderr.strip()


def write_uninstaller(target_dir):
    path = os.path.join(target_dir, "uninstall.cmd")
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "taskkill /F /IM %s >nul 2>&1" % EXE,
        'powershell -NoProfile -Command "foreach ($d in @([Environment]::GetFolderPath(\'Desktop\'), '
        '[Environment]::GetFolderPath(\'Programs\'))) { Remove-Item (Join-Path $d \'%s.lnk\') -ErrorAction SilentlyContinue }"' % APP_NAME,
        'reg delete "HKCU\\%s" /f >nul 2>&1' % REG_KEY,
        "rem 余额和设置在 %APPDATA%\\WoWChatTranslator，卸载时特意留着；游戏里的插件请在游戏目录里自己删。",
        'start "" /min cmd /c "timeout /t 2 /nobreak >nul & rmdir /s /q ""%s"""' % target_dir,
    ]
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def register(target_dir, uninstaller):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
        for name, value in (("DisplayName", APP_NAME), ("DisplayVersion", APP_VERSION), ("Publisher", "husen.ca"),
                            ("InstallLocation", target_dir), ("DisplayIcon", os.path.join(target_dir, EXE)),
                            ("UninstallString", 'cmd /c "%s"' % uninstaller)):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


def install(target_dir, shortcut=True, registry=True, progress=lambda text: None):
    """执行安装。出错抛异常，信息是给用户看的中文。"""
    target_dir = os.path.normpath(target_dir)
    progress("关闭正在运行的旧版本…")
    subprocess.run(["taskkill", "/F", "/IM", EXE], capture_output=True, creationflags=NO_WINDOW)
    progress("解压文件…")
    try:
        os.makedirs(target_dir, exist_ok=True)
        # 升级时先清掉旧的程序文件（只动我们自己的两样东西），免得新旧文件混在一起
        old = os.path.join(target_dir, "_internal")
        if os.path.isdir(old):
            shutil.rmtree(old)
        with zipfile.ZipFile(resource("payload.zip")) as z:
            z.extractall(target_dir)
    except PermissionError:
        raise RuntimeError("没有权限写入这个文件夹，或者旧版本还在运行。请换一个位置，或者关掉旧版本再试。")
    except OSError as e:
        raise RuntimeError("解压失败：%s" % e)
    if not os.path.isfile(os.path.join(target_dir, EXE)):
        raise RuntimeError("安装包不完整：没有找到主程序。")
    uninstaller = write_uninstaller(target_dir)
    if registry:
        progress("登记到「应用」列表…")
        try:
            register(target_dir, uninstaller)
        except OSError:
            pass                                 # 登记不上不影响使用
    if shortcut:
        progress("创建桌面快捷方式…")
        ok, err = make_shortcuts(target_dir)
        if not ok:
            raise RuntimeError("程序已装好，但快捷方式没建成：%s\n可以自己到 %s 里找 %s。" % (err, target_dir, EXE))
    return os.path.join(target_dir, EXE)


class Wizard:
    def __init__(self):
        root = self.root = tk.Tk()
        root.title(APP_NAME + " 安装")
        root.configure(bg=BG)
        root.resizable(False, False)
        try:
            root.iconbitmap(resource("icon.ico"))
        except tk.TclError:
            pass
        k = max(1.0, root.winfo_fpixels("1i") / 96.0)
        wrap = int(400 * k)
        body = tk.Frame(root, bg=BG, padx=int(20 * k), pady=int(16 * k))
        body.pack()
        tk.Label(body, text=APP_NAME, bg=BG, fg=GOLD, font=(FONT, 20, "bold")).pack(anchor="w")
        tk.Label(body, text="安装程序 · 版本 %s" % APP_VERSION, bg=BG, fg=DIM, font=(FONT, 9)).pack(anchor="w", pady=(0, 12))

        outer = tk.Frame(body, bg=EDGE, padx=1, pady=1)
        outer.pack(fill="x")
        p = tk.Frame(outer, bg=PANEL, padx=14, pady=12)
        p.pack(fill="both")
        tk.Label(p, text="安装到", bg=PANEL, fg=GOLD_DIM, font=(FONT, 10, "bold"), anchor="w").pack(fill="x")
        self.dir = tk.StringVar(value=default_dir())
        tk.Label(p, textvariable=self.dir, bg=PANEL, fg=TEXT, font=(FONT, 9), anchor="w", justify="left",
                 wraplength=wrap).pack(fill="x", pady=(4, 6))
        self.browse_button = self.button(p, "换个位置…", self.browse, width=9)
        self.browse_button.pack(anchor="w")
        self.shortcut = tk.BooleanVar(value=True)
        tk.Checkbutton(p, text="在桌面创建快捷方式", variable=self.shortcut, bg=PANEL, fg=TEXT, selectcolor=BG,
                       activebackground=PANEL, activeforeground=TEXT, font=(FONT, 10), anchor="w").pack(fill="x", pady=(10, 0))
        tk.Label(p, text="不需要管理员权限。以后升级直接再装一次，余额和设置不会丢。", bg=PANEL, fg=DIM, font=(FONT, 9),
                 anchor="w", justify="left", wraplength=wrap).pack(fill="x", pady=(8, 0))

        self.status = tk.Label(body, text="", bg=BG, fg=DIM, font=(FONT, 9), anchor="w", justify="left", wraplength=wrap)
        self.status.pack(fill="x", pady=(12, 8))
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x")
        self.close_button = self.button(row, "取消", root.destroy, width=8)
        self.close_button.pack(side="right")
        self.main_button = self.button(row, "安装", self.go, width=10)
        self.main_button.pack(side="right", padx=(0, 8))
        self.installed_exe = None
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        root.geometry("+%d+%d" % ((root.winfo_screenwidth() - w) // 2, (root.winfo_screenheight() - h) // 3))

    def button(self, parent, text, command, width):
        frame = tk.Frame(parent, bg=EDGE, padx=1, pady=1)
        face = tk.Label(frame, text=text, bg=BTN, fg=GOLD, font=(FONT, 10, "bold"), width=width, pady=4, cursor="hand2")
        face.pack()
        frame.face, frame.enabled, frame.command = face, True, command
        face.bind("<Enter>", lambda e: frame.enabled and face.configure(bg=BTN_HOVER))
        face.bind("<Leave>", lambda e: frame.enabled and face.configure(bg=BTN))
        face.bind("<ButtonRelease-1>", lambda e: frame.enabled and frame.command())
        return frame

    def enable(self, button, on, text=None):
        button.enabled = on
        button.face.configure(bg=BTN if on else BTN_OFF, fg=GOLD if on else DIM, cursor="hand2" if on else "arrow")
        if text:
            button.face.configure(text=text)

    def browse(self):
        chosen = filedialog.askdirectory(parent=self.root, title="选择安装位置", initialdir=os.path.dirname(self.dir.get()))
        if chosen:
            chosen = os.path.normpath(chosen)
            # 选的是现成的文件夹就在里面建一个自己的子文件夹，免得把文件撒在别人的目录里
            if os.path.basename(chosen).lower() != "wowchattranslator":
                chosen = os.path.join(chosen, "WoWChatTranslator")
            self.dir.set(chosen)

    def go(self):
        if self.installed_exe:                                   # 装完后这个按钮变成「启动」
            subprocess.Popen([self.installed_exe], cwd=os.path.dirname(self.installed_exe))
            self.root.destroy()
            return
        for b in (self.main_button, self.browse_button, self.close_button):
            self.enable(b, False)
        self.status.configure(text="开始安装…", fg=DIM)
        threading.Thread(target=self.work, daemon=True).start()

    def work(self):
        try:
            exe = install(self.dir.get(), shortcut=self.shortcut.get(),
                          progress=lambda text: self.root.after(0, lambda: self.status.configure(text=text, fg=DIM)))
            self.root.after(0, lambda: self.done(exe, None))
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.done(None, err))

    def done(self, exe, err):
        self.enable(self.close_button, True, "关闭")
        if err:
            self.status.configure(text=err, fg=BAD)
            self.enable(self.main_button, True, "重试")
            self.enable(self.browse_button, True)
            return
        self.installed_exe = exe
        where = "桌面上多了一个「%s」图标，" % APP_NAME if self.shortcut.get() else ""
        self.status.configure(text="装好了。%s每次玩之前先打开它。" % where, fg=GOOD)
        self.enable(self.main_button, True, "立即打开")


def main():
    args = sys.argv[1:]
    if "--silent" in args:
        target = args[args.index("--dir") + 1] if "--dir" in args else default_dir()
        try:
            exe = install(target, shortcut="--no-shortcut" not in args, registry="--no-registry" not in args)
        except Exception as e:
            sys.exit(str(e))
        if "--launch" in args:
            subprocess.Popen([exe] + (["--autostart"] if "--autostart" in args else []), cwd=os.path.dirname(exe),
                             close_fds=True)
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    Wizard().root.mainloop()


if __name__ == "__main__":
    main()
