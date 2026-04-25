"""Localhost-only JSON HTTP server exposing UsageStats.

Runs on a background thread so the GTK / rumps main loop is never blocked.
Binds only to 127.0.0.1 by default; callers must explicitly opt into a
non-loopback address via config (and then understand the auth implications).
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from claude_usage.collector import UsageStats


def _redact_external(data: dict) -> dict:
    """Strip local paths and raw prompt content from serialized stats.

    Everything listed here gets rewritten because it can reveal either raw
    user prompt content, full local filesystem paths, Anthropic-internal
    identifiers, or Claude-generated narrative that mentions project names:

    - ``cache_opportunities[*].prefix_preview``  (user prompt excerpt)
    - ``active_sessions[*].cwd``                 (full home path)
    - ``ticker_items[*].msg_id``                 (Anthropic message id)
    - ``today_by_project`` keys                  (project folder names)
    - ``weekly_report_text``                     (Claude narrative)
    """
    opps = data.get("cache_opportunities") or []
    for o in opps:
        if isinstance(o, dict) and "prefix_preview" in o:
            length = len(str(o.get("prefix_preview", "") or ""))
            o["prefix_preview"] = f"[{length} chars — redacted]" if length else ""

    sessions = data.get("active_sessions") or []
    # Keep only fields that can't identify the user's local filesystem or a
    # project nickname. `name`, `cwd`, `sessionId`, `bridgeSessionId`, etc.
    # all fall into the leak bucket — we replace each dict with a minimal
    # shape carrying only timing metadata.
    safe_sessions = []
    for s in sessions:
        if not isinstance(s, dict):
            continue
        safe_sessions.append({
            "started_at": s.get("startedAt"),
            "updated_at": s.get("updatedAt"),
            "kind": s.get("kind"),
        })
    data["active_sessions"] = safe_sessions

    ticker = data.get("ticker_items") or []
    for it in ticker:
        if isinstance(it, dict) and "msg_id" in it:
            it["msg_id"] = ""

    projects = data.get("today_by_project") or {}
    if isinstance(projects, dict) and projects:
        data["today_by_project"] = {
            f"project_{i + 1}": v
            for i, (_k, v) in enumerate(projects.items())
        }

    if data.get("weekly_report_text"):
        data["weekly_report_text"] = "[redacted — see local popup]"

    return data


class UsageAPIServer:
    """Background HTTP server exposing /usage and /healthz."""

    def __init__(
        self,
        host: str,
        port: int,
        get_stats: Callable[[], UsageStats],
    ) -> None:
        self.host = host
        self._requested_port = port
        self._get_stats = get_stats
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """The bound port. Differs from the requested port when the caller
        passes 0 and the OS picks a free one — only known after start()."""
        if self._server is None:
            return self._requested_port
        return self._server.server_address[1]

    def start(self) -> None:
        """Bind the socket and start the background serving thread."""
        # Create the server first so we know the bound port, then build the
        # handler class with the real port baked into its Host whitelist
        # (matters when callers pass port=0 to let the OS pick a free one).
        self._server = ThreadingHTTPServer(
            (self.host, self._requested_port), BaseHTTPRequestHandler,
        )
        self._server.RequestHandlerClass = self._make_handler()
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="usage-api", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Shut down the server and wait for its thread to exit."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        get_stats = self._get_stats
        bound_port = self.port

        # DNS-rebinding defence: only honour requests whose Host header
        # resolves to literal loopback. An attacker page on evil.example
        # cannot spoof these.
        allowed_hosts = frozenset({
            f"127.0.0.1:{bound_port}",
            f"localhost:{bound_port}",
            f"[::1]:{bound_port}",
            "127.0.0.1",
            "localhost",
            "[::1]",
        })

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args) -> None:  # noqa: N802
                # Silence the default per-request stderr access log — the
                # widget runs in a desktop session and an interactive
                # terminal shouldn't fill up with HTTP chatter.
                return

            def _reject_if_bad_host(self) -> bool:
                host = (self.headers.get("Host") or "").lower()
                if host not in allowed_hosts:
                    self.send_error(403, "Forbidden")
                    return True
                return False

            def do_GET(self) -> None:  # noqa: N802
                if self._reject_if_bad_host():
                    return
                try:
                    if self.path == "/healthz":
                        self._send_json({"ok": True})
                        return
                    if self.path == "/usage":
                        stats = get_stats()
                        data = asdict(stats) if is_dataclass(stats) else dict(stats)
                        self._send_json(_redact_external(data))
                        return
                    self.send_error(404, "Not Found")
                except Exception:
                    # Never leak Python tracebacks to the caller — the
                    # default BaseHTTPRequestHandler behaviour would.
                    try:
                        self.send_error(500, "internal error")
                    except Exception:
                        pass

            def _send_json(self, payload: dict) -> None:
                body = json.dumps(payload, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        return Handler
