"""Pairing, duplicate detection and regenerable build output.

Three questions get answered here, all of them read-only:

    pair_archives     is this .zip the same thing as the folder next to it
    find_duplicates   are two files the same file wearing different names
    find_regenerable  is this subfolder something a build can recreate

Nothing here decides anything.  Each function returns raw groups, and the
planner turns them into actions and options.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import classifier
from .ids import subject_id as _subject_id
from .scanner import DirStats, Entry, dir_stats_bounded, split_suffix

#: How a name gains a copy marker: "foo (1).pdf", "foo_1.pdf", "Archive 2".
COPY_PATTERNS = (
    re.compile(r"^(?P<base>.+?) \((?P<n>\d+)\)(?P<ext>\.[^.]+)?$"),
    re.compile(r"^(?P<base>.+?)_(?P<n>\d+)(?P<ext>\.[^.]+)?$"),
    re.compile(r"^(?P<base>.+?) (?P<n>\d+)$"),
)

DEFAULT_HASH_MAX_BYTES = 2 * 1024 * 1024 * 1024


@dataclass
class RawGroup:
    kind: str  # "pair" | "duplicate"
    stem: str
    evidence: str  # "name" | "sha256" | "name-pattern"
    members: List[Entry]
    sha256: Optional[str] = None
    display: str = ""
    group_id: str = ""


@dataclass
class RegenerableHit:
    path: Path
    name: str
    owner: Entry  # the top level directory it was found inside
    relative: str  # "web-prototype/node_modules"
    dir_stats: DirStats
    modified_ns: int = 0
    subject_id: str = ""
    age_hours: int = 0


# ---------------------------------------------------------------------------
# name arithmetic
# ---------------------------------------------------------------------------


def copy_base(name: str) -> Tuple[str, bool]:
    """``"foo (1).pdf"`` -> ``("foo.pdf", True)``; unchanged names return False."""

    text = str(name)
    for pattern in COPY_PATTERNS:
        match = pattern.match(text)
        if match:
            base = match.group("base")
            ext = match.groupdict().get("ext") or ""
            return base + ext, True
    return text, False


def _strip_copy_marker(name: str) -> str:
    base, _found = copy_base(name)
    return base


def archive_stem(name: str, config: Any = None) -> Optional[str]:
    """Folded stem of an archive file name, or ``None`` when it is not an archive."""

    text = str(name)
    stem, suffix = split_suffix(text)
    if not suffix:
        return None
    if config is not None:
        if not classifier.is_archive_suffix(suffix, config):
            return None
    elif suffix not in {".zip", ".tar.gz", ".tgz", ".tar", ".7z", ".rar", ".gz", ".xz", ".bz2"}:
        return None
    return _strip_copy_marker(stem).casefold()


def dir_stem(name: str) -> str:
    """``"Archive (1)"`` and ``"Archive 2"`` both fold down to ``"archive"``."""

    return _strip_copy_marker(str(name)).casefold()


def file_sha256(path: Path, *, max_bytes: int = DEFAULT_HASH_MAX_BYTES) -> Optional[str]:
    """Digest of a regular file; ``None`` when it is too big or unreadable."""

    try:
        size = os.path.getsize(str(path))
    except OSError:
        return None
    if size > max_bytes:
        return None
    digest = hashlib.sha256()
    try:
        with open(str(path), "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# pairing
# ---------------------------------------------------------------------------


def pair_archives(entries: Sequence[Entry], config: Any = None) -> List[RawGroup]:
    """An archive and an extracted folder that share a stem belong together."""

    buckets: Dict[str, Dict[str, List[Entry]]] = {}
    for entry in entries:
        if entry.kind == "dir":
            stem = dir_stem(entry.name)
            side = "dirs"
        else:
            stem = archive_stem(entry.name, config)
            side = "files"
            if stem is None:
                continue
        if not stem:
            continue
        buckets.setdefault(stem, {"dirs": [], "files": []})[side].append(entry)

    groups: List[RawGroup] = []
    for stem in sorted(buckets):
        bucket = buckets[stem]
        if not bucket["dirs"] or not bucket["files"]:
            continue
        members = sorted(bucket["dirs"], key=lambda item: item.name.casefold())
        members += sorted(bucket["files"], key=lambda item: item.name.casefold())
        groups.append(
            RawGroup(
                kind="pair",
                stem=stem,
                evidence="name",
                members=members,
                display=members[0].name,
            )
        )
    return groups


# ---------------------------------------------------------------------------
# duplicates
# ---------------------------------------------------------------------------


def find_duplicates(
    entries: Sequence[Entry],
    *,
    hash_duplicates: bool = False,
    hash_max_bytes: int = DEFAULT_HASH_MAX_BYTES,
    exclude: Optional[Sequence[str]] = None,
) -> List[RawGroup]:
    """Byte-identical files first, then names that merely look like copies."""

    skip = set(exclude or ())
    files = [
        entry
        for entry in entries
        if entry.kind == "file" and entry.subject_id not in skip and entry.size_bytes > 0
    ]

    groups: List[RawGroup] = []
    hashed: Dict[str, List[Entry]] = {}
    claimed: set = set()

    if hash_duplicates:
        by_size: Dict[int, List[Entry]] = {}
        for entry in files:
            by_size.setdefault(entry.size_bytes, []).append(entry)
        for size in sorted(by_size):
            candidates = by_size[size]
            if len(candidates) < 2:
                continue
            for entry in candidates:
                digest = file_sha256(entry.path, max_bytes=hash_max_bytes)
                if digest is None:
                    continue
                hashed.setdefault(digest, []).append(entry)
        for digest in sorted(hashed):
            members = hashed[digest]
            if len(members) < 2:
                continue
            ordered = sorted(members, key=lambda item: item.name.casefold())
            for entry in ordered:
                claimed.add(entry.subject_id)
            groups.append(
                RawGroup(
                    kind="duplicate",
                    stem=ordered[0].name,
                    evidence="sha256",
                    members=ordered,
                    sha256=digest,
                    display=ordered[0].name,
                )
            )

    by_base: Dict[str, List[Entry]] = {}
    for entry in files:
        if entry.subject_id in claimed:
            continue
        base, _marked = copy_base(entry.name)
        by_base.setdefault(base.casefold(), []).append(entry)
    for base in sorted(by_base):
        members = by_base[base]
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda item: item.name.casefold())
        groups.append(
            RawGroup(
                kind="duplicate",
                stem=ordered[0].name,
                evidence="name-pattern",
                members=ordered,
                display=ordered[0].name,
            )
        )
    return groups


# ---------------------------------------------------------------------------
# regenerable build output
# ---------------------------------------------------------------------------


def find_regenerable(
    entries: Sequence[Entry],
    config: Any,
    *,
    max_depth: int = 3,
    now: Any = None,
    dir_limits: Optional[Dict[str, Any]] = None,
) -> List[RegenerableHit]:
    """Walk top level folders looking for ``node_modules`` and friends.

    Depth is counted from the top level folder, so ``proj/node_modules`` is one
    and ``proj/a/b/c/node_modules`` is four.  ``.git`` and anything in a no-go
    zone are never entered, and a match is never descended into.
    """

    from . import paths as paths_module

    limits = dir_limits or {}
    hits: List[RegenerableHit] = []
    for entry in entries:
        if entry.kind != "dir":
            continue
        if paths_module.is_forbidden(entry.path, config):
            continue
        stack: List[Tuple[Path, int]] = [(entry.path, 0)]
        while stack:
            current, depth = stack.pop()
            if depth >= max_depth:
                continue
            try:
                children = sorted(os.scandir(str(current)), key=lambda item: item.name)
            except OSError:
                continue
            for child in children:
                name = child.name
                try:
                    if child.is_symlink() or not child.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                if name == ".git":
                    continue
                child_path = Path(child.path)
                if classifier.is_regenerable_name(name, config):
                    stats = dir_stats_bounded(
                        child_path,
                        int(limits.get("max_entries", 50000)),
                        float(limits.get("time_budget_s", 1.5)),
                    )
                    try:
                        child_stat = child.stat(follow_symlinks=False)
                        modified_ns = child_stat.st_mtime_ns
                        stat_size = child_stat.st_size
                    except OSError:
                        modified_ns = entry.modified_ns
                        stat_size = 0
                    relative = "{0}/{1}".format(
                        entry.name, child_path.relative_to(entry.path).as_posix()
                    )
                    age_hours = entry.age_hours
                    if now is not None:
                        seconds = now.timestamp() - (modified_ns / 1_000_000_000)
                        age_hours = int(seconds // 3600) if seconds > 0 else 0
                    hits.append(
                        RegenerableHit(
                            path=child_path,
                            name=name,
                            owner=entry,
                            relative=relative,
                            dir_stats=stats,
                            modified_ns=modified_ns,
                            subject_id=_subject_id(child_path, "dir", stat_size, modified_ns),
                            age_hours=age_hours,
                        )
                    )
                    continue
                if paths_module.is_forbidden(child_path, config):
                    continue
                stack.append((child_path, depth + 1))
    hits.sort(key=lambda hit: hit.relative)
    return hits
