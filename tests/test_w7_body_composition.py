"""W7b — leanness channel: waist / body fat / lean mass end to end.

Covers both HealthAutoExport readers (JSON and the deprecated CSV), the
health_metrics.csv schema migration, and the manual-entry path a tape
measure reading arrives on.

The absence cases matter as much as the presence ones: the export in hand
today carries Body Mass and nothing else, so every metric here is one the
importer must handle by leaving the cell blank rather than writing a zero.
"""
from __future__ import annotations

import csv
import io
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime
from io import StringIO
from pathlib import Path

from shared import csv_store, csv_store_dense, maintain, person_paths
from shared import import_health_auto_export as hae
from shared.csv_store_dense import body_composition_lines
from shared.health_units import (
    PLAUSIBLE_RANGES,
    normalize_body_fat_pct,
    reset_unit_warnings,
)


class WarnStateTestCase(unittest.TestCase):
    """Base case that clears ``convert_unit``'s warn-once registry.

    That registry is process-global and warn-once by design (production
    wants one line per bad unit, not one per row). Left un-reset it makes
    tests order-dependent: whether a test sees its own warning depends on
    whether an earlier test in the same process already burned that unit
    string. Resetting per test lets two tests assert on the *same* unit
    token and both pass, in either order.
    """

    def setUp(self) -> None:
        super().setUp()
        reset_unit_warnings()


class BodyFatNormalisationTests(WarnStateTestCase):
    def test_fraction_and_percentage_encodings_both_land_as_points(self) -> None:
        self.assertEqual(normalize_body_fat_pct("0.18"), 18.0)
        self.assertEqual(normalize_body_fat_pct(0.181), 18.1)
        self.assertEqual(normalize_body_fat_pct(18.1), 18.1)

    def test_a_fraction_of_one_is_not_a_hundred_percent_body_fat(self) -> None:
        # The old gate was (0, 100], so 1.0 normalised to "100% body fat"
        # and 0.005 to 0.5%. Both are impossible bodies; both were stored.
        with redirect_stderr(StringIO()):
            self.assertIsNone(normalize_body_fat_pct(1.0))
            self.assertIsNone(normalize_body_fat_pct(0.005))

    def test_guard_band_boundaries_are_inclusive(self) -> None:
        self.assertEqual(normalize_body_fat_pct(3.0), 3.0)
        self.assertEqual(normalize_body_fat_pct(75.0), 75.0)
        self.assertEqual(normalize_body_fat_pct(0.03), 3.0)   # fraction form
        self.assertEqual(normalize_body_fat_pct(0.75), 75.0)
        with redirect_stderr(StringIO()):
            self.assertIsNone(normalize_body_fat_pct(2.9))
            self.assertIsNone(normalize_body_fat_pct(75.1))

    def test_the_fraction_heuristic_dead_zone_drops_loudly(self) -> None:
        # 1.0 < x < 3.0 is neither a fraction this code will scale nor a
        # plausible percentage. It used to be stored verbatim as "2%".
        for dead in (1.01, 2.0, 2.99):
            err = StringIO()
            with redirect_stderr(err):
                self.assertIsNone(normalize_body_fat_pct(dead), dead)
            self.assertIn("outside the plausible 3-75 range", err.getvalue())

    def test_out_of_range_and_unparseable_values_are_dropped(self) -> None:
        with redirect_stderr(StringIO()):
            for bad in ("n/a", 0, -3, 101, 250):
                self.assertIsNone(normalize_body_fat_pct(bad), bad)

    def test_absent_values_are_silent_but_bad_ones_warn(self) -> None:
        # "No reading" is not a rejection and must not print anything;
        # everything the function actually refuses gets a line on stderr.
        err = StringIO()
        with redirect_stderr(err):
            self.assertIsNone(normalize_body_fat_pct(None))
            self.assertIsNone(normalize_body_fat_pct(""))
        self.assertEqual(err.getvalue(), "")

        for bad in ("n/a", 0, 1.0, 101):
            err = StringIO()
            with redirect_stderr(err):
                normalize_body_fat_pct(bad)
            self.assertIn("body fat percentage", err.getvalue(), bad)

    def test_ranges_are_declared_in_one_place(self) -> None:
        self.assertEqual(PLAUSIBLE_RANGES["waist_cm"], (30.0, 250.0))
        self.assertEqual(PLAUSIBLE_RANGES["lean_body_mass_kg"], (20.0, 150.0))
        self.assertEqual(PLAUSIBLE_RANGES["body_fat_pct"], (3.0, 75.0))


# ----------------------------------------------------- HealthAutoExport
def _daily_zip(path: Path, header: list[str], row: list[str]) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerow(row)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("HealthAutoExport-2026-08-01-2026-08-01.csv", buf.getvalue())
        zf.writestr("Workouts-20260801_000000-20260801_235959.csv", "Workout Type,Start\n")


class HealthAutoExportBodyCompositionTests(WarnStateTestCase):
    @staticmethod
    def _parse(row: dict):
        err = StringIO()
        with redirect_stderr(err):
            metrics, _sleep = hae.parse_daily_rows(
                [{"Date/Time": "2026-08-01 00:00:00", **row}],
                date(2026, 8, 1), date(2026, 8, 1),
            )
        return metrics[0], err.getvalue()

    def test_imperial_headers_are_resolved_by_prefix_and_converted(self) -> None:
        # HealthAutoExport bakes the user's in-app unit choice into the
        # header. A fixed "(cm)" lookup would silently skip this export.
        rows = [{
            "Date/Time": "2026-08-01 00:00:00",
            "Waist Circumference (in)": "33",
            "Body Fat Percentage (%)": "0.181",
            "Lean Body Mass (lb)": "140",
        }]
        err = StringIO()
        with redirect_stderr(err):
            metrics, _sleep = hae.parse_daily_rows(rows, date(2026, 8, 1), date(2026, 8, 1))

        self.assertEqual(metrics[0]["waist_cm"], 83.8)
        self.assertEqual(metrics[0]["body_fat_pct"], 18.1)
        self.assertEqual(metrics[0]["lean_body_mass_kg"], 63.5)
        self.assertNotIn("Waist Circumference (<unit>)", err.getvalue())

    def test_blank_and_zero_cells_read_as_none(self) -> None:
        rows = [{
            "Date/Time": "2026-08-01 00:00:00",
            "Waist Circumference (cm)": "",
            "Body Fat Percentage (%)": "0",
            "Lean Body Mass (kg)": "0",
        }]
        with redirect_stderr(StringIO()):
            metrics, _sleep = hae.parse_daily_rows(rows, date(2026, 8, 1), date(2026, 8, 1))

        self.assertIsNone(metrics[0]["waist_cm"])
        self.assertIsNone(metrics[0]["body_fat_pct"])
        self.assertIsNone(metrics[0]["lean_body_mass_kg"])

    def test_unknown_header_unit_warns_and_skips(self) -> None:
        # Deliberately the same unit token the Apple-XML test uses. The
        # warn-once registry is process-global, so before it was made
        # resettable these two tests could only both pass by picking
        # different strings — an order dependency dressed up as coverage.
        metrics, err = self._parse({"Waist Circumference (cubits)": "33"})
        self.assertIsNone(metrics["waist_cm"])
        self.assertIn("unknown waist circumference unit", err)

    # ------------------------------------------------ plausibility gate
    def test_waist_column_in_metres_is_dropped_not_stored_as_8450_cm(self) -> None:
        # HealthAutoExport bakes the user's in-app unit into the header,
        # so a metre-denominated waist column is a well-formed export.
        metrics, err = self._parse({"Waist Circumference (m)": "84.5"})
        self.assertIsNone(metrics["waist_cm"])
        self.assertIn("outside the plausible 30-250 range", err)
        self.assertIn("'m'", err)

    def test_lean_mass_column_in_grams_is_dropped(self) -> None:
        metrics, err = self._parse({"Lean Body Mass (g)": "63.2"})
        self.assertIsNone(metrics["lean_body_mass_kg"])
        self.assertIn("outside the plausible 20-150 range", err)

    def test_absurd_waist_in_a_correct_unit_is_still_dropped(self) -> None:
        metrics, err = self._parse({"Waist Circumference (cm)": "8450"})
        self.assertIsNone(metrics["waist_cm"])
        self.assertIn("outside the plausible 30-250 range", err)

    def test_range_boundaries_are_inclusive_on_this_path_too(self) -> None:
        for column, value in (("Waist Circumference (cm)", "30"),
                              ("Waist Circumference (cm)", "250"),
                              ("Lean Body Mass (kg)", "20"),
                              ("Lean Body Mass (kg)", "150")):
            metrics, _err = self._parse({column: value})
            key = "waist_cm" if column.startswith("Waist") else "lean_body_mass_kg"
            self.assertEqual(metrics[key], float(value), (column, value))
        for column, value in (("Waist Circumference (cm)", "29.9"),
                              ("Waist Circumference (cm)", "250.1"),
                              ("Lean Body Mass (kg)", "19.9"),
                              ("Lean Body Mass (kg)", "150.1")):
            metrics, _err = self._parse({column: value})
            key = "waist_cm" if column.startswith("Waist") else "lean_body_mass_kg"
            self.assertIsNone(metrics[key], (column, value))

    def test_body_fat_column_unit_is_read_and_gated(self) -> None:
        metrics, err = self._parse({"Body Fat Percentage (cubits)": "0.181"})
        self.assertIsNone(metrics["body_fat_pct"])
        self.assertIn("unknown body fat percentage unit", err)

    def test_body_fat_guard_band_applies_on_this_path_too(self) -> None:
        metrics, err = self._parse({"Body Fat Percentage (%)": "1.0"})
        self.assertIsNone(metrics["body_fat_pct"])
        self.assertIn("outside the plausible 3-75 range", err)

    def test_zip_roundtrip_writes_the_new_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "HealthAutoExport.zip"
            _daily_zip(
                path,
                ["Date/Time", "Waist Circumference (cm)", "Body Fat Percentage (%)",
                 "Lean Body Mass (kg)"],
                ["2026-08-01 00:00:00", "84.5", "0.181", "63.2"],
            )
            with redirect_stderr(StringIO()):
                metrics, _sleep, _workouts, _swim = hae.parse_health_auto_export_zip(
                    path, date(2026, 8, 1), date(2026, 8, 1)
                )

        self.assertEqual(metrics[0]["waist_cm"], 84.5)
        self.assertEqual(metrics[0]["body_fat_pct"], 18.1)
        self.assertEqual(metrics[0]["lean_body_mass_kg"], 63.2)


class ReplaceRangeBodyCompositionTests(WarnStateTestCase):
    """``--replace-range`` must not take the body-composition cells with it."""

    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_root = person_paths.WORKOUT_TRACKER_ROOT
        self.old_hae_root = hae.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = root
        hae.WORKOUT_TRACKER_ROOT = root
        csv_store.write_profile("Test", source="health_auto_export", auto_cardio=True)

    def tearDown(self) -> None:
        person_paths.WORKOUT_TRACKER_ROOT = self.old_root
        hae.WORKOUT_TRACKER_ROOT = self.old_hae_root
        self.tmp.cleanup()

    def test_a_populated_waist_survives_a_range_clear(self) -> None:
        # The readings only exist because someone typed them into Apple's
        # Body Measurements screen; the export cannot regenerate them, so
        # clearing the window must leave them standing while the
        # machine-sourced metrics beside them go.
        csv_store.upsert_health_metrics("Test", [{
            "date": "2026-08-01",
            "waist_cm": 84.5,
            "body_fat_pct": 18.1,
            "lean_body_mass_kg": 63.2,
            "bodyweight_kg": 79.5,
            "resting_hr": 53,
            "hrv_sdnn": 40.6,
        }])

        summary = hae.clear_health_metrics_range(
            "Test", date(2026, 8, 1), date(2026, 8, 1)
        )
        self.assertIn("cleared 2 machine value(s)", summary)

        row = csv_store.read_health_metrics("Test")[0]
        self.assertEqual(row["waist_cm"], 84.5)
        self.assertEqual(row["body_fat_pct"], 18.1)
        self.assertEqual(row["lean_body_mass_kg"], 63.2)
        self.assertEqual(row["bodyweight_kg"], 79.5)
        # ...while the machine-sourced fields in the same row are wiped.
        self.assertIsNone(row["resting_hr"])
        self.assertIsNone(row["hrv_sdnn"])

    def test_every_body_composition_field_is_out_of_the_clear_list(self) -> None:
        # Guards the constant itself, so adding a fifth field to
        # BODY_COMPOSITION_FIELDS without thinking about the clear path
        # fails here rather than silently losing data on the next
        # --replace-range run.
        for field in csv_store_dense.BODY_COMPOSITION_FIELDS:
            self.assertNotIn(field, hae.RANGE_FIELDS_TO_CLEAR)


class HealthAutoExportJsonBodyCompositionTests(WarnStateTestCase):
    """The JSON reader carries the same unit awareness the CSV reader has.

    HealthAutoExport writes the user's in-app unit preference into the
    metric's ``units`` field, so an imperial export sends waist in inches
    and lean mass in pounds over identical JSON. Assuming metric has
    already cost this repo one silent corruption.
    """

    @staticmethod
    def _parse(name: str, units: str, qty):
        err = StringIO()
        with redirect_stderr(err):
            metrics, _sleep, _w, _s = hae.parse_health_auto_export_json(
                {"data": {"workouts": [], "metrics": [{
                    "name": name, "units": units,
                    "data": [{"date": "2026-08-01 07:30:00 +0200",
                              "qty": qty, "source": "Device"}],
                }]}},
                None, None,
            )
        return (metrics[0] if metrics else {}), err.getvalue()

    def test_waist_is_unit_aware_cm_and_inches(self) -> None:
        row, _ = self._parse("waist_circumference", "cm", 84.5)
        self.assertEqual(row["waist_cm"], 84.5)
        row, _ = self._parse("waist_circumference", "in", 33.27)
        self.assertEqual(row["waist_cm"], 84.5)

    def test_lean_mass_is_unit_aware_kg_and_pounds(self) -> None:
        row, _ = self._parse("lean_body_mass", "kg", 63.2)
        self.assertEqual(row["lean_body_mass_kg"], 63.2)
        row, _ = self._parse("lean_body_mass", "lb", 139.33)
        self.assertEqual(row["lean_body_mass_kg"], 63.2)

    def test_body_fat_accepts_both_encodings(self) -> None:
        self.assertEqual(self._parse("body_fat_percentage", "%", 0.181)[0]["body_fat_pct"], 18.1)
        self.assertEqual(self._parse("body_fat_percentage", "%", 18.1)[0]["body_fat_pct"], 18.1)

    def test_an_unknown_unit_drops_the_value_rather_than_storing_it_raw(self) -> None:
        row, err = self._parse("waist_circumference", "cubits", 84.5)
        self.assertNotIn("waist_cm", row)
        self.assertIn("unknown", err)

    def test_a_clean_conversion_to_an_impossible_body_still_drops(self) -> None:
        # "84.5 m" converts cleanly to 8450 cm. The unit table cannot
        # catch that; the plausibility gate is what does.
        row, err = self._parse("waist_circumference", "m", 84.5)
        self.assertNotIn("waist_cm", row)
        self.assertIn("plausible", err)

    def test_an_absent_metric_leaves_the_cell_blank_not_zero(self) -> None:
        row, _ = self._parse("weight_body_mass", "kg", 79.8)
        self.assertEqual(row["bodyweight_kg"], 79.8)
        for field in ("waist_cm", "body_fat_pct", "lean_body_mass_kg"):
            self.assertIsNone(row.get(field))

    def test_body_composition_lines_name_the_gap_on_a_json_import(self) -> None:
        row, _ = self._parse("weight_body_mass", "kg", 79.8)
        lines = body_composition_lines([row])
        self.assertTrue(any("Bodyweight: 1 dates" in ln for ln in lines))
        self.assertTrue(any("Waist: 0 dates" in ln for ln in lines))


# ------------------------------------------------------------- CSV store
class HealthMetricsSchemaTests(WarnStateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = person_paths.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = Path(self.tmp.name)
        csv_store.write_profile("Test", source="health_auto_export", auto_cardio=True)

    def tearDown(self) -> None:
        person_paths.WORKOUT_TRACKER_ROOT = self.old_root
        self.tmp.cleanup()

    def _header(self) -> list[str]:
        with person_paths.health_metrics_csv("Test").open(encoding="utf-8") as f:
            return next(csv.reader(f))

    def test_new_columns_sit_before_notes_and_roundtrip(self) -> None:
        csv_store.upsert_health_metrics("Test", [{
            "date": "2026-08-01",
            "bodyweight_kg": 79.5,
            "waist_cm": 84.5,
            "body_fat_pct": 18.1,
            "lean_body_mass_kg": 63.2,
        }])
        header = self._header()
        self.assertEqual(
            header[-7:],
            ["Waist (cm)", "Body Fat %", "Lean Mass (kg)",
             "Steps", "Active Energy (kcal)", "Basal Energy (kcal)", "Notes"],
        )

        row = csv_store.read_health_metrics("Test")[0]
        self.assertEqual(row["waist_cm"], 84.5)
        self.assertEqual(row["body_fat_pct"], 18.1)
        self.assertEqual(row["lean_body_mass_kg"], 63.2)

    def test_sparse_merge_never_overwrites_a_populated_cell_with_none(self) -> None:
        csv_store.upsert_health_metrics("Test", [{"date": "2026-08-01", "waist_cm": 84.5}])
        # A later Apple import that carries no waist record at all.
        csv_store.upsert_health_metrics("Test", [{
            "date": "2026-08-01",
            "bodyweight_kg": 79.5,
            "waist_cm": None,
            "body_fat_pct": None,
            "lean_body_mass_kg": None,
        }])
        row = csv_store.read_health_metrics("Test")[0]
        self.assertEqual(row["waist_cm"], 84.5)
        self.assertEqual(row["bodyweight_kg"], 79.5)

    def test_manual_waist_merges_onto_an_existing_importer_row(self) -> None:
        # The importer has already written the day's recovery metrics
        # when a hand-entered waist reading arrives for the same date.
        # Today that reading is typed into Apple's Health app (Browse ›
        # Body Measurements) and reaches this CSV on a later import;
        # ``/log`` has no waist path — append_workout.py takes
        # ``bodyweight`` only. Either way the merge has to be additive,
        # which is what this pins.
        csv_store.upsert_health_metrics("Test", [{
            "date": "2026-08-01", "resting_hr": 53, "hrv_sdnn": 40.6,
        }])
        csv_store.upsert_health_metrics("Test", [{"date": "2026-08-01", "waist_cm": 84.5}])

        rows = csv_store.read_health_metrics("Test")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["waist_cm"], 84.5)
        self.assertEqual(rows[0]["resting_hr"], 53)
        self.assertEqual(rows[0]["hrv_sdnn"], 40.6)

    def test_repeated_identical_writes_are_idempotent(self) -> None:
        entry = {"date": "2026-08-01", "waist_cm": 84.5, "body_fat_pct": 18.1}
        csv_store.upsert_health_metrics("Test", [entry])
        first = person_paths.health_metrics_csv("Test").read_text(encoding="utf-8")
        csv_store.upsert_health_metrics("Test", [dict(entry)])
        second = person_paths.health_metrics_csv("Test").read_text(encoding="utf-8")

        self.assertEqual(first, second)
        self.assertEqual(len(csv_store.read_health_metrics("Test")), 1)

    def test_pre_migration_16_column_file_reads_and_self_migrates(self) -> None:
        # The on-disk shape of both real trackers before this change.
        legacy_header = [
            "Date", "Bodyweight (kg)", "VO2max", "Resting HR", "HRV SDNN",
            "Walking HR", "HR Recovery 1min", "Sleep Total", "Sleep Deep",
            "Sleep REM", "Time in Bed", "Resp Rate", "Wrist Temp",
            "Sleep Breath Dist", "Exercise Min", "Notes",
        ]
        legacy_row = [
            "2026-07-31", "79.2", "", "54", "38.1", "85", "", "7.0", "1.1",
            "1.5", "", "14.5", "36.2", "0.55", "", "felt flat",
        ]
        path = person_paths.health_metrics_csv("Test")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(legacy_header)
            w.writerow(legacy_row)

        # Reads by header name, so the narrower file still parses and the
        # new fields come back blank rather than shifted or garbled.
        row = csv_store.read_health_metrics("Test")[0]
        self.assertEqual(row["bodyweight_kg"], 79.2)
        self.assertEqual(row["wrist_temp_c"], 36.2)
        self.assertEqual(row["notes"], "felt flat")
        self.assertIsNone(row["waist_cm"])
        self.assertIsNone(row["body_fat_pct"])
        self.assertIsNone(row["lean_body_mass_kg"])

        # Next write pads the old row and lands the new header.
        csv_store.upsert_health_metrics("Test", [{"date": "2026-08-01", "waist_cm": 84.5}])
        self.assertEqual(len(self._header()), 22)
        rows = {r["date"]: r for r in csv_store.read_health_metrics("Test")}
        self.assertEqual(rows["2026-07-31"]["notes"], "felt flat")
        self.assertIsNone(rows["2026-07-31"]["waist_cm"])
        self.assertEqual(rows["2026-08-01"]["waist_cm"], 84.5)

    def test_explicit_header_migration_preserves_values_and_is_idempotent(self) -> None:
        csv_store.upsert_health_metrics("Test", [{"date": "2026-08-01", "bodyweight_kg": 79.5}])
        path = person_paths.health_metrics_csv("Test")
        # Rewind the file to the pre-migration shape.
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(rows[0][:15] + ["Notes"])
            w.writerow(rows[1][:15] + [rows[1][-1]])

        first = csv_store_dense.migrate_health_metrics_header("Test")
        self.assertIn("header migrated", first)
        self.assertEqual(len(self._header()), 22)
        self.assertEqual(csv_store.read_health_metrics("Test")[0]["bodyweight_kg"], 79.5)

        second = csv_store_dense.migrate_health_metrics_header("Test")
        self.assertIn("already current", second)


class ReadBodyCompositionTests(WarnStateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = person_paths.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = Path(self.tmp.name)
        csv_store.write_profile("Test", source="health_auto_export", auto_cardio=True)

    def tearDown(self) -> None:
        person_paths.WORKOUT_TRACKER_ROOT = self.old_root
        self.tmp.cleanup()

    def test_returns_ascending_dated_values_and_skips_blanks(self) -> None:
        csv_store.upsert_health_metrics("Test", [
            {"date": "2026-08-01", "waist_cm": 84.5},
            {"date": "2026-07-25", "waist_cm": 85.0},
            {"date": "2026-07-18", "bodyweight_kg": 79.0},  # no waist
        ])
        series = csv_store_dense.read_body_composition("Test", "waist_cm")

        self.assertEqual(series, [
            {"date": "2026-07-25", "value": 85.0},
            {"date": "2026-08-01", "value": 84.5},
        ])

    def test_unmeasured_field_returns_empty_not_zeros(self) -> None:
        csv_store.upsert_health_metrics("Test", [{"date": "2026-08-01", "bodyweight_kg": 79.5}])
        self.assertEqual(csv_store_dense.read_body_composition("Test", "waist_cm"), [])
        self.assertEqual(csv_store_dense.read_body_composition("Test", "body_fat_pct"), [])
        self.assertEqual(csv_store_dense.read_body_composition("Test", "lean_body_mass_kg"), [])

    def test_bodyweight_matches_the_existing_read_path(self) -> None:
        # Same source column and ordering contract as the coach's
        # extract.read_bodyweight, so a trend helper works on either.
        csv_store.upsert_health_metrics("Test", [
            {"date": "2026-08-01", "bodyweight_kg": 79.5},
            {"date": "2026-07-25", "bodyweight_kg": 78.9},
        ])
        series = csv_store_dense.read_body_composition("Test", "bodyweight_kg")
        self.assertEqual([e["date"] for e in series], ["2026-07-25", "2026-08-01"])
        self.assertEqual([e["value"] for e in series], [78.9, 79.5])

    def test_unknown_field_raises_rather_than_returning_empty(self) -> None:
        with self.assertRaises(ValueError):
            csv_store_dense.read_body_composition("Test", "visceral_fat")


# ------------------------------------------------------- maintain.py wiring
class MaintainHeaderValidationTests(WarnStateTestCase):
    """A header mismatch must not switch the rest of validation off.

    Both real trackers sit on a 16-column health_metrics.csv against the
    19-column schema. Under the old ``continue`` that bought them the
    mismatch line and nothing else — no DESC-order check, no row count —
    for the whole duration of the migration.
    """

    LEGACY_HEADER = [
        "Date", "Bodyweight (kg)", "VO2max", "Resting HR", "HRV SDNN",
        "Walking HR", "HR Recovery 1min", "Sleep Total", "Sleep Deep",
        "Sleep REM", "Time in Bed", "Resp Rate", "Wrist Temp",
        "Sleep Breath Dist", "Exercise Min", "Notes",
    ]

    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = person_paths.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = Path(self.tmp.name)
        csv_store.write_profile("Test", source="health_auto_export", auto_cardio=True)

    def tearDown(self) -> None:
        person_paths.WORKOUT_TRACKER_ROOT = self.old_root
        self.tmp.cleanup()

    def _write_legacy(self, rows: list[list[str]]) -> Path:
        path = person_paths.health_metrics_csv("Test")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(self.LEGACY_HEADER)
            w.writerows(rows)
        return path

    @staticmethod
    def _line(lines: list[str], label: str) -> list[str]:
        return [ln for ln in lines if ln.startswith(label)]

    def test_row_count_is_still_reported_under_a_header_mismatch(self) -> None:
        self._write_legacy([
            ["2026-08-01"] + [""] * 15,
            ["2026-07-31"] + [""] * 15,
        ])
        lines = maintain.validate_csvs("Test")
        hm = self._line(lines, "health_metrics.csv")

        self.assertTrue(any("header mismatch" in ln for ln in hm), hm)
        self.assertTrue(any("2 rows ok" in ln for ln in hm), hm)

    def test_sort_order_is_still_checked_under_a_header_mismatch(self) -> None:
        # Dates ASC on a file the schema says is DESC. The old code never
        # got here.
        self._write_legacy([
            ["2026-07-31"] + [""] * 15,
            ["2026-08-01"] + [""] * 15,
        ])
        hm = self._line(maintain.validate_csvs("Test"), "health_metrics.csv")

        self.assertTrue(any("header mismatch" in ln for ln in hm), hm)
        self.assertTrue(any("dates not strictly DESC" in ln for ln in hm), hm)

    def test_the_mismatch_line_names_the_column_counts_and_the_remedy(self) -> None:
        self._write_legacy([["2026-08-01"] + [""] * 15])
        mismatch = next(
            ln for ln in maintain.validate_csvs("Test") if "header mismatch" in ln
        )
        self.assertIn("got 16 cols", mismatch)
        self.assertIn("expected 22 cols", mismatch)
        self.assertIn("--fix-header", mismatch)

    def test_a_current_header_reports_no_mismatch(self) -> None:
        csv_store.upsert_health_metrics("Test", [{"date": "2026-08-01", "waist_cm": 84.5}])
        hm = self._line(maintain.validate_csvs("Test"), "health_metrics.csv")
        self.assertEqual(hm, ["health_metrics.csv: 1 rows ok"])

    def test_validate_never_rewrites_the_file(self) -> None:
        # The whole reason the migration is a flag: a diagnostics run must
        # not mutate the user's CSV as a side effect of being asked a
        # question.
        path = self._write_legacy([["2026-08-01", "79.5"] + [""] * 14])
        before = path.read_bytes()
        maintain.validate_csvs("Test")
        self.assertEqual(path.read_bytes(), before)

    def test_fix_header_flag_migrates_and_is_idempotent(self) -> None:
        self._write_legacy([["2026-08-01", "79.5"] + [""] * 13 + ["felt flat"]])
        path = person_paths.health_metrics_csv("Test")

        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(maintain.fix_health_metrics_header("Test"), 0)
        self.assertIn("header migrated", out.getvalue())

        with path.open(encoding="utf-8") as f:
            self.assertEqual(len(next(csv.reader(f))), 22)
        row = csv_store.read_health_metrics("Test")[0]
        self.assertEqual(row["bodyweight_kg"], 79.5)
        self.assertEqual(row["notes"], "felt flat")
        self.assertEqual(maintain.validate_csvs("Test")[0], "health_metrics.csv: 1 rows ok")

        out = StringIO()
        with redirect_stdout(out):
            maintain.fix_health_metrics_header("Test")
        self.assertIn("already current", out.getvalue())

    def test_fix_header_dry_run_writes_nothing(self) -> None:
        path = self._write_legacy([["2026-08-01", "79.5"] + [""] * 14])
        before = path.read_bytes()

        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(maintain.fix_health_metrics_header("Test", dry_run=True), 0)

        self.assertIn("would migrate", out.getvalue())
        self.assertIn("1 rows preserved", out.getvalue())
        self.assertEqual(path.read_bytes(), before)

    def test_the_migration_is_reachable_from_production_code(self) -> None:
        # It used to be called only by its own test.
        self.assertIs(
            maintain.migrate_health_metrics_header,
            csv_store.migrate_health_metrics_header,
        )
        self.assertIn("--fix-header", maintain.HEADER_FIX_HINTS["health_metrics.csv"])


class CsvStoreFacadeTests(unittest.TestCase):
    """Skills/CLAUDE.md designates csv_store the public-import facade."""

    def test_body_composition_surface_is_exported(self) -> None:
        for name in ("BODY_COMPOSITION_FIELDS", "read_body_composition",
                     "migrate_health_metrics_header"):
            self.assertIn(name, csv_store.__all__, name)
            self.assertIs(getattr(csv_store, name), getattr(csv_store_dense, name))


if __name__ == "__main__":
    unittest.main()
