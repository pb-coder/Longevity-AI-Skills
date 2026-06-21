"""Tests for Cluster F bugs:
  F10 - Longevity body-comp score ignores active phase goal
  F12 - REM counter threshold and advertised target_min_pct disagree
  F14 - Thermal/light adherence band is asymmetric (over-target reads on-target)
  F17 - Swim pace has no unit-sanity clamp
  F19 - Fuzzy matcher ranks "lat raise" -> "Leg Raise" (wrong)

All data is synthetic — no real personal data.
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ============================================================ F10
class LongevityBodyCompPhaseAwareTests(unittest.TestCase):
    """F10: A -0.3 kg/wk trend during an active 'cut' should score GOOD,
    not the worst band (50.0 / warn), because losing weight at a
    well-paced rate is exactly correct during a cut."""

    def _call(self, bw_trend, phase_type=None):
        from workout_coach.lib.health_longevity import compute_longevity_score
        # Supply only bodyweight_trend so the result isolates the component.
        result = compute_longevity_score(
            vo2_percentile=None,
            recovery=None,
            sleep_summary=None,
            sleep_regularity=None,
            acwr=None,
            cardio_zones=None,
            movement_consistency=None,
            bodyweight_trend_kg_per_week=bw_trend,
            estimated_1rm=None,
            phase_type=phase_type,
        )
        return result

    def test_cut_paced_loss_scores_good_not_worst(self):
        """F10 regression: -0.3 kg/wk during a cut must score in the GOOD
        band (band != 'warn') rather than landing at 50.0 (worst tier)."""
        result = self._call(-0.3, phase_type="cut")
        self.assertIsNotNone(result, "compute_longevity_score returned None unexpectedly")
        comp = next(
            (c for c in result["components"] if c["name"] == "body_comp_trend"),
            None,
        )
        self.assertIsNotNone(comp, "body_comp_trend component missing from result")
        # The score component must be clearly above the 50.0 floor that
        # the original buggy code returned for any negative trend.
        self.assertGreater(
            comp["score"], 60.0,
            f"Expected body_comp_trend > 60 for cut phase, got {comp['score']}"
        )

    def test_cut_gain_scores_poorly(self):
        """Gaining weight during a cut should score badly."""
        result = self._call(0.4, phase_type="cut")
        comp = next(
            (c for c in result["components"] if c["name"] == "body_comp_trend"),
            None,
        )
        self.assertIsNotNone(comp)
        # Weight gain during a cut is bad — should not score above 60.
        self.assertLess(
            comp["score"], 61.0,
            f"Expected body_comp_trend <= 60 for gain during cut, got {comp['score']}"
        )

    def test_backward_compat_no_phase_type(self):
        """Without phase_type (None/absent), existing scoring still works."""
        result = self._call(0.2, phase_type=None)
        self.assertIsNotNone(result)
        comp = next(
            (c for c in result["components"] if c["name"] == "body_comp_trend"),
            None,
        )
        self.assertIsNotNone(comp)
        # Neutral slight gain with no phase should still score >=60 (lean-bulk default)
        self.assertGreaterEqual(comp["score"], 60.0)

    def test_bulk_slight_gain_scores_good(self):
        """Slight gain during bulk should score well."""
        result = self._call(0.2, phase_type="bulk")
        comp = next(
            (c for c in result["components"] if c["name"] == "body_comp_trend"),
            None,
        )
        self.assertIsNotNone(comp)
        self.assertGreater(comp["score"], 60.0)

    def test_maintain_flat_scores_well(self):
        """Flat weight during maintain should score well."""
        result = self._call(0.05, phase_type="maintain")
        comp = next(
            (c for c in result["components"] if c["name"] == "body_comp_trend"),
            None,
        )
        self.assertIsNotNone(comp)
        self.assertGreater(comp["score"], 60.0)


# ============================================================ F12
class REMThresholdConsistencyTests(unittest.TestCase):
    """F12: The threshold used to count low-REM nights (currently 15%)
    and the advertised target_min_pct (currently 20%) must be the same
    value in flag_rem_sleep_anomalies()."""

    def _make_nights(self, rem_pct: float, n: int = 5) -> list[dict]:
        """Synthetic nights where REM = rem_pct% of total sleep."""
        today = date(2026, 6, 21)
        nights = []
        for i in range(n):
            d = (today - timedelta(days=i)).isoformat()
            total = 8.0
            rem = total * (rem_pct / 100.0)
            nights.append({"date": d, "total_h": total, "rem_h": rem})
        return nights

    def test_threshold_and_reported_target_agree(self):
        """The value used to count low_rem_nights must equal target_min_pct."""
        from workout_coach.lib.sleep import flag_rem_sleep_anomalies
        today = date(2026, 6, 21)

        # Nights at exactly the boundary between "low" and "normal".
        # With the bug: threshold=15% but target=20%, so nights at 17%
        # do NOT trigger the counter but ARE below the advertised target.
        # After fix: both should use the same value.

        # All nights at 17% REM — between old threshold (15) and old target (20).
        nights_17 = self._make_nights(17.0, n=5)
        result_17 = flag_rem_sleep_anomalies(nights_17, today)
        self.assertIsNotNone(result_17)

        threshold = result_17["target_min_pct"]
        low_count = result_17["low_rem_nights"]
        mean_pct = result_17["mean_rem_pct"]

        # The single source of truth test: whatever the advertised threshold
        # is, nights below it must be counted and nights above must not be.
        if mean_pct < threshold:
            self.assertGreater(
                low_count, 0,
                f"Nights at {mean_pct}% are below advertised target {threshold}% "
                f"but low_rem_nights={low_count} (not counted)"
            )
        else:
            self.assertEqual(
                low_count, 0,
                f"Nights at {mean_pct}% are above advertised target {threshold}% "
                f"but low_rem_nights={low_count} (incorrectly counted)"
            )

    def test_nights_at_exactly_threshold_boundary(self):
        """Nights just below threshold should be counted as low-REM."""
        from workout_coach.lib.sleep import flag_rem_sleep_anomalies
        today = date(2026, 6, 21)

        # Build a result with nights clearly above any reasonable threshold (25%)
        # to determine what the threshold is, then confirm the counter is consistent.
        nights_above = self._make_nights(25.0, n=5)
        result_above = flag_rem_sleep_anomalies(nights_above, today)
        self.assertIsNotNone(result_above)
        threshold = result_above["target_min_pct"]

        # Now build nights just below the threshold.
        pct_below = threshold - 2.0
        nights_below = self._make_nights(pct_below, n=5)
        result_below = flag_rem_sleep_anomalies(nights_below, today)
        self.assertIsNotNone(result_below)

        # All nights are below threshold — they should ALL be counted.
        self.assertEqual(
            result_below["low_rem_nights"],
            result_below["n_nights"],
            f"All nights at {pct_below}% (below threshold {threshold}%) should "
            f"be counted as low-REM, got {result_below['low_rem_nights']} / "
            f"{result_below['n_nights']}"
        )


# ============================================================ F14
class ThermalAdherenceBandTests(unittest.TestCase):
    """F14: 4.5 sessions/wk against a 3/wk target should read 'above-target',
    not 'on-target'. The asymmetric band (-0.5/+1.5) wrongly allows
    values well above target to read 'on-target'."""

    def _make_sessions(self, n_sessions: int) -> list[dict]:
        """Synthetic heat sessions spread over the last 28 days."""
        today = date(2026, 6, 21)
        sessions = []
        for i in range(n_sessions):
            d = (today - timedelta(days=i % 27)).isoformat()
            sessions.append({
                "date": d,
                "heat_type": "dry",
                "heat_total_min": 25.0,
                "heat_temp_c": 85.0,
            })
        return sessions

    def test_thermal_above_target_reads_above_target(self):
        """4.5/wk vs 3/wk target should be 'above-target', not 'on-target'."""
        from workout_coach.lib.thermal import thermal_summary
        today = date(2026, 6, 21)
        # 4.5 sessions/wk × 4 weeks = 18 sessions
        sessions = self._make_sessions(18)
        result = thermal_summary(sessions, today, target_per_week=3)
        self.assertIsNotNone(result)
        adherence = result["adherence"]
        actual_per_week = adherence["heat_actual_per_week"]
        # Verify we're actually generating the expected frequency
        self.assertGreater(actual_per_week, 4.0,
                           f"Expected >4 sessions/wk but got {actual_per_week}")
        self.assertEqual(
            adherence["heat_status"], "above-target",
            f"Expected 'above-target' for {actual_per_week}/wk vs target=3, "
            f"got '{adherence['heat_status']}'"
        )

    def test_thermal_on_target_reads_on_target(self):
        """Sessions within ±0.5 of target should still read 'on-target'."""
        from workout_coach.lib.thermal import thermal_summary
        today = date(2026, 6, 21)
        # 3/wk target × 4 weeks = 12 sessions exactly
        sessions = self._make_sessions(12)
        result = thermal_summary(sessions, today, target_per_week=3)
        adherence = result["adherence"]
        self.assertEqual(adherence["heat_status"], "on-target")

    def test_thermal_below_target_reads_below_target(self):
        """Sessions well below target should still read 'below-target'."""
        from workout_coach.lib.thermal import thermal_summary
        today = date(2026, 6, 21)
        # 1/wk × 4 weeks = 4 sessions
        sessions = self._make_sessions(4)
        result = thermal_summary(sessions, today, target_per_week=3)
        adherence = result["adherence"]
        self.assertEqual(adherence["heat_status"], "below-target")


class LightTherapyAdherenceBandTests(unittest.TestCase):
    """F14 (light_therapy): Same asymmetric band bug in light_therapy.py."""

    def _make_sessions(self, n_sessions: int) -> list[dict]:
        """Synthetic light therapy sessions spread over the last 28 days."""
        today = date(2026, 6, 21)
        sessions = []
        for i in range(n_sessions):
            d = (today - timedelta(days=i % 27)).isoformat()
            sessions.append({
                "date": d,
                "light_type": "red+ir",
                "modality": "panel",
                "duration_min": 12.0,
            })
        return sessions

    def test_light_above_target_reads_above_target(self):
        """4.5/wk vs 3/wk target should be 'above-target', not 'on-target'."""
        from workout_coach.lib.light_therapy import light_therapy_summary
        today = date(2026, 6, 21)
        # 4.5/wk × 4 weeks = 18 sessions
        sessions = self._make_sessions(18)
        result = light_therapy_summary(sessions, today, target_per_week=3)
        self.assertIsNotNone(result)
        adherence = result["adherence"]
        actual = adherence["actual_per_week"]
        self.assertGreater(actual, 4.0,
                           f"Expected >4 sessions/wk but got {actual}")
        self.assertEqual(
            adherence["status"], "above-target",
            f"Expected 'above-target' for {actual}/wk vs target=3, "
            f"got '{adherence['status']}'"
        )

    def test_light_on_target_reads_on_target(self):
        """Sessions at target should read 'on-target'."""
        from workout_coach.lib.light_therapy import light_therapy_summary
        today = date(2026, 6, 21)
        sessions = self._make_sessions(12)  # exactly 3/wk
        result = light_therapy_summary(sessions, today, target_per_week=3)
        adherence = result["adherence"]
        self.assertEqual(adherence["status"], "on-target")

    def test_light_below_target_reads_below_target(self):
        """Sessions well below target should read 'below-target'."""
        from workout_coach.lib.light_therapy import light_therapy_summary
        today = date(2026, 6, 21)
        sessions = self._make_sessions(4)  # 1/wk
        result = light_therapy_summary(sessions, today, target_per_week=3)
        adherence = result["adherence"]
        self.assertEqual(adherence["status"], "below-target")


# ============================================================ F17
class SwimPaceUnitSanityClampTests(unittest.TestCase):
    """F17: A swim pace outside a plausible band (<20 or >600 sec/100m)
    should be blanked/flagged rather than reported as a real pace.

    The classic failure mode is distance stored in metres when the field
    expects km (e.g. 1500 stored as 1500 instead of 1.5), which makes
    the computed pace implausibly fast (<1 sec/100m)."""

    def test_implausibly_fast_pace_is_blanked(self):
        """Distance stored as metres-as-km yields ~0.04 sec/100m — must return None."""
        from workout_coach.lib.swim import pace_per_100m
        # 1500m stored as 1500 km (metres-as-km bug), 30 min duration.
        # pace = (30*60) / (1500*10) = 1800/15000 = 0.12 sec/100m — implausibly fast.
        result = pace_per_100m(1500.0, 30.0)
        self.assertIsNone(
            result,
            f"Expected None for implausibly fast pace (metres-as-km), got {result}"
        )

    def test_implausibly_slow_pace_is_blanked(self):
        """A pace > 600 sec/100m should return None (someone near-stationary)."""
        from workout_coach.lib.swim import pace_per_100m
        # 0.01 km in 30 min = 1800/0.1 = 18000 sec/100m
        result = pace_per_100m(0.01, 30.0)
        self.assertIsNone(
            result,
            f"Expected None for implausibly slow pace, got {result}"
        )

    def test_valid_pace_is_returned(self):
        """A normal competitive pace (e.g. 1.5 km in 25 min ≈ 100 sec/100m)
        should pass through correctly."""
        from workout_coach.lib.swim import pace_per_100m
        # 1.5 km in 25 min: pace = (25*60)/(1.5*10) = 1500/15 = 100 sec/100m
        result = pace_per_100m(1.5, 25.0)
        self.assertIsNotNone(result, "Valid pace should not be blanked")
        self.assertAlmostEqual(result, 100.0, places=0)

    def test_slow_but_valid_pace_is_returned(self):
        """A slow but plausible pace (~500 sec/100m) should be returned."""
        from workout_coach.lib.swim import pace_per_100m
        # 0.1 km in ~8.3 min: pace ≈ 500 sec/100m (very slow beginner)
        result = pace_per_100m(0.1, 8.33)
        self.assertIsNotNone(result, "Slow but valid pace should not be blanked")
        self.assertLess(result, 600.0)

    def test_boundary_value_20_sec_per_100m_is_returned(self):
        """A pace of exactly 20 sec/100m should be valid (elite sprinter territory)."""
        from workout_coach.lib.swim import pace_per_100m
        # 1.0 km in 3.333 min = 200 sec / 10 blocks = 20 sec/100m
        result = pace_per_100m(1.0, 200.0 / 60.0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 20.0, places=0)


# ============================================================ F19
class FuzzyMatchRankingTests(unittest.TestCase):
    """F19: fuzzy_match("lat raise") must rank a lateral raise above "Leg Raise".
    fuzzy_match("calf raise") must rank a calf raise first."""

    def test_lat_raise_matches_lateral_raise_not_leg_raise(self):
        """'lat raise' should best-match a lateral raise variant, not 'Leg Raise'."""
        from shared.exercises_database import fuzzy_match
        results = fuzzy_match("lat raise", k=5)
        self.assertGreater(len(results), 0, "fuzzy_match returned no results")
        names = [r[0] for r in results]
        # Check that a lateral raise variant appears in the top results
        lateral_raises = [n for n in names
                          if "lateral raise" in n.lower() or "lat raise" in n.lower()]
        self.assertGreater(
            len(lateral_raises), 0,
            f"No lateral raise in top-5 results for 'lat raise': {names}"
        )
        # Check that the top hit is a lateral raise, not a leg raise
        top_hit = names[0].lower()
        self.assertNotIn(
            "leg raise", top_hit,
            f"Top hit for 'lat raise' is '{names[0]}' — should be a lateral raise"
        )
        # The lateral raise should be ranked above any leg raise
        leg_raise_idxs = [i for i, n in enumerate(names) if "leg raise" in n.lower()]
        lateral_raise_idxs = [i for i, n in enumerate(names)
                               if "lateral raise" in n.lower()]
        if leg_raise_idxs and lateral_raise_idxs:
            self.assertLess(
                min(lateral_raise_idxs),
                min(leg_raise_idxs),
                f"Lateral raise (idx {min(lateral_raise_idxs)}) ranked below "
                f"Leg Raise (idx {min(leg_raise_idxs)}) for input 'lat raise': {names}"
            )

    def test_calf_raise_matches_calf_raise_first(self):
        """'calf raise' should best-match a calf raise variant."""
        from shared.exercises_database import fuzzy_match
        results = fuzzy_match("calf raise", k=5)
        self.assertGreater(len(results), 0)
        names = [r[0] for r in results]
        top_hit = names[0].lower()
        self.assertIn(
            "calf raise", top_hit,
            f"Top hit for 'calf raise' is '{names[0]}' — expected a calf raise"
        )

    def test_lat_raise_top_score_above_leg_raise_score(self):
        """For 'lat raise', the score of the best lateral raise must be
        strictly higher than the score of the best leg raise."""
        from shared.exercises_database import fuzzy_match
        results = fuzzy_match("lat raise", k=20)
        scores_by_name = {n: s for n, s in results}
        lateral_scores = [s for n, s in scores_by_name.items()
                          if "lateral raise" in n.lower()]
        leg_scores = [s for n, s in scores_by_name.items()
                      if "leg raise" in n.lower()]
        if lateral_scores and leg_scores:
            self.assertGreater(
                max(lateral_scores),
                max(leg_scores),
                f"Best lateral raise score {max(lateral_scores)} must beat "
                f"best leg raise score {max(leg_scores)} for input 'lat raise'"
            )


if __name__ == "__main__":
    unittest.main()
