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
        "zh": "文档按类型归档到 {dest}",
        "en": "Document filed by type into {dest}",
    },
    "ext_image": {
        "zh": "图片按类型归档到 {dest}",
        "en": "Image filed by type into {dest}",
    },
    "ext_video": {
        "zh": "视频按类型归档到 {dest}",
        "en": "Video filed by type into {dest}",
    },
    "ext_audio": {
        "zh": "音频按类型归档到 {dest}",
        "en": "Audio filed by type into {dest}",
    },
    "ext_web": {
        "zh": "网页文件按类型归档到 {dest}",
        "en": "Web file filed by type into {dest}",
    },
    "ext_script": {
        "zh": "脚本归入工具与导出",
        "en": "Script filed under tools and exports",
    },
    "ext_data": {
        "zh": "数据文件归入数据库与查询",
        "en": "Data file filed under database and queries",
    },
    "ext_archive": {
        "zh": "压缩包静置满 {hours} 小时后归档",
        "en": "Archive filed after sitting still for {hours}h",
    },
    "ext_installer": {
        "zh": "安装包静置满 {hours} 小时后归档",
        "en": "Installer filed after sitting still for {hours}h",
    },
    "ext_other": {
        "zh": "按扩展名规则归档到 {dest}",
        "en": "Filed by extension rule into {dest}",
    },
    # --- sensitive -------------------------------------------------------
    "sensitive_isolated": {
        "zh": "名字看着像凭证，先单独隔离，未读取内容",
        "en": "The name looks like a credential, so it is isolated; contents were never read",
    },
    "sensitive_manual": {
        "zh": "你标成了敏感，移到敏感信息区，未读取内容",
        "en": "Marked sensitive by you; moved to the sensitive area, contents were never read",
    },
    # --- directories -----------------------------------------------------
    "dir_pending": {
        "zh": "整个目录保留原名，先进待判断",
        "en": "Whole folder keeps its name and waits in Pending",
    },
    "dir_derivative": {
        "zh": "看着像某个目录的衍生副本（{hint}），先进待判断",
        "en": "Looks like a derived copy ({hint}); waits in Pending",
    },
    # --- grouping --------------------------------------------------------
    "pair": {
        "zh": "压缩包和解压目录是一对，默认建议留目录",
        "en": "Archive and extracted folder are a pair; keeping the folder is suggested",
    },
    "dup_sha256": {
        "zh": "内容完全相同（sha256 一致），留一份就够",
        "en": "Byte-identical (same sha256); one copy is enough",
    },
    "dup_name": {
        "zh": "名字像副本，但内容没有逐字节比对过，默认都留着",
        "en": "Names look like copies, but the contents were not compared; both are kept by default",
    },
    "regenerable": {
        "zh": "构建产物，删掉还能再生成（{restore}）",
        "en": "Build output; it can be regenerated ({restore})",
    },
    # --- cold storage candidates ----------------------------------------
    "cold_large": {
        "zh": "体积较大（{size}），可以考虑处置",
        "en": "Large item ({size}); worth a decision",
    },
    "cold_installer": {
        "zh": "安装包或压缩包用完通常就不需要了",
        "en": "Installers and archives are usually disposable once used",
    },
    # --- conflicts and unknowns -----------------------------------------
    "conflict": {
        "zh": "目标位置已经有同名文件，不覆盖，改放重复待确认",
        "en": "The destination already exists; nothing is overwritten, it goes to Duplicates Review",
    },
    "unknown_ext": {
        "zh": "扩展名不在规则表里，先进待判断，可以在页面上改去向",
        "en": "Extension is not in the rule table; it waits in Pending and can be rerouted",
    },
    "name_pattern": {
        "zh": "命中你自己写的名字规则 {pattern}",
        "en": "Matched your own name rule {pattern}",
    },
    "tag_group": {
        "zh": "按你打的 Finder 标签 {tag} 归组",
        "en": "Grouped by your Finder tag {tag}",
    },
    # --- holds -----------------------------------------------------------
    "hold_aging": {
        "zh": "还在静置期，已放 {age} 小时，满 {needed} 小时再动",
        "en": "Still settling: {age}h of the required {needed}h",
    },
    "hold_pinned": {
        "zh": "你把它挪回顶层过，算常驻，不再动它",
        "en": "You put it back at the top level, so it stays put",
    },
    "hold_forbidden": {
        "zh": "禁刀区，只展示不处理（{label}）",
        "en": "No-go zone, shown but never touched ({label})",
    },
    "hold_in_use": {
        "zh": "现在有进程开着它：{who}，先不动",
        "en": "A process still has it open: {who}",
    },
    "hold_referenced": {
        "zh": "有配置或脚本引用了这个路径：{where}，动它之前先改引用",
        "en": "A config or script references this path: {where}; fix the reference first",
    },
    "hold_recent": {
        "zh": "十分钟内刚改过，先放一放",
        "en": "Changed within the last ten minutes; leaving it alone",
    },
    "hold_worktree": {
        "zh": "这是 git worktree，路径写死在别处，不能搬",
        "en": "This is a git worktree; its path is recorded elsewhere and must not move",
    },
    "hold_no_trash": {
        "zh": "这台机器没有可用的废纸篓后端，处置选项不可用",
        "en": "No trash backend on this machine, so disposal is unavailable",
    },
    # --- hints -----------------------------------------------------------
    "hint_git_repo": {
        "zh": "这是 git 仓库，搬之前建议先 push，未提交 {count} 项",
        "en": "Git repository; consider pushing first, {count} uncommitted item(s)",
    },
    "hint_venv": {
        "zh": "里面有虚拟环境，路径写死在文件里，搬完需要重建",
        "en": "Contains a virtualenv with absolute paths baked in; rebuild after moving",
    },
    "hint_dotenv": {
        "zh": "里面有 .env，搬之前确认没有别的程序在读它",
        "en": "Contains a .env; check nothing else reads it before moving",
    },
    "hint_derivative": {
        "zh": "名字里带 {hint}，像是临时副本",
        "en": "Name contains {hint}, which looks like a scratch copy",
    },
    # --- details ---------------------------------------------------------
    "detail_aged": {
        "zh": "静置 {age} 小时，已满 {needed} 小时",
        "en": "aged {age}h, past the {needed}h threshold",
    },
    "detail_sensitive": {
        "zh": "命中敏感词 {needle}，不看静置期",
        "en": "matched {needle}; the settling period is skipped",
    },
    "detail_pair": {
        "zh": "和 {other} 同名成对，一起搬进 {dest}",
        "en": "pairs with {other} by name; both go to {dest}",
    },
    "detail_dup_unverified": {
        "zh": "名字像副本，内容没有比对过",
        "en": "the name looks like a copy; contents were not compared",
    },
    "detail_referenced_warning": {
        "zh": "别处引用了它（{where}），你让它照常处理，动完记得改引用",
        "en": "It is referenced elsewhere ({where}); you allowed it anyway, so fix the reference afterwards",
    },
    "detail_dir_truncated": {
        "zh": "目录太大，统计到上限就停了，体积是下限值",
        "en": "The folder is large; counting stopped at the cap, so the size is a lower bound",
    },
    "detail_no_trash": {
        "zh": "这台机器没有废纸篓后端，只给了永久删除",
        "en": "No trash backend on this machine, so only permanent delete is offered",
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
        "zh": "删掉就没了，只对可再生的构建产物用这一项",
        "en": "Permanent; only use this for regenerable build output",
    },
    # --- folder mess, one line per colour ---------------------------------
    "mess_green": {
        "zh": "散件 {loose} 件，没有等着你判断的东西，这个目录现在是清爽的",
        "en": "{loose} loose items and nothing waiting on you; this folder is in good shape",
    },
    "mess_yellow": {
        "zh": "散件 {loose} 件，其中 {pending} 件要你看一眼，还没到失控的地步",
        "en": "{loose} loose items, {pending} of them want a look from you; not out of hand yet",
    },
    "mess_red": {
        "zh": "散件 {loose} 件，{pending} 件待判断，另有 {groups} 组重复或可再生的东西，该花点时间了",
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
    "cli_plan_written": {"zh": "计划：{path}", "en": "Plan:   {path}"},
    "cli_report_written": {"zh": "审核页：{path}", "en": "Review: {path}"},
    "cli_nothing_moved": {
        "zh": "本次只读扫描，没有移动或删除任何文件。",
        "en": "Read-only scan. Nothing was moved or deleted.",
    },
    "cli_dotfile_written": {"zh": "已记住设置：{path}", "en": "Settings remembered: {path}"},
    "cli_notes_merged": {
        "zh": "说明已并入计划：{path}（{count} 条提醒）",
        "en": "Notes merged into the plan: {path} ({count} warning(s))",
    },
    "cli_lang_source": {"zh": "语言：{lang}（来自 {source}）", "en": "Language: {lang} (from {source})"},
    "cli_not_implemented": {
        "zh": "子命令 {command} 还没接上：{module} 里没有 run 入口。",
        "en": "Subcommand {command} is not wired up yet: {module} provides no run() entry point.",
    },
    "cli_lang_ambiguous": {
        "zh": "这个目录里中英文分区都有，说不准该用哪套，请加 --lang zh 或 --lang en。",
        "en": "This folder has both Chinese and English partitions; pass --lang zh or --lang en.",
    },
    "warning_prefix": {"zh": "提醒：", "en": "warning: "},
    "section_pending_moves": {"zh": "待批准移动", "en": "Moves awaiting approval"},
    "section_groups": {"zh": "配对与重复", "en": "Pairs and duplicates"},
    "section_disposal": {"zh": "可再生与冷存候选", "en": "Regenerable and cold candidates"},
    "section_holding": {"zh": "静置中与常驻", "en": "Settling and pinned"},
    "section_forbidden": {"zh": "禁刀区", "en": "No-go zone"},
    "section_undecided": {"zh": "待判断", "en": "Undecided"},
    "button_export": {"zh": "导出批准文件", "en": "Export approved plan"},
    "button_apply": {"zh": "执行已勾选的项", "en": "Apply the checked items"},
    "button_show_delete": {"zh": "显示永久删除选项", "en": "Show permanent delete options"},
    "banner_reversible": {
        "zh": "移动只改路径不删内容。哪个软件找不到文件了，用 undo 或者清单里的 mv 命令原路放回。",
        "en": "Moving only changes paths. If something cannot find a file, use undo or the mv line in the manifest.",
    },
    "banner_do_not_touch": {
        "zh": "计划生成之后先别动这些目录，动过的会在执行时自动跳过。",
        "en": "Do not touch these folders after the plan is generated; changed ones are skipped at apply time.",
    },
    "option_keep_all": {"zh": "都保留，一起搬进待判断", "en": "Keep both, move them together"},
    "option_keep_one": {"zh": "留 {keep}，{drop} 进废纸篓", "en": "Keep {keep}, trash {drop}"},
    "option_keep_one_delete": {
        "zh": "留 {keep}，{drop} 永久删除",
        "en": "Keep {keep}, permanently delete {drop}",
    },
    "option_trash_all": {"zh": "全部进废纸篓", "en": "Trash all of them"},
    "option_delete_all": {"zh": "全部永久删除", "en": "Permanently delete all of them"},
    "option_keep_all_plain": {"zh": "都保留", "en": "Keep both"},
    "cli_report_skipped": {
        "zh": "审核页还没接上（{module}），这次只写了计划文件。",
        "en": "The review page is not wired up yet ({module}); only the plan file was written.",
    },
    "cli_scan_summary": {
        "zh": "扫描到 {entries} 项，候选动作 {actions} 条，其中待批准 {approvable} 条。",
        "en": "Scanned {entries} item(s), {actions} candidate action(s), {approvable} awaiting approval.",
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
