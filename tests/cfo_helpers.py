"""Shared scaffolding for the engine tests.

Two rules keep these tests honest: time is always injected, and the safety net
never touches the real machine.  ``GUARD_OFFLINE`` gives every planner test an
empty reference list, an empty symlink scan root and no lsof at all, so a test
run cannot depend on what happens to be open on the developer's laptop.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

TZ = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=TZ)

#: The safety net, wired to nothing.
GUARD_OFFLINE: Dict[str, Any] = {
    "reference_files": [],
    "scan_roots": [],
    "lsof_enabled": False,
}


def guard_with(**overrides: Any) -> Dict[str, Any]:
    options = dict(GUARD_OFFLINE)
    options.update(overrides)
    return options


def write(path: Path, content: str = "placeholder\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def age(path: Path, hours: float, now: datetime = NOW) -> Path:
    """Backdate ``path`` so it reads as ``hours`` old relative to ``now``."""

    when = (now - timedelta(hours=hours)).timestamp()
    os.utime(str(path), (when, when))
    return path


def fake_lsof(mapping: Optional[Dict[str, str]] = None):
    """An lsof stand-in: path substring -> ``command,pid``."""

    table = mapping or {}

    class _Result(object):
        def __init__(self, stdout: str, returncode: int = 0) -> None:
            self.stdout = stdout
            self.returncode = returncode

    def runner(argv, timeout_s):  # noqa: ANN001 - mirrors subprocess.run's shape
        lines = []
        for argument in argv:
            for needle, who in table.items():
                if needle in str(argument):
                    command, pid = who.split(",")
                    lines.append("p{0}".format(pid))
                    lines.append("c{0}".format(command))
                    lines.append("n{0}".format(argument))
        return _Result("\n".join(lines) + ("\n" if lines else ""), 0 if lines else 1)

    return runner


def action_for(plan: Dict[str, Any], filename: str, kind: str = "move") -> Dict[str, Any]:
    for action in plan["actions"]:
        if action["filename"] == filename and action["kind"] == kind:
            return action
    raise AssertionError(
        "no {0} action for {1}; saw {2}".format(
            kind,
            filename,
            sorted({(a["filename"], a["kind"]) for a in plan["actions"]}),
        )
    )


def actions_for(plan: Dict[str, Any], filename: str):
    return [action for action in plan["actions"] if action["filename"] == filename]
