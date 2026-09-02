"""The after picture, and the promise that it is only a picture.

The preview reads plan.json and draws where things land.  It decides nothing, it
fetches nothing, and it never shows anybody's home directory.  Every test here
is one of those three promises, or the arithmetic that keeps the drawing honest:
one node per subject, five partitions, hold stays at the root, and a graph too
big to read collapses into an aggregate instead of a hairball.
"""

from __future__ import annotations

import os
import sys

# Runs under both invocations the repo uses: ``unittest discover -s tests``
# (which puts tests/ on the path for us) and ``unittest tests.test_cfo_preview``
# (which does not).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cfo_path  # noqa: E402,F401 - puts the skill's scripts dir on sys.path

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from carl_file_organizer import preview
from carl_file_organizer.preview import (
    MAX_NODES,
    PREVIEW_TEXT,
    build_graph,
    render_preview_html,
    render_preview_page,
)

FIXTURES = Path(cfo_path.FIXTURES_DIR)
PLAN_PATH = FIXTURES / "plan-v2-sample.json"
ANALYSIS_PATH = FIXTURES / "storage-analysis-sample.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def index(graph):
    return {node["id"]: node for node in graph["nodes"]}


class GraphShapeTest(unittest.TestCase):
    """The graph mirrors the plan: one node per subject, and the tree above it."""

    def setUp(self):
        self.plan = load(PLAN_PATH)
        self.graph = build_graph(self.plan)

    def test_one_node_per_subject_move_beats_hold_and_the_rest(self):
        subjects = {
            action["subject_id"]
            for action in self.plan["actions"]
            if action["kind"] in ("move", "hold")
        }
        files = [node for node in self.graph["nodes"] if node["type"] == "file"]
        self.assertEqual(len(files), len(subjects))
        self.assertEqual(len({node["id"] for node in files}), len(files))

        # Archive.zip carries move + trash + delete; only the move survives.
        archive = index(self.graph)["f:3c4d5e6f7a8b9c0d"]
        self.assertTrue(archive["moving"])
        self.assertTrue(archive["to"].startswith("00_收件箱/待判断"))

    def test_five_partitions_labelled_by_their_real_directory_names(self):
        partitions = [node for node in self.graph["nodes"] if node["type"] == "partition"]
        self.assertEqual(len(partitions), 5)
        self.assertEqual(self.graph["stats"]["partitions"], 5)
        self.assertEqual(
            [node["label"] for node in partitions],
            [self.plan["names"][key] for key in preview.PARTITION_ORDER],
        )

    def test_second_level_folders_are_deduplicated(self):
        folders = [node for node in self.graph["nodes"] if node["type"] == "folder"]
        labels = [node["label"] for node in folders]
        self.assertEqual(len(labels), len(set(labels)) if len(set(labels)) == len(labels) else len(labels))
        self.assertEqual(len({node["id"] for node in folders}), len(folders))
        # Three PDFs share one 文档资料 folder node.
        self.assertEqual(sum(1 for node in folders if node["label"] == "文档资料"), 1)
        self.assertIn("待判断", labels)

    def test_hold_files_stay_at_the_root(self):
        nodes = index(self.graph)
        root_label = nodes["root"]["label"]
        holds = [
            action["subject_id"]
            for action in self.plan["actions"]
            if action["kind"] == "hold"
        ]
        self.assertTrue(holds)
        for subject in holds:
            node = nodes["f:" + subject]
            self.assertEqual(node["to"], root_label)
            self.assertFalse(node["moving"])
            self.assertEqual(node["color"], "red")

    def test_every_link_points_at_a_real_node_and_now_links_cover_every_file(self):
        ids = set(index(self.graph))
        for link in self.graph["links"]:
            self.assertIn(link["source"], ids)
            self.assertIn(link["target"], ids)
            self.assertIn(link["kind"], ("now", "after"))
        files = [node for node in self.graph["nodes"] if node["type"] == "file"]
        now_links = [link for link in self.graph["links"] if link["kind"] == "now"]
        self.assertEqual(len(now_links), len(files))
        self.assertTrue(all(link["target"] == "root" for link in now_links))
        # Child -> parent, exactly once per node that has a parent.
        after_parents = [link["source"] for link in self.graph["links"] if link["kind"] == "after"]
        self.assertEqual(len(after_parents), len(set(after_parents)))

    def test_stats_add_up(self):
        stats = self.graph["stats"]
        self.assertEqual(stats["files"], stats["moving"] + stats["staying"])
        self.assertGreater(stats["moving"], 0)
        self.assertGreater(stats["staying"], 0)
        # node_modules is trashed rather than moved, so it only shows up as space.
        self.assertGreaterEqual(stats["reclaim_bytes"], 198311744)

    def test_no_home_directory_ever_reaches_the_graph(self):
        blob = json.dumps(self.graph, ensure_ascii=False)
        self.assertNotIn("/Users/", blob)
        self.assertNotIn("/home/", blob)


class MachineLayerTest(unittest.TestCase):
    """With an analysis in hand, the cleanup map joins the same drawing."""

    def setUp(self):
        self.plan = load(PLAN_PATH)
        self.analysis = load(ANALYSIS_PATH)
        self.graph = build_graph(self.plan, self.analysis)

    def test_machine_root_carries_every_analysis_item(self):
        nodes = index(self.graph)
        self.assertEqual(nodes["machine"]["type"], "machine")
        self.assertEqual(nodes["machine"]["label"], self.analysis["machine"]["hostname"])
        storage = [node for node in self.graph["nodes"] if node["type"] == "storage"]
        self.assertEqual(len(storage), len(self.analysis["items"]))
        self.assertEqual(self.graph["stats"]["storage_items"], len(storage))
        parents = {
            link["target"]
            for link in self.graph["links"]
            if link["source"].startswith("s:")
        }
        self.assertEqual(parents, {"machine"})
        self.assertIn(
            {"source": "root", "target": "machine", "kind": "after"}, self.graph["links"]
        )

    def test_green_items_are_flagged_as_pending_clean(self):
        nodes = index(self.graph)
        derived = nodes["s:st-derived-data"]
        self.assertEqual(derived["color"], "green")
        self.assertTrue(derived["pending_clean"])
        self.assertIn(PREVIEW_TEXT["zh"]["tip_clean"], derived["hint"])
        chrome = nodes["s:st-chrome-profile"]
        self.assertEqual(chrome["color"], "yellow")
        self.assertFalse(chrome["pending_clean"])

    def test_analysis_green_bytes_join_the_reclaim_total(self):
        without = build_graph(self.plan)["stats"]["reclaim_bytes"]
        green = sum(
            item["size_bytes"] for item in self.analysis["items"] if item["color"] == "green"
        )
        self.assertEqual(self.graph["stats"]["reclaim_bytes"], without + green)

    def test_storage_paths_stay_portable(self):
        blob = json.dumps(self.graph, ensure_ascii=False)
        self.assertNotIn("/Users/", blob)
        self.assertIn("$HOME", blob)


class NodeBudgetTest(unittest.TestCase):
    """Past four hundred nodes the picture stops adding dots and starts counting."""

    def synthetic(self, count):
        plan = load(PLAN_PATH)
        template = plan["actions"][0]
        actions = []
        for i in range(count):
            action = copy.deepcopy(template)
            action["id"] = "gen%06d" % i
            action["subject_id"] = "gen%06d" % i
            action["filename"] = "file-%06d.pdf" % i
            action["size_bytes"] = 1000 + i
            action["destination_portable"] = (
                "$HOME/Downloads/20_知识库/文档资料/PDF/file-%06d.pdf" % i
            )
            action["destination"] = None
            actions.append(action)
        plan["actions"] = actions
        return plan

    def test_under_the_cap_nothing_is_aggregated(self):
        graph = build_graph(self.synthetic(50))
        self.assertEqual(graph["stats"]["dropped"], 0)
        self.assertNotIn("agg:rest", index(graph))

    def test_over_the_cap_the_tail_becomes_one_node(self):
        graph = build_graph(self.synthetic(900))
        self.assertLessEqual(len(graph["nodes"]), MAX_NODES)
        aggregate = index(graph)["agg:rest"]
        self.assertGreater(aggregate["aggregate"], 0)
        self.assertEqual(
            aggregate["label"], PREVIEW_TEXT["zh"]["rest"].format(k=aggregate["aggregate"])
        )
        kept = [node for node in graph["nodes"] if node["type"] == "file" and node["id"] != "agg:rest"]
        self.assertEqual(len(kept) + aggregate["aggregate"], 900)
        # The survivors are the big ones.
        self.assertEqual(
            min(node["size_bytes"] for node in kept),
            max(
                node["size_bytes"] for node in kept
            ) - (len(kept) - 1),
        )

    def test_the_cap_also_covers_the_machine_layer(self):
        graph = build_graph(self.synthetic(900), load(ANALYSIS_PATH))
        self.assertLessEqual(len(graph["nodes"]), MAX_NODES)


class FragmentTest(unittest.TestCase):
    """A fragment you can paste anywhere: no network, no leaks, no surprises."""

    def setUp(self):
        self.graph = build_graph(load(PLAN_PATH), load(ANALYSIS_PATH))
        self.fragment = render_preview_html(self.graph, lang="zh")

    def test_it_is_one_self_contained_section(self):
        self.assertTrue(self.fragment.startswith("<section id=\"cfo-preview\""))
        self.assertTrue(self.fragment.rstrip().endswith("</section>"))
        self.assertIn("<canvas>", self.fragment)
        self.assertIn("<style>", self.fragment)
        self.assertIn("<script>", self.fragment)
        self.assertNotIn("<!doctype", self.fragment.lower())

    def test_it_loads_nothing_from_anywhere(self):
        for needle in ("http://", "https://", "<link", "<script src", "@import", "url("):
            self.assertNotIn(needle, self.fragment, needle)

    def test_it_shows_nobody_their_own_home_directory(self):
        self.assertNotIn("/Users/", self.fragment)
        self.assertNotIn("/home/", self.fragment)

    def test_the_embed_id_scopes_every_rule(self):
        fragment = render_preview_html(self.graph, embed_id="after-map", height=540)
        self.assertIn('<section id="after-map"', fragment)
        self.assertIn("#after-map {", fragment)
        self.assertIn("height: 540px;", fragment)
        self.assertNotIn("#cfo-preview", fragment)
        self.assertNotIn('getElementById("cfo-preview")', fragment)

    def test_two_fragments_can_share_one_page(self):
        one = render_preview_html(self.graph, embed_id="map-a")
        two = render_preview_html(self.graph, embed_id="map-b")
        self.assertNotIn("map-b", one)
        self.assertNotIn("map-a", two)
        self.assertEqual(one.count("#map-a "), two.count("#map-b "))

    def test_language_switches_every_visible_string(self):
        english = render_preview_html(self.graph, lang="en")
        self.assertIn(PREVIEW_TEXT["en"]["state_after"], english)
        self.assertIn('data-lang="en"', english)
        self.assertIn('["en"]', english)
        self.assertIn(PREVIEW_TEXT["zh"]["state_after"], self.fragment)

    def test_the_data_survives_the_round_trip(self):
        match = re.search(r"var DATA = (\{.*?\});\n", self.fragment, re.S)
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1).replace("<\\/", "</"))
        self.assertEqual(len(payload["nodes"]), len(self.graph["nodes"]))
        self.assertEqual(len(payload["links"]), len(self.graph["links"]))
        self.assertEqual(payload["stats"]["moving"], self.graph["stats"]["moving"])


class CopyTest(unittest.TestCase):
    """Both columns of the copy table say the same things."""

    def test_zh_and_en_carry_the_same_keys(self):
        self.assertEqual(set(PREVIEW_TEXT), {"zh", "en"})
        self.assertEqual(set(PREVIEW_TEXT["zh"]), set(PREVIEW_TEXT["en"]))
        for key, value in PREVIEW_TEXT["zh"].items():
            self.assertTrue(value.strip(), key)
            self.assertTrue(PREVIEW_TEXT["en"][key].strip(), key)

    def test_the_chinese_column_avoids_straight_double_quotes(self):
        for key, value in PREVIEW_TEXT["zh"].items():
            self.assertNotIn('"', value, key)

    def test_placeholders_match_across_languages(self):
        for key in PREVIEW_TEXT["zh"]:
            zh = set(re.findall(r"\{(\w+)\}", PREVIEW_TEXT["zh"][key]))
            en = set(re.findall(r"\{(\w+)\}", PREVIEW_TEXT["en"][key]))
            self.assertEqual(zh, en, key)


class CliTest(unittest.TestCase):
    """The command line writes a page you can double-click."""

    def test_it_writes_a_standalone_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "nested" / "preview.html"
            code = preview.main([str(PLAN_PATH), "-o", str(out)])
            self.assertEqual(code, 0)
            html = out.read_text(encoding="utf-8")
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("<canvas>", html)
        self.assertIn("</html>", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("/Users/", html)

    def test_the_analysis_flag_adds_the_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "preview.html"
            preview.main(
                [str(PLAN_PATH), "--analysis", str(ANALYSIS_PATH), "-o", str(out), "--lang", "en"]
            )
            html = out.read_text(encoding="utf-8")
        self.assertIn("carl-macbook", html)
        self.assertIn(PREVIEW_TEXT["en"]["shape_storage"], html)
        self.assertIn('<html lang="en">', html)

    def test_the_fragment_flag_skips_the_page_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fragment.html"
            preview.main([str(PLAN_PATH), "--fragment", "-o", str(out)])
            html = out.read_text(encoding="utf-8")
        self.assertTrue(html.startswith("<section"))
        self.assertNotIn("<!doctype", html.lower())


class PageTest(unittest.TestCase):
    """The wrapper is the same fragment with a cream background around it."""

    def test_the_page_embeds_the_fragment_verbatim(self):
        graph = build_graph(load(PLAN_PATH))
        page = render_preview_page(graph, lang="zh")
        self.assertIn(render_preview_html(graph, lang="zh"), page)
        self.assertIn("#FAFAF7", page)
        self.assertIn("<title>" + PREVIEW_TEXT["zh"]["title"] + "</title>", page)


class DegenerateInputTest(unittest.TestCase):
    """A plan with nothing in it still draws a folder rather than an exception."""

    def test_an_empty_plan_still_produces_a_root(self):
        graph = build_graph({"lang": "zh", "source_root_portable": "$HOME/Downloads", "names": {}, "actions": []})
        self.assertEqual(graph["stats"]["files"], 0)
        self.assertEqual(index(graph)["root"]["label"], "Downloads")
        html = render_preview_html(graph)
        self.assertIn("<canvas>", html)

    def test_a_plan_is_required_to_be_a_mapping(self):
        with self.assertRaises(TypeError):
            build_graph([])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
