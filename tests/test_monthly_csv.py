from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path


from shared import monthly_csv, person_paths


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

    def test_canonicalize_places_total_between_strength_and_cardio_rows(self) -> None:
        rows = [
            ["", "2026-05-12", "1", "Hack Squat",      "1", "6", "40", "",
             "", "", "", "", "", "", "", "", "", "manual"],
            ["", "2026-05-12", "2", "Leg Extension",   "1", "10", "35", "",
             "", "", "", "", "", "", "", "", "", "manual"],
            ["", "2026-05-12", "3", "Outdoor Cycling", "1", "", "", "",
             "", "4.3", "13:54", "", "150", "124", "147", "7", "13:54", "apple"],
            ["", "2026-05-12", "4", "Outdoor Cycling", "1", "", "", "",
             "", "2.7", "10:12", "", "127", "74",  "90",  "3", "10:12", "apple"],
        ]
        path = self.write_month("2026.05", monthly_csv.MONTHLY_HEADERS, rows)
        monthly_csv.canonicalize_monthly_csv("Test", "2026.05")
        _, out = self.read_rows(path)

        exercises = [r[3] for r in out]
        self.assertEqual(
            exercises,
            ["Hack Squat", "Leg Extension", monthly_csv.TOTAL_LABEL,
             "Outdoor Cycling", "Outdoor Cycling"],
        )

    def test_canonicalize_keeps_manual_isometric_holds_with_strength_rows(self) -> None:
        rows = [
            ["", "2026-05-14", "1", "Jumping Jacks",     "1", "50", "0", "",
             "", "", "", "", "", "", "", "", "", "manual"],
            ["", "2026-05-14", "2", "Dead Hang",         "1", "0",  "0", "",
             "", "", "0:30", "", "", "", "", "", "", "manual"],
            ["", "2026-05-14", "3", "Cable Lat Pulldown","1", "8",  "57.5", "",
             "", "", "", "", "", "", "", "", "", "manual"],
        ]
        path = self.write_month("2026.05", monthly_csv.MONTHLY_HEADERS, rows)
        monthly_csv.canonicalize_monthly_csv("Test", "2026.05")
        _, out = self.read_rows(path)

        exercises = [r[3] for r in out]
        self.assertEqual(
            exercises,
            ["Jumping Jacks", "Dead Hang", "Cable Lat Pulldown",
             monthly_csv.TOTAL_LABEL],
        )

    def test_canonicalize_keeps_isometric_hold_duration_on_row(self) -> None:
        rows = [
            ["", "2026-05-14", "1", "Dead Hang",         "1", "0",  "0", "",
             "", "", "0:30", "", "", "", "", "", "", "manual"],
            ["", "2026-05-14", "2", "Cable Lat Pulldown","1", "8",  "57.5", "",
             "", "", "", "", "", "", "", "", "", "manual"],
        ]
        path = self.write_month("2026.05", monthly_csv.MONTHLY_HEADERS, rows)
        monthly_csv.canonicalize_monthly_csv("Test", "2026.05")
        _, out = self.read_rows(path)

        dead_hang = [r for r in out if r[3] == "Dead Hang"][0]
        total = [r for r in out if r[3] == monthly_csv.TOTAL_LABEL][0]
        # Per-set hold time stays on the Dead Hang row.
        self.assertEqual(dead_hang[10], "0:30")
        # And does NOT bubble up to the strength session's TOTAL row.
        self.assertEqual(total[10], "")

    def test_canonicalize_renumbers_duplicate_num_across_strength_and_cardio(self) -> None:
        # Strength /log-ged AFTER cardio importer ran: both numbered 1..N
        # from their respective writers. Canonicalize must renumber.
        rows = [
            ["", "2026-05-11", "1", "Outdoor Cycling",     "1", "",  "",  "",
             "", "3.7", "14:06", "", "150", "120", "150", "20", "14:06", "apple"],
            ["", "2026-05-11", "2", "Outdoor Cycling",     "1", "",  "",  "",
             "", "0.9", "6:18",  "", "138", "46",  "56",  "8",  "6:18",  "apple"],
            ["", "2026-05-11", "1", "Hack Squat",          "1", "8", "40", "",
             "", "", "", "", "", "", "", "", "", "manual"],
            ["", "2026-05-11", "2", "Leg Extension",       "1", "10","35", "",
             "", "", "", "", "", "", "", "", "", "manual"],
        ]
        path = self.write_month("2026.05", monthly_csv.MONTHLY_HEADERS, rows)
        monthly_csv.canonicalize_monthly_csv("Test", "2026.05")
        _, out = self.read_rows(path)

        # Expected emit order: 2 strength exercises, TOTAL, 2 cardio
        # rides (cardio rows get fresh num per row — each ride is its
        # own workout even with the same exercise name).
        nums = [r[2] for r in out]
        exercises = [r[3] for r in out]
        self.assertEqual(exercises, [
            "Hack Squat", "Leg Extension",
            monthly_csv.TOTAL_LABEL,
            "Outdoor Cycling", "Outdoor Cycling",
        ])
        self.assertEqual(nums, ["1", "2", "", "3", "4"])

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
        self.assertIn("2026.04: 1 (Hike=1)", "\n".join(summary))
        self.assertIn("--allow-past-months", "\n".join(summary))

    def test_auto_cardio_past_month_gate_reports_month_and_type_breakdown(self) -> None:
        summary = monthly_csv.upsert_monthly_cardio(
            "Test",
            [
                {"date": "2026-03-20", "exercise": "Hike", "duration_min": 45},
                {"date": "2026-04-20", "exercise": "Outdoor Run", "duration_min": 30},
                {"date": "2026-04-21", "exercise": "Outdoor Run", "duration_min": 31},
            ],
            today_d=date(2026, 5, 15),
        )
        text = "\n".join(summary)
        self.assertIn("3 input rows skipped", text)
        self.assertIn("2026.03: 1 (Hike=1)", text)
        self.assertIn("2026.04: 2 (Outdoor Run=2)", text)


if __name__ == "__main__":
    unittest.main()
