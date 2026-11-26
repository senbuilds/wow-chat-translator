"""简体 / 繁体：转换规则、Tk 钩子（控件文字、窗口标题、翻译页里插入的译文）、发出去的繁体先转简体、官网链接。
运行：python tests/test_i18n.py   （需要 pip install opencc）
"""
import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
os.environ.pop("WOWTR_LANG", None)
import i18n  # noqa: E402

ok = 0


def check(cond, what):
    global ok
    assert cond, what
    ok += 1
    print("  ok  " + what)


check(i18n.set_mode("hant") == "hant" and i18n.set_mode("hans") == "hans", "手动选简体 / 繁体")
check(i18n.resolve("auto") in ("hans", "hant"), "auto 跟系统语言")
os.environ["WOWTR_LANG"] = "hant"
check(i18n.resolve("hans") == "hant", "WOWTR_LANG 可以强制（测试用）")
os.environ.pop("WOWTR_LANG")

i18n.set_mode("hant")
check(i18n.t("插件已装进魔兽世界「无限」") == "插件已裝進魔獸世界「永恆」", "插件不会被换成「外掛」（台湾那是作弊的意思）")
check(i18n.t("别只会打 ty 和 gg。") == "別只會打 ty 和 gg。", "「只」不会被误转成量词「隻」")
check(i18n.t("游戏设置") == "遊戲設定" and i18n.t("翻译程序没开") == "翻譯程式沒開", "台湾常用词：設定、程式")
check(i18n.t("领取免费 200 条") == "領取免費 200 則" and i18n.t("屏幕角落一小条色块") == "螢幕角落一小條色塊",
      "量词：消息用「則」，色块还是「條」")
check(i18n.t("侏儒和地精在奥格瑞玛打死亡矿井，团灭了") == "地精和哥布林在奧格瑪打死亡礦坑，滅團了",
      "台服译名：种族错开也不串（一次替换）")
check(i18n.t("充值") == "儲值" and i18n.t("点「更多信息」→「仍要运行」") == "點「其他資訊」→「仍要執行」",
      "台湾说法：儲值；Windows 提示框按台湾版 Windows 的字")
check(i18n.t("开发版不自动安装") == "開發版不自動安裝", "「开发版」不会被「发版」的词条切坏")
check(i18n.t("服务器") == "伺服器" and i18n.t("窗口可以最小化") == "視窗可以最小化", "台湾常用词：伺服器、視窗")
check(i18n.to_hans("我來打斷骷髏，第二個我打不到") == "我来打断骷髅，第二个我打不到", "玩家打的繁体发出去前转回简体（黑话表只认简体）")
check(i18n.to_hans("我来打断骷髅") == "我来打断骷髅", "简体原样")
check(i18n.site("/guide/install.html") == "https://wow.husen.ca/hant/guide/install.html", "繁体模式的官网链接指到 /hant/")

i18n.install_tk_hook()
root = tk.Tk()
root.withdraw()
root.title("魔兽聊天翻译")
lab = tk.Label(root, text="余额")
lab.configure(text="领取免费 200 条")
c = tk.Canvas(root)
item = c.create_text(10, 10, text="游戏设置")
txt = tk.Text(root)
txt.insert("end", "[小队] ", "ch", "队友：巡逻怪来了，等它过去\n", ())
check(root.title() == "魔獸聊天翻譯", "窗口标题转繁体")
check(lab.cget("text") == "領取免費 200 則", "控件文字转繁体")
check(c.itemcget(item, "text") == "遊戲設定", "画布上的文字（按钮）转繁体")
check(txt.get("1.0", "end-1c") == "[隊伍] 隊友：巡邏怪來了，等它過去\n", "翻译页里插入的译文转繁体（标签名不动）")
i18n.set_mode("hans")
lab.configure(text="余额")
check(lab.cget("text") == "余额", "简体模式原样")
root.destroy()

import launcher  # noqa: E402
i18n.set_mode("hant")
check(launcher.hant_url("https://wow.husen.ca/trial?k=promo&t=abc") == "https://wow.husen.ca/hant/trial?k=promo&t=abc",
      "繁体模式：领试用 / 推广码验证页开繁体版")
i18n.set_mode("hans")
check(launcher.hant_url("https://wow.husen.ca/trial?t=abc") == "https://wow.husen.ca/trial?t=abc", "简体模式不改链接")
print("全部通过：%d 项" % ok)
