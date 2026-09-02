"""scan, report, apply: the three steps a person actually runs.

The engine grew two entrances, and for a while the person running it got two of
everything: two scans, two reports, two approval files.  This module puts the
one road back:

    scan    one read-only pass over the folder and, unless told otherwise, over
            the machine; writes plan.json and storage-scan.json side by side in
            the folder's own managed directory
    report  one page from whatever that directory holds -- the plan half, the
            analysis half, or both -- with the after picture at the end
    apply   one decisions file, the moves first and the cleanup second, each
            half going through the very same engine the old subcommands used

Nothing here decides what is safe.  ``executor.run_document`` and
``dispose.run_document`` own every check, every refusal and every paper trail;
this module only reads files, works out which half is which, and prints.

The step-by-step subcommands (plan, build, review, dispose, storage-report,
undo, status, clear-tags) all still work and all still write the same files.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import i18n

#: The decisions file the combined page exports.
DECISIONS_SCHEMA = "carl-file-organizer/decisions"

#: The older, storage-only decisions file.  ``dispose`` still takes it.
STORAGE_DECISIONS_SCHEMA = "carl-file-organizer/storage-decisions"

#: Everything ``scan`` writes and ``report`` looks for, all in one directory.
PLAN_NAME = "plan.json"
STORAGE_SCAN_NAME = "storage-scan.json"
ANALYSIS_NAME = "analysis.json"
NOTES_NAME = "notes.json"
REPORT_NAME = "report.html"

#: ``carl_file_organizer/flow.py`` -> ``scripts/storage_scan.py``
STORAGE_SCAN_PATH = Path(__file__).resolve().parent.parent / "storage_scan.py"

_SCANNER: Optional[Any] = None


class FlowError(RuntimeError):
    """One sentence about a file that is missing, unreadable or the wrong shape."""


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def read_json(path: Path, what: str) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise FlowError("cannot read {0} {1}: {2}".format(what, path, error)) from error
    except ValueError as error:
        raise FlowError("{0} {1} is not valid JSON: {2}".format(what, path, error)) from error
    if not isinstance(data, dict):
        raise FlowError("{0} {1} must hold a JSON object".format(what, path))
    return data


def _optional_json(path: Optional[Path], what: str) -> Dict[str, Any]:
    if path is None or not Path(path).is_file():
        return {}
    return read_json(Path(path), what)


def storage_scanner() -> Any:
    """The ``storage_scan`` script, loaded once by path.

    It sits next to the package rather than inside it because a person runs it
    by hand, so it is loaded the same way ``render`` loads ``build_report``.
    """

    global _SCANNER
    if _SCANNER is not None:
        return _SCANNER
    if not STORAGE_SCAN_PATH.is_file():
        raise FlowError("the whole-machine scanner is missing: {0}".format(STORAGE_SCAN_PATH))
    spec = importlib.util.spec_from_file_location("carl_file_organizer._storage_scan", str(STORAGE_SCAN_PATH))
    if spec is None or spec.loader is None:
        raise FlowError("cannot load the whole-machine scanner from {0}".format(STORAGE_SCAN_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # noqa: BLE001 - a broken scanner is one sentence
        sys.modules.pop(spec.name, None)
        raise FlowError("the whole-machine scanner failed to load: {0}".format(error)) from error
    _SCANNER = module
    return module


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------


def run_scan(args: Any) -> int:
    """``scan <dir> [--lang] [--no-storage] [--budget-seconds N]``: read only, twice over."""

    from . import config as config_module
    from . import planner

    cfg = getattr(args, "config", None)
    if cfg is None:
        cfg = config_module.resolve_config(
            Path(args.source), lang=getattr(args, "lang", None), profile=getattr(args, "profile", None)
        )
        args.config = cfg
    lang = cfg.lang

    # The combined report is rendered a step later; a tidy-up-only page here
    # would only be a second thing to open and a second thing to keep in step.
    args.write_report = False
    code = int(planner.run(args))
    if code:
        return code

    managed = config_module.managed_dir(cfg)
    managed.mkdir(parents=True, exist_ok=True)

    if not bool(getattr(args, "storage", True)):
        print(i18n.t("cli_storage_skipped", lang))
    else:
        try:
            scanner = storage_scanner()
            data = scanner.run_scan(
                home=getattr(args, "home", None),
                budget_seconds=float(getattr(args, "budget_seconds", None) or 60.0),
            )
        except Exception as error:  # noqa: BLE001 - the tidy-up half is still worth having
            print(i18n.t("cli_storage_failed", lang, error=error), file=sys.stderr)
        else:
            target = managed / STORAGE_SCAN_NAME
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(i18n.t("cli_storage_written", lang, path=target))

    print(
        i18n.t(
            "cli_next_steps",
            lang,
            notes=managed / NOTES_NAME,
            analysis=managed / ANALYSIS_NAME,
            managed=managed,
        )
    )
    return 0


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------


def collect(managed: Path, analysis_path: Optional[Path] = None) -> Dict[str, Any]:
    """The combined document for one managed directory: the halves that exist.

    ``plan.json`` is the tidy-up half.  The whole-machine half is the Agent's
    ``analysis.json``, never the raw ``storage-scan.json``: the scan has no
    colours and no plain-language lines, so putting it on a page would show
    buttons nobody vouched for.
    """

    managed = Path(managed)
    document: Dict[str, Any] = {}
    plan_path = managed / PLAN_NAME
    if plan_path.is_file():
        document["plan"] = read_json(plan_path, PLAN_NAME)
    chosen = Path(analysis_path) if analysis_path else managed / ANALYSIS_NAME
    if chosen.is_file():
        document["analysis"] = read_json(chosen, ANALYSIS_NAME)
    elif analysis_path is not None:
        raise FlowError("cannot read {0} {1}: no such file".format(ANALYSIS_NAME, chosen))
    return document


def run_report(args: Any) -> int:
    """``report <managed_dir> [--notes n.json] [--analysis a.json] [-o page.html] [--serve]``."""

    managed = Path(getattr(args, "managed_dir")).expanduser()
    analysis_arg = getattr(args, "analysis", None)
    document = collect(managed, Path(analysis_arg).expanduser() if analysis_arg else None)
    lang = getattr(args, "lang", None) or (document.get("plan") or {}).get("lang") or (
        document.get("analysis") or {}
    ).get("lang") or "en"
    if not document:
        raise FlowError(i18n.t("cli_nothing_to_report", lang, managed=managed))

    notes_arg = getattr(args, "notes", None)
    notes_path = Path(notes_arg).expanduser() if notes_arg else managed / NOTES_NAME
    notes = _optional_json(notes_path, NOTES_NAME) or None

    if bool(getattr(args, "serve", False)):
        from . import server as server_module

        return server_module.serve_review(
            document,
            port=int(getattr(args, "port", 0) or 0),
            allow_permanent_delete=bool(getattr(args, "allow_permanent_delete", False)),
            open_browser=bool(getattr(args, "open_browser", True)),
            managed_dir=managed,
            notes=notes,
            lang=getattr(args, "lang", None),
        )

    from . import render

    html = render.render(document, mode="static", lang=getattr(args, "lang", None), notes=notes)
    output = Path(getattr(args, "output", None) or (managed / REPORT_NAME)).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    print(i18n.t("cli_report_combined", lang, path=output))
    return 0


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------


def _halves(decisions: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    plan = decisions.get("plan")
    storage = decisions.get("storage")
    return (plan if isinstance(plan, dict) else {}), (storage if isinstance(storage, dict) else {})


def _managed_of(plan: Dict[str, Any]) -> Optional[Path]:
    """The tidy-up half's managed directory, so the cleanup's paper trail joins it.

    One scan, one report, one approval file, one folder holding the record of
    what happened.  The page exports a plan with ``managed_dir`` stripped and
    only its ``$HOME``-relative twin left, which is exactly what this expands.
    """

    from . import paths

    absolute = plan.get("managed_dir")
    if isinstance(absolute, str) and absolute:
        return Path(absolute).expanduser()
    portable = plan.get("managed_dir_portable")
    if not isinstance(portable, str) or not portable:
        return None
    try:
        return Path(paths.expand_portable(portable, paths.plan_home(plan)))
    except Exception:  # noqa: BLE001 - a guess that fails just means the old location
        return None


def _source_document(
    section: Dict[str, Any], override: Any, managed: Optional[Path], name: str
) -> Dict[str, Any]:
    """The plan or analysis a half was decided against, in order of trust.

    A file named on the command line wins, then the copy the page put inside
    the decisions file, then the one sitting in the managed directory.
    """

    if override:
        return read_json(Path(override).expanduser(), name)
    document = section.get("document")
    if isinstance(document, dict):
        return document
    if managed and (managed / name).is_file():
        return read_json(managed / name, name)
    return {}


def _approved_plan(section: Dict[str, Any], document: Dict[str, Any], decisions: Dict[str, Any]) -> Dict[str, Any]:
    """The plan the executor validates: the source document plus the ticked ids."""

    plan = dict(document)
    plan["approved_action_ids"] = [str(i) for i in (section.get("approved_action_ids") or [])]
    plan["overrides"] = list(section.get("overrides") or [])
    plan["approved_at"] = decisions.get("decided_at") or _now()
    plan["approved_by"] = decisions.get("decided_by") or "decisions"
    return plan


def run_apply(args: Any) -> int:
    """``apply <decisions.json>``: the moves first, the cleanup second, one summary.

    An older ``approved.json`` and an older storage decisions file both still
    work; they are recognised by what they carry and handed to the subcommand
    that has always owned them.
    """

    from . import dispose as dispose_module
    from . import executor as executor_module

    path = Path(args.approval).expanduser()
    decisions = read_json(path, "decisions file")
    schema = str(decisions.get("schema") or "")

    if schema != DECISIONS_SCHEMA:
        if schema == STORAGE_DECISIONS_SCHEMA:
            return _apply_storage_only(args, decisions)
        # An approved.json is the plan itself; the executor has always read it.
        return int(executor_module.run(args))

    lang = getattr(args, "lang", None) or "en"
    dry_run = bool(getattr(args, "dry_run", False))
    allow_permanent = bool(getattr(args, "allow_permanent_delete", False))
    plan_section, storage_section = _halves(decisions)
    managed = Path(getattr(args, "managed_dir", None)).expanduser() if getattr(args, "managed_dir", None) else None

    plan_ids = [str(i) for i in (plan_section.get("approved_action_ids") or [])]
    item_ids = [str(i) for i in (storage_section.get("item_ids") or [])]
    if not plan_ids and not item_ids:
        print(i18n.t("cli_decisions_empty", lang))
        return 0

    # Both documents are found before either half runs, so a missing analysis
    # is a refusal up front rather than a half-applied batch.
    plan_document = (
        _source_document(plan_section, getattr(args, "plan", None), managed, PLAN_NAME) if plan_ids else {}
    )
    if plan_ids and not plan_document:
        raise FlowError(i18n.t("cli_decisions_no_plan", lang))
    analysis_document = (
        _source_document(storage_section, getattr(args, "analysis", None), managed, ANALYSIS_NAME) if item_ids else {}
    )
    if item_ids and not analysis_document:
        raise FlowError(i18n.t("cli_decisions_no_analysis", lang))
    lang = (
        getattr(args, "lang", None)
        or plan_document.get("lang")
        or analysis_document.get("lang")
        or "en"
    )
    if managed is None:
        managed = _managed_of(plan_document)

    codes = {"plan": 0, "storage": 0}

    if plan_ids:
        print("== " + i18n.t("cli_decisions_plan", lang))
        codes["plan"] = int(
            executor_module.run_document(
                _approved_plan(plan_section, plan_document, decisions),
                dry_run=dry_run,
                allow_permanent_delete=allow_permanent,
                audit=Path(args.audit).expanduser() if getattr(args, "audit", None) else None,
                approval_path=path,
            )
        )

    if item_ids:
        print("== " + i18n.t("cli_decisions_storage", lang))
        codes["storage"] = int(
            dispose_module.run_document(
                analysis_document,
                _storage_decisions(storage_section, decisions),
                dry_run=dry_run,
                allow_permanent_delete=allow_permanent,
                managed=managed,
                lang=getattr(args, "lang", None),
            )
        )

    print(i18n.t("cli_decisions_summary", lang, plan=codes["plan"], storage=codes["storage"]))
    return codes["plan"] or codes["storage"]


def _storage_decisions(section: Dict[str, Any], decisions: Dict[str, Any]) -> Dict[str, Any]:
    item_ids = [str(i) for i in (section.get("item_ids") or [])]
    actions = section.get("actions") if isinstance(section.get("actions"), dict) else {}
    return {
        "schema": STORAGE_DECISIONS_SCHEMA,
        "schema_version": 1,
        "item_ids": item_ids,
        "actions": {i: str(actions.get(i) or "trash") for i in item_ids},
        "decided_at": decisions.get("decided_at") or _now(),
        "decided_by": decisions.get("decided_by") or "decisions",
    }


def _apply_storage_only(args: Any, decisions: Dict[str, Any]) -> int:
    """A storage-only decisions file still applies, as long as an analysis is at hand."""

    from . import dispose as dispose_module

    lang = getattr(args, "lang", None) or "en"
    override = getattr(args, "analysis", None)
    managed = Path(getattr(args, "managed_dir", None)).expanduser() if getattr(args, "managed_dir", None) else None
    if override:
        document = read_json(Path(override).expanduser(), ANALYSIS_NAME)
    elif managed and (managed / ANALYSIS_NAME).is_file():
        document = read_json(managed / ANALYSIS_NAME, ANALYSIS_NAME)
    else:
        raise FlowError(i18n.t("cli_decisions_no_analysis", lang))
    return int(
        dispose_module.run_document(
            document,
            decisions,
            dry_run=bool(getattr(args, "dry_run", False)),
            allow_permanent_delete=bool(getattr(args, "allow_permanent_delete", False)),
            managed=managed,
            lang=getattr(args, "lang", None),
        )
    )


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------


def run(args: Any) -> int:
    command = getattr(args, "command", "")
    if command == "scan":
        return run_scan(args)
    if command == "report":
        return run_report(args)
    if command == "apply":
        return run_apply(args)
    raise FlowError("flow.run does not own the subcommand {0}".format(command))
