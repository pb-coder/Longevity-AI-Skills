"""Tests for the daily-energy surface added with the Steps / Active Energy /
Basal Energy columns.

Three producers are covered:

* ``cardio.energy_28d`` — the ``energy_28d`` block: the three daily means,
  the per-DAY TDEE rule, the absent-channel case, and the trend pair.
* ``cardio.daily_activity_28d`` — ``steps_daily_avg`` and the step-count
  band, which is now the primary basis for ``assessment``.
* ``nutrition_phase.nutrition_phase_summary`` — the ``energy`` sub-block's
  deficit arithmetic, its sign convention, and its omission when no
  measured TDEE exists.

All data is synthetic — no real personal data.
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from workout_coach.lib.cardio import (
    STEPS_HIGH_PER_DAY,
    STEPS_LOW_PER_DAY,
    daily_activity_28d,
    energy_28d,
)
from workout_coach.lib.nutrition_phase import nutrition_phase_summary


TODAY = date(2026, 8, 15)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _day(offset: int, **fields) -> dict:
    """One health_metrics row ``offset`` days before ``TODAY``."""
    row = {"date": (TODAY - timedelta(days=offset)).isoformat()}
    row.update(fields)
    return row


def _flat_energy(n_days: int = 28, active: float = 1000.0,
                 basal: float = 2100.0) -> list[dict]:
    """``n_days`` consecutive days ending today, both components present."""
    return [
        _day(i, active_energy_kcal=active, basal_energy_kcal=basal)
        for i in range(n_days)
    ]


def _open_cut_phase(target_rate: float = -0.5) -> list[dict]:
    return [{
        "start_date": (TODAY - timedelta(days=42)).isoformat(),
        "end_date": None,
        "phase_type": "cut",
        "target_rate_kg_per_wk": target_rate,
    }]


# ---------------------------------------------------------------------------
# energy_28d — the three daily means
# ---------------------------------------------------------------------------

class EnergyAveragesTests(unittest.TestCase):

    def test_means_are_whole_kcal_and_tdee_is_the_sum(self):
        block = energy_28d(_flat_energy(28, active=1058.0, basal=2146.0), TODAY)
        self.assertEqual(block["active_kcal_daily_avg"], 1058)
        self.assertEqual(block["basal_kcal_daily_avg"], 2146)
        self.assertEqual(block["tdee_kcal_daily_avg"], 3204)
        self.assertEqual(block["n_days"], 28)
        self.assertIsInstance(block["tdee_kcal_daily_avg"], int)

    def test_means_average_only_the_days_that_carry_a_reading(self):
        """Seven populated days out of 28 average over 7, not over 28.

        Dividing by the window instead of by the readings would report a
        quarter of the athlete's real expenditure and read as a crash.
        """
        rows = _flat_energy(7, active=1000.0, basal=2000.0)
        rows += [_day(i) for i in range(7, 28)]  # 21 blank days
        block = energy_28d(rows, TODAY)
        self.assertEqual(block["active_kcal_daily_avg"], 1000)
        self.assertEqual(block["basal_kcal_daily_avg"], 2000)
        self.assertEqual(block["tdee_kcal_daily_avg"], 3000)
        self.assertEqual(block["n_days"], 7)

    def test_readings_outside_the_28_day_window_are_excluded(self):
        rows = _flat_energy(28, active=1000.0, basal=2000.0)
        # A day 40 back with wildly different values must not move the mean.
        rows.append(_day(40, active_energy_kcal=9000.0,
                         basal_energy_kcal=9000.0))
        block = energy_28d(rows, TODAY)
        self.assertEqual(block["n_days"], 28)
        self.assertEqual(block["tdee_kcal_daily_avg"], 3000)

    def test_future_dated_rows_do_not_enter_the_window(self):
        rows = _flat_energy(28, active=1000.0, basal=2000.0)
        rows.append(_day(-3, active_energy_kcal=9000.0,
                         basal_energy_kcal=9000.0))
        block = energy_28d(rows, TODAY)
        self.assertEqual(block["n_days"], 28)
        self.assertEqual(block["tdee_kcal_daily_avg"], 3000)


# ---------------------------------------------------------------------------
# energy_28d — the both-present-only TDEE rule
# ---------------------------------------------------------------------------

class TdeeBothPresentRuleTests(unittest.TestCase):

    def test_tdee_uses_only_days_carrying_both_components(self):
        """TDEE is a per-day sum, never the sum of two windowed means.

        The two columns are given deliberately different day sets, which
        is the only arrangement that tells the two arithmetics apart:

          * days 0-3   — active 500, basal 2,000   (both present)
          * days 4-13  — active 1,500, basal blank (active only)
          * days 14-27 — basal 2,400, active blank (basal only)

        The active mean is then 1,214 over its 14 days and the basal mean
        2,311 over its 18, so summing two independently-windowed means
        reports 3,525 — a figure no day in the file shows, built by adding
        one fortnight's active energy to a different fortnight's basal.
        The honest TDEE is the mean of the four days that carry both:
        2,500.
        """
        rows = []
        for i in range(28):
            if i < 4:
                fields = {"active_energy_kcal": 500.0,
                          "basal_energy_kcal": 2000.0}
            elif i < 14:
                fields = {"active_energy_kcal": 1500.0}
            else:
                fields = {"basal_energy_kcal": 2400.0}
            rows.append(_day(i, **fields))
        block = energy_28d(rows, TODAY)

        # n_days is the both-present count — not the window, and not
        # either column's own count.
        self.assertEqual(block["n_days"], 4)
        self.assertEqual(block["n_active_days"], 14)
        self.assertEqual(block["n_basal_days"], 18)
        self.assertEqual(block["active_kcal_daily_avg"], 1214)
        self.assertEqual(block["basal_kcal_daily_avg"], 2311)
        # Mean over the both-present days, each summed first.
        self.assertEqual(block["tdee_kcal_daily_avg"], 2500)
        # ...which is NOT active_mean + basal_mean.
        naive = (block["active_kcal_daily_avg"]
                 + block["basal_kcal_daily_avg"])
        self.assertEqual(naive, 3525)
        self.assertNotEqual(block["tdee_kcal_daily_avg"], naive)

    def test_no_overlapping_day_means_no_tdee_but_the_block_survives(self):
        rows = [_day(i, active_energy_kcal=1000.0) for i in range(0, 14)]
        rows += [_day(i, basal_energy_kcal=2000.0) for i in range(14, 28)]
        block = energy_28d(rows, TODAY)
        self.assertIsNotNone(block)
        self.assertIsNone(block["tdee_kcal_daily_avg"])
        self.assertEqual(block["n_days"], 0)
        self.assertEqual(block["active_kcal_daily_avg"], 1000)
        self.assertEqual(block["basal_kcal_daily_avg"], 2000)

    def test_one_component_alone_still_reports_its_own_mean(self):
        rows = [_day(i, basal_energy_kcal=2100.0) for i in range(28)]
        block = energy_28d(rows, TODAY)
        self.assertEqual(block["basal_kcal_daily_avg"], 2100)
        self.assertIsNone(block["active_kcal_daily_avg"])
        self.assertIsNone(block["tdee_kcal_daily_avg"])


# ---------------------------------------------------------------------------
# energy_28d — the empty case
# ---------------------------------------------------------------------------

class EnergyEmptyCaseTests(unittest.TestCase):

    def test_no_energy_data_at_all_produces_no_block(self):
        rows = [_day(i, steps=8000, exercise_min=40.0) for i in range(28)]
        self.assertIsNone(energy_28d(rows, TODAY))

    def test_empty_health_series_produces_no_block(self):
        self.assertIsNone(energy_28d([], TODAY))
        self.assertIsNone(energy_28d(None, TODAY))

    def test_energy_only_outside_the_window_produces_no_block(self):
        rows = [_day(i, active_energy_kcal=1000.0, basal_energy_kcal=2000.0)
                for i in range(40, 60)]
        self.assertIsNone(energy_28d(rows, TODAY))

    def test_blank_and_unparseable_cells_read_as_absent(self):
        rows = [_day(i, active_energy_kcal="", basal_energy_kcal=None)
                for i in range(28)]
        self.assertIsNone(energy_28d(rows, TODAY))


# ---------------------------------------------------------------------------
# energy_28d — the trend pair (shared OLS helper, not a second regression)
# ---------------------------------------------------------------------------

class EnergyTrendTests(unittest.TestCase):

    def test_six_contract_keys_are_present_with_those_exact_names(self):
        block = energy_28d(_flat_energy(28), TODAY)
        for key in ("tdee_kcal_daily_avg", "active_kcal_daily_avg",
                    "basal_kcal_daily_avg", "n_days",
                    "tdee_trend_kcal_per_week", "basal_trend_kcal_per_week"):
            self.assertIn(key, block)

    def test_trend_blocks_carry_state_and_reason(self):
        block = energy_28d(_flat_energy(28), TODAY)
        for key in ("tdee_trend", "basal_trend"):
            self.assertIn("state", block[key])
            self.assertIn("reason", block[key])
            self.assertIn("note", block[key])
            self.assertIn("method", block[key])

    def test_a_flat_series_leaves_the_scalar_null_with_a_reason(self):
        """No slope means no rate — never 0.0 reported as a finding."""
        block = energy_28d(_flat_energy(28), TODAY)
        self.assertIsNone(block["tdee_trend_kcal_per_week"])
        self.assertEqual(block["tdee_trend"]["state"], "unresolved")
        self.assertEqual(block["tdee_trend"]["reason"], "ci_straddles_zero")

    def test_a_falling_basal_series_resolves_and_reports_a_negative_rate(self):
        """Basal falling during a cut is the adaptive-thermogenesis signal
        the stored split exists to expose, so it has to be resolvable."""
        rows = [
            _day(i, active_energy_kcal=1000.0,
                 basal_energy_kcal=2100.0 - 12.0 * (27 - i))
            for i in range(28)
        ]
        block = energy_28d(rows, TODAY)
        self.assertEqual(block["basal_trend"]["state"], "resolved")
        self.assertIsNotNone(block["basal_trend_kcal_per_week"])
        self.assertLess(block["basal_trend_kcal_per_week"], 0.0)
        self.assertEqual(block["basal_trend_kcal_per_week"],
                         block["basal_trend"]["kcal_per_week"])

    def test_too_few_days_reports_the_sample_size_not_a_slope(self):
        rows = _flat_energy(3, active=1000.0, basal=2000.0)
        block = energy_28d(rows, TODAY)
        self.assertIsNone(block["tdee_trend_kcal_per_week"])
        self.assertEqual(block["tdee_trend"]["reason"], "too_few_readings")

    def test_a_stale_series_says_so_rather_than_reporting_a_current_rate(self):
        rows = [
            _day(i, active_energy_kcal=1000.0 + 20.0 * i,
                 basal_energy_kcal=2000.0)
            for i in range(14, 28)
        ]
        block = energy_28d(rows, TODAY)
        self.assertIsNone(block["tdee_trend_kcal_per_week"])
        self.assertEqual(block["tdee_trend"]["reason"], "readings_stale")

    def test_the_two_channels_can_disagree_about_resolving(self):
        """Basal moves on a formula and TDEE on behaviour, so one channel
        resolving while the other does not is the normal case."""
        rows = [
            _day(i,
                 active_energy_kcal=1000.0 + (400.0 if i % 2 else -400.0),
                 basal_energy_kcal=2100.0 - 12.0 * (27 - i))
            for i in range(28)
        ]
        block = energy_28d(rows, TODAY)
        self.assertEqual(block["basal_trend"]["state"], "resolved")
        self.assertEqual(block["tdee_trend"]["state"], "unresolved")
        self.assertIsNone(block["tdee_trend_kcal_per_week"])


# ---------------------------------------------------------------------------
# daily_activity_28d — steps become the primary band basis
# ---------------------------------------------------------------------------

class StepsDailyAverageTests(unittest.TestCase):

    def test_steps_daily_avg_is_a_whole_number_over_reporting_days(self):
        rows = [_day(i, steps=8000 + (100 if i % 2 else -100))
                for i in range(28)]
        block = daily_activity_28d(rows, [], TODAY)
        self.assertEqual(block["steps_daily_avg"], 8000)
        self.assertIsInstance(block["steps_daily_avg"], int)

    def test_absent_step_column_leaves_the_key_null(self):
        rows = [_day(i, exercise_min=30.0) for i in range(28)]
        block = daily_activity_28d(rows, [], TODAY)
        self.assertIsNone(block["steps_daily_avg"])


class StepsBandBoundaryTests(unittest.TestCase):
    """The band edges are 7,000 and 10,000 steps/day, low side inclusive."""

    def _band(self, steps: float) -> dict:
        rows = [_day(i, steps=steps) for i in range(28)]
        return daily_activity_28d(rows, [], TODAY)

    def test_just_below_the_low_edge_is_low(self):
        block = self._band(STEPS_LOW_PER_DAY - 1)
        self.assertEqual(block["assessment"], "low")
        self.assertEqual(block["assessment_basis"], "steps")

    def test_exactly_the_low_edge_is_moderate(self):
        self.assertEqual(self._band(STEPS_LOW_PER_DAY)["assessment"],
                         "moderate")

    def test_just_below_the_high_edge_is_moderate(self):
        self.assertEqual(self._band(STEPS_HIGH_PER_DAY - 1)["assessment"],
                         "moderate")

    def test_exactly_the_high_edge_is_high(self):
        self.assertEqual(self._band(STEPS_HIGH_PER_DAY)["assessment"], "high")

    def test_well_above_the_high_edge_is_high(self):
        self.assertEqual(self._band(18000)["assessment"], "high")

    def test_zero_steps_is_low_not_null(self):
        block = self._band(0)
        self.assertEqual(block["assessment"], "low")
        self.assertEqual(block["assessment_basis"], "steps")


class StepsOverrideExerciseMinutesTests(unittest.TestCase):

    def test_steps_win_over_exercise_minutes_when_both_are_present(self):
        """A trained person can clear the exercise-minute bar on one hard
        hour and still be sedentary the other twenty-three. Steps are the
        signal that separates those, so they take precedence."""
        rows = [_day(i, steps=3000, exercise_min=60.0) for i in range(28)]
        block = daily_activity_28d(rows, [], TODAY)
        self.assertEqual(block["assessment"], "low")
        self.assertEqual(block["assessment_basis"], "steps")

    def test_exercise_minutes_remain_the_fallback_without_steps(self):
        rows = [_day(i, exercise_min=60.0) for i in range(28)]
        block = daily_activity_28d(rows, [], TODAY)
        self.assertEqual(block["assessment"], "high")
        self.assertEqual(block["assessment_basis"], "exercise_min")

    def test_walking_minutes_remain_the_last_fallback(self):
        sessions = [
            {"date": (TODAY - timedelta(days=i)).isoformat(),
             "apple_type": "Walking", "duration_min": 60.0,
             "distance_km": 5.0}
            for i in range(28)
        ]
        block = daily_activity_28d([_day(i) for i in range(28)], sessions,
                                   TODAY)
        self.assertEqual(block["assessment"], "high")
        self.assertEqual(block["assessment_basis"], "walking_minutes")

    def test_no_signal_at_all_leaves_the_band_null(self):
        block = daily_activity_28d([_day(i) for i in range(28)], [], TODAY)
        self.assertIsNone(block["assessment"])
        self.assertIsNone(block["assessment_basis"])

    def test_walking_context_fields_survive_the_change(self):
        sessions = [
            {"date": TODAY.isoformat(), "apple_type": "Walking",
             "duration_min": 10.0, "distance_km": 0.8, "incidental": True},
            {"date": TODAY.isoformat(), "apple_type": "Walking",
             "duration_min": 55.0, "distance_km": 4.5},
        ]
        rows = [_day(i, steps=12000) for i in range(28)]
        block = daily_activity_28d(rows, sessions, TODAY)
        self.assertEqual(block["walking_workouts_count"], 2)
        self.assertEqual(block["walking_minutes_28d"], 65.0)
        self.assertEqual(block["incidental_walks_count"], 1)


# ---------------------------------------------------------------------------
# nutrition_phase — binding deficit arithmetic
# ---------------------------------------------------------------------------

class PhaseDeficitArithmeticTests(unittest.TestCase):

    def test_half_kg_per_week_cut_at_7700_kcal_per_kg(self):
        """-0.5 kg/wk is -550 kcal/day; against 3,204 TDEE that is 2,654."""
        block = nutrition_phase_summary(_open_cut_phase(-0.5), [], TODAY,
                                        tdee_kcal=3204)
        energy = block["energy"]
        self.assertEqual(energy["tdee_kcal"], 3204)
        self.assertEqual(energy["target_deficit_kcal"], 550)
        self.assertEqual(energy["implied_intake_kcal"], 2654)
        self.assertEqual(energy["basis"], "measured_28d")

    def test_implied_intake_is_always_tdee_minus_deficit(self):
        block = nutrition_phase_summary(_open_cut_phase(-0.5), [], TODAY,
                                        tdee_kcal=3204)
        energy = block["energy"]
        self.assertEqual(energy["implied_intake_kcal"],
                         energy["tdee_kcal"] - energy["target_deficit_kcal"])

    def test_a_bulk_gives_a_negative_deficit_and_intake_above_tdee(self):
        phases = [{
            "start_date": (TODAY - timedelta(days=30)).isoformat(),
            "end_date": None,
            "phase_type": "bulk",
            "target_rate_kg_per_wk": 0.25,
        }]
        energy = nutrition_phase_summary(phases, [], TODAY,
                                         tdee_kcal=3000)["energy"]
        self.assertEqual(energy["target_deficit_kcal"], -275)
        self.assertEqual(energy["implied_intake_kcal"], 3275)

    def test_maintain_at_zero_rate_puts_intake_at_tdee(self):
        phases = [{
            "start_date": (TODAY - timedelta(days=30)).isoformat(),
            "end_date": None,
            "phase_type": "maintain",
        }]
        energy = nutrition_phase_summary(phases, [], TODAY,
                                         tdee_kcal=2800)["energy"]
        self.assertEqual(energy["target_deficit_kcal"], 0)
        self.assertEqual(energy["implied_intake_kcal"], 2800)

    def test_the_default_cut_target_is_used_when_the_phase_omits_one(self):
        phases = [{
            "start_date": (TODAY - timedelta(days=30)).isoformat(),
            "end_date": None,
            "phase_type": "cut",
        }]
        energy = nutrition_phase_summary(phases, [], TODAY,
                                         tdee_kcal=3204)["energy"]
        self.assertEqual(energy["target_deficit_kcal"], 550)


class PhaseEnergyGuardTests(unittest.TestCase):

    def test_absent_entirely_without_a_measured_tdee(self):
        """No TDEE means no arithmetic — and no nulls standing in for it."""
        block = nutrition_phase_summary(_open_cut_phase(), [], TODAY)
        self.assertIsNone(block["energy"])

    def test_absent_when_the_phase_has_no_resolvable_target_rate(self):
        phases = [{
            "start_date": (TODAY - timedelta(days=30)).isoformat(),
            "end_date": None,
            "phase_type": "recomp",
        }]
        block = nutrition_phase_summary(phases, [], TODAY, tdee_kcal=3204)
        self.assertIsNone(block["energy"])

    def test_the_block_names_intake_as_untracked(self):
        """Intake is not recorded anywhere; the block must make that
        impossible to misread as an observation of what was eaten."""
        energy = nutrition_phase_summary(_open_cut_phase(), [], TODAY,
                                         tdee_kcal=3204)["energy"]
        self.assertEqual(energy["intake_tracking_status"], "not_tracked")
        caveat = energy["intake_caveat"].lower()
        self.assertIn("not tracked", caveat)
        self.assertIn("adherence", caveat)

    def test_no_open_phase_still_returns_no_block_at_all(self):
        phases = [{
            "start_date": (TODAY - timedelta(days=90)).isoformat(),
            "end_date": (TODAY - timedelta(days=30)).isoformat(),
            "phase_type": "cut",
        }]
        self.assertIsNone(
            nutrition_phase_summary(phases, [], TODAY, tdee_kcal=3204))


if __name__ == "__main__":
    unittest.main()
