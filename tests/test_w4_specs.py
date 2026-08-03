"""W4 — distribution-shaped, blocking prescription targets.

Three groups, all guarding the same failure mode: **this coach optimises
precisely to whatever is measured and stops there.** A target with only a
quantity axis is always satisfiable by the cheapest legal item times N.

1. Time- and distance-denominated work counts as work. Before this, the
   documented hold format scored zero sets and the validator argued
   *against* the movements the core spec exists to introduce.
2. `core_week_spec` / `arm_week_spec` — quantity, diversity and identity
   axes, each machine-checkable, returned as blocking errors.
3. The landmark table's unit, and the emphasis / grow / maintain tiers.

The plan fixtures named ``_PLAN_DEGENERATE_*`` are the anti-gaming
exhibits: each is the cheapest plan that satisfies a spec, kept in the
suite so that weakening the spec later shows up as a test that starts
passing something it should not.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from workout_coach.lib import render_validators
from workout_coach.lib.constants import (
    ARM_WEEK_SPEC,
    BLOCK_EMPHASIS_DEFAULT,
    CORE_WEEK_SPEC,
    DEFAULT_PRIORITY_TIER,
    MUSCLE_PRIORITY_PROFILE_KEY,
    RP_DIRECT_SET_LANDMARKS,
    SYNERGIST_CREDIT_MEASUREMENT,
    SYNERGIST_CREDIT_OFFSET,
    VOLUME_LANDMARKS,
    muscle_priority_tiers,
    muscle_volume_targets,
)
from workout_coach.lib.render_validators import (
    MIN_CREDITED_CARRY_METRES,
    MIN_CREDITED_HOLD_SECONDS,
    arm_week_errors,
    core_week_errors,
    count_working_sets_per_workout,
    validate_workout_plan,
    workout_core_warnings,
)


def _workout(title: str, *bullets: str) -> str:
    return f"## Workout {title}\n" + "".join(f"- {b}\n" for b in bullets) + "\n"


_HEAD = "# Workout plan — 2026-08-02\n\n"


# The 2026-07-18 shape, reduced: one machine crunch, two sets, every
# session. Passed every validator the system had.
_PLAN_ONE_EXERCISE_EVERY_SESSION = _HEAD + "".join([
    _workout("1: LOWER A + CORE",
             "Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8",
             "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
             "Calf Raise Machine: 55kgx10-12 /// 55kgx10-12"),
    _workout("2: UPPER A + CORE",
             "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
             "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
             "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
    _workout("3: LOWER B + CORE",
             "Leg Press: 200kgx10 /// 200kgx10",
             "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
             "Hip Adductor Machine: 50kgx12 /// 50kgx12"),
    _workout("4: UPPER B + CORE",
             "Cable Lat Pulldown: 65kgx8 /// 65kgx8",
             "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
             "Rear Delt Fly Machine: 20kgx12 /// 20kgx12"),
])

# ANTI-GAMING EXHIBIT A. The cheapest week that satisfies every axis of
# `core_week_spec` **on the split D3 actually prescribes** — two lower
# days at 4 core sets and two upper days at 2, so 12 sets is the D3
# budget exactly, not a number this fixture chose.
#
# CORRECTED 2026-08-02. This comment used to claim 12 sets was the
# cheapest legal week full stop. It never was, and the gap was the
# exploit: `_PLAN_EXPLOIT_MINIMAL_FLEXION` below is 8 core sets and
# `_PLAN_CHEAPEST_LEGAL_CORE` still is, because a week naming every
# session as an upper day buys the 2-set budget four times over. The
# claim is now scoped to the split, and the unscoped claim is carried by
# `_PLAN_CHEAPEST_LEGAL_CORE` with a minimality proof rather than a
# comment.
#
# Training-acceptable at 12: 4 loaded flexion, 4 anti-extension, 2
# anti-rotation, 2 anti-lateral-flexion is a direct correction of the
# measured 94/0/0/1 distribution. If a future edit makes this plan
# illegal, the spec got stricter than intended.
_PLAN_DEGENERATE_CORE_LEGAL = _HEAD + "".join([
    _workout("1: LOWER A + CORE",
             "Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8",
             "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
             "Plank: 45s /// 45s",
             "Calf Raise Machine: 55kgx10-12 /// 55kgx10-12"),
    _workout("2: UPPER A + CORE",
             "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
             "Cable Pallof Press: 15kgx10 /// 15kgx10",
             "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
    _workout("3: LOWER B + CORE",
             "Leg Press: 200kgx10 /// 200kgx10",
             "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
             "Side Plank: 45s /// 45s",
             "Hip Adductor Machine: 50kgx12 /// 50kgx12"),
    _workout("4: UPPER B + CORE",
             "Cable Lat Pulldown: 65kgx8 /// 65kgx8",
             "Plank: 45s /// 45s",
             "Rear Delt Fly Machine: 20kgx12 /// 20kgx12"),
])

# ANTI-GAMING EXHIBIT B. Three distinct exercise NAMES, two of which are
# the same movement in two directions. Clears the diversity count and the
# frequency cap; the pattern-category axis is the only thing that stops it.
_PLAN_DEGENERATE_EQUIPMENT_FLAVOUR = _HEAD + "".join([
    _workout("1: LOWER A + CORE",
             "Barbell Back Squat: 90kgx8 /// 90kgx8",
             "Cable Woodchop (High to Low): 20kgx12 /// 20kgx12",
             "Cable Woodchop (Low to High): 20kgx12 /// 20kgx12",
             "Calf Raise Machine: 55kgx12 /// 55kgx12"),
    _workout("2: UPPER A + CORE",
             "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
             "Ab Crunch Machine: 30kgx12 /// 30kgx12",
             "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
    _workout("3: LOWER B + CORE",
             "Leg Press: 200kgx10 /// 200kgx10",
             "Cable Woodchop (High to Low): 20kgx12 /// 20kgx12",
             "Cable Woodchop (Low to High): 20kgx12 /// 20kgx12",
             "Hip Adductor Machine: 50kgx12 /// 50kgx12"),
    _workout("4: UPPER B + CORE",
             "Cable Lat Pulldown: 65kgx8 /// 65kgx8",
             "Ab Crunch Machine: 30kgx12 /// 30kgx12",
             "Rear Delt Fly Machine: 20kgx12 /// 20kgx12"),
])


class TimeAndDistanceWorkTests(unittest.TestCase):
    """`render_validators` used to accept only `kg`, digit-x-digit or
    `///` as evidence of work, so an isometric hold or a loaded carry
    scored zero sets."""

    def test_multi_set_hold_counts_one_set_per_token(self) -> None:
        plan = _HEAD + _workout("1: UPPER A", "Plank: 45s /// 45s /// 45s")
        self.assertEqual(count_working_sets_per_workout(plan)["Workout 1: UPPER A"], 3)

    def test_single_hold_bullet_counts_one_set(self) -> None:
        # The `Exercise: 45s hold` shape SKILL.md documents.
        plan = _HEAD + _workout("1: UPPER A", "Plank: 45s hold")
        self.assertEqual(count_working_sets_per_workout(plan)["Workout 1: UPPER A"], 1)

    def test_clock_and_spelled_out_seconds_count(self) -> None:
        plan = _HEAD + _workout(
            "1: UPPER A",
            "Plank: 0:45 /// 0:45",
            "Hollow Body Hold: 30 sec /// 30 seconds",
        )
        self.assertEqual(count_working_sets_per_workout(plan)["Workout 1: UPPER A"], 4)

    def test_carry_metres_count_as_sets(self) -> None:
        plan = _HEAD + _workout(
            "1: LOWER A", "Suitcase Carry: 24kgx30m /// 24kgx30m /// 24kgx30m")
        self.assertEqual(count_working_sets_per_workout(plan)["Workout 1: LOWER A"], 3)

    def test_minutes_are_not_metres(self) -> None:
        # `m` is metres on a carry, but must never swallow `min`. A prep
        # bullet stays prep; a cardio-style duration is not a working set.
        plan = _HEAD + _workout(
            "1: LOWER A", "Rowing Machine: 3 min", "Jumping Jacks: 50")
        self.assertEqual(count_working_sets_per_workout(plan)["Workout 1: LOWER A"], 0)

    def test_sub_floor_hold_is_not_a_working_set(self) -> None:
        # Accepting seconds without a floor hands the coach a new
        # degenerate solution: `4 x 5s` is a 4-set core budget met with
        # 20 seconds of work.
        secs = int(MIN_CREDITED_HOLD_SECONDS) - 5
        plan = _HEAD + _workout("1: UPPER A", f"Plank: {secs}s /// {secs}s")
        self.assertEqual(count_working_sets_per_workout(plan)["Workout 1: UPPER A"], 0)

    def test_sub_floor_carry_is_not_a_working_set(self) -> None:
        metres = int(MIN_CREDITED_CARRY_METRES) - 5
        plan = _HEAD + _workout(
            "1: LOWER A", f"Suitcase Carry: {metres}m /// {metres}m")
        self.assertEqual(count_working_sets_per_workout(plan)["Workout 1: LOWER A"], 0)

    def test_tempo_cue_does_not_delete_a_loaded_set(self) -> None:
        # `(3s pause)` riding on a loaded set must not drag it under the
        # hold floor. Load is checked before time, for exactly this.
        plan = _HEAD + _workout(
            "1: LOWER A", "Barbell Back Squat: 90kgx8 (3s pause) /// 90kgx8")
        self.assertEqual(count_working_sets_per_workout(plan)["Workout 1: LOWER A"], 2)

    def test_hold_bullet_no_longer_reports_a_false_under_allocation(self) -> None:
        # The regression this fixes: a correctly-written anti-extension
        # hold used to score 0 core sets and trip "under-allocated".
        plan = _HEAD + _workout(
            "1: UPPER A + CORE",
            "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
            "Kneeling Cable Crunch: 20kgx12 /// 20kgx12",
            "Plank: 45s /// 45s",
            "Cable Lateral Raise: 14kgx10 /// 14kgx10",
        )
        self.assertEqual(
            [w for w in workout_core_warnings(plan) if "under-allocated" in w], [])


# THE EXPLOIT, 2026-08-02. Eight core sets, ONE of them flexion (12.5%),
# 70 seconds of bodyweight holds, and before the fix: zero errors, exit
# 0, HTML written. Two holes, one plan.
#
#   * every session is named FULL BODY, which `session_type_from_title`
#     classifies as `full`, which used to take min(lower, upper) = 2 as
#     its core floor. The coach picked its own budget by picking a name.
#   * `min_loaded_flexion_exercises_per_week` counts EXERCISES, so the
#     single 1-set machine crunch satisfied the only flexion axis there
#     was. Flexion SET count was unmeasured, and §5.2 of the spec says
#     what happens to anything unmeasured.
#
# Kept as the acceptance case for both gates. It must never render.
_PLAN_EXPLOIT_MINIMAL_FLEXION = _HEAD + "".join([
    _workout("1: FULL BODY A",
             "Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8",
             "Plank: 10s /// 10s",
             "Incline Dumbbell Curl: 14kgx10 /// 14kgx10 /// 14kgx10",
             "Cable Tricep Pushdown: 25kgx10 /// 25kgx10 /// 25kgx10",
             "Calf Raise Machine: 55kgx12 /// 55kgx12"),
    _workout("2: FULL BODY B",
             "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
             "Ab Crunch Machine: 30kgx12",
             "Bird Dog: 10s",
             "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
    _workout("3: FULL BODY C",
             "Leg Press: 200kgx10 /// 200kgx10",
             "Side Plank: 10s /// 10s",
             "Bayesian Cable Curl: 14kgx10 /// 14kgx10 /// 14kgx10",
             "Cable Overhead Tricep Extension: 29kgx10 /// 29kgx10 /// 29kgx10",
             "Hip Adductor Machine: 50kgx12 /// 50kgx12"),
    _workout("4: FULL BODY D",
             "Cable Lat Pulldown: 65kgx8 /// 65kgx8",
             "Hollow Body Hold: 10s /// 10s",
             "Rear Delt Fly Machine: 20kgx12 /// 20kgx12"),
])

# ANTI-GAMING EXHIBIT D. The genuinely cheapest legal core week under the
# fixed rules, found by search rather than asserted: 8 core sets, because
# naming every session an UPPER day is the only way to buy the 2-set
# per-session floor four times, and 8 is then 4 x 2.
#
# Its composition is forced, not chosen. Four flexion sets, because
# ceil(8/3) = 3 is the floor and the per-session budget of 2 means
# flexion lands in whole sessions; three distinct movements across three
# categories, because 8 sets caps neither diversity axis; and the flexion
# movement is loaded, because a bodyweight one fails the identity axis.
# `MinimumLegalCorePlanTests` proves the minimality by perturbation:
# every single-set reduction and every flexion substitution makes it
# illegal.
#
# TRAINING-ACCEPTABLE, and this is the claim to argue with if you
# disagree with the spec. 8 fractional core sets/wk sits above RP's
# published core MEV of 4 direct sets. The split is 50% flexion / 25%
# anti-extension / 25% anti-rotation against a measured baseline of
# 94/0/0, the loaded machine crunch is progressible and therefore visible
# to `estimated_1rm` and `progression_summary`, and no movement carries a
# sub-2-set dose. What it is NOT is a balanced week overall: four upper
# days and no lower day. That is a legs problem, not a core problem, and
# no axis in `core_week_spec` is the right place to catch it.
_PLAN_CHEAPEST_LEGAL_CORE = _HEAD + "".join([
    _workout("1: UPPER A + CORE",
             "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
             "Ab Crunch Machine: 30kgx12 /// 30kgx12",
             "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
    _workout("2: UPPER B + CORE",
             "Cable Lat Pulldown: 65kgx8 /// 65kgx8",
             "Ab Crunch Machine: 30kgx12 /// 30kgx12",
             "Cable Face Pull: 20kgx15 /// 20kgx15"),
    _workout("3: UPPER C + CORE",
             "Shoulder Press Machine: 45kgx8 /// 45kgx8",
             "Plank: 45s /// 45s",
             "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
    _workout("4: UPPER D + CORE",
             "Chest Press Machine: 60kgx8 /// 60kgx8",
             "Cable Pallof Press: 15kgx10 /// 15kgx10",
             "Rear Delt Fly Machine: 20kgx12 /// 20kgx12"),
])


class CoreWeekSpecTests(unittest.TestCase):
    def test_one_exercise_every_session_fails_three_weekly_axes(self) -> None:
        errors = core_week_errors(_PLAN_ONE_EXERCISE_EVERY_SESSION)
        self.assertTrue(any("1 distinct core exercises" in e for e in errors))
        self.assertTrue(any("1 core pattern categories" in e for e in errors))
        self.assertTrue(any("appears in 4 sessions" in e for e in errors))
        self.assertGreaterEqual(len(errors), 3)

    def test_minimum_legal_week_passes_every_axis(self) -> None:
        self.assertEqual(core_week_errors(_PLAN_DEGENERATE_CORE_LEGAL), [])

    def test_equipment_flavour_rotation_fails_the_category_axis(self) -> None:
        # Two woodchop directions read as two distinct exercises and clear
        # the frequency cap. Only the pattern-category axis catches it.
        errors = core_week_errors(_PLAN_DEGENERATE_EQUIPMENT_FLAVOUR)
        self.assertTrue(any("core pattern categories" in e for e in errors))
        self.assertFalse(any("distinct core exercises" in e for e in errors))
        self.assertFalse(any("sessions per week" in e for e in errors))

    def test_named_but_zero_set_core_bullets_do_not_count(self) -> None:
        # Listing three movements at zero prescribed sets must not satisfy
        # the diversity axis. Naming is not prescribing.
        plan = _HEAD + _workout(
            "1: LOWER A + CORE",
            "Barbell Back Squat: 90kgx8 /// 90kgx8",
            "Plank: 5s",
            "Bird Dog: 10",
            "Side Plank: 5s",
            "Calf Raise Machine: 55kgx12 /// 55kgx12",
        )
        errors = core_week_errors(plan)
        self.assertTrue(any("0 distinct core exercises" in e for e in errors))

    def test_all_bodyweight_core_week_fails_the_loaded_flexion_axis(self) -> None:
        plan = _HEAD + "".join([
            _workout("1: LOWER A + CORE",
                     "Barbell Back Squat: 90kgx8 /// 90kgx8",
                     "Crunch: 15 /// 15",
                     "Plank: 45s /// 45s",
                     "Calf Raise Machine: 55kgx12 /// 55kgx12"),
            _workout("2: UPPER A + CORE",
                     "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
                     "Bird Dog: 12 /// 12",
                     "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
        ])
        errors = core_week_errors(plan)
        self.assertTrue(any("loaded flexion" in e for e in errors))

    def test_loaded_flexion_axis_is_satisfied_by_an_external_load(self) -> None:
        plan = _HEAD + "".join([
            _workout("1: LOWER A + CORE",
                     "Barbell Back Squat: 90kgx8 /// 90kgx8",
                     "Kneeling Cable Crunch: 20kgx12 /// 20kgx12",
                     "Plank: 45s /// 45s",
                     "Calf Raise Machine: 55kgx12 /// 55kgx12"),
            _workout("2: UPPER A + CORE",
                     "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
                     "Bird Dog: 12 /// 12",
                     "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
        ])
        self.assertEqual(
            [e for e in core_week_errors(plan) if "loaded flexion" in e], [])

    def test_two_handed_farmer_walk_does_not_satisfy_the_core_spec(self) -> None:
        # D4: the bilateral carry is a finisher budgeted OUTSIDE the core
        # allocation. The catalog files it under FULL BODY with no core
        # credit (the two loads cancel, 11-14% MVIC), so it must never
        # register as a core pattern category.
        #
        # Two sessions, not one, so the week carries 4 credited core sets.
        # The distinct-exercise floor is dose-aware — it caps at
        # `sets // MIN_SETS_PER_DISTINCT_EXERCISE` — and a single-session
        # fixture supplies only 2, which caps the requirement at 1 and
        # makes the axis silent for a reason that has nothing to do with
        # D4. Four sets caps it at 2, so the axis is live and the carry's
        # exclusion is what the assertion actually measures.
        plan = _HEAD + "".join([
            _workout("1: LOWER A + CORE",
                     "Barbell Back Squat: 90kgx8 /// 90kgx8",
                     "Ab Crunch Machine: 30kgx12 /// 30kgx12",
                     "Dumbbell Farmer Walk: 48kgx30m /// 48kgx30m"),
            _workout("2: UPPER A + CORE",
                     "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
                     "Ab Crunch Machine: 30kgx12 /// 30kgx12",
                     "Dumbbell Farmer Walk: 48kgx30m /// 48kgx30m"),
        ])
        errors = core_week_errors(plan)
        self.assertTrue(any("1 distinct core exercises" in e for e in errors),
                        errors)
        # The carry contributed neither a distinct exercise nor a category.
        self.assertTrue(any("1 core pattern categories (flexion)" in e
                            for e in errors), errors)

    def test_suitcase_carry_counts_as_core_anti_lateral_flexion(self) -> None:
        # D4's other half: the one-handed carry IS core (33.0% MVIC
        # contralateral external oblique) and satisfies a category.
        plan = _HEAD + "".join([
            _workout("1: LOWER A + CORE",
                     "Barbell Back Squat: 90kgx8 /// 90kgx8",
                     "Ab Crunch Machine: 30kgx12 /// 30kgx12",
                     "Suitcase Carry: 24kgx30m /// 24kgx30m",
                     "Calf Raise Machine: 55kgx12 /// 55kgx12"),
            _workout("2: UPPER A + CORE",
                     "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
                     "Cable Pallof Press: 15kgx10 /// 15kgx10",
                     "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
        ])
        self.assertEqual(
            [e for e in core_week_errors(plan) if "pattern categories" in e], [])

    def test_fails_open_when_the_catalog_resolves_no_core_movement(self) -> None:
        with patch.object(render_validators, "_core_pattern_categories",
                          return_value=(set(), {})):
            self.assertEqual(
                core_week_errors(_PLAN_ONE_EXERCISE_EVERY_SESSION), [])

    def test_silent_on_markdown_with_no_workout_block(self) -> None:
        self.assertEqual(core_week_errors("# Notes\n\nnothing here\n"), [])

    def test_flexion_category_key_resolves_against_the_catalog(self) -> None:
        # Drift guard: the spec names one category by string. If the
        # catalog's CORE subsection is renamed, the loaded-flexion axis
        # would silently stop firing.
        _, categories = render_validators._core_pattern_categories()
        self.assertIn(CORE_WEEK_SPEC["flexion_category"], categories)


class FlexionSetFloorTests(unittest.TestCase):
    """The flexion SET floor — `min_flexion_share_of_core_sets`.

    THE GAP, closed 2026-08-02. `min_loaded_flexion_exercises_per_week`
    counts EXERCISES, so one bullet carrying one set satisfied it in
    full, and flexion set count was left unmeasured when the build
    replaced a scalar core-set target with distribution-shaped ones.
    `_PLAN_EXPLOIT_MINIMAL_FLEXION` is what that bought: a week of 8
    core sets with a single flexion set, rendering at exit 0.

    The two axes are separate constraints and the exhibits prove it —
    a week can satisfy either one alone.
    """

    def _flexion_errors(self, plan: str) -> list[str]:
        return [e for e in core_week_errors(plan)
                if "core sets are flexion" in e]

    def test_the_exploit_week_now_fails_the_flexion_set_floor(self) -> None:
        errors = self._flexion_errors(_PLAN_EXPLOIT_MINIMAL_FLEXION)
        self.assertTrue(errors, "the 12.5%-flexion week still passes")
        self.assertIn("1 of 8 core sets are flexion", errors[0])
        self.assertIn("requires 3", errors[0])

    def test_the_exploit_week_is_blocked_end_to_end(self) -> None:
        # Both gates fire on it: the per-session floor four times (the
        # FULL BODY headings no longer buy the 2-set budget) and the
        # flexion floor once.
        errors, warnings = validate_workout_plan(_PLAN_EXPLOIT_MINIMAL_FLEXION)
        self.assertTrue(any("core sets are flexion" in e for e in errors))
        self.assertEqual(
            len([e for e in errors if "under-allocated" in e]), 4, errors)
        self.assertEqual(warnings, [])

    def test_one_loaded_flexion_exercise_no_longer_covers_the_week(self) -> None:
        # The exact shape the identity axis was satisfied by, isolated:
        # the loaded-flexion axis passes and the set floor still fails.
        # If these two ever agree on every input, one of them is dead.
        loaded = [e for e in core_week_errors(_PLAN_EXPLOIT_MINIMAL_FLEXION)
                  if "loaded flexion movements" in e]
        self.assertEqual(loaded, [], "the identity axis is doing this work")
        self.assertTrue(self._flexion_errors(_PLAN_EXPLOIT_MINIMAL_FLEXION))

    def test_the_required_count_is_a_third_of_volume_with_a_floor_of_three(self) -> None:
        # Pinned as a table, because the message quotes the number and a
        # ceil/floor slip would silently move the whole gate.
        for total, expected in ((0, 0), (1, 3), (3, 3), (6, 3), (8, 3),
                                (9, 3), (10, 4), (12, 4), (15, 5), (24, 8)):
            with self.subTest(total_core_sets=total):
                self.assertEqual(
                    render_validators._required_flexion_sets(
                        total, CORE_WEEK_SPEC),
                    expected)

    def test_the_share_and_the_absolute_floor_are_an_and_not_an_or(self) -> None:
        share = CORE_WEEK_SPEC["min_flexion_share_of_core_sets"]
        floor = CORE_WEEK_SPEC["min_flexion_sets_per_week"]
        self.assertAlmostEqual(share, 1 / 3)
        self.assertEqual(floor, 3)
        # Below the crossover the absolute floor binds; above it, the share.
        self.assertEqual(
            render_validators._required_flexion_sets(6, CORE_WEEK_SPEC), floor)
        self.assertGreater(
            render_validators._required_flexion_sets(24, CORE_WEEK_SPEC), floor)

    def test_zero_core_sets_does_not_add_a_fourth_way_to_say_no_core(self) -> None:
        # A week with no core is already named three louder ways. "0 of 0
        # core sets are flexion" is not a distribution finding, it is a
        # restatement, and it reads like a bug.
        plan = _HEAD + _workout(
            "1: LOWER A + CORE",
            "Barbell Back Squat: 90kgx8 /// 90kgx8",
            "Plank: 5s",
            "Calf Raise Machine: 55kgx12 /// 55kgx12")
        self.assertEqual(self._flexion_errors(plan), [])
        # ...and the absence is still reported, by the axes that own it.
        self.assertTrue(any("0 distinct core exercises" in e
                            for e in core_week_errors(plan)))

    def test_the_share_is_structural_and_a_deload_does_not_excuse_it(self) -> None:
        # THE tagging decision, and it was measured the hard way. Tagging
        # the whole floor AXIS_VOLUME made all five of the exploit's
        # findings demotable, so a payload declaring `reactive_deload`
        # rendered the 12.5%-flexion week at exit 0 — the gate disarmed
        # by the artifact it was gating. Moving an existing set from
        # anti-extension to flexion costs no fatigue, so the share is
        # structural and survives the relief.
        findings = dict(
            (msg, axis) for axis, msg
            in render_validators._core_week_findings(
                _PLAN_EXPLOIT_MINIMAL_FLEXION))
        share = [m for m in findings if "core sets are flexion" in m]
        self.assertTrue(share, findings)
        self.assertEqual(findings[share[0]], render_validators.AXIS_STRUCTURE)

        errors, _ = validate_workout_plan(_PLAN_EXPLOIT_MINIMAL_FLEXION,
                                          deload_week=True)
        self.assertTrue(any("core sets are flexion" in e for e in errors),
                        "a declared deload rendered the exploit clean")

    def test_the_absolute_floor_is_volume_and_a_deload_demotes_it(self) -> None:
        # The other half. 2 flexion sets of 6 satisfies the 33% share
        # exactly, so only the absolute 3/wk floor is unmet — and getting
        # to 3 means ADDING work, which a deload legitimately will not.
        # This is the real 2026-07-13 shape.
        plan = _HEAD + "".join([
            _workout("1: UPPER A + CORE",
                     "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
                     "Ab Crunch Machine: 30kgx12 /// 30kgx12",
                     "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
            _workout("2: UPPER B + CORE",
                     "Cable Lat Pulldown: 65kgx8 /// 65kgx8",
                     "Plank: 45s /// 45s",
                     "Cable Face Pull: 20kgx15 /// 20kgx15"),
            _workout("3: UPPER C + CORE",
                     "Shoulder Press Machine: 45kgx8 /// 45kgx8",
                     "Cable Pallof Press: 15kgx10 /// 15kgx10",
                     "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
        ])
        findings = dict((msg, axis) for axis, msg
                        in render_validators._core_week_findings(plan))
        absolute = [m for m in findings if "flexion sets across the plan" in m]
        self.assertTrue(absolute, findings)
        self.assertEqual(findings[absolute[0]], render_validators.AXIS_VOLUME)
        self.assertFalse([m for m in findings if "core sets are flexion" in m],
                         "the share is met; only the absolute floor is not")

    def test_the_measured_94_percent_flexion_week_is_not_what_this_catches(self) -> None:
        # A floor, not a band. The historic failure was 94% flexion and
        # the pattern-category axis is what bounds that end; this axis
        # must stay silent on it or the two rules fight.
        self.assertEqual(
            self._flexion_errors(_PLAN_ONE_EXERCISE_EVERY_SESSION), [])
        self.assertTrue(any("core pattern categories" in e for e in
                            core_week_errors(_PLAN_ONE_EXERCISE_EVERY_SESSION)))


class MinimumLegalCorePlanTests(unittest.TestCase):
    """`_PLAN_CHEAPEST_LEGAL_CORE` is minimal, proved by perturbation.

    A comment claiming "this is the cheapest legal plan" is what went
    wrong the first time — exhibit A carried that claim at 12 sets while
    an 8-set week rendered clean. So the claim is a test: take one set
    away anywhere, or move one set out of flexion, and the plan must
    become illegal.
    """

    def _core_findings(self, plan: str) -> list[str]:
        # The union the render gate applies: per-session dose and shape
        # plus the weekly distribution axes.
        return workout_core_warnings(plan) + core_week_errors(plan)

    def test_the_cheapest_legal_plan_is_legal(self) -> None:
        self.assertEqual(self._core_findings(_PLAN_CHEAPEST_LEGAL_CORE), [])

    def test_it_is_cheaper_than_the_prescribed_split_allows(self) -> None:
        # 8 sets against exhibit A's 12, which is the point of keeping
        # both: the D3 budget is not the binding constraint on a week
        # that names no lower day.
        counts = count_working_sets_per_workout(_PLAN_CHEAPEST_LEGAL_CORE)
        self.assertEqual(len(counts), 4)
        self.assertEqual(self._core_findings(_PLAN_DEGENERATE_CORE_LEGAL), [])

    def test_removing_any_single_core_set_makes_it_illegal(self) -> None:
        for label, before, after in (
            ("session 1 flexion", "Ab Crunch Machine: 30kgx12 /// 30kgx12",
             "Ab Crunch Machine: 30kgx12"),
            ("session 3 anti-extension", "Plank: 45s /// 45s", "Plank: 45s"),
            ("session 4 anti-rotation",
             "Cable Pallof Press: 15kgx10 /// 15kgx10",
             "Cable Pallof Press: 15kgx10"),
        ):
            with self.subTest(set_removed=label):
                thinner = _PLAN_CHEAPEST_LEGAL_CORE.replace(before, after, 1)
                self.assertNotEqual(thinner, _PLAN_CHEAPEST_LEGAL_CORE)
                self.assertTrue(self._core_findings(thinner),
                                f"dropping the {label} set stayed legal")

    def test_moving_two_sets_out_of_flexion_makes_it_illegal(self) -> None:
        # Same total volume, same distinct count, same categories — only
        # the flexion share changes, 4/8 to 2/8. This is the perturbation
        # nothing caught before the gate.
        swapped = _PLAN_CHEAPEST_LEGAL_CORE.replace(
            "- Ab Crunch Machine: 30kgx12 /// 30kgx12\n- Cable Face Pull",
            "- Hollow Body Hold: 45s /// 45s\n- Cable Face Pull", 1)
        self.assertNotEqual(swapped, _PLAN_CHEAPEST_LEGAL_CORE)
        self.assertEqual(
            sum(count_working_sets_per_workout(swapped).values()),
            sum(count_working_sets_per_workout(
                _PLAN_CHEAPEST_LEGAL_CORE).values()))
        self.assertTrue(any("core sets are flexion" in e
                            for e in self._core_findings(swapped)))

    def test_renaming_the_sessions_full_body_makes_it_illegal(self) -> None:
        # Gate 2 from the other direction: the 2-set-per-session budget
        # has to be EARNED by naming an upper day.
        renamed = _PLAN_CHEAPEST_LEGAL_CORE.replace("UPPER", "FULL BODY")
        findings = self._core_findings(renamed)
        self.assertEqual(len([f for f in findings if "under-allocated" in f]),
                         4, findings)


class CorePerSessionDoseTests(unittest.TestCase):
    def _core_dose_findings(self, plan: str) -> list[str]:
        return [w for w in workout_core_warnings(plan) if "core sets" in w]

    def test_lower_day_under_four_sets_is_reported(self) -> None:
        plan = _HEAD + _workout(
            "1: LOWER A + CORE",
            "Barbell Back Squat: 90kgx8 /// 90kgx8",
            "Ab Crunch Machine: 30kgx12 /// 30kgx12",
            "Calf Raise Machine: 55kgx12 /// 55kgx12")
        findings = self._core_dose_findings(plan)
        self.assertTrue(any("2 core sets" in f and "under-allocated" in f
                            for f in findings))

    def test_lower_day_at_four_sets_is_clean(self) -> None:
        plan = _HEAD + _workout(
            "1: LOWER A + CORE",
            "Barbell Back Squat: 90kgx8 /// 90kgx8",
            "Ab Crunch Machine: 30kgx12 /// 30kgx12",
            "Plank: 45s /// 45s",
            "Calf Raise Machine: 55kgx12 /// 55kgx12")
        self.assertEqual(self._core_dose_findings(plan), [])

    def test_upper_day_at_two_sets_is_clean(self) -> None:
        plan = _HEAD + _workout(
            "1: UPPER A + CORE",
            "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
            "Ab Crunch Machine: 30kgx12 /// 30kgx12",
            "Cable Lateral Raise: 14kgx10 /// 14kgx10")
        self.assertEqual(self._core_dose_findings(plan), [])

    def test_upper_day_tolerates_exactly_one_extra_set(self) -> None:
        tol = CORE_WEEK_SPEC["session_set_overshoot_tolerance"]
        self.assertEqual(tol, 1)
        three = _HEAD + _workout(
            "1: UPPER A + CORE",
            "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
            "Ab Crunch Machine: 30kgx12 /// 30kgx12 /// 30kgx12",
            "Cable Lateral Raise: 14kgx10 /// 14kgx10")
        four = three.replace("30kgx12 /// 30kgx12 /// 30kgx12",
                             "30kgx12 /// 30kgx12 /// 30kgx12 /// 30kgx12")
        self.assertEqual(self._core_dose_findings(three), [])
        self.assertTrue(any("over-allocated" in f
                            for f in self._core_dose_findings(four)))

    def test_unclassified_session_takes_the_lower_day_floor(self) -> None:
        # A heading the classifier cannot place used to accept the whole
        # [upper, lower] band, which let the coach pick its own core
        # budget by naming the session. The floor is now the lower-day
        # one; the ceiling stays loose. See
        # `test_w3a_enforcement.FullBodySessionFloorTests` for the rest.
        lower = CORE_WEEK_SPEC["sets_per_session"]["lower"]
        upper = CORE_WEEK_SPEC["sets_per_session"]["upper"]
        for n_sets, expect_finding in ((upper, True), (lower, False)):
            sets = " /// ".join(["30kgx12"] * n_sets)
            plan = _HEAD + _workout(
                "1: FULL BODY",
                "Barbell Back Squat: 90kgx8 /// 90kgx8",
                f"Ab Crunch Machine: {sets}",
                "Calf Raise Machine: 55kgx12 /// 55kgx12")
            findings = self._core_dose_findings(plan)
            self.assertEqual(bool(findings), expect_finding,
                             f"{n_sets} sets on an unclassified day: {findings}")

    def test_explicit_flat_band_overrides_the_session_type(self) -> None:
        plan = _HEAD + _workout(
            "1: LOWER A + CORE",
            "Barbell Back Squat: 90kgx8 /// 90kgx8",
            "Ab Crunch Machine: 30kgx12 /// 30kgx12",
            "Calf Raise Machine: 55kgx12 /// 55kgx12")
        self.assertEqual(
            [w for w in workout_core_warnings(plan, min_sets=1, max_sets=3)
             if "core sets" in w], [])


class ArmWeekSpecTests(unittest.TestCase):
    _ONE_EXERCISE_EACH = _HEAD + "".join([
        _workout("1: UPPER A",
                 "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
                 "Cable Tricep Pushdown: 25kgx10 /// 25kgx10 /// 25kgx10",
                 "Incline Dumbbell Curl: 14kgx10 /// 14kgx10 /// 14kgx10",
                 "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
        _workout("2: UPPER B",
                 "Cable Lat Pulldown: 65kgx8 /// 65kgx8",
                 "Cable Tricep Pushdown: 25kgx10 /// 25kgx10 /// 25kgx10",
                 "Incline Dumbbell Curl: 14kgx10 /// 14kgx10 /// 14kgx10",
                 "Cable Face Pull: 20kgx15 /// 20kgx15"),
    ])

    # ANTI-GAMING EXHIBIT C. The cheapest week satisfying `arm_week_spec`:
    # 6 direct sets and 2 movements per muscle. Training-acceptable — that
    # is a textbook MEV-level arm allocation, and the two triceps entries
    # differ in shoulder position (long head vs lateral head).
    _MINIMUM_LEGAL = _HEAD + "".join([
        _workout("1: UPPER A",
                 "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
                 "Cable Tricep Pushdown: 25kgx10 /// 25kgx10 /// 25kgx10",
                 "Incline Dumbbell Curl: 14kgx10 /// 14kgx10 /// 14kgx10",
                 "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
        _workout("2: UPPER B",
                 "Cable Lat Pulldown: 65kgx8 /// 65kgx8",
                 "Cable Overhead Tricep Extension: 29kgx10 /// 29kgx10 /// 29kgx10",
                 "Bayesian Cable Curl: 14kgx10 /// 14kgx10 /// 14kgx10",
                 "Cable Face Pull: 20kgx15 /// 20kgx15"),
    ])

    def test_meeting_the_floor_with_one_exercise_fails_the_diversity_axis(self) -> None:
        errors = arm_week_errors(self._ONE_EXERCISE_EACH)
        self.assertTrue(any("1 distinct direct biceps exercises" in e
                            for e in errors))
        self.assertTrue(any("1 distinct direct triceps exercises" in e
                            for e in errors))
        # The quantity axis is satisfied: 6 sets each. Only diversity fails.
        self.assertFalse(any("floor is" in e for e in errors))

    def test_minimum_legal_arm_week_passes(self) -> None:
        self.assertEqual(arm_week_errors(self._MINIMUM_LEGAL), [])

    def test_zero_arm_work_reports_the_floor_and_not_the_diversity_axis(self) -> None:
        plan = _HEAD + _workout(
            "1: UPPER A",
            "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
            "Cable Lat Pulldown: 65kgx8 /// 65kgx8")
        errors = arm_week_errors(plan)
        self.assertTrue(any("0 direct biceps sets" in e for e in errors))
        self.assertTrue(any("0 direct triceps sets" in e for e in errors))
        self.assertFalse(any("distinct direct" in e for e in errors))

    def test_spec_floor_is_the_single_source_of_the_six_set_minimum(self) -> None:
        self.assertEqual(render_validators.DIRECT_ARM_MIN_SETS_PER_WEEK,
                         ARM_WEEK_SPEC["min_direct_sets_per_week"])

    def test_a_zero_set_arm_bullet_does_not_buy_diversity(self) -> None:
        # The core loop skips zero-set bullets and so does the arm loop,
        # but nothing tested the arm side, so deleting its `b["sets"] <= 0`
        # guard kept the suite green. Naming a second curl is not
        # performing one.
        #
        # Six credited sets on ONE movement, plus a second curl written
        # with no load, no time and no `///` — which credits zero sets.
        # With the guard the diversity axis fires; without it the plan
        # reads as two distinct movements and goes quiet.
        plan = _HEAD + _workout(
            "1: UPPER A",
            "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
            "Incline Dumbbell Curl: 14kgx10 /// 14kgx10 /// 14kgx10 "
            "/// 14kgx10 /// 14kgx10 /// 14kgx10",
            "Bayesian Cable Curl: 12",
            "Cable Lateral Raise: 14kgx10 /// 14kgx10")
        errors = arm_week_errors(plan)
        self.assertEqual(count_working_sets_per_workout(plan)["Workout 1: UPPER A"],
                         10, "fixture drifted: the second curl must credit 0")
        self.assertTrue(any("1 distinct direct biceps exercises" in e
                            for e in errors), errors)
        # The volume floor is satisfied by the six real sets, so the
        # diversity axis is the only thing under test here.
        self.assertFalse(any("direct biceps sets across" in e for e in errors),
                         errors)


class BlockingEntryPointTests(unittest.TestCase):
    def test_dose_and_distribution_findings_come_back_as_errors(self) -> None:
        errors, warnings = validate_workout_plan(_PLAN_ONE_EXERCISE_EVERY_SESSION)
        self.assertTrue(any("distinct core exercises" in e for e in errors))
        self.assertTrue(any("core pattern categories" in e for e in errors))
        self.assertTrue(any("direct biceps sets" in e for e in errors))
        self.assertEqual(warnings, [])

    def test_set_budget_drift_stays_a_warning(self) -> None:
        # An intentional deload legitimately undershoots the set budget,
        # so that one check must NOT block the render.
        plan = _HEAD + _workout(
            "1: UPPER A + CORE",
            "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
            "Ab Crunch Machine: 30kgx12 /// 30kgx12")
        _, warnings = validate_workout_plan(plan, target_working_sets=22)
        self.assertTrue(any("under" in w for w in warnings))

    def test_a_compliant_plan_produces_no_errors(self) -> None:
        # The minimum legal core week plus the minimum legal arm week,
        # with arms inside the isolation block rather than the terminal
        # slot. Nothing here should block a render.
        plan = _HEAD + "".join([
            _workout("1: LOWER A + CORE",
                     "Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8",
                     "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
                     "Plank: 45s /// 45s",
                     "Calf Raise Machine: 55kgx10-12 /// 55kgx10-12"),
            _workout("2: UPPER A + CORE",
                     "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
                     "Cable Pallof Press: 15kgx10 /// 15kgx10",
                     "Incline Dumbbell Curl: 14kgx10 /// 14kgx10 /// 14kgx10",
                     "Cable Tricep Pushdown: 25kgx10 /// 25kgx10 /// 25kgx10",
                     "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
            _workout("3: LOWER B + CORE",
                     "Leg Press: 200kgx10 /// 200kgx10",
                     "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
                     "Side Plank: 45s /// 45s",
                     "Hip Adductor Machine: 50kgx12 /// 50kgx12"),
            _workout("4: UPPER B + CORE",
                     "Cable Lat Pulldown: 65kgx8 /// 65kgx8",
                     "Plank: 45s /// 45s",
                     "Bayesian Cable Curl: 14kgx10 /// 14kgx10 /// 14kgx10",
                     "Cable Overhead Tricep Extension: 29kgx10 /// 29kgx10 /// 29kgx10",
                     "Rear Delt Fly Machine: 20kgx12 /// 20kgx12"),
        ])
        errors, _ = validate_workout_plan(plan)
        self.assertEqual(errors, [])


class VolumeLandmarkUnitTests(unittest.TestCase):
    """D9 — the landmark table and the tracker measured different things.

    RP publishes DIRECT sets per week; `weekly_volume_per_muscle` emits
    direct + 0.5 x synergist. `VOLUME_LANDMARKS` is now derived from the
    published table plus a measured, per-muscle synergist offset."""

    def test_landmarks_are_derived_from_published_values_plus_the_offset(self) -> None:
        self.assertEqual(set(VOLUME_LANDMARKS), set(RP_DIRECT_SET_LANDMARKS))
        for muscle, bands in RP_DIRECT_SET_LANDMARKS.items():
            offset = SYNERGIST_CREDIT_OFFSET.get(muscle, 0)
            for band, value in bands.items():
                self.assertEqual(VOLUME_LANDMARKS[muscle][band], value + offset,
                                 f"{muscle}.{band}")

    def test_every_offset_muscle_actually_receives_synergist_credit(self) -> None:
        # An offset on a muscle the catalog never credits as a synergist
        # would be a landmark inflated for no reason.
        from pathlib import Path
        from workout_coach.lib.extract import load_exercises_db
        from shared.exercises_database import DATABASE_PATH

        db = load_exercises_db(Path(DATABASE_PATH))
        credited = {syn
                    for meta in db.values()
                    if not meta.get("is_warmup")
                    for syn in (meta.get("synergists") or [])}
        for muscle, offset in SYNERGIST_CREDIT_OFFSET.items():
            self.assertGreater(offset, 0, muscle)
            self.assertIn(muscle, credited,
                          f"{muscle} carries a synergist offset but appears "
                          f"as a synergist nowhere in the catalog")

    def test_structurally_unsynergised_muscles_are_not_restated(self) -> None:
        # These appear zero times as a synergist, so the fractional unit
        # and the direct unit are the same unit for them. `core` is the
        # load-bearing case: the core landmark must transfer unchanged.
        from pathlib import Path
        from workout_coach.lib.extract import load_exercises_db
        from shared.exercises_database import DATABASE_PATH

        db = load_exercises_db(Path(DATABASE_PATH))
        credited = {syn
                    for meta in db.values()
                    if not meta.get("is_warmup")
                    for syn in (meta.get("synergists") or [])}
        for muscle in ("core", "side_delts", "calves", "adductors", "neck"):
            self.assertNotIn(muscle, credited, muscle)
            self.assertEqual(SYNERGIST_CREDIT_OFFSET.get(muscle, 0), 0, muscle)
            self.assertEqual(VOLUME_LANDMARKS[muscle],
                             RP_DIRECT_SET_LANDMARKS[muscle], muscle)

    def test_rear_delt_and_calf_mev_lowered_into_rp_published_range(self) -> None:
        self.assertEqual(RP_DIRECT_SET_LANDMARKS["rear_delts"]["mev"], 6)
        self.assertEqual(RP_DIRECT_SET_LANDMARKS["calves"]["mev"], 6)

    def test_bands_stay_ordered_after_the_shift(self) -> None:
        for muscle, bands in VOLUME_LANDMARKS.items():
            self.assertLessEqual(bands["mv"], bands["mev"], muscle)
            self.assertLessEqual(bands["mev"], bands["mav"], muscle)
            self.assertLessEqual(bands["mav"], bands["mrv"], muscle)


class SynergistOffsetPinTests(unittest.TestCase):
    """The offsets are integers with consequences, so they are pinned.

    WHY THIS CLASS EXISTS. `SYNERGIST_CREDIT_OFFSET` drives every
    landmark through ``VOLUME_LANDMARKS = published + offset``, and its
    only coverage was two tautologies: one asserting
    ``landmarks == published + offset`` (true for ANY offset) and one
    asserting ``offset > 0`` (true for any positive offset). Doubling the
    biceps offset 3 -> 6 moved its MEV 11 -> 14 and 630 tests stayed
    green. A number nothing pins is a number nothing defends.
    """

    def test_the_derivation_rule_is_floor_of_the_smaller_estimator(self) -> None:
        # THE RULE, executable rather than commented:
        #     offset = floor(min(pooled_median, pooled_mean))
        # It is not implied by the numbers — floor(median) and
        # floor(mean) disagree for two of the six rows — so it has to be
        # written down somewhere that fails when it changes.
        from math import floor
        for muscle, (median, mean) in SYNERGIST_CREDIT_MEASUREMENT.items():
            with self.subTest(muscle=muscle):
                self.assertEqual(SYNERGIST_CREDIT_OFFSET[muscle],
                                 floor(min(median, mean)))

    def test_the_two_estimators_actually_disagree_somewhere(self) -> None:
        # If they never disagreed the rule would be decorative and
        # "measured, then floored" would be the whole story. They
        # disagree on exactly two rows, which is why min() is in the
        # formula and why it is biased low rather than rounded.
        from math import floor
        split = {m for m, (med, mean) in SYNERGIST_CREDIT_MEASUREMENT.items()
                 if floor(med) != floor(mean)}
        self.assertEqual(split, {"front_delts", "glutes"})
        for muscle in split:
            median, _mean = SYNERGIST_CREDIT_MEASUREMENT[muscle]
            self.assertLess(SYNERGIST_CREDIT_OFFSET[muscle], floor(median),
                            f"{muscle}: the median would have given more")

    def test_the_offsets_are_the_measured_integers(self) -> None:
        self.assertEqual(
            dict(SYNERGIST_CREDIT_OFFSET),
            {"biceps": 3, "triceps": 3, "front_delts": 2, "glutes": 2,
             "rear_delts": 1, "external_rotators": 1})

    def test_the_derived_landmarks_every_consumer_reads_are_pinned(self) -> None:
        # The values downstream code compares real volume against. This
        # is the assertion the biceps mutation had to survive and did
        # not: MEV 11, not 14.
        for muscle, bands in {
            "biceps":            {"mv": 8, "mev": 11, "mav": 19, "mrv": 25},
            "triceps":           {"mv": 7, "mev": 9,  "mav": 15, "mrv": 19},
            "front_delts":       {"mv": 2, "mev": 2,  "mav": 8,  "mrv": 14},
            "glutes":            {"mv": 2, "mev": 6,  "mav": 14, "mrv": 18},
            "rear_delts":        {"mv": 7, "mev": 7,  "mav": 17, "mrv": 23},
            "external_rotators": {"mv": 1, "mev": 3,  "mav": 7,  "mrv": 13},
        }.items():
            with self.subTest(muscle=muscle):
                self.assertEqual(VOLUME_LANDMARKS[muscle], bands)

    def test_external_rotators_is_measured_not_ambiguous(self) -> None:
        # It was filed under `# AMBIGUOUS` at offset 0 while measuring a
        # pooled median of 1.00 and mean of 1.05, nonzero in both
        # trackers. That is the wrong disclosure, and not a neutral one:
        # at offset 0 its ~1.05 fractional sets/wk were being compared
        # against a DIRECT-set MEV of 2 (53% of target) instead of a
        # fractional MEV of 3 (35%), so the least-served muscle in the
        # table read as one of the better-served.
        #
        # It was then filed UNHITTABLE on a SATISFIABILITY ground: the
        # catalog carried no primary entry for the muscle, so the restated
        # MEV could not be hit until it gained one. That gap closed on
        # 2026-08-03 when `Cable External Rotation` landed. The offset and
        # the landmark are unchanged by that — restating a unit conversion
        # never depended on the target being reachable — so both pins stay.
        self.assertEqual(SYNERGIST_CREDIT_OFFSET["external_rotators"], 1)
        self.assertEqual(VOLUME_LANDMARKS["external_rotators"]["mev"], 3)

        from pathlib import Path
        from workout_coach.lib.extract import load_exercises_db
        from shared.exercises_database import DATABASE_PATH

        db = load_exercises_db(Path(DATABASE_PATH))
        primaries = {meta.get("primary") for meta in db.values()}
        self.assertIn("external_rotators", primaries,
                      "the catalog lost its primary external-rotator entry; "
                      "the restated MEV of 3 is unreachable again and the "
                      "HITTABLE note in constants.py is stale")

    def test_the_ambiguous_marker_means_exactly_one_thing(self) -> None:
        # Three muscles are left at 0 because the number is UNKNOWN. That
        # marker is only worth reading while it never also means "known
        # but inconvenient", which is what external_rotators made it mean.
        import inspect
        from workout_coach.lib import constants
        src = inspect.getsource(constants)
        # The AMBIGUOUS block ends where the external-rotators block starts.
        # That heading was "# UNHITTABLE" until 2026-08-03 and is now
        # "# HITTABLE since ..."; match the stable part so a future status
        # change to that one muscle cannot silently widen this slice to the
        # rest of the file and make the assertion below vacuous.
        ambiguous = src.split("# AMBIGUOUS —")[1].split("HITTABLE")[0]
        self.assertLess(len(ambiguous), 2000,
                        "AMBIGUOUS slice ran past its terminator")
        for muscle in ("erectors", "forearms", "neck"):
            self.assertIn(muscle, ambiguous)
            self.assertNotIn(muscle, SYNERGIST_CREDIT_MEASUREMENT)
            self.assertEqual(SYNERGIST_CREDIT_OFFSET.get(muscle, 0), 0)
        self.assertNotIn("external_rotators", ambiguous)

    def test_every_mv_equals_mev_collapse_is_flagged_in_the_table(self) -> None:
        # Three muscles now target the same number for `maintain` and
        # `grow`, which makes the tier distinction meaningless for them.
        # Two were flagged; front_delts was not, and its MV moved 0 -> 2
        # in the process, so a muscle whose maintenance requirement was
        # ZERO now demands 2 fractional sets/wk. Pinned as a set so a
        # fourth cannot appear silently.
        collapsed = {m for m, b in VOLUME_LANDMARKS.items()
                     if b["mv"] == b["mev"]}
        self.assertEqual(collapsed, {"rear_delts", "calves", "front_delts"})

        # The note has to sit ON the row, not merely somewhere in the
        # file — a caveat two hundred lines from the number it qualifies
        # is not a disclosure. Walk back from each landmark row through
        # its own contiguous comment block.
        import inspect
        from workout_coach.lib import constants
        lines = inspect.getsource(constants).splitlines()
        # Two accepted phrasings because the rows were written at
        # different times and rewording a row that is not being changed
        # would be churn. Both name the same fact.
        phrasings = ("MV == MEV", "EQUALS MEV")
        for muscle in sorted(collapsed):
            with self.subTest(muscle=muscle):
                idx = next(i for i, ln in enumerate(lines)
                           if ln.strip().startswith(f'"{muscle}":')
                           and '"mv"' in ln)
                start = idx
                while start and lines[start - 1].strip().startswith("#"):
                    start -= 1
                note = "\n".join(lines[start:idx])
                self.assertTrue(
                    any(p in note for p in phrasings),
                    f"{muscle} collapses MV into MEV with no note on its "
                    f"own row (searched {phrasings})")
        # front_delts specifically: the collapse the OFFSET creates, not a
        # published-range correction. Both direct values are 0.
        self.assertEqual(RP_DIRECT_SET_LANDMARKS["front_delts"]["mv"], 0)
        self.assertEqual(RP_DIRECT_SET_LANDMARKS["front_delts"]["mev"], 0)
        self.assertEqual(VOLUME_LANDMARKS["front_delts"]["mv"], 2)


class PriorityTierTests(unittest.TestCase):
    """D8 — emphasise / grow / maintain, targeting mid-MAV / MEV / MV."""

    def test_default_tiers_emphasise_the_block_set_and_maintain_the_rest(self) -> None:
        tiers, unknown = muscle_priority_tiers()
        self.assertEqual(unknown, [])
        self.assertEqual(
            {m for m, t in tiers.items() if t == "emphasis"},
            set(BLOCK_EMPHASIS_DEFAULT))
        self.assertEqual(set(tiers), set(VOLUME_LANDMARKS))
        for muscle in ("chest", "back", "quads", "hamstrings", "glutes"):
            self.assertEqual(tiers[muscle], "maintain", muscle)

    def test_maintain_is_the_default_for_an_unlisted_muscle(self) -> None:
        tiers, _ = muscle_priority_tiers(
            {MUSCLE_PRIORITY_PROFILE_KEY: "chest:emphasis"})
        self.assertEqual(tiers["chest"], "emphasis")
        self.assertEqual(tiers["core"], DEFAULT_PRIORITY_TIER)

    def test_profile_config_replaces_the_built_in_emphasis_set(self) -> None:
        # Config wins in full, so a person can drop a muscle from
        # emphasis without a code change.
        tiers, unknown = muscle_priority_tiers(
            {MUSCLE_PRIORITY_PROFILE_KEY: "back:emphasis; biceps:grow"})
        self.assertEqual(unknown, [])
        self.assertEqual(tiers["back"], "emphasis")
        self.assertEqual(tiers["biceps"], "grow")
        self.assertEqual(tiers["core"], "maintain")

    def test_typos_are_reported_rather_than_silently_applied(self) -> None:
        tiers, unknown = muscle_priority_tiers(
            {MUSCLE_PRIORITY_PROFILE_KEY: "core:emphasise;nosuchmuscle:grow"})
        self.assertEqual(tiers["core"], DEFAULT_PRIORITY_TIER)
        self.assertEqual(sorted(unknown), ["core:emphasise", "nosuchmuscle:grow"])

    def test_targets_are_mid_mav_mev_and_mv(self) -> None:
        targets = muscle_volume_targets(
            {"core": "emphasis", "chest": "grow", "back": "maintain"})
        core = VOLUME_LANDMARKS["core"]
        self.assertEqual(targets["core"]["target_sets"],
                         round((core["mev"] + core["mav"]) / 2.0, 1))
        self.assertEqual(targets["chest"]["target_sets"],
                         float(VOLUME_LANDMARKS["chest"]["mev"]))
        self.assertEqual(targets["back"]["target_sets"],
                         float(VOLUME_LANDMARKS["back"]["mv"]))

    def test_block_emphasis_targets_match_the_approved_numbers(self) -> None:
        # Cross-check against the numbers signed off in the spec's volume
        # trade. calves is 10 rather than the spec's 11 because that
        # arithmetic predates the authorised calves MEV 8 -> 6 fix.
        targets = muscle_volume_targets()
        self.assertEqual(
            {m: targets[m]["target_sets"] for m in BLOCK_EMPHASIS_DEFAULT},
            {"core": 8.0, "side_delts": 12.0, "rear_delts": 12.0,
             "calves": 10.0, "traps": 9.5})


if __name__ == "__main__":
    unittest.main()
