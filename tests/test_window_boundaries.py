from __future__ import annotations

import unittest
from datetime import date

from workout_coach.lib.cardio import cardio_last_28d
from workout_coach.lib.light_therapy import recent_light_therapy_sessions
from workout_coach.lib.sleep import recent_sleep_nights
from workout_coach.lib.swim import recent_swim_workouts
from workout_coach.lib.thermal import recent_thermal_sessions


class WindowBoundaryTests(unittest.TestCase):
    def test_recent_helpers_use_exact_n_calendar_days(self) -> None:
        today = date(2026, 5, 28)
        rows = [
            {"date": "2026-04-30", "duration_min": 10, "distance_km": 1},
            {"date": "2026-05-01", "duration_min": 20, "distance_km": 2},
            {"date": "2026-05-28", "duration_min": 30, "distance_km": 3},
        ]

        self.assertEqual([r["date"] for r in recent_sleep_nights(rows, today, 28)], ["2026-05-01", "2026-05-28"])
        self.assertEqual([r["date"] for r in recent_thermal_sessions(rows, today, 28)], ["2026-05-01", "2026-05-28"])
        self.assertEqual([r["date"] for r in recent_swim_workouts(rows, today, 28)], ["2026-05-01", "2026-05-28"])
        self.assertEqual([r["date"] for r in recent_light_therapy_sessions(rows, today, 28)], ["2026-05-01", "2026-05-28"])

    def test_cardio_last_28d_excludes_day_29(self) -> None:
        today = date(2026, 5, 28)
        rows = [
            {"date": "2026-04-30", "exercise": "Outdoor Run", "duration_min": 10, "distance_km": 1},
            {"date": "2026-05-01", "exercise": "Outdoor Run", "duration_min": 20, "distance_km": 2},
            {"date": "2026-05-28", "exercise": "Outdoor Run", "duration_min": 30, "distance_km": 3},
        ]

        summary = cardio_last_28d(rows, today)

        self.assertEqual(summary["sessions"], 2)
        self.assertEqual(summary["total_minutes"], 50)
        self.assertEqual(summary["total_distance_km"], 5)


if __name__ == "__main__":
    unittest.main()
