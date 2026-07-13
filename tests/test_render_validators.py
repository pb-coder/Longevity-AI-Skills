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

    def test_working_set_count_includes_bodyweight_multiset(self) -> None:
        # Bodyweight working exercises carry no `kg`/`x` but ARE working
        # sets when written as `///`-separated reps. The old counter scored
        # these zero and silently shrank the budget.
        plan = """# Workout plan — 2026-06-21

## Workout 1: PUSH
- Jumping Jacks: 50
- Dip: 8-10 /// 8-10 /// 8-10
- Captain's Chair Knee Raise: 12 /// 12 /// 12
- Dumbbell Shoulder Press: 22kgx8 /// 22kgx8 /// 22kgx8
"""
        counts = count_working_sets_per_workout(plan)
        # 3 dips + 3 knee raises + 3 presses = 9; Jumping Jacks prep = 0.
        self.assertEqual(counts["Workout 1: PUSH"], 9)

    def test_cardio_section_does_not_leak_into_workout_count(self) -> None:
        # A `## Cardio` heading must reset the active workout title so its
        # bullets (which contain words like "max"/"VO2max") never add to a
        # workout's set count.
        plan = """# Workout plan — 2026-06-21

## Workout 1: PULL
- Cable Lat Pulldown: 65kgx8 /// 65kgx8 /// 65kgx8

## Cardio 1: Intervals (20 min total)
- Work: 5 x 3 min @ HR 165-175bpm (Zone 4-5, ~85% max), 2 min easy
- Notes: builds VO2max, not within 24h of heavy legs
"""
        counts = count_working_sets_per_workout(plan)
        self.assertEqual(counts.get("Workout 1: PULL"), 3)
        self.assertNotIn("Cardio 1: Intervals (20 min total)", counts)

    def test_set_budget_passes_on_target(self) -> None:
        self.assertEqual(workout_set_budget_warnings(_PLAN_17, 17), [])

    def test_set_budget_flags_short_session(self) -> None:
        warns = workout_set_budget_warnings(_PLAN_SHORT, 17)
        self.assertTrue(any("under" in w and "Workout 1" in w for w in warns))

    def test_set_budget_silent_when_no_target(self) -> None:
        self.assertEqual(workout_set_budget_warnings(_PLAN_SHORT, None), [])

    def test_set_budget_per_workout_downgrade_does_not_flag_full_later_sessions(self) -> None:
        # Tier C downgrade: workouts 1-2 trimmed (budget 13), 3-4 full
        # (budget 22). A correct plan [13, 12, 22, 20] must produce NO
        # warnings. The old global-scale-to-13 wrongly flagged W3/W4 as over.
        def wk(title, n):
            sets = " /// ".join(["60kgx8"] * n)
            return f"## Workout {title}\n- Cable Lat Pulldown: {sets}\n"

        plan = "# Workout plan — 2026-06-21\n\n" + wk("1: PULL", 13) + wk(
            "2: LEGS", 12) + wk("3: PUSH", 22) + wk("4: PULL", 20)

        def budget_for(idx):  # base 22, first 2 downgraded to round(22*0.6)=13
            return 13 if idx < 2 else 22

        self.assertEqual(
            workout_set_budget_warnings(plan, 22, budget_by_index=budget_for), [])
        # The old global scale (everything judged at 13) flags W3/W4 as over.
        self.assertTrue(
            any("over" in w for w in workout_set_budget_warnings(plan, 13)))

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

    def test_workout_md_flags_strength_sets_when_gate_says_zone_2(self) -> None:
        errors, _ = validate_workout_md(
            _PLAN_17, {"substitute": {"kind": "zone_2"}})
        self.assertTrue(
            any("zone_2" in e and "gate" in e for e in errors))

    def test_workout_md_flags_strength_sets_when_gate_says_rest(self) -> None:
        errors, _ = validate_workout_md(
            _PLAN_17, {"substitute": {"kind": "rest"}})
        self.assertTrue(any("rest" in e and "gate" in e for e in errors))

    def test_workout_md_allows_strength_sets_on_reactive_deload_week(self) -> None:
        # Tier B reactive_deload_week legitimately prescribes reduced-volume
        # strength, so it must NOT be flagged even though it is a no-strength
        # look-alike tier.
        errors, _ = validate_workout_md(
            _PLAN_17, {"substitute": {"kind": "reactive_deload_week"}})
        self.assertFalse(any("gate" in e for e in errors))

    def test_workout_md_allows_strength_sets_on_normal_strength(self) -> None:
        errors, _ = validate_workout_md(
            _PLAN_17, {"substitute": {"kind": "normal_strength"}})
        self.assertFalse(any("gate" in e for e in errors))

    def test_workout_md_zone_2_gate_does_not_flag_cardio_only_plan(self) -> None:
        # A zone_2 gate paired with a markdown that only has cardio (no
        # kg/reps load, no ///) must not be flagged; there are no strength
        # working sets to honor the gate against.
        plan = """# Workout plan — 2026-06-14

## Workout 1: CARDIO
- Rowing Machine: 45 min
"""
        errors, _ = validate_workout_md(plan, {"substitute": {"kind": "zone_2"}})
        self.assertFalse(any("gate" in e for e in errors))

    def test_workout_md_backward_compat_no_session_recommendation_arg(self) -> None:
        # Existing callers that don't pass session_recommendation must see
        # identical behavior to before this check was added.
        errors, warnings = validate_workout_md(_PLAN_17)
        self.assertFalse(any("gate" in e for e in errors))

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
