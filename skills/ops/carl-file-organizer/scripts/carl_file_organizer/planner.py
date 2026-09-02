"""The decision chain: scan, classify, group, guard, and write plan.json v2.

Nothing in this module touches the filesystem beyond reading.  It produces a
list of candidate actions and a list of grouped choices, and every one of them
starts out unapproved.  The order of the chain is the whole design:

    pinned            you already put it back once, so it stays
    no-go zone        shown, never touched
    guard             a process, a launch agent or a symlink still needs it
    sensitive naming  isolated without ever opening the file
    your Finder tags  optional, off by default
    your name rules   from the settings file
    archive pairing   a .zip and its extracted folder move together
    top level folders whole, keeping their name
    extension rules   plus the settling period
    unknown extension waits in Pending and can be rerouted
    cold candidates   large items and used-up installers get a disposal option

Afterwards, duplicate and regenerable groups add their disposal options, and any
move whose destination already exists is redirected to a Duplicates Review
folder rather than overwriting anything.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import __version__
from . import classifier
from . import config as config_module
from . import grouping, guard, i18n, paths, trash
from .ids import action_id as _action_id
from .scanner import Entry, scan_top_level, split_suffix, user_tags

SCHEMA_VERSION = 2

DEFAULT_LARGE_BYTES = 500 * 1024 * 1024
DEFAULT_TARGET_PERCENT = 90.0

CONFIDENCE = {
    "ext": 0.98,
    "sensitive": 0.9,
    "name": 0.9,
    "tag": 0.85,
    "pair": 0.8,
    "dir": 0.6,
    "unknown": 0.55,
    "dup_sha256": 0.95,
    "dup_name": 0.7,
    "regenerable": 0.99,
    "cold": 0.5,
    "hold": 1.0,
}

# ---------------------------------------------------------------------------
# the three colours
# ---------------------------------------------------------------------------

GREEN = "green"
YELLOW = "yellow"
RED = "red"

#: Written into ``action.color``, ``group.color`` and ``mess.color``.
COLORS = (GREEN, YELLOW, RED)

#: Folder mess thresholds.  ``references/tiers.md`` is the prose version of this
#: table, and an agent may override the resulting colour through notes.json;
#: it may never override an action's colour, because the buttons follow that.
MESS_THRESHOLDS = {
    GREEN: {"loose": 3, "pending": 0},
    YELLOW: {"loose": 15, "pending": 5},
}

#: Weights behind ``mess.score``: how much of each thing counts as "full".  The
#: score only sets the length of a bar; the colour comes from the thresholds
#: above, and neither is derived from the other.
MESS_WEIGHTS = {
    "loose": 15.0,
    "pending": 5.0,
    "aging": 20.0,
    "groups": 12.0,
    "top_dirs": 20.0,
}

#: Top level folders below this count do not add to the score at all.
MESS_TOP_DIRS_FREE = 5


def action_color(action: Mapping[str, Any]) -> str:
    """Green go ahead, yellow look first, red leave it alone.

    The buttons on the review page follow this one field, so it is derived from
    the decision rather than written by hand: every hold is red; a move is green
    unless it is one of the reroutable ones still waiting on a human; a disposal
    is green only when the thing disposed of can be rebuilt from source.
    """

    if action.get("kind") == "hold":
        return RED
    if action.get("kind") == "move":
        return YELLOW if action.get("reroutable") else GREEN
    return GREEN if action.get("tier") == "regenerable" else YELLOW


def mess_counts(
    entries: Sequence[Any], actions: Sequence[Mapping[str, Any]], groups: Sequence[Any]
) -> Dict[str, int]:
    """The five numbers the folder colour is decided on."""

    return {
        "loose": len(entries),
        "aging": sum(
            1 for a in actions if a.get("kind") == "hold" and a.get("tier") == "aging"
        ),
        "pending": len({a["subject_id"] for a in actions if a.get("reroutable")}),
        "groups": len(groups),
        "top_dirs": sum(1 for entry in entries if getattr(entry, "is_dir", False)),
    }


def mess_score(counts: Mapping[str, int]) -> int:
    """0 to 100, bigger is messier.  Only a bar length, never a verdict.

    Two properties matter and a plain weighted sum has neither.  The bar must
    never sit at 100 on a folder that is merely untidy, or the one folder that
    really is a landslide has nowhere left to go; and it must keep moving, so
    that clearing thirty files out of two hundred visibly does something.  So
    the pressure is fed through ``p / (p + 1)``, which saturates instead of
    clipping: it approaches 100 and never arrives.

    ``loose`` and ``pending`` are combined with max rather than added, because
    they measure the same folder two ways and adding them counts one pile twice.
    """

    load = max(
        counts.get("loose", 0) / MESS_WEIGHTS["loose"],
        counts.get("pending", 0) / MESS_WEIGHTS["pending"],
    )
    extra = (
        counts.get("aging", 0) / MESS_WEIGHTS["aging"]
        + counts.get("groups", 0) / MESS_WEIGHTS["groups"]
        + max(0, counts.get("top_dirs", 0) - MESS_TOP_DIRS_FREE) / MESS_WEIGHTS["top_dirs"]
    )
    pressure = load + extra
    return int(round(100 * pressure / (pressure + 1)))


def mess_color(counts: Mapping[str, int]) -> str:
    """Green, yellow or red for the folder as a whole."""

    loose = counts.get("loose", 0)
    pending = counts.get("pending", 0)
    if loose <= MESS_THRESHOLDS[GREEN]["loose"] and pending <= MESS_THRESHOLDS[GREEN]["pending"]:
        return GREEN
    if loose <= MESS_THRESHOLDS[YELLOW]["loose"] or pending <= MESS_THRESHOLDS[YELLOW]["pending"]:
        return YELLOW
    return RED


def build_mess(
    entries: Sequence[Any], actions: Sequence[Mapping[str, Any]], groups: Sequence[Any]
) -> Dict[str, Any]:
    """The ``mess`` block: how bad this folder is, and the one line that says why."""

    counts = mess_counts(entries, actions, groups)
    colour = mess_color(counts)
    return {
        "score": mess_score(counts),
        "color": colour,
        "color_source": "rule",
        "counts": counts,
        "reason": i18n.both("mess_" + colour, **counts),
    }


def color_totals(actions: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, int]]:
    """``summary.by_color``: how many actions wear each colour, and how big they are.

    Counted per action, not per subject, exactly like ``by_tier`` and ``by_kind``:
    one file can hold a green move and a yellow disposal at the same time, so the
    bytes column adds up to more than the folder holds.  It is a shape, not a total.
    """

    totals = {colour: {"actions": 0, "bytes": 0} for colour in COLORS}
    for action in actions:
        slot = totals.get(str(action.get("color")))
        if slot is None:
            continue
        slot["actions"] += 1
        slot["bytes"] += int(action.get("size_bytes") or 0)
    return totals


@dataclass
class PlanPaths:
    managed: Path
    plan: Path
    report: Path


def plan_paths(config: Any) -> PlanPaths:
    managed = config_module.managed_dir(config)
    return PlanPaths(managed=managed, plan=managed / "plan.json", report=managed / "report.html")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def action_id(subject: str, kind: str, destination_portable: Optional[str]) -> str:
    """Thin re-export so no caller ever hand-rolls an id."""

    return _action_id(subject, kind, destination_portable)


def _disk_status(root: Path, target_percent: float) -> Dict[str, Any]:
    usage = shutil.disk_usage(str(root))
    percent = (usage.used / usage.total * 100) if usage.total else 0.0
    target_used = int(usage.total * target_percent / 100)
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_percent": round(percent, 2),
        "target_percent": target_percent,
        "bytes_to_remove_for_target": max(0, usage.used - target_used),
        "note": "Moves on this volume reclaim 0 bytes.",
    }


def detect_trash_backend() -> str:
    """Which trash backend this machine has, without importing the executor.

    One spelling only: :mod:`carl_file_organizer.trash` owns the answer, and a
    platform added there shows up in the plan without a second edit here.
    """

    return trash.detect_backend()


def _finder_tags_available() -> bool:
    return sys.platform == "darwin" and shutil.which("xattr") is not None


def _aware(moment: Optional[datetime]) -> datetime:
    if moment is None:
        return datetime.now().astimezone()
    if moment.tzinfo is None:
        return moment.astimezone()
    return moment


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return "{0:.1f} {1}".format(size, unit)
        size /= 1024
    return "{0:.1f} TB".format(size)


# ---------------------------------------------------------------------------
# planning context
# ---------------------------------------------------------------------------


@dataclass
class _PairRef:
    group_id: str
    display: str
    stem: str


@dataclass
class PlanContext:
    config: Any
    root: Path
    home: Path
    now: datetime
    large_bytes: int
    offer_delete: bool
    trash_backend: str
    allow_referenced: bool
    guard_context: Any
    pairs: Dict[str, _PairRef] = field(default_factory=dict)
    duplicates: Dict[str, Any] = field(default_factory=dict)
    taken: set = field(default_factory=set)

    @property
    def trash_available(self) -> bool:
        return self.trash_backend != "none"


def _portable(ctx: PlanContext, path: Path) -> str:
    return paths.portable(path, ctx.home)


def _dest_base(ctx: PlanContext, key: str) -> Path:
    return config_module.dest_dir(ctx.config, key)


def _claim(ctx: PlanContext, entry: Entry, key: str, target: Path) -> Tuple[Path, str, bool]:
    """Hand back a destination that does not exist yet; collisions get redirected.

    ``entry`` rather than its name, because a redirected file keeps its suffix
    (``report-<stamp>.pdf``) while a directory does not.
    """

    occupied = target.exists() or target.is_symlink() or str(target) in ctx.taken
    if not occupied:
        ctx.taken.add(str(target))
        return target, key, False
    dup_key = "sensitive.dup" if str(key).split(".")[0] == "sensitive" else "inbox.dup"
    try:
        redirected = _dest_base(ctx, dup_key) / paths.conflict_name(
            entry.name, ctx.now, is_dir=entry.is_dir
        )
    except (KeyError, ValueError):
        ctx.taken.add(str(target))
        return target, key, False
    ctx.taken.add(str(redirected))
    return redirected, dup_key, True


# ---------------------------------------------------------------------------
# action construction
# ---------------------------------------------------------------------------


def make_action(
    entry: Entry,
    kind: str,
    *,
    ctx: PlanContext,
    rule: str,
    reason: Mapping[str, str],
    tier: str,
    confidence: float,
    destination: Optional[Path] = None,
    destination_key: Optional[str] = None,
    detail: Optional[Mapping[str, str]] = None,
    group_id: Optional[str] = None,
    approvable: bool = True,
    reroutable: bool = False,
    requires: Optional[Sequence[str]] = None,
    hints: Optional[Sequence[str]] = None,
    hold_reason: Optional[Mapping[str, Any]] = None,
    guard_block: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """One row of ``plan.actions``, with every frozen field present."""

    source_portable = _portable(ctx, entry.path)
    destination_portable = _portable(ctx, destination) if destination is not None else None

    if kind == "move" and destination is not None:
        restore = i18n.both(
            "restore_move",
            dest='"{0}"'.format(destination_portable),
            src='"{0}/"'.format(_portable(ctx, entry.path.parent)),
        )
    elif kind == "trash":
        restore = i18n.both("restore_trash")
    elif kind == "delete":
        restore = i18n.both("restore_delete")
    else:
        restore = None

    action = {
        "id": _action_id(entry.subject_id, kind, destination_portable),
        "subject_id": entry.subject_id,
        "kind": kind,
        "subject_kind": entry.kind,
        "source": str(entry.path),
        "source_portable": source_portable,
        "filename": entry.name,
        "destination": str(destination) if destination is not None else None,
        "destination_portable": destination_portable,
        "destination_key": destination_key,
        "size_bytes": entry.size_bytes,
        "modified_ns": entry.modified_ns,
        "age_hours": entry.age_hours,
        "rule": rule,
        "reason": dict(reason),
        "detail": dict(detail) if detail else None,
        "confidence": confidence,
        "tier": tier,
        "group_id": group_id,
        "approvable": bool(approvable),
        "reroutable": bool(reroutable),
        "default_selected": False,
        "requires": list(requires or ()),
        "reclaims_bytes": entry.size_bytes if kind in ("trash", "delete") else 0,
        "restore_method": restore,
        "tags": user_tags(entry.tags, config_module.transient_tags(ctx.config)),
        "hints": list(hints or ()),
        "hold_reason": dict(hold_reason) if hold_reason else None,
        "guard": dict(guard_block)
        if guard_block
        else {"open_by": [], "referenced_in": [], "incoming_symlinks": [], "shape": []},
        "dir_stats": entry.dir_stats.as_dict() if entry.dir_stats is not None else None,
        "color": None,
    }
    # Derived last so it can never disagree with the fields above; build_plan
    # recomputes it once more after the duplicate pass rewrites a few tiers.
    action["color"] = action_color(action)
    return action


def _hold(
    entry: Entry,
    ctx: PlanContext,
    *,
    rule: str,
    tier: str,
    reason: Mapping[str, str],
    extra: Optional[Mapping[str, Any]] = None,
    hints: Optional[Sequence[str]] = None,
    guard_block: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    hold_reason = dict(reason)
    if extra:
        hold_reason.update(extra)
    return make_action(
        entry,
        "hold",
        ctx=ctx,
        rule=rule,
        reason=reason,
        tier=tier,
        confidence=CONFIDENCE["hold"],
        approvable=False,
        hold_reason=hold_reason,
        hints=hints,
        guard_block=guard_block,
    )


def disposal_alternatives(
    entry: Entry,
    ctx: PlanContext,
    *,
    rule: str,
    reason: Mapping[str, str],
    tier: str,
    confidence: float,
    group_id: Optional[str] = None,
    guard_block: Optional[Mapping[str, Any]] = None,
    allow_delete: bool = True,
    detail: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Trash and, when it is offered, permanent delete for the same subject."""

    found: List[Dict[str, Any]] = []
    if ctx.trash_available:
        found.append(
            make_action(
                entry,
                "trash",
                ctx=ctx,
                rule=rule,
                reason=reason,
                detail=detail,
                tier=tier,
                confidence=confidence,
                group_id=group_id,
                guard_block=guard_block,
            )
        )
    if ctx.offer_delete and allow_delete:
        found.append(
            make_action(
                entry,
                "delete",
                ctx=ctx,
                rule=rule,
                reason=reason,
                detail=detail,
                tier=tier,
                confidence=confidence,
                group_id=group_id,
                requires=["allow-permanent-delete"],
                guard_block=guard_block,
            )
        )
    return found


# ---------------------------------------------------------------------------
# the guard verdict
# ---------------------------------------------------------------------------


def _who(handles: Sequence[Mapping[str, Any]]) -> str:
    return "、".join(
        "{0}({1})".format(item.get("command") or "?", item.get("pid")) for item in handles
    )


def _where(references: Sequence[Mapping[str, Any]], links: Sequence[str]) -> str:
    parts = ["{0}:{1}".format(item.get("file"), item.get("line")) for item in references]
    parts.extend(str(link) for link in links)
    return "、".join(parts)


def guard_verdict(
    entry: Entry, block: Mapping[str, Any], ctx: PlanContext
) -> Optional[Tuple[str, str, Dict[str, str]]]:
    """``(rule, tier, reason)`` when the safety net says leave this alone."""

    handles = block.get("open_by") or []
    if handles:
        return "hold:in_use", "in_use", i18n.both("hold_in_use", who=_who(handles))

    if "git-worktree" in (block.get("shape") or []):
        return "hold:referenced", "referenced", i18n.both("hold_worktree")

    references = block.get("referenced_in") or []
    links = block.get("incoming_symlinks") or []
    if (references or links) and not ctx.allow_referenced:
        return (
            "hold:referenced",
            "referenced",
            i18n.both("hold_referenced", where=_where(references, links)),
        )

    if guard.recently_modified(entry, ctx.now, ctx.guard_context.recent_minutes):
        return "hold:aging", "aging", i18n.both("hold_recent")
    return None


def _guard_hints(
    block: Mapping[str, Any], ctx: PlanContext
) -> Tuple[List[str], Optional[Dict[str, str]]]:
    """Observations that never change the verdict, plus the downgrade warning."""

    hints: List[str] = []
    shape = block.get("shape") or []
    for label, hint in (
        ("git-dir", "git-repo"),
        ("venv", "venv"),
        ("dotenv", "dotenv"),
        ("node-project", "node-project"),
    ):
        if label in shape:
            hints.append(hint)
    detail = None
    references = block.get("referenced_in") or []
    links = block.get("incoming_symlinks") or []
    if (references or links) and ctx.allow_referenced:
        hints.append("referenced-warning")
        detail = i18n.both("detail_referenced_warning", where=_where(references, links))
    return hints, detail


# ---------------------------------------------------------------------------
# the chain
# ---------------------------------------------------------------------------


def decide_entry(entry: Entry, ctx: PlanContext) -> List[Dict[str, Any]]:
    """Every candidate action for one scanned item, in priority order."""

    config = ctx.config

    # 1. pinned -------------------------------------------------------------
    pinned = classifier.match_pinned(entry.name, config)
    if pinned:
        return [
            _hold(
                entry,
                ctx,
                rule="hold:pinned",
                tier="pinned",
                reason=i18n.both("hold_pinned"),
                extra={"pattern": pinned},
            )
        ]

    # 2. no-go zone ---------------------------------------------------------
    label = paths.is_forbidden(entry.path, config)
    if label:
        return [
            _hold(
                entry,
                ctx,
                rule="hold:forbidden",
                tier="forbidden",
                reason=i18n.both("hold_forbidden", label=label),
                extra={"label": label},
            )
        ]

    # 3. the safety net -----------------------------------------------------
    block = guard.inspect(entry.path, config, ctx.guard_context, is_dir=entry.is_dir)
    verdict = guard_verdict(entry, block, ctx)
    if verdict is not None:
        rule, tier, reason = verdict
        return [_hold(entry, ctx, rule=rule, tier=tier, reason=reason, guard_block=block)]
    hints, guard_detail = _guard_hints(block, ctx)

    # 4. sensitive naming ---------------------------------------------------
    hit = classifier.is_sensitive(entry.name, config)
    if hit is not None:
        target, key, conflicted = _claim(
            ctx,
            entry,
            "sensitive.pending",
            _dest_base(ctx, "sensitive.pending") / entry.name,
        )
        return [
            make_action(
                entry,
                "move",
                ctx=ctx,
                destination=target,
                destination_key=key,
                rule="conflict" if conflicted else "sensitive:{0}".format(hit.layer),
                reason=i18n.both("conflict") if conflicted else i18n.both("sensitive_isolated"),
                detail=guard_detail or i18n.both("detail_sensitive", needle=hit.needle),
                tier="sensitive",
                confidence=CONFIDENCE["sensitive"],
                hints=hints,
                guard_block=block,
            )
        ]

    # 5. your own Finder tags ----------------------------------------------
    profile = getattr(config, "profile", config)
    group_by_tag = bool((profile.get("tags") or {}).get("group_by_user_tags"))
    mine = user_tags(entry.tags, config_module.transient_tags(config))
    if group_by_tag and mine:
        tag = sorted(mine)[0]
        base = _dest_base(ctx, "inbox.by_tag") / paths.safe_dir_name(tag)
        target, key, conflicted = _claim(ctx, entry, "inbox.by_tag", base / entry.name)
        return [
            make_action(
                entry,
                "move",
                ctx=ctx,
                destination=target,
                destination_key=key,
                rule="conflict" if conflicted else "tag:{0}".format(tag),
                reason=i18n.both("conflict") if conflicted else i18n.both("tag_group", tag=tag),
                detail=guard_detail,
                tier="routine",
                confidence=CONFIDENCE["tag"],
                hints=hints,
                guard_block=block,
            )
        ]

    # 6. your own name rules ------------------------------------------------
    pattern = classifier.match_name_pattern(entry.name, config)
    if pattern is not None:
        if pattern.dest_key:
            base = _dest_base(ctx, pattern.dest_key)
            key = pattern.dest_key
            keyed = True
        else:
            base = ctx.root / str(pattern.dest)
            key = "inbox.pending"
            keyed = False
        target, key, conflicted = _claim(ctx, entry, key, base / entry.name)
        return [
            make_action(
                entry,
                "move",
                ctx=ctx,
                destination=target,
                destination_key=key if (keyed or conflicted) else None,
                rule="conflict" if conflicted else "name:{0}".format(pattern.id),
                reason=i18n.both("conflict")
                if conflicted
                else i18n.both("name_pattern", pattern=pattern.id),
                detail=guard_detail,
                tier="routine",
                confidence=CONFIDENCE["name"],
                hints=hints,
                guard_block=block,
            )
        ]

    # 7. archive and extracted folder --------------------------------------
    pair = ctx.pairs.get(entry.subject_id)
    if pair is not None:
        folder = paths.safe_dir_name(split_suffix(pair.display)[0])
        base = _dest_base(ctx, "inbox.pending") / folder
        target, key, conflicted = _claim(ctx, entry, "inbox.pending", base / entry.name)
        reason = i18n.both("pair")
        found = [
            make_action(
                entry,
                "move",
                ctx=ctx,
                destination=target,
                destination_key=key,
                rule="conflict" if conflicted else "pair",
                reason=i18n.both("conflict") if conflicted else reason,
                detail=guard_detail,
                tier="duplicate",
                confidence=CONFIDENCE["pair"],
                group_id=pair.group_id,
                hints=hints,
                guard_block=block,
            )
        ]
        found.extend(
            disposal_alternatives(
                entry,
                ctx,
                rule="pair",
                reason=reason,
                tier="duplicate",
                confidence=CONFIDENCE["pair"],
                group_id=pair.group_id,
                guard_block=block,
                allow_delete=not entry.is_dir,
            )
        )
        return found

    in_duplicate_group = entry.subject_id in ctx.duplicates

    # 8. top level folders --------------------------------------------------
    if entry.is_dir:
        hint = classifier.derivative_hint(entry.name, config)
        if hint:
            hints = list(hints) + ["derivative-copy:{0}".format(hint)]
        target, key, conflicted = _claim(
            ctx, entry, "inbox.pending", _dest_base(ctx, "inbox.pending") / entry.name
        )
        rule = "dir:derivative" if hint else "dir:pending"
        return [
            make_action(
                entry,
                "move",
                ctx=ctx,
                destination=target,
                destination_key=key,
                rule="conflict" if conflicted else rule,
                reason=i18n.both("conflict")
                if conflicted
                else (i18n.both("dir_derivative", hint=hint) if hint else i18n.both("dir_pending")),
                detail=guard_detail,
                tier="routine",
                confidence=CONFIDENCE["dir"],
                reroutable=not conflicted,
                hints=hints,
                guard_block=block,
            )
        ]

    # 9. extension rules and the settling period ---------------------------
    rule_hit = classifier.match_rule(entry.suffix, config)
    found = []
    if rule_hit is not None and rule_hit.dest_key:
        if entry.age_hours < rule_hit.min_age_hours:
            ready = datetime.fromtimestamp(
                entry.modified_ns / 1_000_000_000, tz=ctx.now.tzinfo
            ) + timedelta(hours=rule_hit.min_age_hours)
            return [
                _hold(
                    entry,
                    ctx,
                    rule="hold:aging",
                    tier="aging",
                    reason=i18n.both(
                        "hold_aging", age=entry.age_hours, needed=rule_hit.min_age_hours
                    ),
                    extra={"ready_at": ready.isoformat()},
                    hints=hints,
                    guard_block=block,
                )
            ]
        dest_name = config_module.dir_name(config, rule_hit.dest_key)
        target, key, conflicted = _claim(
            ctx, entry, rule_hit.dest_key, _dest_base(ctx, rule_hit.dest_key) / entry.name
        )
        detail = guard_detail
        if detail is None and rule_hit.min_age_hours > 0:
            detail = i18n.both("detail_aged", age=entry.age_hours, needed=rule_hit.min_age_hours)
        found.append(
            make_action(
                entry,
                "move",
                ctx=ctx,
                destination=target,
                destination_key=key,
                rule="conflict" if conflicted else "ext:{0}".format(entry.suffix),
                reason=i18n.both("conflict")
                if conflicted
                else i18n.both(rule_hit.reason_key, dest=dest_name, hours=rule_hit.min_age_hours),
                detail=detail,
                tier="routine",
                confidence=CONFIDENCE["ext"],
                hints=hints,
                guard_block=block,
            )
        )
    else:
        # 10. unknown extension ---------------------------------------------
        target, key, conflicted = _claim(
            ctx, entry, "inbox.pending", _dest_base(ctx, "inbox.pending") / entry.name
        )
        found.append(
            make_action(
                entry,
                "move",
                ctx=ctx,
                destination=target,
                destination_key=key,
                rule="conflict" if conflicted else "unknown-ext",
                reason=i18n.both("conflict") if conflicted else i18n.both("unknown_ext"),
                detail=guard_detail,
                tier="routine",
                confidence=CONFIDENCE["unknown"],
                reroutable=not conflicted,
                hints=hints,
                guard_block=block,
            )
        )

    # 11. cold storage candidates -------------------------------------------
    if not in_duplicate_group:
        if entry.size_bytes >= ctx.large_bytes:
            found.extend(
                disposal_alternatives(
                    entry,
                    ctx,
                    rule="cold:large",
                    reason=i18n.both("cold_large", size=_format_bytes(entry.size_bytes)),
                    tier="cold",
                    confidence=CONFIDENCE["cold"],
                    guard_block=block,
                    allow_delete=not entry.is_dir,
                )
            )
        elif rule_hit is not None and (
            classifier.is_installer_suffix(entry.suffix, config)
            or classifier.is_archive_suffix(entry.suffix, config)
        ):
            found.extend(
                disposal_alternatives(
                    entry,
                    ctx,
                    rule="cold:installer",
                    reason=i18n.both("cold_installer"),
                    tier="cold",
                    confidence=CONFIDENCE["cold"],
                    guard_block=block,
                    allow_delete=not entry.is_dir,
                )
            )
    return found


# ---------------------------------------------------------------------------
# groups
# ---------------------------------------------------------------------------


def _group_id(prefix: str, material: str) -> str:
    return "{0}-{1}".format(prefix, hashlib.sha256(material.encode("utf-8")).hexdigest()[:8])


def _member_label(entry: Entry) -> str:
    return entry.name + "/" if entry.is_dir else entry.name


def _keep_options(
    members: Sequence[Entry],
    index: Mapping[Tuple[str, str], str],
    *,
    label_of,
) -> List[Dict[str, Any]]:
    options: List[Dict[str, Any]] = []
    for keep in members:
        ids = [index.get((keep.subject_id, "move"))]
        dropped = [m for m in members if m.subject_id != keep.subject_id]
        ids += [index.get((m.subject_id, "trash")) for m in dropped]
        if not all(ids):
            continue
        options.append(
            {
                "key": "keep:{0}".format(keep.subject_id),
                "label": i18n.ui_both(
                    "option_keep_one",
                    keep=label_of(keep),
                    drop="、".join(label_of(m) for m in dropped),
                ),
                "action_ids": ids,
                "requires": [],
            }
        )
    return options


def _build_pair_group(
    raw: Any, group_id: str, index: Mapping[Tuple[str, str], str], ctx: PlanContext
) -> Optional[Dict[str, Any]]:
    members = list(raw.members)
    options: List[Dict[str, Any]] = []

    move_ids = [index.get((m.subject_id, "move")) for m in members]
    if all(move_ids):
        options.append(
            {
                "key": "keep_all",
                "label": i18n.ui_both("option_keep_all"),
                "action_ids": list(move_ids),
                "requires": [],
            }
        )
    options.extend(_keep_options(members, index, label_of=_member_label))

    default_member = next((m for m in members if m.is_dir), members[0])
    dropped = [m for m in members if m.subject_id != default_member.subject_id]
    delete_ids = [index.get((default_member.subject_id, "move"))] + [
        index.get((m.subject_id, "delete")) for m in dropped
    ]
    if ctx.offer_delete and dropped and all(delete_ids):
        options.append(
            {
                "key": "keep:{0}:delete".format(default_member.subject_id),
                "label": i18n.ui_both(
                    "option_keep_one_delete",
                    keep=_member_label(default_member),
                    drop="、".join(_member_label(m) for m in dropped),
                ),
                "action_ids": delete_ids,
                "requires": ["allow-permanent-delete"],
            }
        )

    if not options:
        return None
    keys = [option["key"] for option in options]
    preferred = "keep:{0}".format(default_member.subject_id)
    default_choice = preferred if preferred in keys else keys[0]
    return {
        "group_id": group_id,
        "kind": "pair",
        "tier": "duplicate",
        "stem": raw.stem,
        "evidence": raw.evidence,
        "sha256": raw.sha256,
        "members": [m.subject_id for m in members],
        "member_labels": {m.subject_id: _member_label(m) for m in members},
        "reason": i18n.both("pair"),
        "options": options,
        "default_choice": default_choice,
        "potential_bytes": sum(m.size_bytes for m in dropped)
        if default_choice == preferred
        else 0,
    }


def _build_duplicate_group(
    raw: Any, group_id: str, index: Mapping[Tuple[str, str], str], ctx: PlanContext
) -> Optional[Dict[str, Any]]:
    members = list(raw.members)
    verified = raw.evidence == "sha256"
    reason = i18n.both("dup_sha256") if verified else i18n.both("dup_name")
    options: List[Dict[str, Any]] = []

    move_ids = [index.get((m.subject_id, "move")) for m in members]
    if all(move_ids):
        options.append(
            {
                "key": "keep_all",
                "label": i18n.ui_both("option_keep_all_plain"),
                "action_ids": list(move_ids),
                "requires": [],
            }
        )
    options.extend(_keep_options(members, index, label_of=lambda item: item.name))

    if verified and ctx.offer_delete:
        keep = members[0]
        dropped = [m for m in members if m.subject_id != keep.subject_id]
        delete_ids = [index.get((keep.subject_id, "move"))] + [
            index.get((m.subject_id, "delete")) for m in dropped
        ]
        if dropped and all(delete_ids):
            options.append(
                {
                    "key": "keep:{0}:delete".format(keep.subject_id),
                    "label": i18n.ui_both(
                        "option_keep_one_delete",
                        keep=keep.name,
                        drop="、".join(m.name for m in dropped),
                    ),
                    "action_ids": delete_ids,
                    "requires": ["allow-permanent-delete"],
                }
            )

    if not options:
        return None
    keys = [option["key"] for option in options]
    if verified:
        preferred = "keep:{0}".format(members[0].subject_id)
        default_choice = preferred if preferred in keys else keys[0]
        potential = sum(m.size_bytes for m in members[1:]) if default_choice == preferred else 0
    else:
        default_choice = "keep_all" if "keep_all" in keys else keys[0]
        potential = 0
    return {
        "group_id": group_id,
        "kind": "duplicate",
        "tier": "duplicate",
        "stem": raw.stem,
        "evidence": raw.evidence,
        "sha256": raw.sha256,
        "members": [m.subject_id for m in members],
        "member_labels": {m.subject_id: m.name for m in members},
        "reason": reason,
        "options": options,
        "default_choice": default_choice,
        "potential_bytes": potential,
    }


# ---------------------------------------------------------------------------
# build_plan
# ---------------------------------------------------------------------------


def build_plan(
    source_root: Path,
    *,
    config: Any = None,
    now: Optional[datetime] = None,
    hash_duplicates: bool = False,
    large_bytes: int = DEFAULT_LARGE_BYTES,
    target_percent: float = DEFAULT_TARGET_PERCENT,
    dir_sizes: bool = True,
    offer_permanent_delete: bool = True,
    allow_referenced: bool = False,
    home: Optional[Path] = None,
    guard_options: Optional[Mapping[str, Any]] = None,
    trash_backend: Optional[str] = None,
) -> Dict[str, Any]:
    """Scan ``source_root`` read-only and return a schema v2 plan."""

    requested = Path(source_root).expanduser()
    cfg = config if config is not None else config_module.resolve_config(requested)
    # The config owns the root: destinations are built from it, so anything else
    # here would make every destination fall outside the root it is compared to.
    root = Path(cfg.root)
    if not root.is_dir():
        raise ValueError("Source is not a directory: {0}".format(root))
    moment = _aware(now)
    home_dir = Path(home) if home is not None else Path.home()
    backend = trash_backend if trash_backend is not None else detect_trash_backend()

    options = dict(guard_options or {})
    guard_context = guard.build_context(
        cfg,
        home=home_dir,
        enabled=bool(options.get("enabled", True)),
        reference_files=options.get("reference_files"),
        scan_roots=options.get("scan_roots"),
        lsof_runner=options.get("lsof_runner"),
        lsof_enabled=bool(options.get("lsof_enabled", True)),
        crontab_runner=options.get("crontab_runner"),
        git_status_runner=options.get("git_status_runner"),
    )

    entries, notes = scan_top_level(root, cfg, now=moment, dir_sizes=dir_sizes)
    guard_context.prime(
        [entry.path for entry in entries if not entry.is_dir],
        [entry.path for entry in entries if entry.is_dir],
    )

    profile = cfg.profile
    dedupe = profile.get("dedupe") or {}
    hash_max_bytes = int(dedupe.get("hash_max_bytes", grouping.DEFAULT_HASH_MAX_BYTES))
    regen_depth = int((profile.get("regenerable") or {}).get("scan_depth", 3))

    ctx = PlanContext(
        config=cfg,
        root=root,
        home=home_dir,
        now=moment,
        large_bytes=int(large_bytes),
        offer_delete=bool(offer_permanent_delete),
        trash_backend=backend,
        allow_referenced=bool(allow_referenced),
        guard_context=guard_context,
    )

    raw_pairs = grouping.pair_archives(entries, cfg)
    paired_subjects = set()
    for raw in raw_pairs:
        raw.group_id = _group_id("pair", raw.stem)
        for member in raw.members:
            paired_subjects.add(member.subject_id)
            ctx.pairs[member.subject_id] = _PairRef(raw.group_id, raw.display, raw.stem)

    raw_dups = grouping.find_duplicates(
        entries,
        hash_duplicates=hash_duplicates,
        hash_max_bytes=hash_max_bytes,
        exclude=paired_subjects,
    )
    for raw in raw_dups:
        raw.group_id = _group_id("dup", (raw.sha256 or raw.stem) + raw.evidence)
        for member in raw.members:
            ctx.duplicates[member.subject_id] = raw

    actions: List[Dict[str, Any]] = []
    for entry in entries:
        actions.extend(decide_entry(entry, ctx))

    by_subject: Dict[str, List[Dict[str, Any]]] = {}
    for action in actions:
        by_subject.setdefault(action["subject_id"], []).append(action)

    # duplicate groups relabel the primary move and add disposal options
    for raw in raw_dups:
        verified = raw.evidence == "sha256"
        reason = i18n.both("dup_sha256") if verified else i18n.both("dup_name")
        rule = "dup:sha256" if verified else "dup:name"
        confidence = CONFIDENCE["dup_sha256"] if verified else CONFIDENCE["dup_name"]
        for member in raw.members:
            primary = [
                item for item in by_subject.get(member.subject_id, []) if item["kind"] == "move"
            ]
            if not primary:
                continue
            head = primary[0]
            head["group_id"] = raw.group_id
            if head["rule"] != "conflict":
                head["rule"] = rule
                head["reason"] = dict(reason)
            head["confidence"] = confidence
            head["tier"] = "duplicate"
            head["reroutable"] = False
            actions.extend(
                disposal_alternatives(
                    member,
                    ctx,
                    rule=rule,
                    reason=reason,
                    tier="duplicate",
                    confidence=confidence,
                    group_id=raw.group_id,
                    guard_block=head["guard"],
                    allow_delete=verified and not member.is_dir,
                    detail=None if verified else i18n.both("detail_dup_unverified"),
                )
            )

    # regenerable build output inside top level folders
    regen_groups: List[Dict[str, Any]] = []
    for hit in grouping.find_regenerable(entries, cfg, max_depth=regen_depth, now=moment):
        subject = Entry(
            path=hit.path,
            name=hit.name,
            kind="dir",
            size_bytes=hit.dir_stats.bytes,
            modified_ns=hit.modified_ns,
            age_hours=hit.age_hours,
            suffix="",
            tags=[],
            dir_stats=hit.dir_stats,
            subject_id=hit.subject_id,
        )
        group_id = _group_id("regen", hit.relative)
        restore = classifier.regenerable_restore(hit.name, cfg)
        reason = {
            "zh": i18n.reason("regenerable", "zh", restore=restore.get("zh", "")),
            "en": i18n.reason("regenerable", "en", restore=restore.get("en", "")),
        }
        made = disposal_alternatives(
            subject,
            ctx,
            rule="regenerable:{0}".format(hit.name),
            reason=reason,
            tier="regenerable",
            confidence=CONFIDENCE["regenerable"],
            group_id=group_id,
        )
        if not made:
            continue
        actions.extend(made)
        by_kind = {item["kind"]: item["id"] for item in made}
        options = []
        if "trash" in by_kind:
            options.append(
                {
                    "key": "trash_all",
                    "label": i18n.ui_both("option_trash_all"),
                    "action_ids": [by_kind["trash"]],
                    "requires": [],
                }
            )
        if "delete" in by_kind:
            options.append(
                {
                    "key": "delete_all",
                    "label": i18n.ui_both("option_delete_all"),
                    "action_ids": [by_kind["delete"]],
                    "requires": ["allow-permanent-delete"],
                }
            )
        regen_groups.append(
            {
                "group_id": group_id,
                "kind": "regenerable",
                "tier": "regenerable",
                "stem": hit.name,
                "evidence": "basename",
                "sha256": None,
                "members": [hit.subject_id],
                "member_labels": {hit.subject_id: hit.relative},
                "reason": reason,
                "options": options,
                "default_choice": options[0]["key"],
                "potential_bytes": hit.dir_stats.bytes,
            }
        )

    index: Dict[Tuple[str, str], str] = {}
    for action in actions:
        index[(action["subject_id"], action["kind"])] = action["id"]

    groups: List[Dict[str, Any]] = []
    for raw in raw_pairs:
        built = _build_pair_group(raw, raw.group_id, index, ctx)
        if built is not None:
            groups.append(built)
    for raw in raw_dups:
        built = _build_duplicate_group(raw, raw.group_id, index, ctx)
        if built is not None:
            groups.append(built)
    groups.extend(regen_groups)

    known_groups = {group["group_id"] for group in groups}
    for action in actions:
        if action["group_id"] is not None and action["group_id"] not in known_groups:
            action["group_id"] = None

    # The duplicate pass rewrites a few tiers and clears a reroutable flag, so
    # every colour is settled here, once, on the finished list.
    for action in actions:
        action["color"] = action_color(action)
    # A group is a question, and most questions are yellow: whichever option you
    # pick, something gets disposed of that a rule alone would not touch.  The
    # regenerable group is the exception, and it follows its own members: build
    # output rebuilds itself from source, so both of its options are green and
    # colouring the question yellow would only ask for a look nobody needs.
    for group in groups:
        group["color"] = GREEN if group.get("kind") == "regenerable" else YELLOW

    names: Dict[str, str] = {}
    for key in profile.get("names") or {}:
        try:
            names[key] = config_module.dir_name(cfg, key)
        except (KeyError, ValueError):
            continue

    by_tier: Dict[str, int] = {}
    by_kind_count: Dict[str, int] = {}
    by_destination: Dict[str, int] = {}
    reclaimable: Dict[str, int] = {}
    for action in actions:
        by_tier[action["tier"]] = by_tier.get(action["tier"], 0) + 1
        by_kind_count[action["kind"]] = by_kind_count.get(action["kind"], 0) + 1
        if action["kind"] == "move" and action["destination"]:
            try:
                relative = Path(action["destination"]).parent.relative_to(root).as_posix()
            except ValueError:
                relative = str(Path(action["destination"]).parent)
            by_destination[relative] = by_destination.get(relative, 0) + 1
        if action["kind"] in ("trash", "delete"):
            reclaimable[action["subject_id"]] = action["size_bytes"]

    managed = config_module.managed_dir(cfg)
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "carl-file-organizer", "version": __version__},
        # created_at follows the plan's clock, so --now gives a byte-identical
        # plan twice in a row; generated_at keeps the real one for support.
        "created_at": moment.isoformat(),
        "generated_at": datetime.now().astimezone().isoformat(),
        "now": moment.isoformat(),
        "lang": cfg.lang,
        "lang_source": cfg.lang_source,
        "profile": {
            "name": cfg.profile_name,
            "source": cfg.profile_source,
            "dotfile": paths.portable(cfg.dotfile_path, home_dir) if cfg.dotfile_path else None,
            "hash": cfg.profile_hash,
        },
        "source_root": str(root),
        "source_root_portable": paths.portable(root, home_dir),
        "managed_dir": str(managed),
        "managed_dir_portable": paths.portable(managed, home_dir),
        "names": names,
        "capabilities": {
            "trash_backend": backend,
            "finder_tags": _finder_tags_available(),
            "permanent_delete_offered": bool(offer_permanent_delete)
            and any(action["kind"] == "delete" for action in actions),
        },
        "scan_policy": {
            "depth": 1,
            "hidden_files": "ignored",
            "symlinks": "ignored",
            "managed_partitions": "skipped",
            "regenerable_scan_depth": regen_depth,
            "dir_size_limit": {"max_entries": 50000, "time_budget_s": 1.5}
            if dir_sizes
            else {"max_entries": 0, "time_budget_s": 0},
            "hash_duplicates": bool(hash_duplicates),
            "hash_max_bytes": hash_max_bytes,
            "allow_referenced": bool(allow_referenced),
            "skipped": {
                "hidden": notes.skipped_hidden,
                "symlinks": notes.skipped_symlinks,
                "partitions": notes.skipped_partitions,
                "artifacts": notes.skipped_artifacts,
            },
        },
        "disk": _disk_status(root, target_percent),
        "mess": build_mess(entries, actions, groups),
        "summary": {
            "entries": len(entries),
            "files": sum(1 for entry in entries if not entry.is_dir),
            "dirs": sum(1 for entry in entries if entry.is_dir),
            "bytes": sum(entry.size_bytes for entry in entries),
            "by_tier": dict(sorted(by_tier.items())),
            "by_kind": dict(sorted(by_kind_count.items())),
            "by_color": color_totals(actions),
            "by_destination": dict(sorted(by_destination.items())),
            "groups": {
                "pair": sum(1 for group in groups if group["kind"] == "pair"),
                "duplicate": sum(1 for group in groups if group["kind"] == "duplicate"),
                "regenerable": sum(1 for group in groups if group["kind"] == "regenerable"),
            },
            "potential_reclaimable_bytes": sum(reclaimable.values()),
            "proposed_reclaimed_bytes": 0,
        },
        "pinned": [str(item) for item in (profile.get("pinned") or ())],
        "actions": actions,
        "groups": groups,
        # Prose written by an agent on top of the rules, filled in by
        # ``carl_file_organizer.notes``.  None means nobody wrote any, and the
        # report falls back to the rule text.
        "notes": None,
        "approved_action_ids": [],
        "overrides": [],
        "approved_at": None,
        "approved_by": None,
    }


def write_plan(plan: Dict[str, Any], output: Path) -> None:
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def run(args: Any) -> int:
    """``carl-file-organizer plan``: a read-only scan, then a plan and a review page."""

    cfg = getattr(args, "config", None)
    if cfg is None:
        cfg = config_module.resolve_config(
            Path(args.source),
            lang=getattr(args, "lang", None),
            profile=getattr(args, "profile", None),
        )

    large_mb = int(getattr(args, "large_mb", 500))
    target_percent = float(getattr(args, "target_percent", DEFAULT_TARGET_PERCENT))
    if large_mb < 1:
        raise ValueError("--large-mb must be at least 1")
    if not 1 <= target_percent <= 99:
        raise ValueError("--target-percent must be between 1 and 99")

    where = plan_paths(cfg)
    where.managed.mkdir(parents=True, exist_ok=True)

    plan = build_plan(
        cfg.root,
        config=cfg,
        now=getattr(args, "now", None),
        hash_duplicates=bool(getattr(args, "hash_duplicates", False)),
        large_bytes=large_mb * 1024 * 1024,
        target_percent=target_percent,
        dir_sizes=bool(getattr(args, "dir_sizes", True)),
        offer_permanent_delete=bool(getattr(args, "permanent_delete_options", True)),
        allow_referenced=bool(getattr(args, "allow_referenced", False)),
    )
    write_plan(plan, where.plan)
    print(i18n.t("cli_plan_written", cfg.lang, path=where.plan))

    try:
        from .report import write_report

        write_report(plan, where.report)
    except Exception as error:  # noqa: BLE001 - the plan itself is the deliverable
        print(
            i18n.t("cli_report_skipped", cfg.lang, module="carl_file_organizer.report")
            + " ({0})".format(error)
        )
    else:
        print(i18n.t("cli_report_written", cfg.lang, path=where.report))

    approvable = sum(1 for action in plan["actions"] if action["approvable"])
    print(
        i18n.t(
            "cli_scan_summary",
            cfg.lang,
            entries=plan["summary"]["entries"],
            actions=len(plan["actions"]),
            approvable=approvable,
        )
    )
    print(i18n.t("cli_nothing_moved", cfg.lang))
    return 0
