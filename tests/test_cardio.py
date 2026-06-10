from __future__ import annotations

import unittest
from datetime import date

from workout_coach.lib.cardio import cardio_hr_zones, training_load_summary, trimp_per_session


class CardioTests(unittest.TestCase):
    def test_z2_minutes_are_split_by_activity_type(self) -> None:
        sessions = [
            {
                "date": "2026-05-12",
                "session_kind": "cardio",
                "exercise_first": "Swimming",
                "avg_hr": 151,
                "duration_min": 4.7,
            },
            {
                "date": "2026-05-13",
                "session_kind": "cardio",
                "exercise_first": "Outdoor Run",
                "avg_hr": 151,
                "duration_min": 35.0,
            },
        ]

        zones = cardio_hr_zones(
            sessions,
            date(2026, 5, 14),
            max_hr=200,
            rest_hr=60,
        )

        self.assertEqual(zones["z2"], 39.7)
        self.assertEqual(zones["z2_by_activity"], {
            "run": 35.0,
            "swim": 4.7,
        })

    def test_trimp_and_training_load_ewma_golden_case(self) -> None:
        sessions = [{
            "date": "2026-05-01",
            "session_kind": "cardio",
            "avg_hr": 150,
            "duration_min": 30,
        }]

        trimps = trimp_per_session(sessions, max_hr=190, rest_hr=60, sex="male")
        load = training_load_summary(trimps, date(2026, 5, 7))

        self.assertEqual(trimps[0]["trimp"], 50.2)
        self.assertEqual(load, {"ctl": 1.0, "atl": 2.8, "tsb": -1.8, "trend_7d": 0.0})


if __name__ == "__main__":
    unittest.main()
