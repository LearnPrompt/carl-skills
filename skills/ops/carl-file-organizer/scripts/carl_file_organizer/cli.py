"""Command-line interface: argument parsing and dispatch only.

Every subcommand resolves to ``<module>.run(args)``.  No business logic lives
here, so the subcommands and their flag names are frozen from day zero and each
work package only fills in its own module.

Three of them are the road most people walk:

    scan           -> carl_file_organizer.flow.run   one read-only pass, both halves
    report         -> carl_file_organizer.flow.run   one page out of one folder
    apply          -> carl_file_organizer.flow.run   one decisions file, both halves

The rest are the same work split into steps, and every one of them still writes
the same files it always did:

    plan           -> carl_file_organizer.planner.run
    build          -> carl_file_organizer.notes.run
    review         -> carl_file_organizer.server.run
    undo           -> carl_file_organizer.undo.run
    status         -> carl_file_organizer.status.run
    clear-tags     -> carl_file_organizer.tags.run
    storage-report -> carl_file_organizer.render.run
    dispose        -> carl_file_organizer.dispose.run

``apply`` still reads an older approved.json and an older storage decisions
file; ``flow`` recognises them and hands them to the module that owns them.

A module that has no ``run`` yet produces a one-line message and exit code 2,
never an ImportError traceback.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional

from . import __version__, i18n

#: subcommand name -> module inside this package that owns it
COMMAND_MODULES = {
    "scan": "flow",
    "report": "flow",
    "plan": "planner",
    "build": "notes",
    "apply": "flow",
    "review": "server",
    "undo": "undo",
    "status": "status",
    "clear-tags": "tags",
    "storage-report": "render",
    "dispose": "dispose",
}


def _iso(text: str) -> datetime:
    try:
        return datetime.fromisoformat(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "--now must be an ISO 8601 timestamp, for example 2026-09-02T10:15:00"
        ) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="carl-file-organizer",
        description="Human-first file organization with explicit approval.",
        epilog=(
            "Three steps do the job: scan <dir>, then report <managed_dir>, then "
            "apply <decisions.json> --dry-run.  The other subcommands are those "
            "same steps taken apart, for when you want one piece on its own."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- scan ---------------------------------------------------------------
    scan = subparsers.add_parser(
        "scan", help="read-only pass over the folder and the machine (step 1 of 3)"
    )
    scan.add_argument("source", nargs="?", type=Path, default=Path.home() / "Downloads")
    scan.add_argument("--lang", choices=["zh", "en"], default=None)
    scan.add_argument("--profile", choices=["tiered", "simple"], default=None)
    scan.add_argument(
        "--no-storage",
        dest="storage",
        action="store_false",
        help="skip the whole-machine inventory and only plan the folder",
    )
    scan.add_argument("--storage", dest="storage", action="store_true", help=argparse.SUPPRESS)
    scan.add_argument(
        "--budget-seconds",
        type=float,
        default=60.0,
        help="hard ceiling on the whole-machine scan (default 60)",
    )
    scan.add_argument("--home", default=None, help="the home directory to inventory (default: this account)")
    scan.add_argument("--hash-duplicates", action="store_true")
    scan.add_argument("--large-mb", type=int, default=500)
    scan.add_argument("--target-percent", type=float, default=90.0)
    scan.add_argument("--no-dir-sizes", dest="dir_sizes", action="store_false")
    scan.add_argument("--no-permanent-delete-options", dest="permanent_delete_options", action="store_false")
    scan.add_argument("--now", type=_iso, default=None, help="fix the clock (tests and replays)")
    scan.add_argument("--allow-outside-home", action="store_true")
    scan.add_argument("--allow-referenced", action="store_true")
    scan.set_defaults(storage=True, dir_sizes=True, permanent_delete_options=True)

    # -- report -------------------------------------------------------------
    report = subparsers.add_parser(
        "report", help="one page out of one managed directory (step 2 of 3)"
    )
    report.add_argument("managed_dir", type=Path, help="the folder scan wrote plan.json into")
    report.add_argument("--notes", type=Path, default=None, help="notes.json (default: the one in that folder)")
    report.add_argument("--analysis", type=Path, default=None, help="analysis.json (default: the one in that folder)")
    report.add_argument("-o", "--output", type=Path, default=None, help="where to write report.html")
    report.add_argument("--serve", action="store_true", help="serve the page instead of writing it")
    report.add_argument("--port", type=int, default=0)
    report.add_argument("--no-open", dest="open_browser", action="store_false")
    report.add_argument("--allow-permanent-delete", action="store_true")
    report.add_argument("--lang", choices=["zh", "en"], default=None)
    report.set_defaults(open_browser=True)

    # -- plan ---------------------------------------------------------------
    plan = subparsers.add_parser("plan", help="scan read-only and write a review page")
    plan.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=Path.home() / "Downloads",
        help="folder to scan (default: ~/Downloads)",
    )
    plan.add_argument("--lang", choices=["zh", "en"], default=None)
    plan.add_argument("--profile", choices=["tiered", "simple"], default=None)
    plan.add_argument("--hash-duplicates", action="store_true")
    plan.add_argument("--large-mb", type=int, default=500)
    plan.add_argument("--target-percent", type=float, default=90.0)
    plan.add_argument("--no-dir-sizes", dest="dir_sizes", action="store_false")
    plan.add_argument(
        "--no-permanent-delete-options",
        dest="permanent_delete_options",
        action="store_false",
    )
    plan.add_argument("--now", type=_iso, default=None, help="fix the clock (tests and replays)")
    plan.add_argument("--allow-outside-home", action="store_true")
    plan.add_argument(
        "--allow-referenced",
        action="store_true",
        help="downgrade referenced-elsewhere holds to a warning",
    )
    plan.set_defaults(dir_sizes=True, permanent_delete_options=True)

    # -- build --------------------------------------------------------------
    build = subparsers.add_parser(
        "build", help="lay an agent's notes.json over a plan.json"
    )
    build.add_argument("plan", type=Path, help="the plan.json to annotate")
    build.add_argument(
        "--notes",
        type=Path,
        default=None,
        help="notes.json written by the agent; without it the plan is only rewritten",
    )
    build.add_argument(
        "--output",
        type=Path,
        default=None,
        help="where to write the annotated plan (default: in place)",
    )
    build.add_argument(
        "--report",
        action="store_true",
        help="also re-render report.html next to the output plan",
    )
    build.add_argument("--lang", choices=["zh", "en"], default=None)

    # -- apply --------------------------------------------------------------
    apply_cmd = subparsers.add_parser(
        "apply", help="act on one decisions file, moves first then cleanup (step 3 of 3)"
    )
    apply_cmd.add_argument("approval", type=Path, help="carl-file-organizer-decisions.json (or an older approved.json)")
    apply_cmd.add_argument("--dry-run", action="store_true")
    apply_cmd.add_argument("--allow-permanent-delete", action="store_true")
    apply_cmd.add_argument("--audit", type=Path, default=None)
    apply_cmd.add_argument("--plan", type=Path, default=None, help="plan.json, when the decisions file carries none")
    apply_cmd.add_argument("--analysis", type=Path, default=None, help="analysis.json, when the decisions file carries none")
    apply_cmd.add_argument("--managed-dir", type=Path, default=None, help="where to look for those two, and where the paper trail lands")
    apply_cmd.add_argument("--lang", choices=["zh", "en"], default=None)

    # -- review -------------------------------------------------------------
    review = subparsers.add_parser("review", help="open the review page")
    review.add_argument("plan", type=Path)
    review.add_argument("--serve", action="store_true", required=True)
    review.add_argument("--port", type=int, default=0)
    review.add_argument("--no-open", dest="open_browser", action="store_false")
    review.add_argument("--allow-permanent-delete", action="store_true")
    review.set_defaults(open_browser=True)

    # -- undo ---------------------------------------------------------------
    undo = subparsers.add_parser("undo", help="move things back where they came from")
    undo.add_argument("record", type=Path, help="audit.jsonl or a manifest .tsv")
    undo.add_argument("--dry-run", action="store_true")

    # -- status -------------------------------------------------------------
    status = subparsers.add_parser("status", help="last tidy-up and current mess")
    status.add_argument(
        "source", nargs="?", type=Path, default=Path.home() / "Downloads"
    )
    status.add_argument("--lang", choices=["zh", "en"], default=None)
    status.add_argument("--allow-outside-home", action="store_true")

    # -- storage-report -----------------------------------------------------
    storage_report = subparsers.add_parser(
        "storage-report", help="render the whole-machine page from an analysis.json"
    )
    storage_report.add_argument("analysis", type=Path, help="analysis.json written by the agent")
    storage_report.add_argument(
        "--notes",
        type=Path,
        default=None,
        help="notes.json laid over the analysis before rendering",
    )
    storage_report.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="where to write report.html (default: next to the analysis)",
    )
    storage_report.add_argument(
        "--serve",
        action="store_true",
        help="serve the page on 127.0.0.1 with one-click disposal instead of writing a file",
    )
    storage_report.add_argument("--port", type=int, default=0)
    storage_report.add_argument("--no-open", dest="open_browser", action="store_false")
    storage_report.add_argument("--allow-permanent-delete", action="store_true")
    storage_report.add_argument("--lang", choices=["zh", "en"], default=None)
    storage_report.set_defaults(open_browser=True)

    # -- dispose ------------------------------------------------------------
    dispose = subparsers.add_parser(
        "dispose", help="act on the decisions exported from the whole-machine page"
    )
    dispose.add_argument("analysis", type=Path, help="the analysis.json those decisions came from")
    dispose.add_argument("decisions", type=Path, help="carl-file-organizer-decisions.json")
    dispose.add_argument("--dry-run", action="store_true")
    dispose.add_argument("--allow-permanent-delete", action="store_true")
    dispose.add_argument("--lang", choices=["zh", "en"], default=None)

    # -- clear-tags ---------------------------------------------------------
    clear = subparsers.add_parser("clear-tags", help="remove the temporary Finder tag")
    clear.add_argument(
        "source", nargs="?", type=Path, default=Path.home() / "Downloads"
    )
    clear.add_argument("--from", dest="from_lists", action="append", type=Path, default=None)
    clear.add_argument("--all-lists", action="store_true")
    clear.add_argument("--tag", default=None)
    clear.add_argument("--dry-run", action="store_true")

    return parser


def _module_run(module_name: str) -> Optional[Callable[[Any], int]]:
    """Return ``module.run`` when it exists, without letting ImportError escape."""

    full_name = "{0}.{1}".format(__package__, module_name)
    try:
        if importlib.util.find_spec(full_name) is None:
            return None
    except (ImportError, ValueError):
        return None
    module = importlib.import_module(full_name)
    run = getattr(module, "run", None)
    return run if callable(run) else None


def _forgiving_console() -> None:
    """Never let a code page turn a finished job into a failure.

    Every line this tool prints can carry Chinese, and on Windows a redirected
    stdout is a legacy code page rather than UTF-8: ``print`` then raises
    UnicodeEncodeError, the CLI boundary below catches it, and a build that
    wrote its plan correctly reports exit code 2.  The text is the report, not
    the deliverable, so unrepresentable characters get escaped and the run goes
    on.  A console that can spell them is untouched.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # a stream somebody replaced, in a test or a host
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (ValueError, OSError):
            continue


def _not_implemented(command: str, module_name: str, lang: str) -> int:
    print(
        "error: "
        + i18n.t(
            "cli_not_implemented",
            lang,
            command=command,
            module="{0}.{1}".format(__package__, module_name),
        ),
        file=sys.stderr,
    )
    return 2


def _prepare_config(args: argparse.Namespace) -> Any:
    """Shared front half of plan/status: refuse bad roots, resolve settings."""

    from . import config as config_module
    from . import paths

    root = paths.refuse_root(
        args.source, allow_outside_home=getattr(args, "allow_outside_home", False)
    )
    cfg = config_module.resolve_config(root, lang=args.lang, profile=getattr(args, "profile", None))
    for message in cfg.warnings:
        print(i18n.t("warning_prefix", cfg.lang) + message, file=sys.stderr)
    return cfg


def main(argv: Optional[List[str]] = None) -> int:
    _forgiving_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command
    module_name = COMMAND_MODULES[command]
    lang = getattr(args, "lang", None) or "en"

    try:
        if command in ("plan", "scan"):
            from . import config as config_module

            cfg = _prepare_config(args)
            lang = cfg.lang
            written = config_module.save_dotfile(cfg, only_if_missing=True)
            if written is not None:
                print(i18n.t("cli_dotfile_written", cfg.lang, path=written))
            print(i18n.t("cli_lang_source", cfg.lang, lang=cfg.lang, source=cfg.lang_source))
            args.config = cfg
            run = _module_run(module_name)
            if run is None:
                return _not_implemented(command, module_name, cfg.lang)
            return int(run(args))

        if command == "status":
            cfg = _prepare_config(args)
            lang = cfg.lang
            args.config = cfg

        run = _module_run(module_name)
        if run is None:
            return _not_implemented(command, module_name, lang)
        return int(run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # noqa: BLE001 - CLI boundary: one clean line, never a traceback
        print("error: {0}".format(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
