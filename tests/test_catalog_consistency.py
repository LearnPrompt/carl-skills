from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
REGISTRY = ROOT / "registry.json"


class CatalogConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.readme = README.read_text(encoding="utf-8")
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_directory_and_cards_follow_catalog_order(self) -> None:
        directory = self.readme.split("## 📋 目录", 1)[1].split("## 📦 安装方式", 1)[0]
        directory_anchors = re.findall(r"^\| .*?\]\(#([^)]+)\) \|", directory, re.MULTILINE)

        cards = self.readme.split("## ✨ Skills", 1)[1].split("## 🗂 Registry", 1)[0]
        card_anchors = [
            anchor
            for anchor in re.findall(r'<a id="([^"]+)"></a>', cards)
            if anchor != "-skills"
        ]

        expected = self.registry["catalog_order"]
        self.assertEqual(len(expected), len(set(expected)))
        self.assertEqual(directory_anchors, expected)
        self.assertEqual(card_anchors, expected)
        self.assertEqual(len(card_anchors), len(set(card_anchors)))
        self.assertEqual(cards.count("<table>"), len(expected))
        self.assertEqual(cards.count("</table>"), len(expected))

    def test_every_active_skill_maps_to_a_visible_card(self) -> None:
        active = [
            skill
            for skill in self.registry["skills"]
            if skill.get("status", "").startswith("active")
        ]
        anchors = {skill.get("catalog_anchor") for skill in active}
        self.assertNotIn(None, anchors)
        self.assertEqual(anchors, set(self.registry["catalog_order"]))
        for anchor in self.registry["catalog_order"]:
            self.assertTrue(
                any(skill["catalog_anchor"] == anchor for skill in active),
                f"catalog anchor has no active Skill: {anchor}",
            )

    def test_badges_report_workflow_and_skill_counts(self) -> None:
        workflow_count = len(self.registry["catalog_order"])
        skill_count = len(self.registry["skills"])
        self.assertIn(f"Workflows-{workflow_count}-", self.readme)
        self.assertIn(f"Skills-{skill_count}-", self.readme)

    def test_install_contract_is_explicit_and_non_partial(self) -> None:
        for skill in self.registry["skills"]:
            if not skill.get("installable"):
                continue
            if skill.get("install_mode") == "skill-folder":
                self.assertTrue(skill.get("install_command"), skill["id"])
                self.assertFalse(skill.get("hermes_installable", True), skill["id"])
                self.assertTrue(skill.get("hermes_skip_reason"), skill["id"])
            else:
                self.assertTrue(skill.get("raw_skill_url"), skill["id"])

    def test_suite_members_exist(self) -> None:
        skill_ids = {skill["id"] for skill in self.registry["skills"]}
        for suite in self.registry.get("suites", []):
            missing = set(suite.get("skill_ids", [])) - skill_ids
            self.assertFalse(missing, f"{suite['id']} has missing Skill IDs: {sorted(missing)}")


if __name__ == "__main__":
    unittest.main()
