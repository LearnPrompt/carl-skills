---
name: carl-file-organizer
description: 文件整理：整理下载目录或任意散乱文件夹,先出方案再执行。用户说「整理下载目录」「收拾一下 Downloads」「下载文件夹太乱了」「帮我归档文件」「文件太多了理一理」「整理一下这个文件夹」「organize my downloads」「clean up my downloads folder」「tidy this folder」「sort these files」「my downloads is a mess」时使用。它跑 carl-file-organizer 命令行工具,只对工具标为待判断且允许改道的文件做语义判断,任何移动、进废纸篓或删除都要用户在聊天里明确说执行才做。
---

# Carl File Organizer

你是这套工具的操作员,不是决策者。它自己已经用规则把大部分文件的去向定好了,你只处理剩下那部分需要看文件名和上下文才能判断的,把判断交回去给用户确认,最后由用户点头才落地。

## 什么时候用,什么时候不用

用户想整理某个文件夹里的散件,尤其是下载目录,用它。
用户要清系统缓存、清 node_modules、找磁盘大户这类整机存储清理,那不是这个工具的活,直接说明白,不要硬套。
用户只是问某个文件该放哪,不需要跑工具,直接回答就行。

## 第一步,确认工具在

跑 `carl-file-organizer --version`。不存在就把后面所有命令都换成这个前缀:

```
uvx --from git+https://github.com/LearnPrompt/carl-file-organizer carl-file-organizer <子命令...>
```

两条都不行,告诉用户怎么装,停下,不要自己想办法绕过去。

## 第二步,只读扫描

```bash
carl-file-organizer plan <目录> --lang zh
```

目录不写默认 `~/Downloads`,用户没指定就用默认值,不要自己猜别的路径。用户说英文目录名就把 `--lang` 换成 `en`。

这一步只读,不动任何文件。产物落在目标目录下的管理目录里:中文是 `<目录>/00_下载目录管理/`,英文是 `<目录>/00_File_Organizer/`,包含 `plan.json` 和 `report.html`。

## 第三步,读 plan.json,只转述不判断

plan.json 的结构里,`actions` 是全部候选动作,`groups` 是几选一的选择题,`approved_action_ids` 和 `overrides` 目前都是空的,等你和用户一起填。

先看 `summary`,按 `tier` 报一下总数:多少条常规移动(`routine`)、多少组压缩包配对和重复副本、多少条可再生产物、多少条静置未到期或者被判定为禁刀区 / 正被占用 / 被外部引用(这些统称 hold,一律不能批准,只读原因),多少条待判断。

`groups` 里的每一组都带着 `options`,每个选项自带一份 `action_ids`。你的活是把这些选项摆给用户看,让用户选,选完直接把那个选项的 `action_ids` 整体抄进批准名单,不要自己去 `actions` 里挑单条、不要自己拼凑,这是唯一被允许的映射方式。

## 第四步,只对待判断且可改道的做语义判断

`actions` 里 `reroutable` 为 true 的那些才是你能碰的待判断项,其余的一律原样转述,不要建议改动。

对每一条,只根据文件名、扩展名、大小、修改时间去判断它更适合放进 `plan.json` 的 `names` 里哪个 key,不要打开文件、不要读内容。名字里带着密钥、密码、令牌、证书、身份信息一类线索的,不要自己往敏感区搬,工具已经在敏感判断上有独立的一套规则,拿不准就原样跳过,交给用户自己在页面上处理。

拿不准分类的,不写判断,让它留在收件箱的待判断区,不要为了给出答案硬猜。

把你的判断整理成一张表给用户看,列出文件名、你判给哪个分区、一句理由,然后停下等用户回复,不要替用户拍板。

## 第五步,写批准文件

用户确认之后,把 `plan.json` 原样复制成同一个管理目录下的 `approved.json`,只改这几处,其余字段一个字都不能动:

- `approved_action_ids`:用户同意的动作 id,包括他直接同意的常规移动、他在组里选的那个选项的 `action_ids`、以及他同意进废纸篓的可再生产物和冷存候选。永远不要往这里加 `kind` 是 `delete` 的 id,除非用户明确说要永久删除并且你确认过命令行会带 `--allow-permanent-delete`。
- `overrides`:上一步整理出的 `{action_id, destination_key}` 列表,`destination_key` 必须原样取自 `plan.json` 的 `names`,不要自己编路径。
- `approved_at`、`approved_by`:当前时间和 `agent:<你的名字>`。

工具会按 `id` 重新核对每一条,任何字段被改过都会被当成篡改直接拒绝执行,所以不要顺手改别的地方。

## 第六步,执行门禁

先跑一遍 dry-run,把输出原样贴给用户:

```bash
carl-file-organizer apply <管理目录>/approved.json --dry-run
```

只有用户在聊天里明确说了执行、apply、动手、可以了这类话,才去掉 `--dry-run` 跑真的一遍。用户说看看、先别动、再想想,都不算授权,继续停在只读或 dry-run。

几条硬规矩,任何情况都不能破:

- 永远不用 `rm`、`mv`、`trash`、`osascript` 这类命令自己动文件,所有动作必须走 `carl-file-organizer apply`。
- 永远不在命令里加 `--allow-permanent-delete`,这个开关只能由用户自己在终端里加。
- 工具拒绝执行、报错或者把某一批标为 refused 的,原样把那句话转告用户,不要自己想办法绕开或者重试出别的路径。
- `overrides` 之外没有第二条改道通道,不要直接编辑 `destination`。

## 第七步,回报

按这个顺序说完就停,不要多说:

- 这一轮做到了哪一步:只读盘点 / 已 dry-run / 已执行。
- 移动了多少项,进废纸篓多少项,跳过和被拒绝的各多少项、为什么。
- 待判断里你判了几条、用户改了几条、还剩几条没处理。
- 没碰过的范围:禁刀区、静置期没到的、正被占用或被外部引用的。
- `plan.json`、`approved.json`、`audit.jsonl` 的路径。
- 一句话提醒:`carl-file-organizer undo` 能把这轮移动的都挪回去,`carl-file-organizer clear-tags` 能清掉页面留下的 Finder 标签。
