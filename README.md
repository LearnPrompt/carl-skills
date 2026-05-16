<div align="center">

# Carl Skills

> Real-world AI workflows for creators.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-catalog--first-D6A85A)](#registry)
[![Humanize PPT](https://img.shields.io/badge/first%20star-humanize--ppt-B88746)](https://github.com/LearnPrompt/humanize-ppt)

**真实AI工作流技能库：把选题、写作、评测、资料整理、PPT、Agent协作、飞书和Obsidian工作流，沉淀成可以交给AI Agent复用的skills。**

[Start here](#start-here) · [Install](#install) · [Registry](#registry) · [Workflow map](#workflow-map)

</div>

---

## 这不是prompt合集

Carl Skills只做一件事：

**把真实工作里跑通过的AI方法，变成下次还能交给Agent继续用的skill。**

这里不是把每个skill复制一份做备份，而是做一个公开目录：

- **Canonical repo**：每个skill自己的主仓库，负责源码、README、demo、issue和更新。
- **Carl Skills registry**：这个仓库的`registry.json`，负责把所有LearnPrompt系skill集中索引起来。
- **Install URL**：安装时优先指向canonical repo里的`SKILL.md`，避免两边版本不同步。

---

## Start here

| Skill | Status | Canonical repo | Install source |
|---|---|---|---|
| [Humanize PPT](https://github.com/LearnPrompt/humanize-ppt) | active-star | `LearnPrompt/humanize-ppt` | canonical `SKILL.md` |
| [AI News Radar](https://github.com/LearnPrompt/ai-news-radar) | active | `LearnPrompt/ai-news-radar` | canonical `skills/ai-news-radar/SKILL.md` |
| [Skillrush Town](https://github.com/LearnPrompt/skillrush-town) | active | `LearnPrompt/skillrush-town` | canonical `skills/skillrush-town/SKILL.md` |
| [X Article Publisher](https://github.com/LearnPrompt/x-article-publisher-skill) | active | `LearnPrompt/x-article-publisher-skill` | canonical `skills/x-article-publisher/SKILL.md` |
| [Skill Sync](https://github.com/LearnPrompt/skill-sync) | active | `LearnPrompt/skill-sync` | canonical `SKILL.md` |
| [CC Harness Skills](https://github.com/LearnPrompt/cc-harness-skills) | active | `LearnPrompt/cc-harness-skills` | canonical `skills/*/SKILL.md` |

> `AnythingWeb`当前没有发现`SKILL.md`，先作为related project记录在registry里，不放进可安装skill列表。

---

## Install

### Install one skill

```bash
hermes skills install https://raw.githubusercontent.com/LearnPrompt/humanize-ppt/main/SKILL.md --yes
```

### Install all installable skills in this catalog

```bash
git clone https://github.com/LearnPrompt/carl-skills.git
cd carl-skills
python3 scripts/install_all_hermes_skills.py --dry-run
python3 scripts/install_all_hermes_skills.py --yes
```

`--dry-run`只打印安装命令，不改本机环境。

---

## Registry

`registry.json`保留。它的作用不是替代Hermes的`SKILL.md`，而是给Agent和脚本一个机器可读目录：

- 哪些skill已经可安装；
- 每个skill的canonical repo在哪里；
- 应该从哪个`raw_skill_url`安装；
- 当前索引到哪个`source_commit`。

所以：

- **单独安装某个skill**：不依赖registry，直接安装它的canonical `raw_skill_url`。
- **从Carl Skills批量安装/让Agent发现全部skill**：依赖registry。
- **更新Humanize PPT**：只要主仓库`SKILL.md`更新，用户通过canonical URL安装就会拿到新版；Carl Skills只需要在想更新目录展示或`source_commit`时同步registry，不需要复制一份`SKILL.md`。

---

## Workflow map

Carl Skills follows a simple loop:

1. **Capture**：保存链接、论文、文档、评论、产品更新和灵感。
2. **Test**：用真实任务测试AI工具，而不是复述发布说明。
3. **Shape**：把混乱材料整理成选题卡、脚本、草稿、PPT大纲或评测表。
4. **Publish**：从草稿推进到文章、视频、README、demo page或项目卡片。
5. **Remember**：把可重复部分沉淀成skill，让下一个Agent能继续用。

---

## Roadmap

- [x] 建立catalog-first registry。
- [x] 收录LearnPrompt下已公开且带`SKILL.md`的skill项目。
- [x] 将Humanize PPT安装入口改回canonical repo，避免collection mirror版本同步问题。
- [ ] 给每个active skill补更短的人类介绍页和真实使用案例。
- [ ] 如果未来出现只属于Carl Skills合集的skill，再在本仓库内放置collection-native `SKILL.md`。

---

## English

Carl Skills is a catalog of real-world AI workflows for creators.

It indexes installable LearnPrompt skills and points agents to each skill's canonical `SKILL.md`, so updates happen in one place instead of drifting across duplicated mirrors.
