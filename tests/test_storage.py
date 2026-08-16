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
            light_therapy_target_per_week=3,
            light_therapy_target_min_per_session=12,
            sauna_target_per_week=4,
        )
        path = person_paths.profile_csv("Test")
        with path.open("a", encoding="utf-8", newline="") as f:
            f.write("custom_key,custom_value\n")

        profile = csv_store.read_profile("Test")
        self.assertEqual(profile["light_therapy_target_per_week"], 3)
        self.assertEqual(profile["light_therapy_target_min_per_session"], 12)
        self.assertEqual(profile["sauna_target_per_week"], 4)

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

    def test_thermal_defaults_and_heat_total_invariant(self) -> None:
        csv_store.upsert_thermal_sessions(
            "Test",
            [{
                "date": "2026-05-03",
                "start": "18:30",
                "heat_type": "dry",
                "heat_round_durations_min": [12, 8],
                "cold_type": "cold_air",
                "cold_duration_sec": 300,
            }],
        )
        row = csv_store.read_thermal_sessions("Test")[0]
        self.assertEqual(row["heat_temp_c"], 90)
        self.assertEqual(row["heat_rounds"], 2)
        self.assertEqual(row["heat_total_min"], 20)

    def test_thermal_unknown_enum_raises(self) -> None:
        with self.assertRaises(ValueError):
            csv_store.upsert_thermal_sessions(
                "Test",
                [{
                    "date": "2026-05-03",
                    "start": "18:30",
                    "heat_type": "mystery_sauna",
                    "heat_round_durations_min": [10],
                }],
            )

    def test_thermal_missing_start_preserves_same_shape_collisions(self) -> None:
        csv_store.upsert_thermal_sessions(
            "Test",
            [{
                "date": "2026-05-03",
                "heat_type": "dry",
                "heat_round_durations_min": [10],
            }],
        )
        csv_store.upsert_thermal_sessions(
            "Test",
            [{
                "date": "2026-05-03",
                "cold_type": "cold_shower",
                "cold_duration_sec": 60,
            }],
        )
        csv_store.upsert_thermal_sessions(
            "Test",
            [{
                "date": "2026-05-03",
                "heat_type": "dry",
                "heat_round_durations_min": [12],
            }],
        )
        csv_store.upsert_thermal_sessions(
            "Test",
            [{
                "date": "2026-05-03",
                "heat_type": "dry",
                "heat_round_durations_min": [12],
            }],
        )

        rows = csv_store.read_thermal_sessions("Test")
        self.assertEqual(len(rows), 3)
        dry_rows = sorted(
            [r for r in rows if r.get("heat_type") == "dry"],
            key=lambda r: str(r.get("start") or ""),
        )
        cold = [r for r in rows if r.get("cold_type") == "cold_shower"][0]
        self.assertEqual([r["heat_total_min"] for r in dry_rows], [10, 12])
        self.assertEqual(dry_rows[1]["start"], "occurrence:2")
        self.assertEqual(cold["cold_duration_sec"], 60)

    def test_light_therapy_defaults_and_roundtrip(self) -> None:
        csv_store.upsert_light_therapy_sessions(
            "Test",
            [{
                "date": "2026-05-14",
                "duration_min": 5,
                "light_type": "red+ir",
                "ambient_temp_c": 45,
                "body_area": "full_body",
            }],
        )
        row = csv_store.read_light_therapy_sessions("Test")[0]
        self.assertEqual(row["duration_min"], 5)
        self.assertEqual(row["light_type"], "red+ir")
        self.assertEqual(row["ambient_temp_c"], 45)
        self.assertEqual(row["modality"], "cabin")  # auto-defaulted from heated-cabin temp

        # Sparse-merge: a later write only updates the column it touches.
        csv_store.upsert_light_therapy_sessions(
            "Test",
            [{"date": "2026-05-14", "wavelength_nm": 660}],
        )
        row = csv_store.read_light_therapy_sessions("Test")[0]
        self.assertEqual(row["wavelength_nm"], 660)
        self.assertEqual(row["duration_min"], 5)
        self.assertEqual(row["light_type"], "red+ir")

    def test_light_therapy_unknown_enum_raises(self) -> None:
        with self.assertRaises(ValueError):
            csv_store.upsert_light_therapy_sessions(
                "Test",
                [{"date": "2026-05-14", "duration_min": 10, "light_type": "ultraviolet"}],
            )
        with self.assertRaises(ValueError):
            csv_store.upsert_light_therapy_sessions(
                "Test",
                [{"date": "2026-05-14", "duration_min": 10, "modality": "laser_pointer"}],
            )

    def test_upsert_workout_sessions_reparsed_timestamp_is_idempotent(self) -> None:
        # Regression guard for a re-import duplication bug: the start key
        # comes from health_units.hhmm(), re-derived from the export's
        # timestamp on every run (not cached). A real re-import re-parses
        # the same underlying HealthKit event and must produce the
        # identical (date, start) key both times, or the dense
        # (date, start) dedupe in upsert_workout_sessions would insert a
        # second row instead of updating the first.
        from datetime import datetime

        from shared.health_units import hhmm

        def build_entry() -> dict:
            # Fresh datetime object each call, mirroring how each importer
            # run re-parses the export from scratch rather than reusing
            # state from a prior run.
            dt = datetime(2026, 5, 1, 8, 15, 37)
            return {
                "date": "2026-05-01",
                "start": hhmm(dt),
                "apple_type": "Running",
                "duration_min": 30,
            }

        csv_store.upsert_workout_sessions("Test", [build_entry()])
        csv_store.upsert_workout_sessions("Test", [build_entry()])  # full re-import

        sessions = csv_store.read_workout_sessions("Test")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["start"], "08:15:37")

    def test_hhmm_preserves_seconds_not_just_minute(self) -> None:
        # Locks in hhmm()'s actual (second-precision) output. A prior audit
        # mistakenly believed the importer wrote minute-only start keys via
        # hhmm(); this pins the true behavior so a future regression to
        # minute truncation is caught immediately.
        from datetime import datetime

        from shared.health_units import hhmm

        self.assertEqual(hhmm(datetime(2026, 5, 1, 8, 15, 37)), "08:15:37")

    def test_upsert_workout_sessions_reparsed_health_auto_export_minute_is_idempotent(self) -> None:
        # Same guard as above for the HealthAutoExport importer. Its "Start"
        # source column is itself minute-precision (HealthAutoExport's CSV
        # never includes seconds), so _parse_workout_minute + _hhmmss always
        # reproduce the same "HH:MM:00" key for the same raw Start string --
        # including across HealthAutoExport's overlapping rolling exports,
        # which re-emit an identical "Start" cell for a workout that falls
        # in two consecutive export windows.
        from shared.import_health_auto_export import _hhmmss, _parse_workout_minute

        def build_entry() -> dict:
            start_dt = _parse_workout_minute("2026-05-01 08:15")
            return {
                "date": "2026-05-01",
                "start": _hhmmss(start_dt),
                "apple_type": "Running",
                "duration_min": 30,
            }

        csv_store.upsert_workout_sessions("Test", [build_entry()])
        csv_store.upsert_workout_sessions("Test", [build_entry()])  # overlapping-export re-import

        sessions = csv_store.read_workout_sessions("Test")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["start"], "08:15:00")

    def test_swim_laps_replace_on_match(self) -> None:
        base = {
            "date": "2026-05-04",
            "workout_start": "07:00:00",
            "lap_num": 1,
            "duration_sec": 30,
            "swolf": 45,
            "stroke_raw": 2,
            "stroke_decoded": "Free",
            "source": "xml",
        }
        csv_store.upsert_swim_laps("Test", [base])
        changed = dict(base, swolf=46)
        csv_store.upsert_swim_laps("Test", [changed])
        rows = csv_store.read_swim_laps("Test")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["swolf"], 46)


if __name__ == "__main__":
    unittest.main()
