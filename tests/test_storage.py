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
        csv_store.write_profile("Test", source="xml", auto_cardio=True)

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

    def test_thermal_missing_start_dedupes_by_protocol_shape(self) -> None:
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

        rows = csv_store.read_thermal_sessions("Test")
        self.assertEqual(len(rows), 2)
        dry = [r for r in rows if r.get("heat_type") == "dry"][0]
        cold = [r for r in rows if r.get("cold_type") == "cold_shower"][0]
        self.assertEqual(dry["heat_total_min"], 12)
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
