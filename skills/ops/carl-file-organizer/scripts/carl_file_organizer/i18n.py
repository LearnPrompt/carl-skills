"""Bilingual strings: UI copy and plan reason text.

Two entry points are frozen for every work package:

    t(key, lang, **kw)       UI copy (buttons, headings, CLI lines)
    reason(key, lang, **kw)  one line of plan reasoning

``both(key, **kw)`` is a convenience that returns ``{"zh": ..., "en": ...}``,
which is exactly the shape plan.json stores in ``action.reason`` /
``action.detail`` / ``group.reason``.

Rules for editors: keys are only ever added, never renamed or removed; the zh
column avoids straight double quotes and reads like a person talking.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

LANGS = ("zh", "en")
DEFAULT_LANG = "en"

#: Reason text attached to actions and groups.
REASONS: Dict[str, Dict[str, str]] = {
    # --- extension rules -------------------------------------------------
    "ext_doc": {
        "zh": "文档，按类型放进 {dest}",
        "en": "A document, so it goes by type into {dest}",
    },
    "ext_image": {
        "zh": "图片，按类型放进 {dest}",
        "en": "An image, so it goes by type into {dest}",
    },
    "ext_video": {
        "zh": "视频，按类型放进 {dest}",
        "en": "A video, so it goes by type into {dest}",
    },
    "ext_audio": {
        "zh": "音频，按类型放进 {dest}",
        "en": "Audio, so it goes by type into {dest}",
    },
    "ext_web": {
        "zh": "网页文件，按类型放进 {dest}",
        "en": "A saved web page, so it goes by type into {dest}",
    },
    "ext_script": {
        "zh": "脚本，放进工具与导出",
        "en": "A script, so it goes under tools and exports",
    },
    "ext_data": {
        "zh": "数据文件，放进数据库与查询",
        "en": "A data file, so it goes under database and queries",
    },
    "ext_archive": {
        "zh": "压缩包，放满 {hours} 小时没人动过，可以归档了",
        "en": "An archive that has sat untouched for {hours}h, ready to be filed away",
    },
    "ext_installer": {
        "zh": "安装包，放满 {hours} 小时没人动过，可以归档了",
        "en": "An installer that has sat untouched for {hours}h, ready to be filed away",
    },
    "ext_other": {
        "zh": "扩展名规则命中，放进 {dest}",
        "en": "The extension matched a rule, so it goes into {dest}",
    },
    # --- sensitive -------------------------------------------------------
    "sensitive_isolated": {
        "zh": "名字看着像凭证，先单独隔离起来，未读取内容",
        "en": "The name looks like a credential, so it is set aside on its own; the contents were never read",
    },
    "sensitive_manual": {
        "zh": "你自己标成了敏感，移到敏感信息区，未读取内容",
        "en": "You marked it sensitive, so it goes to the sensitive area; the contents were never read",
    },
    # --- directories -----------------------------------------------------
    "dir_pending": {
        "zh": "整个目录原样搬进待判断，名字不动，里面不拆",
        "en": "The whole folder goes to Pending as it is, name and contents untouched",
    },
    "dir_derivative": {
        "zh": "看着像别的目录的一份副本（{hint}），先放待判断，你来定",
        "en": "Looks like a copy of another folder ({hint}); it waits in Pending for you",
    },
    # --- grouping --------------------------------------------------------
    "pair": {
        "zh": "压缩包和它解压出来的目录是一对，建议留目录",
        "en": "The archive and the folder it unpacked into are a pair; keeping the folder is the usual call",
    },
    "dup_sha256": {
        "zh": "内容一模一样，sha256 对得上，留一份就够",
        "en": "Byte for byte the same, the sha256 matches; one copy is enough",
    },
    "dup_name": {
        "zh": "名字像副本，但内容没有逐字节比过，默认两份都留着",
        "en": "The names look like copies, but the contents were never compared, so both stay by default",
    },
    "regenerable": {
        "zh": "构建产物，删了还能再生成，{restore}",
        "en": "Build output, it can be made again ({restore})",
    },
    # --- cold storage candidates ----------------------------------------
    "cold_large": {
        "zh": "个头不小（{size}），要不要留只有你知道",
        "en": "A big one ({size}); only you know whether it is still wanted",
    },
    "cold_installer": {
        "zh": "安装包或压缩包，装完解完通常就用不上了",
        "en": "An installer or archive; once used, it is usually done with",
    },
    # --- conflicts and unknowns -----------------------------------------
    "conflict": {
        "zh": "目标位置已经有同名的东西，不覆盖，改放重复待确认",
        "en": "Something with this name is already at the destination; nothing is overwritten, it goes to Duplicates Review instead",
    },
    "unknown_ext": {
        "zh": "扩展名不在规则表里，先放待判断，页面上可以改去向",
        "en": "The extension is not in the rule table, so it waits in Pending; you can reroute it on the page",
    },
    "name_pattern": {
        "zh": "命中你自己写的名字规则 {pattern}",
        "en": "Matched your own name rule {pattern}",
    },
    "tag_group": {
        "zh": "按你打的 Finder 标签 {tag} 归到一起",
        "en": "Grouped by your Finder tag {tag}",
    },
    # --- holds -----------------------------------------------------------
    "hold_aging": {
        "zh": "刚下载没多久，才放了 {age} 小时，满 {needed} 小时再动",
        "en": "Still fresh, only {age}h in; it moves once it has sat for {needed}h",
    },
    "hold_pinned": {
        "zh": "你之前把它挪回过顶层，算常驻，不再动它",
        "en": "You put it back at the top level once, so it stays put",
    },
    "hold_forbidden": {
        "zh": "禁刀区，只展示不处理（{label}）",
        "en": "No-go zone, shown here but never touched ({label})",
    },
    "hold_in_use": {
        "zh": "现在有进程开着它，{who}，先不动",
        "en": "Something still has it open ({who}), so it stays where it is",
    },
    "hold_referenced": {
        "zh": "有配置或脚本写死了这个路径（{where}），动它之前先改引用",
        "en": "A config or script points at this path ({where}); fix that reference before moving it",
    },
    "hold_recent": {
        "zh": "十分钟内刚改过，先放一放",
        "en": "Changed within the last ten minutes, so it is left alone for now",
    },
    "hold_worktree": {
        "zh": "这是 git worktree，路径写死在主仓库里，搬了就断",
        "en": "This is a git worktree; the main repository records its path, so moving it breaks it",
    },
    "hold_no_trash": {
        "zh": "这台机器没有可用的废纸篓，处置选项先不给",
        "en": "No trash backend on this machine, so disposal is not offered",
    },
    # --- hints -----------------------------------------------------------
    "hint_git_repo": {
        "zh": "这是 git 仓库，还有 {count} 项没提交，搬之前建议先 push",
        "en": "A git repository with {count} uncommitted item(s); consider pushing before moving it",
    },
    "hint_venv": {
        "zh": "里面有虚拟环境，路径写死在文件里，搬完得重建",
        "en": "Contains a virtualenv with absolute paths baked in; rebuild it after the move",
    },
    "hint_dotenv": {
        "zh": "里面有 .env，搬之前确认没有别的程序在读它",
        "en": "Contains a .env; make sure nothing else reads it before moving",
    },
    "hint_derivative": {
        "zh": "名字里带 {hint}，像是随手复制的一份",
        "en": "The name contains {hint}, which looks like a scratch copy",
    },
    # --- details ---------------------------------------------------------
    "detail_aged": {
        "zh": "已经放了 {age} 小时，过了 {needed} 小时的线",
        "en": "sat for {age}h, past the {needed}h line",
    },
    "detail_sensitive": {
        "zh": "命中敏感词 {needle}，不等静置期",
        "en": "matched {needle}; no waiting period for this one",
    },
    "detail_pair": {
        "zh": "和 {other} 同名成对，一起搬进 {dest}",
        "en": "pairs with {other} by name; both go to {dest}",
    },
    "detail_dup_unverified": {
        "zh": "名字像副本，内容没有比过",
        "en": "the name looks like a copy; the contents were not compared",
    },
    "detail_referenced_warning": {
        "zh": "别处引用了它（{where}），你说照常处理，那动完记得改引用",
        "en": "It is referenced elsewhere ({where}); you asked to go ahead anyway, so fix that reference afterwards",
    },
    "detail_dir_truncated": {
        "zh": "目录太大，数到上限就停了，体积只是下限",
        "en": "The folder is big; counting stopped at the cap, so the size is a lower bound",
    },
    "detail_no_trash": {
        "zh": "这台机器没有废纸篓，所以只剩永久删除这一个选项",
        "en": "No trash backend on this machine, so permanent delete is the only option offered",
    },
    # --- restore methods -------------------------------------------------
    "restore_move": {
        "zh": "mv {dest} {src}",
        "en": "mv {dest} {src}",
    },
    "restore_trash": {
        "zh": "在废纸篓里选放回原处",
        "en": "Put Back from the Trash",
    },
    "restore_delete": {
        "zh": "删了就没了，这一项只对能重新生成的构建产物用",
        "en": "Gone for good; only use this on build output that can be regenerated",
    },
    # --- folder mess, one line per colour ---------------------------------
    "mess_green": {
        "zh": "散件 {loose} 件，没有等着你判断的东西，这个目录现在挺清爽",
        "en": "{loose} loose items and nothing waiting on you; this folder is in good shape",
    },
    "mess_yellow": {
        "zh": "散件 {loose} 件，其中 {pending} 件要你看一眼，还没到失控的地步",
        "en": "{loose} loose items, {pending} of them want a look from you; not out of hand yet",
    },
    "mess_red": {
        "zh": "散件 {loose} 件，{pending} 件等你判断，另有 {groups} 组重复或可再生的东西，该花点时间了",
        "en": (
            "{loose} loose items, {pending} waiting on you and {groups} duplicate or "
            "regenerable groups; this one needs real time"
        ),
    },
}

#: UI copy: CLI lines, report headings, buttons.
UI: Dict[str, Dict[str, str]] = {
    "app_name": {"zh": "文件整理", "en": "Carl File Organizer"},
    "tagline": {
        "zh": "先站好队，再决定谁走",
        "en": "Everything lines up first, then you decide what moves",
    },
    "cli_plan_written": {"zh": "计划写在 {path}", "en": "Plan written to {path}"},
    "cli_report_written": {"zh": "审核页在 {path}，双击就能看", "en": "Review page at {path}, open it in a browser"},
    "cli_nothing_moved": {
        "zh": "本次只读扫描，没有移动或删除任何文件。",
        "en": "Read-only scan. Nothing was moved or deleted.",
    },
    "cli_dotfile_written": {"zh": "设置记在 {path}，下次不用再传参数", "en": "Settings remembered in {path}, no flags needed next time"},
    "cli_notes_merged": {
        "zh": "说明已并入计划 {path}，{count} 条提醒",
        "en": "Notes merged into the plan at {path}, {count} warning(s)",
    },
    "cli_lang_source": {"zh": "语言用 {lang}，依据是 {source}", "en": "Language {lang}, decided by {source}"},
    "cli_not_implemented": {
        "zh": "子命令 {command} 还没接上，{module} 里没有 run 入口。",
        "en": "Subcommand {command} is not wired up yet; {module} has no run() entry point.",
    },
    "cli_lang_ambiguous": {
        "zh": "这个目录里中英文分区都有，说不准该用哪套，请加 --lang zh 或 --lang en。",
        "en": "This folder has both Chinese and English partitions and it is not clear which to follow; pass --lang zh or --lang en.",
    },
    "warning_prefix": {"zh": "提醒，", "en": "warning: "},
    "section_pending_moves": {"zh": "等你批准的移动", "en": "Moves awaiting your go-ahead"},
    "section_groups": {"zh": "配对与重复", "en": "Pairs and duplicates"},
    "section_disposal": {"zh": "可再生与冷存候选", "en": "Regenerable and cold candidates"},
    "section_holding": {"zh": "还在静置的与常驻的", "en": "Settling and pinned"},
    "section_forbidden": {"zh": "禁刀区", "en": "No-go zone"},
    "section_undecided": {"zh": "待判断", "en": "Undecided"},
    "button_export": {"zh": "导出批准文件", "en": "Export approved plan"},
    "button_apply": {"zh": "执行已勾选的项", "en": "Apply the checked items"},
    "button_show_delete": {"zh": "显示永久删除选项", "en": "Show permanent delete options"},
    "banner_reversible": {
        "zh": "移动只改路径，内容一个字节都不动。哪个软件找不到文件了，用 undo 或者清单里的 mv 命令原路放回。",
        "en": "Moving only changes the path, never the contents. If some app loses track of a file, run undo or the mv line in the manifest.",
    },
    "banner_do_not_touch": {
        "zh": "计划生成之后先别动这些目录，中途改过的条目执行时会自动跳过。",
        "en": "Leave these folders alone once the plan exists; anything changed in between is skipped at apply time.",
    },
    "option_keep_all": {"zh": "都保留，一起搬进待判断", "en": "Keep both and move them to Pending together"},
    "option_keep_one": {"zh": "留 {keep}，{drop} 进废纸篓", "en": "Keep {keep}, send {drop} to the Trash"},
    "option_keep_one_delete": {
        "zh": "留 {keep}，{drop} 永久删除",
        "en": "Keep {keep}, permanently delete {drop}",
    },
    "option_trash_all": {"zh": "全部进废纸篓", "en": "Send all of them to the Trash"},
    "option_delete_all": {"zh": "全部永久删除", "en": "Permanently delete all of them"},
    "option_keep_all_plain": {"zh": "都保留", "en": "Keep both"},
    "cli_report_skipped": {
        "zh": "审核页还没接上（{module}），这次只写了计划文件。",
        "en": "The review page is not wired up yet ({module}); only the plan file was written.",
    },
    "cli_scan_summary": {
        "zh": "扫到 {entries} 项，候选动作 {actions} 条，其中 {approvable} 条等你批准。",
        "en": "Scanned {entries} item(s), {actions} candidate action(s), {approvable} of them waiting on you.",
    },
    "cli_storage_written": {
        "zh": "整机盘点写在 {path}",
        "en": "Whole-machine scan written to {path}",
    },
    "cli_storage_skipped": {
        "zh": "这次跳过整机盘点，报告里就只有整理这一半。",
        "en": "The whole-machine scan was skipped, so the report carries the tidy-up half only.",
    },
    "cli_storage_failed": {
        "zh": "整机盘点没跑成（{error}），整理这一半照常。",
        "en": "The whole-machine scan did not finish ({error}); the tidy-up half is unaffected.",
    },
    "cli_next_steps": {
        "zh": "下一步，把每一项的人话写进 {notes}，把盘点定色写进 {analysis}，然后跑 report {managed}。",
        "en": "Next: write the plain-language notes into {notes}, the colour calls into {analysis}, then run report {managed}.",
    },
    "cli_report_combined": {
        "zh": "一份报告写在 {path}，清理、搬动和整理后预览都在里面。",
        "en": "One report at {path}: the cleanup, the moves and the after picture together.",
    },
    "cli_nothing_to_report": {
        "zh": "{managed} 里既没有 plan.json 也没有 analysis.json，先跑一次 scan。",
        "en": "{managed} holds neither plan.json nor analysis.json; run scan first.",
    },
    "cli_decisions_plan": {"zh": "先搬动这一半", "en": "The moves first"},
    "cli_decisions_storage": {"zh": "再清理这一半", "en": "The cleanup second"},
    "cli_decisions_empty": {
        "zh": "这份决定清单一项都没勾，什么都没做。",
        "en": "Nothing is ticked in this decisions file, so nothing was done.",
    },
    "cli_decisions_summary": {
        "zh": "两段合计，搬动这段返回 {plan}，清理这段返回 {storage}。",
        "en": "Both halves done: the moves returned {plan}, the cleanup returned {storage}.",
    },
    "cli_decisions_no_analysis": {
        "zh": "决定清单里没带 analysis.json，加 --analysis 指给我，或者改用 dispose 子命令。",
        "en": "The decisions file carries no analysis.json; pass --analysis, or use the dispose subcommand.",
    },
    "cli_decisions_no_plan": {
        "zh": "决定清单里没带 plan.json，加 --plan 指给我。",
        "en": "The decisions file carries no plan.json; pass --plan.",
    },
    "status_last_run": {"zh": "最后整理时间", "en": "Last tidy-up"},
    "status_dirty_now": {"zh": "现在是否又脏了", "en": "Messy again?"},
    "status_never": {"zh": "还没整理过", "en": "not tidied yet"},
}


def _lookup(table: Mapping[str, Mapping[str, str]], key: str, lang: str) -> str:
    entry = table.get(key)
    if entry is None:
        return key
    chosen = entry.get(lang)
    if chosen is None:
        chosen = entry.get(DEFAULT_LANG)
    if chosen is None:
        chosen = next(iter(entry.values()), key)
    return chosen


def _format(template: str, kw: Mapping[str, Any]) -> str:
    if not kw:
        return template
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError):
        return template


def t(key: str, lang: str = DEFAULT_LANG, /, **kw: Any) -> str:
    """UI copy for ``key`` in ``lang``; unknown keys return the key itself.

    ``key`` and ``lang`` are positional-only so a template placeholder may be
    called ``lang`` without colliding with the parameter.
    """

    return _format(_lookup(UI, key, lang), kw)


def reason(key: str, lang: str = DEFAULT_LANG, /, **kw: Any) -> str:
    """Plan reasoning for ``key`` in ``lang``; unknown keys return the key itself."""

    return _format(_lookup(REASONS, key, lang), kw)


def both(key: str, /, **kw: Any) -> Dict[str, str]:
    """``{"zh": ..., "en": ...}`` for a reason key, ready to drop into plan.json."""

    return {lang: reason(key, lang, **kw) for lang in LANGS}


def ui_both(key: str, /, **kw: Any) -> Dict[str, str]:
    """``{"zh": ..., "en": ...}`` for a UI key."""

    return {lang: t(key, lang, **kw) for lang in LANGS}


def has_reason(key: str) -> bool:
    return key in REASONS
