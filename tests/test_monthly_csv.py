from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILLS_ROOT))
sys.path.insert(0, str(SKILLS_ROOT / "shared"))

import person_paths  # noqa: E402
import monthly_csv  # noqa: E402


class MonthlyCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = person_paths.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = Path(self.tmp.name)

    def tearDown(self) -> None:
        person_paths.WORKOUT_TRACKER_ROOT = self.old_root
        self.tmp.cleanup()

    def write_month(self, ym: str, header: list[str], rows: list[list]) -> Path:
        path = person_paths.monthly_csv("Test", ym)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def read_rows(self, path: Path) -> tuple[list[str], list[list[str]]]:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            return next(reader), list(reader)

    def test_canonicalize_migrates_17_columns_rebuilds_total_and_is_idempotent(self) -> None:
        old_header = monthly_csv.MONTHLY_HEADERS[:-1]
        row = [
            "", "2026-05-10", "1", "Dumbbell Row", "1", "10", "20", "",
            "", "", "", "", "", "", "", "", "",
        ]
        path = self.write_month("2026.05", old_header, [row])

        monthly_csv.canonicalize_monthly_csv("Test", "2026.05")
        first = path.read_text(encoding="utf-8")
        monthly_csv.canonicalize_monthly_csv("Test", "2026.05")
        second = path.read_text(encoding="utf-8")

        header, rows = self.read_rows(path)
        self.assertEqual(header, monthly_csv.MONTHLY_HEADERS)
        self.assertEqual(first, second)
        self.assertEqual(rows[0][7], "200")
        self.assertEqual(rows[0][-1], "manual")
        self.assertEqual(rows[1][3], monthly_csv.TOTAL_LABEL)
        self.assertEqual(rows[1][7], "200")

    def test_auto_cardio_respects_manual_row_and_current_month_gate(self) -> None:
        manual = [
            "", "2026-05-11", "1", "Hike", "1", "", "", "",
            "", "5", "60:00", "12:00", "", "", "", "", "", "manual",
        ]
        path = self.write_month("2026.05", monthly_csv.MONTHLY_HEADERS, [manual])

        summary = monthly_csv.upsert_monthly_cardio(
            "Test",
            [{"date": "2026-05-11", "exercise": "Hike", "duration_min": 60, "distance_km": 5}],
            today_d=date(2026, 5, 15),
        )
        _, rows = self.read_rows(path)
        hikes = [r for r in rows if len(r) > 3 and r[3] == "Hike"]
        self.assertEqual(len(hikes), 1)
        self.assertIn("0 cardio rows appended", "\n".join(summary))

        summary = monthly_csv.upsert_monthly_cardio(
            "Test",
            [{"date": "2026-04-20", "exercise": "Hike", "duration_min": 45, "distance_km": 4}],
            today_d=date(2026, 5, 15),
        )
        self.assertFalse(person_paths.monthly_csv("Test", "2026.04").exists())
        self.assertIn("past months are not re-scanned", "\n".join(summary))


if __name__ == "__main__":
    unittest.main()
