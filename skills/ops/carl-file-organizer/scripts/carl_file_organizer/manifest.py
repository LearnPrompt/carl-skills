"""Paper trail: TSV manifests, tag lists, audit log, the human review log.

Four kinds of file live in the managed directory, and every one of them is
written for a person to read first and a program second:

    downloads-moves-<ts>.tsv        what moved, with a restore command per row
    downloads-move-tags-<ts>.txt    the paths that got the temporary Finder tag
    audit.jsonl                     one JSON line per executed action
    人工调整日志.md / review-log.md   a dated summary in plain sentences

The first seven manifest columns are byte-for-byte the ones the reference
script has been writing since August, so old manifests stay readable and old
readers keep working; ``kind`` and ``action_id`` are appended after them.

Paths inside these files are always written in ``$HOME/...`` form.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

MANIFEST_COLUMNS = (
    "moved_at",
    "status",
    "original_path",
    "target_path",
    "size_bytes",
    "reason",
    "restore_method",
    "kind",
    "action_id",
)

#: The seven columns the reference script wrote; anything after them is extra.
LEGACY_COLUMNS = MANIFEST_COLUMNS[:7]

MANIFEST_SERIES = ("conflict-moves", "moves", "removals", "undo")

#: Series that count as a tidy-up run when answering "when was this last done".
TIDY_SERIES = ("conflict-moves", "moves", "removals")

AUDIT_NAME = "audit.jsonl"
TAG_LIST_SERIES = "move-tags"
TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"

REVIEW_LOG_NAMES = {"zh": "人工调整日志.md", "en": "review-log.md"}
REVIEW_LOG_TITLES = {"zh": "# 人工调整日志", "en": "# Review log"}

_MANIFEST_RE = re.compile(
    r"^(?P<slug>.+?)-(?P<series>conflict-moves|moves|removals|undo)-"
    r"(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.tsv$"
)

#: Manifest statuses that mean the action really happened.
DONE_STATUSES = ("MOVED", "TRASHED", "DELETED", "RESTORED")


@dataclass
class RunInfo:
    """One past run, read from a manifest file name and its rows."""

    path: Path
    series: str
    timestamp: Optional[datetime]
    moved_at: str
    rows: int
    done: int
    bytes: int = 0
    statuses: Dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------
# names and small helpers
# --------------------------------------------------------------------------


def safe_field(value: Any) -> str:
    """Flatten a value so it cannot break the tab separated layout."""

    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def slug(name: str) -> str:
    """``"Downloads"`` -> ``"downloads"``; used as the manifest name prefix."""

    folded = str(name).strip().casefold()
    folded = re.sub(r"[\s/\\]+", "-", folded)
    folded = re.sub(r"[^0-9a-z一-鿿._-]+", "", folded)
    folded = folded.strip("-._")
    return folded or "folder"


def timestamp_text(ts: datetime) -> str:
    return ts.strftime(TIMESTAMP_FORMAT)


def manifest_path(managed: Path, root_name: str, series: str, ts: datetime) -> Path:
    """``downloads-moves-2026-09-02_10-20-11.tsv`` inside the managed directory."""

    if series not in MANIFEST_SERIES:
        raise ValueError("unknown manifest series: {0}".format(series))
    return Path(managed) / "{0}-{1}-{2}.tsv".format(
        slug(root_name), series, timestamp_text(ts)
    )


def tag_list_path(managed: Path, root_name: str, ts: datetime) -> Path:
    """``downloads-move-tags-2026-09-02_10-20-11.txt``."""

    return Path(managed) / "{0}-{1}-{2}.txt".format(
        slug(root_name), TAG_LIST_SERIES, timestamp_text(ts)
    )


def audit_path(managed: Path) -> Path:
    return Path(managed) / AUDIT_NAME


def review_log_name(lang: str) -> str:
    return REVIEW_LOG_NAMES.get(lang or "en", REVIEW_LOG_NAMES["en"])


def _atomic_write(path: Path, text: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(temporary), str(target))
    return target


# --------------------------------------------------------------------------
# manifests
# --------------------------------------------------------------------------


def write_manifest(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    """Write every row under :data:`MANIFEST_COLUMNS`, atomically."""

    lines = ["\t".join(MANIFEST_COLUMNS)]
    for row in rows:
        lines.append(
            "\t".join(safe_field(row.get(column, "")) for column in MANIFEST_COLUMNS)
        )
    return _atomic_write(path, "\n".join(lines) + "\n")


def read_manifest(path: Path) -> List[Dict[str, str]]:
    """Read a manifest by its own header line, so seven column files still parse."""

    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(str(target))
    text = target.read_text(encoding="utf-8")
    lines = [line for line in text.split("\n") if line != ""]
    if not lines:
        return []
    header = lines[0].split("\t")
    rows: List[Dict[str, str]] = []
    for line in lines[1:]:
        fields = line.split("\t")
        row: Dict[str, str] = {}
        for index, column in enumerate(header):
            row[column] = fields[index] if index < len(fields) else ""
        rows.append(row)
    return rows


def write_tag_list(path: Path, portable_paths: Iterable[str]) -> Path:
    items = [safe_field(item) for item in portable_paths]
    return _atomic_write(path, "\n".join(items) + ("\n" if items else ""))


def read_tag_list(path: Path) -> List[str]:
    target = Path(path)
    if not target.is_file():
        return []
    return [
        line.strip()
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------
# audit log
# --------------------------------------------------------------------------


def append_audit(results: Iterable[Mapping[str, Any]], path: Path) -> Path:
    """Append audit records; this is the authority when a run is interrupted."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for record in results:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return target


def read_audit(path: Path) -> List[Dict[str, Any]]:
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(str(target))
    records: List[Dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


# --------------------------------------------------------------------------
# human review log
# --------------------------------------------------------------------------


def append_review_log(
    managed: Path,
    lang: str,
    day: date,
    bullets: Sequence[str],
    *,
    name: Optional[str] = None,
) -> Path:
    """Add ``bullets`` under a ``## YYYY-MM-DD`` heading, creating what is missing."""

    target = Path(managed) / (name or review_log_name(lang))
    target.parent.mkdir(parents=True, exist_ok=True)
    heading = "## {0}".format(day.isoformat())
    items = ["- {0}".format(safe_field(bullet)) for bullet in bullets if str(bullet).strip()]
    if not items:
        return target

    if target.is_file():
        lines = target.read_text(encoding="utf-8").split("\n")
    else:
        lines = [REVIEW_LOG_TITLES.get(lang or "en", REVIEW_LOG_TITLES["en"]), ""]

    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index
            break

    if start is None:
        while lines and lines[-1].strip() == "":
            lines.pop()
        lines.extend(["", heading, ""])
        lines.extend(items)
        lines.append("")
    else:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if lines[index].startswith("## "):
                end = index
                break
        section = lines[start:end]
        while section and section[-1].strip() == "":
            section.pop()
        section.extend(items)
        section.append("")
        lines[start:end] = section

    target.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return target


# --------------------------------------------------------------------------
# last run
# --------------------------------------------------------------------------


def _parse_timestamp(text: str) -> Optional[datetime]:
    try:
        return datetime.strptime(text, TIMESTAMP_FORMAT)
    except (ValueError, TypeError):
        return None


def _row_bytes(row: Mapping[str, str]) -> int:
    try:
        return int(str(row.get("size_bytes", "") or 0))
    except ValueError:
        return 0


def run_info(path: Path) -> Optional[RunInfo]:
    """Read one manifest file into a :class:`RunInfo`, or ``None`` if it is not one."""

    target = Path(path)
    match = _MANIFEST_RE.match(target.name)
    if match is None:
        return None
    try:
        rows = read_manifest(target)
    except (OSError, ValueError):
        rows = []
    statuses: Dict[str, int] = {}
    moved_at = ""
    total = 0
    done = 0
    for row in rows:
        status = str(row.get("status", "")).strip().upper()
        statuses[status] = statuses.get(status, 0) + 1
        stamp = str(row.get("moved_at", "")).strip()
        if stamp > moved_at:
            moved_at = stamp
        if status in DONE_STATUSES:
            done += 1
            total += _row_bytes(row)
    return RunInfo(
        path=target,
        series=match.group("series"),
        timestamp=_parse_timestamp(match.group("ts")),
        moved_at=moved_at or match.group("ts").replace("_", " ").replace("-", "-"),
        rows=len(rows),
        done=done,
        bytes=total,
        statuses=statuses,
    )


def list_runs(managed: Path, *, series: Sequence[str] = TIDY_SERIES) -> List[RunInfo]:
    """Every manifest in ``managed``, newest first, judged only by file names."""

    folder = Path(managed)
    if not folder.is_dir():
        return []
    found: List[RunInfo] = []
    try:
        names = sorted(entry.name for entry in folder.iterdir() if entry.is_file())
    except OSError:
        return []
    for name in names:
        match = _MANIFEST_RE.match(name)
        if match is None or match.group("series") not in series:
            continue
        info = run_info(folder / name)
        if info is not None:
            found.append(info)
    found.sort(
        key=lambda item: (item.timestamp or datetime.min, item.path.name), reverse=True
    )
    return found


def latest_run(managed: Path, *, series: Sequence[str] = TIDY_SERIES) -> Optional[RunInfo]:
    """The most recent run, read from manifest names only; folder mtimes lie."""

    runs = list_runs(managed, series=series)
    return runs[0] if runs else None
