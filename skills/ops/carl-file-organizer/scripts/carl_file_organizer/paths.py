"""Path helpers: portable $HOME form, boundary checks, safe names, no-go zones.

This module never imports other Carl File Organizer modules, so every work package can
depend on it.  ``config`` objects are accepted by duck typing (anything exposing
``.profile`` as a mapping is fine).

It also owns the two halves of the privacy rule, because both are pure path
arithmetic: :func:`strip_absolute` drops every absolute path out of a plan
before it is embedded in a shareable page, and
:func:`hydrate_absolute` puts them back from the ``$HOME`` twins at apply time.
"""

from __future__ import annotations

import copy
import fnmatch
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

#: The one token written to disk, on every platform.  plan.json, the manifests,
#: the audit log and report.html all use this and only this, because those files
#: travel: a plan made on a Mac gets opened on a Windows machine, and a report is
#: a page somebody forwards.  One stored token means one parser and one privacy
#: check, and that check is a single ``startswith`` over the whole document.
HOME_TOKEN = "$HOME"

#: The same idea spelled the way Windows spells it.  Understood on input, and
#: shown on screen by :func:`display_portable`, but never written into a file.
WINDOWS_HOME_TOKEN = "%USERPROFILE%"

#: Both spellings, for everything that reads rather than writes.
HOME_TOKENS = (HOME_TOKEN, WINDOWS_HOME_TOKEN)

#: Path separators a stored portable string may arrive with.
SEPARATORS = ("/", "\\")


def home_token(platform: Optional[str] = None) -> str:
    """The token a person on this platform recognises at a glance."""

    system = platform if platform is not None else sys.platform
    return WINDOWS_HOME_TOKEN if system == "win32" else HOME_TOKEN


def split_home_token(text: str) -> Optional[Tuple[str, str]]:
    """``(token, remainder)`` when ``text`` starts with either home token.

    The remainder has no leading separator and always comes back with forward
    slashes, so callers can hand it straight to :class:`~pathlib.Path`.
    """

    if not isinstance(text, str):
        return None
    for token in HOME_TOKENS:
        if text == token:
            return token, ""
        for separator in SEPARATORS:
            prefix = token + separator
            if text.startswith(prefix):
                rest = text[len(prefix) :]
                return token, rest.replace("\\", "/")
    return None


def display_portable(text: str, platform: Optional[str] = None) -> str:
    """Rewrite a stored ``$HOME/...`` string for the eyes of this platform.

    Storage never changes; only the rendering does.  Everywhere but Windows
    this hands back exactly what it was given.
    """

    token = home_token(platform)
    if token == HOME_TOKEN:
        return text
    split = split_home_token(text)
    if split is None:
        return text
    _found, rest = split
    if not rest:
        return token
    return token + "\\" + rest.replace("/", "\\")

#: Compound suffixes that must survive as one unit, so ``a.tar.gz`` is an archive.
#: :mod:`carl_file_organizer.scanner` re-exports this pair; there is only one spelling.
DOUBLE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst", ".tar.lz")

#: Envelope fields that hold an absolute path and have a ``_portable`` twin.
PLAN_ABSOLUTE_FIELDS = ("source_root", "managed_dir")

#: The same, per action.
ACTION_ABSOLUTE_FIELDS = ("source", "destination")

#: Roots that are refused outright, relative to ``$HOME``.
REFUSED_HOME_SUBDIRS = ("Library", "Applications")

#: Absolute roots that are refused outright regardless of ``$HOME``.
REFUSED_ABSOLUTE = ("/", "/System", "/Library", "/Applications", "/private", "/usr", "/bin", "/etc", "/var")


def _home(home: Optional[Path] = None) -> Path:
    return Path(os.path.realpath(str(home))) if home is not None else Path(os.path.realpath(str(Path.home())))


def realpath(path: Path) -> Path:
    """``os.path.realpath`` as a :class:`Path`, without touching the filesystem twice."""

    return Path(os.path.realpath(str(path)))


def portable(path: Path, home: Optional[Path] = None) -> str:
    """Render ``path`` as ``$HOME/...`` when it lives under the home directory.

    Forward slashes on every platform, because this string is stored, compared
    and shipped rather than opened.  :func:`display_portable` is what turns it
    into something a Windows user reads.
    """

    base = home if home is not None else Path.home()
    text = str(path)
    try:
        return HOME_TOKEN + "/" + Path(text).relative_to(base).as_posix()
    except ValueError:
        return text


def expand_portable(text: str, home: Optional[Path] = None) -> Path:
    """Inverse of :func:`portable`, reading either home token.

    A plan written on Windows and applied on a Mac, or a person who typed
    ``%USERPROFILE%\\Downloads`` into a settings file by hand, both land here
    and both come out as a real path on this machine.
    """

    base = home if home is not None else Path.home()
    split = split_home_token(text)
    if split is not None:
        _token, rest = split
        return Path(base) / rest if rest else Path(base)
    return Path(text).expanduser()


def inside_root(path: Path, root: Path) -> bool:
    """True when ``path`` resolves inside ``root`` (both sides realpath'ed)."""

    resolved = realpath(path)
    base = realpath(root)
    if resolved == base:
        return True
    try:
        resolved.relative_to(base)
        return True
    except ValueError:
        return False


def has_symlink_component(path: Path, root: Path) -> bool:
    """True when any path segment below ``root`` is a symlink."""

    base = realpath(root)
    try:
        relative = Path(path).relative_to(root)
    except ValueError:
        try:
            relative = realpath(path).relative_to(base)
        except ValueError:
            return True
    current = Path(root)
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def safe_dir_name(name: str) -> str:
    """Turn an arbitrary entry name into something safe to use as a directory name."""

    cleaned = name.replace("\x00", "").replace("/", "-").replace(os.sep, "-")
    cleaned = cleaned.lstrip("$").strip()
    had_quote = '"' in cleaned or "'" in cleaned
    cleaned = cleaned.replace('"', "").replace("'", "").strip()
    cleaned = cleaned.strip(".").strip()
    if not cleaned:
        return "quote-dir" if had_quote else "unnamed"
    return cleaned


def split_suffix(name: str) -> Tuple[str, str]:
    """``("archive", ".tar.gz")``; a leading dot never counts as a suffix.

    The stem keeps its original case, the suffix is folded, so callers comparing
    against a rule table do not have to fold again.  ``name[len(stem):]`` gives
    the suffix back exactly as it was written.
    """

    folded = name.casefold()
    for double in DOUBLE_SUFFIXES:
        if folded.endswith(double) and len(name) > len(double):
            return name[: -len(double)], double
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        return name, ""
    return stem, ("." + ext).casefold()


def conflict_name(name: str, ts: datetime, *, is_dir: bool = False) -> str:
    """Name used when a destination is taken: ``quarterly-report-2026-09-02_10-20-11.pdf``.

    The stamp goes before the suffix so the copy still opens with a double click.
    Directories and names without a suffix keep the plain ``<name>-<stamp>``
    shape, and ``a.tar.gz`` stays one unit because the split is the scanner's.
    """

    safe = safe_dir_name(name)
    stamp = ts.strftime("%Y-%m-%d_%H-%M-%S")
    if is_dir:
        return "{0}-{1}".format(safe, stamp)
    stem, folded = split_suffix(safe)
    if not folded:
        return "{0}-{1}".format(safe, stamp)
    return "{0}-{1}{2}".format(stem, stamp, safe[len(stem) :])


def _forbidden_section(config: Any) -> dict:
    profile = getattr(config, "profile", config)
    section = profile.get("forbidden") if hasattr(profile, "get") else None
    return section if isinstance(section, dict) else {}


def is_forbidden(path: Path, config: Any) -> Optional[str]:
    """Return a rule label when ``path`` sits in a no-go zone, otherwise ``None``."""

    section = _forbidden_section(config)
    name = Path(path).name
    folded = name.casefold()

    for basename in section.get("basenames", []) or []:
        if name == basename or folded == str(basename).casefold():
            return "forbidden:basename:{0}".format(basename)

    for suffix in section.get("suffixes", []) or []:
        if folded.endswith(str(suffix).casefold()):
            return "forbidden:suffix:{0}".format(suffix)

    for pattern in section.get("glob", []) or []:
        if fnmatch.fnmatch(name, str(pattern)):
            return "forbidden:glob:{0}".format(pattern)

    try:
        is_dir = Path(path).is_dir()
    except OSError:
        is_dir = False
    if is_dir:
        for marker in section.get("markers", []) or []:
            try:
                if (Path(path) / str(marker)).exists():
                    return "forbidden:marker:{0}".format(marker)
            except OSError:
                continue
    return None


def refuse_root(
    root: Path,
    *,
    allow_outside_home: bool = False,
    home: Optional[Path] = None,
) -> Path:
    """Validate a scan root and return its realpath, or raise ``ValueError``."""

    candidate = Path(root).expanduser()
    if candidate.is_symlink():
        raise ValueError("refused root: {0} is a symlink".format(candidate))
    resolved = realpath(candidate)
    if not resolved.is_dir():
        raise ValueError("refused root: {0} is not a directory".format(resolved))

    home_dir = _home(home)
    if str(resolved) in REFUSED_ABSOLUTE:
        raise ValueError("refused root: {0} is a system directory".format(resolved))
    if resolved == home_dir:
        raise ValueError("refused root: the home directory itself is out of scope")
    for sub in REFUSED_HOME_SUBDIRS:
        blocked = home_dir / sub
        if resolved == blocked or inside_root(resolved, blocked):
            raise ValueError("refused root: {0} is out of scope".format(blocked))
    if not allow_outside_home and not inside_root(resolved, home_dir):
        raise ValueError(
            "refused root: {0} is outside {1}; pass --allow-outside-home to override".format(
                resolved, home_dir
            )
        )
    return resolved


# ---------------------------------------------------------------------------
# the privacy rule: absolute paths never leave the managed folder
# ---------------------------------------------------------------------------


def plan_home(plan: Any, home: Optional[Path] = None) -> Path:
    """Recover the home directory a plan was written against.

    ``source_root`` and ``source_root_portable`` are two spellings of the same
    path, so subtracting one from the other gives back ``$HOME`` and nobody has
    to store it anywhere.  A stripped plan has lost the absolute half, and then
    the answer is this machine's home, which is the only one apply can act on.
    """

    if home is not None:
        return Path(home)
    envelope = plan if isinstance(plan, dict) else {}
    root = str(envelope.get("source_root") or "")
    portable_text = str(envelope.get("source_root_portable") or "")
    if not root:
        return Path.home()
    split = split_home_token(portable_text)
    if split is None:
        return Path.home()
    _token, rest = split
    if not rest:
        return Path(root)
    relative = Path(rest).parts
    whole = Path(root).parts
    if len(whole) > len(relative) and whole[-len(relative) :] == relative:
        return Path(*whole[: -len(relative)])
    return Path.home()


def _portable_text(text: str, base: str) -> str:
    """Rewrite every mention of the home directory, in either separator style."""

    if not base or base in ("/", os.sep):
        return text
    if text == base:
        return HOME_TOKEN
    for separator in dict.fromkeys(("/", os.sep)):
        text = text.replace(base + separator, HOME_TOKEN + "/")
    return text


def _scrub(value: Any, base: str) -> Any:
    """Every remaining string rendered in ``$HOME`` form, no exemptions."""

    if isinstance(value, dict):
        return {k: _scrub(v, base) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(item, base) for item in value]
    if isinstance(value, str):
        return _portable_text(value, base)
    return value


def strip_absolute(plan: Any, home: Optional[Path] = None) -> Any:
    """A copy of ``plan`` carrying no absolute path, only the ``_portable`` twins.

    This is what the review page embeds and what ``/api/plan`` serves, so a
    report.html handed to somebody else never spells out the account it came
    from.  The four fields with a twin are dropped outright; anything that names
    the home directory is rewritten rather than deleted, so a field added later
    cannot quietly reopen the leak.  The plan.json in the managed folder is not
    touched, and :func:`hydrate_absolute` reverses this at apply time.
    """

    if not isinstance(plan, dict):
        return plan
    base = str(plan_home(plan, home))
    data = copy.deepcopy(plan)
    for field in PLAN_ABSOLUTE_FIELDS:
        data.pop(field, None)
    actions = data.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict):
                for field in ACTION_ABSOLUTE_FIELDS:
                    action.pop(field, None)
    return _scrub(data, base)


def _rehydrate(holder: Dict[str, Any], field: str, home: Optional[Path]) -> None:
    if holder.get(field):
        return
    twin = holder.get(field + "_portable")
    if isinstance(twin, str) and twin:
        holder[field] = str(expand_portable(twin, home))
    else:
        holder[field] = holder.get(field)


def hydrate_absolute(plan: Any, home: Optional[Path] = None) -> Any:
    """A copy of ``plan`` with the absolute paths rebuilt from their twins.

    Idempotent: a plan that still has them is returned unchanged.  A plan
    exported from the review page has only ``$HOME`` forms, and they are expanded
    against this machine's home unless one is injected.
    """

    if not isinstance(plan, dict):
        return plan
    base = plan_home(plan, home)
    data = copy.deepcopy(plan)
    for field in PLAN_ABSOLUTE_FIELDS:
        _rehydrate(data, field, base)
    actions = data.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict):
                for field in ACTION_ABSOLUTE_FIELDS:
                    _rehydrate(action, field, base)
    return data
