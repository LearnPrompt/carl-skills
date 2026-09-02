"""Command-line interface: argument parsing and dispatch only.

Every subcommand resolves to ``<module>.run(args)``.  No business logic lives
here, so the subcommands and their flag names are frozen from day zero and each
work package only fills in its own module.

    plan       -> carl_file_organizer.planner.run
    build      -> carl_file_organizer.notes.run
    apply      -> carl_file_organizer.executor.run
    review     -> carl_file_organizer.server.run
    undo       -> carl_file_organizer.undo.run
    status     -> carl_file_organizer.status.run
    clear-tags -> carl_file_organizer.tags.run

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
    "plan": "planner",
    "build": "notes",
    "apply": "executor",
    "review": "server",
    "undo": "undo",
    "status": "status",
    "clear-tags": "tags",
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
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    apply_cmd = subparsers.add_parser("apply", help="apply only the approved actions")
    apply_cmd.add_argument("approval", type=Path)
    apply_cmd.add_argument("--dry-run", action="store_true")
    apply_cmd.add_argument("--allow-permanent-delete", action="store_true")
    apply_cmd.add_argument("--audit", type=Path, default=None)

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
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command
    module_name = COMMAND_MODULES[command]
    lang = getattr(args, "lang", None) or "en"

    try:
        if command == "plan":
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
