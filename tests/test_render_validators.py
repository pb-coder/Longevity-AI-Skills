from __future__ import annotations

import unittest
from unittest.mock import patch


from workout_coach.lib import render_validators
from workout_coach.lib.render_validators import (
    COACH_STRING_MAX,
    auto_wrap_terms,
    count_working_sets_per_workout,
    validate_coach_reads,
    validate_workout_md,
    workout_set_budget_warnings,
)

_PLAN_17 = """# Workout plan — 2026-06-14

## Workout 1: PUSH
- Jumping Jacks: 50
- Dumbbell Flat Bench Press: 28kgx5 (warmup) /// 40kgx3 (warmup) /// 52kgx8 /// 52kgx8 /// 52kgx8 /// 52kgx8
- Incline Chest Press Machine: 60kgx8 /// 60kgx8 /// 60kgx8
- Shoulder Press Machine: 60kgx8 /// 60kgx8 /// 60kgx8
- Cable Lateral Raise: 14kgx10 /// 14kgx10 /// 14kgx10
- Cable Overhead Tricep Extension: 19kgx8 /// 19kgx8
- Chest Press Machine: 60kgx8 /// 60kgx8
"""

_PLAN_SHORT = """# Workout plan — 2026-06-14

## Workout 1: PUSH
- Jumping Jacks: 50
- Dumbbell Flat Bench Press: 52kgx8 /// 52kgx8 /// 52kgx8
- Shoulder Press Machine: 60kgx8 /// 60kgx8
- Cable Overhead Tricep Extension: 19kgx8 /// 19kgx8
"""


class RenderValidatorTests(unittest.TestCase):
    def test_rejects_em_dash_in_headline_and_cards(self) -> None:
        errors, _ = validate_coach_reads({
            "headline": "Train — but gently",
            "cards": {"strength": "Good — enough"},
        })
        self.assertTrue(any("headline" in e and "em-dash" in e for e in errors))
        self.assertTrue(any("cards.strength" in e and "em-dash" in e for e in errors))

    def test_rejects_overlong_card_text(self) -> None:
        errors, _ = validate_coach_reads({
            "headline": "Valid",
            "cards": {"strength": "x" * (COACH_STRING_MAX + 1)},
        })
        self.assertTrue(any("cards.strength" in e and "max" in e for e in errors))

    def test_missing_required_callouts_are_warnings(self) -> None:
        errors, warnings = validate_coach_reads({"headline": "Valid", "cards": {}})
        self.assertEqual(errors, [])
        self.assertTrue(any("cards.strength missing" in w for w in warnings))

    def test_gated_cards_do_not_warn_when_missing(self) -> None:
        # recovery_practices renders an empty-state with no callout when there
        # is no thermal/light data, so a missing callout must not warn.
        _, warnings = validate_coach_reads({"headline": "Valid", "cards": {}})
        joined = "\n".join(warnings)
        for gated in ("recovery_practices", "swim_trajectory_callout",
                      "nutrition_phase_callout"):
            self.assertNotIn(gated, joined)

    def test_session_recommendation_callout_is_a_known_card(self) -> None:
        # Guards the doc/code drift that silently dropped today_headline.
        self.assertIn("session_recommendation_callout",
                      render_validators.COACH_CARD_KEYS)
        self.assertNotIn("today_headline", render_validators.COACH_CARD_KEYS)

    def test_working_set_count_excludes_warmup_and_prep(self) -> None:
        counts = count_working_sets_per_workout(_PLAN_17)
        # 4 bench + 3 incline + 3 shoulder + 3 lateral + 2 tricep + 2 chest = 17;
        # warmup ramp tokens and the Jumping Jacks prep line are excluded.
        self.assertEqual(counts["Workout 1: PUSH"], 17)

    def test_set_budget_passes_on_target(self) -> None:
        self.assertEqual(workout_set_budget_warnings(_PLAN_17, 17), [])

    def test_set_budget_flags_short_session(self) -> None:
        warns = workout_set_budget_warnings(_PLAN_SHORT, 17)
        self.assertTrue(any("under" in w and "Workout 1" in w for w in warns))

    def test_set_budget_silent_when_no_target(self) -> None:
        self.assertEqual(workout_set_budget_warnings(_PLAN_SHORT, None), [])

    def test_auto_wrap_terms_wraps_first_occurrence_only(self) -> None:
        wrapped = auto_wrap_terms("CTL is up; CTL matters.")
        self.assertEqual(wrapped.count('class="term"'), 1)
        self.assertIn("Chronic Training Load", wrapped)

    def test_workout_md_rejects_prose_em_dash(self) -> None:
        errors, _ = validate_workout_md("""# Workout plan — 2026-05-29

## Workout 1: PUSH
- Dumbbell Flat Bench Press: 30kgx8
> Why — too much prose
""")
        self.assertTrue(any("em-dash" in e for e in errors))

    def test_workout_md_allows_sub_bullet_marker_em_dash(self) -> None:
        errors, warnings = validate_workout_md("""# Workout plan — 2026-05-29

## Workout 1: PUSH
- Dumbbell Flat Bench Press: 30kgx8
  — keep shoulder blades set
""")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_workout_md_rejects_non_canonical_exercise(self) -> None:
        errors, _ = validate_workout_md("""# Workout plan — 2026-05-29

## Workout 1: LEGS
- Standing Calf Raise: 30kgx12
""")
        self.assertTrue(any("Standing Calf Raise" in e for e in errors))

    def test_workout_md_warns_on_sub_bullet_count_and_banned_phrases(self) -> None:
        errors, warnings = validate_workout_md("""# Workout plan — 2026-05-29

## Workout 1: LEGS
- Barbell Back Squat: 70kgx8
  — knees track over toes
- Romanian Deadlift: 80kgx8
  — last logged 15 weeks ago, start light
- Leg Press: 120kgx10
  — brace before the first rep
""")
        self.assertEqual(errors, [])
        self.assertTrue(any("3 sub-bullets" in w for w in warnings))
        self.assertTrue(any("comparative-history" in w for w in warnings))

    def test_workout_md_builds_exercise_catalog_once_per_validation(self) -> None:
        text = """# Workout plan — 2026-05-29

## Workout 1: PUSH
- Dumbbell Flat Bench Press: 30kgx8
- Dumbbell Flat Bench Press: 30kgx8
- Dumbbell Flat Bench Press: 30kgx8
"""
        with patch.object(
            render_validators,
            "_workout_exercise_name_set",
            return_value={"dumbbell flat bench press"},
        ) as names:
            errors, warnings = validate_workout_md(text)

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        names.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
