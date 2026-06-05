from __future__ import annotations

import unittest
from unittest.mock import patch


from workout_coach.lib import render_validators
from workout_coach.lib.render_validators import (
    COACH_STRING_MAX,
    auto_wrap_terms,
    validate_coach_reads,
    validate_workout_md,
)


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
