from __future__ import annotations

import importlib.util
import json
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
                upsert.return_value = {"added": 1, "skipped": 0, "replaced": 0, "conflicts": 0}
                status = append_workout.write_payload("person_a", rows, [])

        upsert.assert_called_once()
        self.assertIn("Appended 1 row(s) to 2026.05 (new sheet)", status[0])

    def test_load_payload_rejects_non_iso_dates(self) -> None:
        with TemporaryDirectory() as td:
            payload = Path(td) / "payload.json"
            payload.write_text(json.dumps({
                "rows": [{
                    "date": "2026-5-28",
                    "num": 1,
                    "exercise": "Dead Hang",
                    "set": 1,
                }]
            }))

            with self.assertRaises(ValueError):
                append_workout.load_payload(str(payload))

    def test_load_payload_rejects_impossible_calendar_dates(self) -> None:
        with TemporaryDirectory() as td:
            payload = Path(td) / "payload.json"
            payload.write_text(json.dumps({"rows": [{"date": "2026-11-31",
                "num": 1, "exercise": "Dead Hang", "set": 1}]}))
            with self.assertRaisesRegex(ValueError, "calendar date"):
                append_workout.load_payload(str(payload))

    def test_invalid_optional_data_is_rejected_before_any_write(self) -> None:
        cases = [
            {"bodyweight": [{"date": "2026-05-28", "kg": "heavy"}]},
            {"bodyweight": [{"date": "2026-05-28", "kg": "NaN"}]},
            {"css_test": {"t400_sec": 100, "t200_sec": 200}},
            {"css_test": {"t400_sec": "fast", "t200_sec": 200}},
            {"css_test": {}},
            {"sleep": [{"date": "2026-05-28", "total_h": "unknown"}]},
            {"nutrition_phase": [{"start_date": "2026-05-28", "phase_type": "other"}]},
            {"nutrition_phase": [{"start_date": "2026-05-28", "end_date": "2026-02-31"}]},
        ]
        with TemporaryDirectory() as td:
            payload = Path(td) / "payload.json"
            for case in cases:
                with self.subTest(case=case):
                    payload.write_text(json.dumps(case))
                    with self.assertRaises(ValueError):
                        append_workout.load_payload(str(payload))

    def test_optional_data_accepts_numeric_strings_and_partial_updates(self) -> None:
        data = {"bodyweight": {"date": "2026-05-28", "kg": "80.5"},
                "css_test": {"t400_sec": "450", "t200_sec": "210"},
                "sleep": {"date": "2026-05-28", "total_h": "7.5"},
                "nutrition_phase": {"start_date": "2026-05-28", "end_date": "2026-06-01"}}
        with TemporaryDirectory() as td:
            payload = Path(td) / "payload.json"
            payload.write_text(json.dumps(data))
            self.assertEqual(len(append_workout.load_payload(str(payload))[1]), 1)

    def test_structured_context_is_preserved_and_validated(self) -> None:
        row = {"date": "2026-05-28", "num": 1, "exercise": "Cable Seated Row",
               "set": 1, "reps": 10, "kg": 40, "gym": "A", "machine": "Cable 1",
               "load_basis": "total"}
        with TemporaryDirectory() as td:
            payload = Path(td) / "payload.json"
            payload.write_text(json.dumps({"rows": [row]}))
            parsed = append_workout.load_payload(str(payload))[0][0]
            stored = append_workout._to_monthly_row(parsed)
            self.assertEqual((stored["gym"], stored["machine"], stored["load_basis"]),
                             ("A", "Cable 1", "total"))
            for key, invalid in (("gym", 12), ("machine", []), ("load_basis", "maybe"), ("load_basis", [])):
                bad = {**row, key: invalid}
                payload.write_text(json.dumps({"rows": [bad]}))
                with self.assertRaises(ValueError):
                    append_workout.load_payload(str(payload))

    def test_retired_payload_categories_fail_before_any_write(self) -> None:
        for category in ("thermal", "light_therapy"):
            with self.subTest(category=category), TemporaryDirectory() as td:
                payload = Path(td) / "payload.json"
                payload.write_text(json.dumps({
                    "bodyweight": [{"date": "2026-06-01", "kg": 80}],
                    category: [{"date": "2026-06-01"}],
                }))
                with self.assertRaisesRegex(ValueError, "Retired logging categories"):
                    append_workout.load_payload(str(payload))

    def test_cli_rejects_retired_categories_without_writing_or_committing(self) -> None:
        with TemporaryDirectory() as td:
            payload = Path(td) / "payload.json"
            payload.write_text(json.dumps({"thermal": [{"date": "2026-06-01"}]}))
            with patch("sys.argv", ["append_workout.py", "--person", "Test", str(payload)]), \
                 patch.object(append_workout, "write_payload") as write, \
                 patch.object(append_workout, "commit_data") as commit, \
                 patch("sys.stderr"):
                self.assertEqual(append_workout.main(), 1)
            write.assert_not_called()
            commit.assert_not_called()

    def test_cli_commits_partial_writes_and_fails_on_conflicts(self) -> None:
        with TemporaryDirectory() as td:
            payload = Path(td) / "payload.json"
            payload.write_text(json.dumps({"rows": [{"date": "2026-05-28", "num": 1,
                "exercise": "Dead Hang", "set": 1}]}))
            with patch("sys.argv", ["append_workout.py", "--person", "Test", str(payload)]), \
                 patch.object(append_workout, "write_payload", return_value=[
                     "Appended 1 row(s)", "WARN: conflicting sets were not changed"]), \
                 patch.object(append_workout, "commit_data") as commit, patch("sys.stdout"):
                self.assertEqual(append_workout.main(), 2)
            commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
