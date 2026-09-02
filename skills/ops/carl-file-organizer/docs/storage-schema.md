# 整机盘点的两份 JSON

盘点这条线上有两份数据，分工很清楚。

`storage-scan.json` 由 `scripts/storage_scan.py` 产出，全是机器量出来的事实：谁多大、在哪、是什么、按规则该是什么颜色。它不解释，也不建议动谁。

`analysis.json` 由 Agent 写，是人话层：这是什么、删了会怎样、怎么处置、命令是什么。它必须建立在扫描结果之上，不能凭空捏造路径。

报告模板同时吃这两份，缺了 `analysis.json` 也能渲染，只是退回规则文案。

---

## storage-scan.json

```jsonc
{
  "schema": "storage-scan/1",
  "generated_at": "2026-09-02 14:20:31 +0900",
  "platform": "darwin",                  // sys.platform 原样
  "home_token": "$HOME",                 // Windows 上是 %USERPROFILE%
  "system": { ... },
  "disks": [ ... ],
  "groups": { "<组名>": [ 条目, ... ] },
  "top_files": [ 大文件, ... ],
  "denied": [ 读不到的目录, ... ],
  "elapsed_seconds": 37.9,
  "budget_seconds": 60.0,
  "budget_hit": false,
  "skipped_groups": [],
  "summary": { ... }
}
```

### system

体检信息，全部来自只读命令，每个子进程 5 秒硬超时，取不到就整个字段不出现。

| 字段 | 说明 |
|---|---|
| `platform` / `home_token` / `python` / `cpu_count` | 任何平台都有 |
| `os` / `os_build` / `arch` | macOS 走 `sw_vers`、`uname`；Windows 走 `platform` 模块 |
| `cpu` / `memory_bytes` / `memory_human` | macOS 走 `sysctl`，Windows 上没有 |
| `memory_pressure_head` / `vm_stat_head` / `uptime` | macOS 才有，各截前几行，取不到就跳过 |

### disks

macOS 解析 `df -k`，只保留设备名以 `/dev/` 开头的卷；解析失败退回 `shutil.disk_usage("/")`。
Windows 用 `ctypes.windll.kernel32.GetLogicalDrives()` 拿盘符位图，逐个 `shutil.disk_usage`。

```jsonc
{
  "mount": "/System/Volumes/Data",
  "device": "/dev/disk3s5",
  "total_bytes": 245107195904,
  "used_bytes": 177894096896,
  "free_bytes": 22015442944,
  "total_human": "228.3 GB",
  "used_human": "165.7 GB",
  "free_human": "20.5 GB",
  "capacity_percent": 89.0,
  "flags": ["high_usage", "low_free"],   // >=85% / 可用不足 30GiB
  "source": "df"
}
```

`flags` 就是判断口径：`high_usage` 表示进清理优先区，`low_free` 表示多开几个 agent 加浏览器就会紧。

### groups

macOS 的组，按扫描顺序：

| 组 | 内容 |
|---|---|
| `dev_caches` | `~/.npm` `~/.pnpm-store` `~/.cache` `~/.cargo` `~/.gradle` `~/.m2` `~/.nuget` `~/.bun` `~/go/pkg`，以及 `~/Library/Caches` 下的 pip、uv、ms-playwright、Homebrew、Xcode |
| `downloads_installers` | Downloads 顶层的 dmg/pkg/zip/iso/exe/msi 等安装包，不进子目录 |
| `trash` | `~/.Trash` 整体体积 |
| `developer` | Xcode DerivedData、Archives、iOS DeviceSupport、CoreSimulator |
| `caches` | `~/Library/Caches` 一层子目录 |
| `app_support` | `~/Library/Application Support` 一层子目录 |
| `containers` | `~/Library/Containers` 一层子目录 |
| `group_containers` | `~/Library/Group Containers` 一层子目录 |
| `logs` | `~/Library/Logs` 一层子目录 |
| `projects_regenerable` | 常见工作区下深度不超过 3 的 `node_modules` `.next` `dist` `build` `target` `coverage` `__pycache__` 等，命中即当叶子不再深入 |
| `library` | `~/Library` 一层子目录 |
| `home_top` | `$HOME` 一层子目录 |
| `system_notes` | 只写不扫，见下 |

Windows 的组：`dev_caches`、`downloads_installers`、`recycle_bin`、`appdata_local`（`%LOCALAPPDATA%` 一层，外加 Temp、pip\Cache、npm-cache、Yarn、NuGet、浏览器 User Data 这些藏得深的）、`appdata_roaming`、`projects_regenerable`、`user_top`、`system_notes`。

组的顺序是有讲究的：先量深层再量浅层。目录体积带 memo，深层量过之后浅层直接命中缓存，`home_top` 扫到 `~/Library` 时不用重走一遍。

**组之间会重复。** 同一个路径可能同时出现在 `dev_caches` 和 `caches`，`home_top` 更是把下面所有组的父目录又列了一遍。聚合和排序时按 `path` 去重，不然会重复计算。

### 条目

```jsonc
{
  "name": "ms-playwright",
  "path": "<家目录绝对路径>/Library/Caches/ms-playwright", // 给执行器用
  "path_portable": "$HOME/Library/Caches/ms-playwright", // 给人和报告看，不带用户名
  "size_bytes": 1932735283,
  "size_human": "1.8 GB",
  "kind": "dev_cache",
  "suggested_color": "green",
  "restore_hint": "下次装依赖或构建时会重新下载，第一次会慢一点",
  "mtime": "2026-08-30 11:02:44",
  "group": "dev_caches",
  "partial": false,
  "red_reason": "里面埋着 vm_bundles",     // 只有 red 才有
  "contains_notable": [".git", "messages"] // 有才出现，见下
}
```

`kind` 的取值：`cache`、`app_data`、`dev_cache`、`build_artifact`、`installer`、`media`、`project`、`unknown`，`system_notes` 里另有一个 `system`。

`partial` 为真表示这个条目的时间片用完了，没量到底，`size_bytes` 是下限而不是真值。报告里必须显出来，不能当准数用。

`system_notes` 的条目 `size_bytes` 是 `null`、`scanned` 是 `false`、另有一个 `note` 字段。它们只是提醒 Agent 这些地方也占空间但要走系统自己的路子，不参与任何删除动作。

### suggested_color 的规则

判定顺序写死在脚本里，Agent 可以在 analysis 里覆盖，但覆盖要给理由。

1. 路径本身命中禁刀区词表，`red`。
2. 废纸篓和回收站，`green`。
3. `kind` 是 `cache` / `dev_cache` / `build_artifact`，`green`。纯可再生的东西不因为里面混了个什么目录就变色。
4. 遍历中撞见特异的禁刀区标志物（`vm_bundles`、浏览器的 `User Data`、`.photoslibrary` 这类），`red`，并写 `red_reason`。
5. 其余一律 `yellow`。

第四条的标志物必须足够特异。早期版本把 `messages`、`mail`、`profiles`、`.git` 也算进去，结果 Downloads、Documents、projects 全被染红，三色直接失效 —— 这些名字随便哪个代码库里都有。现在它们降级成 `contains_notable`，只提示不改色。

### top_files

在上面那些组的目录范围内顺手捡出来的大文件，默认门槛 200MB，默认取前 30。不是全盘搜索，所以扫不到的地方就不会出现在榜上；`--budget-seconds` 给得少时，榜单会随着走到哪儿而变。

### denied

读不到的目录，按 `path` 去重。

```jsonc
{ "path": "…", "path_portable": "…", "reason": "permission_denied", "counted_bytes": 0 }
```

`reason` 是 `permission_denied` 或 `os_error:<异常类名>`。macOS 上 TCC 保护的目录会成批出现在这里，属于正常现象。

### summary

| 字段 | 说明 |
|---|---|
| `item_count` / `group_count` | 条目和组的数量 |
| `partial_item_count` / `sizes_are_lower_bounds` / `partial_note` | 有多少条目没量完 |
| `measured_bytes` / `measured_human` | 量到的总量，因为组之间重复，这个数会大于实际占用，只能当量级参考 |
| `dropped_below_floor` | 因为小于门槛被丢掉的条目数 |
| `min_size_bytes` / `min_file_bytes` | 本次用的两个门槛 |
| `denied_count` / `denied_note` | 读不到的目录数与提示 |

### 尺寸口径

目录体积是其下所有文件 `st_size` 之和，也就是逻辑大小。跟 `du` 的块大小口径不一样：稀疏文件和 APFS 压缩过的文件会偏大，硬链接会被重复计算。要的是量级判断，不是审计账。

### 预算怎么分

`--budget-seconds` 是整轮硬上限。剩余时间在组之间平分，组内再在条目之间平分，最少给每个条目 0.3 秒。任何一层撞线，整棵树立刻收手并把这个条目标成 `partial`。全局预算耗尽时，后面的组进 `skipped_groups`，`budget_hit` 置真。

真机参考：本机 165GB 已用的 macOS，60 秒预算实际跑 38 秒，产出 231 个条目，其中 173 个是下限，145 个目录读不到。

---

## analysis.json

Agent 读完 `storage-scan.json` 之后写这一份。**每一条的路径都必须来自扫描结果，不能自己编。**

```jsonc
{
  "schema": "storage-analysis/1",
  "generated_at": "2026-09-02 14:31:00 +0900",

  "overview": {
    "one_line": "一句话说清这台机器现在什么状况，第一刀该切哪儿。",
    "tier_stats": { "green": 5368709120, "yellow": 32212254720, "red": 12884901888 },
    "priority": [ "现在就能动的，按收益排序，每条一句话" ],
    "long_term": [ "适合冷存、外置盘、应用内清理的，每条一句话" ]
  },

  "top5": [
    {
      "rank": 1,
      "color": "red",
      "size_bytes": 12884901888,
      "kind": "app_data",
      "name": "Claude 桌面端的虚拟机镜像",
      "path_portable": "$HOME/Library/Application Support/Claude/vm_bundles",
      "note": "最大的一块，但里面是虚拟机磁盘，删了要重装重配，不在这一轮里动。"
    }
  ],

  "items": [
    {
      "id": "playwright-cache",
      "color": "green",
      "name": "Playwright 下载的浏览器",
      "path_portable": "$HOME/Library/Caches/ms-playwright",
      "size_bytes": 1932735283,
      "what": "跑浏览器自动化时下载的 Chromium、Firefox、WebKit 三份完整浏览器。",
      "if_removed": "下次跑自动化会重新下一遍，几分钟的事，别的什么都不受影响。",
      "disposal": "trash",
      "risk": "low",
      "restore_hint": "npx playwright install 会重新下载",
      "trash_paths": ["$HOME/Library/Caches/ms-playwright"],
      "kill_processes": [],
      "commands": [
        { "label": "看看有多大", "cmd": "du -sh \"$HOME/Library/Caches/ms-playwright\"" }
      ],
      "app_paths": [],
      "open_note": ""
    }
  ]
}
```

### items 的字段

| 字段 | 说明 |
|---|---|
| `id` | 本份文件内唯一，报告和执行器拿它对账 |
| `color` | `green` / `yellow` / `red`，可以覆盖扫描器的建议，覆盖了就在 `what` 里说一句为什么 |
| `name` | 人话名字，不是路径尾巴 |
| `path_portable` | 必须用 `$HOME` 或 `%USERPROFILE%` 开头，不带用户名 |
| `size_bytes` | 照抄扫描结果，别自己算 |
| `what` | 这是什么。写给一个不知道 ms-playwright 是干嘛的人看 |
| `if_removed` | 删了会怎样。说具体后果，不说没事 |
| `disposal` | `trash`（移到废纸篓）/ `delete`（永久删除）/ `archive`（冷存）/ `in_app`（应用内清理）/ `keep`（别动） |
| `risk` | `low` / `medium` / `high` |
| `restore_hint` | 怎么恢复。没法恢复就直说没法恢复 |
| `trash_paths` | 见下，红色项必须是空数组 |
| `kill_processes` | 动之前要先退掉的进程名，没有就空数组 |
| `commands` | `{label, cmd}`，只放只读或用户自己复制去跑的命令 |
| `app_paths` | 红色项里应用本体的位置，用于引导用户去应用内清理 |
| `open_note` | 打开所在位置之后该看什么，一句话 |

### trash_paths 的硬规矩

这是唯一会被执行器当成动作输入的字段，所以它的规矩最严。

- 只有 `green` 和 `yellow` 能有 `trash_paths`，`red` 必须是空数组。
- 每条都必须是 Agent 核实过的具体安全子路径，不能图省事写父目录。写 `$HOME/Library/Caches` 是不合格的，要写到具体那个缓存目录。
- realpath 必须落在 `$HOME` / `%USERPROFILE%` 之内，路径里不能有 symlink 段，不能命中禁刀区。
- 扫描结果里 `partial` 为真的条目，体积是下限，不代表内容不确定，但要在 `what` 里说明这个数是下限。

### 三色对应的按钮权限

| 颜色 | 报告里能点什么 |
|---|---|
| 🟢 green | 移到废纸篓；永久删除（还要执行器带 `--allow-permanent-delete`）；打开所在位置 |
| 🟡 yellow | 移到废纸篓（可逆）；打开所在位置。没有永久删除 |
| 🔴 red | 只有打开所在位置。不提供任何删除接口 |

不管哪一色，每次点击都要浏览器二次确认，执行前复查占用，执行后写 manifest 和 audit。执行器只认 `analysis.json` 里算出来的 `id` 和白名单路径，报告页面传什么它都不认。
