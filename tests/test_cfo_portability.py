"""Reading a plan that was written on the other kind of machine.

A plan.json and a report.html both travel: made on a Mac, opened on Windows, or
the reverse.  So one token is stored, both tokens are understood, and the token
a person actually sees is decided at render time and nowhere else.
"""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import os
import sys
import unittest
from pathlib import Path

from carl_file_organizer import guard, paths, trash


class TokenTests(unittest.TestCase):
    def test_only_one_token_is_ever_written(self) -> None:
        home = Path("/home/someone")
        self.assertEqual(
            paths.portable(home / "Downloads" / "a.pdf", home), "$HOME/Downloads/a.pdf"
        )
        self.assertTrue(paths.portable(home, home).startswith("$HOME"))

    def test_a_stored_path_always_uses_forward_slashes(self) -> None:
        home = Path("/home/someone")
        stored = paths.portable(home / "Downloads" / "deep" / "a.pdf", home)
        self.assertNotIn("\\", stored)

    def test_both_tokens_expand_to_the_same_place(self) -> None:
        home = Path("/home/someone")
        expected = home / "Downloads" / "a.pdf"
        for text in (
            "$HOME/Downloads/a.pdf",
            "%USERPROFILE%/Downloads/a.pdf",
            "%USERPROFILE%\\Downloads\\a.pdf",
        ):
            self.assertEqual(paths.expand_portable(text, home), expected, text)

    def test_a_bare_token_is_the_home_directory(self) -> None:
        home = Path("/home/someone")
        for text in ("$HOME", "%USERPROFILE%"):
            self.assertEqual(paths.expand_portable(text, home), home, text)

    def test_something_that_is_not_a_token_is_left_alone(self) -> None:
        home = Path("/home/someone")
        self.assertEqual(paths.expand_portable("/etc/hosts", home), Path("/etc/hosts"))

    def test_split_home_token_reports_which_spelling_it_found(self) -> None:
        self.assertEqual(paths.split_home_token("$HOME/a/b"), ("$HOME", "a/b"))
        self.assertEqual(
            paths.split_home_token("%USERPROFILE%\\a\\b"), ("%USERPROFILE%", "a/b")
        )
        self.assertIsNone(paths.split_home_token("relative/a"))
        self.assertIsNone(paths.split_home_token(None))

    def test_display_swaps_the_token_only_for_windows_eyes(self) -> None:
        self.assertEqual(
            paths.display_portable("$HOME/Downloads/a.pdf", platform="darwin"),
            "$HOME/Downloads/a.pdf",
        )
        self.assertEqual(
            paths.display_portable("$HOME/Downloads/a.pdf", platform="win32"),
            "%USERPROFILE%\\Downloads\\a.pdf",
        )
        self.assertEqual(paths.display_portable("$HOME", platform="win32"), "%USERPROFILE%")

    def test_display_leaves_a_path_it_does_not_recognise_untouched(self) -> None:
        self.assertEqual(
            paths.display_portable("/etc/hosts", platform="win32"), "/etc/hosts"
        )

    def test_home_token_follows_the_platform(self) -> None:
        self.assertEqual(paths.home_token("win32"), "%USERPROFILE%")
        self.assertEqual(paths.home_token("darwin"), "$HOME")
        self.assertEqual(paths.home_token("linux"), "$HOME")


class PlanHomeTests(unittest.TestCase):
    def test_a_windows_written_plan_still_gives_up_its_home(self) -> None:
        plan = {
            "source_root": "/home/someone/Downloads",
            "source_root_portable": "%USERPROFILE%\\Downloads",
        }
        self.assertEqual(paths.plan_home(plan), Path("/home/someone"))

    def test_a_mac_written_plan_gives_up_its_home_too(self) -> None:
        plan = {
            "source_root": "/home/someone/Downloads",
            "source_root_portable": "$HOME/Downloads",
        }
        self.assertEqual(paths.plan_home(plan), Path("/home/someone"))

    def test_a_stripped_plan_falls_back_to_this_machine(self) -> None:
        self.assertEqual(paths.plan_home({}), Path.home())


class WindowsBackendTests(unittest.TestCase):
    """The Windows code paths, exercised from whatever machine is running this."""

    def test_the_flag_word_always_keeps_undo(self) -> None:
        self.assertTrue(trash.WINDOWS_FLAGS & trash.FOF_ALLOWUNDO)
        self.assertTrue(trash.WINDOWS_FLAGS & trash.FOF_NOCONFIRMATION)
        self.assertTrue(trash.WINDOWS_FLAGS & trash.FOF_SILENT)

    def test_the_path_argument_ends_in_two_nuls(self) -> None:
        argument = trash.windows_path_argument(Path("C:/Users/someone/a.pdf"))
        self.assertTrue(argument.endswith("\0\0"))
        self.assertEqual(argument.count("\0"), 2)
        self.assertTrue(argument.startswith(os.path.abspath("C:/Users/someone/a.pdf")))

    def test_a_recycle_bin_call_that_returns_nonzero_is_a_failure(self) -> None:
        with self.assertRaises(trash.TrashError) as caught:
            trash.move_to_trash(
                Path("nowhere.pdf"),
                backend=trash.WINDOWS,
                win_runner=lambda path: (124, False),
            )
        self.assertIn("124", str(caught.exception))

    def test_an_aborted_call_is_a_failure_too(self) -> None:
        with self.assertRaises(trash.TrashError):
            trash.move_to_trash(
                Path("nowhere.pdf"),
                backend=trash.WINDOWS,
                win_runner=lambda path: (0, True),
            )

    def test_a_success_that_left_the_file_behind_is_still_a_failure(self) -> None:
        here = Path(__file__)
        with self.assertRaises(trash.TrashError) as caught:
            trash.move_to_trash(
                here, backend=trash.WINDOWS, win_runner=lambda path: (0, False), lang="zh"
            )
        self.assertIn(here.name, str(caught.exception))

    def test_a_failed_recycle_bin_call_never_becomes_a_delete(self) -> None:
        here = Path(__file__)
        for runner in (
            lambda path: (1, False),
            lambda path: (0, True),
            lambda path: (_ for _ in ()).throw(OSError("shell32 went away")),
        ):
            with self.assertRaises(trash.TrashError):
                trash.move_to_trash(here, backend=trash.WINDOWS, win_runner=runner)
            self.assertTrue(here.exists())

    def test_an_unknown_backend_name_is_refused_outright(self) -> None:
        with self.assertRaises(trash.TrashError):
            trash.move_to_trash(Path("x"), backend="dumpster")

    @unittest.skipUnless(sys.platform == "win32", "shell32 only exists on Windows")
    def test_this_windows_machine_can_reach_the_recycle_bin(self) -> None:
        self.assertTrue(trash.windows_available())
        self.assertEqual(trash.detect_backend(), trash.WINDOWS)

    @unittest.skipIf(sys.platform == "win32", "the negative case is for everywhere else")
    def test_windows_helpers_are_inert_off_windows(self) -> None:
        self.assertFalse(trash.windows_available())


class LsofTests(unittest.TestCase):
    def test_windows_never_claims_nobody_has_it_open(self) -> None:
        """Unknown is a real answer; a guessed "nobody" would let a file move."""

        if sys.platform == "win32":
            self.assertFalse(guard.lsof_possible())
        else:
            self.assertEqual(guard.lsof_possible(), guard.shutil.which("lsof") is not None)

    @unittest.skipUnless(sys.platform == "win32", "only Windows lacks lsof by definition")
    def test_open_handles_on_windows_is_unknown(self) -> None:
        result = guard.open_handles(Path(__file__))
        self.assertEqual(result.status, "unknown")
        self.assertFalse(result.handles)


if __name__ == "__main__":
    unittest.main()
