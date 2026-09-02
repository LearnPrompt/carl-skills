#!/usr/bin/env python3
"""Render the three-colour report page from plan.json or analysis.json.

    python3 build_report.py <plan.json|analysis.json> [--notes notes.json]
        [-o report.html] [--mode static|serve] [--token X] [--lang zh|en]

One template (``assets/report_template.html``) serves both entrances: the
tidy-up page (``data-kind="organize"``, fed by a schema v2 plan.json) and the
whole-machine storage page (``data-kind="storage"``, fed by analysis.json).
The kind is detected from the file, the body is rendered here in Python and
dropped into the template together with the sanitised data, so the page works
from ``file://`` with no requests and the tests can assert on plain HTML.

Nothing that reaches the page carries an absolute path.  :func:`sanitize`
mirrors ``paths.strip_absolute`` from the engine without importing it: the four
fields with a ``_portable`` twin are dropped and every string that names a home
directory is rewritten to ``$HOME``.

``render(data, mode=..., token=..., lang=..., notes=None)`` is the function the
local server calls; ``main`` is the command line around it.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

__version__ = "0.3.0"

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE.parent / "assets" / "report_template.html"

LANGS = ("zh", "en")
MODES = ("static", "serve")
KINDS = ("organize", "storage", "combined")
COLORS = ("green", "yellow", "red")
PERMANENT_FLAG = "allow-permanent-delete"
HOME_TOKEN = "$HOME"

PLAN_ABSOLUTE_FIELDS = ("source_root", "managed_dir")
ACTION_ABSOLUTE_FIELDS = ("source", "destination")

#: Tiers that put an action in the red section when the planner did not colour it.
RED_TIERS = ("forbidden", "in_use", "referenced", "aging", "pinned")
#: Tiers that put an action in the yellow section when the planner did not colour it.
YELLOW_TIERS = ("duplicate", "cold", "user-data")

_HOME_PATTERNS = (
    re.compile(r"/Users/[^/\\\s\"']+"),
    re.compile(r"/home/[^/\\\s\"']+"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"']+"),
)


# --------------------------------------------------------------------------
# template and copy
# --------------------------------------------------------------------------

_TEMPLATE_CACHE: Dict[str, Any] = {}


def load_template(path: Optional[Union[str, Path]] = None) -> str:
    target = Path(path) if path else TEMPLATE_PATH
    key = str(target)
    if key not in _TEMPLATE_CACHE:
        _TEMPLATE_CACHE[key] = target.read_text(encoding="utf-8")
    return _TEMPLATE_CACHE[key]


def template_text(template: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """The ``TEXT`` table at the top of the template, so copy lives in one place.

    Values are strings, with one exception: ``badge`` holds a nested table of
    tier and kind tokens, read through :meth:`_T.badge`.
    """

    html = template if template is not None else load_template()
    match = re.search(r'<script id="report-text" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        raise ValueError("report_template.html has no report-text block")
    return json.loads(match.group(1))


def _lang_of(data: Dict[str, Any], lang: Optional[str]) -> str:
    chosen = lang or data.get("lang") or "zh"
    return chosen if chosen in LANGS else "zh"


class _T(object):
    """``t("key", n=3)`` with fallback to English and then the key itself."""

    def __init__(self, text: Dict[str, Dict[str, Any]], lang: str) -> None:
        self.text = text
        self.lang = lang

    def badge(self, token: Any) -> str:
        """The reader's word for a tier or a kind, from the template's badge table.

        Cards used to print the raw token, so a page in Chinese still said
        ``aging``, ``in use`` and ``build_artifact`` on its own badges.  A token
        the table does not know falls through unchanged, which is the only way a
        plan written by a newer planner still renders.
        """

        key = str(token or "")
        if not key:
            return ""
        for lang in (self.lang, "en"):
            table = (self.text.get(lang) or {}).get("badge")
            if isinstance(table, dict):
                label = table.get(key)
                if label:
                    return str(label)
        return key

    def __call__(self, key: str, **kw: Any) -> str:
        table = self.text.get(self.lang) or {}
        template = table.get(key)
        if template is None:
            template = (self.text.get("en") or {}).get(key)
        if template is None:
            template = key
        if kw:
            try:
                return template.format(**kw)
            except (KeyError, IndexError, ValueError):
                return template
        return template


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def format_bytes(value: Union[int, float, None]) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return "{0:.1f} {1}".format(size, unit) if unit != "B" else "{0} B".format(int(size))
        size /= 1024
    return "{0:.1f} TB".format(size)


def _pick(value: Any, lang: str) -> str:
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("en") or value.get("zh") or "")
    if value is None:
        return ""
    return str(value)


def _e(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def _embed_json(data: Any) -> str:
    text = json.dumps(data, ensure_ascii=False)
    return (
        text.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _display_time(value: Any) -> str:
    text = str(value or "")
    short = text
    if len(text) >= 16 and text[10] == "T":
        short = text[:10] + " " + text[11:16]
    return '<span title="{0}">{1}</span>'.format(_e(text), _e(short))


#: ``2026-09-04T11:56:03.412870+09:00`` -> the year, month, day, hour, minute.
_ISO_HEAD = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})")

_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_ready_at(value: Any, lang: str) -> str:
    """A settling deadline the way a person says it: ``9 月 4 日 11:56``.

    The planner stores an ISO timestamp with microseconds and an offset, which
    is the right thing to store and the wrong thing to read.  The template does
    no date arithmetic; the whole conversion happens here, and anything that is
    not an ISO stamp is handed through untouched.
    """

    text = str(value or "")
    match = _ISO_HEAD.match(text)
    if not match:
        return text
    _year, month, day, hour, minute = match.groups()
    if lang == "zh":
        return "{0} 月 {1} 日 {2}:{3}".format(int(month), int(day), hour, minute)
    return "{0} {1}, {2}:{3}".format(_MONTHS_EN[int(month) - 1], int(day), hour, minute)


def _color(value: Any, fallback: str) -> str:
    return value if value in COLORS else fallback


def _widths(parts: List[Tuple[str, float]]) -> List[Tuple[str, int]]:
    """Integer percentages, floored, so they never add up past 100."""

    total = sum(max(0.0, float(v or 0)) for _, v in parts)
    if total <= 0:
        return [(k, 0) for k, _ in parts]
    return [(k, int(max(0.0, float(v or 0)) * 100 // total)) for k, v in parts]


def _segbar(parts: List[Tuple[str, float]]) -> str:
    segs = []
    for key, width in _widths(parts):
        if width <= 0:
            continue
        segs.append('<span class="seg {0}" style="width:{1}%"></span>'.format(_e(key), width))
    return '<div class="segbar">{0}</div>'.format("".join(segs))


# --------------------------------------------------------------------------
# kind detection, sanitising, notes
# --------------------------------------------------------------------------


def detect_kind(data: Dict[str, Any]) -> str:
    if isinstance(data.get("plan"), dict) or isinstance(data.get("analysis"), dict):
        return "combined"
    schema = str(data.get("schema") or "")
    if "storage" in schema or "analysis" in schema:
        return "storage"
    if "actions" in data and data.get("schema_version") == 2:
        return "organize"
    if "items" in data or "disks" in data:
        return "storage"
    if "actions" in data:
        return "organize"
    raise ValueError("cannot tell whether this is a plan.json or an analysis.json")


def _home_of(data: Dict[str, Any], home: Optional[Union[str, Path]]) -> str:
    if home is not None:
        return str(home)
    root = str(data.get("source_root") or "")
    portable = str(data.get("source_root_portable") or "")
    if root and portable == HOME_TOKEN:
        return root
    prefix = HOME_TOKEN + "/"
    if root and portable.startswith(prefix):
        relative = Path(portable[len(prefix):]).parts
        whole = Path(root).parts
        if len(whole) > len(relative) and whole[-len(relative):] == relative:
            return str(Path(*whole[: -len(relative)]))
    return str(Path.home())


def _portable_text(text: str, base: str) -> str:
    if base and base != "/":
        if text == base:
            text = HOME_TOKEN
        else:
            text = text.replace(base + "/", HOME_TOKEN + "/").replace(base + "\\", HOME_TOKEN + "\\")
    for pattern in _HOME_PATTERNS:
        text = pattern.sub(HOME_TOKEN, text)
    return text


def _scrub(value: Any, base: str) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v, base) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(item, base) for item in value]
    if isinstance(value, str):
        return _portable_text(value, base)
    return value


def sanitize(data: Any, home: Optional[Union[str, Path]] = None) -> Any:
    """A copy carrying no absolute path: the ``paths.strip_absolute`` rule, re-stated.

    ``source_root``, ``managed_dir`` and every action's ``source`` and
    ``destination`` are dropped (their ``_portable`` twins stay); every other
    string that starts with the home directory, or looks like one on macOS,
    Linux or Windows, is rewritten to ``$HOME``.
    """

    if not isinstance(data, dict):
        return data
    base = _home_of(data, home)
    out = copy.deepcopy(data)
    for field in PLAN_ABSOLUTE_FIELDS:
        out.pop(field, None)
    for action in out.get("actions") or []:
        if isinstance(action, dict):
            for field in ACTION_ABSOLUTE_FIELDS:
                action.pop(field, None)
    for item in out.get("items") or []:
        if isinstance(item, dict):
            item.pop("path", None)
    return _scrub(out, base)


def merge_notes(data: Dict[str, Any], notes: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """``notes.json`` on top of whatever ``data["notes"]`` already carries."""

    merged: Dict[str, Any] = copy.deepcopy(data.get("notes") or {}) if isinstance(data.get("notes"), dict) else {}
    for key, value in (notes or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            inner = dict(merged[key])
            for k2, v2 in value.items():
                if isinstance(v2, dict) and isinstance(inner.get(k2), dict):
                    tmp = dict(inner[k2])
                    tmp.update(v2)
                    inner[k2] = tmp
                else:
                    inner[k2] = v2
            merged[key] = inner
        else:
            merged[key] = value
    out = dict(data)
    out["notes"] = merged
    return out


def _note_for(notes: Dict[str, Any], table: str, ids: List[str], lang: str) -> Dict[str, str]:
    bucket = notes.get(table) or {}
    for i in ids:
        entry = bucket.get(i)
        if isinstance(entry, dict):
            return {k: _pick(v, lang) for k, v in entry.items() if isinstance(v, (str, dict))}
    return {}


# --------------------------------------------------------------------------
# colours for a plan that predates them
# --------------------------------------------------------------------------


def action_color(action: Dict[str, Any]) -> str:
    given = action.get("color")
    if given in COLORS:
        return given
    kind = action.get("kind", "move")
    tier = action.get("tier", "routine")
    if kind == "hold" or tier in RED_TIERS:
        return "red"
    if action.get("reroutable") or tier in YELLOW_TIERS:
        return "yellow"
    return "green"


def group_color(group: Dict[str, Any]) -> str:
    given = group.get("color")
    if given in COLORS:
        return given
    return "green" if group.get("kind") == "regenerable" else "yellow"


def _mess_fallback(plan: Dict[str, Any], t: _T) -> Dict[str, Any]:
    actions = [a for a in (plan.get("actions") or []) if isinstance(a, dict)]
    groups = plan.get("groups") or []
    summary = plan.get("summary") or {}
    entries = int(summary.get("entries") or len({a.get("subject_id") for a in actions}))
    pending = len([a for a in actions if a.get("kind") == "move" and a.get("reroutable")])
    holds = len([a for a in actions if a.get("kind") == "hold"])
    aging = len([a for a in actions if a.get("kind") == "hold" and a.get("tier") == "aging"])
    top_dirs = len({a.get("subject_id") for a in actions if a.get("subject_kind") == "dir" and a.get("kind") != "hold"})
    score = int(min(100, round(entries * 1.5 + pending * 5 + len(groups) * 6 + holds * 2)))
    color = "green" if score < 35 else "yellow" if score < 70 else "red"
    return {
        "score": score,
        "color": color,
        "counts": {"scattered": entries, "pending": pending, "duplicate": len(groups), "aging": aging, "top_dirs": top_dirs},
        "reason": t("mess_fallback", entries=entries, pending=pending, groups=len(groups), holds=holds),
        "source": "fallback",
    }


def _by_color_fallback(plan: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    out = {c: {"count": 0, "bytes": 0} for c in COLORS}
    seen = set()
    for a in plan.get("actions") or []:
        if not isinstance(a, dict):
            continue
        sid = str(a.get("subject_id") or a.get("id"))
        if sid in seen:
            continue
        seen.add(sid)
        c = action_color(a)
        out[c]["count"] += 1
        out[c]["bytes"] += int(a.get("size_bytes") or 0)
    return out


def _normalise_by_color(raw: Any, fallback: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    if not isinstance(raw, dict):
        return fallback
    out = {}
    for c in COLORS:
        v = raw.get(c)
        if isinstance(v, dict):
            count = v.get("count")
            if count is None:
                count = v.get("actions", v.get("items", 0))
            out[c] = {"count": int(count or 0), "bytes": int(v.get("bytes") or 0)}
        elif isinstance(v, (int, float)):
            out[c] = {"count": int(v), "bytes": fallback.get(c, {}).get("bytes", 0)}
        else:
            out[c] = {"count": 0, "bytes": 0}
    return out


# --------------------------------------------------------------------------
# shared fragments
# --------------------------------------------------------------------------


def _copy_block(command: str, t: _T) -> str:
    return (
        '<div class="cmd"><code>{0}</code>'
        '<button type="button" class="btn small copy" data-action="copy">{1}</button></div>'
    ).format(_e(command), t("copy"))


def _reveal_button(path: str, mode: str, t: _T) -> str:
    if mode != "serve" or not path:
        return ""
    return '<button type="button" class="btn small" data-action="reveal" data-path="{0}">{1}</button>'.format(
        _e(path), t("reveal")
    )


def _dl(rows: List[Tuple[str, str]]) -> str:
    body = "".join("<dt>{0}</dt><dd>{1}</dd>".format(_e(k), v) for k, v in rows if v)
    return "<dl>{0}</dl>".format(body) if body else ""


def _card(
    *,
    ids: List[str],
    subject: str,
    color: str,
    name: str,
    badges: List[str],
    size: Any,
    head_extra: str = "",
    pick: str = "",
    body: str,
    open_by_default: bool = False,
    extra_attrs: str = "",
) -> str:
    return (
        '<article class="item{open}" data-color="{color}" data-ids="{ids}" data-subject="{sid}"{extra}>'
        '<div class="item-head">'
        '<span class="pick">{pick}</span>'
        '<span class="title"><span class="name">{name}</span>{badges}{head_extra}</span>'
        '<span class="size">{size}</span>'
        '<span class="gn-status"></span>'
        '<span class="chev" aria-hidden="true"></span>'
        "</div>"
        '<div class="item-body">{body}</div>'
        "</article>"
    ).format(
        open=" open" if open_by_default else "",
        color=_e(color),
        ids=_e(" ".join(i for i in ids if i)),
        sid=_e(subject),
        extra=extra_attrs,
        pick=pick,
        name=_e(name),
        badges="".join(badges),
        head_extra=head_extra,
        size=format_bytes(size),
        body=body,
    )


def _section(
    key: str,
    color: str,
    title: str,
    desc: str,
    cards: List[str],
    *,
    mode: str,
    t: _T,
    selectable: bool,
    tools_extra: str = "",
    subgroups: Optional[List[Tuple[str, List[str]]]] = None,
) -> str:
    """One coloured band.  ``subgroups`` splits it into labelled runs of cards.

    The combined page needs each band to say cleanup first and moves second
    without growing a second section markup; everything else -- the head, the
    tools, the empty line -- is the same either way, so the two shapes share
    this function and differ only in how the body is assembled.
    """

    if subgroups is not None:
        cards = [card for _, group in subgroups for card in group]
    tools = []
    if cards:
        tools.append(
            '<button type="button" class="btn small gn-fold-all" data-on="{0}" data-off="{1}">{0}</button>'.format(
                t("expand_all"), t("collapse_all")
            )
        )
    if selectable and cards:
        tools.append(
            '<button type="button" class="btn small gn-toggle-all" data-on="{0}" data-off="{1}">{0}</button>'.format(
                t("btn_select_all"), t("btn_clear_all")
            )
        )
        if mode == "serve":
            tools.append('<button type="button" class="btn small gn-section-run">{0}</button>'.format(t("btn_section")))
    tools.append(tools_extra)
    if subgroups is not None:
        parts = []
        for label, group in subgroups:
            if not group:
                continue
            parts.append('<h3 class="subhead">{0}<span class="n">{1}</span></h3>'.format(_e(label), len(group)))
            parts.extend(group)
        body = "".join(parts) or '<p class="empty sub">{0}</p>'.format(t("empty"))
    else:
        body = "".join(cards) or '<p class="empty sub">{0}</p>'.format(t("empty"))
    return (
        '<section class="sec" data-color="{color}" data-group="{key}" id="sec-{key}">'
        '<div class="sec-head"><div><h2><span class="dot {color}"></span>{title}'
        '<span class="count">{count}</span></h2><p class="sub">{desc}</p></div>'
        '<div class="sec-tools">{tools}</div></div>'
        "{body}</section>"
    ).format(color=_e(color), key=_e(key), title=_e(title), count=len(cards), desc=_e(desc), tools="".join(tools), body=body)


# --------------------------------------------------------------------------
# organize page
# --------------------------------------------------------------------------


def _guard_lines(action: Dict[str, Any], lang: str, t: _T) -> List[str]:
    guard = action.get("guard") or {}
    lines: List[str] = []
    hold = action.get("hold_reason")
    if isinstance(hold, dict) and hold.get("ready_at"):
        lines.append(_e(t("ready_at", time=format_ready_at(hold.get("ready_at"), lang))))
    if isinstance(hold, dict) and hold.get("label"):
        lines.append('<span class="mono">{0}</span>'.format(_e(hold.get("label"))))
    open_by = guard.get("open_by") or []
    if open_by:
        procs = ", ".join(
            "{0} (pid {1})".format(_e(p.get("command")), _e(p.get("pid"))) if isinstance(p, dict) else _e(p) for p in open_by
        )
        lines.append("{0}: <span class=\"mono\">{1}</span>".format(t("open_by"), procs))
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
        lines.append("{0}: <span class=\"mono\">{1}</span>".format(t("referenced_in"), "; ".join(items)))
    links = guard.get("incoming_symlinks") or []
    if links:
        lines.append("{0}: <span class=\"mono\">{1}</span>".format(t("symlinks"), _e("; ".join(str(x) for x in links))))
    shape = guard.get("shape") or []
    if shape:
        lines.append("{0}: {1}".format(t("shape"), _e(" · ".join(str(s) for s in shape))))
    return lines


def _action_badges(action: Dict[str, Any], t: _T) -> List[str]:
    badges = []
    if action.get("subject_kind") == "dir":
        badges.append('<span class="badge">{0}</span>'.format(_e(t.badge("dir"))))
    if action.get("tier") == "sensitive":
        badges.append('<span class="badge yellow">{0}</span>'.format(_e(t.badge("sensitive"))))
    return badges


def _action_extras(action: Dict[str, Any], t: _T) -> str:
    bits = []
    stats = action.get("dir_stats")
    if isinstance(stats, dict):
        key = "dir_files_trunc" if stats.get("truncated") else "dir_files"
        bits.append('<div class="sub">{0}</div>'.format(_e(t(key, n=stats.get("files", 0)))))
    tags = [x for x in (action.get("tags") or []) if x]
    if tags:
        bits.append('<div class="sub">{0}: {1}</div>'.format(t("tags"), _e(" · ".join(str(x) for x in tags))))
    hints = [str(h) for h in (action.get("hints") or []) if h]
    if hints:
        bits.append('<div class="sub">{0}: {1}</div>'.format(t("hint"), _e(" · ".join(hints))))
    return "".join(bits)


def _explain(action: Dict[str, Any], note: Dict[str, str], lang: str, t: _T, *, what_default: str = "") -> str:
    """what / why / if_removed: the note when the Agent wrote one, the rule text otherwise."""

    what = note.get("what") or what_default or _pick(action.get("reason"), lang)
    why = note.get("why") or _pick(action.get("detail"), lang)
    hold = _pick(action.get("hold_reason"), lang)
    if not why and hold and hold != what:
        why = hold
    restore = _pick(action.get("restore_method"), lang)
    if_removed = note.get("if_removed") or ""
    if not if_removed and action.get("kind") == "trash":
        if_removed = t("restore_trash")
    if not if_removed and action.get("kind") == "delete":
        if_removed = t("restore_delete")
    rows = [(t("what"), _e(what)), (t("why"), _e(why)), (t("if_removed"), _e(if_removed))]
    if restore and action.get("kind") != "move":
        rows.append((t("restore"), _e(restore)))
    return _dl(rows)


def _path_line(path: str, t: _T) -> str:
    return '<div class="path mono">{0}</div>'.format(_e(path)) if path else ""


def _card_move(action: Dict[str, Any], color: str, names: Dict[str, str], notes: Dict[str, Any], lang: str, mode: str, t: _T) -> str:
    aid = str(action.get("id", ""))
    note = _note_for(notes, "actions", [aid], lang)
    dest = names.get(str(action.get("destination_key") or ""), "")
    if not dest:
        dest_path = action.get("destination_portable") or ""
        dest = str(Path(str(dest_path)).parent) if dest_path else ""
    path = str(action.get("source_portable") or "")
    pending = bool(action.get("reroutable"))
    controls_allowed = color != "red"
    pick = ""
    if controls_allowed:
        pick = '<input type="checkbox" class="gn-pick" data-action="move" data-action-id="{0}" aria-label="{1}">'.format(
            _e(aid), _e(action.get("filename"))
        )
    badges = _action_badges(action, t)
    if pending:
        badges.append('<span class="badge yellow">{0}</span>'.format(t("pending_label")))
    if dest:
        badges.append('<span class="badge dest">→ {0}</span>'.format(_e(dest)))
    body = [_path_line(path, t), _action_extras(action, t), _explain(action, note, lang, t)]
    restore = _pick(action.get("restore_method"), lang)
    if restore:
        body.append('<div class="sub">{0}</div>'.format(t("restore")))
        body.append(_copy_block(restore, t))
    controls = []
    if pending and controls_allowed:
        current = str(action.get("destination_key") or "")
        options = []
        for key, value in sorted(names.items(), key=lambda kv: (str(kv[1]), kv[0])):
            options.append('<option value="{0}"{1}>{2}</option>'.format(_e(key), " selected" if key == current else "", _e(value)))
        controls.append(
            '<label class="choice">{0} <select class="gn-dest" data-action-id="{1}" data-original="{2}">{3}</select></label>'.format(
                t("change_dest"), _e(aid), _e(current), "".join(options)
            )
        )
    controls.append(_reveal_button(path, mode, t))
    if any(controls):
        body.append('<div class="controls">{0}</div>'.format("".join(controls)))
    return _card(
        ids=[aid], subject=str(action.get("subject_id", "")), color=color, name=str(action.get("filename") or ""),
        badges=badges, size=action.get("size_bytes"), pick=pick, body="".join(body),
    )


def _card_candidate(
    trash: Optional[Dict[str, Any]], delete: Optional[Dict[str, Any]], color: str, notes: Dict[str, Any], lang: str, mode: str, t: _T,
    *, trash_available: bool, delete_offered: bool,
) -> str:
    action = trash or delete or {}
    sid = str(action.get("subject_id", ""))
    ids = [str(a["id"]) for a in (trash, delete) if a and a.get("id")]
    note = _note_for(notes, "actions", ids, lang)
    name = "cand-" + (sid or "-".join(ids))
    path = str(action.get("source_portable") or "")
    choices: List[str] = []
    if color != "red":
        if trash is not None and trash_available and trash.get("approvable", True):
            choices.append(
                '<label class="choice"><input type="radio" class="gn-choice" name="{n}" value="{v}" data-action="trash" data-kind="trash" data-default="1" checked> {label}</label>'.format(
                    n=_e(name), v=_e(trash.get("id")), label=t("opt_trash")
                )
            )
        if color == "green" and delete is not None and delete_offered and delete.get("approvable", True):
            choices.append(
                '<label class="choice needs-permanent"><input type="radio" class="gn-choice" name="{n}" value="{v}" data-action="delete" data-kind="delete" data-path="{p}" data-size="{s}" disabled> {label}</label>'.format(
                    n=_e(name), v=_e(delete.get("id")), p=_e(path or delete.get("filename")),
                    s=_e(format_bytes(delete.get("size_bytes"))), label=t("opt_delete"),
                )
            )
    pick = ""
    if choices:
        pick = '<input type="checkbox" class="gn-pick" data-choice="{0}" aria-label="{1}">'.format(_e(name), _e(action.get("filename")))
    badges = _action_badges(action, t)
    badges.append('<span class="badge {0}">{1}</span>'.format(color, t("opt_trash") if trash is not None else t("opt_delete")))
    body = [_path_line(path, t), _action_extras(action, t), _explain(action, note, lang, t)]
    controls = choices + [_reveal_button(path, mode, t)]
    if any(controls):
        body.append('<div class="controls">{0}</div>'.format("".join(controls)))
    elif color != "red":
        body.append('<div class="controls"><span class="sub">{0}</span></div>'.format(t("keep_here")))
    return _card(
        ids=ids, subject=sid, color=color, name=str(action.get("filename") or ""), badges=badges,
        size=action.get("size_bytes"), pick=pick, body="".join(body),
    )


def _card_hold(action: Dict[str, Any], color: str, notes: Dict[str, Any], lang: str, mode: str, t: _T) -> str:
    aid = str(action.get("id", ""))
    note = _note_for(notes, "actions", [aid], lang)
    path = str(action.get("source_portable") or "")
    hold = _pick(action.get("hold_reason"), lang)
    reason = _pick(action.get("reason"), lang)
    what = note.get("what") or hold or reason
    why = note.get("why") or (reason if reason != what else "")
    rows = [(t("what"), _e(what)), (t("why"), _e(why)), (t("if_removed"), _e(note.get("if_removed") or ""))]
    body = [_path_line(path, t), _action_extras(action, t), _dl(rows)]
    guard = _guard_lines(action, lang, t)
    if guard:
        body.append("".join('<div class="sub">{0}</div>'.format(line) for line in guard))
    reveal = _reveal_button(path, mode, t)
    if reveal:
        body.append('<div class="controls">{0}</div>'.format(reveal))
    badges = _action_badges(action, t)
    tier = str(action.get("tier") or "")
    if tier:
        badges.append('<span class="badge red">{0}</span>'.format(_e(t.badge(tier))))
    head_extra = '<span class="sub">{0}</span>'.format(_e(what)) if what else ""
    return _card(
        ids=[aid], subject=str(action.get("subject_id", "")), color=color, name=str(action.get("filename") or ""),
        badges=badges, size=action.get("size_bytes"), head_extra=head_extra, body="".join(body),
    )


def _card_group(
    group: Dict[str, Any], color: str, by_subject: Dict[str, Dict[str, Any]], by_id: Dict[str, Dict[str, Any]],
    notes: Dict[str, Any], lang: str, mode: str, t: _T, *, trash_available: bool, delete_offered: bool,
) -> str:
    gid = str(group.get("group_id", ""))
    note = _note_for(notes, "groups", [gid], lang)
    labels = group.get("member_labels") or {}
    members = [str(m) for m in (group.get("members") or [])]
    member_rows = []
    total = 0
    for sid in members:
        action = by_subject.get(sid) or {}
        label = labels.get(sid) or action.get("filename") or sid
        source = action.get("source_portable") or ""
        total += int(action.get("size_bytes") or 0)
        member_rows.append(
            '<li><span class="name">{0}</span><span class="sub">{1}</span>{2}{3}</li>'.format(
                _e(label), format_bytes(action.get("size_bytes")),
                '<span class="mono">{0}</span>'.format(_e(source)) if source else "",
                _reveal_button(str(source), mode, t),
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
        needs_permanent = PERMANENT_FLAG in (option.get("requires") or []) or any(
            by_id.get(i, {}).get("kind") == "delete" for i in ids
        )
        if color == "red":
            continue
        if needs_permanent and (not delete_offered or color != "green"):
            continue
        if not trash_available and any(by_id.get(i, {}).get("kind") == "trash" for i in ids):
            continue
        attrs = [
            'type="radio"', 'class="gn-option"', 'name="{0}"'.format(_e(radio_name)), 'value="{0}"'.format(_e(key)),
            'data-action-ids="{0}"'.format(_e(" ".join(ids))),
        ]
        if key == default:
            attrs.append("checked")
            attrs.append('data-default="1"')
        if needs_permanent:
            attrs.append('data-action="delete"')
            attrs.append('data-kind="delete"')
            attrs.append('data-path="{0}"'.format(_e(" / ".join(str(labels.get(m, m)) for m in members))))
            attrs.append('data-size="{0}"'.format(_e(format_bytes(group.get("potential_bytes")))))
            attrs.append("disabled")
        else:
            attrs.append('data-action="{0}"'.format("trash" if any(by_id.get(i, {}).get("kind") == "trash" for i in ids) else "move"))
        options_html.append(
            '<label class="choice{cls}"><input {attrs}> {label}</label>'.format(
                cls=" needs-permanent" if needs_permanent else "", attrs=" ".join(attrs), label=_e(_pick(option.get("label"), lang))
            )
        )
    pick = ""
    if options_html:
        pick = '<input type="checkbox" class="gn-adopt" aria-label="{0}">'.format(t("adopt_group"))
    potential = group.get("potential_bytes") or 0
    badges = ['<span class="badge">{0}</span>'.format(_e(t.badge(group.get("kind") or "group")))]
    if potential:
        badges.append('<span class="badge {0}">{1}</span>'.format(color, _e(t("potential", bytes=format_bytes(potential)))))
    reason = _pick(group.get("reason"), lang)
    rows = [
        (t("what"), _e(note.get("what") or reason)),
        (t("why"), _e(note.get("why") or (_e(group.get("evidence") or "") if note.get("what") else ""))),
        (t("if_removed"), _e(note.get("if_removed") or "")),
    ]
    body = ['<ul class="members">{0}</ul>'.format("".join(member_rows)), _dl(rows)]
    if options_html:
        body.append('<div class="controls">{0}</div>'.format("".join(options_html)))
    else:
        body.append('<div class="controls"><span class="sub">{0}</span></div>'.format(t("keep_here")))
    title = " · ".join(str(labels.get(m, m)) for m in members)
    return _card(
        ids=all_ids, subject=gid, color=color, name=title, badges=badges, size=total, pick=pick, body="".join(body),
        extra_attrs=' data-group-id="{0}"'.format(_e(gid)),
    )


def _permanent_switch(data: Dict[str, Any], mode: str, t: _T) -> str:
    """The green section's permanent-delete toggle, or nothing when it is off."""

    capabilities = data.get("capabilities") or {}
    if not bool(capabilities.get("permanent_delete_offered", True)):
        return ""
    enabled = capabilities.get("permanent_delete_enabled", True)
    disabled = " disabled" if mode == "serve" and not enabled else ""
    note = t("permanent_not_enabled") if (mode == "serve" and not enabled) else t("permanent_static_note")
    return '<label class="switch" title="{2}"><input type="checkbox" id="gn-permanent"{0}> {1}</label>'.format(
        disabled, t("toggle_permanent"), _e(note)
    )


def _organize_buckets(plan: Dict[str, Any], lang: str, mode: str, t: _T) -> Dict[str, List[str]]:
    """Every tidy-up card, already sorted, keyed by colour."""

    actions: List[Dict[str, Any]] = [a for a in (plan.get("actions") or []) if isinstance(a, dict)]
    groups: List[Dict[str, Any]] = [g for g in (plan.get("groups") or []) if isinstance(g, dict)]
    names: Dict[str, str] = {str(k): str(v) for k, v in (plan.get("names") or {}).items()}
    notes: Dict[str, Any] = plan.get("notes") or {}
    capabilities = plan.get("capabilities") or {}
    trash_available = capabilities.get("trash_backend", "finder") != "none"
    delete_offered = bool(capabilities.get("permanent_delete_offered", True))

    by_id = {str(a.get("id")): a for a in actions}
    by_subject: Dict[str, Dict[str, Any]] = {}
    for a in actions:
        by_subject.setdefault(str(a.get("subject_id", a.get("id"))), a)
    grouped_ids = set()
    for g in groups:
        for option in g.get("options") or []:
            for i in option.get("action_ids") or []:
                grouped_ids.add(str(i))

    buckets: Dict[str, List[Tuple[int, str]]] = {c: [] for c in COLORS}
    candidates: Dict[str, Dict[str, Optional[Dict[str, Any]]]] = {}
    order: List[str] = []

    for a in actions:
        kind = a.get("kind", "move")
        aid = str(a.get("id"))
        color = action_color(a)
        if kind == "hold":
            buckets[color].append((4, _card_hold(a, color, notes, lang, mode, t)))
            continue
        if aid in grouped_ids:
            continue
        if kind == "move":
            rank = 1 if a.get("reroutable") else 0
            buckets[color].append((rank, _card_move(a, color, names, notes, lang, mode, t)))
            continue
        if kind in ("trash", "delete"):
            sid = str(a.get("subject_id", aid))
            if sid not in candidates:
                candidates[sid] = {"trash": None, "delete": None}
                order.append(sid)
            candidates[sid][kind] = a
            continue
        buckets[color].append((0, _card_move(a, color, names, notes, lang, mode, t)))

    for g in groups:
        color = group_color(g)
        buckets[color].append(
            (2, _card_group(g, color, by_subject, by_id, notes, lang, mode, t, trash_available=trash_available, delete_offered=delete_offered))
        )
    for sid in order:
        trash, delete = candidates[sid]["trash"], candidates[sid]["delete"]
        color = action_color(trash or delete or {})
        buckets[color].append(
            (3, _card_candidate(trash, delete, color, notes, lang, mode, t, trash_available=trash_available, delete_offered=delete_offered))
        )

    return {c: [h for _, h in sorted(buckets[c], key=lambda x: x[0])] for c in COLORS}


def _organize_sections(plan: Dict[str, Any], lang: str, mode: str, t: _T) -> Tuple[str, Dict[str, int]]:
    buckets = _organize_buckets(plan, lang, mode, t)
    permanent = _permanent_switch(plan, mode, t)
    counts = {c: len(buckets[c]) for c in COLORS}
    html = "".join(
        [
            _section("green", "green", t("sec_green"), t("sec_green_desc"), buckets["green"], mode=mode, t=t, selectable=True, tools_extra=permanent),
            _section("yellow", "yellow", t("sec_yellow"), t("sec_yellow_desc"), buckets["yellow"], mode=mode, t=t, selectable=True),
            _section("red", "red", t("sec_red"), t("sec_red_desc"), buckets["red"], mode=mode, t=t, selectable=False),
        ]
    )
    return html, counts


def _mess_inner(plan: Dict[str, Any], lang: str, t: _T) -> str:
    """The mess score, the pill, the counts, the three-colour bar and one line.

    Both the tidy-up page and the combined page open with this block, so it
    lives on its own rather than inside either overview.
    """

    notes = plan.get("notes") or {}
    mess = plan.get("mess") if isinstance(plan.get("mess"), dict) else _mess_fallback(plan, t)
    mess_color = _color(mess.get("color"), "yellow")
    score = mess.get("score")
    by_color = _normalise_by_color((plan.get("summary") or {}).get("by_color"), _by_color_fallback(plan))
    line = _pick((notes.get("mess") or {}).get("line"), lang) if isinstance(notes.get("mess"), dict) else ""
    if isinstance(notes.get("mess"), dict) and notes["mess"].get("color") in COLORS:
        mess_color = notes["mess"]["color"]
    if not line:
        line = _pick(mess.get("reason"), lang)
    chips = []
    for key, value in (mess.get("counts") or {}).items():
        label = t("count_" + str(key))
        chips.append("<span>{0} <b>{1}</b></span>".format(_e(label if label != "count_" + str(key) else key), _e(value)))
    legend = "".join(
        '<span><span class="dot {0}"></span>{1} <b>{2}</b> · {3}</span>'.format(
            c, t("legend_" + c), by_color[c]["count"], format_bytes(by_color[c]["bytes"])
        )
        for c in COLORS
    )
    big = '<span class="big">{0}<small>/100</small></span>'.format(_e(score)) if isinstance(score, (int, float)) else ""
    return (
        '<h3>{title}</h3>'
        '<div class="mess">{big}<span class="pill {color}">{label}</span></div>'
        '<div class="chips">{chips}</div>'
        "{bar}"
        '<div class="legend">{legend}</div>'
        '<p class="line">{line}</p>'
    ).format(
        title=t("mess_title"), big=big, color=mess_color, label=t("mess_" + mess_color), chips="".join(chips),
        bar=_segbar([(c, by_color[c]["count"]) for c in COLORS]), legend=legend, line=_e(line),
    )


def _advice_items(counts: Dict[str, int], t: _T) -> List[str]:
    """One line per colour that actually has cards, in colour order."""

    items = []
    for color in COLORS:
        if counts.get(color):
            items.append("<li>{0}</li>".format(_e(t("advice_" + color, n=counts[color]))))
    return items


def _pick_green_button(counts: Dict[str, int], t: _T) -> str:
    if not counts.get("green"):
        return ""
    return '<div class="tools"><button type="button" class="btn" id="gn-pick-green">{0}</button></div>'.format(
        t("btn_pick_green")
    )


def _organize_overview(plan: Dict[str, Any], lang: str, mode: str, t: _T, counts: Dict[str, int]) -> str:
    notes = plan.get("notes") or {}
    overview = '<div class="card overview">{0}</div>'.format(_mess_inner(plan, lang, t))
    folder_line = _pick(notes.get("folder_line"), lang)
    advice_items = _advice_items(counts, t)
    if not advice_items:
        advice_items.append("<li>{0}</li>".format(_e(t("advice_none"))))
    tools = _pick_green_button(counts, t)
    advice = (
        '<div class="card advice"><h3>{title}</h3>{folder}<ol>{items}</ol>{tools}</div>'
    ).format(
        title=t("advice_title"), folder='<p class="line">{0}</p>'.format(_e(folder_line)) if folder_line else "",
        items="".join(advice_items), tools=tools,
    )
    return '<div class="grid2">{0}{1}</div>'.format(overview, advice)


def _organize_longterm(plan: Dict[str, Any], lang: str, t: _T) -> str:
    aging = []
    for a in plan.get("actions") or []:
        if not isinstance(a, dict) or a.get("kind") != "hold":
            continue
        hold = a.get("hold_reason") if isinstance(a.get("hold_reason"), dict) else {}
        if hold.get("ready_at"):
            aging.append(
                "<li>{0}</li>".format(
                    _e(
                        t(
                            "aging_line",
                            name=a.get("filename"),
                            time=format_ready_at(hold.get("ready_at"), lang),
                        )
                    )
                )
            )
    aging_html = ""
    if aging:
        aging_html = "<h3>{0}</h3><ul>{1}</ul>".format(t("aging_title"), "".join(aging))
    capabilities = plan.get("capabilities") or {}
    notes = [t("undo_hint"), t("pledge"), t("pledge_more"), t("disk_note")]
    if capabilities.get("trash_backend", "finder") == "none":
        notes.append(t("no_trash_backend"))
    return '<div class="card longterm notes">{0}<h3>{1}</h3>{2}</div>'.format(
        aging_html, t("longterm_title"), "".join("<p>{0}</p>".format(_e(n)) for n in notes)
    )


def _organize_bar(plan: Dict[str, Any], lang: str, mode: str, t: _T) -> str:
    cells = [
        (t("bar_dir"), '<span class="v mono">{0}</span>'.format(_e(plan.get("source_root_portable") or ""))),
        (t("bar_time"), '<span class="v">{0}</span>'.format(_display_time(plan.get("created_at") or plan.get("now") or ""))),
        (t("bar_mode"), '<span class="v">{0}</span>'.format(t("mode_" + mode))),
    ]
    return _bar(t("title_organize"), cells, mode, t)


def _bar(brand: str, cells: List[Tuple[str, str]], mode: str, t: _T) -> str:
    items = "".join('<span class="cell"><span class="k">{0}</span>{1}</span>'.format(_e(k), v) for k, v in cells)
    serve = '<div class="serve-line">{0}</div>'.format(t("serve_note")) if mode == "serve" else ""
    return '<header class="bar"><div class="wrap"><div class="row"><span class="brand">{0}</span>{1}</div>{2}</div></header>'.format(
        _e(brand), items, serve
    )


def _footer(kind: str, mode: str, t: _T) -> str:
    if mode == "serve":
        buttons = ['<button type="button" class="btn" id="gn-shutdown">{0}</button>'.format(t("btn_shutdown"))]
        if kind in ("organize", "combined"):
            buttons.append('<button type="button" class="btn" id="gn-dry">{0}</button>'.format(t("btn_dry")))
        label = t("btn_apply_all") if kind == "combined" else t("btn_apply")
        buttons.append('<button type="button" class="btn primary" id="gn-main">{0}</button>'.format(label))
        hint = ""
    else:
        label = t("btn_export") if kind == "organize" else t("btn_export_decisions")
        buttons = ['<button type="button" class="btn primary" id="gn-main">{0}</button>'.format(label)]
        hint = '<div class="sub">{0}</div>'.format(t("footer_static_hint"))
    return (
        '<footer class="foot"><div class="wrap"><div class="foot-row">'
        '<div><div id="gn-count"></div><div id="gn-message" class="sub"></div>{hint}</div>'
        '<div class="foot-buttons">{buttons}</div>'
        "</div></div></footer>"
    ).format(hint=hint, buttons="".join(buttons))


def render_organize_body(plan: Dict[str, Any], lang: str, mode: str, t: _T) -> str:
    sections, counts = _organize_sections(plan, lang, mode, t)
    return "".join(
        [
            _organize_bar(plan, lang, mode, t),
            '<main class="wrap">',
            '<div class="intro"><h1>{0}</h1><p class="lede">{1}</p></div>'.format(t("heading_organize"), t("lede_organize")),
            _organize_overview(plan, lang, mode, t, counts),
            sections,
            _organize_longterm(plan, lang, t),
            '<p class="colophon">{0}</p>'.format(t("print_hint")),
            "</main>",
            _footer("organize", mode, t),
        ]
    )


# --------------------------------------------------------------------------
# storage page
# --------------------------------------------------------------------------


def item_color(item: Dict[str, Any]) -> str:
    given = item.get("color")
    if given in COLORS:
        return given
    tier = str(item.get("tier") or "")
    if tier in RED_TIERS or item.get("open_by"):
        return "red"
    if tier in YELLOW_TIERS or not item.get("trash_paths"):
        return "yellow"
    return "green"


def _kind_label(kind: Any, t: _T) -> str:
    """The badge table first, the older ``kind_*`` keys second, the token last."""

    token = str(kind or "other")
    badge = t.badge(token)
    if badge != token:
        return badge
    key = "kind_" + token
    label = t(key)
    return token if label == key else label


def _card_item(item: Dict[str, Any], color: str, notes: Dict[str, Any], lang: str, mode: str, t: _T, *, delete_offered: bool) -> str:
    iid = str(item.get("id", ""))
    note = _note_for(notes, "items", [iid], lang)
    path = str(item.get("path_portable") or "")
    trash_paths = [str(p) for p in (item.get("trash_paths") or []) if p]
    action = str(item.get("action") or ("trash" if trash_paths else "keep"))
    name = "item-" + iid
    choices: List[str] = []
    if color != "red" and trash_paths and action in ("trash", "delete"):
        choices.append(
            '<label class="choice"><input type="radio" class="gn-choice" name="{n}" value="{v}" data-action="trash" data-kind="trash" data-default="1" checked> {label}</label>'.format(
                n=_e(name), v=_e(iid), label=t("opt_trash")
            )
        )
        if color == "green" and delete_offered:
            choices.append(
                '<label class="choice needs-permanent"><input type="radio" class="gn-choice" name="{n}" value="{v}" data-action="delete" data-kind="delete" data-path="{p}" data-size="{s}" disabled> {label}</label>'.format(
                    n=_e(name), v=_e(iid), p=_e(path), s=_e(format_bytes(item.get("size_bytes"))), label=t("opt_delete")
                )
            )
    pick = ""
    if choices:
        pick = '<input type="checkbox" class="gn-pick" data-choice="{0}" data-item-id="{1}" aria-label="{2}">'.format(
            _e(name), _e(iid), _e(item.get("name"))
        )
    badges = ['<span class="badge">{0}</span>'.format(_e(_kind_label(item.get("kind"), t)))]
    if item.get("open_by"):
        badges.append('<span class="badge red">{0}</span>'.format(t("open_by")))
    what = note.get("what") or _pick(item.get("what"), lang) or _pick(item.get("note"), lang)
    why = note.get("why") or _pick(item.get("why"), lang)
    if_removed = note.get("if_removed") or _pick(item.get("if_removed"), lang)
    restore = _pick(item.get("restore"), lang)
    rows = [(t("what"), _e(what)), (t("why"), _e(why)), (t("if_removed"), _e(if_removed)), (t("restore"), _e(restore))]
    body = [_path_line(path, t), _dl(rows)]
    extra_note = _pick(item.get("note"), lang)
    if extra_note and extra_note != what:
        body.append('<div class="sub">{0}: {1}</div>'.format(t("hint"), _e(extra_note)))
    if trash_paths and (len(trash_paths) > 1 or trash_paths[0] != path):
        body.append(
            '<div class="sub">{0}</div><ul class="members">{1}</ul>'.format(
                t("trash_paths"), "".join('<li><span class="mono">{0}</span></li>'.format(_e(p)) for p in trash_paths)
            )
        )
    kill = [str(p) for p in (item.get("kill_processes") or []) if p]
    if kill:
        body.append('<div class="sub">{0}: {1}</div>'.format(t("kill_processes"), _e(" · ".join(kill))))
    open_by = item.get("open_by") or []
    if open_by:
        procs = ", ".join(
            "{0} (pid {1})".format(_e(p.get("command")), _e(p.get("pid"))) if isinstance(p, dict) else _e(p) for p in open_by
        )
        body.append('<div class="sub">{0}: <span class="mono">{1}</span></div>'.format(t("open_by"), procs))
    commands = [str(c) for c in (item.get("commands") or []) if c]
    if commands:
        body.append('<div class="sub">{0}</div>'.format(t("commands")))
        body.extend(_copy_block(c, t) for c in commands)
    controls = choices + [_reveal_button(path, mode, t)]
    if any(controls):
        body.append('<div class="controls">{0}</div>'.format("".join(controls)))
    return _card(
        ids=[iid], subject=iid, color=color, name=str(item.get("name") or path), badges=badges,
        size=item.get("size_bytes"), pick=pick, body="".join(body),
    )


def _storage_buckets(data: Dict[str, Any], lang: str, mode: str, t: _T) -> Dict[str, List[str]]:
    """Every whole-machine card, keyed by colour."""

    items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
    notes = data.get("notes") or {}
    capabilities = data.get("capabilities") or {}
    delete_offered = bool(capabilities.get("permanent_delete_offered", True))
    buckets: Dict[str, List[str]] = {c: [] for c in COLORS}
    for item in items:
        color = item_color(item)
        buckets[color].append(_card_item(item, color, notes, lang, mode, t, delete_offered=delete_offered))
    return buckets


def _storage_sections(data: Dict[str, Any], lang: str, mode: str, t: _T) -> Tuple[str, Dict[str, int]]:
    buckets = _storage_buckets(data, lang, mode, t)
    permanent = _permanent_switch(data, mode, t)
    counts = {c: len(buckets[c]) for c in COLORS}
    html = "".join(
        [
            _section("green", "green", t("st_sec_green"), t("st_sec_green_desc"), buckets["green"], mode=mode, t=t, selectable=True, tools_extra=permanent),
            _section("yellow", "yellow", t("st_sec_yellow"), t("st_sec_yellow_desc"), buckets["yellow"], mode=mode, t=t, selectable=True),
            _section("red", "red", t("st_sec_red"), t("st_sec_red_desc"), buckets["red"], mode=mode, t=t, selectable=False),
        ]
    )
    return html, counts


def _disk_segments(disk: Dict[str, Any], items: List[Dict[str, Any]], primary: bool) -> List[Tuple[str, float]]:
    mount = str(disk.get("mount") or "")
    colored = {c: 0.0 for c in COLORS}
    for item in items:
        where = str(item.get("disk") or "")
        if where == mount or (not where and primary):
            colored[item_color(item)] += float(item.get("size_bytes") or 0)
    used = float(disk.get("used_bytes") or 0)
    total = float(disk.get("total_bytes") or 0)
    free = float(disk.get("free_bytes") or max(0.0, total - used))
    other = max(0.0, used - sum(colored.values()))
    return [("green", colored["green"]), ("yellow", colored["yellow"]), ("red", colored["red"]), ("other", other), ("free", free)]


def _priority_items(data: Dict[str, Any], lang: str) -> List[str]:
    """``overview.priority`` as list items; the Agent's own order is kept."""

    out = []
    for entry in (data.get("overview") or {}).get("priority") or []:
        text = _pick(entry.get("text") if isinstance(entry, dict) else entry, lang)
        if text:
            out.append("<li>{0}</li>".format(_e(text)))
    return out


def _disk_bars(data: Dict[str, Any], t: _T) -> str:
    """One bar per volume, used dividing into green / yellow / red / other / free."""

    items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
    disks = [d for d in (data.get("disks") or []) if isinstance(d, dict)]
    disk_html = []
    for index, disk in enumerate(disks):
        primary = bool(disk.get("primary")) or (index == 0 and not any(d.get("primary") for d in disks))
        used = disk.get("used_bytes")
        pct = disk.get("used_percent")
        pct_text = "{0:.0f}%".format(float(pct)) if isinstance(pct, (int, float)) else ""
        disk_html.append(
            '<div class="disk"><div class="head"><span><span class="name">{name}</span> <span class="sub mono">{mount}</span></span>'
            '<span class="sub">{used} · {pct}</span></div>{bar}'
            '<div class="legend"><span><span class="dot green"></span>{lg}</span><span><span class="dot yellow"></span>{ly}</span>'
            '<span><span class="dot red"></span>{lr}</span><span><span class="dot"></span>{lo}</span><span>{lf}</span></div></div>'.format(
                name=_e(disk.get("name") or disk.get("mount")), mount=_e(disk.get("mount") or ""),
                used=_e(t("disk_used", used=format_bytes(used), total=format_bytes(disk.get("total_bytes")))), pct=pct_text,
                bar=_segbar(_disk_segments(disk, items, primary)),
                lg=t("legend_green"), ly=t("legend_yellow"), lr=t("legend_red"), lo=t("seg_other"),
                lf=_e(t("disk_free", free=format_bytes(disk.get("free_bytes")))),
            )
        )
    return "".join(disk_html)


def _storage_overview(data: Dict[str, Any], lang: str, mode: str, t: _T, counts: Dict[str, int]) -> str:
    items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
    machine = data.get("machine") or {}
    summary = data.get("summary") or {}
    scan = data.get("scan") or {}
    overview = data.get("overview") or {}
    notes = data.get("notes") or {}
    by_color = _normalise_by_color(summary.get("by_color"), _by_color_items(items))

    sys_rows = [
        (t("sys_host"), machine.get("hostname")),
        (t("sys_os"), " ".join(str(x) for x in (machine.get("os"), machine.get("arch")) if x)),
        (t("sys_cpu"), machine.get("cpu")),
        (t("sys_mem"), format_bytes(machine.get("memory_bytes")) if machine.get("memory_bytes") else None),
        (t("sys_uptime"), t("sys_uptime_days", n=machine.get("uptime_days")) if machine.get("uptime_days") is not None else None),
        (t("sys_scanned"), format_bytes(summary.get("scanned_bytes")) if summary.get("scanned_bytes") else None),
        (t("sys_reclaim"), format_bytes(summary.get("reclaimable_bytes")) if summary.get("reclaimable_bytes") else None),
        (t("sys_elapsed"), "{0:.0f} s".format(float(scan.get("elapsed_s"))) if isinstance(scan.get("elapsed_s"), (int, float)) else None),
        (t("sys_denied"), ", ".join(str(x) for x in (scan.get("denied") or [])) or None),
    ]
    sys_html = "".join(
        '<div><span class="k">{0}</span><span class="v">{1}</span></div>'.format(_e(k), _e(v)) for k, v in sys_rows if v
    )
    legend = "".join(
        '<span><span class="dot {0}"></span>{1} <b>{2}</b> · {3}</span>'.format(
            c, t("legend_" + c), by_color[c]["count"], format_bytes(by_color[c]["bytes"])
        )
        for c in COLORS
    )
    headline = _pick(notes.get("headline"), lang) or _pick(overview.get("headline"), lang)
    left = (
        '<div class="card overview"><h3>{dt}</h3>{disks}'
        '<h3 style="margin-top:20px">{lt}</h3>{bar}<div class="legend">{legend}</div>{line}'
        '<h3 style="margin-top:20px">{st}</h3><div class="sys">{sys}</div></div>'
    ).format(
        dt=t("disk_title"), disks=_disk_bars(data, t), lt=t("color_split"), bar=_segbar([(c, by_color[c]["bytes"]) for c in COLORS]),
        legend=legend, line='<p class="line">{0}</p>'.format(_e(headline)) if headline else "", st=t("sys_title"), sys=sys_html,
    )
    li = _priority_items(data, lang) or _advice_items(counts, t)
    right = '<div class="card advice"><h3>{0}</h3><ol>{1}</ol>{2}</div>'.format(
        t("advice_title"), "".join(li), _pick_green_button(counts, t)
    )
    return '<div class="grid2">{0}{1}</div>'.format(left, right)


def _by_color_items(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    out = {c: {"count": 0, "bytes": 0} for c in COLORS}
    for item in items:
        c = item_color(item)
        out[c]["count"] += 1
        out[c]["bytes"] += int(item.get("size_bytes") or 0)
    return out


def _storage_top5(data: Dict[str, Any], lang: str, t: _T) -> str:
    top = [x for x in (data.get("top5") or data.get("top") or []) if isinstance(x, dict)]
    if not top:
        return ""
    by_id = {str(i.get("id")): i for i in (data.get("items") or []) if isinstance(i, dict)}

    def _size(entry: Dict[str, Any]) -> int:
        item = by_id.get(str(entry.get("id")), {})
        return int(entry.get("size_bytes") or item.get("size_bytes") or 0)

    # The written order is whatever the Agent typed; the table promises the five
    # largest, so it is sorted here rather than trusted.
    top = sorted(top, key=_size, reverse=True)
    rows = []
    for entry in top[:5]:
        item = by_id.get(str(entry.get("id")), {})
        color = _color(entry.get("color"), item_color(item) if item else "yellow")
        note = _pick(entry.get("note"), lang) or _pick(item.get("what"), lang)
        rows.append(
            '<tr><td class="c"><span class="dot {c}"></span></td><td class="size">{size}</td><td>{kind}</td>'
            '<td><b>{name}</b></td><td class="mono">{path}</td><td class="sub">{note}</td></tr>'.format(
                c=color, size=format_bytes(entry.get("size_bytes") or item.get("size_bytes")),
                kind=_e(_kind_label(entry.get("kind") or item.get("kind"), t)), name=_e(entry.get("name") or item.get("name")),
                path=_e(entry.get("path_portable") or item.get("path_portable") or ""), note=_e(note),
            )
        )
    head = "".join("<th>{0}</th>".format(_e(t(k))) for k in ("th_color", "th_size", "th_kind", "th_name", "th_path", "th_note"))
    return '<div class="card top5"><h3>{0}</h3><div class="scroll"><table><thead><tr>{1}</tr></thead><tbody>{2}</tbody></table></div></div>'.format(
        t("top5_title"), head, "".join(rows)
    )


def _storage_longterm(data: Dict[str, Any], lang: str, t: _T) -> str:
    overview = data.get("overview") or {}
    notes = data.get("notes") or {}
    lines = notes.get("long_term") if isinstance(notes.get("long_term"), list) else overview.get("long_term") or []
    li = "".join("<li>{0}</li>".format(_e(_pick(x, lang))) for x in lines if _pick(x, lang))
    if not li:
        return ""
    return '<div class="card longterm"><h3>{0}</h3><ul>{1}</ul></div>'.format(t("longterm_title"), li)


def _storage_bar(data: Dict[str, Any], lang: str, mode: str, t: _T) -> str:
    machine = data.get("machine") or {}
    cells = [
        (t("bar_machine"), '<span class="v">{0}</span>'.format(_e(" · ".join(str(x) for x in (machine.get("hostname"), machine.get("os")) if x)))),
        (t("bar_time"), '<span class="v">{0}</span>'.format(_display_time(data.get("created_at") or ""))),
        (t("bar_mode"), '<span class="v">{0}</span>'.format(t("mode_" + mode))),
    ]
    return _bar(t("title_storage"), cells, mode, t)


def render_storage_body(data: Dict[str, Any], lang: str, mode: str, t: _T) -> str:
    sections, counts = _storage_sections(data, lang, mode, t)
    return "".join(
        [
            _storage_bar(data, lang, mode, t),
            '<main class="wrap">',
            '<div class="intro"><h1>{0}</h1><p class="lede">{1}</p></div>'.format(t("heading_storage"), t("lede_storage")),
            _storage_overview(data, lang, mode, t, counts),
            _storage_top5(data, lang, t),
            sections,
            _storage_longterm(data, lang, t),
            '<p class="colophon">{0}</p>'.format(t("print_hint")),
            "</main>",
            _footer("storage", mode, t),
        ]
    )


# --------------------------------------------------------------------------
# combined page: one report, one entrance, one approval file
# --------------------------------------------------------------------------


def _clean_combined(
    data: Dict[str, Any], notes: Optional[Dict[str, Any]], home: Optional[Union[str, Path]]
) -> Dict[str, Any]:
    """Redact the two halves separately, then put them back in one envelope.

    They cannot share a pass: the tidy-up half knows its own home directory
    from ``source_root``/``source_root_portable``, the whole-machine half has no
    such pair and falls back to this account's home.  The Agent's notes are laid
    over both, and each half reads only the tables it knows.
    """

    plan, analysis = split_combined(data)
    out: Dict[str, Any] = {}
    if plan:
        out["plan"] = sanitize(merge_notes(plan, notes), home)
    if analysis:
        out["analysis"] = sanitize(merge_notes(analysis, notes), home)
    lang = data.get("lang") or (plan.get("lang") if plan else None) or (analysis.get("lang") if analysis else None)
    if lang:
        out["lang"] = lang
    capabilities: Dict[str, Any] = {}
    for half in (plan, analysis):
        capabilities.update(half.get("capabilities") or {})
    if capabilities:
        out["capabilities"] = capabilities
    executed = data.get("executed_ids")
    out["executed_ids"] = list(executed) if isinstance(executed, list) else []
    return out


def split_combined(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """``{"plan": ..., "analysis": ...}`` -> the two halves, either of them empty.

    A caller may hand over only one half; the page then simply has one block
    fewer.  Anything that is not a dict is treated as absent rather than as an
    error, because a half-written analysis.json should still let the tidy-up
    half render.
    """

    plan = data.get("plan")
    analysis = data.get("analysis")
    return (plan if isinstance(plan, dict) else {}), (analysis if isinstance(analysis, dict) else {})


def _combined_bar(plan: Dict[str, Any], analysis: Dict[str, Any], mode: str, t: _T) -> str:
    machine = analysis.get("machine") or {}
    cells = []
    if plan:
        cells.append((t("bar_dir"), '<span class="v mono">{0}</span>'.format(_e(plan.get("source_root_portable") or ""))))
    if analysis:
        cells.append(
            (
                t("bar_machine"),
                '<span class="v">{0}</span>'.format(
                    _e(" · ".join(str(x) for x in (machine.get("hostname"), machine.get("os")) if x))
                ),
            )
        )
    when = plan.get("created_at") or plan.get("now") or analysis.get("created_at") or ""
    cells.append((t("bar_time"), '<span class="v">{0}</span>'.format(_display_time(when))))
    cells.append((t("bar_mode"), '<span class="v">{0}</span>'.format(t("mode_" + mode))))
    return _bar(t("title_combined"), cells, mode, t)


def _combined_overview(
    plan: Dict[str, Any], analysis: Dict[str, Any], lang: str, mode: str, t: _T, counts: Dict[str, int]
) -> str:
    """Left: the disks and the mess score.  Right: one numbered list of what to do first."""

    left_parts = []
    if analysis.get("disks"):
        left_parts.append("<h3>{0}</h3>{1}".format(t("disk_title"), _disk_bars(analysis, t)))
    if plan:
        left_parts.append(
            '<div class="block">{0}</div>'.format(_mess_inner(plan, lang, t))
            if left_parts
            else _mess_inner(plan, lang, t)
        )
    headline = ""
    if analysis:
        notes = analysis.get("notes") or {}
        headline = _pick(notes.get("headline"), lang) or _pick((analysis.get("overview") or {}).get("headline"), lang)
    if headline:
        left_parts.append('<p class="line">{0}</p>'.format(_e(headline)))
    left = '<div class="card overview">{0}</div>'.format("".join(left_parts))

    items = _priority_items(analysis, lang) if analysis else []
    items.extend(_advice_items(counts, t))
    if not items:
        items.append("<li>{0}</li>".format(_e(t("advice_none"))))
    folder_line = _pick((plan.get("notes") or {}).get("folder_line"), lang) if plan else ""
    right = '<div class="card advice"><h3>{title}</h3>{folder}<ol>{items}</ol>{tools}</div>'.format(
        title=t("advice_title"),
        folder='<p class="line">{0}</p>'.format(_e(folder_line)) if folder_line else "",
        items="".join(items),
        tools=_pick_green_button(counts, t),
    )
    return '<div class="grid2">{0}{1}</div>'.format(left, right)


def _combined_sections(
    plan: Dict[str, Any], analysis: Dict[str, Any], lang: str, mode: str, t: _T
) -> Tuple[str, Dict[str, int]]:
    """Three bands, each one cleanup first and moves second."""

    clean = _storage_buckets(analysis, lang, mode, t) if analysis else {c: [] for c in COLORS}
    move = _organize_buckets(plan, lang, mode, t) if plan else {c: [] for c in COLORS}
    permanent = _permanent_switch(analysis or plan, mode, t)
    counts = {c: len(clean[c]) + len(move[c]) for c in COLORS}
    titles = {"green": "cb_green", "yellow": "cb_yellow", "red": "cb_red"}
    html = []
    for color in COLORS:
        html.append(
            _section(
                color,
                color,
                t(titles[color]),
                t(titles[color] + "_desc"),
                [],
                mode=mode,
                t=t,
                selectable=color != "red",
                tools_extra=permanent if color == "green" else "",
                subgroups=[(t("sub_clean"), clean[color]), (t("sub_move"), move[color])],
            )
        )
    return "".join(html), counts


def _preview_block(plan: Dict[str, Any], analysis: Dict[str, Any], lang: str, t: _T) -> str:
    """The after picture, rendered by ``carl_file_organizer.preview``.

    The fragment carries its own style and script and loads nothing, so it is
    dropped in verbatim.  A preview that cannot be built is not worth failing a
    report over, so a broken one leaves the section out entirely.
    """

    try:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        from carl_file_organizer import preview as preview_module
    except Exception:  # noqa: BLE001 - a missing preview costs the page one block
        return ""
    try:
        graph = preview_module.build_graph(plan or {}, analysis or None)
        fragment = preview_module.render_preview_html(graph, lang=lang, height=720)
    except Exception:  # noqa: BLE001 - same reasoning
        return ""
    return (
        '<section class="preview-wrap" id="gn-preview">'
        '<div class="sec-head"><div><h2>{0}</h2><p class="sub">{1}</p></div></div>'
        "{2}</section>"
    ).format(_e(t("preview_title")), _e(t("preview_note")), fragment)


def _combined_longterm(plan: Dict[str, Any], analysis: Dict[str, Any], lang: str, t: _T) -> str:
    blocks = []
    if analysis:
        blocks.append(_storage_longterm(analysis, lang, t))
    if plan:
        blocks.append(_organize_longterm(plan, lang, t))
    return "".join(b for b in blocks if b)


def render_combined_body(data: Dict[str, Any], lang: str, mode: str, t: _T) -> str:
    plan, analysis = split_combined(data)
    sections, counts = _combined_sections(plan, analysis, lang, mode, t)
    return "".join(
        [
            _combined_bar(plan, analysis, mode, t),
            '<main class="wrap">',
            '<div class="intro"><h1>{0}</h1><p class="lede">{1}</p></div>'.format(
                t("heading_combined"), t("lede_combined")
            ),
            _combined_overview(plan, analysis, lang, mode, t, counts),
            _storage_top5(analysis, lang, t) if analysis else "",
            sections,
            _preview_block(plan, analysis, lang, t),
            _combined_longterm(plan, analysis, lang, t),
            '<p class="colophon">{0}</p>'.format(t("print_hint")),
            "</main>",
            _footer("combined", mode, t),
        ]
    )


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def render(
    data: Dict[str, Any],
    *,
    mode: str = "static",
    token: str = "",
    lang: Optional[str] = None,
    notes: Optional[Dict[str, Any]] = None,
    kind: Optional[str] = None,
    template_path: Optional[Union[str, Path]] = None,
    home: Optional[Union[str, Path]] = None,
) -> str:
    """The finished page for ``data`` (a plan.json or an analysis.json dict)."""

    if mode not in MODES:
        raise ValueError("mode must be one of {0}".format(", ".join(MODES)))
    kind = kind or detect_kind(data)
    if kind not in KINDS:
        raise ValueError("kind must be one of {0}".format(", ".join(KINDS)))
    template = load_template(template_path)
    text = template_text(template)
    if kind == "combined":
        clean = _clean_combined(data, notes, home)
    else:
        clean = sanitize(merge_notes(data, notes), home)
    lang = _lang_of(clean, lang)
    t = _T(text, lang)
    if mode != "serve":
        token = ""
    capabilities = dict(clean.get("capabilities") or {})
    config = {
        "kind": kind,
        "mode": mode,
        "token": token,
        "lang": lang,
        "capabilities": capabilities,
        "generator": "build_report.py {0}".format(__version__),
    }
    if kind == "combined":
        body = render_combined_body(clean, lang, mode, t)
    elif kind == "organize":
        body = render_organize_body(clean, lang, mode, t)
    else:
        body = render_storage_body(clean, lang, mode, t)
    mapping = {
        "LANG": "zh-CN" if lang == "zh" else "en",
        "TITLE": _e(t("title_" + kind)),
        "KIND": kind,
        "MODE": mode,
        "DATA": _embed_json(clean),
        "CONFIG": _embed_json(config),
        "BODY": body,
    }
    return re.sub(r"__REPORT_(LANG|TITLE|KIND|MODE|DATA|CONFIG|BODY)__", lambda m: mapping[m.group(1)], template)


def _read_json(path: Union[str, Path]) -> Dict[str, Any]:
    with open(str(path), "r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render the three-colour report page.")
    parser.add_argument("input", help="plan.json or analysis.json")
    parser.add_argument("--notes", help="notes.json written by the Agent (what / why / if_removed per id)")
    parser.add_argument("-o", "--output", help="where to write report.html (default: next to the input)")
    parser.add_argument("--mode", choices=MODES, default="static")
    parser.add_argument("--token", default="", help="serve-mode token embedded in the page")
    parser.add_argument("--lang", choices=LANGS, default=None)
    parser.add_argument("--kind", choices=KINDS, default=None, help="override the auto-detected page kind")
    args = parser.parse_args(argv)

    data = _read_json(args.input)
    notes = _read_json(args.notes) if args.notes else None
    html = render(data, mode=args.mode, token=args.token, lang=args.lang, notes=notes, kind=args.kind)
    output = Path(args.output) if args.output else Path(args.input).resolve().parent / "report.html"
    output.write_text(html, encoding="utf-8")
    sys.stdout.write("{0}\n".format(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
