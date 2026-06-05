from __future__ import annotations

import unittest

from workout_coach.lib.strength import estimated_1rm


def row(date: str, kg: float, reps: int = 6) -> dict:
    return {
        "date": date,
        "exercise": "Dumbbell Flat Bench Press",
        "kg": kg,
        "reps": reps,
        "notes": "",
    }


class StrengthTests(unittest.TestCase):
    def test_e1rm_slope_excludes_recent_deload_session(self) -> None:
        rows = [
            row("2026-05-01", 100),
            row("2026-05-08", 102.5),
            row("2026-05-15", 105),
            row("2026-05-22", 80),
        ]

        result = estimated_1rm(rows, deload_dates=["2026-05-22"])
        bench = result["Dumbbell Flat Bench Press"]

        self.assertEqual(bench["deload_excluded"], 1)
        self.assertEqual(bench["slope_kg_per_4w"], 12.0)
        self.assertEqual(bench["confidence"], "medium")


if __name__ == "__main__":
    unittest.main()
