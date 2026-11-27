"""在 Lua 5.1 里用假的魔兽接口加载插件，模拟聊天事件，再用小程序的解码器读色块，核对两边一致。

运行：python tests/test_addon.py   （需要 pip install lupa）
"""
import locale
import os
import sys

import lupa.lua51 as lua51

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
import codec  # noqa: E402

STUBS = r"""
frames, printed, now = {}, {}, 0
local function widget()
    local w = { scripts = {}, events = {}, shown = true }
    local mt = {}
    mt.__index = function(t, k)
        return function() end          -- 没单独实现的方法都是空操作
    end
    setmetatable(w, mt)
    w.SetScript = function(self, name, fn) self.scripts[name] = fn end
    w.RegisterEvent = function(self, e) self.events[e] = true end
    w.Show = function(self) self.shown = true end
    w.Hide = function(self) self.shown = false end
    w.SetColorTexture = function(self, r, g, b) self.color = { r, g, b } end
    w.SetPoint = function(self, _, _, _, x, y) self.x, self.y = x, y end
    w.SetScale = function(self, s) self.scale = s end
    w.IsShown = function(self) return self.shown end
    w.IsVisible = function(self) return self.shown end
    w.GetLeft = function(self) return rawget(self, "l") end
    w.GetTop = function(self) return rawget(self, "t") end
    w.GetWidth = function(self) return rawget(self, "w") end
    w.GetHeight = function(self) return rawget(self, "h") end
    w.GetEffectiveScale = function(self) return rawget(self, "es") or 1 end
    w.GetRect = function(self)
        local l, t, wd, ht = rawget(self, "l"), rawget(self, "t"), rawget(self, "w"), rawget(self, "h")
        if not (l and t and wd and ht) then return nil end
        return l, t - ht, wd, ht
    end
    w.CreateFontString = function(self) return widget() end
    w.CreateTexture = function(self, _, layer)
        local t = widget(); t.layer = layer
        local list = rawget(self, "textures") or {}
        rawset(self, "textures", list)
        list[#list + 1] = t
        return t
    end
    return w
end
function CreateFrame(kind, name)
    local f = widget(); f.name = name
    frames[#frames + 1] = f
    return f
end
WorldFrame = widget()
UIParent = widget()
ChatFrame1 = widget()
IsControlKeyDown = function() return ctrl end
IsAltKeyDown = function() return false end
ChatFrame1EditBox = widget()
ChatFrame1EditBox.hooks = {}
ChatFrame1EditBox.text = ""
ChatFrame1EditBox.chatBridgeHooked = false   -- 假框体的未知字段默认是函数，这里显式置假
ChatFrame1EditBox.HookScript = function(self, name, fn) self.hooks[name] = fn end
ChatFrame1EditBox.GetText = function(self) return self.text end
ChatFrame1EditBox.SetText = function(self, t) self.text = t end
function boxtext() return ChatFrame1EditBox.text end
function typebox(t) ChatFrame1EditBox.text = t; ChatFrame1EditBox.hooks.OnTextChanged(ChatFrame1EditBox, true) end
function presskey(k, c) ctrl = c; ChatFrame1EditBox.hooks.OnKeyDown(ChatFrame1EditBox, k); ctrl = false end
function GetPhysicalScreenSize() return 1920, 1080 end
function GetTime() return now end
function UnitName() return "Senhu" end
function Ambiguate(n) return (n:gsub("%-.*", "")) end
function print(...) printed[#printed + 1] = table.concat({ ... }, " ") end
SlashCmdList = {}
secrets = {}
function issecretvalue(v) return secrets[v] == true end

function fire(event, ...)
    for _, f in ipairs(frames) do
        if f.scripts.OnEvent and (f.events[event]) then f.scripts.OnEvent(f, event, ...) end
    end
end
function tick(dt)
    now = now + dt
    for _, f in ipairs(frames) do
        if f.scripts.OnUpdate then f.scripts.OnUpdate(f, dt) end
    end
end
function strip_shown() return frames[1].shown end
function strip_scale() return frames[1].scale end
function strip_count() return #frames[1].textures end
function snapshot()
    local out = {}
    for _, t in ipairs(frames[1].textures) do
        if t.layer == "ARTWORK" then
            out[#out + 1] = t.x; out[#out + 1] = t.y
            out[#out + 1] = t.color[1]; out[#out + 1] = t.color[2]; out[#out + 1] = t.color[3]
        end
    end
    return out
end
"""


def read_strip(lua):
    """把假框体上的色块画成像素函数，交给真正的解码器。"""
    if not lua.eval("strip_shown()"):
        return None
    flat = list(lua.eval("snapshot()").values())
    grid = {}
    for i in range(0, len(flat), 5):
        x, y, r, g, b = flat[i:i + 5]
        grid[(int(x) // codec.CELL, int(-y) // codec.CELL)] = tuple(int(round(c * 255)) for c in (r, g, b))

    def pixel(x, y):
        return grid[(x // codec.CELL, y // codec.CELL)]

    return codec.decode(pixel)


def main():
    # Python 启动时会把字符分类设成系统区域（英文 Windows 是 cp1252），Lua 的 %s、%c 会跟着变，
    # 把中文 UTF-8 里的 0x85、0x9D 之类当成空白/控制字符。游戏里的 Lua 用的是 C 区域，这里对齐。
    locale.setlocale(locale.LC_CTYPE, "C")
    lua = lua51.LuaRuntime(unpack_returned_tuples=True, encoding=None)
    lua.execute(STUBS.encode())
    with open(os.path.join(ROOT, "addon", "ChatBridge", "ChatBridge.lua"), "rb") as f:
        lua.execute(f.read())
    fire, tick = lua.eval("fire"), lua.eval("tick")

    fire(b"ADDON_LOADED", b"ChatBridge")
    fire(b"PLAYER_ENTERING_WORLD")
    assert abs(lua.eval("strip_scale()") - 768 / 1080) < 1e-9, "缩放应让 1 单位 = 1 物理像素"
    assert lua.eval("strip_count()") == codec.COLS * codec.ROWS + 1

    seen = []

    def pump(seconds=1.0):
        t = 0.0
        while t < seconds:
            tick(0.02)
            t += 0.02
            got = read_strip(lua)
            if got and (not seen or seen[-1] != got):
                seen.append(got)

    # 登录后立刻发一次，加载画面结束后隔 1 秒、4 秒再各补发一次（共三轮）
    pump(6.0)
    assert [p for _, p in seen] == [b"@\t" + lua.eval("ChatBridge.VERSION") + b"\tSenhu", b"W\t0\t"] * 3, seen
    fire(b"LOADING_SCREEN_DISABLED")
    pump(6.0)
    assert len(seen) == 10, len(seen)

    # 翻译页：打开后把物理像素位置发给小程序；挪动聊天框会自动再发；关掉发 0
    lua.execute(b"""
        for _, f in ipairs(frames) do
            if f.name == "ChatBridgePanel" then f.l, f.t, f.w, f.h, f.es = 10, 300, 400, 200, 0.8 end
        end""")
    toggle = lua.eval("ChatBridge.TogglePage")
    toggle()
    pump(0.8)
    assert seen[-1][1] == b"W\t1,11,743,450,207,207,18\t", seen[-1]
    lua.execute(b'for _, f in ipairs(frames) do if f.name == "ChatBridgePanel" then f.l = 110 end end')
    pump(1.0)
    assert seen[-1][1] == b"W\t1,124,743,450,207,207,18\t", seen[-1]
    n = len(seen)
    pump(1.5)
    assert len(seen) == n, "位置没变就不该重复发"

    # 游戏窗口（比如专业窗口）盖到翻译页上：发 0 让译文先藏起来；窗口关了自动恢复。不挨着的窗口不影响
    lua.execute(b"TradeSkillFrame = CreateFrame('Frame', 'TradeSkillFrame'); "
                b"TradeSkillFrame.l, TradeSkillFrame.t, TradeSkillFrame.w, TradeSkillFrame.h = 200, 400, 300, 300")
    pump(0.8)
    assert seen[-1][1] == b"W	0	", seen[-1]
    lua.execute(b"TradeSkillFrame:Hide()")
    pump(0.8)
    assert seen[-1][1] == b"W	1,124,743,450,207,207,18	", seen[-1]
    lua.execute(b"CharacterFrame = CreateFrame('Frame', 'CharacterFrame'); "
                b"CharacterFrame.l, CharacterFrame.t, CharacterFrame.w, CharacterFrame.h = 900, 700, 300, 300")
    pump(0.8)
    assert seen[-1][1] == b"W	1,124,743,450,207,207,18	", "不挨着的窗口不该藏译文"
    lua.execute(b"CharacterFrame:Hide()")

    # 中间提示卡（还没收到过聊天时显示）：位置跟在矩形后面发给小程序，让它在同一位置盖上自己的卡
    lua.execute(b"for _, f in ipairs(frames) do if f.name == 'ChatBridgeCard' then "
                b"f.l, f.t, f.w, f.h, f.es = 124, 232, 372, 52, 0.8 end end")
    pump(0.8)
    assert seen[-1][1] == b"W	1,124,743,450,207,207,18,16,77,419,59	", seen[-1]
    lua.execute(b"ChatBridge.sawChat = true; ChatBridge.UpdateCard()")     # 收到聊天后卡收起
    pump(0.8)
    assert seen[-1][1] == b"W	1,124,743,450,207,207,18	", seen[-1]
    n = len(seen)
    toggle()
    pump(0.8)
    assert seen[-1][1] == b"W\t0\t", seen[-1]

    # 「只翻队友」默认开：说话、公会不发，小队和密语照发
    before = len(seen)
    fire(b"CHAT_MSG_SAY", b"city noise", b"Stranger")
    fire(b"CHAT_MSG_GUILD", b"guild chatter", b"Gm")
    fire(b"CHAT_MSG_YELL", b"LOUD", b"Stranger")
    fire(b"CHAT_MSG_PARTY", b"team talk", b"Mate")
    fire(b"CHAT_MSG_WHISPER", b"psst", b"Friend")
    pump(1.0)
    got = [p.decode() for _, p in seen[before:]]
    assert got == ["P\tMate\tteam talk", "H\tFriend\tpsst"], got

    # 按频道订阅：单独勾上「公会」后公会消息才发；右键设置窗口能建出来、能开关
    before = len(seen)
    set_sub = lua.eval("ChatBridge.SetSub")
    set_sub(b"G", True)
    fire(b"CHAT_MSG_GUILD", b"guild now on", b"Gm")
    fire(b"CHAT_MSG_SAY", b"still off", b"Stranger")
    set_sub(b"P", False)
    fire(b"CHAT_MSG_PARTY", b"party now off", b"Mate")
    pump(1.0)
    got = [p.decode() for _, p in seen[before:]]
    assert got == ["G\tGm\tguild now on"], got
    lua.eval("ChatBridge.ToggleSettings")()
    assert lua.eval('(function() for _, f in ipairs(frames) do if f.name == "ChatBridgeSettings" then return f.shown end end end)()') is True
    assert not any(b"\xe6\xb2\xa1\xe5\xbb\xba\xe6\x88\x90" in bytes(p) for p in lua.eval("printed").values()), "设置窗口建失败了"
    lua.eval("ChatBridge.ToggleSettings")()
    # 第一次装插件：聊天框里说一次要装电脑程序和下载地址；再进世界不重复说
    def site_lines():
        return sum(b"wow.husen.ca" in bytes(p) for p in lua.eval("printed").values())
    assert site_lines() == 1, site_lines()
    assert lua.eval("ChatBridgeDB.welcomed") is True      # 记下来了，下次进世界不再说
    lua.eval("ChatBridge.ApplyPreset")(b"team")
    assert lua.eval("ChatBridgeDB.subs.P") is True and lua.eval("ChatBridgeDB.subs.G") is False

    # 后面的用例测全部频道（公共频道先关着）
    lua.eval("ChatBridge.ApplyPreset")(b"all")
    set_sub(b"C", False)

    cases = [
        (b"CHAT_MSG_SAY", "hi", "Allin-Ethereum", "S\tAllin\thi"),
        (b"CHAT_MSG_PARTY", "lfm 1 healer |cffffffff|Hitem:1234::::|h[Glowing Staff]|h|r pst", "Bob",
         "P\tBob\tlfm 1 healer [Glowing Staff] pst"),
        (b"CHAT_MSG_PARTY_LEADER", "治疗没蓝了，等一下再拉 {rt8}", "队长", "P\t队长\t治疗没蓝了，等一下再拉 {rt8}"),
        (b"CHAT_MSG_RAID_WARNING", "x" * 600, "Rl", "X\tRl\t" + "x" * (codec.MAX_PAYLOAD - 5)),
        (b"CHAT_MSG_WHISPER", "  a || b  ", "Zed-Area52", "H\tZed\ta | b"),
    ]
    for event, text, sender, expect in cases:
        before = len(seen)
        fire(event, text.encode(), sender.encode())
        pump(0.6)
        assert len(seen) == before + 1, (event, seen[before:])
        assert seen[-1][1] == expect.encode(), (seen[-1][1].decode(errors="replace"), expect)

    # 公共频道（默认关）、空文本都不该发；自己说的话要发，名字后面带「这是我」的记号（\x1f 职业色 \x1e）
    before = len(seen)
    fire(b"CHAT_MSG_SAY", b"my own line", b"Senhu-Ethereum")
    fire(b"CHAT_MSG_CHANNEL", b"WTS stuff", b"Trader")
    fire(b"CHAT_MSG_SAY", b"|T123:0|t", b"Icon")
    pump(0.6)
    assert [p for _, p in seen[before:]] == [b"S\tSenhu\x1f\x1e\tmy own line"], seen[before:]
    before = len(seen)

    # 秘密值：只发「读不到」的通知，10 秒内只发一次
    lua.execute(b'secrets["SECRETTEXT"] = true')
    fire(b"CHAT_MSG_INSTANCE_CHAT", b"SECRETTEXT", b"Someone")
    fire(b"CHAT_MSG_INSTANCE_CHAT", b"SECRETTEXT", b"Someone")
    pump(0.6)
    assert len(seen) == before + 1 and seen[-1][1] == b"!\tI\t", seen[before:]

    # 连发 5 条，全部按顺序收到，序号连续
    before = len(seen)
    for i in range(5):
        fire(b"CHAT_MSG_GUILD", ("burst %d" % i).encode(), b"Gm")
    pump(2.0)
    got = [p.decode() for _, p in seen[before:]]
    assert got == ["G\tGm\tburst %d" % i for i in range(5)], got
    seqs = [s for s, _ in seen[before:]]
    assert seqs == list(range(seqs[0], seqs[0] + 5)), seqs

    # 队列发完后色块要收起来
    pump(0.6)
    assert not lua.eval("strip_shown()")

    # 斜杠命令
    slash = lua.eval("SlashCmdList.CHATBRIDGE")
    before = len(seen)
    slash(b"test")
    slash(b"channel")
    fire(b"CHAT_MSG_CHANNEL", b"WTS stuff", b"Trader")
    slash(b"")
    pump(1.0)
    got = [p.decode() for _, p in seen[before:]]
    assert got[0].startswith("T\tChatBridge\t") and got[1] == "C\tTrader\tWTS stuff", got

    # 发消息：聊天框里打中文，Ctrl+T 或末尾两个分号触发
    typebox, presskey, boxtext = lua.eval("typebox"), lua.eval("presskey"), lua.eval("boxtext")
    before = len(seen)
    typebox("治疗没蓝了，等一下再拉".encode())
    presskey(b"T", False)          # 没按 Ctrl：不触发
    assert boxtext() != b""
    presskey(b"T", True)
    assert boxtext() == b""
    typebox("谢谢大家;;".encode())
    assert boxtext() == b""
    typebox("打得好；；".encode())
    typebox(b"plain typing; no trigger")
    assert boxtext() == b"plain typing; no trigger"
    pump(1.5)
    got = [p.decode() for _, p in seen[before:]]
    assert got == ["Q\t\t治疗没蓝了，等一下再拉", "Q\t\t谢谢大家", "Q\t\t打得好"], got

    # 用量页：点「用量」切过去（翻译页自动打开，内容区大小不变），再点切回来
    before = len(seen)
    lua.eval("ChatBridge.RequestUsage")()
    pump(1.5)
    got = [p for _, p in seen[before:]]
    assert b"U\t1\t" in got and got[-1] == b"W\t1,124,743,450,207,207,18\t", got
    # 游戏里不能有兑换码输入框（暴雪插件政策：游戏内不出现付费相关的东西）
    assert lua.eval("ChatBridge.Redeem") is None
    assert lua.eval('(function() for _, f in ipairs(frames) do if f.name == "ChatBridgeRedeemBox" then return true end end return false end)()') is False
    before = len(seen)
    lua.eval("ChatBridge.RequestUsage")()
    pump(1.5)
    got = [p for _, p in seen[before:]]
    assert b"U\t0\t" in got and got[-1] == b"W\t1,124,743,450,207,207,18\t", got
    lua.eval("ChatBridge.ResetLayout")()
    assert lua.eval("ChatBridgeDB.panelBox") is None

    # 职业颜色：带 GUID 的消息，名字后面带 \x1f + 6 位颜色；拿不到职业就不带
    lua.execute(b"""
        RAID_CLASS_COLORS = { PALADIN = { r = 0.96, g = 0.55, b = 0.73 } }
        function GetPlayerInfoByGUID(g) if g == "Player-1-PAL" then return "Paladin", "PALADIN" end end
    """)
    before = len(seen)
    fire(b"CHAT_MSG_PARTY", b"heal pls", b"Holy-Server", b"", b"", b"", b"", 0, 0, b"", 0, 1, b"Player-1-PAL")
    fire(b"CHAT_MSG_PARTY", b"no guid here", b"Mystery")
    pump(1.0)
    got = [p for _, p in seen[before:] if not p.startswith(b"W\t")]
    assert got == [b"P\tHoly\x1ff58cba\theal pls", b"P\tMystery\tno guid here"], got

    # 滚轮：还没发出去的滚动合并成一条
    before = len(seen)
    for d in (1, 1, 1, -1):
        lua.eval("ChatBridge.EnqueueScroll")(d)
    pump(1.0)
    assert [p for _, p in seen[before:]] == [b"V\t2\t"], seen[before:]

    # 小程序晚于游戏启动：30 秒没发过位置，下一条聊天前顺手补发一次位置
    lua.execute(b"now = now + 40")
    before = len(seen)
    fire(b"CHAT_MSG_PARTY", b"late app", b"Mate")
    pump(1.0)
    got = [p for _, p in seen[before:]]
    assert got[0].startswith(b"W\t") and got[-1] == b"P\tMate\tlate app", got
    before = len(seen)
    fire(b"CHAT_MSG_PARTY", b"again", b"Mate")
    pump(1.0)
    assert [p for _, p in seen[before:]] == [b"P\tMate\tagain"], "刚补发过就不该再发"

    # 物品链接：用编号查本机客户端的名字（中文客户端就是中文名），换进方括号
    lua.execute("""
        names, requested, timers = { [12784] = "奥金斧" }, {}, {}
        C_Item = { GetItemNameByID = function(id) return names[id] end,
                   RequestLoadItemDataByID = function(id) requested[#requested + 1] = id end }
        C_Timer = { After = function(_, f) timers[#timers + 1] = f end }
        function runtimers() local t = timers; timers = {}; for _, f in ipairs(t) do f() end end
    """.encode())
    link = "|cffa335ee|Hitem:%d::::::::60:::::|h[%s]|h|r"
    before = len(seen)
    fire(b"CHAT_MSG_PARTY", ("WTS " + link % (12784, "Arcanite Reaper") + " 50g").encode(), b"Mate")
    pump(1.0)
    assert [p.decode() for _, p in seen[before:]] == ["P\tMate\tWTS [奥金斧] 50g"], seen[before:]
    # 本机还没缓存的物品：先让客户端去取，等一下再发；取到了用中文名
    before = len(seen)
    fire(b"CHAT_MSG_PARTY", ("need " + link % (999, "Felstriker") + " ?").encode(), b"Mate")
    pump(1.0)
    assert len(seen) == before and list(lua.eval("requested").values()) == [999], "没缓存的物品应先等一下"
    lua.execute("names[999] = '魔王之刃'".encode())
    lua.eval("runtimers")()
    pump(1.0)
    assert [p.decode() for _, p in seen[before:]] == ["P\tMate\tneed [魔王之刃] ?"], seen[before:]
    # 一直取不到：照原名发，不卡住
    before = len(seen)
    fire(b"CHAT_MSG_PARTY", ("lol " + link % (555, "Mystery Thing")).encode(), b"Mate")
    lua.eval("runtimers")()
    pump(1.0)
    assert [p.decode() for _, p in seen[before:]] == ["P\tMate\tlol [Mystery Thing]"], seen[before:]

    # 发话时插了物品链接：送去翻的是 {1} 占位符；译文贴回聊天框后换回真链接
    mine = link % (12784, "奥金斧")
    before = len(seen)
    lua.eval("typebox")(("出 " + mine + " 50金;;").encode())
    pump(1.0)
    assert [p.decode() for _, p in seen[before:]] == ["Q\t\t出 {1} 50金"], seen[before:]
    lua.eval("typebox")(b"WTS {1} 50g")
    assert lua.eval("boxtext()").decode() == "WTS " + mine + " 50g", lua.eval("boxtext()")
    lua.eval("typebox")(b"plain {1} text")
    assert lua.eval("boxtext()") == b"plain {1} text", "换过一次就不再换"
    lua.eval("typebox")(b"")

    # ------------------------------------------------------------------
    # 2.10 的修改
    # ------------------------------------------------------------------
    def out(before):
        """before 之后收到的消息；翻译页位置（W）可能随时插进来，和这里要核对的顺序无关，滤掉"""
        return [p.decode() for _, p in seen[before:] if not p.startswith(b"W\t")]

    # 版本号：插件和 toc 一致
    with open(os.path.join(ROOT, "addon", "ChatBridge", "ChatBridge.toc"), encoding="utf-8") as f:
        assert "## Version: 2.11\n" in f.read()
    assert lua.eval("ChatBridge.VERSION") == b"2.11"

    # 1) 发话时的链接占位符：新引擎的 |cnIQ4: 颜色写法和老的 |cff…… 都认，编号按出现顺序
    newstyle = "|cnIQ4:|Hitem:19019::::::::70:::::|h[雷霆之怒]|h|r"
    before = len(seen)
    typebox(("出 " + newstyle + " 和 " + mine + ";;").encode())
    pump(0.6)
    assert out(before) == ["Q\t\t出 {1} 和 {2}"], seen[before:]
    typebox(b"WTS {1} and {2}")
    assert boxtext().decode() == "WTS " + newstyle + " and " + mine, boxtext()
    assert lua.eval("ChatBridge.outLinks") is None, "都换回去了，表应该清空"
    # 没跟着链接的 |cn…: 颜色前缀也要剥掉，不能带着转义送去翻
    before = len(seen)
    typebox("|cnIQ2:绿字|r 你好;;".encode())
    pump(0.6)
    assert out(before) == ["Q\t\t绿字 你好"], seen[before:]

    # 8) 连着两次 Ctrl+T：第二句不带链接，不能清掉第一句还没用掉的链接
    before = len(seen)
    typebox(("出 " + mine + ";;").encode())
    typebox("谢谢;;".encode())
    pump(1.0)
    assert out(before) == ["Q\t\t出 {1}", "Q\t\t谢谢"], seen[before:]
    typebox(b"WTS {1}")
    assert boxtext().decode() == "WTS " + mine, boxtext()
    # 两句都带链接：编号接着排（{1}、{2}），哪句译文先贴回来都各自换对；全换完后编号回到 {1}
    before = len(seen)
    typebox(("出 " + mine + ";;").encode())
    typebox(("收 " + newstyle + ";;").encode())
    pump(1.0)
    assert out(before) == ["Q\t\t出 {1}", "Q\t\t收 {2}"], seen[before:]
    typebox(b"WTB {2}")                                   # 第二句的译文先回来
    assert boxtext().decode() == "WTB " + newstyle, boxtext()
    typebox(b"WTS {1} {1}")                               # 同一个占位符出现两次也都换
    assert boxtext().decode() == "WTS " + mine + " " + mine, boxtext()
    before = len(seen)
    typebox(("再出 " + mine + ";;").encode())
    pump(0.6)
    assert out(before) == ["Q\t\t再出 {1}"], seen[before:]
    lua.execute(b"now = now + 61")                        # 60 秒没用：作废，不再替换
    typebox(b"late {1}")
    assert boxtext() == b"late {1}" and lua.eval("ChatBridge.outLinks") is None
    typebox(b"")

    # 2) 队列优先级：控制类排在所有没发出的聊天前面（控制类之间先后不变）；满了只丢最老的聊天
    enq, scroll = lua.eval("ChatBridge.Enqueue"), lua.eval("ChatBridge.EnqueueScroll")
    pump(0.6)
    before = len(seen)
    for i in range(35):                                   # 上限 30：m0~m4 被挤掉
        enq(("P\tMate\tm%d" % i).encode())
    enq("Q\t\t我要发的话".encode())                        # 控制类各挤掉一条最老的聊天（m5、m6、m7）
    enq(b"A\t\t")
    scroll(1)
    scroll(2)                                             # 队尾是聊天也要能和上一条滚动合并
    pump(9.0)
    assert out(before) == ["Q\t\t我要发的话", "A\t\t", "V\t3\t"] + ["P\tMate\tm%d" % i for i in range(8, 35)], out(before)
    # 排着的全是控制类：一条都不丢（哪怕超过上限），这时新来的聊天让路
    before = len(seen)
    for i in range(32):
        enq(("Q\t\tn%d" % i).encode())
    enq(b"P\tMate\tno room")
    pump(9.0)
    assert out(before) == ["Q\t\tn%d" % i for i in range(32)], out(before)
    # 真实路径：聊天刷屏后按 Ctrl+T，这句话下一个就发
    before = len(seen)
    for i in range(6):
        fire(b"CHAT_MSG_PARTY", ("spam %d" % i).encode(), b"Mate")
    typebox("等我一下;;".encode())
    pump(2.5)
    assert out(before) == ["Q\t\t等我一下"] + ["P\tMate\tspam %d" % i for i in range(6)], out(before)

    # 3) 带随机后缀的物品：先拿整串链接查（带后缀的本地名），查不到再退回按编号查
    lua.execute("""
        fullnames, infomode, namecalls, infocalls = {}, "ok", 0, 0
        local byId = C_Item.GetItemNameByID
        C_Item.GetItemNameByID = function(id) namecalls = namecalls + 1; return byId(id) end
        function GetItemInfo(arg)
            infocalls = infocalls + 1
            if infomode == "error" then error("boom") end
            if infomode == "secret" then return "SECRETNAME" end
            if type(arg) == "string" then return fullnames[arg] end
        end
        secrets["SECRETNAME"] = true
        names[7460] = "勇士护腿"
        fullnames["item:7460:0:0:0:0:0:584:0"] = "灵猴之勇士护腿"
    """.encode())
    suffixed = "|cff1eff00|Hitem:7460:0:0:0:0:0:584:0|h[Champion's Leggings of the Monkey]|h|r"
    for mode, expect in (("ok", "灵猴之勇士护腿"), ("secret", "勇士护腿"), ("error", "勇士护腿")):
        lua.execute(('infomode = "%s"' % mode).encode())
        before = len(seen)
        fire(b"CHAT_MSG_PARTY", ("WTS " + suffixed).encode(), b"Mate")
        pump(0.6)
        assert out(before) == ["P\tMate\tWTS [%s]" % expect], (mode, out(before))
    lua.execute(b'infomode = "ok"')

    # 4) 一条消息只查一遍名字（以前 onChat 查一遍、Clean 又查一遍）
    lua.execute(b"namecalls, infocalls = 0, 0")
    before = len(seen)
    fire(b"CHAT_MSG_PARTY", ("WTS " + link % (12784, "Arcanite Reaper")).encode(), b"Mate")
    pump(0.6)
    assert out(before) == ["P\tMate\tWTS [奥金斧]"], out(before)
    assert (lua.eval("infocalls"), lua.eval("namecalls")) == (1, 1), (lua.eval("infocalls"), lua.eval("namecalls"))
    assert lua.eval("ChatBridge.Clean")(("x " + suffixed).encode()).decode() == "x [灵猴之勇士护腿]"   # Clean 仍是「查名字 + 剥转义」

    # 5) 战网密语：发言人是受保护名字串，用第 13 个参数 bnSenderID 认人
    def bn(text, bn_id, sender=b"|Kp12|k"):
        fire(b"CHAT_MSG_BN_WHISPER", text, sender, b"", b"", b"", b"", 0, 0, b"", 0, 1, b"", bn_id)
    before = len(seen)
    bn(b"hey", 12)                                        # 没有 C_BattleNet：用能区分人的占位名
    bn(b"yo", 13)
    pump(1.0)
    assert out(before) == ["B\t战网好友12\they", "B\t战网好友13\tyo"], out(before)
    lua.execute("""
        bninfo = {
            [21] = { battleTag = "Bob#1234", accountName = "|Kq21|k" },
            [22] = { accountName = "Alice Real" },
            [23] = { accountName = "|Kq23|k" },                       -- 名字也是受保护串：剥完是空的
            [24] = { battleTag = "SECRETNAME", accountName = "SECRETNAME" },
        }
        C_BattleNet = { GetAccountInfoByID = function(id)
            if id == 25 then error("boom") end
            return bninfo[id]
        end }
    """.encode())
    before = len(seen)
    for i in range(21, 27):
        bn(b"m", i)
    pump(2.0)
    assert out(before) == ["B\t%s\tm" % n for n in ("Bob", "Alice Real", "战网好友23", "战网好友24", "战网好友25", "战网好友26")], out(before)
    # 编号本身是秘密值 / 没带编号：退回老办法（名字串剥掉后是「?」），不报错
    lua.execute(b"secrets[99] = true")
    before = len(seen)
    bn(b"m", 99)
    fire(b"CHAT_MSG_BN_WHISPER", b"n", b"|Kp12|k")
    pump(1.0)
    assert out(before) == ["B\t?\tm", "B\t?\tn"], out(before)
    # 重试路径（物品没缓存，0.4 秒后再走一遍）也带着编号
    before = len(seen)
    bn(("look " + link % (4242, "Uncached Thing")).encode(), 21)
    lua.eval("runtimers")()
    pump(0.6)
    assert out(before) == ["B\tBob\tlook [Uncached Thing]"], out(before)
    # 秘密内容照旧只发「读不到」
    lua.execute(b"now = now + 20")
    before = len(seen)
    bn(b"SECRETTEXT", 21)
    pump(0.6)
    assert out(before) == ["!\tB\t"], out(before)

    # 6) 自己说的话：有 GUID 就比 GUID——跨服同名的别人照翻，自己的话不翻；没 GUID 才比名字
    lua.execute(b'function UnitGUID(unit) if unit == "player" then return "Player-1-ME" end end')

    def say(text, sender, guid=None):
        args = (b"", b"", b"", b"", 0, 0, b"", 0, 1, guid) if guid else ()
        fire(b"CHAT_MSG_SAY", text, sender, *args)
    before = len(seen)
    say(b"same name other realm", b"Senhu-Stormrage", b"Player-2-OTHER")
    say(b"mine by guid", b"Senhu-Ethereum", b"Player-1-ME")
    say(b"mine by name", b"Senhu-Ethereum")
    say(b"hello", b"Other", b"Player-3-X")
    pump(1.6)
    raw = out(before)
    assert raw == ["S\tSenhu\tsame name other realm", "S\tSenhu\x1f\x1e\tmine by guid",
                   "S\tSenhu\x1f\x1e\tmine by name", "S\tOther\thello"], raw   # 同名别人不带记号，自己的两句都带
    lua.execute(b'secrets["Player-1-ME"] = true')         # 自己的 GUID 读出来是秘密值：不拿它比，退回比名字
    before = len(seen)
    say(b"x", b"Senhu-Ethereum", b"Player-2-OTHER")
    say(b"y", b"Other", b"Player-3-X")
    pump(1.0)
    raw = out(before)
    assert raw == ["S\tSenhu\x1f\x1e\tx", "S\tOther\ty"], raw
    lua.execute(b'secrets["Player-1-ME"] = nil')

    # 7) 临时聊天窗口（ChatFrame11 起）也要挂上 Ctrl+T：游戏开临时窗口后再挂一遍
    lua.execute(b"""
        hookcalls, openhooks = 0, {}
        function FCF_OpenTemporaryWindow() end
        function hooksecurefunc(name, fn)
            hookcalls = hookcalls + 1
            assert(name == "FCF_OpenTemporaryWindow")
            local orig = _G[name]
            _G[name] = function(...) orig(...); fn(...) end
        end
        function mkbox(name)
            local b = CreateFrame("EditBox", name)
            b.hooks, b.text, b.chatBridgeHooked = {}, "", false
            b.HookScript = function(self, n, fn) assert(self.hooks[n] == nil, "hooked twice"); self.hooks[n] = fn end
            b.GetText = function(self) return self.text end
            b.SetText = function(self, t) self.text = t end
            _G[name] = b
            return b
        end
    """)
    fire(b"PLAYER_ENTERING_WORLD")
    fire(b"PLAYER_ENTERING_WORLD")                        # 每次过图都会触发：钩子只能装一次
    assert lua.eval("hookcalls") == 1, lua.eval("hookcalls")
    pump(6.0)
    lua.execute(b'CHAT_FRAMES = { "ChatFrame1", "ChatFrame11" }; mkbox("ChatFrame11EditBox"); FCF_OpenTemporaryWindow()')
    assert lua.eval("ChatFrame11EditBox.hooks.OnKeyDown ~= nil and ChatFrame11EditBox.hooks.OnTextChanged ~= nil")
    lua.execute(b"FCF_OpenTemporaryWindow()")             # 再开一个：已挂过的不重复挂（重复会触发上面的 assert）
    before = len(seen)
    lua.execute("ChatFrame11EditBox.text = '密语窗口里的话'; ctrl = true; "
                "ChatFrame11EditBox.hooks.OnKeyDown(ChatFrame11EditBox, 'T'); ctrl = false".encode())
    pump(0.6)
    assert out(before) == ["Q\t\t密语窗口里的话"] and lua.eval("ChatFrame11EditBox.text") == b"", out(before)

    # 9) 遮挡检测碰到秘密数值 / 报错的框体：当它不存在，位置上报不能停
    def last_w():
        return [p for _, p in seen if p.startswith(b"W\t")][-1]
    pump(1.0)
    shown = b"W\t1,124,743,450,207,207,18\t"
    assert last_w() == shown, last_w()
    # 位置上明明盖住了翻译页，但 GetRect 返回的是秘密数值：不能拿来算，当没这个框体
    lua.execute(b"""
        for _, v in ipairs({ 200.5, 100.5, 300.5 }) do secrets[v] = true end
        MailFrame = CreateFrame('Frame', 'MailFrame')
        MailFrame.GetRect = function() return 200.5, 100.5, 300.5, 300.5 end
    """)
    pump(1.0)
    assert last_w() == shown, "秘密数值的框体不该参与遮挡判断"
    lua.execute(b"MailFrame.GetRect = function() return 200, 100, 300, 300 end")   # 同一位置、普通数值：确实算盖住
    pump(1.0)
    assert last_w() == b"W\t0\t", last_w()
    lua.execute(b"MailFrame.GetRect = function() error('secret arithmetic') end")   # 这个框体一查就报错
    pump(1.0)                                             # 以前错误会从 OnUpdate 里冒出来（这里 tick 直接抛异常）
    assert last_w() == shown, last_w()
    lua.execute(b"TradeSkillFrame:Show()")                # 一个框体报错不连累别的框体的判断
    pump(1.0)
    assert last_w() == b"W\t0\t", last_w()
    lua.execute(b"TradeSkillFrame:Hide(); MailFrame:Hide()")
    pump(1.0)
    assert last_w() == shown, last_w()
    # 算位置本身出错：OnUpdate 不报错，恢复后照常上报
    lua.execute(b"realPageRect = ChatBridge.PageRect; ChatBridge.PageRect = function() error('boom') end")
    lua.eval("ChatBridge.Announce")()
    before = len(seen)
    pump(5.0)
    assert out(before) == ["@\t2.11\tSenhu"] * 2, out(before)      # 位置发不了，「我在线」照发
    lua.execute(b"ChatBridge.PageRect = realPageRect; "
                b"for _, f in ipairs(frames) do if f.name == 'ChatBridgePanel' then f.l = 210 end end")
    pump(1.0)
    assert last_w() == b"W\t1,236,743,450,207,207,18\t", last_w()

    # 下面两条查的是官网文件。官网不进开源仓库（那边的自动构建也跑这个测试），所以文件在才查。
    index_html = os.path.join(ROOT, "site", "index.html")
    if os.path.exists(index_html):
        # 10) 官网「上次买的兑换码」：只有请求成功且服务器说已兑换才记成已用，临时错误照常显示
        with open(index_html, encoding="utf-8") as f:
            page = f.read()
        assert "!j.code" not in page, "不带 code 的响应（502、429）不能当成已兑换"
        assert "return r.ok ? r.json() : null;" in page and "if (j && j.used) {" in page

    if os.path.exists(os.path.join(ROOT, "tools", "build_hant.py")) and os.path.isdir(os.path.join(ROOT, "site", "guide")):
        # 11) 繁体页的人机验证组件用繁体
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import build_hant
        import i18n
        mode, i18n._mode = i18n._mode, "hant"
        try:
            hant = build_hant.to_hant_page("<script>turnstile.render('#captcha', {sitekey: K, language: 'zh-cn',});</script>", "trial.html")
        finally:
            i18n._mode = mode
        assert "language: 'zh-tw'" in hant and "zh-cn" not in hant, hant

    print("addon tests passed:", len(seen), "frames decoded")


if __name__ == "__main__":
    main()
