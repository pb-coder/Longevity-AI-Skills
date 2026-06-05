from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from workout_coach.lib.extract import load_exercises_db
from workout_coach.lib.strength import (
    estimated_1rm,
    stale_exercises,
    weekly_volume_per_muscle,
)

# Real catalog so db.get(name.lower()) resolves to canonical entries.
_DB_PATH = Path(__file__).resolve().parents[1] / "shared" / "exercises-database.md"
_DB = load_exercises_db(_DB_PATH)


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


class WeeklyVolumeTests(unittest.TestCase):
    def test_current_is_per_week_not_raw_28d_sum(self) -> None:
        # "Leg Extension" is canonical (primary=quads, no synergists), so
        # each working set contributes exactly 1.0 set to quads. Spread 8
        # working sets across the 28-day window. The raw 28-day count is 8;
        # the weekly-normalized value must be 8 / (28/7) = 8 / 4.0 = 2.0.
        today_d = date(2026, 6, 5)
        dates = [
            "2026-05-12", "2026-05-12",   # week 1
            "2026-05-19", "2026-05-19",   # week 2
            "2026-05-26", "2026-05-26",   # week 3
            "2026-06-02", "2026-06-02",   # week 4
        ]
        rows = [
            {"date": d, "exercise": "Leg Extension",
             "kg": 60, "reps": 10, "notes": ""}
            for d in dates
        ]

        unknown: set[str] = set()
        result = weekly_volume_per_muscle(rows, _DB, today_d, 28, unknown)

        raw_28d_sum = len(dates)  # 8 working sets, each 1.0 into quads
        self.assertEqual(raw_28d_sum, 8)
        # Apples-to-apples with weekly landmarks: per-week, not the raw sum.
        self.assertEqual(result["current"]["quads"], 2.0)
        self.assertNotEqual(result["current"]["quads"], float(raw_28d_sum))
        self.assertEqual(result["window_days"], 28)
        self.assertEqual(unknown, set())


class StaleExerciseTests(unittest.TestCase):
    def test_off_catalog_exercise_excluded_known_stale_kept(self) -> None:
        # "Band Pull-Apart" is no longer in the catalog (post [Band] removal),
        # so it must NOT surface as stale even though it is old. "Leg
        # Extension" is canonical and old → it must still surface.
        today_d = date(2026, 6, 5)
        rows = [
            {"date": "2026-01-01", "exercise": "Band Pull-Apart",
             "kg": 0, "reps": 15, "notes": ""},
            {"date": "2026-01-01", "exercise": "Leg Extension",
             "kg": 60, "reps": 12, "notes": ""},
        ]

        out = stale_exercises(rows, _DB, today_d, threshold_days=28)
        names = {e["exercise"] for e in out}

        self.assertNotIn("Band Pull-Apart", names)
        self.assertIn("Leg Extension", names)


if __name__ == "__main__":
    unittest.main()
