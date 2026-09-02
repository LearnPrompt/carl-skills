"""``review --serve`` and ``storage-report --serve``: the page on 127.0.0.1.

One server, one page, whichever halves it was handed.  A plan.json alone
answers ``/api/apply``, an analysis.json alone answers ``/api/dispose``, and the
combined envelope ``{"plan": ..., "analysis": ...}`` answers both, which is what
``report --serve`` sends.  Everything else -- the page itself, the token, the
checks, the reveal endpoint, the shutdown -- is the same in all three cases,
because there is one template and one set of rules about what may leave this
process.

Security model (see docs/review-page.md):

* binds ``127.0.0.1`` only, port 0 by default, one random token per run;
* the token is printed to stderr once and handed to the browser in the URL;
  the page wipes it from the address bar and sends it as ``X-GN-Token``;
* every request checks the token with ``hmac.compare_digest``, the ``Host``
  header, and for POST the same-origin ``Origin`` header, JSON content type
  and a 1 MiB body cap;
* the server validates nothing about the plan or the analysis itself.
  ``/api/apply`` fills ``approved_action_ids`` and calls the very same
  ``apply_approved_plan`` the CLI uses; ``/api/dispose`` builds a decisions
  document and calls the very same ``dispose.apply_decisions``.  Every safety
  check lives in one place, and it is not this file;
* single-threaded ``HTTPServer`` plus a lock: executions never overlap.
"""

from __future__ import annotations

import copy
import hmac
import json
import os
import secrets
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlsplit

from . import paths
from . import render as render_module

MAX_BODY_BYTES = 1024 * 1024
DRAIN_LIMIT_BYTES = 8 * MAX_BODY_BYTES
TOKEN_HEADER = "X-GN-Token"
EXECUTED_STATUSES = ("moved", "trashed", "deleted")
JSON_TYPE = "application/json"

ORGANIZE = "organize"
STORAGE = "storage"
COMBINED = "combined"

ApplyFn = Callable[..., Any]
DisposeFn = Callable[..., Any]
RevealFn = Callable[..., bool]


class ServerError(RuntimeError):
    """Raised when the review server cannot be prepared."""


def _default_apply_fn() -> ApplyFn:
    try:
        from .executor import apply_approved_plan
    except ImportError as error:  # pragma: no cover - depends on the executor work package
        raise ServerError(
            "executor.apply_approved_plan is unavailable ({0}); review --serve needs it".format(error)
        ) from error
    return apply_approved_plan


def _default_dispose_fn() -> DisposeFn:
    try:
        from .dispose import apply_decisions
    except ImportError as error:  # pragma: no cover - depends on the dispose module
        raise ServerError(
            "dispose.apply_decisions is unavailable ({0}); the storage page needs it".format(error)
        ) from error
    return apply_decisions


def _default_reveal_fn() -> RevealFn:
    from .opener import reveal

    return reveal


def _load_plan(plan_path: Union[str, Path]) -> Dict[str, Any]:
    """Read the plan.json or analysis.json this run is about."""

    path = Path(plan_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ServerError("cannot read plan: {0}".format(error)) from error
    except ValueError as error:
        raise ServerError("plan is not valid JSON: {0}".format(error)) from error
    if not isinstance(data, dict):
        raise ServerError("plan must be a JSON object")
    return data


def detect_kind(data: Dict[str, Any]) -> str:
    """Which page this document asks for, or a refusal saying it asks for neither."""

    try:
        return render_module.detect_kind(data)
    except render_module.RenderError as error:
        raise ServerError(str(error)) from error


class ReviewState:
    """Everything the handler needs, shared through ``server.gn_state``."""

    def __init__(
        self,
        plan: Dict[str, Any],
        *,
        token: str,
        allow_permanent_delete: bool,
        apply_fn: Optional[ApplyFn],
        kind: Optional[str] = None,
        home: Optional[Path] = None,
        managed_dir: Optional[Path] = None,
        dispose_fn: Optional[DisposeFn] = None,
        reveal_fn: Optional[RevealFn] = None,
        notes: Optional[Dict[str, Any]] = None,
        lang: Optional[str] = None,
    ) -> None:
        self.plan = plan
        self.kind = kind or detect_kind(plan)
        self.token = token
        self.allow_permanent_delete = allow_permanent_delete
        self._apply_fn = apply_fn
        self._dispose_fn = dispose_fn
        self._reveal_fn = reveal_fn
        self.notes = notes
        self.lang = lang
        self.lock = threading.Lock()
        self.executed_ids: List[str] = []
        self.port = 0
        self.home = Path(home) if home is not None else self._home_of(plan)
        self.managed_dir = Path(managed_dir) if managed_dir is not None else None
        for document in self._documents():
            caps = dict(document.get("capabilities") or {})
            caps["permanent_delete_enabled"] = bool(allow_permanent_delete)
            document["capabilities"] = caps

    def _documents(self) -> List[Dict[str, Any]]:
        """The one or two documents this run is about, in the order they render."""

        if self.kind != COMBINED:
            return [self.plan]
        return [half for half in (self.organize_doc, self.storage_doc) if half]

    @property
    def organize_doc(self) -> Dict[str, Any]:
        """The tidy-up half, or an empty dict when this run has none."""

        if self.kind == STORAGE:
            return {}
        if self.kind == ORGANIZE:
            return self.plan
        inner = self.plan.get("plan")
        return inner if isinstance(inner, dict) else {}

    @property
    def storage_doc(self) -> Dict[str, Any]:
        """The whole-machine half, or an empty dict when this run has none."""

        if self.kind == ORGANIZE:
            return {}
        if self.kind == STORAGE:
            return self.plan
        inner = self.plan.get("analysis")
        return inner if isinstance(inner, dict) else {}

    def _home_of(self, plan: Dict[str, Any]) -> Path:
        organize = self.organize_doc
        if organize:
            return Path(paths.plan_home(organize))
        return Path.home()

    @property
    def apply_fn(self) -> ApplyFn:
        if self._apply_fn is None:
            self._apply_fn = _default_apply_fn()
        return self._apply_fn

    @property
    def dispose_fn(self) -> DisposeFn:
        if self._dispose_fn is None:
            self._dispose_fn = _default_dispose_fn()
        return self._dispose_fn

    @property
    def reveal_fn(self) -> RevealFn:
        if self._reveal_fn is None:
            self._reveal_fn = _default_reveal_fn()
        return self._reveal_fn

    def public_plan(self) -> Dict[str, Any]:
        """What leaves this process: the document with every absolute path removed.

        Only the page and ``/api/plan`` get this.  ``self.plan`` keeps its
        absolute paths and is what ``/api/apply`` and ``/api/dispose`` hand to
        the engine, so stripping here costs the acting path nothing.
        """

        if self.kind == ORGANIZE:
            data = paths.strip_absolute(self.plan)
        elif self.kind == STORAGE:
            data = render_module.sanitize(self.plan, self.home)
        else:
            data = {}
            if self.organize_doc:
                data["plan"] = paths.strip_absolute(self.organize_doc)
            if self.storage_doc:
                data["analysis"] = render_module.sanitize(self.storage_doc, self.home)
            data["capabilities"] = dict((self.storage_doc or self.organize_doc).get("capabilities") or {})
        data["executed_ids"] = list(self.executed_ids)
        return data

    def page(self) -> str:
        """The rendered page, from the same renderer ``build_report.py`` uses."""

        data = copy.deepcopy(self.plan)
        data["executed_ids"] = list(self.executed_ids)
        try:
            return render_module.render(
                data,
                mode="serve",
                token=self.token,
                lang=self.lang,
                notes=self.notes,
                kind=self.kind,
                home=self.home,
            )
        except render_module.RenderError as error:
            raise ServerError(str(error)) from error

    def kinds_for(self, action_ids: List[str]) -> Dict[str, str]:
        actions = (self.organize_doc or {}).get("actions") or []
        index = {str(a.get("id")): str(a.get("kind", "")) for a in actions if isinstance(a, dict)}
        return {i: index.get(i, "") for i in action_ids}


def _normalize_results(report: Any) -> List[Dict[str, Any]]:
    """``ApplyReport.results`` or a bare list of dicts -> list of dicts."""

    results = getattr(report, "results", report)
    if results is None:
        return []
    out = []
    for item in results:
        if isinstance(item, dict):
            out.append(item)
        else:
            out.append(
                {
                    "action_id": getattr(item, "action_id", None),
                    "status": getattr(item, "status", None),
                    "detail": getattr(item, "detail", None),
                }
            )
    return out


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "CarlFileOrganizerReview/0.3"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    # -- plumbing -----------------------------------------------------------

    @property
    def state(self) -> ReviewState:
        return self.server.gn_state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        # never echo the query string (it carries the token on first load)
        path = urlsplit(self.path).path
        sys.stderr.write(
            "{0} - {1} {2} {3}\n".format(self.address_string(), self.command, path, args[1] if len(args) > 1 else "")
        )

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", JSON_TYPE + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _origin(self) -> str:
        return "http://127.0.0.1:{0}".format(self.state.port)

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") == "127.0.0.1:{0}".format(self.state.port)

    def _token_ok(self, presented: Optional[str]) -> bool:
        return hmac.compare_digest(str(presented or ""), self.state.token)

    def _guard_common(self) -> bool:
        if not self._host_ok():
            self._send_json(400, {"error": "bad Host header"})
            return False
        return True

    # -- GET ----------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if not self._guard_common():
            return
        parts = urlsplit(self.path)
        if parts.path == "/":
            token = (parse_qs(parts.query).get("t") or [""])[0]
            if not self._token_ok(token):
                self._send_json(401, {"error": "missing or wrong token"})
                return
            with self.state.lock:
                html = self.state.page()
            self._send_html(html)
            return
        if not self._token_ok(self.headers.get(TOKEN_HEADER)):
            self._send_json(401, {"error": "missing or wrong token"})
            return
        if parts.path == "/api/plan":
            with self.state.lock:
                self._send_json(200, self.state.public_plan())
            return
        self._send_json(404, {"error": "not found"})

    # -- POST ---------------------------------------------------------------

    def _read_json_body(self) -> Optional[Dict[str, Any]]:
        origin = self.headers.get("Origin", "")
        if origin != self._origin():
            self._send_json(403, {"error": "Origin must be {0}".format(self._origin())})
            return None
        if not self._token_ok(self.headers.get(TOKEN_HEADER)):
            self._send_json(401, {"error": "missing or wrong token"})
            return None
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type != JSON_TYPE:
            self._send_json(415, {"error": "Content-Type must be application/json"})
            return None
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "bad Content-Length"})
            return None
        if length < 0 or length > MAX_BODY_BYTES:
            self._drain(length)
            self._send_json(413, {"error": "body larger than 1 MiB"})
            return None
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._send_json(400, {"error": "body is not valid JSON"})
            return None
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return None
        return data

    def _drain(self, length: int) -> None:
        """Read and discard an oversized body (bounded) so the client sees the 413, not a reset."""

        remaining = min(max(length, 0), DRAIN_LIMIT_BYTES)
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)

    def _endpoints(self) -> Dict[str, Callable[[Dict[str, Any]], None]]:
        table: Dict[str, Callable[[Dict[str, Any]], None]] = {"/api/reveal": self._reveal}
        if self.state.organize_doc:
            table["/api/apply"] = self._apply
        if self.state.storage_doc:
            table["/api/dispose"] = self._dispose
        return table

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        if not self._guard_common():
            return
        path = urlsplit(self.path).path
        table = self._endpoints()
        if path not in table and path != "/api/shutdown":
            # keep the same checks for unknown paths so probing reveals nothing
            if self._read_json_body() is not None:
                self._send_json(404, {"error": "not found"})
            return
        body = self._read_json_body()
        if body is None:
            return
        if path == "/api/shutdown":
            self._send_json(200, {"ok": True, "shutting_down": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        table[path](body)

    # -- the tidy-up page ---------------------------------------------------

    def _apply(self, body: Dict[str, Any]) -> None:
        action_ids = body.get("action_ids")
        overrides = body.get("overrides", [])
        dry_run = bool(body.get("dry_run", False))
        if not isinstance(action_ids, list) or not all(isinstance(i, str) for i in action_ids):
            self._send_json(400, {"error": "action_ids must be a list of strings"})
            return
        if not action_ids:
            self._send_json(400, {"error": "action_ids is empty"})
            return
        if not isinstance(overrides, list) or not all(isinstance(o, dict) for o in overrides):
            self._send_json(400, {"error": "overrides must be a list of objects"})
            return
        state = self.state
        with state.lock:
            repeated = sorted(set(action_ids) & set(state.executed_ids))
            if repeated:
                self._send_json(409, {"error": "already executed", "action_ids": repeated})
                return
            kinds = state.kinds_for(action_ids)
            deletes = sorted(i for i, kind in kinds.items() if kind == "delete")
            if deletes and not state.allow_permanent_delete:
                self._send_json(
                    403,
                    {
                        "error": "permanent delete is off; restart with --allow-permanent-delete",
                        "action_ids": deletes,
                    },
                )
                return
            plan = copy.deepcopy(state.organize_doc)
            plan["approved_action_ids"] = list(action_ids)
            plan["overrides"] = list(overrides)
            plan["approved_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            plan["approved_by"] = "serve"
            try:
                report = state.apply_fn(
                    plan, dry_run=dry_run, allow_permanent_delete=state.allow_permanent_delete
                )
            except Exception as error:  # noqa: BLE001 - executor refusals become one JSON line
                self._send_json(422, {"error": "{0}: {1}".format(type(error).__name__, error)})
                return
            results = _normalize_results(report)
            newly_done = []
            if not dry_run:
                for item in results:
                    if item.get("status") in EXECUTED_STATUSES and item.get("action_id"):
                        aid = str(item["action_id"])
                        if aid not in state.executed_ids:
                            state.executed_ids.append(aid)
                            newly_done.append(aid)
            payload: Dict[str, Any] = {
                "ok": True,
                "dry_run": dry_run,
                "results": results,
                "executed_ids": list(state.executed_ids),
                "newly_executed": newly_done,
            }
            for key in ("run_id", "manifest", "audit"):
                value = getattr(report, key, None)
                if value is not None:
                    payload[key] = str(value)
            self._send_json(200, payload)

    # -- the whole-machine page ---------------------------------------------

    def _dispose(self, body: Dict[str, Any]) -> None:
        item_ids = body.get("item_ids")
        action = body.get("action", "trash")
        if not isinstance(item_ids, list) or not all(isinstance(i, str) for i in item_ids):
            self._send_json(400, {"error": "item_ids must be a list of strings"})
            return
        if not item_ids:
            self._send_json(400, {"error": "item_ids is empty"})
            return
        if action not in ("trash", "delete"):
            self._send_json(400, {"error": 'action must be "trash" or "delete"'})
            return
        state = self.state
        with state.lock:
            if action == "delete" and not state.allow_permanent_delete:
                self._send_json(
                    403,
                    {
                        "error": "permanent delete is off; restart with --allow-permanent-delete",
                        "item_ids": sorted(item_ids),
                    },
                )
                return
            repeated = sorted(set(item_ids) & set(state.executed_ids))
            if repeated:
                self._send_json(409, {"error": "already executed", "item_ids": repeated})
                return
            decisions = {
                "schema": "carl-file-organizer/storage-decisions",
                "schema_version": 1,
                "item_ids": list(item_ids),
                "actions": {i: action for i in item_ids},
                "decided_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "decided_by": "serve",
            }
            try:
                report = state.dispose_fn(
                    copy.deepcopy(state.storage_doc),
                    decisions,
                    dry_run=False,
                    allow_permanent_delete=state.allow_permanent_delete,
                    home=state.home,
                    managed_dir=state.managed_dir,
                )
            except Exception as error:  # noqa: BLE001 - a refusal becomes one JSON line
                self._send_json(422, {"error": "{0}: {1}".format(type(error).__name__, error)})
                return
            results = _normalize_results(report)
            newly_done = []
            for item in results:
                if item.get("status") in EXECUTED_STATUSES and item.get("item_id"):
                    iid = str(item["item_id"])
                    if iid not in state.executed_ids:
                        state.executed_ids.append(iid)
                        newly_done.append(iid)
            payload: Dict[str, Any] = {
                "ok": True,
                "dry_run": False,
                "action": action,
                "results": results,
                "executed_ids": list(state.executed_ids),
                "newly_executed": newly_done,
            }
            for key in ("run_id", "manifest", "audit"):
                value = getattr(report, key, None)
                if value is not None:
                    payload[key] = str(value)
            self._send_json(200, payload)

    # -- both pages ---------------------------------------------------------

    def _reveal(self, body: Dict[str, Any]) -> None:
        """Put a folder on screen.  Reads nothing, writes nothing, moves nothing."""

        portable = body.get("path_portable")
        if not isinstance(portable, str) or not portable.strip():
            self._send_json(400, {"error": "path_portable must be a non-empty string"})
            return
        state = self.state
        target = paths.expand_portable(portable, state.home)
        if not paths.inside_root(target, state.home):
            self._send_json(403, {"error": "that path is outside the home directory"})
            return
        if not os.path.lexists(str(target)):
            self._send_json(404, {"error": "that path is not there any more"})
            return
        try:
            shown = bool(state.reveal_fn(target))
        except Exception as error:  # noqa: BLE001 - a file manager is never worth a 500
            self._send_json(200, {"ok": False, "error": str(error)})
            return
        self._send_json(200, {"ok": shown, "path_portable": portable})


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def build_server(
    plan: Union[Dict[str, Any], str, Path],
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    allow_permanent_delete: bool = False,
    apply_fn: Optional[ApplyFn] = None,
    dispose_fn: Optional[DisposeFn] = None,
    reveal_fn: Optional[RevealFn] = None,
    token: Optional[str] = None,
    home: Optional[Path] = None,
    managed_dir: Optional[Path] = None,
    notes: Optional[Dict[str, Any]] = None,
    lang: Optional[str] = None,
) -> Tuple[HTTPServer, str]:
    """Prepare (but do not run) the review server.  Returns ``(server, token)``."""

    data = _load_plan(plan) if not isinstance(plan, dict) else copy.deepcopy(plan)
    token = token or secrets.token_urlsafe(32)
    state = ReviewState(
        data,
        token=token,
        allow_permanent_delete=allow_permanent_delete,
        apply_fn=apply_fn,
        dispose_fn=dispose_fn,
        reveal_fn=reveal_fn,
        home=home,
        managed_dir=managed_dir,
        notes=notes,
        lang=lang,
    )
    server = HTTPServer((host, port), ReviewHandler)
    state.port = server.server_address[1]
    server.gn_state = state  # type: ignore[attr-defined]
    return server, token


def serve_review(
    plan_path: Union[str, Path, Dict[str, Any]],
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    allow_permanent_delete: bool = False,
    open_browser: bool = True,
    apply_fn: Optional[ApplyFn] = None,
    dispose_fn: Optional[DisposeFn] = None,
    home: Optional[Path] = None,
    managed_dir: Optional[Path] = None,
    notes: Optional[Dict[str, Any]] = None,
    lang: Optional[str] = None,
) -> int:
    """Run the review server until Ctrl-C or ``POST /api/shutdown``."""

    server, token = build_server(
        plan_path,
        host=host,
        port=port,
        allow_permanent_delete=allow_permanent_delete,
        apply_fn=apply_fn,
        dispose_fn=dispose_fn,
        home=home,
        managed_dir=managed_dir,
        notes=notes,
        lang=lang,
    )
    state = server.gn_state  # type: ignore[attr-defined]
    # fail early with a clear line instead of a 422 on the first click
    if state.organize_doc and apply_fn is None:
        state.apply_fn  # noqa: B018
    if state.storage_doc and dispose_fn is None:
        state.dispose_fn  # noqa: B018
    bound_port = server.server_address[1]
    url = "http://127.0.0.1:{0}/?t={1}".format(bound_port, token)
    sys.stderr.write("review page (token inside, only on this line): {0}\n".format(url))
    sys.stderr.write("page kind: {0}\n".format(state.kind))
    if allow_permanent_delete:
        sys.stderr.write("permanent delete is ENABLED for this session\n")
    sys.stderr.write("press Ctrl-C to stop\n")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - a browser failure is not fatal
            pass
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0


def run(args: Any) -> int:
    """CLI entry: ``review <plan.json> --serve [--port N] [--no-open] [--allow-permanent-delete]``."""

    return serve_review(
        args.plan,
        port=int(getattr(args, "port", 0) or 0),
        allow_permanent_delete=bool(getattr(args, "allow_permanent_delete", False)),
        open_browser=bool(getattr(args, "open_browser", True)),
    )
