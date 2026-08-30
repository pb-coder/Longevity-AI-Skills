"""Clock, calendar and range primitives for Health Export Kit.

The export renders every workout and sleep timestamp as MM-dd HH:mm:ss with
no year, and every timestamp dated before a daylight-saving transition comes
out exactly one hour early (spec 5.1). Both defects are silent: a shifted
workout still looks like a workout, and a January date parsed as the wrong
year still sorts. The tests below pin the corrected values against real
observed pairs so a regression cannot pass unnoticed.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from shared import hek_time


def _meta(range_start="2025-12-31T23:00:00Z",
          range_end="2026-08-30T07:22:53Z",
          exported_at="2026-08-30T07:25:07Z",
          tz="Europe/Paris") -> dict:
    return {
        "rangeStart": range_start,
        "rangeEnd": range_end,
        "exportedAt": exported_at,
        "timeZone": tz,
    }


class ExportOffsetTests(unittest.TestCase):

    def test_offset_is_read_from_the_export_instant_not_the_range(self) -> None:
        # Exported 2026-08-30, inside CEST, so +02:00.
        self.assertEqual(hek_time.export_offset(_meta()), timedelta(hours=2))

    def test_winter_export_reads_plus_one(self) -> None:
        m = _meta(exported_at="2026-01-15T09:00:00Z")
        self.assertEqual(hek_time.export_offset(m), timedelta(hours=1))


class ClockCorrectionTests(unittest.TestCase):
    """Real observed pairs from the primary tracker's 2026-01-01 backfill."""

    def test_pre_transition_stamp_gains_an_hour(self) -> None:
        # Export said 12:38:19; the tracker's stored row says 13:38:19.
        got = hek_time.parse_stamp("03-28 12:38:19", _meta())
        self.assertEqual(got, datetime(2026, 3, 28, 13, 38, 19))

    def test_post_transition_stamp_is_unchanged(self) -> None:
        # Export said 15:19:20; stored row says 15:19:20.
        got = hek_time.parse_stamp("08-02 15:19:20", _meta())
        self.assertEqual(got, datetime(2026, 8, 2, 15, 19, 20))

    def test_the_transition_day_itself_is_unchanged(self) -> None:
        # 2026-03-29 is the CET->CEST switch; stored and export agree.
        got = hek_time.parse_stamp("03-29 13:06:05", _meta())
        self.assertEqual(got, datetime(2026, 3, 29, 13, 6, 5))

    def test_guard_rejects_a_non_whole_hour_correction(self) -> None:
        # A zone with a 30-minute DST step would produce a fractional
        # correction. We would rather fail loudly than shift real data.
        m = _meta(tz="Australia/Lord_Howe")
        with self.assertRaises(hek_time.ClockGuardError):
            hek_time.parse_stamp("01-15 10:00:00", m)

    def test_guard_rejects_a_correction_larger_than_two_hours(self) -> None:
        with self.assertRaises(hek_time.ClockGuardError):
            hek_time._check_correction(timedelta(hours=3))


class YearReconstructionTests(unittest.TestCase):

    def test_year_comes_from_the_range_not_from_today(self) -> None:
        m = _meta(range_start="2024-12-31T23:00:00Z",
                  range_end="2025-03-01T23:00:00Z",
                  exported_at="2025-03-01T23:05:00Z")
        self.assertEqual(hek_time.resolve_year("01-15", m), 2025)

    def test_a_range_crossing_new_year_picks_the_right_side(self) -> None:
        m = _meta(range_start="2026-12-01T23:00:00Z",
                  range_end="2027-01-15T23:00:00Z",
                  exported_at="2027-01-15T23:05:00Z")
        self.assertEqual(hek_time.resolve_year("12-15", m), 2026)
        self.assertEqual(hek_time.resolve_year("01-05", m), 2027)

    def test_a_range_longer_than_a_year_is_refused(self) -> None:
        m = _meta(range_start="2024-01-01T00:00:00Z",
                  range_end="2026-01-01T00:00:00Z",
                  exported_at="2026-01-01T00:05:00Z")
        with self.assertRaises(hek_time.ClockGuardError):
            hek_time.resolve_year("06-15", m)

    def test_a_day_that_fits_two_years_inside_a_legal_range_is_refused(self) -> None:
        # 2025-12-31 00:00 -> 2026-12-30 00:00 local is 364 days, under
        # MAX_RANGE_DAYS, so the length guard does not fire first. "12-31"
        # still lands inside the range on both sides once RANGE_SLACK is
        # added, and two candidates is a refusal, never a coin flip.
        m = _meta(range_start="2025-12-30T23:00:00Z",
                  range_end="2026-12-29T23:00:00Z",
                  exported_at="2026-12-29T23:05:00Z")
        with self.assertRaisesRegex(hek_time.ClockGuardError, "2 candidates"):
            hek_time.resolve_year("12-31", m)

    def test_a_day_outside_a_short_range_is_refused(self) -> None:
        # No candidate year puts 07-15 inside a January range. Refusing beats
        # inventing a year the export never covered.
        m = _meta(range_start="2026-01-01T00:00:00Z",
                  range_end="2026-02-01T00:00:00Z",
                  exported_at="2026-02-01T00:05:00Z")
        with self.assertRaisesRegex(hek_time.ClockGuardError, "0 candidates"):
            hek_time.resolve_year("07-15", m)

    def test_a_sleep_session_starting_a_day_before_the_range_still_resolves(self) -> None:
        # Sessions overlapping the range are included in full, so a start
        # stamp can fall just outside it.
        m = _meta(range_start="2026-08-01T00:00:00Z",
                  range_end="2026-08-30T00:00:00Z",
                  exported_at="2026-08-30T00:05:00Z")
        self.assertEqual(hek_time.resolve_year("07-31", m), 2026)


class CompleteDayTests(unittest.TestCase):

    def test_partial_first_and_last_days_are_excluded(self) -> None:
        # Range runs 2026-07-31 08:45 local to 2026-08-30 08:45 local.
        m = _meta(range_start="2026-07-31T06:45:00Z",
                  range_end="2026-08-30T06:45:00Z",
                  exported_at="2026-08-30T06:46:00Z")
        first, last = hek_time.complete_days(m)
        self.assertEqual(first, date(2026, 8, 1))
        self.assertEqual(last, date(2026, 8, 29))

    def test_a_midnight_aligned_range_keeps_its_first_day(self) -> None:
        # 2025-12-31T23:00Z is 2026-01-01 00:00 in that zone.
        m = _meta(range_start="2025-12-31T23:00:00Z",
                  range_end="2026-08-30T07:22:53Z",
                  exported_at="2026-08-30T07:25:07Z")
        first, last = hek_time.complete_days(m)
        self.assertEqual(first, date(2026, 1, 1))
        self.assertEqual(last, date(2026, 8, 29))


if __name__ == "__main__":
    unittest.main()
