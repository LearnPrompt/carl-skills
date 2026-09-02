"""One renderer for both entrances, loaded from the script next door.

``scripts/build_report.py`` owns the three-colour page: it detects whether it is
looking at a plan.json or an analysis.json, strips every absolute path, lays the
Agent's notes over the rules and fills the template.  It is a script rather than
a module of this package because a person runs it by hand
(``python3 scripts/build_report.py analysis.json -o report.html``).

The review server has to produce byte-for-byte the same page, so it does not
reimplement any of that: this module loads that very file through
:mod:`importlib` and hands its functions on.  One renderer, one template, no
second copy to keep in step.

    from . import render
    html = render.render(plan, mode="serve", token=token)

The module is loaded once and cached.  ``build_report.py`` sitting next to the
package is part of the skill's layout, so a missing file is a broken install and
raises :class:`RenderError` with a sentence saying so, never an ImportError
traceback in the middle of a review session.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union

#: ``carl_file_organizer/render.py`` -> ``scripts/build_report.py``
BUILD_REPORT_PATH = Path(__file__).resolve().parent.parent / "build_report.py"

MODULE_NAME = "carl_file_organizer._build_report"

_MODULE: Optional[Any] = None


class RenderError(RuntimeError):
    """The renderer could not be loaded or refused the data it was given."""


def module(path: Optional[Union[str, Path]] = None) -> Any:
    """The loaded ``build_report`` module, imported at most once per process."""

    global _MODULE
    if _MODULE is not None and path is None:
        return _MODULE
    target = Path(path) if path is not None else BUILD_REPORT_PATH
    if not target.is_file():
        raise RenderError(
            "the report renderer is missing: {0}".format(target)
        )
    existing = sys.modules.get(MODULE_NAME)
    if existing is not None and path is None:
        _MODULE = existing
        return existing
    spec = importlib.util.spec_from_file_location(MODULE_NAME, str(target))
    if spec is None or spec.loader is None:
        raise RenderError("cannot load the report renderer from {0}".format(target))
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = loaded
    try:
        spec.loader.exec_module(loaded)
    except Exception as error:  # noqa: BLE001 - a broken renderer is one sentence
        sys.modules.pop(MODULE_NAME, None)
        raise RenderError("the report renderer failed to load: {0}".format(error)) from error
    if path is None:
        _MODULE = loaded
    return loaded


def detect_kind(data: Dict[str, Any]) -> str:
    """``"organize"`` for a plan.json, ``"storage"`` for an analysis.json."""

    try:
        return str(module().detect_kind(data))
    except RenderError:
        raise
    except ValueError as error:
        raise RenderError(str(error)) from error


def sanitize(data: Any, home: Optional[Union[str, Path]] = None) -> Any:
    """The renderer's own redaction, so callers do not grow a second one."""

    return module().sanitize(data, home)


def render(
    data: Dict[str, Any],
    *,
    mode: str = "static",
    token: str = "",
    lang: Optional[str] = None,
    notes: Optional[Dict[str, Any]] = None,
    kind: Optional[str] = None,
    home: Optional[Union[str, Path]] = None,
) -> str:
    """The finished page.  Same arguments, same output, as ``build_report.render``."""

    try:
        return str(
            module().render(
                data, mode=mode, token=token, lang=lang, notes=notes, kind=kind, home=home
            )
        )
    except RenderError:
        raise
    except ValueError as error:
        raise RenderError(str(error)) from error


# --------------------------------------------------------------------------
# storage-report subcommand
# --------------------------------------------------------------------------


def _read_json(path: Path, what: str) -> Dict[str, Any]:
    import json

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise RenderError("cannot read {0} {1}: {2}".format(what, path, error)) from error
    except ValueError as error:
        raise RenderError("{0} {1} is not valid JSON: {2}".format(what, path, error)) from error
    if not isinstance(data, dict):
        raise RenderError("{0} {1} must hold a JSON object".format(what, path))
    return data


def run(args: Any) -> int:
    """``storage-report <analysis.json> [--notes n.json] [-o page.html] [--serve]``."""

    analysis_path = Path(getattr(args, "analysis"))
    analysis = _read_json(analysis_path, "analysis.json")
    notes_path = getattr(args, "notes", None)
    notes = _read_json(Path(notes_path), "notes.json") if notes_path else None
    lang = getattr(args, "lang", None)

    if bool(getattr(args, "serve", False)):
        from . import server as server_module

        return server_module.serve_review(
            analysis_path,
            port=int(getattr(args, "port", 0) or 0),
            allow_permanent_delete=bool(getattr(args, "allow_permanent_delete", False)),
            open_browser=bool(getattr(args, "open_browser", True)),
            notes=notes,
            lang=lang,
        )

    html = render(analysis, mode="static", lang=lang, notes=notes)
    output = Path(getattr(args, "output", None) or (analysis_path.resolve().parent / "report.html"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(output)
    return 0
