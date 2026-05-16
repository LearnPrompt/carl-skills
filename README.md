<div align="center">

# 🦞 Carl Skills

#### 我自己真实跑通、反复用过的AI工作流，都收在这里

[![License](https://img.shields.io/badge/License-MIT-3B82F6?style=for-the-badge)](./LICENSE)
[![Skills](https://img.shields.io/badge/Skills-11-10B981?style=for-the-badge)](#-skills)
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

| 名字 | 一句话 | 安装来源 |
|---|---|---|
| 🎯 [**humanize-ppt**](#humanize-ppt) | 先把资料变成人愿意听的PPT主线，再交给下游工具生成页面 | [canonical](https://github.com/LearnPrompt/humanize-ppt) |
| 🛰️ [**ai-news-radar**](#ai-news-radar) | 24小时AI/科技信息雷达，持续追踪高信号更新 | [canonical](https://github.com/LearnPrompt/ai-news-radar) |
| 🏘️ [**skillrush-town**](#skillrush-town) | 淘金小镇，追踪ClawHub Top100和潜力Skill变化 | [canonical](https://github.com/LearnPrompt/skillrush-town) |
| ✍️ [**x-article-publisher**](#x-article-publisher) | 把飞书或本地Markdown文章发布到X Articles草稿 | [canonical](https://github.com/LearnPrompt/x-article-publisher-skill) |
| 🔁 [**skill-sync**](#skill-sync) | 把多端Agent skills整理成一个可信来源 | [canonical](https://github.com/LearnPrompt/skill-sync) |
| 🧩 [**cc-harness-skills**](#cc-harness-skills) | 一套Agent工作底座，记忆、压缩、协调、验证、主动模式一起用 | [canonical](https://github.com/LearnPrompt/cc-harness-skills) |

---

## 📦 安装方式

### 装一个skill

比如只装Humanize PPT：

```bash
hermes skills install https://raw.githubusercontent.com/LearnPrompt/humanize-ppt/main/SKILL.md --yes
```

### 装这个目录里的全部可安装skill

```bash
git clone https://github.com/LearnPrompt/carl-skills.git
cd carl-skills
python3 scripts/install_all_hermes_skills.py --dry-run
python3 scripts/install_all_hermes_skills.py --yes
```

`--dry-run`只打印安装命令，不改本机环境。确认没问题后再执行`--yes`。

---

## 🧠 这个仓库的逻辑

Carl Skills现在是**catalog-first**。

也就是说，这里不再把每个`SKILL.md`复制一份做镜像。每个skill都有自己的canonical repo，源码、README、demo、issue、更新都在那里维护。Carl Skills只负责把它们放进一个好找、好读、Agent也能读的目录里。

这样有两个好处：

- 更新Humanize PPT这类独立skill时，只需要改它自己的主仓库
- Agent批量安装时，仍然可以通过`registry.json`找到全部canonical install URL

如果以后有只属于Carl Skills合集的skill，再把`SKILL.md`直接放在这个仓库里。

---

## ✨ Skills

<a id="-skills"></a>

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

---

## 🗂 Registry

`registry.json`是这个仓库的机器可读目录。它记录：

- 哪些skill已经可安装
- 每个skill的canonical repo在哪里
- 同一套skill是否属于同一个`suite`
- 应该从哪个`raw_skill_url`安装
- 当前索引到哪个`source_commit`

如果你只装一个skill，不需要关心registry。直接装它的raw `SKILL.md`就行。

如果你想让Agent理解「Carl Skills里到底有什么」，或者想批量安装，就看registry。

---

## 🛣 Roadmap

- [x] 建立catalog-first registry
- [x] 收录LearnPrompt下已公开且带`SKILL.md`的skill项目
- [x] 将Humanize PPT安装入口改回canonical repo，避免collection mirror版本同步问题
- [x] 将CC Harness Skills按suite统一分组
- [ ] 给每个active skill补真实案例截图和更具体的使用入口
- [ ] 如果未来出现只属于Carl Skills合集的skill，再在本仓库内放置collection-native `SKILL.md`

---

## 🌟 关于

我是Carl，日常主要做AI工具实测、内容创作、工作流搭建和Agent协作。

这个仓库不会追求「技能数量很多」，更在意一件事：这些skill是不是真的在真实工作里跑过，能不能让下一个Agent少走一点弯路。

如果你也在把AI从「聊天窗口」推进到真实工作流里，欢迎直接clone、安装、改造。

---

<div align="center">

[MIT License](./LICENSE) · Real-world AI workflows for creators

Made by [LearnPrompt](https://github.com/LearnPrompt)

</div>
