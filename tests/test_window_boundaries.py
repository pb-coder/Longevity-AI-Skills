from __future__ import annotations

import statistics
import unittest
from datetime import date, timedelta
from pathlib import Path

from workout_coach.lib import strength
from workout_coach.lib.cardio import cardio_last_28d
from workout_coach.lib.extract import load_exercises_db
from workout_coach.lib.light_therapy import recent_light_therapy_sessions
from workout_coach.lib.sleep import recent_sleep_nights
from workout_coach.lib.strength import (
    hr_at_volume_divergence,
    weekly_volume_per_muscle,
)
from workout_coach.lib.swim import recent_swim_workouts
from workout_coach.lib.thermal import recent_thermal_sessions

_DB = load_exercises_db(
    Path(__file__).resolve().parents[1] / "shared" / "exercises-database.md"
)


def _quad_set(day: str) -> dict:
    """One working set of a primary-quads, no-synergist movement."""
    return {"date": day, "exercise": "Leg Extension",
            "kg": 60, "reps": 10, "notes": ""}


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


class WeeklyVolumeWindowTests(unittest.TestCase):
    """``weekly_volume_per_muscle`` had no boundary coverage at all, and
    was the one helper still spanning ``window_days + 1`` inclusive days
    while dividing by ``window_days / 7`` — an always-upward bias."""

    today = date(2026, 5, 28)

    def volume(self, days: list[str], window_days: int = 28) -> float:
        unknown: set[str] = set()
        result = weekly_volume_per_muscle(
            [_quad_set(d) for d in days], _DB, self.today, window_days, unknown
        )
        return result["current"].get("quads", 0.0)

    def test_window_spans_exactly_n_inclusive_days(self) -> None:
        # today - 27 is the 28th day and counts; today - 28 is the 29th and
        # must not. Before the fix both landed inside a 28-day window.
        self.assertEqual(self.volume(["2026-05-01"]), 0.2)   # 28th day, in
        self.assertEqual(self.volume(["2026-04-30"]), 0.0)   # 29th day, out
        self.assertEqual(self.volume(["2026-05-28"]), 0.2)   # today, in

    def test_rows_after_today_are_rejected(self) -> None:
        self.assertEqual(self.volume(["2026-05-29"]), 0.0)
        self.assertEqual(self.volume(["2026-06-30"]), 0.0)

    def test_29th_day_no_longer_inflates_the_weekly_mean(self) -> None:
        # Four sets inside the window plus one on the 29th day. The extra
        # set used to be counted and divided by 4.0 weeks, adding 0.25
        # sets/wk of pure boundary error.
        inside = ["2026-05-28", "2026-05-21", "2026-05-14", "2026-05-07"]
        self.assertEqual(self.volume(inside), 1.0)
        self.assertEqual(self.volume(inside + ["2026-04-30"]), 1.0)

    def test_per_week_buckets_are_oldest_first_and_cover_the_window(self) -> None:
        unknown: set[str] = set()
        rows = (
            [_quad_set("2026-05-28")] * 3      # week 0 → newest bucket
            + [_quad_set("2026-05-10")] * 2    # 18 days back → bucket 2
            + [_quad_set("2026-05-01")]        # 27 days back → oldest bucket
        )
        result = weekly_volume_per_muscle(rows, _DB, self.today, 28, unknown)
        self.assertEqual(result["per_week"]["quads"], [1.0, 2.0, 0.0, 3.0])
        # The mean over the window must still equal the sum of the buckets
        # divided by the number of weeks.
        self.assertEqual(result["current"]["quads"], 1.5)

    def test_a_window_that_is_not_whole_weeks_is_rejected(self) -> None:
        """The buckets are 7 days wide, so 30 days leaves a 2-day oldest
        bucket. It reads as a near-empty week, dragging ``median`` down, and
        it breaks ``sum(per_week) / n_weeks == current``. Only 28 is passed
        today, so this was latent — reject it rather than let the next
        caller find out from a wrong median."""
        for bad in (30, 10, 1, 0, -7):
            with self.subTest(window_days=bad):
                with self.assertRaises(ValueError) as ctx:
                    weekly_volume_per_muscle(
                        [_quad_set("2026-05-28")], _DB, self.today, bad, set()
                    )
                self.assertIn("whole", str(ctx.exception))
        for good in (7, 14, 28, 56):
            with self.subTest(window_days=good):
                out = weekly_volume_per_muscle(
                    [_quad_set("2026-05-28")], _DB, self.today, good, set()
                )
                self.assertEqual(len(out["per_week"]["quads"]), good // 7)

    def test_bucket_sum_over_weeks_equals_current(self) -> None:
        unknown: set[str] = set()
        days = ["2026-05-28", "2026-05-27", "2026-05-20", "2026-05-13",
                "2026-05-12", "2026-05-11", "2026-05-04", "2026-05-03"]
        result = weekly_volume_per_muscle(
            [_quad_set(d) for d in days], _DB, self.today, 28, unknown
        )
        per_week = result["per_week"]["quads"]
        n_weeks = len(per_week)
        self.assertEqual(n_weeks, 4)
        self.assertAlmostEqual(
            sum(per_week) / n_weeks, result["current"]["quads"], places=6
        )

    def test_median_comes_from_the_stdlib(self) -> None:
        """``CLAUDE.md``: one concept, one source of truth. The hand-rolled
        ``_median`` is gone; the emitted value must match
        ``statistics.median`` including on an even-length bucket list, where
        a reimplementation most often diverges."""
        self.assertFalse(
            hasattr(strength, "_median"),
            "strength._median is back — use statistics.median",
        )
        unknown: set[str] = set()
        days = (["2026-05-28"] * 5 + ["2026-05-20"] * 3
                + ["2026-05-13"] * 2 + ["2026-05-04"] * 4)
        result = weekly_volume_per_muscle(
            [_quad_set(d) for d in days], _DB, self.today, 28, unknown
        )
        buckets = result["per_week"]["quads"]      # oldest-first, 4 entries
        self.assertEqual(sorted(buckets), [2.0, 3.0, 4.0, 5.0])
        self.assertEqual(
            result["median"]["quads"], round(statistics.median(buckets), 1)
        )
        self.assertEqual(result["median"]["quads"], 3.5)


class HrAtVolumeDivergenceWindowTests(unittest.TestCase):
    """``hr_at_volume_divergence`` was the last helper still running one
    day long: ``today_d - weeks*7`` with a ``d < cutoff`` test spans 57
    inclusive days for an 8-week window."""

    today = date(2026, 6, 5)

    def _fixture(self, oldest_days_back: int):
        """Six squat sessions; the oldest sits ``oldest_days_back`` back."""
        offsets = [oldest_days_back, 42, 35, 28, 21, 14, 7, 0]
        rows, sessions_ = [], []
        for i, back in enumerate(offsets):
            d = (self.today - timedelta(days=back)).isoformat()
            rows.append({"date": d, "exercise": "Leg Extension",
                         "kg": 60, "reps": 10, "notes": "", "volume": 600})
            sessions_.append({"date": d, "session_kind": "strength",
                              "avg_hr": 120 + i * 2})
        return rows, sessions_

    def test_the_57th_day_is_outside_an_eight_week_window(self) -> None:
        inside = hr_at_volume_divergence(
            *self._fixture(55), db=_DB, today_d=self.today, window_weeks=8)
        edge = hr_at_volume_divergence(
            *self._fixture(56), db=_DB, today_d=self.today, window_weeks=8)
        self.assertEqual(inside["quads"]["n_sessions"], 8)
        # Day 56 back is the 57th inclusive day: out.
        self.assertEqual(edge["quads"]["n_sessions"], 7)

    def test_the_56th_day_is_the_last_one_inside(self) -> None:
        out = hr_at_volume_divergence(
            *self._fixture(55), db=_DB, today_d=self.today, window_weeks=8)
        self.assertEqual(out["quads"]["n_sessions"], 8)


if __name__ == "__main__":
    unittest.main()
