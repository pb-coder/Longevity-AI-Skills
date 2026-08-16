"""HealthAutoExport JSON reader: daily aggregation parity, sleep, and swim.

The aggregation table is the highest-risk surface in the importer. Rolling
HRV up as latest-of-day instead of mean, or resting HR as mean instead of
latest, produces per-day numbers that look entirely plausible while
shifting every downstream recovery z-score, and nothing else in the suite
would notice. The parity tests below therefore construct days whose mean,
latest and max are all *different* numbers, so a handler wired to the
wrong strategy cannot accidentally pass.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from datetime import date
from io import StringIO
from pathlib import Path

from shared import import_health_auto_export as hae

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "hae-json-export.json"


def _point(stamp: str, qty: float) -> dict:
    return {"date": stamp, "qty": qty, "source": "Device"}


def _payload(metrics: list[dict], workouts: list[dict] | None = None) -> dict:
    return {"data": {"metrics": metrics, "workouts": workouts or []}}


def _parse(payload: dict, since=None, until=None):
    with redirect_stderr(StringIO()):
        return hae.parse_health_auto_export_json(payload, since, until)


class AggregationParityTests(unittest.TestCase):
    """Each strategy is pinned against a day where the three disagree."""

    # Readings chosen so mean=20.0, latest=45.0 and max=45.0 are distinct
    # from one another wherever the strategy could plausibly be confused.
    DAY = [
        _point("2026-08-13 02:00:00 +0200", 5.0),
        _point("2026-08-13 04:00:00 +0200", 10.0),
        _point("2026-08-13 23:00:00 +0200", 45.0),
    ]

    def test_hrv_is_the_mean_of_the_day(self) -> None:
        metrics, _sleep, _w, _s = _parse(_payload([
            {"name": "heart_rate_variability", "units": "ms", "data": self.DAY},
        ]))
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["hrv_sdnn"], 20.0)

    def test_resting_hr_is_the_latest_of_the_day_not_the_mean_or_the_max(self) -> None:
        day = [
            _point("2026-08-13 02:00:00 +0200", 80.0),   # the max
            _point("2026-08-13 04:00:00 +0200", 60.0),
            _point("2026-08-13 23:00:00 +0200", 55.0),   # the latest
        ]
        metrics, _sleep, _w, _s = _parse(_payload([
            {"name": "resting_heart_rate", "units": "count/min", "data": day},
        ]))
        self.assertEqual(metrics[0]["resting_hr"], 55.0)

    def test_walking_hr_and_vo2max_are_latest_of_day(self) -> None:
        metrics, _sleep, _w, _s = _parse(_payload([
            {"name": "walking_heart_rate_average", "units": "count/min", "data": self.DAY},
            {"name": "vo2_max", "units": "ml/(kg·min)", "data": self.DAY},
        ]))
        self.assertEqual(metrics[0]["walking_hr"], 45.0)
        self.assertEqual(metrics[0]["vo2max"], 45.0)

    def test_wrist_temp_is_latest_within_its_night(self) -> None:
        # Wrist temp is night-bucketed (see SleepOnsetBucketingTests), so
        # the readings here are kept inside one calendar day on purpose.
        day = [
            _point("2026-08-13 02:00:00 +0200", 35.5),
            _point("2026-08-13 04:00:00 +0200", 36.2),
        ]
        metrics, _sleep, _w, _s = _parse(_payload([
            {"name": "apple_sleeping_wrist_temperature", "units": "degC", "data": day},
        ]))
        self.assertEqual(metrics[0]["date"], "2026-08-13")
        self.assertEqual(metrics[0]["wrist_temp_c"], 36.2)

    def test_exercise_minutes_are_summed_not_averaged(self) -> None:
        metrics, _sleep, _w, _s = _parse(_payload([
            {"name": "apple_exercise_time", "units": "min", "data": self.DAY},
        ]))
        self.assertEqual(metrics[0]["exercise_min"], 60.0)

    def test_respiratory_rate_is_the_mean_of_the_day(self) -> None:
        metrics, _sleep, _w, _s = _parse(_payload([
            {"name": "respiratory_rate", "units": "count/min", "data": self.DAY},
        ]))
        self.assertEqual(metrics[0]["resp_rate"], 20.0)

    def test_cardio_recovery_keeps_the_best_reading_of_the_day(self) -> None:
        """The XML aggregator kept the largest HR-recovery reading of the day.

        It did not keep the last one, so the recovery model has always been
        calibrated on best-of-day. A day whose final reading is its worst
        is the case that separates the two.
        """
        day = [
            _point("2026-08-13 08:00:00 +0200", 42.0),   # best, earliest
            _point("2026-08-13 12:00:00 +0200", 31.0),
            _point("2026-08-13 20:00:00 +0200", 18.0),   # latest, worst
        ]
        metrics, _sleep, _w, _s = _parse(_payload([
            {"name": "cardio_recovery", "units": "count/min", "data": day},
        ]))
        self.assertEqual(metrics[0]["hr_recovery_1min"], 42.0)

    def test_every_stored_metric_has_an_aggregation_rule(self) -> None:
        for name in hae.JSON_METRIC_FIELDS:
            self.assertIn(name, hae.METRIC_AGGREGATION, f"{name} has no roll-up rule")
        self.assertIn(hae.JSON_BODY_FAT_METRIC, hae.METRIC_AGGREGATION)

    def test_a_day_whose_only_reading_is_unparsable_yields_no_cell(self) -> None:
        """A blank cell is recoverable; a zero stamped over it is not."""
        metrics, _sleep, _w, _s = _parse(_payload([
            {"name": "heart_rate_variability", "units": "ms",
             "data": [{"date": "2026-08-13 02:00:00 +0200", "qty": None, "source": "Device"}]},
        ]))
        self.assertEqual(metrics, [])


class SleepOnsetBucketingTests(unittest.TestCase):
    """Overnight readings belong to the night's wake date, not its bedtime.

    The XML aggregator bucketed wrist temperature and breathing
    disturbances by the record's ``endDate`` — the morning — while every
    other handler used the start. HealthAutoExport collapses each to one
    timestamp taken at sleep onset, which for a normal bedtime is the
    evening *before*. Filing those by their own calendar day puts the
    next night's reading beside this night's sleep totals on the same
    row, and the recovery score reads that row per date.
    """

    def _rows(self, stamp: str, qty: float, metric: str):
        metrics, _sleep, _w, _s = _parse(_payload([
            {"name": metric, "units": "degC", "data": [_point(stamp, qty)]},
        ]))
        return metrics

    def test_an_evening_reading_is_filed_under_the_next_morning(self) -> None:
        rows = self._rows("2026-08-12 23:27:00 +0200", 36.057,
                          "apple_sleeping_wrist_temperature")
        self.assertEqual(rows[0]["date"], "2026-08-13")

    def test_an_after_midnight_reading_stays_on_its_own_date(self) -> None:
        rows = self._rows("2026-08-13 00:36:00 +0200", 35.446,
                          "apple_sleeping_wrist_temperature")
        self.assertEqual(rows[0]["date"], "2026-08-13")

    def test_breathing_disturbances_bucket_the_same_way(self) -> None:
        rows = self._rows("2026-08-12 23:27:00 +0200", 0.78, "breathing_disturbances")
        self.assertEqual(rows[0]["date"], "2026-08-13")

    def test_both_ends_of_one_night_collapse_onto_the_same_row(self) -> None:
        """The two readings of a single night must not become two rows."""
        metrics, _s, _w, _sw = _parse(_payload([
            {"name": "apple_sleeping_wrist_temperature", "units": "degC", "data": [
                _point("2026-08-12 23:00:00 +0200", 35.815),
                _point("2026-08-13 00:18:00 +0200", 35.711),
            ]},
        ]))
        self.assertEqual([m["date"] for m in metrics], ["2026-08-13"])
        # Latest-of-night wins, and 00:18 is later than 23:00 the evening before.
        self.assertEqual(metrics[0]["wrist_temp_c"], 35.711)

    def test_daytime_metrics_are_not_night_bucketed(self) -> None:
        """Only the two sleep-onset metrics roll over; nothing else does."""
        metrics, _s, _w, _sw = _parse(_payload([
            {"name": "resting_heart_rate", "units": "count/min",
             "data": [_point("2026-08-12 23:00:00 +0200", 60.0)]},
        ]))
        self.assertEqual(metrics[0]["date"], "2026-08-12")

    def test_the_rollover_hour_matches_the_sleep_night_convention(self) -> None:
        self.assertEqual(hae.SLEEP_NIGHT_ROLLOVER_HOUR, 18)
        self.assertEqual(
            hae.SLEEP_ONSET_METRICS,
            frozenset({"apple_sleeping_wrist_temperature", "breathing_disturbances"}),
        )


class DateWindowTests(unittest.TestCase):
    def test_points_outside_the_window_are_dropped(self) -> None:
        metrics, _sleep, _w, _s = _parse(
            _payload([{
                "name": "resting_heart_rate", "units": "count/min",
                "data": [
                    _point("2026-08-12 02:00:00 +0200", 60.0),
                    _point("2026-08-13 02:00:00 +0200", 61.0),
                    _point("2026-08-14 02:00:00 +0200", 62.0),
                ],
            }]),
            since=date(2026, 8, 13), until=date(2026, 8, 13),
        )
        self.assertEqual([m["date"] for m in metrics], ["2026-08-13"])

    def test_the_timezone_offset_is_stripped_rather_than_re_based(self) -> None:
        """A 23:30 +0200 reading belongs to that local day, not to the UTC one."""
        self.assertEqual(
            hae.parse_hae_dt("2026-08-13 23:30:00 +0200").isoformat(),
            "2026-08-13T23:30:00",
        )


class SleepTests(unittest.TestCase):
    NIGHT = {
        "date": "2026-08-13 00:00:00 +0200",
        "source": "Device",
        "totalSleep": 6.479103389845955,
        "core": 3.7035414790113768,
        "deep": 1.4212124426166217,
        "rem": 1.3543494682179555,
        "awake": 0.07524114986260733,
        "asleep": 0,
        "inBed": 0,
        "sleepStart": "2026-08-12 23:51:32 +0200",
        "sleepEnd": "2026-08-13 06:24:48 +0200",
        "inBedStart": "2026-08-12 23:51:32 +0200",
        "inBedEnd": "2026-08-13 06:24:48 +0200",
    }

    def _night(self, **overrides):
        payload = _payload([
            {"name": "sleep_analysis", "units": "hr", "data": [{**self.NIGHT, **overrides}]},
        ])
        _metrics, sleep, _w, _s = _parse(payload)
        return sleep[0]

    def test_the_night_is_bucketed_on_the_wake_date(self) -> None:
        self.assertEqual(self._night()["date"], "2026-08-13")

    def test_segment_timestamps_survive_which_is_what_the_index_reads(self) -> None:
        night = self._night()
        self.assertEqual(night["first_segment_start"], "2026-08-12 23:51:32")
        self.assertEqual(night["last_segment_end"], "2026-08-13 06:24:48")

    def test_time_in_bed_comes_from_the_in_bed_span_not_the_zero_field(self) -> None:
        # inBed reads 0 on every observed night; the span is the real datum.
        self.assertEqual(self._night()["time_in_bed_h"], 6.55)

    def test_n_segments_is_blank_rather_than_a_fabricated_zero(self) -> None:
        self.assertIsNone(self._night()["n_segments"])

    def test_asleep_is_the_unspecified_stage_bucket(self) -> None:
        night = self._night(
            asleep=1.755630675289366, totalSleep=6.094479241205586,
            core=2.5247584944632315, deep=1.2791056430008676, rem=0.5349844284521209,
        )
        self.assertEqual(night["unspecified_h"], 1.76)
        self.assertAlmostEqual(
            night["core_h"] + night["deep_h"] + night["rem_h"] + night["unspecified_h"],
            night["total_h"], places=2,
        )

    def test_efficiency_is_left_for_the_store_to_derive(self) -> None:
        self.assertIsNone(self._night()["efficiency_pct"])

    def test_sleep_headline_fields_are_mirrored_onto_health_metrics(self) -> None:
        payload = _payload([
            {"name": "sleep_analysis", "units": "hr", "data": [self.NIGHT]},
        ])
        metrics, _sleep, _w, _s = _parse(payload)
        self.assertEqual(metrics[0]["sleep_total_h"], 6.48)
        self.assertEqual(metrics[0]["sleep_deep_h"], 1.42)
        self.assertEqual(metrics[0]["sleep_rem_h"], 1.35)
        self.assertEqual(metrics[0]["time_in_bed_h"], 6.55)


class SwimTests(unittest.TestCase):
    SWIM = {
        "name": "Pool Swim",
        "start": "2026-07-25 12:30:45 +0200",
        "end": "2026-07-25 12:45:12 +0200",
        "duration": 866.3148880004883,
        "isIndoor": True,
        "location": "Pool",
        "distance": {"qty": 0.38, "units": "km"},
        "lapLength": {"qty": 0.02, "units": "m"},
        "totalSwimmingStrokeCount": {"qty": 199.99999999999991, "units": "count"},
        "activeEnergyBurned": {"qty": 529.9880680114317, "units": "kJ"},
        "totalEnergy": {"qty": 632.7808040145765, "units": "kJ"},
        "avgHeartRate": {"qty": 127.5, "units": "count/min"},
        "maxHeartRate": {"qty": 144, "units": "count/min"},
        "heartRate": {"min": {"qty": 108}, "avg": {"qty": 127.5}, "max": {"qty": 144}},
    }

    def _swim(self, **overrides):
        _m, _sl, _w, swim = _parse(_payload([], [{**self.SWIM, **overrides}]))
        return swim[0] if swim else None

    def test_lap_length_is_kilometres_despite_its_metre_label(self) -> None:
        # 0.02 "m" is a 20 m pool. Multiplying by 1000 is the whole fix.
        self.assertEqual(self._swim()["pool_length_m"], 20)

    def test_laps_and_spl_are_derived_from_distance_and_strokes(self) -> None:
        swim = self._swim()
        self.assertEqual(swim["laps"], 19)      # 380 m / 20 m
        self.assertEqual(swim["strokes"], 200)
        self.assertEqual(swim["spl"], 10.5)     # 200 / 19

    def test_an_implausible_pool_length_drops_rather_than_scaling_the_laps(self) -> None:
        swim = self._swim(lapLength={"qty": 25.0, "units": "m"})
        self.assertIsNone(swim["pool_length_m"])
        self.assertIsNone(swim["laps"])
        self.assertIsNone(swim["spl"])

    def test_swolf_and_stroke_mix_stay_blank_with_no_per_lap_payload(self) -> None:
        swim = self._swim()
        self.assertIsNone(swim["avg_swolf"])
        self.assertIsNone(swim["stroke_mix"])

    def test_water_temperature_comes_from_readings_inside_the_swim_window(self) -> None:
        payload = _payload(
            [{"name": "underwater_temperature", "units": "degC", "data": [
                _point("2026-07-25 11:00:00 +0200", 5.0),     # before the swim
                _point("2026-07-25 12:35:00 +0200", 27.5),
                _point("2026-07-25 12:40:00 +0200", 27.7),
                _point("2026-07-25 18:00:00 +0200", 99.0),    # after the swim
            ]}],
            [self.SWIM],
        )
        _m, _sl, _w, swim = _parse(payload)
        self.assertEqual(swim[0]["water_temp_c"], 27.6)

    def test_garbage_swim_speeds_are_never_read(self) -> None:
        """Wrist-underwater GPS reports 1819 and 4367 under ``units: "m"``.

        Nothing stores a speed, so the reader must not grow a field that
        would carry one; pace is recomputed from distance and duration.
        """
        _m, _sl, workouts, swim = _parse(_payload([], [dict(
            self.SWIM,
            avgSpeed={"qty": 1819.0437173920823, "units": "m"},
            maxSpeed={"qty": 4367.2251283899, "units": "m"},
        )]))
        for row in (*workouts, *swim):
            for key, value in row.items():
                self.assertNotIn("speed", key.lower())
                self.assertNotEqual(value, 1819.0437173920823)
                self.assertNotEqual(value, 4367.2251283899)

    def test_an_open_water_swim_without_lap_length_still_writes_a_row(self) -> None:
        swim = self._swim(
            name="Open Water Swim", location="Open Water", isIndoor=False,
            lapLength=None, totalSwimmingStrokeCount=None,
            distance={"qty": 0.16183591534972994, "units": "km"},
        )
        self.assertEqual(swim["location"], "Open Water")
        self.assertEqual(swim["distance_km"], 0.162)
        self.assertIsNone(swim["laps"])
        self.assertIsNone(swim["spl"])


class WorkoutTests(unittest.TestCase):
    WALK = {
        "name": "Outdoor Walk",
        "start": "2026-08-14 19:33:55 +0200",
        "end": "2026-08-14 19:37:53 +0200",
        "duration": 238.4625689983368,
        "distance": {"qty": 0.3529884772600081, "units": "km"},
        "elevationUp": {"qty": 8.27, "units": "m"},
        "activeEnergyBurned": {"qty": 125.85053600000003, "units": "kJ"},
        "temperature": {"qty": 30.232971191403806, "units": "degC"},
        "humidity": {"qty": 30, "units": "%"},
    }

    def _walk(self, **overrides):
        _m, _sl, workouts, _s = _parse(_payload([], [{**self.WALK, **overrides}]))
        return workouts[0]

    def test_workout_names_are_canonical_english_and_map_to_apple_types(self) -> None:
        self.assertEqual(self._walk()["apple_type"], "Walking")
        self.assertEqual(
            self._walk(name="Traditional Strength Training")["apple_type"],
            "TraditionalStrengthTraining",
        )

    def test_workout_energy_is_kilojoules(self) -> None:
        # 125.85 kJ / 4.184 = 30.1 kcal
        self.assertEqual(self._walk()["active_cal"], 30.1)

    def test_short_walks_are_flagged_incidental(self) -> None:
        self.assertTrue(self._walk()["incidental"])
        self.assertFalse(self._walk(duration=3600.0)["incidental"])

    def test_basal_energy_is_the_gap_between_total_and_active(self) -> None:
        row = self._walk(totalEnergy={"qty": 200.0, "units": "kJ"})
        self.assertEqual(row["total_cal"], 47.8)
        self.assertEqual(row["active_cal"], 30.1)
        self.assertEqual(row["basal_cal"], 17.7)

    def test_a_missing_total_energy_is_left_blank_not_defaulted_to_active(self) -> None:
        """51 of 121 workouts in the reference export carry no totalEnergy.

        Basal is 23% of total on the ones that do, so defaulting the
        total to the active figure understates those rows by about a
        quarter while reading as a measurement. They carry no basal
        series either, so the datum genuinely does not exist.
        """
        row = self._walk()
        self.assertNotIn("totalEnergy", self.WALK)
        self.assertEqual(row["active_cal"], 30.1)
        self.assertIsNone(row["total_cal"])
        self.assertIsNone(row["basal_cal"])


class HeartRateSourceTests(unittest.TestCase):
    """The windowed top-level series is the primary heart-rate source.

    HealthAutoExport's per-workout ``heartRate`` object is computed from
    its own ``heartRateData`` series, and that series is truncated in
    practice: a 15-minute run can carry 25 samples spanning two minutes.
    Measured against the rows the retired XML importer wrote, the
    per-workout object is 2.47 bpm out on average and up to 25 bpm wrong,
    against 0.84 bpm for the windowed series. It also covers 52 workouts
    that carry no per-workout object at all.
    """

    WORKOUT = {
        "name": "Indoor Run",
        "start": "2026-08-13 07:46:00 +0200",
        "end": "2026-08-13 08:01:00 +0200",
        "duration": 900.0,
    }

    def _hr_series(self, *pairs):
        return {"name": "heart_rate", "units": "count/min", "data": [
            {"date": stamp, "Avg": v, "Min": v, "Max": v, "source": "Device"}
            for stamp, v in pairs
        ]}

    def test_the_windowed_series_wins_over_a_truncated_workout_average(self) -> None:
        payload = _payload(
            [self._hr_series(
                ("2026-08-13 07:47:00 +0200", 120.0),
                ("2026-08-13 07:52:00 +0200", 140.0),
                ("2026-08-13 07:58:00 +0200", 160.0),
            )],
            # The truncated object saw only the opening two minutes.
            [dict(self.WORKOUT, heartRate={"avg": {"qty": 114.4}, "max": {"qty": 119},
                                           "min": {"qty": 110}})],
        )
        _m, _s, workouts, _sw = _parse(payload)
        self.assertEqual(workouts[0]["avg_hr"], 140.0)

    def test_a_workout_with_no_hr_object_still_gets_heart_rate(self) -> None:
        """52 of 121 workouts carry no per-workout HR; all 52 are in-window."""
        payload = _payload(
            [self._hr_series(("2026-08-13 07:50:00 +0200", 133.0))],
            [dict(self.WORKOUT)],
        )
        _m, _s, workouts, _sw = _parse(payload)
        self.assertEqual(workouts[0]["avg_hr"], 133.0)
        self.assertEqual(workouts[0]["max_hr"], 133)

    def test_the_peak_is_the_higher_of_the_two_sources(self) -> None:
        """Under-sampling can miss a beat, never invent one."""
        payload = _payload(
            [self._hr_series(("2026-08-13 07:50:00 +0200", 150.0))],
            [dict(self.WORKOUT, maxHeartRate={"qty": 171, "units": "count/min"})],
        )
        _m, _s, workouts, _sw = _parse(payload)
        self.assertEqual(workouts[0]["max_hr"], 171)

    def test_falls_back_to_the_workout_object_when_the_window_is_empty(self) -> None:
        payload = _payload(
            [self._hr_series(("2026-08-13 20:00:00 +0200", 60.0))],  # outside
            [dict(self.WORKOUT, heartRate={"avg": {"qty": 139.8}, "max": {"qty": 165},
                                           "min": {"qty": 101}})],
        )
        _m, _s, workouts, _sw = _parse(payload)
        self.assertEqual(workouts[0]["avg_hr"], 139.8)
        self.assertEqual(workouts[0]["min_hr"], 101)


class WorkoutUnitGateTests(unittest.TestCase):
    """Workout scalars are unit-gated, like every daily metric already is.

    HealthAutoExport bakes the in-app unit preference into its output and
    its unit strings are not always honest, as ``lapLength`` proves.
    """

    BASE = {
        "name": "Outdoor Walk",
        "start": "2026-08-14 19:33:55 +0200",
        "end": "2026-08-14 19:37:53 +0200",
        "duration": 238.0,
    }

    def _row(self, **overrides):
        _m, _s, workouts, _sw = _parse(_payload([], [{**self.BASE, **overrides}]))
        return workouts[0]

    def test_energy_in_kcal_is_not_multiplied_as_though_it_were_kilojoules(self) -> None:
        row = self._row(activeEnergyBurned={"qty": 250, "units": "kcal"})
        self.assertIsNone(row["active_cal"])

    def test_distance_in_miles_is_dropped_not_stored_as_kilometres(self) -> None:
        self.assertIsNone(self._row(distance={"qty": 5.0, "units": "mi"})["distance_km"])

    def test_elevation_in_feet_is_dropped_not_stored_as_metres(self) -> None:
        self.assertIsNone(self._row(elevationUp={"qty": 1000, "units": "ft"})["elevation_m"])

    def test_expected_units_pass_through(self) -> None:
        row = self._row(
            activeEnergyBurned={"qty": 125.85, "units": "kJ"},
            distance={"qty": 0.353, "units": "km"},
            elevationUp={"qty": 8.27, "units": "m"},
        )
        self.assertEqual(row["active_cal"], 30.1)
        self.assertEqual(row["distance_km"], 0.353)
        self.assertEqual(row["elevation_m"], 8.3)

    def test_basal_energy_never_goes_negative(self) -> None:
        """The XML path added active and basal; it could not produce this."""
        row = self._row(
            activeEnergyBurned={"qty": 1000.0, "units": "kJ"},
            totalEnergy={"qty": 900.0, "units": "kJ"},
        )
        self.assertIsNone(row["basal_cal"])
        self.assertIsNone(row["total_cal"])


class DuplicateMetricBlockTests(unittest.TestCase):
    def test_two_blocks_of_one_metric_accumulate_instead_of_last_wins(self) -> None:
        """The exporter can split a series by source device."""
        metrics, _s, _w, _sw = _parse(_payload([
            {"name": "apple_exercise_time", "units": "min",
             "data": [_point("2026-08-13 08:00:00 +0200", 30.0)]},
            {"name": "apple_exercise_time", "units": "min",
             "data": [_point("2026-08-13 18:00:00 +0200", 20.0)]},
        ]))
        self.assertEqual(metrics[0]["exercise_min"], 50.0)


class TimezoneOrderingTests(unittest.TestCase):
    def test_latest_of_day_orders_by_instant_not_by_wall_clock(self) -> None:
        """22:00 +0200 is genuinely earlier than 20:00 -0400 the same date."""
        metrics, _s, _w, _sw = _parse(_payload([
            {"name": "resting_heart_rate", "units": "count/min", "data": [
                {"date": "2026-08-13 22:00:00 +0200", "qty": 64, "source": "Device"},
                {"date": "2026-08-13 20:00:00 -0400", "qty": 72, "source": "Device"},
            ]},
        ]))
        self.assertEqual(metrics[0]["resting_hr"], 72.0)


class SleepEdgeCaseTests(unittest.TestCase):
    BASE = dict(SleepTests.NIGHT)

    def _night(self, **overrides):
        _m, sleep, _w, _sw = _parse(_payload([
            {"name": "sleep_analysis", "units": "hr", "data": [{**self.BASE, **overrides}]},
        ]))
        return sleep[0] if sleep else None

    def test_a_stage_that_never_occurred_is_blank_not_zero(self) -> None:
        """0.0 overwrites under a sparse merge; None leaves the cell alone."""
        night = self._night(rem=0, awake=0)
        self.assertIsNone(night["rem_h"])
        self.assertIsNone(night["awake_h"])

    def test_a_zero_sleep_record_writes_no_night_at_all(self) -> None:
        self.assertIsNone(self._night(totalSleep=0, core=0, deep=0, rem=0, asleep=0, awake=0))

    def test_a_nap_derives_no_time_in_bed_and_so_no_fake_efficiency(self) -> None:
        night = self._night(
            totalSleep=0.5, core=0.5, deep=0, rem=0, asleep=0,
            sleepStart="2026-08-13 14:00:00 +0200", sleepEnd="2026-08-13 14:30:00 +0200",
            inBedStart="2026-08-13 14:00:00 +0200", inBedEnd="2026-08-13 14:30:00 +0200",
        )
        self.assertEqual(night["total_h"], 0.5)
        self.assertIsNone(night["time_in_bed_h"])

    def test_a_night_plus_a_nap_on_one_date_accumulate(self) -> None:
        """Overwriting would erase the night and leave the nap as the whole of it."""
        nap = dict(self.BASE, totalSleep=0.5, core=0.5, deep=0, rem=0, asleep=0, awake=0,
                   sleepStart="2026-08-13 14:00:00 +0200", sleepEnd="2026-08-13 14:30:00 +0200",
                   inBedStart="2026-08-13 14:00:00 +0200", inBedEnd="2026-08-13 14:30:00 +0200")
        _m, sleep, _w, _sw = _parse(_payload([
            {"name": "sleep_analysis", "units": "hr", "data": [self.BASE, nap]},
        ]))
        self.assertEqual(len(sleep), 1)
        self.assertAlmostEqual(sleep[0]["total_h"], 6.98, places=2)
        self.assertEqual(sleep[0]["first_segment_start"], "2026-08-12 23:51:32")
        self.assertEqual(sleep[0]["last_segment_end"], "2026-08-13 14:30:00")

    def test_a_night_carrying_nothing_creates_no_health_row(self) -> None:
        """A date-only row serialises as a fully blank CSV line."""
        metrics, _s, _w, _sw = _parse(_payload([
            {"name": "sleep_analysis", "units": "hr", "data": [{
                "date": "2026-08-13 00:00:00 +0200", "source": "Device",
                "totalSleep": 0, "core": 0, "deep": 0, "rem": 0, "asleep": 0,
                "awake": 0.5, "inBed": 0,
            }]},
        ]))
        self.assertEqual(metrics, [])


class MissingUnitsTests(unittest.TestCase):
    def test_an_absent_units_key_does_not_discard_the_metric(self) -> None:
        """The XML aggregator defaulted the unit; dropping loses everything."""
        metrics, _s, _w, _sw = _parse(_payload([
            {"name": "weight_body_mass",
             "data": [_point("2026-08-13 06:43:00 +0200", 79.8)]},
        ]))
        self.assertEqual(metrics[0]["bodyweight_kg"], 79.8)


class FixtureImportTests(unittest.TestCase):
    """End-to-end over a trimmed two-day export with a real pool swim."""

    def setUp(self) -> None:
        self.metrics, self.sleep, self.workouts, self.swim = _parse(
            json.loads(FIXTURE.read_text())
        )

    def test_one_health_metrics_row_per_day(self) -> None:
        dates = [m["date"] for m in self.metrics]
        # The fixture holds two days of readings. The third row is the
        # 13th's bedtime wrist-temp and breathing readings, which belong
        # to the night waking on the 14th — a real boundary row, not a
        # duplicate.
        self.assertEqual(dates, ["2026-07-25", "2026-08-13", "2026-08-14"])
        self.assertEqual(len(dates), len(set(dates)))
        self.assertEqual(
            sorted(self.metrics[-1]),
            ["date", "sleep_breath_dist", "wrist_temp_c"],
        )

    def test_hrv_matches_an_independently_computed_daily_mean(self) -> None:
        raw = json.loads(FIXTURE.read_text())["data"]["metrics"]
        points = next(m for m in raw if m["name"] == "heart_rate_variability")["data"]
        checked = 0
        for row in self.metrics:
            same_day = [p["qty"] for p in points if p["date"][:10] == row["date"]]
            if not same_day:
                self.assertIsNone(row.get("hrv_sdnn"))
                continue
            self.assertEqual(row["hrv_sdnn"], round(sum(same_day) / len(same_day), 2))
            checked += 1
        self.assertEqual(checked, 2)

    def test_resting_hr_matches_the_last_reading_of_each_day(self) -> None:
        raw = json.loads(FIXTURE.read_text())["data"]["metrics"]
        points = next(m for m in raw if m["name"] == "resting_heart_rate")["data"]
        checked = 0
        for row in self.metrics:
            same_day = sorted(
                (p for p in points if p["date"][:10] == row["date"]),
                key=lambda p: p["date"],
            )
            if not same_day:
                self.assertIsNone(row.get("resting_hr"))
                continue
            self.assertEqual(row["resting_hr"], round(same_day[-1]["qty"], 1))
            checked += 1
        self.assertEqual(checked, 2)

    def test_the_pool_swim_derives_its_laps_and_spl(self) -> None:
        self.assertEqual(len(self.swim), 1)
        swim = self.swim[0]
        self.assertEqual(swim["date"], "2026-07-25")
        self.assertEqual(swim["pool_length_m"], 20)
        self.assertEqual(swim["laps"], 19)
        self.assertEqual(swim["spl"], 10.5)
        self.assertEqual(swim["strokes"], 200)

    def test_sleep_nights_carry_timestamps_and_no_segment_count(self) -> None:
        self.assertEqual([n["date"] for n in self.sleep], ["2026-07-25", "2026-08-13"])
        for night in self.sleep:
            self.assertIsNotNone(night["first_segment_start"])
            self.assertIsNotNone(night["last_segment_end"])
            self.assertIsNone(night["n_segments"])

    def test_the_fixture_carries_no_identifying_source_strings(self) -> None:
        """Every ``source`` in the fixture is the neutral placeholder.

        A real export names the device and the device carries its owner's
        name ("Apple Watch von <Person>"). This fixture is committed to a
        public repo, so it is screened on an allowlist rather than on a
        denylist of known names: an identifier nobody thought to screen
        for still fails, and the test does not itself have to spell out
        the names it exists to keep out.
        """
        data = json.loads(FIXTURE.read_text()).get("data") or {}
        sources: set[str] = set()

        def collect(points) -> None:
            for point in points or []:
                if isinstance(point, dict) and point.get("source"):
                    sources.add(point["source"])

        for metric in data.get("metrics") or []:
            collect(metric.get("data"))
        for workout in data.get("workouts") or []:
            collect([workout])
            for value in workout.values():
                if isinstance(value, list):
                    collect(value)

        self.assertEqual(sources, {"Device"})


class ReaderDispatchTests(unittest.TestCase):
    def test_a_json_member_selects_the_json_reader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "HealthAutoExport_20260815.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr(
                    "HealthAutoExport-2026-08-13-2026-08-13.json",
                    FIXTURE.read_text(),
                )
                zf.writestr("Outdoor Walk-Route-20260813_171835.gpx", "<gpx/>")
            with redirect_stderr(StringIO()):
                metrics, sleep, _workouts, swim = hae.parse_health_auto_export_zip(
                    path, None, None
                )
        # 3 metric rows: two full days plus the wake-date boundary row
        # carrying the second day's bedtime wrist-temp reading.
        self.assertEqual(len(metrics), 3)
        self.assertEqual(len(sleep), 2)
        self.assertEqual(len(swim), 1)

    def test_route_gpx_files_do_not_confuse_the_member_lookup(self) -> None:
        names = [
            "HealthAutoExport-2026-08-13-2026-08-13.json",
            "Outdoor Walk-Route-20260813_171835.gpx",
        ]
        self.assertEqual(
            hae._find_json_member(names),
            "HealthAutoExport-2026-08-13-2026-08-13.json",
        )

    def test_an_archive_without_json_falls_back_to_the_csv_reader(self) -> None:
        self.assertIsNone(hae._find_json_member(["HealthAutoExport-2026-08-13.csv"]))


class EmptyImportTests(unittest.TestCase):
    """An import that writes nothing must not report success.

    Pointing the importer at a localised CSV export produced
    ``Health Metrics: 0 dates written`` at exit 0 — a silent failure
    indistinguishable from a good run.
    """

    def test_an_export_with_no_metrics_and_no_sleep_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "HealthAutoExport_empty.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr(
                    "HealthAutoExport-2026-08-13-2026-08-13.json",
                    json.dumps({"data": {"metrics": [], "workouts": []}}),
                )
            with self.assertRaises(hae.EmptyImportError):
                with redirect_stderr(StringIO()):
                    hae.import_archive("Test", path, None, None)

    def test_a_dry_run_over_an_empty_export_still_reports_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "HealthAutoExport_empty.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr(
                    "HealthAutoExport-2026-08-13-2026-08-13.json",
                    json.dumps({"data": {"metrics": [], "workouts": []}}),
                )
            with redirect_stderr(StringIO()):
                lines = hae.import_archive("Test", path, None, None, dry_run=True)
        self.assertTrue(any("0 dates would be written" in ln for ln in lines))


if __name__ == "__main__":
    unittest.main()
