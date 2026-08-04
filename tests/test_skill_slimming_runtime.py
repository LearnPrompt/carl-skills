from __future__ import annotations

import importlib.util
import json
import stat
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "skills" / "ops" / "skill-slimming" / "scripts" / "review_server.py"
SPEC = importlib.util.spec_from_file_location("skill_slimming_runtime", RUNTIME_PATH)
runtime = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(runtime)


def sample_inventory(changed_hash: str = "hash-a", include_new: bool = False) -> dict:
    skills = [
        {
            "skillId": "writer",
            "name": "writer",
            "description": "写作工作流",
            "contentHash": changed_hash,
            "sourceGroup": "Carl",
            "category": "内容与写作",
            "managementPolicy": "reviewable",
            "suggestedDecision": "global",
            "currentStartupTokens": 18,
            "shellStartupTokens": 4,
            "postCallTokens": 1200,
            "hosts": ["Codex"],
        },
        {
            "skillId": "deploy",
            "name": "deploy",
            "description": "发布和回滚",
            "contentHash": "hash-critical",
            "sourceGroup": "Ops",
            "category": "开发工程",
            "managementPolicy": "reviewable",
            "rareCritical": True,
            "suggestedDecision": "undecided",
            "currentStartupTokens": 8,
            "shellStartupTokens": 12,
            "postCallTokens": 2200,
        },
        {
            "skillId": "builtin",
            "name": "Codex builtin",
            "description": "宿主内置能力",
            "contentHash": "hash-managed",
            "sourceGroup": "Codex",
            "managementPolicy": "managed",
            "managementReason": "Codex 内置，只能由宿主管理",
            "ownershipTags": ["Codex 内置"],
            "currentStartupTokens": 3,
            "postCallTokens": 300,
        },
    ]
    if include_new:
        skills.append(
            {
                "skillId": "new-skill",
                "name": "new-skill",
                "description": "新加入能力",
                "contentHash": "hash-new",
                "sourceGroup": "Carl",
                "managementPolicy": "reviewable",
            }
        )
    return {
        "schemaVersion": 8,
        "auditId": "audit-test",
        "environmentId": "test-profile",
        "generatedAt": "2026-08-04T00:00:00Z",
        "projects": [{"id": "goodcase", "name": "GoodCase", "location": "/tmp/goodcase"}],
        "plugins": [{"id": "github", "enabled": True, "token": "must-not-survive"}],
        "mcps": [{"id": "browser", "connected": True, "env": {"SECRET": "must-not-survive"}}],
        "skills": skills,
    }


def valid_complete_state(inventory: dict) -> dict:
    state = runtime.initial_state(inventory)
    state["reviewStatus"] = "complete"
    for item in state["decisions"]:
        if item["skillId"] == "writer":
            item["decision"] = "global"
        elif item["skillId"] == "deploy":
            item["decision"] = "trigger"
            item["triggerTerms"] = ["准备发布", "回滚版本"]
            item["rareCriticalConfirmed"] = True
    return state


class RuntimeContractTests(unittest.TestCase):
    def test_normalization_preserves_measurement_and_management_boundaries(self) -> None:
        inventory = runtime.normalize_inventory(sample_inventory())
        self.assertEqual(inventory["counts"], {
            "skills": 3,
            "reviewable": 2,
            "managed": 1,
            "rareCritical": 1,
            "plugins": 1,
            "mcps": 1,
        })
        builtin = next(skill for skill in inventory["skills"] if skill["skillId"] == "builtin")
        self.assertEqual(builtin["managementPolicy"], "managed")
        self.assertEqual(builtin["suggestedDecision"], "undecided")
        self.assertEqual(builtin["tokenMeasurement"], "估算值")
        self.assertNotIn("token", inventory["plugins"][0])
        self.assertNotIn("env", inventory["mcps"][0])

    def test_trigger_requires_two_terms_and_rare_critical_confirmation(self) -> None:
        inventory = runtime.normalize_inventory(sample_inventory())
        state = runtime.initial_state(inventory)
        deploy = next(item for item in state["decisions"] if item["skillId"] == "deploy")
        deploy["decision"] = "trigger"
        deploy["triggerTerms"] = ["发布"]
        with self.assertRaisesRegex(runtime.ValidationError, "2–5"):
            runtime.validate_state(state, inventory)
        deploy["triggerTerms"] = ["准备发布", "回滚版本"]
        with self.assertRaisesRegex(runtime.ValidationError, "RARE_CRITICAL"):
            runtime.validate_state(state, inventory)
        deploy["rareCriticalConfirmed"] = True
        validated = runtime.validate_state(state, inventory)
        self.assertEqual(validated["reviewStatus"], "draft")

    def test_runtime_recomputes_declared_inventory_revision(self) -> None:
        raw = sample_inventory()
        raw["inventoryRevision"] = "stale-revision"
        inventory = runtime.normalize_inventory(raw)
        self.assertNotEqual(inventory["inventoryRevision"], "stale-revision")
        self.assertEqual(inventory["sourceInventoryRevision"], "stale-revision")

    def test_decision_content_hash_must_match_inventory(self) -> None:
        inventory = runtime.normalize_inventory(sample_inventory())
        state = runtime.initial_state(inventory)
        state["decisions"][0]["contentHash"] = "tampered"
        with self.assertRaisesRegex(runtime.ValidationError, "contentHash"):
            runtime.validate_state(state, inventory)

    def test_project_decision_requires_known_project(self) -> None:
        inventory = runtime.normalize_inventory(sample_inventory())
        state = runtime.initial_state(inventory)
        writer = next(item for item in state["decisions"] if item["skillId"] == "writer")
        writer["decision"] = "project"
        writer["projects"] = []
        with self.assertRaisesRegex(runtime.ValidationError, "至少一个项目"):
            runtime.validate_state(state, inventory)
        writer["projects"] = ["missing"]
        with self.assertRaisesRegex(runtime.ValidationError, "未知项目"):
            runtime.validate_state(state, inventory)

    def test_complete_requires_every_reviewable_skill_to_be_decided(self) -> None:
        inventory = runtime.normalize_inventory(sample_inventory())
        state = runtime.initial_state(inventory)
        state["reviewStatus"] = "complete"
        with self.assertRaisesRegex(runtime.ValidationError, "尚未完成复审"):
            runtime.validate_state(state, inventory)

    def test_state_is_private_atomic_and_restored(self) -> None:
        inventory = runtime.normalize_inventory(sample_inventory())
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "state"
            store = runtime.StateStore(root, "test-profile", inventory)
            saved = store.save(valid_complete_state(inventory))
            self.assertEqual(saved["reviewStatus"], "complete")
            mode = stat.S_IMODE(store.current_path.stat().st_mode)
            self.assertEqual(mode, 0o600)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)

            restored = runtime.StateStore(root, "test-profile", inventory)
            self.assertEqual(restored.state["reviewStatus"], "complete")
            self.assertEqual(
                next(item for item in restored.state["decisions"] if item["skillId"] == "deploy")["decision"],
                "trigger",
            )

    def test_changed_and_new_skills_are_reconciled_without_reusing_stale_decisions(self) -> None:
        first = runtime.normalize_inventory(sample_inventory())
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "state"
            store = runtime.StateStore(root, "test-profile", first)
            store.save(valid_complete_state(first))

            second = runtime.normalize_inventory(sample_inventory(changed_hash="hash-b", include_new=True))
            restored = runtime.StateStore(root, "test-profile", second)
            writer = next(item for item in restored.state["decisions"] if item["skillId"] == "writer")
            new_skill = next(item for item in restored.state["decisions"] if item["skillId"] == "new-skill")
            deploy = next(item for item in restored.state["decisions"] if item["skillId"] == "deploy")
            self.assertEqual(writer["decision"], "undecided")
            self.assertTrue(writer["needsReview"])
            self.assertEqual(new_skill["decision"], "undecided")
            self.assertEqual(deploy["decision"], "trigger")
            self.assertEqual(restored.state["reviewStatus"], "draft")

    def test_active_pointer_cannot_escape_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            runtime.atomic_write_json(
                root / "active.json",
                {"statePath": "/etc/passwd", "profile": "tampered"},
            )
            with self.assertRaisesRegex(runtime.ValidationError, "状态根目录之外"):
                runtime.read_saved_state(root, None)


class LoopbackServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.inventory = runtime.normalize_inventory(sample_inventory())
        self.store = runtime.StateStore(Path(self.temp.name), "test-profile", self.inventory)
        self.token = "test-secret-token"
        self.server = runtime.ReviewServer(("127.0.0.1", 0), self.store, self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path: str, method: str = "GET", data: dict | None = None, token: str | None = None, origin: str | None = None):
        headers = {}
        if token is not None:
            headers["X-Skill-Slimming-Token"] = token
        if origin is not None:
            headers["Origin"] = origin
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, method=method, data=body, headers=headers)
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, response.read(), response.headers

    def test_health_is_available_but_bootstrap_requires_token(self) -> None:
        status, body, _ = self.request("/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/api/bootstrap")
        self.assertEqual(context.exception.code, 401)
        status, body, _ = self.request("/api/bootstrap", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["inventory"]["counts"]["skills"], 3)

    def test_state_write_rejects_cross_origin_and_accepts_same_origin(self) -> None:
        state = valid_complete_state(self.inventory)
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request("/api/state", "PUT", state, self.token, "https://evil.example")
        self.assertEqual(context.exception.code, 403)
        status, body, _ = self.request("/api/state", "PUT", state, self.token, self.base)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_mutating_execution_endpoints_do_not_exist(self) -> None:
        request = urllib.request.Request(
            self.base + "/api/apply",
            method="POST",
            data=b"{}",
            headers={"X-Skill-Slimming-Token": self.token, "Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(context.exception.code, 405)

    def test_review_html_has_local_persistence_and_token_semantics_copy(self) -> None:
        status, body, headers = self.request(f"/?token={self.token}")
        html = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("全局入口 → 触发空壳", html)
        self.assertIn("两种方式都读完整 Skill", html)
        self.assertIn("我选好了", html)
        self.assertIn("自动保存到本机私有目录", html)
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()
