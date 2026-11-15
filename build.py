"""打包：先把程序做成一个文件夹（主程序 + 依赖），再把它塞进一个单文件的安装包。

运行（要用装了 PyInstaller 和 Pillow 的 Python）：
    python build.py
产物：
    dist/WoWTranslator/                 程序本体（启动器和翻译进程是同一个 exe）
    dist/魔兽聊天翻译-安装包.exe          发给朋友的就是这一个文件
"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST, WORK = os.path.join(ROOT, "dist"), os.path.join(ROOT, "build")
ICON = os.path.join(ROOT, "assets", "icon.ico")
SETUP_NAME = "魔兽聊天翻译-安装包.exe"


def run(*args):
    print(">", " ".join(args[:6]), "...")
    subprocess.run(args, check=True, cwd=ROOT)


def main():
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_icon.py")], check=True)
    for d in (DIST, WORK):
        shutil.rmtree(d, ignore_errors=True)

    # 1) 程序本体。--noconsole：不弹黑窗口；数据文件：游戏插件和图标
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
        "--name", "WoWTranslator", "--noconsole", "--icon", ICON,
        "--paths", os.path.join(ROOT, "app"),
        "--hidden-import", "app", "--hidden-import", "launcher", "--hidden-import", "codec",
        "--hidden-import", "version",
        "--add-data", os.path.join(ROOT, "addon", "ChatBridge") + os.pathsep + os.path.join("addon", "ChatBridge"),
        "--add-data", ICON + os.pathsep + "assets",
        "--distpath", DIST, "--workpath", WORK, "--specpath", WORK,
        os.path.join(ROOT, "app", "main.py"))

    # 2) 把程序文件夹压成 payload.zip
    app_dir = os.path.join(DIST, "WoWTranslator")
    payload = os.path.join(WORK, "payload.zip")
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for folder, _, files in os.walk(app_dir):
            for name in files:
                full = os.path.join(folder, name)
                z.write(full, os.path.relpath(full, app_dir))

    # 3) 安装包：单文件，里面带着 payload.zip
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--log-level", "WARN",
        "--name", "WoWTranslatorSetup", "--onefile", "--noconsole", "--icon", ICON,
        "--paths", os.path.join(ROOT, "app"), "--hidden-import", "version",
        "--add-data", payload + os.pathsep + ".", "--add-data", ICON + os.pathsep + ".",
        "--distpath", DIST, "--workpath", WORK, "--specpath", WORK,
        os.path.join(ROOT, "installer", "setup.py"))
    final = os.path.join(DIST, SETUP_NAME)
    os.replace(os.path.join(DIST, "WoWTranslatorSetup.exe"), final)
    print("程序本体：%s" % app_dir)
    print("安装包：  %s  (%.1f MB)" % (final, os.path.getsize(final) / 1e6))


if __name__ == "__main__":
    main()
