"""Simultaneous recovery signals keep tier and substitute precedence."""
from datetime import date
import unittest

from workout_coach.lib.health_session_rec import compute_session_recommendation


def recommendation(**changes):
    inputs = dict(
        recovery={"score": 7, "drivers": []}, training_load={"tsb": 0},
        acwr=None, weekly_volume=None, sleep_regularity=None,
        sleep_summary=None, estimated_1rm=None, hr_at_volume_divergence=None,
        deloads=None, auto_deload_candidates=None, health_all=[],
        today_d=date(2026, 5, 28), estimated_max_hr=190,
    )
    return compute_session_recommendation(**(inputs | changes))


class RecoveryGatePriorityTests(unittest.TestCase):
    def test_acute_rest_takes_precedence_over_fatigue_and_sleep(self):
        rec = recommendation(
            recovery={"score": 1, "drivers": [
                {"metric": "hrv_sdnn", "z": -2},
                {"metric": "resting_hr", "z": -2},
            ]}, training_load={"tsb": -20},
            sleep_summary={"means_h": {"total": 3}},
        )
        self.assertEqual(rec["tier"], "A")
        self.assertEqual([r["signal"] for r in rec["rationale"]], ["recovery_crash"])
        self.assertEqual(rec["load_policy"]["policy"], "reduce")

    def test_mrv_breach_overrides_an_earlier_zone_two_substitute(self):
        volume = {"current": {m: 30 for m in ("chest", "back", "quads")},
                  "landmarks": {m: {"mrv": 20} for m in ("chest", "back", "quads")}}
        rec = recommendation(training_load={"tsb": -20}, weekly_volume=volume)
        self.assertEqual(rec["tier"], "B")
        self.assertEqual(rec["substitute"]["kind"], "reactive_deload_week")
        self.assertEqual([r["signal"] for r in rec["rationale"]], ["tsb", "muscles_over_mrv"])

    def test_later_non_mrv_trigger_keeps_the_first_substitute(self):
        rec = recommendation(training_load={"tsb": -20},
                             auto_deload_candidates=["2026-05-27"])
        self.assertEqual(rec["tier"], "B")
        self.assertEqual(rec["substitute"]["kind"], "zone_2")
        self.assertEqual([r["signal"] for r in rec["rationale"]], ["tsb", "auto_deload_candidate"])

    def test_downgrade_collects_multiple_signals_in_order(self):
        rec = recommendation(recovery={"score": 3.5, "drivers": []},
                             sleep_summary={"means_h": {"total": 3}},
                             sleep_regularity={"sri": 30})
        self.assertEqual(rec["tier"], "C")
        self.assertEqual([r["signal"] for r in rec["rationale"]],
                         ["recovery_score", "sleep_7d_mean_h", "sleep_regularity_index"])


if __name__ == "__main__":
    unittest.main()
