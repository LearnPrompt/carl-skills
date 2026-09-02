"""Showing a path to a person, on three platforms, from one of them.

The command shape is asserted rather than the effect, because the effect is a
window opening on somebody's screen.  What matters and what can be checked here
is that no shell is involved and that the path arrives as one argument.
"""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from carl_file_organizer import opener


class Launcher(object):
    """Stands in for subprocess.Popen and records the call."""

    def __init__(self, error: bool = False) -> None:
        self.calls = []
        self.kwargs = []
        self.error = error

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.kwargs.append(dict(kwargs))
        if self.error:
            raise OSError("no such file manager")
        return object()


class CommandShapeTests(unittest.TestCase):
    def test_macos_selects_the_item_itself(self) -> None:
        argv = opener.reveal_command(Path("/tmp/report.pdf"), platform="darwin")
        self.assertEqual(argv[:2], ["open", "-R"])
        self.assertEqual(argv[2], os.path.abspath("/tmp/report.pdf"))

    def test_windows_passes_one_argument_with_the_comma_attached(self) -> None:
        argv = opener.reveal_command(Path("C:/Users/someone/report.pdf"), platform="win32")
        self.assertEqual(argv[0], "explorer")
        self.assertEqual(len(argv), 2)
        self.assertTrue(argv[1].startswith("/select,"))
        self.assertNotIn(" ", argv[1][:8])
        self.assertIn("report.pdf", argv[1])

    def test_linux_opens_the_parent_because_xdg_open_cannot_select(self) -> None:
        with mock.patch.object(opener.shutil, "which", return_value="/usr/bin/xdg-open"):
            argv = opener.reveal_command(Path("/tmp/deep/report.pdf"), platform="linux")
        self.assertEqual(argv, ["/usr/bin/xdg-open", os.path.abspath("/tmp/deep")])

    def test_linux_without_xdg_open_has_no_command_at_all(self) -> None:
        with mock.patch.object(opener.shutil, "which", return_value=None):
            self.assertIsNone(opener.reveal_command(Path("/tmp/x.pdf"), platform="linux"))
            self.assertFalse(opener.supported(platform="linux"))

    def test_a_hostile_filename_stays_one_argument(self) -> None:
        name = "$(rm -rf ~) & echo pwned.pdf"
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / name
            for platform in ("darwin", "win32"):
                argv = opener.reveal_command(target, platform=platform)
                self.assertTrue(any(name in part for part in argv), platform)
                self.assertEqual(len(argv), 3 if platform == "darwin" else 2, platform)


class RevealTests(unittest.TestCase):
    def test_reveal_never_goes_through_a_shell(self) -> None:
        launcher = Launcher()
        self.assertTrue(
            opener.reveal(Path("/tmp/x.pdf"), platform="darwin", runner=launcher)
        )
        self.assertIsInstance(launcher.calls[0], list)
        self.assertFalse(launcher.kwargs[0].get("shell", False))
        self.assertNotIn("shell", launcher.kwargs[0])

    def test_reveal_does_not_hold_on_to_the_file_manager_output(self) -> None:
        launcher = Launcher()
        opener.reveal(Path("/tmp/x.pdf"), platform="darwin", runner=launcher)
        self.assertIn("stdout", launcher.kwargs[0])
        self.assertIn("stderr", launcher.kwargs[0])

    def test_a_missing_file_manager_is_false_not_an_exception(self) -> None:
        launcher = Launcher(error=True)
        self.assertFalse(
            opener.reveal(Path("/tmp/x.pdf"), platform="darwin", runner=launcher)
        )

    def test_no_command_means_no_launch_attempt(self) -> None:
        launcher = Launcher()
        with mock.patch.object(opener.shutil, "which", return_value=None):
            self.assertFalse(
                opener.reveal(Path("/tmp/x.pdf"), platform="linux", runner=launcher)
            )
        self.assertEqual(launcher.calls, [])

    @unittest.skipUnless(sys.platform == "darwin", "the macOS default only exists on macOS")
    def test_this_machine_can_show_a_path(self) -> None:
        self.assertTrue(opener.supported())


if __name__ == "__main__":
    unittest.main()
