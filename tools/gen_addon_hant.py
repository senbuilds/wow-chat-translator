"""游戏插件的繁体对照表：扫 ChatBridge.lua 里所有 L("…") 的字面量，用程序同一套简→繁规则（app/i18n.py）转好，
写成 addon/ChatBridge/ChatBridge_Hant.lua。改了插件里的中文以后重跑一次。
第一次用 --wrap：把 ChatBridge.lua 里（注释以外）所有含中文的字符串字面量包成 L("…")。
用法：python tools/gen_addon_hant.py [--wrap]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
import i18n  # noqa: E402

LUA = os.path.join(ROOT, "addon", "ChatBridge", "ChatBridge.lua")
OUT = os.path.join(ROOT, "addon", "ChatBridge", "ChatBridge_Hant.lua")
CJK = re.compile(r"[一-鿿　-〿＀-￯]")
STR = re.compile(r'"((?:[^"\\]|\\.)*)"')


def split_code_comment(line):
    """返回 (代码部分, 注释部分)。只认字符串外面的 --。"""
    in_str, i = False, 0
    while i < len(line):
        ch = line[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif line.startswith("--", i):
                return line[:i], line[i:]
        i += 1
    return line, ""


def wrap():
    src = open(LUA, encoding="utf-8").read().split("\n")
    out, n = [], 0
    for line in src:
        code, comment = split_code_comment(line)

        def rep(m):
            nonlocal n
            start = m.start()
            if not CJK.search(m.group(1)) or code[max(0, start - 2):start] == "L(":
                return m.group(0)
            n += 1
            return 'L("%s")' % m.group(1)
        out.append(STR.sub(rep, code) + comment)
    open(LUA, "w", encoding="utf-8", newline="\n").write("\n".join(out))
    print("包了 %d 处" % n)


def generate():
    i18n._mode = "hant"
    keys = []
    for line in open(LUA, encoding="utf-8"):
        code, _ = split_code_comment(line)
        for m in re.finditer(r'L\("((?:[^"\\]|\\.)*)"\)', code):
            if m.group(1) not in keys:
                keys.append(m.group(1))
    rows = ['    ["%s"] = "%s",' % (k, i18n.to_hant(k)) for k in keys]
    text = ("-- 自动生成（tools/gen_addon_hant.py），别手改：插件界面文字的简体 → 繁体对照。\n"
            "ChatBridge_HANT = {\n%s\n}\n" % "\n".join(rows))
    open(OUT, "w", encoding="utf-8", newline="\n").write(text)
    print("对照表 %d 条 -> %s" % (len(keys), OUT))


if __name__ == "__main__":
    if "--wrap" in sys.argv:
        wrap()
    generate()
