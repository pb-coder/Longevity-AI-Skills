from __future__ import annotations

import unittest
from unittest.mock import patch


from workout_coach.lib import render_validators
from workout_coach.lib.render_validators import (
    COACH_STRING_MAX,
    auto_wrap_terms,
    core_week_errors,
    count_working_sets_per_workout,
    muscle_floor_errors,
    muscle_floors,
    validate_coach_reads,
    validate_workout_md,
    workout_arm_dose_warnings,
    workout_core_warnings,
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

_PLAN_CORE_COMPLIANT = """# Workout plan — 2026-06-14

## Workout 1: UPPER PUSH + CORE
- Jumping Jacks: 50
- Arm Circles: 20
- Dumbbell Flat Bench Press: 28kgx5 (warmup) /// 40kgx3 (warmup) /// 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10
- Shoulder Press Machine: 45kgx8-10 /// 45kgx8-10 /// 45kgx8-10
  — leave 1-2 in tank
- Dumbbell Fly: 18kgx10 /// 18kgx10 /// 18kgx10
- Cable Lateral Raise: 15kgx10 /// 15kgx10 /// 15kgx10
- Kneeling Cable Crunch: 20kgx12-15 /// 20kgx12-15
- Cable Overhead Tricep Extension: 35kgx8-10 /// 35kgx8-10 /// 35kgx8-10
"""

_PLAN_NO_CORE = """# Workout plan — 2026-06-14

## Workout 1: LEGS
- Jumping Jacks: 50
- Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8
- Leg Press: 120kgx10 /// 120kgx10
"""

_PLAN_CORE_LAST = """# Workout plan — 2026-06-14

## Workout 1: PUSH
- Jumping Jacks: 50
- Dumbbell Flat Bench Press: 52kgx8 /// 52kgx8 /// 52kgx8
- Cable Lateral Raise: 14kgx10 /// 14kgx10
- Kneeling Cable Crunch: 20kgx12 /// 20kgx12
"""

_PLAN_CORE_OVER_ALLOCATED = """# Workout plan — 2026-06-14

## Workout 1: PUSH
- Jumping Jacks: 50
- Dumbbell Flat Bench Press: 52kgx8 /// 52kgx8 /// 52kgx8
- Kneeling Cable Crunch: 20kgx12 /// 20kgx12 /// 20kgx12 /// 20kgx12
- Cable Lateral Raise: 14kgx10 /// 14kgx10
"""

_PLAN_CORE_OPTIONAL_QUALIFIER = """# Workout plan — 2026-06-14

## Workout 1: PUSH
- Jumping Jacks: 50
- Dumbbell Flat Bench Press: 52kgx8 /// 52kgx8 /// 52kgx8
- Kneeling Cable Crunch: 20kgx12 /// 20kgx12 (if you can make it)
- Cable Lateral Raise: 14kgx10 /// 14kgx10
"""

_PLAN_CORE_NO_FLEXION = """# Workout plan — 2026-06-14

## Workout 1: PULL
- Jumping Jacks: 50
- Cable Lat Pulldown: 65kgx8 /// 65kgx8 /// 65kgx8
- Cable Pallof Press: 15kgx10 /// 15kgx10
- Cable Face Pull: 20kgx15 /// 20kgx15
"""

_PLAN_ARM_NONE = """# Workout plan — 2026-06-14

## Workout 1: PUSH
- Jumping Jacks: 50
- Dumbbell Flat Bench Press: 52kgx8 /// 52kgx8 /// 52kgx8
- Shoulder Press Machine: 60kgx8 /// 60kgx8
"""

_PLAN_ARM_DOSE_MET = """# Workout plan — 2026-06-14

## Workout 1: PUSH
- Jumping Jacks: 50
- Dumbbell Flat Bench Press: 52kgx8 /// 52kgx8 /// 52kgx8
- Cable Overhead Tricep Extension: 20kgx10 /// 20kgx10 /// 20kgx10
- Cable Tricep Pushdown: 25kgx10 /// 25kgx10 /// 25kgx10
- Shoulder Press Machine: 60kgx8 /// 60kgx8

## Workout 2: PULL
- Cable Lat Pulldown: 65kgx8 /// 65kgx8 /// 65kgx8
- Incline Dumbbell Curl: 14kgx10 /// 14kgx10 /// 14kgx10
- Bayesian Cable Curl: 12kgx10 /// 12kgx10 /// 12kgx10
- Cable Face Pull: 20kgx15 /// 20kgx15
"""

def _tiers(**tiers: str) -> dict:
    """A payload carrying only ``muscle_volume_targets``: muscle -> tier."""
    return {"muscle_volume_targets": {m: {"tier": t}
                                      for m, t in tiers.items()}}


_PLAN_ARM_CURL_LAST = """# Workout plan — 2026-06-14

## Workout 1: PULL
- Jumping Jacks: 50
- Cable Lat Pulldown: 65kgx8 /// 65kgx8 /// 65kgx8
- Cable Face Pull: 20kgx15 /// 20kgx15
- Incline Dumbbell Curl: 14kgx10 /// 14kgx10 /// 14kgx10
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
        # Pinned string updated 2026-08-02: the counter now says
        # "rationale sub-bullets", because it counts only those. All three
        # sub-bullets here ARE rationale (none is an anchor-change
        # line), so the COUNT is unchanged at 3 and
        # this test still measures what it always measured.
        self.assertTrue(any("3 rationale sub-bullets" in w for w in warnings))
        self.assertTrue(any("comparative-history" in w for w in warnings))

    def test_core_warnings_silent_on_compliant_workout(self) -> None:
        # The SKILL.md worked example (fixed by Task D): core sits
        # inside the isolation block, 2 sets, a flexion
        # movement, not the final bullet, no optional qualifier.
        self.assertEqual(workout_core_warnings(_PLAN_CORE_COMPLIANT), [])

    def test_core_warnings_flags_zero_core_bullets(self) -> None:
        warns = workout_core_warnings(_PLAN_NO_CORE)
        self.assertTrue(any(
            "Workout 1: LEGS" in w and "no core exercise" in w for w in warns))

    def test_core_warnings_flags_core_as_last_bullet(self) -> None:
        # The known-bad shape: C-04 measured this in 24/24 real plans.
        warns = workout_core_warnings(_PLAN_CORE_LAST)
        self.assertTrue(any(
            "core is the last bullet" in w and "isolation block" in w
            for w in warns))

    def test_core_warnings_flags_over_allocated_sets(self) -> None:
        warns = workout_core_warnings(_PLAN_CORE_OVER_ALLOCATED)
        self.assertTrue(any(
            "4 core sets" in w and "over-allocated" in w for w in warns))
        # Core isn't the last bullet here, so warning (2) must not fire.
        self.assertFalse(any("last bullet" in w for w in warns))

    def test_core_warnings_flags_optional_qualifier(self) -> None:
        warns = workout_core_warnings(_PLAN_CORE_OPTIONAL_QUALIFIER)
        self.assertTrue(any(
            "Kneeling Cable Crunch" in w and "optional" in w for w in warns))

    def test_flexion_is_a_weekly_requirement_not_a_per_session_one(self) -> None:
        # REPLACES test_core_warnings_flags_zero_flexion_movement.
        #
        # A session whose only core movement is anti-rotation (Cable
        # Pallof Press is CORE > Anti-Rotation) used to be flagged. It is
        # not any more, and that is the point of W4: requiring flexion in
        # EVERY session is the rule that produced 94% flexion over six
        # months. See `workout_core_warnings`' docstring for the
        # arithmetic. Flexion is now required once per WEEK, and more
        # strictly — it must carry an external load.
        self.assertEqual(
            [w for w in workout_core_warnings(_PLAN_CORE_NO_FLEXION)
             if "flexion" in w],
            [])
        week = _PLAN_CORE_NO_FLEXION + """
## Workout 2: LOWER
- Barbell Back Squat: 90kgx8 /// 90kgx8
- Cable Pallof Press: 15kgx10 /// 15kgx10 /// 15kgx10 /// 15kgx10
- Leg Press: 120kgx10 /// 120kgx10
"""
        self.assertTrue(any("loaded flexion" in e
                            for e in core_week_errors(week)))

    def test_core_warnings_does_not_hardcode_exercise_names(self) -> None:
        # Regression guard for the audit's hard constraint: the core
        # movement set and the flexion subset must come from the catalog
        # parser, never a literal list living in this module.
        import inspect
        src = inspect.getsource(render_validators)
        for catalog_name in ("Kneeling Cable Crunch", "Leg Raise",
                              "Cable Pallof Press", "Plank", "Dead Bug"):
            self.assertNotIn(catalog_name, src)

    def test_zero_direct_arm_sets_trip_the_per_muscle_floor(self) -> None:
        # The arm volume floor is two rows of the per-muscle floor now;
        # `workout_arm_dose_warnings` keeps placement and diversity.
        errors = muscle_floor_errors(_PLAN_ARM_NONE, _tiers(
            biceps="maintain", triceps="emphasis"))
        self.assertTrue(any("0 direct biceps sets" in e and "floor is 5" in e
                            for e in errors), errors)
        self.assertTrue(any("0 direct triceps sets" in e and "floor is 6" in e
                            for e in errors), errors)
        self.assertEqual(workout_arm_dose_warnings(_PLAN_ARM_NONE), [])

    def test_arm_dose_warnings_silent_when_weekly_floor_met(self) -> None:
        # 6 direct biceps sets (Incline Dumbbell Curl + Bayesian Cable
        # Curl) and 6 direct triceps sets (Cable Overhead Tricep
        # Extension + Cable Tricep Pushdown) summed ACROSS both
        # workouts meets a maintain floor (5 and 4) and the diversity
        # axis; nothing fires. The compounds (bench, lat pulldown)
        # contribute synergist credit only and must not be counted.
        self.assertEqual(workout_arm_dose_warnings(_PLAN_ARM_DOSE_MET), [])
        self.assertEqual(muscle_floor_errors(_PLAN_ARM_DOSE_MET, _tiers(
            biceps="maintain", triceps="maintain")), [])

    def test_arm_dose_warnings_flags_curl_as_last_bullet(self) -> None:
        warns = workout_arm_dose_warnings(_PLAN_ARM_CURL_LAST)
        self.assertTrue(any(
            "biceps is the last bullet" in w and "isolation block" in w
            for w in warns))

    def test_arm_dose_warnings_fail_open_when_catalog_unresolved(self) -> None:
        # A validator that cannot identify any biceps/triceps exercise
        # must not flag every workout as arm-deficient.
        with patch.object(
            render_validators, "_primary_muscle_by_exercise",
            return_value={},
        ):
            self.assertEqual(workout_arm_dose_warnings(_PLAN_ARM_NONE), [])
            self.assertEqual(muscle_floor_errors(
                _PLAN_ARM_NONE, _tiers(biceps="emphasis")), [])

    def test_arm_dose_warnings_does_not_hardcode_exercise_names(self) -> None:
        # Same regression guard as core: the biceps/triceps name sets must
        # come from the catalog parser, never a literal list in this module.
        import inspect
        src = inspect.getsource(render_validators)
        for catalog_name in ("Incline Dumbbell Curl", "Bayesian Cable Curl",
                              "Cable Overhead Tricep Extension",
                              "Cable Tricep Pushdown"):
            self.assertNotIn(catalog_name, src)

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


class ExternalLoadFlagTests(unittest.TestCase):
    """``bullet["loaded"]`` means an EXTERNAL kg load and nothing else.

    `_WORKOUT_EXTERNAL_LOAD_RE` is deliberately narrower than
    `_WORKOUT_LOADED_RE`: the wider pattern also accepts a bare
    digit-x-digit rep token, which says nothing about load. That one
    regex is the only thing keeping a bodyweight crunch out of the core
    spec's loaded-flexion axis, and until now nothing tested it —
    widening it to the rep-x-load form left the whole suite green while
    letting `Crunch: 3x15` count as progressively loadable work.
    """

    def _loaded(self, bullet: str) -> bool:
        text = f"## Workout 1: PUSH\n- {bullet}\n"
        bullets = render_validators._iter_workout_exercise_bullets(text)
        return bullets["Workout 1: PUSH"][0]["loaded"]

    def test_a_kg_load_is_loaded(self) -> None:
        for body in ("Ab Crunch Machine: 30kgx12 /// 30kgx12",
                     "Kneeling Cable Crunch: 20 kg x 12",
                     "Suitcase Carry: 24kgx30m"):
            with self.subTest(body=body):
                self.assertTrue(self._loaded(body))

    def test_a_rep_by_rep_token_is_not_a_load(self) -> None:
        # THE case. `3x15` is sets-by-reps, not kilograms. If this ever
        # reads as loaded, a bodyweight crunch satisfies the core spec's
        # loaded-flexion requirement and the only progressively-loadable
        # pattern quietly leaves the week.
        for body in ("Crunch: 3x15 /// 3x15",
                     "Hanging Leg Raise: 3 x 12",
                     "Plank: 45s /// 45s",
                     "Bird Dog: 12 /// 12"):
            with self.subTest(body=body):
                self.assertFalse(self._loaded(body))

    def test_a_bodyweight_flexion_week_written_in_reps_still_fails(self) -> None:
        # The same defect at the axis it protects, so this survives a
        # refactor that moves the regex.
        plan = """# Workout plan — 2026-08-02

## Workout 1: LOWER A + CORE
- Barbell Back Squat: 90kgx8 /// 90kgx8
- Crunch: 3x15 /// 3x15
- Plank: 45s /// 45s
- Calf Raise Machine: 55kgx12 /// 55kgx12

## Workout 2: UPPER A + CORE
- Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8
- Crunch: 3x15 /// 3x15
- Cable Lateral Raise: 14kgx10 /// 14kgx10
"""
        self.assertTrue(any("loaded flexion" in e
                            for e in core_week_errors(plan)),
                        core_week_errors(plan))


# A week with one clean answer per muscle: 6 side delt sets, 0 rear delt,
# 0 trap, a back extension and a wrist-free grip week, and two front raises.
_PLAN_FLOOR_WEEK = """# Workout plan — 2026-10-14

## Workout 1: UPPER A
- Jumping Jacks: 50
- Cable Lateral Raise: 14kgx10 /// 14kgx10 /// 14kgx10
- Cable Front Raise: 10kgx10 /// 10kgx10
- Cable Lat Pulldown: 65kgx8 /// 65kgx8

## Workout 2: UPPER B
- Dumbbell Lateral Raise: 8kgx12 /// 8kgx12 /// 8kgx12
"""


class MuscleFloorTests(unittest.TestCase):
    """One weekly direct-set floor for every muscle."""

    def test_floor_is_mv_in_direct_sets_and_mev_for_emphasis(self) -> None:
        floors = muscle_floors({
            "rear_delts": "grow", "biceps": "emphasis", "triceps": "emphasis",
            "calves": "maintain", "traps": "maintain", "chest": "emphasis",
            "back": "grow",
        })
        # Direct units, not the payload's fractional target_sets: biceps
        # emphasis is 15 fractional and 8 direct (its MEV; mid-MAV is 12).
        self.assertEqual(floors, {"rear_delts": 6, "biceps": 8, "triceps": 6,
                                  "calves": 6, "traps": 2, "chest": 8,
                                  "back": 6})

    def test_the_same_muscle_is_lower_off_emphasis(self) -> None:
        self.assertEqual(muscle_floors({"chest": "emphasis"}), {"chest": 8})
        self.assertEqual(muscle_floors({"chest": "grow"}), {"chest": 3})
        self.assertEqual(muscle_floors({"chest": "maintain"}), {"chest": 3})

    def test_a_muscle_with_no_floor_is_absent_not_zero(self) -> None:
        # Core keeps core_week_spec (12 sets on a two-and-two week, above
        # its generic MEV of 4); erectors and forearms have no measured
        # direct supply; the rest have an MV of 0 or no direct exercise.
        floors = muscle_floors({
            "core": "emphasis", "erectors": "emphasis",
            "forearms": "emphasis", "glutes": "grow", "front_delts": "grow",
            "adductors": "maintain", "neck": "maintain",
            "external_rotators": "emphasis",
        })
        self.assertEqual(floors, {})

    def test_the_constants_function_is_the_one_the_validator_calls(self) -> None:
        from workout_coach.lib import constants
        tiers = {"biceps": "emphasis", "external_rotators": "emphasis"}
        # Without the catalog the unservable muscle is not filtered out...
        self.assertEqual(constants.muscle_floors(tiers),
                         {"biceps": 8, "external_rotators": 2})
        # ...the validator's wrapper adds only that filter.
        self.assertEqual(muscle_floors(tiers), {"biceps": 8})
        self.assertEqual(
            muscle_floors(tiers),
            constants.muscle_floors(
                tiers,
                servable=set(
                    render_validators._primary_muscle_by_exercise().values())))

    def test_a_payload_floor_key_cannot_move_the_bar(self) -> None:
        payload = _tiers(rear_delts="grow")
        payload["muscle_floors"] = {"rear_delts": 0}
        self.assertTrue(muscle_floor_errors(_PLAN_FLOOR_WEEK, payload))

    def test_zero_floors_never_fire(self) -> None:
        # Glutes, front delts, adductors and neck have MV 0; external
        # rotators has no primary catalog entry at all.
        tiers = _tiers(glutes="grow", front_delts="maintain",
                       adductors="maintain", neck="maintain",
                       external_rotators="emphasis")
        self.assertEqual(muscle_floor_errors(_PLAN_FLOOR_WEEK, tiers), [])

    def test_erectors_and_forearms_are_exempt(self) -> None:
        self.assertEqual(muscle_floor_errors(
            _PLAN_FLOOR_WEEK, _tiers(erectors="emphasis",
                                     forearms="emphasis")), [])

    def test_core_is_governed_by_the_core_spec_not_the_muscle_floor(self) -> None:
        # _PLAN_FLOOR_WEEK has no core work; the per-muscle floor is silent
        # about it and `core_week_errors` is where core is judged.
        self.assertEqual(muscle_floor_errors(
            _PLAN_FLOOR_WEEK, _tiers(core="emphasis")), [])

    def test_the_message_names_muscle_sets_and_floor(self) -> None:
        errors = muscle_floor_errors(
            _PLAN_FLOOR_WEEK, _tiers(rear_delts="grow", traps="maintain",
                                     side_delts="grow"))
        self.assertEqual(len(errors), 2, errors)
        self.assertIn("Week: 0 direct rear_delts sets across the plan — "
                      "floor is 6 (grow tier;", errors[0])
        self.assertIn("0 direct traps sets", errors[1])
        # 6 side delt sets meet the MV floor of 6, and the lat pulldown's
        # rear-delt synergist credit is not a direct set.
        self.assertFalse(any("side_delts" in e for e in errors))

    def test_front_raises_credit_front_delts_and_not_side_delts(self) -> None:
        sets = render_validators._direct_sets_by_muscle(_PLAN_FLOOR_WEEK)
        self.assertEqual(dict(sets["front_delts"]), {"cable front raise": 2})
        self.assertEqual(sum(sets["side_delts"].values()), 6)

    def test_only_listed_muscles_are_judged(self) -> None:
        self.assertEqual(muscle_floor_errors(_PLAN_FLOOR_WEEK, _tiers()), [])
        self.assertEqual(muscle_floor_errors(_PLAN_FLOOR_WEEK, None), [])

    def test_a_document_with_no_workout_is_not_a_violation(self) -> None:
        self.assertEqual(muscle_floor_errors(
            "# Notes\n\nNo plan here.\n", _tiers(traps="maintain")), [])

    def test_a_deload_demotes_the_floor_and_names_why(self) -> None:
        from workout_coach.lib.render_validators import validate_workout_plan
        payload = _tiers(rear_delts="grow")
        errors, _ = validate_workout_plan(_PLAN_FLOOR_WEEK, payload=payload)
        self.assertTrue(any("rear_delts sets" in e for e in errors))
        errors, warnings = validate_workout_plan(
            _PLAN_FLOOR_WEEK, payload=payload, deload_week=True)
        self.assertFalse(any("rear_delts sets" in e for e in errors))
        self.assertTrue(any("rear_delts sets" in w
                            and "[advisory: deload week]" in w
                            for w in warnings))

    def test_a_payload_with_no_targets_says_the_floor_did_not_run(self) -> None:
        from workout_coach.lib.render_validators import validate_workout_plan
        _, warnings = validate_workout_plan(_PLAN_FLOOR_WEEK, payload={})
        self.assertTrue(any("per-muscle weekly floor was not checked" in w
                            for w in warnings))
        _, warnings = validate_workout_plan(_PLAN_FLOOR_WEEK)
        self.assertFalse(any("not checked" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
