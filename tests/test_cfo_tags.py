"""Finder tags: a no-op away from macOS, a real round trip on it."""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from carl_file_organizer import tags

DARWIN = sys.platform == "darwin"


class OffMacTests(unittest.TestCase):
    def test_noop_off_macos(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "note.txt"
            target.write_text("hello", encoding="utf-8")
            with mock.patch("carl_file_organizer.tags.sys.platform", "linux"), mock.patch(
                "carl_file_organizer.tags.subprocess.run"
            ) as runner:
                self.assertFalse(tags.supported())
                self.assertEqual(tags.read_tags(target), [])
                self.assertFalse(tags.add_tag(target, "文件移动"))
                self.assertFalse(tags.remove_tag(target, "文件移动"))
                self.assertFalse(tags.write_tags(target, ["x"]))
                runner.assert_not_called()

    def test_clear_tags_off_macos_touches_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "note.txt"
            target.write_text("hello", encoding="utf-8")
            with mock.patch("carl_file_organizer.tags.sys.platform", "linux"), mock.patch(
                "carl_file_organizer.tags.subprocess.run"
            ) as runner:
                report = tags.clear_tags([target], "文件移动", dry_run=False)
                runner.assert_not_called()
            self.assertEqual(report.checked, 1)
            self.assertEqual(report.cleared, 0)
            self.assertEqual(report.skipped, 1)
            self.assertTrue(target.exists())


class UserTagTests(unittest.TestCase):
    def test_colour_suffix_and_transient_tag_are_stripped(self) -> None:
        raw = ["Red\n6", "项目A", "文件移动", "文件移动\n2"]
        self.assertEqual(
            tags.user_tags(raw, ["文件移动", "Moved by File Organizer"]),
            ["Red", "项目A"],
        )

    def test_no_transient_list_keeps_everything_but_colours(self) -> None:
        self.assertEqual(tags.user_tags(["Blue\n4"]), ["Blue"])

    def test_duplicates_collapse(self) -> None:
        self.assertEqual(tags.user_tags(["A\n1", "A\n2", "B"]), ["A", "B"])


@unittest.skipUnless(DARWIN, "Finder tags only exist on macOS")
class MacRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        if not tags.supported():
            self.skipTest("xattr is not available")

    def test_roundtrip_plist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "tagged.txt"
            target.write_text("hello", encoding="utf-8")

            self.assertEqual(tags.read_tags(target), [])
            self.assertTrue(tags.add_tag(target, "文件移动"))
            self.assertEqual(tags.read_tags(target), ["文件移动"])
            # Adding the same tag twice writes nothing the second time.
            self.assertFalse(tags.add_tag(target, "文件移动"))

            self.assertTrue(tags.write_tags(target, ["文件移动", "Red\n6"]))
            self.assertEqual(tags.user_tags(target, ["文件移动"]), ["Red"])

            self.assertTrue(tags.remove_tag(target, "文件移动"))
            self.assertEqual(tags.read_tags(target), ["Red\n6"])
            self.assertFalse(tags.remove_tag(target, "文件移动"))

    def test_clear_tags_reports_each_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tagged = root / "tagged.txt"
            plain = root / "plain.txt"
            tagged.write_text("a", encoding="utf-8")
            plain.write_text("b", encoding="utf-8")
            tags.add_tag(tagged, "文件移动")

            preview = tags.clear_tags([tagged, plain, root / "gone.txt"], "文件移动", dry_run=True)
            self.assertEqual((preview.cleared, preview.skipped, preview.missing), (1, 1, 1))
            self.assertEqual(tags.read_tags(tagged), ["文件移动"])

            report = tags.clear_tags([tagged, plain, root / "gone.txt"], "文件移动", dry_run=False)
            self.assertEqual((report.cleared, report.skipped, report.missing), (1, 1, 1))
            self.assertEqual(report.failed, 0)
            self.assertEqual(tags.read_tags(tagged), [])


class TagListDiscoveryTests(unittest.TestCase):
    def test_find_tag_lists_is_sorted_and_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            managed = Path(temporary)
            for name in (
                "downloads-move-tags-2026-09-01_03-11-13.txt",
                "downloads-move-tags-2026-08-30_15-06-43.txt",
                "downloads-moves-2026-09-01_03-11-13.tsv",
                "notes.txt",
            ):
                (managed / name).write_text("", encoding="utf-8")
            found = [item.name for item in tags.find_tag_lists(managed)]
            self.assertEqual(
                found,
                [
                    "downloads-move-tags-2026-08-30_15-06-43.txt",
                    "downloads-move-tags-2026-09-01_03-11-13.txt",
                ],
            )

    def test_paths_from_lists_expands_home_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            managed = Path(temporary)
            home = Path(temporary) / "home"
            first = managed / "downloads-move-tags-2026-09-01_03-11-13.txt"
            second = managed / "downloads-move-tags-2026-09-01_03-11-52.txt"
            first.write_text("$HOME/Downloads/a.txt\n$HOME/Downloads/b.txt\n", encoding="utf-8")
            second.write_text("$HOME/Downloads/b.txt\n", encoding="utf-8")
            found = tags.paths_from_lists([first, second], home=home)
            self.assertEqual(
                [str(item) for item in found],
                [str(home / "Downloads/a.txt"), str(home / "Downloads/b.txt")],
            )


if __name__ == "__main__":
    unittest.main()
