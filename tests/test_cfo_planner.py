"""The decision chain end to end, with the clock and the safety net injected."""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from carl_file_organizer import paths
from carl_file_organizer.config import resolve_config
from carl_file_organizer.planner import SCHEMA_VERSION, build_plan, plan_paths, write_plan

from cfo_helpers import (  # noqa: E402 - the path shim has to run first
    GUARD_OFFLINE,
    NOW,
    action_for,
    actions_for,
    age,
    fake_lsof,
    guard_with,
    write,
)


def plan_for(root: Path, *, lang: str = "zh", profile: str = "tiered", **kwargs):
    """Build a plan whose home is the temp root, so portable paths stay $HOME/."""

    config = kwargs.pop("config", None) or resolve_config(root, profile=profile, lang=lang)
    options = kwargs.pop("guard_options", GUARD_OFFLINE)
    return build_plan(
        root,
        config=config,
        now=kwargs.pop("now", NOW),
        home=kwargs.pop("home", root),
        guard_options=options,
        trash_backend=kwargs.pop("trash_backend", "finder"),
        **kwargs
    )


class EnvelopeTests(unittest.TestCase):
    def test_schema_and_top_level_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md", "# hi\n"), hours=100)
            plan = plan_for(root)

            self.assertEqual(plan["schema_version"], SCHEMA_VERSION)
            for key in (
                "generator", "created_at", "now", "lang", "lang_source", "profile",
                "source_root", "source_root_portable", "managed_dir", "managed_dir_portable",
                "names", "capabilities", "scan_policy", "disk", "summary", "pinned",
                "actions", "groups", "approved_action_ids", "overrides",
                "approved_at", "approved_by",
            ):
                self.assertIn(key, plan)
            self.assertEqual(plan["approved_action_ids"], [])
            self.assertEqual(plan["overrides"], [])
            self.assertEqual(plan["now"], NOW.isoformat())

    def test_every_portable_path_starts_at_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md"), hours=100)
            age(write(root / "photo.png"), hours=100)
            plan = plan_for(root)

            seen = 0
            stack = [plan]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    for key, value in node.items():
                        if isinstance(value, str) and key.endswith("_portable"):
                            seen += 1
                            self.assertTrue(value.startswith("$HOME/"), "{0}={1}".format(key, value))
                        else:
                            stack.append(value)
                elif isinstance(node, list):
                    stack.extend(node)
            self.assertGreater(seen, 3)

    def test_absolute_paths_appear_only_where_they_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md"), hours=100)
            plan = plan_for(root)
            allowed = {"source", "destination", "source_root", "managed_dir"}
            for action in plan["actions"]:
                for key, value in action.items():
                    if key in allowed or not isinstance(value, str):
                        continue
                    self.assertNotIn(str(root), value, key)

    def test_capabilities_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md"), hours=100)
            plan = plan_for(root)
            self.assertIn(
                plan["capabilities"]["trash_backend"], {"finder", "gio", "none"}
            )
            self.assertIn("finder_tags", plan["capabilities"])
            self.assertIn("permanent_delete_offered", plan["capabilities"])

    def test_summary_counts_match_the_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md"), hours=100)
            age(write(root / "fresh.md"), hours=1)
            (root / "folder").mkdir()
            age(root / "folder", hours=100)
            plan = plan_for(root)

            by_kind = {}
            by_tier = {}
            for action in plan["actions"]:
                by_kind[action["kind"]] = by_kind.get(action["kind"], 0) + 1
                by_tier[action["tier"]] = by_tier.get(action["tier"], 0) + 1
            self.assertEqual(plan["summary"]["by_kind"], by_kind)
            self.assertEqual(plan["summary"]["by_tier"], by_tier)
            self.assertEqual(
                plan["summary"]["entries"],
                plan["summary"]["files"] + plan["summary"]["dirs"],
            )
            self.assertEqual(plan["summary"]["proposed_reclaimed_bytes"], 0)

    def test_plan_paths_and_write_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md"), hours=100)
            config = resolve_config(root, profile="tiered", lang="zh")
            where = plan_paths(config)
            self.assertEqual(where.managed.name, "00_下载目录管理")
            plan = plan_for(root, config=config)
            write_plan(plan, where.plan)
            self.assertTrue(where.plan.is_file())


class SettlingTests(unittest.TestCase):
    def test_forty_seven_hours_holds_and_forty_nine_moves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = write(root / "report.pdf", "%PDF\n")

            age(target, hours=47)
            plan = plan_for(root)
            hold = action_for(plan, "report.pdf", "hold")
            self.assertEqual(hold["rule"], "hold:aging")
            self.assertEqual(hold["tier"], "aging")
            self.assertFalse(hold["approvable"])
            self.assertIsNone(hold["destination"])
            self.assertIn("ready_at", hold["hold_reason"])
            ready = hold["hold_reason"]["ready_at"]
            self.assertTrue(ready > NOW.isoformat())

            age(target, hours=49)
            plan = plan_for(root)
            move = action_for(plan, "report.pdf", "move")
            self.assertEqual(move["rule"], "ext:.pdf")
            self.assertEqual(move["tier"], "routine")
            self.assertTrue(move["approvable"])
            self.assertIn("20_知识库/文档资料/PDF", move["destination_portable"])

    def test_archives_wait_a_full_week(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "tool.zip", "PK"), hours=100)
            plan = plan_for(root)
            self.assertEqual(action_for(plan, "tool.zip", "hold")["rule"], "hold:aging")

    def test_ready_at_is_the_modification_time_plus_the_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "report.pdf"), hours=10)
            plan = plan_for(root)
            hold = action_for(plan, "report.pdf", "hold")
            expected = (NOW - timedelta(hours=10) + timedelta(hours=48)).isoformat()
            self.assertEqual(hold["hold_reason"]["ready_at"][:16], expected[:16])


class PriorityTests(unittest.TestCase):
    def test_pinned_beats_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "api-password-notes.md"), hours=100)
            config = resolve_config(root, profile="tiered", lang="zh")
            config.profile["pinned"] = list(config.profile["pinned"]) + [
                "api-password-notes.md"
            ]
            plan = plan_for(root, config=config)

            found = actions_for(plan, "api-password-notes.md")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["rule"], "hold:pinned")
            self.assertEqual(found[0]["tier"], "pinned")

    def test_forbidden_beats_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "secret-vault.photoslibrary"
            vault.mkdir()
            age(vault, hours=100)
            plan = plan_for(root)

            found = actions_for(plan, "secret-vault.photoslibrary")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["rule"], "hold:forbidden")
            self.assertIn("forbidden:suffix", found[0]["hold_reason"]["label"])

    def test_a_sensitive_folder_moves_whole_and_ignores_the_settling_period(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "api-credential-dump"
            write(folder / "inside.txt")
            age(folder, hours=1)
            plan = plan_for(root)

            move = action_for(plan, "api-credential-dump", "move")
            self.assertEqual(move["tier"], "sensitive")
            self.assertEqual(move["subject_kind"], "dir")
            self.assertTrue(move["rule"].startswith("sensitive:"))
            self.assertIn("60_敏感信息/待转移/api-credential-dump", move["destination_portable"])
            self.assertIn("未读取内容", move["reason"]["zh"])

    def test_sensitive_beats_the_extension_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "server.pem"), hours=1)
            plan = plan_for(root)
            move = action_for(plan, "server.pem", "move")
            self.assertEqual(move["rule"], "sensitive:suffix")

    def test_pairing_beats_the_plain_folder_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "Archive.zip", "PK")
            write(root / "Archive" / "inside.txt")
            for item in (root / "Archive.zip", root / "Archive"):
                age(item, hours=300)
            plan = plan_for(root)

            folder = action_for(plan, "Archive", "move")
            self.assertEqual(folder["rule"], "pair")
            self.assertIn("00_收件箱/待判断/Archive/Archive", folder["destination_portable"])
            self.assertIsNotNone(folder["group_id"])


class FolderTests(unittest.TestCase):
    def test_a_folder_moves_whole_and_keeps_its_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "foo" / "inner.txt")
            age(root / "foo", hours=100)
            plan = plan_for(root)

            move = action_for(plan, "foo", "move")
            self.assertEqual(move["rule"], "dir:pending")
            self.assertTrue(move["reroutable"])
            self.assertTrue(move["destination_portable"].endswith("00_收件箱/待判断/foo"))
            self.assertIsNotNone(move["dir_stats"])

    def test_a_scratch_copy_only_gets_a_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "project-worktree-topic" / "inner.txt")
            age(root / "project-worktree-topic", hours=100)
            plan = plan_for(root)

            move = action_for(plan, "project-worktree-topic", "move")
            self.assertEqual(move["rule"], "dir:derivative")
            self.assertIn("derivative-copy:-worktree-", move["hints"])

    def test_unknown_extensions_wait_in_pending_and_can_be_rerouted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "dataset.parquet"), hours=100)
            plan = plan_for(root)

            move = action_for(plan, "dataset.parquet", "move")
            self.assertEqual(move["rule"], "unknown-ext")
            self.assertTrue(move["reroutable"])
            self.assertEqual(move["confidence"], 0.55)
            self.assertIn(move["destination_key"], plan["names"])


class BoundaryTests(unittest.TestCase):
    def test_partitions_hidden_files_and_symlinks_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md"), hours=100)
            write(root / ".hidden.md")
            for name in ("00_收件箱", "20_知识库", "00_下载目录管理"):
                (root / name).mkdir()
            (root / "link.md").symlink_to(root / "notes.md")
            write(root / "carl-file-organizer-approved-1.json", "{}")

            plan = plan_for(root)
            names = {action["filename"] for action in plan["actions"]}

            self.assertEqual(names, {"notes.md"})
            self.assertEqual(plan["scan_policy"]["skipped"]["partitions"], 3)
            self.assertEqual(plan["scan_policy"]["skipped"]["symlinks"], 1)
            self.assertEqual(plan["scan_policy"]["skipped"]["artifacts"], 1)

    def test_a_taken_destination_is_redirected_and_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "report.pdf", "new\n"), hours=100)
            write(root / "20_知识库" / "文档资料" / "PDF" / "report.pdf", "already here\n")

            plan = plan_for(root)
            move = action_for(plan, "report.pdf", "move")

            self.assertEqual(move["rule"], "conflict")
            self.assertEqual(move["destination_key"], "inbox.dup")
            self.assertEqual(
                move["destination_portable"],
                "$HOME/00_收件箱/重复待确认/report-2026-09-02_12-00-00.pdf",
            )
            self.assertFalse(move["reroutable"])
            self.assertEqual(
                (root / "20_知识库" / "文档资料" / "PDF" / "report.pdf").read_text(), "already here\n"
            )

    def test_a_redirected_copy_keeps_a_double_suffix_and_a_folder_keeps_none(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "release.tar.gz", "new\n"), hours=400)
            write(root / "90_归档" / "压缩包" / "其他压缩包" / "release.tar.gz", "already here\n")
            folder = root / "web-prototype"
            age(write(folder / "index.html", "<p>hi</p>\n"), hours=100)
            age(folder, hours=100)
            write(root / "00_收件箱" / "待判断" / "web-prototype" / "keep.txt", "taken\n")

            plan = plan_for(root)
            archive = action_for(plan, "release.tar.gz", "move")
            self.assertEqual(
                archive["destination_portable"],
                "$HOME/00_收件箱/重复待确认/release-2026-09-02_12-00-00.tar.gz",
            )

            moved_dir = action_for(plan, "web-prototype", "move")
            self.assertEqual(
                moved_dir["destination_portable"],
                "$HOME/00_收件箱/重复待确认/web-prototype-2026-09-02_12-00-00",
            )


class LanguageTests(unittest.TestCase):
    def test_english_names_are_used_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "report.pdf"), hours=100)
            age(write(root / "dataset.parquet"), hours=100)
            plan = plan_for(root, lang="en")

            self.assertEqual(plan["lang"], "en")
            self.assertIn(
                "20_Library/Documents/PDF", action_for(plan, "report.pdf")["destination_portable"]
            )
            self.assertIn(
                "00_Inbox/Pending", action_for(plan, "dataset.parquet")["destination_portable"]
            )
            self.assertEqual(plan["names"]["library.docs.pdf"], "20_Library/Documents/PDF")


class GroupTests(unittest.TestCase):
    def test_pair_group_options_all_point_at_real_approvable_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "Archive.zip", "PK")
            write(root / "Archive" / "inside.txt")
            for item in (root / "Archive.zip", root / "Archive"):
                age(item, hours=300)
            plan = plan_for(root)

            group = next(g for g in plan["groups"] if g["kind"] == "pair")
            by_id = {action["id"]: action for action in plan["actions"]}
            keys = [option["key"] for option in group["options"]]

            self.assertIn("keep_all", keys)
            self.assertIn(group["default_choice"], keys)
            self.assertTrue(group["default_choice"].startswith("keep:"))
            for option in group["options"]:
                self.assertTrue(option["action_ids"])
                for action_id in option["action_ids"]:
                    self.assertIn(action_id, by_id)
                    self.assertTrue(by_id[action_id]["approvable"])
                    self.assertEqual(by_id[action_id]["group_id"], group["group_id"])
                if any(by_id[a]["kind"] == "delete" for a in option["action_ids"]):
                    self.assertIn("allow-permanent-delete", option["requires"])

    def test_identical_files_form_a_sha256_group_that_defaults_to_keeping_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "guide.pdf", "same bytes\n"), hours=100)
            age(write(root / "guide (1).pdf", "same bytes\n"), hours=100)
            plan = plan_for(root, hash_duplicates=True)

            group = next(g for g in plan["groups"] if g["kind"] == "duplicate")
            self.assertEqual(group["evidence"], "sha256")
            self.assertIsNotNone(group["sha256"])
            self.assertTrue(group["default_choice"].startswith("keep:"))
            self.assertGreater(group["potential_bytes"], 0)

    def test_lookalike_names_default_to_keeping_everything(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "export.png", "AAAA"), hours=100)
            age(write(root / "export_1.png", "BBBB"), hours=100)
            plan = plan_for(root, hash_duplicates=True)

            group = next(g for g in plan["groups"] if g["kind"] == "duplicate")
            self.assertEqual(group["evidence"], "name-pattern")
            self.assertEqual(group["default_choice"], "keep_all")
            self.assertEqual(group["potential_bytes"], 0)
            self.assertFalse(
                [
                    action
                    for action in plan["actions"]
                    if action["group_id"] == group["group_id"] and action["kind"] == "delete"
                ]
            )

    def test_regenerable_output_offers_trash_and_delete_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "proj" / "package.json", "{}")
            write(root / "proj" / "node_modules" / "left-pad" / "index.js", "x")
            age(root / "proj", hours=100)
            plan = plan_for(root)

            group = next(g for g in plan["groups"] if g["kind"] == "regenerable")
            self.assertEqual(
                {option["key"] for option in group["options"]}, {"trash_all", "delete_all"}
            )
            self.assertEqual(group["default_choice"], "trash_all")
            self.assertEqual(group["member_labels"][group["members"][0]], "proj/node_modules")
            kinds = {
                action["kind"]
                for action in plan["actions"]
                if action["group_id"] == group["group_id"]
            }
            self.assertEqual(kinds, {"trash", "delete"})

    def test_permanent_delete_can_be_turned_off_entirely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "proj" / "node_modules" / "left-pad" / "index.js", "x")
            age(root / "proj", hours=100)
            plan = plan_for(root, offer_permanent_delete=False)

            self.assertFalse([a for a in plan["actions"] if a["kind"] == "delete"])
            self.assertFalse(plan["capabilities"]["permanent_delete_offered"])

    def test_without_a_trash_backend_nothing_offers_the_trash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "proj" / "node_modules" / "left-pad" / "index.js", "x")
            age(root / "proj", hours=100)
            plan = plan_for(root, trash_backend="none")

            self.assertFalse([a for a in plan["actions"] if a["kind"] == "trash"])
            group = next(g for g in plan["groups"] if g["kind"] == "regenerable")
            self.assertEqual([option["key"] for option in group["options"]], ["delete_all"])


class GuardChainTests(unittest.TestCase):
    def test_an_open_file_is_held_with_the_process_named(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = age(write(root / "session.log", "line\n"), hours=100)
            with open(str(target), "r", encoding="utf-8"):
                plan = plan_for(
                    root,
                    guard_options=guard_with(
                        lsof_enabled=True,
                        lsof_runner=fake_lsof({"session.log": "python3,48213"}),
                    ),
                )

            hold = action_for(plan, "session.log", "hold")
            self.assertEqual(hold["rule"], "hold:in_use")
            self.assertEqual(hold["tier"], "in_use")
            self.assertFalse(hold["approvable"])
            self.assertEqual(hold["guard"]["open_by"][0]["pid"], 48213)
            self.assertIn("python3", hold["reason"]["zh"])

    def test_a_referenced_script_is_held_with_the_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / "Downloads"
            root.mkdir()
            age(write(root / "backup-tool.sh", "#!/bin/sh\n"), hours=100)
            plist = write(
                home / "com.example.backup.plist",
                "<plist>\n<string>$HOME/Downloads/backup-tool.sh</string>\n</plist>\n",
            )
            plan = plan_for(
                root, home=home, guard_options=guard_with(reference_files=[plist])
            )

            hold = action_for(plan, "backup-tool.sh", "hold")
            self.assertEqual(hold["rule"], "hold:referenced")
            self.assertEqual(hold["tier"], "referenced")
            self.assertEqual(hold["guard"]["referenced_in"][0]["line"], 2)
            self.assertIn(":2", hold["reason"]["zh"])

    def test_allow_referenced_downgrades_the_hold_to_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / "Downloads"
            root.mkdir()
            age(write(root / "backup-tool.sh", "#!/bin/sh\n"), hours=100)
            plist = write(
                home / "com.example.backup.plist",
                "<plist>\n<string>$HOME/Downloads/backup-tool.sh</string>\n</plist>\n",
            )
            plan = plan_for(
                root,
                home=home,
                allow_referenced=True,
                guard_options=guard_with(reference_files=[plist]),
            )

            move = action_for(plan, "backup-tool.sh", "move")
            self.assertTrue(move["approvable"])
            self.assertIn("referenced-warning", move["hints"])
            self.assertTrue(move["guard"]["referenced_in"])
            self.assertIn("改引用", move["detail"]["zh"])
            self.assertTrue(plan["scan_policy"]["allow_referenced"])

    def test_a_symlink_pointing_in_is_a_reference_too(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            root = home / "Downloads"
            root.mkdir()
            target = age(write(root / "backup-tool.sh"), hours=100)
            binaries = home / "bin"
            binaries.mkdir()
            (binaries / "backup-tool").symlink_to(target)

            plan = plan_for(root, home=home, guard_options=guard_with(scan_roots=[binaries]))
            hold = action_for(plan, "backup-tool.sh", "hold")

            self.assertEqual(hold["tier"], "referenced")
            self.assertEqual(hold["guard"]["incoming_symlinks"], ["$HOME/bin/backup-tool"])

    def test_a_git_file_means_a_worktree_and_a_worktree_is_never_moved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree = root / "topic-worktree-fix"
            write(worktree / ".git", "gitdir: /elsewhere/.git/worktrees/topic\n")
            age(worktree, hours=100)

            plan = plan_for(root)
            hold = action_for(plan, "topic-worktree-fix", "hold")

            self.assertEqual(hold["rule"], "hold:referenced")
            self.assertEqual(hold["tier"], "referenced")
            self.assertIn("git-worktree", hold["guard"]["shape"])
            self.assertIn("worktree", hold["reason"]["en"])

    def test_a_git_folder_only_gets_a_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            write(repo / ".git" / "HEAD", "ref: refs/heads/main\n")
            write(repo / "package.json", "{}")
            age(repo, hours=100)

            config = resolve_config(root, profile="tiered", lang="zh")

            class _Status(object):
                returncode = 0
                stdout = " M a.py\n"

            plan = plan_for(
                root,
                config=config,
                guard_options=guard_with(git_status_runner=lambda path, timeout: _Status()),
            )
            move = action_for(plan, "repo", "move")

            self.assertTrue(move["approvable"])
            self.assertIn("git-repo", move["hints"])
            self.assertIn("node-project", move["hints"])
            self.assertIn("git-dir", move["guard"]["shape"])
            self.assertEqual(move["guard"]["uncommitted"], 1)

    def test_something_touched_ten_minutes_ago_waits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "dataset.parquet"), hours=0.05)
            plan = plan_for(root)

            hold = action_for(plan, "dataset.parquet", "hold")
            self.assertEqual(hold["rule"], "hold:aging")
            self.assertEqual(hold["tier"], "aging")
            self.assertIn("十分钟", hold["reason"]["zh"])


class ColdTests(unittest.TestCase):
    def test_a_large_file_gains_a_disposal_option(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "clip.mp4", "x" * 4096), hours=100)
            plan = plan_for(root, large_bytes=1024)

            kinds = {action["kind"] for action in actions_for(plan, "clip.mp4")}
            self.assertEqual(kinds, {"move", "trash", "delete"})
            trash = action_for(plan, "clip.mp4", "trash")
            self.assertEqual(trash["tier"], "cold")
            self.assertEqual(trash["rule"], "cold:large")
            self.assertEqual(trash["reclaims_bytes"], 4096)
            self.assertEqual(action_for(plan, "clip.mp4", "move")["reclaims_bytes"], 0)

    def test_a_settled_installer_gains_a_disposal_option(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "tool.dmg", "x"), hours=400)
            plan = plan_for(root)

            trash = action_for(plan, "tool.dmg", "trash")
            self.assertEqual(trash["rule"], "cold:installer")
            self.assertEqual(trash["tier"], "cold")


class SimpleProfileTests(unittest.TestCase):
    def test_the_flat_profile_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write(root / "notes.txt", "hello")
            plan = plan_for(root, profile="simple", lang="en")

            move = action_for(plan, "notes.txt", "move")
            self.assertEqual(move["destination_key"], "documents")
            self.assertTrue(move["destination_portable"].endswith("Documents/notes.txt"))


if __name__ == "__main__":
    unittest.main()
