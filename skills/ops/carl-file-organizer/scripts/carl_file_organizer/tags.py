"""macOS Finder tags: read, write, add, remove, and clear the temporary one.

The temporary tag is how a person sees what one run touched: open Finder, click
the tag, and there is the whole batch.  Tagging is a courtesy, never a
precondition, so every failure here warns on stderr and returns False instead
of stopping a batch that already moved files.

Everywhere except macOS these functions are honest no-ops.

This module also owns the ``clear-tags`` subcommand.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

TAG_XATTR = "com.apple.metadata:_kMDItemUserTags"

#: Finder stores a colour as a second line inside the tag string.
COLOR_SEPARATOR = "\n"

TAG_LIST_GLOB = "*-move-tags-*.txt"

MESSAGES = {
    "cleared": {"zh": "已清除标签 {tag}：{count} 项", "en": "Cleared tag {tag} from {count} item(s)"},
    "dry_run": {
        "zh": "预演：会清除标签 {tag}，共 {count} 项，没有真的改动",
        "en": "Dry run: would clear tag {tag} from {count} item(s); nothing changed",
    },
    "unsupported": {
        "zh": "这台机器不支持 Finder 标签，没有可清除的东西",
        "en": "Finder tags are not available on this machine; nothing to clear",
    },
    "no_lists": {
        "zh": "管理目录里没有标签清单（{glob}），可以用 --from 指定一个",
        "en": "No tag list ({glob}) in the managed folder; pass --from to name one",
    },
    "missing": {"zh": "找不到：{path}", "en": "missing: {path}"},
    "summary": {
        "zh": "检查 {checked} 项，清除 {cleared} 项，跳过 {skipped} 项，失败 {failed} 项",
        "en": "checked {checked}, cleared {cleared}, skipped {skipped}, failed {failed}",
    },
}


@dataclass
class ClearReport:
    tag: str
    dry_run: bool
    checked: int = 0
    cleared: int = 0
    skipped: int = 0
    missing: int = 0
    failed: int = 0
    lists: List[Path] = field(default_factory=list)
    details: List[Dict[str, Any]] = field(default_factory=list)


def message(key: str, lang: str = "en", **kw: Any) -> str:
    entry = MESSAGES.get(key, {})
    template = entry.get(lang) or entry.get("en") or key
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError):
        return template


def _warn(text: str) -> None:
    print("tag_warning: {0}".format(text), file=sys.stderr)


def supported() -> bool:
    """True only on macOS with the ``xattr`` tool available."""

    return sys.platform == "darwin" and bool(shutil.which("xattr"))


# --------------------------------------------------------------------------
# raw tag access
# --------------------------------------------------------------------------


def read_tags(path: Path) -> List[str]:
    """Every Finder tag on ``path``, colour suffix included, or an empty list."""

    if not supported():
        return []
    try:
        result = subprocess.run(
            ["xattr", "-p", "-x", TAG_XATTR, str(path)],
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        _warn("{0}\t{1}".format(path, error))
        return []
    if result.returncode != 0:
        return []
    hex_text = "".join(result.stdout.split())
    if not hex_text:
        return []
    try:
        tags = plistlib.loads(bytes.fromhex(hex_text))
    except Exception:  # noqa: BLE001 - a malformed xattr is not worth a traceback
        return []
    if not isinstance(tags, list):
        return []
    return [str(tag) for tag in tags]


def write_tags(path: Path, tags: Sequence[str]) -> bool:
    """Replace the tag list on ``path``; warn and return False on any failure."""

    if not supported():
        return False
    try:
        payload = plistlib.dumps([str(tag) for tag in tags], fmt=plistlib.FMT_BINARY).hex()
        subprocess.run(
            ["xattr", "-w", "-x", TAG_XATTR, payload, str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        _warn("{0}\t{1}".format(path, error))
        return False
    return True


def add_tag(path: Path, tag: str) -> bool:
    """Add one tag, keeping the others.  False means nothing was written."""

    if not supported():
        return False
    current = read_tags(path)
    if any(_tag_name(item) == tag for item in current):
        return False
    return write_tags(path, list(current) + [tag])


def remove_tag(path: Path, tag: str) -> bool:
    """Drop one tag, keeping the others.  False means nothing was written."""

    if not supported():
        return False
    current = read_tags(path)
    remaining = [item for item in current if _tag_name(item) != tag]
    if len(remaining) == len(current):
        return False
    return write_tags(path, remaining)


def _tag_name(tag: str) -> str:
    """``"Red\\n6"`` -> ``"Red"``: strip the colour line Finder appends."""

    return str(tag).split(COLOR_SEPARATOR, 1)[0]


def user_tags(source: Any, transient: Iterable[str] = ()) -> List[str]:
    """Tags a person put there: colours stripped, our temporary tag removed.

    ``source`` is either a path to read or an already read list of tags.
    """

    if isinstance(source, (str, os.PathLike)):
        raw: Iterable[str] = read_tags(Path(source))
    else:
        raw = source or []
    drop = {str(item) for item in transient}
    names: List[str] = []
    for tag in raw:
        name = _tag_name(tag)
        if not name or name in drop or name in names:
            continue
        names.append(name)
    return names


# --------------------------------------------------------------------------
# clear-tags
# --------------------------------------------------------------------------


def clear_tags(paths: Iterable[Path], tag: str, *, dry_run: bool = False) -> ClearReport:
    """Remove ``tag`` from every path that still has it."""

    report = ClearReport(tag=tag, dry_run=dry_run)
    for item in paths:
        target = Path(item)
        report.checked += 1
        if not os.path.lexists(str(target)):
            report.missing += 1
            report.details.append({"path": str(target), "status": "missing"})
            continue
        current = read_tags(target)
        if not any(_tag_name(entry) == tag for entry in current):
            report.skipped += 1
            report.details.append({"path": str(target), "status": "untagged"})
            continue
        if dry_run:
            report.cleared += 1
            report.details.append({"path": str(target), "status": "would-clear"})
            continue
        if remove_tag(target, tag):
            report.cleared += 1
            report.details.append({"path": str(target), "status": "cleared"})
        else:
            report.failed += 1
            report.details.append({"path": str(target), "status": "failed"})
    return report


def find_tag_lists(managed: Path) -> List[Path]:
    """Every ``*-move-tags-*.txt`` written by past runs, oldest first."""

    folder = Path(managed)
    if not folder.is_dir():
        return []
    return sorted(folder.glob(TAG_LIST_GLOB))


def paths_from_lists(lists: Sequence[Path], *, home: Optional[Path] = None) -> List[Path]:
    """Expand the ``$HOME/...`` lines of the given tag lists, in order, deduped."""

    from . import manifest as manifest_module
    from . import paths as paths_module

    seen = set()
    found: List[Path] = []
    for source in lists:
        for line in manifest_module.read_tag_list(Path(source)):
            expanded = paths_module.expand_portable(line, home)
            key = str(expanded)
            if key in seen:
                continue
            seen.add(key)
            found.append(expanded)
    return found


def run(args: Any) -> int:
    """``carl-file-organizer clear-tags [dir] [--from list]... [--all-lists] [--tag NAME]``."""

    from . import config as config_module
    from . import paths as paths_module

    root = paths_module.refuse_root(
        args.source, allow_outside_home=getattr(args, "allow_outside_home", False)
    )
    cfg = config_module.resolve_config(root, lang=getattr(args, "lang", None))
    lang = cfg.lang
    managed = config_module.managed_dir(cfg)
    tag = getattr(args, "tag", None) or config_module.transient_tag(cfg)

    chosen: List[Path] = []
    explicit = list(getattr(args, "from_lists", None) or [])
    if explicit:
        chosen.extend(Path(item) for item in explicit)
    if getattr(args, "all_lists", False) or not explicit:
        for candidate in find_tag_lists(managed):
            if candidate not in chosen:
                chosen.append(candidate)

    missing_lists = [item for item in chosen if not Path(item).is_file()]
    for item in missing_lists:
        print(message("missing", lang, path=item), file=sys.stderr)
    chosen = [item for item in chosen if Path(item).is_file()]

    if not chosen:
        print(message("no_lists", lang, glob=TAG_LIST_GLOB), file=sys.stderr)
        return 2

    if not supported():
        print(message("unsupported", lang))
        return 0

    targets = paths_from_lists(chosen)
    report = clear_tags(targets, tag, dry_run=bool(getattr(args, "dry_run", False)))
    report.lists = chosen

    for entry in report.details:
        print("{0}\t{1}".format(entry["status"], entry["path"]))
    key = "dry_run" if report.dry_run else "cleared"
    print(message(key, lang, tag=tag, count=report.cleared))
    print(
        message(
            "summary",
            lang,
            checked=report.checked,
            cleared=report.cleared,
            skipped=report.skipped + report.missing,
            failed=report.failed,
        )
    )
    return 2 if report.failed else 0
