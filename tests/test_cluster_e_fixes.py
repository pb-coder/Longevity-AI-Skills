"""Tests for Cluster E bug fixes: E3, E6, E15, E16, E20.

All data is synthetic — no real per-person data.
"""
from __future__ import annotations

import sys
import os
import unittest
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[1]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))


# ---------------------------------------------------------------------------
# E3: render crash on empty cardio window
# ---------------------------------------------------------------------------

class E3RenderCrashEmptyCardioTests(unittest.TestCase):
    """E3: `or {{}}` inside f-string is a set containing a dict ->
    TypeError: unhashable type: 'dict'. Must crash before the fix."""

    def _make_minimal_tracker(self, cardio_hr_zones_28d=None):
        """Return a minimal synthetic tracker JSON dict."""
        j = {
            "today": "2026-01-15",
            "recovery": {"score": 7.0, "confidence": "high", "drivers": []},
            "training_load": {"tsb": 0.0, "ctl": 50.0, "atl": 45.0, "trend_7d": 0.5},
            "health_metrics_weekly": [],
            "weekly_volume_per_muscle": {},
            "estimated_1rm": {},
            "thermal_summary": {},
            "light_therapy_summary": {},
            "bodyweight_latest": {},
            "vo2max_latest": {},
            "week_over_week": {"rows": []},
            "monthly_sessions": [],
            "longevity_score": {},
            "tier_history": [],
        }
        if cardio_hr_zones_28d is not None:
            j["cardio_hr_zones_28d"] = cardio_hr_zones_28d
        return j

    def _render(self, j):
        """Import render() and call it; return the resulting HTML string."""
        # We need scripts/ on the path so render_dashboard.py is importable
        scripts_dir = SKILLS_ROOT / "workout-coach" / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "render_dashboard",
            scripts_dir / "render_dashboard.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        coach = {"headline": "Test.", "cards": {}}
        return mod.render(j, coach, "# Workout\n", "Person A")

    def test_render_crashes_with_empty_dict_cardio_zones_before_fix(self):
        """Calling render() with cardio_hr_zones_28d={} raises TypeError
        before the fix because `or {{}}` constructs a set literal `{dict}`.

        After the fix this test is replaced by the smoke test below, but
        we capture the crash root cause here: the buggy expression IS the
        one we target.
        """
        # Directly verify the expression that was buggy evaluates incorrectly.
        # Before fix: `{} or {{}}` inside an f-string created `{{{}}}` which
        # Python sees as set({}) – unhashable. We verify the FIXED form works.
        # This test exercises the render path end-to-end; it must not raise.
        j = self._make_minimal_tracker(cardio_hr_zones_28d={})
        # Should NOT raise after the fix.
        html = self._render(j)
        self.assertIn("<!doctype html>", html)

    def test_render_with_absent_cardio_zones_does_not_crash(self):
        """render() must not crash when cardio_hr_zones_28d is absent."""
        j = self._make_minimal_tracker()  # key absent
        html = self._render(j)
        self.assertIn("<!doctype html>", html)

    def test_render_with_none_cardio_zones_does_not_crash(self):
        """render() must not crash when cardio_hr_zones_28d is None."""
        j = self._make_minimal_tracker(cardio_hr_zones_28d=None)
        html = self._render(j)
        self.assertIn("<!doctype html>", html)


# ---------------------------------------------------------------------------
# E6: ### subsection headings zero out sets beneath them
# ---------------------------------------------------------------------------

from workout_coach.lib.render_validators import count_working_sets_per_workout


class E6SubsectionHeadingTests(unittest.TestCase):
    """E6: count_working_sets_per_workout resets scope on ANY heading,
    including ### Accessories, zeroing out sets that follow."""

    def test_subsection_heading_does_not_reset_workout_scope(self):
        """Sets under a ### Accessories heading still count under Workout A."""
        plan = """# Workout plan — 2026-01-15

## Workout A: PUSH
- Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8 /// 50kgx8

### Accessories
- Cable Lateral Raise: 14kgx12 /// 14kgx12

"""
        counts = count_working_sets_per_workout(plan)
        # 3 bench + 2 lateral = 5; ### heading must NOT reset scope
        self.assertEqual(counts.get("Workout A: PUSH"), 5)

    def test_section_level_2_non_workout_still_resets_scope(self):
        """## Cardio (not a Workout heading) must still reset scope so
        cardio bullets never bleed into a prior workout's count."""
        plan = """# Workout plan — 2026-01-15

## Workout 1: PULL
- Cable Lat Pulldown: 65kgx8 /// 65kgx8 /// 65kgx8

## Cardio 1: Intervals
- Work: 5 x 3 min @ HR 165-175bpm (Zone 4-5, ~85% max), 2 min easy
"""
        counts = count_working_sets_per_workout(plan)
        self.assertEqual(counts.get("Workout 1: PULL"), 3)
        self.assertNotIn("Cardio 1: Intervals", counts)

    def test_deep_heading_h4_does_not_reset_scope(self):
        """#### level headings (h4) also must not reset workout scope."""
        plan = """# Workout plan — 2026-01-15

## Workout B: LEGS
- Barbell Back Squat: 80kgx5 /// 80kgx5

#### Finishers
- Romanian Deadlift: 70kgx10 /// 70kgx10 /// 70kgx10

"""
        counts = count_working_sets_per_workout(plan)
        # 2 squat + 3 rdl = 5
        self.assertEqual(counts.get("Workout B: LEGS"), 5)


# ---------------------------------------------------------------------------
# E15: Freshness hero renders blank big-number when TSB is None
# ---------------------------------------------------------------------------

from workout_coach.lib.render_cards_today import card_hero


class E15FreshnessHeroTsbNoneTests(unittest.TestCase):
    """E15: card_hero must show a placeholder when tsb is None."""

    def test_card_hero_tsb_none_shows_placeholder_not_blank(self):
        """card_hero with tsb=None must NOT render an empty <div class="value">."""
        html = card_hero(
            score=None,
            score_cls="muted",
            confidence=None,
            tsb=None,
            tsb_cls="muted",
            tsb_label="—",
            ctl=None,
            atl=None,
            tsb_trend=None,
        )
        # The freshness value div must not be a bare empty string
        self.assertNotIn('<div class="value"></div>', html)
        # It should contain a visible placeholder
        self.assertIn("—", html)

    def test_card_hero_tsb_with_value_still_renders_number(self):
        """card_hero with a real tsb value still renders the signed number."""
        html = card_hero(
            score=7.0,
            score_cls="good",
            confidence="high",
            tsb=3.5,
            tsb_cls="good",
            tsb_label="Balanced",
            ctl=50.0,
            atl=45.0,
            tsb_trend=0.2,
        )
        self.assertIn("+3.5", html)


# ---------------------------------------------------------------------------
# E16: NEAT card renders half-empty on empty/all-zero window
# ---------------------------------------------------------------------------

from workout_coach.lib.render_cards_today import card_neat


class E16NeatCardEmptyWindowTests(unittest.TestCase):
    """E16: card_neat must return '' (not a half-empty card) when all activity
    fields are zero or missing."""

    def test_card_neat_all_zeros_returns_empty(self):
        """All-zero activity data must produce an empty string (no card)."""
        activity = {
            "exercise_min_daily_avg": 0,
            "walking_minutes_28d": 0,
            "walking_distance_km_28d": 0,
        }
        result = card_neat(activity)
        self.assertEqual(result, "")

    def test_card_neat_none_fields_returns_empty(self):
        """None fields with no assessment must produce an empty string."""
        activity = {
            "exercise_min_daily_avg": None,
            "walking_minutes_28d": None,
            "walking_distance_km_28d": None,
        }
        result = card_neat(activity)
        self.assertEqual(result, "")

    def test_card_neat_no_assessment_with_zero_avg_returns_empty(self):
        """No assessment key AND zero exercise avg must produce an empty string."""
        activity = {
            "exercise_min_daily_avg": 0,
        }
        result = card_neat(activity)
        self.assertEqual(result, "")

    def test_card_neat_with_real_data_still_renders(self):
        """card_neat with actual non-zero data must still render a card."""
        activity = {
            "exercise_min_daily_avg": 32.5,
            "walking_minutes_28d": 1400,
            "walking_distance_km_28d": 70,
            "assessment": "moderate",
        }
        result = card_neat(activity)
        self.assertIn("NEAT", result)
        self.assertIn("32", result)


# ---------------------------------------------------------------------------
# E20: freshness_scale colors TSB = -5.0 in the wrong band
# ---------------------------------------------------------------------------

from workout_coach.lib.render_components_recovery import freshness_scale


class E20FreshnessScaleBoundaryTests(unittest.TestCase):
    """E20: TSB = -5.0 should be in the 'good' (green/amber) band, not warn."""

    def test_tsb_exactly_minus_5_is_good_marker(self):
        """TSB = -5.0 is the 'balanced' boundary and must get marker class 'good'."""
        html = freshness_scale(-5.0)
        # The marker SVG circle should have class 'good'
        self.assertIn('class="fresh-marker good"', html)

    def test_tsb_just_below_minus_5_is_amber(self):
        """TSB = -5.1 crosses into 'carrying load' territory -> 'amber'."""
        html = freshness_scale(-5.1)
        self.assertIn('class="fresh-marker amber"', html)

    def test_tsb_zero_is_good(self):
        """TSB = 0.0 is balanced and stays 'good'."""
        html = freshness_scale(0.0)
        self.assertIn('class="fresh-marker good"', html)

    def test_tsb_minus_10_is_warn(self):
        """TSB = -10.0 is fatigued -> 'warn'."""
        html = freshness_scale(-10.0)
        self.assertIn('class="fresh-marker warn"', html)


if __name__ == "__main__":
    unittest.main()
