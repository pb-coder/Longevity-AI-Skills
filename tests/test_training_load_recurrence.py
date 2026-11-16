"""Training-load summaries preserve daily decay and short-history semantics."""
from datetime import date, timedelta
import unittest

from workout_coach.lib.cardio import training_load_summary


class TrainingLoadRecurrenceTests(unittest.TestCase):
    def test_single_load_matches_closed_form_at_week_boundary_and_long_gaps(self):
        start = date(2026, 1, 1)
        for elapsed in (0, 1, 6, 7, 8, 42, 365):
            with self.subTest(elapsed=elapsed):
                today = start + timedelta(days=elapsed)
                ctl = 100 / 42 * (41 / 42) ** elapsed
                atl = 100 / 7 * (6 / 7) ** elapsed
                earlier_ctl = (100 / 42 * (41 / 42) ** (elapsed - 7)
                               if elapsed >= 7 else ctl)
                self.assertEqual(training_load_summary(
                    [{"date": start.isoformat(), "trimp": 100}], today), {
                    "ctl": round(ctl, 1), "atl": round(atl, 1),
                    "tsb": round(ctl - atl, 1),
                    "trend_7d": round(ctl - earlier_ctl, 1),
                })

    def test_same_day_loads_sum_and_future_loads_do_not_contribute(self):
        today = date(2026, 1, 8)
        expected = training_load_summary([{"date": "2026-01-01", "trimp": 100}], today)
        self.assertEqual(training_load_summary([
            {"date": "2026-01-01", "trimp": 40},
            {"date": "2026-01-01", "trimp": 60},
            {"date": "2026-01-09", "trimp": 200},
            {"date": "invalid", "trimp": 200},
        ], today), expected)

    def test_no_usable_history_stays_unknown(self):
        for rows in ([], [{"date": "invalid", "trimp": 100}]):
            self.assertEqual(training_load_summary(rows, date(2026, 1, 8)),
                             dict.fromkeys(("ctl", "atl", "tsb", "trend_7d")))
