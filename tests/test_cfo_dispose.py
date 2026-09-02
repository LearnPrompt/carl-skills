"""The gate in front of the whole-machine disposals.

Every test here builds a fake home directory and a small analysis.json over it,
because the rules this module enforces are all about the relationship between a
path, the home directory and the colour the Agent gave it.  Nothing touches the
real machine: the trash backend is always a stub, and ``lsof`` is never called.
"""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from carl_file_organizer import dispose as dispose_module
from carl_file_organizer import trash as trash_module

TZ = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=TZ)

GREEN = "green"
YELLOW = "yellow"
RED = "red"


class Handles(object):
    """What ``guard.open_handles`` hands back, without asking the machine."""

    def __init__(self, handles=(), status="ok"):
        self.handles = list(handles)
        self.status = status


def free(_path):
    return Handles()


def unknown(_path):
    return Handles(status="unknown")


class Trashcan(object):
    """A trash backend that really moves things, so "gone" means gone."""

    def __init__(self, root, fail=False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.fail = fail
        self.calls = []
        self.before = []

    def __call__(self, path, *, backend=None, lang="en", **kw):
        self.calls.append(Path(path))
        self.before.append(self.snapshot())
        if self.fail:
            raise trash_module.TrashError("the trash refused this one")
        target = self.root / Path(path).name
        os.rename(str(path), str(target))

    def snapshot(self):
        return None


def item(item_id, color, portable, trash_paths, **extra):
    entry = {
        "id": item_id,
        "color": color,
        "name": item_id,
        "path_portable": portable,
        "size_bytes": 4096,
        "what": "a thing",
        "trash_paths": list(trash_paths),
    }
    entry.update(extra)
    return entry


def decisions_for(pairs):
    return {
        "schema": dispose_module.SCHEMA,
        "schema_version": 1,
        "item_ids": [i for i, _a in pairs],
        "actions": {i: a for i, a in pairs},
    }


class DisposeCase(unittest.TestCase):
    """A fake home with one green cache, one yellow download, one red library."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.trashcan = Trashcan(Path(self.tmp.name) / "trash")
        self.managed = self.home / ".carl-file-organizer" / "storage"

        self.green_path = self.make_dir("Library/Caches/pip")
        self.green_2 = self.make_dir("Library/Caches/uv")
        self.yellow_path = self.make_file("Downloads/Toolbox.dmg")
        self.red_path = self.make_dir("Pictures/Snapshots.photoslibrary")

        self.analysis = {
            "schema": "carl-file-organizer/storage-analysis",
            "lang": "en",
            "items": [
                item("green-pip", GREEN, "$HOME/Library/Caches/pip", ["$HOME/Library/Caches/pip"]),
                item("green-uv", GREEN, "$HOME/Library/Caches/uv", ["$HOME/Library/Caches/uv"]),
                item("yellow-dmg", YELLOW, "$HOME/Downloads", ["$HOME/Downloads/Toolbox.dmg"]),
                item("red-photos", RED, "$HOME/Pictures/Snapshots.photoslibrary", []),
            ],
        }

    # -- fixture helpers ----------------------------------------------------

    def make_dir(self, relative, content="body\n"):
        target = self.home / relative
        target.mkdir(parents=True, exist_ok=True)
        (target / "one.bin").write_text(content, encoding="utf-8")
        return target

    def make_file(self, relative, content="body\n"):
        target = self.home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def add(self, entry):
        self.analysis["items"].append(entry)

    def apply(self, pairs, *, dry_run=False, allow_permanent_delete=False, trash_fn=None, handles=free):
        return dispose_module.apply_decisions(
            self.analysis,
            decisions_for(pairs),
            dry_run=dry_run,
            allow_permanent_delete=allow_permanent_delete,
            home=self.home,
            managed_dir=self.managed,
            now=NOW,
            trash_backend=trash_module.GIO,
            trash_fn=trash_fn or self.trashcan,
            open_handles_fn=handles,
        )

    def status_of(self, report, item_id):
        return [r["status"] for r in report.results if r["item_id"] == item_id]

    def detail_of(self, report, item_id):
        return " ".join(r["detail"] for r in report.results if r["item_id"] == item_id)

    def manifests(self):
        return sorted(self.managed.glob("storage-removals-*.tsv"))


# --------------------------------------------------------------------------
# colour is the gate
# --------------------------------------------------------------------------


class ColourGateTests(DisposeCase):
    def test_a_red_item_is_refused_whatever_is_asked_for(self):
        self.add(item("red-loaded", RED, "$HOME/Library/Caches/pip", ["$HOME/Library/Caches/pip"]))
        for action in ("trash", "delete"):
            report = self.apply([("red-loaded", action)], allow_permanent_delete=True)
            self.assertEqual(self.status_of(report, "red-loaded"), ["refused"])
            self.assertTrue(self.green_path.is_dir())
            self.assertEqual(self.trashcan.calls, [])

    def test_a_yellow_item_may_be_trashed_but_never_deleted(self):
        report = self.apply([("yellow-dmg", "delete")], allow_permanent_delete=True)
        self.assertEqual(self.status_of(report, "yellow-dmg"), ["refused"])
        self.assertIn("trash", self.detail_of(report, "yellow-dmg"))
        self.assertTrue(self.yellow_path.is_file())

        report = self.apply([("yellow-dmg", "trash")])
        self.assertEqual(self.status_of(report, "yellow-dmg"), ["trashed"])
        self.assertFalse(self.yellow_path.exists())

    def test_a_green_delete_without_the_flag_is_refused_and_the_files_stay(self):
        report = self.apply([("green-pip", "delete")])
        self.assertEqual(self.status_of(report, "green-pip"), ["refused"])
        self.assertIn("allow-permanent-delete", self.detail_of(report, "green-pip"))
        self.assertTrue(self.green_path.is_dir())
        self.assertTrue((self.green_path / "one.bin").is_file())

    def test_a_green_delete_with_the_flag_really_deletes(self):
        report = self.apply([("green-pip", "delete")], allow_permanent_delete=True)
        self.assertEqual(self.status_of(report, "green-pip"), ["deleted"])
        self.assertFalse(self.green_path.exists())
        self.assertEqual(self.trashcan.calls, [])

    def test_an_unknown_id_and_an_unknown_action_are_refused_not_guessed(self):
        report = self.apply([("no-such-item", "trash")])
        self.assertEqual(self.status_of(report, "no-such-item"), ["refused"])
        report = self.apply([("green-pip", "shred")])
        self.assertEqual(self.status_of(report, "green-pip"), ["refused"])
        self.assertTrue(self.green_path.is_dir())

    def test_a_system_note_takes_no_action(self):
        self.add(
            item(
                "note-winsxs",
                GREEN,
                "$HOME/Library/Caches/pip",
                ["$HOME/Library/Caches/pip"],
                scanned=False,
                size_bytes=None,
            )
        )
        report = self.apply([("note-winsxs", "trash")])
        self.assertEqual(self.status_of(report, "note-winsxs"), ["refused"])
        self.assertTrue(self.green_path.is_dir())

    def test_an_item_with_no_whitelisted_path_has_nothing_to_act_on(self):
        self.add(item("green-empty", GREEN, "$HOME/Library/Caches/pip", []))
        report = self.apply([("green-empty", "trash")])
        self.assertEqual(self.status_of(report, "green-empty"), ["refused"])
        self.assertEqual(self.trashcan.calls, [])


# --------------------------------------------------------------------------
# the path rules
# --------------------------------------------------------------------------


class PathRuleTests(DisposeCase):
    def test_a_path_outside_the_home_directory_is_refused(self):
        outside = Path(self.tmp.name) / "elsewhere"
        outside.mkdir()
        (outside / "one.bin").write_text("body\n", encoding="utf-8")
        self.add(item("green-outside", GREEN, str(outside), [str(outside)]))
        report = self.apply([("green-outside", "trash")])
        self.assertEqual(self.status_of(report, "green-outside"), ["refused"])
        self.assertTrue((outside / "one.bin").is_file())
        self.assertEqual(self.trashcan.calls, [])

    def test_a_path_that_climbs_back_out_is_refused(self):
        outside = Path(self.tmp.name) / "elsewhere"
        outside.mkdir()
        self.add(item("green-climb", GREEN, "$HOME/x", ["$HOME/../elsewhere"]))
        report = self.apply([("green-climb", "trash")])
        self.assertEqual(self.status_of(report, "green-climb"), ["refused"])
        self.assertTrue(outside.is_dir())

    @unittest.skipUnless(
        sys.platform != "win32",
        "creating a symlink on Windows needs administrator rights",
    )
    def test_a_symlink_segment_is_refused(self):
        real = self.make_dir("Library/Caches/real-cache")
        link = self.home / "Library" / "Caches" / "linked"
        link.symlink_to(real, target_is_directory=True)
        self.add(item("green-link", GREEN, "$HOME/Library/Caches/linked", ["$HOME/Library/Caches/linked"]))
        report = self.apply([("green-link", "trash")])
        self.assertEqual(self.status_of(report, "green-link"), ["refused"])
        self.assertIn("symlink", self.detail_of(report, "green-link"))
        self.assertTrue(real.is_dir())
        self.assertTrue(link.is_symlink())

    def test_a_no_go_basename_is_refused_even_when_the_agent_called_it_green(self):
        self.make_dir("projects/site/.git")
        self.add(item("green-git", GREEN, "$HOME/projects/site/.git", ["$HOME/projects/site/.git"]))
        report = self.apply([("green-git", "trash")])
        self.assertEqual(self.status_of(report, "green-git"), ["refused"])
        self.assertIn("forbidden", self.detail_of(report, "green-git"))
        self.assertTrue((self.home / "projects" / "site" / ".git").is_dir())

    def test_a_no_go_suffix_is_refused(self):
        self.add(
            item(
                "green-photos",
                GREEN,
                "$HOME/Pictures/Snapshots.photoslibrary",
                ["$HOME/Pictures/Snapshots.photoslibrary"],
            )
        )
        report = self.apply([("green-photos", "trash")])
        self.assertEqual(self.status_of(report, "green-photos"), ["refused"])
        self.assertTrue(self.red_path.is_dir())

    def test_the_home_directory_and_its_children_are_too_coarse(self):
        for portable in ("$HOME", "$HOME/Downloads", "$HOME/Library"):
            self.add(item("green-coarse", GREEN, portable, [portable]))
            report = self.apply([("green-coarse", "trash")])
            self.assertEqual(self.status_of(report, "green-coarse"), ["refused"], portable)
            self.assertIn("children", self.detail_of(report, "green-coarse"))
            self.analysis["items"].pop()
        self.assertTrue(self.yellow_path.is_file())
        self.assertTrue(self.green_path.is_dir())

    def test_one_bad_path_condemns_the_whole_item(self):
        self.add(
            item(
                "green-mixed",
                GREEN,
                "$HOME/Library/Caches",
                ["$HOME/Library/Caches/pip", "$HOME/Library"],
            )
        )
        report = self.apply([("green-mixed", "trash")])
        self.assertEqual(self.status_of(report, "green-mixed"), ["refused"])
        self.assertTrue(self.green_path.is_dir())
        self.assertEqual(self.trashcan.calls, [])

    def test_the_same_path_twice_in_one_batch_is_only_acted_on_once(self):
        self.add(item("green-again", GREEN, "$HOME/Library/Caches/pip", ["$HOME/Library/Caches/pip"]))
        report = self.apply([("green-pip", "trash"), ("green-again", "trash")])
        self.assertEqual(self.status_of(report, "green-pip"), ["trashed"])
        self.assertEqual(self.status_of(report, "green-again"), ["skipped"])
        self.assertEqual(len(self.trashcan.calls), 1)

    def test_a_path_that_is_already_gone_is_skipped_not_failed(self):
        self.add(item("green-gone", GREEN, "$HOME/Library/Caches/vanished", ["$HOME/Library/Caches/vanished"]))
        report = self.apply([("green-gone", "trash")])
        self.assertEqual(self.status_of(report, "green-gone"), ["skipped"])
        self.assertEqual(self.trashcan.calls, [])


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------


class PreflightTests(DisposeCase):
    def test_an_open_file_is_refused(self):
        def busy(_path):
            return Handles([{"command": "Cursor", "pid": 4242}])

        report = self.apply([("green-pip", "trash")], handles=busy)
        self.assertEqual(self.status_of(report, "green-pip"), ["refused"])
        self.assertIn("Cursor", self.detail_of(report, "green-pip"))
        self.assertTrue(self.green_path.is_dir())

    def test_an_unknown_answer_lets_it_through_but_is_written_down(self):
        report = self.apply([("green-pip", "trash")], handles=unknown)
        self.assertEqual(self.status_of(report, "green-pip"), ["trashed"])
        record = [r for r in report.results if r["item_id"] == "green-pip"][0]
        self.assertEqual(record["open_check"], "unknown")
        audit = json.loads((self.managed / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(audit["open_check"], "unknown")


# --------------------------------------------------------------------------
# the paper trail
# --------------------------------------------------------------------------


class PaperTrailTests(DisposeCase):
    def test_the_manifest_is_on_disk_before_the_first_path_is_touched(self):
        seen = {}

        def watcher(path, *, backend=None, lang="en", **kw):
            files = self.manifests()
            seen["files"] = list(files)
            seen["rows"] = dispose_module.read_manifest(files[0]) if files else []
            return self.trashcan(path, backend=backend, lang=lang)

        report = self.apply([("green-pip", "trash")], trash_fn=watcher)
        self.assertEqual(self.status_of(report, "green-pip"), ["trashed"])
        self.assertEqual(len(seen["files"]), 1)
        self.assertEqual([r["status"] for r in seen["rows"]], ["PLANNED"])
        self.assertEqual(seen["rows"][0]["path"], "$HOME/Library/Caches/pip")
        self.assertTrue(int(seen["rows"][0]["size_kib_before"]) >= 1)

        final = dispose_module.read_manifest(self.manifests()[0])
        self.assertEqual([r["status"] for r in final], ["TRASHED"])
        self.assertEqual(final[0]["error"], "")
        self.assertIn("Trash", final[0]["restore_method"])

    def test_the_manifest_columns_are_the_storage_seven(self):
        self.apply([("green-pip", "trash")])
        header = self.manifests()[0].read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(header.split("\t"), list(dispose_module.MANIFEST_COLUMNS))

    def test_each_path_gets_its_own_audit_line_naming_no_account(self):
        self.apply([("green-pip", "trash"), ("yellow-dmg", "trash")])
        lines = (self.managed / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        records = [json.loads(line) for line in lines]
        self.assertEqual([r["item_id"] for r in records], ["green-pip", "yellow-dmg"])
        self.assertEqual([r["status"] for r in records], ["trashed", "trashed"])
        for record in records:
            self.assertEqual(record["line"], "storage")
            self.assertEqual(record["kind"], "trash")
            self.assertTrue(record["source"].startswith("$HOME/"))
            self.assertNotIn(str(self.home), json.dumps(record))

    def test_a_dry_run_writes_nothing_and_moves_nothing(self):
        report = self.apply([("green-pip", "trash"), ("yellow-dmg", "trash")], dry_run=True)
        self.assertEqual([r["status"] for r in report.results], ["dry-run", "dry-run"])
        self.assertIsNone(report.manifest)
        self.assertIsNone(report.audit)
        self.assertFalse(self.managed.exists())
        self.assertEqual(self.trashcan.calls, [])
        self.assertTrue(self.green_path.is_dir())
        self.assertTrue(self.yellow_path.is_file())

    def test_a_refusal_still_reaches_the_manifest_with_its_sentence(self):
        report = self.apply([("red-photos", "trash"), ("green-pip", "trash")])
        rows = dispose_module.read_manifest(self.manifests()[0])
        self.assertEqual([r["status"] for r in rows], ["REFUSED", "TRASHED"])
        self.assertTrue(rows[0]["error"])
        self.assertEqual(rows[1]["error"], "")
        self.assertEqual(report.counts["total"], 2)


# --------------------------------------------------------------------------
# what happens when the trash says no
# --------------------------------------------------------------------------


class TrashFailureTests(DisposeCase):
    def test_a_failed_trash_never_becomes_a_permanent_delete(self):
        failing = Trashcan(Path(self.tmp.name) / "trash", fail=True)
        report = self.apply([("green-pip", "trash")], trash_fn=failing, allow_permanent_delete=True)
        self.assertEqual(self.status_of(report, "green-pip"), ["failed"])
        self.assertTrue(self.green_path.is_dir())
        self.assertTrue((self.green_path / "one.bin").is_file())
        rows = dispose_module.read_manifest(self.manifests()[0])
        self.assertEqual(rows[0]["status"], "FAILED")
        self.assertIn("refused this one", rows[0]["error"])

    def test_the_first_failure_stops_the_rest_of_the_batch(self):
        failing = Trashcan(Path(self.tmp.name) / "trash", fail=True)
        report = self.apply(
            [("green-pip", "trash"), ("green-uv", "trash"), ("yellow-dmg", "trash")],
            trash_fn=failing,
        )
        self.assertEqual(
            [r["status"] for r in report.results], ["failed", "skipped", "skipped"]
        )
        self.assertTrue(report.stopped)
        self.assertEqual(len(failing.calls), 1)
        self.assertTrue(self.green_2.is_dir())
        self.assertTrue(self.yellow_path.is_file())

    def test_no_trash_backend_means_no_disposal_at_all(self):
        report = dispose_module.apply_decisions(
            self.analysis,
            decisions_for([("green-pip", "trash")]),
            home=self.home,
            managed_dir=self.managed,
            now=NOW,
            trash_backend=trash_module.NONE,
            open_handles_fn=free,
        )
        self.assertEqual(self.status_of(report, "green-pip"), ["refused"])
        self.assertTrue(self.green_path.is_dir())


# --------------------------------------------------------------------------
# the shape of the API
# --------------------------------------------------------------------------


class ContractTests(DisposeCase):
    def test_validate_returns_rows_without_touching_anything(self):
        validated = dispose_module.validate_decisions(
            self.analysis,
            decisions_for([("green-pip", "trash"), ("red-photos", "trash")]),
            home=self.home,
            trash_backend=trash_module.GIO,
        )
        self.assertEqual([r.status for r in validated.rows], ["planned", "refused"])
        self.assertEqual(len(validated.targets), 1)
        self.assertEqual(validated.targets[0].path, self.green_path)
        self.assertTrue(self.green_path.is_dir())

    def test_a_decisions_file_that_is_not_one_is_refused_outright(self):
        for bad in (
            {"schema": "something/else", "item_ids": ["green-pip"], "actions": {}},
            {"schema": dispose_module.SCHEMA, "item_ids": "green-pip", "actions": {}},
            {"schema": dispose_module.SCHEMA, "item_ids": [], "actions": {}},
            {"schema": dispose_module.SCHEMA, "item_ids": ["green-pip"], "actions": {"green-pip": 3}},
        ):
            with self.assertRaises(dispose_module.DisposeError):
                dispose_module.validate_decisions(self.analysis, bad, home=self.home)

    def test_results_carry_the_five_fields_the_page_reads(self):
        report = self.apply([("green-pip", "trash")])
        record = report.results[0]
        for key in ("item_id", "path", "status", "detail", "size_bytes"):
            self.assertIn(key, record)
        self.assertEqual(report.executed_ids, ["green-pip"])

    def test_the_managed_folder_is_its_own_corner_of_the_home_directory(self):
        self.assertEqual(
            dispose_module.managed_dir(self.home),
            self.home / ".carl-file-organizer" / "storage",
        )


if __name__ == "__main__":
    unittest.main()
