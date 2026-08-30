"""Health Export Kit reader.

Every test here pins a rule that fails silently when it is wrong: a daily
sum written for a half-covered day, a breathing-disturbance value filed on
the night it started instead of the morning it belongs to, a humidity value
a hundred times too large. None of those would raise; all of them would sit
in the CSV looking plausible.
"""
from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from shared import import_health_export_kit as hek

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "hek-export.json"


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def _meta(range_start="2026-01-01T00:00:00Z",
          range_end="2026-01-05T00:00:00Z",
          exported_at="2026-01-05T00:05:00Z") -> dict:
    return {
        "rangeStart": range_start,
        "rangeEnd": range_end,
        "exportedAt": exported_at,
        "timeZone": "Europe/Paris",
        "categories": ["activity", "heart"],
        "schemaVersion": 1,
    }


def _payload(meta=None, daily=None, additional=None,
             workouts=None, sessions=None) -> dict:
    return {
        "meta": meta or _meta(),
        "activity": {"daily": daily or [], "workouts": workouts or []},
        "sleep": {"sessions": sessions or [], "streams": {}},
        "additional": additional or {},
    }


class DailySumCoverageTests(unittest.TestCase):
    """Sums need a fully covered day; averages and latest readings do not."""

    # Range starts 08:45 on the 2nd, so the 2nd is half a day.
    PARTIAL = _meta(range_start="2026-01-02T07:45:00Z",
                    range_end="2026-01-05T00:00:00Z",
                    exported_at="2026-01-05T00:05:00Z")

    def test_a_partial_day_drops_its_sums(self) -> None:
        rows = hek.build_health_payload(_payload(
            meta=self.PARTIAL,
            daily=[{"date": "2026-01-02", "steps": 5926,
                    "activeEnergyKcal": 583.9, "exerciseMinutes": 33}],
        ), None, None)
        self.assertEqual(rows, [])

    def test_a_partial_day_keeps_its_non_sums(self) -> None:
        rows = hek.build_health_payload(_payload(
            meta=self.PARTIAL,
            daily=[{"date": "2026-01-02", "steps": 5926}],
            additional={"heart": {
                "units": {"restingHR": "bpm"},
                "aggregation": {"restingHR": "avg"},
                "daily": [{"date": "2026-01-02", "values": {"restingHR": 63}}],
            }},
        ), None, None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-01-02")
        self.assertEqual(rows[0]["resting_hr"], 63)
        self.assertNotIn("steps", rows[0])

    def test_a_fully_covered_day_keeps_its_sums(self) -> None:
        rows = hek.build_health_payload(_payload(
            meta=self.PARTIAL,
            daily=[{"date": "2026-01-03", "steps": 11082,
                    "activeEnergyKcal": 1066.3, "basalEnergyKcal": 2129.8,
                    "exerciseMinutes": 121}],
        ), None, None)
        self.assertEqual(rows[0]["steps"], 11082)
        self.assertEqual(rows[0]["active_energy_kcal"], 1066.3)
        self.assertEqual(rows[0]["basal_energy_kcal"], 2129.8)
        self.assertEqual(rows[0]["exercise_min"], 121)


class AbsentKeyTests(unittest.TestCase):

    def test_an_absent_key_is_not_written_as_zero(self) -> None:
        rows = hek.build_health_payload(_payload(
            daily=[{"date": "2026-01-02", "steps": 9995}],
        ), None, None)
        self.assertNotIn("exercise_min", rows[0])
        self.assertEqual(rows[0]["steps"], 9995)

    def test_an_absent_section_does_not_raise(self) -> None:
        rows = hek.build_health_payload(_payload(
            daily=[{"date": "2026-01-02", "steps": 100}],
            additional={},
        ), None, None)
        self.assertEqual(len(rows), 1)

    def test_a_requested_but_absent_category_does_not_raise(self) -> None:
        meta = _meta()
        meta["categories"] = ["activity", "nutrition"]
        rows = hek.build_health_payload(_payload(
            meta=meta, daily=[{"date": "2026-01-02", "steps": 100}],
        ), None, None)
        self.assertEqual(len(rows), 1)


class BreathingDisturbanceShiftTests(unittest.TestCase):
    """The export files the night's value on the day it began."""

    def test_the_value_moves_forward_one_day(self) -> None:
        rows = hek.build_health_payload(_payload(
            additional={"heart": {
                "units": {"breathingDisturbances": "count"},
                "aggregation": {"breathingDisturbances": "avg"},
                "daily": [{"date": "2026-01-02",
                           "values": {"breathingDisturbances": 0.9}}],
            }},
        ), None, None)
        by_date = {r["date"]: r for r in rows}
        self.assertNotIn("sleep_breath_dist", by_date.get("2026-01-02", {}))
        self.assertEqual(by_date["2026-01-03"]["sleep_breath_dist"], 0.9)


class HrvTests(unittest.TestCase):

    def test_daily_hrv_is_never_written(self) -> None:
        # The export has no all-day HRV. Writing the sleep-window value into
        # the historical column would corrupt the recovery baseline.
        rows = hek.build_health_payload(_payload(
            daily=[{"date": "2026-01-02", "steps": 100}],
        ), None, None)
        for row in rows:
            self.assertNotIn("hrv_sdnn", row)


class SinceUntilTests(unittest.TestCase):

    def test_rows_outside_the_window_are_dropped(self) -> None:
        payload = _payload(daily=[
            {"date": "2026-01-02", "steps": 1},
            {"date": "2026-01-03", "steps": 2},
            {"date": "2026-01-04", "steps": 3},
        ])
        rows = hek.build_health_payload(payload, date(2026, 1, 3), date(2026, 1, 3))
        self.assertEqual([r["date"] for r in rows], ["2026-01-03"])


class FixtureHealthTests(unittest.TestCase):

    def test_the_fixture_produces_one_row_per_date(self) -> None:
        rows = hek.build_health_payload(_load(), None, None)
        dates = [r["date"] for r in rows]
        self.assertEqual(len(dates), len(set(dates)))
        self.assertTrue(dates == sorted(dates))

    def test_no_row_is_date_only(self) -> None:
        for row in hek.build_health_payload(_load(), None, None):
            self.assertGreater(len(row), 1, f"date-only row: {row}")


if __name__ == "__main__":
    unittest.main()
