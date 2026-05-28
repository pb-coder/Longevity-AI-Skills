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


if __name__ == "__main__":
    unittest.main()
