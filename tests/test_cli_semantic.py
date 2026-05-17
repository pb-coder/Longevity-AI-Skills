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

    def test_read_tracker_nihad_semantic_golden(self) -> None:
        data = self.read_tracker("Nihad")
        self.assertEqual(len(data["monthly_sessions"]), 3)
        self.assertEqual(len(data["estimated_1rm"]), 2)
        self.assertEqual(data["unknown_exercises"], [])
        self.assertIn("sleep_summary", data)
        self.assertIn("swim_summary", data)
        self.assertIn("thermal_summary", data)
        self.assertGreater(data["estimated_max_hr"], 150)

    def test_read_tracker_fabian_semantic_golden(self) -> None:
        data = self.read_tracker("Fabian")
        self.assertEqual(len(data["monthly_sessions"]), 2)
        self.assertEqual(len(data["estimated_1rm"]), 1)
        self.assertEqual(data["unknown_exercises"], [])
        self.assertNotIn("sleep_summary", data)
        self.assertNotIn("swim_summary", data)
        self.assertGreater(data["estimated_max_hr"], 150)

    def test_maintain_dry_run_is_read_only_and_explainable(self) -> None:
        maintain = str(SKILLS_ROOT / "shared" / "maintain.py")
        nihad = self.run_cmd(maintain, "--person", "Nihad", "--dry-run")
        self.assertEqual(nihad.returncode, 0, nihad.stderr)
        self.assertIn("Dry run", nihad.stdout)
        self.assertIn("health_metrics.csv", nihad.stdout)

        fabian = self.run_cmd(maintain, "--person", "Fabian", "--dry-run")
        self.assertEqual(fabian.returncode, 0, fabian.stderr)
        self.assertIn("Dry run", fabian.stdout)
        self.assertIn("header mismatch", fabian.stdout)


if __name__ == "__main__":
    unittest.main()
