# 报告页视觉规范（report.html，v0.3 三色版）

报告页是整个 skill 唯一给人看的界面。一份模板三种形态，由 `data-kind` 决定：`combined` 是人真正看到的那一份，清理和搬动写在同一页，末尾带整理后预览；`organize` 只有整理这一半，`storage` 只有盘点这一半，两者是分步命令留下的旧形态。页面不加载任何外部资源，双击打开 file:// 也是零请求；同一份模板在 static 与 serve 两种模式下长得一样，只有底栏按钮的动作不同。

三个文件对应本文：`assets/report_template.html` 是模板（样式、脚本、顶部的 TEXT 文案表），`scripts/build_report.py` 负责把数据脱敏后渲染成正文并注入模板，仓库根 `tests/test_cfo_report_template.py` 逐条断言本文的约束。改样式先改模板，改文案只改 TEXT。

## combined：一份报告，一个入口，一份批准文件

`render(data)` 收到 `{"plan": plan, "analysis": analysis}` 就渲染这一份。两半都在最好，只给一半也能渲染，页面上就少一块。两半分别脱敏，因为整理那半能从 `source_root` 反推自己的家目录，盘点那半没有这一对字段，只能退回当前账号的家目录。

```
顶栏         目录 · 机器 · 扫描时间 · 模式
页面标题 + 一句引导
总览双卡     左：磁盘条（盘点）+ 杂乱度大字与三色分段（整理）+ 一句话
             右：先做什么，analysis.overview.priority 与整理三条建议合成一个编号清单
最大的五项   只有带 analysis 时才有
三色三个区   green → yellow → red，每区先「清理」后「搬动」两个小标题
整理后预览   标题「整理后长这样」，下面是 preview.py 渲染的自足片段
长期建议     盘点的 overview.long_term，加整理的静置到期时间与固定说明
底栏         一个主按钮
```

小标题是 `<h3 class="subhead">`，空的那一组不渲染标题也不占位。三个区永远都在，整区空了才写一句本组没有条目。

预览片段来自 `carl_file_organizer.preview`：`build_graph(plan, analysis)` 出图，`render_preview_html(graph, lang=, height=720)` 出片段，整块包在 `<section class="preview-wrap" id="gn-preview">` 里。片段自带样式和脚本，不加载任何外部资源，全页只出现一次。页面上勾选或取消任何一项时，`refresh()` 会 `window.dispatchEvent(new CustomEvent('cfo:selection', {detail: {action_ids, item_ids}}))`，预览里监听这个事件，把没勾中的「要搬」节点画成空心，并改写面板上的要搬与留下计数。首次渲染不发这个事件，所以打开页面看到的仍是完整的整理后状态。

## combined 的批准文件

static 模式底栏只有一个按钮，导出一份 `carl-file-organizer-decisions.json`：

```json
{
  "schema": "carl-file-organizer/decisions",
  "schema_version": 1,
  "decided_at": "2026-09-02T12:00:00+09:00",
  "decided_by": "html-static",
  "plan": {
    "approved_action_ids": ["9c1f0a7b2d3e4f55"],
    "overrides": [{"action_id": "0112233445566a7b", "destination_key": "work.data"}],
    "document": { "...": "渲染时用的 plan.json，已脱敏" }
  },
  "storage": {
    "item_ids": ["st-pip-cache"],
    "actions": {"st-pip-cache": "trash"},
    "document": { "...": "渲染时用的 analysis.json，已脱敏" }
  }
}
```

`document` 两块是页面顺手带上的来源文件，所以 `apply` 只要这一个参数就够。两块都能缺，缺了就用 `--plan`、`--analysis` 或 `--managed-dir` 指过去。`apply` 先跑整理那段再跑盘点那段，两段各自写清单和审计，最后打一行合计。

serve 模式底栏是「执行全部已选」，前端按类型拆开：先 POST `/api/apply`（body `{action_ids, overrides, dry_run}`），再 POST `/api/dispose`（body `{item_ids, action}`，废纸篓一次永久删除一次），逐项回显状态。同一个服务两个端点都接，`/api/plan` 返回 `{plan, analysis, executed_ids}`，两半共用一份 `executed_ids`。

## 一句话原则

三色是核心，别的都让路。绿是放心做，黄是你看一眼，红是别动。强调色用墨色，页面里没有蓝，没有渐变，没有深色模式。危险动作靠文字说清楚，按钮权限跟颜色走。

## Token 表

| token | 值 | 用途 |
|---|---|---|
| `--bg` | `#f6f7f9` | 页面底、命令块底 |
| `--card` | `#ffffff` | 卡片底 |
| `--ink` | `#1d2129` | 正文、主按钮底、勾选框选中色，也是唯一的强调色 |
| `--muted` | `#86909c` | 次要文字、表头、路径 |
| `--line` | `#e5e6eb` | 1px 分隔线、次按钮描边 |
| `--green` / `--green-bg` | `#00b42a` / `#e8ffea` | 放心归位、可清 |
| `--yellow` / `--yellow-bg` | `#ff7d00` / `#fff7e8` | 你看一眼 |
| `--red` / `--red-bg` | `#f53f3f` / `#ffece8` | 别动 |
| `--other` | `#c9cdd4` | 磁盘条里的其他占用、无色的点 |
| `--radius` | `14px` | 卡片圆角；命令块、按钮、下拉用 `--radius-s` 8px |
| `--shadow` | `0 1px 3px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.04)` | 所有卡片同一个浅阴影 |

字体：正文 `-apple-system, "PingFang SC", "Segoe UI", "Noto Sans CJK SC", "Helvetica Neue", Arial, sans-serif`，15px 行高 1.6；路径、命令、id 用 `ui-monospace, "SF Mono", Menlo, Consolas, "Noto Sans Mono CJK SC", monospace`，13px。标题只有页面标题 26px/700 和分区标题 18px/700，小节标题 13px 灰色大写字距。没有 web font。

## 布局（从上到下，organize 与 storage 两种旧形态）

combined 的布局见开头那一节，下面这份是分步命令产出的单半页面。

```
顶栏（sticky top，白底 92% 透明加轻微模糊，底边 1px）
  标题 · 目录或机器 · 扫描时间 · 模式；serve 时多一行「本页只在这台机器可见」
页面标题 + 一句引导
总览网格（两列，窄屏单列）
  整理页左：杂乱度大字 + 三色 pill + 计数小字 + 三色分段条 + 三色图例 + 一句话
  盘点页左：每块磁盘一条（已用拆成 绿/黄/红/其他 四段加可用）+ 三色占比条 + 一句话 + 系统信息网格
  右：执行建议卡「先做什么」，整理页按三色计数各一句，盘点页用 overview.priority；有绿项时给「勾选全部绿项」按钮
Top 5 表（只有盘点页）：色点 · 大小 · 类型 · 名字 · 路径 · 一句话
三色分区 green → yellow → red，每区一个 <section class="sec" data-color="…">
  分区头：色点 + 标题 + 计数 + 一句说明 + 工具（全部展开 / 本组全选 / serve 的执行本组 / 绿区的永久删除开关）
  每项一张 <article class="item" data-color="…">，左侧 4px 色条
长期建议卡：盘点页 overview.long_term；整理页列静置中的到期时间，再放 undo 提示与三句固定说明
底栏（sticky bottom）：已选计数 + 主按钮（static 导出，serve 执行）
```

三个分区永远都渲染，空的写一句本组没有条目。分段条的每一段用 `style="width:NN%"`，NN 按数量或字节向下取整，所以宽度之和永远不超过 100。

## 卡片

卡片头：勾选框（有权限才有）、名字、徽章（目录、敏感命名、待判断、去向、类型、组类型、可腾出）、大小、状态、折叠箭头。点头部空白处展开，点控件不展开。

卡片体：路径（等宽）、目录统计与标签、`这是什么 / 为什么这么判 / 动了会怎样 / 怎么恢复` 四行、命令块带复制按钮、控件行。

四行文案的来源：Agent 写了 notes 就用 notes（`notes.actions[id]`、`notes.groups[id]`、`notes.items[id]` 里的 `what / why / if_removed`），没写就回落到脚本的 `reason / detail / hold_reason / restore_method`（整理页）或条目自带的 `what / why / if_removed / restore`（盘点页）。空行不渲染。

## 按钮权限跟色走

| 颜色 | 整理页 | 盘点页 |
|---|---|---|
| green | 勾选执行；trash/delete 候选给单选，永久删除折叠在开关后并弹 confirm | 勾选；废纸篓单选默认选中，永久删除折叠在开关后 |
| yellow | 勾选移动或进废纸篓（都可逆）；配对与重复组的单选；待判断的去向下拉写进 overrides | 只有「移到废纸篓（可逆）」，且仅当 `trash_paths` 非空；serve 时多「打开所在位置」 |
| red | 没有任何 input，没有 `data-action="trash|delete"`；serve 时只有「打开所在位置」 | 同左 |

判色顺序：数据里带 `color` 就用它；没有则整理页按 kind/tier 推（hold 或 forbidden/in_use/referenced/aging/pinned 是红，reroutable 或 duplicate/cold 是黄，其余绿；组里 regenerable 绿、pair/duplicate 黄），盘点页按 tier 和 `open_by`、`trash_paths` 推。

带永久删除的选项加 `needs-permanent` 类，`body[data-permanent="off"]` 时整体隐藏并 disabled；打开绿区的开关才显示。选中时弹 `confirm()`，文案含路径与大小，取消就退回默认选项。yellow 区永远不渲染永久删除选项，即便数据里有。

## 控件 data 属性

- 勾选框 `input.gn-pick`：整理页移动带 `data-action-id`，候选行带 `data-choice`；盘点页带 `data-item-id` 与 `data-choice`。
- 单选 `input.gn-choice`：`data-action="trash|delete"`，永久删除再带 `data-kind="delete"`、`data-path`、`data-size`。
- 组：`article[data-group-id]` 内 `input.gn-adopt` 与 `input.gn-option[data-action-ids]`，页面只按 `options[].action_ids` 映射，不自己推导。
- 待判断下拉 `select.gn-dest`，`data-original` 记原去向，改了才写进 overrides。
- 按钮 `data-action="copy"` 复制同块 `<code>`；`data-action="reveal"` 带 `data-path`，只在 serve 渲染。
- 状态回写按 `[data-ids]` 匹配 id，`.gn-status` 显示文字，`done` 时禁用该卡片全部控件。

## static 与 serve

| | static | serve |
|---|---|---|
| 主按钮 | combined 导出一份 `carl-file-organizer-decisions.json`（格式见上）；整理页导出 `carl-file-organizer-approved.json`（plan 本身加 `approved_action_ids / overrides / approved_at / approved_by`）；盘点页导出 `carl-file-organizer-decisions.json` 的旧格式（`item_ids` 加每个 id 的 `actions` 映射） | combined 先 POST `/api/apply` 再 POST `/api/dispose`；整理页只 POST `/api/apply`，body `{action_ids, overrides, dry_run}`；盘点页只 POST `/api/dispose`，按动作分两次，body `{item_ids, action: "trash"\|"delete"}` |
| 其他按钮 | 无 | 停止服务（POST `/api/shutdown`）；带整理那半时多「先预演」；分区头多「执行本组已选」 |
| 打开所在位置 | 不渲染 | POST `/api/reveal`，body `{path_portable}` |
| token | 不嵌 | 嵌进 config，也接受 `?t=` 后立即从地址栏抹掉；请求头 `X-GN-Token` |
| 启动时 | 无请求 | 带整理那半时 GET `/api/plan` 同步 `executed_ids` 与 `permanent_delete_enabled` |

服务端响应 `{results: [{action_id 或 item_id, status, detail}]}`，status 取 `moved / trashed / deleted / dry-run / skipped / refused / failed`。

## 脱敏

页面和内嵌 JSON 里一个绝对路径都没有。渲染前整份数据过 `build_report.sanitize()`，combined 的两半各过一遍：`source_root`、`managed_dir`、每条 action 的 `source` 与 `destination`、每个 item 的 `path` 直接删掉，只留 `_portable` 双胞胎；其余任何字符串里出现家目录（按 plan 反推的 home，以及 `/Users/x`、`/home/x`、`C:\Users\x` 三种形态）都改写成 `$HOME`。测试扫整页不许出现 `/Users/`。

## 文案

所有固定文案都在模板顶部 `<script id="report-text">` 的 TEXT 表里，zh 与 en 两份键集合完全一致，build_report.py 从同一块读取来渲染正文，页面脚本也从它取 confirm 与状态文案。改文案只改这一处。

## 打印

`@media print` 隐藏所有按钮、开关、折叠箭头、控件行和整理后预览，卡片全部展开，阴影换成 1px 边，顶栏与底栏取消 sticky。预览是张要拖要缩的画布，印在纸上没有意义。

## 为什么不做深色模式

三色语义在深色底上要重新调，成本高收益低；报告页看几分钟就关，浅灰底白卡片在任何屏幕上都稳。
