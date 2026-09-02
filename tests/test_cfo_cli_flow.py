"""scan -> report -> apply: the three commands a person actually types.

Everything happens in a temporary folder with the whole-machine scan pointed at
a fake home directory, so the test never reads this machine and never writes
outside its own sandbox.  ``apply`` runs with ``--dry-run`` only; a test that
moves real files is what ``test_cfo_executor`` is for.
"""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from carl_file_organizer import flow
from carl_file_organizer.cli import main

MANAGED_ZH = "00_下载目录管理"


def _run(argv):
    """Run one subcommand and hand back ``(exit code, everything it printed)``."""

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue() + err.getvalue()


class CombinedFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "downloads"
        self.source.mkdir()
        for name in ("quarterly-report.pdf", "screenshot.png", "notes.txt", "thing.weirdext"):
            path = self.source / name
            path.write_text("placeholder\n", encoding="utf-8")
            # a fresh download is still settling and would produce no moves at
            # all, which is a fine plan and a poor test fixture
            old = (datetime.now() - timedelta(days=30)).timestamp()
            os.utime(str(path), (old, old))
        self.fake_home = self.root / "fakehome"
        (self.fake_home / "Library" / "Caches" / "pip").mkdir(parents=True)
        (self.fake_home / "Library" / "Caches" / "pip" / "wheel.bin").write_bytes(b"0" * 4096)
        self.managed = self.source / MANAGED_ZH

    # -- step 1 -------------------------------------------------------------

    def test_scan_writes_both_halves_into_one_managed_directory(self) -> None:
        code, text = _run(
            [
                "scan", str(self.source), "--lang", "zh", "--allow-outside-home",
                "--budget-seconds", "5", "--home", str(self.fake_home),
            ]
        )
        self.assertEqual(code, 0, text)
        self.assertTrue((self.managed / "plan.json").is_file())
        self.assertTrue((self.managed / "storage-scan.json").is_file())
        # scan renders nothing; report is the one thing that writes a page
        self.assertFalse((self.managed / "report.html").exists())
        self.assertIn("plan.json", text)
        self.assertIn("storage-scan.json", text)
        self.assertIn("analysis.json", text)
        scan = json.loads((self.managed / "storage-scan.json").read_text(encoding="utf-8"))
        self.assertIn("disks", scan)

    def test_no_storage_leaves_the_whole_machine_half_out(self) -> None:
        code, text = _run(["scan", str(self.source), "--lang", "zh", "--allow-outside-home", "--no-storage"])
        self.assertEqual(code, 0, text)
        self.assertTrue((self.managed / "plan.json").is_file())
        self.assertFalse((self.managed / "storage-scan.json").exists())

    # -- step 2 -------------------------------------------------------------

    def _scan_and_annotate(self) -> None:
        code, text = _run(["scan", str(self.source), "--lang", "zh", "--allow-outside-home", "--no-storage"])
        self.assertEqual(code, 0, text)
        plan = json.loads((self.managed / "plan.json").read_text(encoding="utf-8"))
        (self.managed / "notes.json").write_text(
            json.dumps(
                {
                    "folder_line": "上周做提案时下载的一堆东西。",
                    "actions": {
                        action["id"]: {
                            "what": "一份提案用到的文件",
                            "why": "扩展名规则命中",
                            "if_removed": "只是搬家，内容不动",
                        }
                        for action in plan["actions"]
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.managed / "analysis.json").write_text(
            json.dumps(
                {
                    "schema": "carl-file-organizer/storage-analysis",
                    "schema_version": 1,
                    "lang": "zh",
                    "created_at": "2026-09-02T12:00:00+09:00",
                    "machine": {"hostname": "test-machine", "os": "macOS"},
                    "disks": [
                        {
                            "name": "Macintosh HD",
                            "mount": "/",
                            "total_bytes": 500 * 1024 ** 3,
                            "used_bytes": 400 * 1024 ** 3,
                            "free_bytes": 100 * 1024 ** 3,
                            "used_percent": 80.0,
                            "primary": True,
                        }
                    ],
                    "overview": {
                        "headline": "系统盘用了八成，先清缓存。",
                        "priority": [{"text": "pip 缓存可以直接清掉。"}],
                        "long_term": ["把老仓库搬到外置盘。"],
                    },
                    "items": [
                        {
                            "id": "st-pip",
                            "name": "pip cache",
                            "path_portable": "$HOME/Library/Caches/pip",
                            "size_bytes": 4096,
                            "kind": "cache",
                            "tier": "regenerable",
                            "color": "green",
                            "disk": "/",
                            "what": "pip 装包时留下的缓存",
                            "why": "删了下次装包重新下载",
                            "if_removed": "第一次装包慢一点",
                            "action": "trash",
                            "trash_paths": ["$HOME/Library/Caches/pip"],
                            "restore": "再装一次包就有了",
                        }
                    ],
                    "top5": [
                        {"id": "st-pip", "name": "pip cache", "size_bytes": 4096, "kind": "cache", "color": "green"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_report_renders_one_combined_page(self) -> None:
        self._scan_and_annotate()
        code, text = _run(["report", str(self.managed)])
        self.assertEqual(code, 0, text)
        page = self.managed / "report.html"
        self.assertTrue(page.is_file())
        html = page.read_text(encoding="utf-8")
        self.assertIn('data-kind="combined"', html)
        self.assertNotIn("/Users/", html)
        # both halves and the after picture
        self.assertIn("上周做提案时下载的一堆东西。", html)
        self.assertIn("pip 装包时留下的缓存", html)
        self.assertIn("pip 缓存可以直接清掉。", html)
        self.assertEqual(html.count('id="cfo-preview"'), 1)
        self.assertIn("carl-file-organizer-decisions.json", html)

    def test_report_takes_an_output_path_and_an_analysis_elsewhere(self) -> None:
        self._scan_and_annotate()
        moved = self.root / "elsewhere.json"
        moved.write_text((self.managed / "analysis.json").read_text(encoding="utf-8"), encoding="utf-8")
        (self.managed / "analysis.json").unlink()
        out = self.root / "combined.html"
        code, text = _run(["report", str(self.managed), "--analysis", str(moved), "-o", str(out)])
        self.assertEqual(code, 0, text)
        self.assertIn('data-kind="combined"', out.read_text(encoding="utf-8"))
        self.assertIn("pip 装包时留下的缓存", out.read_text(encoding="utf-8"))

    def test_report_serve_hands_both_halves_to_one_server(self) -> None:
        self._scan_and_annotate()
        from carl_file_organizer import server as server_module

        seen = {}

        def fake_serve(document, **kw):
            seen["document"] = document
            seen["kw"] = kw
            return 0

        original = server_module.serve_review
        server_module.serve_review = fake_serve
        self.addCleanup(setattr, server_module, "serve_review", original)

        code, text = _run(["report", str(self.managed), "--serve", "--no-open", "--port", "0"])
        self.assertEqual(code, 0, text)
        self.assertIn("plan", seen["document"])
        self.assertIn("analysis", seen["document"])
        self.assertEqual(seen["kw"]["managed_dir"], self.managed)
        self.assertIs(seen["kw"]["open_browser"], False)
        # notes.json in the managed folder is picked up without being named
        self.assertIn("actions", seen["kw"]["notes"])
        # the page is served, never written next to the plan
        self.assertFalse((self.managed / "report.html").exists())

    def test_report_without_either_half_says_so(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        code, text = _run(["report", str(empty)])
        self.assertEqual(code, 2)
        self.assertIn("scan", text)

    # -- step 3 -------------------------------------------------------------

    def _decisions(self) -> Path:
        plan = json.loads((self.managed / "plan.json").read_text(encoding="utf-8"))
        analysis = json.loads((self.managed / "analysis.json").read_text(encoding="utf-8"))
        approvable = [a["id"] for a in plan["actions"] if a["kind"] == "move"][:2]
        target = self.root / "carl-file-organizer-decisions.json"
        target.write_text(
            json.dumps(
                {
                    "schema": flow.DECISIONS_SCHEMA,
                    "schema_version": 1,
                    "decided_at": "2026-09-02T12:00:00+09:00",
                    "decided_by": "html-static",
                    "plan": {"approved_action_ids": approvable, "overrides": [], "document": plan},
                    "storage": {
                        "item_ids": ["st-pip"],
                        "actions": {"st-pip": "trash"},
                        "document": analysis,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return target

    def test_apply_dry_run_walks_both_halves_and_touches_nothing(self) -> None:
        self._scan_and_annotate()
        decisions = self._decisions()
        before = sorted(p.name for p in self.source.iterdir())
        code, text = _run(
            ["apply", str(decisions), "--dry-run", "--lang", "zh", "--managed-dir", str(self.managed)]
        )
        self.assertEqual(code, 0, text)
        # one summary per half, the moves first and the cleanup second
        moves_at = text.index("先搬动这一半")
        cleanup_at = text.index("再清理这一半")
        self.assertLess(moves_at, cleanup_at)
        self.assertIn("dry-run", text)
        self.assertIn("两段合计", text)
        self.assertEqual(sorted(p.name for p in self.source.iterdir()), before)

    def test_an_older_approved_file_still_applies(self) -> None:
        self._scan_and_annotate()
        plan = json.loads((self.managed / "plan.json").read_text(encoding="utf-8"))
        plan["approved_action_ids"] = [a["id"] for a in plan["actions"] if a["kind"] == "move"][:1]
        plan["overrides"] = []
        approved = self.root / "carl-file-organizer-approved.json"
        approved.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        code, text = _run(["apply", str(approved), "--dry-run"])
        self.assertEqual(code, 0, text)
        self.assertIn("dry-run", text)

    def test_a_decisions_file_with_nothing_ticked_does_nothing(self) -> None:
        self._scan_and_annotate()
        empty = self.root / "empty-decisions.json"
        empty.write_text(
            json.dumps(
                {
                    "schema": flow.DECISIONS_SCHEMA,
                    "plan": {"approved_action_ids": [], "overrides": []},
                    "storage": {"item_ids": [], "actions": {}},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        code, text = _run(["apply", str(empty), "--lang", "zh"])
        self.assertEqual(code, 0, text)
        self.assertIn("一项都没勾", text)

    def test_a_missing_analysis_is_refused_before_anything_runs(self) -> None:
        self._scan_and_annotate()
        lonely = self.root / "no-analysis.json"
        lonely.write_text(
            json.dumps(
                {
                    "schema": flow.DECISIONS_SCHEMA,
                    "plan": {"approved_action_ids": [], "overrides": []},
                    "storage": {"item_ids": ["st-pip"], "actions": {"st-pip": "trash"}},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        code, text = _run(["apply", str(lonely), "--lang", "zh"])
        self.assertEqual(code, 2)
        self.assertIn("analysis.json", text)


class ManagedDirectoryTests(unittest.TestCase):
    """The cleanup's paper trail joins the tidy-up half's folder, not a corner of its own."""

    def setUp(self) -> None:
        self.plan = json.loads(
            (Path(cfo_path.FIXTURES_DIR) / "plan-v2-sample.json").read_text(encoding="utf-8")
        )

    def test_an_absolute_managed_dir_is_used_as_written(self) -> None:
        found = flow._managed_of(self.plan)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "00_下载目录管理")

    def test_a_stripped_plan_still_gives_up_its_managed_dir(self) -> None:
        import build_report

        stripped = build_report.sanitize(self.plan)
        self.assertNotIn("managed_dir", stripped)
        found = flow._managed_of(stripped)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "00_下载目录管理")
        self.assertTrue(found.is_absolute())

    def test_a_plan_without_either_field_means_the_old_location(self) -> None:
        self.assertIsNone(flow._managed_of({}))


class CollectTests(unittest.TestCase):
    """``report`` reads the Agent's analysis.json, never the raw scan."""

    def test_a_raw_scan_alone_is_not_enough(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            managed = Path(tmp)
            (managed / "storage-scan.json").write_text('{"disks": []}', encoding="utf-8")
            self.assertEqual(flow.collect(managed), {})

    def test_an_analysis_named_on_the_command_line_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            managed = Path(tmp)
            with self.assertRaises(flow.FlowError):
                flow.collect(managed, managed / "nope.json")


if __name__ == "__main__":
    unittest.main()
