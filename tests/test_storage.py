from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


from shared import csv_store, person_paths


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = person_paths.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = Path(self.tmp.name)
        csv_store.write_profile("Test", source="health_auto_export", auto_cardio=True)

    def tearDown(self) -> None:
        person_paths.WORKOUT_TRACKER_ROOT = self.old_root
        self.tmp.cleanup()

    def test_health_metrics_sparse_merge_preserves_existing_values(self) -> None:
        csv_store.upsert_health_metrics("Test", [{"date": "2026-05-01", "vo2max": 42.0}])
        csv_store.upsert_health_metrics(
            "Test",
            [{"date": "2026-05-01", "vo2max": None, "resting_hr": 58}],
        )
        row = csv_store.read_health_metrics("Test")[0]
        self.assertEqual(row["vo2max"], 42.0)
        self.assertEqual(row["resting_hr"], 58)

    def test_health_auto_export_uses_full_schema(self) -> None:
        csv_store.write_profile("Test", source="health_auto_export", auto_cardio=True)
        csv_store.upsert_health_metrics(
            "Test",
            [{
                "date": "2026-05-01",
                "vo2max": 42.0,
                "resting_hr": 58,
                "hrv_sdnn": 55,
                "sleep_deep_h": 1.2,
                "wrist_temp_c": 36.1,
            }],
        )
        row = csv_store.read_health_metrics("Test")[0]
        self.assertEqual(row["hrv_sdnn"], 55)
        self.assertEqual(row["sleep_deep_h"], 1.2)
        self.assertEqual(row["wrist_temp_c"], 36.1)

    def test_profile_roundtrips_targets_and_unknown_keys(self) -> None:
        csv_store.write_profile(
            "Test",
            swim_pool_length_default=25,
        )
        path = person_paths.profile_csv("Test")
        with path.open("a", encoding="utf-8", newline="") as f:
            f.write("custom_key,custom_value\n")

        profile = csv_store.read_profile("Test")

        csv_store.write_profile("Test", auto_cardio=False)
        self.assertIn("custom_key,custom_value", path.read_text(encoding="utf-8"))

    def test_session_target_min_default_and_override(self) -> None:
        csv_store.write_profile("Test", source="health_auto_export")
        self.assertEqual(csv_store.read_profile("Test")["session_target_min"], 60)
        csv_store.write_profile("Test", session_target_min=75)
        self.assertEqual(csv_store.read_profile("Test")["session_target_min"], 75)
        # Out-of-range values fall back to the default rather than corrupting.
        csv_store.write_profile("Test", session_target_min=5)
        self.assertEqual(csv_store.read_profile("Test")["session_target_min"], 60)

    def test_muscle_priority_tiers_reach_the_coach(self) -> None:
        # The documented per-person override was parsed into the unknown
        # rows and dropped, so every tracker silently ran on the built-in
        # emphasis set whatever its profile said.
        from workout_coach.lib.constants import muscle_priority_tiers
        self.assertIsNone(csv_store.read_profile("Test")["muscle_priority_tiers"])
        csv_store.write_profile("Test",
                                muscle_priority_tiers="chest:emphasis;calves:maintain")
        profile = csv_store.read_profile("Test")
        self.assertEqual(profile["muscle_priority_tiers"],
                         "chest:emphasis;calves:maintain")
        tiers, unknown = muscle_priority_tiers(profile)
        self.assertEqual((tiers["chest"], tiers["calves"], unknown),
                         ("emphasis", "maintain", []))

    def test_sleep_efficiency_and_notes_are_manual_wins(self) -> None:
        csv_store.upsert_sleep_nights(
            "Test",
            [{"date": "2026-05-02", "total_h": 8.0, "time_in_bed_h": 10.0, "notes": "manual"}],
        )
        csv_store.upsert_sleep_nights(
            "Test",
            [{"date": "2026-05-02", "deep_h": 1.2, "notes": "overwrite"}],
        )
        row = csv_store.read_sleep_nights("Test")[0]
        self.assertEqual(row["efficiency_pct"], 80.0)
        self.assertEqual(row["deep_h"], 1.2)
        self.assertEqual(row["notes"], "manual")

    def test_upsert_workout_sessions_reparsed_timestamp_is_idempotent(self) -> None:
        # Reparse the same export on each import and preserve seconds in the key.
        from shared.import_health_export_kit import build_workout_payload

        payload = {
            "meta": {"timeZone": "UTC", "rangeStart": "2026-05-01T00:00:00Z",
                     "rangeEnd": "2026-05-02T00:00:00Z", "exportedAt": "2026-05-02T00:00:00Z"},
            "activity": {"workouts": [{"start": "05-01 08:15:37",
                                        "type": "Running", "durationSec": 1800}]},
        }
        for _ in range(2):
            csv_store.upsert_workout_sessions(
                "Test", build_workout_payload(payload, None, None)
            )

        sessions = csv_store.read_workout_sessions("Test")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["start"], "08:15:37")

    def test_frozen_swim_lap_history_remains_readable(self) -> None:
        import csv

        path = person_paths.swim_laps_csv("Test", "2026.05")
        path.parent.mkdir(parents=True, exist_ok=True)
        values = {"date": "2026-05-04", "workout_start": "07:00:00",
                  "lap_num": 1, "duration_sec": 30, "swolf": 45,
                  "stroke_decoded": "Free", "source": "xml"}
        with path.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(csv_store.SWIM_LAPS_HEADERS)
            writer.writerow([values.get(field, "") for field in
                             ["date", *csv_store.SWIM_LAPS_FIELDS]])
        before = path.read_bytes()
        rows = csv_store.read_swim_laps("Test")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["swolf"], 45)
        self.assertEqual(rows[0]["workout_start"], "07:00:00")
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()


class WorkoutHeartRatePreservationTests(unittest.TestCase):
    """A re-import must not blank a heart rate it simply does not carry.

    ``upsert_workout_sessions`` replaces a matched row entirely, so that a
    corrected distance propagates. Heart rate is the exception: the retired
    importer derived it by averaging a series across the workout's window,
    and the current export reports only Apple's own per-workout statistic,
    which is absent on some workouts. Without this, a routine refresh
    silently strips readings the tracker already held.
    """

    def _round_trip(self, first: dict, second: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            old = person_paths.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = Path(tmp)
            try:
                csv_store.write_profile("T", source="health_export_kit")
                csv_store.upsert_workout_sessions("T", [first])
                csv_store.upsert_workout_sessions("T", [second])
                return csv_store.read_workout_sessions("T")[0]
            finally:
                person_paths.WORKOUT_TRACKER_ROOT = old

    BASE = {
        "date": "2026-08-13", "start": "17:12:00", "end": "17:30:00",
        "apple_type": "Walking", "duration_min": 18.0, "distance_km": 1.2,
        "source": "Device",
    }

    def test_an_absent_heart_rate_does_not_blank_a_stored_one(self) -> None:
        got = self._round_trip(
            {**self.BASE, "avg_hr": 102.0, "max_hr": 128, "min_hr": 74},
            dict(self.BASE),
        )
        self.assertEqual(got["avg_hr"], 102.0)
        self.assertEqual(got["max_hr"], 128)
        self.assertEqual(got["min_hr"], 74)

    def test_a_supplied_heart_rate_still_replaces_the_stored_one(self) -> None:
        got = self._round_trip(
            {**self.BASE, "avg_hr": 102.0, "max_hr": 128, "min_hr": 74},
            {**self.BASE, "avg_hr": 110.0, "max_hr": 140, "min_hr": 80},
        )
        self.assertEqual(got["avg_hr"], 110.0)
        self.assertEqual(got["max_hr"], 140)

    def test_other_fields_are_still_replaced_outright(self) -> None:
        got = self._round_trip(
            {**self.BASE, "distance_km": 550.0},
            {**self.BASE, "distance_km": 0.55},
        )
        self.assertEqual(got["distance_km"], 0.55)
