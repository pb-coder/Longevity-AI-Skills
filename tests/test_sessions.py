from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILLS_ROOT / "workout-coach" / "lib"))
sys.path.insert(0, str(SKILLS_ROOT / "shared"))

import sessions  # noqa: E402


class BuildMonthlySessionsTests(unittest.TestCase):
    def test_strength_session_does_not_inherit_cardio_row_metadata(self) -> None:
        # Mixed-day: manual strength session + 2 auto-imported cycling
        # rides. The strength TOTAL summary is empty (manual session has
        # no Apple-watch metadata). The first cycling ride's duration,
        # avg HR, elevation, calories must NOT bleed into the strength
        # session's metadata.
        rows = [
            {"date": "2026-05-11", "exercise": "Hack Squat",
             "kg": 40, "reps": 8, "duration_min": None, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
            {"date": "2026-05-11", "exercise": "Outdoor Cycling",
             "kg": None, "reps": None, "duration_min": 14.1, "distance_km": 3.7,
             "avg_hr": 150, "active_cal": 120, "total_cal": 150,
             "elevation_m": 22, "elapsed": "14:06", "source": "apple"},
            {"date": "2026-05-11", "exercise": "Outdoor Cycling",
             "kg": None, "reps": None, "duration_min": 6.3, "distance_km": 0.9,
             "avg_hr": 138, "active_cal": 46, "total_cal": 56,
             "elevation_m": 8, "elapsed": "6:18", "source": "apple"},
        ]
        out = sessions.build_monthly_sessions(rows, {}, {}, [])
        self.assertEqual(len(out), 2)
        strength = out[0]
        cardio = out[1]
        self.assertEqual(strength["session_kind"], "strength")
        self.assertIsNone(strength["duration_min"])
        self.assertIsNone(strength["elevation_m"])
        self.assertIsNone(strength["avg_hr"])
        self.assertIsNone(strength["active_cal"])
        self.assertEqual(cardio["session_kind"], "cardio")
        self.assertEqual(cardio["duration_min"], 14.1)
        self.assertEqual(cardio["avg_hr"], 150)

    def test_strength_session_uses_total_summary_when_present(self) -> None:
        # Mixed day with HealthAutoExport TOTAL summary present: strength
        # session takes its metadata from the TOTAL summary, not cardio.
        rows = [
            {"date": "2026-04-27", "exercise": "Hack Squat",
             "kg": 40, "reps": 8, "duration_min": None, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
            {"date": "2026-04-27", "exercise": "Outdoor Cycling",
             "kg": None, "reps": None, "duration_min": 13.9, "distance_km": 4.3,
             "avg_hr": 150, "active_cal": 124, "total_cal": 147,
             "elevation_m": 7, "elapsed": "13:54", "source": "apple"},
        ]
        summaries = {"2026-04-27": {
            "duration_min": 62.2, "avg_hr": 131.3,
            "active_cal": 505, "total_cal": 601,
            "elevation_m": None, "elapsed": "1:02:12",
        }}
        out = sessions.build_monthly_sessions(rows, summaries, {}, [])
        s = out[0]
        self.assertEqual(s["session_kind"], "strength")
        self.assertEqual(s["duration_min"], 62.2)
        self.assertEqual(s["avg_hr"], 131.3)
        self.assertEqual(s["active_cal"], 505)
        # TOTAL summary had no elevation → stays None, NOT 7 from cycling.
        self.assertIsNone(s["elevation_m"])

    def test_pure_cardio_session_still_inherits_from_cardio_rows(self) -> None:
        # No strength rows on the date → cardio row metadata fills the
        # session (the previous behavior, unchanged for pure cardio).
        rows = [
            {"date": "2026-04-02", "exercise": "Outdoor Run",
             "kg": None, "reps": None, "duration_min": 35.4, "distance_km": 6.0,
             "avg_hr": 162, "active_cal": 396, "total_cal": 455,
             "elevation_m": 53, "elapsed": "35:24", "source": "apple"},
        ]
        out = sessions.build_monthly_sessions(rows, {}, {}, [])
        s = out[0]
        self.assertEqual(s["session_kind"], "cardio")
        self.assertEqual(s["duration_min"], 35.4)
        self.assertEqual(s["avg_hr"], 162)
        self.assertEqual(s["elevation_m"], 53)

    def test_isometric_hold_is_not_treated_as_cardio_row(self) -> None:
        # Dead Hang with duration_min=0.5, no HR, no distance, manual
        # source → must be classified as "other", not "cardio". So the
        # session_kind for a hold-only day must be "other", not "cardio".
        rows = [
            {"date": "2026-05-14", "exercise": "Dead Hang",
             "kg": 0, "reps": 0, "duration_min": 0.5, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
        ]
        self.assertFalse(sessions._is_cardio_row(rows[0]))
        out = sessions.build_monthly_sessions(rows, {}, {}, [])
        s = out[0]
        self.assertEqual(s["session_kind"], "other")
        self.assertIsNone(s["duration_min"])

    def test_isometric_hold_in_strength_session_does_not_set_duration(self) -> None:
        # Strength session with Jumping Jacks + Dead Hang + working sets.
        # The Dead Hang's 0:30 hold time must not propagate to the
        # session's duration_min.
        rows = [
            {"date": "2026-05-14", "exercise": "Jumping Jacks",
             "kg": 0, "reps": 50, "duration_min": None, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
            {"date": "2026-05-14", "exercise": "Dead Hang",
             "kg": 0, "reps": 0, "duration_min": 0.5, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
            {"date": "2026-05-14", "exercise": "Cable Lat Pulldown",
             "kg": 57.5, "reps": 8, "duration_min": None, "distance_km": None,
             "avg_hr": None, "active_cal": None, "total_cal": None,
             "elevation_m": None, "elapsed": None, "source": "manual"},
        ]
        out = sessions.build_monthly_sessions(rows, {}, {}, [])
        s = out[0]
        self.assertEqual(s["session_kind"], "strength")
        self.assertIsNone(s["duration_min"])


if __name__ == "__main__":
    unittest.main()
