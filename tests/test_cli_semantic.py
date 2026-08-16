from __future__ import annotations

import json
import os
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
        return json.loads(proc.stdout)

    def test_read_tracker_person_a_semantic_golden(self) -> None:
        data = self.read_tracker("person_a")
        self.assertEqual(len(data["monthly_sessions"]), 3)
        self.assertEqual(len(data["estimated_1rm"]), 2)
        self.assertEqual(data["unknown_exercises"], [])
        self.assertIn("sleep_summary", data)
        self.assertIn("swim_summary", data)
        self.assertIn("thermal_summary", data)
        self.assertIn("light_therapy_summary", data)
        self.assertEqual(data["light_therapy_summary"]["n_sessions_28d"], 1)
        self.assertEqual(data["light_therapy_summary"]["dominant_light_type"], "red+ir")
        self.assertEqual(data["light_therapy_summary"]["dominant_modality"], "cabin")
        self.assertTrue(data["capabilities"]["light_therapy_log"])
        self.assertGreater(data["estimated_max_hr"], 150)

    def test_read_tracker_person_b_semantic_golden(self) -> None:
        data = self.read_tracker("person_b")
        self.assertEqual(data["data_source"], "health_auto_export")
        self.assertEqual(len(data["monthly_sessions"]), 2)
        self.assertEqual(len(data["estimated_1rm"]), 1)
        self.assertEqual(data["unknown_exercises"], [])
        self.assertIn("sleep_summary", data)
        self.assertNotIn("swim_summary", data)
        # person_b has no light_therapy/ folder yet → key absent.
        self.assertNotIn("light_therapy_summary", data)
        self.assertTrue(data["capabilities"]["hrv"])
        self.assertTrue(data["capabilities"]["per_workout_hr_strength"])
        self.assertTrue(data["capabilities"]["light_therapy_log"])
        self.assertGreater(data["estimated_max_hr"], 150)

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
            ("shared/import_health_auto_export.py", "--help"),
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
