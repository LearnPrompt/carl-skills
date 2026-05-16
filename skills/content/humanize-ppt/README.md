# Humanize PPT

> PPT不是资料容器，是观众状态改变器。

Humanize PPT是Carl Skills收录的第一颗明星skill。它的任务不是直接生成漂亮页面，而是在PPT/HTML Slide生成之前，先把原始资料整理成一条人愿意听下去的演示路径。

## 它解决什么问题

AI可以很快生成PPT，但它经常把资料当成容器来塞：功能点很多，页面也不少，可听众不知道为什么要继续听。

Humanize PPT先做大纲导演：

- 观众是谁；
- 观众听之前是什么状态；
- 听完以后应该变成什么状态；
- 中间最大的认知张力是什么；
- 每一页如何推动状态转移；
- 哪些素材应该交给下游PPT/HTML工具继续生成。

## 安装

```bash
hermes skills install https://raw.githubusercontent.com/LearnPrompt/carl-skills/main/skills/content/humanize-ppt/SKILL.md --yes
```

## 安装后第一句话

```text
请使用Humanize PPT Skill，先问我要原始资料、目标听众、演示场景和时长，然后帮我输出deck_brief、ast_outline、slide_plan、speaker_intent和asset_manifest。不要直接生成PPT页面，先把观众状态转移路径整理清楚。
```

## Canonical repo

Humanize PPT的主仓库仍然是：

<https://github.com/LearnPrompt/humanize-ppt>

Carl Skills里保留这份可安装镜像，是为了让合集仓库本身也能被Agent使用，而不是只给人看跳转链接。
