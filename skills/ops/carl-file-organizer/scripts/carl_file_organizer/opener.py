"""Show a path to the person sitting in front of the machine.

This is the only thing offered for the items the tool refuses to touch: it
cannot move them, it cannot dispose of them, but it can put the folder on
screen with the item already selected, so the decision is made by a person
looking at the real thing.

Nothing here writes, deletes or renames.  Every call goes through
:func:`subprocess.Popen` with an argument list and never through a shell, so a
file called ``$(rm -rf ~).pdf`` is a file with a silly name and nothing else.

    reveal(Path("~/Downloads/report.pdf").expanduser())

Returns True when the platform's file manager was launched, False when there is
nothing to launch it with; it never raises for a missing file manager, because
"I could not show you this" is not worth ending a review session over.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional

DARWIN = "darwin"
WINDOWS = "win32"

#: Handed to Popen so a file manager that lives a long time does not keep the
#: review server alive with it.
_POPEN_KW = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def supported(platform: Optional[str] = None) -> bool:
    """True when this machine has a file manager we know how to call."""

    return reveal_command(Path.home(), platform=platform) is not None


def reveal_command(path: Path, *, platform: Optional[str] = None) -> Optional[List[str]]:
    """The exact argv used to reveal ``path``, or None when there is none.

    Split out from :func:`reveal` so the shape of each platform's command can be
    asserted from any other platform.  macOS and Windows both select the item
    itself; ``xdg-open`` has no such option anywhere, so on Linux the parent
    folder is opened and the item is merely visible in it.
    """

    system = platform or sys.platform
    absolute = os.path.abspath(str(path))

    if system == DARWIN:
        return ["open", "-R", absolute]
    if system == WINDOWS:
        # explorer wants exactly this comma with no space after it, and it is
        # one argument, not two.
        return ["explorer", "/select,{0}".format(absolute)]
    opener = shutil.which("xdg-open")
    if opener is None:
        return None
    return [opener, os.path.dirname(absolute) or absolute]


def reveal(
    path: Path,
    *,
    platform: Optional[str] = None,
    runner: Optional[Callable[..., Any]] = None,
) -> bool:
    """Open the file manager with ``path`` shown.  Never raises for a missing one."""

    argv = reveal_command(Path(path), platform=platform)
    if argv is None:
        return False
    launch = runner if runner is not None else subprocess.Popen
    try:
        launch(argv, **_POPEN_KW)
    except OSError:
        return False
    return True
