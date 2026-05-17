from __future__ import annotations

import csv
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILLS_ROOT))
sys.path.insert(0, str(SKILLS_ROOT / "shared"))

import csv_store  # noqa: E402
import import_health_auto_export as hae  # noqa: E402
import monthly_csv  # noqa: E402
import person_paths  # noqa: E402


def _write_csv_to_zip(zf: zipfile.ZipFile, name: str, header: list[str], rows: list[list]) -> None:
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    zf.writestr(name, buf.getvalue())


def build_export_zip(path: Path) -> None:
    daily_header = [
        "Date/Time",
        "Weight (kg)",
        "VO2 Max (ml/(kg·min))",
        "Resting Heart Rate (count/min)",
        "Heart Rate Variability (ms)",
        "Walking Heart Rate Average (count/min)",
        "Cardio Recovery (count/min)",
        "Sleep Analysis [Total] (hr)",
        "Sleep Analysis [Core] (hr)",
        "Sleep Analysis [Deep] (hr)",
        "Sleep Analysis [REM] (hr)",
        "Sleep Analysis [Awake] (hr)",
        "Sleep Analysis [In Bed] (hr)",
        "Respiratory Rate (count/min)",
        "Apple Sleeping Wrist Temperature (degC)",
        "Breathing Disturbances (count)",
        "Apple Exercise Time (min)",
    ]
    workout_header = [
        "Workout Type",
        "Start",
        "End",
        "Duration",
        "Active Energy (kJ)",
        "Resting Energy (kJ)",
        "Intensity (kcal/hr·kg)",
        "Max. Heart Rate (count/min)",
        "Avg. Heart Rate (count/min)",
        "Distance (km)",
        "Max. Speed (km/hr)",
        "Avg. Speed (km/hr)",
        "Flights Climbed",
        "Elevation Ascended (m)",
        "Elevation Descended (m)",
        "Step Count",
        "Step Cadence (spm)",
        "Swimming Stroke Count",
        "Swim Cadence (spm)",
        "Lap Length (m)",
        "Swim Stroke Style",
        "SWOLF Score",
        "Water Salinity",
        "Temperature (degC)",
        "Humidity (%)",
        "Location",
        "",
    ]
    with zipfile.ZipFile(path, "w") as zf:
        _write_csv_to_zip(
            zf,
            "HealthAutoExport-2026-04-01-2026-04-01.csv",
            daily_header,
            [[
                "2026-04-01 00:00:00",
                "",
                "46.5",
                "61",
                "55.5",
                "103",
                "28.4",
                "7",
                "4",
                "1",
                "2",
                "0.5",
                "0",
                "14.2",
                "36.1",
                "1.2",
                "75",
            ]],
        )
        _write_csv_to_zip(
            zf,
            "Workouts-20260401_000000-20260401_235959.csv",
            workout_header,
            [
                [
                    "Traditional Strength Training",
                    "2026-04-01 18:00",
                    "2026-04-01 18:40",
                    "00:40:00",
                    "400",
                    "80",
                    "",
                    "150",
                    "120",
                    "0",
                    "",
                    "",
                    "",
                    "0",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ],
                [
                    "Outdoor Run",
                    "2026-04-01 16:45",
                    "2026-04-01 17:08",
                    "00:23:29",
                    "418.4",
                    "83.68",
                    "",
                    "180",
                    "150",
                    "5.0",
                    "",
                    "",
                    "",
                    "10",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ],
            ],
        )
        _write_csv_to_zip(
            zf,
            "Outdoor Run-Heart Rate-20260401_164521.csv",
            ["Date/Time", "Min (count/min)", "Max (count/min)", "Avg (count/min)", "Context", "Source"],
            [["2026-04-01 16:45:21", "100", "180", "150", "", "Watch"]],
        )
        _write_csv_to_zip(
            zf,
            "Traditional Strength Training-Heart Rate-20260401_180011.csv",
            ["Date/Time", "Min (count/min)", "Max (count/min)", "Avg (count/min)", "Context", "Source"],
            [["2026-04-01 18:00:11", "90", "150", "120", "", "Watch"]],
        )


class HealthAutoExportTests(unittest.TestCase):
    def test_monthly_cardio_dedupes_same_batch_auto_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = person_paths.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = root
            try:
                summaries = monthly_csv.upsert_monthly_cardio(
                    "Test",
                    [
                        {
                            "date": "2026-04-02",
                            "exercise": "Outdoor Run",
                            "duration_min": 30.0,
                            "distance_km": 5.0,
                            "avg_hr": 140,
                            "active_cal": 250,
                        },
                        {
                            "date": "2026-04-02",
                            "exercise": "Outdoor Run",
                            "duration_min": 30.4,
                            "distance_km": 5.0,
                            "avg_hr": 141,
                            "active_cal": 251,
                        },
                    ],
                    allow_past_months=True,
                    today_d=date(2026, 4, 2),
                )
                monthly = monthly_csv.read_monthly("Test", "2026.04")
            finally:
                person_paths.WORKOUT_TRACKER_ROOT = old_root

        runs = [r for r in monthly if r.get("exercise") == "Outdoor Run"]
        self.assertEqual(len(runs), 1)
        self.assertIn("1 cardio rows appended", summaries[0])
        self.assertIn("1 skipped", summaries[0])

    def test_parser_maps_daily_sleep_and_workout_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "HealthAutoExport.zip"
            build_export_zip(path)

            metrics, sleep, workouts = hae.parse_health_auto_export_zip(
                path, date(2026, 4, 1), date(2026, 4, 1)
            )

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["vo2max"], 46.5)
        self.assertIsNone(metrics[0]["time_in_bed_h"])
        self.assertEqual(len(sleep), 1)
        self.assertEqual(sleep[0]["total_h"], 7.0)
        self.assertIsNone(sleep[0]["time_in_bed_h"])
        run = [w for w in workouts if w["apple_type"] == "Running"][0]
        self.assertEqual(run["start"], "16:45:21")
        self.assertEqual(run["active_cal"], 100.0)
        self.assertEqual(run["total_cal"], 120.0)
        self.assertEqual(run["min_hr"], 100)
        self.assertEqual(run["distance_km"], 5.0)

    def test_replace_range_removes_hl_rows_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = person_paths.WORKOUT_TRACKER_ROOT
            old_importer_root = hae.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = root
            hae.WORKOUT_TRACKER_ROOT = root
            try:
                csv_store.write_profile("Test", source="hl_export", auto_cardio=True)
                csv_store.upsert_health_metrics(
                    "Test",
                    [{"date": "2026-04-01", "bodyweight_kg": 77.5, "vo2max": 45.0}],
                )
                csv_store.upsert_workout_sessions(
                    "Test",
                    [{
                        "date": "2026-04-01",
                        "start": "16:40:00",
                        "end": "17:05:00",
                        "apple_type": "Running",
                        "duration_min": 25,
                        "active_cal": 90,
                        "distance_km": 4.5,
                        "source": "HLExport",
                    }],
                )
                monthly_csv.upsert_rows(
                    "Test",
                    "2026.04",
                    [
                        {
                            "date": "2026-04-01",
                            "num": 1,
                            "exercise": "Bench Press",
                            "set": 1,
                            "reps": 8,
                            "kg": 60,
                            "source": "manual",
                        },
                        {
                            "date": "2026-04-01",
                            "num": 2,
                            "exercise": "Outdoor Run",
                            "set": 1,
                            "distance": 4.5,
                            "duration": "25:00",
                            "notes": "auto-imported from Apple",
                        },
                    ],
                )
                # Seed old machine-owned strength metadata on TOTAL.
                path = person_paths.monthly_csv("Test", "2026.04")
                header, rows = monthly_csv._read_csv_rows(path)
                for row in rows:
                    if len(row) > 3 and row[3] == monthly_csv.TOTAL_LABEL:
                        row[10] = "55:00"
                        row[12] = "99"
                        row[13] = "300"
                monthly_csv._write_csv_atomic(path, rows)

                export = root / "HealthAutoExport.zip"
                build_export_zip(export)
                kwargs = dict(
                    person="Test",
                    zip_path=export,
                    since=date(2026, 4, 1),
                    until=date(2026, 4, 1),
                    allow_past_months=True,
                    replace_range=True,
                    dry_run=False,
                    keep_export=True,
                )
                hae.import_archive(**kwargs)
                hae.import_archive(**kwargs)

                profile = csv_store.read_profile("Test")
                health = csv_store.read_health_metrics("Test")
                sessions = csv_store.read_workout_sessions("Test")
                monthly = monthly_csv.read_monthly("Test", "2026.04")
            finally:
                person_paths.WORKOUT_TRACKER_ROOT = old_root
                hae.WORKOUT_TRACKER_ROOT = old_importer_root

        self.assertEqual(profile["source"], "health_auto_export")
        self.assertEqual(health[0]["bodyweight_kg"], 77.5)
        self.assertEqual(health[0]["vo2max"], 46.5)
        self.assertEqual(len(sessions), 2)
        self.assertFalse(any(s.get("source") == "HLExport" for s in sessions))
        runs = [r for r in monthly if r.get("exercise") == "Outdoor Run"]
        self.assertEqual(len(runs), 1)
        total = [r for r in monthly if r.get("exercise") == monthly_csv.TOTAL_LABEL][0]
        self.assertEqual(total["duration"], "40:00")
        self.assertEqual(total["avg_hr"], 120)


if __name__ == "__main__":
    unittest.main()
