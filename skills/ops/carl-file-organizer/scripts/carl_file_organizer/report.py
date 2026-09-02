"""Self-contained HTML review page: one template, two modes.

``render_report(plan, mode="static"|"serve", token="", lang=None)`` renders the
same controls either way.  Only the bottom bar and the submit function differ:
static exports ``carl-file-organizer-approved.json`` through a Blob download, serve
POSTs to ``/api/apply`` on the local review server.

The page reads nothing but plan.json (schema v2).  It never loads an external
resource, so it works from ``file://`` with zero requests.  Copy lives in the
``TEXT`` table below; ``i18n.py`` is not touched by this module.

One thing the page never sees is an absolute path.  ``render_report`` runs the
plan through :func:`carl_file_organizer.paths.strip_absolute` first, so both the body
and the embedded ``gn-plan`` JSON carry only ``$HOME/...`` spellings and a page
mailed to a colleague does not spell out the user's account name.  The
approved.json exported from the page inherits that, and the executor expands the
twins back at apply time.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from . import paths

LANGS = ("zh", "en")
MODES = ("static", "serve")
PERMANENT_FLAG = "allow-permanent-delete"
HOLD_TIER_PROTECTED = "forbidden"

TEXT: Dict[str, Dict[str, str]] = {
    "zh": {
        "title": "Carl File Organizer 审核页",
        "heading": "整理方案，等你批准",
        "lede": "扫描只读，页面上的每一项都要你亲手勾选才会执行。",
        "bar_path": "目录",
        "bar_time": "扫描时间",
        "bar_pending": "待批准",
        "bar_disk": "卷使用率",
        "bar_reclaim": "可释放估算",
        "bar_mode": "模式",
        "mode_static": "静态页面",
        "mode_serve": "本地服务",
        "serve_note": "本页只在这台机器可见，关掉终端即失效。",
        "pledge": "移动只改路径不删内容，任何软件找不到文件时，用 undo 或清单里的 mv 命令原路放回。",
        "pledge_more": "计划生成后先别改动这些文件和目录，改过的条目执行时会被跳过，重新 plan 即可。",
        "disk_note": "同一卷上移动释放 0 字节，只有进废纸篓和永久删除的行会腾出空间。",
        "items": "项",
        "sec_move": "待批准移动",
        "sec_move_desc": "按扩展名和命名规则归到分区，目录整个搬且保留原名。",
        "sec_pair": "压缩包与解压目录",
        "sec_pair_desc": "成对出现的压缩包和目录，选留谁。默认留目录。",
        "sec_duplicate": "重复文件",
        "sec_duplicate_desc": "内容一致的副本，选留哪一份。名字像副本但没比对过内容的，默认都保留。",
        "sec_regenerable": "可再生产物",
        "sec_regenerable_desc": "构建产物和依赖目录，删掉能重新生成。默认进废纸篓。",
        "sec_cold": "冷存候选",
        "sec_cold_desc": "过了静置期的大文件和安装包。默认进废纸篓，不选就是保留。",
        "sec_hold": "静置中、常驻与被占用",
        "sec_hold_desc": "这一轮不动。静置期没满、常驻白名单、有进程开着、有配置引用着的都在这里。",
        "sec_protected": "禁刀区",
        "sec_protected_desc": "系统库和应用数据，只展示，任何情况下都不处理。",
        "sec_pending": "待判断",
        "sec_pending_desc": "规则表认不出的条目。可以在这里改去向，改动会写进 overrides；拿不准就留在收件箱。",
        "th_pick": "批准",
        "th_file": "文件",
        "th_size": "大小",
        "th_dest": "去向",
        "th_reason": "理由",
        "th_action": "处置",
        "th_restore": "恢复方式",
        "th_status": "状态",
        "th_why": "原因",
        "adopt_group": "采纳这组",
        "opt_trash": "进废纸篓",
        "opt_delete": "永久删除",
        "toggle_permanent": "显示永久删除选项",
        "permanent_not_enabled": "服务启动时没加 --allow-permanent-delete，永久删除在本页不可用。",
        "permanent_static_note": "导出后执行时也要加 --allow-permanent-delete，否则整批拒绝。",
        "no_trash_backend": "本机没有废纸篓后端，进废纸篓的选项已隐藏。",
        "confirm_delete": "永久删除 {path}（{size}）？删掉就没了，废纸篓里也找不到。",
        "confirm_apply": "将执行 {moves} 项移动、{trash} 项进废纸篓、{delete} 项永久删除，预计释放 {bytes}。继续？",
        "confirm_dry": "只试运行，不动任何文件。检查这 {n} 项？",
        "confirm_shutdown": "停掉本地服务？之后要重新运行 review --serve。",
        "nothing_selected": "还没勾选任何项。",
        "exported_note": "批准文件已下载，把它交给 carl-file-organizer apply。",
        "empty": "本组没有条目。",
        "footer_count": "已选 {moves} 项移动 · {trash} 项进废纸篓 · {delete} 项永久删除 · 预计释放 {bytes}",
        "btn_export": "导出批准文件",
        "btn_apply": "执行全部已选",
        "btn_dry": "先试运行",
        "btn_section": "执行本组已选",
        "btn_select_all": "全选本组",
        "btn_clear_all": "清空本组",
        "btn_shutdown": "停止服务",
        "status_working": "处理中",
        "status_moved": "已移动",
        "status_trashed": "已进废纸篓",
        "status_deleted": "已删除",
        "status_dry": "试运行通过",
        "status_failed": "失败，看终端",
        "status_skipped": "已跳过",
        "status_done": "已完成",
        "request_failed": "请求失败：{status} {detail}",
        "network_failed": "连不上本地服务，终端可能已经关掉。",
        "hint": "提示",
        "tags": "标签",
        "dir_files": "{n} 个文件",
        "dir_files_trunc": "至少 {n} 个文件",
        "dir_label": "目录",
        "sensitive_label": "敏感命名",
        "ready_at": "静置到 {time}",
        "open_by": "被进程占用",
        "referenced_in": "被引用",
        "symlinks": "被软链指向",
        "shape": "目录形态",
        "keep_here": "留在原处",
        "potential": "可腾出 {bytes}",
        "restore_trash": "废纸篓里选放回原处",
        "restore_delete": "不可恢复",
        "footer_static_hint": "导出的文件会落到浏览器的下载目录，下次扫描前请交给 apply 或收走。",
        "print_hint": "打印版隐藏按钮，只留清单。",
    },
    "en": {
        "title": "Carl File Organizer review",
        "heading": "A tidy-up proposal, waiting for your approval",
        "lede": "The scan was read-only. Nothing on this page runs until you tick it yourself.",
        "bar_path": "Folder",
        "bar_time": "Scanned",
        "bar_pending": "Awaiting approval",
        "bar_disk": "Volume used",
        "bar_reclaim": "Reclaimable estimate",
        "bar_mode": "Mode",
        "mode_static": "static page",
        "mode_serve": "local server",
        "serve_note": "This page is only reachable from this machine and stops working when the terminal closes.",
        "pledge": "Moves only change the path, never the contents. If any software cannot find a file, run undo or the mv command in the manifest to put it back.",
        "pledge_more": "Leave these files and folders alone until you apply the plan; anything changed in between is skipped, and a fresh plan fixes that.",
        "disk_note": "Moving files between folders on this volume reclaims 0 bytes; only the trash and permanent-delete rows free up space.",
        "items": "items",
        "sec_move": "Moves awaiting approval",
        "sec_move_desc": "Filed by extension and naming rules. Folders move whole and keep their names.",
        "sec_pair": "Archives and their extracted folders",
        "sec_pair_desc": "An archive and its folder found together; pick which one stays. The folder is the default.",
        "sec_duplicate": "Duplicate files",
        "sec_duplicate_desc": "Copies with identical contents; pick the one to keep. Name-only matches default to keeping all.",
        "sec_regenerable": "Regenerable output",
        "sec_regenerable_desc": "Build output and dependency folders that can be rebuilt. Trash is the default.",
        "sec_cold": "Cold storage candidates",
        "sec_cold_desc": "Large files and installers past their settling period. Trash is the default; leave unticked to keep.",
        "sec_hold": "Settling, pinned and in use",
        "sec_hold_desc": "Untouched this round: still settling, pinned by you, held open by a process, or referenced from a config.",
        "sec_protected": "No-go zone",
        "sec_protected_desc": "System libraries and app data. Shown for context, never handled.",
        "sec_pending": "Needs a decision",
        "sec_pending_desc": "Entries the rule table does not recognise. Change the destination here and it is recorded in overrides; when unsure, leave it in the inbox.",
        "th_pick": "Approve",
        "th_file": "File",
        "th_size": "Size",
        "th_dest": "Destination",
        "th_reason": "Why",
        "th_action": "Action",
        "th_restore": "How to restore",
        "th_status": "Status",
        "th_why": "Reason",
        "adopt_group": "Adopt this group",
        "opt_trash": "Move to Trash",
        "opt_delete": "Delete permanently",
        "toggle_permanent": "Show permanent delete options",
        "permanent_not_enabled": "The server was started without --allow-permanent-delete, so permanent deletion is unavailable on this page.",
        "permanent_static_note": "Apply the exported file with --allow-permanent-delete, otherwise the whole batch is refused.",
        "no_trash_backend": "No trash backend on this machine; the trash options are hidden.",
        "confirm_delete": "Permanently delete {path} ({size})? It will not be in the Trash afterwards.",
        "confirm_apply": "Run {moves} moves, {trash} to Trash and {delete} permanent deletes, reclaiming about {bytes}. Continue?",
        "confirm_dry": "Dry run only, nothing is touched. Check these {n} items?",
        "confirm_shutdown": "Stop the local server? You will need to run review --serve again.",
        "nothing_selected": "Nothing is ticked yet.",
        "exported_note": "The approval file was downloaded. Hand it to carl-file-organizer apply.",
        "empty": "Nothing in this group.",
        "footer_count": "{moves} moves · {trash} to Trash · {delete} permanent deletes · about {bytes} reclaimed",
        "btn_export": "Export approved plan",
        "btn_apply": "Apply everything ticked",
        "btn_dry": "Dry run first",
        "btn_section": "Apply this group",
        "btn_select_all": "Select all here",
        "btn_clear_all": "Clear all here",
        "btn_shutdown": "Stop server",
        "status_working": "Working",
        "status_moved": "Moved",
        "status_trashed": "In Trash",
        "status_deleted": "Deleted",
        "status_dry": "Dry run passed",
        "status_failed": "Failed, see terminal",
        "status_skipped": "Skipped",
        "status_done": "Done",
        "request_failed": "Request failed: {status} {detail}",
        "network_failed": "Cannot reach the local server; the terminal may have been closed.",
        "hint": "Hint",
        "tags": "Tags",
        "dir_files": "{n} files",
        "dir_files_trunc": "at least {n} files",
        "dir_label": "folder",
        "sensitive_label": "sensitive name",
        "ready_at": "settles at {time}",
        "open_by": "Held open by",
        "referenced_in": "Referenced in",
        "symlinks": "Symlinked from",
        "shape": "Folder shape",
        "keep_here": "Keep in place",
        "potential": "frees {bytes}",
        "restore_trash": "Put Back from the Trash",
        "restore_delete": "Not recoverable",
        "footer_static_hint": "The export lands in the browser download folder; hand it to apply or move it away before the next scan.",
        "print_hint": "The print version hides the buttons and keeps the list.",
    },
}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _format_bytes(value: Union[int, float, None]) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return "{0:.1f} {1}".format(size, unit) if unit != "B" else "{0} B".format(int(size))
        size /= 1024
    return "{0:.1f} TB".format(size)


def _lang(plan: Dict[str, Any], lang: Optional[str]) -> str:
    chosen = lang or plan.get("lang") or "en"
    return chosen if chosen in LANGS else "en"


def _t(lang: str, key: str, **kw: Any) -> str:
    template = TEXT[lang].get(key) or TEXT["en"].get(key) or key
    if kw:
        try:
            return template.format(**kw)
        except (KeyError, IndexError, ValueError):
            return template
    return template


def _pick(value: Any, lang: str) -> str:
    """A ``{zh, en}`` dict, a plain string or None -> display string."""

    if isinstance(value, dict):
        return str(value.get(lang) or value.get("en") or value.get("zh") or "")
    if value is None:
        return ""
    return str(value)


def _e(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def _embed_json(data: Any) -> str:
    """JSON safe inside a <script> element: no raw ``<``, ``>``, ``&`` or line separators."""

    text = json.dumps(data, ensure_ascii=False)
    return (
        text.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _action_approvable(action: Dict[str, Any]) -> bool:
    return bool(action.get("approvable", action.get("kind", "move") != "hold"))


def _requires_permanent(item: Dict[str, Any]) -> bool:
    return PERMANENT_FLAG in (item.get("requires") or [])


def _empty(lang: str) -> str:
    return '<p class="empty sub">{0}</p>'.format(_t(lang, "empty"))


# --------------------------------------------------------------------------
# fragments shared by several rows
# --------------------------------------------------------------------------


def _file_cell(action: Dict[str, Any], lang: str, *, label_for: Optional[str] = None) -> str:
    name = _e(action.get("filename") or Path(str(action.get("source", ""))).name)
    if label_for:
        title = '<label for="{0}" class="mono name">{1}</label>'.format(_e(label_for), name)
    else:
        title = '<span class="mono name">{0}</span>'.format(name)
    badges: List[str] = []
    if action.get("subject_kind") == "dir":
        badges.append('<span class="badge">{0}</span>'.format(_t(lang, "dir_label")))
    if action.get("tier") == "sensitive":
        badges.append('<span class="badge">{0}</span>'.format(_t(lang, "sensitive_label")))
    extras: List[str] = []
    source = action.get("source_portable") or action.get("source")
    if source:
        extras.append('<div class="sub mono">{0}</div>'.format(_e(source)))
    stats = action.get("dir_stats")
    if isinstance(stats, dict):
        key = "dir_files_trunc" if stats.get("truncated") else "dir_files"
        extras.append('<div class="sub">{0}</div>'.format(_e(_t(lang, key, n=stats.get("files", 0)))))
    tags = [t for t in (action.get("tags") or []) if t]
    if tags:
        extras.append(
            '<div class="sub">{0}: {1}</div>'.format(_t(lang, "tags"), _e(" · ".join(str(t) for t in tags)))
        )
    hints = [str(h) for h in (action.get("hints") or []) if h]
    shape = [str(s) for s in ((action.get("guard") or {}).get("shape") or []) if s]
    hint_bits = hints + [s for s in shape if s not in hints]
    if hint_bits:
        extras.append('<div class="sub">{0}: {1}</div>'.format(_t(lang, "hint"), _e(" · ".join(hint_bits))))
    return '<td class="c-file">{0}{1}{2}</td>'.format(title, "".join(badges), "".join(extras))


def _reason_cell(action: Dict[str, Any], lang: str) -> str:
    body = _e(_pick(action.get("reason"), lang))
    detail = _pick(action.get("detail"), lang)
    if detail:
        body += '<div class="sub">{0}</div>'.format(_e(detail))
    restore = _pick(action.get("restore_method"), lang)
    if restore and action.get("kind") == "move":
        body += '<div class="sub mono">{0}</div>'.format(_e(restore))
    return '<td class="c-reason">{0}</td>'.format(body)


def _guard_details(action: Dict[str, Any], lang: str) -> str:
    guard = action.get("guard") or {}
    lines: List[str] = []
    hold = action.get("hold_reason")
    if isinstance(hold, dict) and hold.get("ready_at"):
        lines.append(_e(_t(lang, "ready_at", time=hold.get("ready_at"))))
    if isinstance(hold, dict) and hold.get("label"):
        lines.append('<span class="mono">{0}</span>'.format(_e(hold.get("label"))))
    open_by = guard.get("open_by") or []
    if open_by:
        procs = ", ".join(
            "{0} (pid {1})".format(_e(p.get("command")), _e(p.get("pid"))) if isinstance(p, dict) else _e(p)
            for p in open_by
        )
        lines.append('{0}: <span class="mono">{1}</span>'.format(_t(lang, "open_by"), procs))
    refs = guard.get("referenced_in") or []
    if refs:
        items = []
        for ref in refs:
            if isinstance(ref, dict):
                where = "{0}:{1}".format(ref.get("file", ""), ref.get("line", ""))
                form = ref.get("form")
                items.append(_e(where) + (" ({0})".format(_e(form)) if form else ""))
            else:
                items.append(_e(ref))
        lines.append('{0}: <span class="mono">{1}</span>'.format(_t(lang, "referenced_in"), "; ".join(items)))
    links = guard.get("incoming_symlinks") or []
    if links:
        lines.append(
            '{0}: <span class="mono">{1}</span>'.format(_t(lang, "symlinks"), _e("; ".join(str(x) for x in links)))
        )
    shape = guard.get("shape") or []
    if shape:
        lines.append("{0}: {1}".format(_t(lang, "shape"), _e(" · ".join(str(s) for s in shape))))
    return "".join('<div class="sub">{0}</div>'.format(line) for line in lines)


def _names_options(names: Dict[str, str], current: Optional[str]) -> str:
    ordered = sorted(names.items(), key=lambda kv: (str(kv[1]), kv[0]))
    parts = []
    for key, path in ordered:
        selected = " selected" if key == current else ""
        parts.append('<option value="{0}"{1}>{2}</option>'.format(_e(key), selected, _e(path)))
    return "".join(parts)


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------


def _row_move(action: Dict[str, Any], lang: str, names: Dict[str, str]) -> str:
    aid = str(action.get("id", ""))
    pick_id = "pick-" + aid
    dest = names.get(str(action.get("destination_key") or ""), "")
    if not dest:
        dest_path = action.get("destination_portable") or action.get("destination") or ""
        dest = str(Path(str(dest_path)).parent) if dest_path else str(action.get("category") or "")
    return (
        '<tr data-ids="{aid}" data-subject="{sid}">'
        '<td class="c-pick"><input type="checkbox" class="gn-pick" id="{pid}" data-action-id="{aid}"></td>'
        "{file}"
        '<td class="c-size">{size}</td>'
        '<td class="c-dest mono">{dest}</td>'
        "{reason}"
        '<td class="c-status gn-status"></td>'
        "</tr>"
    ).format(
        aid=_e(aid),
        sid=_e(action.get("subject_id", "")),
        pid=_e(pick_id),
        file=_file_cell(action, lang, label_for=pick_id),
        size=_format_bytes(action.get("size_bytes")),
        dest=_e(dest),
        reason=_reason_cell(action, lang),
    )


def _row_pending(action: Dict[str, Any], lang: str, names: Dict[str, str]) -> str:
    aid = str(action.get("id", ""))
    pick_id = "pick-" + aid
    current = str(action.get("destination_key") or "")
    return (
        '<tr data-ids="{aid}" data-subject="{sid}">'
        '<td class="c-pick"><input type="checkbox" class="gn-pick" id="{pid}" data-action-id="{aid}"></td>'
        "{file}"
        '<td class="c-size">{size}</td>'
        "{reason}"
        '<td class="c-dest"><select class="gn-dest mono" data-action-id="{aid}" data-original="{cur}">{opts}</select></td>'
        '<td class="c-status gn-status"></td>'
        "</tr>"
    ).format(
        aid=_e(aid),
        sid=_e(action.get("subject_id", "")),
        pid=_e(pick_id),
        file=_file_cell(action, lang, label_for=pick_id),
        size=_format_bytes(action.get("size_bytes")),
        reason=_reason_cell(action, lang),
        cur=_e(current),
        opts=_names_options(names, current),
    )


def _row_candidate(
    trash: Optional[Dict[str, Any]],
    delete: Optional[Dict[str, Any]],
    lang: str,
    *,
    trash_available: bool,
    delete_offered: bool,
) -> str:
    action = trash or delete or {}
    sid = str(action.get("subject_id", ""))
    ids = [str(a["id"]) for a in (trash, delete) if a and a.get("id")]
    name = "cand-" + (sid or "-".join(ids))
    pick_id = "pick-" + name
    choices: List[str] = []
    if trash is not None and trash_available and _action_approvable(trash):
        choices.append(
            '<label class="choice"><input type="radio" class="gn-choice" name="{n}" value="{v}" data-kind="trash" data-default="1" checked> {label}</label>'.format(
                n=_e(name), v=_e(trash.get("id")), label=_t(lang, "opt_trash")
            )
        )
    if delete is not None and delete_offered and _action_approvable(delete):
        choices.append(
            '<label class="choice needs-permanent"><input type="radio" class="gn-choice" name="{n}" value="{v}" data-kind="delete" data-path="{p}" data-size="{s}" disabled> {label}</label>'.format(
                n=_e(name),
                v=_e(delete.get("id")),
                p=_e(delete.get("source_portable") or delete.get("source") or delete.get("filename")),
                s=_e(_format_bytes(delete.get("size_bytes"))),
                label=_t(lang, "opt_delete"),
            )
        )
    label_for: Optional[str] = None
    pick = ""
    if choices:
        pick = '<input type="checkbox" class="gn-pick" id="{0}" data-choice="{1}">'.format(_e(pick_id), _e(name))
        label_for = pick_id
    restore_bits = []
    if trash is not None:
        restore_bits.append(_pick(trash.get("restore_method"), lang) or _t(lang, "restore_trash"))
    if delete is not None:
        restore_bits.append(_pick(delete.get("restore_method"), lang) or _t(lang, "restore_delete"))
    reason = _e(_pick(action.get("reason"), lang))
    hold = _pick(action.get("hold_reason"), lang)
    if hold:
        reason += '<div class="sub">{0}</div>'.format(_e(hold))
    return (
        '<tr data-ids="{ids}" data-subject="{sid}">'
        '<td class="c-pick">{pick}</td>'
        "{file}"
        '<td class="c-size">{size}</td>'
        '<td class="c-reason">{reason}<div class="sub">{restore}</div></td>'
        '<td class="c-action">{choices}</td>'
        '<td class="c-status gn-status"></td>'
        "</tr>"
    ).format(
        ids=_e(" ".join(ids)),
        sid=_e(sid),
        pick=pick,
        file=_file_cell(action, lang, label_for=label_for),
        size=_format_bytes(action.get("size_bytes")),
        reason=reason,
        restore=_e(" / ".join(b for b in restore_bits if b)),
        choices="".join(choices) or '<span class="sub">{0}</span>'.format(_t(lang, "keep_here")),
    )


def _row_hold(action: Dict[str, Any], lang: str) -> str:
    hold = action.get("hold_reason")
    text = _pick(hold, lang) if isinstance(hold, dict) else ""
    reason = _pick(action.get("reason"), lang)
    body = _e(text or reason)
    if text and reason and reason != text:
        body += '<div class="sub">{0}</div>'.format(_e(reason))
    body += _guard_details(action, lang)
    return (
        '<tr class="hold" data-ids="{aid}" data-subject="{sid}">'
        "{file}"
        '<td class="c-size">{size}</td>'
        '<td class="c-why">{body}</td>'
        "</tr>"
    ).format(
        aid=_e(action.get("id", "")),
        sid=_e(action.get("subject_id", "")),
        file=_file_cell(action, lang),
        size=_format_bytes(action.get("size_bytes")),
        body=body,
    )


def _group_block(
    group: Dict[str, Any],
    lang: str,
    by_subject: Dict[str, Dict[str, Any]],
    by_id: Dict[str, Dict[str, Any]],
    *,
    trash_available: bool,
    delete_offered: bool,
) -> str:
    gid = str(group.get("group_id", ""))
    labels = group.get("member_labels") or {}
    members = [str(m) for m in (group.get("members") or [])]
    member_rows = []
    for sid in members:
        action = by_subject.get(sid) or {}
        label = labels.get(sid) or action.get("filename") or sid
        source = action.get("source_portable") or action.get("source") or ""
        member_rows.append(
            '<li><span class="mono name">{0}</span> <span class="sub">{1}</span>{2}</li>'.format(
                _e(label),
                _format_bytes(action.get("size_bytes")),
                '<div class="sub mono">{0}</div>'.format(_e(source)) if source else "",
            )
        )
    all_ids: List[str] = []
    options_html = []
    default = group.get("default_choice")
    radio_name = "grp-" + gid
    for option in group.get("options") or []:
        key = str(option.get("key", ""))
        ids = [str(i) for i in (option.get("action_ids") or [])]
        for i in ids:
            if i not in all_ids:
                all_ids.append(i)
        needs_permanent = _requires_permanent(option) or any(
            by_id.get(i, {}).get("kind") == "delete" for i in ids
        )
        if needs_permanent and not delete_offered:
            continue
        if not trash_available and any(by_id.get(i, {}).get("kind") == "trash" for i in ids):
            continue
        attrs = [
            'type="radio"',
            'class="gn-option"',
            'name="{0}"'.format(_e(radio_name)),
            'value="{0}"'.format(_e(key)),
            'data-action-ids="{0}"'.format(_e(" ".join(ids))),
        ]
        if key == default:
            attrs.append("checked")
            attrs.append('data-default="1"')
        if needs_permanent:
            attrs.append('data-kind="delete"')
            attrs.append('data-path="{0}"'.format(_e(" / ".join(str(labels.get(m, m)) for m in members))))
            attrs.append('data-size="{0}"'.format(_e(_format_bytes(group.get("potential_bytes")))))
            attrs.append("disabled")
        options_html.append(
            '<label class="choice{cls}"><input {attrs}> {label}</label>'.format(
                cls=" needs-permanent" if needs_permanent else "",
                attrs=" ".join(attrs),
                label=_e(_pick(option.get("label"), lang)),
            )
        )
    adopt_id = "adopt-" + gid
    potential = group.get("potential_bytes") or 0
    return (
        '<div class="group" data-group-id="{gid}" data-ids="{ids}">'
        '<div class="group-head">'
        '<label class="adopt" for="{aid}"><input type="checkbox" class="gn-adopt" id="{aid}"> {adopt}</label>'
        '<span class="group-title">{title}</span>'
        '<span class="sub">{potential}</span>'
        '<span class="gn-status"></span>'
        "</div>"
        '<ul class="members">{members}</ul>'
        '<div class="options">{options}</div>'
        '<div class="sub">{reason}</div>'
        "</div>"
    ).format(
        gid=_e(gid),
        ids=_e(" ".join(all_ids)),
        aid=_e(adopt_id),
        adopt=_t(lang, "adopt_group"),
        title=_e(" · ".join(str(labels.get(m, m)) for m in members)),
        potential=_e(_t(lang, "potential", bytes=_format_bytes(potential))) if potential else "",
        members="".join(member_rows),
        options="".join(options_html) or '<span class="sub">{0}</span>'.format(_t(lang, "keep_here")),
        reason=_e(_pick(group.get("reason"), lang)),
    )


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------


def _table(head: List[str], rows: List[str], lang: str) -> str:
    if not rows:
        return _empty(lang)
    return '<div class="scroll"><table><thead><tr>{0}</tr></thead><tbody>{1}</tbody></table></div>'.format(
        "".join("<th>{0}</th>".format(h) for h in head), "".join(rows)
    )


def _section(key: str, lang: str, body: str, count: int, *, mode: str, selectable: bool) -> str:
    buttons = []
    if selectable and count:
        buttons.append(
            '<button type="button" class="btn secondary gn-toggle-all" data-on="{0}" data-off="{1}">{0}</button>'.format(
                _t(lang, "btn_select_all"), _t(lang, "btn_clear_all")
            )
        )
    if mode == "serve" and selectable and count:
        buttons.append(
            '<button type="button" class="btn secondary gn-section-run">{0}</button>'.format(_t(lang, "btn_section"))
        )
    return (
        '<section class="sec" data-group="{key}" id="sec-{key}">'
        '<div class="sec-head"><div><h2>{title} <span class="count">{count}</span></h2>'
        '<p class="sub">{desc}</p></div><div class="sec-tools">{buttons}</div></div>'
        "{body}"
        "</section>"
    ).format(
        key=_e(key),
        title=_t(lang, "sec_" + key),
        count=count,
        desc=_t(lang, "sec_" + key + "_desc"),
        buttons="".join(buttons),
        body=body,
    )


def _build_sections(plan: Dict[str, Any], lang: str, mode: str) -> str:
    actions: List[Dict[str, Any]] = [a for a in (plan.get("actions") or []) if isinstance(a, dict)]
    groups: List[Dict[str, Any]] = [g for g in (plan.get("groups") or []) if isinstance(g, dict)]
    names: Dict[str, str] = {str(k): str(v) for k, v in (plan.get("names") or {}).items()}
    capabilities = plan.get("capabilities") or {}
    trash_available = capabilities.get("trash_backend", "finder") != "none"
    delete_offered = bool(capabilities.get("permanent_delete_offered", True))

    by_id: Dict[str, Dict[str, Any]] = {str(a.get("id")): a for a in actions}
    by_subject: Dict[str, Dict[str, Any]] = {}
    for a in actions:
        by_subject.setdefault(str(a.get("subject_id", a.get("id"))), a)

    grouped_ids = set()
    for g in groups:
        for option in g.get("options") or []:
            for i in option.get("action_ids") or []:
                grouped_ids.add(str(i))

    moves: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    holds: List[Dict[str, Any]] = []
    protected: List[Dict[str, Any]] = []
    candidates: Dict[str, Dict[str, Optional[Dict[str, Any]]]] = {}
    candidate_order: List[str] = []
    candidate_tier: Dict[str, str] = {}

    for a in actions:
        kind = a.get("kind", "move")
        aid = str(a.get("id"))
        if kind == "hold":
            (protected if a.get("tier") == HOLD_TIER_PROTECTED else holds).append(a)
            continue
        if aid in grouped_ids:
            continue
        if kind == "move":
            (pending if a.get("reroutable") else moves).append(a)
            continue
        if kind in ("trash", "delete"):
            sid = str(a.get("subject_id", aid))
            if sid not in candidates:
                candidates[sid] = {"trash": None, "delete": None}
                candidate_order.append(sid)
                candidate_tier[sid] = "regenerable" if a.get("tier") == "regenerable" else "cold"
            candidates[sid][kind] = a
            continue
        moves.append(a)

    regen_rows: List[str] = []
    cold_rows: List[str] = []
    for sid in candidate_order:
        row = _row_candidate(
            candidates[sid]["trash"],
            candidates[sid]["delete"],
            lang,
            trash_available=trash_available,
            delete_offered=delete_offered,
        )
        (regen_rows if candidate_tier[sid] == "regenerable" else cold_rows).append(row)

    pair_blocks: List[str] = []
    dup_blocks: List[str] = []
    regen_blocks: List[str] = []
    for g in groups:
        block = _group_block(
            g, lang, by_subject, by_id, trash_available=trash_available, delete_offered=delete_offered
        )
        kind = g.get("kind")
        if kind == "pair":
            pair_blocks.append(block)
        elif kind == "regenerable":
            regen_blocks.append(block)
        else:
            dup_blocks.append(block)

    def th(*keys: str) -> List[str]:
        return [_t(lang, "th_" + k) for k in keys]

    move_head = th("pick", "file", "size", "dest", "reason", "status")
    cand_head = th("pick", "file", "size", "restore", "action", "status")
    pending_head = th("pick", "file", "size", "reason", "dest", "status")
    hold_head = th("file", "size", "why")

    regen_body = "".join(regen_blocks)
    if regen_rows or not regen_blocks:
        regen_body += _table(cand_head, regen_rows, lang)

    out = [
        _section(
            "move", lang, _table(move_head, [_row_move(a, lang, names) for a in moves], lang), len(moves),
            mode=mode, selectable=True,
        ),
        _section("pair", lang, "".join(pair_blocks) or _empty(lang), len(pair_blocks), mode=mode, selectable=True),
        _section(
            "duplicate", lang, "".join(dup_blocks) or _empty(lang), len(dup_blocks), mode=mode, selectable=True
        ),
        _section(
            "regenerable", lang, regen_body, len(regen_blocks) + len(regen_rows), mode=mode, selectable=True
        ),
        _section("cold", lang, _table(cand_head, cold_rows, lang), len(cold_rows), mode=mode, selectable=True),
        _section(
            "hold", lang, _table(hold_head, [_row_hold(a, lang) for a in holds], lang), len(holds),
            mode=mode, selectable=False,
        ),
        _section(
            "protected", lang, _table(hold_head, [_row_hold(a, lang) for a in protected], lang), len(protected),
            mode=mode, selectable=False,
        ),
        _section(
            "pending", lang, _table(pending_head, [_row_pending(a, lang, names) for a in pending], lang),
            len(pending), mode=mode, selectable=True,
        ),
    ]
    return "".join(out)


# --------------------------------------------------------------------------
# top bar, notes, footer
# --------------------------------------------------------------------------


def _display_time(value: Any) -> str:
    """``2026-09-02T10:15:00+09:00`` -> ``2026-09-02 10:15`` (full value in the title)."""

    text = str(value or "")
    short = text
    if len(text) >= 16 and text[10] == "T":
        short = text[:10] + " " + text[11:16]
    return '<span title="{0}">{1}</span>'.format(_e(text), _e(short))


def _pending_count(plan: Dict[str, Any]) -> int:
    subjects = set()
    for a in plan.get("actions") or []:
        if isinstance(a, dict) and _action_approvable(a) and a.get("kind", "move") != "hold":
            subjects.add(str(a.get("subject_id", a.get("id"))))
    return len(subjects)


def _summary_bar(plan: Dict[str, Any], lang: str, mode: str) -> str:
    disk = plan.get("disk") or {}
    summary = plan.get("summary") or {}
    used = disk.get("used_percent")
    used_text = "{0:.1f}%".format(float(used)) if isinstance(used, (int, float)) else "–"
    reclaim = summary.get("potential_reclaimable_bytes")
    cells = [
        (
            "bar_path",
            '<span class="mono">{0}</span>'.format(
                _e(plan.get("source_root_portable") or plan.get("source_root") or "")
            ),
        ),
        ("bar_time", _display_time(plan.get("created_at") or plan.get("now") or "")),
        ("bar_pending", "{0} {1}".format(_pending_count(plan), _t(lang, "items"))),
        ("bar_disk", used_text),
        ("bar_reclaim", _format_bytes(reclaim) if reclaim is not None else "–"),
        ("bar_mode", _t(lang, "mode_" + mode)),
    ]
    items = "".join(
        '<div class="cell"><span class="k">{0}</span><span class="v">{1}</span></div>'.format(_t(lang, key), value)
        for key, value in cells
    )
    serve_line = '<div class="serve-line">{0}</div>'.format(_t(lang, "serve_note")) if mode == "serve" else ""
    return '<header class="bar"><div class="wrap"><div class="cells">{0}</div>{1}</div></header>'.format(
        items, serve_line
    )


def _footer(lang: str, mode: str) -> str:
    if mode == "serve":
        buttons = (
            '<button type="button" class="btn secondary" id="gn-shutdown">{shutdown}</button>'
            '<button type="button" class="btn secondary" id="gn-dry">{dry}</button>'
            '<button type="button" class="btn primary" id="gn-main">{apply}</button>'
        ).format(shutdown=_t(lang, "btn_shutdown"), dry=_t(lang, "btn_dry"), apply=_t(lang, "btn_apply"))
        hint = ""
    else:
        buttons = '<button type="button" class="btn primary" id="gn-main">{0}</button>'.format(
            _t(lang, "btn_export")
        )
        hint = '<div class="sub">{0}</div>'.format(_t(lang, "footer_static_hint"))
    return (
        '<footer class="foot"><div class="wrap"><div class="foot-row">'
        '<div><div id="gn-count"></div><div id="gn-message" class="sub"></div>{hint}</div>'
        '<div class="foot-buttons">{buttons}</div>'
        "</div></div></footer>"
    ).format(hint=hint, buttons=buttons)


def _permanent_toggle(plan: Dict[str, Any], lang: str, mode: str) -> str:
    capabilities = plan.get("capabilities") or {}
    if not capabilities.get("permanent_delete_offered", True):
        return ""
    enabled = capabilities.get("permanent_delete_enabled", True)
    disabled = " disabled" if mode == "serve" and not enabled else ""
    if mode == "serve":
        note = "" if enabled else _t(lang, "permanent_not_enabled")
    else:
        note = _t(lang, "permanent_static_note")
    return (
        '<div class="switch"><label><input type="checkbox" id="gn-permanent"{0}> {1}</label>'
        '<span class="sub">{2}</span></div>'
    ).format(disabled, _t(lang, "toggle_permanent"), _e(note))


# --------------------------------------------------------------------------
# style and script
# --------------------------------------------------------------------------

CSS = """
:root{--gn-accent:#c8501e;--gn-accent-deep:#b4481b;--gn-ink:#111111;--gn-muted:#6b6b6b;--gn-line:#d9d9d9;--gn-paper:#ffffff;--gn-panel:#f5f5f5;--gn-radius:0;--gn-border:1px solid var(--gn-line);--gn-unit:8px;--gn-mono:ui-monospace,"SF Mono",Menlo,"Noto Sans Mono CJK SC",monospace}
*{box-sizing:border-box;border-radius:0}
html{background:var(--gn-paper)}
body{margin:0;color:var(--gn-ink);background:var(--gn-paper);font:15px/1.5 -apple-system,"PingFang SC","Helvetica Neue","Noto Sans CJK SC",Arial,sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:0 32px}
.mono{font-family:var(--gn-mono);font-size:13px}
.sub{color:var(--gn-muted);font-size:13px;line-height:1.5}
h1{font-size:24px;font-weight:600;line-height:32px;margin:0 0 8px}
h2{font-size:17px;font-weight:600;line-height:24px;margin:0}
h2 .count{color:var(--gn-muted);font-weight:400;margin-left:8px}
.bar{position:sticky;top:0;z-index:5;background:var(--gn-panel);border-bottom:1px solid var(--gn-ink)}
.cells{display:grid;grid-template-columns:repeat(12,1fr);gap:0 24px;padding:8px 0}
.cell{grid-column:span 2;padding:8px 0;min-width:0}
.cell:nth-child(1){grid-column:span 4}
.cell:nth-child(3),.cell:nth-child(4){grid-column:span 1}
.cell .k{display:block;color:var(--gn-muted);font-size:12px;line-height:16px}
.cell .v{display:block;font-size:15px;line-height:24px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cell:nth-child(1) .v{white-space:normal;overflow-wrap:anywhere}
.serve-line{border-top:var(--gn-border);padding:8px 0;font-size:13px;color:var(--gn-muted)}
.intro{padding:32px 0 0}
.lede{margin:0 0 16px;color:var(--gn-muted)}
.pledge{border:1px solid var(--gn-ink);border-left:4px solid var(--gn-accent);padding:16px;margin:0 0 16px}
.pledge p{margin:0}
.pledge p+p{margin-top:8px}
.switch{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;padding:8px 0 0}
.sec{margin:32px 0 0;padding:0 0 0 16px;border-left:4px solid transparent}
.sec.current{border-left-color:var(--gn-accent)}
.sec-head{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;padding-bottom:8px;border-bottom:1px solid var(--gn-ink)}
.sec-head p{margin:4px 0 0}
.sec-tools{display:flex;gap:8px;flex-shrink:0}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%}
th{text-align:left;color:var(--gn-muted);font-weight:400;font-size:12px;letter-spacing:.04em;height:40px;padding:8px 12px;border-bottom:var(--gn-border);white-space:nowrap}
td{padding:8px 12px;border-bottom:var(--gn-border);vertical-align:top;height:40px}
tr.hold td{background:var(--gn-panel)}
tr.done td,tr.done .name{color:var(--gn-muted)}
tr.working td{color:var(--gn-muted)}
tr.failed .gn-status{color:var(--gn-ink);font-weight:600}
.c-pick{width:40px}
.c-size{white-space:nowrap;font-variant-numeric:tabular-nums}
.c-status{white-space:nowrap;min-width:96px}
.name{overflow-wrap:anywhere;font-weight:600}
label.name{cursor:pointer}
.badge{display:inline-block;border:1px solid var(--gn-ink);padding:0 6px;font-size:12px;line-height:18px;margin-left:8px;vertical-align:1px}
.empty{padding:16px 0;margin:0}
.group{border:var(--gn-border);margin-top:16px;padding:16px}
.group-head{display:flex;flex-wrap:wrap;align-items:center;gap:8px 24px;padding-bottom:8px;border-bottom:var(--gn-border)}
.group-title{font-weight:600;overflow-wrap:anywhere;font-family:var(--gn-mono);font-size:13px}
.adopt{white-space:nowrap}
.members{list-style:none;margin:0;padding:8px 0;border-bottom:var(--gn-border)}
.members li{padding:4px 0}
.options{display:flex;flex-wrap:wrap;gap:8px 24px;padding:8px 0}
.choice{white-space:nowrap}
.group.done{color:var(--gn-muted)}
.group.failed .gn-status{font-weight:600}
input[type=checkbox],input[type=radio]{accent-color:var(--gn-accent);width:16px;height:16px;margin:0 4px 0 0;vertical-align:-3px}
select.gn-dest{height:36px;border:1px solid var(--gn-ink);background:var(--gn-paper);color:var(--gn-ink);padding:0 8px;max-width:100%}
body[data-permanent="off"] .needs-permanent{display:none}
.btn{height:36px;padding:0 16px;font:inherit;font-size:14px;cursor:pointer;border:1px solid var(--gn-ink);background:var(--gn-paper);color:var(--gn-ink)}
.btn.primary{background:var(--gn-accent);border-color:var(--gn-accent);color:#ffffff}
.btn.primary:hover{background:var(--gn-accent-deep);border-color:var(--gn-accent-deep)}
.btn:disabled,.btn.primary:disabled{background:var(--gn-paper);border-color:var(--gn-line);color:var(--gn-muted);cursor:not-allowed}
.foot{position:sticky;bottom:0;z-index:5;background:var(--gn-paper);border-top:1px solid var(--gn-ink);margin-top:32px}
.foot-row{display:flex;justify-content:space-between;align-items:center;gap:24px;padding:16px 0}
.foot-buttons{display:flex;gap:8px;flex-shrink:0}
#gn-count{font-weight:600}
.colophon{padding:32px 0 48px;color:var(--gn-muted);font-size:13px}
@media (max-width:760px){.wrap{padding:0 16px}.cells{grid-template-columns:1fr}.cell,.cell:first-child{grid-column:span 1}.sec-head,.foot-row{flex-direction:column;align-items:stretch}.foot-buttons{flex-wrap:wrap}}
@media print{.btn,.foot-buttons,.sec-tools,.switch{display:none}.bar,.foot{position:static}body{font-size:12px}}
"""

JS_COMMON = r"""
(function () {
  var GN = window.GN;
  var T = GN.text;
  var byId = {};
  (GN.plan.actions || []).forEach(function (a) { byId[a.id] = a; });
  var permanentOn = false;
  var executed = {};

  function $(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function fmt(tpl, vars) { return String(tpl).replace(/\{(\w+)\}/g, function (m, k) { return vars[k] !== undefined ? vars[k] : m; }); }
  function fmtBytes(n) {
    var size = Number(n) || 0, units = ['B', 'KB', 'MB', 'GB', 'TB'];
    for (var i = 0; i < units.length; i++) {
      if (size < 1024 || i === units.length - 1) return (i === 0 ? Math.round(size) : size.toFixed(1)) + ' ' + units[i];
      size /= 1024;
    }
    return size.toFixed(1) + ' TB';
  }
  function hasId(el, id) { return (' ' + (el.dataset.ids || '') + ' ').indexOf(' ' + id + ' ') >= 0; }
  function elementsFor(id) { return $('[data-ids]').filter(function (el) { return hasId(el, id); }); }

  function selection(root) {
    var ids = [];
    $('input.gn-pick:checked', root).forEach(function (cb) {
      if (cb.disabled) return;
      if (cb.dataset.actionId) { ids.push(cb.dataset.actionId); return; }
      var chosen = document.querySelector('input.gn-choice[name="' + cb.dataset.choice + '"]:checked');
      if (chosen && !chosen.disabled) ids.push(chosen.value);
    });
    $('input.gn-adopt:checked', root).forEach(function (cb) {
      if (cb.disabled) return;
      var block = cb.closest('[data-group-id]');
      var opt = block ? block.querySelector('input.gn-option:checked') : null;
      if (opt && !opt.disabled) opt.dataset.actionIds.split(' ').forEach(function (id) { if (id && ids.indexOf(id) < 0) ids.push(id); });
    });
    return ids.filter(function (id) { return !executed[id]; });
  }
  function overrides() {
    var out = [];
    $('select.gn-dest').forEach(function (sel) {
      if (sel.disabled) return;
      if (sel.value !== sel.dataset.original) out.push({ action_id: sel.dataset.actionId, destination_key: sel.value });
    });
    return out;
  }
  function tally(ids) {
    var t = { move: 0, trash: 0, delete: 0, bytes: 0 };
    ids.forEach(function (id) { var a = byId[id]; if (!a) return; t[a.kind] = (t[a.kind] || 0) + 1; t.bytes += Number(a.reclaims_bytes) || 0; });
    return t;
  }
  function refresh() {
    var ids = selection();
    var t = tally(ids);
    var count = document.getElementById('gn-count');
    if (count) count.textContent = fmt(T.footer_count, { moves: t.move, trash: t.trash, delete: t.delete, bytes: fmtBytes(t.bytes) });
    if (GN.busy) return;
    ['gn-main', 'gn-dry'].forEach(function (id) { var b = document.getElementById(id); if (b) b.disabled = ids.length === 0; });
  }
  function message(text) { var el = document.getElementById('gn-message'); if (el) el.textContent = text || ''; }

  function fallbackChoice(input) {
    var group = $('input[name="' + input.name + '"]');
    var def = group.filter(function (i) { return i.dataset.default === '1' && !i.disabled; })[0]
      || group.filter(function (i) { return !i.disabled && i !== input; })[0];
    input.checked = false;
    if (def) def.checked = true;
  }
  function applyPermanent() {
    document.body.dataset.permanent = permanentOn ? 'on' : 'off';
    $('.needs-permanent input').forEach(function (inp) {
      if (inp.dataset.executed === '1') return;
      inp.disabled = !permanentOn;
      if (!permanentOn && inp.checked) fallbackChoice(inp);
    });
    refresh();
  }
  function disableInputs(el) {
    $('input, select, button', el).forEach(function (inp) {
      if (inp.type === 'checkbox') inp.checked = false;
      inp.disabled = true;
      inp.dataset.executed = '1';
    });
  }
  function setStatus(id, cls, text) {
    elementsFor(id).forEach(function (el) {
      el.classList.remove('working', 'done', 'failed');
      if (cls) el.classList.add(cls);
      var cell = el.querySelector('.gn-status');
      if (cell) cell.textContent = text;
      if (cls === 'done') disableInputs(el);
    });
  }
  function markResults(results) {
    (results || []).forEach(function (r) {
      var st = r.status;
      var tail = r.detail ? ' · ' + r.detail : '';
      if (st === 'moved' || st === 'trashed' || st === 'deleted') {
        executed[r.action_id] = true;
        setStatus(r.action_id, 'done', T['status_' + st] || T.status_done);
      } else if (st === 'dry-run') {
        setStatus(r.action_id, '', T.status_dry + tail);
      } else if (st === 'skipped') {
        setStatus(r.action_id, 'failed', T.status_skipped + tail);
      } else {
        setStatus(r.action_id, 'failed', T.status_failed + tail);
      }
    });
    refresh();
  }
  function markExecuted(ids) {
    (ids || []).forEach(function (id) {
      executed[id] = true;
      var a = byId[id] || {};
      var key = a.kind === 'move' ? 'status_moved' : a.kind === 'trash' ? 'status_trashed' : a.kind === 'delete' ? 'status_deleted' : 'status_done';
      setStatus(id, 'done', T[key]);
    });
    refresh();
  }

  document.addEventListener('change', function (e) {
    var el = e.target;
    if (el.matches && el.matches('input[data-kind="delete"]') && el.checked) {
      if (!confirm(fmt(T.confirm_delete, { path: el.dataset.path || '', size: el.dataset.size || '' }))) fallbackChoice(el);
    }
    if (el.id === 'gn-permanent') { permanentOn = el.checked; applyPermanent(); return; }
    refresh();
  });
  document.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('button') : null;
    if (!btn || !btn.classList.contains('gn-toggle-all')) return;
    var sec = btn.closest('section');
    var boxes = $('input.gn-pick, input.gn-adopt', sec).filter(function (b) { return !b.disabled; });
    var turnOn = boxes.some(function (b) { return !b.checked; });
    boxes.forEach(function (b) { b.checked = turnOn; });
    btn.textContent = turnOn ? btn.dataset.off : btn.dataset.on;
    refresh();
  });

  var sections = $('section.sec');
  function spy() {
    var bar = document.querySelector('.bar');
    var limit = (bar ? bar.offsetHeight : 0) + 16;
    var current = null;
    sections.forEach(function (s) { if (s.getBoundingClientRect().top <= limit) current = s; });
    sections.forEach(function (s) { s.classList.toggle('current', s === current); });
  }
  window.addEventListener('scroll', spy, { passive: true });

  GN.api = { $: $, fmt: fmt, fmtBytes: fmtBytes, selection: selection, overrides: overrides, tally: tally, refresh: refresh, message: message, markResults: markResults, markExecuted: markExecuted, setStatus: setStatus, byId: byId };
  applyPermanent();
  markExecuted(GN.plan.executed_ids || []);
  spy();
})();
"""

JS_STATIC = r"""
(function () {
  var GN = window.GN, A = GN.api, T = GN.text;
  document.getElementById('gn-main').addEventListener('click', function () {
    var ids = A.selection();
    if (!ids.length) { alert(T.nothing_selected); return; }
    var approved = {};
    Object.keys(GN.plan).forEach(function (k) { if (k !== 'executed_ids') approved[k] = GN.plan[k]; });
    approved.approved_action_ids = ids;
    approved.overrides = A.overrides();
    approved.approved_at = new Date().toISOString();
    approved.approved_by = 'html-static';
    var blob = new Blob([JSON.stringify(approved, null, 2) + '\n'], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = 'carl-file-organizer-approved.json';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    A.message(T.exported_note);
  });
})();
"""

JS_SERVE = r"""
(function () {
  var GN = window.GN, A = GN.api, T = GN.text;
  (function () {
    var m = location.search.match(/[?&]t=([^&]+)/);
    if (m && !GN.token) GN.token = decodeURIComponent(m[1]);
    if (location.search && window.history && history.replaceState) history.replaceState(null, '', location.pathname);
  })();
  function headers() { return { 'Content-Type': 'application/json', 'X-GN-Token': GN.token || '' }; }
  function busy(on) {
    GN.busy = on;
    ['gn-main', 'gn-dry'].forEach(function (id) { var b = document.getElementById(id); if (b) b.disabled = on; });
    A.$('.gn-section-run').forEach(function (b) { b.disabled = on; });
    A.refresh();
  }
  function submit(ids, dryRun) {
    if (!ids.length) { alert(T.nothing_selected); return; }
    var t = A.tally(ids);
    var text = dryRun ? A.fmt(T.confirm_dry, { n: ids.length })
      : A.fmt(T.confirm_apply, { moves: t.move, trash: t.trash, delete: t.delete, bytes: A.fmtBytes(t.bytes) });
    if (!confirm(text)) return;
    A.message('');
    ids.forEach(function (id) { A.setStatus(id, 'working', T.status_working); });
    busy(true);
    fetch('/api/apply', { method: 'POST', headers: headers(), body: JSON.stringify({ action_ids: ids, overrides: A.overrides(), dry_run: !!dryRun }) })
      .then(function (r) { return r.text().then(function (body) { var j = {}; try { j = JSON.parse(body); } catch (e) { j = { error: body }; } return { status: r.status, body: j }; }); })
      .then(function (res) {
        if (res.status !== 200) {
          ids.forEach(function (id) { A.setStatus(id, 'failed', T.status_failed); });
          A.message(A.fmt(T.request_failed, { status: res.status, detail: res.body.error || '' }));
          return;
        }
        A.markResults(res.body.results || []);
        if (res.body.error) A.message(res.body.error);
      })
      .catch(function () {
        ids.forEach(function (id) { A.setStatus(id, 'failed', T.status_failed); });
        A.message(T.network_failed);
      })
      .then(function () { busy(false); });
  }
  document.getElementById('gn-main').addEventListener('click', function () { submit(A.selection(), false); });
  document.getElementById('gn-dry').addEventListener('click', function () { submit(A.selection(), true); });
  document.getElementById('gn-shutdown').addEventListener('click', function () {
    if (!confirm(T.confirm_shutdown)) return;
    fetch('/api/shutdown', { method: 'POST', headers: headers(), body: '{}' })
      .then(function () { A.message(T.network_failed); }, function () { A.message(T.network_failed); });
  });
  A.$('.gn-section-run').forEach(function (btn) {
    btn.addEventListener('click', function () { submit(A.selection(btn.closest('section')), false); });
  });
  fetch('/api/plan', { headers: headers() })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (plan) {
      if (!plan) return;
      if (plan.executed_ids) A.markExecuted(plan.executed_ids);
      var caps = plan.capabilities || {};
      var toggle = document.getElementById('gn-permanent');
      if (toggle && caps.permanent_delete_enabled === false) { toggle.checked = false; toggle.disabled = true; }
    })
    .catch(function () {});
})();
"""


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def render_report(
    plan: Dict[str, Any],
    *,
    mode: str = "static",
    token: str = "",
    lang: Optional[str] = None,
) -> str:
    """Render the review page for ``plan``.

    ``mode`` is ``static`` (export approved.json) or ``serve`` (POST to the
    local server).  ``token`` is only embedded in serve mode.  ``lang`` falls
    back to ``plan["lang"]`` and then to English.
    """

    if mode not in MODES:
        raise ValueError("mode must be one of {0}".format(", ".join(MODES)))
    plan = paths.strip_absolute(plan)
    lang = _lang(plan, lang)
    if mode != "serve":
        token = ""
    capabilities = dict(plan.get("capabilities") or {})
    trash_available = capabilities.get("trash_backend", "finder") != "none"

    config = {
        "mode": mode,
        "token": token,
        "capabilities": capabilities,
        "lang": lang,
        "text": TEXT[lang],
    }
    notes = [
        "<p><strong>{0}</strong></p>".format(_t(lang, "pledge")),
        "<p>{0}</p>".format(_t(lang, "pledge_more")),
        "<p>{0}</p>".format(_t(lang, "disk_note")),
    ]
    if not trash_available:
        notes.append("<p>{0}</p>".format(_t(lang, "no_trash_backend")))

    parts = [
        "<!doctype html>",
        '<html lang="{0}">'.format("zh-CN" if lang == "zh" else "en"),
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="referrer" content="no-referrer">',
        "<title>{0}</title>".format(_t(lang, "title")),
        "<style>{0}</style>".format(CSS),
        "</head>",
        '<body data-mode="{0}" data-permanent="off">'.format(mode),
        _summary_bar(plan, lang, mode),
        '<main class="wrap">',
        '<div class="intro"><h1>{0}</h1><p class="lede">{1}</p>'.format(_t(lang, "heading"), _t(lang, "lede")),
        '<div class="pledge">{0}</div>'.format("".join(notes)),
        _permanent_toggle(plan, lang, mode),
        "</div>",
        _build_sections(plan, lang, mode),
        '<p class="colophon">{0}</p>'.format(_t(lang, "print_hint")),
        "</main>",
        _footer(lang, mode),
        '<script id="gn-plan" type="application/json">{0}</script>'.format(_embed_json(plan)),
        "<script>window.GN = {0};window.GN.plan = JSON.parse(document.getElementById('gn-plan').textContent);</script>".format(
            _embed_json(config)
        ),
        "<script>{0}</script>".format(JS_COMMON),
        "<script>{0}</script>".format(JS_SERVE if mode == "serve" else JS_STATIC),
        "</body></html>",
    ]
    return "\n".join(parts)


def write_report(plan: Dict[str, Any], output: Union[str, Path], *, lang: Optional[str] = None) -> None:
    """Write the static page (the serve page never touches disk)."""

    Path(output).write_text(render_report(plan, mode="static", lang=lang), encoding="utf-8")
