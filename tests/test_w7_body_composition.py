"""W7b — leanness channel: waist / body fat / lean mass end to end.

Covers the unit/range normalisation, the health_metrics.csv schema
migration, and the manual-entry path a tape measure reading arrives on.

The absence cases matter as much as the presence ones: every metric here
is one the store must handle by leaving the cell blank rather than
writing a zero.
"""
from __future__ import annotations

import csv
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from shared import csv_store, csv_store_dense, maintain, person_paths
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
