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

    def test_median_separates_one_big_week_from_a_steady_habit(self) -> None:
        # The observed failure: back read 8.2 sets/wk on a 21 / 4 / 4 / 4
        # series. The mean says "comfortably above MEV"; the typical week
        # is 4. Both shapes below share a mean and differ in median, which
        # is exactly the discrimination `current` alone cannot make.
        today_d = date(2026, 6, 5)

        def volume(dates: list[str]) -> dict:
            unknown: set[str] = set()
            return weekly_volume_per_muscle(
                [{"date": d, "exercise": "Leg Extension",
                  "kg": 60, "reps": 10, "notes": ""} for d in dates],
                _DB, today_d, 28, unknown,
            )

        spiky = volume(["2026-06-02"] * 12 + ["2026-05-26", "2026-05-19",
                                              "2026-05-12"])
        steady = volume(["2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
                         "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29",
                         "2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22",
                         "2026-05-12", "2026-05-13", "2026-05-14"])

        self.assertEqual(spiky["current"]["quads"], 3.8)
        self.assertEqual(steady["current"]["quads"], 3.8)
        self.assertEqual(spiky["per_week"]["quads"], [1.0, 1.0, 1.0, 12.0])
        self.assertEqual(steady["per_week"]["quads"], [3.0, 4.0, 4.0, 4.0])
        self.assertEqual(spiky["median"]["quads"], 1.0)
        self.assertEqual(steady["median"]["quads"], 4.0)

    def test_current_and_landmarks_keep_their_prior_shape(self) -> None:
        # Backward compatibility: render_components_volume.muscle_bars and
        # health_session_rec._muscles_over_mrv both read `current` and
        # `landmarks` and must not see a changed contract.
        today_d = date(2026, 6, 5)
        unknown: set[str] = set()
        result = weekly_volume_per_muscle(
            [{"date": "2026-06-02", "exercise": "Leg Extension",
              "kg": 60, "reps": 10, "notes": ""}],
            _DB, today_d, 28, unknown,
        )
        self.assertIsInstance(result["current"]["quads"], float)
        self.assertIn("mev", result["landmarks"]["quads"])
        self.assertEqual(set(result["per_week"]), set(result["current"]))
        self.assertEqual(set(result["median"]), set(result["current"]))


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

    def test_newest_stale_leads_so_the_slice_is_a_comeback_pool(self) -> None:
        """``read_tracker`` keeps the head of this list. Sorted oldest-first
        that head is the retirement pile — measured over four run dates six
        weeks apart it was byte-identical every time."""
        today_d = date(2026, 8, 2)
        rows = [
            {"date": "2026-02-13", "exercise": "Leg Extension",
             "kg": 60, "reps": 12, "notes": ""},
            {"date": "2026-06-19", "exercise": "Chest Press Machine",
             "kg": 60, "reps": 10, "notes": ""},
        ]
        out = stale_exercises(rows, _DB, today_d, threshold_days=28)
        self.assertEqual([e["exercise"] for e in out],
                         ["Chest Press Machine", "Leg Extension"])

    def test_ties_break_on_more_sessions_then_name(self) -> None:
        # A total order keeps a run reproducible; two movements last seen
        # on the same day must not swap places between runs.
        today_d = date(2026, 8, 2)
        rows = [
            {"date": "2026-06-01", "exercise": "Leg Extension",
             "kg": 60, "reps": 12, "notes": ""},
            {"date": "2026-05-20", "exercise": "Pec Deck",
             "kg": 40, "reps": 12, "notes": ""},
            {"date": "2026-06-01", "exercise": "Pec Deck",
             "kg": 40, "reps": 12, "notes": ""},
        ]
        out = stale_exercises(rows, _DB, today_d, threshold_days=28)
        self.assertEqual([e["exercise"] for e in out],
                         ["Pec Deck", "Leg Extension"])


class DeadliftFamilyAndCarryTests(unittest.TestCase):
    def test_conventional_deadlift_dedupes_primary_from_synergists(self) -> None:
        # Conventional Deadlift lists BOTH "(primary: posterior chain)"
        # (→ glutes) AND "+glutes" in its synergist list. The parser must
        # dedupe the primary out of synergists so a single working set
        # credits glutes exactly 1.0 (not 1.0 + 0.5 = 1.5).
        entry = _DB["conventional deadlift"]
        self.assertEqual(entry["primary"], "glutes")
        self.assertNotIn("glutes", entry["synergists"])

        today_d = date(2026, 6, 5)
        rows = [
            {"date": "2026-06-01", "exercise": "Conventional Deadlift",
             "kg": 120, "reps": 5, "notes": ""},
        ]
        unknown: set[str] = set()
        result = weekly_volume_per_muscle(rows, _DB, today_d, 7, unknown)
        self.assertEqual(result["current"]["glutes"], 1.0)

    def test_deadlift_family_primaries_are_consistent(self) -> None:
        # Sumo, Trap Bar, and Machine variants must all resolve to the same
        # primary as Conventional Deadlift (glutes via the posterior-chain
        # override), not fall back to the BACK section heading.
        for name in ("sumo deadlift", "trap bar deadlift", "deadlift machine"):
            with self.subTest(name=name):
                self.assertEqual(_DB[name]["primary"], "glutes")

    def test_superman_primary_is_erectors(self) -> None:
        # Superman is an erector-chain exercise, not a lats/mid-back (BACK
        # section) movement.
        self.assertEqual(_DB["superman"]["primary"], "erectors")

    def test_dumbbell_farmer_walk_credits_carry_muscles(self) -> None:
        # Loaded carries were muscle-invisible (no synergists) despite
        # counting as working sets; they must now credit the muscles that
        # actually do the work.
        entry = _DB["dumbbell farmer walk"]
        self.assertIn("traps", entry["synergists"])
        self.assertIn("forearms", entry["synergists"])
        # NOT core. The two-handed carry is symmetrically loaded, so it
        # trains no anti-lateral-flexion, and SKILL.md budgets it as a
        # finisher outside the core allocation precisely so closing a
        # session on it cannot earn core credit it did not do the work for.
        self.assertNotIn("core", entry["synergists"])


class NeglectedMuscleTests(unittest.TestCase):
    def test_neglected_muscles_lists_zero_credit_trainable_muscles(self) -> None:
        # Only "Leg Extension" (primary=quads, no synergists) is logged, so
        # every other trainable landmark muscle gets zero credited sets in
        # the window and must surface in neglected_muscles, sorted. "abs"
        # has mev > 0 but no catalog entry can ever produce it (only "core"
        # is used), so it must never appear even though it's a landmark key.
        today_d = date(2026, 6, 5)
        rows = [
            {"date": "2026-06-01", "exercise": "Leg Extension",
             "kg": 60, "reps": 10, "notes": ""},
        ]
        unknown: set[str] = set()
        result = weekly_volume_per_muscle(rows, _DB, today_d, 28, unknown)

        neglected = result["neglected_muscles"]
        self.assertEqual(neglected, sorted(neglected))
        self.assertIn("glutes", neglected)
        self.assertNotIn("quads", neglected)
        self.assertNotIn("abs", neglected)


if __name__ == "__main__":
    unittest.main()
