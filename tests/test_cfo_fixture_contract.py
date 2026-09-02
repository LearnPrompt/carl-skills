"""The plan.json schema v2 contract, checked against the hand-written sample.

Every work package reads and writes this shape, so the sample is the shared
truth: if a change breaks this file, it breaks the review page, the executor
and the agent skill at the same time.
"""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import json
import unittest
from pathlib import Path

FIXTURE = Path(cfo_path.FIXTURES_DIR) / "plan-v2-sample.json"

HOLD_TIERS = {"aging", "pinned", "forbidden", "in_use", "referenced"}
REROUTABLE_RULES = {"unknown-ext", "dir:pending", "dir:derivative"}
KINDS = {"move", "trash", "delete", "hold"}
COLORS = {"green", "yellow", "red"}
TIERS = {
    "routine",
    "sensitive",
    "regenerable",
    "duplicate",
    "cold",
    "aging",
    "pinned",
    "forbidden",
    "in_use",
    "referenced",
}


def _portable_values(node, trail=""):
    """Yield every ``*_portable`` string in the document with its path."""

    if isinstance(node, dict):
        for key, value in node.items():
            where = "{0}.{1}".format(trail, key)
            if isinstance(value, str) and key.endswith("_portable"):
                yield where, value
            else:
                for item in _portable_values(value, where):
                    yield item
    elif isinstance(node, list):
        for index, value in enumerate(node):
            for item in _portable_values(value, "{0}[{1}]".format(trail, index)):
                yield item


class PlanV2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.actions = cls.plan["actions"]
        cls.by_id = {action["id"]: action for action in cls.actions}

    def test_schema_version_and_top_level_shape(self) -> None:
        self.assertEqual(self.plan["schema_version"], 2)
        for key in (
            "generator", "created_at", "now", "lang", "lang_source", "profile",
            "source_root", "source_root_portable", "managed_dir", "managed_dir_portable",
            "names", "capabilities", "scan_policy", "disk", "mess", "summary",
            "pinned", "actions", "groups", "notes", "approved_action_ids",
            "overrides", "approved_at", "approved_by",
        ):
            self.assertIn(key, self.plan)
        self.assertEqual(self.plan["approved_action_ids"], [])
        self.assertEqual(self.plan["overrides"], [])
        self.assertIsNone(self.plan["notes"])

    def test_action_ids_are_unique(self) -> None:
        self.assertEqual(len(self.by_id), len(self.actions))

    def test_every_action_carries_the_frozen_fields(self) -> None:
        required = (
            "id", "subject_id", "kind", "subject_kind", "source", "source_portable",
            "filename", "destination", "destination_portable", "destination_key",
            "size_bytes", "modified_ns", "age_hours", "rule", "reason", "detail",
            "confidence", "tier", "group_id", "approvable", "reroutable",
            "default_selected", "requires", "reclaims_bytes", "restore_method",
            "tags", "hints", "hold_reason", "guard", "dir_stats", "color",
        )
        for action in self.actions:
            for key in required:
                self.assertIn(key, action, action["id"])
            self.assertIn(action["kind"], KINDS)
            self.assertIn(action["tier"], TIERS)
            self.assertIn(action["color"], COLORS)
            self.assertIn(action["subject_kind"], {"file", "dir"})
            self.assertEqual(set(action["reason"]), {"zh", "en"})
            self.assertFalse(action["default_selected"])
            for slot in ("open_by", "referenced_in", "incoming_symlinks", "shape"):
                self.assertIn(slot, action["guard"])

    def test_group_options_map_onto_real_actions(self) -> None:
        group_ids = set()
        for group in self.plan["groups"]:
            group_ids.add(group["group_id"])
            self.assertIn(group["kind"], {"pair", "duplicate", "regenerable"})
            self.assertTrue(group["options"], group["group_id"])
            keys = [option["key"] for option in group["options"]]
            self.assertIn(group["default_choice"], keys)
            for option in group["options"]:
                self.assertTrue(option["action_ids"])
                for action_id in option["action_ids"]:
                    self.assertIn(action_id, self.by_id, option["key"])
                    self.assertEqual(self.by_id[action_id]["group_id"], group["group_id"])
                    self.assertTrue(self.by_id[action_id]["approvable"])
                delete_ids = [
                    aid for aid in option["action_ids"] if self.by_id[aid]["kind"] == "delete"
                ]
                if delete_ids:
                    self.assertIn("allow-permanent-delete", option["requires"])
            member_subjects = set(group["members"])
            for member in member_subjects:
                self.assertIn(member, group["member_labels"])
        for action in self.actions:
            if action["group_id"] is not None:
                self.assertIn(action["group_id"], group_ids)

    def test_group_kinds_present(self) -> None:
        kinds = {group["kind"] for group in self.plan["groups"]}
        self.assertEqual(kinds, {"pair", "duplicate", "regenerable"})
        pair = next(g for g in self.plan["groups"] if g["kind"] == "pair")
        option_keys = {option["key"] for option in pair["options"]}
        self.assertIn("keep_all", option_keys)
        self.assertEqual(
            sum(1 for key in option_keys if key.startswith("keep:")), 3
        )
        duplicate = next(g for g in self.plan["groups"] if g["kind"] == "duplicate")
        self.assertEqual(duplicate["evidence"], "sha256")
        self.assertIsNotNone(duplicate["sha256"])
        regenerable = next(g for g in self.plan["groups"] if g["kind"] == "regenerable")
        self.assertEqual(
            {option["key"] for option in regenerable["options"]}, {"trash_all", "delete_all"}
        )

    def test_holds_are_never_approvable(self) -> None:
        holds = [action for action in self.actions if action["kind"] == "hold"]
        self.assertGreaterEqual(len(holds), 4)
        for action in holds:
            self.assertFalse(action["approvable"], action["id"])
            self.assertFalse(action["reroutable"], action["id"])
            self.assertIsNone(action["destination"])
            self.assertIsNone(action["destination_portable"])
            self.assertIsNotNone(action["hold_reason"])
            self.assertIn(action["tier"], HOLD_TIERS)
        tiers = {action["tier"] for action in holds}
        self.assertTrue({"aging", "forbidden", "in_use", "referenced"} <= tiers)

    def test_guard_evidence_on_in_use_and_referenced(self) -> None:
        in_use = next(a for a in self.actions if a["tier"] == "in_use")
        self.assertTrue(in_use["guard"]["open_by"])
        self.assertIn("pid", in_use["guard"]["open_by"][0])
        referenced = next(a for a in self.actions if a["tier"] == "referenced")
        self.assertTrue(referenced["guard"]["referenced_in"])
        first = referenced["guard"]["referenced_in"][0]
        self.assertIn("file", first)
        self.assertIn("line", first)

    def test_reroutable_actions_stay_in_the_allowed_rule_set(self) -> None:
        reroutable = [action for action in self.actions if action["reroutable"]]
        self.assertTrue(reroutable)
        self.assertTrue(any(action["rule"] == "unknown-ext" for action in reroutable))
        for action in reroutable:
            self.assertIn(action["rule"], REROUTABLE_RULES, action["id"])
            self.assertEqual(action["kind"], "move")
            self.assertTrue(action["approvable"])
            self.assertIn(action["destination_key"], self.plan["names"])

    def test_destination_keys_resolve_through_names(self) -> None:
        for action in self.actions:
            if action["destination_key"] is None:
                self.assertIsNone(action["destination"])
                continue
            self.assertIn(action["destination_key"], self.plan["names"])
            relative = self.plan["names"][action["destination_key"]]
            self.assertIn(relative, action["destination_portable"])

    def test_delete_actions_require_the_flag(self) -> None:
        deletes = [action for action in self.actions if action["kind"] == "delete"]
        self.assertTrue(deletes)
        for action in deletes:
            self.assertIn("allow-permanent-delete", action["requires"])
            self.assertIn(action["tier"], {"regenerable", "duplicate", "cold"})
            self.assertGreater(action["reclaims_bytes"], 0)

    def test_moves_reclaim_nothing_and_carry_a_restore_line(self) -> None:
        for action in self.actions:
            if action["kind"] == "move":
                self.assertEqual(action["reclaims_bytes"], 0)
                self.assertIn("mv ", action["restore_method"]["zh"])
                self.assertIn(action["filename"], action["destination_portable"])

    def test_portable_paths_never_leak_a_user_name(self) -> None:
        seen = 0
        for where, value in _portable_values(self.plan):
            seen += 1
            self.assertTrue(value.startswith("$HOME/"), "{0}: {1}".format(where, value))
        self.assertGreater(seen, 10)
        self.assertEqual(self.plan["source_root_portable"], "$HOME/Downloads")

    def test_summary_matches_the_actions(self) -> None:
        summary = self.plan["summary"]
        by_kind = {}
        by_tier = {}
        for action in self.actions:
            by_kind[action["kind"]] = by_kind.get(action["kind"], 0) + 1
            by_tier[action["tier"]] = by_tier.get(action["tier"], 0) + 1
        self.assertEqual(summary["by_kind"], by_kind)
        self.assertEqual(summary["by_tier"], by_tier)
        self.assertEqual(summary["proposed_reclaimed_bytes"], 0)
        self.assertEqual(summary["entries"], summary["files"] + summary["dirs"])

    def test_every_colour_follows_from_the_decision(self) -> None:
        """The buttons follow this field, so it may never be an opinion."""

        for action in self.actions:
            if action["kind"] == "hold":
                self.assertEqual(action["color"], "red", action["id"])
            elif action["kind"] == "move":
                expected = "yellow" if action["reroutable"] else "green"
                self.assertEqual(action["color"], expected, action["id"])
            elif action["tier"] == "regenerable":
                self.assertEqual(action["color"], "green", action["id"])
            else:
                self.assertEqual(action["color"], "yellow", action["id"])
        colours = {action["color"] for action in self.actions}
        self.assertEqual(colours, COLORS)

    def test_no_red_action_can_ever_be_approved(self) -> None:
        for action in self.actions:
            if action["color"] == "red":
                self.assertFalse(action["approvable"], action["id"])

    def test_every_group_is_a_yellow_question(self) -> None:
        self.assertTrue(self.plan["groups"])
        for group in self.plan["groups"]:
            self.assertEqual(group["color"], "yellow", group["group_id"])

    def test_mess_block_describes_the_whole_folder(self) -> None:
        mess = self.plan["mess"]
        self.assertIn(mess["color"], COLORS)
        self.assertEqual(mess["color_source"], "rule")
        self.assertTrue(0 <= mess["score"] <= 100)
        self.assertEqual(
            set(mess["counts"]), {"loose", "aging", "pending", "groups", "top_dirs"}
        )
        for key, value in mess["counts"].items():
            self.assertIsInstance(value, int, key)
            self.assertGreaterEqual(value, 0, key)
        self.assertEqual(set(mess["reason"]), {"zh", "en"})
        self.assertEqual(mess["counts"]["groups"], len(self.plan["groups"]))
        self.assertEqual(mess["counts"]["loose"], self.plan["summary"]["entries"])
        self.assertEqual(mess["counts"]["top_dirs"], self.plan["summary"]["dirs"])

    def test_by_color_counts_every_action_exactly_once(self) -> None:
        by_color = self.plan["summary"]["by_color"]
        self.assertEqual(set(by_color), COLORS)
        self.assertEqual(
            sum(slot["actions"] for slot in by_color.values()), len(self.actions)
        )
        for colour in COLORS:
            wearing = [a for a in self.actions if a["color"] == colour]
            self.assertEqual(by_color[colour]["actions"], len(wearing), colour)
            self.assertEqual(
                by_color[colour]["bytes"], sum(a["size_bytes"] for a in wearing), colour
            )

    def test_sensitive_action_says_contents_were_never_read(self) -> None:
        sensitive = next(a for a in self.actions if a["tier"] == "sensitive")
        self.assertTrue(sensitive["rule"].startswith("sensitive:"))
        self.assertIn("未读取内容", sensitive["reason"]["zh"])
        self.assertIn("60_敏感信息/待转移", sensitive["destination_portable"])


if __name__ == "__main__":
    unittest.main()
