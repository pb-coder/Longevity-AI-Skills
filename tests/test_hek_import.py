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


def _session(start, end, stages, asleep=None, awake=0, vitals=None) -> dict:
    total = sum(s["durationSec"] for s in stages)
    asleep_sec = asleep if asleep is not None else sum(
        s["durationSec"] for s in stages if s["stage"] != "awake"
    )
    return {
        "start": start, "end": end,
        "durationSec": total,
        "asleepSec": asleep_sec,
        "awakeSec": awake,
        "source": "Apple Watch",
        "stages": stages,
        "vitals": vitals or {},
    }


def _stage(stage, start, end, seconds) -> dict:
    return {"stage": stage, "start": start, "end": end, "durationSec": seconds}


class NightAssemblyTests(unittest.TestCase):
    """Reproduces the retired pipeline, verified on 224 of 224 stored nights."""

    META = _meta(range_start="2026-06-01T00:00:00Z",
                 range_end="2026-07-01T00:00:00Z",
                 exported_at="2026-07-01T00:05:00Z")

    def test_a_night_is_keyed_by_its_wake_date(self) -> None:
        p = _payload(meta=self.META, sessions=[
            _session("06-05 23:30:00", "06-06 07:00:00",
                     [_stage("asleepCore", "06-05 23:30:00", "06-06 07:00:00", 27000)]),
        ])
        self.assertEqual(sorted(hek.assemble_nights(p)), ["2026-06-06"])

    def test_a_session_starting_after_six_pm_belongs_to_the_next_night(self) -> None:
        # A 2026-06-27 20:25 nap is stored on the 2026-06-28 night row.
        p = _payload(meta=self.META, sessions=[
            _session("06-27 20:25:09", "06-27 22:34:34",
                     [_stage("asleepCore", "06-27 20:25:09", "06-27 22:34:34", 7765)]),
        ])
        self.assertEqual(sorted(hek.assemble_nights(p)), ["2026-06-28"])

    def test_a_split_night_merges_into_one_row(self) -> None:
        # 2026-06-07: 23:19->04:30 and 05:02->07:46 became one stored night
        # with total 5.97 h, in bed 8.44 h and 37 segments.
        p = _payload(meta=self.META, sessions=[
            _session("06-06 23:19:41", "06-07 04:30:41",
                     [_stage("asleepCore", "06-06 23:19:41", "06-07 04:30:41", 12129)],
                     asleep=12129, awake=6540),
            _session("06-07 05:02:50", "06-07 07:46:21",
                     [_stage("asleepCore", "06-07 05:02:50", "06-07 07:46:21", 9360)],
                     asleep=9360, awake=480),
        ])
        rows = hek.build_sleep_payload(p, None, None)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["date"], "2026-06-07")
        self.assertEqual(row["total_h"], round((12129 + 9360) / 3600, 2))
        # In bed spans the gap between the two sessions.
        self.assertEqual(row["time_in_bed_h"], round((8 * 3600 + 26 * 60 + 40) / 3600, 2))
        self.assertEqual(row["n_segments"], 2)
        self.assertEqual(row["first_segment_start"], "2026-06-06 23:19:41")
        self.assertEqual(row["last_segment_end"], "2026-06-07 07:46:21")

    def test_the_gap_between_sessions_is_in_bed_but_not_awake(self) -> None:
        p = _payload(meta=self.META, sessions=[
            _session("06-06 23:19:41", "06-07 04:30:41",
                     [_stage("asleepCore", "06-06 23:19:41", "06-07 04:30:41", 12129)],
                     asleep=12129, awake=6540),
            _session("06-07 05:02:50", "06-07 07:46:21",
                     [_stage("asleepCore", "06-07 05:02:50", "06-07 07:46:21", 9360)],
                     asleep=9360, awake=480),
        ])
        row = hek.build_sleep_payload(p, None, None)[0]
        self.assertEqual(row["awake_h"], round((6540 + 480) / 3600, 2))

    def test_stage_totals_come_from_the_stage_intervals(self) -> None:
        p = _payload(meta=self.META, sessions=[
            _session("06-05 23:00:00", "06-06 06:00:00", [
                _stage("asleepCore", "06-05 23:00:00", "06-06 01:00:00", 7200),
                _stage("asleepDeep", "06-06 01:00:00", "06-06 02:00:00", 3600),
                _stage("asleepREM", "06-06 02:00:00", "06-06 03:00:00", 3600),
                _stage("awake", "06-06 03:00:00", "06-06 03:10:00", 600),
                _stage("asleepCore", "06-06 03:10:00", "06-06 06:00:00", 10200),
            ]),
        ])
        row = hek.build_sleep_payload(p, None, None)[0]
        self.assertEqual(row["core_h"], round(17400 / 3600, 2))
        self.assertEqual(row["deep_h"], 1.0)
        self.assertEqual(row["rem_h"], 1.0)
        self.assertEqual(row["n_segments"], 5)

    def test_the_clock_correction_is_applied_to_sleep_stamps(self) -> None:
        m = _meta(range_start="2026-01-01T00:00:00Z",
                  range_end="2026-08-30T07:22:53Z",
                  exported_at="2026-08-30T07:25:07Z")
        p = _payload(meta=m, sessions=[
            _session("03-27 22:19:41", "03-28 06:30:41",
                     [_stage("asleepCore", "03-27 22:19:41", "03-28 06:30:41", 29460)]),
        ])
        row = hek.build_sleep_payload(p, None, None)[0]
        self.assertEqual(row["first_segment_start"], "2026-03-27 23:19:41")
        self.assertEqual(row["last_segment_end"], "2026-03-28 07:30:41")


class SleepHeadlineTests(unittest.TestCase):

    META = NightAssemblyTests.META

    def test_the_headline_mirror_carries_respiratory_rate_from_sleep_vitals(self) -> None:
        p = _payload(meta=self.META, sessions=[
            _session("06-05 23:00:00", "06-06 06:00:00",
                     [_stage("asleepCore", "06-05 23:00:00", "06-06 06:00:00", 25200)],
                     vitals={"respiratoryRate": {"avg": 14.5, "unit": "brpm"}}),
        ])
        rows = hek.sleep_headline_rows(p, None, None)
        self.assertEqual(rows[0]["date"], "2026-06-06")
        self.assertEqual(rows[0]["resp_rate"], 14.5)
        self.assertEqual(rows[0]["sleep_total_h"], 7.0)
        self.assertEqual(rows[0]["time_in_bed_h"], 7.0)


class FixtureSleepTests(unittest.TestCase):

    def test_every_fixture_night_has_a_span_at_least_as_long_as_its_sleep(self) -> None:
        for row in hek.build_sleep_payload(_load(), None, None):
            self.assertGreaterEqual(row["time_in_bed_h"], row["total_h"])

    def test_the_fixture_contains_a_merged_night(self) -> None:
        rows = hek.build_sleep_payload(_load(), None, None)
        self.assertTrue(any(r["n_segments"] and r["n_segments"] > 10 for r in rows))


class TypeMapTests(unittest.TestCase):
    """Verified against 663 stored workouts; no combination fell through."""

    CASES = [
        ("Walking", False, "Walking"),
        ("Walking", True, "IndoorWalking"),
        ("Strength Training", False, "TraditionalStrengthTraining"),
        ("Functional Strength", False, "FunctionalStrengthTraining"),
        ("Core Training", False, "CoreTraining"),
        ("Running", True, "IndoorRunning"),
        ("Running", False, "Running"),
        ("Cycling", True, "IndoorCycling"),
        ("Cycling", False, "Cycling"),
        ("HIIT", False, "HighIntensityIntervalTraining"),
        ("Swimming", True, "Swimming"),
        ("Swimming", False, "Swimming"),
        ("Hiking", False, "Hiking"),
        ("Rowing", True, "Rowing"),
    ]

    def test_every_observed_combination_maps(self) -> None:
        from shared import apple_workout_types as awt
        for raw, indoor, expected in self.CASES:
            with self.subTest(raw=raw, indoor=indoor):
                self.assertEqual(awt.hek_canonical_type(raw, indoor), expected)

    def test_a_missing_indoor_flag_is_treated_as_outdoor(self) -> None:
        from shared import apple_workout_types as awt
        self.assertEqual(awt.hek_canonical_type("Hiking", None), "Hiking")

    def test_an_unknown_type_still_produces_a_storable_name(self) -> None:
        from shared import apple_workout_types as awt
        self.assertEqual(awt.hek_canonical_type("Water Polo", False), "WaterPolo")


class WorkoutFieldTests(unittest.TestCase):

    META = _meta(range_start="2026-08-01T00:00:00Z",
                 range_end="2026-08-30T00:00:00Z",
                 exported_at="2026-08-30T00:05:00Z")

    # "source" below uses the \u00a0 escape deliberately, matching the real
    # export: Apple writes a non-breaking space in "Apple Watch". Do not
    # replace it with the literal character -- an invisible character in
    # source cannot be reviewed and does not survive copying reliably.
    WORKOUT = {
        "start": "08-02 15:54:27", "end": "08-02 17:15:42",
        "type": "Strength Training", "isIndoor": False,
        "durationSec": 4875,
        "averageHeartRateBpm": 105, "maxHeartRateBpm": 147,
        "minHeartRateBpm": 85,
        "activeEnergyKcal": 388, "totalEnergyKcal": 525.5,
        "basalEnergyKcal": 137.5,
        "source": "Apple\u00a0Watch",
        "weatherHumidityPercent": 4200, "weatherTemperatureC": 24.6,
    }

    def _one(self, **overrides) -> dict:
        w = {**self.WORKOUT, **overrides}
        rows = hek.build_workout_payload(
            _payload(meta=self.META, workouts=[w]), None, None
        )
        return rows[0]

    def test_core_fields_map_straight_across(self) -> None:
        row = self._one()
        self.assertEqual(row["date"], "2026-08-02")
        self.assertEqual(row["start"], "15:54:27")
        self.assertEqual(row["end"], "17:15:42")
        self.assertEqual(row["apple_type"], "TraditionalStrengthTraining")
        self.assertEqual(row["duration_min"], 81.2)
        self.assertEqual(row["avg_hr"], 105)
        self.assertEqual(row["max_hr"], 147)
        self.assertEqual(row["min_hr"], 85)
        self.assertEqual(row["active_cal"], 388)

    def test_the_non_breaking_space_in_source_is_normalized(self) -> None:
        self.assertEqual(self._one()["source"], "Apple Watch")

    def test_a_workout_with_no_heart_rate_is_stored_without_one(self) -> None:
        w = {k: v for k, v in self.WORKOUT.items()
             if k not in ("averageHeartRateBpm", "maxHeartRateBpm", "minHeartRateBpm")}
        rows = hek.build_workout_payload(
            _payload(meta=self.META, workouts=[w]), None, None
        )
        self.assertNotIn("avg_hr", rows[0])
        self.assertEqual(rows[0]["apple_type"], "TraditionalStrengthTraining")

    def test_a_workout_with_no_start_is_dropped(self) -> None:
        w = {k: v for k, v in self.WORKOUT.items() if k != "start"}
        rows = hek.build_workout_payload(
            _payload(meta=self.META, workouts=[w]), None, None
        )
        self.assertEqual(rows, [])

    def test_zero_distance_is_treated_as_absent(self) -> None:
        rows = hek.build_workout_payload(
            _payload(meta=self.META, workouts=[{**self.WORKOUT, "distanceKm": 0}]),
            None, None,
        )
        self.assertNotIn("distance_km", rows[0])


class HumidityTests(unittest.TestCase):
    """The field is named Percent but carries basis points. An app bug."""

    def test_basis_points_are_divided(self) -> None:
        self.assertEqual(hek.humidity_percent(4200), 42.0)
        self.assertEqual(hek.humidity_percent(8700), 87.0)

    def test_a_real_percent_is_left_alone(self) -> None:
        self.assertEqual(hek.humidity_percent(42), 42)

    def test_absent_stays_absent(self) -> None:
        self.assertIsNone(hek.humidity_percent(None))


class FixtureWorkoutTests(unittest.TestCase):

    def test_every_fixture_workout_produces_a_row_with_a_type(self) -> None:
        rows = hek.build_workout_payload(_load(), None, None)
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row["apple_type"])
            self.assertTrue(row["date"])
            self.assertTrue(row["start"])

    def test_workout_starts_are_unique_per_date(self) -> None:
        rows = hek.build_workout_payload(_load(), None, None)
        keys = [(r["date"], r["start"]) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))


class SwimTests(unittest.TestCase):

    META = _meta(range_start="2026-07-01T00:00:00Z",
                 range_end="2026-07-31T00:00:00Z",
                 exported_at="2026-07-31T00:05:00Z")

    SWIM = {
        "start": "07-25 12:30:45", "end": "07-25 12:45:12",
        "type": "Swimming", "isIndoor": False,
        "durationSec": 864, "distanceKm": 0.38,
        "averageHeartRateBpm": 128, "activeEnergyKcal": 127,
        "source": "Apple Watch",
        "events": ([{"type": "lap", "start": "07-25 12:31:00",
                     "end": "07-25 12:31:20"}] * 19)
                  + [{"type": "pause", "start": "07-25 12:45:12",
                      "end": "07-25 12:45:12"}],
    }

    def _one(self, **overrides) -> dict:
        rows = hek.build_swim_payload(
            _payload(meta=self.META, workouts=[{**self.SWIM, **overrides}]),
            None, None,
        )
        return rows[0]

    def test_laps_are_counted_from_lap_events(self) -> None:
        # 19 laps on 2026-07-25, matching the stored swimming file exactly.
        self.assertEqual(self._one()["laps"], 19)

    def test_pause_events_are_not_counted_as_laps(self) -> None:
        row = self._one(events=[{"type": "pause", "start": "07-25 12:45:12",
                                 "end": "07-25 12:45:12"}])
        self.assertIsNone(row.get("laps"))

    def test_outdoor_swims_are_open_water(self) -> None:
        self.assertEqual(self._one(isIndoor=False)["location"], "Open Water")

    def test_indoor_swims_are_pool(self) -> None:
        self.assertEqual(self._one(isIndoor=True)["location"], "Pool")

    def test_an_absent_indoor_flag_leaves_location_blank(self) -> None:
        w = {k: v for k, v in self.SWIM.items() if k != "isIndoor"}
        rows = hek.build_swim_payload(_payload(meta=self.META, workouts=[w]),
                                      None, None)
        self.assertIsNone(rows[0].get("location"))

    def test_fields_with_no_source_are_left_unset(self) -> None:
        row = self._one()
        for field in ("pool_length_m", "strokes", "spl",
                      "avg_swolf", "stroke_mix", "water_temp_c"):
            self.assertNotIn(field, row)

    def test_only_swims_are_returned(self) -> None:
        rows = hek.build_swim_payload(_payload(meta=self.META, workouts=[
            self.SWIM,
            {"start": "07-25 18:00:00", "end": "07-25 18:30:00",
             "type": "Walking", "isIndoor": False, "durationSec": 1800},
        ]), None, None)
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
