"""Put things back where they came from, in reverse order.

Undo reads either the audit log or a TSV manifest, walks it backwards, and
moves each item back to the path it started from.  It is deliberately timid:
if the original path is occupied again, or the item is no longer where the
record says it is, that row is skipped and reported rather than forced.

Trash and permanent delete cannot be undone from here.  Trashed items are put
back from the Trash by the person; permanently deleted ones are gone, and
saying so plainly is more useful than pretending.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import manifest as manifest_module
from . import paths
from . import tags as tags_module

#: Record statuses that describe a completed move, in both spellings.
UNDOABLE_STATUSES = ("moved", "MOVED", "restored", "RESTORED")

TEXT = {
    "trashed": {
        "zh": "这一项进了废纸篓，在废纸篓里选放回原处就行，这里不动它",
        "en": "This one went to the trash; put it back from there, not from here",
    },
    "deleted": {
        "zh": "这一项已永久删除，没法还原",
        "en": "This one was permanently deleted and cannot be restored",
    },
    "not_moved": {
        "zh": "这条记录不是一次成功的移动（{status}），跳过",
        "en": "This record is not a completed move ({status}); skipped",
    },
    "no_paths": {
        "zh": "这条记录缺少原路径或当前路径，跳过",
        "en": "This record has no original or current path; skipped",
    },
    "occupied": {
        "zh": "原来的位置已经有同名的东西了，不覆盖，跳过",
        "en": "Something is at the original path again; not overwriting, skipped",
    },
    "missing": {
        "zh": "现在的位置上找不到它，可能已经被人挪走了，跳过",
        "en": "It is not where the record says it is; skipped",
    },
    "outside": {
        "zh": "路径不在整理目录里，拒绝移动",
        "en": "That path is outside the folder; refused",
    },
    "symlink": {"zh": "路径里有软链，拒绝移动", "en": "A symlink sits in this path; refused"},
    "restored": {"zh": "已放回原处", "en": "put back"},
    "dry_run": {"zh": "预演：会放回原处", "en": "dry run: would put it back"},
    "error": {"zh": "放回失败：{error}", "en": "putting it back failed: {error}"},
    "log": {
        "zh": "撤销了 {count} 项移动，已放回原处；清单：`{manifest}`。",
        "en": "Undid {count} move(s) and put them back; manifest: `{manifest}`.",
    },
    "summary": {
        "zh": "共 {total} 条：放回 {restored}，跳过 {skipped}，失败 {failed}",
        "en": "{total} record(s): restored {restored}, skipped {skipped}, failed {failed}",
    },
    "no_records": {
        "zh": "这个文件里没有可撤销的记录：{path}",
        "en": "No undoable record in {path}",
    },
    "unknown_root": {
        "zh": "看不出这些记录属于哪个整理目录：{path}",
        "en": "Cannot tell which folder these records belong to: {path}",
    },
}


def text(key: str, lang: str = "en", **kw: Any) -> str:
    entry = TEXT.get(key, {})
    template = entry.get(lang) or entry.get("en") or key
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError):
        return template


@dataclass
class UndoStep:
    record: Dict[str, Any]
    kind: str
    status: str
    ok: bool
    detail: str = ""
    action_id: str = ""
    original: Optional[Path] = None
    current: Optional[Path] = None
    size_bytes: int = 0


@dataclass
class UndoReport:
    run_id: str
    dry_run: bool
    results: List[Dict[str, Any]] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    manifest: Optional[Path] = None
    audit: Optional[Path] = None
    review_log: Optional[Path] = None


# --------------------------------------------------------------------------
# reading records
# --------------------------------------------------------------------------


def load_records(path: Path) -> List[Dict[str, Any]]:
    """Read an ``audit.jsonl`` or a manifest ``.tsv`` into one common shape."""

    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(str(source))
    suffix = source.suffix.casefold()
    if suffix in (".jsonl", ".json", ".ndjson"):
        return manifest_module.read_audit(source)
    if suffix == ".tsv":
        return [_from_manifest_row(row) for row in manifest_module.read_manifest(source)]
    raise ValueError(
        "undo reads an audit .jsonl or a manifest .tsv, not {0}".format(source.name)
    )


def _from_manifest_row(row: Dict[str, str]) -> Dict[str, Any]:
    """A manifest row wearing the audit record's field names."""

    target = row.get("target_path") or ""
    try:
        size = int(row.get("size_bytes") or 0)
    except ValueError:
        size = 0
    return {
        "timestamp": row.get("moved_at", ""),
        "action_id": row.get("action_id", ""),
        "kind": row.get("kind") or ("move" if target else ""),
        "source": row.get("original_path", ""),
        "destination": target,
        "status": row.get("status", ""),
        "size_bytes": size,
        "detail": row.get("reason", ""),
        "origin": "manifest",
    }


# --------------------------------------------------------------------------
# planning the undo
# --------------------------------------------------------------------------


def plan_undo(
    records: Sequence[Dict[str, Any]],
    *,
    root: Path,
    home: Optional[Path] = None,
    lang: str = "en",
) -> List[UndoStep]:
    """Reverse order, and one step per record so nothing disappears silently."""

    steps: List[UndoStep] = []
    for record in reversed(list(records)):
        kind = str(record.get("kind") or "")
        status = str(record.get("status") or "")
        action_id = str(record.get("action_id") or "")

        if kind == "trash" or status in ("trashed", "TRASHED"):
            steps.append(
                UndoStep(record, kind or "trash", "skipped", False, text("trashed", lang), action_id)
            )
            continue
        if kind == "delete" or status in ("deleted", "DELETED"):
            steps.append(
                UndoStep(record, kind or "delete", "skipped", False, text("deleted", lang), action_id)
            )
            continue
        if kind and kind != "move":
            steps.append(
                UndoStep(record, kind, "skipped", False, text("not_moved", lang, status=status), action_id)
            )
            continue
        if status not in UNDOABLE_STATUSES:
            steps.append(
                UndoStep(record, "move", "skipped", False, text("not_moved", lang, status=status), action_id)
            )
            continue

        original_text = str(record.get("source") or "")
        current_text = str(record.get("destination") or "")
        if not original_text or not current_text:
            steps.append(
                UndoStep(record, "move", "skipped", False, text("no_paths", lang), action_id)
            )
            continue

        original = paths.expand_portable(original_text, home)
        current = paths.expand_portable(current_text, home)
        try:
            size = int(record.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size = 0
        steps.append(
            UndoStep(
                record,
                "move",
                "ready",
                True,
                "",
                action_id,
                original=original,
                current=current,
                size_bytes=size,
            )
        )
    return steps


# --------------------------------------------------------------------------
# running it
# --------------------------------------------------------------------------


def run_undo(
    steps: Sequence[UndoStep],
    *,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    root: Optional[Path] = None,
    home: Optional[Path] = None,
    config: Any = None,
    lang: Optional[str] = None,
    managed: Optional[Path] = None,
    transient_tag: Optional[str] = None,
) -> UndoReport:
    """Move each ready step back, then write its own manifest, audit and log."""

    from . import config as config_module

    moment = now or datetime.now().astimezone()
    run_id = manifest_module.timestamp_text(moment)
    moved_at = moment.isoformat(timespec="seconds")
    speech = lang or (getattr(config, "lang", None) or "en")
    home_dir = Path(home) if home is not None else Path.home()

    if managed is None and config is not None:
        managed = config_module.managed_dir(config)
    if transient_tag is None and config is not None:
        transient_tag = config_module.transient_tag(config)

    report = UndoReport(run_id=run_id, dry_run=dry_run)
    rows: List[Dict[str, Any]] = []

    for step in steps:
        status, detail = _restore_one(step, root=root, dry_run=dry_run, lang=speech)
        if status == "restored" and not dry_run and transient_tag and step.original:
            try:
                tags_module.remove_tag(step.original, transient_tag)
            except Exception as error:  # noqa: BLE001 - tagging never stops an undo
                print("tag_warning: {0}\t{1}".format(step.original, error), file=sys.stderr)

        record = {
            "timestamp": moved_at,
            "run_id": run_id,
            "action_id": step.action_id,
            "subject_id": step.record.get("subject_id"),
            "kind": "move",
            "source": paths.portable(step.current, home_dir) if step.current else None,
            "destination": paths.portable(step.original, home_dir) if step.original else None,
            "status": "moved" if status == "restored" else status,
            "detail": detail,
            "size_bytes": step.size_bytes,
            "manifest": "",
            "tagged": False,
            "trash_backend": "",
            "undo": True,
        }
        report.results.append(record)

        if step.original and step.current:
            rows.append(
                {
                    "moved_at": moved_at,
                    "status": "RESTORED" if status == "restored" else status.upper(),
                    "original_path": paths.portable(step.current, home_dir),
                    "target_path": paths.portable(step.original, home_dir),
                    "size_bytes": step.size_bytes,
                    "reason": detail,
                    "restore_method": 'mv "{0}" "{1}"'.format(
                        paths.portable(step.original, home_dir),
                        paths.portable(step.current, home_dir),
                    ),
                    "kind": "move",
                    "action_id": step.action_id,
                }
            )

    counts: Dict[str, int] = {"total": len(report.results)}
    for record in report.results:
        key = str(record.get("status"))
        counts[key] = counts.get(key, 0) + 1
    report.counts = counts

    restored = counts.get("moved", 0)
    if not dry_run and managed is not None and rows:
        managed = Path(managed)
        managed.mkdir(parents=True, exist_ok=True)
        root_name = Path(root).name if root is not None else managed.parent.name
        manifest_file = manifest_module.manifest_path(managed, root_name, "undo", moment)
        manifest_module.write_manifest(manifest_file, rows)
        report.manifest = manifest_file
        manifest_text = paths.portable(manifest_file, home_dir)
        for record in report.results:
            record["manifest"] = manifest_text
        report.audit = manifest_module.append_audit(
            report.results, manifest_module.audit_path(managed)
        )
        if restored:
            report.review_log = manifest_module.append_review_log(
                managed,
                speech,
                moment.date(),
                [text("log", speech, count=restored, manifest=manifest_text)],
                name=config_module.review_log_name(config) if config is not None else None,
            )

    return report


def _restore_one(
    step: UndoStep, *, root: Optional[Path], dry_run: bool, lang: str
) -> Tuple[str, str]:
    if not step.ok:
        return step.status, step.detail
    original = step.original
    current = step.current
    if original is None or current is None:
        return "skipped", text("no_paths", lang)

    if os.path.lexists(str(original)):
        return "skipped", text("occupied", lang)
    if not os.path.lexists(str(current)):
        return "skipped", text("missing", lang)

    if root is not None:
        base = Path(root)
        if not paths.inside_root(current, base) or not paths.inside_root(original.parent, base):
            return "refused", text("outside", lang)
        if paths.has_symlink_component(current, base) or paths.has_symlink_component(
            original.parent, base
        ):
            return "refused", text("symlink", lang)

    if dry_run:
        return "dry-run", text("dry_run", lang)

    try:
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(current), str(original))
    except (OSError, shutil.Error) as error:
        return "failed", text("error", lang, error=error)
    return "restored", text("restored", lang)


# --------------------------------------------------------------------------
# undo subcommand
# --------------------------------------------------------------------------


def infer_root(record_path: Path, steps: Sequence[UndoStep]) -> Optional[Path]:
    """The folder these records belong to: the managed directory's parent."""

    candidate = paths.realpath(Path(record_path)).parent.parent
    for step in steps:
        if step.original is not None and paths.inside_root(step.original.parent, candidate):
            return candidate
    originals = [str(step.original.parent) for step in steps if step.original is not None]
    if not originals:
        return candidate if candidate.is_dir() else None
    try:
        common = Path(os.path.commonpath(originals))
    except ValueError:
        return None
    return common if common.is_dir() else None


def run(args: Any) -> int:
    """``carl-file-organizer undo <audit.jsonl | manifest.tsv> [--dry-run]``."""

    from . import config as config_module

    record_path = Path(args.record).expanduser()
    records = load_records(record_path)
    if not records:
        print(text("no_records", "en", path=record_path), file=sys.stderr)
        return 2

    steps = plan_undo(records, root=Path("/"), home=None)
    root = infer_root(record_path, steps)
    if root is None:
        print(text("unknown_root", "en", path=record_path), file=sys.stderr)
        return 2

    config = config_module.resolve_config(root)
    lang = config.lang
    steps = plan_undo(records, root=root, home=None, lang=lang)

    report = run_undo(
        steps,
        dry_run=bool(args.dry_run),
        root=root,
        config=config,
        lang=lang,
        managed=config_module.managed_dir(config),
    )

    for record in report.results:
        print(
            "{0}\t{1}\t{2}".format(
                record.get("status"), record.get("source") or "", record.get("detail")
            )
        )
    print(
        text(
            "summary",
            lang,
            total=report.counts.get("total", 0),
            restored=report.counts.get("moved", 0) + report.counts.get("dry-run", 0),
            skipped=report.counts.get("skipped", 0) + report.counts.get("refused", 0),
            failed=report.counts.get("failed", 0),
        )
    )
    if report.manifest:
        print("manifest: {0}".format(report.manifest))
    return 2 if report.counts.get("failed", 0) else 0
