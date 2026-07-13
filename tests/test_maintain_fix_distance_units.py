from __future__ import annotations

import csv
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from shared import csv_store, maintain, monthly_csv, person_paths


class MaintainFixDistanceUnitsTests(unittest.TestCase):
    """Regression tests for shared/maintain.py --fix-distance-units — the
    legacy meter-as-km swim distance sweep across monthly CSVs and
    workout_sessions.csv. Previously untested despite mutating historical
    data.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = person_paths.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = Path(self.tmp.name)
        csv_store.write_profile("Test", source="xml", auto_cardio=True)

    def tearDown(self) -> None:
        person_paths.WORKOUT_TRACKER_ROOT = self.old_root
        self.tmp.cleanup()

    def write_month(self, ym: str, rows: list[list]) -> Path:
        path = person_paths.monthly_csv("Test", ym)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(monthly_csv.MONTHLY_HEADERS)
            writer.writerows(rows)
        return path

    def read_rows(self, path: Path) -> tuple[list[str], list[list[str]]]:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            return next(reader), list(reader)

    def test_swim_distance_over_10km_divided_and_pace_recomputed(self) -> None:
        # 550 (metres mis-stored as km) is well over the 10 km suspicious
        # threshold and must be divided by 1000, with pace recomputed from
        # the corrected distance rather than left stale.
        row = [
            "", "2026-05-14", "1", "Swim", "1", "", "", "",
            "", "550", "20", "", "", "", "", "", "", "manual",
        ]
        path = self.write_month("2026.05", [row])

        with redirect_stdout(StringIO()):
            rc = maintain.fix_distance_units("Test", dry_run=False)

        self.assertEqual(rc, 0)
        header, rows = self.read_rows(path)
        dist_idx = header.index("Distance (km)")
        pace_idx = header.index("Pace (min/km)")
        self.assertEqual(rows[0][dist_idx], "0.55")
        self.assertEqual(rows[0][pace_idx], "36:22")

    def test_legitimate_non_swim_distance_is_flagged_not_mutated(self) -> None:
        # A non-swim row with an implausible pace is only ever flagged for
        # manual review — the sweep must never auto-mutate Run/Cycle/Walk/
        # Hike rows the way it does for the known swim bug.
        rows = [
            [
                "", "2026-05-14", "1", "Swim", "1", "", "", "",
                "", "550", "20", "", "", "", "", "", "", "manual",
            ],
            [
                "", "2026-05-14", "2", "Outdoor Run", "1", "", "", "",
                "", "20", "5", "", "", "", "", "", "", "manual",
            ],
        ]
        path = self.write_month("2026.05", rows)

        out = StringIO()
        with redirect_stdout(out):
            maintain.fix_distance_units("Test", dry_run=False)

        self.assertIn("flag [monthly/2026.05.csv row 3]", out.getvalue())
        self.assertIn("Outdoor Run", out.getvalue())

        header, out_rows = self.read_rows(path)
        dist_idx = header.index("Distance (km)")
        run_row = [r for r in out_rows if r[3] == "Outdoor Run"][0]
        self.assertEqual(run_row[dist_idx], "20")

    def test_dry_run_reports_fix_without_mutating_file(self) -> None:
        row = [
            "", "2026-05-14", "1", "Swim", "1", "", "", "",
            "", "550", "20", "", "", "", "", "", "", "manual",
        ]
        path = self.write_month("2026.05", [row])
        before_text = path.read_text(encoding="utf-8")

        out = StringIO()
        with redirect_stdout(out):
            maintain.fix_distance_units("Test", dry_run=True)

        self.assertIn("550.0 → 0.55 km", out.getvalue())
        self.assertIn("Dry run", out.getvalue())
        self.assertEqual(path.read_text(encoding="utf-8"), before_text)

    def test_rerun_is_idempotent(self) -> None:
        row = [
            "", "2026-05-14", "1", "Swim", "1", "", "", "",
            "", "550", "20", "", "", "", "", "", "", "manual",
        ]
        path = self.write_month("2026.05", [row])

        with redirect_stdout(StringIO()):
            maintain.fix_distance_units("Test", dry_run=False)
        first_text = path.read_text(encoding="utf-8")

        out = StringIO()
        with redirect_stdout(out):
            maintain.fix_distance_units("Test", dry_run=False)
        second_text = path.read_text(encoding="utf-8")

        self.assertIn("no fixes needed", out.getvalue())
        self.assertEqual(first_text, second_text)

    def test_workout_sessions_csv_swim_distance_also_fixed(self) -> None:
        csv_store.upsert_workout_sessions(
            "Test",
            [{
                "date": "2026-05-14", "start": "07:00:00",
                "apple_type": "Swimming", "duration_min": 20,
                "distance_km": 550,
            }],
        )
        ws_path = person_paths.workout_sessions_csv("Test")

        with redirect_stdout(StringIO()):
            maintain.fix_distance_units("Test", dry_run=False)

        header, rows = self.read_rows(ws_path)
        dist_idx = header.index("Distance (km)")
        self.assertEqual(rows[0][dist_idx], "0.55")


if __name__ == "__main__":
    unittest.main()
