"""魔兽聊天翻译 · 安装程序。

把程序解压到当前用户的程序目录（不需要管理员权限），在桌面和开始菜单建快捷方式，
并登记到「设置 → 应用」里方便卸载。重复运行就是升级：余额和设置存在别处，不会丢。

命令行参数（启动器自动更新时用，也方便测试）：
  --silent  --dir <目录>  --no-shortcut  --no-registry
  --launch       装完直接打开程序
  --autostart    打开后自动点「启动」（更新前翻译在跑时用）
"""
import ctypes
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
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
# 配色和官网、启动器一致：深棕底、金色小标题、羊皮纸色正文、细线分隔、平的按钮
BG, PANEL, EDGE = "#170e09", "#170e09", "#4a3b30"
GOLD, GOLD_DIM, TEXT, DIM, WHITE = "#edaf00", "#edaf00", "#ebdec2", "#b1997f", "#ffffff"
BTN, BTN_HOVER = "#aa2409", "#c22c0c"           # 主按钮：红底白字
SEC, SEC_HOVER = "#2a1e15", "#3a2a1d"           # 次按钮：深棕底、细线边
BTN_OFF, OFF_TEXT, OFF_EDGE = "#211710", "#6f604f", "#2e241c"
GOOD, BAD = "#8fc46a", "#e8664f"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PRIVACY_URL = "https://wow.husen.ca/privacy.html"
PRIVACY_TEXT = ("默认使用线上翻译：要翻译的那句话和一个匿名设备编号会发到 wow.husen.ca，服务器不保存聊天内容。"
                "程序还会报几项匿名数字（版本、连接状态、消息条数），用来排查装好后用不了的问题。"
                "不想经过我们的服务器，可以在启动器里改用「自带模型」。")


def resource(name):
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), name)


def default_dir():
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", "WoWChatTranslator")


def powershell(script):
    # errors="replace"：PowerShell 的报错按控制台代码页输出，和 Python 默认的解码方式对不上时不要因此抛异常
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)


def ps_quote(text):
    """放进 PowerShell 单引号字符串之前：把引号写两遍（PowerShell 里 '' 表示一个 '）。
    用户名里可能有单引号（O'Brien）。PowerShell 把弯引号 ‘ ’ ‚ ‛ 也当单引号用，所以一起处理。"""
    return re.sub("(['\u2018\u2019\u201a\u201b])", r"\1\1", text)


def make_shortcuts(target_dir):
    """桌面和开始菜单各建一个快捷方式。桌面可能被 OneDrive 接管，所以让系统自己报路径。"""
    exe = os.path.join(target_dir, EXE)
    icon = exe
    try:                                      # 繁体中文的系统：快捷方式用「譯」字图标
        import i18n
        hant_icon = os.path.join(target_dir, "_internal", "assets", "icon_hant.ico")
        if i18n.mode() == "hant" and os.path.exists(hant_icon):
            icon = hant_icon
    except Exception:
        pass
    script = (
        "$w = New-Object -ComObject WScript.Shell; "
        "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { "
        "$s = $w.CreateShortcut((Join-Path $d '%s.lnk')); $s.TargetPath = '%s'; $s.WorkingDirectory = '%s'; "
        "$s.IconLocation = '%s,0'; $s.Description = '%s'; $s.Save() }"
    ) % tuple(ps_quote(v) for v in (APP_NAME, exe, target_dir, icon, APP_NAME))
    try:
        result = powershell(script)
    except Exception as e:                    # PowerShell 被禁用 / 被拦：当成「没建成」，由调用的地方决定要不要紧
        return False, str(e)
    return result.returncode == 0, result.stderr.strip()


def write_uninstaller(target_dir):
    """生成 uninstall.cmd。它分两段跑：
    1) 在程序目录里跑：关程序、删快捷方式、删注册表登记，然后把自己复制到 %TEMP%，从那里再跑一次（带 --cleanup）；
    2) %TEMP% 里的那份：等 2 秒，删程序文件。脚本不能在自己所在的目录里删掉这个目录，所以要挪出去。

    为什么这么绕（以前是一行 start ... cmd /c，里面用两个双引号包住路径再 rmdir /s /q）：
    - cmd 里连写两个双引号不是转义引号，路径有空格时 rmdir 会收到两个参数，可能删错目录。
      现在所有带路径的地方都只用一对普通引号，而且启动第二段时命令行里根本不出现路径
      （先 cd 到 %TEMP%，再用不含空格和特殊字符的相对文件名），不用再考虑引号套引号。
    - 程序目录在生成脚本时写死在 set "TARGET=..." 里：% 写成 %%；& ^ ( ) ! 在引号里是普通字符
      （脚本关掉了延迟展开，! 不会被解释）。Windows 的路径里不会有双引号；万一有，或者有换行，
      或者目标是盘符根目录，就把 TARGET 留空，脚本看到空的就不删任何文件（宁可不删）。
    - 只删我们自己装进去的东西（_internal、主程序、卸载脚本），最后用不带 /s 的 rmdir 收尾：
      目录里有别的文件（用户把程序装进了一个已有的文件夹）就留着不动。
      删之前先确认目录里有主程序；目录被挪走、改名了就什么都不删。
    不处理的情况：路径以空格或句点结尾、超长路径——这些情况下文件可能删不掉，但不会删错。
    """
    path = os.path.join(target_dir, "uninstall.cmd")
    unsafe = (any(c == '"' or ord(c) < 32 for c in target_dir)
              or os.path.dirname(target_dir) == target_dir)          # 盘符根目录
    embedded = "" if unsafe else target_dir.replace("%", "%%")
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "setlocal DisableDelayedExpansion",
        'set "TARGET=%s"' % embedded,
        'if "%~1"=="--cleanup" goto cleanup',
        "taskkill /F /IM %s >nul 2>&1" % EXE,
        'powershell -NoProfile -Command "foreach ($d in @([Environment]::GetFolderPath(\'Desktop\'), '
        '[Environment]::GetFolderPath(\'Programs\'))) { Remove-Item (Join-Path $d \'%s.lnk\') -ErrorAction SilentlyContinue }"' % APP_NAME,
        'reg delete "HKCU\\%s" /f >nul 2>&1' % REG_KEY,
        "rem 余额和设置在 %APPDATA%\\WoWChatTranslator，卸载时特意留着；游戏里的插件请在游戏目录里自己删。",
        "if not defined TARGET goto finish",
        "if not defined TEMP goto finish",
        'set "CLEAN=wowtr-uninstall-%RANDOM%%RANDOM%.cmd"',
        'copy /y "%~f0" "%TEMP%\\%CLEAN%" >nul 2>&1',
        "if errorlevel 1 goto finish",
        'cd /d "%TEMP%"',
        "if errorlevel 1 goto finish",
        'start "" /min cmd /c .\\%CLEAN% --cleanup',
        ":finish",
        "exit /b 0",
        "",
        ":cleanup",
        "if not defined TARGET goto cleanup_done",
        "timeout /t 2 /nobreak >nul 2>&1 || ping -n 3 127.0.0.1 >nul",
        'if not exist "%TARGET%\\' + EXE + '" goto cleanup_done',
        'if exist "%TARGET%\\_internal" rmdir /s /q "%TARGET%\\_internal"',
        'del /f /q "%TARGET%\\' + EXE + '" >nul 2>&1',
        'del /f /q "%TARGET%\\uninstall.cmd" >nul 2>&1',
        'rmdir "%TARGET%" >nul 2>&1',
        ":cleanup_done",
        'del "%~f0" >nul 2>&1 & exit',
    ]
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def register(target_dir, uninstaller):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
        for name, value in (("DisplayName", APP_NAME + " (ChatBridge Translator)"), ("DisplayVersion", APP_VERSION),
                            ("Publisher", "ChatBridge Translator"),
                            ("InstallLocation", target_dir), ("DisplayIcon", os.path.join(target_dir, EXE)),
                            # 外面多包一层引号：cmd /c 遇到「开头是引号、且不止一对」会剥掉最外面那层，
                            # 里面那对原样留下。只包一层的话，路径里有 & ( ) 时 cmd 会连这层也剥掉，带空格的路径就断了
                            ("UninstallString", 'cmd /c ""%s""' % uninstaller)):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


def launcher_settings_path():
    """和启动器用同一个文件：%APPDATA%\\WoWChatTranslator\\launcher.json。"""
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WoWChatTranslator", "launcher.json")


def load_launcher_settings():
    try:
        with open(launcher_settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_launcher_setting(key, value):
    data = load_launcher_settings()
    data[key] = value
    try:
        os.makedirs(os.path.dirname(launcher_settings_path()), exist_ok=True)
        with open(launcher_settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass                                     # 存不上就按默认（检查更新），不影响安装


def old_version_running():
    """旧版本的进程还在不在。True / False；查不了（tasklist 被禁用等）返回 None。"""
    try:
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % EXE, "/FO", "CSV", "/NH"],
                                capture_output=True, creationflags=NO_WINDOW, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    # 按字节比：tasklist 的提示文字是控制台代码页，不解码就不会因为编码对不上出错；程序名本身是 ASCII
    return EXE.lower().encode("ascii") in result.stdout.lower()


def stop_old_version(wait=10.0):
    """关掉正在运行的旧版本，并等它真的退出（最多约 wait 秒）。
    taskkill 只是发出结束请求，进程和它占着的文件要过一会儿才放开；不等的话后面换文件会撞上「文件被占用」。
    这里不报错：到底能不能换，由后面的改名来判断（改名失败会原样保留旧版）。"""
    deadline = time.time() + wait
    while True:
        try:
            subprocess.run(["taskkill", "/F", "/IM", EXE], capture_output=True, creationflags=NO_WINDOW, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        state = old_version_running()
        if state is False:
            return
        if state is None:                        # 查不了进程列表：保守地多等一会儿
            time.sleep(1.5)
            return
        if time.time() >= deadline:              # 关不掉（比如旧版本是「以管理员身份运行」的）
            return
        time.sleep(0.5)


def retry(action, tries=6, delay=0.5):
    """文件操作失败就隔一会儿再试：刚结束的进程、杀毒软件的扫描会短暂占着文件。最后一次还失败就把异常抛出去。"""
    for n in range(tries):
        try:
            return action()
        except OSError:
            if n == tries - 1:
                raise
            time.sleep(delay)


def swap_in(staging, target_dir, backup):
    """用 staging 里的新文件换掉 target_dir 里的同名旧文件。失败抛 OSError，并把已经动过的全部放回去。

    只用「改名」，不直接删旧文件：改名要么整个成功、要么完全没动，不会出现删了一半的 _internal。
    旧文件先挪到 backup，新文件都就位后才由调用的地方删掉 backup。"""
    names = sorted(os.listdir(staging), key=lambda n: n != "_internal")   # 最容易被占用的 _internal 先试，不行就什么都还没动
    moved_out, moved_in = [], []

    def move(src, dst):
        retry(lambda: os.rename(src, dst))

    try:
        for name in names:
            if os.path.lexists(os.path.join(target_dir, name)):
                move(os.path.join(target_dir, name), os.path.join(backup, name))
                moved_out.append(name)
        for name in names:
            move(os.path.join(staging, name), os.path.join(target_dir, name))
            moved_in.append(name)
    except OSError:
        for name in moved_in:                    # 放回去：先把已经就位的新文件挪走，再把旧文件挪回来
            try:
                os.rename(os.path.join(target_dir, name), os.path.join(staging, name))
            except OSError:
                pass
        for name in moved_out:
            try:
                os.rename(os.path.join(backup, name), os.path.join(target_dir, name))
            except OSError:
                pass
        raise


def install(target_dir, shortcut=True, registry=True, progress=lambda text: None, shortcut_fatal=True):
    """执行安装。出错抛异常，信息是给用户看的中文。

    覆盖安装的顺序：关旧版本并等它退出 → 新文件先解到旁边的临时目录 → 都解好了再和旧文件对调。
    中间任何一步失败，目标目录里的旧版本都保持原样、还能用。
    shortcut_fatal=False（静默更新时）：快捷方式没建成也算装好。"""
    target_dir = os.path.abspath(os.path.normpath(target_dir))
    # 临时目录放在目标目录旁边（同一个盘，改名才是瞬间完成的）。名字带 wowtr，免得和用户自己的文件夹撞名：
    # 开工前会清掉上次留下的这两个目录，如果只叫 .new / .old，装到 D:\Games 时就会删掉用户的 D:\Games.old
    staging, backup = target_dir + ".wowtr-new", target_dir + ".wowtr-old"
    progress("关闭正在运行的旧版本…")
    stop_old_version()
    progress("解压文件…")
    try:
        os.makedirs(target_dir, exist_ok=True)
        for leftover in (staging, backup):
            if os.path.lexists(leftover):
                retry(lambda: shutil.rmtree(leftover))
        os.makedirs(backup)
        with zipfile.ZipFile(resource("payload.zip")) as z:
            z.extractall(staging)
    except PermissionError:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        raise RuntimeError("没有权限写入这个文件夹。请换一个位置再试。")
    except (OSError, zipfile.BadZipFile) as e:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        raise RuntimeError("解压失败：%s" % e)
    if not os.path.isfile(os.path.join(staging, EXE)):
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        raise RuntimeError("安装包不完整：没有找到主程序。")
    progress("替换旧文件…")
    try:
        swap_in(staging, target_dir, backup)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        try:
            os.rmdir(backup)                     # 只删空的：万一旧文件没能放回去，它们还在这里，不能丢
        except OSError:
            pass
        raise RuntimeError("旧版本的文件还被占用着，没能换成新版。请关掉魔兽聊天翻译再试。")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    if not os.path.isfile(os.path.join(target_dir, EXE)):
        raise RuntimeError("安装包不完整：没有找到主程序。")
    try:
        uninstaller = write_uninstaller(target_dir)
    except OSError:
        uninstaller = None                       # 卸载脚本写不出来不影响使用（旧的那份还在的话接着用）
    if registry and uninstaller:
        progress("登记到「应用」列表…")
        try:
            register(target_dir, uninstaller)
        except OSError:
            pass                                 # 登记不上不影响使用
    if shortcut:
        progress("创建桌面快捷方式…")
        try:
            ok, err = make_shortcuts(target_dir)
        except Exception as e:
            ok, err = False, str(e)
        if not ok and shortcut_fatal:
            raise RuntimeError("程序已装好，但快捷方式没建成：%s\n可以自己到 %s 里找 %s。" % (err, target_dir, EXE))
    return os.path.join(target_dir, EXE)


class Wizard:
    def __init__(self):
        try:                                      # 繁体中文的系统显示繁体（安装时还没有设置，只看系统语言）
            import i18n
            if i18n.set_mode("auto") == "hant":
                global PRIVACY_URL
                PRIVACY_URL = "https://wow.husen.ca/hant/privacy.html"
            i18n.install_tk_hook()
        except Exception:
            pass
        root = self.root = tk.Tk()
        root.title(APP_NAME + " 安装")
        try:                                      # 标题栏用深色（Windows 10/11），不支持就算了
            root.update_idletasks()
            on = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.windll.user32.GetParent(root.winfo_id()), 20,
                                                       ctypes.byref(on), ctypes.sizeof(on))
        except Exception:
            pass
        root.configure(bg=BG)
        root.resizable(False, False)
        try:
            hant = os.path.exists(resource("icon_hant.ico")) and "hant" in PRIVACY_URL       # 繁体系统用「譯」图标
            root.iconbitmap(resource("icon_hant.ico" if hant else "icon.ico"))
        except tk.TclError:
            pass
        k = max(1.0, root.winfo_fpixels("1i") / 96.0)
        wrap = int(400 * k)
        body = tk.Frame(root, bg=BG, padx=int(20 * k), pady=int(16 * k))
        body.pack()
        tk.Label(body, text=APP_NAME, bg=BG, fg=WHITE, font=(FONT, 18, "bold")).pack(anchor="w")
        tk.Label(body, text="ChatBridge Translator · 安装 %s 版" % APP_VERSION, bg=BG, fg=DIM,
                 font=(FONT, 9, "bold")).pack(anchor="w", pady=(0, 14))
        tk.Frame(body, bg=EDGE, height=1).pack(fill="x")
        p = tk.Frame(body, bg=PANEL, pady=12)
        p.pack(fill="x")
        tk.Label(p, text="安装到", bg=PANEL, fg=GOLD_DIM, font=(FONT, 10, "bold"), anchor="w").pack(fill="x")
        self.dir = tk.StringVar(value=default_dir())
        tk.Label(p, textvariable=self.dir, bg=PANEL, fg=TEXT, font=(FONT, 9), anchor="w", justify="left",
                 wraplength=wrap).pack(fill="x", pady=(4, 6))
        self.browse_button = self.button(p, "换个位置…", self.browse, width=9, primary=False)
        self.browse_button.pack(anchor="w")
        self.shortcut = tk.BooleanVar(value=True)
        tk.Checkbutton(p, text="在桌面创建快捷方式", variable=self.shortcut, bg=PANEL, fg=TEXT, selectcolor="#120b07",
                       activebackground=PANEL, activeforeground=TEXT, font=(FONT, 10), anchor="w").pack(fill="x", pady=(10, 0))
        self.auto_update = tk.BooleanVar(value=load_launcher_settings().get("auto_check_update", True))
        tk.Checkbutton(p, text="启动时自动检查更新（会访问 wow.husen.ca）", variable=self.auto_update, bg=PANEL, fg=TEXT,
                       selectcolor="#120b07", activebackground=PANEL, activeforeground=TEXT, font=(FONT, 10),
                       anchor="w").pack(fill="x")
        tk.Label(p, text="不需要管理员权限。升级时再装一次就行，余额和设置都会保留。", bg=PANEL, fg=DIM, font=(FONT, 9),
                 anchor="w", justify="left", wraplength=wrap).pack(fill="x", pady=(8, 0))

        tk.Frame(p, bg=EDGE, height=1).pack(fill="x", pady=(14, 0))
        tk.Label(p, text="隐私", bg=PANEL, fg=GOLD_DIM, font=(FONT, 10, "bold"), anchor="w").pack(fill="x", pady=(10, 0))
        tk.Label(p, text=PRIVACY_TEXT, bg=PANEL, fg=DIM, font=(FONT, 9), anchor="w", justify="left",
                 wraplength=wrap).pack(fill="x", pady=(4, 0))
        link = tk.Label(p, text="完整隐私说明：" + PRIVACY_URL, bg=PANEL, fg=GOLD, font=(FONT, 9, "underline"),
                        anchor="w", cursor="hand2")
        link.pack(fill="x", pady=(4, 0))
        link.bind("<ButtonRelease-1>", lambda e: webbrowser.open(PRIVACY_URL))

        self.status = tk.Label(body, text="", bg=BG, fg=DIM, font=(FONT, 9), anchor="w", justify="left", wraplength=wrap)
        self.status.pack(fill="x", pady=(12, 8))
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x")
        self.close_button = self.button(row, "取消", root.destroy, width=8, primary=False)
        self.close_button.pack(side="right")
        self.main_button = self.button(row, "安装", self.go, width=10)
        self.main_button.pack(side="right", padx=(0, 8))
        self.installed_exe = None
        self.events = queue.Queue()              # 工作线程 → 主线程：("progress", 文字) 或 ("done", exe, 错误)
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        root.geometry("+%d+%d" % ((root.winfo_screenwidth() - w) // 2, (root.winfo_screenheight() - h) // 3))

    def button(self, parent, text, command, width, primary=True):
        colors = (BTN, BTN_HOVER, WHITE, BTN) if primary else (SEC, SEC_HOVER, TEXT, EDGE)
        frame = tk.Frame(parent, bg=colors[3], padx=1, pady=1)
        face = tk.Label(frame, text=text, bg=colors[0], fg=colors[2], font=(FONT, 10, "bold"), width=width, pady=5,
                        cursor="hand2")
        face.pack()
        frame.face, frame.enabled, frame.command, frame.colors = face, True, command, colors
        face.bind("<Enter>", lambda e: frame.enabled and face.configure(bg=colors[1]))
        face.bind("<Leave>", lambda e: frame.enabled and face.configure(bg=colors[0]))
        face.bind("<ButtonRelease-1>", lambda e: frame.enabled and frame.command())
        return frame

    def enable(self, button, on, text=None):
        button.enabled = on
        c = button.colors
        button.face.configure(bg=c[0] if on else BTN_OFF, fg=c[2] if on else OFF_TEXT, cursor="hand2" if on else "arrow")
        button.configure(bg=c[3] if on else OFF_EDGE)
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
        # Tk 的变量和控件只能在主线程碰：这里先把值取好，再交给工作线程
        options = (self.dir.get(), bool(self.shortcut.get()), bool(self.auto_update.get()))
        threading.Thread(target=self.work, args=options, daemon=True).start()
        self.root.after(100, self.poll)

    def work(self, target_dir, shortcut, auto_update):
        """在后台线程里跑。不碰任何 Tk 的东西，进度和结果都放进 self.events，由主线程的 poll 取出来显示。"""
        try:
            exe = install(target_dir, shortcut=shortcut, progress=lambda text: self.events.put(("progress", text)))
            save_launcher_setting("auto_check_update", auto_update)
            self.events.put(("done", exe, None))
        except Exception as e:
            self.events.put(("done", None, str(e)))

    def poll(self):
        """主线程：每 0.1 秒看一眼工作线程放进来的进度，收到 done 就不再排下一次。"""
        finished = False
        try:
            while True:
                item = self.events.get_nowait()
                if item[0] == "progress":
                    self.status.configure(text=item[1], fg=DIM)
                else:
                    finished = True
                    self.done(item[1], item[2])
        except queue.Empty:
            pass
        finally:
            if not finished:
                self.root.after(100, self.poll)

    def done(self, exe, err):
        self.enable(self.close_button, True, "关闭")
        if err:
            self.status.configure(text=err, fg=BAD)
            self.enable(self.main_button, True, "重试")
            self.enable(self.browse_button, True)
            return
        self.installed_exe = exe
        where = "桌面上多了一个「%s」图标，" % APP_NAME if self.shortcut.get() else ""
        self.status.configure(text="安装完成。%s每次玩之前先打开它。" % where, fg=GOOD)
        self.enable(self.main_button, True, "立即打开")


def message_box(text):
    """弹一个系统消息框。安装包是不带控制台的程序，静默模式下出了事只有这一个办法告诉用户。"""
    title = APP_NAME
    try:                                          # 繁体中文的系统显示繁体
        import i18n
        i18n.set_mode("auto")
        text, title = i18n.t(text), i18n.t(title)
    except Exception:
        pass
    try:
        # 0x30 警告图标；0x10000 | 0x40000 提到最前面并置顶：这时候没有别的窗口，别让它躲在游戏后面
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x30 | 0x10000 | 0x40000)
    except Exception:
        pass


def silent_install(args):
    """静默安装（启动器「立即更新」时调用）。参数保持和旧版一样，旧版启动器会用老参数调用新安装包。"""
    target = None
    try:
        target = args[args.index("--dir") + 1] if "--dir" in args else default_dir()
        # 静默更新时快捷方式建不成不算失败：程序已经换好了，接着打开就行
        exe = install(target, shortcut="--no-shortcut" not in args, registry="--no-registry" not in args,
                      shortcut_fatal=False)
    except Exception as e:
        silent_failed(target, args, e)
        sys.exit(1)
    if "--launch" in args:
        try:
            subprocess.Popen([exe] + (["--autostart"] if "--autostart" in args else []), cwd=os.path.dirname(exe),
                             close_fds=True)
        except OSError:
            message_box("新版本装好了，但没能自动打开。请从桌面图标打开。")


def silent_failed(target, args, error):
    """静默安装失败：以前是直接退出，用户只看到点了「立即更新」之后程序没了。
    现在把旧版本重新打开（更新前被我们关掉了），再弹框说明原因。"""
    old_exe = os.path.join(os.path.abspath(os.path.normpath(target)), EXE) if target else ""
    old_ok = bool(old_exe) and os.path.isfile(old_exe) and os.path.isdir(os.path.join(os.path.dirname(old_exe), "_internal"))
    if old_ok and "--launch" in args:            # 先打开旧版本再弹框：翻译能早点恢复，不用等用户点「确定」
        try:
            subprocess.Popen([old_exe] + (["--autostart"] if "--autostart" in args else []),
                             cwd=os.path.dirname(old_exe), close_fds=True)
        except OSError:
            pass
    if isinstance(error, RuntimeError):          # install() 自己抛的：本来就是写给用户看的话
        reason = str(error).strip().rstrip("。.")
    else:                                        # 没料到的错误：原样带上，用户截图反馈时我们看得懂
        reason = "安装程序出了点问题（%s: %s）" % (error.__class__.__name__, error)
    message_box("更新没装上：%s。%s" % (reason, "旧版本还在，可以继续用。" if old_ok
                                  else "请到 wow.husen.ca 重新下载安装包再装一次。"))


def main():
    args = sys.argv[1:]
    if "--silent" in args:
        silent_install(args)
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    Wizard().root.mainloop()


if __name__ == "__main__":
    main()
