"""Manifests, tag lists, the audit log and the human review log."""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from carl_file_organizer import manifest


#: The exact header the reference script has been writing since August.
LEGACY_HEADER = (
    "moved_at",
    "status",
    "original_path",
    "target_path",
    "size_bytes",
    "reason",
    "restore_method",
)

STAMP = datetime(2026, 9, 2, 10, 20, 11)


def _row(**kw):
    row = {
        "moved_at": "2026-09-02T10:20:11+09:00",
        "status": "MOVED",
        "original_path": "$HOME/Downloads/report.pdf",
        "target_path": "$HOME/Downloads/20_知识库/文档资料/PDF/report.pdf",
        "size_bytes": 2411008,
        "reason": "文档按类型归档",
        "restore_method": 'mv "$HOME/Downloads/20_知识库/文档资料/PDF/report.pdf" "$HOME/Downloads/"',
        "kind": "move",
        "action_id": "9c1f0a7b2d3e4f55",
    }
    row.update(kw)
    return row


class ManifestColumnTests(unittest.TestCase):
    def test_manifest_columns_prefix_compatible(self) -> None:
        self.assertEqual(manifest.MANIFEST_COLUMNS[:7], LEGACY_HEADER)
        self.assertEqual(manifest.MANIFEST_COLUMNS[7:], ("kind", "action_id"))

    def test_manifest_path_names_match_the_reference_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            managed = Path(temporary)
            path = manifest.manifest_path(managed, "Downloads", "moves", STAMP)
            self.assertEqual(path.name, "downloads-moves-2026-09-02_10-20-11.tsv")
            tags = manifest.tag_list_path(managed, "Downloads", STAMP)
            self.assertEqual(tags.name, "downloads-move-tags-2026-09-02_10-20-11.txt")
            self.assertEqual(manifest.audit_path(managed).name, "audit.jsonl")

    def test_unknown_series_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                manifest.manifest_path(Path(temporary), "Downloads", "whatever", STAMP)

    def test_write_and_read_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "downloads-moves-2026-09-02_10-20-11.tsv"
            manifest.write_manifest(path, [_row(), _row(status="PLANNED")])
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("\t".join(manifest.MANIFEST_COLUMNS)))
            rows = manifest.read_manifest(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["kind"], "move")
            self.assertEqual(rows[1]["status"], "PLANNED")
            self.assertFalse(list(Path(temporary).glob("*.tmp")))

    def test_tabs_and_newlines_cannot_break_a_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = manifest.manifest_path(Path(temporary), "Downloads", "moves", STAMP)
            manifest.write_manifest(path, [_row(reason="a\tb\nc")])
            rows = manifest.read_manifest(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["reason"], "a b c")

    def test_seven_column_manifest_still_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "downloads-moves-2026-08-30_15-06-43.tsv"
            path.write_text(
                "\t".join(LEGACY_HEADER)
                + "\n"
                + "\t".join(
                    [
                        "2026-08-30T15:06:43+09:00",
                        "MOVED",
                        "$HOME/Downloads/api-credential.txt",
                        "$HOME/Downloads/60_敏感信息/待转移/api-credential.txt",
                        "98",
                        "敏感命名文件直接移入待转移，不读取内容",
                        'mv "$HOME/Downloads/60_敏感信息/待转移/api-credential.txt" "$HOME/Downloads/"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            rows = manifest.read_manifest(path)
            self.assertEqual(rows[0]["status"], "MOVED")
            self.assertEqual(rows[0].get("kind", ""), "")


class TagListTests(unittest.TestCase):
    def test_tag_list_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = manifest.tag_list_path(Path(temporary), "Downloads", STAMP)
            manifest.write_tag_list(path, ["$HOME/Downloads/a.txt", "$HOME/Downloads/b.txt"])
            self.assertEqual(
                manifest.read_tag_list(path),
                ["$HOME/Downloads/a.txt", "$HOME/Downloads/b.txt"],
            )

    def test_missing_tag_list_reads_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(manifest.read_tag_list(Path(temporary) / "nope.txt"), [])


class AuditTests(unittest.TestCase):
    def test_append_audit_is_one_json_object_per_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = manifest.audit_path(Path(temporary))
            manifest.append_audit([{"action_id": "a", "status": "moved"}], path)
            manifest.append_audit([{"action_id": "b", "status": "skipped"}], path)
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[1])["action_id"], "b")
            records = manifest.read_audit(path)
            self.assertEqual([item["status"] for item in records], ["moved", "skipped"])

    def test_a_broken_line_does_not_stop_the_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = manifest.audit_path(Path(temporary))
            path.write_text('{"status": "moved"}\nnot json\n\n', encoding="utf-8")
            self.assertEqual(len(manifest.read_audit(path)), 1)


class ReviewLogTests(unittest.TestCase):
    def test_review_log_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            managed = Path(temporary)
            first = manifest.append_review_log(
                managed, "zh", date(2026, 9, 2), ["移动了 3 项。"]
            )
            self.assertEqual(first.name, "人工调整日志.md")
            text = first.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# 人工调整日志"))
            self.assertIn("## 2026-09-02", text)
            self.assertIn("- 移动了 3 项。", text)

            manifest.append_review_log(
                managed, "zh", date(2026, 9, 2), ["复查结果：dry-run actions=0。"]
            )
            text = first.read_text(encoding="utf-8")
            self.assertEqual(text.count("## 2026-09-02"), 1)
            self.assertIn("- 复查结果：dry-run actions=0。", text)
            self.assertLess(
                text.index("- 移动了 3 项。"), text.index("- 复查结果：dry-run actions=0。")
            )

            manifest.append_review_log(managed, "zh", date(2026, 9, 3), ["第二天。"])
            text = first.read_text(encoding="utf-8")
            self.assertIn("## 2026-09-03", text)
            self.assertLess(text.index("## 2026-09-02"), text.index("## 2026-09-03"))
            # A later day must not swallow the earlier day's bullets.
            self.assertLess(text.index("- 复查结果"), text.index("## 2026-09-03"))

    def test_english_log_has_its_own_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = manifest.append_review_log(
                Path(temporary), "en", date(2026, 9, 2), ["Moved 3 items."]
            )
            self.assertEqual(path.name, "review-log.md")
            self.assertIn("# Review log", path.read_text(encoding="utf-8"))

    def test_no_bullets_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = manifest.append_review_log(Path(temporary), "zh", date(2026, 9, 2), [])
            self.assertFalse(path.exists())


class LatestRunTests(unittest.TestCase):
    def _manifest(self, managed: Path, series: str, stamp: str, rows=1, status="MOVED"):
        path = managed / "downloads-{0}-{1}.tsv".format(series, stamp)
        manifest.write_manifest(
            path,
            [
                _row(status=status, moved_at="{0}+09:00".format(stamp.replace("_", "T")))
                for _ in range(rows)
            ],
        )
        return path

    def test_status_reads_only_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            managed = Path(temporary) / "00_下载目录管理"
            managed.mkdir()
            # A very fresh folder with no manifest means nobody ever tidied it.
            (managed / "plan.json").write_text("{}", encoding="utf-8")
            (managed / "notes.md").write_text("hello", encoding="utf-8")
            self.assertIsNone(manifest.latest_run(managed))

            self._manifest(managed, "moves", "2026-08-30_15-06-43", rows=2)
            self._manifest(managed, "moves", "2026-09-01_03-11-13", rows=3)
            self._manifest(managed, "undo", "2026-09-02_04-00-00", rows=9)

            latest = manifest.latest_run(managed)
            self.assertIsNotNone(latest)
            self.assertEqual(latest.path.name, "downloads-moves-2026-09-01_03-11-13.tsv")
            self.assertEqual(latest.series, "moves")
            self.assertEqual(latest.rows, 3)
            self.assertEqual(latest.done, 3)

    def test_conflict_moves_is_its_own_series(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            managed = Path(temporary)
            self._manifest(managed, "conflict-moves", "2026-09-01_03-12-04")
            latest = manifest.latest_run(managed)
            self.assertEqual(latest.series, "conflict-moves")

    def test_missing_folder_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(manifest.latest_run(Path(temporary) / "nope"))
            self.assertEqual(manifest.list_runs(Path(temporary) / "nope"), [])


if __name__ == "__main__":
    unittest.main()
