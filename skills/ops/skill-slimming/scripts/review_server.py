#!/usr/bin/env python3
"""Loopback-only review runtime for the Skill Slimming workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import threading
import unicodedata
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


SCHEMA_VERSION = 1
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_HISTORY = 50
VALID_DECISIONS = {"undecided", "global", "project", "trigger"}
VALID_REVIEW_STATUSES = {"draft", "complete"}
GATE_PROMPT = "这个能力对应的 Skill 已归档，是否要为当前项目临时加载？"

SCRIPT_DIR = Path(__file__).resolve().parent
ASSET_PATH = SCRIPT_DIR.parent / "assets" / "review.html"


class ValidationError(ValueError):
    """Raised when inventory or state data violates the runtime contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def safe_profile_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized or len(normalized) > 80 or not re.fullmatch(r"[\w.-]+", normalized, re.UNICODE):
        raise ValidationError("profile 只能包含字母、数字、下划线、点和连字符，且长度不超过 80。")
    return normalized


def as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, result)


def as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = as_text(item)
        if text and text not in result:
            result.append(text)
    return result


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "enabled"}
    return bool(value)


def first_present(source: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


SENSITIVE_KEY_MARKERS = ("token", "secret", "cookie", "password", "authorization")


def _is_sensitive_key(key: Any) -> bool:
    return any(marker in str(key).casefold() for marker in SENSITIVE_KEY_MARKERS)


def scrub_sensitive(value: Any) -> Any:
    """Recursively strip any dict key whose casefolded name contains a sensitive marker.

    Mirrors the allowlist-style redaction normalize_component() already applies to
    plugins/mcps (only known-safe fields survive), but as a generic recursive pass
    usable for arbitrary external JSON such as a verification receipt.
    """
    if isinstance(value, dict):
        return {
            key: scrub_sensitive(item)
            for key, item in value.items()
            if not _is_sensitive_key(key)
        }
    if isinstance(value, list):
        return [scrub_sensitive(item) for item in value]
    return value


def normalize_project(raw: Any, index: int) -> dict[str, str]:
    if isinstance(raw, str):
        raw = {"id": raw, "name": raw}
    if not isinstance(raw, dict):
        raise ValidationError(f"projects[{index}] 必须是对象或字符串。")
    project_id = as_text(first_present(raw, "id", "projectId", "name"))
    name = as_text(first_present(raw, "name", "label", "id"))
    if not project_id or not name:
        raise ValidationError(f"projects[{index}] 缺少 id 或 name。")
    return {
        "id": project_id,
        "name": name,
        "location": as_text(first_present(raw, "location", "path")),
    }


def normalize_skill(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError(f"skills[{index}] 必须是对象。")

    name = as_text(first_present(raw, "name", "displayName", "id"))
    if not name:
        raise ValidationError(f"skills[{index}] 缺少 name。")

    identity_basis = {
        "name": unicodedata.normalize("NFKC", name).casefold(),
        "entry": as_text(first_present(raw, "entryPath", "path", "realPath")),
        "source": as_text(first_present(raw, "sourceRef", "sourceGroup", "sourceLabel")),
    }
    skill_id = as_text(first_present(raw, "skillId", "stableId", "id"))
    if not skill_id:
        skill_id = "skill-" + sha256_json(identity_basis)[:16]

    summary = as_text(first_present(raw, "summary", "description", "capabilitySummary"), "暂无能力摘要")
    source_group = as_text(first_present(raw, "sourceGroup", "sourceLabel", "source"), "来源待确认")
    source_label = as_text(first_present(raw, "sourceLabel", "sourceGroup", "source"), source_group)
    content_hash = as_text(first_present(raw, "contentHash", "sha256", "skillHash"))
    if not content_hash:
        content_hash = sha256_json(
            {
                "name": name,
                "summary": summary,
                "entry": identity_basis["entry"],
                "source": source_group,
            }
        )

    management_policy = as_text(first_present(raw, "managementPolicy", "policy"), "reviewable")
    if management_policy not in {"reviewable", "managed", "review-only"}:
        management_policy = "review-only"

    suggested = as_text(first_present(raw, "suggestedDecision", "decision"), "undecided")
    if suggested not in VALID_DECISIONS:
        suggested = "undecided"
    if management_policy != "reviewable":
        suggested = "undecided"

    startup = as_int(first_present(raw, "currentStartupTokens", "startupTokens"))
    shell = as_int(first_present(raw, "shellStartupTokens", "triggerStartupTokens"))
    post_call = as_int(first_present(raw, "postCallTokens", "fullSkillTokens"))
    token_measurement = as_text(
        first_present(raw, "tokenMeasurement", "tokenMeasurementLabel"), "估算值"
    )

    ownership = as_text_list(first_present(raw, "ownershipTags", "ownershipTag", "owners"))
    hosts = as_text_list(first_present(raw, "hosts", "host"))
    trigger_terms = as_text_list(first_present(raw, "triggers", "triggerTerms", "trigger"))[:5]

    host_override_state = as_text(first_present(raw, "hostOverrideState"), "unknown")
    if host_override_state not in {"on", "off", "unknown"}:
        host_override_state = "unknown"

    entry_health = as_text(first_present(raw, "entryHealth"), "unknown")
    if entry_health not in {"ok", "broken-symlink", "cross-machine-path", "unknown"}:
        entry_health = "unknown"

    global_tier = as_text(first_present(raw, "globalTier"), "unknown")
    if global_tier not in {"core", "conservative", "unknown"}:
        global_tier = "unknown"

    return {
        "skillId": skill_id,
        "name": name,
        "summary": summary,
        "entryPath": identity_basis["entry"],
        "contentHash": content_hash,
        "sourceGroup": source_group,
        "sourceLabel": source_label,
        "sourceConfidence": as_text(first_present(raw, "sourceConfidence"), "unknown"),
        "category": as_text(first_present(raw, "category", "purposeCategory"), "其他与待分类"),
        "specificUse": as_text(first_present(raw, "specificUse", "purpose"), "AI 辅助分类"),
        "managementPolicy": management_policy,
        "managementReason": as_text(first_present(raw, "managementReason")),
        "ownershipTags": ownership,
        "hosts": hosts,
        "rareCritical": as_bool(first_present(raw, "rareCritical", "rare_critical", default=False)),
        "suggestedDecision": suggested,
        "currentStartupTokens": startup,
        "shellStartupTokens": shell,
        "postCallTokens": post_call,
        "tokenMeasurement": token_measurement,
        "actualCallCount": first_present(raw, "actualCallCount", "usageCount"),
        "usageMeasurement": as_text(first_present(raw, "usageMeasurement"), "不可用"),
        "lastUsedAt": first_present(raw, "lastUsedAt", "lastUsed"),
        "lastUsedMeasurement": as_text(first_present(raw, "lastUsedMeasurement"), "不可用"),
        "triggerTerms": trigger_terms,
        "appliedProjects": as_text_list(first_present(raw, "appliedProjects", "projects")),
        "hostOverrideState": host_override_state,
        "entryHealth": entry_health,
        "globalTier": global_tier,
    }


def normalize_component(raw: Any, index: int, kind: str) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"id": raw, "name": raw}
    if not isinstance(raw, dict):
        raise ValidationError(f"{kind}[{index}] 必须是对象或字符串。")
    component_id = as_text(first_present(raw, "id", "pluginId", "serverId", "name"))
    name = as_text(first_present(raw, "name", "label", "id"), component_id)
    if not component_id:
        raise ValidationError(f"{kind}[{index}] 缺少 id 或 name。")
    result: dict[str, Any] = {
        "id": component_id,
        "name": name,
        "source": as_text(first_present(raw, "source", "marketplace", "provider")),
        "status": as_text(first_present(raw, "status"), "unknown"),
        "lastUsedAt": first_present(raw, "lastUsedAt", "lastUsed"),
        "lastUsedMeasurement": as_text(first_present(raw, "lastUsedMeasurement"), "不可用"),
    }
    for key in ("installed", "enabled", "connected"):
        if key in raw:
            result[key] = as_bool(raw[key])
    for output_key, input_keys in (
        ("toolCount", ("toolCount", "tools")),
        ("skillCount", ("skillCount", "directSkillEntries")),
    ):
        value = first_present(raw, *input_keys)
        if isinstance(value, list):
            value = len(value)
        if value is not None:
            result[output_key] = as_int(value)
    return result


def normalize_inventory(raw: Any, profile: str | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError("inventory 顶层必须是 JSON 对象。")
    raw_skills = raw.get("skills")
    if not isinstance(raw_skills, list):
        raise ValidationError("inventory.skills 必须是数组。")

    projects_raw = first_present(raw, "projects", "projectCatalog", default=[])
    if isinstance(projects_raw, dict):
        projects_raw = projects_raw.get("projects", [])
    if not isinstance(projects_raw, list):
        raise ValidationError("inventory.projects 必须是数组。")

    projects = [normalize_project(item, index) for index, item in enumerate(projects_raw)]
    skills = [normalize_skill(item, index) for index, item in enumerate(raw_skills)]

    ids = [skill["skillId"] for skill in skills]
    if len(ids) != len(set(ids)):
        raise ValidationError("inventory 中存在重复 skillId；请在审计结果中提供稳定且唯一的 ID。")

    environment_id = safe_profile_name(
        profile or as_text(first_present(raw, "environmentId", "profileId"), "default")
    )
    revision_basis = [
        {"skillId": skill["skillId"], "contentHash": skill["contentHash"]}
        for skill in sorted(skills, key=lambda item: item["skillId"])
    ]
    computed_revision = sha256_json(revision_basis)
    declared_revision = as_text(raw.get("inventoryRevision"))
    inventory_revision = computed_revision
    audit_id = as_text(raw.get("auditId")) or f"audit-{inventory_revision[:12]}"

    plugins = raw.get("plugins", [])
    mcps = first_present(raw, "mcps", "mcpServers", default=[])
    if isinstance(plugins, dict):
        plugins = plugins.get("plugins", [])
    if isinstance(mcps, dict):
        mcps = mcps.get("servers", mcps.get("mcps", []))
    if not isinstance(plugins, list):
        plugins = []
    if not isinstance(mcps, list):
        mcps = []
    plugins = [normalize_component(item, index, "plugins") for index, item in enumerate(plugins)]
    mcps = [normalize_component(item, index, "mcps") for index, item in enumerate(mcps)]

    return {
        "schemaVersion": SCHEMA_VERSION,
        "auditId": audit_id,
        "environmentId": environment_id,
        "inventoryRevision": inventory_revision,
        "sourceInventoryRevision": declared_revision or None,
        "generatedAt": as_text(raw.get("generatedAt"), utc_now()),
        "safety": "decision-only; no configuration changes",
        "projects": projects,
        "plugins": plugins,
        "mcps": mcps,
        "skills": skills,
        "counts": {
            "skills": len(skills),
            "reviewable": sum(skill["managementPolicy"] == "reviewable" for skill in skills),
            "managed": sum(skill["managementPolicy"] != "reviewable" for skill in skills),
            "rareCritical": sum(skill["rareCritical"] for skill in skills),
            "plugins": len(plugins),
            "mcps": len(mcps),
        },
    }


def load_inventory(path: Path, profile: str | None = None) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"找不到 inventory：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"inventory 不是有效 JSON：{exc}") from exc
    return normalize_inventory(raw, profile)


def load_receipt(path: Path) -> dict[str, Any] | None:
    """Read-only, best-effort load of an apply-phase verification_receipt.json.

    Never raises: a missing file or invalid JSON is a warning, not a fatal error,
    since the receipt is purely for read-only display in the review page. The
    returned object (if any) has all token/secret/cookie/password/authorization
    keys stripped recursively before it is ever handed to the HTTP layer.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.stderr.write(f"[skill-slimming] 警告：回执文件不存在，已忽略：{path}\n")
        return None
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"[skill-slimming] 警告：回执文件不是合法 JSON，已忽略：{path}（{exc}）\n")
        return None
    if not isinstance(raw, dict):
        sys.stderr.write(f"[skill-slimming] 警告：回执顶层必须是 JSON 对象，已忽略：{path}\n")
        return None
    return scrub_sensitive(raw)


def default_decision(skill: dict[str, Any]) -> dict[str, Any]:
    decision = skill["suggestedDecision"]
    # RARE_CRITICAL 改为 project/trigger 需要人工二次确认，种子状态不能预先替用户做
    # 这个决定，否则初始状态本身无法通过 validate_state 保存。
    if skill["rareCritical"] and decision in ("project", "trigger"):
        decision = "undecided"
    trigger_terms = skill["triggerTerms"][:5] if decision == "trigger" else []
    if decision == "trigger" and len(trigger_terms) < 2:
        decision = "undecided"
        trigger_terms = []
    projects = skill["appliedProjects"] if decision == "project" else []
    if decision == "project" and not projects:
        decision = "undecided"
    return {
        "skillId": skill["skillId"],
        "name": skill["name"],
        "contentHash": skill["contentHash"],
        "decision": decision,
        "projects": projects,
        "triggerTerms": trigger_terms,
        "rareCritical": skill["rareCritical"],
        "rareCriticalConfirmed": False,
        "notes": "",
        "needsReview": False,
    }


def initial_state(inventory: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    previous_by_id: dict[str, Any] = {}
    if isinstance(previous, dict):
        previous_by_id = {
            item.get("skillId"): item
            for item in previous.get("decisions", [])
            if isinstance(item, dict) and item.get("skillId")
        }

    decisions: list[dict[str, Any]] = []
    preserved = 0
    reset = 0
    added = 0
    for skill in inventory["skills"]:
        prior = previous_by_id.get(skill["skillId"])
        if prior and prior.get("contentHash") == skill["contentHash"]:
            candidate = {
                **default_decision(skill),
                **{key: prior.get(key) for key in (
                    "decision", "projects", "triggerTerms", "rareCriticalConfirmed", "notes"
                )},
                "name": skill["name"],
                "contentHash": skill["contentHash"],
                "rareCritical": skill["rareCritical"],
                "needsReview": False,
            }
            preserved += 1
        else:
            candidate = default_decision(skill)
            if previous_by_id:
                candidate.update(
                    {
                        "decision": "undecided",
                        "projects": [],
                        "triggerTerms": [],
                        "rareCriticalConfirmed": False,
                    }
                )
            if prior:
                candidate["needsReview"] = True
                reset += 1
            else:
                added += 1
        decisions.append(candidate)

    removed = len(set(previous_by_id) - {skill["skillId"] for skill in inventory["skills"]})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "auditId": inventory["auditId"],
        "environmentId": inventory["environmentId"],
        "inventoryRevision": inventory["inventoryRevision"],
        "savedAt": None,
        "reviewStatus": "draft",
        "safety": "decision-only; no configuration changes",
        "gatePrompt": GATE_PROMPT,
        "projectCatalog": inventory["projects"],
        "decisions": decisions,
        "reconciliation": {
            "preserved": preserved,
            "resetBecauseChanged": reset,
            "added": added,
            "removed": removed,
        },
    }


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def atomic_write_json(path: Path, value: Any) -> None:
    ensure_private_dir(path.parent)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


class StateStore:
    def __init__(
        self,
        root: Path,
        profile: str,
        inventory: dict[str, Any],
        receipt: dict[str, Any] | None = None,
    ):
        self.root = root.expanduser().resolve()
        self.profile = safe_profile_name(profile)
        self.inventory = inventory
        self.receipt = receipt
        self.profile_dir = self.root / "profiles" / self.profile
        self.current_path = self.profile_dir / "current.json"
        self.history_dir = self.profile_dir / "history"
        self.active_path = self.root / "active.json"
        self.lock = threading.Lock()
        ensure_private_dir(self.root)
        ensure_private_dir(self.profile_dir)
        ensure_private_dir(self.history_dir)
        previous = self._read_existing()
        self.state = initial_state(inventory, previous)
        if previous and previous.get("inventoryRevision") == inventory["inventoryRevision"]:
            try:
                self.state = validate_state(previous, inventory)
                self.state["savedAt"] = previous.get("savedAt")
            except ValidationError:
                self.state = initial_state(inventory)
        self._write_active()

    def _read_existing(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.current_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return value if isinstance(value, dict) else None

    def _write_active(self) -> None:
        atomic_write_json(
            self.active_path,
            {
                "schemaVersion": SCHEMA_VERSION,
                "profile": self.profile,
                "auditId": self.inventory["auditId"],
                "inventoryRevision": self.inventory["inventoryRevision"],
                "statePath": str(self.current_path),
                "updatedAt": utc_now(),
            },
        )

    def bootstrap(self) -> dict[str, Any]:
        with self.lock:
            return {"inventory": self.inventory, "state": self.state, "receipt": self.receipt}

    def save(self, raw_state: Any) -> dict[str, Any]:
        with self.lock:
            validated = validate_state(raw_state, self.inventory)
            validated["savedAt"] = utc_now()
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            if self.current_path.exists():
                previous = self._read_existing()
                if previous:
                    atomic_write_json(self.history_dir / f"{timestamp}.json", previous)
            atomic_write_json(self.current_path, validated)
            self.state = validated
            self._trim_history()
            self._write_active()
            return validated

    def _trim_history(self) -> None:
        history = sorted(self.history_dir.glob("*.json"), reverse=True)
        for path in history[MAX_HISTORY:]:
            path.unlink(missing_ok=True)


def validate_state(raw: Any, inventory: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError("state 必须是 JSON 对象。")
    if raw.get("schemaVersion") != SCHEMA_VERSION:
        raise ValidationError(f"state.schemaVersion 必须为 {SCHEMA_VERSION}。")
    if raw.get("auditId") != inventory["auditId"]:
        raise ValidationError("auditId 与当前审计不一致，请刷新页面后重试。")
    if raw.get("inventoryRevision") != inventory["inventoryRevision"]:
        raise ValidationError("inventoryRevision 已漂移，请重新复审。")

    review_status = raw.get("reviewStatus", "draft")
    if review_status not in VALID_REVIEW_STATUSES:
        raise ValidationError("reviewStatus 只能是 draft 或 complete。")

    project_catalog = raw.get("projectCatalog", inventory["projects"])
    if not isinstance(project_catalog, list):
        raise ValidationError("projectCatalog 必须是数组。")
    projects = [normalize_project(project, index) for index, project in enumerate(project_catalog)]
    project_ids = {project["id"] for project in projects}

    raw_decisions = raw.get("decisions")
    if not isinstance(raw_decisions, list):
        raise ValidationError("decisions 必须是数组。")
    by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw_decisions):
        if not isinstance(item, dict):
            raise ValidationError(f"decisions[{index}] 必须是对象。")
        skill_id = as_text(item.get("skillId"))
        if not skill_id or skill_id in by_id:
            raise ValidationError("decisions 中的 skillId 必须存在且唯一。")
        by_id[skill_id] = item

    inventory_by_id = {skill["skillId"]: skill for skill in inventory["skills"]}
    if set(by_id) != set(inventory_by_id):
        raise ValidationError("decisions 必须与当前 inventory 的 Skill 集合完全一致。")

    validated_decisions: list[dict[str, Any]] = []
    for skill in inventory["skills"]:
        item = by_id[skill["skillId"]]
        if as_text(item.get("contentHash")) != skill["contentHash"]:
            raise ValidationError(f"{skill['name']} 的 contentHash 与当前 inventory 不一致。")
        decision = as_text(item.get("decision"), "undecided")
        if decision not in VALID_DECISIONS:
            raise ValidationError(f"{skill['name']} 的 decision 无效。")
        if skill["managementPolicy"] != "reviewable" and decision != "undecided":
            raise ValidationError(f"{skill['name']} 是托管只读项，不能逐项改变作用域。")

        selected_projects = as_text_list(item.get("projects")) if decision == "project" else []
        if decision == "project":
            if not selected_projects:
                raise ValidationError(f"{skill['name']} 设为项目级时必须绑定至少一个项目。")
            unknown = set(selected_projects) - project_ids
            if unknown:
                raise ValidationError(f"{skill['name']} 引用了未知项目：{', '.join(sorted(unknown))}")

        trigger_terms = as_text_list(item.get("triggerTerms")) if decision == "trigger" else []
        if decision == "trigger" and not 2 <= len(trigger_terms) <= 5:
            raise ValidationError(f"{skill['name']} 设为触发时必须填写 2–5 个自然语言触发词。")
        if any(len(term) > 80 for term in trigger_terms):
            raise ValidationError(f"{skill['name']} 的触发词过长。")

        confirmed = bool(item.get("rareCriticalConfirmed", False))
        if skill["rareCritical"] and decision in {"project", "trigger"} and not confirmed:
            raise ValidationError(f"{skill['name']} 是 RARE_CRITICAL，改为项目或触发前必须二次确认。")

        needs_review = bool(item.get("needsReview", False))
        if review_status == "complete" and skill["managementPolicy"] == "reviewable":
            if decision == "undecided" or needs_review:
                raise ValidationError(f"{skill['name']} 尚未完成复审。")

        validated_decisions.append(
            {
                "skillId": skill["skillId"],
                "name": skill["name"],
                "contentHash": skill["contentHash"],
                "decision": decision,
                "projects": selected_projects,
                "triggerTerms": trigger_terms,
                "rareCritical": skill["rareCritical"],
                "rareCriticalConfirmed": confirmed,
                "notes": as_text(item.get("notes"))[:1000],
                "needsReview": needs_review,
            }
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "auditId": inventory["auditId"],
        "environmentId": inventory["environmentId"],
        "inventoryRevision": inventory["inventoryRevision"],
        "savedAt": raw.get("savedAt"),
        "reviewStatus": review_status,
        "safety": "decision-only; no configuration changes",
        "gatePrompt": GATE_PROMPT,
        "projectCatalog": projects,
        "decisions": validated_decisions,
        "reconciliation": raw.get("reconciliation", {}),
    }


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: StateStore, token: str):
        super().__init__(address, ReviewHandler)
        self.store = store
        self.token = token


class ReviewHandler(BaseHTTPRequestHandler):
    server: ReviewServer

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[skill-slimming] " + fmt % args + "\n")

    def _json(self, status: HTTPStatus, value: Any) -> None:
        payload = canonical_json(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "")
        allowed = {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
            f"[::1]:{self.server.server_port}",
        }
        return host in allowed

    def _authorized(self) -> bool:
        query_token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        header_token = self.headers.get("X-Skill-Slimming-Token", "")
        supplied = header_token or query_token
        return bool(supplied) and secrets.compare_digest(supplied, self.server.token)

    def _valid_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin in {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
            f"http://[::1]:{self.server.server_port}",
        }

    def _guard(self, require_origin: bool = False) -> bool:
        if not self._valid_host():
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_host"})
            return False
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return False
        if require_origin and not self._valid_origin():
            self._json(HTTPStatus.FORBIDDEN, {"error": "invalid_origin"})
            return False
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            if not self._valid_host():
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_host"})
                return
            self._json(HTTPStatus.OK, {"ok": True, "service": "skill-slimming"})
            return
        if parsed.path == "/":
            if not self._guard():
                return
            try:
                payload = ASSET_PATH.read_bytes()
            except FileNotFoundError:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "review_asset_missing"})
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/api/bootstrap":
            if not self._guard():
                return
            self._json(HTTPStatus.OK, self.server.store.bootstrap())
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/state":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._guard(require_origin=True):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body_too_large"})
            return
        try:
            raw = json.loads(self.rfile.read(length).decode("utf-8"))
            saved = self.server.store.save(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return
        except ValidationError as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "validation", "message": str(exc)})
            return
        self._json(HTTPStatus.OK, {"ok": True, "state": saved})

    def do_POST(self) -> None:
        self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read_review_only"})

    def do_DELETE(self) -> None:
        self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read_review_only"})


def resolve_state_root(value: str | None) -> Path:
    return Path(value).expanduser() if value else Path.home() / ".skill-slimming"


def read_saved_state(root: Path, profile: str | None) -> tuple[Path, dict[str, Any]]:
    if profile:
        path = root / "profiles" / safe_profile_name(profile) / "current.json"
    else:
        active_path = root / "active.json"
        try:
            active = json.loads(active_path.read_text(encoding="utf-8"))
            path = Path(active["statePath"]).expanduser().resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ValidationError("active.json 指向了状态根目录之外，已拒绝读取。") from exc
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
            raise ValidationError("没有找到上一次复审状态；请先运行 serve。") from exc
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"状态文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"状态文件损坏：{path}") from exc
    return path, state


def is_cross_machine(target: str, home: str) -> bool:
    """Pure predicate: does an absolute /Users/... target fall outside the current home?

    Only meaningful for already-resolved absolute paths; callers decide whether the
    entry is a symlink and whether it is broken before consulting this.
    """
    if not target.startswith("/Users/"):
        return False
    home_norm = home.rstrip("/")
    if not home_norm:
        return True
    return target != home_norm and not target.startswith(home_norm + "/")


def classify_entry(path: Path) -> dict[str, Any]:
    """Read-only classification of one skills-dir entry: symlink-ness, target, health.

    Never reads file contents. broken-symlink takes priority over cross-machine-path
    when both conditions would otherwise apply.
    """
    is_symlink = os.path.islink(path)
    target = os.readlink(path) if is_symlink else None
    broken = os.path.lexists(path) and not os.path.exists(path)
    entry_health = "ok"
    if broken:
        entry_health = "broken-symlink"
    elif is_symlink:
        try:
            resolved = os.path.realpath(path)
        except OSError:
            resolved = target
        home = os.path.expanduser("~")
        if is_cross_machine(resolved, home):
            entry_health = "cross-machine-path"
    return {"isSymlink": is_symlink, "target": target, "entryHealth": entry_health}


def read_settings_overrides(path: Path) -> dict[str, Any] | None:
    """Read skillOverrides from a host settings.json. None means unreadable/invalid."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    overrides = raw.get("skillOverrides")
    if not isinstance(overrides, dict):
        return {}
    return overrides


def command_probe(args: argparse.Namespace) -> int:
    overrides: dict[str, Any] | None = None
    if args.settings:
        settings_path = Path(args.settings).expanduser()
        overrides = read_settings_overrides(settings_path)
        if overrides is None:
            sys.stderr.write(
                f"[skill-slimming] 警告：无法读取或解析 settings：{settings_path}，overrideState 全部标记 unknown。\n"
            )

    scanned_dirs: list[str] = []
    entries: list[dict[str, Any]] = []
    any_dir_found = False

    for raw_dir in args.skills_dir:
        skills_dir = Path(raw_dir).expanduser()
        if not skills_dir.exists():
            sys.stderr.write(f"[skill-slimming] 警告：目录不存在，已跳过：{skills_dir}\n")
            continue
        any_dir_found = True
        scanned_dirs.append(str(skills_dir))
        for child in sorted(skills_dir.iterdir(), key=lambda p: p.name):
            if child.name.startswith("."):
                continue
            is_symlink = os.path.islink(child)
            if not is_symlink and not child.is_dir():
                continue
            classified = classify_entry(child)
            if args.settings and overrides is not None:
                override_state = "off" if overrides.get(child.name) == "off" else "on"
            else:
                override_state = "unknown"
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "isSymlink": classified["isSymlink"],
                    "target": classified["target"],
                    "entryHealth": classified["entryHealth"],
                    "overrideState": override_state,
                }
            )

    result = {
        "generatedBy": "skill-slimming probe",
        "scannedDirs": scanned_dirs,
        "entries": entries,
        "summary": {
            "total": len(entries),
            "ok": sum(1 for e in entries if e["entryHealth"] == "ok"),
            "brokenSymlink": sum(1 for e in entries if e["entryHealth"] == "broken-symlink"),
            "crossMachinePath": sum(1 for e in entries if e["entryHealth"] == "cross-machine-path"),
            "overrideOff": sum(1 for e in entries if e["overrideState"] == "off"),
            "overrideUnknown": sum(1 for e in entries if e["overrideState"] == "unknown"),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.skills_dir and not any_dir_found:
        return 2
    return 0


def command_validate(args: argparse.Namespace) -> int:
    inventory = load_inventory(Path(args.inventory), args.profile)
    print(json.dumps(inventory, ensure_ascii=False, indent=2))
    return 0


def command_read(args: argparse.Namespace) -> int:
    root = resolve_state_root(args.state_root).resolve()
    path, state = read_saved_state(root, args.profile)
    if args.require_complete and state.get("reviewStatus") != "complete":
        raise ValidationError("复审状态仍是 draft；请让用户在页面中点击“完成复审”。")
    if args.path_only:
        print(path)
    else:
        print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    root = resolve_state_root(args.state_root).resolve()
    path, state = read_saved_state(root, args.profile)
    decisions = state.get("decisions", [])
    counts = {key: 0 for key in sorted(VALID_DECISIONS)}
    for item in decisions:
        decision = item.get("decision", "undecided")
        if decision in counts:
            counts[decision] += 1
    print(
        json.dumps(
            {
                "path": str(path),
                "reviewStatus": state.get("reviewStatus"),
                "savedAt": state.get("savedAt"),
                "auditId": state.get("auditId"),
                "inventoryRevision": state.get("inventoryRevision"),
                "counts": counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_serve(args: argparse.Namespace) -> int:
    inventory = load_inventory(Path(args.inventory), args.profile)
    root = resolve_state_root(args.state_root)
    profile = inventory["environmentId"]
    receipt = load_receipt(Path(args.receipt).expanduser()) if args.receipt else None
    store = StateStore(root, profile, inventory, receipt=receipt)
    token = secrets.token_urlsafe(32)
    server = ReviewServer(("127.0.0.1", args.port), store, token)
    url = f"http://127.0.0.1:{server.server_port}/?token={token}"
    ready = {
        "url": url,
        "port": server.server_port,
        "profile": profile,
        "statePath": str(store.current_path),
        "inventoryRevision": inventory["inventoryRevision"],
    }
    if args.ready_file:
        atomic_write_json(Path(args.ready_file).expanduser().resolve(), ready)
    print(json.dumps(ready, ensure_ascii=False), flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Skill 瘦身本地复审运行层：只保存决策，不执行配置修改。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="校验并标准化 inventory JSON。")
    validate_parser.add_argument("--inventory", required=True)
    validate_parser.add_argument("--profile")
    validate_parser.set_defaults(func=command_validate)

    probe_parser = subparsers.add_parser(
        "probe", help="只读采集 skills 目录的入口健康度与宿主控制面 overrideState。"
    )
    probe_parser.add_argument("--skills-dir", action="append", required=True, dest="skills_dir")
    probe_parser.add_argument("--settings", help="宿主 settings.json 路径；缺省时 overrideState 全部为 unknown。")
    probe_parser.add_argument("--json", action="store_true", help="与默认输出相同；显式声明输出为 JSON。")
    probe_parser.set_defaults(func=command_probe)

    serve_parser = subparsers.add_parser("serve", help="启动 127.0.0.1 复审网页并持续保存状态。")
    serve_parser.add_argument("--inventory", required=True)
    serve_parser.add_argument("--profile", help="同一台机器上的状态空间名称。")
    serve_parser.add_argument("--state-root", help="默认是 ~/.skill-slimming。")
    serve_parser.add_argument("--port", type=int, default=0, help="默认自动选择空闲端口。")
    serve_parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器。")
    serve_parser.add_argument("--ready-file", help="把启动信息写入指定 JSON，便于自动化验收。")
    serve_parser.add_argument(
        "--receipt",
        help="apply 阶段 verification_receipt.json 路径；只读回显于复审页，不参与任何校验。",
    )
    serve_parser.set_defaults(func=command_serve)

    for name, help_text, func in (
        ("read", "读取持久化决策，供 Agent 在用户确认后生成计划。", command_read),
        ("status", "读取上一次复审的摘要状态。", command_status),
    ):
        child = subparsers.add_parser(name, help=help_text)
        child.add_argument("--profile")
        child.add_argument("--state-root", help="默认是 ~/.skill-slimming。")
        if name == "read":
            child.add_argument("--require-complete", action="store_true")
            child.add_argument("--path-only", action="store_true")
        child.set_defaults(func=func)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
