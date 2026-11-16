from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from shared import csv_store, import_conflicts, import_health_export_kit as hek, monthly_csv, person_paths

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/hek-export.json"
spec = importlib.util.spec_from_file_location("prepare_guard_test", ROOT / "shared/prepare_training.py")
prepare = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(prepare)


class ImportOverwriteGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        root = patch.object(person_paths, "WORKOUT_TRACKER_ROOT", self.root)
        root.start()
        self.addCleanup(root.stop)
        commit = patch.object(hek, "commit_data", return_value=None)
        commit.start()
        self.addCleanup(commit.stop)
        self.export = self.root / "health-export-json-test.json"
        self.export.write_bytes(FIXTURE.read_bytes())
        self.payload = hek.read_export(self.export)

    def test_conflicts_in_all_stores_stop_before_writes_and_override_allows_replay(self):
        health = hek.build_health_payload(self.payload, None, None)
        nights = hek.build_sleep_payload(self.payload, None, None)
        swims = hek.build_swim_payload(self.payload, None, None)
        workouts = hek.build_workout_payload(self.payload, None, None)
        day = next(r for r in health if r.get("steps") is not None)
        night = next(r for r in nights if r.get("total_h") is not None)
        swim = next(r for r in swims if r.get("avg_hr") is not None)
        workout = next(r for r in workouts if r.get("duration_min") is not None)
        csv_store.upsert_health_metrics("Test", [{"date": day["date"], "steps": day["steps"] + 50}])
        csv_store.upsert_sleep_nights("Test", [{"date": night["date"], "total_h": night["total_h"] + 1}])
        csv_store.upsert_swim_workouts("Test", [{"date": swim["date"], "start": swim["start"], "avg_hr": swim["avg_hr"] + 1}])
        csv_store.upsert_workout_sessions("Test", [{**workout, "duration_min": workout["duration_min"] + 1}])
        data = person_paths.data_dir("Test")
        before = {p.relative_to(data): p.read_bytes() for p in data.rglob("*.csv")}
        preview = hek.import_export("Test", self.export, None, None, dry_run=True)
        summary = next(line for line in preview if line.startswith("Import conflicts:"))
        for label in ("Health Metrics", "Sleep Nights", "Swim Workouts", "Workout Sessions"):
            self.assertIn(label, summary)
        with self.assertRaisesRegex(ValueError, "stopped before writes"):
            hek.import_export("Test", self.export, None, None)
        self.assertTrue(self.export.exists())
        self.assertEqual(before, {p.relative_to(data): p.read_bytes() for p in data.rglob("*.csv")})
        hek.import_export("Test", self.export, None, None, overwrite_existing=True, keep_export=True)
        self.assertFalse(any(line.startswith("Import conflicts:") for line in
                             hek.import_export("Test", self.export, None, None, dry_run=True)))
        hek.import_export("Test", self.export, None, None, keep_export=True)

    def test_normalizes_numeric_values_and_projects_manual_sleep(self):
        self.assertFalse(import_conflicts._equal(False, 0))
        self.assertFalse(import_conflicts._equal(True, 1))
        with patch.object(import_conflicts, "read_health_metrics", return_value=[
            {"date": "2026-03-28", "steps": 10.0, "sleep_total_h": 8.0}]), \
             patch.object(import_conflicts, "read_sleep_nights", return_value=[]):
            self.assertEqual(import_conflicts.find_import_conflicts("Test", [
                {"date": "2026-03-28", "steps": "10.00", "sleep_total_h": 7.0},
                {"date": "2026-03-28", "sleep_total_h": 8.0}], [], [], []), [])
            conflicts = import_conflicts.find_import_conflicts("Test", [
                {"date": "2026-03-28", "sleep_total_h": 8.0}], [], [], [],
                sleep=[{"date": "2026-03-28", "total_h": 6.0}])
            self.assertEqual([c[2] for c in conflicts], ["sleep_total_h"])

    def test_preview_includes_every_conflicting_value(self):
        conflicts = [("Health Metrics", (f"2026-03-{day:02}",), "steps", 100, 200)
                     for day in range(1, 13)]
        lines = import_conflicts.format_import_conflicts(conflicts)
        self.assertEqual(len(lines), 13)
        self.assertIn("2026-03-12 steps: 100 -> 200", lines[-1])

    def test_workout_blank_clear_is_conflict_and_other_start_is_distinct(self):
        existing = [{"date": "2026-03-28", "start": "10:00:00", "distance_km": 3.0,
                     "avg_hr": 120, "incidental": True, "notes": "manual"}]
        with patch.object(import_conflicts, "read_workout_sessions", return_value=existing):
            incoming = [{"date": "2026-03-28", "start": "10:00:00"},
                        {"date": "2026-03-28", "start": "11:00:00", "distance_km": 4}]
            conflicts = import_conflicts.find_import_conflicts("Test", [], [], [], incoming)
        self.assertEqual([(c[2], c[3], c[4]) for c in conflicts], [("distance_km", 3.0, None)])

    def test_sleep_efficiency_recalculation_cannot_silently_replace_manual_value(self):
        existing = [{"date": "2026-03-28", "total_h": 8, "time_in_bed_h": 10,
                     "efficiency_pct": 85}]
        incoming = [{"date": "2026-03-28", "total_h": 8}]
        with patch.object(import_conflicts, "read_sleep_nights", return_value=existing):
            conflicts = import_conflicts.find_import_conflicts("Test", [], incoming, [], [])
        self.assertEqual([(c[2], c[3], c[4]) for c in conflicts], [("efficiency_pct", 85, 80.0)])

    def test_paired_apply_checks_later_conflict_and_projects_manual_sleep(self):
        for person in ("First", "Second"):
            (self.root / person / "data").mkdir(parents=True)
        sleep_row = hek.build_sleep_payload(self.payload, None, None)[0]
        workout = self.root / "manual.json"
        workout.write_text(json.dumps({"sleep": [{"date": sleep_row["date"],
                                                   "total_h": sleep_row["total_h"] + 1}]}))
        args = ["prepare", "--entry", "First", "-", str(workout),
                "--entry", "Second", str(self.export), str(workout), "--apply"]
        # Separate files for the two entries, since each payload must be unique.
        other = self.root / "other.json"
        other.write_text(json.dumps({"bodyweight": [{"date": "2026-03-28", "kg": 70}]}))
        args[args.index("First") + 2] = str(other)
        with patch.object(prepare, "person_dir", side_effect=lambda p: self.root / p), \
             patch.object(sys, "argv", args), patch.object(prepare.subprocess, "run") as run, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(prepare.main(), 1)
        run.assert_not_called()

    def test_cli_preview_reject_and_explicit_override(self):
        day = next(r for r in hek.build_health_payload(self.payload, None, None)
                   if r.get("steps") is not None)
        csv_store.upsert_health_metrics("Test", [{"date": day["date"], "steps": day["steps"] + 1}])
        data = person_paths.data_dir("Test")
        before = {p.relative_to(data): p.read_bytes() for p in data.rglob("*.csv")}
        env = dict(os.environ, WORKOUT_TRACKER_ROOT=str(self.root))
        cmd = [sys.executable, str(ROOT / "shared/import_health_export_kit.py"),
               "--person", "Test", "--export", str(self.export), "--keep-export"]
        preview = subprocess.run(cmd + ["--dry-run"], env=env, capture_output=True, text=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("Import conflicts:", preview.stdout)
        rejected = subprocess.run(cmd, env=env, capture_output=True, text=True)
        self.assertEqual(rejected.returncode, 3)
        self.assertIn("--overwrite-existing", rejected.stderr)
        self.assertTrue(self.export.exists())
        self.assertEqual(before, {p.relative_to(data): p.read_bytes() for p in data.rglob("*.csv")})
        applied = subprocess.run(cmd + ["--overwrite-existing"], env=env, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("Import conflicts:", applied.stdout)

    def test_monthly_import_metadata_only_fills_empty_cells(self):
        monthly_csv.upsert_rows("Test", "2026.03", [{"date": "2026-03-28", "num": 1,
            "exercise": "Hack Squat", "set": 1, "reps": 10, "kg": 40}])
        monthly_csv.upsert_monthly_strength_session("Test", [{"date": "2026-03-28", "total_cal": 500}],
                                                   today_d=date(2026, 3, 29))
        monthly_csv.upsert_monthly_strength_session("Test", [{"date": "2026-03-28", "total_cal": 600,
                                                               "active_cal": 300}], today_d=date(2026, 3, 29))
        strength = next(r for r in monthly_csv.read_monthly("Test", "2026.03") if r["exercise"] == "TOTAL")
        self.assertEqual((strength["total_cal"], strength["active_cal"]), (500, 300))

        cardio = {"date": "2026-03-29", "start": "09:00:00", "exercise": "Outdoor Run",
                  "duration_min": 30, "total_cal": 400}
        monthly_csv.upsert_monthly_cardio("Test", [cardio], today_d=date(2026, 3, 29))
        monthly_csv.upsert_monthly_cardio("Test", [{**cardio, "total_cal": 500, "active_cal": 250}],
                                         today_d=date(2026, 3, 29))
        stored = next(r for r in monthly_csv.read_monthly("Test", "2026.03") if r["exercise"] == "Outdoor Run")
        self.assertEqual((stored["total_cal"], stored["active_cal"]), (400, 250))


if __name__ == "__main__":
    unittest.main()
