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
    """Strip raw prompt content from serialized stats.

    ``cache_opportunities[*].prefix_preview`` is the first ~100 chars of an
    actual user prompt — fine for the local Qt popup, but we don't want
    callers of ``/usage`` or ``--json`` slurping prompt text into logs.
    """
    opps = data.get("cache_opportunities") or []
    for o in opps:
        if isinstance(o, dict) and "prefix_preview" in o:
            length = len(str(o.get("prefix_preview", "") or ""))
            o["prefix_preview"] = f"[{length} chars — redacted]" if length else ""
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
        if self._server is None:
            return self._requested_port
        return self._server.server_address[1]

    def start(self) -> None:
        """Bind the socket and start the background serving thread."""
        handler_cls = self._make_handler()
        self._server = ThreadingHTTPServer((self.host, self._requested_port), handler_cls)
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

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args) -> None:  # noqa: N802
                return

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/healthz":
                    self._send_json({"ok": True})
                    return
                if self.path == "/usage":
                    stats = get_stats()
                    data = asdict(stats) if is_dataclass(stats) else dict(stats)
                    self._send_json(_redact_external(data))
                    return
                self.send_error(404, "Not Found")

            def _send_json(self, payload: dict) -> None:
                body = json.dumps(payload, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        return Handler
