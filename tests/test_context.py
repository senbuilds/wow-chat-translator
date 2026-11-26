"""前文（聊天上下文）和物品链接的客户端逻辑。不连网。运行：python tests/test_context.py"""
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
print("全部通过：%d 项" % n)
