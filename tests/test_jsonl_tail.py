"""Incremental reads of append-only JSONL files (issue #39).

Every refresh used to decode every line of every recent transcript, several
times over: ~230k json.loads and a full core for 1-2 s each minute on a
heavy user's ~/.claude. JsonlTail remembers how far it read each file and
decodes only what was appended since, while returning exactly what a full
read would.
"""
from __future__ import annotations

import json
import os

import pytest

from claude_usage.jsonl_tail import JsonlTail


class CountingExtract:
    """Keeps each entry's "n", skips entries without one, counts calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, entry: dict):
        self.calls += 1
        return entry.get("n")


def _line(n) -> str:
    return json.dumps({"n": n}) + "\n"


@pytest.fixture
def tail():
    extract = CountingExtract()
    return JsonlTail(extract), extract


def test_reads_every_record_once(tmp_path, tail):
    t, extract = tail
    path = tmp_path / "a.jsonl"
    path.write_text(_line(1) + _line(2) + "\n" + json.dumps({"x": 0}) + "\n" + _line(3))
    assert t.records(str(path)) == [1, 2, 3]
    assert extract.calls == 4  # blank line skipped, {"x": 0} extracted to None


def test_unchanged_file_is_not_decoded_again(tmp_path, tail):
    t, extract = tail
    path = tmp_path / "a.jsonl"
    path.write_text(_line(1) + _line(2))
    t.records(str(path))
    calls = extract.calls
    assert t.records(str(path)) == [1, 2]
    assert extract.calls == calls


def test_only_appended_lines_are_decoded(tmp_path, tail):
    t, extract = tail
    path = tmp_path / "a.jsonl"
    path.write_text(_line(1) + _line(2))
    t.records(str(path))
    with open(path, "a") as f:
        f.write(_line(3) + _line(4))
    calls = extract.calls
    assert t.records(str(path)) == [1, 2, 3, 4]
    assert extract.calls == calls + 2


def test_line_being_written_counts_once_it_is_complete(tmp_path, tail):
    t, _ = tail
    path = tmp_path / "a.jsonl"
    full = _line(2)
    path.write_text(_line(1) + full[:5])  # a writer is mid-line
    assert t.records(str(path)) == [1]
    with open(path, "a") as f:
        f.write(full[5:])
    assert t.records(str(path)) == [1, 2]
    assert t.records(str(path)) == [1, 2]


def test_complete_last_line_without_newline_is_read(tmp_path, tail):
    # A full read has always parsed it; it must neither be lost nor doubled
    # once the newline (and more lines) arrive.
    t, _ = tail
    path = tmp_path / "a.jsonl"
    path.write_text(_line(1) + json.dumps({"n": 2}))
    assert t.records(str(path)) == [1, 2]
    with open(path, "a") as f:
        f.write("\n" + _line(3))
    assert t.records(str(path)) == [1, 2, 3]


def test_replaced_file_is_read_from_scratch(tmp_path, tail):
    t, _ = tail
    path = tmp_path / "a.jsonl"
    path.write_text(_line(1) + _line(2))
    t.records(str(path))
    new = tmp_path / "new.jsonl"
    new.write_text(_line(7) + _line(8) + _line(9))
    os.replace(new, path)  # an atomic rewrite
    assert t.records(str(path)) == [7, 8, 9]


def test_file_rewritten_in_place_is_read_from_scratch(tmp_path, tail):
    t, _ = tail
    path = tmp_path / "a.jsonl"
    path.write_text(_line(1) + _line(2))
    t.records(str(path))
    path.write_text(_line(5) + _line(6) + _line(7))  # same inode, longer
    assert t.records(str(path)) == [5, 6, 7]


def test_truncated_file_is_read_from_scratch(tmp_path, tail):
    t, _ = tail
    path = tmp_path / "a.jsonl"
    path.write_text(_line(1) + _line(2) + _line(3))
    t.records(str(path))
    path.write_text(_line(9))
    assert t.records(str(path)) == [9]


def test_malformed_lines_and_bad_bytes_are_skipped(tmp_path, tail):
    t, _ = tail
    path = tmp_path / "a.jsonl"
    path.write_bytes(_line(1).encode() + b"{not json\n" + b'{"n": "\xff"}\n' + _line(3).encode())
    assert t.records(str(path)) == [1, "�", 3]


def test_missing_file_has_no_records(tmp_path, tail):
    t, _ = tail
    path = tmp_path / "a.jsonl"
    path.write_text(_line(1))
    t.records(str(path))
    path.unlink()
    assert t.records(str(path)) == []


def test_files_not_read_since_the_last_sweep_are_forgotten(tmp_path, tail):
    t, extract = tail
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text(_line(1))
    b.write_text(_line(2))
    t.records(str(a))
    t.records(str(b))
    t.forget_untouched()   # both were read: both kept
    t.records(str(a))
    t.forget_untouched()   # b wasn't: forgotten
    calls = extract.calls
    assert t.records(str(a)) == [1]
    assert extract.calls == calls       # still cached
    assert t.records(str(b)) == [2]
    assert extract.calls == calls + 1   # decoded again


def test_same_length_rewrite_is_noticed(tmp_path, tail):
    # Size and mtime can both match within one timestamp tick.
    t, _ = tail
    path = tmp_path / "a.jsonl"
    path.write_text(_line(1) + _line(2))
    t.records(str(path))
    path.write_text(_line(3) + _line(4))
    assert t.records(str(path)) == [3, 4]


def test_returned_list_is_a_copy(tmp_path, tail):
    t, _ = tail
    path = tmp_path / "a.jsonl"
    path.write_text(_line(1))
    t.records(str(path)).append(99)
    assert t.records(str(path)) == [1]


def test_consecutive_equal_records_share_one_object(tmp_path):
    # Claude Code writes one line per content block, each repeating the
    # message's usage: their records are equal and needn't each take memory.
    t = JsonlTail(lambda entry: (entry["id"], entry["n"]))
    path = tmp_path / "a.jsonl"
    lines = [{"id": "m1", "n": 5}, {"id": "m1", "n": 5}, {"id": "m2", "n": 5}, {"id": "m2", "n": 5}]
    path.write_text("".join(json.dumps(e) + "\n" for e in lines))
    records = t.records(str(path))
    assert records == [("m1", 5), ("m1", 5), ("m2", 5), ("m2", 5)]
    assert records[0] is records[1]
    assert records[2] is records[3]
    assert records[1] is not records[2]
