"""The agent explanation layer: prose laid on top of a plan, changing nothing.

The rules decide, and they say why in one fixed sentence per rule.  That reads
like a form letter, because it is one.  An agent that has looked at the folder
can say what a thing actually is, why it is there and what breaks if it goes
away, and that is what this module carries.

The one rule that makes it safe: notes are text.  :func:`merge_notes` copies
nothing but strings, and it copies them into ``plan["notes"]``, never into an
action.  No note can add an action, approve one, change a destination, change a
colour on an action, or turn a hold into anything else.  The executor still only
knows the ids the planner computed, so a wrong note is a wrong sentence and
nothing worse.

The single exception is the folder colour: thresholds are a guess about a folder
an agent has actually looked at, so ``notes["mess"]["color"]`` may override
``plan["mess"]["color"]``.  The original stays in ``rule_color`` and the plan
records who decided, so nobody has to wonder later.

    plan = merge_notes(plan, json.loads(Path("notes.json").read_text()))

Unknown ids only warn.  A note left over from a previous scan is a stale
sentence, not a reason to refuse to write a report.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import i18n
from .planner import COLORS

#: Version of the notes.json shape.  Bumped only when a field is removed.
NOTES_SCHEMA = 1

#: The three sentences an agent may write about one action or one group.
ITEM_FIELDS = ("what", "why", "if_removed")

#: Top level keys notes.json is allowed to carry.
TOP_FIELDS = ("mess", "actions", "groups", "folder_line")

#: Longest a single sentence may be; longer is truncated, never dropped.
MAX_TEXT = 600


class NotesError(ValueError):
    """The notes file is not a JSON object at all.  Everything else only warns."""


# ---------------------------------------------------------------------------
# reading and cleaning
# ---------------------------------------------------------------------------


def load_notes(path: Path) -> Dict[str, Any]:
    """Read notes.json, or raise :class:`NotesError` with a readable line."""

    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise NotesError("cannot read notes file {0}: {1}".format(path, error)) from error
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise NotesError("notes file {0} is not valid JSON: {1}".format(path, error)) from error
    if not isinstance(data, dict):
        raise NotesError("notes file {0} must hold a JSON object".format(path))
    return data


def _text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:MAX_TEXT]


def _clean_item(
    raw: Any, where: str, warnings: List[str]
) -> Optional[Dict[str, str]]:
    """Keep the three known sentences, drop everything else with a warning."""

    if not isinstance(raw, dict):
        warnings.append("{0}: expected an object, ignored".format(where))
        return None
    kept: Dict[str, str] = {}
    for key, value in raw.items():
        if key not in ITEM_FIELDS:
            warnings.append("{0}: unknown field {1!r}, ignored".format(where, key))
            continue
        text = _text(value)
        if text is None:
            warnings.append("{0}.{1}: not a non-empty string, ignored".format(where, key))
            continue
        kept[key] = text
    if not kept:
        return None
    return kept


def _clean_map(
    raw: Any,
    known_ids: Mapping[str, Any],
    label: str,
    warnings: List[str],
) -> Dict[str, Dict[str, str]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        warnings.append("{0}: expected an object keyed by id, ignored".format(label))
        return {}
    cleaned: Dict[str, Dict[str, str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            warnings.append("{0}: non-string id ignored".format(label))
            continue
        if key not in known_ids:
            warnings.append("{0}: no such id in this plan: {1}".format(label, key))
            continue
        item = _clean_item(value, "{0}[{1}]".format(label, key), warnings)
        if item is not None:
            cleaned[key] = item
    return cleaned


def _clean_mess(raw: Any, warnings: List[str]) -> Dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        warnings.append("mess: expected an object, ignored")
        return {}
    cleaned: Dict[str, Any] = {}
    for key, value in raw.items():
        if key == "color":
            if value in COLORS:
                cleaned["color"] = value
            else:
                warnings.append("mess.color: not one of {0}, ignored".format(", ".join(COLORS)))
        elif key == "line":
            text = _text(value)
            if text is None:
                warnings.append("mess.line: not a non-empty string, ignored")
            else:
                cleaned["line"] = text
        else:
            warnings.append("mess: unknown field {0!r}, ignored".format(key))
    return cleaned


# ---------------------------------------------------------------------------
# merging
# ---------------------------------------------------------------------------


def validate_notes(
    plan: Mapping[str, Any], notes: Mapping[str, Any]
) -> Tuple[Dict[str, Any], List[str]]:
    """``(cleaned notes, warnings)``.  Nothing here reads the filesystem."""

    warnings: List[str] = []
    if not isinstance(notes, dict):
        raise NotesError("notes must be a JSON object")

    action_ids = {
        str(action.get("id")): action for action in (plan.get("actions") or []) if isinstance(action, dict)
    }
    group_ids = {
        str(group.get("group_id")): group for group in (plan.get("groups") or []) if isinstance(group, dict)
    }

    for key in notes:
        if key not in TOP_FIELDS:
            warnings.append("unknown top level field {0!r}, ignored".format(key))

    cleaned: Dict[str, Any] = {
        "schema": NOTES_SCHEMA,
        "mess": _clean_mess(notes.get("mess"), warnings),
        "actions": _clean_map(notes.get("actions"), action_ids, "actions", warnings),
        "groups": _clean_map(notes.get("groups"), group_ids, "groups", warnings),
        "folder_line": _text(notes.get("folder_line")),
    }
    if notes.get("folder_line") is not None and cleaned["folder_line"] is None:
        warnings.append("folder_line: not a non-empty string, ignored")
    return cleaned, warnings


def merge_notes(plan: Mapping[str, Any], notes: Mapping[str, Any]) -> Dict[str, Any]:
    """A copy of ``plan`` with ``notes`` merged into ``plan["notes"]``.

    The input plan is not touched.  Merging twice is the same as merging once
    with the second set of notes: the previous block is replaced, not appended,
    so a re-run after fixing a sentence does not leave the old one behind.
    """

    if not isinstance(plan, dict):
        raise NotesError("plan must be a JSON object")
    cleaned, warnings = validate_notes(plan, notes)
    merged = copy.deepcopy(dict(plan))
    cleaned["warnings"] = warnings
    merged["notes"] = cleaned

    mess = merged.get("mess")
    if isinstance(mess, dict):
        # Put the rule's own answer somewhere permanent before anything can
        # overwrite it, whether or not the notes carry a colour.
        mess.setdefault("rule_color", mess.get("color"))
        chosen = cleaned["mess"].get("color")
        if chosen:
            mess["color"] = chosen
            mess["color_source"] = "notes"
        else:
            mess["color_source"] = mess.get("color_source") or "rule"
        line = cleaned["mess"].get("line")
        if line:
            mess["line"] = line
    elif cleaned["mess"]:
        warnings.append("mess: this plan has no mess block, the folder colour was not changed")
    return merged


def merge_notes_file(plan: Mapping[str, Any], path: Path) -> Dict[str, Any]:
    """:func:`merge_notes` with the reading done for you."""

    return merge_notes(plan, load_notes(path))


# ---------------------------------------------------------------------------
# CLI entry point: carl-file-organizer build
# ---------------------------------------------------------------------------


def run(args: Any) -> int:
    """``build``: lay notes.json over a plan.json and write the plan back."""

    plan_path = Path(getattr(args, "plan"))
    lang = getattr(args, "lang", None) or "en"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise NotesError("cannot read plan {0}: {1}".format(plan_path, error)) from error
    except ValueError as error:
        raise NotesError("plan {0} is not valid JSON: {1}".format(plan_path, error)) from error
    if not isinstance(plan, dict):
        raise NotesError("plan {0} must hold a JSON object".format(plan_path))
    lang = plan.get("lang") or lang

    notes_path = getattr(args, "notes", None)
    if notes_path is None:
        merged = plan
        warnings: List[str] = []
    else:
        merged = merge_notes(plan, load_notes(Path(notes_path)))
        warnings = list((merged.get("notes") or {}).get("warnings") or ())

    output = Path(getattr(args, "output", None) or plan_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for line in warnings:
        print(i18n.t("warning_prefix", lang) + line)
    print(i18n.t("cli_notes_merged", lang, path=output, count=len(warnings)))

    if bool(getattr(args, "report", False)):
        try:
            from .report import write_report

            report_path = output.parent / "report.html"
            write_report(merged, report_path)
        except Exception as error:  # noqa: BLE001 - the plan is the deliverable
            print(
                i18n.t("cli_report_skipped", lang, module="carl_file_organizer.report")
                + " ({0})".format(error)
            )
        else:
            print(i18n.t("cli_report_written", lang, path=report_path))
    return 0
