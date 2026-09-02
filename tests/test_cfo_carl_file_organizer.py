from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from carl_file_organizer.classifier import classify
from carl_file_organizer.config import resolve_config
from carl_file_organizer.executor import PlanError, apply_approved_plan
from carl_file_organizer.planner import build_plan
from carl_file_organizer.report import render_report

# The safety net has nowhere to look in these tests: no launch agents, no
# symlink scan roots, no lsof.  Behaviour must not depend on the machine.
GUARD_OFFLINE = {"reference_files": [], "scan_roots": [], "lsof_enabled": False}


def simple_config(root: Path):
    return resolve_config(root, profile="simple", lang="en")


def plan_for(root: Path, **kwargs):
    # A day of imaginary distance, so freshly written fixture files are past the
    # ten-minute "just touched it" guard.
    later = datetime.now().astimezone() + timedelta(days=1)
    return build_plan(
        root,
        config=kwargs.pop("config", None) or simple_config(root),
        home=kwargs.pop("home", root),
        now=kwargs.pop("now", later),
        guard_options=kwargs.pop("guard_options", GUARD_OFFLINE),
        **kwargs
    )


def action_for(plan, filename, kind="move"):
    return next(
        action
        for action in plan["actions"]
        if action["filename"] == filename and action["kind"] == kind
    )


class CarlFileOrganizerTests(unittest.TestCase):
    def test_classifier_is_small_and_predictable(self) -> None:
        self.assertEqual(classify(Path("paper.PDF"))[0], "Documents")
        self.assertEqual(classify(Path("photo.heic"))[0], "Images")
        self.assertEqual(classify(Path("unknown.blob"))[0], "Other")

    def test_plan_is_shallow_and_ignores_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "notes.txt").write_text("hello", encoding="utf-8")
            (root / ".secret.txt").write_text("hidden", encoding="utf-8")
            nested = root / "Already Organized"
            nested.mkdir()
            (nested / "inside.pdf").write_text("stay", encoding="utf-8")

            plan = plan_for(root)

            self.assertEqual(plan["summary"]["files"], 1)
            self.assertEqual(
                action_for(plan, "notes.txt")["destination"],
                str(root / "Documents" / "notes.txt"),
            )
            self.assertEqual(plan["summary"]["proposed_reclaimed_bytes"], 0)
            # the folder travels whole, and nothing inside it is filed separately
            self.assertEqual(action_for(plan, "Already Organized")["subject_kind"], "dir")
            self.assertTrue((nested / "inside.pdf").exists())

    def test_duplicate_detection_hashes_equal_size_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one.txt").write_text("same", encoding="utf-8")
            (root / "two.txt").write_text("same", encoding="utf-8")
            (root / "other.txt").write_text("diff", encoding="utf-8")

            plan = plan_for(root, hash_duplicates=True)

            groups = [group for group in plan["groups"] if group["kind"] == "duplicate"]
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["evidence"], "sha256")
            self.assertEqual(groups[0]["potential_bytes"], 4)

    def test_only_approved_action_moves(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.pdf"
            second = root / "second.jpg"
            first.write_text("document", encoding="utf-8")
            second.write_text("image", encoding="utf-8")
            config = simple_config(root)
            plan = plan_for(root, config=config)
            chosen = action_for(plan, "first.pdf")
            plan["approved_action_ids"] = [chosen["id"]]

            report = apply_approved_plan(plan, config=config, home=root)

            self.assertEqual(report.results[0]["status"], "moved")
            self.assertTrue((root / "Documents" / "first.pdf").exists())
            self.assertTrue(second.exists())

    def test_unknown_approval_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "first.pdf").write_text("document", encoding="utf-8")
            plan = plan_for(root)
            plan["approved_action_ids"] = ["invented"]
            with self.assertRaises(PlanError):
                apply_approved_plan(plan, home=root)

    def test_tampered_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "first.pdf").write_text("document", encoding="utf-8")
            config = simple_config(root)
            plan = plan_for(root, config=config)
            action = action_for(plan, "first.pdf")
            plan["approved_action_ids"] = [action["id"]]
            action["destination"] = str(root / "Other" / "renamed.pdf")
            action["destination_portable"] = "$HOME/Other/renamed.pdf"
            with self.assertRaises(PlanError):
                apply_approved_plan(plan, config=config, home=root)

    def test_report_embeds_readable_plan_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "paper.pdf").write_text("document", encoding="utf-8")
            plan = plan_for(root)
            html = render_report(plan)
            self.assertIn("paper.pdf", html)
            self.assertIn(json.dumps(plan["schema_version"]), html)


if __name__ == "__main__":
    unittest.main()
