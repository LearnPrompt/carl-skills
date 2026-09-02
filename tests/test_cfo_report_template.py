"""Three-colour report: one template, two entrances, two modes."""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import copy
import json
import re
import unittest
from pathlib import Path, PurePosixPath

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
        # A green regenerable group offers the permanent option; a yellow group never does.
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


class CombinedPageTests(unittest.TestCase):
    """One page, one entrance, one approval file: cleanup, moves and the after picture."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = _load(PLAN)
        cls.analysis = _load(ANALYSIS)
        cls.both = {"plan": cls.plan, "analysis": cls.analysis}
        cls.pages = {
            "static": build_report.render(cls.both, mode="static"),
            "serve": build_report.render(cls.both, mode="serve", token="test-token-value"),
        }

    def test_the_envelope_is_detected_and_stamped(self) -> None:
        self.assertEqual(build_report.detect_kind(self.both), "combined")
        self.assertEqual(build_report.detect_kind({"plan": self.plan}), "combined")
        self.assertEqual(build_report.detect_kind({"analysis": self.analysis}), "combined")
        # a bare plan or analysis still means what it always meant
        self.assertEqual(build_report.detect_kind(self.plan), "organize")
        self.assertEqual(build_report.detect_kind(self.analysis), "storage")
        for mode, html in self.pages.items():
            self.assertIn('<body data-kind="combined" data-mode="{0}"'.format(mode), html)
            self.assertNotRegex(html, r"__REPORT_[A-Z]+__")

    def test_both_halves_are_on_the_page(self) -> None:
        html = self.pages["static"]
        # the tidy-up half
        self.assertIn("文档按类型归档到 20_知识库/文档资料/PDF", html)
        self.assertIn('<select class="gn-dest"', html)
        self.assertIn('data-group-id="pair-7d2c1e9f"', html)
        # the whole-machine half
        self.assertIn('<div class="disk">', html)
        self.assertIn('class="card top5"', html)
        self.assertIn("$HOME/Library/Caches/pip", html)
        # one numbered list holding the analysis priorities and the colour advice
        self.assertIn("先清 Xcode DerivedData", html)
        self.assertEqual(re.findall(r'<section class="sec" data-color="(\w+)"', html), ["green", "yellow", "red"])

    def test_each_band_says_cleanup_first_and_moves_second(self) -> None:
        text = build_report.template_text()["zh"]
        green = _section(self.pages["static"], "green")
        heads = re.findall(r'<h3 class="subhead">([^<]*)<', green)
        self.assertEqual(heads, [text["sub_clean"], text["sub_move"]])
        clean_at = green.index(text["sub_clean"])
        move_at = green.index(text["sub_move"])
        self.assertLess(clean_at, move_at)

    def test_one_half_alone_still_renders_with_one_block_fewer(self) -> None:
        only_plan = build_report.render({"plan": self.plan}, mode="static")
        self.assertIn('<body data-kind="combined"', only_plan)
        self.assertNotIn('<div class="disk">', only_plan)
        self.assertNotIn('class="card top5"', only_plan)
        self.assertIn("文档按类型归档到 20_知识库/文档资料/PDF", only_plan)

        only_analysis = build_report.render({"analysis": self.analysis}, mode="static")
        self.assertIn('<body data-kind="combined"', only_analysis)
        self.assertIn('<div class="disk">', only_analysis)
        self.assertNotIn('<select class="gn-dest"', only_analysis)
        for html in (only_plan, only_analysis):
            self.assertEqual(re.findall(r'<section class="sec" data-color="(\w+)"', html), ["green", "yellow", "red"])

    def test_the_after_picture_is_there_exactly_once(self) -> None:
        for html in self.pages.values():
            self.assertEqual(html.count('id="cfo-preview"'), 1)
            self.assertEqual(html.count('id="gn-preview"'), 1)
            self.assertIn("cfo:selection", html)
        text = build_report.template_text()["zh"]
        self.assertIn(text["preview_title"], self.pages["static"])
        self.assertIn(text["preview_note"], self.pages["static"])
        # and only on this page kind
        self.assertNotIn('id="cfo-preview"', build_report.render(self.plan, mode="static"))

    def test_the_selection_event_reaches_the_picture(self) -> None:
        html = self.pages["static"]
        self.assertIn("new CustomEvent('cfo:selection'", html)
        self.assertIn('window.addEventListener("cfo:selection"', html)

    def test_one_decisions_file_carries_both_halves(self) -> None:
        html = self.pages["static"]
        self.assertIn("carl-file-organizer-decisions.json", html)
        self.assertIn("carl-file-organizer/decisions", html)
        self.assertIn("approved_action_ids", html)
        self.assertIn("item_ids", html)
        # exactly one main button, and it exports the combined file
        self.assertEqual(html.count('id="gn-main"'), 1)
        self.assertIn("if (C.kind === 'combined')", html)
        self.assertEqual(_embedded(html, "report-config")["kind"], "combined")

    def test_serve_posts_to_both_engines(self) -> None:
        html = self.pages["serve"]
        self.assertIn("/api/apply", html)
        self.assertIn("/api/dispose", html)
        self.assertIn("/api/reveal", html)
        self.assertIn(build_report.template_text()["zh"]["btn_apply_all"], html)
        self.assertIn('id="gn-dry"', html)
        self.assertIn("test-token-value", html)

    def test_button_permissions_still_follow_the_colour(self) -> None:
        for html in self.pages.values():
            for card in _cards(html, "red"):
                self.assertNotIn("<input", card)
                self.assertNotIn("<select", card)
                self.assertNotRegex(card, r'data-action="(trash|delete)"')
            for card in _cards(html, "yellow"):
                self.assertNotRegex(card, r'data-kind="delete"')
                self.assertNotIn("needs-permanent", card)
            red = _section(html, "red")
            self.assertNotIn("gn-toggle-all", red)
            self.assertNotIn("gn-section-run", red)
            self.assertEqual(html.count('id="gn-permanent"'), 1)

    def test_nothing_on_the_page_names_an_account(self) -> None:
        for mode, html in self.pages.items():
            bare = _strip_comments(html)
            self.assertNotIn("/Users/", bare, mode)
            self.assertNotIn("http://", bare, mode)
            self.assertNotIn("https://", bare, mode)
            self.assertNotIn("<link", bare)
            self.assertNotIn("<script src", bare)
        data = _embedded(self.pages["static"], "report-data")
        self.assertNotIn("source_root", data["plan"])
        self.assertNotIn("managed_dir", data["plan"])
        for item in data["analysis"]["items"]:
            self.assertNotIn("path", item)
        self.assertNotIn("/Users/", json.dumps(data, ensure_ascii=False))

    def test_notes_reach_both_halves(self) -> None:
        notes = {
            "folder_line": "先把绿的一键清掉，剩下的慢慢看。",
            "actions": {"9c1f0a7b2d3e4f55": {"what": "一份季度报告 PDF", "why": "扩展名规则命中", "if_removed": "只是搬家"}},
            "items": {"st-pip-cache": {"what": "pip 下载来的轮子缓存", "why": "装过的包留下的", "if_removed": "下次装包慢一点"}},
        }
        html = build_report.render(self.both, mode="static", notes=notes)
        self.assertIn("一份季度报告 PDF", html)
        self.assertIn("pip 下载来的轮子缓存", html)
        self.assertIn("先把绿的一键清掉", html)

    def test_the_english_page(self) -> None:
        html = build_report.render(self.both, mode="static", lang="en")
        self.assertIn('<html lang="en">', html)
        body = re.sub(r'<script id="report-text".*?</script>', "", html, flags=re.S)
        self.assertIn(build_report.template_text()["en"]["sub_clean"], body)
        self.assertIn(build_report.template_text()["en"]["preview_title"], body)

    def test_render_does_not_mutate_either_half(self) -> None:
        plan = _load(PLAN)
        analysis = _load(ANALYSIS)
        build_report.render({"plan": plan, "analysis": analysis}, mode="static")
        self.assertEqual(plan["source_root"], self.plan["source_root"])
        self.assertEqual(analysis["items"][0]["id"], self.analysis["items"][0]["id"])
        # The fixture is a plan written on a Mac, so its absoluteness is a
        # POSIX question: on Windows Path("/Users/x/Downloads").is_absolute()
        # is False for want of a drive, and that says nothing about render.
        self.assertTrue(PurePosixPath(plan["source_root"]).is_absolute())


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


class EscapingTests(unittest.TestCase):
    """A filename is data.  It never becomes markup, in the body or in the JSON."""

    def setUp(self) -> None:
        self.plan = _load(PLAN)

    def test_plan_strings_are_escaped_in_the_body(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["actions"][0]["filename"] = '<img src=x onerror="alert(1)">.pdf'
        plan["actions"][0]["reason"]["zh"] = "含 <script> 的理由"
        html = build_report.render(plan, mode="static")
        self.assertNotIn('<img src=x onerror="alert(1)">', html)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;.pdf", html)
        self.assertNotIn("含 <script>", html)

    def test_embedded_data_has_no_raw_angle_brackets(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["actions"][0]["filename"] = "</script><b>x</b>.pdf"
        for mode in ("static", "serve"):
            html = build_report.render(plan, mode=mode, token="t")
            block = re.search(
                r'<script id="report-data" type="application/json">(.*?)</script>', html, re.S
            ).group(1)
            self.assertNotIn("<", block)
            self.assertNotIn(">", block)
            round_trip = json.loads(
                block.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")
            )
            self.assertEqual(round_trip["actions"][0]["filename"], "</script><b>x</b>.pdf")
            self.assertEqual(round_trip["schema_version"], 2)

    def test_render_does_not_mutate_the_caller_s_plan(self) -> None:
        plan = _load(PLAN)
        build_report.render(plan, mode="static")
        self.assertEqual(plan["source_root"], self.plan["source_root"])
        self.assertEqual(plan["actions"][0]["source"], self.plan["actions"][0]["source"])
        # The fixture is a plan written on a Mac, so its absoluteness is a
        # POSIX question: on Windows Path("/Users/x/Downloads").is_absolute()
        # is False for want of a drive, and that says nothing about render.
        self.assertTrue(PurePosixPath(plan["source_root"]).is_absolute())

    def test_every_approvable_action_is_reachable(self) -> None:
        html = build_report.render(self.plan, mode="static")
        for action in self.plan["actions"]:
            if not action["approvable"]:
                continue
            self.assertIn(action["id"], html, "approvable id missing: " + action["id"])

    def test_a_referenced_form_is_rewritten_too(self) -> None:
        # form is the literal text found in someone's config file; it used to be
        # exempt from the $HOME rewrite and no longer is.
        plan = copy.deepcopy(self.plan)
        home = str(Path(plan["source_root"]).parent)
        absolute_form = home + "/Downloads/backup-tool.sh"
        plan["actions"][0].setdefault("guard", {})["referenced_in"] = [
            {"file": home + "/.zshrc", "line": 7, "form": absolute_form}
        ]
        html = build_report.render(plan, mode="static")
        self.assertNotIn(absolute_form, html)
        self.assertIn("$HOME/Downloads/backup-tool.sh", html)

    def test_static_carries_no_server_wiring(self) -> None:
        # One template serves both modes, so the fetch code is in the file
        # either way; what a static page must not carry is a token or a live
        # endpoint it could actually post to.
        html = build_report.render(self.plan, mode="static", token="should-not-leak")
        self.assertNotIn("should-not-leak", html)
        self.assertEqual(_embedded(html, "report-config")["token"], "")
        self.assertEqual(_embedded(html, "report-config")["mode"], "static")


class CopyTests(unittest.TestCase):
    def test_the_two_languages_carry_the_same_keys(self) -> None:
        text = build_report.template_text()
        self.assertEqual(set(text["zh"]), set(text["en"]))
        self.assertEqual(set(text["zh"]["badge"]), set(text["en"]["badge"]))

    def test_zh_copy_has_no_straight_double_quotes(self) -> None:
        for key, value in build_report.template_text()["zh"].items():
            if isinstance(value, dict):
                for token, label in value.items():
                    self.assertNotIn('"', label, "{0}.{1}".format(key, token))
            else:
                self.assertNotIn('"', value, key)


class BadgeTests(unittest.TestCase):
    """Cards say 静置中, not aging.  A badge is copy, not a token dump."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = _load(PLAN)
        cls.analysis = _load(ANALYSIS)
        cls.zh = build_report.render(cls.plan, mode="static")
        cls.storage_zh = build_report.render(cls.analysis, mode="static")

    def _badges(self, html: str) -> list:
        return re.findall(r'<span class="badge[^"]*">([^<]*)</span>', html)

    def test_no_english_token_reaches_a_chinese_badge(self) -> None:
        for name, html in (("organize", self.zh), ("storage", self.storage_zh)):
            found = self._badges(html)
            self.assertTrue(found, name)
            for label in found:
                for token in (
                    "aging", "in use", "in_use", "referenced", "forbidden", "pinned",
                    "dev_cache", "app_data", "build_artifact", "regenerable",
                    "duplicate", "pair", "unknown",
                ):
                    self.assertNotIn(token, label, "{0}: {1}".format(name, label))

    def test_the_settling_tier_reads_as_chinese(self) -> None:
        self.assertIn(">静置中<", self.zh)
        self.assertIn(">被占用<", self.zh)

    def test_english_badges_come_from_the_english_table(self) -> None:
        html = build_report.render(self.plan, mode="static", lang="en")
        self.assertIn(">settling<", html)
        self.assertIn(">in use<", html)

    def test_an_unknown_token_falls_through_unchanged(self) -> None:
        t = build_report._T(build_report.template_text(), "zh")
        self.assertEqual(t.badge("aging"), "静置中")
        self.assertEqual(t.badge("brand_new_tier"), "brand_new_tier")
        self.assertEqual(t.badge(""), "")


class ReadyAtTests(unittest.TestCase):
    def test_an_iso_stamp_becomes_a_readable_time(self) -> None:
        self.assertEqual(
            build_report.format_ready_at("2026-09-04T11:56:03.412870+09:00", "zh"),
            "9 月 4 日 11:56",
        )
        self.assertEqual(
            build_report.format_ready_at("2026-09-04T11:56:03.412870+09:00", "en"),
            "Sep 4, 11:56",
        )

    def test_anything_that_is_not_a_stamp_is_handed_through(self) -> None:
        self.assertEqual(build_report.format_ready_at("", "zh"), "")
        self.assertEqual(build_report.format_ready_at("soon", "zh"), "soon")

    def test_the_page_shows_the_readable_form_and_not_the_iso_one(self) -> None:
        plan = _load(PLAN)
        html = build_report.render(plan, mode="static")
        self.assertNotIn("2026-09-07T19:15:00", html.split('id="report-data"')[0])
        self.assertIn("9 月 7 日 19:15", html)
        english = build_report.render(plan, mode="static", lang="en")
        self.assertIn("Sep 7, 19:15", english)


class TopFiveTests(unittest.TestCase):
    def test_the_table_is_sorted_by_size_whatever_the_analysis_says(self) -> None:
        analysis = _load(ANALYSIS)
        analysis["top5"] = list(reversed(analysis["top5"]))
        html = build_report.render(analysis, mode="static")
        sizes = re.findall(r'<tr><td class="c">.*?<td class="size">([^<]+)</td>', html, re.S)
        self.assertEqual(len(sizes), 5)

        def as_bytes(text: str) -> float:
            number, unit = text.split()
            return float(number) * {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}[unit]

        values = [as_bytes(x) for x in sizes]
        self.assertEqual(values, sorted(values, reverse=True))


class StaticEntranceTests(unittest.TestCase):
    """``plan`` and ``build --report`` write the same page the server serves."""

    def test_build_report_writes_the_shared_template(self) -> None:
        import tempfile

        from carl_file_organizer.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            plan_path.write_text(PLAN.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(main(["build", str(plan_path), "--report"]), 0)
            html = (root / "report.html").read_text(encoding="utf-8")
            self.assertIn('<body data-kind="organize" data-mode="static"', html)
            self.assertIn('<script id="report-config" type="application/json">', html)
            self.assertNotIn("/Users/", _strip_comments(html))

    def test_the_old_report_module_is_gone(self) -> None:
        with self.assertRaises(ImportError):
            __import__("carl_file_organizer.report")


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
