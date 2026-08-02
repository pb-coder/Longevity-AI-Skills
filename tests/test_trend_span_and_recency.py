"""The window is not the span, and the fit is not necessarily current.

Three defects, one root cause. ``_trend_verdict`` derived its floors from
``SE ~= sigma*sqrt(12) / (sqrt(n)*T)`` where ``T`` is the SPREAD of the
readings, and then checked the WINDOW LENGTH instead. Those are different
quantities, and substituting one for the other let this through:

    four waist readings taken on four consecutive days, 0.3 cm apart end
    to end, reported ``-2.80 cm/4wk`` with a 95% interval of
    ``[-2.80, -2.80]`` -- zero width -- and a note that said "over 4
    measurements / 56 days".

Every part of that is wrong in a different way. The rate is 0.3 cm divided
by a 3-day span and multiplied back up to 28, so the same drift reads as
-2.80 over 3 days and -0.30 over 28. The interval has zero width because
four rounded tape readings landed on a straight line, which at two degrees
of freedom is a sample too small to see its own error, not certainty. And
0.3 cm is inside the 0.5-1.0 cm test-retest spread of a tape measure, so
there is no measurement here at all. The note then told the coach the fit
rested on 56 days of data.

What this file pins:

1. **Span.** The readings must spread across a real stretch of time, and
   the number that gate uses comes out of the SE arithmetic, not out of
   the window length.
2. **Recency.** A fit whose newest reading is old describes a period that
   has ended, and must not be printed as a current rate.
3. **A near-zero standard error is not certainty.** The interval is
   floored at the spread the instrument is known to carry. This is
   deliberately NOT a new unresolved state -- see
   ``ALongCleanSeriesStillResolvesTests``, which is the other half of the
   decision.
4. **The note reports the span**, never the window.
5. **The gate only ever got tighter.** Nothing that was unresolved before
   resolves now.

Every fixture here is synthetic. Nothing reads or writes a tracker.
"""
from __future__ import annotations

import inspect
import re
import unittest
from datetime import date, timedelta

from workout_coach.lib import render_cards_health as rch
from workout_coach.lib import sessions
from workout_coach.lib.sessions import (
    BODYWEIGHT_MEASUREMENT_SD_KG,
    BODYWEIGHT_TREND_MAX_STALE_DAYS,
    BODYWEIGHT_TREND_MIN_READINGS,
    BODYWEIGHT_TREND_MIN_SPAN_DAYS,
    BODYWEIGHT_TREND_MIN_WINDOW_DAYS,
    TREND_MIN_EFFECTIVE_READINGS,
    WAIST_MEASUREMENT_SD_CM,
    WAIST_TREND_MAX_STALE_DAYS,
    WAIST_TREND_MIN_READINGS,
    WAIST_TREND_MIN_SPAN_DAYS,
    WAIST_TREND_MIN_WINDOW_DAYS,
    bodyweight_trend,
    ols_rate_per_week,
    waist_trend,
)

# Dated well outside the tracker's own era, per ``Skills/CLAUDE.md``: a
# dated bodyweight series is a profile fact and must not be reproduced in
# committed test data.
T = date(2026, 8, 2)


def waist(days_ago_to_cm) -> list[dict]:
    return [{"date": (T - timedelta(days=d)).isoformat(), "cm": cm}
            for d, cm in days_ago_to_cm]


def weighins(days_ago_to_kg) -> list[dict]:
    return [{"date": (T - timedelta(days=d)).isoformat(), "kg": kg,
             "notes": ""}
            for d, kg in days_ago_to_kg]


# ------------------------------------------------------------------ C1
class TheSpanIsNotTheWindowTests(unittest.TestCase):
    """The reproduction, and the arithmetic that says why it was wrong."""

    C1 = waist([(3, 87.5), (2, 87.4), (1, 87.3), (0, 87.2)])

    def test_four_readings_over_three_days_do_not_resolve(self) -> None:
        block = waist_trend(self.C1, today_d=T)
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "span_shorter_than_min")
        self.assertIsNone(block["cm_per_4w"])
        # Not a point estimate either. -2.80 cm/4wk from 0.3 cm of drift
        # is not a lean worth showing a human; it is an artifact of the
        # denominator.
        self.assertIsNone(block["point_cm_per_4w"])
        self.assertIsNone(block["ci95_cm_per_4w"])

    def test_the_readings_pass_every_gate_the_old_one_had(self) -> None:
        """Guard the guard: C1 is inside the window, has enough readings,
        and is perfectly fresh. Only the new span check can catch it, so a
        span gate that quietly did nothing would leave the test above
        passing for the wrong reason."""
        block = waist_trend(self.C1, today_d=T)
        self.assertEqual(block["window_days"], WAIST_TREND_MIN_WINDOW_DAYS)
        self.assertGreaterEqual(block["n_readings"], WAIST_TREND_MIN_READINGS)
        self.assertEqual(block["days_since_last_reading"], 0)

    def test_the_block_reports_the_span_beside_the_window(self) -> None:
        block = waist_trend(self.C1, today_d=T)
        self.assertEqual(block["span_days"], 3)
        self.assertEqual(block["window_days"], 56)
        self.assertNotEqual(block["span_days"], block["window_days"])

    def test_the_note_says_three_days_and_never_says_fifty_six(self) -> None:
        """The note is what the coach reads. Saying "56 days" over a
        three-day fit does not merely omit the problem, it asserts the
        opposite of it."""
        note = waist_trend(self.C1, today_d=T)["note"]
        self.assertIn("spanning 3 days", note)
        self.assertNotIn("/ 56 days", note)

    def test_the_same_drift_no_longer_reads_as_five_different_rates(self) -> None:
        """The defect in one line: 0.3 cm of drift resolved at EVERY span,
        to a rate that changed by 9x depending only on the denominator
        (3d -> -2.80, 5d -> -1.72, 7d -> -1.16, 14d -> -0.61, 28d -> -0.30).
        None of them may resolve now -- 0.3 cm is inside tape error."""
        for span in (3, 5, 7, 14, 28, 39, 55):
            with self.subTest(span=span):
                block = waist_trend(
                    waist([(span, 87.5),
                           (round(span * 2 / 3), 87.4),
                           (round(span / 3), 87.3),
                           (0, 87.2)]),
                    today_d=T)
                self.assertEqual(block["state"], "unresolved", span)
                self.assertIsNone(block["cm_per_4w"])

    def test_the_span_floor_is_the_number_the_se_arithmetic_gives(self) -> None:
        """SE_4w = 28*sigma*sqrt(12) / (sqrt(n)*T), at the sigma and effect
        size the estimator's own design comment names (0.8 cm test-retest,
        1 cm per 4 weeks of real change) and the sample size this gate
        admits (n = 4). Solving for T is the whole derivation, and it must
        stay tied to it rather than drifting to a round number."""
        sigma, effect, n, horizon = 0.8, 1.0, WAIST_TREND_MIN_READINGS, 28
        t_min = horizon * sigma * (12 ** 0.5) / (n ** 0.5 * effect)
        self.assertAlmostEqual(t_min, 38.80, places=1)
        self.assertEqual(WAIST_TREND_MIN_SPAN_DAYS, 39)
        self.assertGreaterEqual(WAIST_TREND_MIN_SPAN_DAYS, t_min)
        # And it has to be reachable, or the column is dead. A 56-day
        # window holds a 55-day span.
        self.assertLess(WAIST_TREND_MIN_SPAN_DAYS,
                        WAIST_TREND_MIN_WINDOW_DAYS)


# ------------------------------------------------------------------ C2
class AStaleFitIsNotACurrentRateTests(unittest.TestCase):

    C2 = waist([(55, 87.5), (54, 87.4), (53, 87.3), (52, 87.2)])

    def test_readings_that_stop_two_months_ago_do_not_resolve(self) -> None:
        block = waist_trend(self.C2, today_d=T)
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "readings_stale")
        self.assertIsNone(block["cm_per_4w"])
        self.assertEqual(block["days_since_last_reading"], 52)

    def test_the_note_names_the_age_of_the_newest_reading(self) -> None:
        note = waist_trend(self.C2, today_d=T)["note"]
        self.assertIn("52 days old", note)

    def test_a_resolved_waist_rate_always_has_a_reading_in_the_sparkline_window(self) -> None:
        """The dashboard draws the waist sparkline over 4 weeks while the
        estimator fits over 8, so before this gate a rate could print
        beside an EMPTY sparkline. The recency bound is set to the same 4
        weeks, which guarantees at least one measurement inside the drawn
        period whenever a rate prints. It does not guarantee TWO, which is
        what the sparkline needs to draw a line -- see the module note in
        ``render_cards_health`` and the tooltip, which now says so."""
        self.assertEqual(WAIST_TREND_MAX_STALE_DAYS, 28)
        pts = [(7 * i, 90.0 - 0.25 * (7 - i) + (0.2 if i % 2 else -0.2))
               for i in range(8)]
        block = waist_trend(waist(pts), today_d=T)
        self.assertEqual(block["state"], "resolved")
        self.assertLessEqual(block["days_since_last_reading"],
                             WAIST_TREND_MAX_STALE_DAYS)

    def test_staleness_is_reported_ahead_of_span_when_both_fail(self) -> None:
        """C2 fails both checks. "You stopped measuring two months ago" is
        the true and actionable one; telling someone to measure over a
        longer stretch sends them the wrong way."""
        block = waist_trend(self.C2, today_d=T)
        self.assertEqual(block["span_days"], 3)
        self.assertLess(block["span_days"], WAIST_TREND_MIN_SPAN_DAYS)
        self.assertEqual(block["reason"], "readings_stale")


# ------------------------------------------------------------- leverage
class TheSpanIsNotTheDistributionTests(unittest.TestCase):
    """C1's sibling: the span gate measures the ENDS, not the middle.

    Three readings clustered today plus one 39-55 days back spans 39-55
    days, carries four readings and is perfectly fresh. It clears the
    span gate, the recency gate and the sample-size gate, and it is a
    two-point slope: a cluster, a lone anchor, and nothing observed
    between them.

    It is not merely uninformative. ``Sxx`` is maximised by pushing mass
    to the ends, so the clustered design reports a NARROWER interval than
    the evenly-spread one the span floor was derived from -- 1.79 cm/4wk
    of half-interval against 2.07 at the same n and span. The extra
    confidence is bought from geometry rather than from measurement, and
    one mis-read tape at either end then clears the smaller bar.
    """

    # 3.2 cm of apparent narrowing across the hole. Reproduces the
    # shipped defect exactly: -1.99 cm/4wk, SE 0.37, interval clear of
    # zero, off two effective points.
    CLUSTERED = waist([(45, 90.2), (2, 87.1), (1, 87.0), (0, 87.1)])

    def test_the_fixture_cleared_every_gate_that_came_before(self) -> None:
        """Guard the guard. If it failed for span or recency instead, the
        leverage check below would be passing for the wrong reason."""
        block = waist_trend(self.CLUSTERED, today_d=T)
        self.assertGreaterEqual(block["span_days"], WAIST_TREND_MIN_SPAN_DAYS)
        self.assertGreaterEqual(block["n_readings"], WAIST_TREND_MIN_READINGS)
        self.assertLessEqual(block["days_since_last_reading"],
                             WAIST_TREND_MAX_STALE_DAYS)

    def test_a_cluster_plus_one_anchor_no_longer_resolves(self) -> None:
        block = waist_trend(self.CLUSTERED, today_d=T)
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "too_few_effective_readings")
        self.assertIsNone(block["cm_per_4w"])
        # Not a point estimate either: -1.99 cm/4wk off two effective
        # points is an artifact of where the readings sit, not a lean.
        self.assertIsNone(block["point_cm_per_4w"])
        self.assertIsNone(block["ci95_cm_per_4w"])

    def test_the_block_reports_the_gap_and_what_the_series_is_worth(self) -> None:
        block = waist_trend(self.CLUSTERED, today_d=T)
        self.assertEqual(block["span_days"], 45)
        self.assertEqual(block["max_gap_days"], 43)
        self.assertAlmostEqual(block["effective_readings"], 2.05, places=2)

    def test_the_note_names_the_gap_not_the_span(self) -> None:
        note = waist_trend(self.CLUSTERED, today_d=T)["note"]
        self.assertIn("43 days", note)
        self.assertIn("2.0 evenly spaced", note)

    def test_it_fails_across_the_whole_39_to_55_day_family(self) -> None:
        for back in (39, 45, 50, 55):
            for drift in (2.8, 3.2, 3.6):
                with self.subTest(back=back, drift=drift):
                    block = waist_trend(
                        waist([(back, 87.0 + drift), (2, 87.1),
                               (1, 87.0), (0, 87.1)]), today_d=T)
                    self.assertEqual(block["reason"],
                                     "too_few_effective_readings")

    def test_the_effective_sample_size_is_exact_for_an_even_cadence(self) -> None:
        """``n_eff = 1 + span / max_gap`` is not a heuristic: for n
        readings evenly spread over a span the largest gap is exactly
        ``span / (n - 1)``, so inverting it returns n. Anything else and
        the floor below would not mean what it says.

        Step 5 rather than 7 so every n here fits inside the 56-day
        window; the metric is emitted on every verdict, so the assertion
        holds whether or not the series also clears the span floor."""
        for n in (4, 5, 6, 8, 12):
            with self.subTest(n=n):
                step = 5
                block = waist_trend(
                    waist([(step * i, 87.0 + 0.4 * i + (0.2 if i % 2 else 0))
                           for i in range(n)]), today_d=T)
                self.assertEqual(block["n_readings"], n)
                self.assertAlmostEqual(block["effective_readings"], float(n),
                                       places=6)

    def test_the_floor_is_the_two_point_slope_boundary(self) -> None:
        """2 effective readings IS a two-point slope -- every reading at
        one of two ends, the stretch between them unobserved, and the
        error estimated off within-cluster scatter. 3 is the smallest
        design carrying an interior anchor, so the floor is 3 rather than
        a tuned number."""
        self.assertEqual(TREND_MIN_EFFECTIVE_READINGS, 3.0)
        # Every all-at-two-ends design scores exactly 2, including the
        # replicated-endpoint one that a maximum-leverage test scores as
        # healthy because no single reading dominates.
        replicated = waist([(45, 90.2), (45, 90.0), (0, 87.1), (0, 87.0)])
        block = waist_trend(replicated, today_d=T)
        self.assertEqual(block["effective_readings"], 2.0)
        self.assertEqual(block["reason"], "too_few_effective_readings")

    def test_the_floor_leaves_the_sparsest_legal_cadence_headroom(self) -> None:
        """A floor no honest cadence clears is a deleted column. The
        sparsest series the other gates admit -- 4 measurements evenly
        spread over the 39-day span floor -- must score a full reading
        clear of the floor, and stay clear under a day of jitter."""
        even = waist([(39, 90.0), (26, 89.1), (13, 88.4), (0, 87.4)])
        block = waist_trend(even, today_d=T)
        self.assertEqual(block["effective_readings"], 4.0)
        self.assertNotEqual(block["reason"], "too_few_effective_readings")
        for jitter in (-1, 1):
            with self.subTest(jitter=jitter):
                jittered = waist([(39, 90.0), (26 + jitter, 89.1),
                                  (13 + jitter, 88.4), (0, 87.4)])
                self.assertNotEqual(waist_trend(jittered, today_d=T)["reason"],
                                    "too_few_effective_readings")

    def test_an_ordinary_weekly_cadence_is_untouched(self) -> None:
        pts = [(7 * i, 90.0 - 0.25 * (7 - i) + (0.2 if i % 2 else -0.2))
               for i in range(8)]
        block = waist_trend(waist(pts), today_d=T)
        self.assertEqual(block["state"], "resolved")
        self.assertEqual(block["effective_readings"], 8.0)

    def test_a_ramp_up_from_one_old_reading_is_not_punished(self) -> None:
        """One measurement, then a real cadence starting later, is how a
        channel actually begins. It must not be read as a cluster."""
        pts = [(42, 90.0), (28, 89.2), (21, 88.9), (14, 88.4), (7, 88.0),
               (0, 87.4)]
        block = waist_trend(waist(pts), today_d=T)
        self.assertNotEqual(block["reason"], "too_few_effective_readings")
        self.assertGreaterEqual(block["effective_readings"],
                                TREND_MIN_EFFECTIVE_READINGS)

    def test_bodyweight_inherits_the_check_from_the_shared_gate(self) -> None:
        block = bodyweight_trend(
            weighins([(22, 76.4), (2, 78.2), (1, 78.1), (0, 78.3)]), today_d=T)
        self.assertEqual(block["reason"], "too_few_effective_readings")
        self.assertIsNone(block["kg_per_week"])
        self.assertIn("20 days", block["note"])

    def test_the_live_bodyweight_shapes_still_clear_the_floor(self) -> None:
        """Both tracked series resolve today and must keep resolving. The
        offsets are the real reading CADENCE (not the values, which are
        invented): 15 near-daily weigh-ins with a 6-day hole, and 11 with
        an 8-day one. The second sits at 3.25 effective readings, which
        is thin enough to be worth pinning rather than rediscovering."""
        dense = [0, 1, 3, 7, 8, 14, 15, 17, 19, 20, 21, 22, 23, 24, 26]
        gappy = [0, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18]
        for offsets, expected in ((dense, 5.33), (gappy, 3.25)):
            with self.subTest(n=len(offsets)):
                block = bodyweight_trend(
                    weighins([(o, 78.0 + 0.07 * (30 - o)) for o in offsets]),
                    today_d=T)
                self.assertAlmostEqual(block["effective_readings"], expected,
                                       places=2)
                self.assertNotEqual(block["reason"],
                                    "too_few_effective_readings")


# ----------------------------------------------------- near-zero SE
class AZeroStandardErrorIsNotCertaintyTests(unittest.TestCase):
    """The decision recorded in code: floor the noise, do not add a state.

    A zero-width interval arises when the readings happen to sit on a
    straight line. With tape values rounded to 0.1 cm on a slowly-moving
    body that is a realistic input, not a synthetic one, and at ``dof = 2``
    it says nothing about the body. Refusing it outright would also refuse
    a long dense clean series, which is the STRONGEST evidence in the file
    -- so instead the residual is floored at what the instrument is known
    to carry and the ordinary interval test decides. Same verdict path as
    every other series.
    """

    def test_a_perfectly_collinear_series_gets_a_real_interval(self) -> None:
        block = waist_trend(
            waist([(42, 87.5), (28, 87.4), (14, 87.3), (0, 87.2)]),
            today_d=T)
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "ci_straddles_zero")
        lo, hi = block["ci95_cm_per_4w"]
        self.assertGreater(hi - lo, 0.0, "a zero-width interval is back")
        self.assertGreater(block["se_cm_per_4w"], 0.0)
        self.assertLess(lo, 0.0)
        self.assertGreater(hi, 0.0)

    def test_the_floor_is_the_low_end_of_the_documented_tape_error(self) -> None:
        """A floor asserts what the instrument cannot go below, not what it
        typically is, so it takes the LOW end of the cited 0.5-1.0 cm
        band."""
        self.assertEqual(WAIST_MEASUREMENT_SD_CM, 0.5)
        self.assertEqual(BODYWEIGHT_MEASUREMENT_SD_KG, 0.5)

    def test_the_fit_says_when_the_floor_bound(self) -> None:
        pts = [(date(2026, 5, 1) + timedelta(days=7 * i), 87.0 - 0.1 * i)
               for i in range(6)]
        bare = ols_rate_per_week(pts)
        floored = ols_rate_per_week(pts, noise_sd_floor=0.5)
        self.assertFalse(bare["noise_floored"])
        self.assertAlmostEqual(bare["se_per_week"], 0.0, places=9)
        self.assertTrue(floored["noise_floored"])
        self.assertGreater(floored["se_per_week"], 0.0)
        # The estimate itself is untouched; only its uncertainty moves.
        self.assertAlmostEqual(bare["per_week"], floored["per_week"],
                               places=12)

    def test_a_noisy_series_is_left_alone_by_the_floor(self) -> None:
        """The floor is a floor. On data noisier than the instrument it
        must not touch the interval at all, or every fit silently inherits
        a caveat it did not earn."""
        pts = [(date(2026, 5, 1) + timedelta(days=7 * i), v)
               for i, v in enumerate([87.0, 89.4, 85.1, 88.9, 84.6, 88.2])]
        bare = ols_rate_per_week(pts)
        floored = ols_rate_per_week(pts, noise_sd_floor=0.5)
        self.assertGreater(bare["residual_sd"], 0.5)
        self.assertFalse(floored["noise_floored"])
        self.assertEqual(bare["se_per_week"], floored["se_per_week"])

    def test_the_floor_is_off_by_default(self) -> None:
        """``ols_rate_per_week`` is the classic estimator and other callers
        rely on it being exactly that."""
        sig = inspect.signature(ols_rate_per_week)
        self.assertIsNone(sig.parameters["noise_sd_floor"].default)

    def test_the_note_declares_the_floor_only_when_it_bound(self) -> None:
        clean = waist([(49, 91.0), (42, 90.5), (35, 90.0), (28, 89.5),
                       (21, 89.0), (14, 88.5), (7, 88.0), (0, 87.5)])
        noisy = waist([(49, 91.0), (42, 92.6), (35, 88.4), (28, 91.2),
                       (21, 87.3), (14, 90.1), (7, 86.2), (0, 88.9)])
        self.assertIn("fit too cleanly", waist_trend(clean, today_d=T)["note"])
        self.assertNotIn("fit too cleanly",
                         waist_trend(noisy, today_d=T)["note"])


class ALongCleanSeriesStillResolvesTests(unittest.TestCase):
    """The other half of the "no new state" decision.

    If a near-zero SE were made ``unresolved`` outright, the series with
    the most evidence in the file would be the one the estimator refused
    to read. It must resolve, and the caveat rides along in the note.
    """

    def test_a_real_two_centimetre_cut_over_seven_weeks_resolves(self) -> None:
        block = waist_trend(
            waist([(7 * i, 87.0 + 0.5 * i) for i in range(9)]), today_d=T)
        self.assertEqual(block["state"], "resolved")
        self.assertLess(block["cm_per_4w"], 0.0)
        lo, hi = block["ci95_cm_per_4w"]
        self.assertLess(hi, 0.0)
        self.assertIn("narrowing", block["note"])

    def test_the_cut_the_design_comment_promises_is_detectable(self) -> None:
        """The comment claims T = 56 days at n = 8 is where a ~1 cm/4wk
        change becomes resolvable. Before the noise floor that claim was
        untestable, because ANY drift resolved. It should hold now."""
        pts = [(7 * i, 90.0 - 0.25 * (7 - i) + (0.2 if i % 2 else -0.2))
               for i in range(8)]
        block = waist_trend(waist(pts), today_d=T)
        self.assertEqual(block["state"], "resolved")
        self.assertLess(abs(block["cm_per_4w"]), 1.6)
        self.assertLess(block["ci95_cm_per_4w"][1], 0.0)


# ------------------------------------------------- bodyweight, shared gate
class BodyweightInheritsTheSameGateTests(unittest.TestCase):
    """The gate is shared, so bodyweight gets these checks too.

    A reviewer confirmed the same zero-SE path existed in
    ``bodyweight_trend``; it was only harder to reach because weigh-ins
    are near-daily. A per-column copy of the fix is how the original
    window/span confusion got in, so the fix lives in ``_trend_verdict``.
    """

    def test_the_c1_shape_is_blocked_on_bodyweight_too(self) -> None:
        block = bodyweight_trend(
            weighins([(3, 78.3), (2, 78.2), (1, 78.1), (0, 78.0)]), today_d=T)
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "span_shorter_than_min")
        self.assertIsNone(block["kg_per_week"])
        self.assertIn("spanning 3 days", block["note"])

    def test_weigh_ins_that_stop_ten_days_ago_do_not_resolve(self) -> None:
        block = bodyweight_trend(
            weighins([(10 + i, 78.0 + 0.05 * i) for i in range(5)]),
            today_d=T)
        self.assertEqual(block["reason"], "readings_stale")
        self.assertEqual(block["days_since_last_reading"], 10)

    def test_four_collinear_weekly_weigh_ins_no_longer_claim_certainty(self) -> None:
        """The bodyweight twin of C1's zero-width interval. +0.10 kg/wk
        with a +-0.00 interval is not a finding."""
        block = bodyweight_trend(
            weighins([(21, 77.7), (14, 77.8), (7, 77.9), (0, 78.0)]),
            today_d=T)
        self.assertEqual(block["state"], "unresolved")
        self.assertEqual(block["reason"], "ci_straddles_zero")
        lo, hi = block["ci95_kg_per_week"]
        self.assertGreater(hi - lo, 0.5)

    def test_a_well_sampled_current_gain_still_resolves(self) -> None:
        """The shape the live tracker actually holds: a few weeks of dense
        weigh-ins with real day-to-day scatter, ending today. This is the
        regression that would matter most, so it is pinned with an
        explicit fixture rather than left to the live data.

        Values are invented and the dates are anchored to a synthetic
        ``T``; nothing here reproduces a tracker's weigh-ins.
        """
        kgs = [77.6, 78.9, 77.4, 79.3, 78.1, 79.8, 78.6, 80.4,
               79.2, 80.9, 79.7, 81.3, 80.4, 81.8, 80.9]
        offsets = [26, 24, 22, 21, 19, 17, 15, 13, 11, 9, 7, 6, 4, 2, 0]
        block = bodyweight_trend(weighins(list(zip(offsets, kgs))), today_d=T)
        self.assertEqual(block["state"], "resolved",
                         f"a working metric went dark: {block['note']}")
        self.assertGreater(block["kg_per_week"], 0.0)
        self.assertGreater(block["ci95_kg_per_week"][0], 0.0)
        self.assertGreaterEqual(block["span_days"],
                                BODYWEIGHT_TREND_MIN_SPAN_DAYS)

    def test_the_bodyweight_span_floor_is_reachable_inside_its_window(self) -> None:
        """The trap this floor had to avoid. A 28-day window holds at most
        a 27-day span, so an SE-derived floor (58 days at n = 4, or 24 at
        the daily cadence the design comment assumes) is either impossible
        or so tight that ordinary weekly weigh-ins flicker in and out of
        it as the window slides. The floor is the reporting horizon
        instead, and detectability is left to the interval, which handles
        it correctly."""
        max_span = BODYWEIGHT_TREND_MIN_WINDOW_DAYS - 1
        self.assertLessEqual(BODYWEIGHT_TREND_MIN_SPAN_DAYS, max_span)
        # Weekly weigh-ins inside a 28-day window span 21 days. They must
        # not be structurally excluded.
        weekly = bodyweight_trend(
            weighins([(21, 79.4), (14, 78.1), (7, 79.9), (0, 78.6)]),
            today_d=T)
        self.assertNotIn(weekly["reason"],
                         {"span_shorter_than_min", "readings_stale"})

    def test_the_note_reports_the_span_not_the_window(self) -> None:
        kgs = [77.6, 78.9, 77.4, 79.3, 78.1, 79.8, 78.6, 80.4,
               79.2, 80.9, 79.7, 81.3, 80.4, 81.8, 80.9]
        offsets = [26, 24, 22, 21, 19, 17, 15, 13, 11, 9, 7, 6, 4, 2, 0]
        block = bodyweight_trend(weighins(list(zip(offsets, kgs))), today_d=T)
        self.assertIn(f"spanning {block['span_days']} days", block["note"])
        self.assertNotIn(f"/ {block['window_days']} days", block["note"])


# ------------------------------------------------------------ monotonicity
class TheGateOnlyGotTighterTests(unittest.TestCase):
    """Nothing that failed before may pass now.

    The pre-fix behaviour is still reachable exactly: ``_trend_verdict``'s
    new parameters all default to off, so calling it with the old argument
    list IS the old code path rather than a re-implementation of it.
    """

    CASES = [
        [(0, 87.2), (1, 87.3), (2, 87.4), (3, 87.5)],
        [(0, 87.2), (13, 87.4), (26, 87.6), (39, 87.8)],
        [(0, 87.2), (18, 87.6), (36, 88.0), (54, 88.4)],
        [(52, 87.2), (53, 87.3), (54, 87.4), (55, 87.5)],
        [(0, 90.0), (14, 90.1), (28, 89.4), (42, 90.6), (55, 89.1)],
        [(0, 87.0), (7, 87.0), (14, 87.0), (21, 87.0), (28, 87.0),
         (35, 87.0), (42, 87.0), (49, 87.0)],
        [(0, 84.0), (12, 85.5), (24, 87.0), (36, 88.5), (48, 90.0)],
        # Clustered-leverage family: cluster + one distant anchor, at
        # both ends of the reachable span, plus the replicated-endpoint
        # shape. All of these RESOLVED before the leverage check.
        [(0, 87.1), (1, 87.0), (2, 87.1), (45, 90.2)],
        [(0, 87.1), (1, 87.0), (2, 87.1), (39, 90.2)],
        [(0, 87.1), (0, 87.0), (55, 90.1), (55, 90.2)],
    ]

    def _pts(self, case):
        return sorted((T - timedelta(days=d), cm) for d, cm in case)

    def _after(self, pts):
        return sessions._trend_verdict(
            pts, T, None, WAIST_TREND_MIN_WINDOW_DAYS,
            WAIST_TREND_MIN_READINGS,
            min_span_days=WAIST_TREND_MIN_SPAN_DAYS,
            max_stale_days=WAIST_TREND_MAX_STALE_DAYS,
            noise_sd_floor=WAIST_MEASUREMENT_SD_CM,
            min_effective_readings=TREND_MIN_EFFECTIVE_READINGS)

    def test_no_case_moves_from_unresolved_to_resolved(self) -> None:
        for i, case in enumerate(self.CASES):
            with self.subTest(case=i):
                pts = self._pts(case)
                before = sessions._trend_verdict(
                    pts, T, None, WAIST_TREND_MIN_WINDOW_DAYS,
                    WAIST_TREND_MIN_READINGS)
                if self._after(pts)[0] == "resolved":
                    self.assertEqual(before[0], "resolved",
                                     "the gate got LOOSER on this series")

    def test_the_fixtures_exercise_both_verdicts(self) -> None:
        """Guard the guard: an all-unresolved fixture set would make the
        monotonicity assertion vacuous."""
        after = [self._after(self._pts(c))[0] for c in self.CASES]
        self.assertIn("resolved", after)
        self.assertIn("unresolved", after)

    def test_every_new_parameter_defaults_to_off(self) -> None:
        """The pre-fix behaviour has to stay reachable EXACTLY, or the
        comparison above is against a re-implementation rather than
        against the old code path."""
        sig = inspect.signature(sessions._trend_verdict)
        for name in ("min_span_days", "min_effective_readings"):
            with self.subTest(name):
                self.assertEqual(sig.parameters[name].default, 0)
        for name in ("max_stale_days", "noise_sd_floor"):
            with self.subTest(name):
                self.assertIsNone(sig.parameters[name].default)

    def test_the_leverage_check_is_what_catches_the_clustered_family(self) -> None:
        """The three clustered fixtures must fail for the LEVERAGE reason
        specifically. A span or recency reason there would mean the new
        gate is dead weight and the older ones happened to cover it."""
        for i in (7, 8, 9):
            with self.subTest(case=i):
                before = sessions._trend_verdict(
                    self._pts(self.CASES[i]), T, None,
                    WAIST_TREND_MIN_WINDOW_DAYS, WAIST_TREND_MIN_READINGS)
                after = self._after(self._pts(self.CASES[i]))
                self.assertEqual(before[0], "resolved")
                self.assertEqual(after[1], "too_few_effective_readings")


# ------------------------------------------------------------------- C8
class TheTooltipStatesTheGateItActuallyHasTests(unittest.TestCase):
    """The one sentence a non-technical user reads directly.

    It used to say "the rate needs at least 56 days of measurements before
    it can resolve a direction". The estimator had no such requirement --
    it needed 4 readings inside a 56-day window, which the C1 fixture
    satisfies over three days.
    """

    def _tooltip(self) -> str:
        html = rch.card_vitals(
            [{"week_start": "2026-07-13", "hrv_sdnn": 55, "waist_cm": 87.4},
             {"week_start": "2026-07-20", "hrv_sdnn": 56, "waist_cm": 87.2}],
            {"value": 48.0}, 0.3, {"kg": 78.4, "date": "2026-08-01"},
            None, [77.9, 78.1], "")
        row = next(r for r in html.split("<tr>") if ">Waist<" in r)
        return re.search(r'data-tip="([^"]*)"', row).group(1)

    def test_it_no_longer_claims_a_requirement_the_gate_does_not_have(self) -> None:
        tip = self._tooltip()
        self.assertNotIn("56 days of measurements", tip)

    def test_it_names_each_of_the_three_things_the_gate_checks(self) -> None:
        tip = self._tooltip()
        self.assertIn("4 measurements", tip)      # sample size
        self.assertIn("39 days", tip)             # span
        self.assertIn("4 weeks old", tip)         # recency

    def test_it_admits_the_sparkline_is_shorter_than_the_fit(self) -> None:
        """The sparkline is built over 4 weeks and the rate is fitted over
        up to 8. The reconciliation belongs in the payload builder, which
        this build does not own; until then the tooltip must not let the
        reader assume the line and the number cover the same period."""
        tip = self._tooltip()
        self.assertIn("last 4 weeks", tip)
        self.assertIn("8", tip)

    def test_both_new_reason_codes_render_their_own_words(self) -> None:
        for reason, label in (("span_shorter_than_min", "span under"),
                              ("readings_stale", "last measured over")):
            with self.subTest(reason=reason):
                self.assertIn(label, rch._WAIST_STATE_LABEL[reason])
        for reason in ("span_shorter_than_min", "readings_stale"):
            with self.subTest(bw=reason):
                self.assertIn(reason, rch._BW_STATE_LABEL)
        # Distinct wording, or the distinction is decorative.
        self.assertEqual(len(set(rch._WAIST_STATE_LABEL.values())),
                         len(rch._WAIST_STATE_LABEL))
        self.assertEqual(len(set(rch._BW_STATE_LABEL.values())),
                         len(rch._BW_STATE_LABEL))

    def test_every_reason_the_estimator_can_emit_has_a_label(self) -> None:
        """A new reason code with no label falls through to a generic
        "trend unresolved", which is how the dashboard ends up saying less
        than the estimator knows."""
        emitted = set(re.findall(r'"(\w+)", \*tail',
                                 inspect.getsource(sessions._trend_verdict)))
        emitted.discard("no_readings")   # emitted, and mapped, on both
        self.assertTrue(emitted, "reason codes could not be extracted")
        for reason in emitted | {"no_readings"}:
            with self.subTest(reason=reason):
                self.assertIn(reason, rch._WAIST_STATE_LABEL)
                self.assertIn(reason, rch._BW_STATE_LABEL)


class ThresholdsStayTiedToTheirDerivationTests(unittest.TestCase):

    def test_the_recency_bound_is_the_reporting_horizon(self) -> None:
        """Each field is labelled with a period -- "cm per 4 weeks", "kg per
        week". If the newest reading is older than that period, the fit
        does not overlap the period the label names."""
        self.assertEqual(WAIST_TREND_MAX_STALE_DAYS, 28)
        self.assertEqual(BODYWEIGHT_TREND_MAX_STALE_DAYS, 7)

    def test_the_bodyweight_span_floor_is_the_reporting_horizon(self) -> None:
        self.assertEqual(BODYWEIGHT_TREND_MIN_SPAN_DAYS, 7)

    def test_no_threshold_is_a_no_op(self) -> None:
        for name, value in (
            ("WAIST_TREND_MIN_SPAN_DAYS", WAIST_TREND_MIN_SPAN_DAYS),
            ("WAIST_TREND_MAX_STALE_DAYS", WAIST_TREND_MAX_STALE_DAYS),
            ("BODYWEIGHT_TREND_MIN_SPAN_DAYS",
             BODYWEIGHT_TREND_MIN_SPAN_DAYS),
            ("BODYWEIGHT_TREND_MAX_STALE_DAYS",
             BODYWEIGHT_TREND_MAX_STALE_DAYS),
            ("WAIST_MEASUREMENT_SD_CM", WAIST_MEASUREMENT_SD_CM),
            ("BODYWEIGHT_MEASUREMENT_SD_KG", BODYWEIGHT_MEASUREMENT_SD_KG),
        ):
            with self.subTest(name):
                self.assertGreater(value, 0, f"{name} disables its gate")


if __name__ == "__main__":
    unittest.main()
