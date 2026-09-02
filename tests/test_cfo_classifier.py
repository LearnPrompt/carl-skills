"""Rule matching, and above all the sensitive naming rules.

The interesting cases are the near misses: a short word must never win by
substring, because that is exactly how ``r2`` once swallowed ``pixverse-r2.md``.
"""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import unittest
from pathlib import Path

from carl_file_organizer import classifier
from carl_file_organizer.config import resolve_config
from carl_file_organizer.classifier import (
    classify,
    derivative_hint,
    is_regenerable_name,
    is_sensitive,
    match_name_pattern,
    match_pinned,
    match_rule,
)


def tiered():
    return resolve_config(Path.cwd(), profile="tiered", lang="zh")


class ClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = tiered()

    # -- the original taxonomy stays untouched ---------------------------
    def test_legacy_classify_still_answers(self) -> None:
        self.assertEqual(classify(Path("paper.PDF"))[0], "Documents")
        self.assertEqual(classify(Path("unknown.blob"))[0], "Other")

    # -- extension rules --------------------------------------------------
    def test_match_rule_reads_the_profile(self) -> None:
        rule = match_rule(".pdf", self.config)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.dest_key, "library.docs.pdf")
        self.assertEqual(rule.min_age_hours, 48)

    def test_archive_rules_carry_the_longer_settling_period(self) -> None:
        self.assertEqual(match_rule(".zip", self.config).min_age_hours, 168)
        self.assertEqual(match_rule(".dmg", self.config).min_age_hours, 168)

    def test_compound_suffix_is_a_rule_of_its_own(self) -> None:
        rule = match_rule(".tar.gz", self.config)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.dest_key, "archive.zip.other")

    def test_unknown_suffix_has_no_rule(self) -> None:
        self.assertIsNone(match_rule(".parquet", self.config))

    # -- sensitive naming --------------------------------------------------
    def test_sensitive_exact_never_matches_a_substring(self) -> None:
        self.assertIsNotNone(is_sensitive("key.txt", self.config))
        self.assertIsNone(is_sensitive("monkey.txt", self.config))
        self.assertIsNone(is_sensitive("pixverse-r2.md", self.config))
        self.assertIsNone(is_sensitive("keyboard-shortcuts.md", self.config))

    def test_sensitive_layers_are_reported(self) -> None:
        self.assertEqual(is_sensitive("id_rsa", self.config).where, "exact_names")
        self.assertEqual(is_sensitive("key.txt", self.config).where, "exact_stems")
        self.assertEqual(is_sensitive("server.pem", self.config).layer, "suffix")
        hit = is_sensitive("my-password-list.md", self.config)
        self.assertEqual(hit.layer, "marker")
        self.assertEqual(hit.needle, "password")

    def test_dot_env_matches_as_a_suffix_and_as_a_whole_name(self) -> None:
        self.assertIsNotNone(is_sensitive("prod.env", self.config))
        self.assertIsNotNone(is_sensitive(".env", self.config))

    def test_chinese_markers_match_as_substrings(self) -> None:
        self.assertIsNotNone(is_sensitive("公司营业执照扫描件.pdf", self.config))
        self.assertIsNotNone(is_sensitive("阿里云密钥备份.txt", self.config))

    def test_a_short_ascii_marker_is_refused_at_load_time(self) -> None:
        from carl_file_organizer.config import merge_profile

        with self.assertRaises(ValueError):
            merge_profile(self.config.profile, {"sensitive": {"markers": ["r2"]}})

    # -- derived copies, regenerable names, pinned -------------------------
    def test_derivative_hint(self) -> None:
        self.assertEqual(derivative_hint("web-prototype-fix-20260830", self.config), "-fix-")
        self.assertEqual(derivative_hint("repo-worktree-topic", self.config), "-worktree-")
        self.assertIsNone(derivative_hint("fixture.pdf", self.config))

    def test_is_regenerable_name(self) -> None:
        self.assertTrue(is_regenerable_name("node_modules", self.config))
        self.assertTrue(is_regenerable_name("__pycache__", self.config))
        self.assertFalse(is_regenerable_name("src", self.config))

    def test_match_pinned_takes_exact_names_and_globs(self) -> None:
        self.assertEqual(
            match_pinned("carl-file-organizer-approved-1.json", self.config), "carl-file-organizer-*.json"
        )
        self.assertIsNone(match_pinned("notes.md", self.config))

    def test_pinned_from_the_settings_file_is_exact(self) -> None:
        config = resolve_config(Path.cwd(), profile="tiered", lang="zh")
        config.profile["pinned"] = list(config.profile["pinned"]) + ["fable51-table"]
        self.assertEqual(match_pinned("fable51-table", config), "fable51-table")
        self.assertIsNone(match_pinned("fable51-table-copy", config))

    # -- user written name rules ------------------------------------------
    def test_name_patterns_respect_suffix_filters(self) -> None:
        config = tiered()
        config.profile["name_patterns"] = [
            {
                "id": "reports-sql",
                "match": "contains",
                "needle": "reports",
                "suffixes": [".sql"],
                "dest": "10_工作区/数据库与查询/SQL",
            }
        ]
        self.assertIsNotNone(match_name_pattern("monthly-reports.sql", config))
        self.assertIsNone(match_name_pattern("monthly-reports.pdf", config))

    def test_name_patterns_refuse_a_three_letter_substring(self) -> None:
        config = tiered()
        config.profile["name_patterns"] = [
            {"id": "tiny", "match": "contains", "needle": "abc", "dest": "00_收件箱/待判断"}
        ]
        self.assertIsNone(match_name_pattern("abcdef.md", config))

    def test_archive_and_installer_suffix_lookups(self) -> None:
        self.assertTrue(classifier.is_archive_suffix(".tar.gz", self.config))
        self.assertTrue(classifier.is_installer_suffix(".dmg", self.config))
        self.assertFalse(classifier.is_installer_suffix(".pdf", self.config))


if __name__ == "__main__":
    unittest.main()
