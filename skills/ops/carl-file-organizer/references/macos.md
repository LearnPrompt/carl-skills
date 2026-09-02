# macOS 的东西都存在哪

给 Agent 读的参考。目的是看到一个路径能说出它是什么、删了会怎样、归哪一色。
不确定的时候一律往保守里判，把它交给人看一眼，比误删一次划算得多。

## 磁盘先看哪个数

Apple Silicon 的 Mac 是 APFS 容器，`df` 会列出一堆卷，真正有意义的只有一个：

- `/System/Volumes/Data` 才是你的数据卷，用量和余量看它。
- `/` 是只读的系统卷快照，十几 GB 且基本不变，别拿它算余量。
- `/System/Volumes/VM` 是交换文件，动不了也不用动。
- 各个卷显示的可用空间是同一个池子，看着重复是正常的。

判断口径：Data 卷用到 85% 就该动手了；可用空间掉到 30GiB 以下，多开几个 agent 加浏览器加桌面端大模型就会明显发紧。

「可清除空间」是系统标记为随时能回收的部分，`df` 里算在已用里。它不需要你操心，真缺空间时系统自己会放。时间机器的本地快照也挂在系统卷上，用户目录里看不见，但确实占地方。

## 用户目录的地形

`~/Library` 是大头所在，Finder 默认还把它藏起来。里面几个关键位置：

| 位置 | 是什么 | 一般归哪色 |
|---|---|---|
| `~/Library/Caches` | 应用缓存，绝大多数能自己重建 | 🟢 |
| `~/Library/Application Support` | 应用的账号、配置、本地数据库、模型、虚拟机 | 🟡，含禁刀区的 🔴 |
| `~/Library/Containers` | 沙盒应用的私有目录，等于那个应用的全部身家 | 🟡 |
| `~/Library/Group Containers` | 一组应用共享的数据，办公套件和 Apple 自家应用都在这儿 | 🟡 |
| `~/Library/Logs` | 日志，通常不大，删了只是丢排查线索 | 🟢 |
| `~/Library/Developer` | Xcode 的构建中间产物和模拟器 | 🟢 |
| `~/Library/Mobile Documents` | iCloud Drive 的本地落地点 | 🔴 |
| `~/Library/Keychains` `Messages` `Mail` | 钥匙串、聊天、邮件的主数据 | 🔴 |

`~/Library/Containers` 和 `Group Containers` 条目特别多，一台常用的 Mac 上八十几个是常态，绝大多数只有几 MB。真正值得看的是排在前面那几个。

## 一眼认出可再生的东西

### 开发缓存

这些是最干净的第一刀：体积大、可再生、不含任何用户资产。

| 路径 | 是什么 | 怎么回来 |
|---|---|---|
| `~/.npm` | npm 的包缓存 | 下次 install 重新下 |
| `~/.pnpm-store` | pnpm 的全局仓库 | 下次 install 重新下，但 pnpm 项目会先变慢 |
| `~/.cache` | 通用缓存根，`huggingface` 子目录里常有几十 GB 的模型 | 模型要重新下载，注意流量 |
| `~/.cargo` `~/.gradle` `~/.m2` `~/.nuget` | Rust、Gradle、Maven、NuGet 的依赖仓库 | 下次构建重新拉 |
| `~/.bun` | Bun 的安装与缓存 | 重新安装 |
| `~/Library/Caches/ms-playwright` | 三份完整的浏览器 | `npx playwright install` |
| `~/Library/Caches/Homebrew` | 下载过的安装包和 bottle | 自动重下，`brew cleanup` 是正规做法 |
| `~/Library/Caches/pip` `uv` | Python 包缓存 | 下次装包重新下 |
| `~/Library/Developer/Xcode/DerivedData` | Xcode 的编译中间产物 | 重新编译，第一次会很慢 |
| `~/Library/Developer/CoreSimulator` | 模拟器运行时和设备镜像 | Xcode 里重新下载运行时，可能好几 GB |

### 构建产物

在工作区里按名字认：`node_modules`、`.next`、`dist`、`build`、`target`、`coverage`、`__pycache__`、`.turbo`、`.nuxt`、`.svelte-kit`、`.parcel-cache`。

它们全部 🟢。恢复方式写清楚就行：`node_modules` 重跑包管理器，其余重跑一次构建。注意两点：正在跑 dev server 的项目先别动；`.next/cache` 之类删了只是下次构建慢一点，不影响代码。

### 安装包

Downloads 顶层的 `.dmg` `.pkg` `.iso` `.exe` `.msi`，装完就没用了。归 🟡 不是 🟢，因为里面偶尔混着买断制软件的安装包和授权文件，值得人扫一眼再动。老版本的应用包适合冷存不适合直接删。

## 禁刀区

这些不是不能优化，是不能一刀切。它们要么是唯一副本，要么删了就得重新登录重新配置，要么根本不该由脚本来动。

- `~/Library/Application Support/*/vm_bundles`：桌面端大模型应用的虚拟机磁盘镜像，单个就能十几 GB，是很多 Mac 上最大的一块。想省这块空间得在应用里操作，不能删文件。
- 浏览器的用户数据：`~/Library/Application Support/Google/Chrome`、`Firefox`、`Microsoft Edge`、`BraveSoftware`，以及 `~/Library/Safari`。里面是登录态、Cookie、书签、扩展。
- `~/Library/Keychains`：钥匙串。
- `~/Library/Messages`、`~/Library/Mail`，以及对应的 `~/Library/Containers/com.apple.mail` 等容器。
- `~/Pictures/照片图库.photoslibrary`（英文系统是 `Photos Library.photoslibrary`）。同类的还有 `.musiclibrary`、`.tvlibrary`、`.imovielibrary`、`.fcpbundle`。
- `~/Library/Mobile Documents`：iCloud Drive 的本地副本，删本地会触发同步删云端。
- 虚拟机镜像：`.utm`、`.pvm`、`.vmwarevm`，以及 Docker Desktop 的数据卷。
- 活跃仓库的 `.git`。
- Obsidian 之类的知识库主库，判别方式是目录里有 `.obsidian`。
- 任何看着像唯一副本的证件、合同、财务、签证材料。

## 容易踩的几个坑

**通用目录名不能当禁刀区标志。** `messages`、`mail`、`profiles`、`.git` 这些名字在任何代码库里都能撞见，拿它们判定「这个目录里埋着禁刀区」，会把 Downloads、Documents、projects 一起染红，三色就没意义了。只有 `vm_bundles`、浏览器的 `User Data`、`.photoslibrary` 这种足够特异的名字才配当标志物。

**顶层目录不是删除单元。** `$HOME/Documents`、`$HOME/Downloads` 这种条目出现在盘点里是为了让人知道空间去哪了，不是为了让人整个删掉。给它们 🟡，具体动作落到里面的子路径上。

**读不到的目录是常态。** macOS 的隐私保护会挡住一批目录，一次扫描出现上百个读不到的目录很正常。它们的体积没计入，所以报告里的总量永远偏小，这句话必须写给用户看。

**agent 的会话日志会悄悄长很大。** 各种命令行 AI 工具在 `~/.codex`、`~/.claude` 这类目录下按天存 jsonl，单个文件上 GB 很常见。它们不是缓存也不是用户资产，属于典型的 🟡：多半可以清掉旧的，但清之前值得人确认还要不要回溯。

**废纸篓不等于释放。** 移到 `~/.Trash` 只是改了位置，空间还占着。要真的释放必须明确清空，而清空之后不可恢复。

**Backups 目录先别删。** 备份包体积大、看着像垃圾，实际是出事时唯一的退路。归 🟡，建议迁到外置盘或冷存，不建议直接删。

## 只读体检命令

这些都不改任何东西，可以直接跑：

```bash
df -k                                    # 看 /System/Volumes/Data
sw_vers                                  # 系统版本
sysctl -n hw.memsize hw.ncpu             # 内存和核数
memory_pressure                          # 内存压力
vm_stat                                  # 分页与压缩情况
uptime                                   # 负载
tmutil listlocalsnapshots /              # 本地快照
```

看后台谁在磨机器：

```bash
ps aux | awk 'NR==1 || $3+0 >= 10 || $4+0 >= 2' | sort -k3 -nr | head -30
```

动任何东西之前确认没被占用：

```bash
lsof +D "<目标目录>" 2>/dev/null | head
```
