"""Waist circumference: stored -> payload -> dashboard.

Both importers have written ``Waist (cm)`` to ``health_metrics.csv`` since
the 2026-08 schema migration, and until this build nothing read it back:
the number was saved and invisible. These tests cover the read side.

Three things are load-bearing here and each has its own section below.

1. **A trend over one point is not a trend.** The tracker holds exactly
   one waist measurement today. ``waist_trend`` must return its explicit
   unresolved state for that, not ``0.0``, not a null that reads as zero,
   and not a two-point slope. This repo has already shipped that bug once
   on bodyweight (a confident -0.37 kg/wk over a stretch whose honest fit
   was +0.07 +/- 0.25), which is why the waist estimator routes through
   the same gate rather than growing its own.
2. **The ``--today`` horizon.** A payload anchored on a past date may not
   contain a measurement taken after it. The codebase had a systemic leak
   of exactly this shape; a new column is a new place for it to come back.
3. **An empty or single-point channel says so.** The dashboard row must
   render and state the gap, rather than drawing a flat line through one
   point or disappearing.

The fixtures here are synthetic and written to a temp directory. Nothing
in this file reads or writes a real person's CSV store.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from workout_coach.lib.render_cards_health import card_vitals
from workout_coach.lib.sessions import (
    WAIST_TREND_MIN_READINGS,
    WAIST_TREND_MIN_WINDOW_DAYS,
    bodyweight_trend,
    waist_trend,
)

SKILLS_ROOT = Path(__file__).resolve().parents[1]
READ_TRACKER = SKILLS_ROOT / "workout-coach" / "scripts" / "read_tracker.py"

_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
# A CSS hex literal. The negative lookbehind spares HTML entities
# (``&#x27;``), which are not colours.
_HEX_LITERAL_RE = re.compile(r"(?<!&)#[0-9a-fA-F]{3,8}\b")


def _readings(pairs):
    return [{"date": d, "cm": cm} for d, cm in pairs]


def _weekly_series(dates_start: str, values):
    """``health_metrics_weekly``-shaped rows carrying ``waist_cm``."""
    start = date.fromisoformat(dates_start)
    return [
        {"week_start": (start + timedelta(days=7 * i)).isoformat(),
         "hrv_sdnn": 55, "waist_cm": v}
        for i, v in enumerate(values)
    ]


# ------------------------------------------------------------------ 1.
class WaistTrendHonestyTests(unittest.TestCase):
    """What the estimator is allowed to claim, and when."""

    def test_one_measurement_is_not_a_trend(self) -> None:
        block = waist_trend(_readings([("2026-08-02", 87.0)]),
                            today_d="2026-08-02")
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "too_few_readings")
        self.assertEqual(block["n_readings"], 1)
        # The three shapes a fabricated answer could take.
        self.assertIsNone(block["cm_per_4w"])
        self.assertNotEqual(block["cm_per_4w"], 0.0)
        self.assertIsNone(block["point_cm_per_4w"])
        self.assertIsNone(block["ci95_cm_per_4w"])
        self.assertIn("not a trend", block["note"])

    def test_no_measurements_at_all_is_its_own_reason(self) -> None:
        block = waist_trend([], today_d="2026-08-02")
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "no_readings")
        self.assertEqual(block["n_readings"], 0)
        self.assertIsNone(block["cm_per_4w"])

    def test_two_measurements_do_not_produce_a_slope(self) -> None:
        """The exact shape of the bug this estimator exists to avoid."""
        block = waist_trend(
            _readings([("2026-06-10", 92.0), ("2026-08-02", 87.0)]),
            today_d="2026-08-02")
        self.assertEqual(block["reason"], "too_few_readings")
        self.assertIsNone(block["cm_per_4w"])
        self.assertIsNone(block["point_cm_per_4w"])

    def test_two_measurements_six_months_apart_do_not_produce_a_slope(self) -> None:
        """A long baseline does not buy back the missing sample size.

        It is also the case that the older reading is outside the window,
        so only one point is even eligible; both facts point the same way
        and neither yields a number.
        """
        block = waist_trend(
            _readings([("2026-02-02", 95.0), ("2026-08-02", 87.0)]),
            today_d="2026-08-02")
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "too_few_readings")
        self.assertEqual(block["n_readings"], 1)
        self.assertIsNone(block["cm_per_4w"])

    def test_enough_measurements_over_enough_days_do_resolve(self) -> None:
        """The channel is not unconditionally mute: a real, well-sampled
        change comes back as a number with a sign."""
        pts = []
        d0 = date(2026, 6, 8)
        for i in range(9):
            wobble = 0.15 if i % 2 == 0 else -0.15
            pts.append(((d0 + timedelta(days=7 * i)).isoformat(),
                        92.0 - 0.35 * i + wobble))
        block = waist_trend(_readings(pts), today_d="2026-08-03")
        self.assertEqual(block["state"], "resolved")
        self.assertIsNone(block["reason"])
        self.assertIsNotNone(block["cm_per_4w"])
        self.assertLess(block["cm_per_4w"], 0)
        self.assertIn("narrowing", block["note"])
        lo, hi = block["ci95_cm_per_4w"]
        self.assertLess(hi, 0.0, "a resolved fit must have an interval "
                                 "that excludes zero")
        self.assertLess(lo, hi)

    def test_noise_larger_than_the_signal_stays_unresolved(self) -> None:
        pts = []
        d0 = date(2026, 6, 8)
        for i in range(9):
            wobble = 1.6 if i % 2 == 0 else -1.6
            pts.append(((d0 + timedelta(days=7 * i)).isoformat(),
                        92.0 - 0.05 * i + wobble))
        block = waist_trend(_readings(pts), today_d="2026-08-03")
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "ci_straddles_zero")
        self.assertIsNone(block["cm_per_4w"])
        # The lean is still visible to a human, just not claimed.
        self.assertIsNotNone(block["point_cm_per_4w"])
        self.assertIn("Do not report", block["note"])

    def test_the_window_is_a_fixed_period_not_a_last_n_measurements_rule(self) -> None:
        """The field must always describe the same length of time.

        A "last N measurements" rule makes the window silently elastic: the
        same key covers 16 days at one anchor and 9 weeks at another, and
        nothing in the payload says which. Bodyweight was fixed for that
        reason and waist inherits the rule.
        """
        pairs = [((date(2026, 2, 1) + timedelta(days=14 * i)).isoformat(),
                  95.0 - 0.2 * i) for i in range(14)]
        block = waist_trend(_readings(pairs), today_d="2026-08-02")
        self.assertEqual(block["window_days"], WAIST_TREND_MIN_WINDOW_DAYS)
        self.assertEqual(block["window_start"], "2026-06-08")
        # Only the measurements inside that fixed period count, however
        # much older history exists.
        inside = [p for p in pairs if p[0] >= "2026-06-08"]
        self.assertEqual(block["n_readings"], len(inside))
        self.assertLess(len(inside), len(pairs))

    def test_widening_the_floor_changes_which_period_is_described(self) -> None:
        pairs = [((date(2026, 2, 1) + timedelta(days=14 * i)).isoformat(),
                  95.0 - 0.2 * i) for i in range(14)]
        narrow = waist_trend(_readings(pairs), today_d="2026-08-02")
        wide = waist_trend(_readings(pairs), today_d="2026-08-02",
                           min_window_days=168)
        self.assertEqual(wide["window_days"], 168)
        self.assertGreater(wide["n_readings"], narrow["n_readings"])
        # And the window it describes is reported, not implied.
        self.assertNotEqual(wide["window_start"], narrow["window_start"])

    def test_a_sparse_cadence_is_refused_rather_than_stretched(self) -> None:
        """Someone who measures monthly has fewer than four measurements in
        any 56-day window, so the honest answer is that the cadence is too
        sparse -- not a rate fitted over a quietly widened window."""
        monthly = [((date(2026, 1, 5) + timedelta(days=30 * i)).isoformat(),
                    95.0 - 0.4 * i) for i in range(8)]
        block = waist_trend(_readings(monthly), today_d="2026-08-02")
        self.assertEqual(block["reason"], "too_few_readings")
        self.assertIsNone(block["cm_per_4w"])
        self.assertLess(block["n_readings"], WAIST_TREND_MIN_READINGS)

    def test_all_measurements_on_one_day_has_no_slope_to_fit(self) -> None:
        block = waist_trend(
            _readings([("2026-08-02", 87.0), ("2026-08-02", 87.4),
                       ("2026-08-02", 86.8), ("2026-08-02", 87.1)]),
            today_d="2026-08-02")
        self.assertEqual(block["reason"], "no_time_variance")
        self.assertIsNone(block["cm_per_4w"])

    def test_a_unit_confused_reading_widens_the_interval_instead_of_the_slope(self) -> None:
        """Inches typed into a centimetre column survive the importer's
        corruption gate when they land inside 30-250. This estimator does
        not try to out-guess that gate; what it guarantees is that the
        outlier inflates the residual spread, so the verdict degrades to
        unresolved rather than to a confident (and enormous) slope."""
        clean = [("2026-06-08", 92.0), ("2026-06-22", 91.4),
                 ("2026-07-06", 90.9), ("2026-07-20", 90.3),
                 ("2026-08-02", 89.8)]
        honest = waist_trend(_readings(clean), today_d="2026-08-02")
        self.assertEqual(honest["state"], "resolved")

        confused = list(clean)
        confused[2] = ("2026-07-06", 35.0)   # 35 inches, stored as cm
        block = waist_trend(_readings(confused), today_d="2026-08-02")
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "ci_straddles_zero")
        self.assertIsNone(block["cm_per_4w"])

    def test_readings_after_the_anchor_are_outside_the_window(self) -> None:
        past = _readings([("2026-06-08", 92.0), ("2026-06-22", 91.4),
                          ("2026-07-06", 90.9), ("2026-07-20", 90.3)])
        future = _readings([("2026-09-01", 80.0), ("2026-10-01", 78.0)])
        anchored = waist_trend(past + future, today_d="2026-08-02")
        only_past = waist_trend(past, today_d="2026-08-02")
        self.assertEqual(anchored, only_past)
        self.assertEqual(anchored["window_end"], "2026-08-02")
        self.assertEqual(anchored["n_readings"], 4)

    def test_the_value_key_has_aliases_for_the_other_reader(self) -> None:
        """``csv_store_dense.read_body_composition`` yields ``value`` and a
        raw health row yields ``waist_cm``. A second tracked person on a
        different importer must not need an adapter."""
        pairs = [("2026-06-08", 92.0), ("2026-06-22", 91.4),
                 ("2026-07-06", 90.9), ("2026-07-20", 90.3)]
        by_cm = waist_trend(_readings(pairs), today_d="2026-08-02")
        by_value = waist_trend(
            [{"date": d, "value": v} for d, v in pairs], today_d="2026-08-02")
        by_raw = waist_trend(
            [{"date": d, "waist_cm": v} for d, v in pairs], today_d="2026-08-02")
        self.assertEqual(by_cm, by_value)
        self.assertEqual(by_cm, by_raw)

    def test_the_window_floor_is_stricter_than_bodyweights(self) -> None:
        """Waist is read off a tape and moves slowly; loosening its floor
        below bodyweight's would be the laxer second implementation this
        build exists to avoid."""
        self.assertGreaterEqual(WAIST_TREND_MIN_WINDOW_DAYS, 28)
        self.assertGreaterEqual(WAIST_TREND_MIN_READINGS, 4)

    def test_the_block_mirrors_the_bodyweight_block(self) -> None:
        bw = bodyweight_trend([], today_d="2026-08-02")
        waist = waist_trend([], today_d="2026-08-02")
        # ``span_days`` and ``days_since_last_reading`` are shared because
        # the gate that produces them is shared. They are also the two
        # keys that make ``window_days`` readable: a consumer holding only
        # the window cannot tell a month of readings from four taken on
        # one weekend, which is the shape that reported -2.80 cm/4wk with
        # a zero-width interval.
        # ``max_gap_days`` / ``effective_readings`` join them for the same
        # reason one step further in: the span is first-to-last and says
        # nothing about the DISTRIBUTION inside it, so a consumer holding
        # only the span cannot tell an even cadence from a cluster plus
        # one distant anchor -- the shape that resolved at -1.99 cm/4wk
        # off what was really a two-point slope.
        shared = {"state", "reason", "note", "n_readings",
                  "window_start", "window_end", "window_days",
                  "span_days", "days_since_last_reading",
                  "max_gap_days", "effective_readings", "method"}
        self.assertTrue(shared <= set(bw))
        self.assertTrue(shared <= set(waist))
        # Same key structure, unit-suffixed rate fields.
        self.assertEqual(
            {k for k in bw if k not in shared},
            {"kg_per_week", "point_kg_per_week", "se_kg_per_week",
             "ci95_kg_per_week"})
        self.assertEqual(
            {k for k in waist if k not in shared},
            {"cm_per_4w", "point_cm_per_4w", "se_cm_per_4w",
             "ci95_cm_per_4w"})


# ------------------------------------------------------------------ 2.
MONTHLY_HEADER = (
    "SESSION,Date,#,Exercise,Set,Reps,kg,Volume,Notes,Distance (km),"
    "Duration (min),Pace (min/km),Avg HR,Active Cal,Total Cal,"
    "Elevation (m),Elapsed,Source\n"
)

HEALTH_HEADER = (
    "Date,Bodyweight (kg),VO2max,Resting HR,HRV SDNN,Walking HR,"
    "HR Recovery 1min,Sleep Total,Sleep Deep,Sleep REM,Time in Bed,"
    "Resp Rate,Wrist Temp,Sleep Breath Dist,Exercise Min,"
    "Waist (cm),Body Fat %,Lean Mass (kg),Notes\n"
)

PROFILE = "key,value\nsource,xml\nauto_cardio,true\nbirthday,1995-01-01\n"

# Weekly health rows from early April to the end of August. The anchors the
# tests use all sit inside that span, so every anchor has rows on both
# sides of it and no horizon assertion can pass vacuously.
_HEALTH_DAYS = [(date(2026, 4, 4) + timedelta(days=7 * i)).isoformat()
                for i in range(22)]

# The person who measures: a steady taper with a small alternating wobble,
# so the fit is real but its residual variance is not degenerate.
_WAIST_BY_DATE = {
    d: round(94.0 - 0.35 * i + (0.15 if i % 2 == 0 else -0.15), 2)
    for i, d in enumerate(_HEALTH_DAYS)
}

# The person who has measured exactly once, which is the live tracker's
# actual shape today.
_SINGLE_WAIST_DATE = _HEALTH_DAYS[-4]

PERSON_MEASURES = "person_waist_series"
PERSON_ONCE = "person_waist_once"
PERSON_NONE = "person_waist_never"


def _write_person(root: Path, person: str, waist_for) -> None:
    data = root / person / "data"
    (data / "monthly").mkdir(parents=True)
    for ym in ("2026.04", "2026.05", "2026.06", "2026.07", "2026.08"):
        day = f"{ym.replace('.', '-')}-06"
        body = (
            f"1,{day},1,Barbell Back Squat,1,5,100,500,,,,,,,,,,manual\n"
            f"1,{day},1,Barbell Back Squat,2,5,100,500,,,,,,,,,,manual\n"
            f"1,{day},,TOTAL,,,,1000,,,60:00,,126,360,430,,60:00,manual\n"
        )
        (data / "monthly" / f"{ym}.csv").write_text(
            MONTHLY_HEADER + body, encoding="utf-8")

    rows = [HEALTH_HEADER]
    for i, day in enumerate(_HEALTH_DAYS):
        waist = waist_for(day)
        waist_cell = "" if waist is None else f"{waist}"
        rows.append(
            f"{day},{78.0 + i * 0.1:.1f},47.0,58,62,92,28,7.5,1.2,1.6,8.0,"
            f"14.2,36.4,0.1,45,{waist_cell},,,\n"
        )
    (data / "health_metrics.csv").write_text("".join(rows), encoding="utf-8")
    (data / "profile.csv").write_text(PROFILE, encoding="utf-8")


class _PayloadCase(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        _write_person(cls.root, PERSON_MEASURES, _WAIST_BY_DATE.get)
        _write_person(cls.root, PERSON_ONCE,
                      lambda d: 87.0 if d == _SINGLE_WAIST_DATE else None)
        _write_person(cls.root, PERSON_NONE, lambda d: None)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def payload(self, person: str, today: str) -> dict:
        env = os.environ.copy()
        env["WORKOUT_TRACKER_ROOT"] = str(self.root)
        proc = subprocess.run(
            [sys.executable, str(READ_TRACKER),
             "--person", person, "--today", today, "--months", "6"],
            cwd=str(self.root), env=env, text=True,
            capture_output=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)


class PayloadEmissionTests(_PayloadCase):
    def test_a_person_who_measures_gets_both_keys(self) -> None:
        data = self.payload(PERSON_MEASURES, "2026-08-08")
        self.assertIn("waist_latest", data)
        self.assertEqual(set(data["waist_latest"]), {"value_cm", "date"})
        self.assertEqual(data["waist_latest"]["date"], _HEALTH_DAYS[-4])
        self.assertEqual(data["waist_latest"]["value_cm"],
                         _WAIST_BY_DATE[_HEALTH_DAYS[-4]])
        block = data["waist_trend_cm_per_4w"]
        self.assertEqual(block["state"], "resolved")
        self.assertLess(block["cm_per_4w"], 0)

    def test_a_person_who_has_never_measured_gets_no_latest_and_a_reason(self) -> None:
        data = self.payload(PERSON_NONE, "2026-08-08")
        # ``_compact`` drops null keys payload-wide, so "absent" is how a
        # null reaches the consumer here -- same as ``bodyweight_latest``
        # and ``vo2max_latest``.
        self.assertNotIn("waist_latest", data)
        block = data["waist_trend_cm_per_4w"]
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "no_readings")
        self.assertNotIn("cm_per_4w", block)

    def test_the_live_single_reading_shape_reports_too_few(self) -> None:
        data = self.payload(PERSON_ONCE, "2026-08-08")
        self.assertEqual(data["waist_latest"],
                         {"value_cm": 87.0, "date": _SINGLE_WAIST_DATE})
        block = data["waist_trend_cm_per_4w"]
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "too_few_readings")
        self.assertEqual(block["n_readings"], 1)
        self.assertNotIn("cm_per_4w", block)
        self.assertNotIn("point_cm_per_4w", block)

    def test_the_trend_block_is_always_present(self) -> None:
        """Unlike ``waist_latest``, the block never compacts away: an
        unresolved state is an answer and the consumer must see it."""
        for person in (PERSON_MEASURES, PERSON_ONCE, PERSON_NONE):
            with self.subTest(person=person):
                data = self.payload(person, "2026-08-08")
                self.assertIn("waist_trend_cm_per_4w", data)

    def test_the_weekly_series_carries_the_sparkline_input(self) -> None:
        data = self.payload(PERSON_MEASURES, "2026-08-08")
        weeks = data["health_metrics_weekly"]
        measured = [w for w in weeks if w.get("waist_cm") is not None]
        self.assertTrue(measured, "vitals card has no waist series to draw")
        for w in measured:
            self.assertIn(w["waist_cm"], set(_WAIST_BY_DATE.values()))

    def test_no_waist_field_appears_for_a_person_without_readings(self) -> None:
        data = self.payload(PERSON_NONE, "2026-08-08")
        for w in data["health_metrics_weekly"]:
            self.assertNotIn("waist_cm", w)


class WaistHorizonRegressionTests(_PayloadCase):
    """``--today`` is the as-of date for the waist column too.

    ``health_metrics.csv`` runs to the end of August in this fixture, so a
    run anchored earlier has real, later measurements sitting in the file
    in front of the analytics layer. That is the leak this guards.
    """

    ANCHORS = ("2026-06-01", "2026-06-30", "2026-07-15")

    def _waist_subtree(self, data: dict) -> dict:
        return {
            "waist_latest": data.get("waist_latest"),
            "waist_trend_cm_per_4w": data.get("waist_trend_cm_per_4w"),
            "weekly_waist": [w.get("waist_cm")
                             for w in data.get("health_metrics_weekly", [])],
        }

    def test_no_waist_value_is_dated_after_the_anchor(self) -> None:
        for today in self.ANCHORS:
            with self.subTest(today=today):
                data = self.payload(PERSON_MEASURES, today)
                subtree = json.dumps(self._waist_subtree(data))
                later = [m for m in _ISO_DATE_RE.findall(subtree) if m > today]
                self.assertEqual(later, [],
                                 f"waist payload dated after --today {today}: "
                                 f"{later}")

    def test_the_latest_measurement_is_the_one_the_anchor_could_see(self) -> None:
        for today in self.ANCHORS:
            with self.subTest(today=today):
                data = self.payload(PERSON_MEASURES, today)
                expected_date = max(d for d in _HEALTH_DAYS if d <= today)
                self.assertEqual(
                    data["waist_latest"],
                    {"value_cm": _WAIST_BY_DATE[expected_date],
                     "date": expected_date})

    def test_no_future_measurement_reaches_the_weekly_series(self) -> None:
        for today in self.ANCHORS:
            with self.subTest(today=today):
                data = self.payload(PERSON_MEASURES, today)
                future_values = {
                    v for d, v in _WAIST_BY_DATE.items() if d > today}
                seen = {w.get("waist_cm")
                        for w in data["health_metrics_weekly"]}
                self.assertEqual(future_values & seen, set())

    def test_the_trend_window_ends_at_the_anchor(self) -> None:
        for today in self.ANCHORS:
            with self.subTest(today=today):
                block = self.payload(
                    PERSON_MEASURES, today)["waist_trend_cm_per_4w"]
                self.assertEqual(block["window_end"], today)

    def test_moving_the_anchor_moves_the_answer(self) -> None:
        """Guard the guard. A clip that silently did nothing would leave
        every assertion above passing on identical payloads."""
        early = self.payload(PERSON_MEASURES, "2026-06-01")["waist_latest"]
        late = self.payload(PERSON_MEASURES, "2026-08-08")["waist_latest"]
        self.assertNotEqual(early, late)

    def test_the_fixture_actually_has_measurements_past_every_anchor(self) -> None:
        for today in self.ANCHORS:
            with self.subTest(today=today):
                self.assertTrue(
                    any(d > today for d in _WAIST_BY_DATE),
                    "fixture has nothing past the anchor, so the horizon "
                    "assertion proves nothing")


# ------------------------------------------------------------------ 3.
_VITALS_ARGS = ({"value": 48.0}, 0.3, {"kg": 78.4, "date": "2026-08-01"},
                None, [77.9, 78.1], "")


def _vitals(weekly, **kw) -> str:
    return card_vitals(weekly, *_VITALS_ARGS, **kw)


def _waist_row(html: str) -> str:
    """The one <tr> carrying the waist label."""
    rows = [r for r in html.split("<tr>") if ">Waist<" in r]
    return rows[0] if rows else ""


class WaistCardTests(unittest.TestCase):
    def test_an_empty_channel_says_not_measured_rather_than_vanishing(self) -> None:
        html = _vitals([{"week_start": "2026-07-27", "hrv_sdnn": 55}])
        row = _waist_row(html)
        self.assertTrue(row, "the waist row disappeared on an empty channel")
        self.assertIn("not measured", row)

    def test_a_single_point_says_so_and_draws_no_line(self) -> None:
        html = _vitals(_weekly_series("2026-07-13", [None, None, 87.0]))
        row = _waist_row(html)
        self.assertIn("87.0", row)
        self.assertIn("no trend", row)
        self.assertNotIn("polyline", row,
                         "one point must not be drawn as a flat line")

    def test_two_or_more_points_draw_the_sparkline(self) -> None:
        html = _vitals(_weekly_series("2026-07-13", [88.4, 87.9, 87.0]))
        row = _waist_row(html)
        self.assertIn("polyline", row)

    def test_an_unresolved_block_names_its_reason(self) -> None:
        cases = {
            "no_readings":             "not measured",
            "too_few_readings":        "too few measurements",
            "window_shorter_than_min": "window under 56d",
            "no_time_variance":        "one day only",
            "ci_straddles_zero":       "direction unresolved",
        }
        weekly = _weekly_series("2026-07-13", [88.4, 87.9, 87.0])
        for reason, label in cases.items():
            with self.subTest(reason=reason):
                row = _waist_row(_vitals(weekly, waist_trend_block={
                    "state": "unresolved", "reason": reason,
                    "cm_per_4w": None}))
                self.assertIn(label, row)

    def test_an_unresolved_block_never_prints_a_rate(self) -> None:
        weekly = _weekly_series("2026-07-13", [88.4, 87.9, 87.0])
        row = _waist_row(_vitals(weekly, waist_trend_block={
            "state": "unresolved", "reason": "ci_straddles_zero",
            "cm_per_4w": None, "point_cm_per_4w": -1.21}))
        self.assertNotIn("cm/4w", row)
        self.assertNotIn("-1.21", row)

    def test_a_resolved_block_prints_the_rate_with_its_sign(self) -> None:
        weekly = _weekly_series("2026-07-13", [88.4, 87.9, 87.0])
        row = _waist_row(_vitals(weekly, waist_trend_block={
            "state": "resolved", "reason": None, "cm_per_4w": -1.21}))
        self.assertIn("-1.21 cm/4w", row)

    def test_the_headline_value_prefers_the_latest_measurement(self) -> None:
        """The weekly series carries ISO-week MEANS; ``waist_latest`` is the
        measurement itself, so it wins the value cell when supplied."""
        weekly = _weekly_series("2026-07-13", [88.4, 87.9, 87.0])
        row = _waist_row(_vitals(
            weekly, waist_latest={"value_cm": 86.2, "date": "2026-08-02"}))
        self.assertIn("86.2", row)

    def test_a_resolved_block_with_no_rate_is_not_read_as_zero(self) -> None:
        """A malformed block must not print a bare unit or a "+0.00"."""
        weekly = _weekly_series("2026-07-13", [88.4, 87.9, 87.0])
        row = _waist_row(_vitals(weekly, waist_trend_block={
            "state": "resolved", "reason": None, "cm_per_4w": None}))
        self.assertNotIn("cm/4w", row)
        self.assertNotIn("0.00", row)

    def test_an_unknown_future_reason_falls_back_without_inventing_one(self) -> None:
        weekly = _weekly_series("2026-07-13", [88.4, 87.9, 87.0])
        row = _waist_row(_vitals(weekly, waist_trend_block={
            "state": "unresolved", "reason": "some_future_reason",
            "cm_per_4w": None}))
        self.assertIn("trend unresolved", row)

    def test_the_card_carries_no_raw_hex_colour(self) -> None:
        """Per Skills/DESIGN.md, colour lives in the token front matter and
        render modules reference CSS variables."""
        html = _vitals(_weekly_series("2026-07-13", [88.4, 87.9, 87.0]),
                       waist_latest={"value_cm": 87.0, "date": "2026-08-02"},
                       waist_trend_block={"state": "resolved", "reason": None,
                                          "cm_per_4w": -1.21})
        self.assertEqual(_HEX_LITERAL_RE.findall(html), [])

    def test_the_bodyweight_row_is_unchanged_by_the_new_neighbour(self) -> None:
        html = _vitals(_weekly_series("2026-07-13", [88.4, 87.9, 87.0]))
        self.assertIn(">Bodyweight<", html)
        self.assertIn(">VO2max<", html)


if __name__ == "__main__":
    unittest.main()
