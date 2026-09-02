"""Read-only top level scan: one Entry per visible item, nothing is opened.

The scan is deliberately shallow.  Partition folders and the managed folder are
boundaries, hidden files and symlinks are ignored, and directory sizes are
measured with both an entry cap and a time budget so a runaway folder can never
stall a plan.

Frozen for every work package::

    scan_top_level(root, config, *, now, dir_sizes=True) -> (entries, notes)
    dir_stats_bounded(path, max_entries=50000, time_budget_s=1.5) -> DirStats
    Entry.subject_id                # from carl_file_organizer.ids.subject_id

One rule worth stating loudly: ``Entry.size_bytes`` for a directory is the
walked total, but its ``subject_id`` is computed from the raw ``stat`` size.
Walked totals are capped and would change under ``--no-dir-sizes``, so mixing
them into the identity would invalidate every directory action; the executor
recomputes the same raw-stat identity before it touches anything.
"""

from __future__ import annotations

import fnmatch
import os
import plistlib
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from . import config as config_module
from .ids import subject_id as _subject_id
from .paths import DOUBLE_SUFFIXES, split_suffix

#: Compound suffixes and the split that honours them live in :mod:`paths`, which
#: needs them to build conflict names; they are re-exported here because this is
#: where every caller already looks for them.
__all_reexported__ = ("DOUBLE_SUFFIXES", "split_suffix")

#: Carl File Organizer's own artefacts, skipped so a downloaded approval file is not
#: treated as a loose document on the next run.
ARTIFACT_GLOBS = ("carl-file-organizer-*.json",)

TAG_XATTR = "com.apple.metadata:_kMDItemUserTags"

DEFAULT_MAX_ENTRIES = 50000
DEFAULT_TIME_BUDGET_S = 1.5


@dataclass
class DirStats:
    files: int
    bytes: int
    truncated: bool

    def as_dict(self) -> dict:
        return {"files": self.files, "bytes": self.bytes, "truncated": self.truncated}


@dataclass
class Entry:
    path: Path
    name: str
    kind: str  # "file" | "dir"
    size_bytes: int
    modified_ns: int
    age_hours: int
    suffix: str
    tags: List[str] = field(default_factory=list)
    dir_stats: Optional[DirStats] = None
    subject_id: str = ""

    @property
    def is_dir(self) -> bool:
        return self.kind == "dir"


@dataclass
class ScanNotes:
    """What the scan deliberately did not look at."""

    skipped_hidden: int = 0
    skipped_symlinks: int = 0
    skipped_partitions: int = 0
    skipped_artifacts: int = 0
    unreadable: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# names and suffixes
# ---------------------------------------------------------------------------


def suffix_of(name: str) -> str:
    return split_suffix(name)[1]


def stem_of(name: str) -> str:
    return split_suffix(name)[0]


def is_artifact_name(name: str) -> bool:
    if name == config_module.DOTFILE_NAME:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in ARTIFACT_GLOBS)


# ---------------------------------------------------------------------------
# Finder tags
# ---------------------------------------------------------------------------


def read_tags(path: Path) -> List[str]:
    """Finder tags without their ``\\n<colour>`` suffix; ``[]`` off macOS."""

    if sys.platform != "darwin":
        return []
    try:
        result = subprocess.run(
            ["xattr", "-p", "-x", TAG_XATTR, str(path)],
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    hex_text = "".join(result.stdout.split())
    if not hex_text:
        return []
    try:
        tags = plistlib.loads(bytes.fromhex(hex_text))
    except Exception:  # noqa: BLE001 - a corrupt xattr is not worth a crash
        return []
    if not isinstance(tags, list):
        return []
    cleaned = []
    for tag in tags:
        text = str(tag).split("\n", 1)[0].strip()
        if text:
            cleaned.append(text)
    return cleaned


def user_tags(tags: Sequence[str], transient: Sequence[str]) -> List[str]:
    """Drop Carl File Organizer's own temporary tag in every language spelling."""

    blocked = {str(item).casefold() for item in transient}
    return [tag for tag in tags if tag.casefold() not in blocked]


# ---------------------------------------------------------------------------
# bounded directory statistics
# ---------------------------------------------------------------------------


def dir_stats_bounded(
    path: Path,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    time_budget_s: float = DEFAULT_TIME_BUDGET_S,
) -> DirStats:
    """Count files and bytes under ``path`` with a hard entry and time cap."""

    started = time.monotonic()
    files = 0
    total = 0
    seen = 0
    truncated = False
    stack: List[str] = [str(path)]

    while stack:
        if seen >= max_entries or (time.monotonic() - started) > time_budget_s:
            truncated = True
            break
        current = stack.pop()
        try:
            iterator = os.scandir(current)
        except OSError:
            truncated = True
            continue
        with iterator:
            while True:
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                except OSError:
                    truncated = True
                    break
                seen += 1
                if seen >= max_entries or (time.monotonic() - started) > time_budget_s:
                    truncated = True
                    break
                try:
                    if item.is_symlink():
                        continue
                    if item.is_dir(follow_symlinks=False):
                        stack.append(item.path)
                        continue
                    stat = item.stat(follow_symlinks=False)
                except OSError:
                    truncated = True
                    continue
                files += 1
                total += stat.st_size
    return DirStats(files=files, bytes=total, truncated=truncated)


# ---------------------------------------------------------------------------
# the scan itself
# ---------------------------------------------------------------------------


def _age_hours(modified_ns: int, now: datetime) -> int:
    seconds = now.timestamp() - (modified_ns / 1_000_000_000)
    if seconds <= 0:
        return 0
    return int(seconds // 3600)


def make_entry(
    path: Path,
    *,
    now: datetime,
    dir_sizes: bool = True,
    stat_result: Any = None,
    dir_limits: Optional[dict] = None,
    read_finder_tags: bool = True,
) -> Entry:
    """Build one :class:`Entry`; ``path`` must already be known to be safe."""

    stat = stat_result if stat_result is not None else os.stat(str(path), follow_symlinks=False)
    kind = "dir" if os.path.isdir(str(path)) else "file"
    limits = dir_limits or {}
    stats = None
    if kind == "dir" and dir_sizes:
        stats = dir_stats_bounded(
            path,
            int(limits.get("max_entries", DEFAULT_MAX_ENTRIES)),
            float(limits.get("time_budget_s", DEFAULT_TIME_BUDGET_S)),
        )
    size = stats.bytes if stats is not None else (0 if kind == "dir" else stat.st_size)
    modified_ns = stat.st_mtime_ns
    return Entry(
        path=path,
        name=path.name,
        kind=kind,
        size_bytes=size,
        modified_ns=modified_ns,
        age_hours=_age_hours(modified_ns, now),
        suffix=suffix_of(path.name) if kind == "file" else "",
        tags=read_tags(path) if read_finder_tags else [],
        dir_stats=stats,
        # The identity always uses the raw stat size, never the walked size:
        # directory totals are capped and would change with --no-dir-sizes.
        subject_id=_subject_id(path, kind, stat.st_size, modified_ns),
    )


def scan_top_level(
    root: Path,
    config: Any,
    *,
    now: datetime,
    dir_sizes: bool = True,
    read_finder_tags: bool = True,
) -> Tuple[List[Entry], ScanNotes]:
    """One level deep, sorted by name; partitions and hidden items are skipped."""

    base = Path(root)
    notes = ScanNotes()
    partitions = {str(name) for name in config_module.partition_dir_names(config)}
    limits = {
        "max_entries": DEFAULT_MAX_ENTRIES,
        "time_budget_s": DEFAULT_TIME_BUDGET_S,
    }

    entries: List[Entry] = []
    try:
        children = sorted(base.iterdir(), key=lambda item: item.name.casefold())
    except OSError as error:
        raise ValueError("cannot read {0}: {1}".format(base, error)) from error

    for path in children:
        name = path.name
        if name.startswith("."):
            notes.skipped_hidden += 1
            continue
        if path.is_symlink():
            notes.skipped_symlinks += 1
            continue
        if name in partitions:
            notes.skipped_partitions += 1
            continue
        if is_artifact_name(name):
            notes.skipped_artifacts += 1
            continue
        try:
            stat = os.stat(str(path), follow_symlinks=False)
        except OSError:
            notes.unreadable.append(name)
            continue
        if not (path.is_dir() or path.is_file()):
            notes.unreadable.append(name)
            continue
        entries.append(
            make_entry(
                path,
                now=now,
                dir_sizes=dir_sizes,
                stat_result=stat,
                dir_limits=limits,
                read_finder_tags=read_finder_tags,
            )
        )
    return entries, notes
