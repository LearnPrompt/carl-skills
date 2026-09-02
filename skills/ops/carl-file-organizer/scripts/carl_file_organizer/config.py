"""Language detection, profile loading and merging, per-folder settings file.

Everything downstream reads a single :class:`Config`.  The contract frozen here:

    resolve_config(root, *, lang=None, profile=None) -> Config
    dir_name(config, key) -> "20_知识库/文档资料/PDF"
    dest_dir(config, key) -> Path
    managed_dir(config)   -> Path
    partition_prefixes(config) -> ("00_", "10_", ...)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import paths

DOTFILE_NAME = ".carl-file-organizer.json"
DEFAULT_PROFILE = "tiered"
LANG_ENV = "CARL_FILE_ORGANIZER_LANG"
LANGS = ("zh", "en")
MAX_NAME_DEPTH = 3

#: Keys whose list values are unioned when a dotfile overrides a built-in profile.
UNION_LIST_KEYS = (
    ("pinned",),
    ("derivative_hints",),
    ("archive_suffixes",),
    ("installer_suffixes",),
    ("sensitive", "exact_names"),
    ("sensitive", "exact_stems"),
    ("sensitive", "suffixes"),
    ("sensitive", "markers"),
    ("forbidden", "basenames"),
    ("forbidden", "suffixes"),
    ("forbidden", "markers"),
    ("forbidden", "glob"),
    ("regenerable", "basenames"),
    ("guard", "reference_files"),
    ("guard", "reference_scan_roots"),
    ("dedupe", "copy_patterns"),
)

#: Sections merged key by key, with the dotfile value winning per key.
SCALAR_SECTIONS = ("aging", "tags", "dedupe", "guard", "regenerable", "sensitive")

#: Top-level keys the dotfile simply overwrites.
OVERRIDE_KEYS = ("lang", "profile", "large_bytes", "managed_dir", "transient_tag", "review_log")

#: Settings that record a choice rather than a rule, and so stay out of the digest.
HASH_IGNORED_KEYS = ("lang",)


class LanguageAmbiguous(ValueError):
    """Both language layouts exist in the same folder and no language was given."""


@dataclass
class Config:
    root: Path
    lang: str
    lang_source: str
    profile_name: str
    profile: Dict[str, Any]
    profile_source: str
    dotfile_path: Optional[Path]
    profile_hash: str
    warnings: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# language detection
# --------------------------------------------------------------------------


def normalize_lang(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    folded = str(text).strip().casefold().replace("_", "-")
    if folded.startswith("zh") or "hans" in folded or "hant" in folded:
        return "zh"
    if folded.startswith("en"):
        return "en"
    return None


def _apple_languages(timeout_s: float = 1.0) -> Optional[str]:
    """First entry of ``defaults read -g AppleLanguages``; ``None`` when unavailable."""

    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleLanguages"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r'"?([A-Za-z]{2}[A-Za-z0-9\-_]*)"?', result.stdout)
    return match.group(1) if match else None


def _posix_locale(env: Mapping[str, str]) -> Optional[str]:
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(key)
        if value:
            return value.split(".")[0]
    return None


def _sniff_dir_names(profile: Mapping[str, Any]) -> Dict[str, List[str]]:
    """Directory names that betray which language layout a folder already uses."""

    probes: Dict[str, List[str]] = {"zh": [], "en": []}
    names = profile.get("names") or {}
    candidates = [names.get("inbox"), profile.get("managed_dir")]
    for entry in candidates:
        if not isinstance(entry, Mapping):
            continue
        zh_name = entry.get("zh")
        en_name = entry.get("en")
        if not zh_name or not en_name or zh_name == en_name:
            continue
        probes["zh"].append(str(zh_name))
        probes["en"].append(str(en_name))
    return probes


def _sniff_existing_dirs(root: Path, profile: Mapping[str, Any]) -> List[str]:
    found: List[str] = []
    probes = _sniff_dir_names(profile)
    for lang in LANGS:
        for name in probes[lang]:
            try:
                if (Path(root) / name).is_dir():
                    found.append(lang)
                    break
            except OSError:
                continue
    return found


def detect_lang(
    root: Path,
    override: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    dotfile: Optional[Mapping[str, Any]] = None,
    profile: Optional[Mapping[str, Any]] = None,
) -> Tuple[str, str]:
    """Return ``(lang, source)``.

    Chain: flag > dotfile > ``CARL_FILE_ORGANIZER_LANG`` > existing directories >
    AppleLanguages > POSIX locale > ``en``.
    """

    environ = os.environ if env is None else env

    if override:
        chosen = normalize_lang(override)
        if chosen is None:
            raise ValueError("unsupported language: {0}".format(override))
        return chosen, "flag"

    settings = dotfile if dotfile is not None else (load_dotfile(root) or {})
    chosen = normalize_lang(settings.get("lang") if isinstance(settings, Mapping) else None)
    if chosen:
        return chosen, "dotfile"

    chosen = normalize_lang(environ.get(LANG_ENV))
    if chosen:
        return chosen, "env"

    if profile:
        found = _sniff_existing_dirs(root, profile)
        if len(found) > 1:
            raise LanguageAmbiguous(
                "both language layouts exist in {0}; pass --lang zh or --lang en".format(root)
            )
        if len(found) == 1:
            return found[0], "existing-dirs"

    chosen = normalize_lang(_apple_languages())
    if chosen:
        return chosen, "apple-languages"

    chosen = normalize_lang(_posix_locale(environ))
    if chosen:
        return chosen, "posix-locale"

    return "en", "default"


# --------------------------------------------------------------------------
# profile loading and merging
# --------------------------------------------------------------------------


def load_builtin_profile(name: str) -> Dict[str, Any]:
    """Read ``carl_file_organizer/profiles/<name>.json`` from the installed package."""

    from importlib.resources import files  # 3.9+

    if not re.fullmatch(r"[a-z0-9_\-]+", name or ""):
        raise ValueError("unknown profile: {0!r}".format(name))
    resource = files("carl_file_organizer.profiles").joinpath("{0}.json".format(name))
    try:
        text = resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as error:
        raise ValueError("unknown profile: {0}".format(name)) from error
    profile = json.loads(text)
    validate_profile(profile)
    return profile


def load_dotfile(root: Path) -> Optional[Dict[str, Any]]:
    """Read ``<root>/.carl-file-organizer.json``; ``None`` when it does not exist."""

    path = Path(root) / DOTFILE_NAME
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(
            "{0} is not valid JSON (line {1}, column {2}): {3}".format(
                path, error.lineno, error.colno, error.msg
            )
        ) from error
    if not isinstance(data, dict):
        raise ValueError("{0} must contain a JSON object".format(path))
    return data


def _union(base: Sequence[Any], extra: Sequence[Any]) -> List[Any]:
    merged: List[Any] = []
    seen = set()
    for item in list(base) + list(extra):
        marker = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, (dict, list)) else item
        if marker in seen:
            continue
        seen.add(marker)
        merged.append(item)
    return merged


def _union_name_patterns(base: Sequence[Any], extra: Sequence[Any]) -> List[Any]:
    merged: List[Any] = []
    index: Dict[str, int] = {}
    for item in list(base) + list(extra):
        if isinstance(item, dict) and item.get("id"):
            key = str(item["id"])
            if key in index:
                merged[index[key]] = item
                continue
            index[key] = len(merged)
        merged.append(item)
    return merged


def _get_in(data: Mapping[str, Any], path: Sequence[str]) -> Any:
    current: Any = data
    for step in path:
        if not isinstance(current, Mapping) or step not in current:
            return None
        current = current[step]
    return current


def _set_in(data: Dict[str, Any], path: Sequence[str], value: Any) -> None:
    current = data
    for step in path[:-1]:
        current = current.setdefault(step, {})
    current[path[-1]] = value


def validate_profile(profile: Mapping[str, Any]) -> None:
    """Refuse footguns before anything reads the profile."""

    sensitive = profile.get("sensitive") or {}
    minimum = int(sensitive.get("marker_min_len", 5) or 5)
    for marker in sensitive.get("markers", []) or []:
        text = str(marker)
        if all(ord(char) < 128 for char in text) and len(text) < minimum:
            raise ValueError(
                "sensitive.markers entry {0!r} is too short: ASCII markers are substring "
                "matched and must be at least {1} characters. Put short words in "
                "sensitive.exact_stems instead.".format(text, minimum)
            )
    names = profile.get("names") or {}
    for key in names:
        if len(str(key).split(".")) > MAX_NAME_DEPTH:
            raise ValueError(
                "names key {0!r} is deeper than {1} levels".format(key, MAX_NAME_DEPTH)
            )


def merge_profile(base: Mapping[str, Any], override: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Sparse overlay of a dotfile on top of a built-in profile.

    ``names`` and ``rules`` merge key by key; list-shaped settings are unioned;
    ``lang`` / ``aging`` / ``large_bytes`` and friends are overwritten.
    """

    merged: Dict[str, Any] = json.loads(json.dumps(base, ensure_ascii=False))
    if not override:
        validate_profile(merged)
        return merged

    for section in ("names", "rules"):
        incoming = override.get(section)
        if not isinstance(incoming, Mapping):
            continue
        target = merged.setdefault(section, {})
        for key, value in incoming.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), Mapping):
                combined = dict(target[key])
                combined.update(value)
                target[key] = combined
            else:
                target[key] = value

    for section in SCALAR_SECTIONS:
        incoming = override.get(section)
        if not isinstance(incoming, Mapping):
            continue
        target = merged.setdefault(section, {})
        for key, value in incoming.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), Mapping):
                combined = dict(target[key])
                combined.update(value)
                target[key] = combined
            else:
                target[key] = value

    # Unions read from ``base`` on purpose: the scalar pass above may have
    # replaced a list wholesale, and a union must never lose built-in entries.
    for path in UNION_LIST_KEYS:
        incoming = _get_in(override, path)
        if not isinstance(incoming, list):
            continue
        current = _get_in(base, path)
        _set_in(merged, path, _union(current if isinstance(current, list) else [], incoming))

    if isinstance(override.get("name_patterns"), list):
        current = base.get("name_patterns")
        merged["name_patterns"] = _union_name_patterns(
            current if isinstance(current, list) else [], override["name_patterns"]
        )

    for key in OVERRIDE_KEYS:
        if key in override:
            value = override[key]
            if key in ("managed_dir", "transient_tag", "review_log") and isinstance(value, Mapping):
                combined = dict(merged.get(key) or {})
                combined.update(value)
                merged[key] = combined
            else:
                merged[key] = value

    validate_profile(merged)
    return merged


def profile_hash(profile: Mapping[str, Any]) -> str:
    """Short digest of the rules in a merged profile; stored in plan.json to catch drift.

    The chosen language is left out on purpose.  The first ``plan`` in a folder
    hashes the settings and then writes the settings file, which records the
    language; hashing that back in would make every second run announce that
    the settings had changed.  Language decides what the folders are called, not
    what goes into them, so it is not drift.  An edited rule or a new sensitive
    name still moves the digest.
    """

    material = {
        key: value for key, value in profile.items() if key not in HASH_IGNORED_KEYS
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


# --------------------------------------------------------------------------
# resolution and persistence
# --------------------------------------------------------------------------


def resolve_config(
    root: Path,
    *,
    lang: Optional[str] = None,
    profile: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Config:
    """Load the dotfile, pick the profile and the language, return a Config."""

    root_path = Path(root).expanduser()
    settings = load_dotfile(root_path)
    profile_name = profile or (settings or {}).get("profile") or DEFAULT_PROFILE
    base = load_builtin_profile(str(profile_name))
    merged = merge_profile(base, settings)

    warnings: List[str] = []
    lang_value, lang_source = detect_lang(
        root_path, lang, env=env, dotfile=settings or {}, profile=merged
    )
    if lang_source == "default":
        warnings.append(
            "no language signal found; falling back to en (pass --lang zh to change it)"
        )

    return Config(
        root=root_path,
        lang=lang_value,
        lang_source=lang_source,
        profile_name=str(profile_name),
        profile=merged,
        profile_source="builtin+dotfile" if settings else "builtin",
        dotfile_path=(root_path / DOTFILE_NAME) if settings is not None else None,
        profile_hash=profile_hash(merged),
        warnings=warnings,
    )


def save_dotfile(config: Config, *, only_if_missing: bool = True) -> Optional[Path]:
    """Write the smallest useful settings file; never write the merged profile back."""

    path = Path(config.root) / DOTFILE_NAME
    if only_if_missing and path.exists():
        return None
    payload = {"profile": config.profile_name, "lang": config.lang}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    config.dotfile_path = path
    return path


# --------------------------------------------------------------------------
# name resolution
# --------------------------------------------------------------------------


def _pick_lang(entry: Any, lang: str) -> str:
    if isinstance(entry, Mapping):
        value = entry.get(lang)
        if value:
            return str(value)
        value = entry.get("en")
        if value:
            return str(value)
        for item in entry.values():
            if item:
                return str(item)
        return ""
    return str(entry)


def dir_name(config: Config, key: str) -> str:
    """``"library.docs.pdf"`` -> ``"20_知识库/文档资料/PDF"``.

    Parent keys are derived from the dotted prefix chain; three levels maximum.
    """

    parts = str(key).split(".")
    if len(parts) > MAX_NAME_DEPTH:
        raise ValueError(
            "destination key {0!r} is deeper than {1} levels".format(key, MAX_NAME_DEPTH)
        )
    names = config.profile.get("names") or {}
    segments: List[str] = []
    for index in range(1, len(parts) + 1):
        prefix = ".".join(parts[:index])
        if prefix not in names:
            raise KeyError("profile {0} has no name for {1!r}".format(config.profile_name, prefix))
        segments.append(paths.safe_dir_name(_pick_lang(names[prefix], config.lang)))
    return "/".join(segments)


def dest_dir(config: Config, key: str) -> Path:
    return Path(config.root) / dir_name(config, key)


def managed_dir(config: Config) -> Path:
    name = _pick_lang(config.profile.get("managed_dir"), config.lang) or "00_File_Organizer"
    return Path(config.root) / paths.safe_dir_name(name)


def transient_tag(config: Config) -> str:
    return _pick_lang(config.profile.get("transient_tag"), config.lang) or "Moved by File Organizer"


def transient_tags(config: Config) -> Tuple[str, ...]:
    """Every language spelling of the temporary tag, for stripping user tags."""

    entry = config.profile.get("transient_tag") or {}
    if isinstance(entry, Mapping):
        return tuple(str(value) for value in entry.values() if value)
    return (str(entry),)


def review_log_name(config: Config) -> str:
    return _pick_lang(config.profile.get("review_log"), config.lang) or "review-log.md"


def partition_dir_names(config: Config) -> Tuple[str, ...]:
    """Top-level partition directory names in every language, plus the managed folder."""

    names = config.profile.get("names") or {}
    found: List[str] = []
    for key, entry in names.items():
        if "." in str(key):
            continue
        if isinstance(entry, Mapping):
            found.extend(str(value) for value in entry.values() if value)
        elif entry:
            found.append(str(entry))
    managed = config.profile.get("managed_dir") or {}
    if isinstance(managed, Mapping):
        found.extend(str(value) for value in managed.values() if value)
    return tuple(sorted(set(found)))


def partition_prefixes(config: Config) -> Tuple[str, ...]:
    """Numeric partition prefixes such as ``("00_", "10_", "20_", "60_", "90_")``."""

    prefixes = set()
    for name in partition_dir_names(config):
        match = re.match(r"^(\d+_)", name)
        if match:
            prefixes.add(match.group(1))
    return tuple(sorted(prefixes))
