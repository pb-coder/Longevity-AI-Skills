"""Body fat % and lean mass: stored -> payload -> dashboard.

Both importers have written ``Body Fat %`` and ``Lean Mass (kg)`` to
``health_metrics.csv`` since the 2026-08 schema migration, and nothing has
ever read them back. That is exactly the gap waist had, with one extra
twist: NEITHER COLUMN CARRIES DATA IN ANY EXPORT IN HAND, so what ships
today is the empty state and the empty state is therefore the deliverable.

Four things are load-bearing and each has its own section below.

1. **An empty channel says it is empty.** Not ``0.0``, not a flat line
   through one point, and not a silently missing row. Those are the three
   ways an unpopulated column has previously become a reported finding,
   and a coach reading the payload cannot tell "unmeasured" from
   "unchanged" unless the payload says which one it is.
2. **A populated channel routes through the SHARED estimator.** No second,
   laxer copy of the gate: the same window / sample-size / span /
   leverage / interval checks, the same block shape, the same
   ``state``-before-the-number discipline.
3. **The ``--today`` horizon.** A payload anchored on a past date may not
   contain a reading taken after it. This codebase had a systemic leak of
   exactly this shape, and two new columns are two new places for it.
4. **Lean mass is not independent evidence.** Every scale that writes it
   computes it from bodyweight and a body-fat estimate, so a resolved
   lean-mass rate restates the other two rather than corroborating them.
   The note has to say so or the coach will report one measurement three
   times.

The fixtures here are synthetic and written to a temp directory. Nothing
in this file reads or writes a real person's CSV store.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from workout_coach.lib import render_cards_health as rch
from workout_coach.lib import sessions
from workout_coach.lib.render_cards_health import card_vitals
from workout_coach.lib.sessions import (
    BODY_FAT_MEASUREMENT_SD_PCT,
    BODY_FAT_TREND_MAX_STALE_DAYS,
    BODY_FAT_TREND_MIN_READINGS,
    BODY_FAT_TREND_MIN_SPAN_DAYS,
    BODY_FAT_TREND_MIN_WINDOW_DAYS,
    BODYWEIGHT_MEASUREMENT_SD_KG,
    LEAN_MASS_MEASUREMENT_SD_KG,
    LEAN_MASS_TREND_MAX_STALE_DAYS,
    LEAN_MASS_TREND_MIN_READINGS,
    LEAN_MASS_TREND_MIN_SPAN_DAYS,
    LEAN_MASS_TREND_MIN_WINDOW_DAYS,
    TREND_MIN_EFFECTIVE_READINGS,
    WAIST_TREND_MAX_STALE_DAYS,
    WAIST_TREND_MIN_SPAN_DAYS,
    WAIST_TREND_MIN_WINDOW_DAYS,
    body_fat_trend,
    lean_mass_trend,
)

SKILLS_ROOT = Path(__file__).resolve().parents[1]
READ_TRACKER = SKILLS_ROOT / "workout-coach" / "scripts" / "read_tracker.py"

# A CSS hex literal. The negative lookbehind spares HTML entities
# (``&#x27;``), which are not colours.
_HEX_LITERAL_RE = re.compile(r"(?<!&)#[0-9a-fA-F]{3,8}\b")

# Dated well outside the tracker's own era, per ``Skills/CLAUDE.md``.
T = date(2026, 8, 3)


def _weekly_readings(key, first_value, per_week, n=20, step=7, wobble=0.0):
    """``n`` readings ending at ``T``, oldest first, with a wobble so the
    residual is not degenerate."""
    return [
        {"date": (T - timedelta(days=step * (n - 1 - i))).isoformat(),
         key: round(first_value + per_week * i * (step / 7.0)
                    + (wobble if i % 2 else -wobble), 2)}
        for i in range(n)
    ]


# ================================================================== 1.
class AnEmptyChannelSaysSoTests(unittest.TestCase):
    """The state both columns are in today, and the only one that ships.

    ``no_readings`` here is not a failure of the estimator; it is the
    honest description of a column nobody has filled in. What matters is
    that it is DISTINGUISHABLE from a measured-and-flat channel, because
    the two license opposite sentences from a coach.
    """

    def test_neither_trend_invents_a_zero(self) -> None:
        for label, block in (("body fat", body_fat_trend([], today_d=T)),
                             ("lean mass", lean_mass_trend([], today_d=T))):
            with self.subTest(label):
                self.assertEqual(block["state"], "unresolved")
                self.assertEqual(block["reason"], "no_readings")
                self.assertIsNone(block.get("pct_per_4w",
                                            block.get("kg_per_4w")))
                self.assertIsNone(block["n_readings"] or None)

    def test_none_is_not_the_same_as_absent(self) -> None:
        """Every rate field is present and null rather than missing, so a
        consumer that reads the key gets an explicit null instead of a
        KeyError it might paper over with a default of zero."""
        block = body_fat_trend(None, today_d=T)
        for key in ("pct_per_4w", "point_pct_per_4w", "se_pct_per_4w",
                    "ci95_pct_per_4w"):
            with self.subTest(key):
                self.assertIn(key, block)
                self.assertIsNone(block[key])

    def test_the_note_names_the_column_and_how_to_fill_it(self) -> None:
        for block in (body_fat_trend([], today_d=T),
                      lean_mass_trend([], today_d=T)):
            with self.subTest(block["method"]):
                self.assertIn("never been recorded", block["note"])
                self.assertIn("Body Measurements", block["note"])

    def test_never_recorded_is_not_confused_with_stopped_recording(self) -> None:
        """A channel with old readings outside the window is a DIFFERENT
        fact from a channel that was never written, and saying "never
        been recorded" over a series that exists would be false."""
        old = [{"date": (T - timedelta(days=400 + 7 * i)).isoformat(),
                "pct": 20.0} for i in range(6)]
        block = body_fat_trend(old, today_d=T)
        self.assertEqual(block["reason"], "no_readings")
        self.assertNotIn("never been recorded", block["note"])
        self.assertIn("newest on file", block["note"])

    def test_one_reading_is_a_value_not_a_trend(self) -> None:
        block = lean_mass_trend([{"date": T.isoformat(), "kg": 61.4}],
                                today_d=T)
        self.assertEqual(block["reason"], "too_few_readings")
        self.assertIsNone(block["kg_per_4w"])
        self.assertIn("value, not a trend", block["note"])


# ================================================================== 2.
class TheSharedEstimatorIsReusedTests(unittest.TestCase):
    """No second, laxer copy of the gate. Same checks, same block shape."""

    BLOCK_KEYS = {"state", "reason", "note", "n_readings", "window_start",
                  "window_end", "window_days", "span_days",
                  "days_since_last_reading", "max_gap_days",
                  "effective_readings", "method"}

    def test_both_blocks_mirror_the_waist_block_shape(self) -> None:
        bf = body_fat_trend([], today_d=T)
        lm = lean_mass_trend([], today_d=T)
        self.assertTrue(self.BLOCK_KEYS <= set(bf))
        self.assertTrue(self.BLOCK_KEYS <= set(lm))
        self.assertEqual({k for k in bf if k not in self.BLOCK_KEYS},
                         {"pct_per_4w", "point_pct_per_4w", "se_pct_per_4w",
                          "ci95_pct_per_4w"})
        self.assertEqual({k for k in lm if k not in self.BLOCK_KEYS},
                         {"kg_per_4w", "point_kg_per_4w", "se_kg_per_4w",
                          "ci95_kg_per_4w"})

    def test_a_real_cut_resolves_on_body_fat(self) -> None:
        block = body_fat_trend(
            _weekly_readings("pct", 26.0, -0.25, n=13, wobble=0.35),
            today_d=T)
        self.assertEqual(block["state"], "resolved", block["note"])
        self.assertLess(block["pct_per_4w"], 0.0)
        self.assertLess(block["ci95_pct_per_4w"][1], 0.0)
        self.assertIn("falling", block["note"])

    def test_a_real_lean_gain_resolves(self) -> None:
        block = lean_mass_trend(
            _weekly_readings("kg", 58.0, 0.15, n=17, wobble=0.3), today_d=T)
        self.assertEqual(block["state"], "resolved", block["note"])
        self.assertGreater(block["kg_per_4w"], 0.0)
        self.assertGreater(block["ci95_kg_per_4w"][0], 0.0)
        self.assertIn("gaining", block["note"])

    def test_noise_the_size_of_the_signal_stays_unresolved(self) -> None:
        """A drift inside the instrument's own spread must not resolve.
        This is the noise floor doing its job on a new channel."""
        block = body_fat_trend(
            _weekly_readings("pct", 22.0, -0.02, n=13, wobble=0.2),
            today_d=T)
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "ci_straddles_zero")
        self.assertIsNone(block["pct_per_4w"])

    def test_the_span_gate_applies_to_both(self) -> None:
        """Readings crammed into part of the window: the C1 shape, on the
        two new columns."""
        for fn, key, rate_key in ((body_fat_trend, "pct", "pct_per_4w"),
                                  (lean_mass_trend, "kg", "kg_per_4w")):
            with self.subTest(rate_key):
                block = fn(_weekly_readings(key, 20.0, -0.1, n=6, step=1),
                           today_d=T)
                self.assertEqual(block["reason"], "span_shorter_than_min")
                self.assertIsNone(block[rate_key])

    def test_the_leverage_gate_applies_to_both(self) -> None:
        """A cluster plus one distant anchor -- R-07's shape on the two
        new columns. Spans the window, is fresh, has enough readings, and
        is a two-point slope."""
        for fn, key, rate_key, back in ((body_fat_trend, "pct",
                                         "pct_per_4w", 60),
                                        (lean_mass_trend, "kg",
                                         "kg_per_4w", 100)):
            with self.subTest(rate_key):
                series = [{"date": (T - timedelta(days=back)).isoformat(),
                           key: 30.0}]
                series += [{"date": (T - timedelta(days=d)).isoformat(),
                            key: 24.0 + 0.1 * d} for d in (2, 1, 0)]
                block = fn(series, today_d=T)
                self.assertEqual(block["reason"],
                                 "too_few_effective_readings")
                self.assertIsNone(block[rate_key])
                self.assertLess(block["effective_readings"],
                                TREND_MIN_EFFECTIVE_READINGS)

    def test_a_stale_series_does_not_print_as_a_current_rate(self) -> None:
        stale = [{"date": (T - timedelta(days=60 + 7 * i)).isoformat(),
                  "pct": 24.0 + 0.2 * i} for i in range(8)]
        block = body_fat_trend(stale, today_d=T)
        self.assertEqual(block["reason"], "readings_stale")
        self.assertIsNone(block["pct_per_4w"])

    def test_lean_mass_declares_that_it_is_derived(self) -> None:
        """The double-counting guard. Nothing measures lean mass: it is
        bodyweight times one minus body fat, so a resolved rate here is
        the other two restated, and the note has to say so where the
        coach reads it."""
        block = lean_mass_trend(
            _weekly_readings("kg", 58.0, 0.15, n=17, wobble=0.3), today_d=T)
        self.assertEqual(block["state"], "resolved")
        self.assertIn("computed from", block["note"])
        self.assertIn("independent evidence", block["note"])
        # And only when there is a rate to caveat. A caveat printed on an
        # empty channel is wallpaper.
        self.assertNotIn("independent evidence",
                         lean_mass_trend([], today_d=T)["note"])

    def test_value_key_aliases_match_the_other_readers(self) -> None:
        """``read_tracker`` passes ``pct`` / ``kg``;
        ``csv_store_dense.read_body_composition`` returns ``value``; the
        raw health_metrics row keys are ``body_fat_pct`` /
        ``lean_body_mass_kg``. All three reach the estimator, so no
        adapter is needed anywhere."""
        for fn, keys in ((body_fat_trend, ("pct", "value", "body_fat_pct")),
                         (lean_mass_trend,
                          ("kg", "value", "lean_body_mass_kg"))):
            for key in keys:
                with self.subTest(key):
                    one = fn([{"date": T.isoformat(), key: 21.0}], today_d=T)
                    self.assertEqual(one["n_readings"], 1)


class ThresholdsStayTiedToTheirDerivationTests(unittest.TestCase):
    """Every floor here comes out of the same SE arithmetic waist's did.

    ``SE_4w = 28*sigma*sqrt(12) / (sqrt(n)*T)``, solved for T at the
    sample size the gate admits (n = 4) against the effect the channel is
    looking for. Pinning the arithmetic rather than the number is what
    stops a future edit rounding these to something comfortable.
    """

    @staticmethod
    def _span_floor(sigma, effect, n=4):
        return 28.0 * sigma * (12 ** 0.5) / (n ** 0.5 * effect)

    def test_the_body_fat_span_floor_is_the_number_the_arithmetic_gives(self) -> None:
        t_min = self._span_floor(BODY_FAT_MEASUREMENT_SD_PCT, 1.0,
                                 BODY_FAT_TREND_MIN_READINGS)
        self.assertAlmostEqual(t_min, 48.50, places=1)
        self.assertEqual(BODY_FAT_TREND_MIN_SPAN_DAYS, 49)
        self.assertGreaterEqual(BODY_FAT_TREND_MIN_SPAN_DAYS, t_min)

    def test_the_lean_mass_span_floor_is_the_number_the_arithmetic_gives(self) -> None:
        t_min = self._span_floor(LEAN_MASS_MEASUREMENT_SD_KG, 0.5,
                                 LEAN_MASS_TREND_MIN_READINGS)
        self.assertAlmostEqual(t_min, 87.30, places=1)
        self.assertEqual(LEAN_MASS_TREND_MIN_SPAN_DAYS, 88)
        self.assertGreaterEqual(LEAN_MASS_TREND_MIN_SPAN_DAYS, t_min)

    def test_the_lean_mass_noise_floor_is_propagated_not_invented(self) -> None:
        """Lean mass is derived, so its noise is the propagation of the
        two floors already in the module rather than a third guess:
        sd = sqrt(((1-f)*sd_W)^2 + (W*sd_f)^2) at 80 kg / 20% fat."""
        w, f = 80.0, 0.20
        sd = ((((1 - f) * BODYWEIGHT_MEASUREMENT_SD_KG) ** 2)
              + ((w * BODY_FAT_MEASUREMENT_SD_PCT / 100.0) ** 2)) ** 0.5
        self.assertAlmostEqual(sd, 0.894, places=3)
        self.assertAlmostEqual(LEAN_MASS_MEASUREMENT_SD_KG, 0.9, places=2)

    def test_every_span_floor_is_reachable_inside_its_window(self) -> None:
        """A span floor at or above the window is a permanently dead
        column, which is worse than no column."""
        for span, window in (
            (BODY_FAT_TREND_MIN_SPAN_DAYS, BODY_FAT_TREND_MIN_WINDOW_DAYS),
            (LEAN_MASS_TREND_MIN_SPAN_DAYS, LEAN_MASS_TREND_MIN_WINDOW_DAYS),
        ):
            with self.subTest(span=span):
                self.assertLess(span, window)

    def test_the_recency_bound_is_the_reporting_horizon(self) -> None:
        """Both fields are labelled "per 4 weeks"; a fit whose newest
        reading is older than that describes a period the label does not
        name."""
        self.assertEqual(BODY_FAT_TREND_MAX_STALE_DAYS, 28)
        self.assertEqual(LEAN_MASS_TREND_MAX_STALE_DAYS, 28)

    def test_the_slower_channel_has_the_longer_window(self) -> None:
        """Ordering is the sanity check on the whole derivation: waist
        moves faster relative to its instrument than body fat does, and
        body fat faster than a lean mass computed from both."""
        self.assertLess(WAIST_TREND_MIN_WINDOW_DAYS,
                        BODY_FAT_TREND_MIN_WINDOW_DAYS)
        self.assertLess(BODY_FAT_TREND_MIN_WINDOW_DAYS,
                        LEAN_MASS_TREND_MIN_WINDOW_DAYS)
        self.assertLess(WAIST_TREND_MIN_SPAN_DAYS,
                        BODY_FAT_TREND_MIN_SPAN_DAYS)
        self.assertLess(BODY_FAT_TREND_MIN_SPAN_DAYS,
                        LEAN_MASS_TREND_MIN_SPAN_DAYS)

    def test_no_threshold_is_a_no_op(self) -> None:
        for name, value in (
            ("BODY_FAT_MEASUREMENT_SD_PCT", BODY_FAT_MEASUREMENT_SD_PCT),
            ("BODY_FAT_TREND_MIN_SPAN_DAYS", BODY_FAT_TREND_MIN_SPAN_DAYS),
            ("BODY_FAT_TREND_MAX_STALE_DAYS", BODY_FAT_TREND_MAX_STALE_DAYS),
            ("LEAN_MASS_MEASUREMENT_SD_KG", LEAN_MASS_MEASUREMENT_SD_KG),
            ("LEAN_MASS_TREND_MIN_SPAN_DAYS", LEAN_MASS_TREND_MIN_SPAN_DAYS),
            ("LEAN_MASS_TREND_MAX_STALE_DAYS",
             LEAN_MASS_TREND_MAX_STALE_DAYS),
            ("TREND_MIN_EFFECTIVE_READINGS", TREND_MIN_EFFECTIVE_READINGS),
        ):
            with self.subTest(name):
                self.assertGreater(value, 0, f"{name} disables its gate")


# ================================================================== 3.
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

# Weekly health rows across most of the year, so every anchor the tests
# use has rows on BOTH sides of it and no horizon assertion can pass
# vacuously.
_HEALTH_DAYS = [(date(2026, 1, 5) + timedelta(days=7 * i)).isoformat()
                for i in range(36)]

# The person who measures: a steady cut with a small alternating wobble,
# so the fit is real and its residual is not degenerate.
_BF_BY_DATE = {d: round(28.0 - 0.25 * i + (0.35 if i % 2 else -0.35), 2)
               for i, d in enumerate(_HEALTH_DAYS)}
_LM_BY_DATE = {d: round(58.0 + 0.15 * i + (0.3 if i % 2 else -0.3), 2)
               for i, d in enumerate(_HEALTH_DAYS)}

PERSON_MEASURES = "person_bodycomp_series"
PERSON_NONE = "person_bodycomp_never"


def _write_person(root: Path, person: str, bf_for, lm_for) -> None:
    data = root / person / "data"
    (data / "monthly").mkdir(parents=True)
    for ym in ("2026.06", "2026.07", "2026.08"):
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
        bf, lm = bf_for(day), lm_for(day)
        rows.append(
            f"{day},{78.0 + i * 0.05:.2f},47.0,58,62,92,28,7.5,1.2,1.6,8.0,"
            f"14.2,36.4,0.1,45,,"
            f"{'' if bf is None else bf},{'' if lm is None else lm},\n"
        )
    (data / "health_metrics.csv").write_text("".join(rows), encoding="utf-8")
    (data / "profile.csv").write_text(PROFILE, encoding="utf-8")


class _PayloadCase(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        _write_person(cls.root, PERSON_MEASURES, _BF_BY_DATE.get,
                      _LM_BY_DATE.get)
        _write_person(cls.root, PERSON_NONE, lambda d: None, lambda d: None)

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
    ANCHOR = "2026-08-03"

    def test_a_person_who_measures_gets_all_four_keys(self) -> None:
        data = self.payload(PERSON_MEASURES, self.ANCHOR)
        self.assertEqual(set(data["body_fat_latest"]), {"value_pct", "date"})
        self.assertEqual(set(data["lean_mass_latest"]), {"value_kg", "date"})
        self.assertIn("body_fat_trend_pct_per_4w", data)
        self.assertIn("lean_mass_trend_kg_per_4w", data)

    def test_a_person_who_never_measured_gets_no_latest_and_a_reason(self) -> None:
        """The live shape today for both tracked people. ``*_latest`` is
        dropped rather than emitted as a zero; the trend block survives
        and carries the explanation."""
        data = self.payload(PERSON_NONE, self.ANCHOR)
        self.assertNotIn("body_fat_latest", data)
        self.assertNotIn("lean_mass_latest", data)
        for key in ("body_fat_trend_pct_per_4w", "lean_mass_trend_kg_per_4w"):
            with self.subTest(key):
                block = data[key]
                self.assertEqual(block["state"], "unresolved")
                self.assertEqual(block["reason"], "no_readings")
                self.assertIn("never been recorded", block["note"])

    def test_no_body_comp_field_appears_as_a_zero(self) -> None:
        """The failure this whole channel exists to prevent: a column
        nobody has written rendering as a measured zero."""
        data = self.payload(PERSON_NONE, self.ANCHOR)
        blob = json.dumps(data)
        self.assertNotIn('"pct_per_4w":0', blob)
        self.assertNotIn('"kg_per_4w":0', blob)
        self.assertNotIn('"value_pct":0', blob)
        self.assertNotIn('"value_kg":0', blob)
        for week in data["health_metrics_weekly"]:
            self.assertNotIn("body_fat_pct", week)
            self.assertNotIn("lean_mass_kg", week)

    def test_the_weekly_series_carries_the_sparkline_input(self) -> None:
        data = self.payload(PERSON_MEASURES, self.ANCHOR)
        weeks = data["health_metrics_weekly"]
        self.assertTrue(any("body_fat_pct" in w for w in weeks))
        self.assertTrue(any("lean_mass_kg" in w for w in weeks))

    def test_a_long_clean_series_resolves_end_to_end(self) -> None:
        data = self.payload(PERSON_MEASURES, self.ANCHOR)
        bf = data["body_fat_trend_pct_per_4w"]
        lm = data["lean_mass_trend_kg_per_4w"]
        self.assertEqual(bf["state"], "resolved", bf["note"])
        self.assertLess(bf["pct_per_4w"], 0.0)
        self.assertEqual(lm["state"], "resolved", lm["note"])
        self.assertGreater(lm["kg_per_4w"], 0.0)


# ================================================================== 4.
class BodyCompHorizonRegressionTests(_PayloadCase):
    """``--today`` is the as-of date for the entire payload.

    This repo had a systemic leak of exactly this shape, so every new
    dated field gets its own horizon assertion rather than inheriting
    trust from ``_clip_series``.
    """

    ANCHORS = ("2026-04-06", "2026-06-01", "2026-07-13")

    def test_the_fixture_actually_has_readings_past_every_anchor(self) -> None:
        """Guard the guard: an anchor past the end of the fixture would
        make every assertion below pass vacuously."""
        for anchor in self.ANCHORS:
            with self.subTest(anchor=anchor):
                self.assertTrue(any(d > anchor for d in _BF_BY_DATE))

    def test_no_value_is_dated_after_the_anchor(self) -> None:
        iso = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
        for anchor in self.ANCHORS:
            with self.subTest(anchor=anchor):
                data = self.payload(PERSON_MEASURES, anchor)
                for key in ("body_fat_latest", "lean_mass_latest",
                            "body_fat_trend_pct_per_4w",
                            "lean_mass_trend_kg_per_4w"):
                    for found in iso.findall(json.dumps(data.get(key) or {})):
                        self.assertLessEqual(found, anchor, key)

    def test_the_latest_reading_is_the_one_the_anchor_could_see(self) -> None:
        for anchor in self.ANCHORS:
            with self.subTest(anchor=anchor):
                data = self.payload(PERSON_MEASURES, anchor)
                visible = [d for d in sorted(_BF_BY_DATE) if d <= anchor]
                self.assertEqual(data["body_fat_latest"]["date"], visible[-1])
                self.assertEqual(data["body_fat_latest"]["value_pct"],
                                 _BF_BY_DATE[visible[-1]])

    def test_the_trend_window_ends_at_the_anchor(self) -> None:
        for anchor in self.ANCHORS:
            with self.subTest(anchor=anchor):
                data = self.payload(PERSON_MEASURES, anchor)
                for key in ("body_fat_trend_pct_per_4w",
                            "lean_mass_trend_kg_per_4w"):
                    self.assertEqual(data[key]["window_end"], anchor, key)

    def test_moving_the_anchor_moves_the_answer(self) -> None:
        """A horizon that is enforced but has no effect proves nothing."""
        early = self.payload(PERSON_MEASURES, self.ANCHORS[0])
        late = self.payload(PERSON_MEASURES, "2026-08-03")
        self.assertNotEqual(early["body_fat_latest"],
                            late["body_fat_latest"])

    def test_no_future_reading_reaches_the_weekly_series(self) -> None:
        for anchor in self.ANCHORS:
            with self.subTest(anchor=anchor):
                data = self.payload(PERSON_MEASURES, anchor)
                for week in data["health_metrics_weekly"]:
                    self.assertLessEqual(week["week_start"], anchor)


# ================================================================== 5.
_VITALS_ARGS = ({"value": 48.0}, 0.3, {"kg": 78.4, "date": "2026-08-01"},
                None, [77.9, 78.1], "")


def _vitals(weekly, **kw) -> str:
    return card_vitals(weekly, *_VITALS_ARGS, **kw)


def _row(html: str, label: str) -> str:
    rows = [r for r in html.split("<tr>") if f">{label}<" in r]
    return rows[0] if rows else ""


def _cells(html: str, label: str) -> list[str]:
    """The row's four ``<td>`` bodies: term / value / sparkline / State.

    Assertions go against the CELL, not the row: the tooltip lives in the
    first cell and quotes phrases like "not measured" verbatim, so a
    whole-row substring check would pass on a row whose State cell said
    something else entirely.
    """
    return re.findall(r"<td[^>]*>(.*?)</td>", _row(html, label), re.S)


def _state(html: str, label: str) -> str:
    return _cells(html, label)[3].strip()


def _value(html: str, label: str) -> str:
    return _cells(html, label)[1].strip()


def _weekly(**series) -> list[dict]:
    """``health_metrics_weekly``-shaped rows carrying the given keys."""
    n = max(len(v) for v in series.values()) if series else 3
    start = date(2026, 7, 13)
    out = []
    for i in range(n):
        row = {"week_start": (start + timedelta(days=7 * i)).isoformat(),
               "hrv_sdnn": 55}
        for key, values in series.items():
            if values[i] is not None:
                row[key] = values[i]
        out.append(row)
    return out


class BodyCompCardTests(unittest.TestCase):
    def test_both_rows_exist_even_with_nothing_to_show(self) -> None:
        """R-09's whole point. A row that vanishes when unmeasured cannot
        be told apart from a row nobody thought to add."""
        html = _vitals(_weekly())
        for label in ("Body fat", "Lean mass"):
            with self.subTest(label):
                self.assertTrue(_row(html, label),
                                f"the {label} row disappeared")
                self.assertEqual(_state(html, label), "not measured")

    def test_an_empty_row_prints_no_number_and_no_bare_unit(self) -> None:
        """Neither a zero nor a lone "%" hanging in the value cell. Both
        read as a measurement whose value went missing rather than as a
        channel nobody has filled in."""
        html = _vitals(_weekly())
        for label, unit in (("Body fat", "%"), ("Lean mass", "kg")):
            with self.subTest(label):
                self.assertEqual(_value(html, label), "")
                self.assertNotIn(unit, _value(html, label))

    def test_an_empty_row_draws_no_line(self) -> None:
        html = _vitals(_weekly())
        for label in ("Body fat", "Lean mass"):
            with self.subTest(label):
                self.assertNotIn("polyline", _row(html, label))

    def test_a_single_point_says_so_rather_than_drawing_a_flat_line(self) -> None:
        html = _vitals(_weekly(body_fat_pct=[None, None, 21.4]))
        self.assertIn("21.4", _value(html, "Body fat"))
        self.assertEqual(_state(html, "Body fat"), "1 week logged, no trend")
        self.assertNotIn("polyline", _row(html, "Body fat"))

    def test_two_or_more_points_draw_the_sparkline(self) -> None:
        html = _vitals(_weekly(lean_mass_kg=[60.1, 60.4, 60.9]))
        self.assertIn("polyline", _row(html, "Lean mass"))

    def test_a_resolved_block_prints_the_rate_with_its_sign(self) -> None:
        html = _vitals(
            _weekly(body_fat_pct=[22.1, 21.6, 21.0],
                    lean_mass_kg=[60.1, 60.4, 60.9]),
            body_fat_trend_block={"state": "resolved", "reason": None,
                                  "pct_per_4w": -0.94},
            lean_mass_trend_block={"state": "resolved", "reason": None,
                                   "kg_per_4w": 0.61})
        self.assertEqual(_state(html, "Body fat"), "-0.94 pp/4w")
        self.assertEqual(_state(html, "Lean mass"), "+0.61 kg/4w")

    def test_the_favourable_direction_differs_between_the_two_rows(self) -> None:
        """Losing fat is good news and losing lean mass is not. A shared
        renderer that got this wrong would colour one of them backwards."""
        html = _vitals(
            _weekly(body_fat_pct=[22.1, 21.6, 21.0],
                    lean_mass_kg=[61.0, 60.4, 60.1]),
            body_fat_trend_block={"state": "resolved", "reason": None,
                                  "pct_per_4w": -0.94},
            lean_mass_trend_block={"state": "resolved", "reason": None,
                                   "kg_per_4w": -0.61})
        # The status class rides on the sparkline element for this table.
        self.assertIn('class="sparkline good"', _row(html, "Body fat"))
        self.assertIn('class="sparkline amber"', _row(html, "Lean mass"))

    def test_an_unresolved_block_never_prints_a_rate(self) -> None:
        html = _vitals(
            _weekly(body_fat_pct=[22.1, 21.6, 21.0]),
            body_fat_trend_block={"state": "unresolved",
                                  "reason": "ci_straddles_zero",
                                  "pct_per_4w": None,
                                  "point_pct_per_4w": -0.31})
        state = _state(html, "Body fat")
        self.assertNotIn("pp/4w", state)
        self.assertNotIn("-0.31", state)
        self.assertEqual(state, "direction unresolved")

    def test_a_resolved_block_with_no_rate_is_not_read_as_zero(self) -> None:
        html = _vitals(
            _weekly(lean_mass_kg=[60.1, 60.4, 60.9]),
            lean_mass_trend_block={"state": "resolved", "reason": None,
                                   "kg_per_4w": None})
        state = _state(html, "Lean mass")
        self.assertNotIn("kg/4w", state)
        self.assertNotIn("0.00", state)

    def test_an_unknown_future_reason_falls_back_without_inventing_one(self) -> None:
        html = _vitals(
            _weekly(body_fat_pct=[22.1, 21.6, 21.0]),
            body_fat_trend_block={"state": "unresolved",
                                  "reason": "some_future_reason",
                                  "pct_per_4w": None})
        self.assertEqual(_state(html, "Body fat"), "trend unresolved")

    def test_the_lean_mass_tooltip_says_it_is_derived(self) -> None:
        html = _vitals(_weekly())
        row = _row(html, "Lean mass")
        tip = re.search(r'data-tip="([^"]*)"', row).group(1)
        self.assertIn("do not measure it", tip)
        self.assertIn("restates", tip)

    def test_both_tooltips_state_the_gate_as_enforced(self) -> None:
        html = _vitals(_weekly())
        for label, span, weeks in (("Body fat", "49 days", "12 weeks"),
                                   ("Lean mass", "88 days", "16 weeks")):
            with self.subTest(label):
                tip = re.search(r'data-tip="([^"]*)"',
                                _row(html, label)).group(1)
                self.assertIn("4 readings", tip)
                self.assertIn(span, tip)
                self.assertIn(weeks, tip)
                self.assertIn("4 weeks old", tip)
                self.assertIn("half that spread", tip)

    def test_the_card_carries_no_raw_hex_colour(self) -> None:
        """Per Skills/DESIGN.md, colour lives in the token front matter
        and render modules reference CSS variables."""
        html = _vitals(
            _weekly(body_fat_pct=[22.1, 21.6, 21.0],
                    lean_mass_kg=[60.1, 60.4, 60.9]),
            body_fat_latest={"value_pct": 21.0, "date": "2026-08-03"},
            lean_mass_latest={"value_kg": 60.9, "date": "2026-08-03"},
            body_fat_trend_block={"state": "resolved", "reason": None,
                                  "pct_per_4w": -0.94},
            lean_mass_trend_block={"state": "resolved", "reason": None,
                                   "kg_per_4w": 0.61})
        self.assertEqual(_HEX_LITERAL_RE.findall(html), [])

    def test_the_existing_rows_are_unchanged_by_the_new_neighbours(self) -> None:
        html = _vitals(_weekly())
        for label in ("HRV", "Resting HR", "Wrist temp", "VO2max",
                      "Bodyweight", "Waist"):
            with self.subTest(label):
                self.assertTrue(_row(html, label))

    def test_the_headline_value_prefers_the_latest_reading(self) -> None:
        """The weekly series carries ISO-week MEANS; ``*_latest`` is the
        reading itself, so it wins the value cell when supplied."""
        html = _vitals(
            _weekly(body_fat_pct=[22.1, 21.6, 21.0]),
            body_fat_latest={"value_pct": 20.4, "date": "2026-08-03"})
        self.assertIn("20.4", _value(html, "Body fat"))


class LabelsMatchTheGateTests(unittest.TestCase):
    """The renderer restates the estimator's floors in prose.

    Two sources of truth for one number is a drift hazard, and the
    renderer deliberately does not import ``sessions`` (it is a pure
    renderer). This test is the seam that catches the drift instead.
    """

    def test_every_reason_the_new_estimators_emit_has_a_label(self) -> None:
        """A reason with no label falls through to a generic "trend
        unresolved", which is how a dashboard ends up saying less than
        the estimator knows."""
        emitted = set(re.findall(r'"(\w+)", \*tail',
                                 inspect.getsource(sessions._trend_verdict)))
        emitted.add("no_readings")
        self.assertTrue(emitted, "reason codes could not be extracted")
        for labels in (rch._BODY_FAT_STATE_LABEL, rch._LEAN_MASS_STATE_LABEL):
            for reason in emitted:
                with self.subTest(reason=reason):
                    self.assertIn(reason, labels)

    def test_each_label_set_is_internally_distinct(self) -> None:
        for labels in (rch._BODY_FAT_STATE_LABEL, rch._LEAN_MASS_STATE_LABEL,
                       rch._WAIST_STATE_LABEL, rch._BW_STATE_LABEL):
            self.assertEqual(len(set(labels.values())), len(labels))

    def test_the_labels_quote_the_floors_the_estimator_enforces(self) -> None:
        for labels, window, span in (
            (rch._WAIST_STATE_LABEL, WAIST_TREND_MIN_WINDOW_DAYS,
             WAIST_TREND_MIN_SPAN_DAYS),
            (rch._BODY_FAT_STATE_LABEL, BODY_FAT_TREND_MIN_WINDOW_DAYS,
             BODY_FAT_TREND_MIN_SPAN_DAYS),
            (rch._LEAN_MASS_STATE_LABEL, LEAN_MASS_TREND_MIN_WINDOW_DAYS,
             LEAN_MASS_TREND_MIN_SPAN_DAYS),
        ):
            with self.subTest(window=window):
                self.assertIn(f"{window}d",
                              labels["window_shorter_than_min"])
                self.assertIn(f"{span}d", labels["span_shorter_than_min"])

    def test_the_recency_labels_quote_the_reporting_horizon(self) -> None:
        for labels, stale in (
            (rch._WAIST_STATE_LABEL, WAIST_TREND_MAX_STALE_DAYS),
            (rch._BODY_FAT_STATE_LABEL, BODY_FAT_TREND_MAX_STALE_DAYS),
            (rch._LEAN_MASS_STATE_LABEL, LEAN_MASS_TREND_MAX_STALE_DAYS),
        ):
            with self.subTest(stale=stale):
                self.assertEqual(stale, 28)
                self.assertIn("4w ago", labels["readings_stale"])


if __name__ == "__main__":
    unittest.main()
