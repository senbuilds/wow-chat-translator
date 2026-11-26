"""简体 / 繁体。界面文字在代码里一律写简体；繁体模式下在 Tk 这一层统一转成繁体（台湾常用字形 + 常用词），
翻译页里的译文也一起转。玩家打的繁体中文发出去之前先转回简体，服务器的黑话表只认简体。

模式：config.json 的 "lang"："auto"（默认，跟系统语言）| "hans" | "hant"。环境变量 WOWTR_LANG 可以强制（测试用）。
转换：先按 twdict.py 的台湾用词表整词替换（一般用语 + 台服游戏译名），其余的字用 OpenCC 的 s2tw 转字形。
不用 s2twp：它会把「插件」换成「外掛」，在台湾「外掛」是作弊程序的意思。
"""
import ctypes
import os
import re

_mode = "hans"
_s2t = _t2s = None
_CJK = re.compile(r"[一-鿿]")

import twdict

HANT_LANGIDS = {0x0404, 0x0C04, 0x1404, 0x7C04}      # zh-TW、zh-HK、zh-MO、zh-Hant
ZH_PRIMARY = 0x04


def system_variant():
    """Windows 显示语言是繁体中文 → hant；是简体中文 → hans；不是中文就看区域设置（香港、台湾、澳门 → hant）。"""
    try:
        k = ctypes.windll.kernel32
        ui = k.GetUserDefaultUILanguage()
        if ui & 0x3FF == ZH_PRIMARY:
            return "hant" if ui in HANT_LANGIDS else "hans"
        buf = ctypes.create_unicode_buffer(85)
        if k.GetUserDefaultLocaleName(buf, 85):
            name = buf.value.lower()
            if name.startswith(("zh-tw", "zh-hk", "zh-mo")) or "hant" in name:
                return "hant"
    except Exception:
        pass
    return "hans"


def resolve(setting):
    forced = os.environ.get("WOWTR_LANG")
    if forced in ("hans", "hant"):
        return forced
    return setting if setting in ("hans", "hant") else system_variant()


def _load():
    global _s2t, _t2s
    if _s2t is None:
        try:
            import opencc
            _s2t, _t2s = opencc.OpenCC("s2tw"), opencc.OpenCC("tw2s")
        except Exception:
            _s2t = _t2s = False
    return _s2t


def set_mode(setting):
    """setting 是 config 里的 "lang"。返回实际用的 hans / hant。"""
    global _mode
    _mode = resolve(setting)
    if _mode == "hant" and not _load():
        _mode = "hans"                    # 转换库没带上：退回简体，不至于显示一半
    return _mode


def mode():
    return _mode


_phrase_re = None
_phrase_map = {}


def _phrases():
    global _phrase_re
    if _phrase_re is None:
        for a, b in twdict.GENERAL + twdict.GAME:
            _phrase_map[a] = b
        keys = sorted(_phrase_map, key=len, reverse=True)           # 长词优先
        _phrase_re = re.compile("|".join(re.escape(k) for k in keys))
    return _phrase_re


def _plain(seg):
    """没被词表整词替换的部分：量词等规则 + 字形转换。"""
    for pat, rep in twdict.REGEX:
        seg = re.sub(pat, rep, seg)
    return _s2t.convert(seg)


def to_hant(text):
    """简体（大陆说法）→ 台湾繁体说法：词表整词替换（一次扫描）+ 其余转字形。"""
    if not text or not _CJK.search(text) or not _load():
        return text
    out, pos = [], 0
    for m in _phrases().finditer(text):
        out.append(_plain(text[pos:m.start()]))
        out.append(_phrase_map[m.group(0)])
        pos = m.end()
    out.append(_plain(text[pos:]))
    res = "".join(out)
    res = re.sub(r"(?<![一二兩三四五六七八九十幾這那每半\d])隻", "只", res)      # OpenCC 偶尔把副词「只」错转成量词「隻」
    res = re.sub(r"(?<=[一-鿿])(?=API|Enter|AI |Battle\.net)|(?:(?<=API)|(?<=Enter)|(?<=Battle\.net))(?=[一-鿿])",
                 " ", res)
    res = re.sub(r"(?<![公英千海鄰故萬百])里(?![程長])", "裡", res)       # 「副本里」这类 OpenCC 没转
    res = res.replace("臺", "台")                                          # 台灣日常写「台」
    return res


def t(text):
    """界面文字：繁体模式下转繁体，否则原样。"""
    if _mode != "hant" or not isinstance(text, str):
        return text
    return to_hant(text)


def to_hans(text):
    """玩家打的中文发出去之前：繁体转简体（简体原样）。"""
    if not text or not _CJK.search(text) or not _load():
        return text
    return _t2s.convert(text)


def site(path=""):
    """官网链接：繁体模式下指向 /hant/ 下的同一页。path 以 / 开头，比如 /guide/install.html。"""
    base = "https://wow.husen.ca"
    if _mode == "hant":
        return base + "/hant" + (path or "/")
    return base + (path or "/")


def install_tk_hook():
    """让所有 Tk 控件的 text / label / 窗口标题、Text 控件插入的文字都过一遍 t()。只装一次。"""
    import tkinter
    if getattr(tkinter, "_cb_i18n", False):
        return
    tkinter._cb_i18n = True
    orig_options = tkinter.Misc._options

    def _options(self, cnf, kw=None):
        if _mode == "hant":
            def fix(d):
                if isinstance(d, dict):
                    for key in ("text", "label"):
                        if isinstance(d.get(key), str):
                            d = dict(d)
                            d[key] = t(d[key])
                return d
            cnf, kw = fix(cnf), fix(kw)
        return orig_options(self, cnf, kw)
    tkinter.Misc._options = _options

    orig_title = tkinter.Wm.wm_title

    def wm_title(self, string=None):
        return orig_title(self, t(string) if string is not None else None)
    tkinter.Wm.wm_title = tkinter.Wm.title = wm_title

    orig_insert = tkinter.Text.insert

    def insert(self, index, chars, *args):
        if _mode == "hant":
            chars = t(chars)
            args = tuple(t(a) if i % 2 == 1 and isinstance(a, str) else a for i, a in enumerate(args))
        return orig_insert(self, index, chars, *args)
    tkinter.Text.insert = insert
