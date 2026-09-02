"""``review --serve``: the review page on 127.0.0.1 with one-click apply.

Security model (see docs/review-page.md):

* binds ``127.0.0.1`` only, port 0 by default, one random token per run;
* the token is printed to stderr once and handed to the browser in the URL;
  the page wipes it from the address bar and sends it as ``X-GN-Token``;
* every request checks the token with ``hmac.compare_digest``, the ``Host``
  header, and for POST the same-origin ``Origin`` header, JSON content type
  and a 1 MiB body cap;
* the server validates nothing about the plan itself.  ``/api/apply`` copies
  the plan, fills ``approved_action_ids`` / ``overrides`` and calls the very
  same ``apply_approved_plan`` the CLI uses, so every safety check lives in
  one place;
* single-threaded ``HTTPServer`` plus a lock: executions never overlap.
"""

from __future__ import annotations

import copy
import hmac
import json
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
from .report import render_report

MAX_BODY_BYTES = 1024 * 1024
DRAIN_LIMIT_BYTES = 8 * MAX_BODY_BYTES
TOKEN_HEADER = "X-GN-Token"
EXECUTED_STATUSES = ("moved", "trashed", "deleted")
JSON_TYPE = "application/json"

ApplyFn = Callable[..., Any]


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


def _load_plan(plan_path: Union[str, Path]) -> Dict[str, Any]:
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


class ReviewState:
    """Everything the handler needs, shared through ``server.gn_state``."""

    def __init__(
        self,
        plan: Dict[str, Any],
        *,
        token: str,
        allow_permanent_delete: bool,
        apply_fn: Optional[ApplyFn],
    ) -> None:
        self.plan = plan
        self.token = token
        self.allow_permanent_delete = allow_permanent_delete
        self._apply_fn = apply_fn
        self.lock = threading.Lock()
        self.executed_ids: List[str] = []
        self.port = 0
        caps = dict(plan.get("capabilities") or {})
        caps["permanent_delete_enabled"] = bool(allow_permanent_delete)
        self.plan["capabilities"] = caps

    @property
    def apply_fn(self) -> ApplyFn:
        if self._apply_fn is None:
            self._apply_fn = _default_apply_fn()
        return self._apply_fn

    def public_plan(self) -> Dict[str, Any]:
        """What leaves this process: the plan with every absolute path removed.

        Only the page and ``/api/plan`` get this.  ``self.plan`` keeps its
        absolute paths and is what ``/api/apply`` hands to the executor, so
        stripping here costs the apply path nothing.
        """

        data = paths.strip_absolute(self.plan)
        data["executed_ids"] = list(self.executed_ids)
        return data

    def kinds_for(self, action_ids: List[str]) -> Dict[str, str]:
        index = {str(a.get("id")): str(a.get("kind", "")) for a in self.plan.get("actions") or [] if isinstance(a, dict)}
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
    server_version = "CarlFileOrganizerReview/0.2"
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
                html = render_report(self.state.public_plan(), mode="serve", token=self.state.token)
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

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        if not self._guard_common():
            return
        path = urlsplit(self.path).path
        if path not in ("/api/apply", "/api/shutdown"):
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
        self._apply(body)

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
            plan = copy.deepcopy(state.plan)
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
    token: Optional[str] = None,
) -> Tuple[HTTPServer, str]:
    """Prepare (but do not run) the review server.  Returns ``(server, token)``."""

    data = _load_plan(plan) if not isinstance(plan, dict) else copy.deepcopy(plan)
    token = token or secrets.token_urlsafe(32)
    state = ReviewState(
        data, token=token, allow_permanent_delete=allow_permanent_delete, apply_fn=apply_fn
    )
    server = HTTPServer((host, port), ReviewHandler)
    state.port = server.server_address[1]
    server.gn_state = state  # type: ignore[attr-defined]
    return server, token


def serve_review(
    plan_path: Union[str, Path],
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    allow_permanent_delete: bool = False,
    open_browser: bool = True,
    apply_fn: Optional[ApplyFn] = None,
) -> int:
    """Run the review server until Ctrl-C or ``POST /api/shutdown``."""

    server, token = build_server(
        plan_path,
        host=host,
        port=port,
        allow_permanent_delete=allow_permanent_delete,
        apply_fn=apply_fn,
    )
    if apply_fn is None:
        # fail early with a clear line instead of a 422 on the first click
        server.gn_state.apply_fn  # type: ignore[attr-defined]  # noqa: B018
    bound_port = server.server_address[1]
    url = "http://127.0.0.1:{0}/?t={1}".format(bound_port, token)
    sys.stderr.write("review page (token inside, only on this line): {0}\n".format(url))
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
