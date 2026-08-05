# Audit and inventory contract

Only read this reference while producing or validating an audit. The review runtime accepts a compact subset, but a publishable report should preserve all evidence fields below.

## Measurement labels

Every numeric field carries one of these labels:

- `精确值`: counted directly from a complete, authoritative source;
- `日志观测值`: observed in a declared log/session window;
- `估算值`: tokenizer or documented approximation;
- `不可用`: the current host does not expose trustworthy evidence.

Never use zero to mean unavailable.

## Count model

Keep these Skill counts separate:

| Field | Meaning |
|---|---|
| installed instances | deployments proven by host inventory, lockfile, manifest, or effective entry |
| exposed entries | entries discoverable by the current host; the same content can be exposed by two hosts |
| content variants | unique normalized-name plus content-hash pairs |
| unique names | Unicode-normalized, trimmed, case-insensitive names |

Also keep plugin `installed`, `enabled`, `cached`, and `directSkillEntries` separate. For MCP, keep `configured`, `enabled`, and `connected` separate.

## Source and management evidence

Source evidence order:

1. host installation lock or official system list;
2. installed plugin manifest and plugin ID;
3. Skill/bundle manifest;
4. resolved symlink plus Git remote/commit/repository-relative path;
5. project loading rules and Git ancestry;
6. path family, name prefix, or content similarity;
7. AI purpose inference.

Use `verified`, `strong`, `inferred`, or `unknown`. Prefixes such as `dbs-*` and `lark-*` can create a provisional source group but remain `inferred` without stronger evidence.

Management policies:

- `reviewable`: user-managed entry that can receive a global/project/trigger decision;
- `managed`: host system or plugin child entry; display only, manage through the owning control plane;
- `review-only`: ownership is unclear; display but do not plan a move.

Ownership tags can include `Codex 内置`, `Codex 官方插件`, `第三方插件`, `Claude Code`, and `用户安装`. A Skill may have multiple host tags but one management policy.

Host control-plane enable/disable state (e.g. Claude Code settings.json `skillOverrides`) ranks with tier 1 host installation evidence; record per-skill `hostOverrideState` and `entryHealth` (broken symlinks and cross-machine absolute paths are dead exposure, not active entries).

## Usage evidence

Evidence priority:

1. structured Skill load/call events;
2. plugin manager Last used;
3. explicit session log load/call event;
4. user-confirmed stable habit;
5. filesystem timestamp as weak estimate.

A conversation mentioning a Skill name is a `mention_signal`, not a call. Record log window, host, timezone, extraction method, and a non-reversible session identifier. Do not copy prompt bodies.

## Context evidence

For each Skill:

- `currentStartupTokens`: current discovery entry;
- `shellStartupTokens`: minimal trigger shell discovery entry;
- `postCallTokens`: full entry and resources actually loaded after a match.

Priority: host `/context` observation > matching tokenizer estimate > documented character approximation. Do not add all references/scripts/assets to `postCallTokens` unless runtime evidence shows they were loaded.

Run fresh-session A/B only when the current host help exposes an official safe mode or customization disable switch. Keep version, model, prompt, enabled items, timing, and uncontrolled variables. Never move live Skill directories just to create the A/B.

## Runtime inventory JSON

The local review runtime requires a JSON object with a `skills` array. This example shows the preferred complete shape; optional unavailable fields can be `null`.

```json
{
  "schemaVersion": 1,
  "auditId": "audit-20260804T120000Z",
  "environmentId": "mac-mini-codex",
  "inventoryRevision": "sha256-of-stable-ids-and-content-hashes",
  "generatedAt": "2026-08-04T12:00:00Z",
  "counts": {
    "installedInstances": {"value": 120, "measurement": "精确值"},
    "exposedEntries": {"value": 157, "measurement": "精确值"},
    "contentVariants": {"value": 151, "measurement": "精确值"},
    "uniqueNames": {"value": 147, "measurement": "精确值"}
  },
  "projects": [
    {"id": "goodcase", "name": "GoodCase", "location": "/absolute/or/verified/path"}
  ],
  "plugins": [],
  "mcps": [],
  "skills": [
    {
      "skillId": "stable-id-from-host-or-audit",
      "name": "example-skill",
      "summary": "一句话能力摘要",
      "entryPath": "/verified/entry/SKILL.md",
      "contentHash": "sha256-of-raw-skill-bytes",
      "sourceGroup": "Verified repository or plugin",
      "sourceLabel": "Human-readable source",
      "sourceConfidence": "verified",
      "category": "开发工程",
      "specificUse": "AI 辅助分类：代码审查",
      "managementPolicy": "reviewable",
      "managementReason": "",
      "ownershipTags": ["用户安装"],
      "hosts": ["Codex Desktop"],
      "rareCritical": false,
      "suggestedDecision": "global",
      "currentStartupTokens": 18,
      "shellStartupTokens": 4,
      "postCallTokens": 2200,
      "tokenMeasurement": "估算值",
      "actualCallCount": 9,
      "usageMeasurement": "日志观测值：最近 60 天",
      "lastUsedAt": "2026-08-01T08:40:00+08:00",
      "lastUsedMeasurement": "日志观测值",
      "triggerTerms": ["审查代码", "大型 review"],
      "appliedProjects": [],
      "hostOverrideState": "on",
      "entryHealth": "ok"
    }
  ]
}
```

`skillId` must be stable and unique in one environment. Prefer a host ID; otherwise derive it deterministically from normalized name plus verified source/entry identity. `contentHash` should hash raw `SKILL.md` bytes. The runtime always recomputes its operational `inventoryRevision` from sorted `skillId + contentHash` pairs and retains a supplied revision only as `sourceInventoryRevision`; this prevents a stale declared revision from reusing changed decisions.

## Report artifacts

`evidence.json` should record command, sanitized arguments, timestamp, exit code, evidence class, and omitted-sensitive-field note. It must not contain secret values or private content.

`report.md` should include:

1. executive summary with separately labelled numbers;
2. scope and host versions;
3. installed/exposed/variant/name counts;
4. global/project/system/plugin/unknown scope;
5. plugin and MCP state;
6. source grouping and confidence;
7. use counts and last-used evidence window;
8. startup/shell/post-call context model and any A/B;
9. global/project/trigger suggestions plus `RARE_CRITICAL` exceptions;
10. unknowns, risks, and the exact local review command.

## Persisted decision state

The runtime saves a state object with:

```json
{
  "schemaVersion": 1,
  "auditId": "audit-id",
  "environmentId": "profile",
  "inventoryRevision": "hash",
  "reviewStatus": "draft|complete",
  "safety": "decision-only; no configuration changes",
  "projectCatalog": [],
  "decisions": [
    {
      "skillId": "stable-id",
      "name": "example-skill",
      "contentHash": "hash",
      "decision": "undecided|global|project|trigger",
      "projects": [],
      "triggerTerms": [],
      "rareCritical": false,
      "rareCriticalConfirmed": false,
      "notes": "",
      "needsReview": false
    }
  ]
}
```

`project` needs at least one known project. `trigger` needs 2–5 unique natural-language phrases. `RARE_CRITICAL` needs confirmation before `project` or `trigger`. `complete` requires every `reviewable` entry to be decided and every changed entry reviewed.
