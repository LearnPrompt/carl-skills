"""Three-colour report: one template, two entrances, two modes."""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import copy
import json
import re
import unittest
from pathlib import Path

import build_report

FIXTURES = Path(cfo_path.FIXTURES_DIR)
PLAN = FIXTURES / "plan-v2-sample.json"
ANALYSIS = FIXTURES / "storage-analysis-sample.json"
SKILL_DIR = Path(cfo_path.SCRIPTS_DIR).parent


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _strip_comments(html: str) -> str:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return re.sub(r"/\*.*?\*/", "", html, flags=re.S)


def _cards(html: str, color: str) -> list:
    return re.findall(r'<article class="item[^"]*" data-color="{0}".*?</article>'.format(color), html, re.S)


def _section(html: str, color: str) -> str:
    match = re.search(r'<section class="sec" data-color="{0}".*?</section>'.format(color), html, re.S)
    assert match, "section {0} missing".format(color)
    return match.group(0)


def _segbar_widths(html: str) -> list:
    bars = re.findall(r'<div class="segbar">(.*?)</div>', html, re.S)
    return [[int(w) for w in re.findall(r'style="width:(\d+)%"', bar)] for bar in bars]


def _embedded(html: str, element_id: str) -> dict:
    match = re.search(r'<script id="{0}" type="application/json">(.*?)</script>'.format(element_id), html, re.S)
    assert match, "{0} script missing".format(element_id)
    text = match.group(1).replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")
    return json.loads(text)


class RenderBothKindsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = _load(PLAN)
        cls.analysis = _load(ANALYSIS)
        cls.pages = {
            ("organize", "static"): build_report.render(cls.plan, mode="static"),
            ("organize", "serve"): build_report.render(cls.plan, mode="serve", token="test-token-value"),
            ("storage", "static"): build_report.render(cls.analysis, mode="static"),
            ("storage", "serve"): build_report.render(cls.analysis, mode="serve", token="test-token-value"),
        }

    def test_kind_is_detected_and_stamped_on_body(self) -> None:
        self.assertEqual(build_report.detect_kind(self.plan), "organize")
        self.assertEqual(build_report.detect_kind(self.analysis), "storage")
        for (kind, mode), html in self.pages.items():
            self.assertIn('<body data-kind="{0}" data-mode="{1}"'.format(kind, mode), html)
            self.assertIn('<html lang="zh-CN">', html)

    def test_no_absolute_paths_no_network_no_gradients(self) -> None:
        for (kind, mode), html in self.pages.items():
            bare = _strip_comments(html)
            self.assertNotIn("/Users/", bare, "{0}/{1} leaks a home path".format(kind, mode))
            self.assertNotIn("http://", bare, "{0}/{1} references the network".format(kind, mode))
            self.assertNotIn("https://", bare, "{0}/{1} references the network".format(kind, mode))
            self.assertNotIn("linear-gradient", bare)
            self.assertNotIn("radial-gradient", bare)
            self.assertNotIn("<link", bare)
            self.assertNotIn('<script src', bare)

    def test_template_slots_are_all_filled(self) -> None:
        for html in self.pages.values():
            self.assertNotRegex(html, r"__REPORT_[A-Z]+__")

    def test_token_only_in_serve(self) -> None:
        self.assertIn("test-token-value", self.pages[("organize", "serve")])
        self.assertIn("test-token-value", self.pages[("storage", "serve")])
        self.assertNotIn("test-token-value", self.pages[("organize", "static")])
        self.assertNotIn("test-token-value", self.pages[("storage", "static")])
        self.assertEqual(_embedded(self.pages[("organize", "static")], "report-config")["token"], "")

    def test_three_sections_in_order(self) -> None:
        for html in self.pages.values():
            self.assertEqual(re.findall(r'<section class="sec" data-color="(\w+)"', html), ["green", "yellow", "red"])

    def test_segbar_widths_never_exceed_100(self) -> None:
        for (kind, mode), html in self.pages.items():
            bars = _segbar_widths(html)
            self.assertTrue(bars, "{0}/{1} has no segbar".format(kind, mode))
            for widths in bars:
                self.assertLessEqual(sum(widths), 100)
                self.assertTrue(all(w >= 0 for w in widths))

    def test_red_cards_carry_no_delete_or_trash_controls(self) -> None:
        for (kind, mode), html in self.pages.items():
            cards = _cards(html, "red")
            self.assertTrue(cards, "{0}/{1} has no red cards".format(kind, mode))
            for card in cards:
                self.assertNotIn("<input", card)
                self.assertNotIn("<select", card)
                self.assertNotRegex(card, r'data-action="(trash|delete)"')
            red = _section(html, "red")
            self.assertNotIn("gn-toggle-all", red)
            self.assertNotIn("gn-section-run", red)

    def test_yellow_cards_have_no_permanent_delete(self) -> None:
        for (kind, mode), html in self.pages.items():
            cards = _cards(html, "yellow")
            self.assertTrue(cards, "{0}/{1} has no yellow cards".format(kind, mode))
            for card in cards:
                self.assertNotRegex(card, r'data-action="delete"')
                self.assertNotRegex(card, r'data-kind="delete"')
                self.assertNotIn("needs-permanent", card)

    def test_green_cards_offer_trash_and_permanent_delete(self) -> None:
        for mode in ("static", "serve"):
            storage = self.pages[("storage", mode)]
            cards = _cards(storage, "green")
            self.assertTrue(cards)
            self.assertTrue(any('data-action="trash"' in c for c in cards))
            self.assertTrue(any('data-action="delete"' in c and "needs-permanent" in c for c in cards))
            self.assertIn('id="gn-permanent"', _section(storage, "green"))
        # The planner colours every group yellow; a green regenerable group shows the permanent option.
        plan = copy.deepcopy(self.plan)
        for group in plan["groups"]:
            if group["kind"] == "regenerable":
                group["color"] = "green"
        html = build_report.render(plan, mode="static")
        green = _section(html, "green")
        self.assertIn('data-action="delete"', green)
        self.assertIn('data-kind="delete"', green)
        self.assertIn('id="gn-permanent"', green)
        self.assertNotIn('data-action="delete"', _section(html, "yellow"))

    def test_organize_pending_has_destination_select_in_yellow(self) -> None:
        for mode in ("static", "serve"):
            html = self.pages[("organize", mode)]
            yellow = _section(html, "yellow")
            self.assertIn('<select class="gn-dest"', yellow)
            self.assertIn('data-action-id="0112233445566a7b"', yellow)
            self.assertNotIn("<select", _section(html, "green"))
            # pair / duplicate groups keep their single choice
            self.assertIn('data-group-id="pair-7d2c1e9f"', yellow)
            self.assertIn('class="gn-option"', yellow)
            self.assertIn('class="gn-adopt"', yellow)

    def test_storage_page_has_disks_top5_and_advice(self) -> None:
        html = self.pages[("storage", "static")]
        self.assertEqual(len(re.findall(r'<div class="disk">', html)), 2)
        self.assertIn('class="card top5"', html)
        self.assertEqual(len(re.findall(r'<tr><td class="c">', html)), 5)
        self.assertIn("先清 Xcode DerivedData", html)
        self.assertIn("Time Machine 本地快照占着 40 GB", html)
        self.assertIn('data-action="copy"', html)
        self.assertIn("brew cleanup --prune=all", html)

    def test_footer_matches_kind_and_mode(self) -> None:
        text = build_report.template_text()["zh"]
        self.assertIn(text["btn_export"], self.pages[("organize", "static")])
        self.assertIn(text["btn_export_decisions"], self.pages[("storage", "static")])
        self.assertIn(text["btn_apply"], self.pages[("organize", "serve")])
        self.assertIn(text["btn_apply"], self.pages[("storage", "serve")])
        self.assertIn('id="gn-dry"', self.pages[("organize", "serve")])
        self.assertNotIn('id="gn-dry"', self.pages[("storage", "serve")])
        self.assertNotIn('id="gn-shutdown"', self.pages[("organize", "static")])
        self.assertIn("carl-file-organizer-approved.json", self.pages[("organize", "static")])
        self.assertIn("carl-file-organizer-decisions.json", self.pages[("storage", "static")])
        self.assertIn("/api/apply", self.pages[("organize", "serve")])
        self.assertIn("/api/dispose", self.pages[("storage", "serve")])
        self.assertIn("/api/reveal", self.pages[("storage", "serve")])

    def test_reveal_only_in_serve(self) -> None:
        for kind in ("organize", "storage"):
            self.assertIn('data-action="reveal"', self.pages[(kind, "serve")])
            self.assertNotIn('data-action="reveal"', self.pages[(kind, "static")])

    def test_embedded_data_is_sanitised(self) -> None:
        data = _embedded(self.pages[("organize", "static")], "report-data")
        self.assertNotIn("source_root", data)
        self.assertNotIn("managed_dir", data)
        self.assertEqual(data["source_root_portable"], "$HOME/Downloads")
        for action in data["actions"]:
            self.assertNotIn("source", action)
            self.assertNotIn("destination", action)
        self.assertNotIn("/Users/", json.dumps(data, ensure_ascii=False))


class NotesAndFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = _load(PLAN)

    def test_without_notes_the_rule_reason_is_shown(self) -> None:
        html = build_report.render(self.plan, mode="static")
        self.assertIn("文档按类型归档到 20_知识库/文档资料/PDF", html)
        self.assertIn("散件 12 件，其中 2 件要你看一眼", html)

    def test_with_notes_the_agent_text_wins(self) -> None:
        notes = {
            "mess": {"color": "red", "line": "这个下载目录已经是泥石流了。"},
            "folder_line": "先把绿的一键清掉，剩下的慢慢看。",
            "actions": {"9c1f0a7b2d3e4f55": {"what": "一份季度报告 PDF", "why": "扩展名规则命中", "if_removed": "只是搬家，随时能搬回来"}},
            "groups": {"pair-7d2c1e9f": {"what": "Archive.zip 和它解压出来的目录", "why": "同名同内容", "if_removed": "留目录扔压缩包最省事"}},
        }
        html = build_report.render(self.plan, mode="static", notes=notes)
        self.assertIn("一份季度报告 PDF", html)
        self.assertIn("只是搬家，随时能搬回来", html)
        self.assertIn("Archive.zip 和它解压出来的目录", html)
        self.assertIn("这个下载目录已经是泥石流了。", html)
        self.assertIn("先把绿的一键清掉", html)
        self.assertIn('<span class="pill red">', html)
        embedded = _embedded(html, "report-data")
        self.assertEqual(embedded["notes"]["actions"]["9c1f0a7b2d3e4f55"]["what"], "一份季度报告 PDF")

    def test_notes_merge_on_top_of_plan_notes(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["notes"] = {"actions": {"9c1f0a7b2d3e4f55": {"what": "旧说明", "why": "旧原因"}}}
        merged = build_report.merge_notes(plan, {"actions": {"9c1f0a7b2d3e4f55": {"what": "新说明"}}})
        self.assertEqual(merged["notes"]["actions"]["9c1f0a7b2d3e4f55"], {"what": "新说明", "why": "旧原因"})

    def test_missing_colour_fields_fall_back_to_tiers(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan.pop("mess", None)
        plan["summary"].pop("by_color", None)
        for action in plan["actions"]:
            action.pop("color", None)
        for group in plan["groups"]:
            group.pop("color", None)
        html = build_report.render(plan, mode="static")
        self.assertEqual(re.findall(r'<section class="sec" data-color="(\w+)"', html), ["green", "yellow", "red"])
        self.assertTrue(_cards(html, "green"))
        self.assertTrue(_cards(html, "yellow"))
        self.assertEqual(len(_cards(html, "red")), 4)
        for widths in _segbar_widths(html):
            self.assertLessEqual(sum(widths), 100)
            self.assertTrue(widths)
        self.assertIn("12 项散件，2 项待判断，3 组重复或配对，4 项这轮不动。", html)
        self.assertEqual(build_report.action_color({"kind": "hold", "tier": "aging"}), "red")
        self.assertEqual(build_report.action_color({"kind": "move", "tier": "routine", "reroutable": True}), "yellow")
        self.assertEqual(build_report.action_color({"kind": "move", "tier": "routine"}), "green")
        self.assertEqual(build_report.group_color({"kind": "regenerable"}), "green")
        self.assertEqual(build_report.group_color({"kind": "pair"}), "yellow")

    def test_storage_items_without_colour_fall_back(self) -> None:
        self.assertEqual(build_report.item_color({"tier": "regenerable", "trash_paths": ["$HOME/x"]}), "green")
        self.assertEqual(build_report.item_color({"tier": "user-data", "trash_paths": []}), "yellow")
        self.assertEqual(build_report.item_color({"tier": "cache", "open_by": [{"command": "x", "pid": 1}]}), "red")

    def test_english_page(self) -> None:
        html = build_report.render(self.plan, mode="static", lang="en")
        self.assertIn('<html lang="en">', html)
        self.assertIn("Look first, then move", html)
        body = re.sub(r'<script id="report-text".*?</script>', "", html, flags=re.S)
        self.assertNotIn("这是什么", body)
        self.assertIn("What it is", body)


class SanitizeTests(unittest.TestCase):
    def test_home_rewritten_everywhere(self) -> None:
        data = {
            "source_root": "/Users/example/Downloads",
            "source_root_portable": "$HOME/Downloads",
            "managed_dir": "/Users/example/Downloads/00_x",
            "actions": [{"source": "/Users/example/Downloads/a", "source_portable": "$HOME/Downloads/a", "destination": None}],
            "guard": {"referenced_in": [{"file": "/Users/example/.zshrc"}], "links": ["/home/bob/x", "C:\\Users\\bob\\y"]},
            "note": "see /Users/someone-else/thing",
        }
        clean = build_report.sanitize(data)
        text = json.dumps(clean)
        self.assertNotIn("/Users/", text)
        self.assertNotIn("/home/bob", text)
        self.assertNotIn("C:\\\\Users\\\\bob", text)
        self.assertNotIn("source_root", clean)
        self.assertNotIn("managed_dir", clean)
        self.assertNotIn("source", clean["actions"][0])
        self.assertNotIn("destination", clean["actions"][0])
        self.assertEqual(clean["guard"]["referenced_in"][0]["file"], "$HOME/.zshrc")
        self.assertEqual(clean["note"], "see $HOME/thing")
        # the input is untouched
        self.assertEqual(data["source_root"], "/Users/example/Downloads")


class CommandLineTests(unittest.TestCase):
    def test_cli_writes_html_and_detects_kind(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.html"
            code = build_report.main([str(ANALYSIS), "-o", str(out), "--mode", "serve", "--token", "abc"])
            self.assertEqual(code, 0)
            html = out.read_text(encoding="utf-8")
            self.assertIn('<body data-kind="storage" data-mode="serve"', html)
            self.assertIn("abc", html)
            out2 = Path(tmp) / "p.html"
            self.assertEqual(build_report.main([str(PLAN), "-o", str(out2), "--lang", "en"]), 0)
            self.assertIn('<body data-kind="organize" data-mode="static"', out2.read_text(encoding="utf-8"))

    def test_template_lives_in_assets(self) -> None:
        self.assertEqual(build_report.TEMPLATE_PATH, SKILL_DIR / "assets" / "report_template.html")
        self.assertTrue(build_report.TEMPLATE_PATH.is_file())
        text = build_report.template_text()
        self.assertEqual(set(text["zh"]), set(text["en"]))


if __name__ == "__main__":
    unittest.main()
