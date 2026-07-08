import unittest
from datetime import datetime, timedelta, timezone

from claude_usage.peak import (
    PeakStatus,
    is_peak_window,
    peak_status,
    _pacific_utcoffset,
    _nth_sunday,
)


# Convenience: build a naive UTC datetime (collector convention).
def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi)


DEFAULT = dict(
    timezone="America/Los_Angeles",
    start_hour=5,
    end_hour=11,
    weekdays=[0, 1, 2, 3, 4],
)


class TestIsPeakWindow(unittest.TestCase):
    def test_wed_0600_pacific_in_peak(self):
        # 06:00 PDT (July) == 13:00 UTC on Wed 2026-07-08.
        self.assertTrue(is_peak_window(_utc(2026, 7, 8, 13, 0), **DEFAULT))

    def test_0459_before_start_false(self):
        # 04:59 PDT == 11:59 UTC.
        self.assertFalse(is_peak_window(_utc(2026, 7, 8, 11, 59), **DEFAULT))

    def test_1100_end_exclusive_false(self):
        # 11:00 PDT == 18:00 UTC — end_hour is exclusive.
        self.assertFalse(is_peak_window(_utc(2026, 7, 8, 18, 0), **DEFAULT))

    def test_weekend_saturday_false(self):
        # Sat 2026-07-11 08:00 PDT == 15:00 UTC.
        self.assertFalse(is_peak_window(_utc(2026, 7, 11, 15, 0), **DEFAULT))

    def test_weekend_sunday_false(self):
        # Sun 2026-07-12 08:00 PDT == 15:00 UTC.
        self.assertFalse(is_peak_window(_utc(2026, 7, 12, 15, 0), **DEFAULT))


class TestDst(unittest.TestCase):
    def test_january_pst_offset_minus8(self):
        # A January UTC instant equal to 05:30 PST (-08:00) -> 13:30 UTC.
        st = peak_status(_utc(2026, 1, 7, 13, 30), {})  # Wed 2026-01-07
        self.assertTrue(st.in_peak)

    def test_july_pdt_offset_minus7(self):
        # A July UTC instant equal to 05:30 PDT (-07:00) -> 12:30 UTC.
        st = peak_status(_utc(2026, 7, 8, 12, 30), {})  # Wed 2026-07-08
        self.assertTrue(st.in_peak)

    def test_offset_switches_by_date(self):
        # Same wall clock (05:30 local) maps to a *different* UTC instant in
        # winter vs summer, proving the offset is not a fixed -8.
        jan = _utc(2026, 1, 7, 13, 30)  # 05:30 PST
        jul = _utc(2026, 7, 8, 12, 30)  # 05:30 PDT
        self.assertEqual(_pacific_utcoffset(jan.replace(tzinfo=timezone.utc)),
                         timedelta(hours=-8))
        self.assertEqual(_pacific_utcoffset(jul.replace(tzinfo=timezone.utc)),
                         timedelta(hours=-7))

    def test_spring_forward_transition(self):
        # 2nd Sunday of March at 02:00 local == 10:00 UTC.
        day = _nth_sunday(2026, 3, 2)
        spring = datetime(2026, 3, day, 10, 0, tzinfo=timezone.utc)
        before = spring - timedelta(minutes=1)
        after = spring + timedelta(minutes=1)
        self.assertEqual(_pacific_utcoffset(before), timedelta(hours=-8))
        self.assertEqual(_pacific_utcoffset(after), timedelta(hours=-7))

    def test_fall_back_transition(self):
        # 1st Sunday of November at 02:00 PDT == 09:00 UTC.
        day = _nth_sunday(2026, 11, 1)
        fall = datetime(2026, 11, day, 9, 0, tzinfo=timezone.utc)
        before = fall - timedelta(minutes=1)
        after = fall + timedelta(minutes=1)
        self.assertEqual(_pacific_utcoffset(before), timedelta(hours=-7))
        self.assertEqual(_pacific_utcoffset(after), timedelta(hours=-8))


class TestNaiveVsAware(unittest.TestCase):
    def test_identical_status(self):
        naive = datetime(2026, 7, 8, 17, 30)  # 10:30 PDT
        aware = naive.replace(tzinfo=timezone.utc)
        self.assertEqual(peak_status(naive, {}), peak_status(aware, {}))

    def test_aware_nonutc_zone_normalized(self):
        # 17:30 UTC expressed as an aware +02:00 offset (19:30) must match.
        aware = datetime(2026, 7, 8, 19, 30, tzinfo=timezone(timedelta(hours=2)))
        naive = datetime(2026, 7, 8, 17, 30)
        self.assertEqual(peak_status(naive, {}), peak_status(aware, {}))


class TestDisabled(unittest.TestCase):
    def test_disabled_short_circuits(self):
        st = peak_status(_utc(2026, 7, 8, 13, 0),
                         {"peak_awareness_enabled": False})
        self.assertEqual(st, PeakStatus(False, "", 0, None))


class TestDataDriven(unittest.TestCase):
    def test_custom_window_shifts(self):
        cfg = {
            "peak_start_hour": 8,
            "peak_end_hour": 10,
            "peak_weekdays": [2],  # Wednesday only
        }
        # Wed 09:00 PDT == 16:00 UTC -> in peak.
        self.assertTrue(peak_status(_utc(2026, 7, 8, 16, 0), cfg).in_peak)
        # Wed 06:00 PDT == 13:00 UTC -> outside custom window.
        self.assertFalse(peak_status(_utc(2026, 7, 8, 13, 0), cfg).in_peak)

    def test_custom_weekday_excludes_day(self):
        cfg = {"peak_start_hour": 8, "peak_end_hour": 10, "peak_weekdays": [0]}
        # Wed (weekday 2) not in [Mon] -> not in peak even at 09:00.
        self.assertFalse(peak_status(_utc(2026, 7, 8, 16, 0), cfg).in_peak)


class TestBadTimezone(unittest.TestCase):
    def test_bogus_timezone_no_raise(self):
        cfg = {"peak_timezone": "Not/AZone"}
        st = peak_status(_utc(2026, 7, 8, 13, 0), cfg)
        self.assertEqual(st, PeakStatus(False, "", 0, None))


class TestMinutesUntilChange(unittest.TestCase):
    def test_just_before_end(self):
        # 10:30 PDT == 17:30 UTC, in peak, 30 min until 11:00 end.
        st = peak_status(_utc(2026, 7, 8, 17, 30), {})
        self.assertTrue(st.in_peak)
        self.assertEqual(st.minutes_until_change, 30)
        self.assertIsNotNone(st.next_change_local)
        self.assertEqual(st.next_change_local.hour, 11)

    def test_just_before_start(self):
        # 04:30 PDT == 11:30 UTC, outside peak, 30 min until 05:00 start.
        st = peak_status(_utc(2026, 7, 8, 11, 30), {})
        self.assertFalse(st.in_peak)
        self.assertEqual(st.minutes_until_change, 30)
        self.assertIsNotNone(st.next_change_local)
        self.assertEqual(st.next_change_local.hour, 5)


class TestHint(unittest.TestCase):
    def test_hint_contains_hour_and_token(self):
        st = peak_status(_utc(2026, 7, 8, 13, 0), {})  # 06:00 PDT, in peak
        self.assertTrue(st.in_peak)
        self.assertIn("11 AM", st.hint)
        self.assertIn("PT", st.hint)

    def test_hint_empty_when_outside(self):
        st = peak_status(_utc(2026, 7, 8, 11, 30), {})  # 04:30 PDT
        self.assertFalse(st.in_peak)
        self.assertEqual(st.hint, "")


if __name__ == "__main__":
    unittest.main()
