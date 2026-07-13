"""Codex provider rows in the self-drawn OSD skins.

Follow-up to the merchant-OSD Codex rows (PR #18): the six paint-your-own
skins consume :class:`SkinData` rather than the overlay's ``UsageStats``, so
they needed their own Codex 5h / 7d rows. These tests lock three things:

1. the adapter converts the Codex epoch resets to the same minutes /
   hours+minutes shape the rows render;
2. every skin renders with the Codex provider active without raising, at the
   taller ``osd_height_*codex`` footprint; and
3. the rows are strictly gated on ``codex_available`` — a panel with the flag
   off is byte-for-byte identical whether or not Codex values are populated
   (the opt-in / byte-identical-by-default contract).
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QImage, QPainter, QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from claude_usage.skins import SKIN_MODULES  # noqa: E402
from claude_usage.skins._adapter import SkinData, from_usage_stats  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _skin_data(*, codex: bool, codex_vals: bool = True, scoped: bool = False) -> SkinData:
    return SkinData(
        session_pct=0.42, session_reset_min=137,
        weekly_pct=0.68, weekly_reset_hrs=52, weekly_reset_min=30,
        scoped_pct=0.55 if scoped else None,
        scoped_label="Fable" if scoped else "",
        scoped_reset_hrs=40, scoped_reset_min=0,
        codex_available=codex,
        # When codex_vals is True these carry real numbers even with the flag
        # off — the gate must ignore them entirely.
        codex_session_pct=0.31 if codex_vals else 0.0,
        codex_session_reset_min=245 if codex_vals else 0,
        codex_weekly_pct=0.77 if codex_vals else 0.0,
        codex_weekly_reset_hrs=88 if codex_vals else 0,
        codex_weekly_reset_min=15 if codex_vals else 0,
    )


def _render(mod, data: SkinData, *, scoped: bool) -> bytes:
    m = mod.METRICS
    key = "osd_height_scoped_codex" if scoped else "osd_height_codex"
    if not data.codex_available:
        key = "osd_height_scoped" if scoped else "osd_height"
    w = int(m["osd_width"])
    h = int(m.get(key, m["osd_height"]))
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#101014"))
    p = QPainter(img)
    try:
        mod.paint_osd(p, QRectF(0, 0, w, h), data, 1.0)
    finally:
        p.end()
    return bytes(img.constBits())


class TestCodexAdapter:
    def test_reset_timestamps_convert_to_minutes_and_hours(self) -> None:
        now = 1_000_000
        stats = SimpleNamespace(
            codex_available=True,
            codex_session_utilization=0.31,
            codex_session_reset=now + 245 * 60,          # 245m out
            codex_weekly_utilization=0.77,
            codex_weekly_reset=now + 88 * 3600 + 15 * 60,  # 88h 15m out
        )
        d = from_usage_stats(stats, now=now)
        assert d.codex_available is True
        assert d.codex_session_pct == 0.31
        assert d.codex_session_reset_min == 245
        assert d.codex_weekly_reset_hrs == 88
        assert d.codex_weekly_reset_min == 15

    def test_absent_provider_leaves_codex_fields_zeroed(self) -> None:
        d = from_usage_stats(SimpleNamespace(), now=1_000_000)
        assert d.codex_available is False
        assert d.codex_session_pct == 0.0
        assert d.codex_session_reset_min == 0
        assert d.codex_weekly_reset_hrs == 0

    def test_utilization_is_clamped(self) -> None:
        stats = SimpleNamespace(
            codex_available=True,
            codex_session_utilization=1.9,
            codex_weekly_utilization=-0.2,
        )
        d = from_usage_stats(stats, now=0)
        assert d.codex_session_pct == 1.0
        assert d.codex_weekly_pct == 0.0


class TestSkinCodexRows:
    def test_every_skin_declares_codex_height_metrics(self) -> None:
        for name, mod in SKIN_MODULES.items():
            m = mod.METRICS
            assert "osd_height_codex" in m, name
            assert "osd_height_scoped_codex" in m, name
            assert m["osd_height_codex"] >= m["osd_height"], name
            assert m["osd_height_scoped_codex"] >= m["osd_height_scoped"], name

    def test_every_skin_renders_with_codex_active(self) -> None:
        for name, mod in SKIN_MODULES.items():
            for scoped in (False, True):
                data = _skin_data(codex=True, scoped=scoped)
                # Must not raise for any skin × (codex-only, scoped+codex).
                assert _render(mod, data, scoped=scoped), name

    def test_absent_codex_is_byte_identical(self) -> None:
        # The opt-in contract: with codex_available False, a panel carrying
        # populated Codex numbers must render identically to one carrying the
        # zeroed defaults — i.e. the flag fully gates the extra rows.
        for name, mod in SKIN_MODULES.items():
            with_vals = _render(mod, _skin_data(codex=False, codex_vals=True), scoped=False)
            without_vals = _render(mod, _skin_data(codex=False, codex_vals=False), scoped=False)
            assert with_vals == without_vals, name
