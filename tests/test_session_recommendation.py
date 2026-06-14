from __future__ import annotations

import unittest
from datetime import date


from tracker.contracts import SessionRecommendation
from workout_coach.lib.health import compute_session_recommendation
from workout_coach.lib.health_session_rec import (
    _genuinely_stalled_lifts,
    _muscles_over_mrv,
)


def _genuine_stall():
    """A lift flat at/near its best and not progressing — a true plateau."""
    return {"stalled_sessions": 3, "current_e1rm_kg": 100.0,
            "best_e1rm_kg": 100.0, "slope_kg_per_4w": 0.0}


def _comeback_lift():
    """Flat but well below best — being re-built after a layoff, not a stall."""
    return {"stalled_sessions": 3, "current_e1rm_kg": 60.0,
            "best_e1rm_kg": 100.0, "slope_kg_per_4w": 0.0}


def _rising_hr(*muscles):
    return {m: {"hint": "rising HR at constant volume — fatigue or under-recovery"}
            for m in muscles}


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


class SessionRecommendationTests(unittest.TestCase):
    def test_green_tier_when_no_gate_fires(self) -> None:
        rec = recommendation()
        self.assertEqual(rec["tier"], "D")
        self.assertEqual(rec["headline"], "Train as planned.")

    def test_recommendation_keys_match_declared_contract(self) -> None:
        rec = recommendation()
        declared = set(SessionRecommendation.__optional_keys__)
        self.assertTrue(set(rec.keys()).issubset(declared), set(rec.keys()) - declared)

    def test_high_fatigue_triggers_zone_2_reactive_deload(self) -> None:
        rec = recommendation(training_load={"tsb": -16})
        self.assertEqual(rec["tier"], "B")
        self.assertEqual(rec["label"], "reactive_deload")
        self.assertEqual(rec["substitute"]["kind"], "zone_2")

    def test_tier_c_includes_expected_rebound_slot(self) -> None:
        rec = recommendation(recovery={
            "score": 7.2,
            "drivers": [{"metric": "hrv_sdnn", "z": -0.5}],
        })
        self.assertEqual(rec["tier"], "C")
        self.assertEqual(rec["expected_rebound_by_session"], 1)
        self.assertIn("workout 1", rec["override_message"])

    def test_tier_c_recent_deload_extends_modification_window(self) -> None:
        rec = recommendation(
            recovery={
                "score": 7.2,
                "drivers": [{"metric": "hrv_sdnn", "z": -0.5}],
            },
            deloads=["2026-05-25"],
        )
        self.assertEqual(rec["tier"], "C")
        self.assertEqual(rec["expected_rebound_by_session"], 2)

    def test_over_recovered_triggers_taper_warning(self) -> None:
        rec = recommendation(training_load={"tsb": 16})
        self.assertEqual(rec["tier"], "E")
        self.assertEqual(rec["label"], "over_recovered")

    def test_recovery_between_tier_c_and_green_holds_load(self) -> None:
        rec = recommendation(recovery={"score": 5.2, "drivers": []})
        self.assertEqual(rec["tier"], "C")
        self.assertEqual(rec["label"], "hold_load")
        self.assertIn("no PR", rec["headline"])

    def test_tier_d_recovery_floor_is_5_5(self) -> None:
        below = recommendation(recovery={"score": 5.49, "drivers": []})
        at_floor = recommendation(recovery={"score": 5.5, "drivers": []})

        self.assertEqual(below["tier"], "C")
        self.assertEqual(at_floor["tier"], "D")

    def test_mrv_gate_uses_current_sets_per_week(self) -> None:
        self.assertEqual(
            _muscles_over_mrv({
                "window_days": 28,
                "current": {"chest": 24.0},
                "landmarks": {"chest": {"mrv": 22}},
            }),
            ["chest"],
        )

    # ---- Regression net: the gate must be able to return to green ----

    def test_flat_isolations_with_green_recovery_not_deload(self) -> None:
        # Returning trainee: flat-at-ceiling lifts + green recovery + balanced freshness.
        e1rm = {f"L{i}": _genuine_stall() for i in range(4)}
        rec = recommendation(
            estimated_1rm=e1rm,
            recovery={"score": 6.5, "drivers": []},
            training_load={"tsb": 1.5},
        )
        self.assertNotEqual(rec["tier"], "B")

    def test_genuine_stall_with_fatigue_triggers_deload(self) -> None:
        # The legit Tuchscherer path stays alive: ceiling-stall + real fatigue.
        e1rm = {f"L{i}": _genuine_stall() for i in range(4)}
        rec = recommendation(
            estimated_1rm=e1rm,
            recovery={"score": 4.0, "drivers": []},
            training_load={"tsb": -2},
        )
        self.assertEqual(rec["tier"], "B")
        self.assertEqual(rec["label"], "reactive_deload")
        self.assertEqual(rec["substitute"]["kind"], "reactive_deload_week")

    def test_comeback_lifts_excluded_from_stall_count(self) -> None:
        self.assertEqual(
            _genuinely_stalled_lifts({f"L{i}": _comeback_lift() for i in range(4)}),
            0,
        )
        self.assertEqual(
            _genuinely_stalled_lifts({f"G{i}": _genuine_stall() for i in range(4)}),
            4,
        )

    def test_hr_creep_during_bulk_not_downgrade(self) -> None:
        # Bulking athlete: systemic HR creep on a bulk is a confounder, not fatigue.
        hv = _rising_hr("chest", "triceps", "side_delts")
        hv["systemic_session_hr"] = {
            "hint": "session HR rose across many muscles — check bodyweight, "
                    "deload boundary, heat, or generic fatigue"}
        rec = recommendation(
            hr_at_volume_divergence=hv,
            recovery={"score": None, "drivers": []},
            training_load={"tsb": 6},
            bodyweight_trend=0.25,
        )
        self.assertNotEqual(rec["tier"], "C")

    def test_over_recovered_dominates_hr_creep(self) -> None:
        rec = recommendation(
            hr_at_volume_divergence=_rising_hr("chest", "triceps"),
            recovery={"score": 7.0, "drivers": []},
            training_load={"tsb": 13},
        )
        self.assertIn(rec["tier"], {"D", "E"})

    def test_recovery_none_high_tsb_returns_green(self) -> None:
        rec = recommendation(
            recovery={"score": None, "drivers": []},
            training_load={"tsb": 6},
        )
        self.assertEqual(rec["tier"], "D")
        self.assertTrue(
            any(r.get("signal") == "recovery_unavailable"
                for r in rec.get("rationale", [])))

    def test_favorable_rhr_does_not_downgrade(self) -> None:
        # rhr_z is inverted: +0.75 means RHR is BELOW baseline (good). A good
        # RHR must not trip the Tier C "RHR elevated" downgrade.
        rec = recommendation(
            recovery={"score": 6.5,
                      "drivers": [{"metric": "resting_hr", "z": 0.75}]},
            training_load={"tsb": 1.5},
        )
        self.assertEqual(rec["tier"], "D")

    def test_elevated_rhr_still_downgrades(self) -> None:
        # The legit case: RHR elevated above baseline (negative inverted z).
        rec = recommendation(
            recovery={"score": 6.5,
                      "drivers": [{"metric": "resting_hr", "z": -0.75}]},
            training_load={"tsb": 1.5},
        )
        self.assertEqual(rec["tier"], "C")

    def test_exit_ramp_clears_served_deload(self) -> None:
        # Recent deload + rebounded → a stale auto-candidate must not re-loop.
        rec = recommendation(
            recovery={"score": 6.5, "drivers": [{"metric": "hrv_sdnn", "z": 0.0}]},
            training_load={"tsb": 0},
            deloads=["2026-05-25"],
            auto_deload_candidates=["2026-05-26"],
            today_d=date(2026, 5, 28),
        )
        self.assertNotEqual(rec["tier"], "B")


if __name__ == "__main__":
    unittest.main()
