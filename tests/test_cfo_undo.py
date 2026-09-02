"""Undo: reverse order, from either record format, and timid about surprises."""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from carl_file_organizer import config as config_module
from carl_file_organizer import manifest, paths, undo

NOW = datetime(2026, 9, 2, 11, 0, 0).astimezone()
MOVED_AT = "2026-09-02T10:20:11+09:00"


class Fixture:
    """A folder that already had a run: files moved, records written."""

    def __init__(self, case: unittest.TestCase) -> None:
        temporary = tempfile.TemporaryDirectory()
        case.addCleanup(temporary.cleanup)
        self.root = paths.realpath(Path(temporary.name))
        self.home = self.root.parent
        self.config = config_module.resolve_config(self.root, lang="zh", profile="tiered")
        self.managed = config_module.managed_dir(self.config)
        self.managed.mkdir(parents=True, exist_ok=True)

    def moved(self, name: str, relative: str, content: str = "hello") -> Path:
        """Put a file where a past run would have left it, and return that path."""

        destination = self.root / relative / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return destination

    def portable(self, path: Path) -> str:
        # Records store absolute paths here: the temporary folder is not under
        # the real home, so the $HOME form would not round trip.
        return paths.portable(path)

    def audit_record(self, name: str, relative: str, *, status="moved", kind="move", size=5):
        return {
            "timestamp": MOVED_AT,
            "run_id": "2026-09-02_10-20-11",
            "action_id": "id-" + name,
            "subject_id": "subject-" + name,
            "kind": kind,
            "source": self.portable(self.root / name),
            "destination": self.portable(self.root / relative / name) if relative else None,
            "status": status,
            "detail": "",
            "size_bytes": size,
            "manifest": "",
            "tagged": True,
            "trash_backend": "finder",
        }

    def manifest_row(self, name: str, relative: str, *, status="MOVED", kind="move", size=5):
        return {
            "moved_at": MOVED_AT,
            "status": status,
            "original_path": self.portable(self.root / name),
            "target_path": self.portable(self.root / relative / name),
            "size_bytes": size,
            "reason": "测试",
            "restore_method": "mv ...",
            "kind": kind,
            "action_id": "id-" + name,
        }


class LoadRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def test_audit_and_manifest_load_into_the_same_shape(self) -> None:
        audit = manifest.audit_path(self.fixture.managed)
        manifest.append_audit([self.fixture.audit_record("a.pdf", "20_知识库")], audit)
        records = undo.load_records(audit)
        self.assertEqual(records[0]["kind"], "move")
        self.assertEqual(records[0]["status"], "moved")

        tsv = manifest.manifest_path(self.fixture.managed, "Downloads", "moves", NOW)
        manifest.write_manifest(tsv, [self.fixture.manifest_row("a.pdf", "20_知识库")])
        rows = undo.load_records(tsv)
        self.assertEqual(rows[0]["kind"], "move")
        self.assertEqual(rows[0]["status"], "MOVED")
        self.assertEqual(rows[0]["source"], records[0]["source"])
        self.assertEqual(rows[0]["destination"], records[0]["destination"])

    def test_another_suffix_is_refused(self) -> None:
        other = self.fixture.managed / "notes.md"
        other.write_text("hi", encoding="utf-8")
        with self.assertRaises(ValueError):
            undo.load_records(other)


class PlanUndoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def test_reverse_order_and_only_completed_moves(self) -> None:
        records = [
            self.fixture.audit_record("a.pdf", "20_知识库"),
            self.fixture.audit_record("b.zip", "", status="trashed", kind="trash"),
            self.fixture.audit_record("c.log", "00_收件箱", status="skipped"),
            self.fixture.audit_record("d.pdf", "20_知识库"),
        ]
        steps = undo.plan_undo(records, root=self.fixture.root, home=None, lang="zh")

        self.assertEqual(len(steps), 4)
        self.assertEqual([step.ok for step in steps], [True, False, False, True])
        self.assertEqual(steps[0].original.name, "d.pdf")
        self.assertEqual(steps[3].original.name, "a.pdf")
        self.assertIn("废纸篓", steps[2].detail)

    def test_a_permanent_delete_says_so_plainly(self) -> None:
        records = [self.fixture.audit_record("node_modules", "", status="deleted", kind="delete")]
        steps = undo.plan_undo(records, root=self.fixture.root, home=None, lang="zh")
        self.assertFalse(steps[0].ok)
        self.assertIn("永久删除", steps[0].detail)


class RunUndoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def _run(self, records, **kw):
        steps = undo.plan_undo(
            records, root=self.fixture.root, home=None, lang="zh"
        )
        options = {
            "root": self.fixture.root,
            "home": self.fixture.home,
            "config": self.fixture.config,
            "lang": "zh",
            "managed": self.fixture.managed,
            "now": NOW,
        }
        options.update(kw)
        return undo.run_undo(steps, **options)

    def test_undo_from_audit_moves_things_back(self) -> None:
        moved = self.fixture.moved("report.pdf", "20_知识库/文档资料/PDF")
        records = [self.fixture.audit_record("report.pdf", "20_知识库/文档资料/PDF")]

        report = self._run(records)

        self.assertEqual(report.results[0]["status"], "moved")
        self.assertTrue((self.fixture.root / "report.pdf").exists())
        self.assertFalse(moved.exists())

    def test_undo_from_manifest_moves_things_back(self) -> None:
        moved = self.fixture.moved("report.pdf", "20_知识库/文档资料/PDF")
        tsv = manifest.manifest_path(self.fixture.managed, "Downloads", "moves", NOW)
        manifest.write_manifest(
            tsv, [self.fixture.manifest_row("report.pdf", "20_知识库/文档资料/PDF")]
        )

        report = self._run(undo.load_records(tsv))

        self.assertEqual(report.results[0]["status"], "moved")
        self.assertTrue((self.fixture.root / "report.pdf").exists())
        self.assertFalse(moved.exists())

    def test_occupied_original_path_is_skipped(self) -> None:
        moved = self.fixture.moved("report.pdf", "20_知识库", content="the moved one")
        (self.fixture.root / "report.pdf").write_text("a new download", encoding="utf-8")
        records = [self.fixture.audit_record("report.pdf", "20_知识库")]

        report = self._run(records)

        self.assertEqual(report.results[0]["status"], "skipped")
        self.assertIn("不覆盖", report.results[0]["detail"])
        self.assertEqual(moved.read_text(encoding="utf-8"), "the moved one")
        self.assertEqual(
            (self.fixture.root / "report.pdf").read_text(encoding="utf-8"), "a new download"
        )

    def test_missing_current_path_is_skipped(self) -> None:
        records = [self.fixture.audit_record("report.pdf", "20_知识库")]
        report = self._run(records)
        self.assertEqual(report.results[0]["status"], "skipped")

    def test_dry_run_touches_nothing(self) -> None:
        moved = self.fixture.moved("report.pdf", "20_知识库")
        records = [self.fixture.audit_record("report.pdf", "20_知识库")]

        report = self._run(records, dry_run=True)

        self.assertEqual(report.results[0]["status"], "dry-run")
        self.assertTrue(moved.exists())
        self.assertFalse((self.fixture.root / "report.pdf").exists())
        self.assertIsNone(report.manifest)
        self.assertEqual(list(self.fixture.managed.glob("*-undo-*.tsv")), [])

    def test_undo_writes_its_own_manifest_audit_and_log(self) -> None:
        self.fixture.moved("report.pdf", "20_知识库")
        records = [self.fixture.audit_record("report.pdf", "20_知识库")]

        report = self._run(records)

        self.assertIsNotNone(report.manifest)
        self.assertIn("-undo-2026-09-02_11-00-00.tsv", report.manifest.name)
        rows = manifest.read_manifest(report.manifest)
        self.assertEqual(rows[0]["status"], "RESTORED")
        self.assertTrue(rows[0]["original_path"].startswith("$HOME/"))

        records_back = manifest.read_audit(manifest.audit_path(self.fixture.managed))
        self.assertEqual(records_back[-1]["status"], "moved")
        self.assertTrue(records_back[-1]["undo"])

        log = report.review_log.read_text(encoding="utf-8")
        self.assertIn("## 2026-09-02", log)
        self.assertIn("撤销了 1 项移动", log)

    def test_a_path_outside_the_folder_is_refused(self) -> None:
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(outside), True)
        stray = outside / "report.pdf"
        stray.write_text("elsewhere", encoding="utf-8")
        record = self.fixture.audit_record("report.pdf", "20_知识库")
        record["destination"] = str(stray)

        report = self._run([record])

        self.assertEqual(report.results[0]["status"], "refused")
        self.assertTrue(stray.exists())


class HomeFormRecordTests(unittest.TestCase):
    """Audit records have always been written in ``$HOME`` form; this pins it.

    The rest of the file uses a temporary folder that is not under the real home,
    so ``portable`` leaves absolute paths alone there.  Here ``home`` is the
    folder itself, which is the only way to get real ``$HOME/...`` records out of
    a temporary directory, and undo has to expand them again to move anything.
    """

    def setUp(self) -> None:
        self.fixture = Fixture(self)
        self.home = self.fixture.root

    def _record(self, name: str, relative: str) -> dict:
        record = self.fixture.audit_record(name, relative)
        record["source"] = paths.portable(self.fixture.root / name, self.home)
        record["destination"] = paths.portable(self.fixture.root / relative / name, self.home)
        return record

    def test_records_round_trip_through_home_form(self) -> None:
        moved = self.fixture.moved("report.pdf", "20_知识库/文档资料/PDF")
        audit = manifest.audit_path(self.fixture.managed)
        record = self._record("report.pdf", "20_知识库/文档资料/PDF")
        self.assertEqual(record["source"], "$HOME/report.pdf")
        self.assertEqual(record["destination"], "$HOME/20_知识库/文档资料/PDF/report.pdf")
        manifest.append_audit([record], audit)

        records = undo.load_records(audit)
        self.assertEqual(records[0]["source"], "$HOME/report.pdf")

        steps = undo.plan_undo(records, root=self.fixture.root, home=self.home, lang="zh")
        self.assertEqual(steps[0].original, self.fixture.root / "report.pdf")
        self.assertEqual(steps[0].current, moved)

        report = undo.run_undo(
            steps,
            root=self.fixture.root,
            home=self.home,
            config=self.fixture.config,
            lang="zh",
            managed=self.fixture.managed,
            now=NOW,
        )

        self.assertEqual(report.results[0]["status"], "moved")
        self.assertTrue((self.fixture.root / "report.pdf").exists())
        self.assertFalse(moved.exists())
        self.assertEqual(report.results[0]["destination"], "$HOME/report.pdf")


class InferRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def test_root_comes_from_the_managed_folder(self) -> None:
        self.fixture.moved("report.pdf", "20_知识库")
        audit = manifest.audit_path(self.fixture.managed)
        manifest.append_audit([self.fixture.audit_record("report.pdf", "20_知识库")], audit)
        steps = undo.plan_undo(undo.load_records(audit), root=Path("/"), home=None)
        # The records use $HOME form, so the inferred root is the managed parent.
        self.assertEqual(undo.infer_root(audit, steps), self.fixture.root)


if __name__ == "__main__":
    unittest.main()
