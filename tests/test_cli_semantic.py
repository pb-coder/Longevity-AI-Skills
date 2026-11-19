from __future__ import annotations

import json
import csv
import os
import shutil
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = SKILLS_ROOT / "tests" / "fixtures"


class CliSemanticTests(unittest.TestCase):
    maxDiff = None

    def run_cmd(self, *args: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["WORKOUT_TRACKER_ROOT"] = str(FIXTURE_ROOT)
        return subprocess.run(
            [sys.executable, *args],
            cwd=FIXTURE_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def read_tracker(self, person: str) -> dict:
        proc = self.run_cmd(
            str(SKILLS_ROOT / "workout-coach" / "scripts" / "read_tracker.py"),
            "--person", person,
            "--today", "2026-05-17",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        # The coaching boundary exposes today's decision and measured trends,
        # without recomputed decision history or report-only display series.
        self.assertIn("session_recommendation", data)
        self.assertIn("health_metrics_weekly", data)
        for retired in ("tier_history", "week_over_week", "bodyweight_weekly"):
            self.assertNotIn(retired, data)
        return data

    def test_reader_argument_validation(self) -> None:
        reader = str(SKILLS_ROOT / "workout-coach" / "scripts" / "read_tracker.py")
        valid = self.run_cmd(reader, "--person=person_a", "--today=2026-05-17",
                             "--weekly", "--sessions=2", "--minutes=35")
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertIn("weekly_plan", json.loads(valid.stdout))
        for flags, message in (
            ([], "required: --person"),
            (["--person", "person_a", "--sessions", "0"], "count from 1 to 14"),
            (["--person", "person_a", "--weekly", "--minutes", "0"], "positive minutes"),
            (["--person", "person_a", "--minutes", "30"], "require --weekly"),
            (["--person", "person_a", "--weekly", "--override-gate"], "dated session analysis"),
            (["--person", "person_a", "--unknown"], "unrecognized arguments"),
        ):
            with self.subTest(flags=flags):
                proc = self.run_cmd(reader, *flags)
                self.assertEqual(proc.returncode, 2)
                self.assertIn(message, proc.stderr)

    def test_read_tracker_person_a_semantic_golden(self) -> None:
        data = self.read_tracker("person_a")
        self.assertEqual(len(data["monthly_sessions"]), 3)
        self.assertEqual(len(data["estimated_1rm"]), 2)
        self.assertEqual(data["unknown_exercises"], [])
        self.assertIn("sleep_summary", data)
        self.assertIn("swim_summary", data)
        self.assertNotIn("thermal_summary", data)
        self.assertNotIn("light_therapy_summary", data)
        self.assertNotIn("thermal_log", data["capabilities"])
        self.assertNotIn("light_therapy_log", data["capabilities"])
        self.assertGreater(data["estimated_max_hr"], 150)

    def test_read_tracker_person_b_semantic_golden(self) -> None:
        data = self.read_tracker("person_b")
        self.assertEqual(data["data_source"], "health_auto_export")
        self.assertEqual(len(data["monthly_sessions"]), 2)
        self.assertEqual(len(data["estimated_1rm"]), 1)
        self.assertEqual(data["unknown_exercises"], [])
        self.assertIn("sleep_summary", data)
        self.assertNotIn("swim_summary", data)
        self.assertNotIn("light_therapy_summary", data)
        self.assertTrue(data["capabilities"]["hrv"])
        self.assertTrue(data["capabilities"]["per_workout_hr_strength"])
        self.assertNotIn("light_therapy_log", data["capabilities"])
        self.assertGreater(data["estimated_max_hr"], 150)

    def test_weekly_reader_has_explicit_future_window_and_no_daily_gate(self) -> None:
        reader = str(SKILLS_ROOT / "workout-coach" / "scripts" / "read_tracker.py")
        before = self.run_cmd(
            reader, "--person", "person_a", "--today", "2026-05-17", "--weekly",
            "--training-days", "2026-05-18,2026-05-22", "--minutes", "35",
        )
        self.assertEqual(before.returncode, 0, before.stderr)
        body = json.loads(before.stdout)
        self.assertEqual(body["weekly_plan"], {
            "as_of": "2026-05-17", "week_start": "2026-05-18", "week_end": "2026-05-24",
            "training_days": ["2026-05-18", "2026-05-22"],
            "session_count": 2, "session_target_min": 35, "person": "person_a",
        })
        self.assertNotIn("session_recommendation", body)
        self.assertNotIn("muscle_floors", body)
        self.assertEqual(body["next_dose"]["load_policy"], "progress")
        self.assertEqual(body["observation_coverage"]["unrecorded_training"], "unknown")
        self.assertEqual(body["observation_coverage"]["health_imports"], {"state": "unknown"})

        later = self.run_cmd(
            reader, "--person", "person_a", "--today", "2026-05-27",
            "--weekly", "--sessions", "2", "--minutes", "35",
        )
        self.assertEqual(later.returncode, 0, later.stderr)
        stale = json.loads(later.stdout)
        self.assertEqual(stale["target_working_sets"], body["target_working_sets"])
        self.assertEqual(stale["next_dose"]["load_policy"], "progress")
        self.assertNotIn("session_recommendation", stale)

    def test_weekly_reader_rejects_days_outside_the_plan(self) -> None:
        proc = self.run_cmd(
            str(SKILLS_ROOT / "workout-coach" / "scripts" / "read_tracker.py"),
            "--person", "person_a", "--today", "2026-05-17", "--weekly",
            "--training-days", "2026-05-17",
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("available planning period", proc.stderr)

    def test_retired_recovery_files_do_not_affect_coaching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(FIXTURE_ROOT / "person_b", root / "person_b")
            env = os.environ.copy()
            env["WORKOUT_TRACKER_ROOT"] = str(root)

            def payload() -> dict:
                proc = subprocess.run(
                    [sys.executable, str(SKILLS_ROOT / "workout-coach" / "scripts" /
                                         "read_tracker.py"), "--person", "person_b",
                     "--today", "2026-05-17"],
                    cwd=root, env=env, text=True, capture_output=True,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                return json.loads(proc.stdout)

            before = payload()
            data_dir = root / "person_b" / "data"
            for name in ("thermal", "light_therapy"):
                folder = data_dir / name
                folder.mkdir()
                # Even malformed archived files must never be consulted.
                (folder / "2026.05.sessions.csv").write_text("retired archive\n")
            with (data_dir / "profile.csv").open("a") as profile:
                profile.write("\nsauna_target_per_week,99\n"
                              "light_therapy_target_per_week,99\n"
                              "light_therapy_target_min_per_session,999\n")
            self.assertEqual(before, payload())

    def test_bodyweight_trend_excludes_annotated_evening_readings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(FIXTURE_ROOT / "person_a", root / "person_a")
            with (root / "person_a/data/health_metrics.csv").open("w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Date", "Bodyweight (kg)", "Notes"])
                writer.writerows([
                    ["2026-04-20", 70, ""], ["2026-04-27", 70.1, ""],
                    ["2026-05-04", 70, ""], ["2026-05-11", 70.1, ""],
                    ["2026-05-17", 75, "evening, after meal"],
                ])
            env = os.environ.copy()
            env["WORKOUT_TRACKER_ROOT"] = str(root)
            proc = subprocess.run(
                [sys.executable, str(SKILLS_ROOT / "workout-coach/scripts/read_tracker.py"),
                 "--person", "person_a", "--today", "2026-05-17"],
                cwd=root, env=env, text=True, capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["bodyweight_trend"]["n_readings"], 4)
            # Latest is still the recorded measurement; only trend evidence
            # excludes observations with incompatible measurement context.
            self.assertEqual(data["bodyweight_latest"], {"date": "2026-05-17", "kg": 75.0})

    def test_maintain_dry_run_is_read_only_and_explainable(self) -> None:
        maintain = str(SKILLS_ROOT / "shared" / "maintain.py")
        person_a = self.run_cmd(maintain, "--person", "person_a", "--dry-run")
        self.assertEqual(person_a.returncode, 0, person_a.stderr)
        self.assertIn("Dry run", person_a.stdout)
        self.assertIn("health_metrics.csv", person_a.stdout)

        person_b = self.run_cmd(maintain, "--person", "person_b", "--dry-run")
        self.assertEqual(person_b.returncode, 0, person_b.stderr)
        self.assertIn("Dry run", person_b.stdout)
        self.assertIn("health_metrics.csv", person_b.stdout)

    def test_public_cli_help_commands_import_cleanly(self) -> None:
        commands = [
            ("shared/import_health_export_kit.py", "--help"),
            ("shared/canonicalize_logs.py", "--help"),
            ("workout-logger/scripts/append_workout.py", "--help"),
        ]
        for script, arg in commands:
            with self.subTest(script=script):
                proc = subprocess.run(
                    [sys.executable, script, arg],
                    cwd=SKILLS_ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("usage:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
