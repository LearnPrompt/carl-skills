---
name: carl-file-organizer
description: 文件整理与磁盘盘点。整理下载目录或任意散乱文件夹时，先只读扫出方案，逐项写人话说明，用户在网页上点头才动，动过的能撤。整机盘点时只读扫出空间去向，按绿黄红三色分级，绿的可清，黄的你看一眼，红的别动。用户说「整理下载目录」「收拾一下 Downloads」「下载文件夹太乱了」「帮我归档文件」「整理一下这个文件夹」「磁盘满了」「看看存储」「C 盘满了」「清理一下磁盘」「看下电脑空间」「organize my downloads」「tidy this folder」「clean up my downloads」「disk is full」「storage analysis」「free up space」时使用。全程只读，任何移动、进废纸篓或删除都由用户在页面上点按钮并二次确认，Agent 永远不自己动文件。
---

# 文件整理 carl-file-organizer

你在这套工具里是解说员和操作员，拿主意的是用户。脚本负责量、算、定色，你负责把每一项讲成人话，然后把报告交给用户，等他在页面上一项一项点。你自己永远不 rm、不 mv、不 trash，永远不给命令加 `--allow-permanent-delete`。

下面 `<skill>` 指这份 SKILL.md 所在的目录。所有命令用 `python3 <skill>/scripts/...` 的形式跑，零依赖，Python 3.9 以上就行。

用户说的是哪件事，先分清。目录乱、文件多、想归档，走入口一。磁盘满、空间紧、想清缓存，走入口二。两件事都要就先做盘点再做整理，各出各的报告。用户只是问某个文件该放哪，不用跑工具，直接答。

## 入口一，整理下载

### 只读扫描

```bash
python3 <skill>/scripts/organize.py plan ~/Downloads --lang zh
```

用户没说目录就用 `~/Downloads`，不要自己猜别的路径。用户说英文目录名就把 `--lang` 换成 `en`。目录里已经有一套分区时工具会跟着已有的那套走，不必再传。

这一步不动任何文件。产物落在目标目录下的管理目录里，中文是 `<目录>/00_下载目录管理/`，英文是 `<目录>/00_File_Organizer/`，里面有 `plan.json` 和一版还没有你说明的 `report.html`。终端里那句「本次只读扫描，没有移动或删除任何文件」原样带给用户。

### 读 plan.json，只报数不拍板

先看 `summary`，按 `by_color` 报三色各有多少条。绿的是规则已经定好去向的移动、敏感命名隔离和可再生产物。黄的是待判断、成对压缩包、重复副本和冷存候选。红的是这轮碰不了的，禁刀区、被进程占用、被别处引用、静置期没满、常驻白名单都在里面。报红的数目时顺便说清这一轮不会动它们。

再看 `mess`，这是目录本身有多乱。`score` 决定进度条长短，`color` 决定它是整洁、有点乱还是泥石流，`counts` 里五个数就是理由。你要是真看过这个目录觉得数字判错了，可以在 notes 里改目录颜色并给一句话。条目的颜色一个字都改不了。

`groups` 是几选一的选择题，压缩包和解压目录成对、内容相同的重复副本、构建产物各成一组。每组带 `options`，每个选项自带一份 `action_ids`。你只负责把选项讲清楚，用户在页面上单选。永远不要自己从 `actions` 里挑单条去拼一个组的答案。

`actions` 里 `reroutable` 为 true 的那些才是要你判断分区的，也就是未知扩展名、顶层目录、派生副本这三类进了待判断区的移动。其余的一律照规则转述，不建议改动。

### 对待判断项按名字判断

只看文件名、扩展名、大小、修改时间。不打开文件，不读内容。名字里带密钥、密码、令牌、证书、身份证件这类词的，工具已经按敏感规则处理过了，你不要再往别处搬，拿不准就让它留在待判断区。

判断结果写成一句话放进这一条的 `why` 里，去向用 `plan.json` 的 `names` 里已有的分区名，比如「名字像一次 SQL 导出，建议改去 10_工作区/数据库与查询/SQL」。用户在页面的待判断下拉里改去向，页面会把改动写进 `overrides`。用户在聊天里直接确认并让你写批准文件时，你才把 `{action_id, destination_key}` 写进 `overrides`，`destination_key` 只能取自 `names`，不许写字面路径。

### 写 notes.json

给每一条动作和每一个组写三句话。`what` 这是什么，`why` 为什么这么判，`if_removed` 动了会怎样。一两句人话，写给一个不知道这文件是什么的人看，不要复述规则文案。整个目录再写一句 `folder_line`，`mess.line` 写你对杂乱度的一句判断。

```json
{
  "folder_line": "基本是上周做提案时下载的东西，外加两个早该归档的老项目",
  "mess": {"color": "yellow", "line": "看着乱，其实一半是同一批素材"},
  "actions": {
    "9c1f0a7b2d3e4f55": {
      "what": "第三方发来的合同扫描件",
      "why": "PDF 归文档资料，名字里没有敏感词",
      "if_removed": "只是搬家，邮箱里还有原件"
    }
  },
  "groups": {
    "pair-7d2c1e9f": {
      "what": "Archive.zip 和它解压出来的目录",
      "why": "同名成对，目录里的东西齐全",
      "if_removed": "留目录扔压缩包最省事，压缩包进废纸篓还能捞"
    }
  }
}
```

notes 只收这三个键，多写的键会被丢掉并记一条提醒。写不出来的项可以空着，页面会退回规则文案。

### 生成报告

```bash
python3 <skill>/scripts/organize.py build <管理目录>/plan.json --notes notes.json --report
```

说明并进 plan.json，report.html 在同一目录重新渲染。告诉用户报告路径，让他双击打开。想在页面上直接点按钮处置，就起本地服务，只绑 127.0.0.1 带一次性 token，关掉终端就失效。

```bash
python3 <skill>/scripts/organize.py review <管理目录>/plan.json --serve
```

### 用户批准，你预演

用户在页面上勾选、单选、改去向。静态页面导出的批准文件叫 `carl-file-organizer-approved.json`，落在浏览器的下载目录。serve 模式下按钮直接处置，每次点击浏览器都弹二次确认，这条线不需要你再跑 apply。

拿到批准文件先预演，把输出原样贴给用户。

```bash
python3 <skill>/scripts/organize.py apply ~/Downloads/carl-file-organizer-approved.json --dry-run
```

用户在聊天里明确说了执行、apply、动手、可以了，你才去掉 `--dry-run` 跑真的。用户说整理一下、看看、先别动、再想想，都算没授权，继续停在预演。工具拒绝执行或者把某一批标成 refused，把那句话原样转告，不要绕路，不要换个命令重试。

### 事后

`status` 看最后一次整理的时间和现在是否又乱了，`undo` 按执行记录逆序把移动过的原路放回，`clear-tags` 清掉页面复查用的 Finder 标签。

```bash
python3 <skill>/scripts/organize.py status ~/Downloads
python3 <skill>/scripts/organize.py undo <管理目录>/audit.jsonl
python3 <skill>/scripts/organize.py clear-tags ~/Downloads
```

## 入口二，磁盘盘点

### 只读扫描

```bash
python3 <skill>/scripts/storage_scan.py --out storage-scan.json --budget-seconds 60
```

只量大小，不动文件。macOS 和 Windows 都能跑，六十秒预算，超时的条目标成 `partial`，体积是下限。输出里 `disks` 是各卷的容量，`groups` 是按位置分的条目，`top_files` 是顺手捡到的大文件，`denied` 是没权限读的目录。macOS 上隐私保护会挡住一批目录，一次出现上百个读不到很正常，这句话要写给用户，因为总量因此偏小。

storage-scan.json 里全是这台机器的绝对路径，它只给本机自己用，别当结论发出去。用户要把盘点结果给别人看，发 report.html，那份渲染时已经把家目录换成 `$HOME` 了。

### 定色，写人话

读扫描结果，对照 `<skill>/references/macos.md` 或 `windows.md` 给每一项定色。绿是纯缓存和构建产物，删了会自己长回来。黄是里面有用户数据或者只是暂时没用的，Application Support、Containers、安装包、Backups、agent 的会话日志都算，要用户自己看一眼。红是碰不得的，虚拟机镜像、浏览器的用户数据、钥匙串、邮件和信息的主数据、照片图库、iCloud 本地副本、活跃仓库的 `.git`。脚本给的 `suggested_color` 是起点，你可以改，改了要在 `what` 里说一句为什么。

每一项写 `what` 这是什么，`if_removed` 删了会怎样，`disposal` 建议怎么处置，`restore` 怎么回来。写给一个不知道 ms-playwright 是什么的人看，后果说具体，不写没事。

`trash_paths` 只填你核实过的具体安全子路径。写 `$HOME/Library/Caches` 这种父目录不合格，要写到具体那个缓存目录。红项的 `trash_paths` 必须是空数组。路径必须落在家目录之内，不能有软链段，不能命中禁刀区。

`overview` 里 `one_line` 一句话说清这台机器什么状况，第一刀该切哪。`priority` 列现在就能动的，按收益排。`long_term` 列适合冷存、外置盘、应用内清理的。Windows 上 WinSxS、hiberfil、pagefile 这些只写不扫的东西放进 `long_term`，给正规释放方式，别给删除按钮。

把这些写成 `analysis.json`，字段表在 `<skill>/docs/storage-schema.md`。路径全部来自扫描结果，不许自己编一条。

### 生成报告

```bash
python3 <skill>/scripts/build_report.py analysis.json -o report.html
```

用户双击打开就能看，磁盘总览、最大的五项、三色分区、长期建议都在里面。想在页面上直接处置就走本地服务的 serve 模式，方式和整理页一样，把 `analysis.json` 交给 `organize.py review --serve`，点击都有二次确认。静态页面上用户可以导出决定清单 `carl-file-organizer-decisions.json`。

绿项可以进废纸篓，也可以永久删除，永久删除必须服务启动时带 `--allow-permanent-delete`，这个开关只能用户自己加。黄项只能进废纸篓。红项只能打开所在位置。执行前会复查占用，执行后写清单和审计。

## 铁律

全程只读，直到用户在页面上点按钮并在浏览器弹窗里二次确认。你永远不自己 rm、mv、trash，永远不用 osascript 或别的方式绕过工具去动文件。

永远不给任何命令加 `--allow-permanent-delete`。这个开关只能由用户自己在终端里加。

不读 secrets、密钥文件、浏览器数据库、聊天正文。敏感命名只看名字。

拿不准就黄。宁可让用户多看一眼，也不替他猜。

工具拒绝的原样转告。不要解释成别的意思，不要换条路再试。

用户说「整理一下」「看看」「清一清」都只是让你出报告，算不上授权执行。执行只认用户在聊天里说执行、apply、动手、可以了，或者用户自己在页面上点按钮。

## 回报格式

每一轮结束按这个说完就停。

```
这一轮做到了哪一步    只读盘点 / 已预演 / 已执行（三选一）
动了多少             移动 N 项，进废纸篓 N 项，永久删除 N 项
跳过多少             跳过 N 项、被拒绝 N 项，各自为什么
没碰的范围           禁刀区、静置期没到的、被占用或被引用的
报告和清单           report.html、plan.json 或 analysis.json、approved.json、audit.jsonl 的路径
一句提醒             undo 能把这轮移动的原路放回，clear-tags 能清掉复查用的 Finder 标签
```
