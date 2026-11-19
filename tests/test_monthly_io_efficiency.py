from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from shared import monthly_csv, monthly_csv_canonicalize, monthly_csv_upsert, person_paths


class MonthlyIoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = patch.object(person_paths, "WORKOUT_TRACKER_ROOT", Path(self.temp.name))
        root.start()
        self.addCleanup(root.stop)

    def test_changed_manual_and_cardio_month_each_read_and_write_once(self):
        operations = (
            lambda: monthly_csv.upsert_rows("Manual", "2026.05", [{
                "date": "2026-05-12", "num": 1, "exercise": "Hack Squat",
                "set": 1, "reps": 10, "kg": 40,
            }]),
            lambda: monthly_csv.upsert_monthly_cardio("Cardio", [{
                "date": "2026-05-12", "exercise": "Hike", "duration_min": 30,
            }], today_d=date(2026, 5, 15)),
        )
        for operation in operations:
            with self.subTest(operation=operation), \
                 patch.object(monthly_csv_upsert, "_read_csv_rows", wraps=monthly_csv_upsert._read_csv_rows) as read, \
                 patch.object(monthly_csv_upsert, "_write_csv_atomic", wraps=monthly_csv_upsert._write_csv_atomic) as write, \
                 patch.object(monthly_csv_canonicalize, "_read_csv_rows", wraps=monthly_csv_canonicalize._read_csv_rows) as canon_read, \
                 patch.object(monthly_csv_canonicalize, "_write_csv_atomic", wraps=monthly_csv_canonicalize._write_csv_atomic) as canon_write:
                operation()
                self.assertEqual(read.call_count + canon_read.call_count, 1)
                self.assertEqual(write.call_count + canon_write.call_count, 1)

    def test_failed_canonicalization_leaves_existing_month_unchanged(self):
        row = {"date": "2026-05-12", "num": 1, "exercise": "Hack Squat",
               "set": 1, "reps": 10, "kg": 40}
        monthly_csv.upsert_rows("Manual", "2026.05", [row])
        path = person_paths.monthly_csv("Manual", "2026.05")
        before = path.read_bytes()
        with patch.object(monthly_csv_upsert, "_canonicalize_rows", side_effect=ValueError("invalid")):
            with self.assertRaises(ValueError):
                monthly_csv.upsert_rows("Manual", "2026.05", [{**row, "set": 2}])
        self.assertEqual(path.read_bytes(), before)

    def test_manual_batch_decodes_existing_rows_once(self):
        row = {"date": "2026-05-12", "num": 1, "exercise": "Hack Squat",
               "set": 1, "reps": 10, "kg": 40}
        monthly_csv.upsert_rows("Manual", "2026.05", [row])
        _, existing = monthly_csv_upsert._read_csv_rows(
            person_paths.monthly_csv("Manual", "2026.05")
        )
        with patch.object(monthly_csv_upsert, "_row_to_dict", wraps=monthly_csv_upsert._row_to_dict) as decode:
            result = monthly_csv.upsert_rows("Manual", "2026.05", [row] * 100, dry_run=True)
        self.assertEqual(result, {"added": 0, "skipped": 100, "conflicts": 0, "replaced": 0})
        self.assertEqual(decode.call_count, len(existing))


if __name__ == "__main__":
    unittest.main()
