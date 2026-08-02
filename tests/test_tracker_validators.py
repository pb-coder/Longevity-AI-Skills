from __future__ import annotations

import unittest

from tracker.validation import validate_tracker_json


class TrackerJsonValidatorTests(unittest.TestCase):
    def valid_tracker(self) -> dict:
        return {
            "today": "2026-05-28",
            "recovery": {"score": 7.0, "confidence": "high", "drivers": []},
            "training_load": {"ctl": 12.0, "atl": 11.0, "tsb": 1.0},
            "session_recommendation": {
                "tier": "D",
                "label": "green",
                "headline": "Train as planned.",
                "substitute": {"kind": "normal_strength"},
                "rationale": [],
                "override_allowed": True,
                "override_message": "",
            },
        }

    def test_unknown_top_level_key_is_warning(self) -> None:
        payload = self.valid_tracker()
        payload["new_field"] = True
        errors, warnings = validate_tracker_json(payload)
        self.assertEqual(errors, [])
        self.assertIn("tracker.new_field", "\n".join(warnings))

    def test_unknown_recovery_key_is_warning(self) -> None:
        payload = self.valid_tracker()
        payload["recovery"]["new_signal"] = 1
        errors, warnings = validate_tracker_json(payload)
        self.assertEqual(errors, [])
        self.assertIn("tracker.recovery.new_signal", "\n".join(warnings))

    def test_missing_today_is_error(self) -> None:
        payload = self.valid_tracker()
        payload.pop("today")
        errors, warnings = validate_tracker_json(payload)
        self.assertIn("tracker.today must be a YYYY-MM-DD string", errors)
        self.assertEqual(warnings, [])

    def test_every_key_read_tracker_emits_is_declared(self) -> None:
        """An undeclared key prints ``not declared in TrackerJSON`` on every
        single run. ``bodyweight_trend`` shipped that way; the point of
        this test is that the next one cannot."""
        payload = self.valid_tracker()
        payload.update({
            "bodyweight_trend": {"state": "unresolved",
                                 "reason": "ci_straddles_zero"},
            "adherence": {"completion_rate": 0.37},
            "dose_staleness": {"unchanged_pct": 0.3},
            "block": {"boundary_due": False},
            "rotation_candidates": [{"exercise": "Barbell Row"}],
            "core_week_spec": {"min_distinct_exercises_per_week": 3},
            "arm_week_spec": {"min_direct_sets_per_week": 6},
            "muscle_priority_tiers": {"core": "emphasis"},
            "muscle_volume_targets": {"core": {"tier": "emphasis"}},
            "volume_landmark_unit": "fractional",
            "synergist_credit_offset": {"biceps": 3},
        })
        errors, warnings = validate_tracker_json(payload)
        self.assertEqual(errors, [])
        self.assertEqual(
            [w for w in warnings if "not declared" in w], [],
            "read_tracker emits these; the contract must declare them")

    def test_training_load_by_modality_is_declared(self) -> None:
        # read_tracker emits this and the gate consumes it; it must not warn.
        payload = self.valid_tracker()
        payload["training_load_by_modality"] = {
            "all": {"ctl": 12.0, "atl": 11.0, "tsb": 1.0},
            "strength": {"ctl": 6.0, "atl": 5.0, "tsb": 1.0},
            "cardio": {"ctl": 6.0, "atl": 6.0, "tsb": 0.0},
        }
        errors, warnings = validate_tracker_json(payload)
        self.assertEqual(errors, [])
        self.assertNotIn("training_load_by_modality", "\n".join(warnings))


if __name__ == "__main__":
    unittest.main()
