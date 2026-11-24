# 魔兽聊天翻译（ChatBridge Translator）· 魔兽世界翻译插件

> **别只会打 ty 和 gg。** 队友的黑话秒懂，你打中文就能发出地道英文——在美服，聊得像本地人。
>
> **Chat like a local.** Read every WoW slang term in Chinese, reply in natural English.

**World of Warcraft chat translator (English ⇄ Chinese) for WoW Forever / US servers** — 魔兽世界美服 / 魔兽世界「无限」聊天实时翻译插件。

官网与下载：<https://wow.husen.ca> · CurseForge：[ChatBridge Translator](https://www.curseforge.com/wow/addons/chatbridge-translator) · 教程：[安装](https://wow.husen.ca/guide/install.html) ·
[免费接 Gemini](https://wow.husen.ca/guide/free-gemini.html) · [魔兽黑话缩写大全](https://wow.husen.ca/guide/wow-slang.html)

队友的英文和黑话（LoS、brez、pat、WTS、COD……）实时翻成中文，直接显示在游戏聊天框旁的「翻译」页里；
你打中文按 `Ctrl+T`，发出去的是美服玩家的说法，英文先填回聊天框，回车发送。支持魔兽世界「无限」（Interface 16001）。
新电脑在启动器里可以领免费 200 条。

## 它怎么工作

游戏插件不能联网。`addon/ChatBridge` 插件把收到的聊天编码成屏幕左上角的一小条色块，
Windows 程序 `app/` 读这条色块的像素、解码出聊天、翻译后把译文盖在游戏里的翻译页上。
程序**只读屏幕像素**，不读游戏内存、不改游戏文件；自动粘贴英文时会模拟一次 `Ctrl+V`，回车由你自己按。

## 两种翻译来源

1. **线上翻译服务（默认）**：作者维护的服务，针对魔兽黑话专门调教过，按实际用量收成本价，充值兑换码在
   <https://wow.husen.ca> 购买。服务端代码、提示词和黑话词表不在本仓库里。
2. **自带模型（免费）**：在启动器里点「自带模型」，填任何 OpenAI 兼容接口（OpenAI、DeepSeek、本机 Ollama /
   LM Studio……）的地址、密钥和模型名。打开后翻译直接发到你自己的模型，不经过线上服务、不扣额度；
   密钥只保存在你自己电脑的配置文件里。自带模型用的是通用提示词，没有线上服务的黑话调教。

## 从源码运行 / 打包

需要 Windows 和 Python 3.12。

```
python app/main.py              # 启动器
python app/main.py --overlay    # 只跑翻译
pip install pyinstaller pillow
python build.py                 # 打包，产物在 dist/
```

插件测试：`pip install lupa`，然后 `python tests/test_addon.py`。

发布用的安装包由 GitHub Actions（`.github/workflows/build.yml`）从本仓库源码自动构建。

## 隐私

- 线上服务只收到要翻译的那一句话和一个匿名设备编号，不存聊天内容。
- 自带模型模式下，聊天只发给你自己填的地址。
- 启动时会检查更新（安装时可以关掉）。完整说明：<https://wow.husen.ca/privacy.html>

## 代码签名政策 · Code signing policy

Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).
（申请审核中；通过前的安装包还没有签名。）

- 安装包只由本仓库的 GitHub Actions 从公开源码构建，每次发版由维护者人工批准后签名。
- Committers and reviewers: [senbuilds](https://github.com/senbuilds)
- Approvers: [senbuilds](https://github.com/senbuilds)
- Privacy policy: <https://wow.husen.ca/privacy.html> (shown in the installer; the update check can be turned off there,
  and the online translation service can be replaced with the user's own model in the launcher).

## 许可

GPL-3.0，见 LICENSE。本项目与暴雪娱乐无关；魔兽世界是暴雪娱乐的商标。
