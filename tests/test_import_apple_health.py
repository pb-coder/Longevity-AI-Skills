from __future__ import annotations

import unittest
from datetime import datetime

from shared.apple_health_core import parse_apple_dt
from shared.apple_health_strength import cluster_strength_sessions
from shared import import_apple_health as iah


class AppleHealthImportTests(unittest.TestCase):
    def test_negligible_swim_artifacts_are_dropped(self) -> None:
        workouts = [
            {
                "date": "2026-05-25",
                "start": "08:00",
                "apple_type": "Swimming",
                "duration_min": 2.2,
                "distance_km": 0.035,
            },
            {
                "date": "2026-05-25",
                "start": "08:10",
                "apple_type": "Swimming",
                "duration_min": 3.0,
                "distance_km": 0.035,
            },
            {
                "date": "2026-05-25",
                "start": "09:00",
                "apple_type": "Running",
                "duration_min": 2.0,
                "distance_km": 0.02,
            },
        ]

        kept, notes = iah._drop_negligible_swims(workouts)

        self.assertEqual([w["start"] for w in kept], ["08:10", "09:00"])
        self.assertEqual(len(notes), 1)
        self.assertIn("skipped negligible swim", notes[0])
        self.assertIn("2026-05-25 08:00", notes[0])

    def test_nearby_swims_are_reported_but_not_merged(self) -> None:
        workouts = [
            {
                "date": "2026-05-29",
                "start": "08:07",
                "apple_type": "Swimming",
                "dt_start": datetime(2026, 5, 29, 8, 7),
                "dt_end": datetime(2026, 5, 29, 8, 15),
            },
            {
                "date": "2026-05-29",
                "start": "08:19",
                "apple_type": "Swimming",
                "dt_start": datetime(2026, 5, 29, 8, 19),
                "dt_end": datetime(2026, 5, 29, 8, 25),
            },
        ]

        notes = iah._note_nearby_swims(workouts)

        self.assertEqual(len(notes), 1)
        self.assertIn("nearby swims kept separate", notes[0])
        self.assertIn("08:07 and 08:19", notes[0])

    def test_strength_clusterer_respects_seconds_and_90_min_window(self) -> None:
        sessions, warnings = cluster_strength_sessions([
            {
                "date": "2026-05-01",
                "start": "08:00:30",
                "apple_type": "TraditionalStrengthTraining",
                "duration_min": 30,
            },
            {
                "date": "2026-05-01",
                "start": "12:00:30",
                "apple_type": "TraditionalStrengthTraining",
                "duration_min": 20,
            },
        ])

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["duration_min"], 30)
        self.assertEqual(len(warnings), 1)

    def test_parse_apple_dt_keeps_offset_for_dst_duration_math(self) -> None:
        d1, start = parse_apple_dt("2026-10-25 02:50:00 +0200")
        d2, end = parse_apple_dt("2026-10-25 02:10:00 +0100")

        self.assertEqual(d1, "2026-10-25")
        self.assertEqual(d2, "2026-10-25")
        self.assertEqual((end - start).total_seconds() / 60, 20)


if __name__ == "__main__":
    unittest.main()
