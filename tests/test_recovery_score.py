from __future__ import annotations

import unittest
from datetime import date, timedelta

from workout_coach.lib.health_recovery import recovery_score

TODAY = date(2026, 6, 14)
CAPS = {"hrv": True, "sleep_stages": True, "wrist_temp": True}


def _d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _build():
    """Health series where every signal sits at personal baseline EXCEPT a
    single, extreme, recent HR-Recovery reading (n_recent=1)."""
    rows = []
    # resting_hr + sleep_total: 14 days at baseline (sufficient recent sample).
    for i in range(14):
        rows.append({"date": _d(i), "resting_hr": 60.0, "sleep_total_h": 7.0})
    # hrv: 60-day baseline at 50, recent 7 at 50 (sufficient, at baseline).
    for i in range(60):
        rows.append({"date": _d(i), "hrv_sdnn": 50.0})
    # hr_recovery: tight baseline of 10 readings at 35 (days 6..27), plus ONE
    # extreme recent reading at 20 (would clamp to -2sigma if counted).
    for i in range(6, 28):
        if i % 2 == 0:
            rows.append({"date": _d(i), "hr_recovery_1min": 35.0})
    rows.append({"date": _d(1), "hr_recovery_1min": 20.0})
    return rows


class RecoverySampleSufficiencyTests(unittest.TestCase):
    def test_single_recent_reading_is_excluded_not_scored(self) -> None:
        res = recovery_score(_build(), TODAY, CAPS)
        hrr = next(d for d in res["drivers"] if d["metric"] == "hr_recovery_1min")
        # The lone reading is surfaced but carries zero weight and is flagged.
        self.assertTrue(hrr.get("under_sampled"))
        self.assertEqual(hrr["weight"], 0.0)
        self.assertEqual(hrr["n_recent"], 1)
        # Score reflects the at-baseline signals (~5.0), NOT dragged toward 0
        # by the single clamped HR-Recovery point.
        self.assertGreaterEqual(res["score"], 4.7)
        # Confidence drops one band because a high-weight signal was excluded.
        self.assertIn(res["confidence"], {"medium", "low"})

    def test_sufficient_recent_reading_still_counts(self) -> None:
        rows = _build()
        # Add two more recent HR-Recovery readings at baseline so n_recent=3.
        rows.append({"date": _d(2), "hr_recovery_1min": 35.0})
        rows.append({"date": _d(3), "hr_recovery_1min": 35.0})
        res = recovery_score(rows, TODAY, CAPS)
        hrr = next(d for d in res["drivers"] if d["metric"] == "hr_recovery_1min")
        self.assertFalse(hrr.get("under_sampled", False))
        self.assertGreater(hrr["weight"], 0.0)
        self.assertGreaterEqual(hrr["n_recent"], 3)


if __name__ == "__main__":
    unittest.main()


_RECOVERY_WITH_RHR = {
    "drivers": [{"metric": "resting_hr", "component_score": 6.0}],
}


class HrvCapabilityCopyTests(unittest.TestCase):
    """A source without HRV must not be asked to produce HRV.

    Health Export Kit carries no all-day HRV. Before this, the dashboard
    rendered "Needs ~7 consecutive nights of HRV (SDNN)" on the same page as
    the copy explaining that HRV is gone for good, and the reactive-deload
    prescription told the user to wait for HRV to recover.
    """

    def test_hrv_is_not_listed_as_a_missing_input_when_the_source_lacks_it(self) -> None:
        from workout_coach.lib.health_longevity import compute_longevity_score
        got = compute_longevity_score(
            vo2_percentile=None, recovery=_RECOVERY_WITH_RHR, sleep_summary=None,
            sleep_regularity=None, acwr=None, cardio_zones=None,
            movement_consistency=None, bodyweight_trend_kg_per_week=None,
            estimated_1rm=None,
            capabilities={"hrv": False, "sleep_regularity": True},
        )
        names = [m.get("name") for m in (got or {}).get("missing_inputs") or []]
        self.assertNotIn("hrv_trend", names)

    def test_hrv_is_still_listed_when_the_source_provides_it(self) -> None:
        from workout_coach.lib.health_longevity import compute_longevity_score
        got = compute_longevity_score(
            vo2_percentile=None, recovery=_RECOVERY_WITH_RHR, sleep_summary=None,
            sleep_regularity=None, acwr=None, cardio_zones=None,
            movement_consistency=None, bodyweight_trend_kg_per_week=None,
            estimated_1rm=None,
            capabilities={"hrv": True, "sleep_regularity": True},
        )
        names = [m.get("name") for m in (got or {}).get("missing_inputs") or []]
        self.assertIn("hrv_trend", names)

    def test_no_prescription_tells_the_user_to_wait_for_hrv(self) -> None:
        """The ``notes`` strings are prescriptions the user reads and acts on.

        Rationale strings elsewhere in the module may name HRV: those are
        built from an HRV z-score and only appear when one exists. A
        prescription is different — it renders whatever the source can do.
        """
        import re
        from pathlib import Path
        src = Path(__file__).resolve().parents[1] / "workout-coach" / "lib" / "health_session_rec.py"
        notes = re.findall(r'"notes":\s*"([^"]*)"', src.read_text(encoding="utf-8"))
        self.assertGreater(len(notes), 2, "expected several prescriptions to check")
        for n in notes:
            self.assertNotIn("HRV", n, f"prescription waits on HRV: {n!r}")
