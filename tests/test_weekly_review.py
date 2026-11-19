"""Regression tests for dated observations and late batch coverage."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from shared import person_paths
from shared.health_import_receipts import read_health_import_receipts, record_health_import
from workout_coach.lib.weekly_review import observation_coverage, week_context


class WeeklyReviewTests(unittest.TestCase):
    def test_weekend_window_can_cross_calendar_year(self):
        week = week_context(date(2028, 12, 30), None, None, 4, 60)
        self.assertEqual(week["week_start"], "2029-01-01")
        self.assertEqual(week["week_end"], "2029-01-07")

    def test_midweek_revision_uses_live_week_and_retains_past_slots(self):
        review = date(2026, 11, 25)
        records = [{"prescription": {
            "week_start": "2026-11-23", "week_end": "2026-11-29",
            "sessions": [{"date": "2026-11-23"}, {"date": "2026-11-26"}],
        }}]
        context = week_context(review, None, "2026-11-27", None, 40, records)
        self.assertEqual(context["week_start"], "2026-11-23")
        self.assertEqual(context["training_days"], ["2026-11-23", "2026-11-27"])
        self.assertEqual(context["session_count"], 2)

    def test_export_coverage_does_not_fabricate_observations_or_rest(self):
        coverage = observation_coverage(
            date(2026, 5, 22),
            [{"date": "2026-05-08", "bodyweight_kg": 70},
             {"date": "2026-05-19", "resting_hr": 55}],
            [{"date": "2026-05-20", "total_h": 7}],
            [],
            [{"date": "2026-05-14"}, {"date": "2026-05-14"}],
            {"hrv": False},
            [
                {"source": "health_export_kit", "imported_on": "2026-05-20",
                 "imported_at": "2026-05-20T16:00:00+00:00", "applied_through": "2026-05-20"},
                {"source": "health_export_kit", "imported_on": "2026-05-21",
                 "imported_at": "2026-05-21T16:00:00+00:00", "applied_through": "2026-05-04"},
                {"source": "health_export_kit", "imported_on": "2026-05-23",
                 "imported_at": "2026-05-23T16:00:00+00:00", "applied_through": "2026-05-23"},
            ],
        )
        self.assertEqual(coverage["health_imports"]["max_applied_through"], "2026-05-20")
        self.assertEqual(coverage["health_imports"]["latest_import"]["applied_through"], "2026-05-04")
        self.assertEqual(coverage["unrecorded_training"], "unknown")
        self.assertEqual(coverage["metrics"]["strength_sets"]["observed_days_14d"], 1)
        self.assertEqual(coverage["metrics"]["bodyweight"]["latest_observed"], "2026-05-08")
        self.assertEqual(coverage["metrics"]["bodyweight"]["observed_days_14d"], 0)
        self.assertEqual(coverage["metrics"]["hrv"]["state"], "source_unavailable")

    def test_receipts_distinguish_export_from_import_and_replay_idempotently(self):
        meta = {
            "rangeStart": "2026-05-01T00:00:00Z",
            "rangeEnd": "2026-05-09T19:00:00Z",
            "exportedAt": "2026-05-09T19:30:00Z",
            "timeZone": "Europe/Berlin",
        }
        with TemporaryDirectory() as temp, patch.object(
            person_paths, "WORKOUT_TRACKER_ROOT", Path(temp)
        ):
            person_paths.ensure_data_dir("Person")
            for _ in range(2):
                record_health_import("Person", "health_export_kit", meta, date(2026, 5, 4), None)
            rows = read_health_import_receipts("Person")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["applied_from"], "2026-05-04")
        self.assertEqual(rows[0]["applied_through"], "2026-05-09")
        self.assertEqual(rows[0]["exported_at"], meta["exportedAt"])
        self.assertTrue(rows[0]["imported_at"].endswith("+00:00"))
