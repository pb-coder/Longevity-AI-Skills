from __future__ import annotations

import unittest
from datetime import date


from tracker.contracts import SessionRecommendation
from workout_coach.lib.health import compute_session_recommendation


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


if __name__ == "__main__":
    unittest.main()
