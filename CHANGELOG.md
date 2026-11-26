# 更新日志 · Changelog

程序安装包在官网下载：<https://wow.husen.ca>（启动器里点「检查更新」可以直接升级）。游戏插件也在 [CurseForge](https://www.curseforge.com/wow/addons/chatbridge-translator)。
日期按 UTC。

## 1.4.0 · 插件 2.9（2026-11-26）
- 队伍里的接话翻得更准：翻小队 / 团队 / 副本 / 密语时，会参考同一场对话刚才的几句（最多 3 句、2 分钟内）。公共频道、公会、说 / 喊不带。这几句只用来帮忙看懂，翻完就丢，不多扣额度。
- 物品 / 技能链接显示成你客户端里的名字：老外发的 [Arcanite Reaper] 在中文客户端里直接是 [奥金斧]（繁体客户端是台服译名）。
- 发话时可以带物品链接：聊天框里 Shift+点击插入的链接，按 Ctrl+T 翻译后还是能点的链接。
- 自带模型：直接选服务商（DeepSeek、OpenAI、Gemini、Claude、通义千问、智谱、硅基流动、OpenRouter、本机 Ollama / LM Studio），粘贴密钥就能用。
- 繁体：游戏名统一叫「永恆」。
- 有新版本时提示更显眼：启动器顶部出现横幅和「立即更新」按钮，游戏里的翻译页也会提示一句。
- Party replies use the last few lines as context; item/spell links show your client's localized names; links survive Ctrl+T; provider presets for bring-your-own-model.

## 1.3.5（2026-11-26）
- 翻译页会提示漏读：游戏画面左上角被别的窗口挡住、游戏最小化或卡顿时，程序没读到的聊天会提示「漏了几条」，并计入匿名连接统计。
- The translation page now tells you when chat lines were missed (game corner covered, minimized or stuttering).

## 1.3.4 · 插件 2.8（2026-11-26）
- 新增繁体中文：程序、游戏插件按 Windows 系统语言自动用简体或繁体，启动器底部可以手动切换；繁体用台湾的说法，图标是「譯」。
- 繁体模式下，游戏内翻译用台湾玩家的说法和台服译名（補師、滅團、奧格瑪、死亡礦坑……）；打繁体中文按 Ctrl+T 也能翻成英文。
- 队友插件的自动播报（Questie 任务进度、DBM、Details 等）不再翻译，也不显示在翻译页，不扣额度。
- Traditional Chinese (Taiwan wording) for the app, the addon and the translations; addon broadcast spam is skipped.

## 1.3.3（2026-11-25）
- 在「游戏设置」里用「浏览…」选完游戏目录、或者换游戏版本时，插件会自动装上。
- The addon is installed automatically after choosing the game folder or switching game version.

## 1.3.2（2026-11-25）
- 修正：游戏里「还能翻多少条」按你实际的单价算（之前买的额度显示少了）。
- Fix: the in-game "lines left" uses the server's per-account number.

## 1.3.1（2026-11-25）
- 第一次打开启动器、找到游戏时自动装好插件，不用再点「安装插件」。
- The addon is installed automatically on first launch.

## 1.3.0（2026-11-25）
- 启动器换了新界面：ChatBridge 标题、状态条、余额和游戏两张卡片；兑换和游戏设置放进小窗口。
- New launcher layout.

## 1.2.9（2026-11-25）
- 兑换框可以填推广码（绑定后送一份额度）。
- Promo codes in the redeem box.

## 1.2.8（2026-11-24）
- 启动器里可以直接「反馈问题」，可选附带诊断信息（版本、连接情况、各频道消息数，不含聊天内容）。
- 匿名报告连接状态（只有数字），用来统计「装好了却用不起来」的情况；界面和官网风格统一。
- In-app feedback with optional diagnostics; anonymous connection status; new look.

## 1.2.7（2026-11-24）
- 新电脑可以领取免费 200 条（30 天内有效）；正式名称 ChatBridge Translator。
- Free 200-line trial for new PCs.

## 1.2.6 · 插件 2.7（2026-11-16）
- 程序没开时，翻译页中间显示醒目的提示卡。
- A clear notice in the middle of the page when the app is not running.

## 1.2.5 · 插件 2.6（2026-11-16）
- 程序没开时，提示去官网下载。
- Point to the download page when the app is not running.

## 1.2.4 · 插件 2.5（2026-11-15）
- 背包、地图、专业等游戏窗口盖住翻译页时，译文自动让开；「已连上」的提示只显示一次。
- Translations step aside when a game window covers the page.

## 1.2.3（2026-11-14）
- 游戏里不再显示价格和兑换框；「用量」显示还能翻多少条。
- No prices or redeem box inside the game; usage shows lines left.

## 1.2.2（2026-11-14）
- 「翻译程序没开」的提示只在程序真的没开时显示。

## 1.2.1（2026-11-14）
- 翻译页半透明、鼠标滚轮翻看之前的消息、名字按职业染色；游戏先开、程序后开也能贴合翻译页。

## 1.2.0（2026-11-14）
- 首次公开：游戏插件 + Windows 程序，可以用线上翻译服务，也可以接自己的 OpenAI 兼容模型。
- Initial public release.
