"""Execution: what it refuses, what it skips, and what it puts back.

Every plan in here is built from real temporary files with ``ids.subject_id``
and ``ids.action_id`` computed on the spot, so the tests exercise the same
identity check the executor uses, without depending on the planner.
"""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from carl_file_organizer import config as config_module
from carl_file_organizer import executor, ids, manifest, paths
from carl_file_organizer.executor import ExecutionRefused, PlanError

HOME = Path.home()
NOW = datetime(2026, 9, 2, 10, 20, 11).astimezone()

NAMES = {
    "inbox": "00_收件箱",
    "inbox.pending": "00_收件箱/待判断",
    "inbox.dup": "00_收件箱/重复待确认",
    "library": "20_知识库",
    "library.docs": "20_知识库/文档资料",
    "library.docs.pdf": "20_知识库/文档资料/PDF",
    "sensitive": "60_敏感信息",
    "sensitive.pending": "60_敏感信息/待转移",
    "work": "10_工作区",
    "work.tools": "10_工作区/工具与导出",
    "work.tools.scripts": "10_工作区/工具与导出/脚本",
}


def make_action(
    path: Path,
    kind: str,
    *,
    destination=None,
    destination_key=None,
    tier: str = "routine",
    rule: str = "ext:.pdf",
    approvable: bool = True,
    reroutable: bool = False,
    group_id=None,
    size_bytes=None,
    home: Path = HOME,
):
    stat = path.stat()
    subject_kind = "dir" if path.is_dir() else "file"
    subject = ids.subject_id(path, subject_kind, stat.st_size, stat.st_mtime_ns)
    destination_portable = (
        paths.portable(Path(destination), home) if destination is not None else None
    )
    recorded_size = stat.st_size if size_bytes is None else size_bytes
    return {
        "id": ids.action_id(subject, kind, destination_portable),
        "subject_id": subject,
        "kind": kind,
        "subject_kind": subject_kind,
        "source": str(path),
        "source_portable": paths.portable(path, home),
        "filename": path.name,
        "destination": str(destination) if destination is not None else None,
        "destination_portable": destination_portable,
        "destination_key": destination_key,
        "size_bytes": recorded_size,
        "modified_ns": stat.st_mtime_ns,
        "age_hours": 100,
        "rule": rule,
        "reason": {"zh": "测试用的理由", "en": "reason for the test"},
        "detail": None,
        "confidence": 0.98,
        "tier": tier,
        "group_id": group_id,
        "approvable": approvable,
        "reroutable": reroutable,
        "default_selected": False,
        "requires": ["allow-permanent-delete"] if kind == "delete" else [],
        "reclaims_bytes": recorded_size if kind in ("trash", "delete") else 0,
        "restore_method": None,
        "tags": [],
        "hints": [],
        "hold_reason": None,
        "guard": {"open_by": [], "referenced_in": [], "incoming_symlinks": [], "shape": []},
        "dir_stats": None,
    }


def make_plan(
    root: Path,
    actions,
    *,
    approved=(),
    overrides=(),
    groups=(),
    lang: str = "zh",
    trash_backend: str = "finder",
    home: Path = HOME,
):
    return {
        "schema_version": 2,
        "generator": {"name": "carl-file-organizer", "version": "0.3.0"},
        "created_at": NOW.isoformat(),
        "now": NOW.isoformat(),
        "lang": lang,
        "lang_source": "flag",
        "profile": {"name": "tiered", "source": "builtin", "dotfile": None, "hash": ""},
        "source_root": str(root),
        "source_root_portable": paths.portable(root, home),
        "managed_dir": str(root / "00_下载目录管理"),
        "managed_dir_portable": paths.portable(root / "00_下载目录管理", home),
        "names": dict(NAMES),
        "capabilities": {
            "trash_backend": trash_backend,
            "finder_tags": True,
            "permanent_delete_offered": True,
        },
        "scan_policy": {"depth": 1},
        "disk": {},
        "summary": {},
        "pinned": [],
        "actions": list(actions),
        "groups": list(groups),
        "approved_action_ids": list(approved),
        "overrides": list(overrides),
        "approved_at": None,
        "approved_by": "agent:test",
    }


class Fixture:
    """A temporary folder plus the config the executor would resolve for it."""

    def __init__(self, stack: unittest.TestCase) -> None:
        temporary = tempfile.TemporaryDirectory()
        stack.addCleanup(temporary.cleanup)
        self.root = paths.realpath(Path(temporary.name))
        self.config = config_module.resolve_config(self.root, lang="zh", profile="tiered")
        self.managed = config_module.managed_dir(self.config)

    def file(self, name: str, content: str = "hello") -> Path:
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def folder(self, name: str, entries=("a.txt", "b.txt")) -> Path:
        target = self.root / name
        target.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            (target / entry).write_text(entry, encoding="utf-8")
        return target

    def pdf_dest(self, name: str) -> Path:
        return self.root / NAMES["library.docs.pdf"] / name

    def apply(self, plan, **kw):
        options = {"config": self.config, "now": NOW, "open_handles_fn": lambda path: []}
        options.update(kw)
        return executor.apply_approved_plan(plan, **options)

    def audit_records(self):
        return manifest.read_audit(manifest.audit_path(self.managed))

    def manifest_file(self):
        found = sorted(self.managed.glob("*.tsv"))
        return found[0] if found else None


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def test_only_approved_action_moves(self) -> None:
        first = self.fixture.file("first.pdf", "document")
        second = self.fixture.file("second.pdf", "image")
        actions = [
            make_action(first, "move", destination=self.fixture.pdf_dest("first.pdf"),
                        destination_key="library.docs.pdf"),
            make_action(second, "move", destination=self.fixture.pdf_dest("second.pdf"),
                        destination_key="library.docs.pdf"),
        ]
        plan = make_plan(self.fixture.root, actions, approved=[actions[0]["id"]])

        report = self.fixture.apply(plan)

        self.assertEqual(len(report.results), 1)
        self.assertEqual(report.results[0]["status"], "moved")
        self.assertTrue(self.fixture.pdf_dest("first.pdf").exists())
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())

    def test_schema_version_one_is_refused(self) -> None:
        plan = make_plan(self.fixture.root, [])
        plan["schema_version"] = 1
        with self.assertRaises(PlanError):
            executor.validate_plan(plan, allow_permanent_delete=False)

    def test_unknown_approval_id_is_rejected(self) -> None:
        first = self.fixture.file("first.pdf")
        actions = [make_action(first, "move", destination=self.fixture.pdf_dest("first.pdf"))]
        plan = make_plan(self.fixture.root, actions, approved=["invented"])
        with self.assertRaises(PlanError):
            self.fixture.apply(plan)
        self.assertTrue(first.exists())

    def test_tampered_destination_is_rejected(self) -> None:
        first = self.fixture.file("first.pdf")
        action = make_action(first, "move", destination=self.fixture.pdf_dest("first.pdf"),
                             destination_key="library.docs.pdf")
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])
        action["destination"] = str(self.fixture.root / "20_知识库" / "renamed.pdf")
        action["destination_portable"] = paths.portable(Path(action["destination"]), HOME)

        with self.assertRaises(PlanError):
            self.fixture.apply(plan)
        self.assertTrue(first.exists())

    def test_destination_outside_the_root_is_rejected(self) -> None:
        first = self.fixture.file("first.pdf")
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(outside), True)
        action = make_action(first, "move", destination=outside / "first.pdf")
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])
        with self.assertRaises(PlanError):
            self.fixture.apply(plan)
        self.assertTrue(first.exists())

    def test_two_actions_on_the_same_subject_are_rejected(self) -> None:
        target = self.fixture.file("Archive.zip")
        move = make_action(target, "move", destination=self.fixture.root / NAMES["inbox.pending"] / "Archive.zip",
                           tier="duplicate", rule="pair")
        drop = make_action(target, "trash", tier="duplicate", rule="pair")
        plan = make_plan(self.fixture.root, [move, drop], approved=[move["id"], drop["id"]])
        with self.assertRaises(PlanError) as caught:
            self.fixture.apply(plan)
        self.assertIn("same item", str(caught.exception))
        self.assertTrue(target.exists())

    def test_hold_id_is_rejected(self) -> None:
        target = self.fixture.file("installer.dmg")
        hold = make_action(target, "hold", tier="aging", rule="hold:aging", approvable=False)
        plan = make_plan(self.fixture.root, [hold], approved=[hold["id"]])
        with self.assertRaises(PlanError) as caught:
            self.fixture.apply(plan)
        self.assertIn("not approvable", str(caught.exception))
        self.assertTrue(target.exists())

    def test_root_that_is_a_symlink_is_refused(self) -> None:
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(outside), True)
        link = self.fixture.root / "link-root"
        link.symlink_to(outside, target_is_directory=True)
        plan = make_plan(link, [])
        with self.assertRaises(PlanError):
            executor.validate_plan(plan, allow_permanent_delete=False)


class DeleteGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def _node_modules(self):
        project = self.fixture.folder("web-prototype", entries=())
        modules = project / "node_modules"
        modules.mkdir()
        (modules / "left-pad.js").write_text("module", encoding="utf-8")
        return modules

    def test_delete_requires_the_flag_and_refuses_the_whole_batch(self) -> None:
        modules = self._node_modules()
        other = self.fixture.file("report.pdf")
        move = make_action(other, "move", destination=self.fixture.pdf_dest("report.pdf"))
        drop = make_action(modules, "delete", tier="regenerable", rule="regenerable:node_modules")
        plan = make_plan(self.fixture.root, [move, drop], approved=[move["id"], drop["id"]])

        with self.assertRaises(ExecutionRefused):
            self.fixture.apply(plan)

        self.assertTrue(modules.exists())
        self.assertTrue(other.exists(), "a refused batch must not move anything either")
        self.assertFalse(self.fixture.managed.exists())

    def test_delete_with_the_flag_removes_regenerable_output(self) -> None:
        modules = self._node_modules()
        drop = make_action(modules, "delete", tier="regenerable", rule="regenerable:node_modules")
        plan = make_plan(self.fixture.root, [drop], approved=[drop["id"]])

        report = self.fixture.apply(plan, allow_permanent_delete=True)

        self.assertEqual(report.results[0]["status"], "deleted")
        self.assertFalse(modules.exists())

    def test_delete_outside_the_regenerable_list_is_refused(self) -> None:
        project = self.fixture.folder("web-prototype", entries=())
        source = project / "src"
        source.mkdir()
        (source / "index.js").write_text("real work", encoding="utf-8")
        drop = make_action(source, "delete", tier="regenerable", rule="regenerable:src")
        plan = make_plan(self.fixture.root, [drop], approved=[drop["id"]])

        report = self.fixture.apply(plan, allow_permanent_delete=True)

        self.assertEqual(report.results[0]["status"], "refused")
        self.assertTrue(source.exists())
        self.assertIn("src", report.results[0]["detail"])

    def test_duplicate_delete_needs_a_surviving_copy(self) -> None:
        first = self.fixture.file("guide.pdf", "same")
        second = self.fixture.file("guide (1).pdf", "same")
        keep = make_action(first, "move", destination=self.fixture.pdf_dest("guide.pdf"),
                           tier="duplicate", rule="dup:sha256", group_id="dup-1")
        drop = make_action(second, "delete", tier="duplicate", rule="dup:sha256", group_id="dup-1")
        group = {
            "group_id": "dup-1",
            "kind": "duplicate",
            "members": [keep["subject_id"], drop["subject_id"]],
        }

        plan = make_plan(self.fixture.root, [keep, drop], approved=[keep["id"], drop["id"]],
                         groups=[group])
        report = self.fixture.apply(plan, allow_permanent_delete=True)
        self.assertEqual(report.status_of(drop["id"]), "deleted")
        self.assertFalse(second.exists())
        self.assertTrue(self.fixture.pdf_dest("guide.pdf").exists())

    def test_deleting_every_member_of_a_group_is_refused(self) -> None:
        first = self.fixture.file("guide.pdf", "same")
        second = self.fixture.file("guide (1).pdf", "same")
        one = make_action(first, "delete", tier="duplicate", rule="dup:sha256", group_id="dup-1")
        two = make_action(second, "delete", tier="duplicate", rule="dup:sha256", group_id="dup-1")
        group = {"group_id": "dup-1", "kind": "duplicate",
                 "members": [one["subject_id"], two["subject_id"]]}
        plan = make_plan(self.fixture.root, [one, two], approved=[one["id"], two["id"]],
                         groups=[group])

        report = self.fixture.apply(plan, allow_permanent_delete=True)

        self.assertEqual({record["status"] for record in report.results}, {"refused"})
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())


class PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def test_changed_source_is_skipped(self) -> None:
        target = self.fixture.file("report.pdf")
        action = make_action(target, "move", destination=self.fixture.pdf_dest("report.pdf"))
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])

        stat = target.stat()
        os.utime(str(target), ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        report = self.fixture.apply(plan)
        self.assertEqual(report.results[0]["status"], "skipped")
        self.assertTrue(target.exists())
        self.assertFalse(self.fixture.pdf_dest("report.pdf").exists())

    def test_vanished_source_is_skipped(self) -> None:
        target = self.fixture.file("report.pdf")
        action = make_action(target, "move", destination=self.fixture.pdf_dest("report.pdf"))
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])
        target.unlink()

        report = self.fixture.apply(plan)
        self.assertEqual(report.results[0]["status"], "skipped")

    def test_no_overwrite_at_apply_time(self) -> None:
        target = self.fixture.file("report.pdf", "mine")
        destination = self.fixture.pdf_dest("report.pdf")
        action = make_action(target, "move", destination=destination)
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("someone else", encoding="utf-8")

        report = self.fixture.apply(plan)
        self.assertEqual(report.results[0]["status"], "conflict")
        self.assertEqual(target.read_text(encoding="utf-8"), "mine")
        self.assertEqual(destination.read_text(encoding="utf-8"), "someone else")

    def test_symlink_escape_is_refused(self) -> None:
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(outside), True)
        real = outside / "secret.pdf"
        real.write_text("outside the folder", encoding="utf-8")
        link = self.fixture.root / "report.pdf"
        link.symlink_to(real)

        action = make_action(link, "move", destination=self.fixture.pdf_dest("report.pdf"))
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])

        report = self.fixture.apply(plan)
        self.assertEqual(report.results[0]["status"], "refused")
        self.assertTrue(real.exists())
        self.assertTrue(link.is_symlink())

    def test_forbidden_zone_is_refused(self) -> None:
        repository = self.fixture.folder(".git", entries=("HEAD",))
        action = make_action(repository, "move",
                             destination=self.fixture.root / NAMES["inbox.pending"] / ".git")
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])

        report = self.fixture.apply(plan)
        self.assertEqual(report.results[0]["status"], "refused")
        self.assertTrue(repository.exists())

    def test_an_open_file_is_skipped(self) -> None:
        target = self.fixture.file("session.log")
        action = make_action(target, "move",
                             destination=self.fixture.root / NAMES["inbox.pending"] / "session.log")
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])

        report = self.fixture.apply(
            plan, open_handles_fn=lambda path: [{"pid": "123", "command": "tail", "name": str(path)}]
        )
        self.assertEqual(report.results[0]["status"], "skipped")
        self.assertTrue(target.exists())

    def test_spotlight_reading_a_file_does_not_count_as_in_use(self) -> None:
        target = self.fixture.file("report.pdf")

        class Result:
            returncode = 0
            stdout = "p501\ncmdworker_shared\nn{0}\n".format(target)
            stderr = ""

        with mock.patch.object(executor.shutil, "which", lambda name: "/usr/sbin/lsof"), \
                mock.patch.object(executor.subprocess, "run", lambda *a, **kw: Result()):
            self.assertEqual(executor.open_handles(target), [])

        class Real:
            returncode = 0
            stdout = "p777\nctail\nn{0}\n".format(target)
            stderr = ""

        with mock.patch.object(executor.shutil, "which", lambda name: "/usr/sbin/lsof"), \
                mock.patch.object(executor.subprocess, "run", lambda *a, **kw: Real()):
            found = executor.open_handles(target)
        self.assertEqual(found, [{"pid": "777", "command": "tail", "name": str(target)}])

    def test_no_lsof_means_no_objection(self) -> None:
        target = self.fixture.file("report.pdf")
        with mock.patch.object(executor.shutil, "which", lambda name: None):
            self.assertEqual(executor.open_handles(target), [])

    def test_a_folder_keeps_its_name_and_moves_whole(self) -> None:
        folder = self.fixture.folder("web-prototype")
        destination = self.fixture.root / NAMES["inbox.pending"] / "web-prototype"
        action = make_action(folder, "move", destination=destination, rule="dir:pending",
                             reroutable=True, destination_key="inbox.pending")
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])

        report = self.fixture.apply(plan)
        self.assertEqual(report.results[0]["status"], "moved")
        self.assertTrue((destination / "a.txt").exists())

    def test_a_folder_whose_recorded_size_was_walked_still_matches(self) -> None:
        folder = self.fixture.folder("web-prototype")
        destination = self.fixture.root / NAMES["inbox.pending"] / "web-prototype"
        action = make_action(folder, "move", destination=destination, rule="dir:pending")
        # A planner may record the walked size rather than the inode size.
        walked = sum(item.stat().st_size for item in folder.iterdir())
        action["size_bytes"] = walked
        action["subject_id"] = ids.subject_id(folder, "dir", walked, folder.stat().st_mtime_ns)
        action["id"] = ids.action_id(
            action["subject_id"], "move", paths.portable(destination, HOME)
        )
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])

        report = self.fixture.apply(plan)
        self.assertEqual(report.results[0]["status"], "moved")


class OverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def _pending(self):
        target = self.fixture.file("dataset.parquet")
        action = make_action(
            target,
            "move",
            destination=self.fixture.root / NAMES["inbox.pending"] / "dataset.parquet",
            destination_key="inbox.pending",
            rule="unknown-ext",
            reroutable=True,
        )
        return target, action

    def test_override_reroutes_through_the_names_table(self) -> None:
        target, action = self._pending()
        plan = make_plan(
            self.fixture.root,
            [action],
            approved=[action["id"]],
            overrides=[{"action_id": action["id"], "destination_key": "work.tools.scripts"}],
        )

        report = self.fixture.apply(plan)

        moved_to = self.fixture.root / NAMES["work.tools.scripts"] / "dataset.parquet"
        self.assertEqual(report.results[0]["status"], "moved")
        self.assertTrue(moved_to.exists())
        self.assertFalse(target.exists())

    def test_override_to_an_unknown_key_is_rejected(self) -> None:
        target, action = self._pending()
        plan = make_plan(
            self.fixture.root,
            [action],
            approved=[action["id"]],
            overrides=[{"action_id": action["id"], "destination_key": "somewhere.else"}],
        )
        with self.assertRaises(PlanError):
            self.fixture.apply(plan)
        self.assertTrue(target.exists())

    def test_override_cannot_carry_a_literal_path(self) -> None:
        target, action = self._pending()
        plan = make_plan(
            self.fixture.root,
            [action],
            approved=[action["id"]],
            overrides=[{"action_id": action["id"], "destination_key": "../../etc"}],
        )
        with self.assertRaises(PlanError):
            self.fixture.apply(plan)
        self.assertTrue(target.exists())

    def test_override_on_a_rule_bound_action_is_rejected(self) -> None:
        target = self.fixture.file("report.pdf")
        action = make_action(target, "move", destination=self.fixture.pdf_dest("report.pdf"),
                             destination_key="library.docs.pdf", rule="ext:.pdf")
        plan = make_plan(
            self.fixture.root,
            [action],
            approved=[action["id"]],
            overrides=[{"action_id": action["id"], "destination_key": "inbox.pending"}],
        )
        with self.assertRaises(PlanError) as caught:
            self.fixture.apply(plan)
        self.assertIn("cannot be rerouted", str(caught.exception))
        self.assertTrue(target.exists())


class VerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def test_verify_move_checks_size_and_both_ends(self) -> None:
        source = self.fixture.file("a.txt", "hello")
        destination = self.fixture.file("b.txt", "hello!")

        # A source still sitting there means the move never happened.
        ok, detail = executor.verify_move(source, destination, {"kind": "file", "size": 5})
        self.assertFalse(ok)
        self.assertIn("source still there", detail)

        source.unlink()
        ok, detail = executor.verify_move(source, destination, {"kind": "file", "size": 5})
        self.assertFalse(ok)
        self.assertIn("size mismatch", detail)

        ok, detail = executor.verify_move(source, destination, {"kind": "file", "size": 6})
        self.assertTrue(ok)

        ok, detail = executor.verify_move(source, self.fixture.root / "nope.txt",
                                          {"kind": "file", "size": 6})
        self.assertFalse(ok)

    def test_verify_move_counts_folder_entries(self) -> None:
        folder = self.fixture.folder("stuff", entries=("a.txt", "b.txt"))
        moved = self.fixture.root / "moved"
        shutil.move(str(folder), str(moved))
        self.assertEqual(
            executor.verify_move(folder, moved, {"kind": "dir", "entries": 2})[0], True
        )
        self.assertEqual(
            executor.verify_move(folder, moved, {"kind": "dir", "entries": 5})[0], False
        )

    def test_a_move_that_does_not_verify_goes_back_and_stops_the_batch(self) -> None:
        first = self.fixture.file("first.pdf", "one")
        second = self.fixture.file("second.pdf", "two")
        actions = [
            make_action(first, "move", destination=self.fixture.pdf_dest("first.pdf")),
            make_action(second, "move", destination=self.fixture.pdf_dest("second.pdf")),
        ]
        plan = make_plan(self.fixture.root, actions,
                         approved=[actions[0]["id"], actions[1]["id"]])

        def wrong_shape(path):
            return {"kind": "file", "size": 999999}

        with mock.patch.object(executor, "_shape", wrong_shape):
            report = self.fixture.apply(plan)

        self.assertEqual(report.results[0]["status"], "failed")
        self.assertIn("原路移回", report.results[0]["detail"])
        self.assertEqual(report.results[1]["status"], "skipped")
        self.assertTrue(report.stopped)

        self.assertEqual(first.read_text(encoding="utf-8"), "one")
        self.assertFalse(self.fixture.pdf_dest("first.pdf").exists())
        self.assertTrue(second.exists())
        self.assertFalse(self.fixture.pdf_dest("second.pdf").exists())

    def test_continue_on_error_keeps_going(self) -> None:
        first = self.fixture.file("first.pdf", "one")
        second = self.fixture.file("second.pdf", "two")
        actions = [
            make_action(first, "move", destination=self.fixture.pdf_dest("first.pdf")),
            make_action(second, "move", destination=self.fixture.pdf_dest("second.pdf")),
        ]
        plan = make_plan(self.fixture.root, actions,
                         approved=[actions[0]["id"], actions[1]["id"]])

        with mock.patch.object(executor, "_shape", lambda path: {"kind": "file", "size": 999999}):
            report = self.fixture.apply(plan, continue_on_error=True)

        self.assertEqual([record["status"] for record in report.results], ["failed", "failed"])
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())

    def test_manifest_is_written_before_execution(self) -> None:
        target = self.fixture.file("report.pdf")
        action = make_action(target, "move", destination=self.fixture.pdf_dest("report.pdf"))
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])
        seen = {}

        real_move = shutil.move

        def exploding_move(source, destination, *args, **kw):
            found = sorted(self.fixture.managed.glob("*.tsv"))
            seen["manifest"] = found[0].read_text(encoding="utf-8") if found else ""
            raise OSError("disk went away")

        with mock.patch.object(executor.shutil, "move", exploding_move):
            report = self.fixture.apply(plan)

        self.assertIn("PLANNED", seen["manifest"])
        self.assertIn("report.pdf", seen["manifest"])
        self.assertEqual(report.results[0]["status"], "failed")
        self.assertTrue(target.exists())

        records = self.fixture.audit_records()
        self.assertEqual(records[-1]["status"], "failed")
        self.assertIn("disk went away", records[-1]["detail"])
        self.assertIn("FAILED", self.fixture.manifest_file().read_text(encoding="utf-8"))
        self.assertIs(shutil.move, real_move)


class PaperTrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def test_dry_run_writes_nothing_at_all(self) -> None:
        target = self.fixture.file("report.pdf")
        action = make_action(target, "move", destination=self.fixture.pdf_dest("report.pdf"))
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])

        report = self.fixture.apply(plan, dry_run=True)

        self.assertEqual(report.results[0]["status"], "dry-run")
        self.assertTrue(target.exists())
        self.assertFalse(self.fixture.managed.exists())
        self.assertIsNone(report.manifest)
        self.assertIsNone(report.audit)

    def test_a_full_run_writes_manifest_audit_and_log(self) -> None:
        report_pdf = self.fixture.file("report.pdf", "a document")
        secret = self.fixture.file("api-key-backup.txt", "never read")
        occupied = self.fixture.file("guide.pdf", "mine")
        taken = self.fixture.pdf_dest("guide.pdf")
        taken.parent.mkdir(parents=True, exist_ok=True)
        taken.write_text("already here", encoding="utf-8")

        actions = [
            make_action(report_pdf, "move", destination=self.fixture.pdf_dest("report.pdf"),
                        destination_key="library.docs.pdf"),
            make_action(secret, "move",
                        destination=self.fixture.root / NAMES["sensitive.pending"] / "api-key-backup.txt",
                        destination_key="sensitive.pending", tier="sensitive",
                        rule="sensitive:marker"),
            make_action(occupied, "move", destination=taken,
                        destination_key="library.docs.pdf"),
        ]
        plan = make_plan(self.fixture.root, actions,
                         approved=[action["id"] for action in actions])

        result = self.fixture.apply(plan, recheck_fn=lambda: 0)

        self.assertEqual(
            [record["status"] for record in result.results], ["moved", "moved", "conflict"]
        )

        rows = manifest.read_manifest(result.manifest)
        self.assertEqual(result.manifest.name, "downloads-moves-2026-09-02_10-20-11.tsv".replace(
            "downloads", manifest.slug(self.fixture.root.name)))
        self.assertEqual([row["status"] for row in rows], ["MOVED", "MOVED", "CONFLICT"])
        self.assertTrue(rows[0]["restore_method"].startswith('mv "'))
        self.assertEqual(rows[0]["kind"], "move")
        self.assertEqual(rows[0]["action_id"], actions[0]["id"])

        records = self.fixture.audit_records()
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["run_id"], "2026-09-02_10-20-11")
        self.assertEqual(records[0]["trash_backend"], "finder")

        log = result.review_log.read_text(encoding="utf-8")
        self.assertIn("## 2026-09-02", log)
        self.assertIn("未读取内容", log)
        self.assertIn("未删除任一项", log)
        self.assertIn("复查结果：dry-run actions=0。", log)

    def test_audit_paths_are_written_in_home_form(self) -> None:
        home = self.fixture.root.parent
        target = self.fixture.file("report.pdf")
        action = make_action(target, "move", destination=self.fixture.pdf_dest("report.pdf"),
                             home=home)
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]], home=home)

        report = self.fixture.apply(plan, home=home)

        self.assertEqual(report.results[0]["status"], "moved")
        self.assertTrue(report.results[0]["source"].startswith("$HOME/"))
        self.assertTrue(report.results[0]["destination"].startswith("$HOME/"))
        self.assertTrue(report.results[0]["manifest"].startswith("$HOME/"))
        text = report.manifest.read_text(encoding="utf-8")
        self.assertNotIn(str(self.fixture.root), text)

    def test_trash_uses_the_backend_and_never_deletes_on_failure(self) -> None:
        target = self.fixture.file("Archive.zip", "zipped")
        action = make_action(target, "trash", tier="duplicate", rule="pair")
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])

        def refuse(path, **kw):
            raise executor.trash_module.TrashError("Finder said no")

        report = self.fixture.apply(plan, trash_fn=refuse)
        self.assertEqual(report.results[0]["status"], "failed")
        self.assertIn("Finder said no", report.results[0]["detail"])
        self.assertTrue(target.exists())

        sent = []

        def accept(path, **kw):
            sent.append((Path(path), kw.get("backend")))
            os.unlink(str(path))

        plan["approved_action_ids"] = [action["id"]]
        report = self.fixture.apply(plan, trash_fn=accept)
        self.assertEqual(report.results[0]["status"], "trashed")
        self.assertEqual(sent[0][1], "finder")
        self.assertFalse(target.exists())

    def test_empty_approval_list_does_nothing_quietly(self) -> None:
        self.fixture.file("report.pdf")
        plan = make_plan(self.fixture.root, [], approved=[])
        report = self.fixture.apply(plan)
        self.assertEqual(report.results, [])
        self.assertFalse(self.fixture.managed.exists())


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    @staticmethod
    def _quiet(argv):
        """Run a subcommand without spilling its report into the test output."""

        from carl_file_organizer import cli

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli.main(argv)
        return code, buffer.getvalue()

    def test_apply_subcommand_keeps_the_approval_file(self) -> None:
        target = self.fixture.file("report.pdf")
        action = make_action(target, "move", destination=self.fixture.pdf_dest("report.pdf"))
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])
        approval = self.fixture.root / "carl-file-organizer-approved.json"
        approval.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

        code, output = self._quiet(["apply", str(approval)])

        self.assertEqual(code, 0)
        self.assertIn("moved", output)
        self.assertTrue(self.fixture.pdf_dest("report.pdf").exists())
        kept = sorted(self.fixture.managed.glob("approved-*.json"))
        self.assertEqual(len(kept), 1)

    def _apply_and_capture(self, plan_hash: str):
        """Run ``apply --dry-run`` on a one-move plan and hand back stderr."""

        from carl_file_organizer import cli

        target = self.fixture.file("report.pdf")
        action = make_action(target, "move", destination=self.fixture.pdf_dest("report.pdf"))
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])
        plan["profile"]["hash"] = plan_hash
        approval = self.fixture.root / "carl-file-organizer-approved.json"
        approval.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["apply", str(approval), "--dry-run"])
        return code, err.getvalue()

    def test_writing_the_settings_file_does_not_look_like_drift(self) -> None:
        # The first plan hashes the settings and then writes the settings file,
        # which records the language: that is not drift and must not warn.
        recorded = self.fixture.config.profile_hash
        config_module.save_dotfile(self.fixture.config, only_if_missing=True)

        code, err = self._apply_and_capture(recorded)

        self.assertEqual(code, 0)
        self.assertNotIn(executor.text("cli_profile_drift", "zh"), err)

    def test_edited_settings_still_warn_before_applying(self) -> None:
        code, err = self._apply_and_capture("0123456789ab")

        self.assertEqual(code, 0)
        self.assertIn(executor.text("cli_profile_drift", "zh"), err)

    def test_apply_dry_run_exits_zero_and_writes_nothing(self) -> None:
        target = self.fixture.file("report.pdf")
        action = make_action(target, "move", destination=self.fixture.pdf_dest("report.pdf"))
        plan = make_plan(self.fixture.root, [action], approved=[action["id"]])
        approval = self.fixture.root / "carl-file-organizer-approved.json"
        approval.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

        code, output = self._quiet(["apply", str(approval), "--dry-run"])

        self.assertEqual(code, 0)
        self.assertIn("dry-run", output)
        self.assertTrue(target.exists())
        self.assertFalse(self.fixture.managed.exists())


class PortableOnlyApprovalTests(unittest.TestCase):
    """The review page exports $HOME paths only; apply has to cope with that.

    ``home`` is the fixture root itself, so ``portable`` actually produces
    ``$HOME/...`` for a temporary folder that does not live under the real home.
    """

    def setUp(self) -> None:
        self.fixture = Fixture(self)
        self.home = self.fixture.root

    def _approval(self, *, kinds=("move",)):
        target = self.fixture.file("report.pdf")
        actions = []
        if "move" in kinds:
            actions.append(
                make_action(
                    target,
                    "move",
                    destination=self.fixture.pdf_dest("report.pdf"),
                    destination_key="library.docs.pdf",
                    home=self.home,
                )
            )
        if "trash" in kinds:
            actions.append(make_action(self.fixture.file("old.dmg"), "trash", home=self.home))
        plan = make_plan(
            self.fixture.root,
            actions,
            approved=[action["id"] for action in actions],
            home=self.home,
        )
        return target, actions, paths.strip_absolute(plan)

    def test_the_exported_shape_really_has_no_absolute_path(self) -> None:
        _target, _actions, approval = self._approval(kinds=("move", "trash"))

        self.assertNotIn("source_root", approval)
        self.assertNotIn("managed_dir", approval)
        self.assertNotIn(str(self.fixture.root), json.dumps(approval, ensure_ascii=False))
        for action in approval["actions"]:
            self.assertNotIn("source", action)
            self.assertNotIn("destination", action)

    def test_validate_accepts_it_and_rebuilds_the_real_paths(self) -> None:
        target, actions, approval = self._approval()

        validated = executor.validate_plan(
            approval, allow_permanent_delete=False, home=self.home
        )

        self.assertEqual(validated.root, paths.realpath(self.fixture.root))
        self.assertEqual(validated.home, self.home)
        self.assertEqual(Path(validated.actions[0]["source"]), target)
        self.assertEqual(
            Path(validated.actions[0]["destination"]), self.fixture.pdf_dest("report.pdf")
        )
        self.assertEqual(validated.actions[0]["id"], actions[0]["id"])

    def test_dry_run_passes_preflight_and_touches_nothing(self) -> None:
        target, actions, approval = self._approval()

        report = self.fixture.apply(approval, dry_run=True, home=self.home)

        self.assertEqual(report.status_of(actions[0]["id"]), "dry-run")
        self.assertEqual(report.counts.get("failed", 0), 0)
        self.assertEqual(report.counts.get("refused", 0), 0)
        self.assertTrue(target.exists())
        self.assertFalse(self.fixture.pdf_dest("report.pdf").exists())

    def test_a_real_apply_moves_the_file_and_audits_in_home_form(self) -> None:
        target, actions, approval = self._approval()

        report = self.fixture.apply(approval, home=self.home)

        self.assertEqual(report.status_of(actions[0]["id"]), "moved")
        self.assertFalse(target.exists())
        self.assertTrue(self.fixture.pdf_dest("report.pdf").exists())
        record = self.fixture.audit_records()[0]
        self.assertEqual(record["source"], "$HOME/report.pdf")
        self.assertEqual(record["destination"], "$HOME/20_知识库/文档资料/PDF/report.pdf")

    def test_a_tampered_destination_is_still_caught(self) -> None:
        _target, _actions, approval = self._approval()
        approval["actions"][0]["destination_portable"] = "$HOME/00_收件箱/report.pdf"

        with self.assertRaises(PlanError):
            executor.validate_plan(approval, allow_permanent_delete=False, home=self.home)


if __name__ == "__main__":
    unittest.main()
