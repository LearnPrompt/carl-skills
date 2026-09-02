"""The safety net: who else is still using this path.

Moving a file is reversible, but a launch agent that hard-codes its path is not
going to notice.  So before anything is proposed, every candidate is asked four
read-only questions, each with a timeout, each degrading to "unknown" rather
than raising:

    G1 open_handles        is a process holding it open right now
    G2 config_references   does launchd, cron or a shell rc file name it
    G3 incoming_symlinks   does a symlink somewhere else point into it
    G4 dir_shape           is it a worktree, a repo, a virtualenv, a project
    G5 recently_modified   was it touched in the last ten minutes

Every entry point takes an injection hook (``lsof_runner``, ``reference_files``,
``scan_roots``, ``git_status_runner``) so tests never touch the real machine.
"""

from __future__ import annotations

import os
import shutil
import stat as stat_module
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import paths as paths_module

#: Files that routinely hard-code a path, relative to the home directory.
SHELL_RC_FILES = (
    ".zshrc",
    ".zprofile",
    ".zshenv",
    ".bashrc",
    ".bash_profile",
    ".profile",
)

LAUNCH_DIRS_HOME = ("Library/LaunchAgents",)
LAUNCH_DIRS_ABSOLUTE = ("/Library/LaunchAgents", "/Library/LaunchDaemons")

#: Daemons that merely look at a file.  Spotlight opens everything that lands in
#: a download folder within seconds, so without this list a fresh download is
#: always "in use" and the plan proposes nothing at all.  These processes read,
#: index or preview; none of them breaks when a path changes.
#:
#: Finder is on the list for the same reason: selecting a file in a Finder window
#: hands it to the QuickLook thumbnail agent, and a folder the user is looking at
#: while the plan is built would otherwise come back held open by the very act of
#: looking.  Names are matched as prefixes because lsof truncates its COMMAND
#: column somewhere between nine and fifteen characters, so the thumbnail agent
#: arrives as ``com.apple.quicklook.ThumbnailsA`` more often than under its full
#: name.
OBSERVER_COMMANDS = (
    "mdworker",
    "mds",
    "mds_stores",
    "mdimport",
    "mdsync",
    "mdbulkimport",
    "quicklookd",
    "qlmanage",
    "QuickLookUIService",
    "com.apple.quicklook.ThumbnailsAgent",
    "com.apple.quicklook.ThumbnailsA",
    "Finder",
    "Spotlight",
    "suggestd",
    "photoanalysisd",
    "cloudd",
    "bird",
    "fseventsd",
    "backupd",
    "XProtect",
    "diskimages-helper",
    "revisiond",
    "distnoted",
)

#: The same list, folded once, so the per-handle check stays a plain lookup.
_OBSERVER_PREFIXES = tuple(sorted({name.casefold() for name in OBSERVER_COMMANDS}))


def is_observer(command: str) -> bool:
    """True for a daemon that only reads the file and never owns its path.

    The match is on the prefix: lsof gives its COMMAND column a fixed width and
    cuts long names off, so a truncated ``com.apple.quicklook.ThumbnailsA`` has
    to read the same as the whole name.
    """

    folded = str(command or "").casefold()
    if not folded:
        return False
    return folded.startswith(_OBSERVER_PREFIXES)


MAX_REFERENCE_FILES = 400
MAX_REFERENCE_BYTES = 2 * 1024 * 1024
SYMLINK_SCAN_BUDGET_S = 2.0
SYMLINK_SCAN_MAX_ENTRIES = 40000


@dataclass
class OpenHandles:
    handles: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "ok"  # "ok" | "unknown"

    def __bool__(self) -> bool:
        return bool(self.handles)


@dataclass
class DirShape:
    labels: List[str] = field(default_factory=list)
    uncommitted: Optional[int] = None

    def __contains__(self, item: object) -> bool:
        return item in self.labels


# ---------------------------------------------------------------------------
# G1: open file handles
# ---------------------------------------------------------------------------


def _default_lsof_runner(argv: Sequence[str], timeout_s: float):
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout_s)


def _parse_lsof(text: str) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    seen = set()
    for _name, handle in _parse_lsof_pairs(text):
        marker = (handle["command"], handle["pid"])
        if marker in seen:
            continue
        seen.add(marker)
        found.append(handle)
    return found


def _parse_lsof_pairs(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """``[(reported path, {command, pid})]`` from ``lsof -F pcn`` output."""

    pairs: List[Tuple[str, Dict[str, Any]]] = []
    pid: Optional[int] = None
    command: Optional[str] = None
    for line in text.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            try:
                pid = int(value)
            except ValueError:
                pid = None
            command = None
        elif tag == "c":
            command = value
        elif tag == "n":
            if pid is None or is_observer(command or ""):
                continue
            pairs.append((value, {"command": command or "", "pid": pid}))
    return pairs


def lsof_possible() -> bool:
    """Can this machine answer "who has that file open" at all?

    Windows never can: there is no lsof, and the closest native answers
    (handle.exe, Restart Manager) need a download or an elevated process, so the
    honest answer is "unknown" rather than a silent "nobody".  That distinction
    matters because "nobody has it open" is what lets an item be moved, and
    guessing it would be the one lie this tool cannot afford.
    """

    if sys.platform == "win32":
        return False
    return shutil.which("lsof") is not None


def open_handles(
    path: Path,
    timeout_s: float = 5.0,
    *,
    lsof_runner: Optional[Callable[..., Any]] = None,
    is_dir: Optional[bool] = None,
) -> OpenHandles:
    """Ask lsof who has ``path`` open.  No lsof, or a timeout, means unknown."""

    runner = lsof_runner
    if runner is None:
        if not lsof_possible():
            return OpenHandles([], "unknown")
        runner = _default_lsof_runner

    directory = os.path.isdir(str(path)) if is_dir is None else bool(is_dir)
    if directory:
        argv = ["lsof", "-F", "pcn", "+d", str(path)]
    else:
        argv = ["lsof", "-F", "pcn", "--", str(path)]

    try:
        result = runner(argv, timeout_s)
    except subprocess.TimeoutExpired:
        return OpenHandles([], "unknown")
    except (OSError, subprocess.SubprocessError):
        return OpenHandles([], "unknown")
    except Exception:  # noqa: BLE001 - an injected runner must never break a plan
        return OpenHandles([], "unknown")

    stdout = getattr(result, "stdout", "") or ""
    returncode = getattr(result, "returncode", 0)
    if returncode not in (0, 1):
        return OpenHandles([], "unknown")
    return OpenHandles(_parse_lsof(stdout), "ok")


def probe_open_handles(
    file_paths: Sequence[Path],
    dir_paths: Sequence[Path] = (),
    timeout_s: float = 5.0,
    *,
    lsof_runner: Optional[Callable[..., Any]] = None,
) -> Dict[str, OpenHandles]:
    """One lsof call for all the files, one per directory.

    lsof is slow enough that asking it once per entry turns a plan into a
    coffee break, so the files go in a single batch and only directories,
    which need ``+d``, are asked one at a time.
    """

    results: Dict[str, OpenHandles] = {}
    runner = lsof_runner
    if runner is None:
        if not lsof_possible():
            for item in list(file_paths) + list(dir_paths):
                results[str(item)] = OpenHandles([], "unknown")
            return results
        runner = _default_lsof_runner

    files = [Path(item) for item in file_paths]
    for item in files:
        results[str(item)] = OpenHandles([], "ok")

    by_real = {}
    for item in files:
        try:
            by_real[os.path.realpath(str(item))] = str(item)
        except OSError:
            continue

    chunk = 150
    for start in range(0, len(files), chunk):
        batch = files[start : start + chunk]
        argv = ["lsof", "-F", "pcn", "--"] + [str(item) for item in batch]
        try:
            result = runner(argv, timeout_s)
        except Exception:  # noqa: BLE001 - unknown beats crashing
            for item in batch:
                results[str(item)] = OpenHandles([], "unknown")
            continue
        if getattr(result, "returncode", 0) not in (0, 1):
            for item in batch:
                results[str(item)] = OpenHandles([], "unknown")
            continue
        for reported, handle in _parse_lsof_pairs(getattr(result, "stdout", "") or ""):
            key = by_real.get(reported) or by_real.get(os.path.realpath(reported))
            if key is None:
                continue
            existing = results.setdefault(key, OpenHandles([], "ok"))
            marker = (handle["command"], handle["pid"])
            if marker not in {(h["command"], h["pid"]) for h in existing.handles}:
                existing.handles.append(handle)

    for item in dir_paths:
        results[str(item)] = open_handles(
            Path(item), timeout_s, lsof_runner=runner, is_dir=True
        )
    return results


# ---------------------------------------------------------------------------
# G2: configuration references
# ---------------------------------------------------------------------------


def path_forms(path: Path, home: Optional[Path] = None) -> List[str]:
    """The spellings a config file might use for the same path.

    Three everywhere: the absolute path, ``~/...`` and ``$HOME/...``.  On
    Windows there are four, because the absolute path has two spellings there
    and a config file carries whichever one its author typed: a ``.gitconfig``
    or a shell profile written under Git Bash or WSL says ``C:/Users/...``,
    while a PowerShell profile says ``C:\\Users\\...``.  Missing the other one
    means missing the reference, and a missed reference is a moved file that
    breaks something silently.
    """

    base = Path(home) if home is not None else Path.home()
    absolute = str(path)
    forms = [absolute]
    slashed = Path(absolute).as_posix()
    if slashed != absolute:
        forms.append(slashed)
    try:
        relative = Path(absolute).relative_to(base)
    except ValueError:
        return forms
    forms.append("~/" + relative.as_posix())
    forms.append("$HOME/" + relative.as_posix())
    return forms


def _read_lines(path: Path) -> Optional[List[str]]:
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_REFERENCE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return None


def default_reference_files(config: Any, home: Optional[Path] = None) -> List[Path]:
    """Launch agents, launch daemons, shell rc files, plus the user's own list."""

    base = Path(home) if home is not None else Path.home()
    found: List[Path] = []
    for relative in LAUNCH_DIRS_HOME:
        directory = base / relative
        try:
            found.extend(sorted(directory.glob("*.plist")))
        except OSError:
            continue
    for absolute in LAUNCH_DIRS_ABSOLUTE:
        try:
            found.extend(sorted(Path(absolute).glob("*.plist")))
        except OSError:
            continue
    for name in SHELL_RC_FILES:
        found.append(base / name)

    profile = getattr(config, "profile", config) or {}
    guard = profile.get("guard") if hasattr(profile, "get") else None
    extra = (guard or {}).get("reference_files") or ()
    for item in extra:
        found.append(paths_module.expand_portable(str(item), base).expanduser())
    return found[:MAX_REFERENCE_FILES]


def _crontab_text(crontab_runner: Optional[Callable[[], Any]]) -> Optional[List[str]]:
    runner = crontab_runner
    if runner is None:
        if shutil.which("crontab") is None:
            return None

        def runner():  # type: ignore[misc]
            return subprocess.run(
                ["crontab", "-l"], capture_output=True, text=True, timeout=3
            )

    try:
        result = runner()
    except Exception:  # noqa: BLE001 - no crontab is a normal machine, not an error
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    return (getattr(result, "stdout", "") or "").splitlines()


def load_reference_texts(
    config: Any,
    home: Optional[Path] = None,
    *,
    reference_files: Optional[Sequence[Any]] = None,
    crontab_runner: Optional[Callable[[], Any]] = None,
    include_crontab: bool = True,
) -> List[Tuple[str, List[str]]]:
    """Read every reference source once, so per-entry matching is pure string work."""

    base = Path(home) if home is not None else Path.home()
    if reference_files is None:
        candidates = default_reference_files(config, base)
    else:
        candidates = [Path(str(item)).expanduser() for item in reference_files]

    texts: List[Tuple[str, List[str]]] = []
    for candidate in candidates:
        lines = _read_lines(Path(candidate))
        if lines is None:
            continue
        texts.append((paths_module.portable(Path(candidate), base), lines))
    if include_crontab:
        cron = _crontab_text(crontab_runner)
        if cron:
            texts.append(("crontab", cron))
    return texts


def config_references(
    path: Path,
    config: Any,
    home: Optional[Path] = None,
    *,
    reference_files: Optional[Sequence[Any]] = None,
    crontab_runner: Optional[Callable[[], Any]] = None,
    texts: Optional[Sequence[Tuple[str, List[str]]]] = None,
) -> List[Dict[str, Any]]:
    """``[{file, line, form}]`` for every config file that names ``path``."""

    base = Path(home) if home is not None else Path.home()
    sources = (
        list(texts)
        if texts is not None
        else load_reference_texts(
            config,
            base,
            reference_files=reference_files,
            crontab_runner=crontab_runner,
            include_crontab=reference_files is None,
        )
    )
    forms = path_forms(Path(path), base)
    found: List[Dict[str, Any]] = []
    for display, lines in sources:
        for number, line in enumerate(lines, start=1):
            for form in forms:
                if form in line:
                    found.append({"file": display, "line": number, "form": form})
                    break
    return found


# ---------------------------------------------------------------------------
# G3: symlinks pointing in
# ---------------------------------------------------------------------------


def default_scan_roots(config: Any, home: Optional[Path] = None) -> List[Path]:
    base = Path(home) if home is not None else Path.home()
    profile = getattr(config, "profile", config) or {}
    guard = profile.get("guard") if hasattr(profile, "get") else None
    roots = (guard or {}).get("reference_scan_roots") or ()
    found: List[Path] = []
    for item in roots:
        found.append(paths_module.expand_portable(str(item), base).expanduser())
    return found


def symlink_index(
    config: Any,
    home: Optional[Path] = None,
    *,
    scan_roots: Optional[Sequence[Any]] = None,
    max_depth: int = 2,
) -> List[Tuple[str, Path]]:
    """Every symlink under the scan roots, with the real path it resolves to.

    Built once per plan; the per-entry check is then a containment test.
    """

    base = Path(home) if home is not None else Path.home()
    if scan_roots is None:
        roots = default_scan_roots(config, base)
    else:
        roots = [Path(str(item)).expanduser() for item in scan_roots]

    skip_names = {"Library", "Applications", ".Trash", "node_modules", ".git"}
    started = time.monotonic()
    seen_entries = 0
    index: List[Tuple[str, Path]] = []
    visited = set()

    for root in roots:
        stack: List[Tuple[Path, int]] = [(Path(root), 0)]
        while stack:
            current, depth = stack.pop()
            try:
                key = os.path.realpath(str(current))
            except OSError:
                continue
            if key in visited:
                continue
            visited.add(key)
            if (time.monotonic() - started) > SYMLINK_SCAN_BUDGET_S:
                return index
            try:
                iterator = list(os.scandir(str(current)))
            except OSError:
                continue
            for item in iterator:
                seen_entries += 1
                if seen_entries > SYMLINK_SCAN_MAX_ENTRIES:
                    return index
                try:
                    if item.is_symlink():
                        target = Path(os.path.realpath(item.path))
                        index.append((paths_module.portable(Path(item.path), base), target))
                        continue
                    if depth + 1 < max_depth and item.is_dir(follow_symlinks=False):
                        if item.name in skip_names or item.name.startswith("."):
                            continue
                        stack.append((Path(item.path), depth + 1))
                except OSError:
                    continue
    return index


def incoming_symlinks(
    path: Path,
    config: Any,
    home: Optional[Path] = None,
    *,
    scan_roots: Optional[Sequence[Any]] = None,
    index: Optional[Sequence[Tuple[str, Path]]] = None,
    max_depth: int = 2,
) -> List[str]:
    """Portable paths of symlinks whose target lands inside ``path``."""

    base = Path(home) if home is not None else Path.home()
    entries = (
        list(index)
        if index is not None
        else symlink_index(config, base, scan_roots=scan_roots, max_depth=max_depth)
    )
    target = Path(os.path.realpath(str(path)))
    found: List[str] = []
    for display, resolved in entries:
        if resolved == target:
            found.append(display)
            continue
        try:
            resolved.relative_to(target)
        except ValueError:
            continue
        found.append(display)
    return sorted(set(found))


# ---------------------------------------------------------------------------
# G4: shape
# ---------------------------------------------------------------------------


def _default_git_status_runner(path: Path, timeout_s: float):
    return subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def dir_shape(
    path: Path,
    *,
    git_status_runner: Optional[Callable[..., Any]] = None,
    timeout_s: float = 2.0,
    count_uncommitted: bool = True,
) -> DirShape:
    """What kind of folder this is: worktree, repo, virtualenv, project."""

    target = Path(path)
    labels: List[str] = []
    uncommitted: Optional[int] = None
    try:
        if not target.is_dir():
            return DirShape([], None)
    except OSError:
        return DirShape([], None)

    git_path = target / ".git"
    try:
        if git_path.is_file():
            labels.append("git-worktree")
        elif git_path.is_dir():
            labels.append("git-dir")
    except OSError:
        pass

    for name in (".venv", "venv", ".tox"):
        try:
            if (target / name).is_dir():
                labels.append("venv")
                break
        except OSError:
            continue

    try:
        if (target / ".env").exists():
            labels.append("dotenv")
    except OSError:
        pass

    try:
        if (target / "package.json").is_file():
            labels.append("node-project")
    except OSError:
        pass

    if "git-dir" in labels and count_uncommitted:
        runner = git_status_runner
        if runner is None and shutil.which("git") is not None:
            runner = _default_git_status_runner
        if runner is not None:
            try:
                result = runner(target, timeout_s)
                if getattr(result, "returncode", 1) == 0:
                    text = getattr(result, "stdout", "") or ""
                    uncommitted = len([line for line in text.splitlines() if line.strip()])
            except Exception:  # noqa: BLE001 - a slow repo is not a planning failure
                uncommitted = None
    return DirShape(labels, uncommitted)


def file_shape(path: Path) -> List[str]:
    """``executable`` and ``shebang`` markers for a plain file."""

    labels: List[str] = []
    target = Path(path)
    try:
        mode = target.stat().st_mode
        if mode & (stat_module.S_IXUSR | stat_module.S_IXGRP | stat_module.S_IXOTH):
            labels.append("executable")
    except OSError:
        return labels
    try:
        with open(str(target), "rb") as handle:
            if handle.read(2) == b"#!":
                labels.append("shebang")
    except OSError:
        pass
    return labels


# ---------------------------------------------------------------------------
# G5: freshly touched
# ---------------------------------------------------------------------------


def recently_modified(entry: Any, now: datetime, minutes: int = 10) -> bool:
    """True when the entry was written inside the last ``minutes``."""

    if minutes <= 0:
        return False
    modified_ns = getattr(entry, "modified_ns", None)
    if modified_ns is None and isinstance(entry, Mapping):
        modified_ns = entry.get("modified_ns")
    if modified_ns is None:
        return False
    delta = now.timestamp() - (float(modified_ns) / 1_000_000_000)
    return 0 <= delta < minutes * 60


# ---------------------------------------------------------------------------
# one context per plan
# ---------------------------------------------------------------------------


@dataclass
class GuardContext:
    home: Path
    enabled: bool = True
    reference_texts: List[Tuple[str, List[str]]] = field(default_factory=list)
    symlinks: List[Tuple[str, Path]] = field(default_factory=list)
    lsof_runner: Optional[Callable[..., Any]] = None
    lsof_enabled: bool = True
    lsof_timeout_s: float = 5.0
    git_status_runner: Optional[Callable[..., Any]] = None
    recent_minutes: int = 10
    open_by: Dict[str, OpenHandles] = field(default_factory=dict)

    def prime(self, file_paths: Sequence[Path], dir_paths: Sequence[Path] = ()) -> None:
        """Batch the lsof work for a whole scan before any entry is decided."""

        if not self.enabled or not self.lsof_enabled:
            return
        self.open_by = probe_open_handles(
            file_paths, dir_paths, self.lsof_timeout_s, lsof_runner=self.lsof_runner
        )


def build_context(
    config: Any,
    *,
    home: Optional[Path] = None,
    enabled: bool = True,
    reference_files: Optional[Sequence[Any]] = None,
    scan_roots: Optional[Sequence[Any]] = None,
    lsof_runner: Optional[Callable[..., Any]] = None,
    lsof_enabled: bool = True,
    crontab_runner: Optional[Callable[[], Any]] = None,
    git_status_runner: Optional[Callable[..., Any]] = None,
) -> GuardContext:
    """Collect everything the per-entry checks need, once."""

    base = Path(home) if home is not None else Path.home()
    profile = getattr(config, "profile", config) or {}
    guard = (profile.get("guard") if hasattr(profile, "get") else None) or {}
    context = GuardContext(
        home=base,
        enabled=enabled,
        lsof_runner=lsof_runner,
        lsof_enabled=lsof_enabled,
        lsof_timeout_s=float(guard.get("lsof_timeout_s", 5) or 5),
        git_status_runner=git_status_runner,
        recent_minutes=int(guard.get("recent_minutes", 10) or 0),
    )
    if not enabled:
        return context
    context.reference_texts = load_reference_texts(
        config,
        base,
        reference_files=reference_files,
        crontab_runner=crontab_runner,
        include_crontab=reference_files is None,
    )
    context.symlinks = symlink_index(config, base, scan_roots=scan_roots)
    return context


def inspect(
    path: Path,
    config: Any,
    context: GuardContext,
    *,
    is_dir: bool = False,
) -> Dict[str, Any]:
    """Run every check for one entry and return the plan.json ``guard`` block."""

    empty = {"open_by": [], "referenced_in": [], "incoming_symlinks": [], "shape": []}
    if not context.enabled:
        return empty

    handles = OpenHandles([], "unknown")
    if context.lsof_enabled:
        cached = context.open_by.get(str(path))
        if cached is not None:
            handles = cached
        else:
            handles = open_handles(
                path,
                context.lsof_timeout_s,
                lsof_runner=context.lsof_runner,
                is_dir=is_dir,
            )
    references = config_references(path, config, context.home, texts=context.reference_texts)
    links = incoming_symlinks(path, config, context.home, index=context.symlinks)
    if is_dir:
        shape = dir_shape(path, git_status_runner=context.git_status_runner)
        labels = list(shape.labels)
        uncommitted = shape.uncommitted
    else:
        labels = file_shape(path)
        uncommitted = None
    block = {
        "open_by": handles.handles,
        "referenced_in": references,
        "incoming_symlinks": links,
        "shape": labels,
    }
    if handles.status == "unknown":
        block["open_by_status"] = "unknown"
    if uncommitted is not None:
        block["uncommitted"] = uncommitted
    return block
