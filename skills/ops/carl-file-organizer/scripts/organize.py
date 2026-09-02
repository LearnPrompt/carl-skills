#!/usr/bin/env python3
"""Entry point for the file organizer: tidy one folder, with approval in between.

The engine is the ``carl_file_organizer`` package sitting next to this file.
Nothing is installed, nothing is on PYTHONPATH, so this script puts its own
directory at the front of ``sys.path`` and hands over to the package CLI.  That
is the whole job; every flag and every subcommand lives in
``carl_file_organizer/cli.py``.

Three commands do the job (any Python 3.9 or newer; there are no dependencies):

    python3 organize.py scan   ~/Downloads --lang zh
    python3 organize.py report ~/Downloads/00_下载目录管理
    python3 organize.py apply  <decisions.json> --dry-run

``scan`` reads the folder and, unless you pass ``--no-storage``, the machine,
and writes plan.json and storage-scan.json into the folder's managed directory.
The Agent then writes notes.json and analysis.json next to them.  ``report``
turns whatever that directory holds into one page: the cleanup and the moves in
the same three colour bands, the after picture below them, and one button that
exports one decisions file (or, with ``--serve``, runs the lot straight away).
``apply`` acts on that file, the moves first and the cleanup second.

The same work split into steps, for when you want one piece on its own:

    python3 organize.py plan  ~/Downloads --lang zh
    python3 organize.py build <plan.json> --notes notes.json --report
    python3 organize.py review <plan.json> --serve
    python3 organize.py storage-report <analysis.json> [--serve]
    python3 organize.py dispose <analysis.json> <decisions.json> --dry-run
    python3 organize.py undo   <audit.jsonl>
    python3 organize.py status ~/Downloads
    python3 organize.py clear-tags ~/Downloads
    python3 organize.py --version

``scan``, ``report``, ``plan``, ``status`` and ``storage-report`` only read.
``build`` only rewrites the plan's prose.  ``apply`` and ``dispose`` are the two
that touch anything, and they touch only the ids you approved.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from carl_file_organizer.cli import main  # noqa: E402 - the path shim has to run first


if __name__ == "__main__":
    sys.exit(main())
