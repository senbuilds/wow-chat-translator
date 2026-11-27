"""翻译窗口进程里能脱离界面测的逻辑：前文（聊天上下文）、物品链接、配置文件读写、分发 / 积压保护、
自动粘贴的判断、漏读提醒、找游戏窗口、自带模型的报错。不连网、不开窗口。运行：python tests/test_context.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
import app  # noqa: E402

n = 0


def check(cond, what):
    global n
    assert cond, what
    n += 1
    print("  ok ", what)


r = app.RecentChat()
check(r.before("P", "Bob\x1fff0000") is None, "队伍里第一句：没有前文")
r.add("P", "Bob\x1fff0000", "who has the key")
r.add("C", "Ads", "WTS stuff 5g")
r.add("G", "Gil", "anyone on for ubrs")
check(r.before("I", "Amy") == ["Bob: who has the key"], "小队 / 团队 / 副本算同一场对话；名字去掉职业色")
check(r.before("C", "Ads") is None and r.before("G", "Gil") is None and r.before("S", "X") is None and r.before("Y", "X") is None,
      "公共频道、公会、说、喊不带前文")
for i in range(5):
    r.add("R", "Amy", "line %d" % i)
check(r.before("P", "Bob") == ["Amy: line 2", "Amy: line 3", "Amy: line 4"], "最多带 3 句，取最近的")
r.add("H", "Zed", "u there?")
check(r.before("H", "Zed") == ["Zed: u there?"] and r.before("H", "Other") is None, "密语只带同一个人的")
check(r.latest() == ["Zed: u there?"], "自己发话：带最近那场对话的几句")
r.add("P", "Bob", "x" * 500)
check(len(r.before("P", "Amy")[-1]) <= 5 + app.CONTEXT_CHARS, "太长的前文截短")
old = app.time.time
app.time.time = lambda: old() + 200
check(r.before("P", "Amy") is None and r.latest() is None, "超过 2 分钟的不带")
app.time.time = old

check(app.needs_translation("WTS [奥金斧] 50g pst"), "方括号里是中文物品名、外面是英文：要翻")
check(not app.needs_translation("[奥金斧] 我要这个") and not app.needs_translation("[奥金斧]"), "外面是中文或只有链接：不翻")

sent = {}


class Fake(app.Relay):
    def _request(self, path, body=None, timeout=10, headers=None):
        sent.update(body)
        return {"text": "ok"}


f = Fake({"own_model": {}})
f.translate("i do", "en2zh", ["Lee: who has the key"])
check(sent.get("context") == ["Lee: who has the key"], "前文随翻译请求带上")
sent.clear()
f.translate("i do", "en2zh")
check("context" not in sent, "没有前文就不带这个字段")

# 新版本提示：启动器写 update.json，翻译页读
import json
import tempfile
app.UPDATE_HINT_PATH = os.path.join(tempfile.mkdtemp(), "update.json")
check(app.update_hint("1.4.0") == (None, False), "没有提示文件：不提示")
json.dump({"latest": "1.5.0", "min": ""}, open(app.UPDATE_HINT_PATH, "w"))
check(app.update_hint("1.4.0") == ("1.5.0", False) and app.update_hint("1.5.0") == (None, False), "有新版本才提示；已是最新不提示")
json.dump({"latest": "1.6.0", "min": "1.5.0"}, open(app.UPDATE_HINT_PATH, "w"))
check(app.update_hint("1.4.0") == ("1.6.0", True) and app.update_hint("1.5.0") == ("1.6.0", False), "低于最低可用版本才算太旧")
json.dump({}, open(app.UPDATE_HINT_PATH, "w"))
check(app.update_hint("1.4.0") == (None, False), "空提示：不提示")


# ---------------------------------------------------------------------------
# 配置文件：原子写、.bak、读坏文件、only= 只更新自己的键
# ---------------------------------------------------------------------------
def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


cfg_dir = tempfile.mkdtemp()
app.CONFIG_PATH = os.path.join(cfg_dir, "sub", "config.json")
BAK = app.CONFIG_PATH + ".bak"
first = app.load_config()
check(first["device_id"].startswith("d_") and read_json(app.CONFIG_PATH)["device_id"] == first["device_id"],
      "没有配置文件：生成设备编号并存盘（目录不存在会自己建）")
check(os.listdir(os.path.dirname(app.CONFIG_PATH)) == ["config.json"], "原子写：换上去以后不留临时文件；第一次保存没有旧文件可备份")

mine = app.load_config()                         # 翻译窗口进程启动时读的那一份
theirs = app.load_config()                       # 启动器那一份：之后换了设备编号、切了繁体，整份保存
theirs["device_id"], theirs["lang"] = "d_" + "1" * 32, "hant"
app.save_config(theirs)
check(read_json(BAK)["device_id"] == first["device_id"], "覆盖之前把旧文件留一份 .bak")
mine["geometry"], mine["dock_rect"] = "480x300+1+2", [True, 1, 2, 3, 4]
app.save_config(mine, only=("geometry", "dock_rect"))
disk = read_json(app.CONFIG_PATH)
check(disk["device_id"] == theirs["device_id"] and disk["lang"] == "hant",
      "only=：翻译窗口存自己的键时，不会把启动器刚换的设备编号盖回旧的")
check(disk["geometry"] == "480x300+1+2" and disk["dock_rect"] == [True, 1, 2, 3, 4], "only=：点名的键写进去了")
check(mine["device_id"] == first["device_id"], "only=：不改调用方手里那份配置")
check("geometry" not in read_json(BAK) or read_json(BAK)["geometry"] != "480x300+1+2", ".bak 是覆盖之前的那一版")
del mine["geometry"]
app.save_config(mine, only=("geometry",))
check("geometry" not in read_json(app.CONFIG_PATH), "only=：点名的键在手里这份没有，就从盘上去掉")
app.save_config(mine)
check(read_json(app.CONFIG_PATH)["device_id"] == first["device_id"] and "lang" not in read_json(app.CONFIG_PATH),
      "不带 only：整份写回，和以前一样（启动器在用）")

app.save_config(theirs)                          # 现在：主文件 = theirs，.bak = mine
write_text(app.CONFIG_PATH, '{"device_id": "d_')            # 写到一半的坏文件
got = app.load_config()
check(got["device_id"] == mine["device_id"], "主文件坏了：用 .bak 里的")
got["geometry"] = "1x1+0+0"
app.save_config(got, only=("geometry",))
check(read_json(BAK)["device_id"] == mine["device_id"], "坏文件不会顶掉好的备份")
check(read_json(app.CONFIG_PATH)["device_id"] == mine["device_id"] and read_json(app.CONFIG_PATH)["geometry"] == "1x1+0+0",
      "主文件坏着的时候用 only= 保存：以 .bak 为底，保存后主文件恢复正常")
write_text(app.CONFIG_PATH, "not json")
write_text(BAK, "[1, 2]")                                    # 是 JSON 但不是配置
got = app.load_config()
check(got["device_id"].startswith("d_") and got["device_id"] not in (mine["device_id"], theirs["device_id"])
      and got["endpoint"] == app.DEFAULTS["endpoint"], "主文件和备份都读不了：按默认值启动，不崩")
check(os.path.exists(app.CONFIG_PATH + ".broken") and read_json(app.CONFIG_PATH)["device_id"] == got["device_id"],
      "读不了的坏文件挪到 .broken 留着，新配置已存盘")
write_text(app.CONFIG_PATH, '{"own_model": "x", "token": "t"}')
check(app.load_config()["own_model"] == app.DEFAULTS["own_model"], "own_model 不是对象：按默认值，不崩")
os.remove(app.CONFIG_PATH)
os.remove(BAK)
app.save_config({"token": "t", "geometry": "9x9+0+0"}, only=("geometry",))
check(read_json(app.CONFIG_PATH) == {"token": "t", "geometry": "9x9+0+0"}, "only=：盘上什么都没有时整份写，不会只剩那几个键")

# ---------------------------------------------------------------------------
# 分发线程 + 翻译线程：显示顺序、前文顺序、积压保护
# ---------------------------------------------------------------------------
import queue
import threading

check(not app.backlog_skip(12, 8.0) and app.backlog_skip(13, 0) and app.backlog_skip(1, 8.1) and not app.backlog_skip(1, 0),
      "积压判断：等翻的超过 12 条、或这条等了超过 8 秒，就不翻")


class FakeRelay:
    def __init__(self):
        self.calls = []

    def translate(self, text, direction, context=None):
        self.calls.append((text, direction, context))
        return "译:" + text, None


def bare_overlay():
    """不开窗口的 Overlay：只装上分发 / 翻译线程用到的那几样。"""
    o = app.Overlay.__new__(app.Overlay)
    o.relay, o.recent = FakeRelay(), app.RecentChat()
    o.chats, o.ui = queue.Queue(), queue.Queue()
    o.chat_waiting, o.chat_lock, o.q_seq = 0, threading.Lock(), 0
    return o


def drain(o, count):
    return [o.ui.get(timeout=5) for _ in range(count)]


o = bare_overlay()
o._dispatch(b"P\tBob\x1fff0000\twho has the key")
o._dispatch(b"P\tAmy\t\xe6\x88\x91\xe6\x9c\x89")              # 「我有」：中文，不翻
o._dispatch(b"P\tBob\tDBM: pull in 5")                       # 插件播报：不显示
o._dispatch(b"P\tBob\tok go")
o._dispatch(b"W\t1,10,20,300,200\t")
o._dispatch(b"~\t3\t1")
o._dispatch(b"broken frame")
check([o.ui.get_nowait() for _ in range(2)] == [("dock", "1,10,20,300,200"), ("lost", 3, True)] and o.ui.empty(),
      "分发线程不等翻译：翻译页位置、漏读记号马上交给界面")
check(o.chat_waiting == 2 and o.chats.qsize() == 3, "收到的聊天都进翻译队列（不翻的也进，保持顺序）；插件播报不进")
threading.Thread(target=o._chat_loop, daemon=True).start()
rows = drain(o, 3)
check([r[3] for r in rows] == ["who has the key", "我有", "ok go"] and [r[4] for r in rows] == ["译:who has the key", None, "译:ok go"],
      "翻译页里按到达顺序显示；中文原话不翻")
check([c[2] for c in o.relay.calls] == [None, ["Bob: who has the key", "Amy: 我有"]],
      "前文按到达顺序：先取这一句之前的，再把这一句记进去（不翻的那句也算前文）")

o = bare_overlay()
for i in range(20):
    o._dispatch(b"S\tBob\tline number %d" % i)
threading.Thread(target=o._chat_loop, daemon=True).start()
rows = drain(o, 20)
check([r[3] for r in rows] == ["line number %d" % i for i in range(20)], "积压时顺序不变")
check([r[4] is None for r in rows] == [True] * 8 + [False] * 12 and all(r[5] is None for r in rows),
      "积压 20 条：前 8 条只显示原文（不报错），剩下 12 条照常翻")
o.chat_waiting = 1
o.chats.put((app.time.monotonic() - 9, "S", "Bob", "old line", True, None, None))
check(drain(o, 1)[0][3:6] == ("old line", None, None) and o.chat_waiting == 0, "等了超过 8 秒的那条：只显示原文")

# ---------------------------------------------------------------------------
# Ctrl+T：序号、太慢只复制
# ---------------------------------------------------------------------------
o = bare_overlay()
o._dispatch(b"Q\t\thello {1}")
o._dispatch(b"Q\t\tsecond one")
sent = sorted(drain(o, 2), key=lambda r: r[3])
check([r[3] for r in sent] == [1, 2] and o.q_seq == 2 and sent[0][1] == "hello {1}", "每次 Ctrl+T 一个递增序号，随译文带回界面")
check(app.outgoing_action(1, 2, 0.5, True) == "drop" and app.outgoing_action(1, 2, 0.5, False) == "drop",
      "不是最新一次 Ctrl+T 的结果：丢掉（不复制、不粘贴、也不报错）")
check(app.outgoing_action(2, 2, 0.5, True) == "paste" and app.outgoing_action(2, 2, 6.0, True) == "paste", "最新的、6 秒内回来：粘贴")
check(app.outgoing_action(2, 2, 6.1, True) == "copy", "超过 6 秒才回来：只复制")
check(app.outgoing_action(2, 2, 0.5, False) == "fail", "最新的一次没翻出来：提示")

# ---------------------------------------------------------------------------
# 漏读提醒：只在游戏一直在前台却连着漏读时说一次
# ---------------------------------------------------------------------------
w = app.LostWatch()
check([w.feed(True, t) for t in (0, 10, 20)] == [False, False, True], "连续 3 次在前台漏读：提醒")
check(not any(w.feed(True, t) for t in range(30, 600, 10)), "10 分钟内不再提醒")
check(w.feed(True, 630), "一直在漏：过了 10 分钟再提醒一次")
w = app.LostWatch()
check(not any(w.feed(front, t) for t, front in ((0, True), (10, True), (20, False), (30, True), (40, True))),
      "中间有一次是切出去漏的：重新数")
w = app.LostWatch()
check(not any(w.feed(True, t) for t in (0, 10, 200, 210)) and w.feed(True, 220), "隔了 2 分钟以上不算连续")

# ---------------------------------------------------------------------------
# 找游戏窗口、聊天原话、自带模型
# ---------------------------------------------------------------------------
check(app.is_game_window("魔獸世界", "GxWindowClass") and app.is_game_window("World of Warcraft", "GxWindowClass")
      and app.is_game_window("魔兽世界", "Whatever"), "窗口标题：简体、繁体、英文都认")
check(not app.is_game_window("World of Warcraft", "CabinetWClass") and not app.is_game_window("魔兽世界", "ExploreWClass")
      and not app.is_game_window("World of Warcraft - Notepad", "Notepad"), "资源管理器里同名的文件夹窗口不算")
check(app.chat_glyph("WTS [奥金斧] 50g") == "WTS [奥金斧] 50g" and app.chat_glyph("") == "", "简体模式：聊天原话原样")

import io
import urllib.error

check(app.own_error_detail(b'{"error": {"message": "Unsupported parameter: temperature", "type": "x"}}')
      == "Unsupported parameter: temperature", "自带模型报错：取出 error.message")
detail = app.own_error_detail('{"error": "bad key sk-abcdef1234567890 for\n MYSECRETKEY, header Bearer zzz999"}', "MYSECRETKEY")
check("MYSECRETKEY" not in detail and "sk-abcdef" not in detail and "zzz999" not in detail and "\n" not in detail,
      "自带模型报错：密钥不会出现在提示里")
check(len(app.own_error_detail("x" * 500)) == 80 and app.own_error_detail(b"<html>502</html>") == "", "报错说明最多 80 个字符；HTML 报错页不附")


class FakeOwn(app.OwnModel):
    """假装是只收 max_completion_tokens 的模型。"""
    posts, reply = [], "好的"

    def _post(self, body, timeout):
        FakeOwn.posts.append(body)
        if "temperature" in body or "max_tokens" in body:
            raise urllib.error.HTTPError("http://x", 400, "Bad Request", {},
                                         io.BytesIO(b'{"error": {"message": "temperature is not supported"}}'))
        return {"choices": [{"message": {"content": FakeOwn.reply}}]}


own_cfg = {"own_model": {"enabled": True, "base_url": "http://own.test/v1/", "api_key": "k", "model": "m1"}}
app._own_alt_style.clear()
check(FakeOwn(own_cfg).translate("hi", "en2zh") == ("好的", None) and len(FakeOwn.posts) == 2
      and FakeOwn.posts[1]["max_completion_tokens"] >= 400 and "temperature" not in FakeOwn.posts[1],
      "自带模型 400：去掉 temperature、改用 max_completion_tokens 重试")
check(FakeOwn(own_cfg).translate("hi", "en2zh") == ("好的", None) and len(FakeOwn.posts) == 3,
      "重试成功后记住这个地址 + 模型的写法：新建的实例也直接用，不再每句先失败一次")
check(FakeOwn.posts[0]["max_tokens"] >= 400, "长度上限至少 400（带思考的模型需要）")
for empty in (None, "", "   "):
    FakeOwn.reply = empty
    check(FakeOwn(own_cfg).translate("hi", "en2zh") == (None, "模型没返回内容，换一个模型试试"), "自带模型返回空内容（%r）：单独提示" % (empty,))


class DownOwn(app.OwnModel):
    def _post(self, body, timeout):
        raise urllib.error.HTTPError("http://x", self.code, "x", {}, io.BytesIO(b'{"error": {"message": "model m2 overloaded, key k-secret-123"}}'))


own2 = {"own_model": dict(own_cfg["own_model"], model="m2", api_key="k-secret-123")}
DownOwn.code = 500
check(DownOwn(own2).translate("hi", "en2zh") == (None, "自带模型出错 500（model m2 overloaded, key ***）"), "其他 HTTP 错误：附上服务返回的说明，密钥打码")
DownOwn.code = 401
check(DownOwn(own2).translate("hi", "en2zh") == (None, "自带模型：密钥不对"), "密钥不对：不附响应内容")
DownOwn.code = 400
check(DownOwn(own2).translate("hi", "en2zh")[1].startswith("自带模型出错 400（") and ("http://own.test/v1", "m2") not in app._own_alt_style,
      "换了写法还是 400：报出来，不记成「要用另一种写法」")

# 自己说的话：插件在名字后面带记号，程序认出来以后不翻译，并和 Ctrl+T 的中文原文配对
check(app.split_me("Senhu\x1f\x1e") == ("Senhu", True), "自己的话（没有职业色）：认出来，名字去掉记号")
check(app.split_me("Senhu\x1fc79c6e\x1e") == ("Senhu\x1fc79c6e", True), "自己的话（带职业色）：认出来，职业色留着")
check(app.split_me("Mate\x1fc79c6e") == ("Mate\x1fc79c6e", False) and app.split_me("Mate") == ("Mate", False), "别人的话：不是自己")
check(app.sent_key("WTS {1} 50g, pst") == app.sent_key("wts [奥金斧] 50g,  pst"), "配对不看大小写、空白和物品链接")
check(app.sent_key("wait, oom") != app.sent_key("wait, oom now"), "改过内容的不算同一句")
check(app.RecentChat._name("Senhu\x1fc79c6e\x1e") == "Senhu", "带记号的名字进前文时也是干净的")
print("全部通过：%d 项" % n)
