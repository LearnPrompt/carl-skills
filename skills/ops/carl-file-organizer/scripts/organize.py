#!/usr/bin/env python3
"""Entry point for the file organizer: tidy one folder, with approval in between.

The engine is the ``carl_file_organizer`` package sitting next to this file.
Nothing is installed, nothing is on PYTHONPATH, so this script puts its own
directory at the front of ``sys.path`` and hands over to the package CLI.  That
is the whole job; every flag and every subcommand lives in
``carl_file_organizer/cli.py``.

Usage (run it with any Python 3.9 or newer; there are no dependencies):

    python3 organize.py plan  ~/Downloads --lang zh
    python3 organize.py build ~/Downloads/00_.../plan.json --notes notes.json
    python3 organize.py review <plan.json> --serve
    python3 organize.py apply  <approved.json>
    python3 organize.py undo   <audit.jsonl>
    python3 organize.py status ~/Downloads
    python3 organize.py clear-tags ~/Downloads
    python3 organize.py --version

The second entrance, the whole-machine inventory, shares the same engine:

    python3 storage_scan.py --out storage-scan.json      # read only
    python3 organize.py storage-report <analysis.json> [--serve]
    python3 organize.py dispose <analysis.json> <decisions.json> --dry-run

``plan``, ``status`` and ``storage-report`` only read.  ``build`` only rewrites
the plan's prose.  ``apply`` and ``dispose`` are the two that touch anything, and
they touch only the ids you approved.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from carl_file_organizer.cli import main  # noqa: E402 - the path shim has to run first


if __name__ == "__main__":
    sys.exit(main())
