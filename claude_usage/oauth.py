"""Refresh Claude Code's expired OAuth access token in ``.credentials.json``.

The access token Claude Code writes lives ~8h and only the CLI refreshes it,
on its own next run. Users who drive Claude through the desktop app or IDE
never run the CLI, so after one night the widget reads an expired token and
shows "Credentials expired" until they happen to launch ``claude``. This
module does what the CLI does on startup: trade the refresh token for a new
access token and write the rotated pair back, so the CLI and the widget keep
sharing one valid session.

Refresh tokens rotate: if two processes refresh the same token, one of them
ends up holding a revoked token and the user is logged out. Coordination
therefore follows Claude Code (2.1.x) itself:

- the same two directory locks, ``<claude_dir>/.oauth_refresh.lock`` and the
  legacy ``<realpath(claude_dir)>.lock`` that older clients still take, with
  proper-lockfile semantics (``mkdir`` is the atomic acquire, a lock older
  than 60s is stale; stealing a stale lock has the same small race
  proper-lockfile accepts);
- a re-read under the locks, and again right before writing, so a refresh or
  ``/login`` done by someone else is never overwritten;
- an atomic, fsynced ``os.replace`` write.

A slow request only makes a concurrent CLI skip its own refresh (it gives up
waiting for the lock after ~7.5s and reloads the file once we write it),
while a short timeout could drop a token the server has already rotated. So
the per-socket-operation timeout is 15s, far below the 60s stale threshold.

Only Linux is supported. On macOS Claude Code keeps the live credentials in
the Keychain, and refreshing a leftover flat file would revoke that copy. On
Windows ``os.replace`` fails while another process (antivirus, indexer) holds
the file open, which would lose the rotated token; it needs its own
validation before being enabled.

Every failure leaves the file untouched and returns silently: the caller
then sends the old token and surfaces the usual "Credentials expired". The
one loss that cannot be avoided is a write failing after the server has
already rotated the token; the temp file is created up front to make that
as unlikely as possible, and the user then has to log in again.
"""

from __future__ import annotations

import http.client
import json
import math
import os
import ssl
import sys
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
# Claude Code's public OAuth client id; the refresh token is bound to it.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
LOCK_NAME = ".oauth_refresh.lock"
LOCK_STALE_SECONDS = 60
# Refresh slightly early so a token can't expire between check and use.
EXPIRY_MARGIN_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 15
# Bounds a hostile/garbled expires_in so the expiry arithmetic can't overflow.
MAX_EXPIRES_IN_SECONDS = 10**9

# Refresh tokens the server rejected. Without this a dead token would be
# re-sent on every poll until the user logs in again.
_dead_refresh_tokens: set[str] = set()


def refresh_if_expired(creds_path: str, ssl_context: ssl.SSLContext | None = None) -> None:
    """Refresh the access token in *creds_path* when it is (nearly) expired."""
    if not sys.platform.startswith("linux") or os.path.islink(creds_path):
        # A symlink would be replaced by a plain file, leaving its target
        # with the revoked token.
        return
    if not _needs_refresh(_read_oauth(creds_path)):
        return
    claude_dir = os.path.dirname(creds_path)
    lock_dirs = [os.path.join(claude_dir, LOCK_NAME),
                 os.path.realpath(claude_dir) + ".lock"]
    held: list[tuple[str, tuple[int, int]]] = []
    try:
        for lock_dir in lock_dirs:
            identity = _acquire_lock(lock_dir)
            if identity is None:
                return  # Another process is refreshing; next poll reads its result.
            held.append((lock_dir, identity))
        _refresh_locked(creds_path, ssl_context)
    finally:
        for lock_dir, identity in reversed(held):
            _release_lock(lock_dir, identity)


def _refresh_locked(creds_path: str, ssl_context: ssl.SSLContext | None) -> None:
    oauth = _read_oauth(creds_path)
    if not _needs_refresh(oauth):
        return  # Refreshed by someone else while we waited.
    sent_refresh_token = oauth["refreshToken"]
    claude_dir = os.path.dirname(creds_path)
    # Create the 0600 temp file before spending the refresh token, so an
    # unwritable directory fails while the old token is still valid.
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".credentials.", suffix=".tmp", dir=claude_dir)
    except OSError:
        return
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tokens = _request_tokens(oauth, ssl_context)
            if tokens is None:
                return
            creds = _read_creds(creds_path)
            current = creds.get("claudeAiOauth") if creds else None
            if not isinstance(current, dict) or current.get("refreshToken") != sent_refresh_token:
                return  # Changed meanwhile (e.g. a /login); keep the newer state.
            current.update(tokens)
            json.dump(creds, tmp, separators=(",", ":"))
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, creds_path)
        replaced = True
        _fsync_dir(claude_dir)  # Durable across a power cut.
    except OSError:
        pass
    finally:
        if not replaced:
            _unlink_quietly(tmp_path)


def _read_creds(creds_path: str) -> dict[str, Any] | None:
    try:
        with open(creds_path, encoding="utf-8") as f:
            creds = json.load(f)
    except (OSError, ValueError):
        return None
    return creds if isinstance(creds, dict) else None


def _read_oauth(creds_path: str) -> dict[str, Any] | None:
    creds = _read_creds(creds_path)
    oauth = creds.get("claudeAiOauth") if creds else None
    return oauth if isinstance(oauth, dict) else None


def _is_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _needs_refresh(oauth: Any) -> bool:
    if not isinstance(oauth, dict):
        return False
    refresh_token = oauth.get("refreshToken")
    if not isinstance(refresh_token, str) or not refresh_token:
        return False
    if refresh_token in _dead_refresh_tokens:
        return False
    now = time.time()
    refresh_expires_at_ms = oauth.get("refreshTokenExpiresAt")
    if _is_number(refresh_expires_at_ms) and refresh_expires_at_ms / 1000 <= now:
        return False
    expires_at_ms = oauth.get("expiresAt")
    if not _is_number(expires_at_ms):
        return False
    return expires_at_ms / 1000 - now < EXPIRY_MARGIN_SECONDS


def _acquire_lock(lock_dir: str) -> tuple[int, int] | None:
    """Take *lock_dir*; return its identity so release can check ownership.

    Inode plus mtime, because ext4 reuses a freed inode right away.
    """
    for _ in range(2):
        try:
            os.mkdir(lock_dir)
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock_dir)
            except OSError:
                continue  # Released between mkdir and stat; try again.
            if age < LOCK_STALE_SECONDS:
                return None
            try:
                os.rmdir(lock_dir)  # Stale: its owner died mid-refresh.
            except OSError:
                return None
        except OSError:
            return None
        else:
            try:
                return _lock_identity(lock_dir)
            except OSError:
                _remove_dir_quietly(lock_dir)
                return None
    return None


def _remove_dir_quietly(path: str) -> None:
    try:
        os.rmdir(path)
    except OSError:
        pass


def _lock_identity(lock_dir: str) -> tuple[int, int]:
    st = os.stat(lock_dir)
    return st.st_ino, st.st_mtime_ns


def _release_lock(lock_dir: str, identity: tuple[int, int]) -> None:
    """Remove *lock_dir* only if it is still the one we created."""
    try:
        if _lock_identity(lock_dir) != identity:
            return
    except OSError:
        return
    _remove_dir_quietly(lock_dir)


def _request_tokens(oauth: dict[str, Any], ssl_context: ssl.SSLContext | None) -> dict[str, Any] | None:
    """POST the refresh grant; return the credential fields to update."""
    refresh_token = oauth["refreshToken"]
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
    }
    scopes = oauth.get("scopes")
    if isinstance(scopes, list) and scopes:
        # Without an explicit scope the server may narrow the grant and drop
        # user:profile, which /api/oauth/usage requires.
        body["scope"] = " ".join(str(s) for s in scopes)
    req = Request(
        TOKEN_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "User-Agent": "claude-usage-widget"},
    )
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS, context=ssl_context) as resp:
            payload = json.loads(resp.read(65536).decode("utf-8", errors="replace"))
    except HTTPError as e:
        with e:
            if _is_invalid_grant(e):
                _dead_refresh_tokens.add(refresh_token)
        return None
    except (URLError, OSError, http.client.HTTPException, ValueError):
        return None
    return _parse_token_response(payload, refresh_token)


def _is_invalid_grant(error: HTTPError) -> bool:
    """True when the server says the refresh token itself is dead.

    Other 4xx (e.g. invalid_scope) may be transient or fixable, so they must
    not disable refreshing for the rest of the process.
    """
    if error.code not in (400, 401):
        return False
    try:
        body = json.loads(error.read(65536).decode("utf-8", errors="replace"))
    except (OSError, http.client.HTTPException, ValueError):
        return False
    return isinstance(body, dict) and body.get("error") == "invalid_grant"


def _parse_token_response(payload: Any, old_refresh_token: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    access_token = payload.get("access_token")
    expires_in = payload.get("expires_in")
    if not isinstance(access_token, str) or not access_token:
        return None
    if not _is_number(expires_in) or not 0 < expires_in <= MAX_EXPIRES_IN_SECONDS:
        return None
    now_ms = int(time.time() * 1000)
    refresh_token = payload.get("refresh_token")
    tokens: dict[str, Any] = {
        "accessToken": access_token,
        # The server omits refresh_token when it does not rotate it.
        "refreshToken": refresh_token if isinstance(refresh_token, str) and refresh_token
        else old_refresh_token,
        "expiresAt": now_ms + int(expires_in * 1000),
    }
    refresh_expires_in = payload.get("refresh_token_expires_in")
    if _is_number(refresh_expires_in) and 0 < refresh_expires_in <= MAX_EXPIRES_IN_SECONDS:
        tokens["refreshTokenExpiresAt"] = now_ms + int(refresh_expires_in * 1000)
    scope = payload.get("scope")
    if isinstance(scope, str) and scope.strip():
        tokens["scopes"] = scope.split()
    return tokens


def _fsync_dir(path: str) -> None:
    dir_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
