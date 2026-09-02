"""Put the file organizer's scripts directory on ``sys.path``.

The engine lives inside a skill folder (``skills/ops/carl-file-organizer/scripts``)
rather than in an installed package, so every test that says
``import carl_file_organizer`` imports this module first.  Importing the whole
package once is much cheaper than loading twenty modules by file path, and it
keeps the intra-package imports (``from . import guard``) working.

Importing this module twice is free; the insert is guarded.
"""

from __future__ import annotations

import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
SCRIPTS_DIR = os.path.join(REPO_ROOT, "skills", "ops", "carl-file-organizer", "scripts")
FIXTURES_DIR = os.path.join(TESTS_DIR, "fixtures", "carl_file_organizer")

for _entry in (SCRIPTS_DIR, TESTS_DIR):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
