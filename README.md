<div align="center">

# 🦞 Carl Skills

#### 我自己真实跑通、反复用过的AI工作流，都收在这里

[![License](https://img.shields.io/badge/License-MIT-3B82F6?style=for-the-badge)](./LICENSE)
[![Workflows](https://img.shields.io/badge/Workflows-15-3B82F6?style=for-the-badge)](#-skills)
[![Skills](https://img.shields.io/badge/Skills-20-10B981?style=for-the-badge)](./registry.json)
[![Registry](https://img.shields.io/badge/Registry-catalog--first-F59E0B?style=for-the-badge)](./registry.json)
[![First Star](https://img.shields.io/badge/First_Star-Humanize_PPT-8B5CF6?style=for-the-badge)](https://github.com/LearnPrompt/humanize-ppt)

![Claude Code](https://img.shields.io/badge/Claude_Code-Skill-D97706?style=flat-square&logo=anthropic&logoColor=white)
![Codex](https://img.shields.io/badge/Codex-Skill-10B981?style=flat-square&logo=openai&logoColor=white)
![OpenCode](https://img.shields.io/badge/OpenCode-Skill-3B82F6?style=flat-square)
![OpenClaw](https://img.shields.io/badge/OpenClaw-Skill-8B5CF6?style=flat-square)
![Hermes](https://img.shields.io/badge/Hermes-Agent-EC4899?style=flat-square)

</div>

我每天会试AI工具，也会把它们塞进真实工作里，选题、写稿、做评测、整理资料、改PPT、发文章、维护Obsidian，让Hermes/Codex/OpenClaw这类Agent真的帮上忙。

很多东西不是想出来的，是一遍遍跑出来的。

所以这个仓库只做一件事：把那些已经跑顺的AI工作流，整理成下次还能交给Agent继续用的skill。

- **Skills**，Agent能直接加载的结构化工作流，安装后可以在Claude Code、Codex、OpenCode、OpenClaw、Hermes里复用
- **Registry**，给Agent和脚本读的机器目录，记录每个skill从哪个canonical repo安装
- **Catalog**，给人看的入口，告诉你每个skill适合干什么、不适合干什么

---

## 📋 目录

| 名字 | Star | 一句话 | 安装来源 |
|---|---|---|---|
| 🛰️ [**ai-news-radar**](#ai-news-radar) | [![](https://img.shields.io/github/stars/LearnPrompt/ai-news-radar?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/ai-news-radar) | 24小时AI/科技信息雷达，持续追踪高信号更新 | [canonical](https://github.com/LearnPrompt/ai-news-radar) |
| 🪚 [**鲁班 luban**](#luban) | [![](https://img.shields.io/github/stars/LearnPrompt/luban-skill?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/luban-skill) | 把能用的skill打磨成能被装、能传播、能验证的公共资产 | [canonical](https://github.com/LearnPrompt/luban-skill) |
| 🎯 [**humanize-ppt**](#humanize-ppt) | [![](https://img.shields.io/github/stars/LearnPrompt/humanize-ppt?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/humanize-ppt) | 先把资料变成人愿意听的PPT主线，再交给下游工具生成页面 | [canonical](https://github.com/LearnPrompt/humanize-ppt) |
| 🧩 [**cc-harness-skills**](#cc-harness-skills) | [![](https://img.shields.io/github/stars/LearnPrompt/cc-harness-skills?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/cc-harness-skills) | 一套Agent工作底座，记忆、压缩、协调、验证、主动模式一起用 | [canonical](https://github.com/LearnPrompt/cc-harness-skills) |
| 🏘️ [**skillrush-town**](#skillrush-town) | [![](https://img.shields.io/github/stars/LearnPrompt/skillrush-town?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/skillrush-town) | 淘金小镇，追踪ClawHub Top100和潜力Skill变化 | [canonical](https://github.com/LearnPrompt/skillrush-town) |
| 📚 [**carl-weread**](#carl-weread) | [![](https://img.shields.io/github/stars/LearnPrompt/carl-weread?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/carl-weread) | 微信读书行动型阅读教练，按当前问题推荐今天读的一小节 | [canonical](https://github.com/LearnPrompt/carl-weread) |
| 🔪 [**庖丁 paoding**](#paoding) | [![](https://img.shields.io/github/stars/LearnPrompt/paoding-skill?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/paoding-skill) | 零API拆解任何博主的爆款打法，蒸馏成可安装的内容教练 | [canonical](https://github.com/LearnPrompt/paoding-skill) |
| 🤝 [**搭子 dazi**](#partner-skill) | [![](https://img.shields.io/github/stars/LearnPrompt/partner-skill?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/partner-skill) | 让Claude和Codex结对开发，分工、互查、合并一条线 | [canonical](https://github.com/LearnPrompt/partner-skill) |
| ✍️ [**x-article-publisher**](#x-article-publisher) | [![](https://img.shields.io/github/stars/LearnPrompt/x-article-publisher-skill?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/x-article-publisher-skill) | 把飞书或本地Markdown文章发布到X Articles草稿 | [canonical](https://github.com/LearnPrompt/x-article-publisher-skill) |
| 🔁 [**skill-sync**](#skill-sync) | [![](https://img.shields.io/github/stars/LearnPrompt/skill-sync?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/skill-sync) | 把多端Agent skills整理成一个可信来源 | [canonical](https://github.com/LearnPrompt/skill-sync) |
| 🧭 [**Skill 瘦身**](#skill-slimming) | [![](https://img.shields.io/github/stars/LearnPrompt/carl-skills?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/carl-skills) | 把Agent能力整理成全局、项目和按需触发 | [collection-native](./skills/ops/skill-slimming/SKILL.md) |
| 🏮 [**阿福 afu**](#afu-llm-todo) | [![](https://img.shields.io/github/stars/LearnPrompt/afu-llm-todo?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/afu-llm-todo) | Obsidian收件箱管家，Inbox到Wiki到待办到周历一条线 | [canonical](https://github.com/LearnPrompt/afu-llm-todo) |
| 📜 [**蔡伦 cailun**](#cailun) | [![](https://img.shields.io/github/stars/LearnPrompt/cailun-skill?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/cailun-skill) | 把对话里聊出来的结论，3秒造成一页能传阅的单文件纸 | [canonical](https://github.com/LearnPrompt/cailun-skill) |
| ⛰️ [**愚公 yugong**](#loop-engineering) | [![](https://img.shields.io/github/stars/LearnPrompt/loop-engineering?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/loop-engineering) | Loop工程方法论，把模糊目标改造成带验证门的自动循环 | [canonical](https://github.com/LearnPrompt/loop-engineering) |
| 🎨 [**Irasutoya配图**](#carl-irasutoya-illustrations) | [![](https://img.shields.io/github/stars/LearnPrompt/carl-irasutoya-illustrations?style=flat&label=%E2%98%85&color=555)](https://github.com/LearnPrompt/carl-irasutoya-illustrations) | 给中文文章配会吐槽的Irasutoya反应人物正文配图 | [canonical](https://github.com/LearnPrompt/carl-irasutoya-illustrations) |

---

## 📦 安装方式

### 装一个skill

比如只装这个仓库原生维护的Skill 瘦身：

```bash
npx skills add LearnPrompt/carl-skills --skill skill-slimming -g
```

这条命令会读取仓库目录来发现Skill，但只把`skill-slimming`这一个完整目录安装到Agent，不会把Carl Skills里的其他Skill一起启用。

Skill 瘦身包含本地复审网页、状态服务和参考合同，不能只下载raw `SKILL.md`。因此它暂不支持Hermes的单文件raw安装；否则能看到提示词，却缺少实际运行层。

### 装这个目录里的全部可安装skill

```bash
git clone https://github.com/LearnPrompt/carl-skills.git
cd carl-skills
python3 scripts/install_all_hermes_skills.py --dry-run
python3 scripts/install_all_hermes_skills.py --yes
```

`--dry-run`只打印安装命令，不改本机环境。确认没问题后再执行`--yes`。脚本会明确跳过需要整目录安装、而Hermes当前只能按raw `SKILL.md`处理的条目。

---

## 🧠 这个仓库的逻辑

Carl Skills现在是**catalog-first**，同时允许少量只属于这个合集的collection-native skill。

也就是说，这里不会把外部skill的`SKILL.md`复制一份做镜像。已有独立canonical repo的skill，源码、README、demo、issue、更新仍在那里维护；只属于Carl Skills合集的能力，才直接放在本仓库的`skills/`目录。

这样有两个好处：

- 更新Humanize PPT这类独立skill时，只需要改它自己的主仓库
- Agent批量安装时，仍然可以通过`registry.json`找到全部canonical install URL
- Skill 瘦身这类collection-native skill可以直接在同一仓库长期迭代和安装

每个条目的真实安装方式以`registry.json`为准：单文件Skill使用`raw_skill_url`，带脚本和资源的Skill使用`install_mode: skill-folder`与`install_command`。

---

## ✨ Skills

<a id="-skills"></a>

<table>
<tr><td>

<a id="ai-news-radar"></a>

### 🛰️ ai-news-radar

> *"AI圈一天发太多东西，真正有用的信号得有人替你扫出来。"*

AI News Radar是一个24小时AI/科技信息雷达。它把RSS、OPML、GitHub feed、来源健康检查、GitHub Actions和网页展示串起来，用来持续追踪高信号更新。

它不是普通资讯收藏夹，更像是给内容创作者和研究型Agent准备的上游信号源。

**适合**

- 每天需要找AI工具、模型、产品、论文的新动向
- 想维护自己的信息源池，而不是只刷平台推荐
- 做选题前需要先看到上游发生了什么

**不适合**

- 只想临时查一条新闻
- 不准备维护来源质量
- 只看中文二手总结

[![Repo](https://img.shields.io/badge/GitHub-ai--news--radar-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/ai-news-radar)
[![Install](https://img.shields.io/badge/Install-raw_SKILL.md-10B981?style=flat-square)](https://raw.githubusercontent.com/LearnPrompt/ai-news-radar/master/skills/ai-news-radar/SKILL.md)

→ [canonical repo](https://github.com/LearnPrompt/ai-news-radar) · [raw SKILL.md](https://raw.githubusercontent.com/LearnPrompt/ai-news-radar/master/skills/ai-news-radar/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="luban"></a>

### 🪚 鲁班 luban

> *"Skill不是写完就算完，要经得住安装、触发、执行和传播。"*

鲁班负责把一个“能用”的Skill打磨成可以公开交付的产品。它会检查真实来源、用户路径、触发描述、目录结构、安装方式和验证证据，再通过访行、过尺和回炉收紧缺口。

**适合**

- 已经有一个Skill，但安装、说明或验证还不完整
- 准备把内部工作流发布到GitHub
- 想让Skill经过结构化体检和真实试跑

**不适合**

- 还没有明确能力，只想从零头脑风暴
- 只是修一处普通代码问题
- 不准备提供真实安装和运行证据

```bash
npx skills add LearnPrompt/luban-skill -g
```

[![Repo](https://img.shields.io/badge/GitHub-luban--skill-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/luban-skill)
[![Install](https://img.shields.io/badge/Install-npx-10B981?style=flat-square)](https://github.com/LearnPrompt/luban-skill)

→ [canonical repo](https://github.com/LearnPrompt/luban-skill) · [SKILL.md](https://github.com/LearnPrompt/luban-skill/blob/master/skills/luban/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="humanize-ppt"></a>

### 🎯 humanize-ppt

> *"PPT不是资料容器，是观众状态改变器。"*

很多AI工具都能生成PPT，但它们经常只是把资料塞进页面里。页数不少，信息不少，听众却不知道为什么要继续听。

Humanize PPT做的是更前面的那一步：先把原始资料整理成一条人愿意听下去的演示路径。它会先处理听众、场景、状态转移、叙事张力、页级意图，再把结构交给下游工具生成页面。

**适合**

- 已经有一堆资料，但PPT主线很散
- 想把文章、报告、产品介绍改成演讲型deck
- 做AI生成PPT前，先把观众路径和页面意图定住

**不适合**

- 只想一键生成漂亮模板
- 只需要改字体、配色、版式
- 原始资料还完全没有方向

[![Repo](https://img.shields.io/badge/GitHub-humanize--ppt-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/humanize-ppt)
[![Install](https://img.shields.io/badge/Install-raw_SKILL.md-10B981?style=flat-square)](https://raw.githubusercontent.com/LearnPrompt/humanize-ppt/main/SKILL.md)

→ [canonical repo](https://github.com/LearnPrompt/humanize-ppt) · [raw SKILL.md](https://raw.githubusercontent.com/LearnPrompt/humanize-ppt/main/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="cc-harness-skills"></a>

### 🧩 CC Harness Skills

> *"这不是六个散装skill，是一套Agent工作底座。"*

CC Harness Skills来自同一个仓库，适合一起用。它们处理的不是某个具体内容任务，而是Agent长期工作时绕不开的底层问题：怎么记忆、怎么压缩上下文、怎么协调多Agent、怎么验证完成声明、怎么做轻量主动模式。

所以在Carl Skills里统一加`cc-harness-`前缀，并放在同一个suite里。

| 名字 | 用来干什么 |
|---|---|
| `cc-harness-dream-memory` | 把近期日志、会话和记忆文件整理成可持续使用的主题记忆 |
| `cc-harness-kairos-lite` | 构建轻量主动模式，包含定时检查、睡眠间隔和过期保护 |
| `cc-harness-memory-extractor` | 从近期对话里提取长期记忆，避免把临时状态写成永久事实 |
| `cc-harness-structured-context-compressor` | 把长会话压缩成可续接摘要，保留当前工作和下一步 |
| `cc-harness-swarm-coordinator` | 拆分多Agent工作，让协调者专注集成而不是淹没在探索里 |
| `cc-harness-verification-gate` | 做只读验证，检查完成声明和测试结果是不是真的 |

**适合**

- 长时间跑Agent任务
- 多Agent协作
- 需要跨会话延续上下文
- 不想让Agent越跑越乱

**不适合**

- 只想完成一次简单问答
- 不需要记忆、压缩、验证和调度

[![Repo](https://img.shields.io/badge/GitHub-cc--harness--skills-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/cc-harness-skills)
[![Suite](https://img.shields.io/badge/Suite-6_skills-8B5CF6?style=flat-square)](./registry.json)

→ [canonical repo](https://github.com/LearnPrompt/cc-harness-skills) · [registry suite](./registry.json)

</td></tr>
</table>

<table>
<tr><td>

<a id="skillrush-town"></a>

### 🏘️ skillrush-town

> *"不是所有skill都值得装，但值得装的东西应该被更早发现。"*

Skillrush Town，淘金小镇，用来追踪ClawHub Top100下载快照和潜力AI Skill变化。它把每天的市场变化沉淀下来，方便看出哪些skill在涨、哪些只是昙花一现。

这更像一个AI Skill市场雷达，而不是单纯榜单页面。

**适合**

- 观察ClawHub生态和skill增长趋势
- 给自己的Skill产品找参考对象
- 做AI Agent生态选题和案例研究

**不适合**

- 只想找一个马上能用的单点工具
- 不关心skill市场变化

[![Repo](https://img.shields.io/badge/GitHub-skillrush--town-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/skillrush-town)
[![Pages](https://img.shields.io/badge/GitHub_Pages-live-3B82F6?style=flat-square)](https://learnprompt.github.io/skillrush-town/)
[![Install](https://img.shields.io/badge/Install-raw_SKILL.md-10B981?style=flat-square)](https://raw.githubusercontent.com/LearnPrompt/skillrush-town/main/skills/skillrush-town/SKILL.md)

→ [canonical repo](https://github.com/LearnPrompt/skillrush-town) · [GitHub Pages](https://learnprompt.github.io/skillrush-town/) · [raw SKILL.md](https://raw.githubusercontent.com/LearnPrompt/skillrush-town/main/skills/skillrush-town/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="carl-weread"></a>

### 📚 carl-weread

> *"把微信读书从「读了多少」改成「今天哪个问题可以被读懂一点」。"*

carl-weread是一个微信读书行动型阅读教练。它根据你当前卡住的问题，交叉书架、笔记和章节，推荐一本书里今天读的一小节，并把阅读收束成一张读后行动卡，Markdown回流，周阅读行动复盘。

它解决的不是「读什么书」，而是「今天读哪一小节、读完做什么」。

**适合**

- 微信读书里囤了很多书，但阅读和手头问题脱节
- 想让每次阅读都落成一个可执行动作
- 希望Agent帮你做书架、笔记、章节的交叉推荐

**不适合**

- 只想要一串书单推荐
- 不用微信读书
- 不想登录微信读书API

```bash
npx skills add LearnPrompt/carl-weread -g
```

[![Repo](https://img.shields.io/badge/GitHub-carl--weread-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/carl-weread)
[![Install](https://img.shields.io/badge/Install-skill_folder-10B981?style=flat-square)](https://github.com/LearnPrompt/carl-weread)

→ [canonical repo](https://github.com/LearnPrompt/carl-weread) · [SKILL.md](https://github.com/LearnPrompt/carl-weread/blob/main/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="paoding"></a>

### 🔪 庖丁 paoding

> *"不是模仿一篇爆文，而是拆出这个创作者稳定重复的刀法。"*

庖丁在不依赖平台API的前提下，读取公开内容样本，拆解选题、标题、结构、语气和转化机制，再把规律蒸馏成可安装、可盲评的内容教练。

**适合**

- 想系统拆解小红书、公众号、抖音等创作者
- 需要从多篇样本提取稳定方法，而不是抄一篇
- 想把拆解结果继续做成内容Skill

**不适合**

- 只提供一条无法访问的内容链接
- 想批量抓取私人或受限数据
- 只需要普通文章摘要

```bash
npx skills add LearnPrompt/paoding-skill -g
```

[![Repo](https://img.shields.io/badge/GitHub-paoding--skill-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/paoding-skill)
[![Install](https://img.shields.io/badge/Install-npx-10B981?style=flat-square)](https://github.com/LearnPrompt/paoding-skill)

→ [canonical repo](https://github.com/LearnPrompt/paoding-skill) · [SKILL.md](https://github.com/LearnPrompt/paoding-skill/blob/master/skills/paoding/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="partner-skill"></a>

### 🤝 搭子 dazi

> *"我的 Claude Code 和 Codex 天下第一好。"*

搭子让Claude Code和Codex围绕同一份目标事实源协作：一边负责高价值规划、交互判断和复核，另一边负责主要实现、命令验证和持续推进，并保留可继续执行的交接与验收记录。

**适合**

- 需要Claude与Codex分工完成成规模开发
- 希望规划、实现和Review由不同视角完成
- 长任务需要Goal、PR和Verification闭环

**不适合**

- 一次性的小改动或普通问答
- 只有一个Agent可用
- 不准备验证子任务的真实输出

```bash
npx skills add LearnPrompt/partner-skill --skill partner-skill -g
```

[![Repo](https://img.shields.io/badge/GitHub-partner--skill-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/partner-skill)
[![Install](https://img.shields.io/badge/Install-skill_folder-10B981?style=flat-square)](https://github.com/LearnPrompt/partner-skill)

→ [canonical repo](https://github.com/LearnPrompt/partner-skill) · [SKILL.md](https://github.com/LearnPrompt/partner-skill/blob/main/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="x-article-publisher"></a>

### ✍️ x-article-publisher

> *"文章写完，不该卡在复制、粘贴、丢格式这一步。"*

X Article Publisher负责把飞书或本地Markdown文章发布到X Articles草稿里，尽量保留富文本结构、封面图和媒体位置。

它解决的是发布链路里最烦人的那段：内容已经写完了，但平台编辑器不听话。

**适合**

- 飞书或Markdown文章已经定稿，要发到X Articles
- 文章里有封面、图片、视频、分割线等结构
- 希望Agent帮你把发布动作跑完，而不是只给一段文本

**不适合**

- 没有X Premium/Articles权限
- 还没登录X或不想使用浏览器自动化
- 只是发一条普通短推

[![Repo](https://img.shields.io/badge/GitHub-x--article--publisher-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/x-article-publisher-skill)
[![Install](https://img.shields.io/badge/Install-raw_SKILL.md-10B981?style=flat-square)](https://raw.githubusercontent.com/LearnPrompt/x-article-publisher-skill/main/skills/x-article-publisher/SKILL.md)

→ [canonical repo](https://github.com/LearnPrompt/x-article-publisher-skill) · [raw SKILL.md](https://raw.githubusercontent.com/LearnPrompt/x-article-publisher-skill/main/skills/x-article-publisher/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="skill-sync"></a>

### 🔁 skill-sync

> *"Skill多了以后，最大的问题不是没有工具，是到处都有一份。"*

Skill Sync用来审计Codex、Claude、OpenClaw、OpenCode、本地workspace和共享目录里的skills，把重复、冲突、过期安装整理成一个可信来源。

它适合在你已经装了一堆skill之后，用来做一次大扫除。

**适合**

- 多个Agent环境里都有skills，已经分不清谁是最新
- 想把本地skills整理成统一源头
- 迁移或公开前，需要先做一次清点和去重

**不适合**

- 你只有一两个skill
- 只是临时安装，不准备长期维护

[![Repo](https://img.shields.io/badge/GitHub-skill--sync-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/skill-sync)
[![Install](https://img.shields.io/badge/Install-raw_SKILL.md-10B981?style=flat-square)](https://raw.githubusercontent.com/LearnPrompt/skill-sync/main/SKILL.md)

→ [canonical repo](https://github.com/LearnPrompt/skill-sync) · [raw SKILL.md](https://raw.githubusercontent.com/LearnPrompt/skill-sync/main/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="skill-slimming"></a>

### 🧭 Skill 瘦身（skill-slimming）

> *"装Skill很容易，难的是让正确的能力只在正确的项目、正确的时机出现。"*

Skill 瘦身把已经在本地控制台中跑通的治理过程，整理成一个可直接安装的完整Skill目录。它先只读盘点Codex、Claude Code等宿主中的Skills、插件和MCP，再用来源证据、实际使用信号和两阶段上下文成本，给出全局、项目、按需触发三档建议。瘦掉的是无效全局暴露和上下文负担，不是粗暴删除能力。

它不会看到低频就删除。首轮只生成审计和本地复审页面，用户选择会自动保存并在下次恢复；用户说“我选好了”后，Agent直接读取持久状态并生成独立执行计划。`RARE_CRITICAL`、60天观察、可逆归档和恢复入口都写进了同一份治理合同。

复审页支持按状态快速分段、筛选结果批量设置和核心/保守全局分布条，apply之后的回执还能在页面顶部只读回显。配套的`probe`命令会顺手查出断链symlink、跨机器绝对路径和宿主配置里已被禁用的条目，把治理漂移在下一轮复审前暴露出来。

**适合**

- 装了很多Skill，已经分不清安装数、暴露数、内容版本和唯一名称
- 想知道哪些能力来自系统、插件、项目或用户目录
- 想把Skill改成全局、项目或先询问再加载的触发空壳
- 想用`/doctor`、`/context`、session日志和fresh-session A/B核对上下文成本

**不适合**

- 只想安装一个新Skill
- 想跳过复审直接批量删除
- 希望保存选择后不经计划与确认就自动执行

```bash
npx skills add LearnPrompt/carl-skills --skill skill-slimming -g
```

[![Repo](https://img.shields.io/badge/GitHub-carl--skills-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/carl-skills)
[![Install](https://img.shields.io/badge/Install-skill_folder-10B981?style=flat-square)](./skills/ops/skill-slimming/SKILL.md)

→ [SKILL.md](./skills/ops/skill-slimming/SKILL.md) · [registry entry](./registry.json)

</td></tr>
</table>

<table>
<tr><td>

<a id="afu-llm-todo"></a>

### 🏮 阿福 afu

> *"收件箱不是仓库，是门口；东西进来以后要知道往哪里走。"*

阿福是Obsidian收件箱管家，把临时资料整理成Wiki、待办卡和周历，并保留处理日志与恢复路径。它强调本地运行、可追溯状态和不误删源笔记。

**适合**

- Obsidian收件箱长期堆积，资料与待办混在一起
- 想把Inbox稳定流转到Wiki和周计划
- 需要本地LLM和可回滚处理记录

**不适合**

- 不使用Obsidian
- 想直接永久删除原始笔记
- 只需要一次性的文件分类

```bash
npx skills add LearnPrompt/afu-llm-todo -g
```

[![Repo](https://img.shields.io/badge/GitHub-afu--llm--todo-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/afu-llm-todo)
[![Install](https://img.shields.io/badge/Install-npx-10B981?style=flat-square)](https://github.com/LearnPrompt/afu-llm-todo)

→ [canonical repo](https://github.com/LearnPrompt/afu-llm-todo) · [SKILL.md](https://github.com/LearnPrompt/afu-llm-todo/blob/main/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="cailun"></a>

### 📜 蔡伦 cailun

> *"对话里聊出来的结论，应该马上变成一张能传阅的纸。"*

蔡伦把已经明确的内容造成一页零依赖HTML：文字是真实内容，版式固定而克制，打开就能读、截图和分享，不把信息藏进复杂交互。

**适合**

- 把聊天结论快速整理成单页说明
- 需要离线可打开、方便截图的HTML
- 做方案纸、决策纸、复盘纸或交接纸

**不适合**

- 需要复杂Web应用或后台系统
- 内容本身还没有形成结论
- 只想套一个炫技模板

```bash
npx skills add LearnPrompt/cailun-skill -g
```

[![Repo](https://img.shields.io/badge/GitHub-cailun--skill-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/cailun-skill)
[![Install](https://img.shields.io/badge/Install-npx-10B981?style=flat-square)](https://github.com/LearnPrompt/cailun-skill)

→ [canonical repo](https://github.com/LearnPrompt/cailun-skill) · [SKILL.md](https://github.com/LearnPrompt/cailun-skill/blob/master/skills/cailun/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="loop-engineering"></a>

### ⛰️ 愚公 yugong

> *"真正的自动化不是多跑几轮提示词，而是先把循环的停止判据和护栏装好。"*

愚公把“让Agent自己反复做某件事”的愿望装配成Loop Spec：goal、intake、trigger、worktree、maker/checker、state、verification和guardrails都有明确落点，最后交付可运行命令，但不替用户扣下启动扳机。

**适合**

- 反复维护、triage、升级或内容流水线
- 需要Agent自主迭代到可验证目标
- 想让Claude Code和Codex共用一份Loop事实源

**不适合**

- 普通一次性任务
- 从零编写一个普通Skill
- 没有可判定的完成条件

```bash
npx skills add LearnPrompt/loop-engineering --skill loop-engineering -g
```

[![Repo](https://img.shields.io/badge/GitHub-loop--engineering-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/loop-engineering)
[![Install](https://img.shields.io/badge/Install-skill_folder-10B981?style=flat-square)](https://github.com/LearnPrompt/loop-engineering)

→ [canonical repo](https://github.com/LearnPrompt/loop-engineering) · [SKILL.md](https://github.com/LearnPrompt/loop-engineering/blob/main/skills/loop-engineering/SKILL.md)

</td></tr>
</table>

<table>
<tr><td>

<a id="carl-irasutoya-illustrations"></a>

### 🎨 Irasutoya 配图

> *"不是给每一段配图，而是给文章里最值钱的判断配一个会吐槽的人。"*

Irasutoya配图从中文文章中挑出值得视觉化的判断，设计白底、圆润、有梗图感的反应人物和生图提示词，并通过角色DNA保持跨图一致。

**适合**

- 公众号、博客、Notion文章需要正文配图
- 想用人物反应强化观点和节奏
- 同一角色需要跨多张图保持一致

**不适合**

- 需要复刻Irasutoya原作素材
- 只想生成装饰性背景图
- 不提供文章上下文和关键判断

```bash
npx skills add LearnPrompt/carl-irasutoya-illustrations -g
```

[![Repo](https://img.shields.io/badge/GitHub-carl--irasutoya--illustrations-111827?style=flat-square&logo=github)](https://github.com/LearnPrompt/carl-irasutoya-illustrations)
[![Install](https://img.shields.io/badge/Install-npx-10B981?style=flat-square)](https://github.com/LearnPrompt/carl-irasutoya-illustrations)

→ [canonical repo](https://github.com/LearnPrompt/carl-irasutoya-illustrations) · [SKILL.md](https://github.com/LearnPrompt/carl-irasutoya-illustrations/blob/main/SKILL.md)

</td></tr>
</table>

---

## 🗂 Registry

`registry.json`是这个仓库的机器可读目录。它记录：

- 哪些skill已经可安装
- 每个skill的canonical repo在哪里
- 同一套skill是否属于同一个`suite`
- 应该用`raw_skill_url`还是完整`skill-folder`安装
- 外部canonical skill当前索引到哪个`source_commit`
- collection-native skill在本仓库的哪个`canonical_path`
- 20个实际Skill如何通过`catalog_anchor`映射到上面的15个工作流卡片

如果你只装一个skill，不需要关心registry。单文件Skill可以装raw `SKILL.md`；带脚本和资源的Skill要用目录感知安装器并通过`--skill`只选择目标项。

如果你想让Agent理解「Carl Skills里到底有什么」，或者想批量安装，就看registry。README里的每一行目录都必须对应一张同名卡片；Registry可以把同一个套装拆成多个实际Skill，但必须共享同一个`catalog_anchor`。

---

## 🛣 Roadmap

- [x] 建立catalog-first registry
- [x] 收录LearnPrompt下已公开且带`SKILL.md`的skill项目
- [x] 将Humanize PPT安装入口改回canonical repo，避免collection mirror版本同步问题
- [x] 将CC Harness Skills按suite统一分组
- [x] 收录班门家族（鲁班/庖丁/搭子/蔡伦/愚公/阿福/Irasutoya配图）并为每项提供独立卡片
- [x] 保证15个工作流目录、15张README卡片和20个Registry Skill自动对账
- [x] 收录首个collection-native skill：Skill 瘦身
- [ ] 给每个active skill补真实案例截图和更具体的使用入口

---

## 🌟 关于

我是Carl，日常主要做AI工具实测、内容创作、工作流搭建和Agent协作。

这个仓库不会追求「技能数量很多」，更在意一件事：这些skill是不是真的在真实工作里跑过，能不能让下一个Agent少走一点弯路。

如果你也在把AI从「聊天窗口」推进到真实工作流里，欢迎直接clone、安装、改造。

---

<div align="center">

[MIT License](./LICENSE) · Real-world AI workflows for creators

</div>

---

<div align="center">

**更多好用 Skill · More Skills** → [learnprompt.pro/skills](https://learnprompt.pro/skills/)

[鲁班·Skill打磨](https://github.com/LearnPrompt/luban-skill) · [庖丁·博主蒸馏](https://github.com/LearnPrompt/paoding-skill) · [蔡伦·对话造纸](https://github.com/LearnPrompt/cailun-skill) · [阿福·LLM Todo](https://github.com/LearnPrompt/afu-llm-todo) · [愚公·Loop工程](https://github.com/LearnPrompt/loop-engineering) · [搭子·结对开发](https://github.com/LearnPrompt/partner-skill) · [AI雷达·零API资讯](https://github.com/LearnPrompt/ai-news-radar)

[淘金小镇·ClawHub日榜](https://github.com/LearnPrompt/skillrush-town) · [Skill 瘦身·能力治理](./skills/ops/skill-slimming/SKILL.md) · [Irasutoya·正文配图](https://github.com/LearnPrompt/carl-irasutoya-illustrations) · [Humanize PPT·演讲系统](https://github.com/LearnPrompt/humanize-ppt) · [CC Harness·六件套](https://github.com/LearnPrompt/cc-harness-skills) · [微信读书教练](https://github.com/LearnPrompt/carl-weread) · [X Article发布](https://github.com/LearnPrompt/x-article-publisher-skill)

<sub>**[LearnPrompt](https://github.com/LearnPrompt) 出品** · 公众号「卡尔的AI沃茨」 · [X @aiwarts](https://x.com/aiwarts)</sub>

</div>
