from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[1]


class RenderDashboardSmokeTests(unittest.TestCase):
    def test_render_dashboard_imports_split_card_modules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            tracker_json = tmp / "tracker.json"
            coach_json = tmp / "coach_reads.json"
            workout_md = tmp / "workout.md"
            out_html = tmp / "assessment.html"

            read_proc = subprocess.run(
                [
                    sys.executable,
                    "workout-coach/scripts/read_tracker.py",
                    "--person",
                    "Nihad",
                    "--today",
                    "2026-05-28",
                ],
                cwd=SKILLS_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(read_proc.returncode, 0, read_proc.stderr)
            tracker_json.write_text(read_proc.stdout, encoding="utf-8")
            coach_json.write_text(
                json.dumps({"headline": "Train as planned.", "cards": {}}),
                encoding="utf-8",
            )
            workout_md.write_text("# Workout\n- Test session\n", encoding="utf-8")

            render_proc = subprocess.run(
                [
                    sys.executable,
                    "workout-coach/scripts/render_dashboard.py",
                    "--tracker",
                    str(tracker_json),
                    "--coach",
                    str(coach_json),
                    "--workout-md",
                    str(workout_md),
                    "--out",
                    str(out_html),
                    "--person",
                    "Nihad",
                ],
                cwd=SKILLS_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(render_proc.returncode, 0, render_proc.stderr)
            html = out_html.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", html)
            self.assertIn("data-tab=\"today\"", html)


if __name__ == "__main__":
    unittest.main()
