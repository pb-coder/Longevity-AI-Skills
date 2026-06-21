"""Tests for Cluster-C bugs in nutrition_phase.py.

[C4]  regressing status falls through to "continue" instead of the correct
      action hint (add_calories for bulk, slow_intake for cut).
[C13] _coach_action_hint triggers end_now at >= 12 weeks, contradicting the
      docstring which documents the off-ramp at >= 8 weeks.

All data is synthetic — no real personal data.
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from workout_coach.lib.nutrition_phase import (
    _coach_action_hint,
    nutrition_phase_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bw_series(start_d: date, n_days: int, start_kg: float,
                    delta_kg_per_day: float) -> list[dict]:
    """Produce a synthetic bodyweight series starting at start_d."""
    return [
        {"date": (start_d + timedelta(days=i)).isoformat(),
         "kg": round(start_kg + delta_kg_per_day * i, 2)}
        for i in range(n_days)
    ]


def _open_phase(phase_type: str, start_date: date,
                target_rate: float | None = None) -> dict:
    return {
        "phase_type": phase_type,
        "start_date": start_date.isoformat(),
        "end_date": None,
        "target_rate_kg_per_wk": target_rate,
    }


# ---------------------------------------------------------------------------
# [C4] regressing status must NOT fall through to "continue"
# ---------------------------------------------------------------------------

class TestC4RegressingActionHint(unittest.TestCase):
    """[C4] When status == 'regressing' and no stop signals, the coach must
    return an actionable hint, never "continue"."""

    def test_bulk_regressing_no_stop_signals_returns_add_calories(self) -> None:
        """Bulk + regressing (losing weight) with zero stop signals should
        return 'add_calories', not the silent 'continue' fall-through."""
        hint = _coach_action_hint(
            status="regressing",
            triggered=[],
            weeks_in_phase=3.0,
            phase_type="bulk",
        )
        self.assertEqual(
            hint, "add_calories",
            f"Bulk + regressing should return 'add_calories', got '{hint}'",
        )

    def test_cut_regressing_no_stop_signals_returns_slow_intake(self) -> None:
        """Cut + regressing (gaining weight) with zero stop signals should
        return 'slow_intake', not the silent 'continue' fall-through."""
        hint = _coach_action_hint(
            status="regressing",
            triggered=[],
            weeks_in_phase=3.0,
            phase_type="cut",
        )
        self.assertEqual(
            hint, "slow_intake",
            f"Cut + regressing should return 'slow_intake', got '{hint}'",
        )

    def test_insufficient_data_still_returns_continue(self) -> None:
        """A brand-new phase (insufficient_data) must still return 'continue'.
        This guards against the fix accidentally breaking the existing behaviour."""
        hint = _coach_action_hint(
            status="insufficient_data",
            triggered=[],
            weeks_in_phase=0.5,
            phase_type="bulk",
        )
        self.assertEqual(hint, "continue")

    def test_on_track_bulk_still_returns_continue(self) -> None:
        """on_track with no stop signals should remain 'continue'."""
        hint = _coach_action_hint(
            status="on_track",
            triggered=[],
            weeks_in_phase=3.0,
            phase_type="bulk",
        )
        self.assertEqual(hint, "continue")

    def test_bulk_regressing_via_summary(self) -> None:
        """End-to-end: a bulk phase where bodyweight is steadily falling
        should surface coach_action_hint == 'add_calories'."""
        today = date(2026, 1, 22)
        start = today - timedelta(days=21)   # 3 weeks in — enough history
        # -0.3 kg/day => regressing on a bulk
        bw = _make_bw_series(start, 22, start_kg=80.0, delta_kg_per_day=-0.03)
        phases = [_open_phase("bulk", start, target_rate=0.25)]
        result = nutrition_phase_summary(phases, bw, today)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "regressing",
                         "Expected status 'regressing' for a falling-weight bulk")
        self.assertEqual(
            result["coach_action_hint"], "add_calories",
            f"Expected 'add_calories' for bulk+regressing, got "
            f"'{result['coach_action_hint']}'",
        )

    def test_cut_regressing_via_summary(self) -> None:
        """End-to-end: a cut phase where bodyweight is rising should surface
        coach_action_hint == 'slow_intake'."""
        today = date(2026, 1, 22)
        start = today - timedelta(days=21)
        # +0.04 kg/day => gaining weight while on a cut => regressing
        bw = _make_bw_series(start, 22, start_kg=80.0, delta_kg_per_day=0.04)
        phases = [_open_phase("cut", start, target_rate=-0.5)]
        result = nutrition_phase_summary(phases, bw, today)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "regressing",
                         "Expected status 'regressing' for a gaining-weight cut")
        self.assertEqual(
            result["coach_action_hint"], "slow_intake",
            f"Expected 'slow_intake' for cut+regressing, got "
            f"'{result['coach_action_hint']}'",
        )


# ---------------------------------------------------------------------------
# [C13] end_now off-ramp boundary — must fire at >= 8 weeks, not >= 12
# ---------------------------------------------------------------------------

class TestC13OffRampWeekBoundary(unittest.TestCase):
    """[C13] The docstring commits to 8 weeks for end_now on a single hard
    stop signal.  The code was using 12.  Verify the boundary is 8."""

    def _hint_with_one_signal(self, weeks: float, phase_type: str = "bulk") -> str:
        return _coach_action_hint(
            status="too_fast",
            triggered=["one hard stop signal"],
            weeks_in_phase=weeks,
            phase_type=phase_type,
        )

    def test_exactly_8_weeks_with_one_signal_returns_end_now(self) -> None:
        """At the 8-week boundary, a single hard stop signal must trigger
        end_now, not consider_ending."""
        hint = self._hint_with_one_signal(weeks=8.0)
        self.assertEqual(
            hint, "end_now",
            f"Expected 'end_now' at 8 weeks, got '{hint}'",
        )

    def test_just_under_8_weeks_with_one_signal_returns_consider_ending(self) -> None:
        """Just below 8 weeks a single stop signal should remain
        'consider_ending', not yet trigger end_now."""
        hint = self._hint_with_one_signal(weeks=7.9)
        self.assertEqual(
            hint, "consider_ending",
            f"Expected 'consider_ending' at 7.9 weeks, got '{hint}'",
        )

    def test_well_over_8_weeks_with_one_signal_returns_end_now(self) -> None:
        """A phase that is 10 weeks in with one stop signal should also fire
        end_now (regression guard for values between 8 and the old 12)."""
        hint = self._hint_with_one_signal(weeks=10.0)
        self.assertEqual(
            hint, "end_now",
            f"Expected 'end_now' at 10 weeks, got '{hint}'",
        )

    def test_two_signals_always_end_now_regardless_of_weeks(self) -> None:
        """Multiple stop signals always return end_now regardless of weeks.
        This behavior must not change."""
        hint = _coach_action_hint(
            status="too_fast",
            triggered=["signal A", "signal B"],
            weeks_in_phase=1.0,
            phase_type="bulk",
        )
        self.assertEqual(hint, "end_now")


if __name__ == "__main__":
    unittest.main()
