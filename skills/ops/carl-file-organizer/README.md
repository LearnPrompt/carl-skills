**中文** · [English](./README.en.md)

# 文件整理 · Carl File Organizer

下载目录整理器。零依赖 Python 命令行工具,先只读扫描出一份方案,你在网页上看过、勾选过,它才动手。默认只进废纸篓,永久删除要你显式打开开关。

```bash
uvx --from git+https://github.com/LearnPrompt/carl-file-organizer carl-file-organizer plan ~/Downloads
open ~/Downloads/00_下载目录管理/report.html
```

打开的页面里逐项看方案,勾上你同意的,导出批准文件,再跑一遍 apply,细节往下看。

## 安装

三种装法,挑一种。

```bash
# 一次性跑,不留常驻命令
uvx --from git+https://github.com/LearnPrompt/carl-file-organizer carl-file-organizer plan ~/Downloads

# 装成常驻命令,以后直接 carl-file-organizer
uv tool install git+https://github.com/LearnPrompt/carl-file-organizer
# 或者
pipx install git+https://github.com/LearnPrompt/carl-file-organizer

# 自己克隆
git clone https://github.com/LearnPrompt/carl-file-organizer
cd carl-file-organizer
python3 -m carl_file_organizer plan ~/Downloads
```

钉住某个版本就在仓库地址后面加 `@v0.2.0`。`uvx` 首次运行会现场拉代码构建,之后按 commit 缓存,不会每次都重新拉。

只需要 Python 3.9 及以上,零第三方依赖。macOS 上功能齐全,包括进废纸篓和 Finder 标签。Linux 上 `plan` 和 `apply` 照常跑,废纸篓退化成系统的 `gio trash`,查不到 `gio` 时废纸篓选项直接不出现在页面上,不会悄悄改成永久删除。

## 三步用起来

第一步,只读扫描:

```bash
carl-file-organizer plan ~/Downloads --lang zh
```

不动任何文件。产物落在 `~/Downloads/00_下载目录管理/`,一份 `plan.json` 给程序和 Agent 读,一份 `report.html` 给你看。首次跑还会在 `~/Downloads/.carl-file-organizer.json` 写一行最小配置,记住你选的语言和规则集,下次不用再传 `--lang`。

第二步,打开 `report.html`,逐项看它想怎么归类,想留哪份重复文件,哪些进废纸篓。两条路都行:双击直接打开,勾完点导出,浏览器会存下一份 `carl-file-organizer-approved.json`,默认就落在 `~/Downloads`;或者跑 `carl-file-organizer review ~/Downloads/00_下载目录管理/plan.json --serve`,本地起一个只绑 127.0.0.1 的服务,页面上的按钮直接落地,不用手动导出再执行。

![审核页(中文)](./docs/images/report-zh.png)

第三步,执行:

```bash
carl-file-organizer apply ~/Downloads/carl-file-organizer-approved.json
```

传进去的就是刚才导出的那份文件,放在哪都行,这里按浏览器的默认下载位置写。执行完它会把这份批准文件收进 `~/Downloads/00_下载目录管理/approved-<时间戳>.json` 留档,顶层不会多出一个散件。

第一次在终端里真正让它把文件送进废纸篓,macOS 会弹一个允许终端控制 Finder 的系统授权,点允许就行,这是系统自己的机制,不是这个工具要你交出什么权限。

后悔了:

```bash
carl-file-organizer undo ~/Downloads/00_下载目录管理/audit.jsonl
```

按执行记录逆序把移动过的文件原路移回。复查完想清掉页面留下的 Finder 标签,跑 `carl-file-organizer clear-tags ~/Downloads`。

## 它不会做什么

不读文件内容,敏感命名只看名字就把它隔离进 60_敏感信息,不会因为怕漏判就打开文件看一眼。不删除,默认进废纸篓,永久删除要显式加 `--allow-permanent-delete` 并且只对你已经批准过的 id 生效,命令行不加这个开关时整批永久删除请求直接被拒绝。不覆盖同名文件,目标位置已经有东西时转进重复待确认区,两份都留着。不出你指定的这一个目录,源和目标必须落在同一个根目录之内,`/`、家目录本身、`~/Library` 一律拒绝。不碰 `.git`、隐藏文件和符号链接段落里的路径。不联网,`review --serve` 只绑在 127.0.0.1 上,还带一次性 token,关掉终端就失效。每次 apply 都往 `audit.jsonl` 里写一行,`undo` 照着它回滚。

动手之前它还会查一遍这个文件是不是正被别的东西用着:有没有进程正打开它,有没有被 launchd、cron 或者 shell 配置文件引用,有没有你自己项目目录下的符号链接指向它,是不是一个 git worktree 或者虚拟环境。查到了就先停手,把原因写进方案里让你自己决定,不会替你硬闯。这套检查覆盖不到某个 App 自己数据库里存的绝对路径,比如某个编辑器的最近项目列表,这类情况靠静置期、Finder 标签和 undo 兜底,不是靠猜,这一点要老实说清楚。

## 为什么会有它

戒指老爷爷那套是说出你卡在哪,老爷爷点人。这里换了个场景:文件先站好队,老爷爷点谁走谁走。它不替你拿主意,它只是先把八成能用规则说清楚的判断做完——扩展名、静置了多久、是不是压缩包配对、是不是重复副本、是不是能重新生成的构建产物,这些代码就能跑。剩下两成看名字看上下文才能判断的,程序单独开一栏叫待判断,连蒙的动作都不做,留给你自己看,或者交给 Agent 按文件名判断后再回来找你确认。

这套流程真在一个跑了一个多月的下载目录上走过好几轮,移动了大几十项,没删过一个东西,每一项都留着清单和 Finder 标签,事后复查一遍复查数归零才算完。

## 分区

| 编号 | 中文名 | 英文名 | 放什么 |
|---|---|---|---|
| 00 | 收件箱 | Inbox | 新到的、静置期没到的、待判断的、按 Finder 标签分组的、重复待确认的 |
| 10 | 工作区 | Workspace | 项目代码、脚本和工具导出、数据库与查询文件 |
| 20 | 知识库 | Library | 文档资料、图片素材、视频素材、音频素材、网页资料,再往下一层按格式分 |
| 60 | 敏感信息 | Sensitive | 按文件名判断出的敏感文件,待你自己转移,程序不读内容 |
| 90 | 归档 | Archive | 静置超过 7 天的压缩包和安装包 |

目录深度封顶三层,`--lang zh|en` 选中英文名字。已经存在的编号目录被当成边界,程序不会再往里面深扫。

## 它靠什么判断

| 机制 | 规则 | 你能调什么 |
|---|---|---|
| 静置期 | 文档类默认 48 小时,压缩包和安装包默认 168 小时,没到期的留在收件箱不强行分类 | `.carl-file-organizer.json` 里的 `aging` 段 |
| 敏感命名隔离 | 精确文件名、去掉后缀的精确短词、敏感后缀、长关键词四层判断,命中就进 60_敏感信息待转移,全程不打开文件 | `sensitive.exact_names`、`name_patterns` |
| Finder 标签 | 本轮被动过的文件和目录打上「文件移动」标签,方便肉眼核对,`clear-tags` 统一清掉 | 无,标记失败只提醒不中断 |
| 压缩包配对 | `a.zip` 和解压出来的 `a/` 同时存在时归成一组,页面上单选留谁,默认留目录,选之前两份都不动 | 组内单选 |
| 重复副本 | 先比对文件大小,加 `--hash-duplicates` 才进一步用 sha256 比内容;名字像副本但没比对过内容的,默认两份都保留 | `--hash-duplicates` |
| 可再生产物 | `node_modules`、`.next`、`dist`、`build`、`__pycache__` 这类只给废纸篓选项,附一句怎么重新生成 | `regenerable` 名单 |

## 命令

| 命令 | 做什么 | 会不会动文件 |
|---|---|---|
| `carl-file-organizer plan [目录]` | 只读扫描,生成 plan.json 和 report.html | 否 |
| `carl-file-organizer review <plan.json> --serve` | 本地起服务打开审核页,按钮直接处置已勾选项 | 是,仅限批准过的 |
| `carl-file-organizer apply <approved.json>` | 执行批准过的动作 | 是 |
| `carl-file-organizer undo <audit.jsonl>` | 按记录逆序移回原处 | 是 |
| `carl-file-organizer status [目录]` | 看最后一次整理的时间和现在是不是又乱了 | 否 |
| `carl-file-organizer clear-tags [目录]` | 清掉本工具打过的 Finder 标签 | 是,只改标签 |

常用参数:`plan` 支持 `--lang zh|en`、`--profile tiered|simple`、`--hash-duplicates`、`--large-mb N`、`--target-percent P`、`--no-dir-sizes`、`--no-permanent-delete-options`、`--now ISO`、`--allow-outside-home`、`--allow-referenced`;`apply` 支持 `--dry-run`、`--allow-permanent-delete`、`--audit PATH`;`review` 的 `--serve` 是必须显式加的,另外支持 `--port N`、`--no-open`、`--allow-permanent-delete`;`undo` 支持 `--dry-run`,除了 audit.jsonl 也能传清单 tsv;`status` 支持 `--lang`、`--allow-outside-home`;`clear-tags` 支持重复出现的 `--from tags.txt`、`--all-lists`、`--tag NAME`、`--dry-run`。

## 给 Agent 用

```bash
npx skills@latest add LearnPrompt/carl-file-organizer
```

Agent 拿到的边界很窄:它能跑 `plan`,能读 `plan.json`,只对待判断且允许改道的那部分文件按文件名做语义判断,把判断写进批准文件的 `overrides` 里,列给你看,等你回复。真正执行永远要你自己在对话里说一句执行,Agent 不会替你按下那个按钮。完整规则在 [skills/carl-file-organizer/SKILL.md](./skills/carl-file-organizer/SKILL.md),字段表在 [docs/plan-schema.md](./docs/plan-schema.md)。

## plan.json 长什么样

```json
{
  "schema_version": 2,
  "lang": "zh",
  "source_root_portable": "$HOME/Downloads",
  "managed_dir_portable": "$HOME/Downloads/00_下载目录管理",
  "names": {
    "library.docs.pdf": "20_知识库/文档资料/PDF",
    "archive.zip.zip": "90_归档/压缩包/ZIP"
  },
  "actions": [
    {
      "id": "9c1f0a7b2d3e4f55",
      "kind": "move",
      "filename": "report.pdf",
      "destination_key": "library.docs.pdf",
      "reason": {"zh": "文档按类型归档到 20_知识库/文档资料/PDF"},
      "tier": "routine",
      "approvable": true
    }
  ],
  "approved_action_ids": [],
  "overrides": []
}
```

完整字段表在 [docs/plan-schema.md](./docs/plan-schema.md),审核页的视觉规范在 [docs/review-page.md](./docs/review-page.md)。

## 老师们

| 老师 | 教的是 | 在这里变成了什么 |
|---|---|---|
| [John Locke](https://en.wikipedia.org/wiki/Commonplace_book) | commonplace book,能检索比完美分类更重要 | 收件箱先接住一切,待判断不强行归类 |
| [Melvil Dewey](https://en.wikipedia.org/wiki/Dewey_Decimal_Classification) | 用编号分区 | 00/10/20/60/90 这套编号,但只到三层就封顶 |
| [S. R. Ranganathan](https://en.wikipedia.org/wiki/S._R._Ranganathan) | 分面分类,一件东西可以有多个机器可读的属性 | `destination_key`、`tier`、`rule` 各管一面,不挤成一个标签 |
| Aby Warburg | 好邻居法则,把相关的放在一起,哪怕分类学上它们不属于同一类 | 分类原则的来源,也是压缩包和解压目录成对处理的直觉来源 |
| [Niklas Luhmann](https://en.wikipedia.org/wiki/Niklas_Luhmann) | 卡片盒的价值在关系和理由,不在卡片本身 | 每条 action 都带一句 `reason`,不是光给个目的地 |
| [Paul Otlet](https://en.wikipedia.org/wiki/Paul_Otlet) | 给人读的卡片,配一份给机器读的索引 | `report.html` 给人,`plan.json` 给程序和 Agent |
| [David Allen](https://en.wikipedia.org/wiki/Getting_Things_Done) | GTD 的 capture、clarify、review、act 四步 | 就是 plan、待判断、review、apply |
| [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) | 面向 Agent 可读的知识库分区思路 | `names` 和 `destination_key` 这套机器优先的分区键 |
| [KKKKhazix / storage-analyzer](https://github.com/KKKKhazix/khazix-skills/tree/main/storage-analyzer) | 网页上一键处置的体验 | `review --serve` 页面上直接点按钮处置 |

署名:LearnPrompt / 卡尔的AI沃茨。

## 开发

```bash
python3 -m unittest discover -s tests -v
python3 scripts/demo_fixture.py /tmp/gn-demo
```

`scripts/demo_fixture.py` 造一份假的下载目录,静置期内外的文件、成对压缩包、重复副本、敏感命名、构建产物都齐全,CI 的冒烟测试和这份 README 的截图用的都是它,不会碰任何真实文件。CI 跑 macOS 和 Linux 各三个 Python 版本的单元测试,再实跑一遍 README 里这套命令,加一次打包检查。

## License

MIT
