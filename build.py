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


PRODUCT = "ChatBridge Translator"
VERSION_TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=%(tuple)s, prodvers=%(tuple)s, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'senbuilds'),
      StringStruct('FileDescription', %(desc)r),
      StringStruct('FileVersion', %(ver)r),
      StringStruct('InternalName', %(name)r),
      StringStruct('LegalCopyright', 'GPL-3.0'),
      StringStruct('OriginalFilename', %(file)r),
      StringStruct('ProductName', %(product)r),
      StringStruct('ProductVersion', %(ver)r)])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def version_file(name, desc):
    """Windows 文件属性里的产品名和版本号（代码签名要求每个 exe 都带上）。"""
    sys.path.insert(0, os.path.join(ROOT, "app"))
    from version import VERSION
    nums = [int(x) for x in VERSION.split(".")][:4]
    nums += [0] * (4 - len(nums))
    path = os.path.join(WORK, name + "-version.txt")
    os.makedirs(WORK, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(VERSION_TEMPLATE % {"tuple": tuple(nums), "ver": VERSION, "desc": desc, "name": name,
                                    "file": name + ".exe", "product": PRODUCT})
    return path


def main():
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_icon.py")], check=True)
    for d in (DIST, WORK):
        shutil.rmtree(d, ignore_errors=True)

    # 1) 程序本体。--noconsole：不弹黑窗口；数据文件：游戏插件和图标
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
        "--name", "WoWTranslator", "--noconsole", "--icon", ICON,
        "--version-file", version_file("WoWTranslator", "ChatBridge Translator"),
        "--paths", os.path.join(ROOT, "app"),
        "--hidden-import", "app", "--hidden-import", "launcher", "--hidden-import", "codec",
        "--hidden-import", "version", "--hidden-import", "fingerprint",
        "--hidden-import", "i18n", "--collect-all", "opencc",          # 简体 / 繁体转换（OpenCC 带字典）
        "--add-data", os.path.join(ROOT, "addon", "ChatBridge") + os.pathsep + os.path.join("addon", "ChatBridge"),
        "--add-data", ICON + os.pathsep + "assets",
        "--add-data", ICON.replace("icon.ico", "icon_hant.ico") + os.pathsep + "assets",       # 繁体界面的「譯」图标
        "--add-data", os.path.join(ROOT, "assets", "ui") + os.pathsep + os.path.join("assets", "ui"),
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
        "--version-file", version_file("WoWTranslatorSetup", "ChatBridge Translator Setup"),
        "--paths", os.path.join(ROOT, "app"), "--hidden-import", "version",
        "--hidden-import", "i18n", "--collect-all", "opencc",
        "--add-data", payload + os.pathsep + ".", "--add-data", ICON + os.pathsep + ".",
        "--add-data", ICON.replace("icon.ico", "icon_hant.ico") + os.pathsep + ".",
        "--distpath", DIST, "--workpath", WORK, "--specpath", WORK,
        os.path.join(ROOT, "installer", "setup.py"))
    final = os.path.join(DIST, SETUP_NAME)
    os.replace(os.path.join(DIST, "WoWTranslatorSetup.exe"), final)
    print("程序本体：%s" % app_dir)
    print("安装包：  %s  (%.1f MB)" % (final, os.path.getsize(final) / 1e6))


if __name__ == "__main__":
    main()
