"""The date hot path preserves the previous accepted-input contract."""
from datetime import date, datetime
import unittest

from workout_coach.lib.parsing import _parse_iso_date


class IsoDateCompatibilityTests(unittest.TestCase):
    def test_fast_path_matches_general_parser(self):
        inputs = [
            "2026-05-17", "2024-02-29", "2026-02-29", "0001-01-01",
            "9999-12-31", "2026-5-7", "2026-05-7", "2026-5-17",
            "20260517", "2026-W20-7", "2026-05-17T00:00:00",
            "2026-13-01", "2026-00-10", "2026-01-00", "not a date",
            "２０２６-05-17", " 2026-05-17", "2026-05-17 ", "", None,
            20260517, date(2026, 5, 17), ["2026-05-17"],
        ]
        for value in inputs:
            with self.subTest(value=value):
                try:
                    expected = datetime.strptime(value, "%Y-%m-%d").date()
                except (TypeError, ValueError):
                    expected = None
                self.assertEqual(_parse_iso_date(value), expected)
