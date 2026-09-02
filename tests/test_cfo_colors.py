"""The three colours: one per action, one per group, one for the folder.

The colour is what the review page turns into a button, so these tests care
about one property above all others: no colour is ever written by hand.  It is
derived from the decision the rules already made, which means a rule change can
break a test here but a wording change never can.
"""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import tempfile
import unittest
from pathlib import Path

from carl_file_organizer import planner
from carl_file_organizer.config import resolve_config
from carl_file_organizer.planner import (
    COLORS,
    GREEN,
    MESS_THRESHOLDS,
    RED,
    YELLOW,
    action_color,
    build_plan,
    color_totals,
    mess_color,
    mess_counts,
    mess_score,
)

from cfo_helpers import (  # noqa: E402 - the path shim has to run first
    GUARD_OFFLINE,
    NOW,
    action_for,
    actions_for,
    age,
    write,
)


def plan_for(root: Path, **kwargs):
    config = kwargs.pop("config", None) or resolve_config(root, profile="tiered", lang="zh")
    return build_plan(
        root,
        config=config,
        now=kwargs.pop("now", NOW),
        home=kwargs.pop("home", root),
        guard_options=kwargs.pop("guard_options", GUARD_OFFLINE),
        trash_backend=kwargs.pop("trash_backend", "finder"),
        **kwargs
    )


class ActionColorTests(unittest.TestCase):
    """The pure function, with no plan around it."""

    def test_every_hold_is_red_whatever_held_it(self) -> None:
        for tier in ("forbidden", "in_use", "referenced", "aging", "pinned"):
            self.assertEqual(action_color({"kind": "hold", "tier": tier}), RED, tier)

    def test_a_settled_move_is_green_and_a_pending_one_is_yellow(self) -> None:
        settled = {"kind": "move", "tier": "routine", "reroutable": False}
        pending = {"kind": "move", "tier": "routine", "reroutable": True}
        self.assertEqual(action_color(settled), GREEN)
        self.assertEqual(action_color(pending), YELLOW)

    def test_a_sensitive_move_is_green_because_isolating_is_the_safe_move(self) -> None:
        action = {"kind": "move", "tier": "sensitive", "reroutable": False}
        self.assertEqual(action_color(action), GREEN)

    def test_a_move_inside_a_group_is_green_the_disposal_next_to_it_is_not(self) -> None:
        self.assertEqual(
            action_color({"kind": "move", "tier": "duplicate", "reroutable": False}), GREEN
        )
        for kind in ("trash", "delete"):
            self.assertEqual(action_color({"kind": kind, "tier": "duplicate"}), YELLOW, kind)

    def test_only_regenerable_disposal_is_green(self) -> None:
        for kind in ("trash", "delete"):
            self.assertEqual(action_color({"kind": kind, "tier": "regenerable"}), GREEN, kind)
            self.assertEqual(action_color({"kind": kind, "tier": "cold"}), YELLOW, kind)


class ColorInAPlanTests(unittest.TestCase):
    def test_a_filed_document_is_green_and_an_unknown_extension_is_yellow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md"), hours=100)
            age(write(root / "mystery.zzz"), hours=100)
            plan = plan_for(root)

            self.assertEqual(action_for(plan, "notes.md")["color"], GREEN)
            self.assertEqual(action_for(plan, "mystery.zzz")["color"], YELLOW)

    def test_a_settling_archive_is_red_while_it_waits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "bundle.zip", "PK\x03\x04"), hours=0.2)
            plan = plan_for(root)

            hold = action_for(plan, "bundle.zip", kind="hold")
            self.assertEqual(hold["tier"], "aging")
            self.assertEqual(hold["color"], RED)
            self.assertFalse(hold["approvable"])

    def test_no_red_action_is_ever_approvable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md"), hours=100)
            age(write(root / "id_rsa"), hours=100)
            age(write(root / "fresh.pdf"), hours=0.1)
            plan = plan_for(root)

            reds = [a for a in plan["actions"] if a["color"] == RED]
            self.assertTrue(reds)
            for action in reds:
                self.assertFalse(action["approvable"], action["id"])
                self.assertEqual(action["kind"], "hold")

    def test_a_group_is_always_a_yellow_question(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "release.zip", "PK\x03\x04"), hours=100)
            age(write(root / "release" / "readme.txt"), hours=100)
            age(root / "release", hours=100)
            plan = plan_for(root)

            self.assertTrue(plan["groups"])
            for group in plan["groups"]:
                self.assertEqual(group["color"], YELLOW, group["group_id"])
            # the moves inside the group stay green; only the disposals are yellow
            moves = [a for a in plan["actions"] if a["kind"] == "move" and a["group_id"]]
            self.assertTrue(moves)
            for action in moves:
                self.assertEqual(action["color"], GREEN, action["id"])

    def test_a_duplicate_head_keeps_its_colour_after_the_tier_is_rewritten(self) -> None:
        """build_plan rewrites the tier of a duplicate's move after the fact."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "report.pdf", "same body\n"), hours=100)
            age(write(root / "report copy.pdf", "same body\n"), hours=100)
            plan = plan_for(root, hash_duplicates=True)

            heads = [a for a in plan["actions"] if a["kind"] == "move" and a["group_id"]]
            self.assertTrue(heads)
            for head in heads:
                self.assertEqual(head["tier"], "duplicate")
                self.assertFalse(head["reroutable"])
                self.assertEqual(head["color"], GREEN, head["id"])
            for action in actions_for(plan, "report copy.pdf"):
                if action["kind"] in ("trash", "delete"):
                    self.assertEqual(action["color"], YELLOW, action["id"])

    def test_by_color_adds_up_to_every_action(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md"), hours=100)
            age(write(root / "mystery.zzz"), hours=100)
            age(write(root / "fresh.pdf"), hours=0.1)
            plan = plan_for(root)

            by_color = plan["summary"]["by_color"]
            self.assertEqual(set(by_color), set(COLORS))
            self.assertEqual(
                sum(slot["actions"] for slot in by_color.values()), len(plan["actions"])
            )
            for colour in COLORS:
                wearing = [a for a in plan["actions"] if a["color"] == colour]
                self.assertEqual(by_color[colour]["actions"], len(wearing), colour)
                self.assertEqual(
                    by_color[colour]["bytes"],
                    sum(a["size_bytes"] for a in wearing),
                    colour,
                )

    def test_color_totals_ignores_an_action_with_no_colour(self) -> None:
        totals = color_totals([{"color": "chartreuse", "size_bytes": 10}])
        self.assertEqual(sum(slot["actions"] for slot in totals.values()), 0)


class MessTests(unittest.TestCase):
    def test_thresholds_are_the_ones_written_down(self) -> None:
        self.assertEqual(MESS_THRESHOLDS[GREEN], {"loose": 3, "pending": 0})
        self.assertEqual(MESS_THRESHOLDS[YELLOW], {"loose": 15, "pending": 5})

    def test_a_tidy_folder_is_green(self) -> None:
        counts = {"loose": 3, "aging": 0, "pending": 0, "groups": 0, "top_dirs": 0}
        self.assertEqual(mess_color(counts), GREEN)

    def test_one_thing_waiting_on_you_takes_green_away(self) -> None:
        counts = {"loose": 2, "aging": 0, "pending": 1, "groups": 0, "top_dirs": 0}
        self.assertEqual(mess_color(counts), YELLOW)

    def test_a_big_pile_with_few_questions_is_still_only_yellow(self) -> None:
        counts = {"loose": 200, "aging": 0, "pending": 4, "groups": 0, "top_dirs": 0}
        self.assertEqual(mess_color(counts), YELLOW)

    def test_many_items_and_many_questions_is_red(self) -> None:
        counts = {"loose": 40, "aging": 3, "pending": 12, "groups": 4, "top_dirs": 9}
        self.assertEqual(mess_color(counts), RED)

    def test_score_is_bounded_and_grows_with_the_mess(self) -> None:
        tidy = {"loose": 1, "aging": 0, "pending": 0, "groups": 0, "top_dirs": 0}
        awful = {"loose": 900, "aging": 90, "pending": 400, "groups": 60, "top_dirs": 80}
        self.assertLess(mess_score(tidy), mess_score(awful))
        self.assertGreaterEqual(mess_score(tidy), 0)
        self.assertLessEqual(mess_score(awful), 100)

    def test_the_bar_never_pegs_so_it_can_always_move(self) -> None:
        """A merely untidy folder must not use up the whole bar."""

        untidy = {"loose": 27, "aging": 2, "pending": 3, "groups": 4, "top_dirs": 3}
        self.assertEqual(mess_color(untidy), YELLOW)
        self.assertLess(mess_score(untidy), 90)

        landslide = {"loose": 400, "aging": 30, "pending": 90, "groups": 40, "top_dirs": 40}
        self.assertEqual(mess_color(landslide), RED)
        self.assertGreater(mess_score(landslide), mess_score(untidy))
        self.assertLess(mess_score(landslide), 100)

    def test_clearing_a_pile_visibly_moves_the_bar(self) -> None:
        before = {"loose": 200, "aging": 0, "pending": 0, "groups": 0, "top_dirs": 0}
        after = {"loose": 170, "aging": 0, "pending": 0, "groups": 0, "top_dirs": 0}
        self.assertGreater(mess_score(before) - mess_score(after), 0)

    def test_loose_and_pending_are_not_counted_twice(self) -> None:
        """They describe the same pile two ways; adding them would double it."""

        counts = {"loose": 15, "aging": 0, "pending": 5, "groups": 0, "top_dirs": 0}
        only_loose = dict(counts, pending=0)
        self.assertEqual(mess_score(counts), mess_score(only_loose))

    def test_score_and_colour_are_computed_separately(self) -> None:
        """The bar length is not allowed to become the verdict, or the reverse."""

        counts = {"loose": 200, "aging": 0, "pending": 0, "groups": 0, "top_dirs": 0}
        self.assertGreater(mess_score(counts), 80)
        self.assertEqual(mess_color(counts), YELLOW)

    def test_counts_come_from_the_scan_not_from_the_action_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md"), hours=100)
            age(write(root / "mystery.zzz"), hours=100)
            age(write(root / "folder" / "inner.txt"), hours=100)
            age(root / "folder", hours=100)
            plan = plan_for(root)

            counts = plan["mess"]["counts"]
            self.assertEqual(counts["loose"], plan["summary"]["entries"])
            self.assertEqual(counts["top_dirs"], plan["summary"]["dirs"])
            self.assertEqual(counts["groups"], len(plan["groups"]))
            self.assertEqual(
                counts["pending"],
                len({a["subject_id"] for a in plan["actions"] if a["reroutable"]}),
            )

    def test_a_plan_says_out_loud_who_chose_the_folder_colour(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            age(write(root / "notes.md"), hours=100)
            plan = plan_for(root)

            self.assertEqual(plan["mess"]["color_source"], "rule")
            self.assertIn(plan["mess"]["color"], COLORS)
            self.assertEqual(set(plan["mess"]["reason"]), {"zh", "en"})
            self.assertIn(str(plan["mess"]["counts"]["loose"]), plan["mess"]["reason"]["zh"])

    def test_an_empty_folder_is_green(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = plan_for(root)

            self.assertEqual(plan["mess"]["color"], GREEN)
            self.assertEqual(plan["mess"]["score"], 0)
            self.assertEqual(plan["mess"]["counts"]["loose"], 0)

    def test_mess_counts_reads_entry_objects_and_actions_together(self) -> None:
        class FakeEntry(object):
            def __init__(self, is_dir: bool) -> None:
                self.is_dir = is_dir

        entries = [FakeEntry(False), FakeEntry(True), FakeEntry(True)]
        actions = [
            {"subject_id": "a", "kind": "hold", "tier": "aging", "reroutable": False},
            {"subject_id": "b", "kind": "move", "tier": "routine", "reroutable": True},
            {"subject_id": "b", "kind": "trash", "tier": "cold", "reroutable": False},
        ]
        counts = mess_counts(entries, actions, [{"group_id": "g"}])
        self.assertEqual(
            counts, {"loose": 3, "aging": 1, "pending": 1, "groups": 1, "top_dirs": 2}
        )

    def test_the_module_only_knows_three_colours(self) -> None:
        self.assertEqual(planner.COLORS, ("green", "yellow", "red"))


if __name__ == "__main__":
    unittest.main()
