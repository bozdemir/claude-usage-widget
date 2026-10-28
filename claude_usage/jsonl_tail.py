"""Incremental reads of append-only JSONL files.

Claude Code only ever appends to a conversation transcript. The refresh
scans that run every minute used to decode every line of every recent
transcript, several scans over the same files, which kept a core busy for a
second or two each minute on a heavy user's ``~/.claude`` (issue #39).

A :class:`JsonlTail` remembers, per file, how far it has read and what its
extractor kept, and decodes only the bytes appended since. A file that was
replaced, truncated or rewritten in place is read again from the start, so
the result is always what a full read would give.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

# Bytes compared to tell an append from a rewrite: the start of the file and
# the stretch just before where the last read stopped.
_HEAD_BYTES = 1024
_EDGE_BYTES = 64


@dataclass
class _FileState:
    ino: int
    offset: int = 0     # end of the last complete line consumed
    touched: bool = True
    head: bytes = b""
    edge: bytes = b""
    records: list = field(default_factory=list)
    # From an unterminated last line: read like a full read would, but kept
    # apart because the writer may still be adding to it.
    tail_records: list = field(default_factory=list)


class JsonlTail:
    """Per-file cache of what *extract* keeps from each line of a JSONL file.

    *extract* gets each line's decoded JSON object and returns the record to
    keep, or None to skip the line. Blank lines, lines that aren't JSON and
    JSON values that aren't objects are skipped, as are undecodable bytes
    (replaced, like a text-mode read with ``errors="replace"``).
    """

    def __init__(self, extract: Callable[[dict], Any]) -> None:
        self._extract = extract
        self._files: dict[str, _FileState] = {}
        self._lock = threading.Lock()

    def records(self, path: str) -> list:
        """Every record kept from *path*, in file order; [] if unreadable."""
        with self._lock:
            state = self._update(path)
            if state is None:
                return []
            return state.records + state.tail_records

    def forget_untouched(self) -> None:
        """Forget every file not read since the previous call, so the cache
        only holds files the scans still look at."""
        with self._lock:
            for path in [p for p, s in self._files.items() if not s.touched]:
                del self._files[path]
            for state in self._files.values():
                state.touched = False

    def _update(self, path: str) -> _FileState | None:
        # Always opened: comparing a few bytes costs microseconds, and unlike
        # size and mtime it catches a same-length rewrite within one
        # timestamp tick.
        try:
            with open(path, "rb") as f:
                st = os.fstat(f.fileno())
                state = self._files.get(path)
                if state is None or not _is_append(f, st, state):
                    state = _FileState(ino=st.st_ino)
                    self._files[path] = state
                self._read_from_offset(f, state)
        except OSError:
            self._files.pop(path, None)
            return None
        state.touched = True
        return state

    def _read_from_offset(self, f, state: _FileState) -> None:
        f.seek(state.offset)
        offset = state.offset
        new_records: list = []
        tail_records: list = []
        last = state.records[-1] if state.records else None
        for raw in f:
            if not raw.endswith(b"\n"):
                tail_records = self._decode(raw)
                break
            offset += len(raw)
            for record in self._decode(raw):
                # Claude Code writes a line per content block, each repeating
                # the message's usage: equal neighbours share one object.
                if last is not None and record == last:
                    record = last
                new_records.append(record)
                last = record
        # Commit only once the whole stretch decoded, so an extractor error
        # can't leave records counted twice on the next read.
        state.records.extend(new_records)
        state.tail_records = tail_records
        state.offset = offset
        f.seek(0)
        state.head = f.read(min(_HEAD_BYTES, offset))
        edge_start = max(0, offset - _EDGE_BYTES)
        f.seek(edge_start)
        state.edge = f.read(offset - edge_start)

    def _decode(self, raw: bytes) -> list:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            return []
        try:
            entry = json.loads(line)
        except ValueError:
            return []
        if not isinstance(entry, dict):
            return []
        record = self._extract(entry)
        return [] if record is None else [record]


def _is_append(f, st: os.stat_result, state: _FileState) -> bool:
    """True when the file is the one last read, with bytes only added."""
    if st.st_ino != state.ino or st.st_size < state.offset:
        return False
    f.seek(0)
    if f.read(len(state.head)) != state.head:
        return False
    f.seek(state.offset - len(state.edge))
    return f.read(len(state.edge)) == state.edge
