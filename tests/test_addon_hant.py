"""插件的简体 / 繁体：启动器写 ChatBridgeLang = "hant" 时插件文字是繁体；"hans" 或没写（非台服客户端）是简体；
没写但游戏是台服繁体客户端（zhTW）也用繁体。对照表要覆盖插件里所有 L("…")。
运行：python tests/test_addon_hant.py   （需要 pip install lupa）
"""
import locale
import os
import re
import sys

import lupa.lua51 as lua51

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "addon", "ChatBridge")
src = open(os.path.join(ROOT, "tests", "test_addon.py"), encoding="utf-8").read()
STUBS = re.search(r'STUBS = r"""(.*?)"""', src, re.S).group(1)
ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("  ok  " + what)


def load(lang, client_locale="enUS"):
    locale.setlocale(locale.LC_CTYPE, "C")
    lua = lua51.LuaRuntime(unpack_returned_tuples=True, encoding=None)
    lua.execute(STUBS.encode())
    lua.execute(('function GetLocale() return "%s" end' % client_locale).encode())
    lua.execute(b"ChatBridgeLang = " + (('"%s"' % lang).encode() if lang else b"nil"))
    for name in ("ChatBridge_Hant.lua", "ChatBridge.lua"):
        with open(os.path.join(ADDON, name), "rb") as f:
            lua.execute(f.read())
    lua.eval("fire")(b"ADDON_LOADED", b"ChatBridge")
    lua.eval("fire")(b"PLAYER_ENTERING_WORLD")
    text = b"\n".join(bytes(p) for p in lua.eval("printed").values()).decode("utf-8")
    channels = [bytes(c[2]).decode("utf-8") for c in lua.eval("ChatBridge.CHANNELS").values()]
    return text, channels


t, ch = load("hant")
check("已載入" in t and "翻譯" in t and "已加载" not in t, "启动器选了繁体：插件提示是繁体")
check(ch[0] == "隊伍" and "公會" in ch, "频道名用台服客户端的叫法（隊伍）")
t, ch = load("hans", "zhTW")
check("已加载" in t and ch[0] == "小队", "启动器选了简体：就算是台服客户端也用简体")
t, ch = load(None, "zhTW")
check("已載入" in t, "没有启动器设置、台服繁体客户端：用繁体")
t, ch = load(None, "enUS")
check("已加载" in t, "没有启动器设置、英文客户端：用简体")

lua_src = open(os.path.join(ADDON, "ChatBridge.lua"), encoding="utf-8").read()
hant_src = open(os.path.join(ADDON, "ChatBridge_Hant.lua"), encoding="utf-8").read()
missing = [k for k in set(re.findall(r'L\("((?:[^"\\]|\\.)*)"\)', lua_src)) if '["%s"]' % k not in hant_src]
check(not missing, "对照表覆盖所有 L(…)（漏了就重跑 tools/gen_addon_hant.py）：%s" % missing[:3])
check(re.search(r'[一-鿿]', "".join(l.split("--")[0] for l in lua_src.split("\n")
                                             if 'L("' not in l and "ChatBridgeLang" not in l)) is None,
      "插件代码里没有漏包 L() 的中文")
print("全部通过：%d 项" % ok)
