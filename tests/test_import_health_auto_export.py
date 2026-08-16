from __future__ import annotations

import csv
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from datetime import date
from io import StringIO
from pathlib import Path


from shared import csv_store, import_health_auto_export as hae, monthly_csv, person_paths


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
        # Body composition. A real HealthAutoExport daily CSV carries all
        # three; the unit token in the header follows the user's in-app
        # preference, so the importer resolves these by prefix.
        "Waist Circumference (cm)",
        "Body Fat Percentage (%)",
        "Lean Body Mass (kg)",
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
                "84.5",
                "0.181",
                "63.2",
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

            metrics, sleep, workouts, _swim = hae.parse_health_auto_export_zip(
                path, date(2026, 4, 1), date(2026, 4, 1)
            )

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["vo2max"], 46.5)
        self.assertIsNone(metrics[0]["time_in_bed_h"])
        # Body composition, metric export. Body fat arrives as HealthKit's
        # fraction and is stored as percentage points.
        self.assertEqual(metrics[0]["waist_cm"], 84.5)
        self.assertEqual(metrics[0]["body_fat_pct"], 18.1)
        self.assertEqual(metrics[0]["lean_body_mass_kg"], 63.2)
        self.assertEqual(len(sleep), 1)
        self.assertEqual(sleep[0]["total_h"], 7.0)
        self.assertIsNone(sleep[0]["time_in_bed_h"])
        run = [w for w in workouts if w["apple_type"] == "Running"][0]
        self.assertEqual(run["start"], "16:45:00")
        self.assertEqual(run["active_cal"], 100.0)
        self.assertEqual(run["total_cal"], 120.0)
        self.assertEqual(run["min_hr"], 100)
        self.assertEqual(run["distance_km"], 5.0)

    def test_missing_hae_columns_warn(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            metrics, sleep = hae.parse_daily_rows(
                [{"Date/Time": "2026-05-01 00:00:00"}],
                date(2026, 5, 1),
                date(2026, 5, 1),
            )

        self.assertIn("HealthAutoExport daily column missing", err.getvalue())
        # Body-composition columns are prefix-resolved, so their absence is
        # reported with a wildcard unit rather than a guessed metric name.
        self.assertIn("Waist Circumference (<unit>)", err.getvalue())
        self.assertIn("Body Fat Percentage (<unit>)", err.getvalue())
        self.assertIn("Lean Body Mass (<unit>)", err.getvalue())
        self.assertEqual(len(metrics), 1)
        self.assertIsNone(metrics[0]["waist_cm"])
        self.assertIsNone(metrics[0]["body_fat_pct"])
        self.assertIsNone(metrics[0]["lean_body_mass_kg"])
        self.assertEqual(sleep, [])

    def test_workout_stamps_use_minute_start_and_report_ambiguous_matches(self) -> None:
        rows = [{
            "Workout Type": "Outdoor Run",
            "Start": "2026-05-01 08:15",
            "End": "2026-05-01 08:45",
            "Duration": "00:30:00",
            "Active Energy (kJ)": "400",
            "Resting Energy (kJ)": "40",
            "Avg. Heart Rate (count/min)": "",
            "Distance (km)": "5",
        }]

        parsed = hae.parse_workout_rows(
            rows,
            {("Outdoor Run", "20260501_0815"): {"20260501_081501", "20260501_081530"}},
            {},
            date(2026, 5, 1),
            date(2026, 5, 1),
        )

        self.assertEqual(parsed[0]["start"], "08:15:00")
        self.assertEqual(parsed[0]["stamp_status"], "ambiguous")

    def test_replace_range_removes_machine_rows_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = person_paths.WORKOUT_TRACKER_ROOT
            old_importer_root = hae.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = root
            hae.WORKOUT_TRACKER_ROOT = root
            try:
                csv_store.write_profile("Test", source="health_auto_export", auto_cardio=True)
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
                        "source": "LegacyImporter",
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

    def test_full_reimport_without_replace_range_does_not_duplicate_sessions(self) -> None:
        # Regression guard for a suspected re-import duplication bug: a
        # full re-run of the *same* HealthAutoExport ZIP with no
        # --replace-range (the plain "run the importer again" path a user
        # actually takes) must be a no-op on workout_sessions.csv, not a
        # row-doubling one.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = person_paths.WORKOUT_TRACKER_ROOT
            old_importer_root = hae.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = root
            hae.WORKOUT_TRACKER_ROOT = root
            try:
                export = root / "HealthAutoExport.zip"
                build_export_zip(export)
                kwargs = dict(
                    person="Test",
                    zip_path=export,
                    since=date(2026, 4, 1),
                    until=date(2026, 4, 1),
                    allow_past_months=True,
                    replace_range=False,
                    dry_run=False,
                    keep_export=True,
                )
                hae.import_archive(**kwargs)
                hae.import_archive(**kwargs)  # full re-run of the identical export

                sessions = csv_store.read_workout_sessions("Test")
            finally:
                person_paths.WORKOUT_TRACKER_ROOT = old_root
                hae.WORKOUT_TRACKER_ROOT = old_importer_root

        self.assertEqual(len(sessions), 2)  # strength + run seeded by build_export_zip
        self.assertEqual(
            sorted(s["start"] for s in sessions),
            ["16:45:00", "18:00:00"],
        )

    def test_overlapping_rolling_exports_share_same_start_key_and_do_not_duplicate(self) -> None:
        # HealthAutoExport's real export mechanism produces overlapping
        # rolling windows (e.g. "last 8 days", "last 8 days" a week later,
        # sharing several days). The same underlying workout then arrives
        # in two separate ZIPs. Because HealthAutoExport's own "Start"
        # column is minute-precision with no jitter between exports, both
        # ZIPs re-emit the identical "Start" string for that workout, so the
        # second import must update/no-op the existing row rather than add
        # a duplicate.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = person_paths.WORKOUT_TRACKER_ROOT
            old_importer_root = hae.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = root
            hae.WORKOUT_TRACKER_ROOT = root
            try:
                export1 = root / "HealthAutoExport_run1.zip"
                export2 = root / "HealthAutoExport_run2.zip"
                build_export_zip(export1)
                build_export_zip(export2)

                for export in (export1, export2):
                    hae.import_archive(
                        person="Test",
                        zip_path=export,
                        since=date(2026, 4, 1),
                        until=date(2026, 4, 1),
                        allow_past_months=True,
                        replace_range=False,
                        dry_run=False,
                        keep_export=True,
                    )

                sessions = csv_store.read_workout_sessions("Test")
            finally:
                person_paths.WORKOUT_TRACKER_ROOT = old_root
                hae.WORKOUT_TRACKER_ROOT = old_importer_root

        self.assertEqual(len(sessions), 2)

    def test_replace_range_past_month_requires_past_month_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = person_paths.WORKOUT_TRACKER_ROOT
            old_importer_root = hae.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = root
            hae.WORKOUT_TRACKER_ROOT = root
            try:
                csv_store.write_profile("Test", source="health_auto_export", auto_cardio=True)
                export = root / "HealthAutoExport.zip"
                build_export_zip(export)
                with self.assertRaises(ValueError):
                    hae.import_archive(
                        "Test",
                        export,
                        since=date(2026, 4, 1),
                        until=date(2026, 4, 1),
                        allow_past_months=False,
                        replace_range=True,
                        dry_run=False,
                        keep_export=True,
                    )
            finally:
                person_paths.WORKOUT_TRACKER_ROOT = old_root
                hae.WORKOUT_TRACKER_ROOT = old_importer_root


if __name__ == "__main__":
    unittest.main()
