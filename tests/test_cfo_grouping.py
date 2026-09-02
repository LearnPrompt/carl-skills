"""Pairing, duplicates and regenerable build output."""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import os
import sys
import tempfile
import unittest
from pathlib import Path

from carl_file_organizer import grouping
from carl_file_organizer.config import resolve_config
from carl_file_organizer.grouping import (
    archive_stem,
    copy_base,
    dir_stem,
    file_sha256,
    find_duplicates,
    find_regenerable,
    pair_archives,
)
from carl_file_organizer.scanner import scan_top_level

from cfo_helpers import NOW, write  # noqa: E402 - the path shim has to run first


def scan(root: Path, profile: str = "tiered"):
    config = resolve_config(root, profile=profile, lang="zh")
    entries, _notes = scan_top_level(root, config, now=NOW, read_finder_tags=False)
    return config, entries


class NameArithmeticTests(unittest.TestCase):
    def test_copy_base(self) -> None:
        self.assertEqual(copy_base("foo (1).pdf"), ("foo.pdf", True))
        self.assertEqual(copy_base("foo_1.pdf"), ("foo.pdf", True))
        self.assertEqual(copy_base("Archive 2"), ("Archive", True))
        self.assertEqual(copy_base("foo.pdf"), ("foo.pdf", False))

    def test_archive_stem_only_answers_for_archives(self) -> None:
        self.assertEqual(archive_stem("Archive.zip"), "archive")
        self.assertEqual(archive_stem("Archive (1).zip"), "archive")
        self.assertEqual(archive_stem("bundle.tar.gz"), "bundle")
        self.assertEqual(archive_stem("xxx-v2.zip"), "xxx-v2")
        self.assertIsNone(archive_stem("notes.md"))

    def test_dir_stem(self) -> None:
        self.assertEqual(dir_stem("Archive (1)"), "archive")
        self.assertEqual(dir_stem("Archive 2"), "archive")
        self.assertEqual(dir_stem("xxx-v2"), "xxx-v2")


class PairTests(unittest.TestCase):
    def test_pair_archive_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "Archive.zip", "z")
            write(root / "Archive (1).zip", "z")
            (root / "Archive").mkdir()
            write(root / "Archive" / "inside.txt")
            (root / "Archive 2").mkdir()
            write(root / "Archive 2" / "inside.txt")
            write(root / "xxx-v2.zip", "z")
            (root / "xxx-v2").mkdir()
            write(root / "xxx-v2" / "inside.txt")
            (root / "xxx").mkdir()
            write(root / "xxx" / "inside.txt")

            config, entries = scan(root)
            groups = pair_archives(entries, config)
            by_stem = {group.stem: group for group in groups}

            self.assertIn("archive", by_stem)
            self.assertEqual(
                sorted(member.name for member in by_stem["archive"].members),
                ["Archive", "Archive (1).zip", "Archive 2", "Archive.zip"],
            )
            self.assertIn("xxx-v2", by_stem)
            self.assertEqual(
                sorted(member.name for member in by_stem["xxx-v2"].members),
                ["xxx-v2", "xxx-v2.zip"],
            )
            self.assertNotIn("xxx", by_stem)

    def test_a_lone_archive_is_not_a_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "solo.zip", "z")
            config, entries = scan(root)
            self.assertEqual(pair_archives(entries, config), [])


class DuplicateTests(unittest.TestCase):
    def test_identical_content_groups_by_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "a.pdf", "identical bytes\n")
            write(root / "a (1).pdf", "identical bytes\n")
            _config, entries = scan(root)

            groups = find_duplicates(entries, hash_duplicates=True)

            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0].evidence, "sha256")
            self.assertIsNotNone(groups[0].sha256)
            self.assertEqual([m.name for m in groups[0].members], ["a (1).pdf", "a.pdf"])

    def test_same_name_shape_but_different_bytes_is_only_a_name_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "export.png", "AAAA")
            write(root / "export_1.png", "BBBB")
            _config, entries = scan(root)

            groups = find_duplicates(entries, hash_duplicates=True)

            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0].evidence, "name-pattern")
            self.assertIsNone(groups[0].sha256)

    def test_without_hashing_only_names_are_compared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "a.pdf", "identical bytes\n")
            write(root / "a (1).pdf", "identical bytes\n")
            _config, entries = scan(root)

            groups = find_duplicates(entries, hash_duplicates=False)
            self.assertEqual([group.evidence for group in groups], ["name-pattern"])

    def test_excluded_subjects_never_form_a_duplicate_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "a.pdf", "same\n")
            write(root / "a (1).pdf", "same\n")
            _config, entries = scan(root)
            everything = [entry.subject_id for entry in entries]
            self.assertEqual(
                find_duplicates(entries, hash_duplicates=True, exclude=everything), []
            )

    def test_file_sha256_gives_up_above_the_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = write(Path(temporary) / "big.bin", "0123456789")
            self.assertIsNone(file_sha256(target, max_bytes=4))
            self.assertIsNotNone(file_sha256(target, max_bytes=4096))


class RegenerableTests(unittest.TestCase):
    def test_scan_respects_depth_and_never_enters_git(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "proj" / "package.json", "{}")
            write(root / "proj" / "node_modules" / "left-pad" / "index.js", "x")
            write(root / "proj" / ".git" / "objects" / "node_modules" / "keep", "x")
            write(root / "proj" / "a" / "b" / "c" / "node_modules" / "deep.js", "x")
            write(root / "proj" / "a" / "b" / "node_modules" / "ok.js", "x")

            config, entries = scan(root)
            hits = find_regenerable(entries, config, max_depth=3, now=NOW)
            relatives = sorted(hit.relative for hit in hits)

            self.assertIn("proj/node_modules", relatives)
            self.assertIn("proj/a/b/node_modules", relatives)
            self.assertNotIn("proj/a/b/c/node_modules", relatives)
            self.assertFalse([r for r in relatives if ".git" in r])

    def test_hit_carries_a_bounded_size_and_a_subject_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "proj" / "node_modules" / "a.js", "0123456789")
            config, entries = scan(root)
            hits = find_regenerable(entries, config, max_depth=3, now=NOW)

            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].dir_stats.files, 1)
            self.assertEqual(hits[0].dir_stats.bytes, 10)
            self.assertFalse(hits[0].dir_stats.truncated)
            self.assertEqual(len(hits[0].subject_id), 16)

    def test_a_matched_folder_is_not_descended_into(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "proj" / "node_modules" / "pkg" / "node_modules" / "x.js", "x")
            config, entries = scan(root)
            hits = find_regenerable(entries, config, max_depth=3, now=NOW)
            self.assertEqual([hit.relative for hit in hits], ["proj/node_modules"])

    def test_forbidden_folders_are_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "vault" / ".obsidian" / "config", "{}")
            write(root / "vault" / "node_modules" / "x.js", "x")
            config, entries = scan(root)
            self.assertEqual(find_regenerable(entries, config, max_depth=3, now=NOW), [])


if __name__ == "__main__":
    unittest.main()
