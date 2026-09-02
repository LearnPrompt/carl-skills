"""Execution in three stages: validate the plan, preflight each action, then act.

Nothing here decides anything.  The plan already said what could happen and a
person already said which of it should happen; this module's whole job is to
refuse everything else, and to leave a trail that lets the person put it all
back.

The stages, in order:

    validate_plan        the approval file as a whole: schema, root, the id list
    preflight_action     one item, against the filesystem as it is right now
    execute_action       the actual move, trash or delete, plus verification
    apply_approved_plan  wires the three together and writes the paper trail

Two rules shape everything below.  A permanent delete needs an explicit flag
and refuses the entire batch when it is missing, because a silent skip would
let someone believe their disk got emptier.  And a move that does not verify is
put straight back where it came from, and the rest of the batch stops.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import i18n, ids
from . import manifest as manifest_module
from . import paths
from . import tags as tags_module
from . import trash as trash_module
from .guard import is_observer

#: Literal on purpose: the executor must not depend on the planner to know
#: which plan format it can run.
SCHEMA_VERSION = 2

SUPPORTED_KINDS = ("move", "trash", "delete")

#: Only these rules produce an action a person may reroute from the page.
REROUTABLE_RULES = ("unknown-ext", "dir:pending", "dir:derivative")

#: Statuses are lowercase in audit.jsonl and uppercase in the TSV manifests.
STATUS_MANIFEST = {
    "planned": "PLANNED",
    "moved": "MOVED",
    "trashed": "TRASHED",
    "deleted": "DELETED",
    "dry-run": "DRY-RUN",
    "skipped": "SKIPPED",
    "conflict": "CONFLICT",
    "refused": "REFUSED",
    "failed": "FAILED",
}

DEFAULT_LSOF_TIMEOUT_S = 3.0
DIR_ENTRY_CAP = 20000
DIR_TIME_BUDGET_S = 1.5

TEXT = {
    "source_missing": {
        "zh": "源已经不在原处，跳过",
        "en": "The source is no longer there; skipped",
    },
    "source_symlink": {
        "zh": "路径里有软链，拒绝执行",
        "en": "A symlink sits in this path; refused",
    },
    "outside_root": {
        "zh": "源或目标不在整理目录里，拒绝执行",
        "en": "Source or destination falls outside the folder; refused",
    },
    "forbidden": {
        "zh": "禁刀区，拒绝执行（{label}）",
        "en": "No-go zone; refused ({label})",
    },
    "changed": {
        "zh": "计划生成之后这一项被改动过，跳过；重新 plan 就好",
        "en": "This item changed after the plan was made; skipped, just run plan again",
    },
    "kind_changed": {
        "zh": "文件和目录的身份变了，跳过",
        "en": "It is no longer the same kind of item; skipped",
    },
    "destination_exists": {
        "zh": "目标已经有同名的东西，不覆盖，源没有动",
        "en": "The destination already exists; nothing was overwritten and the source stayed put",
    },
    "destination_missing": {
        "zh": "这条动作没有目标路径",
        "en": "This action has no destination",
    },
    "in_use": {
        "zh": "现在有进程开着它（{who}），跳过",
        "en": "A process still has it open ({who}); skipped",
    },
    "ready": {"zh": "可以执行", "en": "ready"},
    "delete_no_flag": {
        "zh": "批准名单里有永久删除，但没有加 --allow-permanent-delete，整批拒绝执行",
        "en": (
            "The approval list contains a permanent delete but --allow-permanent-delete "
            "was not given; the whole batch is refused"
        ),
    },
    "delete_not_regenerable": {
        "zh": "只允许永久删除可再生的构建产物，{name} 不在名单里",
        "en": "Permanent delete is only for regenerable build output, and {name} is not on that list",
    },
    "delete_no_survivor": {
        "zh": "重复组里没有确定保留的副本，拒绝永久删除",
        "en": "No surviving copy is confirmed in this duplicate group; refusing the permanent delete",
    },
    "delete_bad_tier": {
        "zh": "这一项不属于可永久删除的类别（{tier}）",
        "en": "This item is not in a permanently deletable class ({tier})",
    },
    "delete_cold_dir": {
        "zh": "冷存候选只允许删文件，不允许删目录",
        "en": "Cold candidates may only be deleted as files, never as folders",
    },
    "moved": {"zh": "已按批准移动", "en": "moved as approved"},
    "trashed": {"zh": "已移入废纸篓", "en": "moved to the trash"},
    "deleted": {"zh": "已永久删除", "en": "permanently deleted"},
    "dry_run": {"zh": "预演通过，没有真的动", "en": "validated; nothing was touched"},
    "verify_failed": {
        "zh": "移动之后校验不通过（{detail}），已原路移回",
        "en": "The move did not verify ({detail}); it was put back",
    },
    "verify_failed_stuck": {
        "zh": "移动之后校验不通过（{detail}），而且移回也失败了：{error}",
        "en": "The move did not verify ({detail}) and moving it back also failed: {error}",
    },
    "batch_stopped": {
        "zh": "本批在前一条失败之后停下了，这一条没有执行",
        "en": "The batch stopped after an earlier failure; this one was not attempted",
    },
    "error": {"zh": "执行出错：{error}", "en": "execution error: {error}"},
    "verify_dst_missing": {"zh": "目标不存在", "en": "destination missing"},
    "verify_src_left": {"zh": "源还在原处", "en": "source still there"},
    "verify_size": {
        "zh": "体积对不上（{before} -> {after}）",
        "en": "size mismatch ({before} -> {after})",
    },
    "verify_entries": {
        "zh": "条目数对不上（{before} -> {after}）",
        "en": "entry count mismatch ({before} -> {after})",
    },
}

REVIEW_TEXT = {
    "log_moved": {
        "zh": "本次整理共移动 {count} 项；执行清单：`{manifest}`。",
        "en": "This run moved {count} item(s); manifest: `{manifest}`.",
    },
    "log_tagged": {
        "zh": "本次移动目标已打 macOS Finder 标签 `{tag}`；标签清单：`{list}`。",
        "en": "The moved items carry the macOS Finder tag `{tag}`; tag list: `{list}`.",
    },
    "log_sensitive": {
        "zh": "已将 {count} 项疑似敏感命名的东西移入 `{dest}`，未读取内容：{names}。",
        "en": (
            "{count} item(s) with credential-looking names went to `{dest}`; "
            "their contents were never read: {names}."
        ),
    },
    "log_conflict": {
        "zh": "{names} 的目标位置已经有同名的东西，未覆盖，也未删除任一项，本次跳过。",
        "en": (
            "{names} already had something at the destination; nothing was overwritten, "
            "neither copy was deleted, and it was skipped."
        ),
    },
    "log_trashed": {
        "zh": "已将 {count} 项移入废纸篓（后端 {backend}），在废纸篓里可以放回原处。",
        "en": "{count} item(s) went to the trash (backend {backend}) and can be put back from there.",
    },
    "log_deleted": {
        "zh": "已永久删除 {count} 项可再生的构建产物：{names}。",
        "en": "Permanently deleted {count} regenerable build output(s): {names}.",
    },
    "log_skipped": {
        "zh": "{count} 项在计划生成之后被动过或已经不在，本次跳过。",
        "en": "{count} item(s) changed or vanished after the plan was made and were skipped.",
    },
    "log_failed": {
        "zh": "{count} 项执行失败并已原路移回，本批余下动作已停止。",
        "en": "{count} item(s) failed, were put back, and the rest of the batch stopped.",
    },
    "log_recheck": {
        "zh": "复查结果：dry-run actions={count}。",
        "en": "Recheck: dry-run actions={count}.",
    },
}

CLI_TEXT = {
    "cli_audit": {"zh": "审计：{path}", "en": "Audit:    {path}"},
    "cli_manifest": {"zh": "清单：{path}", "en": "Manifest: {path}"},
    "cli_tag_list": {"zh": "标签清单：{path}", "en": "Tag list: {path}"},
    "cli_review_log": {"zh": "人工日志：{path}", "en": "Log:      {path}"},
    "cli_approved_copy": {"zh": "批准文件已留档：{path}", "en": "Approval kept at: {path}"},
    "cli_dry_run": {
        "zh": "预演模式：一个字节都没有写，清单和日志也不生成。",
        "en": "Dry run: nothing was written, and no manifest or log was produced.",
    },
    "cli_summary": {
        "zh": "共 {total} 条：移动 {moved}，废纸篓 {trashed}，永久删除 {deleted}，跳过 {skipped}，失败 {failed}",
        "en": (
            "{total} action(s): moved {moved}, trashed {trashed}, deleted {deleted}, "
            "skipped {skipped}, failed {failed}"
        ),
    },
    "cli_profile_drift": {
        "zh": "提醒：计划生成之后设置改过了（profile 摘要对不上），只提醒不中断。",
        "en": "warning: settings changed after the plan was made (profile hash differs); continuing anyway.",
    },
}


class PlanError(ValueError):
    """The approval file violates the execution contract."""


class ExecutionRefused(PlanError):
    """The batch is refused as a whole, on purpose, before anything is touched."""


def text(key: str, lang: str = "en", **kw: Any) -> str:
    entry = TEXT.get(key) or REVIEW_TEXT.get(key) or CLI_TEXT.get(key) or {}
    template = entry.get(lang) or entry.get("en") or key
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError):
        return template


@dataclass
class ValidatedPlan:
    plan: Dict[str, Any]
    root: Path
    home: Path
    lang: str
    actions: List[Dict[str, Any]]
    by_id: Dict[str, Dict[str, Any]]
    overrides: Dict[str, str]
    allow_permanent_delete: bool
    trash_backend: str


@dataclass
class Preflight:
    action: Dict[str, Any]
    ok: bool
    status: str
    detail: str


@dataclass
class ApplyReport:
    run_id: str
    dry_run: bool
    results: List[Dict[str, Any]] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    manifest: Optional[Path] = None
    tag_list: Optional[Path] = None
    audit: Optional[Path] = None
    review_log: Optional[Path] = None
    approved_copy: Optional[Path] = None
    recheck_actions: Optional[int] = None
    trash_backend: str = trash_module.NONE
    stopped: bool = False

    def status_of(self, action_id: str) -> Optional[str]:
        for record in self.results:
            if record.get("action_id") == action_id:
                return str(record.get("status"))
        return None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def plan_home(plan: Dict[str, Any], home: Optional[Path] = None) -> Path:
    """Recover the home directory the plan was written against.

    The arithmetic lives in :func:`carl_file_organizer.paths.plan_home`, which the
    review page needs too; this name stays because the executor's callers know it.
    """

    return paths.plan_home(plan, home)


def _localized(value: Any, lang: str) -> str:
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("en") or next(iter(value.values()), ""))
    return "" if value is None else str(value)


def open_handles(
    path: Path, *, timeout_s: float = DEFAULT_LSOF_TIMEOUT_S
) -> List[Dict[str, str]]:
    """Processes holding ``path`` open, via ``lsof``.  No lsof means no answer.

    This is the single-path spelling used just before a file is touched; the
    plan-time batch lives in :mod:`carl_file_organizer.guard`.  Both skip the same
    indexing and preview daemons, via ``guard.is_observer``.
    """

    executable = shutil.which("lsof")
    if not executable:
        return []
    try:
        result = subprocess.run(
            [executable, "-F", "pcn", "--", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode not in (0, 1):
        return []
    handles: List[Dict[str, str]] = []
    pid = ""
    command = ""
    for line in result.stdout.splitlines():
        tag, value = line[:1], line[1:].strip()
        if tag == "p":
            pid = value
            command = ""
        elif tag == "c":
            command = value
        elif tag == "n" and pid and not is_observer(command):
            handles.append({"pid": pid, "command": command, "name": value})
    return handles


def _count_entries(
    path: Path, *, cap: int = DIR_ENTRY_CAP, budget_s: float = DIR_TIME_BUDGET_S
) -> Tuple[int, bool]:
    """Bounded recursive entry count; the flag says the count hit a limit."""

    deadline = time.monotonic() + budget_s
    total = 0
    stack = [Path(path)]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(str(current)))
        except OSError:
            continue
        for entry in entries:
            total += 1
            if total >= cap or time.monotonic() > deadline:
                return total, True
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
            except OSError:
                continue
    return total, False


def _shape(path: Path) -> Dict[str, Any]:
    """The facts a move has to preserve, captured just before it happens."""

    target = Path(path)
    if target.is_dir() and not target.is_symlink():
        count, truncated = _count_entries(target)
        return {"kind": "dir", "entries": count, "truncated": truncated}
    try:
        size = target.stat().st_size
    except OSError:
        size = -1
    return {"kind": "file", "size": size}


def verify_move(src: Path, dst: Path, before: Dict[str, Any]) -> Tuple[bool, str]:
    """Did the move actually land?  Returns ``(ok, detail)`` and never raises."""

    source = Path(src)
    destination = Path(dst)
    if not os.path.lexists(str(destination)):
        return False, text("verify_dst_missing", "en")
    if os.path.lexists(str(source)):
        return False, text("verify_src_left", "en")

    if before.get("kind") == "dir":
        after, after_truncated = _count_entries(destination)
        if before.get("truncated") and after_truncated:
            return True, ""
        if after != before.get("entries"):
            return (
                False,
                text("verify_entries", "en", before=before.get("entries"), after=after),
            )
        return True, ""

    try:
        after_size = destination.stat().st_size
    except OSError as error:
        return False, str(error)
    if int(before.get("size", -1)) >= 0 and after_size != before["size"]:
        return False, text("verify_size", "en", before=before["size"], after=after_size)
    return True, ""


# --------------------------------------------------------------------------
# stage one: the approval file as a whole
# --------------------------------------------------------------------------


def validate_plan(
    plan: Dict[str, Any],
    *,
    allow_permanent_delete: bool,
    home: Optional[Path] = None,
) -> ValidatedPlan:
    """Check the approval file before a single byte moves.

    The order is part of the contract: schema, root, unknown ids, one action per
    subject, unapprovable ids, tampering, reroutes, and finally the permanent
    delete gate, which refuses the whole batch instead of skipping quietly.
    """

    if not isinstance(plan, dict):
        raise PlanError("the approval file must contain a JSON object")
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise PlanError(
            "unsupported schema_version {0!r}: this build only runs version {1}".format(
                plan.get("schema_version"), SCHEMA_VERSION
            )
        )

    # An approval exported from the review page carries only ``$HOME`` forms,
    # because the page is shareable and absolute paths name the user.  Expanding
    # them here means every check below, and the whole preflight, keeps working
    # on real paths without knowing where the file came from.
    home_dir = plan_home(plan, home)
    plan = paths.hydrate_absolute(plan, home_dir)

    root_text = str(plan.get("source_root") or "")
    if not root_text:
        raise PlanError("the plan has no source_root")
    root = Path(root_text).expanduser()
    if root.is_symlink():
        raise PlanError("the planned folder is a symlink: {0}".format(root))
    if not root.is_dir():
        raise PlanError("the planned folder is unavailable: {0}".format(root))

    actions = plan.get("actions")
    if not isinstance(actions, list):
        raise PlanError("actions must be a list")
    approved = plan.get("approved_action_ids")
    if not isinstance(approved, list):
        raise PlanError("approved_action_ids must be a list")

    by_id: Dict[str, Dict[str, Any]] = {}
    for action in actions:
        if not isinstance(action, dict) or not action.get("id"):
            raise PlanError("every action needs an id")
        by_id[str(action["id"])] = action

    approved_ids: List[str] = []
    seen: Set[str] = set()
    for entry in approved:
        key = str(entry)
        if key in seen:
            continue
        seen.add(key)
        approved_ids.append(key)

    unknown = [key for key in approved_ids if key not in by_id]
    if unknown:
        raise PlanError("approval contains unknown action ids: {0}".format(sorted(unknown)))

    lang = str(plan.get("lang") or "en")

    chosen: List[Dict[str, Any]] = []
    subjects: Dict[str, str] = {}
    for key in approved_ids:
        action = by_id[key]
        subject = str(action.get("subject_id") or "")
        if subject and subject in subjects:
            raise PlanError(
                "two approved actions target the same item: {0} and {1}".format(
                    subjects[subject], key
                )
            )
        subjects[subject] = key
        chosen.append(action)

    for action in chosen:
        if not action.get("approvable", False):
            raise PlanError(
                "action {0} is not approvable ({1})".format(
                    action.get("id"), action.get("rule")
                )
            )
        kind = str(action.get("kind") or "")
        if kind not in SUPPORTED_KINDS:
            raise PlanError(
                "unsupported action kind {0!r} for {1}".format(kind, action.get("id"))
            )
        _check_not_tampered(action, root, home_dir)

    working = [copy.deepcopy(action) for action in chosen]
    working_by_id = {str(action["id"]): action for action in working}
    overrides = _apply_overrides(plan, by_id, working_by_id, root, home_dir)

    if not allow_permanent_delete:
        for action in working:
            if action.get("kind") == "delete":
                raise ExecutionRefused(text("delete_no_flag", lang))

    capabilities = plan.get("capabilities") or {}
    backend = str(capabilities.get("trash_backend") or trash_module.NONE)

    return ValidatedPlan(
        plan=plan,
        root=paths.realpath(root),
        home=home_dir,
        lang=lang,
        actions=working,
        by_id=by_id,
        overrides=overrides,
        allow_permanent_delete=allow_permanent_delete,
        trash_backend=backend,
    )


def _check_not_tampered(action: Dict[str, Any], root: Path, home: Path) -> None:
    """Recompute the action id from the very fields it was derived from."""

    destination = action.get("destination")
    portable = paths.portable(Path(str(destination)), home) if destination else None
    expected = ids.action_id(
        str(action.get("subject_id") or ""), str(action.get("kind") or ""), portable
    )
    if expected != str(action.get("id")):
        raise PlanError(
            "action {0} was altered after the plan was written".format(action.get("id"))
        )
    if destination is not None and not paths.inside_root(Path(str(destination)).parent, root):
        raise PlanError(
            "action {0} points outside the folder being organized".format(action.get("id"))
        )


def _apply_overrides(
    plan: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
    working_by_id: Dict[str, Dict[str, Any]],
    root: Path,
    home: Path,
) -> Dict[str, str]:
    """Reroute pending items, and only through the plan's own names table."""

    raw = plan.get("overrides") or []
    if not isinstance(raw, list):
        raise PlanError("overrides must be a list")
    names = plan.get("names") or {}
    if not isinstance(names, dict):
        raise PlanError("names must be an object")

    resolved: Dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise PlanError("every override must be an object")
        action_key = str(entry.get("action_id") or "")
        key = str(entry.get("destination_key") or "")
        if action_key not in by_id:
            raise PlanError("override names an unknown action: {0}".format(action_key))
        original = by_id[action_key]
        if original.get("kind") != "move" or not original.get("reroutable", False):
            raise PlanError("action {0} cannot be rerouted".format(action_key))
        if str(original.get("rule") or "") not in REROUTABLE_RULES:
            raise PlanError(
                "action {0} has rule {1!r}, which is not reroutable".format(
                    action_key, original.get("rule")
                )
            )
        if key not in names:
            raise PlanError(
                "override destination_key {0!r} is not in the plan's names table".format(key)
            )
        filename = str(original.get("filename") or Path(str(original.get("source"))).name)
        destination = Path(root) / str(names[key]) / filename
        if not paths.inside_root(destination.parent, root):
            raise PlanError("override for {0} escapes the folder".format(action_key))
        resolved[action_key] = key
        target = working_by_id.get(action_key)
        if target is not None:
            target["destination"] = str(destination)
            target["destination_portable"] = paths.portable(destination, home)
            target["destination_key"] = key
            target["rerouted"] = True
    return resolved


# --------------------------------------------------------------------------
# stage two: one item, against the filesystem as it is right now
# --------------------------------------------------------------------------


def preflight_action(
    action: Dict[str, Any],
    root: Path,
    config: Any,
    *,
    lang: str = "en",
    open_handles_fn: Optional[Callable[[Path], Sequence[Any]]] = None,
    duplicate_survivors: Optional[Iterable[str]] = None,
    allow_permanent_delete: bool = True,
) -> Preflight:
    """Everything that must still be true a moment before acting."""

    source = Path(str(action.get("source") or ""))
    kind = str(action.get("kind") or "")

    if not os.path.lexists(str(source)):
        return Preflight(action, False, "skipped", text("source_missing", lang))
    if source.is_symlink() or paths.has_symlink_component(source, Path(root)):
        return Preflight(action, False, "refused", text("source_symlink", lang))
    if not paths.inside_root(source, Path(root)):
        return Preflight(action, False, "refused", text("outside_root", lang))

    label = paths.is_forbidden(source, config)
    if label:
        return Preflight(action, False, "refused", text("forbidden", lang, label=label))

    changed = _subject_changed(action, source, lang)
    if changed is not None:
        return Preflight(action, False, "skipped", changed)

    if kind == "move":
        destination_text = action.get("destination")
        if not destination_text:
            return Preflight(action, False, "refused", text("destination_missing", lang))
        destination = Path(str(destination_text))
        if not paths.inside_root(destination.parent, Path(root)):
            return Preflight(action, False, "refused", text("outside_root", lang))
        if paths.has_symlink_component(destination.parent, Path(root)):
            return Preflight(action, False, "refused", text("source_symlink", lang))
        if os.path.lexists(str(destination)):
            return Preflight(action, False, "conflict", text("destination_exists", lang))

    if kind == "delete":
        refusal = _delete_gate(
            action,
            source,
            config,
            lang=lang,
            duplicate_survivors=duplicate_survivors,
            allow_permanent_delete=allow_permanent_delete,
        )
        if refusal is not None:
            return Preflight(action, False, "refused", refusal)

    handler = open_handles_fn if open_handles_fn is not None else open_handles
    try:
        handles = list(handler(source) or [])
    except Exception:  # noqa: BLE001 - a guard that crashes must not block the batch
        handles = []
    if handles:
        who = ", ".join(
            "{0}({1})".format(item.get("command") or item.get("name", "?"), item.get("pid", "?"))
            if isinstance(item, dict)
            else str(item)
            for item in handles[:3]
        )
        return Preflight(action, False, "skipped", text("in_use", lang, who=who))

    return Preflight(action, True, "ready", text("ready", lang))


def _subject_changed(action: Dict[str, Any], source: Path, lang: str = "en") -> Optional[str]:
    """``None`` when the item is still exactly what the plan looked at."""

    try:
        stat = source.stat()
    except OSError:
        return text("source_missing", lang)

    live_kind = "dir" if source.is_dir() else "file"
    recorded_kind = str(action.get("subject_kind") or live_kind)
    if live_kind != recorded_kind:
        return text("kind_changed", lang)

    recorded = str(action.get("subject_id") or "")
    if not recorded:
        return None

    live = ids.subject_id(source, live_kind, stat.st_size, stat.st_mtime_ns)
    if live == recorded:
        return None

    # Directory sizes are computed with a cap, so a planner may well have
    # recorded a walked size rather than the inode size.  Modification time is
    # the real guard for a directory, so that second spelling is allowed, and
    # only that one.
    if live_kind == "dir":
        try:
            recorded_size = int(action.get("size_bytes") or 0)
        except (TypeError, ValueError):
            recorded_size = 0
        alternate = ids.subject_id(source, live_kind, recorded_size, stat.st_mtime_ns)
        if alternate == recorded:
            return None

    return text("changed", lang)


def _delete_gate(
    action: Dict[str, Any],
    source: Path,
    config: Any,
    *,
    lang: str,
    duplicate_survivors: Optional[Iterable[str]],
    allow_permanent_delete: bool,
) -> Optional[str]:
    """The second door in front of a permanent delete.  ``None`` means open."""

    if not allow_permanent_delete:
        return text("delete_no_flag", lang)

    tier = str(action.get("tier") or "")
    profile = getattr(config, "profile", {}) or {}
    regenerable = (profile.get("regenerable") or {}).get("basenames") or []

    if tier == "regenerable":
        if source.name not in regenerable:
            return text("delete_not_regenerable", lang, name=source.name)
        return None

    if tier == "duplicate":
        survivors = set(str(item) for item in (duplicate_survivors or []))
        subject = str(action.get("subject_id") or "")
        if not (survivors - {subject}):
            return text("delete_no_survivor", lang)
        return None

    if tier == "cold":
        if source.is_dir():
            return text("delete_cold_dir", lang)
        return None

    return text("delete_bad_tier", lang, tier=tier or "unknown")


# --------------------------------------------------------------------------
# stage three: act
# --------------------------------------------------------------------------


def execute_action(
    action: Dict[str, Any],
    *,
    dry_run: bool = False,
    trash_backend: str = trash_module.NONE,
    home: Optional[Path] = None,
    root: Optional[Path] = None,
    config: Any = None,
    lang: str = "en",
    trash_fn: Optional[Callable[..., None]] = None,
) -> Tuple[str, str]:
    """Perform one approved action.  Returns ``(status, detail)`` and never raises."""

    kind = str(action.get("kind") or "")
    source = Path(str(action.get("source") or ""))

    if dry_run:
        return "dry-run", text("dry_run", lang)

    try:
        if kind == "move":
            destination = Path(str(action.get("destination")))
            if os.path.lexists(str(destination)):
                return "conflict", text("destination_exists", lang)
            destination.parent.mkdir(parents=True, exist_ok=True)
            before = _shape(source)
            shutil.move(str(source), str(destination))
            ok, detail = verify_move(source, destination, before)
            if ok:
                return "moved", text("moved", lang)
            try:
                if os.path.lexists(str(destination)) and not os.path.lexists(str(source)):
                    shutil.move(str(destination), str(source))
            except (OSError, shutil.Error) as error:
                return "failed", text(
                    "verify_failed_stuck", lang, detail=detail, error=error
                )
            return "failed", text("verify_failed", lang, detail=detail)

        if kind == "trash":
            sender = trash_fn if trash_fn is not None else trash_module.move_to_trash
            sender(source, backend=trash_backend, lang=lang)
            return "trashed", text("trashed", lang)

        if kind == "delete":
            if source.is_dir() and not source.is_symlink():
                if root is not None and paths.has_symlink_component(source, Path(root)):
                    return "refused", text("source_symlink", lang)
                if config is not None and paths.is_forbidden(source, config):
                    return "refused", text("forbidden", lang, label="recheck")
                shutil.rmtree(str(source))
            else:
                os.unlink(str(source))
            return "deleted", text("deleted", lang)

    except trash_module.TrashError as error:
        return "failed", str(error)
    except Exception as error:  # noqa: BLE001 - one bad item must not kill the batch
        return "failed", text("error", lang, error=error)

    return "refused", text("delete_bad_tier", lang, tier=kind)


# --------------------------------------------------------------------------
# the whole run
# --------------------------------------------------------------------------


def _audit_record(
    action: Dict[str, Any],
    *,
    status: str,
    detail: str,
    run_id: str,
    home: Path,
    manifest: str,
    trash_backend: str,
    tagged: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    destination = action.get("destination")
    return {
        "timestamp": (now or datetime.now().astimezone()).isoformat(timespec="seconds"),
        "run_id": run_id,
        "action_id": action.get("id"),
        "subject_id": action.get("subject_id"),
        "kind": action.get("kind"),
        "source": paths.portable(Path(str(action.get("source"))), home),
        "destination": paths.portable(Path(str(destination)), home) if destination else None,
        "status": status,
        "detail": detail,
        "size_bytes": action.get("size_bytes", 0),
        "manifest": manifest,
        "tagged": tagged,
        "trash_backend": trash_backend,
    }


def _restore_method(action: Dict[str, Any], lang: str, home: Path) -> str:
    kind = str(action.get("kind") or "")
    if kind == "move" and action.get("destination"):
        destination = paths.portable(Path(str(action["destination"])), home)
        parent = paths.portable(Path(str(action["source"])).parent, home)
        return 'mv "{0}" "{1}/"'.format(destination, parent)
    if kind == "trash":
        return i18n.reason("restore_trash", lang)
    if kind == "delete":
        return i18n.reason("restore_delete", lang)
    return ""


def _manifest_row(
    action: Dict[str, Any], status: str, *, moved_at: str, home: Path, lang: str
) -> Dict[str, Any]:
    destination = action.get("destination")
    return {
        "moved_at": moved_at,
        "status": STATUS_MANIFEST.get(status, status.upper()),
        "original_path": paths.portable(Path(str(action.get("source"))), home),
        "target_path": paths.portable(Path(str(destination)), home) if destination else "",
        "size_bytes": action.get("size_bytes", 0),
        "reason": _localized(action.get("reason"), lang),
        "restore_method": _restore_method(action, lang, home),
        "kind": action.get("kind"),
        "action_id": action.get("id"),
    }


def _tag_moved(destination: Path, transient: str) -> bool:
    """Put the temporary tag on a moved item; a failure is a warning, not a stop."""

    try:
        if tags_module.add_tag(destination, transient):
            return True
        # Already carrying the tag from an earlier run counts as tagged, so the
        # path still reaches the tag list that clear-tags reads.
        return transient in tags_module.user_tags(destination, ())
    except Exception as error:  # noqa: BLE001 - tagging never stops a run
        print("tag_warning: {0}\t{1}".format(destination, error), file=sys.stderr)
        return False


def _series_for(actions: Sequence[Dict[str, Any]]) -> str:
    kinds = {str(action.get("kind")) for action in actions}
    if kinds and kinds <= {"trash", "delete"}:
        return "removals"
    if any(str(action.get("rule")) == "conflict" for action in actions):
        return "conflict-moves"
    return "moves"


def _survivors(validated: ValidatedPlan) -> Dict[str, Set[str]]:
    """Per group, the subjects that are kept rather than trashed or deleted."""

    members: Dict[str, Set[str]] = {}
    disposed: Dict[str, Set[str]] = {}
    for group in validated.plan.get("groups") or []:
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("group_id") or "")
        members[group_id] = {str(item) for item in (group.get("members") or [])}
        disposed.setdefault(group_id, set())
    for action in validated.actions:
        group_id = str(action.get("group_id") or "")
        if not group_id:
            continue
        if action.get("kind") in ("trash", "delete"):
            disposed.setdefault(group_id, set()).add(str(action.get("subject_id")))
    return {
        group_id: (members.get(group_id, set()) - gone)
        for group_id, gone in disposed.items()
    }


def _review_bullets(
    report: ApplyReport,
    validated: ValidatedPlan,
    *,
    lang: str,
    transient: str,
    home: Path,
) -> List[str]:
    """The sentences a person reads a week later to remember what happened."""

    def names(records: Sequence[Dict[str, Any]], limit: int = 6) -> str:
        shown = [Path(str(item.get("source"))).name for item in records[:limit]]
        joined = "、".join(shown) if lang == "zh" else ", ".join(shown)
        if len(records) > len(shown):
            joined += "…" if lang == "zh" else ", ..."
        return joined

    by_status: Dict[str, List[Dict[str, Any]]] = {}
    for record in report.results:
        by_status.setdefault(str(record.get("status")), []).append(record)

    bullets: List[str] = []
    moved = by_status.get("moved", [])
    if moved:
        bullets.append(
            text(
                "log_moved",
                lang,
                count=len(moved),
                manifest=paths.portable(report.manifest, home) if report.manifest else "",
            )
        )
        if report.tag_list is not None:
            bullets.append(
                text(
                    "log_tagged",
                    lang,
                    tag=transient,
                    list=paths.portable(report.tag_list, home),
                )
            )

    sensitive = [
        record
        for record in moved
        if str(validated.by_id.get(str(record.get("action_id")), {}).get("tier")) == "sensitive"
    ]
    if sensitive:
        destination = Path(str(sensitive[0].get("destination") or "")).parent
        bullets.append(
            text(
                "log_sensitive",
                lang,
                count=len(sensitive),
                dest=str(destination),
                names=names(sensitive),
            )
        )

    conflicts = by_status.get("conflict", [])
    if conflicts:
        bullets.append(text("log_conflict", lang, names=names(conflicts)))

    trashed = by_status.get("trashed", [])
    if trashed:
        bullets.append(
            text("log_trashed", lang, count=len(trashed), backend=report.trash_backend)
        )

    deleted = by_status.get("deleted", [])
    if deleted:
        bullets.append(text("log_deleted", lang, count=len(deleted), names=names(deleted)))

    skipped = by_status.get("skipped", []) + by_status.get("refused", [])
    if skipped:
        bullets.append(text("log_skipped", lang, count=len(skipped)))

    failed = by_status.get("failed", [])
    if failed:
        bullets.append(text("log_failed", lang, count=len(failed)))

    if report.recheck_actions is not None:
        bullets.append(text("log_recheck", lang, count=report.recheck_actions))

    return bullets


def apply_approved_plan(
    plan: Dict[str, Any],
    *,
    dry_run: bool = False,
    allow_permanent_delete: bool = False,
    now: Optional[datetime] = None,
    recheck_fn: Optional[Callable[[], int]] = None,
    continue_on_error: bool = False,
    home: Optional[Path] = None,
    config: Any = None,
    audit: Optional[Path] = None,
    open_handles_fn: Optional[Callable[[Path], Sequence[Any]]] = None,
    trash_fn: Optional[Callable[..., None]] = None,
) -> ApplyReport:
    """Run every approved action, in order, and write the paper trail.

    The order is deliberate.  The manifest lands before anything moves, so an
    interrupted run still leaves a page saying what was about to happen and how
    to put it back.  Each action appends its own audit line the moment it
    finishes, which is what makes the audit the authority when the manifest is
    stale.  Tagging, the recheck and the human log all wait until the last file
    has settled.
    """

    from . import config as config_module

    validated = validate_plan(
        plan, allow_permanent_delete=allow_permanent_delete, home=home
    )
    lang = validated.lang
    root = validated.root
    home_dir = validated.home

    if config is None:
        config = config_module.resolve_config(root, lang=lang)

    moment = now or datetime.now().astimezone()
    run_id = manifest_module.timestamp_text(moment)
    moved_at = moment.isoformat(timespec="seconds")

    managed = config_module.managed_dir(config)
    audit_file = Path(audit) if audit is not None else manifest_module.audit_path(managed)

    report = ApplyReport(
        run_id=run_id, dry_run=dry_run, trash_backend=validated.trash_backend
    )
    if not validated.actions:
        report.counts = {"total": 0}
        return report

    manifest_file = manifest_module.manifest_path(
        managed, root.name, _series_for(validated.actions), moment
    )
    manifest_text = paths.portable(manifest_file, home_dir)

    survivors = _survivors(validated)
    checks: Dict[str, Preflight] = {}
    for action in validated.actions:
        group_id = str(action.get("group_id") or "")
        checks[str(action["id"])] = preflight_action(
            action,
            root,
            config,
            lang=lang,
            open_handles_fn=open_handles_fn,
            duplicate_survivors=survivors.get(group_id),
            allow_permanent_delete=allow_permanent_delete,
        )

    statuses: Dict[str, str] = {}
    for action in validated.actions:
        check = checks[str(action["id"])]
        statuses[str(action["id"])] = "planned" if check.ok else check.status

    def rows() -> List[Dict[str, Any]]:
        return [
            _manifest_row(
                action,
                statuses[str(action["id"])],
                moved_at=moved_at,
                home=home_dir,
                lang=lang,
            )
            for action in validated.actions
        ]

    if not dry_run:
        managed.mkdir(parents=True, exist_ok=True)
        manifest_module.write_manifest(manifest_file, rows())
        report.manifest = manifest_file

    transient = config_module.transient_tag(config)
    can_tag = (not dry_run) and tags_module.supported()

    stopped = False
    tagged_paths: List[str] = []
    for action in validated.actions:
        key = str(action["id"])
        check = checks[key]
        if not check.ok:
            status, detail = check.status, check.detail
        elif stopped:
            status, detail = "skipped", text("batch_stopped", lang)
        else:
            status, detail = execute_action(
                action,
                dry_run=dry_run,
                trash_backend=validated.trash_backend,
                home=home_dir,
                root=root,
                config=config,
                lang=lang,
                trash_fn=trash_fn,
            )
            if status == "failed" and not continue_on_error:
                stopped = True
        statuses[key] = status

        # Tag the moved item before its audit line is written, so the line can
        # tell the truth about whether the tag landed.
        tagged = False
        if status == "moved" and can_tag and action.get("destination"):
            destination = Path(str(action["destination"]))
            tagged = _tag_moved(destination, transient)
            if tagged:
                tagged_paths.append(paths.portable(destination, home_dir))

        record = _audit_record(
            action,
            status=status,
            detail=detail,
            run_id=run_id,
            home=home_dir,
            manifest=manifest_text if not dry_run else "",
            trash_backend=validated.trash_backend,
            tagged=tagged,
            now=moment,
        )
        report.results.append(record)
        if not dry_run:
            manifest_module.append_audit([record], audit_file)
            report.audit = audit_file

    report.stopped = stopped

    if not dry_run:
        manifest_module.write_manifest(manifest_file, rows())

    if tagged_paths:
        tag_file = manifest_module.tag_list_path(managed, root.name, moment)
        manifest_module.write_tag_list(tag_file, tagged_paths)
        report.tag_list = tag_file

    if recheck_fn is not None:
        try:
            report.recheck_actions = int(recheck_fn())
        except Exception as error:  # noqa: BLE001 - a recheck must not undo a good run
            print("recheck_warning: {0}".format(error), file=sys.stderr)

    counts: Dict[str, int] = {"total": len(report.results)}
    for record in report.results:
        status = str(record.get("status"))
        counts[status] = counts.get(status, 0) + 1
    report.counts = counts

    if not dry_run:
        bullets = _review_bullets(
            report, validated, lang=lang, transient=transient, home=home_dir
        )
        if bullets:
            report.review_log = manifest_module.append_review_log(
                managed,
                lang,
                moment.date(),
                bullets,
                name=config_module.review_log_name(config),
            )

    return report


# --------------------------------------------------------------------------
# apply subcommand
# --------------------------------------------------------------------------


def _recheck_with_planner(
    root: Path, config: Any, moment: datetime
) -> Optional[Callable[[], int]]:
    """A real recheck when the planner is available, and nothing when it is not."""

    try:
        from . import planner as planner_module
    except ImportError:
        return None
    build = getattr(planner_module, "build_plan", None)
    if build is None:
        return None

    def recheck() -> int:
        import inspect

        options: Dict[str, Any] = {}
        try:
            parameters = inspect.signature(build).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "config" in parameters:
            options["config"] = config
        if "now" in parameters:
            options["now"] = moment
        if "dir_sizes" in parameters:
            options["dir_sizes"] = False
        fresh = build(root, **options)
        actions = fresh.get("actions") or []
        return len([item for item in actions if item.get("approvable", True)])

    return recheck


def run(args: Any) -> int:
    """``carl-file-organizer apply <approved.json> [--dry-run] [--allow-permanent-delete]``."""

    from . import config as config_module

    approval_path = Path(args.approval).expanduser()
    plan = paths.hydrate_absolute(json.loads(approval_path.read_text(encoding="utf-8")))
    if not isinstance(plan, dict):
        raise PlanError("the approval file must contain a JSON object")

    root = Path(str(plan.get("source_root") or "")).expanduser()
    profile_name = (plan.get("profile") or {}).get("name")
    config = config_module.resolve_config(root, lang=plan.get("lang"), profile=profile_name)
    lang = config.lang

    recorded_hash = (plan.get("profile") or {}).get("hash")
    if recorded_hash and recorded_hash != getattr(config, "profile_hash", ""):
        print(text("cli_profile_drift", lang), file=sys.stderr)

    moment = datetime.now().astimezone()
    report = apply_approved_plan(
        plan,
        dry_run=bool(args.dry_run),
        allow_permanent_delete=bool(args.allow_permanent_delete),
        now=moment,
        recheck_fn=None
        if args.dry_run
        else _recheck_with_planner(config.root, config, moment),
        config=config,
        audit=Path(args.audit).expanduser() if getattr(args, "audit", None) else None,
    )

    for record in report.results:
        print(
            "{0}\t{1}\t{2}".format(
                record.get("status"), record.get("source"), record.get("detail")
            )
        )

    print(
        text(
            "cli_summary",
            lang,
            total=report.counts.get("total", 0),
            moved=report.counts.get("moved", 0),
            trashed=report.counts.get("trashed", 0),
            deleted=report.counts.get("deleted", 0),
            skipped=report.counts.get("skipped", 0) + report.counts.get("refused", 0),
            failed=report.counts.get("failed", 0),
        )
    )

    if report.dry_run:
        print(text("cli_dry_run", lang))
    else:
        if report.manifest:
            print(text("cli_manifest", lang, path=report.manifest))
        if report.tag_list:
            print(text("cli_tag_list", lang, path=report.tag_list))
        if report.audit:
            print(text("cli_audit", lang, path=report.audit))
        if report.review_log:
            print(text("cli_review_log", lang, path=report.review_log))
        copy_target = _keep_approval(approval_path, config, report.run_id)
        if copy_target is not None:
            report.approved_copy = copy_target
            print(text("cli_approved_copy", lang, path=copy_target))

    return 2 if (report.counts.get("failed", 0) or report.counts.get("refused", 0)) else 0


def _keep_approval(approval: Path, config: Any, run_id: str) -> Optional[Path]:
    """Tuck the approval file into the managed folder so it stops being clutter."""

    from . import config as config_module

    try:
        managed = config_module.managed_dir(config)
        managed.mkdir(parents=True, exist_ok=True)
        target = managed / "approved-{0}.json".format(run_id)
        if paths.realpath(approval) == paths.realpath(target):
            return target
        shutil.copy2(str(approval), str(target))
        return target
    except OSError as error:
        print("keep_approval_warning: {0}".format(error), file=sys.stderr)
        return None


#: The audit writer lives in manifest.py now; this keeps the old import working.
append_audit = manifest_module.append_audit
