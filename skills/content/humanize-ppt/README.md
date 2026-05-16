# Humanize PPT

> PPT不是资料容器，是观众状态改变器。

Humanize PPT的主仓库是：

<https://github.com/LearnPrompt/humanize-ppt>

## 安装

```bash
hermes skills install https://raw.githubusercontent.com/LearnPrompt/humanize-ppt/main/SKILL.md --yes
```

## 为什么Carl Skills里不再镜像SKILL.md

Carl Skills现在采用catalog-first逻辑：

- Humanize PPT的`SKILL.md`只在canonical repo维护。
- Carl Skills通过`registry.json`记录安装入口和source commit。
- 用户安装时直接从Humanize PPT主仓库读取`SKILL.md`。

这样更新Humanize PPT时，不需要强制复制一份到Carl Skills，避免两个版本漂移。
