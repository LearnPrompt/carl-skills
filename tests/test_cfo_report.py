"""Review page: one template, two modes, rendered from the schema v2 sample."""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import copy
import json
import re
import unittest
from pathlib import Path

from carl_file_organizer import paths
from carl_file_organizer.report import TEXT, render_report, write_report

FIXTURE = Path(cfo_path.FIXTURES_DIR) / "plan-v2-sample.json"
EXPECTED_GROUPS = ["move", "pair", "duplicate", "regenerable", "cold", "hold", "protected", "pending"]


def _load_plan() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _groups(html: str) -> list:
    return re.findall(r'<section class="sec" data-group="([a-z]+)"', html)


def _section(html: str, key: str) -> str:
    match = re.search(
        r'<section class="sec" data-group="{0}".*?</section>'.format(key), html, re.S
    )
    assert match, "section {0} missing".format(key)
    return match.group(0)


def _row(html: str, action_id: str) -> str:
    match = re.search(r'<tr[^>]*data-ids="[^"]*\b{0}\b[^"]*"[^>]*>.*?</tr>'.format(action_id), html, re.S)
    assert match, "row for {0} missing".format(action_id)
    return match.group(0)


def _embedded_plan(html: str) -> dict:
    """The JSON the page's own script tag reads, undoing the <script> escaping."""

    match = re.search(
        r'<script id="gn-plan" type="application/json">(.*?)</script>', html, re.S
    )
    assert match, "gn-plan script missing"
    text = (
        match.group(1)
        .replace("\\u003c", "<")
        .replace("\\u003e", ">")
        .replace("\\u0026", "&")
    )
    return json.loads(text)


def _strip_comments(html: str) -> str:
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return re.sub(r"/\*.*?\*/", "", html, flags=re.S)


class RenderModesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = _load_plan()
        cls.static = render_report(cls.plan, mode="static")
        cls.serve = render_report(cls.plan, mode="serve", token="test-token-value")

    def test_both_modes_render_the_same_sections(self) -> None:
        self.assertEqual(_groups(self.static), EXPECTED_GROUPS)
        self.assertEqual(_groups(self.serve), EXPECTED_GROUPS)

    def test_body_carries_the_mode(self) -> None:
        self.assertIn('<body data-mode="static"', self.static)
        self.assertIn('<body data-mode="serve"', self.serve)
        self.assertIn('<html lang="zh-CN">', self.static)

    def test_static_exports_and_serve_posts(self) -> None:
        self.assertIn(TEXT["zh"]["btn_export"], self.static)
        self.assertIn("carl-file-organizer-approved.json", self.static)
        self.assertNotIn("X-GN-Token", self.static)
        self.assertNotIn("test-token-value", self.static)
        self.assertNotIn("/api/apply", self.static)

        self.assertIn("X-GN-Token", self.serve)
        self.assertIn("/api/apply", self.serve)
        self.assertIn("history.replaceState", self.serve)
        self.assertIn("test-token-value", self.serve)
        self.assertIn('<div class="serve-line">' + TEXT["zh"]["serve_note"], self.serve)
        self.assertNotIn('<div class="serve-line">', self.static)
        self.assertIn(TEXT["zh"]["btn_apply"], self.serve)

    def test_static_token_argument_is_ignored(self) -> None:
        html = render_report(self.plan, mode="static", token="should-not-leak")
        self.assertNotIn("should-not-leak", html)

    def test_pledge_sentence_is_fixed_at_the_top(self) -> None:
        pledge = TEXT["zh"]["pledge"]
        self.assertIn(pledge, self.static)
        self.assertLess(self.static.index(pledge), self.static.index('data-group="move"'))

    def test_every_approvable_action_is_reachable(self) -> None:
        for action in self.plan["actions"]:
            if not action["approvable"]:
                continue
            self.assertIn(action["id"], self.static, "approvable id missing from page: " + action["id"])

    def test_plan_strings_are_escaped(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["actions"][0]["filename"] = '<img src=x onerror="alert(1)">.pdf'
        plan["actions"][0]["reason"]["zh"] = "含 <script> 的理由"
        html = render_report(plan, mode="static")
        self.assertNotIn('<img src=x onerror="alert(1)">', html)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;.pdf", html)
        self.assertNotIn("含 <script>", html)

    def test_rejects_unknown_mode(self) -> None:
        with self.assertRaises(ValueError):
            render_report(self.plan, mode="pdf")


class SectionContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = _load_plan()
        cls.html = render_report(cls.plan, mode="static")

    def test_forbidden_rows_have_no_inputs(self) -> None:
        protected = _section(self.html, "protected")
        self.assertIn("Photos Library.photoslibrary", protected)
        self.assertNotIn("<input", protected)
        self.assertNotIn("<select", protected)
        self.assertNotIn("<button", protected)

    def test_hold_rows_have_no_inputs_and_show_guard_details(self) -> None:
        hold = _section(self.html, "hold")
        self.assertNotIn("<input", hold)
        self.assertNotIn("<select", hold)
        self.assertIn("tail (pid 48213)", hold)
        self.assertIn("com.example.backup.plist:14", hold)
        self.assertIn(".zshrc:82", hold)
        self.assertIn("$HOME/.local/bin/backup-tool", hold)
        self.assertIn("2026-09-07T19:15:00+09:00", hold)
        self.assertIn("installer-2026.dmg", hold)

    def test_reroutable_rows_offer_every_name(self) -> None:
        pending = _section(self.html, "pending")
        self.assertIn("dataset.parquet", pending)
        self.assertIn("web-prototype", pending)
        selects = re.findall(r"<select[^>]*class=\"gn-dest[^>]*>.*?</select>", pending, re.S)
        self.assertEqual(len(selects), 2)
        for select in selects:
            values = re.findall(r'<option value="([^"]+)"', select)
            self.assertEqual(sorted(values), sorted(self.plan["names"].keys()))
            self.assertIn('data-original="inbox.pending"', select)
            self.assertIn('<option value="inbox.pending" selected>', select)
        self.assertIn("git-repo", pending)

    def test_move_rows_show_destination_and_size(self) -> None:
        move = _section(self.html, "move")
        self.assertIn("report.pdf", move)
        self.assertIn("20_知识库/文档资料/PDF", move)
        self.assertIn("2.3 MB", move)
        self.assertIn("api-key-backup.txt", move)
        self.assertIn(TEXT["zh"]["sensitive_label"], move)
        self.assertIn('data-action-id="9c1f0a7b2d3e4f55"', move)
        # pair / duplicate moves belong to their groups, not to this table
        self.assertNotIn("guide.pdf", move)
        self.assertNotIn("Archive.zip", move)

    def test_groups_render_options_with_default_choice(self) -> None:
        pair = _section(self.html, "pair")
        self.assertIn('data-group-id="pair-7d2c1e9f"', pair)
        self.assertIn(TEXT["zh"]["adopt_group"], pair)
        checked = re.findall(r'<input type="radio" class="gn-option" name="grp-pair-7d2c1e9f" value="([^"]+)"[^>]*checked', pair)
        self.assertEqual(checked, ["keep:4d5e6f7a8b9c0d1e"])
        self.assertIn('data-action-ids="d4e5f60718293a4b b2c3d40e5f607182"', pair)
        delete_option = re.search(r'<label class="choice needs-permanent"><input ([^>]*)>', pair)
        self.assertIsNotNone(delete_option)
        self.assertIn("disabled", delete_option.group(1))
        self.assertIn('data-kind="delete"', delete_option.group(1))

        duplicate = _section(self.html, "duplicate")
        self.assertIn('data-group-id="dup-3ba91c04"', duplicate)
        self.assertIn("guide (1).pdf", duplicate)

        regenerable = _section(self.html, "regenerable")
        self.assertIn('data-group-id="regen-5c1d77ab"', regenerable)
        self.assertIn('value="trash_all"', regenerable)
        self.assertIn('value="delete_all"', regenerable)

    def test_permanent_toggle_present_when_offered(self) -> None:
        self.assertIn('id="gn-permanent"', self.html)
        self.assertIn(TEXT["zh"]["toggle_permanent"], self.html)


class CapabilityTests(unittest.TestCase):
    def test_no_trash_backend_hides_trash_controls(self) -> None:
        plan = _load_plan()
        plan["capabilities"]["trash_backend"] = "none"
        html = render_report(plan, mode="static")
        self.assertIsNone(re.search(r'<input[^>]*data-kind="trash"', html))
        self.assertNotIn("> " + TEXT["zh"]["opt_trash"] + "</label>", html)
        self.assertIn("<p>" + TEXT["zh"]["no_trash_backend"] + "</p>", html)
        pair = _section(html, "pair")
        self.assertIn('value="keep_all"', pair)
        self.assertNotIn('value="keep:4d5e6f7a8b9c0d1e"', pair)

    def test_no_permanent_delete_offered_hides_toggle_and_delete_options(self) -> None:
        plan = _load_plan()
        plan["capabilities"]["permanent_delete_offered"] = False
        html = render_report(plan, mode="static")
        self.assertNotIn('id="gn-permanent"', html)
        self.assertIsNone(re.search(r'<input[^>]*data-kind="delete"', html))
        self.assertNotIn('value="delete_all"', html)
        self.assertNotIn("needs-permanent\"", html.split("<script", 1)[0].split("</style>", 1)[1])

    def test_serve_without_flag_disables_toggle(self) -> None:
        plan = _load_plan()
        plan["capabilities"]["permanent_delete_enabled"] = False
        html = render_report(plan, mode="serve", token="t")
        self.assertIn('<input type="checkbox" id="gn-permanent" disabled>', html)
        self.assertIn(TEXT["zh"]["permanent_not_enabled"], html)


class VisualRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = _load_plan()
        cls.pages = {
            "static-zh": render_report(cls.plan, mode="static"),
            "serve-zh": render_report(cls.plan, mode="serve", token="t"),
            "static-en": render_report(cls.plan, mode="static", lang="en"),
        }

    def test_no_traffic_light_classes(self) -> None:
        for name, html in self.pages.items():
            self.assertIsNone(re.search(r'class="[^"]*(红|黄|绿|red|yellow|green)', html), name)
            self.assertIsNone(re.search(r"[红黄绿]灯", html), name)

    def test_no_radius_no_gradient_no_shadow(self) -> None:
        for name, html in self.pages.items():
            for value in re.findall(r"border-radius\s*:\s*([^;}]+)", html):
                self.assertEqual(value.strip(), "0", "{0}: border-radius {1}".format(name, value))
            self.assertNotIn("linear-gradient", html, name)
            self.assertNotIn("radial-gradient", html, name)
            self.assertNotIn("box-shadow", html, name)

    def test_no_external_resources(self) -> None:
        for name, html in self.pages.items():
            cleaned = _strip_comments(html)
            self.assertNotIn("https://", cleaned, name)
            self.assertNotIn('src="http', cleaned, name)
            self.assertNotIn("<link", cleaned, name)
            self.assertNotIn("@import", cleaned, name)
            # the only http:// allowed is the plan text itself, never a resource
            for hit in re.findall(r"http://[^\s\"']+", cleaned):
                self.assertTrue(hit.startswith("http://127.0.0.1"), "{0}: {1}".format(name, hit))

    def test_single_accent_and_no_dark_mode(self) -> None:
        html = self.pages["static-zh"]
        self.assertIn("--gn-accent:#c8501e", html)
        self.assertNotIn("prefers-color-scheme", html)
        self.assertIn("@media print", html)
        self.assertNotIn("Georgia", html)

    def test_trash_buttons_are_not_red(self) -> None:
        html = self.pages["static-zh"]
        css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
        for color in re.findall(r"#[0-9a-fA-F]{3,6}\b", css):
            self.assertIn(color.lower(), {"#c8501e", "#b4481b", "#111111", "#6b6b6b", "#d9d9d9", "#ffffff", "#f5f5f5"})

    def test_embedded_plan_has_no_raw_angle_brackets(self) -> None:
        plan = _load_plan()
        plan["actions"][0]["filename"] = "</script><b>x</b>.pdf"
        for mode in ("static", "serve"):
            html = render_report(plan, mode=mode, token="t")
            block = re.search(r'<script id="gn-plan" type="application/json">(.*?)</script>', html, re.S).group(1)
            self.assertNotIn("<", block)
            self.assertNotIn(">", block)
            round_trip = json.loads(block)
            self.assertEqual(round_trip["actions"][0]["filename"], "</script><b>x</b>.pdf")
            self.assertEqual(round_trip["schema_version"], 2)

    def test_zh_copy_has_no_straight_double_quotes(self) -> None:
        for key, value in TEXT["zh"].items():
            self.assertNotIn('"', value, key)


class PrivacyTests(unittest.TestCase):
    """A report.html handed to somebody else must not name the user's account."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = _load_plan()
        cls.static = render_report(cls.plan, mode="static")
        cls.serve = render_report(cls.plan, mode="serve", token="test-token-value")

    def test_no_absolute_path_reaches_either_page(self) -> None:
        planned_home = str(paths.plan_home(self.plan))
        # the directory accounts live in, taken from the fixture rather than
        # spelled out: this repository does not carry absolute home paths
        accounts_dir = str(Path(planned_home).parent) + "/"

        for name, html in (("static", self.static), ("serve", self.serve)):
            self.assertNotIn(self.plan["source_root"], html, name)
            self.assertNotIn(self.plan["managed_dir"], html, name)
            self.assertNotIn(planned_home, html, name)
            self.assertNotIn(accounts_dir, html, name)
            self.assertNotIn(str(Path.home()), html, name)
            for action in self.plan["actions"]:
                self.assertNotIn(action["source"], html, name)
                if action.get("destination"):
                    self.assertNotIn(action["destination"], html, name)

    def test_the_embedded_plan_keeps_only_the_portable_twins(self) -> None:
        embedded = _embedded_plan(self.static)
        self.assertNotIn("source_root", embedded)
        self.assertNotIn("managed_dir", embedded)
        self.assertEqual(embedded["source_root_portable"], "$HOME/Downloads")
        self.assertEqual(embedded["managed_dir_portable"], self.plan["managed_dir_portable"])
        for action in embedded["actions"]:
            self.assertNotIn("source", action)
            self.assertNotIn("destination", action)
            self.assertTrue(action["source_portable"].startswith("$HOME/"))

    def test_the_page_still_shows_the_folder_and_every_row(self) -> None:
        self.assertIn("$HOME/Downloads", self.static)
        for action in self.plan["actions"]:
            self.assertIn(action["source_portable"], self.static)

    def test_render_does_not_mutate_the_caller_s_plan(self) -> None:
        plan = _load_plan()
        render_report(plan, mode="static")
        self.assertEqual(plan["source_root"], self.plan["source_root"])
        self.assertEqual(plan["actions"][0]["source"], self.plan["actions"][0]["source"])
        self.assertTrue(Path(plan["source_root"]).is_absolute())

    def test_referenced_in_form_is_rewritten_too(self) -> None:
        # form used to be exempt from the $HOME rewrite because it is the
        # literal text found in someone's config file; it no longer is.
        plan = copy.deepcopy(self.plan)
        home = str(paths.plan_home(plan))
        absolute_form = home + "/Downloads/backup-tool.sh"
        plan["actions"][0].setdefault("guard", {})["referenced_in"] = [
            {"file": home + "/.zshrc", "line": 7, "form": absolute_form}
        ]
        html = render_report(plan, mode="static")
        self.assertNotIn(absolute_form, html)
        self.assertIn("$HOME/Downloads/backup-tool.sh", html)


class LanguageTests(unittest.TestCase):
    def test_lang_defaults_to_plan_and_can_be_overridden(self) -> None:
        plan = _load_plan()
        zh = render_report(plan)
        en = render_report(plan, lang="en")
        self.assertIn(TEXT["zh"]["sec_move"], zh)
        self.assertIn(TEXT["en"]["sec_move"], en)
        self.assertIn('<html lang="en">', en)
        self.assertIn("Document filed by type into", en)
        self.assertIn("文档按类型归档到", zh)
        self.assertEqual(_groups(zh), _groups(en))

    def test_write_report_writes_static_page(self) -> None:
        import tempfile

        plan = _load_plan()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.html"
            write_report(plan, target, lang="en")
            html = target.read_text(encoding="utf-8")
            self.assertIn('<body data-mode="static"', html)
            self.assertIn(TEXT["en"]["btn_export"], html)


if __name__ == "__main__":
    unittest.main()
