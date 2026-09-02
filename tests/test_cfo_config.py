from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from carl_file_organizer import config, paths


def _write_dotfile(root: Path, payload: dict) -> Path:
    path = root / config.DOTFILE_NAME
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class LanguageDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(config, "_apple_languages", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.profile = config.load_builtin_profile("tiered")

    def test_lang_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "00_收件箱").mkdir()

            self.assertEqual(
                config.detect_lang(
                    root,
                    "en",
                    env={config.LANG_ENV: "zh"},
                    dotfile={"lang": "zh"},
                    profile=self.profile,
                ),
                ("en", "flag"),
            )
            self.assertEqual(
                config.detect_lang(
                    root,
                    None,
                    env={config.LANG_ENV: "en"},
                    dotfile={"lang": "zh"},
                    profile=self.profile,
                ),
                ("zh", "dotfile"),
            )
            self.assertEqual(
                config.detect_lang(
                    root, None, env={config.LANG_ENV: "en"}, dotfile={}, profile=self.profile
                ),
                ("en", "env"),
            )
            self.assertEqual(
                config.detect_lang(root, None, env={}, dotfile={}, profile=self.profile),
                ("zh", "existing-dirs"),
            )

        with tempfile.TemporaryDirectory() as temporary:
            bare = Path(temporary)
            self.assertEqual(
                config.detect_lang(
                    bare, None, env={"LANG": "zh_CN.UTF-8"}, dotfile={}, profile=self.profile
                ),
                ("zh", "posix-locale"),
            )
            self.assertEqual(
                config.detect_lang(bare, None, env={}, dotfile={}, profile=self.profile),
                ("en", "default"),
            )

    def test_apple_languages_beats_posix_locale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bare = Path(temporary)
            with mock.patch.object(config, "_apple_languages", return_value="zh-Hans-CN"):
                self.assertEqual(
                    config.detect_lang(
                        bare, None, env={"LANG": "en_US.UTF-8"}, dotfile={}, profile=self.profile
                    ),
                    ("zh", "apple-languages"),
                )

    def test_existing_dirs_sniff_zh_en(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            zh_root = Path(temporary) / "zh"
            en_root = Path(temporary) / "en"
            both_root = Path(temporary) / "both"
            for folder in (zh_root, en_root, both_root):
                folder.mkdir()
            (zh_root / "00_收件箱").mkdir()
            (en_root / "00_Inbox").mkdir()
            (both_root / "00_收件箱").mkdir()
            (both_root / "00_Inbox").mkdir()

            self.assertEqual(
                config.detect_lang(zh_root, None, env={}, dotfile={}, profile=self.profile),
                ("zh", "existing-dirs"),
            )
            self.assertEqual(
                config.detect_lang(en_root, None, env={}, dotfile={}, profile=self.profile),
                ("en", "existing-dirs"),
            )
            with self.assertRaises(config.LanguageAmbiguous):
                config.detect_lang(both_root, None, env={}, dotfile={}, profile=self.profile)

            # an explicit language always wins over the ambiguous layout
            self.assertEqual(
                config.detect_lang(both_root, "zh", env={}, dotfile={}, profile=self.profile),
                ("zh", "flag"),
            )


class ProfileMergeTests(unittest.TestCase):
    def test_dotfile_merge_union_and_override(self) -> None:
        base = config.load_builtin_profile("tiered")
        merged = config.merge_profile(
            base,
            {
                "lang": "zh",
                "large_bytes": 1024,
                "aging": {"default_hours": 12},
                "names": {"library.docs": {"zh": "文档"}},
                "rules": {".numbers": {"dest": "library.docs.csv"}},
                "pinned": ["notes.md"],
                "sensitive": {"exact_names": ["work-key.txt"], "markers": ["subscription"]},
                "forbidden": {"basenames": ["Sync"]},
                "regenerable": {"basenames": ["vendor"]},
                "guard": {"reference_files": ["$HOME/.config/mytool.conf"], "recent_minutes": 30},
                "name_patterns": [
                    {"id": "reports", "match": "contains", "needle": "report", "dest": "20_知识库/报告"}
                ],
            },
        )

        # union keeps the built-in entries
        self.assertIn("carl-file-organizer-*.json", merged["pinned"])
        self.assertIn("notes.md", merged["pinned"])
        self.assertIn(".env", merged["sensitive"]["exact_names"])
        self.assertIn("work-key.txt", merged["sensitive"]["exact_names"])
        self.assertIn("credential", merged["sensitive"]["markers"])
        self.assertIn("subscription", merged["sensitive"]["markers"])
        self.assertIn(".git", merged["forbidden"]["basenames"])
        self.assertIn("Sync", merged["forbidden"]["basenames"])
        self.assertIn("node_modules", merged["regenerable"]["basenames"])
        self.assertIn("vendor", merged["regenerable"]["basenames"])
        self.assertIn("$HOME", merged["guard"]["reference_scan_roots"])
        self.assertIn("$HOME/.config/mytool.conf", merged["guard"]["reference_files"])
        self.assertEqual([p["id"] for p in merged["name_patterns"]], ["reports"])

        # deep merge on names / rules
        self.assertEqual(merged["names"]["library.docs"]["zh"], "文档")
        self.assertEqual(merged["names"]["library.docs"]["en"], "Documents")
        self.assertEqual(merged["rules"][".numbers"]["dest"], "library.docs.csv")
        self.assertEqual(merged["rules"][".pdf"]["dest"], "library.docs.pdf")

        # plain overrides
        self.assertEqual(merged["lang"], "zh")
        self.assertEqual(merged["large_bytes"], 1024)
        self.assertEqual(merged["aging"]["default_hours"], 12)
        self.assertEqual(merged["aging"]["archive_hours"], 168)
        self.assertEqual(merged["guard"]["recent_minutes"], 30)
        self.assertEqual(merged["guard"]["lsof_timeout_s"], 5)

        # the built-in profile is never mutated
        self.assertNotIn("notes.md", base["pinned"])

    def test_short_ascii_marker_is_refused(self) -> None:
        base = config.load_builtin_profile("tiered")
        with self.assertRaises(ValueError) as caught:
            config.merge_profile(base, {"sensitive": {"markers": ["r2"]}})
        self.assertIn("exact_stems", str(caught.exception))
        # a short CJK marker is fine, it cannot collide the way a two-letter word does
        merged = config.merge_profile(base, {"sensitive": {"markers": ["证件"]}})
        self.assertIn("证件", merged["sensitive"]["markers"])

    def test_save_dotfile_only_if_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cfg = config.resolve_config(root, lang="zh", profile="tiered")
            written = config.save_dotfile(cfg, only_if_missing=True)
            self.assertIsNotNone(written)
            self.assertEqual(
                json.loads(Path(written).read_text(encoding="utf-8")),
                {"profile": "tiered", "lang": "zh"},
            )

            cfg.lang = "en"
            self.assertIsNone(config.save_dotfile(cfg, only_if_missing=True))
            self.assertEqual(
                json.loads(Path(written).read_text(encoding="utf-8"))["lang"], "zh"
            )

            self.assertIsNotNone(config.save_dotfile(cfg, only_if_missing=False))
            self.assertEqual(
                json.loads(Path(written).read_text(encoding="utf-8"))["lang"], "en"
            )

    def test_dotfile_is_read_back_by_resolve_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_dotfile(root, {"profile": "simple", "lang": "en", "pinned": ["keepme.txt"]})
            cfg = config.resolve_config(root)
            self.assertEqual(cfg.profile_name, "simple")
            self.assertEqual(cfg.lang, "en")
            self.assertEqual(cfg.lang_source, "dotfile")
            self.assertEqual(cfg.profile_source, "builtin+dotfile")
            self.assertIn("keepme.txt", cfg.profile["pinned"])
            self.assertEqual(len(cfg.profile_hash), 12)

    def test_recorded_language_stays_out_of_the_settings_digest(self) -> None:
        base = config.load_builtin_profile("tiered")
        zh = config.merge_profile(base, {"profile": "tiered", "lang": "zh"})
        en = config.merge_profile(base, {"profile": "tiered", "lang": "en"})
        self.assertEqual(zh["lang"], "zh")
        self.assertEqual(en["lang"], "en")
        self.assertEqual(config.profile_hash(zh), config.profile_hash(en))
        self.assertEqual(config.profile_hash(zh), config.profile_hash(base))

    def test_an_edited_rule_changes_the_settings_digest(self) -> None:
        base = config.load_builtin_profile("tiered")
        edited = config.merge_profile(base, {"pinned": ["something-new"]})
        self.assertNotEqual(config.profile_hash(base), config.profile_hash(edited))

    def test_broken_dotfile_reports_position(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / config.DOTFILE_NAME).write_text('{"lang": ', encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                config.load_dotfile(root)
            self.assertIn("line", str(caught.exception))


class NameResolutionTests(unittest.TestCase):
    def test_dir_name_three_levels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            zh = config.resolve_config(root, lang="zh", profile="tiered")
            self.assertEqual(config.dir_name(zh, "library"), "20_知识库")
            self.assertEqual(config.dir_name(zh, "library.docs"), "20_知识库/文档资料")
            self.assertEqual(config.dir_name(zh, "library.docs.pdf"), "20_知识库/文档资料/PDF")
            self.assertEqual(
                config.dest_dir(zh, "library.docs.pdf"), root / "20_知识库/文档资料/PDF"
            )
            self.assertEqual(config.managed_dir(zh), root / "00_下载目录管理")

            en = config.resolve_config(root, lang="en", profile="tiered")
            self.assertEqual(config.dir_name(en, "library.docs.pdf"), "20_Library/Documents/PDF")
            self.assertEqual(config.managed_dir(en), root / "00_File_Organizer")

            with self.assertRaises(ValueError):
                config.dir_name(zh, "library.docs.pdf.extra")
            with self.assertRaises(KeyError):
                config.dir_name(zh, "library.nope")

    def test_partition_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cfg = config.resolve_config(Path(temporary), lang="zh", profile="tiered")
            self.assertEqual(
                config.partition_prefixes(cfg), ("00_", "10_", "20_", "60_", "90_")
            )
            names = config.partition_dir_names(cfg)
            self.assertIn("00_收件箱", names)
            self.assertIn("00_Inbox", names)
            self.assertIn("00_下载目录管理", names)


class PathGuardTests(unittest.TestCase):
    def test_refuse_root(self) -> None:
        home = Path.home()
        with self.assertRaises(ValueError):
            paths.refuse_root(Path("/"))
        with self.assertRaises(ValueError):
            paths.refuse_root(home)
        if (home / "Library").is_dir():
            with self.assertRaises(ValueError):
                paths.refuse_root(home / "Library")

        with tempfile.TemporaryDirectory() as temporary:
            outside = Path(temporary)
            with self.assertRaises(ValueError):
                paths.refuse_root(outside)
            self.assertEqual(
                paths.refuse_root(outside, allow_outside_home=True),
                paths.realpath(outside),
            )

            linked = outside / "link"
            os.symlink(str(outside), str(linked))
            with self.assertRaises(ValueError):
                paths.refuse_root(linked, allow_outside_home=True)

            # a folder inside a fake home is accepted
            fake_home = outside / "home"
            (fake_home / "Downloads").mkdir(parents=True)
            self.assertEqual(
                paths.refuse_root(fake_home / "Downloads", home=fake_home),
                paths.realpath(fake_home / "Downloads"),
            )
            with self.assertRaises(ValueError):
                paths.refuse_root(fake_home, home=fake_home)

    def test_portable_round_trip_and_safe_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            target = home / "Downloads" / "report.pdf"
            self.assertEqual(paths.portable(target, home=home), "$HOME/Downloads/report.pdf")
            self.assertEqual(
                paths.expand_portable("$HOME/Downloads/report.pdf", home=home), target
            )
        self.assertEqual(paths.safe_dir_name("$CODE_HOME"), "CODE_HOME")
        self.assertEqual(paths.safe_dir_name('"'), "quote-dir")
        self.assertEqual(paths.safe_dir_name("   "), "unnamed")
        self.assertEqual(paths.safe_dir_name("a/b"), "a-b")

    def test_conflict_name_keeps_the_suffix_last(self) -> None:
        stamp = datetime(2026, 9, 2, 12, 0, 0)
        self.assertEqual(
            paths.conflict_name("quarterly-report.pdf", stamp),
            "quarterly-report-2026-09-02_12-00-00.pdf",
        )
        self.assertEqual(
            paths.conflict_name("archive.tar.gz", stamp),
            "archive-2026-09-02_12-00-00.tar.gz",
        )
        self.assertEqual(
            paths.conflict_name("Report.PDF", stamp), "Report-2026-09-02_12-00-00.PDF"
        )
        self.assertEqual(paths.conflict_name("README", stamp), "README-2026-09-02_12-00-00")
        self.assertEqual(
            paths.conflict_name("my.project", stamp, is_dir=True),
            "my.project-2026-09-02_12-00-00",
        )
        # safe_dir_name eats a leading dot before the stamp is added; hidden
        # entries never reach the planner, so this only pins the existing rule.
        self.assertEqual(paths.conflict_name(".bashrc", stamp), "bashrc-2026-09-02_12-00-00")


class PlanPrivacyTests(unittest.TestCase):
    """strip_absolute drops the four absolute fields; hydrate_absolute rebuilds them.

    Both homes below are invented rather than real ``/<users-dir>/<account>``
    paths, because this repository refuses to carry one machine's absolute paths
    at all: the same rule this feature exists to enforce on report.html.
    """

    HOME = "/opt/gn-test/example"
    OTHER = "/opt/gn-test/someone-else"

    def _plan(self) -> dict:
        home = self.HOME
        return {
            "schema_version": 2,
            "source_root": home + "/Downloads",
            "source_root_portable": "$HOME/Downloads",
            "managed_dir": home + "/Downloads/00_File_Organizer",
            "managed_dir_portable": "$HOME/Downloads/00_File_Organizer",
            "actions": [
                {
                    "id": "a1",
                    "kind": "move",
                    "source": home + "/Downloads/report.pdf",
                    "source_portable": "$HOME/Downloads/report.pdf",
                    "destination": home + "/Downloads/PDF/report.pdf",
                    "destination_portable": "$HOME/Downloads/PDF/report.pdf",
                    "guard": {
                        "referenced_in": [
                            {
                                "file": home + "/.zshrc",
                                "line": 82,
                                "form": home + "/Downloads/report.pdf",
                            }
                        ],
                        "incoming_symlinks": [home + "/.local/bin/report"],
                    },
                },
                {
                    "id": "a2",
                    "kind": "trash",
                    "source": home + "/Downloads/old.dmg",
                    "source_portable": "$HOME/Downloads/old.dmg",
                    "destination": None,
                    "destination_portable": None,
                },
            ],
        }

    def test_strip_removes_every_absolute_path_including_the_reference_form(self) -> None:
        stripped = paths.strip_absolute(self._plan())
        text = json.dumps(stripped, ensure_ascii=False)

        for field in ("source_root", "managed_dir"):
            self.assertNotIn(field, stripped)
        for action in stripped["actions"]:
            self.assertNotIn("source", action)
            self.assertNotIn("destination", action)
        self.assertEqual(stripped["source_root_portable"], "$HOME/Downloads")

        guard = stripped["actions"][0]["guard"]
        self.assertEqual(guard["referenced_in"][0]["file"], "$HOME/.zshrc")
        self.assertEqual(guard["incoming_symlinks"], ["$HOME/.local/bin/report"])
        # form is no longer exempt: it gets the same $HOME rewrite as everything else
        self.assertEqual(
            guard["referenced_in"][0]["form"], "$HOME/Downloads/report.pdf"
        )

        self.assertNotIn(self.HOME, text)

    def test_strip_leaves_the_original_alone(self) -> None:
        plan = self._plan()
        paths.strip_absolute(plan)
        self.assertEqual(plan["source_root"], self.HOME + "/Downloads")
        self.assertEqual(plan["actions"][0]["source"], self.HOME + "/Downloads/report.pdf")

    def test_hydrate_rebuilds_against_the_running_home(self) -> None:
        stripped = paths.strip_absolute(self._plan())
        back = paths.hydrate_absolute(stripped, Path(self.OTHER))

        self.assertEqual(back["source_root"], self.OTHER + "/Downloads")
        self.assertEqual(back["managed_dir"], self.OTHER + "/Downloads/00_File_Organizer")
        self.assertEqual(back["actions"][0]["source"], self.OTHER + "/Downloads/report.pdf")
        self.assertEqual(
            back["actions"][0]["destination"], self.OTHER + "/Downloads/PDF/report.pdf"
        )
        self.assertIsNone(back["actions"][1]["destination"])

    def test_hydrate_is_a_no_op_on_a_full_plan(self) -> None:
        plan = self._plan()
        self.assertEqual(paths.hydrate_absolute(plan, Path(self.HOME)), plan)


if __name__ == "__main__":
    unittest.main()
