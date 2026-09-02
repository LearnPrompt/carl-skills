"""The gate in front of the whole-machine inventory's disposals.

``storage_scan.py`` measures, the Agent explains in ``analysis.json``, the report
page collects clicks, and this module is the only thing that acts.  It exists
because the page is untrusted input: whatever arrives from the browser, the only
paths this module will ever touch are the ones the Agent already whitelisted in
``analysis.json``, and only for the colour that allows the action asked for.

Four doors, in this order:

1. :func:`validate_decisions` matches every submitted id back to an item, refuses
   anything red, refuses a permanent delete on anything but green with the flag,
   and walks each ``trash_paths`` entry through the path rules: inside the home
   directory, no symlink segment, not a no-go basename, and never the home
   directory itself or one of its immediate children.  A parent directory
   standing in for its contents is exactly what that last rule forbids.
2. :func:`preflight` looks at the real filesystem: the path is still there, and
   nobody has it open.  ``lsof`` being unavailable is recorded as ``unknown``
   rather than treated as "nobody", because the honest answer is that we do not
   know.
3. :func:`execute` writes the manifest before it touches anything, appends one
   audit line per path the moment that path is done, and stops the batch on the
   first failure.  A failed trash never turns into a delete: the two branches
   never meet.
4. :func:`apply_decisions` is the three of them in order, and the only thing the
   CLI and the review server call.

Nothing here is specific to macOS beyond the trash backend, which lives in
:mod:`carl_file_organizer.trash` and refuses rather than improvises.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from . import manifest as manifest_module
from . import paths
from . import trash as trash_module

#: Where the storage line keeps its own paper trail, relative to the home
#: directory.  Deliberately not the tidy-up managed folder: a tidy-up ``undo``
#: reads a folder full of moves, and a folder full of disposals has nothing for
#: it to put back.
MANAGED_SUBDIR = (".carl-file-organizer", "storage")

SCHEMA = "carl-file-organizer/storage-decisions"

ACTIONS = ("trash", "delete")
COLORS = ("green", "yellow", "red")

#: One row per path, in the seven columns the storage line writes.
MANIFEST_COLUMNS = (
    "action_at",
    "status",
    "path",
    "size_kib_before",
    "reason",
    "restore_method",
    "error",
)

MANIFEST_PREFIX = "storage-removals"

#: result status -> manifest status.
STATUS_MANIFEST = {
    "planned": "PLANNED",
    "trashed": "TRASHED",
    "deleted": "DELETED",
    "dry-run": "DRY-RUN",
    "skipped": "SKIPPED",
    "refused": "REFUSED",
    "failed": "FAILED",
}

#: Statuses that mean the path is really gone from where it was.
DONE_STATUSES = ("trashed", "deleted")

DEFAULT_MEASURE_BUDGET_S = 5.0
DEFAULT_LSOF_TIMEOUT_S = 3.0

TEXT: Dict[str, Dict[str, str]] = {
    "zh": {
        "not_object": "决定清单必须是一个 JSON 对象",
        "bad_schema": "决定清单的 schema 不是 {expected}，拒绝执行",
        "no_items": "决定清单里一个条目都没有",
        "bad_item_ids": "item_ids 必须是字符串数组",
        "bad_actions": "actions 必须是 id 到 trash 或 delete 的映射",
        "analysis_not_object": "analysis.json 必须是一个 JSON 对象",
        "analysis_no_items": "analysis.json 里没有 items",
        "unknown_item": "这个 id 不在 analysis.json 里，拒绝",
        "bad_action": "不认识的动作 {action}，只接受 trash 或 delete",
        "red": "红色条目不提供任何删除接口，拒绝",
        "yellow_delete": "黄色条目只能进废纸篓，不能永久删除",
        "delete_no_flag": "永久删除要带 --allow-permanent-delete，拒绝",
        "not_scanned": "这是系统提示条目，没有实测体积，不参与处置",
        "no_paths": "这个条目没有核实过的 trash_paths，没有可动的路径",
        "outside_home": "路径不在家目录里，拒绝：{path}",
        "too_shallow": "这是家目录本身或它的一级子目录，太粗了，要写到具体那一层：{path}",
        "symlink": "路径里有软链，拒绝：{path}",
        "forbidden": "路径命中禁刀区（{label}），拒绝：{path}",
        "duplicate_path": "这条路径在这一批里已经出现过了，跳过：{path}",
        "empty_path": "trash_paths 里有一条空路径，拒绝",
        "missing": "这条路径已经不在了，跳过",
        "in_use": "还有程序占着它（{who}），先退掉再来",
        "open_unknown": "这台机器查不了谁在用它，按未知放行",
        "dry_run": "只是试跑，什么都没动",
        "batch_stopped": "前面一条失败了，这一批剩下的都不动",
        "trashed": "已进废纸篓",
        "deleted": "已永久删除",
        "no_backend": "这台机器没有可用的废纸篓后端，拒绝处置",
        "recheck_symlink": "动手前复查发现路径里有软链，拒绝",
        "recheck_forbidden": "动手前复查发现路径进了禁刀区，拒绝",
        "recheck_outside": "动手前复查发现路径不在家目录里，拒绝",
        "error": "出错了：{error}",
        "restore_trash": "在废纸篓里选放回原处",
        "restore_none": "永久删除，没法还原",
        "cli_done": "处置完成：{done} 条动了，{other} 条没动；manifest {manifest}",
        "cli_dry": "试跑完成：{total} 条会走一遍，什么都没动",
        "cli_line": "{status}  {path}  {detail}",
    },
    "en": {
        "not_object": "the decisions file must be a JSON object",
        "bad_schema": "the decisions file is not schema {expected}; refusing",
        "no_items": "the decisions file names no items",
        "bad_item_ids": "item_ids must be a list of strings",
        "bad_actions": "actions must map an id to trash or delete",
        "analysis_not_object": "analysis.json must be a JSON object",
        "analysis_no_items": "analysis.json has no items",
        "unknown_item": "this id is not in analysis.json; refused",
        "bad_action": "unknown action {action}; only trash or delete",
        "red": "a red item has no delete interface at all; refused",
        "yellow_delete": "a yellow item can only go to the trash, never a permanent delete",
        "delete_no_flag": "a permanent delete needs --allow-permanent-delete; refused",
        "not_scanned": "this is a system note with no measured size; it takes no action",
        "no_paths": "this item has no verified trash_paths, so there is nothing to act on",
        "outside_home": "that path is not inside the home directory; refused: {path}",
        "too_shallow": "that is the home directory or one of its immediate children; name the exact folder: {path}",
        "symlink": "a symlink sits in that path; refused: {path}",
        "forbidden": "that path is in a no-go zone ({label}); refused: {path}",
        "duplicate_path": "that path is already in this batch; skipped: {path}",
        "empty_path": "trash_paths holds an empty path; refused",
        "missing": "that path is not there any more; skipped",
        "in_use": "something still has it open ({who}); quit it first",
        "open_unknown": "this machine cannot tell who has it open; treated as unknown",
        "dry_run": "dry run; nothing was touched",
        "batch_stopped": "an earlier item failed; the rest of this batch was left alone",
        "trashed": "moved to the trash",
        "deleted": "permanently deleted",
        "no_backend": "no trash backend on this machine; refusing to dispose of anything",
        "recheck_symlink": "the recheck found a symlink in the path; refused",
        "recheck_forbidden": "the recheck found the path in a no-go zone; refused",
        "recheck_outside": "the recheck found the path outside the home directory; refused",
        "error": "error: {error}",
        "restore_trash": "put it back from the Trash",
        "restore_none": "permanently deleted; nothing to put back",
        "cli_done": "done: {done} acted on, {other} left alone; manifest {manifest}",
        "cli_dry": "dry run finished: {total} paths would be walked, nothing was touched",
        "cli_line": "{status}  {path}  {detail}",
    },
}


class DisposeError(ValueError):
    """The decisions file, or the analysis behind it, cannot be acted on."""


def text(key: str, lang: str = "en", **kw: Any) -> str:
    table = TEXT.get(lang) or TEXT["en"]
    template = table.get(key) or TEXT["en"].get(key) or key
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError):
        return template


# --------------------------------------------------------------------------
# shapes
# --------------------------------------------------------------------------


@dataclass
class DisposeRow:
    """One path, with the decision that put it here and how far it got."""

    item_id: str
    action: str
    color: str
    path: Optional[Path]
    path_portable: str
    status: str
    detail: str = ""
    size_bytes: int = 0
    open_check: str = ""
    reason: str = ""
    restore_method: str = ""

    @property
    def planned(self) -> bool:
        return self.status == "planned"


@dataclass
class ValidatedDecisions:
    analysis: Dict[str, Any]
    decisions: Dict[str, Any]
    home: Path
    lang: str
    allow_permanent_delete: bool
    trash_backend: str
    rows: List[DisposeRow] = field(default_factory=list)
    profile: Dict[str, Any] = field(default_factory=dict)

    @property
    def targets(self) -> List[DisposeRow]:
        return [row for row in self.rows if row.planned]

    def status_of(self, item_id: str) -> List[str]:
        return [row.status for row in self.rows if row.item_id == item_id]


@dataclass
class DisposeReport:
    run_id: str
    dry_run: bool
    results: List[Dict[str, Any]] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    manifest: Optional[Path] = None
    audit: Optional[Path] = None
    trash_backend: str = trash_module.NONE
    stopped: bool = False

    @property
    def executed_ids(self) -> List[str]:
        seen: List[str] = []
        for record in self.results:
            if record.get("status") in DONE_STATUSES:
                item_id = str(record.get("item_id") or "")
                if item_id and item_id not in seen:
                    seen.append(item_id)
        return seen


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def managed_dir(home: Optional[Path] = None) -> Path:
    """``$HOME/.carl-file-organizer/storage``: scan, analysis, report, paper trail."""

    base = Path(home) if home is not None else Path.home()
    return base.joinpath(*MANAGED_SUBDIR)


def manifest_path(managed: Path, ts: datetime) -> Path:
    return Path(managed) / "{0}-{1}.tsv".format(
        MANIFEST_PREFIX, manifest_module.timestamp_text(ts)
    )


def _pick(value: Any, lang: str) -> str:
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("en") or value.get("zh") or "")
    return "" if value is None else str(value)


def measure_bytes(path: Path, *, budget_s: float = DEFAULT_MEASURE_BUDGET_S) -> int:
    """Logical size of ``path`` before it goes away, with a time budget.

    The number is only ever written into the manifest, so a directory that runs
    out of budget returns what it counted rather than holding up the disposal.
    """

    target = Path(path)
    try:
        if target.is_symlink() or not target.is_dir():
            return int(target.lstat().st_size)
    except OSError:
        return 0
    total = 0
    deadline = time.monotonic() + max(budget_s, 0.0)
    for dirpath, _dirnames, filenames in os.walk(str(target), onerror=lambda _e: None):
        for name in filenames:
            try:
                total += int(os.lstat(os.path.join(dirpath, name)).st_size)
            except OSError:
                continue
        if time.monotonic() > deadline:
            break
    return total


def _kib(size_bytes: int) -> int:
    return int(math.ceil(max(int(size_bytes), 0) / 1024.0))


def _default_profile() -> Dict[str, Any]:
    from . import config as config_module

    return config_module.load_builtin_profile("tiered")


def _who(handles: Sequence[Any]) -> str:
    names = []
    for handle in handles:
        if isinstance(handle, Mapping):
            names.append("{0} (pid {1})".format(handle.get("command"), handle.get("pid")))
        else:
            names.append(str(handle))
    return ", ".join(names[:4])


# --------------------------------------------------------------------------
# stage one: validate
# --------------------------------------------------------------------------


def _refusal(item_id: str, action: str, color: str, portable: str, detail: str) -> DisposeRow:
    return DisposeRow(
        item_id=item_id,
        action=action,
        color=color,
        path=None,
        path_portable=portable,
        status="refused",
        detail=detail,
    )


def _check_path(
    portable_text: str,
    *,
    home: Path,
    profile: Mapping[str, Any],
    lang: str,
) -> Optional[str]:
    """``None`` when the path may be acted on, otherwise the refusal sentence."""

    if not portable_text or not isinstance(portable_text, str):
        return text("empty_path", lang)
    expanded = paths.expand_portable(portable_text, home)
    if not paths.inside_root(expanded, home):
        return text("outside_home", lang, path=portable_text)
    try:
        relative = paths.realpath(expanded).relative_to(paths.realpath(home))
    except ValueError:
        return text("outside_home", lang, path=portable_text)
    if len(relative.parts) < 2:
        return text("too_shallow", lang, path=portable_text)
    if paths.has_symlink_component(expanded, home):
        return text("symlink", lang, path=portable_text)
    label = paths.is_forbidden(expanded, profile)
    if label:
        return text("forbidden", lang, label=label, path=portable_text)
    return None


def validate_decisions(
    analysis: Mapping[str, Any],
    decisions: Mapping[str, Any],
    *,
    allow_permanent_delete: bool = False,
    home: Optional[Path] = None,
    profile: Optional[Mapping[str, Any]] = None,
    lang: Optional[str] = None,
    trash_backend: Optional[str] = None,
) -> ValidatedDecisions:
    """Turn a page's clicks into the paths this tool is willing to touch.

    Every rejection becomes a ``refused`` row rather than an exception, so one
    bad id does not cost the person the rest of their selection.  Only the two
    documents themselves being unusable raises :class:`DisposeError`.
    """

    if not isinstance(analysis, Mapping):
        raise DisposeError(text("analysis_not_object", lang or "en"))
    speech = lang or str(analysis.get("lang") or "") or "en"
    if speech not in TEXT:
        speech = "en"
    if not isinstance(decisions, Mapping):
        raise DisposeError(text("not_object", speech))

    schema = str(decisions.get("schema") or SCHEMA)
    if schema != SCHEMA:
        raise DisposeError(text("bad_schema", speech, expected=SCHEMA))

    raw_items = analysis.get("items")
    if not isinstance(raw_items, list):
        raise DisposeError(text("analysis_no_items", speech))
    index: Dict[str, Dict[str, Any]] = {}
    for entry in raw_items:
        if isinstance(entry, Mapping) and entry.get("id"):
            index[str(entry["id"])] = dict(entry)

    item_ids = decisions.get("item_ids")
    if not isinstance(item_ids, list) or not all(isinstance(i, str) for i in item_ids):
        raise DisposeError(text("bad_item_ids", speech))
    if not item_ids:
        raise DisposeError(text("no_items", speech))
    actions = decisions.get("actions") or {}
    if not isinstance(actions, Mapping) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in actions.items()
    ):
        raise DisposeError(text("bad_actions", speech))

    home_dir = Path(home) if home is not None else Path.home()
    rules = dict(profile) if profile is not None else _default_profile()
    backend = trash_backend if trash_backend is not None else trash_module.detect_backend()

    rows: List[DisposeRow] = []
    seen_paths: Dict[str, str] = {}
    for item_id in item_ids:
        action = str(actions.get(item_id) or "trash")
        item = index.get(item_id)
        if item is None:
            rows.append(_refusal(item_id, action, "", "", text("unknown_item", speech)))
            continue
        color = str(item.get("color") or "")
        portable = str(item.get("path_portable") or "")
        if action not in ACTIONS:
            rows.append(_refusal(item_id, action, color, portable, text("bad_action", speech, action=action)))
            continue
        if color not in COLORS or color == "red":
            rows.append(_refusal(item_id, action, color or "red", portable, text("red", speech)))
            continue
        if item.get("scanned") is False:
            rows.append(_refusal(item_id, action, color, portable, text("not_scanned", speech)))
            continue
        if action == "delete" and color != "green":
            rows.append(_refusal(item_id, action, color, portable, text("yellow_delete", speech)))
            continue
        if action == "delete" and not allow_permanent_delete:
            rows.append(_refusal(item_id, action, color, portable, text("delete_no_flag", speech)))
            continue

        trash_paths = [p for p in (item.get("trash_paths") or []) if isinstance(p, str)]
        if not trash_paths:
            rows.append(_refusal(item_id, action, color, portable, text("no_paths", speech)))
            continue

        refusal = None
        for candidate in trash_paths:
            refusal = _check_path(candidate, home=home_dir, profile=rules, lang=speech)
            if refusal is not None:
                break
        if refusal is not None:
            # One bad path condemns the whole item: a whitelist that is partly
            # wrong is a whitelist nobody checked.
            rows.append(_refusal(item_id, action, color, portable, refusal))
            continue

        name = _pick(item.get("name"), speech) or item_id
        reason = "{0} · {1}".format(item_id, name)
        restore = (
            text("restore_trash", speech)
            if action == "trash"
            else (_pick(item.get("restore_hint"), speech) or text("restore_none", speech))
        )
        for candidate in trash_paths:
            expanded = paths.expand_portable(candidate, home_dir)
            key = str(paths.realpath(expanded))
            if key in seen_paths:
                rows.append(
                    DisposeRow(
                        item_id=item_id,
                        action=action,
                        color=color,
                        path=None,
                        path_portable=candidate,
                        status="skipped",
                        detail=text("duplicate_path", speech, path=candidate),
                        reason=reason,
                        restore_method=restore,
                    )
                )
                continue
            seen_paths[key] = item_id
            rows.append(
                DisposeRow(
                    item_id=item_id,
                    action=action,
                    color=color,
                    path=expanded,
                    path_portable=candidate,
                    status="planned",
                    size_bytes=int(item.get("size_bytes") or 0) if len(trash_paths) == 1 else 0,
                    reason=reason,
                    restore_method=restore,
                )
            )

    return ValidatedDecisions(
        analysis=dict(analysis),
        decisions=dict(decisions),
        home=home_dir,
        lang=speech,
        allow_permanent_delete=bool(allow_permanent_delete),
        trash_backend=backend,
        rows=rows,
        profile=rules,
    )


# --------------------------------------------------------------------------
# stage two: preflight
# --------------------------------------------------------------------------


def preflight(
    validated: ValidatedDecisions,
    *,
    open_handles_fn: Optional[Callable[[Path], Any]] = None,
    measure: bool = True,
) -> ValidatedDecisions:
    """Ask the filesystem, right now, whether each planned path can be touched.

    Mutates and returns ``validated``: a row that fails here stops being planned,
    so :func:`execute` only ever walks rows the machine agreed with a moment ago.
    """

    from . import guard as guard_module

    lang = validated.lang
    for row in validated.rows:
        if not row.planned or row.path is None:
            continue
        target = row.path
        if not os.path.lexists(str(target)):
            row.status = "skipped"
            row.detail = text("missing", lang)
            continue
        if measure:
            measured = measure_bytes(target)
            if measured or not row.size_bytes:
                row.size_bytes = measured
        if open_handles_fn is not None:
            handles = open_handles_fn(target)
            status = getattr(handles, "status", "ok")
            found = list(getattr(handles, "handles", handles) or [])
        else:
            result = guard_module.open_handles(target, DEFAULT_LSOF_TIMEOUT_S)
            status = result.status
            found = list(result.handles)
        row.open_check = status
        if found:
            row.status = "refused"
            row.detail = text("in_use", lang, who=_who(found))
            continue
        if status == "unknown":
            # Not a reason to stop: it is a reason to write it down.
            row.detail = text("open_unknown", lang)
    return validated


# --------------------------------------------------------------------------
# stage three: act
# --------------------------------------------------------------------------


def _recheck(row: DisposeRow, validated: ValidatedDecisions) -> Optional[str]:
    """The path rules once more, against the filesystem as it is this instant."""

    target = row.path
    if target is None:
        return text("missing", validated.lang)
    if not paths.inside_root(target, validated.home):
        return text("recheck_outside", validated.lang)
    if paths.has_symlink_component(target, validated.home):
        return text("recheck_symlink", validated.lang)
    if paths.is_forbidden(target, validated.profile):
        return text("recheck_forbidden", validated.lang)
    return None


def execute_row(
    row: DisposeRow,
    validated: ValidatedDecisions,
    *,
    dry_run: bool = False,
    trash_fn: Optional[Callable[..., None]] = None,
) -> None:
    """Act on one path.  Sets ``row.status`` and ``row.detail``; never raises."""

    lang = validated.lang
    if dry_run:
        row.status = "dry-run"
        row.detail = text("dry_run", lang)
        return

    refusal = _recheck(row, validated)
    if refusal is not None:
        row.status = "refused"
        row.detail = refusal
        return

    target = row.path
    if target is None:  # _recheck already refused this, belt and braces
        row.status = "refused"
        row.detail = text("missing", lang)
        return
    try:
        if row.action == "trash":
            sender = trash_fn if trash_fn is not None else trash_module.move_to_trash
            sender(target, backend=validated.trash_backend, lang=lang)
            row.status = "trashed"
            row.detail = text("trashed", lang)
            return
        # A permanent delete only ever reaches here through the green door with
        # the flag on; a failed trash above returns rather than falling through.
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(str(target))
        else:
            os.unlink(str(target))
        row.status = "deleted"
        row.detail = text("deleted", lang)
    except trash_module.TrashError as error:
        row.status = "failed"
        row.detail = str(error)
    except Exception as error:  # noqa: BLE001 - one bad path must not kill the batch
        row.status = "failed"
        row.detail = text("error", lang, error=error)


def _manifest_row(row: DisposeRow, *, action_at: str) -> Dict[str, Any]:
    error = row.detail if row.status in ("failed", "refused") else ""
    return {
        "action_at": action_at,
        "status": STATUS_MANIFEST.get(row.status, row.status.upper()),
        "path": row.path_portable,
        "size_kib_before": _kib(row.size_bytes),
        "reason": row.reason or row.item_id,
        "restore_method": row.restore_method,
        "error": error,
    }


def write_manifest(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    lines = ["\t".join(MANIFEST_COLUMNS)]
    for row in rows:
        lines.append(
            "\t".join(manifest_module.safe_field(row.get(column, "")) for column in MANIFEST_COLUMNS)
        )
    return manifest_module.atomic_write(Path(path), "\n".join(lines) + "\n")


def read_manifest(path: Path) -> List[Dict[str, str]]:
    target = Path(path)
    lines = target.read_text(encoding="utf-8").splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    out: List[Dict[str, str]] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split("\t")
        cells += [""] * (len(header) - len(cells))
        out.append(dict(zip(header, cells)))
    return out


def _audit_record(
    row: DisposeRow,
    *,
    run_id: str,
    manifest: str,
    trash_backend: str,
    now: datetime,
) -> Dict[str, Any]:
    return {
        "timestamp": now.isoformat(timespec="seconds"),
        "run_id": run_id,
        "line": "storage",
        "item_id": row.item_id,
        # ``kind`` is spelled the way the tidy-up audit spells it, so ``undo``
        # reading this file by mistake says "put it back from the Trash"
        # instead of tripping over a word it has never seen.
        "kind": row.action,
        "action": row.action,
        "color": row.color,
        "source": row.path_portable,
        "destination": None,
        "status": row.status,
        "detail": row.detail,
        "size_bytes": row.size_bytes,
        "open_check": row.open_check,
        "manifest": manifest,
        "trash_backend": trash_backend,
    }


def _result(row: DisposeRow) -> Dict[str, Any]:
    return {
        "item_id": row.item_id,
        "path": row.path_portable,
        "action": row.action,
        "color": row.color,
        "status": row.status,
        "detail": row.detail,
        "size_bytes": row.size_bytes,
        "open_check": row.open_check,
    }


def execute(
    validated: ValidatedDecisions,
    *,
    dry_run: bool = False,
    managed: Optional[Path] = None,
    now: Optional[datetime] = None,
    trash_fn: Optional[Callable[..., None]] = None,
    audit: Optional[Path] = None,
) -> DisposeReport:
    """Walk the validated rows once, writing the paper trail as it goes."""

    lang = validated.lang
    moment = now or datetime.now().astimezone()
    run_id = manifest_module.timestamp_text(moment)
    action_at = moment.isoformat(timespec="seconds")
    managed_path = Path(managed) if managed is not None else managed_dir(validated.home)

    report = DisposeReport(run_id=run_id, dry_run=dry_run, trash_backend=validated.trash_backend)

    if not dry_run and validated.targets and validated.trash_backend == trash_module.NONE:
        if any(row.action == "trash" for row in validated.targets):
            for row in validated.targets:
                if row.action == "trash":
                    row.status = "refused"
                    row.detail = text("no_backend", lang)

    manifest_file = manifest_path(managed_path, moment)
    manifest_text = paths.portable(manifest_file, validated.home)
    audit_file = Path(audit) if audit is not None else manifest_module.audit_path(managed_path)

    if not dry_run:
        # The manifest lands before anything moves: an interrupted run still
        # leaves a page naming every path it was about to touch.
        managed_path.mkdir(parents=True, exist_ok=True)
        write_manifest(manifest_file, [_manifest_row(r, action_at=action_at) for r in validated.rows])
        report.manifest = manifest_file

    stopped = False
    for row in validated.rows:
        if row.planned:
            if stopped:
                row.status = "skipped"
                row.detail = text("batch_stopped", lang)
            else:
                execute_row(row, validated, dry_run=dry_run, trash_fn=trash_fn)
                if row.status == "failed":
                    stopped = True
        record = _audit_record(
            row,
            run_id=run_id,
            manifest=manifest_text if not dry_run else "",
            trash_backend=validated.trash_backend,
            now=moment,
        )
        report.results.append(_result(row))
        if not dry_run:
            manifest_module.append_audit([record], audit_file)
            report.audit = audit_file

    report.stopped = stopped
    if not dry_run:
        write_manifest(manifest_file, [_manifest_row(r, action_at=action_at) for r in validated.rows])

    counts: Dict[str, int] = {"total": len(report.results)}
    for record in report.results:
        key = str(record.get("status"))
        counts[key] = counts.get(key, 0) + 1
    report.counts = counts
    return report


def apply_decisions(
    analysis: Mapping[str, Any],
    decisions: Mapping[str, Any],
    *,
    dry_run: bool = False,
    allow_permanent_delete: bool = False,
    home: Optional[Path] = None,
    managed_dir: Optional[Path] = None,  # noqa: A002 - the name callers already use
    now: Optional[datetime] = None,
    profile: Optional[Mapping[str, Any]] = None,
    trash_backend: Optional[str] = None,
    trash_fn: Optional[Callable[..., None]] = None,
    open_handles_fn: Optional[Callable[[Path], Any]] = None,
    audit: Optional[Path] = None,
) -> DisposeReport:
    """Validate, preflight and execute: the only entry the CLI and server use."""

    validated = validate_decisions(
        analysis,
        decisions,
        allow_permanent_delete=allow_permanent_delete,
        home=home,
        profile=profile,
        trash_backend=trash_backend,
    )
    preflight(validated, open_handles_fn=open_handles_fn)
    return execute(
        validated,
        dry_run=dry_run,
        managed=managed_dir,
        now=now,
        trash_fn=trash_fn,
        audit=audit,
    )


# --------------------------------------------------------------------------
# dispose subcommand
# --------------------------------------------------------------------------


def _read_json(path: Path, what: str) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise DisposeError("cannot read {0} {1}: {2}".format(what, path, error)) from error
    except ValueError as error:
        raise DisposeError("{0} {1} is not valid JSON: {2}".format(what, path, error)) from error
    if not isinstance(data, dict):
        raise DisposeError("{0} {1} must hold a JSON object".format(what, path))
    return data


def run(args: Any) -> int:
    """``dispose <analysis.json> <decisions.json> [--dry-run] [--allow-permanent-delete]``."""

    analysis = _read_json(Path(getattr(args, "analysis")), "analysis.json")
    decisions = _read_json(Path(getattr(args, "decisions")), "decisions.json")
    lang = str(analysis.get("lang") or getattr(args, "lang", None) or "en")
    if lang not in TEXT:
        lang = "en"
    dry_run = bool(getattr(args, "dry_run", False))

    report = apply_decisions(
        analysis,
        decisions,
        dry_run=dry_run,
        allow_permanent_delete=bool(getattr(args, "allow_permanent_delete", False)),
    )
    for record in report.results:
        print(
            text(
                "cli_line",
                lang,
                status=record["status"],
                path=record["path"],
                detail=record["detail"],
            )
        )
    done = sum(report.counts.get(key, 0) for key in DONE_STATUSES)
    if dry_run:
        print(text("cli_dry", lang, total=report.counts.get("total", 0)))
    else:
        print(
            text(
                "cli_done",
                lang,
                done=done,
                other=report.counts.get("total", 0) - done,
                manifest=report.manifest,
            )
        )
    failed = report.counts.get("failed", 0)
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover - the CLI owns the entry point
    sys.exit(2)
