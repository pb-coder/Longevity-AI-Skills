from __future__ import annotations

import unittest
from datetime import date

from workout_coach.lib import sessions
from workout_coach.lib.nutrition_phase import nutrition_phase_summary
from workout_coach.lib.sleep import sleep_summary
from workout_coach.lib.swim import swim_summary
from workout_coach.lib.thermal import thermal_summary


class BehaviorCaveatTests(unittest.TestCase):
    def test_steam_does_not_count_toward_dry_hsp_band(self) -> None:
        out = thermal_summary(
            [
                {"date": "2026-06-01", "heat_type": "steam", "heat_total_min": 30, "heat_temp_c": 45},
                {"date": "2026-06-02", "heat_type": "dry", "heat_total_min": 20, "heat_temp_c": 85},
            ],
            date(2026, 6, 3),
        )

        heat = out["heat"]
        self.assertEqual(heat["minutes_above_hsp_threshold_per_week"], 5.0)
        self.assertEqual(heat["steam_minutes_per_week"], 7.5)
        self.assertIn("dry/banya", heat["hsp_threshold_note"])

    def test_sleep_summary_marks_efficiency_as_derived_and_short_sleep_caveat(self) -> None:
        out = sleep_summary(
            [
                {
                    "date": "2026-06-01",
                    "total_h": 6.0,
                    "time_in_bed_h": 6.5,
                    "efficiency_pct": 92.3,
                    "awake_h": 0.2,
                },
                {
                    "date": "2026-06-02",
                    "total_h": 6.2,
                    "time_in_bed_h": 6.6,
                    "efficiency_pct": 93.9,
                    "awake_h": 0.1,
                },
            ],
            date(2026, 6, 3),
        )

        self.assertEqual(out["sleep_efficiency_pct"]["source"], "derived_sleep_period")
        self.assertIn("below 7h", out["absolute_sleep_note"])

    def test_swim_summary_prompts_css_when_swims_exist_without_css(self) -> None:
        out = swim_summary(
            [{"date": "2026-06-01", "start": "07:00:00", "distance_km": 1.0, "duration_min": 25}],
            [],
            date(2026, 6, 2),
            {},
            None,
        )

        self.assertIsNone(out["css"])
        self.assertIn("CSS", out["css_missing_nudge"])

    def test_protein_target_is_caveated_as_untracked(self) -> None:
        out = nutrition_phase_summary(
            [{
                "start_date": "2026-05-01",
                "end_date": None,
                "phase_type": "bulk",
                "target_rate_kg_per_wk": 0.25,
                "target_protein_g_per_kg": 2.0,
            }],
            [
                {"date": "2026-05-01", "kg": 75.0},
                {"date": "2026-05-10", "kg": 75.2},
                {"date": "2026-05-20", "kg": 75.4},
                {"date": "2026-05-28", "kg": 75.5},
            ],
            date(2026, 6, 1),
        )

        self.assertEqual(out["targets"]["protein_tracking_status"], "target_only")
        self.assertIn("do not claim adherence", out["targets"]["protein_caveat"])

    def test_apple_source_with_start_still_classifies_as_cardio(self) -> None:
        row = {
            "date": "2026-06-01",
            "exercise": "Indoor Cycling",
            "duration_min": 30,
            "distance_km": None,
            "avg_hr": None,
            "source": "apple@07:30:00",
        }

        self.assertTrue(sessions._is_cardio_row(row))
        out = sessions.build_monthly_sessions([row], {}, {}, [])
        self.assertEqual(out[0]["session_kind"], "cardio")


if __name__ == "__main__":
    unittest.main()
