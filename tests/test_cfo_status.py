"""Status: the last run comes from manifests, the mess from a fresh plan."""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import contextlib
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from carl_file_organizer import config as config_module
from carl_file_organizer import manifest, paths, status

NOW = datetime(2026, 9, 2, 11, 0, 0).astimezone()


def _plan(actions):
    return {"schema_version": 2, "actions": actions}


def _action(subject, kind, *, tier="routine", rule="ext:.pdf", key=None, approvable=True):
    return {
        "id": subject + kind,
        "subject_id": subject,
        "kind": kind,
        "tier": tier,
        "rule": rule,
        "destination_key": key,
        "approvable": approvable,
    }


class Fixture:
    def __init__(self, case: unittest.TestCase) -> None:
        temporary = tempfile.TemporaryDirectory()
        case.addCleanup(temporary.cleanup)
        self.root = paths.realpath(Path(temporary.name))
        self.config = config_module.resolve_config(self.root, lang="zh", profile="tiered")
        self.managed = config_module.managed_dir(self.config)
        self.managed.mkdir(parents=True, exist_ok=True)

    def past_run(self, stamp: str, rows: int = 2, series: str = "moves") -> Path:
        path = self.managed / "downloads-{0}-{1}.tsv".format(series, stamp)
        manifest.write_manifest(
            path,
            [
                {
                    "moved_at": stamp.replace("_", "T"),
                    "status": "MOVED",
                    "original_path": "$HOME/Downloads/a{0}.pdf".format(index),
                    "target_path": "$HOME/Downloads/20_知识库/a{0}.pdf".format(index),
                    "size_bytes": 10,
                    "reason": "测试",
                    "restore_method": "mv ...",
                    "kind": "move",
                    "action_id": "id{0}".format(index),
                }
                for index in range(rows)
            ],
        )
        return path


class StatusSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def test_status_reads_only_manifest(self) -> None:
        # A folder full of freshly written files, but no manifest anywhere.
        (self.fixture.root / "brand-new.pdf").write_text("today", encoding="utf-8")
        (self.fixture.managed / "plan.json").write_text("{}", encoding="utf-8")

        report = status.compute_status(
            self.fixture.root, config=self.fixture.config, now=NOW, plan_fn=lambda: _plan([])
        )
        self.assertIsNone(report.last_run)
        self.assertIn("还没整理过", status.format_status(report, "zh"))

        self.fixture.past_run("2026-08-30_15-06-43", rows=2)
        self.fixture.past_run("2026-09-01_03-11-13", rows=3)

        report = status.compute_status(
            self.fixture.root, config=self.fixture.config, now=NOW, plan_fn=lambda: _plan([])
        )
        self.assertIsNotNone(report.last_run)
        self.assertEqual(report.last_run.path.name, "downloads-moves-2026-09-01_03-11-13.tsv")
        self.assertEqual(report.last_run.done, 3)

    def test_status_dirt_counts(self) -> None:
        actions = [
            _action("s1", "move", key="library.docs.pdf"),
            _action("s2", "move", rule="unknown-ext", key="inbox.pending"),
            _action("s3", "move", tier="sensitive", rule="sensitive:marker",
                    key="sensitive.pending"),
            _action("s4", "hold", tier="aging", rule="hold:aging", approvable=False),
            _action("s5", "hold", tier="forbidden", rule="hold:forbidden", approvable=False),
            # A second candidate on the same subject must not be counted twice.
            _action("s2", "trash", rule="cold:large"),
        ]
        report = status.compute_status(
            self.fixture.root,
            config=self.fixture.config,
            now=NOW,
            plan_fn=lambda: _plan(actions),
        )
        self.assertEqual(report.loose, 3)
        self.assertEqual(report.aging, 1)
        self.assertEqual(report.pending, 1)
        self.assertEqual(report.sensitive_pending, 1)
        self.assertEqual(report.recheck_actions, 4)

        line = status.format_status(report, "zh")
        self.assertIn("散件 3", line)
        self.assertIn("静置中 1", line)
        self.assertIn("待判断 1", line)
        self.assertIn("敏感待转移 1", line)

    def test_a_missing_planner_says_so_instead_of_crashing(self) -> None:
        def broken():
            raise RuntimeError("扫描模块还没接上")

        report = status.compute_status(
            self.fixture.root, config=self.fixture.config, now=NOW, plan_fn=broken
        )
        self.assertIsNotNone(report.recheck_error)
        self.assertEqual(report.loose, 0)
        line = status.format_status(report, "zh")
        self.assertIn("无法复查", line)

    def test_a_clean_folder_says_so(self) -> None:
        self.fixture.past_run("2026-09-01_03-11-13", rows=1)
        report = status.compute_status(
            self.fixture.root, config=self.fixture.config, now=NOW, plan_fn=lambda: _plan([])
        )
        line = status.format_status(report, "zh")
        self.assertIn("干净", line)
        self.assertIn("最后整理时间", line)
        self.assertIn("现在是否又脏了", line)

    def test_english_status_has_both_labels(self) -> None:
        report = status.compute_status(
            self.fixture.root, config=self.fixture.config, now=NOW, plan_fn=lambda: _plan([])
        )
        line = status.format_status(report, "en")
        self.assertIn("Last tidy-up", line)
        self.assertIn("Messy again?", line)
        self.assertIn("not tidied yet", line)


class StatusCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture(self)

    def test_the_status_subcommand_runs_without_a_planner_result(self) -> None:
        from carl_file_organizer import cli

        self.fixture.past_run("2026-09-01_03-11-13", rows=1)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli.main(
                ["status", str(self.fixture.root), "--lang", "zh", "--allow-outside-home"]
            )
        self.assertEqual(code, 0)
        self.assertIn("最后整理时间", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
