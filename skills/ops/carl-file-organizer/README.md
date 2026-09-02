# 🗂️ 文件整理 carl-file-organizer

> 整理文件夹和清磁盘这两件事，过去靠忍，或者靠一个看不懂你文件的软件，现在跟 Agent 说一句就够了。

随口跟 Agent 说一句「收拾一下 Downloads」或者「磁盘满了」，它先只读扫一遍，然后在浏览器里打开一份报告。就一份：磁盘总览和目录杂乱度并排放在最上面，接着是最大的五项，然后按绿黄红三个区往下排，每个区里先是能清掉的缓存和构建产物，再是要搬去哪儿的文件。每一项都写着这是什么、为什么这么判、动了会怎样。三色区下面是整理后预览，一张图告诉你点完确认之后这个目录长什么样，你勾掉哪项图上那项就变回原地不动。底下只有一个按钮，勾好一次点掉，每次都有二次确认，动过的能一键撤回。

## 它跟传统整理器和清理软件的区别

传统整理器按扩展名把东西搬走，回头你找不到那份合同去了哪。清理软件扫到一个 3.8G 的目录只会写一句「用户缓存，可删」，你不知道里面到底是什么，也不知道删了哪些网站要重新登录。

这个 skill 分两层。脚本负责量大小、算静置期、认压缩包配对和重复副本、查谁还在用这个文件，把八成能用规则说清楚的判断先做完。Agent 负责剩下两成，看过目录之后给每一项写三句人话，这是什么，为什么这么判，删了会怎样。方案先给你看，你点头它才动，删了默认进废纸篓，移动过的能原路放回。

## 三色分级是核心

三色分两层。目录那层告诉你这个文件夹现在有多乱，值不值得花时间。条目那层告诉你这一条你能按什么按钮。

| 目录杂乱度 | 意思 |
|---|---|
| 🟢 整洁 | 没几件散件，没有等你判断的东西 |
| 🟡 有点乱 | 要么量还不大，要么要判断的不多 |
| 🔴 泥石流 | 两条都不满足，该花点时间了 |

| 条目 | 搬动那半 | 清理那半 | 能按什么 |
|---|---|---|---|
| 🟢 放心归位 / 可清 | 规则明确的移动、敏感命名隔离、可再生构建产物 | 纯缓存和临时文件，删了自动再生 | 勾上就走，永久删除要你自己额外开开关 |
| 🟡 你看一眼 | 待判断、成对压缩包、重复副本、冷存候选 | 含用户数据的目录、安装包、备份、agent 会话日志 | 只有打开所在位置和移到废纸篓，都可逆 |
| 🔴 别动 | 禁刀区、被进程占用、被别处引用、静置期没满 | 系统核心、虚拟机镜像、浏览器登录态、照片图库 | 只解释为什么不能动，最多打开所在位置 |

颜色由规则算出来。Agent 看过目录之后只能改目录那层的颜色，条目的颜色一个字都改不了，因为按钮权限跟着它走。

## 铁律

全程只读，直到你在页面上点按钮并在浏览器弹窗里二次确认。Agent 永远不自己 rm、mv、trash，永远不加 `--allow-permanent-delete`，这个开关只能你自己在终端里加。本地服务只绑 127.0.0.1，随机端口加一次性 token，关掉终端就失效。不读文件内容，敏感命名只看名字。拿不准就黄。每次执行都写清单和审计，`undo` 按记录逆序放回。

## 怎么触发

```
整理下载目录
收拾一下 Downloads
下载文件夹太乱了
帮我归档文件
磁盘满了
看看存储
C 盘满了
清理一下磁盘
看下电脑空间
organize my downloads
tidy this folder
disk is full
storage analysis
```

## 安装

```bash
npx skills add LearnPrompt/carl-skills --skill carl-file-organizer -g
```

零第三方依赖，Python 3.9 以上。装完 Agent 会读到 SKILL.md，脚本在 `scripts/` 下，`python3 scripts/organize.py --help` 能看到全部子命令。

## Windows

回收站走系统的 `SHFileOperationW` 接口，带撤销标志，进回收站的东西能从回收站找回。Finder 标签在 Windows 上没有对应功能，直接跳过不报错。打开所在位置用资源管理器。没有 lsof 时占用检查老实标成未知。C 盘之外的盘符一起盘点，WinSxS、hiberfil、pagefile 这些系统大户只提示正规释放方式，不给删除按钮。macOS 上跑过真实目录和真实磁盘，Windows 的代码走过测试但没在真机上磨过，第一次用建议先只读看报告，留个心眼。

## 老师们

| 老师 | 教的是 | 在这里变成了什么 |
|---|---|---|
| [John Locke](https://en.wikipedia.org/wiki/Commonplace_book) | commonplace book，能检索比完美分类更重要 | 收件箱先接住一切，待判断不强行归类 |
| [Melvil Dewey](https://en.wikipedia.org/wiki/Dewey_Decimal_Classification) | 用编号分区 | 00/10/20/60/90 这套编号，只到三层就封顶 |
| [S. R. Ranganathan](https://en.wikipedia.org/wiki/S._R._Ranganathan) | 分面分类，一件东西可以有多个机器可读的属性 | `destination_key`、`tier`、`color` 各管一面 |
| Aby Warburg | 好邻居法则，相关的放在一起，哪怕分类学上它们属于不同类 | 压缩包和解压目录成对处理的直觉来源 |
| [Niklas Luhmann](https://en.wikipedia.org/wiki/Niklas_Luhmann) | 卡片盒的价值在关系和理由 | 每条动作都带一句理由，Agent 再补三句人话 |
| [Paul Otlet](https://en.wikipedia.org/wiki/Paul_Otlet) | 给人读的卡片配一份给机器读的索引 | `report.html` 给人，`plan.json` 给程序和 Agent |
| [David Allen](https://en.wikipedia.org/wiki/Getting_Things_Done) | GTD 的 capture、clarify、review、act 四步 | 就是 plan、待判断、review、apply |
| [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) | LLM Wiki，面向 Agent 可读的知识库分区思路 | `names` 和 `destination_key` 这套机器优先的分区键 |
| [KKKKhazix / storage-analyzer](https://github.com/KKKKhazix/khazix-skills/tree/main/storage-analyzer) | 网页一键处置与三色报告 | 盘点入口的三色分级和页面上直接点按钮的体验 |

署名 LearnPrompt / 卡尔的AI沃茨。
