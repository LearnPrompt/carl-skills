"""Rule matching: extensions, sensitive naming, pinned names, derived copies.

Two eras live side by side here.  ``CATEGORY_EXTENSIONS`` and :func:`classify`
are the original small taxonomy and stay exactly as they were, because the
``simple`` profile and the first test file are built on them.  Everything else
is profile driven and reads its data out of a :class:`~carl_file_organizer.config.Config`.

The sensitive check is the part worth reading twice.  It never opens a file; it
only looks at the name, in four passes of decreasing certainty:

    exact_names   the whole name, compared case-insensitively
    exact_stems   the name minus its suffix, compared as a whole word
    suffixes      the suffix alone
    markers       substring, and only for long or non-ASCII words

Short words are never substring matched.  That is the fix for the day a rule
containing ``r2`` swallowed ``pixverse-r2.md``.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from .scanner import split_suffix


CATEGORY_EXTENSIONS: Dict[str, Set[str]] = {
    "Documents": {
        ".doc",
        ".docx",
        ".epub",
        ".key",
        ".md",
        ".numbers",
        ".pages",
        ".pdf",
        ".ppt",
        ".pptx",
        ".rtf",
        ".txt",
        ".xls",
        ".xlsx",
    },
    "Images": {
        ".avif",
        ".gif",
        ".heic",
        ".jpeg",
        ".jpg",
        ".png",
        ".svg",
        ".tif",
        ".tiff",
        ".webp",
    },
    "Video": {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"},
    "Audio": {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"},
    "Archives": {
        ".7z",
        ".bz2",
        ".gz",
        ".rar",
        ".tar",
        ".tgz",
        ".xz",
        ".zip",
    },
    "Installers": {".apk", ".dmg", ".exe", ".iso", ".msi", ".pkg"},
    "Code & Data": {
        ".c",
        ".cpp",
        ".css",
        ".csv",
        ".go",
        ".html",
        ".ipynb",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".py",
        ".rb",
        ".rs",
        ".sql",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".xml",
        ".yaml",
        ".yml",
    },
}


def classify(path: Path) -> tuple:
    """Return a human-readable category, reason, and confidence."""
    suffix = path.suffix.lower()
    for category, extensions in CATEGORY_EXTENSIONS.items():
        if suffix in extensions:
            return category, "{0} file".format(suffix or "extensionless"), 0.98
    return "Other", "file type is not in the small default taxonomy", 0.55


# ---------------------------------------------------------------------------
# profile driven matching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    key: str  # the suffix that matched, e.g. ".pdf"
    dest_key: str
    min_age_hours: int
    reason_key: str
    label: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class SensitiveHit:
    layer: str  # "exact" | "suffix" | "marker" -> becomes rule "sensitive:<layer>"
    needle: str
    where: str  # "exact_names" | "exact_stems" | "suffixes" | "markers"


@dataclass(frozen=True)
class NamePattern:
    id: str
    match: str  # "contains" | "prefix" | "glob"
    needle: str
    dest: Optional[str]  # literal path relative to root
    dest_key: Optional[str]  # or a key in profile names


def _profile(config: Any) -> Mapping[str, Any]:
    return getattr(config, "profile", config)


def _section(config: Any, name: str) -> Mapping[str, Any]:
    section = _profile(config).get(name)
    return section if isinstance(section, Mapping) else {}


def _list(config: Any, section: str, key: str) -> Sequence[Any]:
    values = _section(config, section).get(key)
    return values if isinstance(values, (list, tuple)) else ()


def match_rule(suffix: str, config: Any) -> Optional[Rule]:
    """Look a suffix up in the profile rule table."""

    rules = _section(config, "rules")
    folded = str(suffix).casefold()
    entry = rules.get(folded)
    if not isinstance(entry, Mapping):
        return None
    aging = _section(config, "aging")
    default_hours = int(aging.get("default_hours", 48) or 0)
    minimum = entry.get("min_age_hours")
    return Rule(
        key=folded,
        dest_key=str(entry.get("dest")),
        min_age_hours=int(default_hours if minimum is None else minimum),
        reason_key=str(entry.get("reason") or "ext_other"),
        label=entry.get("label") if isinstance(entry.get("label"), Mapping) else None,
    )


def is_sensitive(name: str, config: Any) -> Optional[SensitiveHit]:
    """Name-only credential detection.  Contents are never read."""

    text = str(name)
    folded = text.casefold()
    stem, suffix = split_suffix(text)
    folded_stem = stem.casefold()

    for candidate in _list(config, "sensitive", "exact_names"):
        if folded == str(candidate).casefold():
            return SensitiveHit("exact", str(candidate), "exact_names")

    for candidate in _list(config, "sensitive", "exact_stems"):
        if folded_stem == str(candidate).casefold():
            return SensitiveHit("exact", str(candidate), "exact_stems")

    for candidate in _list(config, "sensitive", "suffixes"):
        needle = str(candidate).casefold()
        if suffix and suffix == needle:
            return SensitiveHit("suffix", str(candidate), "suffixes")
        # A dot-prefixed suffix such as ".env" also matches "prod.env" when the
        # name carries no suffix of its own.
        if not suffix and folded.endswith(needle) and folded != needle:
            return SensitiveHit("suffix", str(candidate), "suffixes")

    minimum = int(_section(config, "sensitive").get("marker_min_len", 5) or 5)
    for candidate in _list(config, "sensitive", "markers"):
        marker = str(candidate)
        ascii_only = all(ord(char) < 128 for char in marker)
        if ascii_only and len(marker) < minimum:
            # Refused at load time; skipped here so a hand-edited profile in the
            # wild degrades to "missed" rather than "matched everything".
            continue
        if marker.casefold() in folded:
            return SensitiveHit("marker", marker, "markers")
    return None


def derivative_hint(name: str, config: Any) -> Optional[str]:
    """Return the hint substring when a name looks like a scratch copy."""

    folded = str(name).casefold()
    for hint in _profile(config).get("derivative_hints") or ():
        needle = str(hint).casefold()
        if needle and needle in folded:
            return str(hint)
    return None


def is_regenerable_name(name: str, config: Any) -> bool:
    basenames = _list(config, "regenerable", "basenames")
    return any(str(name) == str(candidate) for candidate in basenames)


def regenerable_restore(name: str, config: Any) -> Dict[str, str]:
    restore = _section(config, "regenerable").get("restore")
    table = restore if isinstance(restore, Mapping) else {}
    entry = table.get(str(name)) or table.get("_default") or {}
    if isinstance(entry, Mapping):
        return {"zh": str(entry.get("zh", "")), "en": str(entry.get("en", ""))}
    return {"zh": str(entry), "en": str(entry)}


def match_pinned(name: str, config: Any) -> Optional[str]:
    """Exact name or fnmatch glob against the pinned allow list."""

    text = str(name)
    for pattern in _profile(config).get("pinned") or ():
        candidate = str(pattern)
        if text == candidate or fnmatch.fnmatch(text, candidate):
            return candidate
    return None


def match_name_pattern(name: str, config: Any) -> Optional[NamePattern]:
    """User written name rules; substring matching needs at least four characters."""

    text = str(name)
    folded = text.casefold()
    _stem, suffix = split_suffix(text)
    for raw in _profile(config).get("name_patterns") or ():
        if not isinstance(raw, Mapping):
            continue
        needle = str(raw.get("needle") or "")
        if not needle:
            continue
        suffixes = raw.get("suffixes")
        if isinstance(suffixes, (list, tuple)) and suffixes:
            allowed = {str(item).casefold() for item in suffixes}
            if suffix not in allowed:
                continue
        how = str(raw.get("match") or "contains")
        folded_needle = needle.casefold()
        if how == "prefix":
            hit = folded.startswith(folded_needle)
        elif how == "glob":
            hit = fnmatch.fnmatch(text, needle)
        else:
            hit = len(folded_needle) >= 4 and folded_needle in folded
        if not hit:
            continue
        return NamePattern(
            id=str(raw.get("id") or needle),
            match=how,
            needle=needle,
            dest=str(raw["dest"]) if raw.get("dest") else None,
            dest_key=str(raw["dest_key"]) if raw.get("dest_key") else None,
        )
    return None


def is_archive_suffix(suffix: str, config: Any) -> bool:
    folded = str(suffix).casefold()
    return any(
        folded == str(item).casefold() for item in _profile(config).get("archive_suffixes") or ()
    )


def is_installer_suffix(suffix: str, config: Any) -> bool:
    folded = str(suffix).casefold()
    return any(
        folded == str(item).casefold() for item in _profile(config).get("installer_suffixes") or ()
    )


def forbidden_markers(config: Any) -> List[str]:
    return [str(item) for item in _list(config, "forbidden", "markers")]
