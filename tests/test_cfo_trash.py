"""The trash backends, and the promise that a failure stays a failure."""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from carl_file_organizer import trash


class Result:
    """Just enough of ``subprocess.CompletedProcess`` for the runner seam."""

    def __init__(self, returncode: int = 0, stderr: str = "", stdout: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


class Runner:
    """A fake subprocess runner that records how it was called."""

    def __init__(self, *, returncode: int = 0, stderr: str = "", unlink: bool = True) -> None:
        self.calls = []
        self.kwargs = []
        self.returncode = returncode
        self.stderr = stderr
        self.unlink = unlink

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        self.kwargs.append(kwargs)
        if self.unlink and self.returncode == 0:
            target = argv[-1]
            if argv[0] == "osascript":
                target = argv[-1].split('POSIX file "', 1)[-1].rstrip('"')
                target = target.replace('\\"', '"').replace("\\\\", "\\")
            if os.path.lexists(target):
                os.unlink(target)
        return Result(self.returncode, self.stderr)


class BackendDetectionTests(unittest.TestCase):
    def test_darwin_with_osascript_is_finder(self) -> None:
        with mock.patch("carl_file_organizer.trash.sys.platform", "darwin"), mock.patch(
            "carl_file_organizer.trash.shutil.which", lambda name: "/usr/bin/" + name
        ):
            self.assertEqual(trash.detect_backend(), trash.FINDER)

    def test_linux_with_gio_is_gio(self) -> None:
        with mock.patch("carl_file_organizer.trash.sys.platform", "linux"), mock.patch(
            "carl_file_organizer.trash.shutil.which", lambda name: "/usr/bin/gio" if name == "gio" else None
        ):
            self.assertEqual(trash.detect_backend(), trash.GIO)

    def test_nothing_available_is_none(self) -> None:
        with mock.patch("carl_file_organizer.trash.sys.platform", "linux"), mock.patch(
            "carl_file_organizer.trash.shutil.which", lambda name: None
        ):
            self.assertEqual(trash.detect_backend(), trash.NONE)


class MoveToTrashTests(unittest.TestCase):
    def test_backend_none_refuses_and_keeps_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "keep.txt"
            target.write_text("still here", encoding="utf-8")
            runner = Runner()
            with self.assertRaises(trash.TrashError):
                trash.move_to_trash(target, backend=trash.NONE, runner=runner)
            self.assertTrue(target.exists())
            self.assertEqual(runner.calls, [])

    def test_finder_command_escaping_and_no_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'weird " name \\ here.txt'
            target.write_text("bye", encoding="utf-8")
            runner = Runner()
            trash.move_to_trash(target, backend=trash.FINDER, runner=runner)

            self.assertEqual(len(runner.calls), 1)
            argv = runner.calls[0]
            self.assertIsInstance(argv, list)
            self.assertEqual(argv[0], "osascript")
            self.assertEqual(argv[1], "-e")
            self.assertIn('tell application "Finder" to delete POSIX file "', argv[2])
            self.assertIn('weird \\" name \\\\ here.txt', argv[2])
            self.assertNotIn("shell", runner.kwargs[0])
            self.assertFalse(runner.kwargs[0].get("shell", False))
            self.assertFalse(target.exists())

    def test_escaping_is_backslash_first(self) -> None:
        self.assertEqual(trash.applescript_quote('a\\b"c'), 'a\\\\b\\"c')

    def test_command_still_there_afterwards_is_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "stubborn.txt"
            target.write_text("nope", encoding="utf-8")
            runner = Runner(unlink=False)
            with self.assertRaises(trash.TrashError) as caught:
                trash.move_to_trash(target, backend=trash.FINDER, runner=runner)
            self.assertIn("stubborn.txt", str(caught.exception))
            self.assertTrue(target.exists())

    def test_automation_denied_explains_where_to_click(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "denied.txt"
            target.write_text("nope", encoding="utf-8")
            runner = Runner(returncode=1, stderr="execution error: ... (-1743)")
            with self.assertRaises(trash.TrashError) as caught:
                trash.move_to_trash(target, backend=trash.FINDER, runner=runner, lang="zh")
            self.assertIn("自动化", str(caught.exception))
            self.assertTrue(target.exists())

    def test_gio_command_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "gone.txt"
            target.write_text("bye", encoding="utf-8")
            runner = Runner()
            trash.move_to_trash(target, backend=trash.GIO, runner=runner)
            self.assertEqual(runner.calls[0][:3], ["gio", "trash", "--"])
            self.assertEqual(runner.calls[0][3], os.path.abspath(str(target)))

    def test_timeout_is_reported_not_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "slow.txt"
            target.write_text("hi", encoding="utf-8")

            def slow(argv, **kwargs):
                raise subprocess.TimeoutExpired(argv, 30)

            with self.assertRaises(trash.TrashError):
                trash.move_to_trash(target, backend=trash.FINDER, runner=slow)
            self.assertTrue(target.exists())

    def test_a_failed_trash_never_becomes_a_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "safe.txt"
            target.write_text("still here", encoding="utf-8")
            for runner in (
                Runner(returncode=1, stderr="boom"),
                Runner(unlink=False),
                Runner(returncode=2, stderr=""),
            ):
                with self.assertRaises(trash.TrashError):
                    trash.move_to_trash(target, backend=trash.FINDER, runner=runner)
                self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
