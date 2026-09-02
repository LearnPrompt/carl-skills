"""The safety net, with every outside dependency injected.

Nothing in this file may consult the real machine: no lsof, no launch agents,
no crontab, no home directory scan.  Every check gets its inputs handed to it.
"""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import os
import sys
import tempfile
import unittest
from pathlib import Path

from carl_file_organizer import guard
from carl_file_organizer.config import resolve_config
from carl_file_organizer.guard import (
    config_references,
    dir_shape,
    file_shape,
    incoming_symlinks,
    open_handles,
    path_forms,
    recently_modified,
)
from carl_file_organizer.scanner import make_entry

from cfo_helpers import NOW, age, fake_lsof, write  # noqa: E402 - the path shim runs first


def tiered(root: Path):
    return resolve_config(root, profile="tiered", lang="zh")


class OpenHandleTests(unittest.TestCase):
    def test_a_held_file_reports_the_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = write(Path(temporary) / "session.log", "line\n")
            with open(str(target), "r", encoding="utf-8"):
                result = open_handles(
                    target, 5.0, lsof_runner=fake_lsof({"session.log": "python3,48213"})
                )
            self.assertTrue(result)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.handles[0]["command"], "python3")
            self.assertEqual(result.handles[0]["pid"], 48213)

    def test_an_untouched_file_reports_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = write(Path(temporary) / "quiet.txt")
            result = open_handles(target, 5.0, lsof_runner=fake_lsof({}))
            self.assertFalse(result)
            self.assertEqual(result.status, "ok")

    def test_a_timeout_is_unknown_rather_than_a_crash(self) -> None:
        import subprocess

        def runner(argv, timeout_s):
            raise subprocess.TimeoutExpired(argv, timeout_s)

        result = open_handles(Path("/nonexistent"), 0.1, lsof_runner=runner)
        self.assertEqual(result.status, "unknown")
        self.assertFalse(result.handles)

    def test_a_broken_runner_is_unknown_too(self) -> None:
        def runner(argv, timeout_s):
            raise OSError("no lsof here")

        self.assertEqual(open_handles(Path("/tmp"), 0.1, lsof_runner=runner).status, "unknown")

    def test_directories_are_asked_with_plus_d(self) -> None:
        seen = {}

        class _Result(object):
            stdout = ""
            returncode = 1

        def runner(argv, timeout_s):
            seen["argv"] = list(argv)
            return _Result()

        with tempfile.TemporaryDirectory() as temporary:
            open_handles(Path(temporary), 1.0, lsof_runner=runner, is_dir=True)
        self.assertIn("+d", seen["argv"])

    def test_spotlight_and_friends_are_not_counted_as_users(self) -> None:
        # A file that just landed in Downloads is open in mdworker_shared within
        # seconds.  Counting that would hold back every fresh download.
        self.assertTrue(guard.is_observer("mdworker_shared"))
        self.assertTrue(guard.is_observer("quicklookd"))
        self.assertFalse(guard.is_observer("tail"))
        with tempfile.TemporaryDirectory() as temporary:
            target = write(Path(temporary) / "photo.png")
            result = open_handles(
                target, 5.0, lsof_runner=fake_lsof({"photo.png": "mdworker_shared,900"})
            )
            self.assertFalse(result.handles)
            self.assertEqual(result.status, "ok")

    def test_finder_preview_daemons_are_observers_too(self) -> None:
        # lsof cuts its COMMAND column off, so the QuickLook thumbnail agent
        # usually arrives under a truncated name.  Both spellings, and the rest
        # of the Finder preview and iCloud crowd, only look at the file.
        for command in (
            "com.apple.quicklook.ThumbnailsAgent",
            "com.apple.quicklook.ThumbnailsA",
            "QuickLookUIService",
            "Finder",
            "mds_stores",
            "suggestd",
            "photoanalysisd",
            "cloudd",
            "bird",
        ):
            self.assertTrue(guard.is_observer(command), command)
        self.assertFalse(guard.is_observer("Preview"))

    def test_a_truncated_quicklook_handle_is_not_a_user(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = write(Path(temporary) / "poster.png")
            result = open_handles(
                target,
                5.0,
                lsof_runner=fake_lsof(
                    {"poster.png": "com.apple.quicklook.ThumbnailsA,71204"}
                ),
            )
            self.assertFalse(result.handles)
            self.assertEqual(result.status, "ok")

    def test_batched_probe_attributes_each_hit_to_its_own_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            busy = write(root / "busy.log")
            quiet = write(root / "quiet.log")
            table = guard.probe_open_handles(
                [busy, quiet], [], 1.0, lsof_runner=fake_lsof({"busy.log": "tail,777"})
            )
            self.assertTrue(table[str(busy)].handles)
            self.assertFalse(table[str(quiet)].handles)


class ReferenceTests(unittest.TestCase):
    def test_the_three_spellings_are_all_generated(self) -> None:
        home = Path("/home/example")
        target = home / "Downloads" / "tool.sh"
        forms = path_forms(target, home)

        # The absolute path is spelled the way this platform spells it, and on
        # Windows the forward-slash spelling comes along too: a config file
        # there carries whichever one its author typed.
        expected = [str(target)]
        if str(target) != target.as_posix():
            expected.append(target.as_posix())
        expected += ["~/Downloads/tool.sh", "$HOME/Downloads/tool.sh"]

        self.assertEqual(forms, expected)
        self.assertIn("/home/example/Downloads/tool.sh", forms)

    def test_a_launch_agent_reference_reports_the_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = write(home / "Downloads" / "backup-tool.sh", "#!/bin/sh\n")
            plist = write(
                home / "fake-LaunchAgents" / "com.example.backup.plist",
                "<plist>\n<string>hello</string>\n"
                "<string>$HOME/Downloads/backup-tool.sh</string>\n</plist>\n",
            )
            config = tiered(home / "Downloads")

            found = config_references(target, config, home, reference_files=[plist])

            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["line"], 3)
            self.assertEqual(found[0]["form"], "$HOME/Downloads/backup-tool.sh")
            self.assertTrue(found[0]["file"].startswith("$HOME/"))

    def test_a_tilde_spelling_in_a_shell_rc_also_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = write(home / "Downloads" / "backup-tool.sh")
            rc = write(home / "fake-zshrc", "\n\nalias b='~/Downloads/backup-tool.sh'\n")
            config = tiered(home / "Downloads")

            found = config_references(target, config, home, reference_files=[rc])

            self.assertEqual(found[0]["line"], 3)
            self.assertEqual(found[0]["form"], "~/Downloads/backup-tool.sh")

    def test_an_unrelated_file_matches_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = write(home / "Downloads" / "notes.md")
            rc = write(home / "fake-zshrc", "export PATH=$HOME/bin:$PATH\n")
            config = tiered(home / "Downloads")
            self.assertEqual(config_references(target, config, home, reference_files=[rc]), [])

    def test_a_missing_reference_file_is_skipped_quietly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = write(home / "Downloads" / "notes.md")
            config = tiered(home / "Downloads")
            self.assertEqual(
                config_references(
                    target, config, home, reference_files=[home / "nowhere.plist"]
                ),
                [],
            )


class SymlinkTests(unittest.TestCase):
    def test_a_symlink_in_a_scan_root_points_back_at_the_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = write(home / "Downloads" / "backup-tool.sh")
            binaries = home / "bin"
            binaries.mkdir(parents=True)
            (binaries / "backup-tool").symlink_to(target)
            config = tiered(home / "Downloads")

            found = incoming_symlinks(target, config, home, scan_roots=[binaries])

            self.assertEqual(found, ["$HOME/bin/backup-tool"])

    def test_a_symlink_into_a_folder_counts_for_the_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            inside = write(home / "Downloads" / "proj" / "run.sh")
            binaries = home / "bin"
            binaries.mkdir(parents=True)
            (binaries / "run").symlink_to(inside)
            config = tiered(home / "Downloads")

            found = incoming_symlinks(
                home / "Downloads" / "proj", config, home, scan_roots=[binaries]
            )
            self.assertEqual(found, ["$HOME/bin/run"])

    def test_no_scan_roots_means_no_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = write(home / "Downloads" / "notes.md")
            config = tiered(home / "Downloads")
            self.assertEqual(incoming_symlinks(target, config, home, scan_roots=[]), [])


class ShapeTests(unittest.TestCase):
    def test_a_git_file_is_a_worktree_and_a_git_folder_is_a_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = root / "topic-worktree"
            write(worktree / ".git", "gitdir: /elsewhere/.git/worktrees/topic\n")
            repo = root / "repo"
            write(repo / ".git" / "HEAD", "ref: refs/heads/main\n")

            self.assertIn("git-worktree", dir_shape(worktree).labels)
            self.assertIn("git-dir", dir_shape(repo, count_uncommitted=False).labels)

    def test_uncommitted_count_comes_from_the_injected_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            write(repo / ".git" / "HEAD", "ref: refs/heads/main\n")

            class _Result(object):
                returncode = 0
                stdout = " M a.py\n?? b.py\n"

            shape = dir_shape(repo, git_status_runner=lambda path, timeout: _Result())
            self.assertEqual(shape.uncommitted, 2)

    def test_virtualenv_dotenv_and_node_project_are_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            write(project / "package.json", "{}")
            write(project / ".env", "A=1\n")
            (project / ".venv").mkdir(parents=True)

            labels = dir_shape(project).labels
            self.assertIn("venv", labels)
            self.assertIn("dotenv", labels)
            self.assertIn("node-project", labels)

    def test_file_shape_sees_the_shebang(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = write(Path(temporary) / "run.sh", "#!/bin/sh\necho hi\n")
            self.assertIn("shebang", file_shape(script))

    # Windows has no execute bit: os.chmod there only moves the read-only flag,
    # and os.access(X_OK) answers from the file extension.  The label is a
    # POSIX fact, so the test that pins it is a POSIX test.
    @unittest.skipIf(os.name == "nt", "Windows 没有执行位")
    def test_file_shape_sees_the_executable_bit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = write(Path(temporary) / "run.sh", "#!/bin/sh\necho hi\n")
            os.chmod(str(script), 0o755)
            self.assertIn("executable", file_shape(script))


class RecentTests(unittest.TestCase):
    def test_ten_minute_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fresh = age(write(Path(temporary) / "fresh.md"), hours=0.05)
            settled = age(write(Path(temporary) / "settled.md"), hours=5)
            fresh_entry = make_entry(fresh, now=NOW, read_finder_tags=False)
            settled_entry = make_entry(settled, now=NOW, read_finder_tags=False)

            self.assertTrue(recently_modified(fresh_entry, NOW, 10))
            self.assertFalse(recently_modified(settled_entry, NOW, 10))
            self.assertFalse(recently_modified(fresh_entry, NOW, 0))


if __name__ == "__main__":
    unittest.main()
