-- ChatBridge: 把收到的聊天编码成屏幕左上角的一小块色块，游戏外的翻译小程序读屏解码。
-- 插件不联网、不发消息、不读写任何游戏外的东西。
--
-- 色块协议（必须和小程序 codec.py 保持一致）：
--   网格 64 列 x 8 行，每格 4x4 物理像素，每个颜色通道 4 档（0, 1/3, 2/3, 1）=> 每格 6 bit。
--   第 0~3 格：识别标记；第 4~7 格：四档灰阶校准；其余格：数据。
--   数据字节流：序号(1) 长度(2) 内容(n) 校验(2, Fletcher-16)，每 3 字节拆成 4 个 6bit 符号。
--   内容： 类型码 \t 发言人 \t 文本

ChatBridge = {}
local CB = ChatBridge

CB.VERSION = "2.9"
CB.COLS, CB.ROWS, CB.CELL, CB.HEADER = 64, 8, 4, 8
CB.MAX_PAYLOAD = math.floor((CB.COLS * CB.ROWS - CB.HEADER) * 6 / 8) - 5
CB.HOLD = 0.25          -- 每条消息的色块显示秒数
CB.MAX_QUEUE = 30

local floor, strbyte = math.floor, string.byte
local PREFIX = "|cff66ccffChatBridge|r "

-- 简体 / 繁体：ChatBridge_Lang.lua 由电脑上的启动器写（"hans" / "hant"，跟程序里的选择一致）；
-- 没写过（比如只从 CurseForge 装了插件）就看游戏客户端语言，台服繁体客户端（zhTW）用繁体。
-- 繁体文字来自 ChatBridge_Hant.lua（tools/gen_addon_hant.py 生成）。
CB.hant = (ChatBridgeLang == "hant") or (ChatBridgeLang == nil and GetLocale ~= nil and GetLocale() == "zhTW")
local HANT = ChatBridge_HANT or {}
local function L(s)
    if CB.hant then return HANT[s] or s end
    return s
end

-- 识别标记与校准格（每项是 r,g,b 的档位 0~3）
local FIXED = {
    { 3, 0, 3 }, { 0, 3, 0 }, { 3, 3, 0 }, { 0, 0, 3 },
    { 0, 0, 0 }, { 1, 1, 1 }, { 2, 2, 2 }, { 3, 3, 3 },
}

local CODES = {
    CHAT_MSG_SAY = "S", CHAT_MSG_YELL = "Y",
    CHAT_MSG_PARTY = "P", CHAT_MSG_PARTY_LEADER = "P",
    CHAT_MSG_RAID = "R", CHAT_MSG_RAID_LEADER = "R", CHAT_MSG_RAID_WARNING = "X",   -- 不能用 W：W 是翻译页位置消息
    CHAT_MSG_INSTANCE_CHAT = "I", CHAT_MSG_INSTANCE_CHAT_LEADER = "I",
    CHAT_MSG_GUILD = "G", CHAT_MSG_OFFICER = "O",
    CHAT_MSG_WHISPER = "H", CHAT_MSG_BN_WHISPER = "B",
    CHAT_MSG_CHANNEL = "C",
}

-- 「只看队友」预设保留的类型：小队、团队、团队通知、副本，以及发给你的密语
local TEAM_CODES = { P = true, R = true, X = true, I = true, H = true, B = true }

-- 可订阅的频道：类型码、显示名、颜色（和小程序里的颜色一致）
CB.CHANNELS = {
    { "P", L("小队"), 0.66, 0.71, 1.00 },
    { "R", L("团队"), 1.00, 0.58, 0.25 },
    { "X", L("团队通知"), 1.00, 0.42, 0.24 },
    { "I", L("副本"), 1.00, 0.58, 0.25 },
    { "H", L("悄悄话"), 1.00, 0.55, 0.95 },
    { "B", L("战网密语"), 0.31, 0.89, 0.88 },
    { "G", L("公会"), 0.37, 0.89, 0.42 },
    { "O", L("官员"), 0.29, 0.76, 0.34 },
    { "S", L("说"), 0.95, 0.95, 0.95 },
    { "Y", L("大喊"), 1.00, 0.35, 0.35 },
    { "C", L("公共频道（综合、交易等）"), 0.94, 0.75, 0.69 },
}

function CB.SetSub(code, on)
    ChatBridgeDB.subs[code] = on and true or false
    if CB.RefreshSettings then CB.RefreshSettings() end
end

-- preset: "team" 只看队友；"all" 全部；"none" 全不翻
function CB.ApplyPreset(preset)
    for _, c in ipairs(CB.CHANNELS) do
        local code = c[1]
        ChatBridgeDB.subs[code] = (preset == "all") or (preset == "team" and TEAM_CODES[code] or false)
    end
    if CB.RefreshSettings then CB.RefreshSettings() end
end

---------------------------------------------------------------------------
-- 纯函数：编码
---------------------------------------------------------------------------

-- 把内容字符串和序号变成全部数据格的 6bit 符号列表
function CB.BuildSymbols(payload, seq)
    if #payload > CB.MAX_PAYLOAD then payload = payload:sub(1, CB.MAX_PAYLOAD) end
    local n = #payload
    local bytes = { seq % 256, floor(n / 256), n % 256 }
    for i = 1, n do bytes[#bytes + 1] = strbyte(payload, i) end
    local s1, s2 = 0, 0
    for i = 1, #bytes do
        s1 = (s1 + bytes[i]) % 255
        s2 = (s2 + s1) % 255
    end
    bytes[#bytes + 1] = s1
    bytes[#bytes + 1] = s2

    local syms = {}
    for i = 1, #bytes, 3 do
        local v = bytes[i] * 65536 + (bytes[i + 1] or 0) * 256 + (bytes[i + 2] or 0)
        syms[#syms + 1] = floor(v / 262144)
        syms[#syms + 1] = floor(v / 4096) % 64
        syms[#syms + 1] = floor(v / 64) % 64
        syms[#syms + 1] = v % 64
    end
    return syms
end

---------------------------------------------------------------------------
-- 物品 / 技能 / 任务链接：聊天里的链接带着编号，名字却是发的人那边客户端的语言（老外发来就是英文）。
-- 这里用编号向本机客户端查名字，中文客户端查到的就是官方中文名（繁体客户端是台服译名），
-- 直接换进方括号里，翻译服务就不用猜物品名了。查不到（客户端还没缓存这件物品）就留原名。
---------------------------------------------------------------------------

local function localName(kind, id)
    local ok, name
    if kind == "item" then
        if C_Item and C_Item.GetItemNameByID then ok, name = pcall(C_Item.GetItemNameByID, id) end
        if (not ok or not name) and GetItemInfo then ok, name = pcall(GetItemInfo, id) end
    elseif kind == "spell" or kind == "enchant" then
        if C_Spell and C_Spell.GetSpellName then ok, name = pcall(C_Spell.GetSpellName, id) end
        if (not ok or not name) and GetSpellInfo then ok, name = pcall(GetSpellInfo, id) end
    elseif kind == "quest" then
        if C_QuestLog and C_QuestLog.GetTitleForQuestID then ok, name = pcall(C_QuestLog.GetTitleForQuestID, id) end
    end
    if ok and type(name) == "string" and name ~= "" and not (issecretvalue and issecretvalue(name)) then return name end
end
CB.LocalName = localName

-- 把链接换成 [本机客户端里的名字]；第二个返回值是还没缓存、查不到名字的物品编号
function CB.LocalizeLinks(text)
    local missing
    text = text:gsub("|H(%a+):(%d+)([^|]*)|h%[(.-)%]|h", function(kind, id, rest, shown)
        id = tonumber(id)
        local name = id and localName(kind, id)
        if name then
            return "|H" .. kind .. ":" .. id .. rest .. "|h[" .. name .. "]|h"
        end
        if kind == "item" and id then
            missing = missing or {}
            missing[#missing + 1] = id
        end
    end)
    return text, missing
end

-- 去掉颜色码、链接、图标等转义，只留纯文本
function CB.Clean(text)
    text = CB.LocalizeLinks(text)
    text = text:gsub("|c%x%x%x%x%x%x%x%x", "")
    text = text:gsub("|cn[^:]*:", "")
    text = text:gsub("|r", "")
    text = text:gsub("|H.-|h(.-)|h", "%1")
    text = text:gsub("|T.-|t", "")
    text = text:gsub("|A.-|a", "")
    text = text:gsub("|K.-|k", "")
    text = text:gsub("||", "|")
    text = text:gsub("[%c]", " ")
    text = text:gsub("^%s+", ""):gsub("%s+$", "")
    return text
end

---------------------------------------------------------------------------
-- 色块显示
---------------------------------------------------------------------------

local strip = CreateFrame("Frame", "ChatBridgeStrip", nil)
strip:SetFrameStrata("TOOLTIP")
strip:SetFrameLevel(9000)
strip:Hide()

local cells = {}

local function layout()
    local _, physicalHeight = GetPhysicalScreenSize()
    if not physicalHeight or physicalHeight <= 0 then return end
    -- 无父框体 + 这个缩放 => 1 个单位正好是 1 个物理像素
    strip:SetScale(768 / physicalHeight)
    strip:SetSize(CB.COLS * CB.CELL, CB.ROWS * CB.CELL)
    strip:ClearAllPoints()
    strip:SetPoint("TOPLEFT", WorldFrame, "TOPLEFT", 0, 0)
end

local function buildCells()
    local bg = strip:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints(strip)
    bg:SetColorTexture(0, 0, 0, 1)
    for i = 0, CB.COLS * CB.ROWS - 1 do
        local t = strip:CreateTexture(nil, "ARTWORK")
        t:SetSize(CB.CELL, CB.CELL)
        t:SetPoint("TOPLEFT", strip, "TOPLEFT", (i % CB.COLS) * CB.CELL, -floor(i / CB.COLS) * CB.CELL)
        t:SetColorTexture(0, 0, 0, 1)
        if t.SetSnapToPixelGrid then t:SetSnapToPixelGrid(false) end
        if t.SetTexelSnappingBias then t:SetTexelSnappingBias(0) end
        cells[i] = t
    end
    for i = 1, #FIXED do
        local f = FIXED[i]
        cells[i - 1]:SetColorTexture(f[1] / 3, f[2] / 3, f[3] / 3, 1)
    end
end

local function paint(syms)
    local total = CB.COLS * CB.ROWS - CB.HEADER
    for k = 1, total do
        local s = syms[k] or 0
        cells[CB.HEADER + k - 1]:SetColorTexture(floor(s / 16) / 3, (floor(s / 4) % 4) / 3, (s % 4) / 3, 1)
    end
end

---------------------------------------------------------------------------
-- 发送队列
---------------------------------------------------------------------------

local queue, seq, shownFor, showing = {}, 0, 0, false

function CB.Enqueue(payload)
    if #queue >= CB.MAX_QUEUE then table.remove(queue, 1) end
    queue[#queue + 1] = payload
end

-- 鼠标滚轮翻看之前的译文：发 "V\t格数\t"；还没发出去的滚动合并成一条
function CB.EnqueueScroll(delta)
    local last = queue[#queue]
    local prev = last and tonumber(last:match("^V\t(%-?%d+)\t$"))
    if prev then
        queue[#queue] = "V\t" .. (prev + delta) .. "\t"
    else
        CB.Enqueue("V\t" .. delta .. "\t")
    end
end

local driver = CreateFrame("Frame")
driver:SetScript("OnUpdate", function(_, elapsed)
    if showing then
        shownFor = shownFor + elapsed
        if shownFor < CB.HOLD then return end
    end
    local payload = table.remove(queue, 1)
    if payload then
        seq = (seq + 1) % 256
        paint(CB.BuildSymbols(payload, seq))
        strip:Show()
        showing, shownFor = true, 0
    elseif showing then
        strip:Hide()
        showing = false
    end
end)

---------------------------------------------------------------------------
-- 聊天事件
---------------------------------------------------------------------------

local function isSecret(v)
    return type(issecretvalue) == "function" and issecretvalue(v) and true or false
end

local lastSecretNotice = -100

-- 发言人的职业颜色（和官方聊天框一样），拿不到就不带
local function classHex(guid)
    if not guid or isSecret(guid) or type(guid) ~= "string" or guid == "" then return nil end
    local ok, _, classFile = pcall(GetPlayerInfoByGUID, guid)
    if not ok or not classFile or isSecret(classFile) then return nil end
    local c = (C_ClassColor and C_ClassColor.GetClassColor and C_ClassColor.GetClassColor(classFile))
        or (RAID_CLASS_COLORS and RAID_CLASS_COLORS[classFile])
    if not c then return nil end
    return string.format("%02x%02x%02x", floor(c.r * 255 + 0.5), floor(c.g * 255 + 0.5), floor(c.b * 255 + 0.5))
end

local function onChat(event, text, sender, guid)
    local code = CODES[event]
    if not code or not ChatBridgeDB.enabled then return end
    if not ChatBridgeDB.subs[code] then return end   -- 没订阅这个频道

    if isSecret(text) then
        -- 副本限制期间读不到内容，只告诉小程序「有一条读不到的消息」，10 秒最多一次
        local now = GetTime()
        if now - lastSecretNotice > 10 then
            lastSecretNotice = now
            CB.Enqueue("!\t" .. code .. "\t")
        end
        return
    end
    if type(text) ~= "string" or text == "" then return end

    local name = "?"
    if not isSecret(sender) and type(sender) == "string" and sender ~= "" then
        name = Ambiguate and Ambiguate(sender, "short") or sender
        if name == UnitName("player") then return end -- 自己说的话不用翻
        name = CB.Clean(name)
        if name == "" then name = "?" end
    end

    -- 链接里有本机还没缓存的物品：让客户端去取名字，0.4 秒后再发这一条（取不到就用原名）
    if not CB.retrying and C_Timer and C_Timer.After and text:find("|Hitem:", 1, true) then
        local _, missing = CB.LocalizeLinks(text)
        if missing then
            for _, id in ipairs(missing) do
                if C_Item and C_Item.RequestLoadItemDataByID then pcall(C_Item.RequestLoadItemDataByID, id) end
            end
            C_Timer.After(0.4, function()
                CB.retrying = true
                pcall(CB.OnChat, event, text, sender, guid)
                CB.retrying = false
            end)
            return
        end
    end

    local clean = CB.Clean(text)
    if clean == "" then return end
    -- 有聊天要翻的时候，如果翻译页位置有一阵没发了，顺手先补发一次：
    -- 小程序可能是进游戏以后才启动的，错过了加载时发的那次
    if CB.RefreshRectIfStale then CB.RefreshRectIfStale() end
    local hex = classHex(guid)
    if hex and name ~= "?" then name = name .. "\031" .. hex end
    CB.Enqueue(code .. "\t" .. name .. "\t" .. clean)
    if CB.NoteIncoming then CB.NoteIncoming() end
    ChatBridgeDB.lastChatAt = time and time() or nil
    if not CB.sawChat then
        CB.sawChat = true
        if CB.UpdateCard then CB.UpdateCard() end
    end
end

CB.OnChat = onChat

---------------------------------------------------------------------------
-- 发消息：在游戏聊天框里打中文，按 Ctrl+T（或在末尾打两个分号），
-- 插件把这句话交给小程序翻成英文放进剪贴板，聊天框清空等你 Ctrl+V。
---------------------------------------------------------------------------

local SUFFIXES = { ";;", "\239\188\155\239\188\155" } -- 半角 ;; 和全角 ；；

local function endsWithSuffix(text)
    for _, s in ipairs(SUFFIXES) do
        if #text >= #s and text:sub(-#s) == s then return #s end
    end
end

function CB.SendOutgoing(editBox)
    local text = editBox:GetText()
    if isSecret(text) then
        print(PREFIX .. L("现在处于副本限制期间，插件读不到输入框内容。"))
        return
    end
    if type(text) ~= "string" then return end
    local cut = endsWithSuffix(text)
    if cut then text = text:sub(1, -cut - 1) end
    text = text:gsub("^%s+", ""):gsub("%s+$", "")
    if text == "" then return end
    -- 这句话里插了物品 / 技能链接（Shift+点击）：先换成 {1} {2} 占位符再送去翻，链接本身记在这里；
    -- 译文贴回聊天框时再把占位符换回真链接，发出去的还是能点的链接。
    local links = {}
    text = text:gsub("|c%x%x%x%x%x%x%x%x|H.-|h.-|h|r", function(link)
        links[#links + 1] = link
        return "{" .. #links .. "}"
    end)
    text = text:gsub("|H.-|h(.-)|h", "%1"):gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "")
    CB.outLinks = #links > 0 and links or nil
    CB.outLinksAt = GetTime()
    CB.Enqueue("Q\t\t" .. text)
    editBox:SetText("")
end

-- 译文贴进聊天框以后：把 {1} {2} 换回刚才记下的链接
function CB.RestoreLinks(editBox)
    local links = CB.outLinks
    if not links then return end
    if GetTime() - (CB.outLinksAt or 0) > 60 then CB.outLinks = nil return end
    local text = editBox:GetText()
    if isSecret(text) or type(text) ~= "string" or not text:find("{%d+}") then return end
    local n
    text, n = text:gsub("{(%d+)}", function(i) return links[tonumber(i)] end)
    if n > 0 then
        CB.outLinks = nil
        editBox:SetText(text)
    end
end

local function hookEditBoxes()
    for i = 1, (NUM_CHAT_WINDOWS or 10) do
        local box = _G["ChatFrame" .. i .. "EditBox"]
        if box and not box.chatBridgeHooked then
            box.chatBridgeHooked = true
            box:HookScript("OnKeyDown", function(self, key)
                if key == "T" and IsControlKeyDown() and not IsAltKeyDown() then
                    CB.SendOutgoing(self)
                end
            end)
            box:HookScript("OnTextChanged", function(self, userInput)
                if CB.outLinks then CB.RestoreLinks(self) end
                if not userInput then return end
                local text = self:GetText()
                if isSecret(text) or type(text) ~= "string" then return end
                if endsWithSuffix(text) then CB.SendOutgoing(self) end
            end)
        end
    end
end

---------------------------------------------------------------------------
-- 翻译页：一块可以拖动、可以缩放的底板，默认盖在主聊天框上。插件画底板、「翻译」按钮
-- 和缩放角标，并把内容区在屏幕上的像素位置告诉小程序；小程序把译文画在这个位置上。
-- 「翻译」按钮也能单独拖到任何地方。位置和大小都记在 ChatBridgeDB 里。
---------------------------------------------------------------------------

local panel, pageButton, unread, lastRect, rectTimer = nil, nil, 0, nil, 0
local dragging = false   -- 拖动或缩放期间让小程序先把译文藏起来，松手后再按新位置显示
local usageMode = false  -- 翻译页当前显示的是「用量」而不是聊天译文
-- 游戏里不放任何付费相关的东西（暴雪插件政策）：充值、兑换只在电脑上的启动器里做
local usageButtonLabel = nil
local GRIP = 16      -- 底板最下面留一条：拖动条 + 右下角缩放角标（小程序不盖这一条）

-- 游戏自己的窗口（专业、背包、人物、地图、菜单、提示框……）盖到翻译页上时，小程序的译文要先藏起来：
-- 译文是电脑程序画在游戏上面的一层，不藏就会压在这些窗口上。窗口一关，译文自动回来。
local COVER_FRAMES = {
    "GameMenuFrame", "SettingsPanel", "InterfaceOptionsFrame", "VideoOptionsFrame", "KeyBindingFrame", "MacroFrame",
    "HelpFrame", "WorldMapFrame", "FlightMapFrame", "TaxiFrame", "BattlefieldFrame", "PVPFrame", "PVEFrame",
    "LFGParentFrame", "CharacterFrame", "InspectFrame", "DressUpFrame", "SpellBookFrame", "PlayerSpellsFrame",
    "PlayerTalentFrame", "TalentFrame", "TradeSkillFrame", "ProfessionsFrame", "CraftFrame", "ClassTrainerFrame",
    "QuestLogFrame", "QuestFrame", "GossipFrame", "FriendsFrame", "GuildFrame", "CommunitiesFrame",
    "CollectionsJournal", "EncounterJournal", "AchievementFrame", "CalendarFrame", "MerchantFrame", "MailFrame",
    "OpenMailFrame", "TradeFrame", "AuctionHouseFrame", "AuctionFrame", "BankFrame", "LootFrame", "GroupLootFrame1",
    "GroupLootFrame2", "GroupLootFrame3", "GroupLootFrame4", "TabardFrame", "PetStableFrame",
    "StaticPopup1", "StaticPopup2", "StaticPopup3", "StaticPopup4", "ContainerFrameCombinedBags",
    "GameTooltip", "ItemRefTooltip", "ShoppingTooltip1", "ShoppingTooltip2",
    "ChatBridgeSettings",                    -- 自己的频道设置窗口
}
for i = 1, 13 do COVER_FRAMES[#COVER_FRAMES + 1] = "ContainerFrame" .. i end

local function screenBox(f)
    local l, b, w, h = f:GetRect()
    if not (l and b and w and h) then return nil end
    local s = f:GetEffectiveScale()
    return l * s, b * s, (l + w) * s, (b + h) * s
end

local function overlaps(f, pl, pb, pr, pt)
    if not (f and f ~= panel and f.IsVisible and f:IsVisible()) then return false end
    local l, b, r, t = screenBox(f)
    return l ~= nil and l < pr and r > pl and b < pt and t > pb
end

function CB.PageCovered()
    if not panel then return false end
    local pl, pb, pr, pt = screenBox(panel)
    if not pl then return false end
    for _, name in ipairs(COVER_FRAMES) do
        if overlaps(_G[name], pl, pb, pr, pt) then return true end
    end
    if GetUIPanel then                       -- 其他插件也会把窗口登记成游戏面板
        for _, where in ipairs({ "left", "center", "right", "doublewide", "fullscreen" }) do
            local ok, f = pcall(GetUIPanel, where)
            if ok and overlaps(f, pl, pb, pr, pt) then return true end
        end
    end
    return false
end

-- 内容区在游戏窗口里的物理像素矩形："1,左,上,宽,高"；没显示时是 "0"
function CB.PageRect()
    if dragging or not panel or not panel:IsVisible() then return "0" end
    if CB.PageCovered() then return "0" end
    local _, physicalHeight = GetPhysicalScreenSize()
    local left, top, width, height = panel:GetLeft(), panel:GetTop(), panel:GetWidth(), panel:GetHeight()
    if not (left and top and width and height and physicalHeight) then return "0" end
    local k = panel:GetEffectiveScale() * physicalHeight / 768
    local rect = string.format("1,%d,%d,%d,%d,%d,%d", floor(left * k + 0.5), floor(physicalHeight - top * k + 0.5),
        floor(width * k + 0.5), floor((height - GRIP) * k + 0.5),
        floor((height - GRIP) * k + 0.5), floor(GRIP * k + 0.5))
    local card = CB.card
    if card and card:IsShown() then
        local cl, ct, cw, ch = card:GetLeft(), card:GetTop(), card:GetWidth(), card:GetHeight()
        if cl and ct and cw and ch then
            local ck = card:GetEffectiveScale() * physicalHeight / 768
            rect = rect .. string.format(",%d,%d,%d,%d", floor(cl * ck - left * k + 0.5),
                floor(top * k - ct * ck + 0.5), floor(cw * ck + 0.5), floor(ch * ck + 0.5))
        end
    end
    return rect
end

local lastRectAt = -100

function CB.CardWanted()
    if CB.sawChat then return false end
    local last = ChatBridgeDB and ChatBridgeDB.lastChatAt
    if last and time and time() - last < 1800 then return false end
    return true
end

function CB.UpdateCard(quiet)
    if not CB.card then return end
    if CB.CardWanted() then CB.card:Show() else CB.card:Hide() end
    if not quiet and CB.SendRectNow then CB.SendRectNow() end      -- 登录时后面马上会发，不用这里再发
end

local function sendRect(force)
    local rect = CB.PageRect()
    if force or rect ~= lastRect then
        lastRect, lastRectAt = rect, GetTime()
        CB.Enqueue("W\t" .. rect .. "\t")
    end
end

function CB.SendRectNow()
    if panel then sendRect(false) end       -- 位置（含提示卡）真变了才发
end

function CB.RefreshRectIfStale()
    if panel and GetTime() - lastRectAt > 30 then sendRect(true) end
end

local function refreshButton()
    if not pageButton then return end
    local on = panel:IsShown()
    pageButton.label:SetText(on and L("翻译") or (unread > 0 and (L("翻译 ") .. unread) or L("翻译")))
    pageButton.bg:SetColorTexture(on and 0.16 or 0.05, on and 0.42 or 0.06, on and 0.62 or 0.08, 0.9)
end

function CB.TogglePage(show)
    if not panel then return end
    if show == nil then show = not panel:IsShown() end
    ChatBridgeDB.page = show and true or false
    if show then panel:Show(); unread = 0 else panel:Hide() end
    refreshButton()
    sendRect(true)
end

-- 在「聊天译文」和「用量」两页之间切换。用量内容由小程序画（只显示还能翻多少条）
function CB.SetUsageMode(on)
    if not panel then return end
    usageMode = on and true or false
    if usageMode and not panel:IsShown() then CB.TogglePage(true) end
    if usageButtonLabel then usageButtonLabel:SetText(usageMode and L("返回") or L("用量")) end
    CB.Enqueue("U\t" .. (usageMode and "1" or "0") .. "\t")
    sendRect(true)
end

function CB.RequestUsage()
    CB.SetUsageMode(not usageMode)
end

-- 记住一个框体现在的位置（和大小），并改成只用一个锚点固定，之后才能自由拖动和缩放
local function saveBox(frame, key, withSize)
    local left, top = frame:GetLeft(), frame:GetTop()
    if not (left and top) then return end
    local box = { x = left, y = top }
    if withSize then box.w, box.h = frame:GetWidth(), frame:GetHeight() end
    ChatBridgeDB[key] = box
    frame:ClearAllPoints()
    frame:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", left, top)
end

-- 翻译页挂在「翻译」按钮上：panelBox 记的是翻译页左上角相对按钮左上角的偏移和大小，
-- 所以拖按钮时翻译页跟着一起走；拉角标只改大小。翻译页自己不能单独拖。
-- 翻译页的右上角永远贴在按钮正下方；缩放角标在左下角，拉的时候右上角不动。
local function placePanel()
    local box = ChatBridgeDB.panelBox
    local w, h = box and box.w, box and box.h
    if not (w and h) then
        -- 默认大小：和主聊天框一样大
        w, h = ChatFrame1:GetWidth(), ChatFrame1:GetHeight()
        if not (w and h and w > 50 and h > 50) then w, h = 430, 200 end
        w, h = w + 6, h + 6
    end
    panel:ClearAllPoints()
    panel:SetSize(w, h)
    panel:SetPoint("TOPRIGHT", pageButton, "BOTTOMRIGHT", 0, -3)
end

-- 缩放结束：记住新大小，并重新贴回按钮下方
local function savePanel()
    local w, h = panel:GetWidth(), panel:GetHeight()
    if not (w and h) then return end
    ChatBridgeDB.panelBox = { w = w, h = h }
    placePanel()
end

local function placeButton()
    pageButton:ClearAllPoints()
    local box = ChatBridgeDB.buttonBox
    if box and box.x and box.y then
        pageButton:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", box.x, box.y)
    else
        pageButton:SetPoint("BOTTOMRIGHT", ChatFrame1, "TOPRIGHT", 3, 6)
    end
end

-- 把按钮和翻译页放回默认位置（贴着主聊天框）
function CB.ResetLayout()
    if not panel then return end
    ChatBridgeDB.panelBox, ChatBridgeDB.buttonBox = nil, nil
    placeButton()
    placePanel()
    sendRect(true)
end

local function buildPage()
    if panel or not ChatFrame1 then return end
    panel = CreateFrame("Frame", "ChatBridgePanel", UIParent)
    panel:SetFrameStrata("MEDIUM")
    panel:EnableMouse(true)
    panel:SetMovable(true)
    panel:SetResizable(true)
    if panel.SetResizeBounds then panel:SetResizeBounds(180, 90)
    elseif panel.SetMinResize then panel:SetMinResize(180, 90) end
    -- 翻译页自己不能拖：要换位置就拖「翻译」按钮，页面跟着按钮走

    local bg = panel:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints(panel)
    bg:SetColorTexture(0.04, 0.05, 0.07, 0.55)        -- 半透明：能透出后面的游戏画面

    -- 底部一条：左下角是缩放角标，右边是「用量」
    local bar = panel:CreateTexture(nil, "BORDER")
    bar:SetPoint("BOTTOMLEFT")
    bar:SetPoint("BOTTOMRIGHT")
    bar:SetHeight(GRIP)
    bar:SetColorTexture(0.10, 0.12, 0.16, 1)        -- 不透明：小程序用同色遮片盖住提示
    local note = panel:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    note:SetPoint("LEFT", bar, "LEFT", 20, 0)
    note:SetPoint("RIGHT", bar, "RIGHT", -46, 0)
    note:SetJustifyH("LEFT")
    note:SetWordWrap(false)
    -- 这句提示一直画着，但翻译程序开着时会被它的同色遮片盖住，所以只有程序没开时才看得见
    -- 从 CurseForge 只装了插件的人也要看得懂：没装程序就去官网下载（只给地址，不提钱）
    note:SetText(L("没开翻译程序？下载 wow.husen.ca"))

    -- 中间的提示卡：比底条那句显眼。还没收到过聊天时才显示（之后页面上有译文，卡就收起来）。
    -- 位置通过翻译页矩形一起发给小程序：程序开着时它在同一位置盖一张同色的卡，写「已连上，等待聊天」，
    -- 所以这句「没开」只有程序真没开时才看得见。
    local card = CreateFrame("Frame", "ChatBridgeCard", panel)
    card:SetPoint("LEFT", panel, "LEFT", 14, GRIP / 2)
    card:SetPoint("RIGHT", panel, "RIGHT", -14, GRIP / 2)
    card:SetHeight(52)
    local cardBg = card:CreateTexture(nil, "BACKGROUND")
    cardBg:SetAllPoints(card)
    cardBg:SetColorTexture(0.10, 0.12, 0.16, 1)
    local cardTitle = card:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    cardTitle:SetPoint("TOP", card, "TOP", 0, -9)
    cardTitle:SetText(L("翻译程序没开"))
    local cardText = card:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    cardText:SetPoint("TOP", cardTitle, "BOTTOM", 0, -5)
    cardText:SetPoint("LEFT", card, "LEFT", 8, 0)
    cardText:SetPoint("RIGHT", card, "RIGHT", -8, 0)
    cardText:SetText(L("去 wow.husen.ca 下载电脑程序，打开后点「启动」"))
    CB.card = card

    -- 滚轮翻看之前的译文（译文由小程序显示，这里把滚动转给它）
    panel:EnableMouseWheel(true)
    panel:SetScript("OnMouseWheel", function(_, delta) CB.EnqueueScroll(delta) end)

    local usage = CreateFrame("Button", nil, panel)
    usage:SetSize(40, GRIP)
    usage:SetPoint("BOTTOMRIGHT", -4, 0)
    local usageHover = usage:CreateTexture(nil, "HIGHLIGHT")
    usageHover:SetAllPoints(usage)
    usageHover:SetColorTexture(1, 1, 1, 0.12)
    local usageLabel = usage:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    usageLabel:SetPoint("CENTER")
    usageLabel:SetText(L("用量"))
    usageButtonLabel = usageLabel
    usage:SetScript("OnClick", function() CB.RequestUsage() end)


    local grip = CreateFrame("Button", nil, panel)
    grip:SetSize(GRIP, GRIP)
    grip:SetPoint("BOTTOMLEFT")
    -- 自己画的阶梯形角标（左下角 3、2、1 个小点），不依赖游戏自带贴图
    for row = 0, 2 do
        for col = 0, 2 - row do
            local dot = grip:CreateTexture(nil, "OVERLAY")
            dot:SetSize(3, 3)
            dot:SetPoint("BOTTOMLEFT", 2 + col * 4, 2 + row * 4)
            dot:SetColorTexture(0.75, 0.80, 0.90, 1)
        end
    end
    grip:SetScript("OnMouseDown", function()
        dragging = true
        sendRect(true)                       -- 先让译文藏起来，拖的过程只有游戏自己的底板在动，才跟手
        panel:StartSizing("BOTTOMLEFT")      -- 从左下角拉：右上角（按钮下方）不动
    end)
    grip:SetScript("OnMouseUp", function()
        panel:StopMovingOrSizing()
        savePanel()
        dragging = false
        sendRect(true)
    end)
    grip:SetScript("OnEnter", function(self)
        if not GameTooltip then return end
        GameTooltip:SetOwner(self, "ANCHOR_TOPRIGHT")
        GameTooltip:AddLine(L("按住拖动，调整翻译页大小"), 1, 1, 1)
        GameTooltip:Show()
    end)
    grip:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)

    panel:Hide()

    pageButton = CreateFrame("Button", "ChatBridgePageButton", UIParent)
    pageButton:SetFrameStrata("MEDIUM")
    pageButton:SetSize(64, 20)
    pageButton:SetClampedToScreen(true)
    pageButton:SetMovable(true)
    pageButton:RegisterForDrag("LeftButton")
    pageButton:SetScript("OnDragStart", function(self)
        dragging = true
        sendRect(true)
        self:StartMoving()
    end)
    pageButton:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
        saveBox(self, "buttonBox", false)
        dragging = false
        sendRect(true)
    end)
    pageButton.bg = pageButton:CreateTexture(nil, "BACKGROUND")
    pageButton.bg:SetAllPoints(pageButton)
    pageButton.label = pageButton:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    pageButton.label:SetPoint("CENTER")
    pageButton:RegisterForClicks("LeftButtonUp", "RightButtonUp")
    pageButton:SetScript("OnClick", function(_, mouseButton)
        if mouseButton == "RightButton" then CB.ToggleSettings() else CB.TogglePage() end
    end)
    pageButton:SetScript("OnEnter", function(self)
        if not GameTooltip then return end
        GameTooltip:SetOwner(self, "ANCHOR_TOP")
        GameTooltip:AddLine(L("翻译"))
        GameTooltip:AddLine(L("左键：展开 / 收起译文"), 1, 1, 1)
        GameTooltip:AddLine(L("右键：选择翻译哪些频道"), 1, 1, 1)
        GameTooltip:AddLine(L("按住拖动：连同翻译页一起换位置"), 1, 1, 1)
        GameTooltip:Show()
    end)
    pageButton:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
    placeButton()
    placePanel()

    if ChatBridgeDB.page then panel:Show() end
    refreshButton()
end

-- 加载画面会挡住色块，那期间发的东西小程序收不到。所以每次加载画面结束后
-- 隔 1 秒和 4 秒各补发一次「我在线」和翻译页位置。
local announceIn = {}

function CB.Announce()
    announceIn = { 1.0, 4.0 }
end

local function pageTick(elapsed)
    for i = #announceIn, 1, -1 do
        announceIn[i] = announceIn[i] - elapsed
        if announceIn[i] <= 0 then
            table.remove(announceIn, i)
            CB.Enqueue("@\t" .. CB.VERSION .. "\t" .. (UnitName("player") or ""))
            if panel then sendRect(true) end
        end
    end
    if not panel then return end
    rectTimer = rectTimer + elapsed
    if rectTimer < 0.3 then return end
    rectTimer = 0
    sendRect(false)      -- 聊天框被拖动、缩放、隐藏时自动通知小程序
end

function CB.NoteIncoming()
    if panel and not panel:IsShown() then
        unread = unread + 1
        refreshButton()
    end
end

---------------------------------------------------------------------------
-- 设置窗口：右键「翻译」按钮打开，勾选要翻译哪些频道
---------------------------------------------------------------------------

local settings, checkRows = nil, {}

function CB.RefreshSettings()
    for code, row in pairs(checkRows) do
        if ChatBridgeDB.subs[code] then row.check:Show() else row.check:Hide() end
    end
end

local function smallButton(parent, text, width, onClick)
    local b = CreateFrame("Button", nil, parent)
    b:SetSize(width, 22)
    local bg = b:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints(b)
    bg:SetColorTexture(0.16, 0.20, 0.28, 1)
    local hl = b:CreateTexture(nil, "HIGHLIGHT")
    hl:SetAllPoints(b)
    hl:SetColorTexture(1, 1, 1, 0.12)
    local label = b:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    label:SetPoint("CENTER")
    label:SetText(text)
    b:SetScript("OnClick", onClick)
    return b
end

local function buildSettings()
    local ROW, PAD, WIDTH = 24, 12, 270
    settings = CreateFrame("Frame", "ChatBridgeSettings", UIParent)
    settings:SetFrameStrata("DIALOG")
    settings:SetSize(WIDTH, PAD * 2 + 26 + #CB.CHANNELS * ROW + 34)
    settings:SetPoint("BOTTOMLEFT", ChatFrame1, "TOPLEFT", 0, 34)
    settings:SetClampedToScreen(true)
    settings:EnableMouse(true)
    settings:SetMovable(true)
    settings:RegisterForDrag("LeftButton")
    settings:SetScript("OnDragStart", settings.StartMoving)
    settings:SetScript("OnDragStop", settings.StopMovingOrSizing)
    if UISpecialFrames then table.insert(UISpecialFrames, "ChatBridgeSettings") end -- 按 Esc 关闭

    local bg = settings:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints(settings)
    bg:SetColorTexture(0.05, 0.06, 0.09, 0.97)
    local edge = settings:CreateTexture(nil, "BORDER")
    edge:SetPoint("TOPLEFT", -1, 1)
    edge:SetPoint("BOTTOMRIGHT", 1, -1)
    edge:SetColorTexture(0.35, 0.40, 0.50, 1)
    edge:SetDrawLayer("BACKGROUND", -1)

    local title = settings:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    title:SetPoint("TOPLEFT", PAD, -PAD)
    title:SetText(L("翻译哪些频道"))

    for i, c in ipairs(CB.CHANNELS) do
        local code = c[1]
        local row = CreateFrame("Button", nil, settings)
        row:SetSize(WIDTH - PAD * 2, ROW - 2)
        row:SetPoint("TOPLEFT", PAD, -(PAD + 26 + (i - 1) * ROW))
        local hl = row:CreateTexture(nil, "HIGHLIGHT")
        hl:SetAllPoints(row)
        hl:SetColorTexture(1, 1, 1, 0.07)
        local box = row:CreateTexture(nil, "ARTWORK")
        box:SetSize(16, 16)
        box:SetPoint("LEFT", 2, 0)
        box:SetColorTexture(0.18, 0.20, 0.25, 1)
        row.check = row:CreateTexture(nil, "OVERLAY")
        row.check:SetSize(10, 10)
        row.check:SetPoint("CENTER", box, "CENTER")
        row.check:SetColorTexture(1.00, 0.82, 0.10, 1)
        local label = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        label:SetPoint("LEFT", box, "RIGHT", 8, 0)
        label:SetText(c[2])
        label:SetTextColor(c[3], c[4], c[5])
        row:SetScript("OnClick", function() CB.SetSub(code, not ChatBridgeDB.subs[code]) end)
        checkRows[code] = row
    end

    local y = PAD
    local team = smallButton(settings, L("只看队友"), 74, function() CB.ApplyPreset("team") end)
    team:SetPoint("BOTTOMLEFT", PAD, y)
    local all = smallButton(settings, L("全选"), 50, function() CB.ApplyPreset("all") end)
    all:SetPoint("LEFT", team, "RIGHT", 6, 0)
    local none = smallButton(settings, L("全不选"), 56, function() CB.ApplyPreset("none") end)
    none:SetPoint("LEFT", all, "RIGHT", 6, 0)
    local close = smallButton(settings, L("关闭"), 48, function() settings:Hide() end)
    close:SetPoint("BOTTOMRIGHT", -PAD, y)

    settings:Hide()
    CB.RefreshSettings()
end

function CB.ToggleSettings()
    if not settings then
        local ok, err = pcall(buildSettings)
        if not ok then print(PREFIX .. L("设置窗口没建成: ") .. tostring(err)); return end
    end
    if settings:IsShown() then settings:Hide() else settings:Show() end
end

local pageDriver = CreateFrame("Frame")
pageDriver:SetScript("OnUpdate", function(_, elapsed) pageTick(elapsed) end)

local events = CreateFrame("Frame")
events:SetScript("OnEvent", function(_, event, ...)
    if event == "ADDON_LOADED" then
        if ... ~= "ChatBridge" then return end
        ChatBridgeDB = ChatBridgeDB or {}
        if ChatBridgeDB.enabled == nil then ChatBridgeDB.enabled = true end
        if type(ChatBridgeDB.subs) ~= "table" then
            -- 从旧版的两个开关（只翻队友 / 公共频道）迁移成按频道订阅
            ChatBridgeDB.subs = {}
            local teamOnly = ChatBridgeDB.teamOnly ~= false
            for _, c in ipairs(CB.CHANNELS) do
                local code = c[1]
                if teamOnly then ChatBridgeDB.subs[code] = TEAM_CODES[code] or false
                elseif code == "C" then ChatBridgeDB.subs[code] = ChatBridgeDB.channel and true or false
                else ChatBridgeDB.subs[code] = true end
            end
            ChatBridgeDB.teamOnly, ChatBridgeDB.channel = nil, nil
        end
        if ChatBridgeDB.subs.W ~= nil then          -- 2.0 及以前团队通知的代号是 W
            if ChatBridgeDB.subs.X == nil then ChatBridgeDB.subs.X = ChatBridgeDB.subs.W end
            ChatBridgeDB.subs.W = nil
        end
        for _, c in ipairs(CB.CHANNELS) do
            if ChatBridgeDB.subs[c[1]] == nil then ChatBridgeDB.subs[c[1]] = TEAM_CODES[c[1]] or false end
        end
        buildCells()
        layout()
    elseif event == "PLAYER_ENTERING_WORLD" then
        layout()
        pcall(hookEditBoxes)
        CB.Enqueue("@\t" .. CB.VERSION .. "\t" .. (UnitName("player") or ""))
        local ok, err = pcall(buildPage)
        if not ok then print(PREFIX .. L("翻译页没建成: ") .. tostring(err)) end
        CB.UpdateCard(true)
        sendRect(true)
        CB.Announce()
        print(PREFIX .. L("已加载。点「翻译」看译文（按钮和翻译页都能拖）；打中文后按 Ctrl+T 翻成英文。/cb 看更多。"))
        if not ChatBridgeDB.welcomed then        -- 第一次装：说清楚还要一个电脑程序（CurseForge 上只有插件）
            ChatBridgeDB.welcomed = true
            print(PREFIX .. L("这个插件要配合电脑上的免费翻译程序使用（Windows）。还没装的话去 wow.husen.ca 下载，打开后点「启动」。"))
        end
    elseif event == "LOADING_SCREEN_DISABLED" then
        CB.Announce()
    elseif event == "DISPLAY_SIZE_CHANGED" or event == "UI_SCALE_CHANGED" then
        layout()
    else
        local text, sender, _, _, _, _, _, _, _, _, _, guid = ...
        local ok, err = pcall(onChat, event, text, sender, guid)
        if not ok and ChatBridgeDB.debug then print(PREFIX .. L("出错: ") .. tostring(err)) end
    end
end)

events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
pcall(events.RegisterEvent, events, "LOADING_SCREEN_DISABLED")
pcall(events.RegisterEvent, events, "DISPLAY_SIZE_CHANGED")
pcall(events.RegisterEvent, events, "UI_SCALE_CHANGED")
for event in pairs(CODES) do pcall(events.RegisterEvent, events, event) end

---------------------------------------------------------------------------
-- 命令
---------------------------------------------------------------------------

local function onOff(b) return b and L("|cff00ff00开|r") or L("|cffff4040关|r") end

SLASH_CHATBRIDGE1 = "/cb"
SLASH_CHATBRIDGE2 = "/chatbridge"
SlashCmdList.CHATBRIDGE = function(msg)
    msg = (msg or ""):lower():gsub("^%s+", ""):gsub("%s+$", "")
    if msg == "test" then
        CB.Enqueue("T\tChatBridge\tlfm 1 healer for deadmines, pst. can someone brez me after this pull?")
        print(PREFIX .. L("已发出一条测试消息，翻译小程序里应该出现译文。"))
    elseif msg == "page" then
        CB.TogglePage()
    elseif msg == "usage" then
        CB.RequestUsage()
    elseif msg == "account" then
        CB.Enqueue("A\t\t")
        print(PREFIX .. L("已让电脑上的翻译小程序打开设备编号窗口（切出游戏看）。"))
    elseif msg == "reset" then
        CB.ResetLayout()
        print(PREFIX .. L("按钮和翻译页已放回默认位置。"))
    elseif msg == "sync" then
        sendRect(true)
        print(PREFIX .. L("已把翻译页的位置重新发给小程序。"))
    elseif msg == "team" then
        CB.ApplyPreset("team")
        print(PREFIX .. L("已切到只看队友：小队、团队、副本、密语。"))
    elseif msg == "all" then
        CB.ApplyPreset("all")
        print(PREFIX .. L("已订阅全部频道。"))
    elseif msg == "channel" then
        CB.SetSub("C", not ChatBridgeDB.subs.C)
        print(PREFIX .. L("公共频道（交易、综合等）翻译: ") .. onOff(ChatBridgeDB.subs.C))
    elseif msg == "config" or msg == "settings" then
        CB.ToggleSettings()
    elseif msg == "on" or msg == "off" then
        ChatBridgeDB.enabled = (msg == "on")
        print(PREFIX .. L("翻译桥: ") .. onOff(ChatBridgeDB.enabled))
    elseif msg == "debug" then
        ChatBridgeDB.debug = not ChatBridgeDB.debug
        print(PREFIX .. L("调试信息: ") .. onOff(ChatBridgeDB.debug))
    else
        local names = {}
        for _, c in ipairs(CB.CHANNELS) do
            if ChatBridgeDB.subs[c[1]] then names[#names + 1] = c[2] end
        end
        print(PREFIX .. "v" .. CB.VERSION .. L("  翻译桥: ") .. onOff(ChatBridgeDB.enabled))
        print(PREFIX .. L("正在翻译的频道: ") .. (#names > 0 and table.concat(names, L("、")) or L("无"))
            .. L("（右键聊天框上的「翻译」按钮可以改）"))
        print(PREFIX .. L("发消息: 聊天框里打中文，按 Ctrl+T（或末尾打 ;;），等一下再 Ctrl+V、回车。"))
        print(PREFIX .. L("命令: /cb config | /cb usage | /cb account | /cb page | /cb reset | /cb team | /cb all | /cb test | /cb on | /cb off"))
        print(PREFIX .. L("翻译由电脑上的免费程序完成，下载：wow.husen.ca"))
    end
end
