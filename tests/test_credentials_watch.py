"""Picking up Claude Code's refreshed token right away.

While the token is expired the widget backs its polls off to up to 5
minutes, so after Claude Code started and refreshed its token the OSD kept
saying "token expired · run claude" for minutes with Claude running. Only
Claude Code can fix a 401, by rewriting its credentials file, so the widget
watches that file and refreshes the moment it is rewritten.

Uses Qt's offscreen platform so the tests run headless on CI.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

from PySide6.QtWidgets import QApplication

from claude_usage.widget import CredentialsWatch

_app = QApplication.instance() or QApplication([])


def _watch(path) -> tuple[CredentialsWatch, list]:
    hits: list = []
    watch = CredentialsWatch(lambda: str(path))
    watch.changed.connect(lambda: hits.append(1))
    return watch, hits


def _write(path, mtime: float) -> None:
    path.write_text('{"claudeAiOauth": {}}')
    os.utime(path, (mtime, mtime))


def test_rewrite_after_the_expired_poll_began_triggers_a_refresh(tmp_path):
    creds = tmp_path / ".credentials.json"
    _write(creds, time.time() - 3600)
    watch, hits = _watch(creds)
    started = time.time() - 5
    watch.arm(since=started)
    watch._tick()
    assert hits == []
    _write(creds, time.time())  # Claude Code refreshed its token
    watch._tick()
    assert hits == [1]
    assert not watch.is_armed()
    watch._tick()
    assert hits == [1]  # once


def test_rewrite_during_the_expired_poll_still_counts(tmp_path):
    # The poll read the old token, Claude Code rewrote the file before the
    # 401 came back: the new token must not wait out the backoff.
    creds = tmp_path / ".credentials.json"
    started = time.time() - 2
    _write(creds, started + 1)
    watch, hits = _watch(creds)
    watch.arm(since=started)
    watch._tick()
    assert hits == [1]


def test_untouched_file_triggers_nothing(tmp_path):
    creds = tmp_path / ".credentials.json"
    _write(creds, time.time() - 3600)
    watch, hits = _watch(creds)
    watch.arm(since=time.time())
    for _ in range(3):
        watch._tick()
    assert hits == []
    assert watch.is_armed()


def test_missing_file_triggers_nothing(tmp_path):
    # Keychain or CLAUDE_CODE_OAUTH_TOKEN users have no file to watch; the
    # backed-off polls still cover them.
    watch, hits = _watch(tmp_path / ".credentials.json")
    watch.arm(since=time.time())
    watch._tick()
    assert hits == []


def test_disarm_stops_watching(tmp_path):
    creds = tmp_path / ".credentials.json"
    _write(creds, time.time() - 3600)
    watch, hits = _watch(creds)
    watch.arm(since=time.time() - 5)
    watch.disarm()
    _write(creds, time.time())
    watch._tick()
    assert hits == []
    assert not watch.is_armed()
