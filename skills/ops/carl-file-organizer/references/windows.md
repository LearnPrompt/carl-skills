# Windows 的东西都存在哪

给 Agent 读的参考。和 macOS 那份一个目的：看到路径能说出它是什么、删了会怎样、归哪一色。
Windows 上还多一层麻烦 —— 占空间最狠的几样东西根本不在用户目录里，而且不能直接删。

## 先看盘，不止看 C 盘

`GetLogicalDrives` 拿到的是全部盘符位图，逐个 `shutil.disk_usage` 才是完整画面。常见情况：

- 系统盘 C 满了，D 盘还空着一半，很多东西可以搬而不是删。
- 网络盘和已弹出的可移动盘会让 `disk_usage` 抛异常，逐个吞掉异常继续，别让一个盘卡死整轮。
- WSL 的虚拟磁盘挂在 C 盘上，但在资源管理器里看不出来。

判断口径和 macOS 一致：用到 85% 进清理优先区，可用不足 30GiB 就该动手。

## 用户目录的地形

| 位置 | 是什么 | 一般归哪色 |
|---|---|---|
| `%LOCALAPPDATA%`（`...\AppData\Local`） | 本机专属的应用数据和缓存，绝大多数大头在这儿 | 混杂 |
| `%LOCALAPPDATA%\Temp` | 临时文件，装过的安装包解压残留全在里面 | 🟢 |
| `%APPDATA%`（`...\AppData\Roaming`） | 跟着账号漫游的配置，通常小但重要 | 🟡 |
| `%USERPROFILE%\Downloads` | 下载和安装包 | 🟡 |
| `C:\$Recycle.Bin` | 回收站，每个用户一个子目录 | 🟢 |

`AppData` 默认是隐藏的，用户自己翻不到，所以报告里给「打开所在位置」比给路径有用得多。

## 一眼认出可再生的东西

### 开发缓存

| 路径 | 是什么 |
|---|---|
| `%USERPROFILE%\.npm` | npm 包缓存 |
| `%LOCALAPPDATA%\npm-cache` | npm 在 Windows 上的另一个缓存位置，两个都要看 |
| `%USERPROFILE%\.gradle` `.m2` `.nuget` `.cargo` | Gradle、Maven、NuGet、Rust 的依赖仓库 |
| `%USERPROFILE%\.cache` | 通用缓存根，`huggingface` 模型常在这儿 |
| `%LOCALAPPDATA%\pip\Cache` | Python 包缓存 |
| `%LOCALAPPDATA%\Yarn` | Yarn 缓存 |
| `%LOCALAPPDATA%\uv` `ms-playwright` `go-build` | uv、Playwright 浏览器、Go 构建缓存 |
| `%LOCALAPPDATA%\Temp` | 临时目录，正在运行的程序可能占着一部分文件 |

`.nuget\packages` 在装过几个 .NET 项目的机器上很容易上 10GB，是常被忽略的大户。

### 浏览器缓存要分清两样东西

这一点比 macOS 上更容易搞错：

- `...\User Data\<Profile>\Cache`、`Code Cache`、`GPUCache` 是缓存，可清。
- `...\User Data\` 这一层本身是**用户数据**：登录态、Cookie、书签、扩展、密码。🔴，绝不能整个删。

同一棵树里两种性质完全不同的东西，所以宁可只给「打开所在位置」，也别给一个作用在 `User Data` 上的删除按钮。Chrome 在 `%LOCALAPPDATA%\Google\Chrome\User Data`，Edge 在 `%LOCALAPPDATA%\Microsoft\Edge\User Data`，Firefox 在 `%APPDATA%\Mozilla\Firefox\Profiles`。

### 构建产物

和 macOS 完全一样，按目录名认：`node_modules`、`.next`、`dist`、`build`、`target`、`coverage`、`__pycache__`。全部 🟢。

Windows 上额外注意：路径长度上限会让深层的 `node_modules` 删不动，正规做法是用支持长路径的工具或者先重命名再删。文件被编辑器或语言服务占着也会删失败，动之前先退掉进程。

## 只提示不上灯的地方

这几样是 Windows 特有的空间大户，全都不在用户目录里，也全都不能直接删。盘点里只写不扫，给出正规释放方式，让用户自己去操作。

| 位置 | 为什么占地方 | 正规释放方式 |
|---|---|---|
| `C:\Windows\WinSxS` | 组件存储，存着系统组件的历史版本。资源管理器算出来的体积严重虚高，因为里面大量是硬链接 | 管理员执行 `DISM /Online /Cleanup-Image /StartComponentCleanup` |
| `C:\Windows\SoftwareDistribution\Download` | 已下载的更新包，装完就没用了 | 磁盘清理里的 Windows 更新清理，或先停 `wuauserv` 再清 |
| `C:\hiberfil.sys` | 休眠用的内存镜像，通常和物理内存一个量级 | `powercfg /hibernate off`，代价是没有休眠和快速启动 |
| `C:\pagefile.sys` | 虚拟内存页面文件，删了要么蓝屏要么立刻被重建 | 系统属性里改大小或者挪到别的盘 |
| `C:\System Volume Information` | 系统还原点和卷影副本，占的是保留配额 | 系统保护里调低磁盘使用比例，或删掉旧还原点 |
| WSL 的 `ext4.vhdx` | 虚拟磁盘只涨不缩，Linux 里删了文件宿主机也不会变小 | 关掉发行版后用 `diskpart` 的 `compact vdisk` 压缩 |
| Docker Desktop 的数据卷 | 镜像和容器层 | `docker system prune`，别去动文件 |

WinSxS 尤其容易误判：看到几十 GB 就想删，实际上真正独占的空间小得多，直接删会让系统更新和修复彻底失败。

## 禁刀区

- 浏览器的 `User Data` / `Profiles` 整棵树。
- `%APPDATA%` 下的邮件客户端数据和 `Microsoft\Crypto`（证书密钥）。
- OneDrive 同步目录：删本地会同步删云端。
- Hyper-V 的 `Virtual Machines` 目录、WSL 的发行版目录、Docker Desktop 的数据卷。
- 活跃仓库的 `.git`。
- 上一节里那几样系统文件，一个都不能碰。

## 平台差异，写代码时要记住的

| 事情 | macOS | Windows |
|---|---|---|
| 移到回收站 | Finder 的废纸篓 | `SHFileOperationW` 带 `FOF_ALLOWUNDO`，走 ctypes，不需要装依赖 |
| 打开所在位置 | 在访达中显示 | `explorer /select,<路径>` |
| 文件标签 | Finder 标签 | 没有对应功能，直接跳过，不要报错 |
| 查占用 | `lsof` | 没有 `lsof`，`handle.exe` 要另装。查不到就老实标成未知，不要假装查过了 |
| 路径大小写 | 默认不区分但保留原样 | 不区分，比较时统一转小写 |
| 路径长度 | 基本无感 | 有上限，深层 `node_modules` 会踩到 |
| 家目录变量 | `$HOME` | `%USERPROFILE%` |

盘点数据里 `path` 一律是绝对路径给执行器用，`path_portable` 一律用 `%USERPROFILE%\` 开头，不带用户名。
