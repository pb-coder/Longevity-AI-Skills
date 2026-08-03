"""W7b — leanness channel: waist / body fat / lean mass end to end.

Covers both import paths (Apple's native XML and HealthAutoExport), the
health_metrics.csv schema migration, and the manual-entry path a tape
measure reading arrives on.

The absence cases matter as much as the presence ones: the export in hand
today carries Body Mass and nothing else, so every record type here is
one the importer must handle by leaving the cell blank rather than
writing a zero.
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
from shared.apple_health_core import (
    PLAUSIBLE_RANGES,
    normalize_body_fat_pct,
    reset_unit_warnings,
)
from shared.apple_health_daily import DayAggregator, WANTED_RECORD_TYPES
from shared.import_apple_health import body_composition_lines, consume_apple_export

WAIST_TYPE = "HKQuantityTypeIdentifierWaistCircumference"
BODY_FAT_TYPE = "HKQuantityTypeIdentifierBodyFatPercentage"
LEAN_MASS_TYPE = "HKQuantityTypeIdentifierLeanBodyMass"

DT = datetime(2026, 8, 1, 7, 30)


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


def _record(agg: DayAggregator, rtype: str, value: str, unit: str | None,
            d: str = "2026-08-01", dt: datetime = DT) -> None:
    attrib = {"type": rtype, "value": value}
    if unit is not None:
        attrib["unit"] = unit
    agg.add_record(attrib, d, dt)


def _emit_one(agg: DayAggregator) -> dict:
    rows = list(agg.emit(None))
    assert len(rows) == 1, rows
    return rows[0]


# ------------------------------------------------------- Apple native XML
class AppleXmlBodyCompositionTests(WarnStateTestCase):
    def test_record_types_are_wanted_by_the_streaming_filter(self) -> None:
        # consume_apple_export() only dispatches types in this set, so a
        # handler that is not listed here is dead code.
        for rtype in (WAIST_TYPE, BODY_FAT_TYPE, LEAN_MASS_TYPE):
            self.assertIn(rtype, WANTED_RECORD_TYPES)

    def test_waist_is_unit_aware_cm_and_inches(self) -> None:
        agg = DayAggregator()
        _record(agg, WAIST_TYPE, "84.5", "cm")
        self.assertEqual(_emit_one(agg)["waist_cm"], 84.5)

        agg = DayAggregator()
        _record(agg, WAIST_TYPE, "33", "in")
        self.assertEqual(_emit_one(agg)["waist_cm"], 83.8)  # 33 * 2.54

    def test_body_fat_fraction_is_stored_as_percentage_points(self) -> None:
        agg = DayAggregator()
        _record(agg, BODY_FAT_TYPE, "0.181", "%")
        self.assertEqual(_emit_one(agg)["body_fat_pct"], 18.1)

    def test_lean_body_mass_is_unit_aware_kg_and_pounds(self) -> None:
        agg = DayAggregator()
        _record(agg, LEAN_MASS_TYPE, "63.2", "kg")
        self.assertEqual(_emit_one(agg)["lean_body_mass_kg"], 63.2)

        agg = DayAggregator()
        _record(agg, LEAN_MASS_TYPE, "140", "lb")
        self.assertEqual(_emit_one(agg)["lean_body_mass_kg"], 63.5)

    def test_latest_reading_of_the_day_wins(self) -> None:
        agg = DayAggregator()
        _record(agg, WAIST_TYPE, "86", "cm", dt=datetime(2026, 8, 1, 7, 0))
        _record(agg, WAIST_TYPE, "84", "cm", dt=datetime(2026, 8, 1, 19, 0))
        self.assertEqual(_emit_one(agg)["waist_cm"], 84.0)

    def test_unknown_waist_unit_warns_and_skips_rather_than_mis_storing(self) -> None:
        # The swim-distance bug (550 m written as 550 km) is the reason
        # this path drops the value instead of passing it through.
        agg = DayAggregator()
        err = StringIO()
        with redirect_stderr(err):
            _record(agg, WAIST_TYPE, "33", "cubits")
        self.assertIn("unknown waist circumference unit", err.getvalue())
        self.assertEqual(agg.waist_cm, {})

    # ------------------------------------------------ plausibility gate
    # A known unit converts cleanly and still produces nonsense: metres
    # and grams are in the conversion tables, so "84.5 m" and "63.2 g"
    # sail straight through unit handling. upsert_health_metrics is a
    # sparse merge, so a poisoned cell is permanent — no later import
    # overwrites it, only a hand edit of the CSV. Same failure class as
    # the swim distances once stored as 550 km.

    def test_waist_in_metres_is_dropped_not_stored_as_8450_cm(self) -> None:
        agg = DayAggregator()
        err = StringIO()
        with redirect_stderr(err):
            _record(agg, WAIST_TYPE, "84.5", "m")
        self.assertEqual(agg.waist_cm, {})
        self.assertIn("waist circumference", err.getvalue())
        self.assertIn("outside the plausible 30-250 range", err.getvalue())
        self.assertIn("'m'", err.getvalue())
        # Nothing reaches the payload, so the sparse-merge upsert is never
        # handed a cell to poison.
        self.assertEqual(list(agg.emit(None)), [])

    def test_a_dropped_waist_leaves_a_co_recorded_metric_alone(self) -> None:
        # The drop is surgical: the day's other readings still emit.
        agg = DayAggregator()
        with redirect_stderr(StringIO()):
            _record(agg, WAIST_TYPE, "84.5", "m")
        _record(agg, "HKQuantityTypeIdentifierBodyMass", "79.5", "kg")
        row = _emit_one(agg)
        self.assertEqual(row["bodyweight_kg"], 79.5)
        self.assertIsNone(row["waist_cm"])

    def test_lean_mass_in_grams_is_dropped_not_stored_as_0_06_kg(self) -> None:
        agg = DayAggregator()
        err = StringIO()
        with redirect_stderr(err):
            _record(agg, LEAN_MASS_TYPE, "63.2", "g")
        self.assertEqual(agg.lean_body_mass_kg, {})
        self.assertIn("lean body mass", err.getvalue())
        self.assertIn("outside the plausible 20-150 range", err.getvalue())

    def test_absurd_waist_in_a_correct_unit_is_still_dropped(self) -> None:
        # No bad unit anywhere: "8450 cm" is a well-formed reading of an
        # impossible body. The unit table cannot catch this one at all.
        agg = DayAggregator()
        err = StringIO()
        with redirect_stderr(err):
            _record(agg, WAIST_TYPE, "8450", "cm")
        self.assertEqual(agg.waist_cm, {})
        self.assertIn("outside the plausible 30-250 range", err.getvalue())

    def test_waist_range_boundaries_are_inclusive(self) -> None:
        for value, expected in ((30.0, 30.0), (250.0, 250.0)):
            agg = DayAggregator()
            _record(agg, WAIST_TYPE, str(value), "cm")
            self.assertEqual(_emit_one(agg)["waist_cm"], expected, value)
        for value in (29.9, 250.1):
            agg = DayAggregator()
            with redirect_stderr(StringIO()):
                _record(agg, WAIST_TYPE, str(value), "cm")
            self.assertEqual(agg.waist_cm, {}, value)

    def test_lean_mass_range_boundaries_are_inclusive(self) -> None:
        for value in (20.0, 150.0):
            agg = DayAggregator()
            _record(agg, LEAN_MASS_TYPE, str(value), "kg")
            self.assertEqual(_emit_one(agg)["lean_body_mass_kg"], value)
        for value in (19.9, 150.1):
            agg = DayAggregator()
            with redirect_stderr(StringIO()):
                _record(agg, LEAN_MASS_TYPE, str(value), "kg")
            self.assertEqual(agg.lean_body_mass_kg, {}, value)

    def test_a_plausible_reading_in_a_non_metric_unit_still_lands(self) -> None:
        # The gate must not become a metric-only filter: 33 in and 140 lb
        # are ordinary readings that happen to need converting first.
        agg = DayAggregator()
        _record(agg, WAIST_TYPE, "33", "in")
        _record(agg, LEAN_MASS_TYPE, "140", "lb")
        row = _emit_one(agg)
        self.assertEqual(row["waist_cm"], 83.8)
        self.assertEqual(row["lean_body_mass_kg"], 63.5)

    def test_body_fat_reads_its_unit_attribute_like_its_siblings(self) -> None:
        # Waist drops "cubits" loudly; body fat used to ignore the unit
        # entirely and accept 0.18 cubits as 18%.
        agg = DayAggregator()
        err = StringIO()
        with redirect_stderr(err):
            _record(agg, BODY_FAT_TYPE, "0.18", "cubits")
        self.assertEqual(agg.body_fat_pct, {})
        self.assertIn("unknown body fat percentage unit", err.getvalue())

    def test_body_fat_accepts_the_units_apple_actually_emits(self) -> None:
        for unit in ("%", "percent", None):
            agg = DayAggregator()
            _record(agg, BODY_FAT_TYPE, "0.18", unit)
            self.assertEqual(_emit_one(agg)["body_fat_pct"], 18.0, unit)

    def test_absent_record_types_emit_none_never_zero(self) -> None:
        # The common case today: the export carries Body Mass only. The
        # other three must come back None so the sparse-merge upsert skips
        # the cells instead of stamping 0.0 over them.
        agg = DayAggregator()
        _record(agg, "HKQuantityTypeIdentifierBodyMass", "79.5", "kg")
        row = _emit_one(agg)

        self.assertEqual(row["bodyweight_kg"], 79.5)
        self.assertIsNone(row["waist_cm"])
        self.assertIsNone(row["body_fat_pct"])
        self.assertIsNone(row["lean_body_mass_kg"])

    def test_a_day_with_only_a_waist_reading_still_emits_a_row(self) -> None:
        # Waist arrives weekly and on its own; it must not need a
        # co-occurring metric to create the day's row.
        agg = DayAggregator()
        _record(agg, WAIST_TYPE, "84.5", "cm")
        row = _emit_one(agg)
        self.assertEqual(row["date"], "2026-08-01")
        self.assertEqual(row["waist_cm"], 84.5)
        self.assertIsNone(row["bodyweight_kg"])

    def test_body_composition_lines_name_the_missing_metrics(self) -> None:
        lines = body_composition_lines([
            {"date": "2026-08-01", "bodyweight_kg": 79.5, "waist_cm": None,
             "body_fat_pct": None, "lean_body_mass_kg": None},
        ])
        joined = "\n".join(lines)
        self.assertIn("Bodyweight: 1 dates (latest 2026-08-01)", joined)
        self.assertIn("Waist: 0 dates — not recorded in this export", joined)
        self.assertIn("Body Fat: 0 dates — not recorded in this export", joined)
        self.assertIn("Lean Mass: 0 dates — not recorded in this export", joined)


def _export_zip(path: Path, records_xml: str) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<HealthData locale=\"en_DE\">\n" + records_xml + "\n</HealthData>\n"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("apple_health_export/Export.xml", xml)


class AppleXmlStreamingTests(WarnStateTestCase):
    """Exercise the real iterparse path, not just DayAggregator.add_record."""

    def _consume(self, records_xml: str, since=None) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Export.zip"
            _export_zip(path, records_xml)
            agg = DayAggregator()
            consume_apple_export(path, since, agg, [])
            return list(agg.emit(since))

    def test_body_composition_records_survive_the_streaming_filter(self) -> None:
        rows = self._consume(
            '  <Record type="HKQuantityTypeIdentifierWaistCircumference" unit="cm"'
            ' startDate="2026-08-01 07:30:00 +0200" endDate="2026-08-01 07:30:00 +0200"'
            ' value="84.5"/>\n'
            '  <Record type="HKQuantityTypeIdentifierBodyFatPercentage" unit="%"'
            ' startDate="2026-08-01 07:31:00 +0200" endDate="2026-08-01 07:31:00 +0200"'
            ' value="0.181"/>\n'
            '  <Record type="HKQuantityTypeIdentifierLeanBodyMass" unit="kg"'
            ' startDate="2026-08-01 07:31:00 +0200" endDate="2026-08-01 07:31:00 +0200"'
            ' value="63.2"/>\n'
            '  <Record type="HKQuantityTypeIdentifierBodyMass" unit="kg"'
            ' startDate="2026-08-01 07:32:00 +0200" endDate="2026-08-01 07:32:00 +0200"'
            ' value="79.5"/>'
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["waist_cm"], 84.5)
        self.assertEqual(rows[0]["body_fat_pct"], 18.1)
        self.assertEqual(rows[0]["lean_body_mass_kg"], 63.2)
        self.assertEqual(rows[0]["bodyweight_kg"], 79.5)

    def test_export_without_body_composition_leaves_the_columns_blank(self) -> None:
        # <Person>'s actual export shape: Body Mass and nothing else.
        rows = self._consume(
            '  <Record type="HKQuantityTypeIdentifierBodyMass" unit="kg"'
            ' startDate="2026-08-01 07:32:00 +0200" endDate="2026-08-01 07:32:00 +0200"'
            ' value="79.5"/>'
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bodyweight_kg"], 79.5)
        self.assertIsNone(rows[0]["waist_cm"])
        self.assertIsNone(rows[0]["body_fat_pct"])
        self.assertIsNone(rows[0]["lean_body_mass_kg"])

    def test_reimport_is_idempotent_on_the_csv(self) -> None:
        records = (
            '  <Record type="HKQuantityTypeIdentifierWaistCircumference" unit="cm"'
            ' startDate="2026-08-01 07:30:00 +0200" endDate="2026-08-01 07:30:00 +0200"'
            ' value="84.5"/>'
        )
        tmp = tempfile.TemporaryDirectory()
        old_root = person_paths.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = Path(tmp.name)
        try:
            csv_store.write_profile("Test", source="xml", auto_cardio=True)
            export = Path(tmp.name) / "Export.zip"
            _export_zip(export, records)

            for _ in range(2):
                agg = DayAggregator()
                consume_apple_export(export, None, agg, [])
                csv_store.upsert_health_metrics("Test", list(agg.emit(None)))

            rows = csv_store.read_health_metrics("Test")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["waist_cm"], 84.5)
        finally:
            person_paths.WORKOUT_TRACKER_ROOT = old_root
            tmp.cleanup()


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
                metrics, _sleep, _workouts = hae.parse_health_auto_export_zip(
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


# ------------------------------------------------------------- CSV store
class HealthMetricsSchemaTests(WarnStateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = person_paths.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = Path(self.tmp.name)
        csv_store.write_profile("Test", source="xml", auto_cardio=True)

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
        self.assertEqual(header[-4:], ["Waist (cm)", "Body Fat %", "Lean Mass (kg)", "Notes"])

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
        self.assertEqual(len(self._header()), 19)
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
        self.assertEqual(len(self._header()), 19)
        self.assertEqual(csv_store.read_health_metrics("Test")[0]["bodyweight_kg"], 79.5)

        second = csv_store_dense.migrate_health_metrics_header("Test")
        self.assertIn("already current", second)


class ReadBodyCompositionTests(WarnStateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = person_paths.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = Path(self.tmp.name)
        csv_store.write_profile("Test", source="xml", auto_cardio=True)

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
        csv_store.write_profile("Test", source="xml", auto_cardio=True)

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
        self.assertIn("expected 19 cols", mismatch)
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
            self.assertEqual(len(next(csv.reader(f))), 19)
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
