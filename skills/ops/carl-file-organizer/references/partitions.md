# 分区表与静置期

两套分区，一套中文一套英文，同一份规则。语言不是翻译问题，是目录名问题：
中文机器上建出来的目录叫 `20_知识库/文档资料/PDF`，英文机器上叫 `20_Library/Documents/PDF`，
规则、去向、静置期完全一样。

选哪套由 `plan.lang` 决定，来源写在 `plan.lang_source`（`flag` / `dotfile` / `env` /
`existing-dirs` / `apple-languages` / `posix-locale` / `default`）。
目录里已经有一套分区时，就跟着已有的那套走，不会在旁边建第二套。

计划里的 `names` 字段是本次解析出来的 key 到相对路径的对照表，页面和 Agent 直接读它，
不必回头翻这份文档。这里是给人看的版本。

## tiered：默认那套，按用途分层

| key | 中文 | English | 收什么 | 静置期 |
|---|---|---|---|---|
| `inbox` | 00_收件箱 | 00_Inbox | 下面三个子区的父目录 | |
| `inbox.pending` | 待判断 | Pending | 未知扩展名、顶层目录、派生副本 | 无 |
| `inbox.by_tag` | 按标签 | By_Tag | 你自己打了访达标签、且打开了按标签分组时 | 无 |
| `inbox.dup` | 重复待确认 | Duplicates_Review | 目标位置已被占，改名后转到这里 | 无 |
| `work.tools.scripts` | 10_工作区/工具与导出/脚本 | 10_Workspace/Tools_Exports/Scripts | `.js` `.py` `.sh` | 无 |
| `work.db.sql` | 10_工作区/数据库与查询/SQL | 10_Workspace/Database/SQL | `.sql` | 无 |
| `library.docs.md` | 20_知识库/文档资料/Markdown | 20_Library/Documents/Markdown | `.md` | 无 |
| `library.docs.pdf` | 20_知识库/文档资料/PDF | 20_Library/Documents/PDF | `.pdf` | 无 |
| `library.docs.ppt` | 20_知识库/文档资料/PPT | 20_Library/Documents/PPT | `.ppt` `.pptx` | 无 |
| `library.docs.office` | 20_知识库/文档资料/办公文档 | 20_Library/Documents/Office | `.doc` `.docx` `.xls` `.xlsx` | 无 |
| `library.docs.csv` | 20_知识库/文档资料/CSV | 20_Library/Documents/CSV | `.csv` | 无 |
| `library.docs.txt` | 20_知识库/文档资料/TXT | 20_Library/Documents/TXT | `.txt` | 无 |
| `library.images.png` | 20_知识库/图片素材/PNG | 20_Library/Images/PNG | `.png` | 无 |
| `library.images.jpeg` | 20_知识库/图片素材/JPEG | 20_Library/Images/JPEG | `.jpg` `.jpeg` | 无 |
| `library.images.gif` | 20_知识库/图片素材/GIF | 20_Library/Images/GIF | `.gif` | 无 |
| `library.images.other` | 20_知识库/图片素材/其他图片 | 20_Library/Images/Other | `.webp` `.heic` `.svg` | 无 |
| `library.video.mp4` | 20_知识库/视频素材/MP4 | 20_Library/Video/MP4 | `.mp4` | 无 |
| `library.video.mov` | 20_知识库/视频素材/MOV | 20_Library/Video/MOV | `.mov` | 无 |
| `library.audio` | 20_知识库/音频素材 | 20_Library/Audio | `.mp3` `.m4a` `.wav` | 无 |
| `library.web.html` | 20_知识库/网页资料/HTML | 20_Library/Web/HTML | `.html` | 无 |
| `sensitive.pending` | 60_敏感信息/待转移 | 60_Sensitive/Pending | 名字看着像凭证的条目 | 无 |
| `sensitive.dup` | 60_敏感信息/重复待确认 | 60_Sensitive/Duplicates_Review | 敏感区里目标被占的那些 | 无 |
| `archive.zip.zip` | 90_归档/压缩包/ZIP | 90_Archive/Compressed/ZIP | `.zip` | 168 小时 |
| `archive.zip.other` | 90_归档/压缩包/其他压缩包 | 90_Archive/Compressed/Other | `.7z` `.rar` `.tar.gz` | 168 小时 |
| `archive.installers.dmg` | 90_归档/安装包/DMG | 90_Archive/Installers/DMG | `.dmg` | 168 小时 |
| `archive.installers.other` | 90_归档/安装包/其他安装包 | 90_Archive/Installers/Other | `.pkg` `.iso` | 168 小时 |

管理目录本身叫 `00_下载目录管理` / `00_File_Organizer`，plan.json、report.html、
清单和审计日志都落在那里。它自己永远不参与扫描。

## simple：不想分那么细的时候

一层七个目录，名字中英文相同：`Documents`、`Images`、`Video`、`Audio`、
`Archives`、`Installers`、`Code & Data`，另加 `Other`（也就是 `inbox`）、
`Other/Pending`、`Other/Duplicates_Review`、`Sensitive`、`Sensitive/Pending`、
`Sensitive/Duplicates_Review`。

simple 的静置期一律为 0：这套是给「先把桌面清出来」用的，不做等待。
用 `plan --profile simple` 选它。

## 静置期

静置期就一句话：刚下载完的东西不动。

| 类别 | tiered | simple |
|---|---|---|
| 压缩包与安装包（`archive_hours`） | 168 小时，也就是七天 | 0 |
| 其他有规则的类型（`default_hours`） | 48 小时 | 0 |

静置未满的条目不会被移动，会变成一条 `hold:aging`，颜色是红的，
`hold_reason.ready_at` 写着到什么时候就可以了。下次跑 plan 的时候它自己就出来了，
不用你记着。

判断用的是修改时间，基准是 `plan.now`；`--now` 能把这个基准钉住，
所以同一份目录跑两遍出来的计划是一样的。

## 改成你自己的

分区名、扩展名规则、静置期、常驻白名单、敏感词都能在设置文件里改，
设置文件是 `<扫描目录>/00_下载目录管理/.file-organizer.json`，
第一次跑 plan 时会自动写一份出来。改完再跑一次 plan，
`plan.profile.source` 会变成 `builtin+dotfile`，`plan.profile.hash` 跟着变。

改设置只影响新算出来的计划。已经批准过的计划里的目标路径是当时算好的，
不会因为你改了设置就跟着变。
