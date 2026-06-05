from __future__ import annotations

import unittest
from datetime import date

from workout_coach.lib.cardio import cardio_hr_zones


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


if __name__ == "__main__":
    unittest.main()
