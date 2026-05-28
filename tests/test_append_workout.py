from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


SKILLS_ROOT = Path(__file__).resolve().parents[1]
APPEND_PATH = SKILLS_ROOT / "workout-logger" / "scripts" / "append_workout.py"

spec = importlib.util.spec_from_file_location("append_workout", APPEND_PATH)
append_workout = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(append_workout)


class AppendWorkoutTests(unittest.TestCase):
    def test_write_payload_canonicalizes_touched_month_once(self) -> None:
        rows = [
            {
                "date": "2026-05-28",
                "num": 1,
                "exercise": "Dead Hang",
                "set": 1,
                "reps": 0,
                "kg": 0,
                "duration_min": 0.5,
            }
        ]
        with TemporaryDirectory() as td:
            target = Path(td) / "2026.05.csv"
            with patch.object(append_workout, "monthly_csv_path", return_value=target), \
                 patch.object(append_workout, "monthly_upsert_rows") as upsert:
                status = append_workout.write_payload("person_a", rows, [])

        upsert.assert_called_once()
        self.assertIn("Appended 1 row(s) to 2026.05 (new sheet)", status[0])


if __name__ == "__main__":
    unittest.main()
