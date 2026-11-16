"""Weekly summaries remain usable when only body measurements are logged."""
from datetime import date
import unittest

from workout_coach.lib.health_windowing import health_metrics_weekly


class SparseWeeklyHealthTests(unittest.TestCase):
    def test_bodyweight_only_week_retains_anchor_without_inventing_vitals(self):
        weeks = health_metrics_weekly(
            [{"date": "2026-05-17", "bodyweight_kg": 70}], date(2026, 5, 17))
        self.assertEqual(len(weeks), 1)
        self.assertEqual(weeks[0]["week_start"], "2026-05-11")
        self.assertEqual(weeks[0]["n_days"], 0)
        self.assertIsNone(weeks[0]["resting_hr"])

    def test_measurement_only_week_does_not_hide_populated_week(self):
        weeks = health_metrics_weekly([
            {"date": "2026-05-10", "waist_cm": 80},
            {"date": "2026-05-17", "resting_hr": 60},
        ], date(2026, 5, 17))
        self.assertEqual([week["n_days"] for week in weeks], [0, 1])
        self.assertEqual(weeks[1]["resting_hr"], 60)


if __name__ == "__main__":
    unittest.main()
