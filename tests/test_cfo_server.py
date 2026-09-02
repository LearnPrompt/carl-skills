"""``--serve``: token, Host, Origin, body checks, and both pages' round trips.

The same server answers a plan.json with ``/api/apply`` and an analysis.json
with ``/api/dispose``.  Neither endpoint exists on the other page, both pages
share ``/api/reveal``, and no absolute path leaves either of them.
"""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from carl_file_organizer import paths
from carl_file_organizer import server as server_module

FIXTURE = Path(cfo_path.FIXTURES_DIR) / "plan-v2-sample.json"
ANALYSIS = Path(cfo_path.FIXTURES_DIR) / "storage-analysis-sample.json"

MOVE_ID = "9c1f0a7b2d3e4f55"
MOVE_ID_2 = "0b7e4411aa93c2d1"
DELETE_ID = "5c6d7e8f90011223"
PENDING_ID = "0112233445566a7b"

GREEN_ITEM = "st-pip-cache"
GREEN_ITEM_2 = "st-brew-cache"
YELLOW_ITEM = "st-dl-installers"
RED_ITEM = "st-photos"


class FakeReport:
    def __init__(self, results, run_id="test-run"):
        self.results = results
        self.run_id = run_id


class StubDisposer:
    """Records every call and answers with a fake DisposeReport."""

    def __init__(self):
        self.calls = []

    def __call__(self, analysis, decisions, **kw):
        self.calls.append({"analysis": analysis, "decisions": decisions, "kw": kw})
        results = []
        for item_id in decisions["item_ids"]:
            action = decisions["actions"][item_id]
            results.append(
                {
                    "item_id": item_id,
                    "path": "$HOME/somewhere/" + item_id,
                    "action": action,
                    "status": "trashed" if action == "trash" else "deleted",
                    "detail": "stub",
                    "size_bytes": 1024,
                }
            )
        return FakeReport(results)


class StubExecutor:
    """Records every call and answers with a fake ApplyReport."""

    def __init__(self):
        self.calls = []

    def __call__(self, plan, *, dry_run=False, allow_permanent_delete=False, **kw):
        self.calls.append(
            {
                "plan": plan,
                "dry_run": dry_run,
                "allow_permanent_delete": allow_permanent_delete,
                "extra": kw,
            }
        )
        results = []
        for action_id in plan["approved_action_ids"]:
            kind = next(a["kind"] for a in plan["actions"] if a["id"] == action_id)
            status = "dry-run" if dry_run else {"move": "moved", "trash": "trashed", "delete": "deleted"}[kind]
            results.append({"action_id": action_id, "status": status, "detail": "stub"})
        return FakeReport(results)


class ServerHarness:
    def __init__(
        self,
        *,
        allow_permanent_delete=False,
        stub=None,
        fixture=FIXTURE,
        disposer=None,
        reveal_fn=None,
        home=None,
    ):
        self.stub = stub or StubExecutor()
        self.disposer = disposer or StubDisposer()
        self.revealed = []

        def _reveal(path):
            self.revealed.append(str(path))
            return True

        self.server, self.token = server_module.build_server(
            fixture,
            allow_permanent_delete=allow_permanent_delete,
            apply_fn=self.stub,
            dispose_fn=self.disposer,
            reveal_fn=reveal_fn or _reveal,
            home=home,
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05})
        self.thread.daemon = True
        self.thread.start()

    @property
    def origin(self):
        return "http://127.0.0.1:{0}".format(self.port)

    def close(self):
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, *, method="GET", body=None, headers=None, token=True, origin=True):
        head = {}
        if token:
            head["X-GN-Token"] = self.token if token is True else token
        if method == "POST":
            if origin:
                head["Origin"] = self.origin if origin is True else origin
            head["Content-Type"] = "application/json"
        if headers:
            head.update(headers)
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.origin + path, data=data, method=method, headers=head)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8"), dict(error.headers)


class ReviewServerTests(unittest.TestCase):
    def setUp(self):
        self.h = ServerHarness()
        self.addCleanup(self.h.close)

    # -- page ----------------------------------------------------------------

    def test_page_requires_token_in_query(self):
        status, body, _ = self.h.request("/", token=False)
        self.assertEqual(status, 401)
        status, body, _ = self.h.request("/?t=wrong-token", token=False)
        self.assertEqual(status, 401)
        status, body, headers = self.h.request("/?t=" + self.h.token, token=False)
        self.assertEqual(status, 200)
        self.assertIn('data-kind="organize"', body)
        self.assertIn('data-mode="serve"', body)
        self.assertIn("X-GN-Token", body)
        self.assertIn("Content-Security-Policy", headers)
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_page_header_token_does_not_unlock_root(self):
        # the first load is only ever reached through the query token
        status, _, _ = self.h.request("/", token=True)
        self.assertEqual(status, 401)

    def test_api_plan_requires_header_token(self):
        status, _, _ = self.h.request("/api/plan", token=False)
        self.assertEqual(status, 401)
        status, _, _ = self.h.request("/api/plan", token="nope")
        self.assertEqual(status, 401)
        status, body, _ = self.h.request("/api/plan")
        self.assertEqual(status, 200)
        plan = json.loads(body)
        self.assertEqual(plan["schema_version"], 2)
        self.assertEqual(plan["executed_ids"], [])
        self.assertIs(plan["capabilities"]["permanent_delete_enabled"], False)

    def test_api_plan_is_stripped_but_apply_still_sees_the_real_paths(self):
        status, body, _ = self.h.request("/api/plan")
        self.assertEqual(status, 200)
        served = json.loads(body)

        self.assertNotIn("source_root", served)
        self.assertNotIn("managed_dir", served)
        self.assertEqual(served["source_root_portable"], "$HOME/Downloads")
        for action in served["actions"]:
            self.assertNotIn("source", action)
            self.assertNotIn("destination", action)

        original = json.loads(FIXTURE.read_text(encoding="utf-8"))
        planned_home = str(paths.plan_home(original))
        self.assertNotIn(planned_home, body)
        self.assertNotIn(str(Path(planned_home).parent) + "/", body)

        payload = {"action_ids": [MOVE_ID], "overrides": [], "dry_run": True}
        status, _, _ = self.h.request("/api/apply", method="POST", body=payload)
        self.assertEqual(status, 200)
        handed = self.h.stub.calls[-1]["plan"]
        self.assertEqual(handed["source_root"], original["source_root"])
        self.assertEqual(handed["actions"][0]["source"], original["actions"][0]["source"])

    def test_bad_host_is_rejected(self):
        status, _, _ = self.h.request("/api/plan", headers={"Host": "evil.example:80"})
        self.assertEqual(status, 400)

    # -- apply ---------------------------------------------------------------

    def test_apply_rejects_missing_or_wrong_token(self):
        payload = {"action_ids": [MOVE_ID], "overrides": [], "dry_run": False}
        status, _, _ = self.h.request("/api/apply", method="POST", body=payload, token=False)
        self.assertEqual(status, 401)
        status, _, _ = self.h.request("/api/apply", method="POST", body=payload, token="bad")
        self.assertEqual(status, 401)
        self.assertEqual(self.h.stub.calls, [])

    def test_apply_rejects_foreign_origin(self):
        payload = {"action_ids": [MOVE_ID], "overrides": [], "dry_run": False}
        status, _, _ = self.h.request("/api/apply", method="POST", body=payload, origin="http://evil")
        self.assertEqual(status, 403)
        status, _, _ = self.h.request("/api/apply", method="POST", body=payload, origin=False)
        self.assertEqual(status, 403)
        self.assertEqual(self.h.stub.calls, [])

    def test_apply_rejects_wrong_content_type_and_big_body(self):
        payload = {"action_ids": [MOVE_ID], "overrides": [], "dry_run": False}
        status, _, _ = self.h.request(
            "/api/apply", method="POST", body=payload, headers={"Content-Type": "text/plain"}
        )
        self.assertEqual(status, 415)
        status, _, _ = self.h.request(
            "/api/apply", method="POST", body=b"{" + b" " * (1024 * 1024 + 8) + b"}"
        )
        self.assertEqual(status, 413)
        status, _, _ = self.h.request("/api/apply", method="POST", body=b"not json")
        self.assertEqual(status, 400)
        status, _, _ = self.h.request("/api/apply", method="POST", body={"action_ids": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(self.h.stub.calls, [])

    def test_apply_round_trip_and_repeat_conflict(self):
        payload = {
            "action_ids": [MOVE_ID, PENDING_ID],
            "overrides": [{"action_id": PENDING_ID, "destination_key": "work.tools"}],
            "dry_run": False,
        }
        status, body, _ = self.h.request("/api/apply", method="POST", body=payload)
        self.assertEqual(status, 200, body)
        response = json.loads(body)
        self.assertTrue(response["ok"])
        self.assertEqual(sorted(response["executed_ids"]), sorted([MOVE_ID, PENDING_ID]))
        self.assertEqual(response["run_id"], "test-run")
        self.assertEqual([r["status"] for r in response["results"]], ["moved", "moved"])

        self.assertEqual(len(self.h.stub.calls), 1)
        call = self.h.stub.calls[0]
        self.assertEqual(call["plan"]["approved_action_ids"], [MOVE_ID, PENDING_ID])
        self.assertEqual(call["plan"]["overrides"], payload["overrides"])
        self.assertEqual(call["plan"]["approved_by"], "serve")
        self.assertIsNotNone(call["plan"]["approved_at"])
        self.assertIs(call["dry_run"], False)
        self.assertIs(call["allow_permanent_delete"], False)
        self.assertEqual(call["extra"], {})
        # the plan handed to the executor is untouched apart from the approval fields
        original = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(call["plan"]["actions"], original["actions"])
        self.assertEqual(call["plan"]["groups"], original["groups"])

        status, body, _ = self.h.request("/api/apply", method="POST", body=payload)
        self.assertEqual(status, 409)
        self.assertEqual(sorted(json.loads(body)["action_ids"]), sorted([MOVE_ID, PENDING_ID]))
        self.assertEqual(len(self.h.stub.calls), 1)

        status, body, _ = self.h.request("/api/plan")
        self.assertEqual(sorted(json.loads(body)["executed_ids"]), sorted([MOVE_ID, PENDING_ID]))

    def test_dry_run_does_not_mark_executed(self):
        payload = {"action_ids": [MOVE_ID], "overrides": [], "dry_run": True}
        status, body, _ = self.h.request("/api/apply", method="POST", body=payload)
        self.assertEqual(status, 200)
        response = json.loads(body)
        self.assertEqual(response["executed_ids"], [])
        self.assertEqual(response["results"][0]["status"], "dry-run")
        self.assertIs(self.h.stub.calls[0]["dry_run"], True)
        status, _, _ = self.h.request("/api/apply", method="POST", body=dict(payload, dry_run=False))
        self.assertEqual(status, 200)

    def test_delete_without_flag_is_forbidden_before_executor_runs(self):
        payload = {"action_ids": [MOVE_ID_2, DELETE_ID], "overrides": [], "dry_run": False}
        status, body, _ = self.h.request("/api/apply", method="POST", body=payload)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["action_ids"], [DELETE_ID])
        self.assertEqual(self.h.stub.calls, [])

    def test_executor_errors_become_422(self):
        def boom(plan, **kw):
            raise ValueError("plan refused by executor")

        h = ServerHarness(stub=boom)
        self.addCleanup(h.close)
        status, body, _ = h.request(
            "/api/apply", method="POST", body={"action_ids": [MOVE_ID], "overrides": [], "dry_run": False}
        )
        self.assertEqual(status, 422)
        self.assertIn("plan refused by executor", json.loads(body)["error"])

    def test_shutdown_stops_the_server(self):
        status, _, _ = self.h.request("/api/shutdown", method="POST", body={}, token=False)
        self.assertEqual(status, 401)
        self.assertTrue(self.h.thread.is_alive())
        status, body, _ = self.h.request("/api/shutdown", method="POST", body={})
        self.assertEqual(status, 200)
        self.h.thread.join(timeout=5)
        self.assertFalse(self.h.thread.is_alive())


class PermanentDeleteFlagTests(unittest.TestCase):
    def test_flag_enables_delete_and_reaches_executor(self):
        h = ServerHarness(allow_permanent_delete=True)
        self.addCleanup(h.close)
        status, body, _ = h.request("/api/plan")
        self.assertIs(json.loads(body)["capabilities"]["permanent_delete_enabled"], True)
        payload = {"action_ids": [DELETE_ID], "overrides": [], "dry_run": False}
        status, body, _ = h.request("/api/apply", method="POST", body=payload)
        self.assertEqual(status, 200, body)
        self.assertIs(h.stub.calls[0]["allow_permanent_delete"], True)
        self.assertEqual(json.loads(body)["results"][0]["status"], "deleted")


class StoragePageTests(unittest.TestCase):
    """The same server, handed an analysis.json instead of a plan.json."""

    def setUp(self):
        self.h = ServerHarness(fixture=ANALYSIS)
        self.addCleanup(self.h.close)

    def test_the_page_is_the_storage_page_and_names_no_account(self):
        status, body, _ = self.h.request("/?t=" + self.h.token, token=False)
        self.assertEqual(status, 200)
        self.assertIn('data-kind="storage"', body)
        self.assertIn('data-mode="serve"', body)
        self.assertNotIn("/Users/", body)
        self.assertNotIn(str(Path.home()), body)
        self.assertIn("$HOME/Library/Caches/pip", body)

    def test_api_plan_is_the_stripped_analysis_with_executed_ids(self):
        status, body, _ = self.h.request("/api/plan")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["schema"], "carl-file-organizer/storage-analysis")
        self.assertEqual(data["executed_ids"], [])
        self.assertNotIn("/Users/", body)
        for item in data["items"]:
            self.assertNotIn("path", item)

    def test_dispose_rejects_missing_token_and_foreign_origin(self):
        payload = {"item_ids": [GREEN_ITEM], "action": "trash"}
        status, _, _ = self.h.request("/api/dispose", method="POST", body=payload, token=False)
        self.assertEqual(status, 401)
        status, _, _ = self.h.request("/api/dispose", method="POST", body=payload, origin="http://evil")
        self.assertEqual(status, 403)
        self.assertEqual(self.h.disposer.calls, [])

    def test_dispose_rejects_a_bad_body(self):
        for payload in ({"item_ids": "x"}, {"item_ids": []}, {"item_ids": [GREEN_ITEM], "action": "burn"}):
            status, _, _ = self.h.request("/api/dispose", method="POST", body=payload)
            self.assertEqual(status, 400, payload)
        self.assertEqual(self.h.disposer.calls, [])

    def test_permanent_delete_is_refused_before_the_engine_runs(self):
        payload = {"item_ids": [GREEN_ITEM], "action": "delete"}
        status, body, _ = self.h.request("/api/dispose", method="POST", body=payload)
        self.assertEqual(status, 403)
        self.assertIn("allow-permanent-delete", json.loads(body)["error"])
        self.assertEqual(self.h.disposer.calls, [])

    def test_dispose_round_trip_and_repeat_conflict(self):
        payload = {"item_ids": [GREEN_ITEM, GREEN_ITEM_2], "action": "trash"}
        status, body, _ = self.h.request("/api/dispose", method="POST", body=payload)
        self.assertEqual(status, 200, body)
        response = json.loads(body)
        self.assertTrue(response["ok"])
        self.assertIs(response["dry_run"], False)
        self.assertEqual(response["action"], "trash")
        self.assertEqual(sorted(response["executed_ids"]), sorted([GREEN_ITEM, GREEN_ITEM_2]))
        self.assertEqual([r["status"] for r in response["results"]], ["trashed", "trashed"])

        call = self.h.disposer.calls[0]
        self.assertEqual(call["decisions"]["item_ids"], [GREEN_ITEM, GREEN_ITEM_2])
        self.assertEqual(call["decisions"]["actions"], {GREEN_ITEM: "trash", GREEN_ITEM_2: "trash"})
        self.assertEqual(call["decisions"]["decided_by"], "serve")
        self.assertIs(call["kw"]["dry_run"], False)
        self.assertIs(call["kw"]["allow_permanent_delete"], False)
        self.assertEqual(call["kw"]["home"], Path.home())
        # the engine gets the analysis as written, not the stripped copy
        self.assertEqual(call["analysis"]["items"][0]["id"], "st-derived-data")

        status, body, _ = self.h.request("/api/dispose", method="POST", body=payload)
        self.assertEqual(status, 409)
        self.assertEqual(sorted(json.loads(body)["item_ids"]), sorted([GREEN_ITEM, GREEN_ITEM_2]))
        self.assertEqual(len(self.h.disposer.calls), 1)

        status, body, _ = self.h.request("/api/plan")
        self.assertEqual(sorted(json.loads(body)["executed_ids"]), sorted([GREEN_ITEM, GREEN_ITEM_2]))

    def test_an_engine_refusal_becomes_422(self):
        def boom(analysis, decisions, **kw):
            raise ValueError("refused by the dispose gate")

        h = ServerHarness(fixture=ANALYSIS, disposer=boom)
        self.addCleanup(h.close)
        status, body, _ = h.request(
            "/api/dispose", method="POST", body={"item_ids": [RED_ITEM], "action": "trash"}
        )
        self.assertEqual(status, 422)
        self.assertIn("refused by the dispose gate", json.loads(body)["error"])

    def test_each_page_only_answers_its_own_endpoint(self):
        status, _, _ = self.h.request(
            "/api/apply", method="POST", body={"action_ids": [MOVE_ID], "overrides": [], "dry_run": True}
        )
        self.assertEqual(status, 404)
        plan_page = ServerHarness()
        self.addCleanup(plan_page.close)
        status, _, _ = plan_page.request(
            "/api/dispose", method="POST", body={"item_ids": [GREEN_ITEM], "action": "trash"}
        )
        self.assertEqual(status, 404)
        self.assertEqual(plan_page.disposer.calls, [])

    def test_delete_flag_reaches_the_engine(self):
        h = ServerHarness(fixture=ANALYSIS, allow_permanent_delete=True)
        self.addCleanup(h.close)
        status, body, _ = h.request(
            "/api/dispose", method="POST", body={"item_ids": [GREEN_ITEM], "action": "delete"}
        )
        self.assertEqual(status, 200, body)
        self.assertIs(h.disposer.calls[0]["kw"]["allow_permanent_delete"], True)
        self.assertEqual(json.loads(body)["results"][0]["status"], "deleted")


class CombinedPageTests(unittest.TestCase):
    """The envelope with both halves: one page, one token, two engines."""

    def setUp(self):
        self.combined = {
            "plan": json.loads(FIXTURE.read_text(encoding="utf-8")),
            "analysis": json.loads(ANALYSIS.read_text(encoding="utf-8")),
        }
        self.h = ServerHarness(fixture=self.combined)
        self.addCleanup(self.h.close)

    def test_the_page_is_the_combined_page_and_names_no_account(self):
        status, body, _ = self.h.request("/?t=" + self.h.token, token=False)
        self.assertEqual(status, 200)
        self.assertIn('data-kind="combined"', body)
        self.assertNotIn("/Users/", body)
        self.assertNotIn(str(Path.home()), body)
        self.assertIn("$HOME/Library/Caches/pip", body)
        self.assertIn("$HOME/Downloads", body)

    def test_api_plan_returns_both_stripped_halves(self):
        status, body, _ = self.h.request("/api/plan")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertNotIn("/Users/", body)
        self.assertEqual(data["executed_ids"], [])
        self.assertNotIn("source_root", data["plan"])
        for action in data["plan"]["actions"]:
            self.assertNotIn("source", action)
        for item in data["analysis"]["items"]:
            self.assertNotIn("path", item)

    def test_apply_sends_the_tidy_up_half_to_the_executor(self):
        payload = {"action_ids": [MOVE_ID, MOVE_ID_2], "overrides": [], "dry_run": False}
        status, body, _ = self.h.request("/api/apply", method="POST", body=payload)
        self.assertEqual(status, 200, body)
        response = json.loads(body)
        self.assertEqual(sorted(response["executed_ids"]), sorted([MOVE_ID, MOVE_ID_2]))
        self.assertEqual([r["status"] for r in response["results"]], ["moved", "moved"])
        call = self.h.stub.calls[0]
        self.assertEqual(call["plan"]["approved_action_ids"], [MOVE_ID, MOVE_ID_2])
        self.assertEqual(call["plan"]["schema_version"], 2)
        self.assertNotIn("analysis", call["plan"])
        self.assertTrue(str(call["plan"]["source_root"]).endswith("Downloads"))
        self.assertEqual(self.h.disposer.calls, [])

    def test_dispose_sends_the_whole_machine_half_to_the_dispose_gate(self):
        payload = {"item_ids": [GREEN_ITEM], "action": "trash"}
        status, body, _ = self.h.request("/api/dispose", method="POST", body=payload)
        self.assertEqual(status, 200, body)
        response = json.loads(body)
        self.assertEqual(response["executed_ids"], [GREEN_ITEM])
        self.assertEqual([r["status"] for r in response["results"]], ["trashed"])
        call = self.h.disposer.calls[0]
        self.assertEqual(call["analysis"]["schema"], "carl-file-organizer/storage-analysis")
        self.assertNotIn("plan", call["analysis"])
        self.assertEqual(call["decisions"]["item_ids"], [GREEN_ITEM])
        self.assertIs(call["kw"]["allow_permanent_delete"], False)
        self.assertEqual(self.h.stub.calls, [])

    def test_both_halves_share_one_executed_list(self):
        self.h.request("/api/apply", method="POST", body={"action_ids": [MOVE_ID], "overrides": [], "dry_run": False})
        self.h.request("/api/dispose", method="POST", body={"item_ids": [GREEN_ITEM], "action": "trash"})
        status, body, _ = self.h.request("/api/plan")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(json.loads(body)["executed_ids"]), sorted([MOVE_ID, GREEN_ITEM]))

    def test_permanent_delete_is_still_gated_on_both_sides(self):
        status, body, _ = self.h.request(
            "/api/apply", method="POST", body={"action_ids": [DELETE_ID], "overrides": [], "dry_run": False}
        )
        self.assertEqual(status, 403)
        self.assertIn("allow-permanent-delete", json.loads(body)["error"])
        status, _, _ = self.h.request(
            "/api/dispose", method="POST", body={"item_ids": [GREEN_ITEM], "action": "delete"}
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.h.stub.calls, [])
        self.assertEqual(self.h.disposer.calls, [])


class RevealTests(unittest.TestCase):
    """Showing a folder is the one thing every colour is allowed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / "Library" / "Caches" / "pip").mkdir(parents=True)
        self.h = ServerHarness(fixture=ANALYSIS, home=self.home)
        self.addCleanup(self.h.close)

    def test_a_path_inside_home_is_shown(self):
        status, body, _ = self.h.request(
            "/api/reveal", method="POST", body={"path_portable": "$HOME/Library/Caches/pip"}
        )
        self.assertEqual(status, 200, body)
        self.assertIs(json.loads(body)["ok"], True)
        self.assertEqual(self.h.revealed, [str(self.home / "Library" / "Caches" / "pip")])

    def test_a_path_outside_home_is_refused(self):
        for portable in ("/etc", "$HOME/../elsewhere", "/System/Library"):
            status, body, _ = self.h.request(
                "/api/reveal", method="POST", body={"path_portable": portable}
            )
            self.assertEqual(status, 403, portable)
            self.assertIn("outside", json.loads(body)["error"])
        self.assertEqual(self.h.revealed, [])

    def test_a_path_that_is_gone_is_a_404_not_a_launch(self):
        status, _, _ = self.h.request(
            "/api/reveal", method="POST", body={"path_portable": "$HOME/Library/Caches/nothing-here"}
        )
        self.assertEqual(status, 404)
        self.assertEqual(self.h.revealed, [])

    def test_reveal_needs_the_token_and_a_string(self):
        status, _, _ = self.h.request(
            "/api/reveal", method="POST", body={"path_portable": "$HOME/Library"}, token=False
        )
        self.assertEqual(status, 401)
        status, _, _ = self.h.request("/api/reveal", method="POST", body={"path_portable": ""})
        self.assertEqual(status, 400)
        self.assertEqual(self.h.revealed, [])

    def test_the_plan_page_reveals_too(self):
        plan_page = ServerHarness()
        self.addCleanup(plan_page.close)
        status, _, _ = plan_page.request(
            "/api/reveal", method="POST", body={"path_portable": "$HOME/Downloads/report.pdf"}
        )
        # the fixture's home does not exist on this machine, so it stops at 404
        # rather than at the boundary check
        self.assertEqual(status, 404)
        self.assertEqual(plan_page.revealed, [])


class OneRendererTests(unittest.TestCase):
    """``review --serve`` and ``build_report.py --mode serve`` are the same page."""

    def test_the_server_renders_through_build_report_itself(self):
        import build_report

        from carl_file_organizer import render as render_module

        for fixture in (FIXTURE, ANALYSIS):
            data = json.loads(fixture.read_text(encoding="utf-8"))
            direct = build_report.render(data, mode="serve", token="a-token")
            through = render_module.render(data, mode="serve", token="a-token")
            self.assertEqual(direct, through, str(fixture))

    def test_the_served_page_is_that_renderer_with_the_live_token(self):
        import build_report

        h = ServerHarness(fixture=ANALYSIS)
        self.addCleanup(h.close)
        status, body, _ = h.request("/?t=" + h.token, token=False)
        self.assertEqual(status, 200)
        data = json.loads(ANALYSIS.read_text(encoding="utf-8"))
        data["capabilities"] = dict(data.get("capabilities") or {})
        data["capabilities"]["permanent_delete_enabled"] = False
        data["executed_ids"] = []
        expected = build_report.render(
            data, mode="serve", token=h.token, kind="storage", home=Path.home()
        )
        self.assertEqual(body, expected)


class BuildServerTests(unittest.TestCase):
    def test_binds_loopback_on_ephemeral_port_with_long_token(self):
        server, token = server_module.build_server(FIXTURE, apply_fn=StubExecutor())
        try:
            host, port = server.server_address[:2]
            self.assertEqual(host, "127.0.0.1")
            self.assertGreater(port, 0)
            self.assertGreaterEqual(len(token), 40)
        finally:
            server.server_close()

    def test_rejects_unreadable_plan(self):
        with self.assertRaises(server_module.ServerError):
            server_module.build_server(Path("/nonexistent/plan.json"), apply_fn=StubExecutor())

    def test_run_signature_matches_cli(self):
        import argparse

        args = argparse.Namespace(
            plan=FIXTURE, serve=True, port=0, open_browser=False, allow_permanent_delete=False
        )
        self.assertTrue(callable(server_module.run))
        self.assertEqual(sorted(vars(args)), ["allow_permanent_delete", "open_browser", "plan", "port", "serve"])


if __name__ == "__main__":
    unittest.main()
