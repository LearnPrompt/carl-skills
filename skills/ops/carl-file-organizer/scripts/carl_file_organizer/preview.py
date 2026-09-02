"""The after picture: one knowledge-graph canvas of where everything lands.

The report ends with a question a table cannot answer well: if I say yes, what
does the folder look like tomorrow?  This module answers it as a picture.

``build_graph`` turns plan.json (optionally plus a storage analysis) into a tiny
graph: a root, five partitions, the second level of folders under them, one node
per subject, and — when a storage analysis is supplied — a second root for the
machine with the cleanup candidates hanging off it.  ``render_preview_html``
turns that graph into a self-contained ``<section>``: canvas, style and script in
one string, no external resource of any kind, safe to paste at the end of the
report or to open on its own from ``file://``.

Two layouts are computed for every node.  In *now* the files are piled evenly
around the root because that is exactly where they are; in *after* they sit
under the folder they are headed for.  The switch at the top interpolates
between the two, which is the whole point of the picture.

The module is deliberately dependency-free (stdlib only, no intra-package
imports) so it can be tested and rendered in isolation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = [
    "MAX_NODES",
    "PARTITION_ORDER",
    "PREVIEW_TEXT",
    "build_graph",
    "render_preview_html",
    "render_preview_page",
    "main",
]

#: Hard ceiling on nodes.  Past this the picture stops being a picture.
MAX_NODES = 400

#: The five partitions, in the order they should ring the root.
PARTITION_ORDER = ("inbox", "work", "library", "sensitive", "archive")

#: Only these two kinds place a subject on the map, in this order of preference.
_KIND_PRECEDENCE = ("move", "hold")

#: Kinds that free up space rather than move it.
_RECLAIM_KINDS = ("trash", "delete")

_HOME_RE = re.compile(r"(?:/Users|/home)/[^/\s\"']+")

# --------------------------------------------------------------------------
# copy
# --------------------------------------------------------------------------

#: Every string the fragment can show, in both languages.  Keys are added, never
#: renamed; the zh column avoids straight double quotes.
PREVIEW_TEXT: Dict[str, Dict[str, str]] = {
    "zh": {
        "title": "整理后长什么样",
        "state_now": "现在",
        "state_after": "整理后",
        "stat_moving": "项要搬",
        "stat_staying": "项留下",
        "stat_reclaim": "可腾出",
        "legend_green": "绿 · 照做就行",
        "legend_yellow": "黄 · 看一眼",
        "legend_red": "红 · 先别动",
        "shape_partition": "分区",
        "shape_folder": "目录",
        "shape_file": "文件",
        "shape_storage": "待清",
        "hint": "拖拽节点 · 滚轮缩放 · 点开关看整理后",
        "tip_size": "体积",
        "tip_from": "现在",
        "tip_to": "去向",
        "tip_stay": "留在原地",
        "tip_clean": "清掉能腾出空间",
        "count_unit": "项",
        "empty": "这一轮没有要搬的东西",
        "machine": "本机",
        "rest": "其余 {k} 项",
    },
    "en": {
        "title": "What it looks like afterwards",
        "state_now": "Now",
        "state_after": "After",
        "stat_moving": "moving",
        "stat_staying": "staying",
        "stat_reclaim": "frees up",
        "legend_green": "Green · just do it",
        "legend_yellow": "Yellow · take a look",
        "legend_red": "Red · leave it alone",
        "shape_partition": "Partition",
        "shape_folder": "Folder",
        "shape_file": "File",
        "shape_storage": "To clear",
        "hint": "Drag nodes · scroll to zoom · flip the switch",
        "tip_size": "Size",
        "tip_from": "Now",
        "tip_to": "Goes to",
        "tip_stay": "Stays where it is",
        "tip_clean": "Clearing this frees space",
        "count_unit": "items",
        "empty": "Nothing to move this round",
        "machine": "This Mac",
        "rest": "{k} more items",
    },
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _scrub(value: Any) -> Any:
    """Replace any real home directory with ``~`` before it reaches the page."""

    if isinstance(value, str):
        return _HOME_RE.sub("~", value)
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _pick_lang(value: Any, lang: str) -> Optional[str]:
    if isinstance(value, Mapping):
        text = value.get(lang) or value.get("zh") or value.get("en")
        return _scrub(text) if isinstance(text, str) else None
    if isinstance(value, str):
        return _scrub(value)
    return None


def _relative_destination(action: Mapping[str, Any], roots: Sequence[str]) -> Optional[str]:
    """The action's destination as a path relative to the source root."""

    for key, root in (("destination_portable", roots[0]), ("destination", roots[1])):
        dest = action.get(key)
        if not isinstance(dest, str) or not dest:
            continue
        if root and dest.startswith(root.rstrip("/") + "/"):
            return dest[len(root.rstrip("/")) + 1 :]
    dest = action.get("destination_portable") or action.get("destination")
    if isinstance(dest, str) and dest:
        # Unanchored destination: keep the tail so the label still reads.
        return dest.lstrip("/")
    return None


def _partition_names(plan: Mapping[str, Any]) -> List[Dict[str, str]]:
    names = plan.get("names") or {}
    out: List[Dict[str, str]] = []
    seen = set()
    for key in PARTITION_ORDER:
        label = names.get(key)
        if isinstance(label, str) and label and label not in seen:
            seen.add(label)
            out.append({"key": key, "label": label})
    for key, label in sorted(names.items()):
        if "." in key or key in PARTITION_ORDER:
            continue
        if isinstance(label, str) and label and label not in seen:
            seen.add(label)
            out.append({"key": key, "label": label})
    return out


def _subject_actions(plan: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """One action per subject: a move wins, otherwise a hold, otherwise nothing."""

    chosen: Dict[str, Mapping[str, Any]] = {}
    for action in plan.get("actions") or []:
        if not isinstance(action, Mapping):
            continue
        kind = action.get("kind")
        if kind not in _KIND_PRECEDENCE:
            continue
        subject = action.get("subject_id") or action.get("id")
        if not subject:
            continue
        current = chosen.get(subject)
        if current is None:
            chosen[subject] = action
            continue
        if _KIND_PRECEDENCE.index(kind) < _KIND_PRECEDENCE.index(current.get("kind")):
            chosen[subject] = action
    ordered: List[Mapping[str, Any]] = []
    seen = set()
    for action in plan.get("actions") or []:
        if not isinstance(action, Mapping):
            continue
        subject = action.get("subject_id") or action.get("id")
        if subject in chosen and subject not in seen and chosen[subject] is action:
            seen.add(subject)
            ordered.append(action)
    return ordered


def _reclaim_bytes(plan: Mapping[str, Any]) -> int:
    """Bytes the trash and delete actions would free, counted once per subject."""

    per_subject: Dict[str, int] = {}
    for action in plan.get("actions") or []:
        if not isinstance(action, Mapping) or action.get("kind") not in _RECLAIM_KINDS:
            continue
        subject = action.get("subject_id") or action.get("id") or ""
        size = action.get("size_bytes") or action.get("bytes") or 0
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = 0
        per_subject[subject] = max(per_subject.get(subject, 0), size)
    return sum(per_subject.values())


# --------------------------------------------------------------------------
# build_graph
# --------------------------------------------------------------------------


def build_graph(plan: Mapping[str, Any], analysis: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Turn a plan (and optionally a storage analysis) into the preview graph."""

    if not isinstance(plan, Mapping):
        raise TypeError("plan must be a mapping loaded from plan.json")

    lang = plan.get("lang") if plan.get("lang") in ("zh", "en") else "zh"
    root_portable = _scrub(plan.get("source_root_portable") or plan.get("source_root") or "~")
    root_label = os.path.basename(root_portable.rstrip("/")) or root_portable

    nodes: List[Dict[str, Any]] = []
    links: List[Dict[str, str]] = []
    index: Dict[str, Dict[str, Any]] = {}

    def add_node(node: Dict[str, Any]) -> Dict[str, Any]:
        node.setdefault("color", None)
        node.setdefault("size_bytes", 0)
        node.setdefault("to", None)
        node.setdefault("from", None)
        node.setdefault("hint", None)
        index[node["id"]] = node
        nodes.append(node)
        return node

    def add_link(source: str, target: str, kind: str) -> None:
        links.append({"source": source, "target": target, "kind": kind})

    add_node(
        {
            "id": "root",
            "label": root_label,
            "type": "root",
            "depth": 1,
            "to": root_portable,
            "from": root_portable,
        }
    )

    # -- machine layer ------------------------------------------------------
    storage_leaves: List[Dict[str, Any]] = []
    if isinstance(analysis, Mapping):
        machine = analysis.get("machine") or {}
        host = machine.get("hostname") if isinstance(machine, Mapping) else None
        add_node(
            {
                "id": "machine",
                "label": _scrub(host) or PREVIEW_TEXT[lang]["machine"],
                "type": "machine",
                "depth": 0,
                "hint": _pick_lang((analysis.get("overview") or {}).get("headline"), lang),
            }
        )
        add_link("root", "machine", "after")
        for item in analysis.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            item_id = item.get("id")
            if not item_id:
                continue
            path = _scrub(item.get("path_portable") or item.get("path") or "")
            parent = path.rsplit("/", 1)[0] if "/" in path else path
            try:
                size = int(item.get("size_bytes") or 0)
            except (TypeError, ValueError):
                size = 0
            color = item.get("color") if item.get("color") in ("green", "yellow", "red") else "yellow"
            what = _pick_lang(item.get("what"), lang) or ""
            hint = what
            if color == "green":
                hint = (PREVIEW_TEXT[lang]["tip_clean"] + " · " + what).strip(" ·")
            node = {
                "id": "s:" + str(item_id),
                "label": _scrub(item.get("name") or item_id),
                "type": "storage",
                "depth": 2,
                "color": color,
                "size_bytes": size,
                "from": parent or None,
                "to": None,
                "hint": hint or None,
                "pending_clean": color == "green",
                "parent": "machine",
            }
            storage_leaves.append(node)

    # -- partitions ---------------------------------------------------------
    partitions = _partition_names(plan)
    partition_by_label: Dict[str, str] = {}
    for entry in partitions:
        node_id = "p:" + entry["key"]
        partition_by_label[entry["label"]] = node_id
        add_node(
            {
                "id": node_id,
                "label": entry["label"],
                "type": "partition",
                "depth": 2,
                "to": root_label + "/" + entry["label"],
            }
        )
        add_link(node_id, "root", "after")

    # -- files --------------------------------------------------------------
    roots = (
        _scrub(plan.get("source_root_portable") or ""),
        plan.get("source_root") or "",
    )
    folder_ids: Dict[str, str] = {}
    file_leaves: List[Dict[str, Any]] = []
    moving = 0
    staying = 0

    for action in _subject_actions(plan):
        subject = str(action.get("subject_id") or action.get("id"))
        kind = action.get("kind")
        try:
            size = int(action.get("size_bytes") or action.get("bytes") or 0)
        except (TypeError, ValueError):
            size = 0
        color = action.get("color") if action.get("color") in ("green", "yellow", "red") else "yellow"
        label = _scrub(action.get("filename") or subject)
        hint_map = action.get("reason") if isinstance(action.get("reason"), Mapping) else None
        node: Dict[str, Any] = {
            "id": "f:" + subject,
            "label": label,
            "type": "file",
            "depth": 4,
            "color": color,
            "size_bytes": size,
            "kind": "dir" if action.get("subject_kind") == "dir" else "file",
            "from": root_label,
            "hint": _pick_lang(hint_map, lang),
            "hint_i18n": _scrub(dict(hint_map)) if hint_map else None,
            "moving": kind == "move",
            # The report page ticks actions, not subjects.  Carrying the action
            # id lets a ``cfo:selection`` event find this node without the
            # fragment having to know anything about plan.json.
            "action_id": str(action.get("id") or ""),
        }

        parent = "root"
        relative = _relative_destination(action, roots) if kind == "move" else None
        if relative:
            segments = [part for part in relative.split("/") if part]
            directories = segments[:-1]
            if directories:
                node["to"] = "/".join(directories)
                partition_id = partition_by_label.get(directories[0])
                if partition_id is None:
                    partition_id = "p:" + directories[0]
                    if partition_id not in index:
                        add_node(
                            {
                                "id": partition_id,
                                "label": directories[0],
                                "type": "partition",
                                "depth": 2,
                                "to": root_label + "/" + directories[0],
                            }
                        )
                        add_link(partition_id, "root", "after")
                    partition_by_label[directories[0]] = partition_id
                parent = partition_id
                if len(directories) >= 2:
                    folder_key = directories[0] + "/" + directories[1]
                    folder_id = folder_ids.get(folder_key)
                    if folder_id is None:
                        folder_id = "d:" + folder_key
                        folder_ids[folder_key] = folder_id
                        add_node(
                            {
                                "id": folder_id,
                                "label": directories[1],
                                "type": "folder",
                                "depth": 3,
                                "to": folder_key,
                            }
                        )
                        add_link(folder_id, partition_id, "after")
                    parent = folder_id

        if node.get("to") is None:
            node["to"] = root_label
            node["moving"] = False

        node["parent"] = parent
        if node["moving"]:
            moving += 1
        else:
            staying += 1
        file_leaves.append(node)

    # -- cap ----------------------------------------------------------------
    leaves = file_leaves + storage_leaves
    structural = len(nodes)
    budget = MAX_NODES - structural - 1
    dropped: List[Dict[str, Any]] = []
    if budget < 0:
        budget = 0
    if len(leaves) > budget:
        leaves = sorted(leaves, key=lambda item: (-int(item.get("size_bytes") or 0), item["id"]))
        dropped = leaves[budget:]
        leaves = leaves[:budget]

    kept_ids = {node["id"] for node in leaves}
    for node in file_leaves + storage_leaves:
        if node["id"] not in kept_ids:
            continue
        parent = node.pop("parent")
        add_node(node)
        add_link(node["id"], parent, "after")
        if node["type"] == "file":
            add_link(node["id"], "root", "now")

    if dropped:
        rest_bytes = sum(int(item.get("size_bytes") or 0) for item in dropped)
        rest_label = {
            code: PREVIEW_TEXT[code]["rest"].format(k=len(dropped)) for code in ("zh", "en")
        }
        add_node(
            {
                "id": "agg:rest",
                "label": rest_label[lang],
                "label_i18n": rest_label,
                "type": "file",
                "depth": 4,
                "color": "yellow",
                "size_bytes": rest_bytes,
                "kind": "file",
                "from": root_label,
                "to": root_label,
                "moving": False,
                "aggregate": len(dropped),
            }
        )
        add_link("agg:rest", "root", "after")
        add_link("agg:rest", "root", "now")

    reclaim = _reclaim_bytes(plan)
    if isinstance(analysis, Mapping):
        for item in analysis.get("items") or []:
            if isinstance(item, Mapping) and item.get("color") == "green":
                try:
                    reclaim += int(item.get("size_bytes") or 0)
                except (TypeError, ValueError):
                    pass

    stats = {
        "files": len(file_leaves),
        "moving": moving,
        "staying": staying,
        "partitions": len(partitions),
        "reclaim_bytes": reclaim,
        "storage_items": len(storage_leaves),
        "dropped": len(dropped),
        "lang": lang,
        "root": root_label,
    }
    return {"nodes": nodes, "links": links, "stats": stats}


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------


def _js_json(payload: Any) -> str:
    """JSON that is safe to sit inline in a ``<script>`` block."""

    text = json.dumps(payload, ensure_ascii=False, sort_keys=False)
    text = text.replace("</", "<\\/")
    text = text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return text


def render_preview_html(
    graph: Mapping[str, Any],
    *,
    lang: str = "zh",
    height: int = 720,
    embed_id: str = "cfo-preview",
) -> str:
    """Render the graph as one self-contained ``<section>``; zero external URLs."""

    if lang not in PREVIEW_TEXT:
        lang = "zh"
    payload = {
        "nodes": _scrub(list(graph.get("nodes") or [])),
        "links": list(graph.get("links") or []),
        "stats": _scrub(dict(graph.get("stats") or {})),
    }
    return (
        _FRAGMENT.replace("__CFO_ID__", embed_id)
        .replace("__CFO_HEIGHT__", str(int(height)))
        .replace("__CFO_LANG__", lang)
        .replace("__CFO_TEXT__", _js_json(PREVIEW_TEXT))
        .replace("__CFO_DATA__", _js_json(payload))
    )


def render_preview_page(
    graph: Mapping[str, Any],
    *,
    lang: str = "zh",
    height: int = 720,
) -> str:
    """The same fragment, wrapped in a page you can open straight from disk."""

    if lang not in PREVIEW_TEXT:
        lang = "zh"
    title = PREVIEW_TEXT[lang]["title"]
    fragment = render_preview_html(graph, lang=lang, height=height)
    return (
        "<!doctype html>\n"
        '<html lang="' + ("zh-CN" if lang == "zh" else "en") + '">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>" + title + "</title>\n"
        "<style>\n"
        "html, body { margin: 0; padding: 0; background: #FAFAF7; }\n"
        "@media (prefers-color-scheme: dark) { html, body { background: #131311; } }\n"
        "body { padding: 24px; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n" + fragment + "\n</body>\n</html>\n"
    )


# --------------------------------------------------------------------------
# the fragment
# --------------------------------------------------------------------------

_FRAGMENT = r"""<section id="__CFO_ID__" class="cfo-preview" data-lang="__CFO_LANG__">
<style>
#__CFO_ID__ {
  --cfo-bg: #FAFAF7;
  --cfo-panel: #FFFFFF;
  --cfo-ink: #141412;
  --cfo-soft: #8F8E86;
  --cfo-line: #141412;
  --cfo-faint: #D8D7D0;
  --cfo-accent: #FF4400;
  --cfo-green: #00b42a;
  --cfo-yellow: #ff7d00;
  --cfo-red: #f53f3f;
  position: relative;
  display: block;
  margin: 0;
  background: var(--cfo-bg);
  color: var(--cfo-ink);
  border: 1px solid var(--cfo-line);
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  overflow: hidden;
}
@media (prefers-color-scheme: dark) {
  #__CFO_ID__ {
    --cfo-bg: #131311;
    --cfo-panel: #1B1B18;
    --cfo-ink: #EDECE6;
    --cfo-soft: #8F8E86;
    --cfo-line: #EDECE6;
    --cfo-faint: #33322E;
    --cfo-accent: #FF5511;
  }
}
#__CFO_ID__ * { box-sizing: border-box; border-radius: 0; }
#__CFO_ID__ .cfo-stage {
  position: relative;
  height: __CFO_HEIGHT__px;
  cursor: grab;
  touch-action: none;
}
#__CFO_ID__ .cfo-stage.cfo-drag { cursor: grabbing; }
#__CFO_ID__ canvas { display: block; width: 100%; height: 100%; }
#__CFO_ID__ .cfo-mono {
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, monospace;
}
#__CFO_ID__ .cfo-panel {
  position: absolute; top: 12px; right: 12px; z-index: 4;
  background: var(--cfo-panel);
  border: 1px solid var(--cfo-line);
  min-width: 188px;
}
#__CFO_ID__ .cfo-switch { display: flex; border-bottom: 1px solid var(--cfo-line); }
#__CFO_ID__ .cfo-switch button {
  flex: 1 1 50%;
  padding: 7px 10px;
  border: 0; background: transparent;
  color: var(--cfo-soft);
  font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase;
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, monospace;
  cursor: pointer;
}
#__CFO_ID__ .cfo-switch button + button { border-left: 1px solid var(--cfo-faint); }
#__CFO_ID__ .cfo-switch button.on { background: var(--cfo-ink); color: var(--cfo-bg); }
#__CFO_ID__ .cfo-switch button:focus-visible { outline: 2px solid var(--cfo-accent); outline-offset: -2px; }
#__CFO_ID__ .cfo-stats {
  padding: 9px 11px;
  font-size: 11px; line-height: 1.7; color: var(--cfo-soft);
  font-variant-numeric: tabular-nums;
  border-bottom: 1px solid var(--cfo-faint);
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, monospace;
}
#__CFO_ID__ .cfo-stats b { color: var(--cfo-accent); font-weight: 700; }
#__CFO_ID__ .cfo-colors { padding: 9px 11px; font-size: 10px; line-height: 1.9; color: var(--cfo-soft); }
#__CFO_ID__ .cfo-colors i {
  display: inline-block; width: 7px; height: 7px; margin-right: 7px;
  vertical-align: middle;
}
#__CFO_ID__ .cfo-bar {
  display: flex; align-items: center; justify-content: space-between;
  border-top: 1px solid var(--cfo-line);
  background: var(--cfo-panel);
  padding: 0 12px;
  font-size: 10px; letter-spacing: 0.06em; color: var(--cfo-soft);
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, monospace;
  min-height: 34px;
  flex-wrap: wrap;
  gap: 4px 0;
}
#__CFO_ID__ .cfo-shapes { display: flex; align-items: center; gap: 16px; padding: 7px 0; }
#__CFO_ID__ .cfo-shapes span { display: inline-flex; align-items: center; gap: 6px; }
#__CFO_ID__ .cfo-shapes svg { display: block; }
#__CFO_ID__ .cfo-tip {
  position: absolute; z-index: 6; pointer-events: none; display: none;
  max-width: 300px;
  background: var(--cfo-panel);
  border: 1px solid var(--cfo-line);
  padding: 8px 10px;
  font-size: 11px; line-height: 1.6; color: var(--cfo-ink);
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, monospace;
}
#__CFO_ID__ .cfo-tip b { color: var(--cfo-accent); font-weight: 700; }
#__CFO_ID__ .cfo-tip em { color: var(--cfo-soft); font-style: normal; }
@media (max-width: 640px) {
  #__CFO_ID__ .cfo-panel { position: static; margin: 0; border: 0; border-bottom: 1px solid var(--cfo-line); }
  #__CFO_ID__ .cfo-shapes { gap: 10px; }
}
</style>
<div class="cfo-stage">
  <canvas></canvas>
  <div class="cfo-panel">
    <div class="cfo-switch">
      <button type="button" data-state="now"></button>
      <button type="button" data-state="after"></button>
    </div>
    <div class="cfo-stats"></div>
    <div class="cfo-colors"></div>
  </div>
  <div class="cfo-tip"></div>
</div>
<div class="cfo-bar">
  <div class="cfo-shapes"></div>
  <div class="cfo-hint"></div>
</div>
<script>
(function () {
  var TEXT = __CFO_TEXT__["__CFO_LANG__"];
  var DATA = __CFO_DATA__;
  var ROOT = document.getElementById("__CFO_ID__");
  if (!ROOT || ROOT.dataset.ready === "1") { return; }
  ROOT.dataset.ready = "1";

  var stage = ROOT.querySelector(".cfo-stage");
  var cv = ROOT.querySelector("canvas");
  var ctx = cv.getContext("2d");
  var tip = ROOT.querySelector(".cfo-tip");
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- palette ----------
  function css(name) {
    return getComputedStyle(ROOT).getPropertyValue(name).trim() || "#141412";
  }
  var TRI = { green: "--cfo-green", yellow: "--cfo-yellow", red: "--cfo-red" };

  // ---------- model ----------
  var nodes = DATA.nodes.map(function (n) { return Object.assign({}, n); });
  var byId = {};
  nodes.forEach(function (n) { byId[n.id] = n; });
  var links = [];
  DATA.links.forEach(function (l) {
    var a = byId[l.source], b = byId[l.target];
    if (a && b) { links.push({ a: a, b: b, kind: l.kind }); }
  });
  var stats = DATA.stats || {};

  var SHAPE = { root: "hex", partition: "square", folder: "hex", file: "circle", storage: "diamond", machine: "square" };
  var RADIUS = { root: 26, partition: 19, folder: 12, machine: 28 };

  function leafRadius(n) {
    var mb = Math.max(0, (n.size_bytes || 0)) / 1048576;
    var r = 6.2 + Math.log(1 + mb) * 1.9;
    if (n.aggregate) { r = 16; }
    return Math.max(6.2, Math.min(n.type === "storage" ? 18 : 15, r));
  }
  nodes.forEach(function (n) {
    n.shape = SHAPE[n.type] || "circle";
    n.r = RADIUS[n.type] || leafRadius(n);
    n.solid = n.type === "file" ? !!n.moving : (n.type === "storage" ? !!n.pending_clean : false);
    if (n.label_i18n && n.label_i18n["__CFO_LANG__"]) { n.label = n.label_i18n["__CFO_LANG__"]; }
    if (n.hint_i18n && n.hint_i18n["__CFO_LANG__"]) { n.hint = n.hint_i18n["__CFO_LANG__"]; }
  });

  var root = byId["root"];
  var machine = byId["machine"];
  var partitions = nodes.filter(function (n) { return n.type === "partition"; });
  var files = nodes.filter(function (n) { return n.type === "file"; });
  var storages = nodes.filter(function (n) { return n.type === "storage"; });

  var parentOf = {};
  links.forEach(function (l) { if (l.kind === "after") { parentOf[l.a.id] = l.b; } });

  // ---------- seeded after-layout ----------
  var ROOT_X = machine ? -320 : 0;
  var MACHINE_X = 590;
  function seed() {
    root.ax = ROOT_X; root.ay = 0;
    if (machine) { machine.ax = MACHINE_X; machine.ay = -40; }
    var pn = partitions.length || 1;
    partitions.forEach(function (p, i) {
      var a = (i / pn) * Math.PI * 2 - Math.PI / 2;
      p._a = a;
      p.ax = ROOT_X + Math.cos(a) * 300;
      p.ay = Math.sin(a) * 250;
    });
    var kids = {};
    nodes.forEach(function (n) {
      var p = parentOf[n.id];
      if (!p) { return; }
      (kids[p.id] = kids[p.id] || []).push(n);
    });
    function ring(list, cx, cy, base, spread, baseAngle) {
      var count = list.length || 1;
      list.forEach(function (n, i) {
        var a = baseAngle + (i - (count - 1) / 2) * (spread / Math.max(1, count));
        var rad = base + (i % 3) * 22;
        n.ax = cx + Math.cos(a) * rad;
        n.ay = cy + Math.sin(a) * rad;
      });
    }
    partitions.forEach(function (p) {
      var list = (kids[p.id] || []);
      ring(list, p.ax, p.ay, 150, Math.PI * 1.5, p._a);
      list.forEach(function (f) {
        ring(kids[f.id] || [], f.ax, f.ay, 78, Math.PI * 1.8, p._a);
      });
    });
    var held = (kids[root.id] || []).filter(function (n) { return n.type !== "partition" && n.type !== "machine"; });
    held.forEach(function (n, i) {
      var a = (i / Math.max(1, held.length)) * Math.PI * 2;
      var rad = 138 + (i % 2) * 46;
      n.ax = ROOT_X + Math.cos(a) * rad;
      n.ay = Math.sin(a) * rad;
    });
    if (machine) {
      storages.forEach(function (s, i) {
        var a = (i / Math.max(1, storages.length)) * Math.PI * 2 - Math.PI / 2;
        s.ax = MACHINE_X + Math.cos(a) * (228 + (i % 3) * 40);
        s.ay = -40 + Math.sin(a) * (208 + (i % 3) * 34);
      });
    }
    nodes.forEach(function (n) {
      if (typeof n.ax !== "number") { n.ax = ROOT_X; n.ay = 0; }
      n.hx = n.ax; n.hy = n.ay;
    });
  }

  function linkLength(l) {
    if (l.b.type === "root" && l.a.type === "partition") { return 300; }
    if (l.a.type === "machine" || l.b.type === "machine") {
      return l.a.type === "root" || l.b.type === "root" ? 900 : 190;
    }
    if (l.b.type === "partition") { return 155; }
    if (l.b.type === "folder") { return 86; }
    if (l.b.type === "root") { return 130; }
    return 110;
  }
  var afterLinks = links.filter(function (l) { return l.kind === "after"; });

  function relax(iterations) {
    var CUT = 250, CUT2 = CUT * CUT;
    for (var it = 0; it < iterations; it++) {
      for (var i = 0; i < nodes.length; i++) {
        var a = nodes[i];
        for (var j = i + 1; j < nodes.length; j++) {
          var b = nodes[j];
          var dx = b.ax - a.ax, dy = b.ay - a.ay;
          var d2 = dx * dx + dy * dy;
          if (d2 > CUT2) { continue; }
          if (d2 < 1) { d2 = 1; dx = (i % 7) - 3; dy = (j % 5) - 2; }
          var d = Math.sqrt(d2);
          var f = Math.min((1400 + (a.r + b.r) * 90) / d2, 26);
          var fx = (dx / d) * f, fy = (dy / d) * f;
          a.vx = (a.vx || 0) - fx; a.vy = (a.vy || 0) - fy;
          b.vx = (b.vx || 0) + fx; b.vy = (b.vy || 0) + fy;
        }
      }
      for (var k = 0; k < afterLinks.length; k++) {
        var l = afterLinks[k];
        var ddx = l.b.ax - l.a.ax, ddy = l.b.ay - l.a.ay;
        var dd = Math.sqrt(ddx * ddx + ddy * ddy) || 1;
        var ff = (dd - linkLength(l)) * 0.055;
        var fxx = (ddx / dd) * ff, fyy = (ddy / dd) * ff;
        l.a.vx = (l.a.vx || 0) + fxx; l.a.vy = (l.a.vy || 0) + fyy;
        l.b.vx = (l.b.vx || 0) - fxx; l.b.vy = (l.b.vy || 0) - fyy;
      }
      for (var m = 0; m < nodes.length; m++) {
        var n = nodes[m];
        var anchor = n.type === "root" || n.type === "machine" ? 0.5 : (n.type === "partition" ? 0.035 : 0.014);
        n.vx = ((n.vx || 0) + (n.hx - n.ax) * anchor) * 0.8;
        n.vy = ((n.vy || 0) + (n.hy - n.ay) * anchor) * 0.8;
        n.ax += n.vx; n.ay += n.vy;
      }
    }
  }

  // ---------- now-layout: everything piled evenly around the root ----------
  function nowLayout() {
    nodes.forEach(function (n) { n.nx = n.ax; n.ny = n.ay; });
    var loose = files.slice().sort(function (a, b) { return (b.size_bytes || 0) - (a.size_bytes || 0); });
    var placed = 0, ringIndex = 0;
    while (placed < loose.length) {
      var radius = 118 + ringIndex * 52;
      var capacity = Math.max(6, Math.round((2 * Math.PI * radius) / 46));
      var take = Math.min(capacity, loose.length - placed);
      for (var i = 0; i < take; i++) {
        var a = (i / take) * Math.PI * 2 + ringIndex * 0.35;
        var n = loose[placed + i];
        n.nx = ROOT_X + Math.cos(a) * radius;
        n.ny = Math.sin(a) * radius;
      }
      placed += take;
      ringIndex++;
    }
  }

  seed();
  relax(reduce ? 90 : 260);
  nowLayout();

  // ---------- labels ----------
  var TOP_LABELS = 30;
  var byBytes = function (a, b) { return (b.size_bytes || 0) - (a.size_bytes || 0); };
  files.filter(function (n) { return n.moving; }).sort(byBytes)
    .forEach(function (n, i) { n.named = i < TOP_LABELS; });
  files.filter(function (n) { return !n.moving; }).sort(byBytes)
    .forEach(function (n, i) { n.named = i < 14; });
  storages.slice().sort(byBytes).forEach(function (n, i) { n.named = i < 12; });
  function clip(text) {
    text = String(text || "");
    return text.length > 24 ? text.slice(0, 23) + "\u2026" : text;
  }
  nodes.forEach(function (n) {
    if (n.type !== "file" && n.type !== "storage") { n.named = true; }
  });

  // ---------- camera ----------
  var W = 0, H = 0, DPR = 1;
  var cam = { x: 0, y: 0, z: 1 };
  var state = "now", mix = 0, mixFrom = 0, mixTo = 0, animStart = 0, animDur = 600;
  var hovered = null, dragNode = null, panning = false, last = { x: 0, y: 0 };
  var running = false, flightUntil = 0;

  function bounds() {
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    nodes.forEach(function (n) {
      [[n.ax, n.ay], [n.nx, n.ny]].forEach(function (p) {
        minX = Math.min(minX, p[0] - n.r); maxX = Math.max(maxX, p[0] + n.r);
        minY = Math.min(minY, p[1] - n.r); maxY = Math.max(maxY, p[1] + n.r);
      });
    });
    if (!isFinite(minX)) { return { cx: 0, cy: 0, w: 800, h: 600 }; }
    return { cx: (minX + maxX) / 2, cy: (minY + maxY) / 2, w: maxX - minX, h: maxY - minY };
  }
  function fit() {
    var b = bounds();
    cam.z = Math.max(0.22, Math.min(1.35, Math.min(W / (b.w + 190), H / (b.h + 190))));
    cam.x = -b.cx * cam.z;
    cam.y = -b.cy * cam.z;
  }
  function resize() {
    DPR = window.devicePixelRatio || 1;
    W = stage.clientWidth; H = stage.clientHeight;
    if (!W || !H) { return; }
    cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR);
    fit();
    request();
  }

  function ease(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
  function px(n) { return n.nx + (n.ax - n.nx) * mix; }
  function py(n) { return n.ny + (n.ay - n.ny) * mix; }
  function sx(n) { return W / 2 + cam.x + px(n) * cam.z; }
  function sy(n) { return H / 2 + cam.y + py(n) * cam.z; }

  // ---------- shapes ----------
  function path(x, y, r, shape) {
    ctx.beginPath();
    if (shape === "square") {
      ctx.rect(x - r, y - r, r * 2, r * 2);
    } else if (shape === "hex") {
      for (var k = 0; k < 6; k++) {
        var a = Math.PI / 6 + k * Math.PI / 3;
        var hx = x + Math.cos(a) * r * 1.12, hy = y + Math.sin(a) * r * 1.12;
        if (k === 0) { ctx.moveTo(hx, hy); } else { ctx.lineTo(hx, hy); }
      }
      ctx.closePath();
    } else if (shape === "diamond") {
      ctx.moveTo(x, y - r * 1.28);
      ctx.lineTo(x + r * 1.18, y);
      ctx.lineTo(x, y + r * 1.28);
      ctx.lineTo(x - r * 1.18, y);
      ctx.closePath();
    } else {
      ctx.arc(x, y, r, 0, Math.PI * 2);
    }
  }

  function hull(points) {
    if (points.length < 3) { return points; }
    var pts = points.slice().sort(function (a, b) { return a.x - b.x || a.y - b.y; });
    function cross(o, a, b) { return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x); }
    var lower = [], upper = [], i;
    for (i = 0; i < pts.length; i++) {
      while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], pts[i]) <= 0) { lower.pop(); }
      lower.push(pts[i]);
    }
    for (i = pts.length - 1; i >= 0; i--) {
      while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], pts[i]) <= 0) { upper.pop(); }
      upper.push(pts[i]);
    }
    lower.pop(); upper.pop();
    return lower.concat(upper);
  }

  var members = {};
  partitions.forEach(function (p) { members[p.id] = [p]; });
  nodes.forEach(function (n) {
    var p = parentOf[n.id];
    while (p && p.type !== "partition" && p.type !== "root" && p.type !== "machine") { p = parentOf[p.id]; }
    if (p && members[p.id]) { members[p.id].push(n); }
  });

  function bytes(v) {
    v = v || 0;
    var units = ["B", "KB", "MB", "GB", "TB"], i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return (v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)) + " " + units[i];
  }

  // ---------- draw ----------
  function draw() {
    if (!W || !H) { return; }
    var ink = css("--cfo-ink"), soft = css("--cfo-soft"), faint = css("--cfo-faint");
    var accent = css("--cfo-accent"), bg = css("--cfo-bg"), panel = css("--cfo-panel");
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.clearRect(0, 0, W, H);

    // partition hulls, only meaningful once the files have landed
    var tags = [];
    if (mix > 0.02) {
      partitions.forEach(function (p) {
        var group = members[p.id] || [];
        var pts = group.map(function (n) { return { x: sx(n), y: sy(n) }; });
        var count = group.length - 1;
        var h = hull(pts);
        if (h.length < 3) { return; }
        var cx = 0, cy = 0;
        h.forEach(function (q) { cx += q.x; cy += q.y; });
        cx /= h.length; cy /= h.length;
        var pad = 26;
        var expanded = h.map(function (q) {
          var dx = q.x - cx, dy = q.y - cy, d = Math.hypot(dx, dy) || 1;
          return { x: q.x + (dx / d) * pad, y: q.y + (dy / d) * pad };
        });
        ctx.save();
        ctx.beginPath();
        expanded.forEach(function (q, i) { i === 0 ? ctx.moveTo(q.x, q.y) : ctx.lineTo(q.x, q.y); });
        ctx.closePath();
        ctx.globalAlpha = 0.055 * mix;
        ctx.fillStyle = accent;
        ctx.fill();
        ctx.globalAlpha = 0.45 * mix;
        ctx.setLineDash([5, 5]);
        ctx.lineWidth = 1;
        ctx.strokeStyle = accent;
        ctx.stroke();
        ctx.restore();
        var top = expanded[0];
        expanded.forEach(function (q) { if (q.y < top.y) { top = q; } });
        tags.push({ x: (top.x + cx) / 2, y: top.y - 6, text: p.label + " · " + count });
      });
    }

    // links
    var flying = mix > 0.001 && mix < 0.999;
    ctx.lineWidth = 1;
    links.forEach(function (l) {
      if (l.kind === "now" && mix > 0.5) { return; }
      if (l.kind === "after" && l.a.type === "file" && mix < 0.5) { return; }
      var hot = flying && l.kind === "after" && l.a.type === "file";
      var near = hovered && (l.a === hovered || l.b === hovered);
      ctx.strokeStyle = hot || near ? accent : faint;
      ctx.lineWidth = hot ? 2 : near ? 1.6 : 1;
      ctx.globalAlpha = hot ? 0.85 : near ? 0.95 : 0.75;
      ctx.beginPath();
      ctx.moveTo(sx(l.a), sy(l.a));
      ctx.lineTo(sx(l.b), sy(l.b));
      ctx.stroke();
    });
    ctx.globalAlpha = 1;

    // nodes
    nodes.forEach(function (n) {
      var x = sx(n), y = sy(n), r = Math.max(4.5, n.r * cam.z);
      if (x < -80 || x > W + 80 || y < -80 || y > H + 80) { return; }
      var alpha = 1;
      if (n.type === "file" && !n.moving && mix > 0.5) { alpha = 0.55; }
      if ((n.type === "partition" || n.type === "folder") && mix < 0.5) { alpha = 0.3 + mix * 0.7; }
      ctx.save();
      ctx.globalAlpha = alpha;
      path(x, y, r, n.shape);
      ctx.fillStyle = n.solid ? accent : bg;
      ctx.fill();
      ctx.lineWidth = n === hovered ? 2.4 : (n.type === "root" || n.type === "machine" ? 1.8 : 1.2);
      ctx.strokeStyle = n === hovered ? accent : (n.solid ? accent : ink);
      ctx.stroke();
      if (n.type === "machine" || n.type === "root") {
        path(x, y, r * 0.52, n.shape);
        ctx.lineWidth = 1;
        ctx.strokeStyle = accent;
        ctx.stroke();
      }
      if (n.color && TRI[n.color]) {
        var dr = Math.max(2.6, r * 0.34);
        var off = r * 0.82;
        ctx.beginPath();
        ctx.arc(x + off, y - off, dr, 0, Math.PI * 2);
        ctx.fillStyle = css(TRI[n.color]);
        ctx.fill();
        ctx.lineWidth = 1;
        ctx.strokeStyle = bg;
        ctx.stroke();
      }
      ctx.restore();
    });

    // labels, drawn in screen space so they stay crisp at any zoom
    var queue = [];
    nodes.forEach(function (n) {
      var show = n.named || n === hovered;
      if (!show) { return; }

      queue.push({
        n: n,
        text: clip(n.label),
        size: n.type === "root" || n.type === "machine" ? 13 : (n.type === "partition" ? 12 : (n.type === "folder" ? 12 : 11)),
        dim: n.type === "file" && !n.moving && mix > 0.5,
        pri: n === hovered ? 5 : (n.type === "root" || n.type === "machine" ? 4 : (n.type === "partition" ? 3 : (n.type === "folder" ? 2 : Math.min(1.9, (n.size_bytes || 0) / 5e10))))
      });
    });
    queue.sort(function (a, b) { return b.pri - a.pri; });
    var taken = [];
    nodes.forEach(function (n) {
      var r = Math.max(4.5, n.r * cam.z), x = sx(n), y = sy(n);
      taken.push({ x1: x - r, y1: y - r, x2: x + r, y2: y + r });
    });
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    queue.forEach(function (L) {
      ctx.font = L.size + 'px ui-monospace, "SF Mono", SFMono-Regular, Menlo, monospace';
      var w = ctx.measureText(L.text).width;
      var nx = sx(L.n), ny = sy(L.n), nr = Math.max(4.5, L.n.r * cam.z);
      var spots = [
        [nx, ny + nr + L.size + 3],
        [nx, ny - nr - 5],
        [nx + nr + w / 2 + 7, ny + L.size / 2 - 1],
        [nx - nr - w / 2 - 7, ny + L.size / 2 - 1]
      ];
      var box = null, x = 0, y = 0;
      for (var si = 0; si < spots.length; si++) {
        x = spots[si][0]; y = spots[si][1];
        var candidate = { x1: x - w / 2 - 4, y1: y - L.size - 3, x2: x + w / 2 + 4, y2: y + 5 };
        var clash = taken.some(function (o) {
          return candidate.x1 < o.x2 && candidate.x2 > o.x1 && candidate.y1 < o.y2 && candidate.y2 > o.y1;
        });
        if (!clash || L.pri >= 4) { box = candidate; break; }
      }
      if (!box) { return; }
      taken.push(box);
      ctx.globalAlpha = L.dim ? 0.55 : 1;
      ctx.lineWidth = 3.5;
      ctx.lineJoin = "round";
      ctx.strokeStyle = bg;
      ctx.strokeText(L.text, x, y);
      ctx.fillStyle = L.n === hovered ? accent
        : (L.n.type === "file" && L.n.moving ? ink : (L.n.type === "file" || L.n.type === "storage" ? soft : ink));
      ctx.fillText(L.text, x, y);
      ctx.globalAlpha = 1;
    });

    // partition tags, like the story tags on the map
    tags.forEach(function (t) {
      ctx.font = '10px ui-monospace, "SF Mono", SFMono-Regular, Menlo, monospace';
      var w = ctx.measureText(t.text).width + 20;
      var x = t.x - w / 2, y = t.y - 18;
      ctx.globalAlpha = Math.min(1, mix * 1.4);
      ctx.fillStyle = panel;
      ctx.fillRect(x, y, w, 18);
      ctx.strokeStyle = ink;
      ctx.lineWidth = 1;
      ctx.strokeRect(x + 0.5, y + 0.5, w - 1, 17);
      ctx.fillStyle = accent;
      ctx.textAlign = "left";
      ctx.fillText("\u25C8", x + 6, y + 13);
      ctx.fillStyle = ink;
      ctx.fillText(t.text, x + 16, y + 13);
      ctx.globalAlpha = 1;
    });
    ctx.textAlign = "center";
  }

  // ---------- loop: runs only while something is moving ----------
  function frame(now) {
    var live = false;
    if (animStart) {
      var t = Math.min(1, (now - animStart) / animDur);
      mix = mixFrom + (mixTo - mixFrom) * ease(t);
      if (t >= 1) { animStart = 0; mix = mixTo; } else { live = true; }
    }
    if (flightUntil && now < flightUntil) { live = true; }
    else if (flightUntil && now >= flightUntil) { flightUntil = 0; go("after"); live = true; }
    draw();
    if (live) { requestAnimationFrame(frame); } else { running = false; }
  }
  function request() {
    if (running) { return; }
    running = true;
    requestAnimationFrame(frame);
  }
  function go(next) {
    state = next;
    mixFrom = mix;
    mixTo = next === "after" ? 1 : 0;
    animStart = reduce ? 0 : performance.now();
    if (reduce) { mix = mixTo; }
    syncChrome();
    request();
  }

  // ---------- chrome ----------
  var buttons = ROOT.querySelectorAll(".cfo-switch button");
  function syncChrome() {
    for (var i = 0; i < buttons.length; i++) {
      var on = buttons[i].dataset.state === state;
      buttons[i].classList.toggle("on", on);
      buttons[i].setAttribute("aria-pressed", on ? "true" : "false");
    }
  }
  buttons[0].textContent = TEXT.state_now;
  buttons[1].textContent = TEXT.state_after;
  for (var bi = 0; bi < buttons.length; bi++) {
    (function (b) {
      b.addEventListener("click", function () { flightUntil = 0; go(b.dataset.state); });
    })(buttons[bi]);
  }
  var shown = { moving: stats.moving || 0, staying: stats.staying || 0, reclaim: stats.reclaim_bytes || 0 };
  function statsChrome() {
    ROOT.querySelector(".cfo-stats").innerHTML =
      "<b>" + shown.moving + "</b> " + TEXT.stat_moving + "<br>" +
      "<b>" + shown.staying + "</b> " + TEXT.stat_staying + "<br>" +
      TEXT.stat_reclaim + " <b>" + bytes(shown.reclaim) + "</b>";
  }
  statsChrome();
  ROOT.querySelector(".cfo-colors").innerHTML =
    '<div><i style="background:var(--cfo-green)"></i>' + TEXT.legend_green + "</div>" +
    '<div><i style="background:var(--cfo-yellow)"></i>' + TEXT.legend_yellow + "</div>" +
    '<div><i style="background:var(--cfo-red)"></i>' + TEXT.legend_red + "</div>";
  ROOT.querySelector(".cfo-hint").textContent = TEXT.hint;
  ROOT.querySelector(".cfo-shapes").innerHTML =
    '<span><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><rect x="2.5" y="2.5" width="9" height="9" fill="none" stroke="currentColor"/></svg>' + TEXT.shape_partition + "</span>" +
    '<span><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><polygon points="11.5,7 9.25,10.9 4.75,10.9 2.5,7 4.75,3.1 9.25,3.1" fill="none" stroke="currentColor"/></svg>' + TEXT.shape_folder + "</span>" +
    '<span><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="var(--cfo-accent)" stroke="var(--cfo-accent)"/></svg>' + TEXT.shape_file + "</span>" +
    '<span><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><polygon points="7,1.8 12.2,7 7,12.2 1.8,7" fill="none" stroke="currentColor"/></svg>' + TEXT.shape_storage + "</span>";

  // ---------- interaction ----------
  function toWorld(x, y) {
    return { x: (x - W / 2 - cam.x) / cam.z, y: (y - H / 2 - cam.y) / cam.z };
  }
  function pick(x, y) {
    var best = null, bd = Infinity;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      var dx = sx(n) - x, dy = sy(n) - y, d = Math.hypot(dx, dy);
      if (d < Math.max(9, n.r * cam.z + 7) && d < bd) { best = n; bd = d; }
    }
    return best;
  }
  function showTip(n, x, y) {
    var rows = [];
    rows.push("<b>" + escapeHtml(n.label) + "</b>");
    if (n.size_bytes) { rows.push("<em>" + TEXT.tip_size + "</em> " + bytes(n.size_bytes)); }
    if (n.type === "file") {
      if (n.moving) {
        rows.push("<em>" + TEXT.tip_from + "</em> " + escapeHtml(n.from || ""));
        rows.push("<em>" + TEXT.tip_to + "</em> " + escapeHtml(n.to || ""));
      } else {
        rows.push("<em>" + TEXT.tip_stay + "</em>");
      }
    } else if (n.type === "storage" && n.from) {
      rows.push("<em>" + TEXT.tip_from + "</em> " + escapeHtml(n.from));
    } else if (n.to) {
      rows.push("<em>" + TEXT.tip_to + "</em> " + escapeHtml(n.to));
    }
    if (n.hint) { rows.push(escapeHtml(n.hint)); }
    tip.innerHTML = rows.join("<br>");
    tip.style.display = "block";
    var w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(6, Math.min(W - w - 6, x + 14)) + "px";
    tip.style.top = Math.max(6, Math.min(H - h - 6, y + 14)) + "px";
  }
  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  stage.addEventListener("pointerdown", function (e) {
    var r = cv.getBoundingClientRect();
    var x = e.clientX - r.left, y = e.clientY - r.top;
    var n = pick(x, y);
    if (n) { dragNode = n; } else { panning = true; stage.classList.add("cfo-drag"); }
    last = { x: x, y: y };
    if (stage.setPointerCapture) { stage.setPointerCapture(e.pointerId); }
  });
  stage.addEventListener("pointermove", function (e) {
    var r = cv.getBoundingClientRect();
    var x = e.clientX - r.left, y = e.clientY - r.top;
    if (dragNode) {
      var w = toWorld(x, y);
      dragNode.ax = w.x; dragNode.ay = w.y;
      dragNode.nx = w.x; dragNode.ny = w.y;
      draw();
      return;
    }
    if (panning) {
      cam.x += x - last.x; cam.y += y - last.y;
      last = { x: x, y: y };
      draw();
      return;
    }
    var n = pick(x, y);
    if (n !== hovered) {
      hovered = n;
      cv.style.cursor = n ? "pointer" : "";
      if (n) { showTip(n, x, y); } else { tip.style.display = "none"; }
      draw();
    } else if (n) {
      showTip(n, x, y);
    }
  });
  function release() {
    dragNode = null; panning = false;
    stage.classList.remove("cfo-drag");
  }
  stage.addEventListener("pointerup", release);
  stage.addEventListener("pointercancel", release);
  stage.addEventListener("pointerleave", function () {
    release();
    hovered = null;
    tip.style.display = "none";
    draw();
  });
  stage.addEventListener("wheel", function (e) {
    e.preventDefault();
    var r = cv.getBoundingClientRect();
    var mx = e.clientX - r.left, my = e.clientY - r.top;
    var before = toWorld(mx, my);
    cam.z = Math.max(0.15, Math.min(3.2, cam.z * (e.deltaY < 0 ? 1.12 : 0.89)));
    cam.x = mx - W / 2 - before.x * cam.z;
    cam.y = my - H / 2 - before.y * cam.z;
    draw();
  }, { passive: false });

  if (window.ResizeObserver) {
    new ResizeObserver(function () { resize(); }).observe(stage);
  }
  window.addEventListener("resize", resize);

  resize();
  syncChrome();
  // The whole trick: hold the mess for a beat, then let it fly into place.
  if (reduce) { mix = 1; state = "after"; syncChrome(); draw(); }
  else { flightUntil = performance.now() + 1000; request(); }
  // ---------- live selection ----------
  // The report page ticks and unticks rows; the picture should agree with it.
  // Only fills change: a node nobody ticked goes hollow, and the counter on the
  // panel follows.  Positions are already computed, so nothing here moves.
  function applySelection(detail) {
    var picked = {}, moved = 0, kept = 0;
    var actionIds = (detail && detail.action_ids) || [];
    var itemIds = (detail && detail.item_ids) || [];
    for (var i = 0; i < actionIds.length; i++) { picked["a:" + actionIds[i]] = true; }
    for (var j = 0; j < itemIds.length; j++) { picked["s:" + itemIds[j]] = true; }
    nodes.forEach(function (n) {
      if (n.type === "file") {
        if (!n.moving) { kept += 1; return; }
        n.solid = !!(picked["a:" + (n.action_id || "-")] || picked["a:" + n.id.slice(2)]);
        if (n.solid) { moved += 1; } else { kept += 1; }
        return;
      }
      if (n.type === "storage" && n.pending_clean) {
        n.solid = !!picked["s:" + n.id.slice(2)];
      }
    });
    shown.moving = moved;
    shown.staying = kept;
    statsChrome();
    draw();
  }
  window.addEventListener("cfo:selection", function (e) { applySelection(e.detail || {}); });

  ROOT.__cfoPreview = { nodes: nodes, links: links, go: go, cam: cam, stats: stats, select: applySelection };
})();
</script>
</section>"""


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _load(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="carl_file_organizer.preview",
        description="Render the after picture for a plan as a standalone HTML page.",
    )
    parser.add_argument("plan", help="path to plan.json")
    parser.add_argument("--analysis", default=None, help="path to a storage analysis JSON")
    parser.add_argument("-o", "--output", default=None, help="write the page here (default: stdout)")
    parser.add_argument("--lang", default=None, choices=["zh", "en"], help="page language")
    parser.add_argument("--height", type=int, default=720, help="canvas height in px")
    parser.add_argument("--fragment", action="store_true", help="emit only the <section>")
    args = parser.parse_args(list(argv) if argv is not None else None)

    plan = _load(args.plan)
    analysis = _load(args.analysis) if args.analysis else None
    graph = build_graph(plan, analysis)
    lang = args.lang or (plan.get("lang") if plan.get("lang") in ("zh", "en") else "zh")
    if args.fragment:
        html = render_preview_html(graph, lang=lang, height=args.height)
    else:
        html = render_preview_page(graph, lang=lang, height=args.height)

    if args.output:
        directory = os.path.dirname(os.path.abspath(args.output))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(html)
        sys.stderr.write(
            "preview: %d nodes, %d links -> %s\n"
            % (len(graph["nodes"]), len(graph["links"]), args.output)
        )
    else:
        sys.stdout.write(html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
