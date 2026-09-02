"""Two answers: when this folder was last tidied, and whether it is messy again.

The first answer comes only from the manifests in the managed directory.  A
folder's modification time changes every time anything is downloaded into it,
so it says nothing about whether anyone ever organized it; the manifests are
the only honest record.

The second answer comes from a fresh read-only plan.  When the planner is not
available the status still prints, and simply says the recheck could not run.
"""

from __future__ import annotations

import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import i18n
from . import manifest as manifest_module

TEXT = {
    "never": {"zh": "还没整理过", "en": "not tidied yet"},
    "last_line": {
        "zh": "{when}，动过 {count} 项（清单 {name}）",
        "en": "{when}, {count} item(s) (manifest {name})",
    },
    "clean": {"zh": "顶层是干净的", "en": "the top level is clear"},
    "dirty": {
        "zh": "散件 {loose} · 静置中 {aging} · 待判断 {pending} · 敏感待转移 {sensitive}",
        "en": "loose {loose} · settling {aging} · undecided {pending} · sensitive {sensitive}",
    },
    "no_recheck": {
        "zh": "无法复查（{error}），下面的数字这次没有算出来",
        "en": "recheck unavailable ({error}); the counts below were not computed",
    },
    "planner_missing": {
        "zh": "扫描模块还没接上",
        "en": "the planner is not wired up yet",
    },
    "root_line": {"zh": "目录", "en": "Folder"},
}


def text(key: str, lang: str = "en", **kw: Any) -> str:
    entry = TEXT.get(key, {})
    template = entry.get(lang) or entry.get("en") or key
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError):
        return template


@dataclass
class StatusReport:
    root: Path
    lang: str = "en"
    last_run: Optional[manifest_module.RunInfo] = None
    loose: int = 0
    aging: int = 0
    pending: int = 0
    sensitive_pending: int = 0
    recheck_actions: Optional[int] = None
    recheck_error: Optional[str] = None
    managed: Optional[Path] = None
    notes: List[str] = field(default_factory=list)


#: Rules that mean the item is waiting for a person to decide where it goes.
PENDING_RULES = ("unknown-ext", "dir:pending", "dir:derivative")


def _plan_counts(plan: Dict[str, Any], report: StatusReport) -> None:
    actions = plan.get("actions") or []
    loose = set()
    aging = set()
    pending = set()
    sensitive = set()
    approvable = 0

    for action in actions:
        if not isinstance(action, dict):
            continue
        subject = str(action.get("subject_id") or action.get("id") or "")
        kind = str(action.get("kind") or "")
        tier = str(action.get("tier") or "")
        rule = str(action.get("rule") or "")
        if action.get("approvable", kind != "hold"):
            approvable += 1
        if kind == "hold":
            if tier == "aging" or rule == "hold:aging":
                aging.add(subject)
            continue
        loose.add(subject)
        if rule in PENDING_RULES or str(action.get("destination_key") or "").startswith(
            "inbox.pending"
        ):
            pending.add(subject)
        if tier == "sensitive":
            sensitive.add(subject)

    report.loose = len(loose)
    report.aging = len(aging)
    report.pending = len(pending)
    report.sensitive_pending = len(sensitive)
    report.recheck_actions = approvable


def _default_plan_fn(root: Path, config: Any, now: Optional[datetime]) -> Dict[str, Any]:
    """Call ``planner.build_plan`` with whichever keywords it actually accepts."""

    import inspect

    from . import planner as planner_module

    build = getattr(planner_module, "build_plan", None)
    if build is None:
        raise RuntimeError(text("planner_missing", "en"))

    options: Dict[str, Any] = {}
    try:
        parameters = inspect.signature(build).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "config" in parameters:
        options["config"] = config
    if "now" in parameters and now is not None:
        options["now"] = now
    if "dir_sizes" in parameters:
        options["dir_sizes"] = False
    if "hash_duplicates" in parameters:
        options["hash_duplicates"] = False
    return build(root, **options)


def compute_status(
    root: Path,
    *,
    config: Any,
    now: Optional[datetime] = None,
    plan_fn: Optional[Callable[[], Dict[str, Any]]] = None,
) -> StatusReport:
    """Last run from the manifests, current mess from a fresh read-only plan."""

    from . import config as config_module

    folder = Path(root)
    report = StatusReport(root=folder, lang=getattr(config, "lang", "en"))
    managed = config_module.managed_dir(config)
    report.managed = managed
    report.last_run = manifest_module.latest_run(managed)

    try:
        plan = plan_fn() if plan_fn is not None else _default_plan_fn(folder, config, now)
    except Exception as error:  # noqa: BLE001 - status must print even when scanning fails
        report.recheck_error = str(error) or error.__class__.__name__
        return report

    if not isinstance(plan, dict):
        report.recheck_error = "the planner returned no plan"
        return report

    _plan_counts(plan, report)
    return report


def _display_width(text_value: str) -> int:
    """Column width of a label, counting wide CJK characters as two cells."""

    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text_value)


def _pad(text_value: str, width: int) -> str:
    return text_value + " " * max(0, width - _display_width(text_value))


def format_status(report: StatusReport, lang: Optional[str] = None) -> str:
    """Two labelled lines: when it was last done, and how it looks now."""

    speech = lang or report.lang or "en"
    label_root = text("root_line", speech)
    label_last = i18n.t("status_last_run", speech)
    label_now = i18n.t("status_dirty_now", speech)
    width = max(_display_width(item) for item in (label_root, label_last, label_now))

    if report.last_run is None:
        last = text("never", speech)
    else:
        stamp = report.last_run.moved_at or ""
        if report.last_run.timestamp is not None and not stamp:
            stamp = report.last_run.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        last = text(
            "last_line",
            speech,
            when=stamp,
            count=report.last_run.done,
            name=report.last_run.path.name,
        )

    if report.recheck_error is not None:
        now_line = text("no_recheck", speech, error=report.recheck_error)
    elif not (report.loose or report.aging or report.pending or report.sensitive_pending):
        now_line = text("clean", speech)
    else:
        now_line = text(
            "dirty",
            speech,
            loose=report.loose,
            aging=report.aging,
            pending=report.pending,
            sensitive=report.sensitive_pending,
        )

    lines = [
        "{0}  {1}".format(_pad(label_root, width), report.root),
        "{0}  {1}".format(_pad(label_last, width), last),
        "{0}  {1}".format(_pad(label_now, width), now_line),
    ]
    return "\n".join(lines)


def run(args: Any) -> int:
    """``carl-file-organizer status [dir] [--lang zh|en]``."""

    config = getattr(args, "config", None)
    if config is None:
        from . import config as config_module
        from . import paths

        root = paths.refuse_root(
            args.source, allow_outside_home=getattr(args, "allow_outside_home", False)
        )
        config = config_module.resolve_config(root, lang=getattr(args, "lang", None))

    report = compute_status(config.root, config=config)
    print(format_status(report, config.lang))
    if report.recheck_error:
        print(report.recheck_error, file=sys.stderr)
    return 0
