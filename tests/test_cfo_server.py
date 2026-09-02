"""review --serve: token, Host, Origin, body checks and the apply round trip."""

from __future__ import annotations

import cfo_path  # noqa: F401 - puts the skill's scripts dir on sys.path

import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from carl_file_organizer import paths
from carl_file_organizer import server as server_module

FIXTURE = Path(cfo_path.FIXTURES_DIR) / "plan-v2-sample.json"

MOVE_ID = "9c1f0a7b2d3e4f55"
MOVE_ID_2 = "0b7e4411aa93c2d1"
DELETE_ID = "5c6d7e8f90011223"
PENDING_ID = "0112233445566a7b"


class FakeReport:
    def __init__(self, results, run_id="test-run"):
        self.results = results
        self.run_id = run_id


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
    def __init__(self, *, allow_permanent_delete=False, stub=None):
        self.stub = stub or StubExecutor()
        self.server, self.token = server_module.build_server(
            FIXTURE, allow_permanent_delete=allow_permanent_delete, apply_fn=self.stub
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
        self.assertIn('<body data-mode="serve"', body)
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
