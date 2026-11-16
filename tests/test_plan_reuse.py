"""Prescription history is parsed once while preserving each consumer's horizon."""
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from workout_coach.lib import adherence, blocks
from workout_coach.lib.extract import load_exercises_db


class PlanReuseTests(unittest.TestCase):
    def test_reuse_matches_independent_reads_and_limits_file_parsing(self):
        today = date(2026, 8, 20)
        db = load_exercises_db(Path(__file__).resolve().parents[1] /
                               "shared" / "exercises-database.md")
        catalog = blocks.load_pattern_catalog(db)
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for offset in range(-11, 2):
                day = (today + timedelta(days=offset)).isoformat()
                path = Path(tmp) / f"{day}-workout.md"
                path.write_text("## Workout 1: LOWER\n"
                                "- Barbell Back Squat: 50kgx10 /// 50kgx10\n")
                paths.append((day, path))
            # Retain an unreadable file in the most recent window: it must
            # still occupy a slot in the limit and report its parse error.
            paths[-4][1].unlink()
            paths.insert(0, ("2026-02-30", Path(tmp) / "invalid"))
            with patch("shared.person_paths.list_workout_plans", return_value=paths), \
                 patch.object(adherence, "read_bench_log", return_value={}), \
                 patch.object(blocks, "read_block", return_value=None), \
                 patch.object(adherence, "parse_plan_file", wraps=adherence.parse_plan_file) as parse:
                # The old pipeline parsed the entire eligible series three
                # times before slicing to the 8/3/8 horizons.
                for limit in (8, 3, 8):
                    adherence.load_plans("test", today, db=db)[-limit:]
                self.assertEqual(parse.call_count, 36)
                parse.reset_mock()
                standalone_adherence = adherence.build_adherence(
                    "test", [], db, today, catalog)
                standalone_block = blocks.block_payload(
                    "test", [], db, catalog, today, adherence=standalone_adherence)
                standalone_plans = adherence.load_plans("test", today, limit=8, db=db)
                # 8 + 3 + 8 selected files, one missing in each series.
                self.assertEqual(parse.call_count, 19)
                parse.reset_mock()
                plans = adherence.load_plans("test", today, limit=8, db=db)
                shared_adherence = adherence.build_adherence(
                    "test", [], db, today, catalog, plans=plans)
                shared_block = blocks.block_payload(
                    "test", [], db, catalog, today, adherence=shared_adherence,
                    plans=plans)
                self.assertEqual(parse.call_count, 8)
                self.assertEqual(plans, standalone_plans)
                self.assertEqual(shared_adherence, standalone_adherence)
                self.assertEqual(shared_block, standalone_block)
                self.assertEqual(plans[-1]["plan_date"], today.isoformat())
                self.assertTrue(plans[-3]["parse_errors"])
                self.assertEqual(shared_block["started"], plans[-2]["plan_date"])

    def test_load_limit_zero_still_means_all_eligible_plans(self):
        today = date(2026, 8, 20)
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for day in ("2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"):
                path = Path(tmp) / day
                path.write_text("## Workout 1: UPPER\n- Plank: 30s\n")
                paths.append((day, path))
            with patch("shared.person_paths.list_workout_plans", return_value=paths):
                self.assertEqual(len(adherence.load_plans("test", today, limit=0)), 3)
                self.assertEqual(len(adherence.load_plans("test", today, limit=2)), 2)


if __name__ == "__main__":
    unittest.main()
