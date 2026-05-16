<div align="center">

# Carl Skills

> Real-world AI workflows for creators.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-building-D6A85A)](#roadmap)
[![Humanize PPT](https://img.shields.io/badge/first%20star-humanize--ppt-B88746)](https://github.com/LearnPrompt/humanize-ppt)

<br>

**真实AI工作流技能库，把选题、写作、评测、资料整理、PPT、Agent协作、飞书和Obsidian工作流，沉淀成可以交给AI Agent复用的skills。**

<br>

[Start here](#start-here) · [Skills](#skills) · [Workflow map](#workflow-map) · [Install](#install) · [Safety](#safety)

</div>

---

## 这不是prompt合集

我每天都会试AI工具，也会把它们用在真实工作里：选题、写稿、做评测、整理资料、改PPT、处理飞书文档、维护Obsidian素材库、让Hermes/Codex/OpenClaw这类Agent真正帮上忙。

问题是，很多跑通的经验很容易消失。

一次飞书里的讨论，一次Hermes帮我跑通的流程，一次Codex改项目踩过的坑，一次PPT主线被改顺的瞬间，如果不沉淀下来，下次还会重新来一遍。

所以Carl Skills只做一件事：

**把真实工作里跑通过的AI方法，变成下次还能交给Agent继续用的skill。**

---

## Start here

| Skill | Status | What it helps you do |
|---|---|---|
| [Humanize PPT](skills/content/humanize-ppt/) | ![Active Star](https://img.shields.io/badge/status-active--star-B88746) | Turn raw material into a presentation people actually want to listen to |
| AI Tool Reviewer | ![Building](https://img.shields.io/badge/status-building-D6A85A) | Test AI tools with real tasks instead of rewriting launch notes |
| Feishu Content Factory | ![Building](https://img.shields.io/badge/status-building-D6A85A) | Turn Feishu notes, comments, and drafts into publishable content |
| Obsidian Topic Planner | ![Building](https://img.shields.io/badge/status-building-D6A85A) | Turn an Obsidian vault into a topic and publishing system |
| Carl Humanizer | ![Building](https://img.shields.io/badge/status-building-D6A85A) | Make AI-written text sound closer to a real creator |
| Paper to PPT | ![Planned](https://img.shields.io/badge/status-planned-6B7280) | Turn papers and PDFs into presentation-ready outlines |
| Topic Radar | ![Paused](https://img.shields.io/badge/status-paused-8A8175) | Monitor upstream signals for future topics |

---

## Skills

### Humanize PPT

> PPT不是资料容器，是观众状态改变器。

Humanize PPT先把资料变成人愿意听的演示路径，再交给下游工具生成页面。它不是通用PPT生成器，也不是文本润色器；它负责在生成页面之前，先把观众、状态转移、叙事张力、页级意图和素材需求整理清楚。

- Canonical repo: <https://github.com/LearnPrompt/humanize-ppt>
- Collection mirror: [`skills/content/humanize-ppt/`](skills/content/humanize-ppt/)
- Agent entry: [`skills/content/humanize-ppt/SKILL.md`](skills/content/humanize-ppt/SKILL.md)

---

## Workflow map

Carl Skills follows a simple loop:

1. **Capture**：保存链接、论文、文档、评论、产品更新和灵感。
2. **Test**：用真实任务测试AI工具，而不是复述发布说明。
3. **Shape**：把混乱材料整理成选题卡、脚本、草稿、PPT大纲或评测表。
4. **Publish**：从草稿推进到文章、视频、README、demo page或项目卡片。
5. **Remember**：把可重复部分沉淀成skill，让下一个Agent能继续用。

---

## Install

### Install one skill

```bash
hermes skills install https://raw.githubusercontent.com/LearnPrompt/carl-skills/main/skills/content/humanize-ppt/SKILL.md --yes
```

### Install bundled skills from this repo

```bash
git clone https://github.com/LearnPrompt/carl-skills.git
cd carl-skills
python3 scripts/install_all_hermes_skills.py --dry-run
python3 scripts/install_all_hermes_skills.py --yes
```

`--dry-run`只打印安装命令，不改本机环境。确认无误后再去掉`--dry-run`。

---

## Registry

`registry.json`是这个仓库的机器可读目录。它记录每个skill的状态、路径、主仓库和安装入口。

状态规则：

- `active-star`：主推明星，已经有独立仓库/README/demo/可传播截图。
- `active`：能稳定使用，可以放进主入口。
- `building`：正在做，适合放Roadmap，不包装成已完成。
- `planned`：有明确需求和定位，但还没开始工程化。
- `paused`：暂缓，不抢第一阶段注意力。

---

## Roadmap

第一阶段先把母舰仓库做成可用入口：

- [x] 建立README和registry。
- [x] 收录Humanize PPT作为第一颗明星skill。
- [x] 写清楚单个skill和合集安装方式。
- [ ] 补AI Tool Reviewer。
- [ ] 补Feishu Content Factory。
- [ ] 补Obsidian Topic Planner。
- [ ] 补Carl Humanizer。
- [ ] 为每个active skill补真实案例和截图。

---

## Safety

这个仓库永远不应该包含：

```text
API keys
cookies
tokens
.env
真实私有文件
邮箱内容
浏览器登录态
私有飞书文档正文
个人Obsidian vault原文
```

私有工作流可以沉淀为结构。私有数据必须留在私有环境里。

---

## English

Carl Skills is a collection of real-world AI workflows for creators.

It turns repeatable parts of real work—topic planning, content production, AI tool review, presentation shaping, Feishu/Obsidian workflows, and agent collaboration—into reusable skills that an AI agent can run again next time.
