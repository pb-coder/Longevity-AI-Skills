from __future__ import annotations

import unittest
from datetime import date, timedelta


from workout_coach.lib import sessions


class BuildMonthlySessionsTests(unittest.TestCase):
    def test_strength_session_does_not_inherit_cardio_row_metadata(self) -> None:
        # Mixed-day: manual strength session + 2 auto-imported cycling
        # rides. The strength TOTAL summary is empty (manual session has
        # no Apple-watch metadata). The first cycling ride's duration,
        # avg HR, elevation, calories must NOT bleed into the strength
        # session's metadata.
        rows = [
            {"date": "2026-05-11", "exercise": "Hack Squat",
             "kg": 40, "reps": 8, "duration_min": None, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
            {"date": "2026-05-11", "exercise": "Outdoor Cycling",
             "kg": None, "reps": None, "duration_min": 14.1, "distance_km": 3.7,
             "avg_hr": 150, "active_cal": 120, "total_cal": 150,
             "elevation_m": 22, "elapsed": "14:06", "source": "apple"},
            {"date": "2026-05-11", "exercise": "Outdoor Cycling",
             "kg": None, "reps": None, "duration_min": 6.3, "distance_km": 0.9,
             "avg_hr": 138, "active_cal": 46, "total_cal": 56,
             "elevation_m": 8, "elapsed": "6:18", "source": "apple"},
        ]
        out = sessions.build_monthly_sessions(rows, {}, {}, [])
        self.assertEqual(len(out), 2)
        strength = out[0]
        cardio = out[1]
        self.assertEqual(strength["session_kind"], "strength")
        self.assertIsNone(strength["duration_min"])
        self.assertIsNone(strength["elevation_m"])
        self.assertIsNone(strength["avg_hr"])
        self.assertIsNone(strength["active_cal"])
        self.assertEqual(cardio["session_kind"], "cardio")
        # Both cycling bouts aggregate into the single cardio entry:
        # durations sum (14.1 + 6.3 = 20.4) and avg_hr is the
        # duration-weighted mean — neither bout is dropped (A1).
        self.assertAlmostEqual(cardio["duration_min"], 20.4, places=4)
        expected_hr = (14.1 * 150 + 6.3 * 138) / 20.4
        self.assertAlmostEqual(cardio["avg_hr"], expected_hr, places=2)

    def test_strength_session_uses_total_summary_when_present(self) -> None:
        # Mixed day with HealthAutoExport TOTAL summary present: strength
        # session takes its metadata from the TOTAL summary, not cardio.
        rows = [
            {"date": "2026-04-27", "exercise": "Hack Squat",
             "kg": 40, "reps": 8, "duration_min": None, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
            {"date": "2026-04-27", "exercise": "Outdoor Cycling",
             "kg": None, "reps": None, "duration_min": 13.9, "distance_km": 4.3,
             "avg_hr": 150, "active_cal": 124, "total_cal": 147,
             "elevation_m": 7, "elapsed": "13:54", "source": "apple"},
        ]
        summaries = {"2026-04-27": {
            "duration_min": 62.2, "avg_hr": 131.3,
            "active_cal": 505, "total_cal": 601,
            "elevation_m": None, "elapsed": "1:02:12",
        }}
        out = sessions.build_monthly_sessions(rows, summaries, {}, [])
        s = out[0]
        self.assertEqual(s["session_kind"], "strength")
        self.assertEqual(s["duration_min"], 62.2)
        self.assertEqual(s["avg_hr"], 131.3)
        self.assertEqual(s["active_cal"], 505)
        # TOTAL summary had no elevation → stays None, NOT 7 from cycling.
        self.assertIsNone(s["elevation_m"])

    def test_pure_cardio_session_still_inherits_from_cardio_rows(self) -> None:
        # No strength rows on the date → cardio row metadata fills the
        # session (the previous behavior, unchanged for pure cardio).
        rows = [
            {"date": "2026-04-02", "exercise": "Outdoor Run",
             "kg": None, "reps": None, "duration_min": 35.4, "distance_km": 6.0,
             "avg_hr": 162, "active_cal": 396, "total_cal": 455,
             "elevation_m": 53, "elapsed": "35:24", "source": "apple"},
        ]
        out = sessions.build_monthly_sessions(rows, {}, {}, [])
        s = out[0]
        self.assertEqual(s["session_kind"], "cardio")
        self.assertEqual(s["duration_min"], 35.4)
        self.assertEqual(s["avg_hr"], 162)
        self.assertEqual(s["elevation_m"], 53)

    def test_isometric_hold_is_not_treated_as_cardio_row(self) -> None:
        # Dead Hang with duration_min=0.5, no HR, no distance, manual
        # source → must be classified as "other", not "cardio". So the
        # session_kind for a hold-only day must be "other", not "cardio".
        rows = [
            {"date": "2026-05-14", "exercise": "Dead Hang",
             "kg": 0, "reps": 0, "duration_min": 0.5, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
        ]
        self.assertFalse(sessions._is_cardio_row(rows[0]))
        out = sessions.build_monthly_sessions(rows, {}, {}, [])
        s = out[0]
        self.assertEqual(s["session_kind"], "other")
        self.assertIsNone(s["duration_min"])

    def test_isometric_hold_in_strength_session_does_not_set_duration(self) -> None:
        # Strength session with Jumping Jacks + Dead Hang + working sets.
        # The Dead Hang's 0:30 hold time must not propagate to the
        # session's duration_min.
        rows = [
            {"date": "2026-05-14", "exercise": "Jumping Jacks",
             "kg": 0, "reps": 50, "duration_min": None, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
            {"date": "2026-05-14", "exercise": "Dead Hang",
             "kg": 0, "reps": 0, "duration_min": 0.5, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
            {"date": "2026-05-14", "exercise": "Cable Lat Pulldown",
             "kg": 57.5, "reps": 8, "duration_min": None, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
        ]
        out = sessions.build_monthly_sessions(rows, {}, {}, [])
        s = out[0]
        self.assertEqual(s["session_kind"], "strength")
        self.assertIsNone(s["duration_min"])


class LoadedCarryWorkingSetTests(unittest.TestCase):
    """A carry is scored by load, not by reps. Requiring ``duration_min``
    when ``reps == 0`` meant a carry measured in metres scored zero sets
    and zero volume."""

    def carry(self, **over) -> dict:
        r = {"date": "2026-02-23", "exercise": "Dumbbell Farmer Walk",
             "kg": 48, "reps": 0, "duration_min": None, "distance_km": None,
             "avg_hr": None, "source": "manual", "notes": ""}
        r.update(over)
        return r

    def test_loaded_carry_by_distance_counts(self) -> None:
        self.assertTrue(sessions._is_working_set(self.carry(distance_km=0.03)))

    def test_loaded_carry_by_duration_counts(self) -> None:
        self.assertTrue(sessions._is_working_set(self.carry(duration_min=0.67)))

    def test_loaded_carry_by_distance_is_not_cardio(self) -> None:
        # The distance→cardio gate keys on kg <= 0, so a loaded carry with
        # distance stays strength work on both sides of the classification.
        row = self.carry(distance_km=0.03)
        self.assertFalse(sessions._is_cardio_row(row))
        out = sessions.build_monthly_sessions([row], {}, {}, [])
        self.assertEqual(out[0]["session_kind"], "other")

    def test_unloaded_distance_row_is_still_cardio(self) -> None:
        run = {"date": "2026-02-23", "exercise": "Outdoor Run",
               "kg": 0, "reps": 0, "duration_min": 35.4, "distance_km": 6.0,
               "avg_hr": 162, "source": "apple", "notes": ""}
        self.assertTrue(sessions._is_cardio_row(run))
        self.assertFalse(sessions._is_working_set(run))
        out = sessions.build_monthly_sessions([run], {}, {}, [])
        self.assertEqual(out[0]["session_kind"], "cardio")

    def test_warmup_tagged_carry_is_still_excluded(self) -> None:
        self.assertFalse(sessions._is_working_set(
            self.carry(distance_km=0.03, notes="(warmup)")
        ))

    def test_carry_with_no_work_unit_at_all_still_scores_zero(self) -> None:
        # Documented gap, not an oversight: a load with neither a duration
        # nor a distance carries no work unit to count. Historical rows in
        # this shape need a data fix; the logger now writes carry time to
        # Duration (min).
        self.assertFalse(sessions._is_working_set(self.carry()))


def _pre_fix_trend(entries: list[dict]) -> float:
    """The estimator this replaces, reproduced verbatim.

    Last 8 clean readings; mean-of-3 head and tail; centroid-to-centroid
    span. Kept here — not imported — so these tests keep failing against
    the old behaviour no matter how ``sessions`` is refactored later.
    """
    pts = sorted(
        (date.fromisoformat(e["date"]), float(e["kg"])) for e in entries
    )[-8:]
    n = max(1, min(3, len(pts) // 2))
    head, tail = pts[:n], pts[-n:]
    head_mean = sum(v for _, v in head) / n
    tail_mean = sum(v for _, v in tail) / n
    base = pts[0][0]
    head_day = sum((d - base).days for d, _ in head) / n
    tail_day = sum((d - base).days for d, _ in tail) / n
    return round((tail_mean - head_mean) / (tail_day - head_day) * 7.0, 3)


def _series(start: str, offsets: list[int], kgs: list[float]) -> list[dict]:
    d0 = date.fromisoformat(start)
    return [
        {"date": (d0 + timedelta(days=o)).isoformat(), "kg": kg, "notes": ""}
        for o, kg in zip(offsets, kgs)
    ]


# A synthetic 36-day phase with the shape that produced the shipped bug: a
# high outlier sitting near the head of the trailing 8 readings, on a series
# whose honest fit over the whole phase is flat-to-slightly-up. Values and
# dates are invented; only the shape is borrowed.
_SPURIOUS_LOSS_START = "2025-03-04"
_SPURIOUS_LOSS_ANCHOR = "2025-04-08"
_SPURIOUS_LOSS = _series(
    _SPURIOUS_LOSS_START,
    [0, 2, 7, 8, 10, 11, 12, 13, 14, 16, 21, 23, 25, 29, 33],
    [71.10, 71.30, 72.60, 72.85, 71.95, 74.40, 74.05, 74.15,
     72.15, 72.55, 71.95, 72.10, 71.45, 72.80, 72.70],
)

# A real +0.5 kg/wk ramp carrying one 2.6 kg spike. The spike lands at the
# head of the trailing-8 window, which is all it takes for a head/tail
# estimator to invert the sign of a gain that is actually there.
_GENUINE_GAIN_START = "2025-06-02"
_GENUINE_GAIN_ANCHOR = "2025-07-07"
_GENUINE_GAIN = _series(
    _GENUINE_GAIN_START,
    [0, 3, 6, 9, 12, 15, 17, 20, 23, 26, 29, 32, 34],
    [68.00, 68.21, 68.43, 68.64, 68.86, 69.07, 71.81,
     69.98, 69.29, 69.86, 70.07, 69.99, 70.18],
)


class BodyweightTrendEstimatorTests(unittest.TestCase):
    """The estimator must not report a sign the data cannot support.

    Reference values below were cross-checked against ``numpy.polyfit(x, y,
    1, cov=True)`` on the same points: fixture A slope +0.0643 kg/wk / SE
    0.2047, fixture B slope +0.4531 / SE 0.1436.
    """

    def test_a_spurious_loss_is_reported_as_unresolved_not_as_a_loss(self) -> None:
        # Establish the input shape: the pre-fix estimator calls this a
        # confident loss.
        self.assertLessEqual(_pre_fix_trend(_SPURIOUS_LOSS), -0.30)

        block = sessions.bodyweight_trend(
            _SPURIOUS_LOSS,
            today_d=_SPURIOUS_LOSS_ANCHOR,
            start_date=_SPURIOUS_LOSS_START,
        )
        # No number is emitted, and the reason is explicit.
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "ci_straddles_zero")
        self.assertIsNone(block["kg_per_week"])
        self.assertIsNone(
            sessions.bodyweight_trend_kg_per_week(
                _SPURIOUS_LOSS,
                start_date=_SPURIOUS_LOSS_START,
                today_d=_SPURIOUS_LOSS_ANCHOR,
            )
        )
        # SIGN, not magnitude: the phase truth is a slight GAIN, and the
        # point estimate must agree with it rather than with the outlier.
        self.assertEqual(block["point_kg_per_week"], 0.064)
        self.assertGreater(block["point_kg_per_week"], 0.0)
        self.assertEqual(block["se_kg_per_week"], 0.205)
        low, high = block["ci95_kg_per_week"]
        self.assertLess(low, 0.0)
        self.assertGreater(high, 0.0)

    def test_a_genuine_gain_still_reads_as_a_gain(self) -> None:
        # The pre-fix estimator turns a real +0.45 kg/wk gain into a loss.
        self.assertLess(_pre_fix_trend(_GENUINE_GAIN), 0.0)

        block = sessions.bodyweight_trend(
            _GENUINE_GAIN,
            today_d=_GENUINE_GAIN_ANCHOR,
            start_date=_GENUINE_GAIN_START,
        )
        self.assertEqual(block["state"], "resolved")
        self.assertIsNone(block["reason"])
        self.assertEqual(block["kg_per_week"], 0.453)
        self.assertEqual(block["se_kg_per_week"], 0.144)
        low, high = block["ci95_kg_per_week"]
        self.assertGreater(low, 0.0, "a resolved gain must exclude zero")
        self.assertEqual(
            sessions.bodyweight_trend_kg_per_week(
                _GENUINE_GAIN,
                start_date=_GENUINE_GAIN_START,
                today_d=_GENUINE_GAIN_ANCHOR,
            ),
            0.453,
        )

    def test_window_is_time_based_not_reading_count_based(self) -> None:
        # Six weigh-ins crammed into the last 9 days plus a sparse tail.
        # A "last 8 readings" window spans 9 days here and reports that
        # burst as a weekly rate; a time window spans the full 28.
        entries = _series(
            "2025-08-01",
            [0, 6, 13, 19, 20, 21, 22, 24, 27],
            [75.00, 75.10, 75.20, 76.90, 75.00, 76.80, 75.10, 76.70, 75.20],
        )
        block = sessions.bodyweight_trend(entries, today_d="2025-08-28")
        self.assertEqual(block["window_days"], 28)
        self.assertEqual(block["window_start"], "2025-08-01")
        self.assertEqual(block["n_readings"], 9)
        # The pre-fix window would have covered only the last 8 readings.
        pre_fix_pts = sorted(e["date"] for e in entries)[-8:]
        pre_fix_span = (
            date.fromisoformat(pre_fix_pts[-1])
            - date.fromisoformat(pre_fix_pts[0])
        ).days
        self.assertEqual(pre_fix_span, 21)
        self.assertGreater(block["window_days"], pre_fix_span)

    def test_the_same_window_length_is_used_at_every_anchor(self) -> None:
        # The concrete regression: the old field silently described 16 days
        # at one anchor and 9 at another. Window length must be a property
        # of the estimator, not of how densely the user happened to weigh in.
        dense = _series("2025-09-01", list(range(0, 28)),
                        [74.0 + 0.02 * i for i in range(28)])
        sparse = _series("2025-09-01", [0, 9, 18, 27],
                         [74.0, 74.2, 74.4, 74.6])
        for label, entries in (("dense", dense), ("sparse", sparse)):
            with self.subTest(label):
                block = sessions.bodyweight_trend(entries, today_d="2025-09-28")
                self.assertEqual(block["window_days"], 28)

    def test_a_phase_shorter_than_the_minimum_window_cannot_resolve(self) -> None:
        entries = _series("2025-10-01", [0, 3, 6, 9, 12, 15],
                          [80.0, 79.6, 79.3, 78.9, 78.6, 78.2])
        block = sessions.bodyweight_trend(
            entries, today_d="2025-10-17", start_date="2025-10-01",
        )
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "window_shorter_than_min")
        self.assertEqual(block["window_days"], 17)
        self.assertIsNone(block["kg_per_week"])
        # No point estimate either — a 17-day window has nothing to say
        # about a weekly rate, and half an answer invites a whole claim.
        self.assertIsNone(block["point_kg_per_week"])

    def test_start_date_bounds_the_window_to_the_phase(self) -> None:
        # Pre-phase readings sit far below the phase; including them would
        # manufacture a large gain that never happened inside the phase.
        entries = _series(
            "2025-11-01",
            [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44],
            [70.0, 70.2, 70.4, 70.6, 76.0, 76.1, 75.9, 76.2,
             76.0, 76.1, 75.8, 76.0],
        )
        phase_start = (date(2025, 11, 1) + timedelta(days=16)).isoformat()
        anchor = (date(2025, 11, 1) + timedelta(days=44)).isoformat()
        unscoped = sessions.bodyweight_trend(entries, today_d=anchor)
        scoped = sessions.bodyweight_trend(
            entries, today_d=anchor, start_date=phase_start,
        )
        self.assertEqual(scoped["window_start"], phase_start)
        self.assertEqual(scoped["n_readings"], 8)
        self.assertEqual(scoped["state"], "unresolved")
        self.assertNotEqual(unscoped["window_start"], phase_start)

    def test_too_few_readings_in_a_long_enough_window(self) -> None:
        entries = _series("2025-12-01", [0, 14, 27], [80.0, 79.0, 78.0])
        block = sessions.bodyweight_trend(entries, today_d="2025-12-28")
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "too_few_readings")
        self.assertIsNone(block["kg_per_week"])

    def test_no_readings_at_all(self) -> None:
        block = sessions.bodyweight_trend([], today_d="2025-12-28")
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "no_readings")
        self.assertIsNone(block["kg_per_week"])
        self.assertIsNone(sessions.bodyweight_trend_kg_per_week([]))

    def test_scalar_accessor_is_not_a_second_implementation(self) -> None:
        # Structural, not numeric: replace the block builder with a
        # sentinel. A scalar that still computes its own rate cannot pick
        # this up, which is exactly the failure mode the old
        # "single implementation" test could not detect.
        sentinel = {"kg_per_week": -12345.0}
        original = sessions.bodyweight_trend
        sessions.bodyweight_trend = lambda *a, **k: sentinel  # type: ignore[assignment]
        try:
            self.assertEqual(
                sessions.bodyweight_trend_kg_per_week(_GENUINE_GAIN),
                -12345.0,
            )
        finally:
            sessions.bodyweight_trend = original  # type: ignore[assignment]

    def test_non_fasted_entries_are_still_excluded(self) -> None:
        clean = _series("2026-01-05", [0, 7, 14, 21, 27],
                        [72.0, 72.3, 72.6, 72.9, 73.2])
        dirty = list(clean)
        dirty.insert(3, {"date": "2026-01-25", "kg": 99.0,
                         "notes": "evening, not fasted"})
        self.assertEqual(
            sessions.bodyweight_trend(clean, today_d="2026-02-01"),
            sessions.bodyweight_trend(dirty, today_d="2026-02-01"),
        )


class OlsRateTests(unittest.TestCase):
    def test_ols_recovers_an_exact_ramp_with_a_zero_width_interval(self) -> None:
        pts = [(date(2026, 5, 1) + timedelta(days=3 * i), 77.0 + 0.15 * i)
               for i in range(6)]
        fit = sessions.ols_rate_per_week(pts)
        self.assertAlmostEqual(fit["per_week"], 0.35, places=6)
        self.assertAlmostEqual(fit["se_per_week"], 0.0, places=6)
        self.assertEqual(fit["n"], 6)
        self.assertEqual(fit["dof"], 4)

    def test_ols_needs_three_points_and_some_time_variance(self) -> None:
        self.assertIsNone(sessions.ols_rate_per_week(
            [(date(2026, 5, 1), 80.0), (date(2026, 5, 8), 79.0)]
        ))
        self.assertIsNone(sessions.ols_rate_per_week(
            [(date(2026, 5, 1), 80.0), (date(2026, 5, 1), 79.0),
             (date(2026, 5, 1), 78.0)]
        ))

    def test_one_outlier_moves_ols_far_less_than_it_moves_endpoints(self) -> None:
        clean = [(date(2026, 5, 1) + timedelta(days=2 * i), 77.0 + 0.05 * i)
                 for i in range(15)]
        spiked = list(clean)
        spiked[1] = (spiked[1][0], spiked[1][1] + 3.0)
        base = sessions.ols_rate_per_week(clean)["per_week"]
        moved = sessions.ols_rate_per_week(spiked)["per_week"]
        endpoint_base = sessions.smoothed_rate_per_week(clean)
        endpoint_moved = sessions.smoothed_rate_per_week(spiked)
        self.assertLess(abs(moved - base), abs(endpoint_moved - endpoint_base))


class SmoothedRateTests(unittest.TestCase):
    def test_smoothing_uses_centroid_span_not_outermost_span(self) -> None:
        # Two flat plateaus 2 kg apart. The group centroids sit 18 days
        # apart (day 1 and day 19), so the honest rate is -2/18*7 kg/wk.
        # Dividing by the 20-day OUTER span would report -0.700 and
        # understate the change by 10%.
        pts = [
            (date(2026, 5, 1), 80.0), (date(2026, 5, 2), 80.0),
            (date(2026, 5, 3), 80.0), (date(2026, 5, 19), 78.0),
            (date(2026, 5, 20), 78.0), (date(2026, 5, 21), 78.0),
        ]
        self.assertAlmostEqual(
            sessions.smoothed_rate_per_week(pts), -0.778, places=3
        )
        outer_span_answer = (78.0 - 80.0) / 20 * 7
        self.assertNotAlmostEqual(
            sessions.smoothed_rate_per_week(pts), outer_span_answer, places=3
        )

    def test_it_refuses_rather_than_degrading_to_raw_endpoints(self) -> None:
        # A 3-point series cannot be smoothed: any head/tail split collapses
        # to the raw endpoints. Returning that number under a name that
        # promises smoothing is the silent degradation being fixed.
        three = [(date(2026, 5, 1), 80.0), (date(2026, 5, 5), 79.0),
                 (date(2026, 5, 12), 78.0)]
        self.assertIsNone(sessions.smoothed_rate_per_week(three))
        raw_endpoints = (78.0 - 80.0) / 11 * 7
        self.assertAlmostEqual(raw_endpoints, -1.273, places=3)

        four = three + [(date(2026, 5, 15), 77.5)]
        self.assertIsNotNone(sessions.smoothed_rate_per_week(four))

    def test_two_points_return_none(self) -> None:
        self.assertIsNone(sessions.smoothed_rate_per_week(
            [(date(2026, 5, 1), 80.0), (date(2026, 5, 8), 79.0)]
        ))


class NoRealPersonalDataTests(unittest.TestCase):
    """``Skills/CLAUDE.md`` forbids committing profile facts. A dated
    bodyweight series is one, so the fixtures above must not reproduce the
    tracker's own weigh-ins."""

    def test_fixtures_are_dated_outside_the_tracker_era(self) -> None:
        for label, series in (("spurious_loss", _SPURIOUS_LOSS),
                              ("genuine_gain", _GENUINE_GAIN)):
            with self.subTest(label):
                for entry in series:
                    self.assertLess(entry["date"], "2026-01-01")


if __name__ == "__main__":
    unittest.main()
