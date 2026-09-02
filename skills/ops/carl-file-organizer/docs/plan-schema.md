# plan.json 契约（schema_version 2）

审核页、本地服务、执行器、undo 和 Agent 都只读这一个文件，谁也不去猜结构。
样例在仓库根的 `tests/fixtures/carl_file_organizer/plan-v2-sample.json`，
本文每一节都能在那份样例里找到对应的行；
`tests/test_cfo_fixture_contract.py` 按本文的约束逐条断言，改结构就要一起改这三处。

一句话记住整份文件：`actions` 是候选清单，`groups` 是几选一的题目，
`approved_action_ids` 是唯一的批准名单，`overrides` 是唯一的改道通道。

## 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | int | 固定 2。执行器见到别的值直接拒绝。 |
| `generator` | object | `{name, version}`，version 取自 `carl_file_organizer.__version__`。 |
| `created_at` | string | 计划时刻，带时区。跟随 `now`，所以同一个 `--now` 跑两遍出来的计划是一样的。 |
| `generated_at` | string | 真实生成时刻（墙钟），带时区。排查问题时看这一个。 |
| `now` | string | 静置期的计算基准。apply 阶段不重算，复现问题时用 `--now` 固定它。 |
| `lang` | string | `zh` 或 `en`，本次输出用的语言。 |
| `lang_source` | string | `flag` / `dotfile` / `env` / `existing-dirs` / `apple-languages` / `posix-locale` / `default`。 |
| `profile` | object | `{name, source, dotfile, hash}`。`source` 是 `builtin` 或 `builtin+dotfile`，`hash` 是合并后 profile 的短摘要，apply 时对不上只提醒不中断。 |
| `source_root` / `source_root_portable` | string | 绝对路径只出现在 plan.json 里；清单、日志、审计一律写 `$HOME/...` 形式。 |
| `managed_dir` / `managed_dir_portable` | string | 可见的管理目录，中文是 `00_下载目录管理`，英文是 `00_File_Organizer`。plan.json 和 report.html 都落在这里。 |
| `names` | object | 本次解析出来的 key → 相对路径，例如 `library.docs.pdf` → `20_知识库/文档资料/PDF`。页面和 Agent 直接显示这里的值，不必回头读 profile。 |
| `capabilities` | object | `{trash_backend, finder_tags, permanent_delete_offered}`。`trash_backend` 是 `finder`（macOS）/ `win32`（Windows 回收站）/ `gio`（Linux）/ `none`，为 none 时废纸篓选项不可批准。 |
| `scan_policy` | object | 本次扫描的边界与上限，写下来是为了让人知道哪些地方根本没看。除设计里那几项，还有 `allow_referenced` 与 `skipped{hidden,symlinks,partitions,artifacts}` 两个计数用的字段。 |
| `disk` | object | 卷容量与目标占用，移动同卷释放 0 字节这句话也写在里面。 |
| `mess` | object | 这个目录现在有多乱，见下。 |
| `summary` | object | 见下。 |
| `pinned` | array | 本次生效的常驻白名单，名字或 glob。 |
| `actions` | array | 候选动作，见下。 |
| `groups` | array | 成组的选择题，见下。 |
| `notes` | object 或 null | Agent 写的人话说明，见下。生成时是 null。 |
| `approved_action_ids` | array | 页面、服务和 Agent 唯一需要填的字段。 |
| `overrides` | array | 待判断项的改道，见下。 |
| `approved_at` | string 或 null | 批准时刻。 |
| `approved_by` | string 或 null | `html-static` / `serve` / `agent:<名字>`。 |

`summary` 里 `entries` / `files` / `dirs` / `bytes` 数的是扫描到的顶层条目，
`by_tier` 和 `by_kind` 数的是 action 条数（同一个文件可能同时有移动和处置两条候选，所以两组数不相等是正常的）。
`potential_reclaimable_bytes` 按 subject 去重后累加，只是个信息量，不代表建议；
`proposed_reclaimed_bytes` 在生成时永远是 0，执行完才按实际写进审计。

`by_color` 是 `{green|yellow|red: {actions, bytes}}`。`actions` 按条数算，
所有颜色加起来等于 `len(actions)`；`bytes` 是这些 action 的 `size_bytes` 之和，
跟 `by_tier` 一样会重复计入同一个文件（一个文件可以同时有一条绿色移动和一条黄色处置），
它描述的是形状不是总量。

## mess：这个目录有多乱

```json
"mess": {
  "score": 59,
  "color": "yellow",
  "color_source": "rule",
  "counts": {"loose": 12, "aging": 1, "pending": 2, "groups": 3, "top_dirs": 3},
  "reason": {"zh": "...", "en": "..."}
}
```

| 字段 | 说明 |
|---|---|
| `score` | 0 到 100，越大越乱。只决定进度条长度，不决定颜色。 |
| `color` | `green` / `yellow` / `red`。 |
| `color_source` | `rule` 或 `notes`，谁定的这个颜色。 |
| `rule_color` | 只在被 notes 覆盖后出现，保存规则原本算出来的颜色。 |
| `line` | 只在 notes 给了一句话时出现。 |
| `counts` | `loose` 顶层散件数、`aging` 静置中、`pending` 待判断（按 subject 去重）、`groups` 组数、`top_dirs` 顶层目录数。 |
| `reason` | `{zh, en}`，规则给的一句话。 |

阈值与分数公式在 `references/tiers.md`，代码里对应 `planner.MESS_THRESHOLDS`。
Agent 可以在 notes.json 里覆盖 `color`，覆盖后 `color_source` 变成 `notes`，
规则的答案退到 `rule_color`。

## action 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | `sha256(subject_id \0 kind \0 destination_portable)[:16]`。同一个文件的移动、废纸篓、永久删除是三条不同 id。 |
| `subject_id` | string | `sha256(realpath \0 subject_kind \0 size \0 mtime_ns)[:16]`。执行前实时重算，对不上就跳过。 |
| `kind` | string | `move` / `trash` / `delete` / `hold`。 |
| `subject_kind` | string | `file` 或 `dir`。目录整个搬，不拆内部结构。 |
| `source` / `source_portable` | string | 源路径。 |
| `filename` | string | 条目名，目录移动后保持原名。 |
| `destination` / `destination_portable` | string 或 null | 目标路径；`trash` / `delete` / `hold` 为 null。 |
| `destination_key` | string 或 null | `names` 里的 key，页面按 key 显示分区名。 |
| `size_bytes` / `modified_ns` / `age_hours` | number | 体积、修改时间、已静置小时数。 |
| `rule` | string | 判定依据，取值见下表。 |
| `reason` | object | `{zh, en}`，一句人话说清为什么。 |
| `detail` | object 或 null | `{zh, en}`，补充证据，例如静置了多久。 |
| `confidence` | number | 0 到 1。未知扩展名是 0.55，扩展名规则命中是 0.98。 |
| `tier` | string | `routine` / `sensitive` / `regenerable` / `duplicate` / `cold` / `aging` / `pinned` / `forbidden` / `in_use` / `referenced`。 |
| `group_id` | string 或 null | 属于某个组时填组 id。 |
| `approvable` | bool | `hold` 恒为 false。执行器见到不可批准的 id 出现在名单里直接抛错。 |
| `reroutable` | bool | 只有 rule 属于 `unknown-ext` / `dir:pending` / `dir:derivative` 的移动才为 true，也只有它们能被 `overrides` 改道。 |
| `default_selected` | bool | 生成时一律 false，勾选由人来做。 |
| `requires` | array | `delete` 是 `["allow-permanent-delete"]`。 |
| `reclaims_bytes` | number | 移动是 0，废纸篓和永久删除是条目体积。 |
| `restore_method` | object 或 null | `{zh, en}`。移动给一条可直接执行的 mv，废纸篓写放回原处，永久删除写清楚不可恢复。 |
| `tags` | array | 扫描到的非临时 Finder 标签。 |
| `hints` | array | 只提示不改判定，例如 `git-repo`、`derivative-copy:-worktree-`。 |
| `color` | string | `green` / `yellow` / `red`。页面的按钮跟着它走，所以它由 kind、tier 与 reroutable 三个字段算出来，永远不手写。判定表在 `references/tiers.md`。 |
| `hold_reason` | object 或 null | hold 时必填，`{zh, en}`，静置类还带 `ready_at`，禁刀区带 `label`，常驻带 `pattern`（命中的那条白名单）。 |
| `guard` | object | 保底层的取证结果，见下。 |
| `dir_stats` | object 或 null | 目录才有，`{files, bytes, truncated}`，`truncated` 为 true 表示统计到上限就停了。 |

### rule 取值

`ext:<后缀>`、`sensitive:exact` / `sensitive:suffix` / `sensitive:marker` / `sensitive:manual`、
`dir:pending`、`dir:derivative`、`pair`、`tag:<标签>`、`name:<规则 id>`、`conflict`、
`unknown-ext`、`dup:sha256`、`dup:name`、`regenerable:<目录名>`、`cold:large`、`cold:installer`、
`hold:aging`、`hold:pinned`、`hold:forbidden`、`hold:in_use`、`hold:referenced`。

`conflict` 是目标位置已经被占了，条目转进重复待确认区并带上时间戳改名。
时间戳插在扩展名前面，所以改完还是能双击打开：
`quarterly-report.pdf` → `00_收件箱/重复待确认/quarterly-report-2026-09-02_12-00-00.pdf`，
`release.tar.gz` → `release-2026-09-02_12-00-00.tar.gz`。
目录和没有扩展名的条目保持 `<原名>-<时间戳>`。

### guard 字段

保底层查的是谁还在用这个路径，命中就把条目变成 hold，让人自己去改引用。

| 键 | 内容 |
|---|---|
| `open_by` | `[{command, pid}]`，来自 lsof。命中即 tier `in_use`，不可降级。 |
| `referenced_in` | `[{file, line, form}]`，来自 launchd、cron、shell 配置和用户自己加的引用文件。命中即 tier `referenced`，`plan --allow-referenced` 可降级成黄字提示。 |
| `incoming_symlinks` | 指进这个条目的软链路径。 |
| `shape` | 目录形态，例如 `git-dir`、`git-worktree`、`venv`、`dotenv`、`node-project`；文件是 `executable`、`shebang`。worktree 直接进 hold，其余只加提示。 |

除这四个必填键，`guard` 还可能带两个可选键：`open_by_status` 为 `unknown` 表示这台机器上没有 lsof 或者 lsof 超时了，
「没人开着它」这句话只是查不出来而不是查过；`uncommitted` 是 git 仓库未提交的条目数。读的人按有则用、无则忽略处理。

lsof 报出来的 Spotlight 一类只读守护进程（`mdworker`、`quicklookd`、`fseventsd` 等）不算占用。
刚下载完的文件几秒内就会被索引，把它们算进去等于整个下载目录永远动不了。

## group 字段

| 字段 | 说明 |
|---|---|
| `group_id` | 组 id，成员 action 的 `group_id` 指向它。 |
| `kind` | `pair`（压缩包与解压目录）、`duplicate`（重复文件）、`regenerable`（构建产物）。 |
| `tier` | pair 与 duplicate 都是 `duplicate`，regenerable 是 `regenerable`。 |
| `stem` | 归组用的词干。 |
| `evidence` | pair 是 `name`；duplicate 是 `sha256` 或 `name-pattern`；regenerable 是 `basename`。 |
| `sha256` | 只有内容验证过的重复组才有值。 |
| `members` | 成员的 `subject_id` 列表。 |
| `member_labels` | subject_id → 给人看的名字。 |
| `reason` | `{zh, en}`。 |
| `options` | 选项数组，见下。 |
| `color` | 恒为 `yellow`。组是一道选择题，不管选哪个都会有东西被处置，这就是需要人看一眼的定义。 |
| `default_choice` | 单选框的默认位置。压缩包配对默认留目录；名字像副本但内容没比对过的重复组默认都保留。 |
| `potential_bytes` | 采纳默认选项能腾出的字节数。 |

`options[]` 里每项是 `{key, label{zh,en}, action_ids[], requires[]}`。
`action_ids` 是组选择映射到批准名单的唯一通道，页面和 Agent 都不许自己推导；
里面出现的每个 id 都在 `actions` 里，而且 `approvable` 一定为 true。
只要选项里包含永久删除，`requires` 就带 `allow-permanent-delete`。

压缩包配对给四个选项：都保留、留目录、留压缩包、留目录并永久删除压缩包。
重复组给每个成员一个留它的选项外加一个都保留。
构建产物组只有全部进废纸篓和全部永久删除两项，不选就等于保留。

## notes：Agent 写的人话

规则给的理由是每条规则一句固定话，读起来像通知。真正有用的是「这是什么、
为什么在这儿、删了会怎样」，那要一个看过这个目录的 Agent 来写。
notes 就是这一层，它只加文字，不改任何决策。

Agent 写一份 notes.json：

```json
{
  "folder_line": "这个目录基本是上周做提案时下载的东西",
  "mess": {"color": "yellow", "line": "看着乱，其实一半是同一批素材"},
  "actions": {
    "0112233445566a7b": {
      "what": "第三方给的合同 PDF 扫描件",
      "why": "扩展名规则命中，归到文档资料",
      "if_removed": "邮箱里还有原件，丢了能要回来"
    }
  },
  "groups": {
    "dup-3ba91c04": {"what": "同一份素材导了两次", "why": "内容哈希一致", "if_removed": "留一份就够"}
  }
}
```

然后跑：

```bash
python3 scripts/organize.py build <plan.json> --notes notes.json
```

合并结果写回 `plan.notes`：

| 字段 | 说明 |
|---|---|
| `schema` | 固定 1。 |
| `folder_line` | 整个目录一句话，或 null。 |
| `mess` | `{color?, line?}`，清理过的那份。 |
| `actions` | `action_id` → `{what?, why?, if_removed?}`，只留这三个键。 |
| `groups` | `group_id` → 同上。 |
| `warnings` | 合并时发现的问题，每条一句话。 |

规矩就三条：

1. **只收三个句子。** `what`、`why`、`if_removed` 之外的键一律丢掉并记一条 warning，
   所以 notes 里写 `"approvable": true` 或 `"destination": "..."` 不会有任何效果。
2. **不认识的 id 只提醒。** 上一次扫描留下的 notes 拿来配这次的计划，多出来的条目
   会被跳过并记一条 warning，不会让整份报告生不出来。
3. **唯一能改的是目录颜色。** `mess.color` 会覆盖 `plan.mess.color`，规则的答案退到
   `rule_color`，`color_source` 记成 `notes`。条目的 `color` 一个字都不能改，
   因为页面的按钮跟着它走，那是安全边界。

单句超过 600 字会被截断，不会被丢掉。合并两次是替换不是叠加，
改完一句重跑一遍不会留下上一版。

Python 里直接用：

```python
from carl_file_organizer.notes import merge_notes
plan = merge_notes(plan, notes)          # 返回新的一份，原来的不动
```

报告怎么渲染是 `build_report.py` 的事，这里只保证 plan.json 里有一份干净的 `notes`。
没有 notes 时报告退回规则文案，一样能出。

## overrides

```json
{"action_id": "0112233445566a7b", "destination_key": "work.db.sql"}
```

只对 `reroutable` 为 true 的 action 生效，`destination_key` 必须是 `names` 里已有的 key。
执行器拿到 override 后自己重算目标路径并校验仍在 root 之内，任何写字面路径的尝试都会被拒。
待判断区的下拉框和 Agent 的语义判断都走这一条路，别的改道方式一律没有。

## report.html 与绝对路径

plan.json 留着绝对路径，report.html 一个都不留。渲染前整份计划先过一遍
`paths.strip_absolute()`：`source_root`、`managed_dir`、每条 action 的 `source` 与
`destination` 这四类字段直接删掉，只留 `_portable` 双胞胎；`guard.referenced_in[].file`、
`guard.referenced_in[].form` 与 `guard.incoming_symlinks` 都改写成 `$HOME` 形式；剩下任何
还带着家目录前缀的字符串一律一起改写，没有例外，免得以后新加的字段又把用户名漏出去。

这条规则的理由很实在：审核页是能直接发给别人看的一页 HTML，绝对路径里带着账号名。
serve 模式的 `/api/plan` 走同一条路，服务进程内存里的计划仍然是完整的，`/api/apply`
用的是内存那份，不受影响。

页面导出的 approved.json 因此也只有 `$HOME` 形式。apply 一侧用
`paths.hydrate_absolute()` 按当前机器的家目录把四类字段展开回来，再做原有的全部校验，
所以 id 重算、越界检查、篡改检测都不用知道文件是从哪来的。

落盘的 token 只有 `$HOME` 一种，Windows 上也是。计划和报告是会跨机器传的东西，
一种拼法就只有一个解析器和一条隐私检查（整份文档一次 `startswith`）。
`paths.expand_portable()` 两种都认，`%USERPROFILE%\Downloads` 和
`$HOME/Downloads` 落到同一个地方；Windows 上给人看的时候由
`paths.display_portable()` 换成 `%USERPROFILE%\...`，那只是渲染，不进文件。

## approved.json 与 plan.json 的关系

approved.json 就是 plan.json 本身，只多填三个字段：`approved_action_ids` 填上勾选的 id，
`overrides` 填上改道，`approved_at` 与 `approved_by` 记下谁在什么时候批的。
`notes` 可以带着，执行器完全不读它。
其余字段一个都不能改，执行器会按 `id` 重算并比对，改过 destination 的文件会被当成篡改直接拒绝。

执行前的校验按顺序是：schema 必须为 2；root 存在且不是软链；
批准的 id 必须都在已知清单里；同一个 subject 只能批准一条；
出现不可批准的 id 直接抛错；名单里有永久删除而命令行没加 `--allow-permanent-delete` 时整批拒绝，不是跳过。

apply 成功之后，用户传进来的 approved.json 会被复制一份到管理目录，叫 `approved-<时间戳>.json`。
浏览器通常把导出文件下载到下载目录根部，不收走的话下次扫描就会被当成散件。

## 审计记录

`managed_dir/audit.jsonl` 每行一条，路径一律 `$HOME` 形式。

| 字段 | 说明 |
|---|---|
| `timestamp` | 这一条执行完的时刻。 |
| `run_id` | 一次 apply 的批次号，形如 `2026-09-02_10-20-11`。 |
| `action_id` / `subject_id` | 对应 plan 里的两个 id。 |
| `kind` | `move` / `trash` / `delete`。 |
| `source` / `destination` | `$HOME` 形式。 |
| `status` | `moved` / `trashed` / `deleted` / `dry-run` / `skipped` / `conflict` / `refused` / `failed`。 |
| `detail` | 状态的一句话解释。 |
| `size_bytes` | 条目体积。 |
| `manifest` | 这一批对应的 TSV 清单路径。 |
| `tagged` | 有没有成功打上临时标签。打标签失败只提醒，不影响这条动作的状态。 |
| `trash_backend` | 本次用的废纸篓后端。 |

崩溃时以 audit 为准。清单会先落一行 PLANNED 再重写终态，
中途断电就停在 PLANNED，undo 和 status 都只信 audit，清单留给人读和查最后整理时间。
