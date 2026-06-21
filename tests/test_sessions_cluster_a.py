"""Cluster A regression tests: cardio same-day aggregation, isometric-hold
set counting, word-bounded warmup detection, and loaded-carry classification.

Synthetic data only — no real per-person data.
"""
from __future__ import annotations

import unittest


from workout_coach.lib import sessions
from shared import monthly_csv_values


class CardioSameDayAggregationTests(unittest.TestCase):
    """[A1] Two+ cardio bouts on one date must all contribute to the single
    (date, "cardio") session entry: durations SUM and avg_hr is a
    duration-weighted mean, so TRIMP / HR-zones / CTL recompute correctly.
    """

    def test_same_day_cardio_bouts_sum_duration_and_weight_hr(self) -> None:
        rows = [
            {"date": "2026-05-20", "exercise": "Pool Swim",
             "kg": None, "reps": None, "duration_min": 4.7, "distance_km": 0.2,
             "avg_hr": 144, "active_cal": 40, "total_cal": 48,
             "elevation_m": None, "elapsed": None, "source": "apple"},
            {"date": "2026-05-20", "exercise": "Pool Swim",
             "kg": None, "reps": None, "duration_min": 3.1, "distance_km": 0.15,
             "avg_hr": 140, "active_cal": 25, "total_cal": 31,
             "elevation_m": None, "elapsed": None, "source": "apple"},
            {"date": "2026-05-20", "exercise": "Outdoor Cycling",
             "kg": None, "reps": None, "duration_min": 16.2, "distance_km": 5.0,
             "avg_hr": 138, "active_cal": 130, "total_cal": 160,
             "elevation_m": 12, "elapsed": None, "source": "apple"},
        ]
        out = sessions.build_monthly_sessions(rows, {}, {}, [])
        cardio = [s for s in out if s["session_kind"] == "cardio"]
        self.assertEqual(len(cardio), 1)
        c = cardio[0]
        # All three bouts contribute: 4.7 + 3.1 + 16.2 = 24.0 min.
        self.assertAlmostEqual(c["duration_min"], 24.0, places=4)
        # Duration-weighted HR: (4.7*144 + 3.1*140 + 16.2*138) / 24.0.
        expected_hr = (4.7 * 144 + 3.1 * 140 + 16.2 * 138) / 24.0
        self.assertAlmostEqual(c["avg_hr"], expected_hr, places=2)
        # Weighted HR must sit within the bout HR range, dominated by the
        # 16.2-min ride at 138.
        self.assertGreater(c["avg_hr"], 138)
        self.assertLess(c["avg_hr"], 142)

    def test_same_day_cardio_sums_calories_and_distance(self) -> None:
        rows = [
            {"date": "2026-05-21", "exercise": "Pool Swim",
             "kg": None, "reps": None, "duration_min": 4.7, "distance_km": 0.2,
             "avg_hr": 144, "active_cal": 40, "total_cal": 48,
             "elevation_m": None, "elapsed": None, "source": "apple"},
            {"date": "2026-05-21", "exercise": "Outdoor Cycling",
             "kg": None, "reps": None, "duration_min": 16.2, "distance_km": 5.0,
             "avg_hr": 138, "active_cal": 130, "total_cal": 160,
             "elevation_m": 12, "elapsed": None, "source": "apple"},
        ]
        out = sessions.build_monthly_sessions(rows, {}, {}, [])
        c = [s for s in out if s["session_kind"] == "cardio"][0]
        self.assertAlmostEqual(c["active_cal"], 170, places=4)
        self.assertAlmostEqual(c["total_cal"], 208, places=4)
        self.assertAlmostEqual(c["distance_km"], 5.2, places=4)

    def test_single_cardio_bout_unchanged(self) -> None:
        # Regression guard: a lone cardio bout keeps its exact values.
        rows = [
            {"date": "2026-05-22", "exercise": "Outdoor Run",
             "kg": None, "reps": None, "duration_min": 35.4, "distance_km": 6.0,
             "avg_hr": 162, "active_cal": 396, "total_cal": 455,
             "elevation_m": 53, "elapsed": "35:24", "source": "apple"},
        ]
        out = sessions.build_monthly_sessions(rows, {}, {}, [])
        c = [s for s in out if s["session_kind"] == "cardio"][0]
        self.assertAlmostEqual(c["duration_min"], 35.4, places=4)
        self.assertEqual(c["avg_hr"], 162)
        self.assertEqual(c["elevation_m"], 53)


class IsometricHoldWorkingSetTests(unittest.TestCase):
    """[A5] A hold (reps=0, duration>0, not cardio/distance) counts as 1
    working SET; warmup-tagged prep is still excluded; load-based paths
    (e1RM) are unaffected.
    """

    def test_plank_hold_counts_as_working_set(self) -> None:
        plank = {"exercise": "Plank", "kg": 0, "reps": 0,
                 "duration_min": 1.0, "distance_km": None,
                 "avg_hr": None, "notes": None, "source": "manual"}
        self.assertTrue(sessions._is_working_set(plank))

    def test_dead_hang_warmup_still_excluded(self) -> None:
        dead_hang = {"exercise": "Dead Hang", "kg": 0, "reps": 0,
                     "duration_min": 0.5, "distance_km": None,
                     "avg_hr": None, "notes": "(warmup)", "source": "manual"}
        self.assertFalse(sessions._is_working_set(dead_hang))

    def test_cardio_hold_not_a_working_set(self) -> None:
        # A duration-only auto-imported cardio bout (reps 0) is NOT a set.
        cardio = {"exercise": "Indoor Cycle", "kg": None, "reps": 0,
                  "duration_min": 20.0, "distance_km": None,
                  "avg_hr": 132, "notes": None, "source": "apple"}
        self.assertFalse(sessions._is_working_set(cardio))

    def test_distance_row_not_a_working_set_via_hold_path(self) -> None:
        # A pure distance row (run) with reps 0 must not become a set.
        run = {"exercise": "Outdoor Run", "kg": None, "reps": 0,
               "duration_min": 30.0, "distance_km": 5.0,
               "avg_hr": 150, "notes": None, "source": "apple"}
        self.assertFalse(sessions._is_working_set(run))

    def test_normal_rep_set_still_counts(self) -> None:
        # Regression guard: ordinary loaded set unaffected.
        s = {"exercise": "Hack Squat", "kg": 40, "reps": 8,
             "duration_min": None, "distance_km": None,
             "avg_hr": None, "notes": None, "source": "manual"}
        self.assertTrue(sessions._is_working_set(s))


class WarmupDetectionTests(unittest.TestCase):
    """[A9] Warmup detection must be word-bounded + structured marker, not a
    bare ``"warmup"`` substring.
    """

    def test_hyphenated_warm_up_excluded_from_working_set(self) -> None:
        r = {"exercise": "Bench Press", "kg": 40, "reps": 5,
             "duration_min": None, "distance_km": None,
             "avg_hr": None, "notes": "warm-up ramp", "source": "manual"}
        self.assertFalse(sessions._is_working_set(r))

    def test_spaced_warm_up_excluded_from_working_set(self) -> None:
        r = {"exercise": "Bench Press", "kg": 40, "reps": 5,
             "duration_min": None, "distance_km": None,
             "avg_hr": None, "notes": "warm up set", "source": "manual"}
        self.assertFalse(sessions._is_working_set(r))

    def test_no_warmup_needed_is_not_excluded(self) -> None:
        # "no warmup needed" describes a real working set; must NOT be
        # dropped just because the substring "warmup" appears.
        r = {"exercise": "Bench Press", "kg": 52, "reps": 8,
             "duration_min": None, "distance_km": None,
             "avg_hr": None, "notes": "no warmup needed", "source": "manual"}
        self.assertTrue(sessions._is_working_set(r))

    def test_progression_summary_word_bounded_warmup(self) -> None:
        # The heaviest set is tagged "warm-up" → must be excluded, so the
        # 52kg working set becomes the reported best (not the 60kg warm-up).
        rows = [
            {"date": "2026-05-10", "exercise": "Bench Press",
             "kg": 60, "reps": 3, "notes": "warm-up ramp"},
            {"date": "2026-05-10", "exercise": "Bench Press",
             "kg": 52, "reps": 8, "notes": "no warmup needed"},
        ]
        summary = sessions.progression_summary(rows)
        self.assertEqual(len(summary), 1)
        # 52kg working set wins; the 60kg "warm-up" ramp is excluded, and
        # the "no warmup needed" set is correctly INCLUDED.
        self.assertIn("52kg", summary[0]["last"])
        self.assertNotIn("60kg", summary[0]["last"])


class LoadedCarryClassificationTests(unittest.TestCase):
    """[A18] A loaded carry (Farmer Walk, kg>0 + distance>0, reps 0) must
    NOT be classified as cardio in either sessions.py or
    shared/monthly_csv_values.py. It interacts with A5: as a loaded
    duration/set row it is part of the strength session.
    """

    def test_farmer_walk_not_cardio_in_sessions(self) -> None:
        farmer = {"exercise": "Farmer Walk", "kg": 40, "reps": 0,
                  "duration_min": 1.0, "distance_km": 0.04,
                  "avg_hr": None, "source": "manual"}
        self.assertFalse(sessions._is_cardio_row(farmer))

    def test_unloaded_distance_row_still_cardio_in_sessions(self) -> None:
        # Regression guard: a true distance bout (kg=0) stays cardio.
        run = {"exercise": "Outdoor Run", "kg": 0, "reps": None,
               "duration_min": 30.0, "distance_km": 5.0,
               "avg_hr": 150, "source": "apple"}
        self.assertTrue(sessions._is_cardio_row(run))

    def test_farmer_walk_not_cardio_in_monthly_csv_values(self) -> None:
        rows = [
            {"exercise": "Farmer Walk", "kg": 40, "reps": 0,
             "distance": 0.04, "duration": "1:00", "source": "manual"},
        ]
        kinds, _ = monthly_csv_values._classify_session_rows(rows)
        self.assertEqual(kinds, ["other"])

    def test_unloaded_distance_still_cardio_in_monthly_csv_values(self) -> None:
        rows = [
            {"exercise": "Outdoor Run", "kg": 0, "reps": 0,
             "distance": 5.0, "duration": "30:00", "source": "apple"},
        ]
        kinds, _ = monthly_csv_values._classify_session_rows(rows)
        self.assertEqual(kinds, ["cardio"])

    def test_farmer_walk_loaded_carry_counts_as_working_set(self) -> None:
        # A5 x A18 interaction: a loaded carry (reps 0, duration>0, kg>0)
        # is a working set (it's load-bearing core/grip work), NOT cardio.
        farmer = {"exercise": "Farmer Walk", "kg": 40, "reps": 0,
                  "duration_min": 1.0, "distance_km": 0.04,
                  "avg_hr": None, "notes": None, "source": "manual"}
        self.assertFalse(sessions._is_cardio_row(farmer))
        self.assertTrue(sessions._is_working_set(farmer))


if __name__ == "__main__":
    unittest.main()
