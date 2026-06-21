"""Cluster B — Recovery gate corroboration fixes.

B2:  Tier B reactive-deload must not over-fire on a single cardio
     week-over-week spike. A >=60% WoW jump off a small base while the
     athlete is strength-fresh is noise, not accumulated strength fatigue.
     The spike must be corroborated (negative strength freshness AND a
     meaningful absolute acute load) before it fires — mirroring the
     corroboration discipline already applied to the soft Tier-C triggers.

B11: Tier A illness RHR-sustained-elevation must use a baseline that
     EXCLUDES the recent elevated run. The old 14-day mean baseline
     included the elevated days, dragging the threshold up so a real
     multi-day RHR elevation over a stable baseline failed to trip Tier A.
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from workout_coach.lib.health import (
    compute_session_recommendation,
    _rhr_sustained_elevation_days,
)


def recommendation(**overrides):
    args = {
        "recovery": {"score": 7.2, "drivers": []},
        "training_load": {"tsb": 0},
        "acwr": {},
        "weekly_volume": {},
        "sleep_regularity": {},
        "sleep_summary": {},
        "estimated_1rm": {},
        "hr_at_volume_divergence": {},
        "deloads": [],
        "auto_deload_candidates": [],
        "health_all": [],
        "today_d": date(2026, 5, 28),
        "estimated_max_hr": 190,
    }
    args.update(overrides)
    return compute_session_recommendation(**args)


class TierBWowSpikeCorroborationTests(unittest.TestCase):
    """B2 — the WoW spike trigger requires corroboration."""

    def test_big_wow_spike_off_small_base_while_fresh_is_not_tier_b(self) -> None:
        # The field failure: a ~19.7-min HIIT against a near-zero prior week
        # produces a huge WoW percent, but strength freshness is positive and
        # the absolute acute load is tiny. This must NOT be a reactive deload.
        rec = recommendation(
            acwr={"wow_change_pct": 275.0, "acute_7d": 40.0, "prior_week": 11.0},
            training_load={"tsb": 3.0},      # strength-fresh
            recovery={"score": 7.0, "drivers": []},
        )
        self.assertNotEqual(rec["tier"], "B")

    def test_real_spike_with_fatigue_and_high_load_still_tier_b(self) -> None:
        # A genuine ramp: large WoW spike, negative strength freshness AND a
        # meaningful absolute acute load. The high-fatigue protection stays
        # intact — this still fires Tier B.
        rec = recommendation(
            acwr={"wow_change_pct": 80.0, "acute_7d": 420.0, "prior_week": 233.0},
            training_load={"tsb": -6.0},     # carrying real strength load
            recovery={"score": 5.0, "drivers": []},
        )
        self.assertEqual(rec["tier"], "B")
        signals = [r.get("signal") for r in rec.get("rationale", [])]
        self.assertIn("wow_change_pct", signals)

    def test_wow_spike_fresh_but_high_absolute_load_is_not_tier_b(self) -> None:
        # Corroboration is conjunctive: a high absolute acute load alone, while
        # strength-fresh, is not strength fatigue. Must not fire on the spike.
        rec = recommendation(
            acwr={"wow_change_pct": 90.0, "acute_7d": 500.0, "prior_week": 263.0},
            training_load={"tsb": 4.0},      # fresh
            recovery={"score": 7.0, "drivers": []},
        )
        self.assertNotEqual(rec["tier"], "B")


class TierARhrBaselineExclusionTests(unittest.TestCase):
    """B11 — RHR sustained-elevation baseline excludes the recent run."""

    @staticmethod
    def _stable_then_elevated(today: date, *, stable_bpm: float,
                              elevated_bpm: float, streak_len: int,
                              history_days: int = 60) -> list[dict]:
        health: list[dict] = []
        for off in range(history_days, streak_len - 1, -1):
            health.append({"date": (today - timedelta(days=off)).isoformat(),
                           "resting_hr": stable_bpm})
        for off in range(streak_len - 1, -1, -1):
            health.append({"date": (today - timedelta(days=off)).isoformat(),
                           "resting_hr": elevated_bpm})
        return health

    def test_sustained_elevation_over_stable_baseline_counts_full_streak(self) -> None:
        # Stable 50 bpm for weeks, then 5 days at 62 bpm (+12 over the true
        # baseline). A baseline that includes the elevated run drags its own
        # threshold up (mean > 52, threshold > 62) so 62 < threshold and the
        # streak reads as 0 — the shipped bug. A 5-day run defeats the
        # contaminated mean at *any* single window length (14d or 28d). With
        # the run excluded from the baseline the threshold is 60 and all 5 days
        # count. This pins the run-exclusion root cause, not the window length.
        today = date(2026, 5, 28)
        health = self._stable_then_elevated(
            today, stable_bpm=50.0, elevated_bpm=62.0, streak_len=5)
        streak = _rhr_sustained_elevation_days(health, today, 10.0)
        self.assertEqual(streak, 5)

    def test_sustained_elevation_trips_tier_a(self) -> None:
        # End-to-end: the same elevation now fires Tier A (rest), which it did
        # not before the baseline fix.
        today = date(2026, 5, 28)
        health = self._stable_then_elevated(
            today, stable_bpm=50.0, elevated_bpm=62.0, streak_len=3)
        rec = recommendation(today_d=today, health_all=health)
        self.assertEqual(rec["tier"], "A")
        signals = [r.get("signal") for r in rec.get("rationale", [])]
        self.assertIn("rhr_sustained_days", signals)

    def test_stable_rhr_has_no_streak(self) -> None:
        # No elevation at all -> streak 0 (no false positive from the new
        # baseline windowing).
        today = date(2026, 5, 28)
        health = [
            {"date": (today - timedelta(days=off)).isoformat(), "resting_hr": 50.0}
            for off in range(60, -1, -1)
        ]
        self.assertEqual(_rhr_sustained_elevation_days(health, today, 10.0), 0)

    def test_single_spike_day_is_streak_one(self) -> None:
        # A one-off elevated day is a streak of 1, not a sustained elevation.
        today = date(2026, 5, 28)
        health = [
            {"date": (today - timedelta(days=off)).isoformat(), "resting_hr": 50.0}
            for off in range(60, 0, -1)
        ]
        health.append({"date": today.isoformat(), "resting_hr": 62.0})
        self.assertEqual(_rhr_sustained_elevation_days(health, today, 10.0), 1)


if __name__ == "__main__":
    unittest.main()
