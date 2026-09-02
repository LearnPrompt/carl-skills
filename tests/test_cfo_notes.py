"""The agent explanation layer, and the promise that it decides nothing.

Every test here is really the same test asked a different way: a notes file is
prose, and prose cannot approve, move, delete, reroute or recolour anything.
The one thing it may change is the folder's own colour, and even then the rule's
answer stays in the file next to it.
"""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import copy
import json
import tempfile
import unittest
from pathlib import Path

from carl_file_organizer import notes as notes_module
from carl_file_organizer.cli import main
from carl_file_organizer.config import resolve_config
from carl_file_organizer.notes import NotesError, merge_notes, validate_notes
from carl_file_organizer.planner import build_plan

from cfo_helpers import (  # noqa: E402 - the path shim has to run first
    GUARD_OFFLINE,
    NOW,
    age,
    write,
)


def sample_plan(root: Path):
    config = resolve_config(root, profile="tiered", lang="zh")
    return build_plan(
        root,
        config=config,
        now=NOW,
        home=root,
        guard_options=GUARD_OFFLINE,
        trash_backend="finder",
    )


def populated(root: Path) -> None:
    age(write(root / "notes.md"), hours=100)
    age(write(root / "mystery.zzz"), hours=100)
    age(write(root / "bundle.zip", "PK\x03\x04"), hours=100)
    age(write(root / "bundle" / "inner.txt"), hours=100)
    age(root / "bundle", hours=100)


class MergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        populated(self.root)
        self.plan = sample_plan(self.root)
        self.action_id = self.plan["actions"][0]["id"]

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_notes_land_in_their_own_block(self) -> None:
        merged = merge_notes(
            self.plan,
            {
                "folder_line": "这个目录基本是上周的下载",
                "actions": {
                    self.action_id: {
                        "what": "上周的会议纪要",
                        "why": "扩展名规则命中",
                        "if_removed": "在备份里还有一份",
                    }
                },
            },
        )
        block = merged["notes"]
        self.assertEqual(block["schema"], notes_module.NOTES_SCHEMA)
        self.assertEqual(block["folder_line"], "这个目录基本是上周的下载")
        self.assertEqual(block["actions"][self.action_id]["what"], "上周的会议纪要")
        self.assertEqual(block["warnings"], [])

    def test_the_original_plan_is_untouched(self) -> None:
        before = copy.deepcopy(self.plan)
        merge_notes(self.plan, {"folder_line": "一句话"})
        self.assertEqual(self.plan, before)

    def test_no_action_field_is_ever_changed(self) -> None:
        before = copy.deepcopy(self.plan["actions"])
        merged = merge_notes(
            self.plan,
            {
                "actions": {
                    self.action_id: {
                        "what": "x",
                        "why": "y",
                        "if_removed": "z",
                        "color": "green",
                        "approvable": True,
                        "destination": "/somewhere/else",
                        "kind": "delete",
                    }
                }
            },
        )
        self.assertEqual(merged["actions"], before)
        self.assertEqual(
            set(merged["notes"]["actions"][self.action_id]), {"what", "why", "if_removed"}
        )
        self.assertTrue(
            any("unknown field" in line for line in merged["notes"]["warnings"])
        )

    def test_an_unknown_id_only_warns(self) -> None:
        merged = merge_notes(
            self.plan, {"actions": {"0000000000000000": {"what": "谁知道呢"}}}
        )
        self.assertEqual(merged["notes"]["actions"], {})
        self.assertTrue(
            any("no such id" in line for line in merged["notes"]["warnings"])
        )

    def test_a_group_note_needs_a_real_group(self) -> None:
        group_id = self.plan["groups"][0]["group_id"]
        merged = merge_notes(
            self.plan,
            {"groups": {group_id: {"what": "压缩包和它解出来的目录"}, "nope": {"what": "x"}}},
        )
        self.assertIn(group_id, merged["notes"]["groups"])
        self.assertNotIn("nope", merged["notes"]["groups"])

    def test_the_folder_colour_can_be_overridden_and_says_so(self) -> None:
        rule_colour = self.plan["mess"]["color"]
        merged = merge_notes(
            self.plan, {"mess": {"color": "red", "line": "我看过了，这里比数字显示的更乱"}}
        )
        self.assertEqual(merged["mess"]["color"], "red")
        self.assertEqual(merged["mess"]["color_source"], "notes")
        self.assertEqual(merged["mess"]["rule_color"], rule_colour)
        self.assertEqual(merged["mess"]["line"], "我看过了，这里比数字显示的更乱")

    def test_without_an_override_the_rule_keeps_the_credit(self) -> None:
        merged = merge_notes(self.plan, {"folder_line": "一句话"})
        self.assertEqual(merged["mess"]["color_source"], "rule")
        self.assertEqual(merged["mess"]["color"], merged["mess"]["rule_color"])

    def test_an_invented_colour_is_refused_not_stored(self) -> None:
        merged = merge_notes(self.plan, {"mess": {"color": "purple"}})
        self.assertEqual(merged["mess"]["color"], self.plan["mess"]["color"])
        self.assertTrue(any("mess.color" in line for line in merged["notes"]["warnings"]))

    def test_merging_twice_replaces_rather_than_piles_up(self) -> None:
        once = merge_notes(self.plan, {"folder_line": "第一版"})
        twice = merge_notes(once, {"folder_line": "第二版"})
        self.assertEqual(twice["notes"]["folder_line"], "第二版")
        self.assertEqual(twice["mess"]["rule_color"], self.plan["mess"]["color"])

    def test_empty_and_non_string_sentences_are_dropped(self) -> None:
        merged = merge_notes(
            self.plan,
            {"actions": {self.action_id: {"what": "   ", "why": 7, "if_removed": "真的"}}},
        )
        self.assertEqual(
            merged["notes"]["actions"][self.action_id], {"if_removed": "真的"}
        )

    def test_a_very_long_sentence_is_trimmed_not_discarded(self) -> None:
        merged = merge_notes(
            self.plan, {"actions": {self.action_id: {"what": "字" * 5000}}}
        )
        self.assertEqual(
            len(merged["notes"]["actions"][self.action_id]["what"]), notes_module.MAX_TEXT
        )

    def test_an_unknown_top_level_field_warns(self) -> None:
        _cleaned, warnings = validate_notes(self.plan, {"nonsense": 1})
        self.assertTrue(any("unknown top level" in line for line in warnings))

    def test_a_notes_file_that_is_not_an_object_is_refused(self) -> None:
        with self.assertRaises(NotesError):
            merge_notes(self.plan, ["not", "an", "object"])


class LoadTests(unittest.TestCase):
    def test_broken_json_names_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "notes.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(NotesError) as caught:
                notes_module.load_notes(path)
            self.assertIn("notes.json", str(caught.exception))

    def test_a_missing_file_is_a_notes_error_not_an_oserror(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(NotesError):
                notes_module.load_notes(Path(temporary) / "absent.json")

    def test_a_json_list_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "notes.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(NotesError):
                notes_module.load_notes(path)


class BuildCommandTests(unittest.TestCase):
    def test_build_writes_the_notes_into_the_plan_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            populated(root)
            plan = sample_plan(root)
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            notes_path = root / "notes.json"
            notes_path.write_text(
                json.dumps(
                    {
                        "folder_line": "上周的下载都在这儿",
                        "mess": {"color": "yellow", "line": "看着乱，其实好收拾"},
                        "actions": {plan["actions"][0]["id"]: {"what": "会议纪要"}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            code = main(["build", str(plan_path), "--notes", str(notes_path)])
            self.assertEqual(code, 0)

            written = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(written["notes"]["folder_line"], "上周的下载都在这儿")
            self.assertEqual(written["mess"]["color"], "yellow")
            self.assertEqual(written["mess"]["color_source"], "notes")

    def test_build_can_write_somewhere_else_and_leave_the_plan_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            populated(root)
            plan = sample_plan(root)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            notes_path = root / "notes.json"
            notes_path.write_text('{"folder_line": "一句话"}', encoding="utf-8")
            out_path = root / "out" / "annotated.json"

            self.assertEqual(
                main(
                    [
                        "build",
                        str(plan_path),
                        "--notes",
                        str(notes_path),
                        "--output",
                        str(out_path),
                    ]
                ),
                0,
            )
            self.assertIsNone(json.loads(plan_path.read_text(encoding="utf-8"))["notes"])
            self.assertEqual(
                json.loads(out_path.read_text(encoding="utf-8"))["notes"]["folder_line"],
                "一句话",
            )

    def test_build_without_notes_is_a_no_op_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            populated(root)
            plan = sample_plan(root)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

            self.assertEqual(main(["build", str(plan_path)]), 0)
            self.assertIsNone(json.loads(plan_path.read_text(encoding="utf-8"))["notes"])

    def test_build_on_a_broken_plan_exits_two_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan_path = Path(temporary) / "plan.json"
            plan_path.write_text("not json at all", encoding="utf-8")
            self.assertEqual(main(["build", str(plan_path)]), 2)


if __name__ == "__main__":
    unittest.main()
