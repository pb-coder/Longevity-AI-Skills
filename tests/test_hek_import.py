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

    # A 6-hour night at 13.0 brpm and a 20-minute nap at 20.0 brpm, both
    # filed on the 2026-06-06 row.
    LONG_NIGHT = ("06-05 22:00:00", "06-06 04:00:00", 21600, 13.0)
    SHORT_NAP = ("06-06 14:00:00", "06-06 14:20:00", 1200, 20.0)

    def _two_session_night(self, asleep_override=None) -> dict:
        sessions = []
        for start, end, seconds, rate in (self.LONG_NIGHT, self.SHORT_NAP):
            asleep = seconds if asleep_override is None else asleep_override
            sessions.append(_session(
                start, end,
                [_stage("asleepCore", start, end, seconds)],
                asleep=asleep,
                vitals={"respiratoryRate": {"avg": rate, "unit": "brpm"}},
            ))
        return hek.sleep_headline_rows(
            _payload(meta=self.META, sessions=sessions), None, None
        )[0]

    def test_respiratory_rate_is_weighted_by_time_asleep(self) -> None:
        # An unweighted mean would read 16.5, letting a 20-minute nap count
        # as much as the 6-hour night it is filed with.
        row = self._two_session_night()
        expected = (13.0 * 21600 + 20.0 * 1200) / (21600 + 1200)
        self.assertEqual(row["resp_rate"], round(expected, 2))
        self.assertLess(row["resp_rate"], 13.5)  # sits near the long night

    def test_the_plain_mean_is_the_fallback_when_no_session_reports_sleep(self) -> None:
        # No asleep seconds anywhere leaves no basis for a weight.
        self.assertEqual(self._two_session_night(asleep_override=0)["resp_rate"], 16.5)


class NightRolloverBoundaryTests(unittest.TestCase):
    """The exact 18:00 boundary.

    Right on all 224 stored nights already; pinned here so a one-character
    edit cannot move a night by a day without a test noticing.
    """

    META = NightAssemblyTests.META

    def _key(self, start, end) -> str:
        p = _payload(meta=self.META, sessions=[
            _session(start, end, [_stage("asleepCore", start, end, 3600)]),
        ])
        return sorted(hek.assemble_nights(p))[0]

    def test_one_second_before_six_pm_keys_to_the_wake_date(self) -> None:
        self.assertEqual(self._key("06-05 17:59:59", "06-05 19:30:00"), "2026-06-05")

    def test_exactly_six_pm_keys_to_the_following_day(self) -> None:
        self.assertEqual(self._key("06-05 18:00:00", "06-05 19:30:00"), "2026-06-06")


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


class AutoCardioPassThroughTests(unittest.TestCase):
    """Fields ``tracker/importing.build_auto_cardio_payload`` reads.

    They are not Workout Sessions columns and are not stored on the session
    row; they ride along so the monthly cardio row gets a Total Cal, an
    Elevation and an Elapsed instead of three blanks.
    """

    META = WorkoutFieldTests.META
    WORKOUT = WorkoutFieldTests.WORKOUT

    def _one(self, **overrides) -> dict:
        w = {**self.WORKOUT, **overrides}
        return hek.build_workout_payload(
            _payload(meta=self.META, workouts=[w]), None, None
        )[0]

    def _without(self, *keys) -> dict:
        w = {k: v for k, v in self.WORKOUT.items() if k not in keys}
        return hek.build_workout_payload(
            _payload(meta=self.META, workouts=[w]), None, None
        )[0]

    def test_energy_and_elevation_come_straight_across(self) -> None:
        row = self._one(elevationAscendedM=42.5)
        self.assertEqual(row["total_cal"], 525.5)
        self.assertEqual(row["basal_cal"], 137.5)
        self.assertEqual(row["elevation_m"], 42.5)

    def test_elapsed_is_the_wall_clock_span_not_the_duration(self) -> None:
        # ``durationSec`` excludes paused time; the span does not. The two
        # differ on 161 of the 698 workouts in the reference export, so
        # elapsed has to be measured from the stamps rather than copied
        # from duration the way the retired importer had to.
        row = self._one(end="08-02 17:24:27")
        self.assertEqual(row["duration_min"], 81.2)   # 4875 s
        self.assertEqual(row["elapsed_min"], 90.0)    # 15:54:27 -> 17:24:27

    def test_elapsed_is_unset_when_the_workout_has_no_end(self) -> None:
        self.assertNotIn("elapsed_min", self._without("end"))

    def test_absent_energy_stays_absent(self) -> None:
        row = self._without("totalEnergyKcal", "basalEnergyKcal")
        self.assertNotIn("total_cal", row)
        self.assertNotIn("basal_cal", row)

    def test_an_absent_elevation_stays_absent(self) -> None:
        self.assertNotIn("elevation_m", self._one())

    def test_zero_elevation_is_treated_as_absent(self) -> None:
        # Same distinction distance_km makes: no climb recorded is not a
        # measured zero.
        self.assertNotIn("elevation_m", self._one(elevationAscendedM=0))

    def test_negative_elevation_is_treated_as_absent(self) -> None:
        self.assertNotIn("elevation_m", self._one(elevationAscendedM=-3.0))


class IncidentalWalkTests(unittest.TestCase):
    """A short walk is movement, not a training session.

    ``workout-coach/lib/health_windowing.py`` drops rows flagged
    ``incidental``. Without the flag, 323 of the 698 workouts in the
    reference export enter the training window as real sessions and the
    incidental-walk count reads zero. Cross-checked against the tracker's
    stored history: the flag agrees on 663 of 663 rows.
    """

    META = WorkoutFieldTests.META

    def _one(self, apple_type, duration_sec, indoor=False) -> dict:
        w = {"start": "08-02 09:00:00", "end": "08-02 09:30:00",
             "type": apple_type, "isIndoor": indoor}
        if duration_sec is not None:
            w["durationSec"] = duration_sec
        return hek.build_workout_payload(
            _payload(meta=self.META, workouts=[w]), None, None
        )[0]

    def test_a_short_walk_is_incidental(self) -> None:
        self.assertTrue(self._one("Walking", 7 * 60)["incidental"])

    def test_a_long_walk_is_not_incidental(self) -> None:
        self.assertFalse(self._one("Walking", 40 * 60)["incidental"])

    def test_a_short_indoor_walk_is_incidental(self) -> None:
        # The type test is a substring, so IndoorWalking has to match too.
        row = self._one("Walking", 7 * 60, indoor=True)
        self.assertEqual(row["apple_type"], "IndoorWalking")
        self.assertTrue(row["incidental"])

    def test_a_short_run_is_not_incidental(self) -> None:
        self.assertFalse(self._one("Running", 7 * 60)["incidental"])

    def test_a_workout_with_no_duration_is_not_incidental(self) -> None:
        self.assertFalse(self._one("Walking", None)["incidental"])

    def test_the_boundary_is_compared_unrounded(self) -> None:
        # A real walk on 2026-05-21 runs durationSec=898, which is 14.9667
        # minutes -- incidental -- but rounds to the stored duration_min of
        # 15.0, which is not. The comparison has to see the full-precision
        # value or this one row disagrees with the stored history.
        self.assertTrue(self._one("Walking", 898)["incidental"])
        self.assertEqual(self._one("Walking", 898)["duration_min"], 15.0)
        # 900 s is exactly 15.0 minutes, and the rule is strictly less than.
        self.assertFalse(self._one("Walking", 900)["incidental"])

    def test_every_fixture_row_carries_the_flag(self) -> None:
        # Absent reads as "not incidental" downstream, which is exactly the
        # bug: the flag has to be written on every row, not only True ones.
        for row in hek.build_workout_payload(_load(), None, None):
            self.assertIn("incidental", row)


class TotalEnergyTests(unittest.TestCase):
    """A total is only a total when the export supplied the parts."""

    META = _meta(range_start="2026-08-01T00:00:00Z",
                 range_end="2026-08-30T00:00:00Z",
                 exported_at="2026-08-30T00:05:00Z")
    BASE = {
        "start": "08-07 18:11:07", "end": "08-07 18:33:01",
        "type": "HIIT", "isIndoor": False, "durationSec": 1314,
        "activeEnergyKcal": 304, "source": "Device",
    }

    def _one(self, **over) -> dict:
        rows = hek.build_workout_payload(
            _payload(meta=self.META, workouts=[{**self.BASE, **over}]), None, None)
        return rows[0]

    def test_total_is_written_when_basal_is_present(self) -> None:
        row = self._one(basalEnergyKcal=37.4, totalEnergyKcal=341.4)
        self.assertEqual(row["total_cal"], 341.4)
        self.assertEqual(row["basal_cal"], 37.4)

    def test_total_equal_to_active_with_no_basal_is_not_a_total(self) -> None:
        # The long-range export bug: basal goes missing and total silently
        # degrades to active. Writing it understated a hike by a quarter.
        row = self._one(totalEnergyKcal=304)
        self.assertNotIn("total_cal", row)
        self.assertNotIn("basal_cal", row)
        self.assertEqual(row["active_cal"], 304)

    def test_a_real_total_without_basal_is_still_kept(self) -> None:
        row = self._one(totalEnergyKcal=341.4)
        self.assertEqual(row["total_cal"], 341.4)


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

    def test_location_is_never_written(self) -> None:
        # isIndoor was measured against 27 real swims and disagreed with
        # the stored Location on 24 of them, so it decides nothing here,
        # true, false or missing alike.
        for indoor in (True, False, None):
            w = {k: v for k, v in self.SWIM.items() if k != "isIndoor"}
            if indoor is not None:
                w["isIndoor"] = indoor
            rows = hek.build_swim_payload(
                _payload(meta=self.META, workouts=[w]), None, None)
            self.assertNotIn("location", rows[0])

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


class FixtureSwimTests(unittest.TestCase):

    def test_the_fixture_produces_exactly_three_swims(self) -> None:
        rows = hek.build_swim_payload(_load(), None, None)
        self.assertEqual(len(rows), 3)

    def test_every_fixture_swim_has_a_date_and_a_start(self) -> None:
        for row in hek.build_swim_payload(_load(), None, None):
            self.assertTrue(row["date"])
            self.assertTrue(row["start"])

    def test_fixture_swim_starts_are_unique_per_date(self) -> None:
        rows = hek.build_swim_payload(_load(), None, None)
        keys = [(r["date"], r["start"]) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_fixture_swim_with_laps_has_a_positive_count(self) -> None:
        for row in hek.build_swim_payload(_load(), None, None):
            if "laps" in row:
                self.assertIsInstance(row["laps"], int)
                self.assertGreater(row["laps"], 0)

    def test_no_fixture_swim_carries_an_unsourced_field(self) -> None:
        for row in hek.build_swim_payload(_load(), None, None):
            for field in ("location", "pool_length_m", "strokes", "spl",
                          "avg_swolf", "stroke_mix", "water_temp_c"):
                self.assertNotIn(field, row)


import tempfile

from shared import csv_store, person_paths


class SchemaGuardTests(unittest.TestCase):
    """Payload keys must exist in the store's field list, or they vanish."""

    def test_health_payload_keys_are_all_real_columns(self) -> None:
        from shared.csv_store_dense import HEALTH_METRICS_FIELDS
        allowed = set(HEALTH_METRICS_FIELDS) | {"date"}
        payload = _load()
        rows = hek.build_health_payload(payload, None, None)
        rows += hek.sleep_headline_rows(payload, None, None)
        for row in rows:
            self.assertLessEqual(set(row), allowed, f"unknown key in {row}")

    # The workout payload legitimately carries four keys that are not
    # Workout Sessions columns. ``tracker/importing.build_auto_cardio_payload``
    # reads them off the same rows to build monthly cardio rows, and
    # ``upsert_workout_sessions`` ignores keys it does not recognise, so they
    # are consumed rather than stored. The retired importer carried the same
    # pass-throughs. Naming them explicitly keeps the test doing its real
    # job: catching a typo'd column name, which would otherwise vanish
    # silently at write time.
    AUTO_CARDIO_PASS_THROUGH = frozenset({
        "total_cal", "basal_cal", "elevation_m", "elapsed_min",
    })

    def test_workout_payload_keys_are_all_real_columns(self) -> None:
        from shared.csv_store_dense import WORKOUT_SESSIONS_FIELDS
        allowed = (set(WORKOUT_SESSIONS_FIELDS) | {"date"}
                   | self.AUTO_CARDIO_PASS_THROUGH)
        for row in hek.build_workout_payload(_load(), None, None):
            self.assertLessEqual(set(row), allowed, f"unknown key in {row}")

    def test_the_guard_still_rejects_a_key_that_is_neither(self) -> None:
        from shared.csv_store_dense import WORKOUT_SESSIONS_FIELDS
        allowed = (set(WORKOUT_SESSIONS_FIELDS) | {"date"}
                   | self.AUTO_CARDIO_PASS_THROUGH)
        self.assertNotIn("duration_mins", allowed)  # a plausible typo

    def test_sleep_payload_keys_are_all_real_columns(self) -> None:
        from shared.csv_store_periodic import SLEEP_NIGHTS_FIELDS
        allowed = set(SLEEP_NIGHTS_FIELDS) | {"date"}
        for row in hek.build_sleep_payload(_load(), None, None):
            self.assertLessEqual(set(row), allowed, f"unknown key in {row}")

    def test_swim_payload_keys_are_all_real_columns(self) -> None:
        from shared.csv_store_periodic import SWIM_WORKOUTS_FIELDS
        allowed = set(SWIM_WORKOUTS_FIELDS) | {"date"}
        for row in hek.build_swim_payload(_load(), None, None):
            self.assertLessEqual(set(row), allowed, f"unknown key in {row}")


class ImportExportTests(unittest.TestCase):
    """End to end against a temp tracker root, run twice for idempotency."""

    def _run_twice(self, **kwargs) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = person_paths.WORKOUT_TRACKER_ROOT
            old_hek_root = hek.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = root
            hek.WORKOUT_TRACKER_ROOT = root
            try:
                export = root / "health-export-json-2026-01-01-0000_to_2026-08-30-0000.json"
                export.write_text(FIXTURE.read_text())
                call = dict(person="Test", export_path=export,
                            since=None, until=None,
                            allow_past_months=True, dry_run=False,
                            keep_export=True)
                call.update(kwargs)
                hek.import_export(**call)
                hek.import_export(**call)
                return {
                    "profile": csv_store.read_profile("Test"),
                    "health": csv_store.read_health_metrics("Test"),
                    "sessions": csv_store.read_workout_sessions("Test"),
                    "sleep": csv_store.read_sleep_nights("Test"),
                }
            finally:
                person_paths.WORKOUT_TRACKER_ROOT = old_root
                hek.WORKOUT_TRACKER_ROOT = old_hek_root

    def test_a_second_identical_import_changes_nothing(self) -> None:
        got = self._run_twice()
        dates = [r["date"] for r in got["health"]]
        self.assertEqual(len(dates), len(set(dates)))
        keys = [(r["date"], r["start"]) for r in got["sessions"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_profile_source_is_pinned(self) -> None:
        self.assertEqual(self._run_twice()["profile"]["source"], "health_export_kit")

    def test_sleep_efficiency_is_derived_by_the_store(self) -> None:
        for row in self._run_twice()["sleep"]:
            if row.get("total_h") and row.get("time_in_bed_h"):
                self.assertIsNotNone(row.get("efficiency_pct"))

    def test_an_empty_export_raises_rather_than_writing_nothing_quietly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = person_paths.WORKOUT_TRACKER_ROOT
            old_hek_root = hek.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = root
            hek.WORKOUT_TRACKER_ROOT = root
            try:
                export = root / "health-export-json-empty.json"
                export.write_text(json.dumps(_payload()))
                with self.assertRaises(hek.EmptyImportError):
                    hek.import_export("Test", export, None, None,
                                      keep_export=True)
            finally:
                person_paths.WORKOUT_TRACKER_ROOT = old_root
                hek.WORKOUT_TRACKER_ROOT = old_hek_root


class MetaValidationTests(unittest.TestCase):
    """A malformed export must report one clear line, not a traceback.

    ``main()`` catches ``ClockGuardError`` and ``ValueError``. A ``meta``
    missing a key it needs used to raise ``KeyError`` deep inside the
    timestamp code and escape as a traceback, which the ``/log`` flow has
    no way to surface.
    """

    def _read(self, payload: dict):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "health-export-json-broken.json"
            export.write_text(json.dumps(payload))
            return hek.read_export(export)

    def test_every_required_meta_key_is_checked_and_named(self) -> None:
        for key in hek.REQUIRED_META_KEYS:
            with self.subTest(key=key):
                payload = _payload()
                del payload["meta"][key]
                with self.assertRaises(ValueError) as ctx:
                    self._read(payload)
                self.assertIn(key, str(ctx.exception))

    def test_an_empty_value_counts_as_missing(self) -> None:
        payload = _payload()
        payload["meta"]["timeZone"] = ""
        with self.assertRaises(ValueError):
            self._read(payload)

    def test_a_complete_meta_reads_normally(self) -> None:
        self.assertEqual(self._read(_payload())["meta"]["schemaVersion"], 1)

    def test_the_failure_reaches_the_caller_as_a_value_error(self) -> None:
        # This is the type main() catches, so the CLI exits 3 with one line.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = _payload()
            del payload["meta"]["rangeStart"]
            export = root / "health-export-json-broken.json"
            export.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                hek.import_export("Test", export, None, None, keep_export=True)


class CapabilityTests(unittest.TestCase):

    def test_the_new_source_declares_no_daily_hrv_and_no_wrist_temp(self) -> None:
        from workout_coach.lib.constants import SOURCE_CAPABILITIES
        caps = SOURCE_CAPABILITIES["health_export_kit"]
        self.assertFalse(caps["hrv"])
        self.assertFalse(caps["wrist_temp"])
        self.assertTrue(caps["sleep_stages"])
        self.assertTrue(caps["sleep_regularity"])
        self.assertTrue(caps["sleep_nights"])

    def test_it_declares_the_same_keys_as_the_retired_source(self) -> None:
        from workout_coach.lib.constants import SOURCE_CAPABILITIES
        self.assertEqual(
            set(SOURCE_CAPABILITIES["health_export_kit"]),
            set(SOURCE_CAPABILITIES["health_auto_export"]),
        )


if __name__ == "__main__":
    unittest.main()
