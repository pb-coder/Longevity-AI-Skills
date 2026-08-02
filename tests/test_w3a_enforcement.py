"""W3a — the checks W4 and W5 built, actually enforcing.

Everything here is a wiring test. The rules themselves are covered by
``test_w4_specs`` and ``test_w5_blocks``; what was missing was anybody
calling them. Three separate holes, each of which made a computed
finding invisible:

1. ``render_dashboard`` put the core and arm checks inside
   ``if base_budget:``, so a payload without ``target_working_sets``
   skipped core and arm validation ENTIRELY. An unrelated missing key
   silently disabled the checks the whole workstream exists to add.
2. ``validate_workout_plan`` — the blocking entry point, tested and
   documented — was dead code. Findings went to stderr, where the July
   round had already proved they get ignored.
3. ``blocks.rotation_diff_errors`` had no caller at all. On the real
   2026-07-18 -> 2026-07-25 transition it finds 14 violations.

Plus the two bodyweight cards, which accept a ``bw_trend_block`` that
nothing was passing, so both fell back to a reason-less "unresolved".
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workout_coach.lib import render_validators
from workout_coach.lib.adherence import session_type_from_title
from workout_coach.lib.blocks import new_block
from workout_coach.lib.constants import ARM_WEEK_SPEC, CORE_WEEK_SPEC
from workout_coach.lib.render_validators import (
    AXIS_STRUCTURE,
    AXIS_VOLUME,
    arm_week_errors,
    block_rotation_errors,
    core_week_errors,
    is_deload_week,
    tier_budget_by_index,
    validate_workout_plan,
    _dose_aware_distinct_floor,
    _arm_findings,
    _core_session_findings,
    _core_week_findings,
    _iter_workout_exercise_bullets,
    _session_core_set_bounds,
)

SKILLS_ROOT = Path(__file__).resolve().parents[1]
RENDER_DASHBOARD = SKILLS_ROOT / "workout-coach" / "scripts" / "render_dashboard.py"


def _load_render_dashboard():
    """Import the script module so ``render()`` can be called directly."""
    spec = importlib.util.spec_from_file_location(
        "_w3a_render_dashboard", RENDER_DASHBOARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _workout(title: str, *bullets: str) -> str:
    return f"## Workout {title}\n" + "".join(f"- {b}\n" for b in bullets) + "\n"


_HEAD = "# Workout plan — 2026-08-02\n\n"

# The 2026-07-18 shape: one machine crunch, two sets, every session.
# Fails the weekly core spec on three axes at once.
_PLAN_CORE_DEFICIENT = _HEAD + "".join([
    _workout("1: LOWER A + CORE",
             "Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8",
             "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
             "Incline Dumbbell Curl: 14kgx10 /// 14kgx10 /// 14kgx10",
             "Cable Tricep Pushdown: 25kgx10 /// 25kgx10 /// 25kgx10",
             "Calf Raise Machine: 55kgx10-12 /// 55kgx10-12"),
    _workout("2: UPPER A + CORE",
             "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
             "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
             "Bayesian Cable Curl: 14kgx10 /// 14kgx10 /// 14kgx10",
             "Cable Overhead Tricep Extension: 29kgx10 /// 29kgx10 /// 29kgx10",
             "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
])

# The minimum legal week: three distinct core movements across three
# pattern categories, one of them loaded flexion, arms above the floor
# on two distinct movements each, arms never in the terminal slot.
_PLAN_COMPLIANT = _HEAD + "".join([
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

# Not a plan: no `## Workout` block, so it prescribes no week at all.
_NOT_A_PLAN = "# Workout\n- Test session\n"

# A previous block holding the two lower-A slots `_PLAN_COMPLIANT` also
# prescribes, so the plan is a mid-block re-issue: every rotating slot
# comes back unchanged. `_PLAN_COMPLIANT` passes every core and arm spec,
# so any finding this payload produces is a ROTATION finding and nothing
# else — which is what makes it usable as the rotation-only fixture.
_ROTATION_PREV_BLOCK = {
    "source": "artifact", "block_id": "2026-06-20",
    "started": "2026-06-20",
    "slots": [
        {"session_type": "lower_a", "position": 1,
         "exercise": "Barbell Back Squat", "tag": "anchor"},
        {"session_type": "lower_a", "position": 2,
         "exercise": "Ab Crunch Machine", "tag": "rotating"},
    ],
}


def _run_render(tracker: dict, workout_md: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "tracker.json").write_text(json.dumps(tracker), encoding="utf-8")
        (tmp / "coach.json").write_text(
            json.dumps({"headline": "Train as planned.", "cards": {}}),
            encoding="utf-8")
        (tmp / "workout.md").write_text(workout_md, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(RENDER_DASHBOARD),
             "--tracker", str(tmp / "tracker.json"),
             "--coach", str(tmp / "coach.json"),
             "--workout-md", str(tmp / "workout.md"),
             "--out", str(tmp / "out.html"),
             "--person", "TestPerson"],
            cwd=SKILLS_ROOT, capture_output=True, text=True)


# ---------------------------------------------------------------- task 1
class ValidationIsBlockingTests(unittest.TestCase):
    """The render must refuse a plan the specs reject."""

    def test_a_core_deficient_plan_exits_2(self) -> None:
        proc = _run_render({"today": "2026-08-02", "target_working_sets": 24},
                           _PLAN_CORE_DEFICIENT)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("workout_md validation error:", proc.stderr)
        self.assertIn("distinct core exercises", proc.stderr)

    def test_core_and_arm_checks_run_without_a_set_budget(self) -> None:
        # THE BUG. `target_working_sets` is the SET-BUDGET input. Core and
        # arm validation has nothing to do with it, but both used to sit
        # inside `if base_budget:`, so a payload missing that one key
        # skipped them entirely and the render passed.
        tracker = {"today": "2026-08-02"}
        self.assertNotIn("target_working_sets", tracker)
        proc = _run_render(tracker, _PLAN_CORE_DEFICIENT)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("distinct core exercises", proc.stderr)
        self.assertIn("core pattern categories", proc.stderr)

    def test_a_compliant_plan_still_renders(self) -> None:
        proc = _run_render({"today": "2026-08-02", "target_working_sets": 24},
                           _PLAN_COMPLIANT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("workout_md validation error:", proc.stderr)

    def test_set_budget_drift_warns_but_still_renders(self) -> None:
        # An intentional deload legitimately undershoots the budget, so
        # this one finding must stay advisory.
        proc = _run_render({"today": "2026-08-02", "target_working_sets": 40},
                           _PLAN_COMPLIANT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("plan warning:", proc.stderr)
        self.assertIn("under) —", proc.stderr)

    def test_a_document_that_prescribes_no_week_is_not_a_violation(self) -> None:
        # A summary doc has no `## Workout` block. Judging it against a
        # weekly arm floor would refuse the render on the strength of a
        # week the document never contained. Core already failed open
        # here; arms did not, which is only visible once the finding
        # blocks instead of printing.
        self.assertEqual(arm_week_errors(_NOT_A_PLAN), [])
        proc = _run_render({"today": "2026-08-02"}, _NOT_A_PLAN)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_a_real_plan_with_no_arm_work_still_errors(self) -> None:
        # The fail-open above must not become a way past the arm floor.
        plan = _HEAD + _workout(
            "1: UPPER A + CORE",
            "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
            "Cable Lateral Raise: 14kgx10 /// 14kgx10")
        errors = arm_week_errors(plan)
        self.assertTrue(any("0 direct biceps sets" in e for e in errors))
        self.assertTrue(any("0 direct triceps sets" in e for e in errors))


class MalformedSpecTests(unittest.TestCase):
    """A spec the validator cannot use is a REFUSAL, not a crash.

    Measured before the fix, all three through the CLI:

        partial core_week_spec  -> rc=1, KeyError: 'sets_per_session'
        partial arm_week_spec   -> rc=1, KeyError: 'min_distinct_...'
        core_week_spec = string -> rc=1, TypeError

    ``spec = spec or CORE_WEEK_SPEC`` guarded only the falsy case and
    every later ``spec[key]`` was bare. rc=1 means the program crashed;
    a spec the validator will not run against is rc=2. And a partial
    spec is not even wrong: `tracker/validation.py` types the field as a
    free dict and `test_tracker_validators` pins a partial one as VALID,
    so it must render.

    OWNERSHIP, decided here. The renderer no longer passes the payload's
    specs into `validate_workout_plan` at all. `read_tracker` writes them
    from the same `constants` the validator imports, so the read was a
    measured no-op (mutation M29: replacing it with ``None`` changed no
    output anywhere) — but a no-op that made the gate's own thresholds an
    input to the gate. A merge gate cannot take its bar from the artifact
    it is judging. The payload copy stays, because the coach reads it
    while authoring; it is checked for shape and ignored for gating.
    """

    _PARTIAL_CORE = {"min_distinct_exercises_per_week": 3}
    _PARTIAL_ARM = {"min_direct_sets_per_week": 6}

    def test_a_partial_spec_fills_in_from_the_constant(self) -> None:
        merged = render_validators._resolved_spec(
            self._PARTIAL_CORE, CORE_WEEK_SPEC, "core_week_spec")
        self.assertEqual(merged["min_distinct_exercises_per_week"], 3)
        self.assertEqual(merged["sets_per_session"],
                         CORE_WEEK_SPEC["sets_per_session"])

    def test_a_partial_nested_spec_fills_in_one_level_deep(self) -> None:
        # `{"sets_per_session": {"lower": 5}}` must keep `upper`, or the
        # next `per_session["upper"]` is the same KeyError in a new place.
        merged = render_validators._resolved_spec(
            {"sets_per_session": {"lower": 5}}, CORE_WEEK_SPEC,
            "core_week_spec")
        self.assertEqual(merged["sets_per_session"],
                         {"lower": 5,
                          "upper": CORE_WEEK_SPEC["sets_per_session"]["upper"]})

    def test_a_partial_spec_no_longer_raises_through_the_public_api(self) -> None:
        for kw in ({"core_spec": self._PARTIAL_CORE},
                   {"arm_spec": self._PARTIAL_ARM}):
            with self.subTest(**kw):
                errors, _ = validate_workout_plan(_PLAN_COMPLIANT, **kw)
                self.assertEqual(errors, [])

    def test_a_non_mapping_spec_raises_a_typed_error_not_a_typeerror(self) -> None:
        for label, spec in (("core_week_spec", "four sets"),
                            ("arm_week_spec", ["six"])):
            with self.subTest(label=label):
                with self.assertRaises(render_validators.SpecError) as caught:
                    render_validators._resolved_spec(
                        spec, CORE_WEEK_SPEC, label)
                self.assertIn(label, str(caught.exception))
                self.assertIn("must be a mapping", str(caught.exception))

    def test_a_wrong_typed_value_names_the_field_and_the_type(self) -> None:
        with self.assertRaises(render_validators.SpecError) as caught:
            render_validators._resolved_spec(
                {"min_distinct_exercises_per_week": "three"},
                CORE_WEEK_SPEC, "core_week_spec")
        msg = str(caught.exception)
        self.assertIn("core_week_spec.min_distinct_exercises_per_week", msg)
        self.assertIn("must be int", msg)

    def test_a_share_written_as_an_int_is_not_a_type_error(self) -> None:
        # Numeric tolerance, on purpose: 1 and 1.0 are the same share.
        merged = render_validators._resolved_spec(
            {"min_flexion_share_of_core_sets": 1}, CORE_WEEK_SPEC,
            "core_week_spec")
        self.assertEqual(merged["min_flexion_share_of_core_sets"], 1)
        # ...but a bool is not a number here.
        with self.assertRaises(render_validators.SpecError):
            render_validators._resolved_spec(
                {"min_flexion_sets_per_week": True}, CORE_WEEK_SPEC,
                "core_week_spec")

    def test_payload_spec_errors_is_quiet_on_valid_and_partial_payloads(self) -> None:
        for payload in (None, {}, {"today": "2026-08-02"},
                        {"core_week_spec": CORE_WEEK_SPEC,
                         "arm_week_spec": ARM_WEEK_SPEC},
                        {"core_week_spec": self._PARTIAL_CORE,
                         "arm_week_spec": self._PARTIAL_ARM}):
            with self.subTest(payload=payload):
                self.assertEqual(
                    render_validators.payload_spec_errors(payload), [])

    def test_the_cli_exits_2_on_a_malformed_spec(self) -> None:
        proc = _run_render(
            {"today": "2026-08-02", "core_week_spec": "four sets"},
            _PLAN_COMPLIANT)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("tracker_json validation error:", proc.stderr)
        self.assertIn("core_week_spec must be a mapping", proc.stderr)
        # Actionable: it names where the shape comes from.
        self.assertIn("workout_coach.lib.constants", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_the_cli_renders_a_partial_spec_instead_of_crashing(self) -> None:
        for key, spec in (("core_week_spec", self._PARTIAL_CORE),
                          ("arm_week_spec", self._PARTIAL_ARM)):
            with self.subTest(key=key):
                proc = _run_render({"today": "2026-08-02", key: spec},
                                   _PLAN_COMPLIANT)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)

    def test_a_payload_cannot_lower_the_bar_it_is_judged_against(self) -> None:
        # The reason the payload read is gone rather than merged. This
        # spec disables every core axis; the render must reject the
        # core-deficient plan anyway.
        toothless = {"sets_per_session": {"lower": 0, "upper": 0},
                     "min_distinct_exercises_per_week": 0,
                     "min_pattern_categories_per_week": 0,
                     "max_sessions_per_exercise_per_week": 99,
                     "min_loaded_flexion_exercises_per_week": 0,
                     "min_flexion_share_of_core_sets": 0.0,
                     "min_flexion_sets_per_week": 0}
        proc = _run_render(
            {"today": "2026-08-02", "core_week_spec": toothless},
            _PLAN_CORE_DEFICIENT)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("distinct core exercises", proc.stderr)

    def test_the_renderer_does_not_read_the_specs_out_of_the_payload(self) -> None:
        # Structural guard on the ownership decision. One keyword away
        # from silently reinstating the weakening vector.
        code = [ln for ln in RENDER_DASHBOARD.read_text(encoding="utf-8")
                .splitlines() if not ln.lstrip().startswith("#")]
        for gone in ("core_spec=", "arm_spec="):
            self.assertEqual([ln for ln in code if gone in ln], [],
                             f"the renderer passes {gone} again")
        self.assertTrue(any("payload_spec_errors(j)" in ln for ln in code))


class TierBudgetTests(unittest.TestCase):
    """The tier scaling used to be an untestable closure inside the CLI."""

    def test_no_base_budget_means_no_budget_check(self) -> None:
        self.assertIsNone(tier_budget_by_index({"tier": "D"}, None))
        self.assertIsNone(tier_budget_by_index(None, 0))

    def test_tier_a_is_a_rest_day(self) -> None:
        self.assertEqual(tier_budget_by_index({"tier": "A"}, 24)(0), 0)

    def test_a_reactive_deload_halves_the_whole_week(self) -> None:
        f = tier_budget_by_index({"tier": "C", "label": "reactive_deload"}, 24)
        self.assertEqual([f(0), f(3)], [12, 12])

    def test_a_downgrade_trims_only_until_the_expected_rebound(self) -> None:
        # The defect a global scale caused: later full-volume sessions
        # judged against the shrunken early-session budget and flagged
        # "over", which invites a coach to trim a correct session.
        f = tier_budget_by_index(
            {"tier": "C", "label": "downgrade",
             "expected_rebound_by_session": 2}, 24)
        self.assertEqual([f(0), f(1), f(2), f(3)], [14, 14, 24, 24])

    def test_a_normal_session_keeps_the_full_budget(self) -> None:
        self.assertEqual(tier_budget_by_index({"tier": "E"}, 24)(0), 24)


# ------------------------------------------------- deload vs Tier C split
# A half-volume week. Every session under-dosed on core, arms at 2 sets
# each, and ONE core movement repeated in all three sessions — so the
# volume axis and the diversity axis are both tripped, by one plan, and
# a test can watch them separate.
_PLAN_HALF_VOLUME_ONE_CORE = _HEAD + "".join([
    _workout("1: LOWER A + CORE",
             "Barbell Back Squat: 90kgx8",
             "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
             "Incline Dumbbell Curl: 14kgx10",
             "Cable Tricep Pushdown: 25kgx10",
             "Calf Raise Machine: 55kgx10-12"),
    _workout("2: UPPER A + CORE",
             "Dumbbell Flat Bench Press: 50kgx8",
             "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
             "Bayesian Cable Curl: 14kgx10",
             "Cable Overhead Tricep Extension: 29kgx10",
             "Cable Lateral Raise: 14kgx10"),
    _workout("3: LOWER B + CORE",
             "Leg Press: 200kgx10",
             "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
             "Hip Adductor Machine: 50kgx12"),
])

# Only the ABSOLUTE flexion floor is a volume finding. The SHARE half of
# the same rule is structural and must survive a deload — see
# `render_validators._core_week_findings`.
_VOLUME_MARKERS = ("under-allocated", "floor is 6", "loaded flexion",
                   "flexion sets across the plan", "no core exercise")
_DIVERSITY_MARKERS = ("distinct core exercises", "core pattern categories",
                      "appears in")


class DeloadVolumeReliefTests(unittest.TestCase):
    """A legitimate deload has to be authorable.

    The new weekly specs made it impossible: the real 2026-07-13 plan —
    a deliberate, correct half-volume week — collected nine blocking
    errors, six of them for containing less work, which is what a deload
    IS. `workout_set_budget_warnings` had always known this ("confirm
    this is an intentional deload"); the new specs contradicted it.

    The split is by cost. A floor on how MUCH work costs fatigue to
    satisfy, so a deload demotes it. A floor on how MANY DIFFERENT
    movements costs nothing — three sessions at two core sets each still
    allows three distinct movements across three categories — so a
    deload does not.
    """

    def _run(self, plan, **kw):
        return validate_workout_plan(plan, core_spec=CORE_WEEK_SPEC,
                                     arm_spec=ARM_WEEK_SPEC, **kw)

    def test_a_deload_demotes_volume_floors_to_warnings(self) -> None:
        errors, _ = self._run(_PLAN_HALF_VOLUME_ONE_CORE)
        blocked = [e for e in errors if any(m in e for m in _VOLUME_MARKERS)]
        self.assertTrue(blocked, "expected volume findings without relief")

        errors, warnings = self._run(_PLAN_HALF_VOLUME_ONE_CORE,
                                     deload_week=True)
        for e in errors:
            for marker in _VOLUME_MARKERS:
                self.assertNotIn(marker, e, f"volume finding still blocking: {e}")
        demoted = [w for w in warnings if "[advisory: deload week]" in w]
        self.assertEqual(len(demoted), len(blocked))

    def test_a_deload_still_blocks_on_diversity(self) -> None:
        # THE case that must not regress. A deload is not a licence to go
        # back to four sets of the same crunch.
        errors, _ = self._run(_PLAN_HALF_VOLUME_ONE_CORE, deload_week=True)
        self.assertTrue(errors, "a monotonous deload rendered clean")
        for marker in _DIVERSITY_MARKERS:
            self.assertTrue(any(marker in e for e in errors),
                            f"diversity axis {marker!r} went silent on a deload")

    def test_a_demoted_finding_says_why_it_was_demoted(self) -> None:
        # A reader must be able to tell a demoted finding from one that
        # is inherently advisory, and see what the deload is costing.
        _, warnings = self._run(_PLAN_HALF_VOLUME_ONE_CORE, deload_week=True)
        self.assertTrue(any(
            "under-allocated" in w and "[advisory: deload week]" in w
            for w in warnings))

    def test_tier_c_is_not_a_deload_and_keeps_every_volume_floor(self) -> None:
        # Tier C fires on poor systemic recovery. The cut belongs on the
        # systemically expensive work (compound volume), not on core and
        # direct arms — those are low-fatigue and are the chronically
        # under-dosed categories this build exists to protect. Halving
        # them on a bad-recovery day would re-create the under-dosing on
        # exactly the days a coach reaches for it.
        tier_c = {"tier": "C", "label": "downgrade",
                  "expected_rebound_by_session": 2}
        self.assertFalse(is_deload_week(tier_c))
        errors, _ = self._run(_PLAN_HALF_VOLUME_ONE_CORE,
                              deload_week=is_deload_week(tier_c))
        self.assertTrue(any("under-allocated" in e for e in errors))
        self.assertTrue(any("direct biceps sets" in e and "floor is 6" in e
                            for e in errors))
        self.assertTrue(any("direct triceps sets" in e and "floor is 6" in e
                            for e in errors))

    def test_tier_c_still_scales_the_set_budget(self) -> None:
        # The two mechanisms are separate on purpose: Tier C trims the
        # session-length budget (a warning) without touching the core and
        # arm floors (errors).
        f = tier_budget_by_index({"tier": "C", "label": "downgrade",
                                  "expected_rebound_by_session": 2}, 24)
        self.assertEqual(f(0), 14)
        self.assertFalse(is_deload_week({"tier": "C", "label": "downgrade"}))

    def test_is_deload_week_truth_table(self) -> None:
        for sr, expected in (
            ({"tier": "B", "label": "reactive_deload"}, True),
            ({"tier": "A", "label": "rest"},            True),
            ({"tier": "A"},                             True),
            ({"tier": "C", "label": "downgrade"},       False),
            ({"tier": "C", "label": "hold_load"},       False),
            ({"tier": "D", "label": "green"},           False),
            ({"tier": "E", "label": "over_recovered"},  False),
            ({},                                        False),
            (None,                                      False),
        ):
            with self.subTest(sr=sr):
                self.assertEqual(is_deload_week(sr), expected)

    def test_a_cadence_deload_is_not_visible_to_the_gate(self) -> None:
        # Documented limitation, pinned so it cannot be forgotten. A
        # deload driven by block age ships with `label: green`, so
        # `is_deload_week` says False and the caller must pass
        # `deload_week=True` itself. read_tracker owes us a flag.
        self.assertFalse(is_deload_week({"tier": "D", "label": "green"}))

    def test_the_docstring_quotes_the_measured_split(self) -> None:
        """The numbers in the docstring are a measurement, so they rot.

        They already had. The docstring claimed the reference deload
        collected "nine blocking errors, six of them for having less work
        in it" and implied the relief made it renderable. Measured on the
        real 2026-07-13 plan on both trackers: 8 strict, splitting 3 + 5,
        and the three that survive are core-PLACEMENT findings, so the
        plan still exits 2 with the relief applied. Pinned so the next
        spec change has to re-measure rather than re-assert.

        `RealPlanAcceptanceTests` re-derives these against the plan tree
        when it is present; this half runs on a bare checkout.
        """
        doc = validate_workout_plan.__doc__
        self.assertIn("8 blocking errors  ->  3 errors + 5 advisory", doc)
        self.assertNotIn("nine blocking errors", doc)
        self.assertIn("does not make that plan renderable", doc)

    def test_a_normal_week_is_unaffected_by_the_split(self) -> None:
        errors, warnings = self._run(_PLAN_COMPLIANT)
        self.assertEqual(errors, [])
        self.assertFalse(any("[advisory: deload week]" in w for w in warnings))

    def test_every_finding_carries_a_known_axis(self) -> None:
        # An untagged finding would crash the router; a MIStagged one
        # would silently become undemotable or, worse, demotable. Pin the
        # vocabulary.
        seen = set()
        for gen in (_core_session_findings(_PLAN_HALF_VOLUME_ONE_CORE),
                    _core_week_findings(_PLAN_HALF_VOLUME_ONE_CORE),
                    _arm_findings(_PLAN_HALF_VOLUME_ONE_CORE)):
            for axis, msg in gen:
                self.assertIn(axis, (AXIS_VOLUME, AXIS_STRUCTURE), msg)
                seen.add(axis)
        self.assertEqual(seen, {AXIS_VOLUME, AXIS_STRUCTURE})

    def test_a_core_overshoot_is_a_ceiling_and_never_demotes(self) -> None:
        # A deload reduces volume; it cannot produce an overshoot, so the
        # ceiling must not ride along with the floors.
        plan = _HEAD + _workout(
            "1: UPPER A + CORE",
            "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
            "Ab Crunch Machine: 30kgx12 /// 30kgx12 /// 30kgx12 /// 30kgx12 /// 30kgx12",
            "Cable Lateral Raise: 14kgx10 /// 14kgx10")
        findings = dict((msg, axis) for axis, msg
                        in _core_session_findings(plan))
        over = [m for m in findings if "over-allocated" in m]
        self.assertTrue(over, "expected an over-allocation finding")
        self.assertEqual(findings[over[0]], AXIS_STRUCTURE)


class DoseAwareDistinctFloorTests(unittest.TestCase):
    """A diversity axis binds only while obeying it leaves a real dose.

    "Diversity costs no fatigue" holds at 6 sets across 3 movements (2
    each) and fails at 2 sets across 2 movements (1 each, which is worse
    training than one 2-set dose). So the floor is
    ``min(spec, sets // MIN_SETS_PER_DISTINCT_EXERCISE)``, computed from
    the sets actually in the plan — not a deload carve-out.

    The shape is what makes it ungameable: cutting sets lowers the
    distinct-exercise requirement but leaves the VOLUME floors blocking
    on a normal week, so a coach shrinking a week to escape the
    diversity axis walks straight into the volume axis.
    """

    def test_the_floor_formula(self) -> None:
        for spec_min, sets, expected in (
            (3, 0, 0), (3, 1, 0), (3, 2, 1), (3, 4, 2),
            (3, 6, 3), (3, 20, 3),          # never above the spec
            (2, 2, 1), (2, 4, 2), (2, 100, 2),
            (0, 10, 0),
        ):
            with self.subTest(spec_min=spec_min, sets=sets):
                self.assertEqual(
                    _dose_aware_distinct_floor(spec_min, sets), expected)

    def test_two_arm_sets_do_not_have_to_become_two_one_set_doses(self) -> None:
        # The reported case: 2 direct sets on 1 movement. 2 // 2 = 1, so
        # the distinct axis is satisfied and only the volume floor
        # remains, which a deload demotes.
        plan = _HEAD + _workout(
            "1: UPPER A + CORE",
            "Dumbbell Flat Bench Press: 50kgx8",
            "Ab Crunch Machine: 30kgx12 /// 30kgx12",
            "Incline Dumbbell Curl: 14kgx10 /// 14kgx10",
            "Cable Lateral Raise: 14kgx10")
        errors = arm_week_errors(plan)
        self.assertFalse(any("distinct direct biceps" in e for e in errors),
                         errors)
        self.assertTrue(any("2 direct biceps sets" in e for e in errors))

    def test_enough_arm_volume_re_arms_the_distinct_axis(self) -> None:
        # 6 sets on one movement is the case the axis exists for.
        plan = _HEAD + _workout(
            "1: UPPER A + CORE",
            "Dumbbell Flat Bench Press: 50kgx8",
            "Cable Tricep Pushdown: 25kgx10 /// 25kgx10 /// 25kgx10 /// 25kgx10 /// 25kgx10 /// 25kgx10",
            "Cable Lateral Raise: 14kgx10")
        errors = arm_week_errors(plan)
        self.assertTrue(any("1 distinct direct triceps exercises" in e
                            for e in errors), errors)
        self.assertFalse(any("direct triceps sets across" in e for e in errors))

    def test_the_monotony_case_is_not_rescued_by_the_relief(self) -> None:
        # THE important check. 6 core sets => capacity 3 => the spec's 3
        # stands in full, and the plan supplies 1.
        errors = validate_workout_plan(
            _PLAN_HALF_VOLUME_ONE_CORE, core_spec=CORE_WEEK_SPEC,
            arm_spec=ARM_WEEK_SPEC, deload_week=True)[0]
        self.assertTrue(any("distinct core exercises" in e for e in errors))
        self.assertTrue(any("core pattern categories" in e for e in errors))
        self.assertTrue(any("appears in 3 sessions" in e for e in errors))

    def test_the_relaxed_message_says_why_it_relaxed(self) -> None:
        plan = _HEAD + _workout(
            "1: UPPER A + CORE",
            "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
            "Ab Crunch Machine: 30kgx12 /// 30kgx12",
            "Cable Lateral Raise: 14kgx10")
        # 2 core sets => the distinct floor caps at 1, so the axis is
        # silent; but the category axis, also capped at 1, is satisfied
        # too. Force the message by asking for a plan with 4 core sets on
        # one movement, where the floor lands at 2.
        plan = _HEAD + "".join([
            _workout("1: LOWER A + CORE",
                     "Barbell Back Squat: 90kgx8",
                     "Ab Crunch Machine: 30kgx12 /// 30kgx12"),
            _workout("2: UPPER A + CORE",
                     "Dumbbell Flat Bench Press: 50kgx8",
                     "Ab Crunch Machine: 30kgx12 /// 30kgx12"),
        ])
        errors = [e for e in core_week_errors(plan)
                  if "distinct core exercises" in e]
        self.assertTrue(errors)
        self.assertIn("requires 2", errors[0])
        self.assertIn("spec floor 3", errors[0])
        self.assertIn("capped by 4 core sets", errors[0])

    def test_a_week_with_no_core_at_all_still_faces_the_full_spec(self) -> None:
        # The one place the relaxation must NOT apply. Core's per-session
        # absence findings are AXIS_VOLUME and demote on a deload, so if
        # the weekly axis also relaxed at zero, a "deload" listing three
        # core movements at zero credited sets would clear every check.
        plan = _HEAD + _workout(
            "1: LOWER A + CORE",
            "Barbell Back Squat: 90kgx8 /// 90kgx8",
            "Plank: 5s",
            "Bird Dog: 10",
            "Side Plank: 5s",
            "Calf Raise Machine: 55kgx12 /// 55kgx12")
        errors, _ = validate_workout_plan(plan, core_spec=CORE_WEEK_SPEC,
                                          arm_spec=ARM_WEEK_SPEC,
                                          deload_week=True)
        self.assertTrue(any("0 distinct core exercises" in e for e in errors),
                        errors)
        self.assertTrue(any("the core spec requires 3" in e for e in errors))

    def test_the_session_cap_relaxes_only_when_obeying_it_forces_a_bad_dose(self) -> None:
        # 3 sessions x 1 core set. Obeying the 2-session cap means
        # splitting into 2 movements out of 3 total sets, so one of them
        # gets a 1-set dose. Capacity 1 < the 2 movements the cap needs,
        # so the cap stands down.
        thin = _HEAD + "".join([
            _workout(f"{i}: LOWER A + CORE",
                     "Barbell Back Squat: 90kgx8",
                     "Ab Crunch Machine: 30kgx12")
            for i in (1, 2, 3)])
        self.assertFalse(any("appears in 3 sessions" in e
                             for e in core_week_errors(thin)),
                         core_week_errors(thin))
        # Double the core dose and the split becomes affordable, so the
        # cap binds again. Same plan shape, more volume.
        thick = _HEAD + "".join([
            _workout(f"{i}: LOWER A + CORE",
                     "Barbell Back Squat: 90kgx8",
                     "Ab Crunch Machine: 30kgx12 /// 30kgx12")
            for i in (1, 2, 3)])
        self.assertTrue(any("appears in 3 sessions" in e
                            for e in core_week_errors(thick)))

    def test_the_normal_week_regression_is_unchanged(self) -> None:
        # 8 core sets on the 07-18 shape: capacity 4, so every axis is at
        # full strength and the five findings are untouched.
        errors, _ = validate_workout_plan(_PLAN_CORE_DEFICIENT,
                                          core_spec=CORE_WEEK_SPEC,
                                          arm_spec=ARM_WEEK_SPEC)
        self.assertTrue(any("distinct core exercises" in e for e in errors))
        self.assertTrue(any("core pattern categories" in e for e in errors))


class DeloadPrescribedHandshakeTests(unittest.TestCase):
    """`is_deload_week` reads `block.deload_prescribed`, and it is there.

    The handshake is complete: `blocks.block_payload` writes
    ``deload_prescribed`` and ``deload_source`` on every read, so a
    CADENCE deload — which ships with ``label: green`` and tells the
    recovery gate nothing — reaches the validator without anyone passing
    ``deload_week=True`` by hand. `test_the_payload_actually_emits_it`
    is what keeps the docstrings that say so honest.
    """

    def test_the_payload_actually_emits_it(self) -> None:
        # End to end through the real CLI against the committed fixture
        # tracker, because "the validator reads a key" and "the payload
        # writes that key" are two claims and only the second one closed
        # the gap. Asserted on presence and type, not value: the fixture
        # is free to change what it prescribes.
        fixtures = SKILLS_ROOT / "tests" / "fixtures"
        env = dict(os.environ, WORKOUT_TRACKER_ROOT=str(fixtures))
        proc = subprocess.run(
            [sys.executable, "workout-coach/scripts/read_tracker.py",
             "--person", "person_a", "--today", "2026-05-28"],
            cwd=SKILLS_ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        block = json.loads(proc.stdout).get("block")
        self.assertIsInstance(block, dict)
        self.assertIn("deload_prescribed", block)
        self.assertIsInstance(block["deload_prescribed"], bool)
        self.assertIn("deload_source", block)
        # And the two clocks stay separate keys, not one conflated flag.
        self.assertIn("boundary_due", block)

    def test_the_upstream_gap_note_is_gone(self) -> None:
        # The docstrings recorded the gap as OPEN, which sends the next
        # reader to build a field that already ships. Doc drift in the
        # direction of "this is missing" costs the same as drift in the
        # direction of "this works".
        import inspect
        src = inspect.getsource(render_validators)
        self.assertNotIn("UPSTREAM GAP", src)
        self.assertNotIn("the field is being\n    added by separate work", src)
        self.assertIn("deload_source", src)

    def test_the_block_flag_is_read_when_present(self) -> None:
        green = {"tier": "D", "label": "green"}
        self.assertTrue(is_deload_week(green, {"deload_prescribed": True}))

    def test_absent_or_false_is_not_a_deload(self) -> None:
        green = {"tier": "D", "label": "green"}
        for block in (None, {}, {"deload_prescribed": False},
                      {"boundary_due": True}):
            with self.subTest(block=block):
                self.assertFalse(is_deload_week(green, block))

    def test_the_gate_alone_still_decides_a_reactive_deload(self) -> None:
        self.assertTrue(is_deload_week({"label": "reactive_deload"}, None))
        self.assertTrue(is_deload_week({"label": "reactive_deload"},
                                       {"deload_prescribed": False}))

    def test_the_renderer_passes_the_block_in(self) -> None:
        src = RENDER_DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("is_deload_week(session_rec, block)", src)


# ------------------------------------------------------- heading grammar
class WorkoutHeadingGrammarTests(unittest.TestCase):
    """One grammar for what a workout heading is.

    The validator matched `^## Workout` and nothing else while
    `adherence` also accepted `## Deload Session N:` and `## Session N:`.
    Two OPPOSITE failures came out of that single inconsistency: a
    deload plan written with the first grammar was judged against
    full-volume specs, and one written with the second bypassed the core
    and arm checks entirely.
    """

    def _titles(self, text):
        return list(_iter_workout_exercise_bullets(text))

    def test_the_deload_and_session_grammars_are_recognised(self) -> None:
        for heading in ("## Workout 1: PUSH",
                        "## Deload Session 1: PUSH",
                        "## Session 1: PUSH"):
            with self.subTest(heading=heading):
                titles = self._titles(
                    f"{heading}\n- Dumbbell Flat Bench Press: 50kgx8\n")
                self.assertEqual(len(titles), 1, heading)
                self.assertIn("PUSH", titles[0])

    def test_the_legacy_unnumbered_form_still_works(self) -> None:
        # `## Workout A: PUSH` predates adherence's `\d+` requirement.
        # Losing it would silently disable every check on that workout,
        # which is the failure mode this workstream removes.
        self.assertEqual(
            self._titles("## Workout A: PUSH\n- Dumbbell Flat Bench Press: 50kgx8\n"),
            ["Workout A: PUSH"])

    def test_cardio_and_prose_headings_still_close_the_scope(self) -> None:
        text = ("## Workout 1: PUSH\n"
                "- Dumbbell Flat Bench Press: 50kgx8\n"
                "## Cardio 1: Intervals\n"
                "- Work: 5 x 3 min at 165bpm\n"
                "## Notes\n"
                "- Sleep: 8h\n")
        self.assertEqual(self._titles(text), ["Workout 1: PUSH"])

    def test_the_validator_recognises_everything_the_ledger_does(self) -> None:
        # Parity, asserted through the public parser rather than the
        # private regex, so this survives a refactor on either side.
        from workout_coach.lib.adherence import parse_plan
        corpus = (
            "## Workout 1: LOWER A + CORE\n- Leg Press: 200kgx10\n\n"
            "## Deload Session 2: PUSH\n- Dumbbell Flat Bench Press: 50kgx8\n\n"
            "## Session 3: PULL\n- Cable Lat Pulldown: 65kgx8\n\n"
            "## Cardio 1: Intervals\n- Work: 5 x 3 min\n"
        )
        ledger = {w["title"] for w in parse_plan(corpus, "2026-08-02")["workouts"]}
        validator = {t.split(":", 1)[1].strip() for t in self._titles(corpus)}
        self.assertTrue(ledger, "corpus parsed to nothing")
        self.assertTrue(
            ledger <= validator,
            f"headings the ledger sees but the validator does not: "
            f"{sorted(ledger - validator)}")

    def test_a_session_with_no_working_sets_is_not_a_strength_session(self) -> None:
        # `## Session 1: Zone 2 cardio + mobility` is a real heading and
        # now falls inside the grammar. Asking it for a core budget
        # invents a violation. Not an escape hatch: a zero-set session
        # contributes zero to every weekly axis too.
        text = ("## Session 1: Zone 2 cardio + mobility (today)\n"
                "- Zone 2 cardio: 45-60 min at ~117 bpm\n"
                "- Mobility: 15 min\n")
        self.assertEqual(list(_core_session_findings(text)), [])

    def test_a_session_with_working_sets_is_still_judged(self) -> None:
        text = ("## Session 2: LEGS\n"
                "- Leg Press: 200kgx10 /// 200kgx10 /// 200kgx10\n")
        findings = list(_core_session_findings(text))
        self.assertTrue(any("no core exercise" in m for _a, m in findings))


# ---------------------------------------------------------------- task 2
def _slot(pos, name, tag="rotating", **kw):
    return dict(position=pos, exercise=name, tag=tag, **kw)


class BlockRotationWiringTests(unittest.TestCase):
    """``rotation_diff_errors`` reaching a caller for the first time."""

    def setUp(self) -> None:
        render_validators._pattern_catalog.cache_clear()

    tearDown = setUp

    _PREV_ARTIFACT = {
        "block_id": "2026-06-20", "started": "2026-06-20",
        "sessions": {"lower_a": [
            _slot(1, "Barbell Back Squat", "anchor"),
            _slot(2, "Ab Crunch Machine"),
        ]},
    }

    # Same session type, same slot positions, the rotating slot unchanged.
    _PLAN_UNROTATED = _HEAD + _workout(
        "1: LOWER A + CORE",
        "Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8",
        "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12")

    def test_an_unchanged_rotating_slot_is_a_blocking_error(self) -> None:
        errors = block_rotation_errors(
            self._PLAN_UNROTATED, self._PREV_ARTIFACT, plan_date="2026-08-02")
        self.assertTrue(any("unchanged from the previous block" in e
                            for e in errors), errors)

    def test_it_surfaces_through_validate_workout_plan(self) -> None:
        # Surfaces as a WARNING this release — see `RotationIsAdvisoryTests`
        # for the switch. What this test pins is that it surfaces at all
        # from the composed entry point, not just from the bare function.
        _, warnings = validate_workout_plan(
            self._PLAN_UNROTATED, prev_block=self._PREV_ARTIFACT,
            plan_date="2026-08-02")
        self.assertTrue(any("unchanged from the previous block" in w
                            for w in warnings), warnings)
        # And is silent when no previous block was supplied, which is the
        # first-run case: nothing to differ from is not a violation.
        errors_no_prev, warnings_no_prev = validate_workout_plan(
            self._PLAN_UNROTATED)
        self.assertFalse(any("previous block" in m
                             for m in errors_no_prev + warnings_no_prev))

    def test_it_reads_the_payloads_flat_slot_list(self) -> None:
        # `block_payload` flattens sessions into `slots` with a
        # `session_type` per entry. That is what the renderer receives.
        payload_block = {
            "source": "artifact", "block_id": "2026-06-20",
            "started": "2026-06-20",
            "slots": [
                {"session_type": "lower_a", "position": 1,
                 "exercise": "Barbell Back Squat", "tag": "anchor"},
                {"session_type": "lower_a", "position": 2,
                 "exercise": "Ab Crunch Machine", "tag": "rotating"},
            ],
        }
        errors = block_rotation_errors(
            self._PLAN_UNROTATED, payload_block, plan_date="2026-08-02")
        self.assertTrue(any("unchanged from the previous block" in e
                            for e in errors), errors)

    def test_a_block_derived_from_this_very_plan_is_not_diffed(self) -> None:
        # `block_payload` bootstraps from the newest plan on disk. On a
        # re-render that plan IS the one being validated, and diffing it
        # against itself reports every rotating slot as unchanged. A
        # tautology is not a finding.
        same_day = dict(self._PREV_ARTIFACT, started="2026-08-02")
        self.assertEqual(
            block_rotation_errors(self._PLAN_UNROTATED, same_day,
                                  plan_date="2026-08-02"), [])
        # ...but a genuinely new plan date still gets checked.
        #
        # Date bumped 2026-08-02, and NOT because this rule changed.
        # `blocks._boundary` gates rotation on the block being at its
        # boundary — `boundary_due`, or BLOCK_MAX_WEEKS of age. A plan one
        # week after `started` is mid-block, so it correctly produces no
        # rotation finding, and the old `2026-08-09` asserted a finding
        # the W5 rule does not make. What this test is actually about is
        # the SELF-DIFF short circuit above, so the second date just has
        # to clear the boundary; it is written as a multiple of
        # BLOCK_MAX_WEEKS rather than a literal so the coupling is
        # visible if that ceiling moves again.
        from datetime import date, timedelta
        from workout_coach.lib.blocks import BLOCK_MAX_DAYS
        past_boundary = (date(2026, 8, 2)
                         + timedelta(days=BLOCK_MAX_DAYS + 7)).isoformat()
        self.assertTrue(block_rotation_errors(
            self._PLAN_UNROTATED, same_day, plan_date=past_boundary))

    def test_no_previous_block_is_silent(self) -> None:
        for empty in (None, {}, {"slots": []}, {"sessions": {}}):
            self.assertEqual(
                block_rotation_errors(self._PLAN_UNROTATED, empty,
                                      plan_date="2026-08-02"), [],
                f"expected silence for {empty!r}")

    def test_a_document_with_no_prescription_is_silent(self) -> None:
        self.assertEqual(
            block_rotation_errors(_NOT_A_PLAN, self._PREV_ARTIFACT,
                                  plan_date="2026-08-02"), [])

    def test_the_catalog_is_built_once_and_passed_in(self) -> None:
        # `rotation_diff_errors(catalog=None)` reparses exercises-database.md
        # on every call. `Skills/CLAUDE.md` names reparsing static markdown
        # inside one command as the first waste to remove.
        import workout_coach.lib.blocks as blocks
        real = blocks.load_pattern_catalog
        calls = {"n": 0}

        def counting(db=None):
            calls["n"] += 1
            return real(db)

        seen = {}
        real_diff = blocks.rotation_diff_errors

        def capturing(prev, new, catalog=None):
            seen["catalog"] = catalog
            return real_diff(prev, new, catalog)

        with patch.object(blocks, "load_pattern_catalog", counting), \
             patch.object(blocks, "rotation_diff_errors", capturing):
            block_rotation_errors(self._PLAN_UNROTATED, self._PREV_ARTIFACT,
                                  plan_date="2026-08-02")
            block_rotation_errors(self._PLAN_UNROTATED, self._PREV_ARTIFACT,
                                  plan_date="2026-08-03")
        self.assertEqual(calls["n"], 1)
        self.assertIsNotNone(seen["catalog"])

    def test_the_payload_block_reaches_the_rotation_check(self) -> None:
        """`prev_block=block` is wired, proved through the CLI.

        `block` appeared in no `render_dashboard` test payload, so
        deleting ``prev_block=block`` from the call kept the suite green
        — the same defect class as the three holes this file opened with:
        a computed finding with no caller. Every other rotation test
        calls `block_rotation_errors` or `validate_workout_plan`
        directly, which is exactly the level the wiring bug lives above.

        The plan is the one that renders CLEAN with no block, so the
        FINDING appears on the presence of the block alone. It appears on
        stderr rather than in the return code because rotation is
        advisory this release (`BLOCK_ROTATION_ENFORCED`); the wiring
        this test exists to pin is unchanged, and demoting a finding to a
        warning must not be allowed to look like deleting the call.
        """
        base = {"today": "2026-08-02", "target_working_sets": 24}

        without = _run_render(base, _PLAN_COMPLIANT)
        self.assertEqual(without.returncode, 0, without.stderr)
        self.assertNotIn("unchanged from the previous block", without.stderr)

        with_block = _run_render(dict(base, block=_ROTATION_PREV_BLOCK),
                                 _PLAN_COMPLIANT)
        self.assertIn("unchanged from the previous block", with_block.stderr)

    def test_a_genuinely_rotated_slot_passes(self) -> None:
        prev = new_block("2026-06-20", {"lower_a": [
            _slot(1, "Barbell Back Squat", "anchor"),
            _slot(2, "Ab Crunch Machine"),
        ]})
        plan = _HEAD + _workout(
            "1: LOWER A + CORE",
            "Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8",
            "Cable Pallof Press: 15kgx10 /// 15kgx10\n"
            "  — superset with the squat above")
        self.assertEqual(
            block_rotation_errors(plan, prev, plan_date="2026-08-02"), [])


class RotationIsAdvisoryTests(unittest.TestCase):
    """Rotation warns; core and arm specs still block.

    Stage one ships the specs whose inputs are the tracker's own data.
    Rotation reads the coach-authored plan markdown and the block derived
    from it, which is where every defect three reviewers found actually
    lived, so it is demoted to advisory for this release and re-armed by
    one named constant.

    Both halves are pinned here on purpose. A demotion is one edit away
    from being a hole: the failure mode is not "rotation warns" but
    "everything warns", and the specs that answer the user's original
    complaint are the ones that must not move.
    """

    _BASE = {"today": "2026-08-02", "target_working_sets": 24}

    def test_a_rotation_only_violation_renders(self) -> None:
        proc = _run_render(dict(self._BASE, block=_ROTATION_PREV_BLOCK),
                           _PLAN_COMPLIANT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("workout_md validation error:", proc.stderr)
        # Demoted, not dropped: the finding still reaches stderr, and it
        # is tagged so a reader can tell it is not a gate.
        self.assertIn("workout_md plan warning:", proc.stderr)
        self.assertIn("unchanged from the previous block", proc.stderr)
        self.assertIn(render_validators.ROTATION_ADVISORY_TAG, proc.stderr)

    def test_a_core_spec_violation_still_exits_2(self) -> None:
        # Same block payload, so rotation findings are present too. The
        # core spec is what decides the exit code.
        proc = _run_render(dict(self._BASE, block=_ROTATION_PREV_BLOCK),
                           _PLAN_CORE_DEFICIENT)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("workout_md validation error:", proc.stderr)
        self.assertIn("distinct core exercises", proc.stderr)

    def test_an_arm_spec_violation_still_exits_2(self) -> None:
        plan = _HEAD + "".join([
            _workout("1: LOWER A + CORE",
                     "Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8",
                     "Ab Crunch Machine: 30kgx10-12 /// 30kgx10-12",
                     "Plank: 45s /// 45s",
                     "Calf Raise Machine: 55kgx10-12 /// 55kgx10-12"),
            _workout("2: UPPER A + CORE",
                     "Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8",
                     "Cable Pallof Press: 15kgx10 /// 15kgx10",
                     "Cable Lateral Raise: 14kgx10 /// 14kgx10"),
        ])
        proc = _run_render(dict(self._BASE, block=_ROTATION_PREV_BLOCK), plan)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("direct biceps sets", proc.stderr)

    def test_the_switch_is_one_named_constant(self) -> None:
        """Flipping the constant is the whole of stage two on this side.

        If re-arming rotation ever needs a second edit, this fails, which
        is the point: the switch is only worth having while it is one
        branch in one function.
        """
        self.assertFalse(render_validators.BLOCK_ROTATION_ENFORCED)
        args = dict(prev_block=_ROTATION_PREV_BLOCK, plan_date="2026-08-02")

        errors, warnings = validate_workout_plan(_PLAN_COMPLIANT, **args)
        self.assertEqual(errors, [])
        rotation = [w for w in warnings
                    if render_validators.ROTATION_ADVISORY_TAG in w]
        self.assertTrue(rotation, warnings)

        with patch.object(render_validators, "BLOCK_ROTATION_ENFORCED", True):
            on_errors, on_warnings = validate_workout_plan(
                _PLAN_COMPLIANT, **args)
        self.assertTrue(any("unchanged from the previous block" in e
                            for e in on_errors), on_errors)
        # Enforced findings carry no advisory tag: the tag says
        # "computed but not a gate", and once it is a gate that is false.
        self.assertEqual(
            [w for w in on_warnings
             if render_validators.ROTATION_ADVISORY_TAG in w], [])

    def test_the_findings_are_the_same_either_way(self) -> None:
        """Demotion changes the ROUTE, not the rule.

        The demotion must not quietly narrow what rotation checks, or
        stage two turns on a weaker rule than the one it turned off.
        """
        bare = block_rotation_errors(_PLAN_COMPLIANT, _ROTATION_PREV_BLOCK,
                                     plan_date="2026-08-02")
        self.assertTrue(bare)
        _, warnings = validate_workout_plan(
            _PLAN_COMPLIANT, prev_block=_ROTATION_PREV_BLOCK,
            plan_date="2026-08-02")
        tagged = [w[:-len(render_validators.ROTATION_ADVISORY_TAG) - 1]
                  for w in warnings
                  if w.endswith(render_validators.ROTATION_ADVISORY_TAG)]
        self.assertEqual(tagged, bare)


# ---------------------------------------------------------------- task 3
class SessionTypeSingleSourceTests(unittest.TestCase):
    """One concept, one source of truth: which sessions are lower days.

    That answer drives the D3 core budget (4 sets lower / 2 upper), and
    it used to be answered twice — by `adherence.session_type_from_title`
    for the ledger and by a private regex pair here for the validator.
    """

    def test_the_private_heading_regexes_are_gone(self) -> None:
        import inspect
        src = inspect.getsource(render_validators)
        self.assertNotIn("_LOWER_DAY_RE", src)
        self.assertNotIn("_UPPER_DAY_RE", src)

    def test_bounds_track_the_public_classifier(self) -> None:
        lower = CORE_WEEK_SPEC["sets_per_session"]["lower"]
        upper = CORE_WEEK_SPEC["sets_per_session"]["upper"]
        tol = CORE_WEEK_SPEC["session_set_overshoot_tolerance"]
        # `full` and unclassified take the LOWER-day band. See
        # `FullBodySessionFloorTests` below for why that is not "guessing".
        assumed = (max(lower, upper), max(lower, upper) + tol)
        cases = {
            "1: LOWER A + CORE":  (lower, lower + tol),
            "3: LEGS":            (lower, lower + tol),
            "2: LEGS + ADDUCTORS + CALVES": (lower, lower + tol),
            "4: UPPER B + CORE":  (upper, upper + tol),
            "1: PUSH":            (upper, upper + tol),
            "2: PULL":            (upper, upper + tol),
            "3: FULL BODY C":     assumed,
            "5: Mobility":        assumed,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(_session_core_set_bounds(title, CORE_WEEK_SPEC),
                                 expected)
                # The upper band is the only one a heading has to EARN, so
                # it is the only one whose bounds identify a session type.
                stype = session_type_from_title(title)
                self.assertEqual(
                    expected == (upper, upper + tol), stype == "upper")


class FullBodySessionFloorTests(unittest.TestCase):
    """A `full` or unreadable heading must not set its own core floor.

    THE HOLE, closed 2026-08-02. `_session_core_set_bounds` returned
    ``min(lower, upper)`` as the floor for a session the classifier
    places as `full` or cannot place at all, on the reasoning that a
    loose bound beats a fabricated one. That reasoning is sound for a
    CEILING and backwards for a FLOOR.

    `session_type_from_title` answers `full` for any heading naming both
    halves, and the heading is free text the coach writes. So the coach
    chose its own core budget by choosing a session name: the same
    bullets that were "2 core sets, under-allocated" under
    ``## Workout 1: LOWER A + CORE`` rendered clean under
    ``## Workout 1: FULL BODY A``.
    """

    def setUp(self) -> None:
        self.lower = CORE_WEEK_SPEC["sets_per_session"]["lower"]
        self.upper = CORE_WEEK_SPEC["sets_per_session"]["upper"]
        self.tol = CORE_WEEK_SPEC["session_set_overshoot_tolerance"]

    def test_full_and_unclassified_take_the_lower_day_floor(self) -> None:
        expected = (self.lower, self.lower + self.tol)
        for title in ("Workout 7: LOWER + PUSH",
                      "Workout 3: FULL BODY C",
                      "Workout 8: FULL BODY (legs focus)"):
            with self.subTest(title=title):
                self.assertEqual(session_type_from_title(title), "full")
                self.assertEqual(
                    _session_core_set_bounds(title, CORE_WEEK_SPEC), expected)
        # And a heading the classifier cannot place at all.
        self.assertIsNone(session_type_from_title("Workout 5: Mobility"))
        self.assertEqual(
            _session_core_set_bounds("Workout 5: Mobility", CORE_WEEK_SPEC),
            expected)

    def test_the_floor_is_the_larger_budget_not_the_smaller(self) -> None:
        # Direct pin on the direction, so a future `min(...)` cannot slip
        # back in behind a passing suite.
        floor, _ceiling = _session_core_set_bounds("Workout 1: FULL BODY A",
                                                   CORE_WEEK_SPEC)
        self.assertEqual(floor, max(self.lower, self.upper))
        self.assertNotEqual(floor, min(self.lower, self.upper))

    def test_renaming_a_session_full_body_no_longer_changes_the_verdict(self) -> None:
        # The acceptance case. Identical bullets, two headings.
        bullets = ("Barbell Back Squat: 90kgx8 /// 90kgx8",
                   "Ab Crunch Machine: 30kgx12 /// 30kgx12",
                   "Calf Raise Machine: 55kgx12 /// 55kgx12")
        as_lower = _HEAD + _workout("1: LOWER A + CORE", *bullets)
        as_full = _HEAD + _workout("1: FULL BODY A", *bullets)

        def dose(plan):
            return [m for _a, m in _core_session_findings(plan)
                    if "under-allocated" in m]

        self.assertTrue(dose(as_lower), "the lower-day floor stopped firing")
        self.assertEqual(len(dose(as_full)), len(dose(as_lower)),
                         "FULL BODY still buys a smaller core budget")

    def test_the_ceiling_stays_loose(self) -> None:
        # Only the floor was the hole. A full-body day may still carry a
        # lower day's worth of core without tripping the over-allocation
        # ceiling, which costs nothing to leave generous.
        _floor, ceiling = _session_core_set_bounds("Workout 1: FULL BODY A",
                                                   CORE_WEEK_SPEC)
        self.assertEqual(ceiling, max(self.lower, self.upper) + self.tol)


# ---------------------------------------------------------------- task 4
_BW_REASON_LABELS = {
    "no_readings":             ("no fasted weigh-ins in the window",
                                "no weigh-ins"),
    "too_few_readings":        ("too few weigh-ins to fit a rate",
                                "too few weigh-ins"),
    "window_shorter_than_min": ("window shorter than the 28-day minimum",
                                "window under 28d"),
    "no_time_variance":        ("all weigh-ins fall on one day",
                                "one day only"),
    "ci_straddles_zero":       ("95% interval spans zero",
                                "direction unresolved"),
}


class BodyweightReasonWiringTests(unittest.TestCase):
    """Both bodyweight surfaces get the reason, not just a null rate.

    "You have not measured enough" and "the data cannot resolve a
    direction" are different sentences with different remedies. The bug
    this replaces reported a confident loss while the user gained 1.7 kg,
    so a card that shrugs at a null is not an acceptable substitute.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.rd = _load_render_dashboard()

    def _html(self, block) -> str:
        j = {
            "today": "2026-08-02",
            "bodyweight_latest": {"kg": 78.4, "date": "2026-08-01"},
            "bodyweight_trend_kg_per_week": None,
            "bodyweight_trend": block,
            "bodyweight_weekly": [77.9, 78.1, 78.4],
            "health_metrics_weekly": [{"hrv_sdnn": 55, "resting_hr": 52,
                                       "wrist_temp_c": 36.1,
                                       "sleep_total_h": 7.2, "vo2max": 48.0}],
        }
        return self.rd.render(j, {"headline": "h", "cards": {}}, "# plan", "P")

    def test_every_reason_code_renders_its_own_words(self) -> None:
        seen = set()
        for reason, (body_comp, vitals) in _BW_REASON_LABELS.items():
            with self.subTest(reason=reason):
                html = self._html({"state": "unresolved", "reason": reason,
                                   "note": "n", "kg_per_week": None})
                self.assertIn(body_comp, html)
                self.assertIn(vitals, html)
                seen.add((body_comp, vitals))
        # Distinct wording per reason, or the distinction is decorative.
        self.assertEqual(len(seen), len(_BW_REASON_LABELS))

    def test_not_measured_enough_reads_differently_from_not_resolvable(self) -> None:
        too_few = self._html({"state": "unresolved",
                              "reason": "too_few_readings",
                              "note": "n", "kg_per_week": None})
        unresolved = self._html({"state": "unresolved",
                                 "reason": "ci_straddles_zero",
                                 "note": "n", "kg_per_week": None})
        self.assertIn("too few weigh-ins to fit a rate", too_few)
        self.assertNotIn("95% interval spans zero", too_few)
        self.assertIn("95% interval spans zero", unresolved)
        self.assertNotIn("too few weigh-ins to fit a rate", unresolved)

    def test_without_the_block_both_cards_fall_back_to_saying_nothing(self) -> None:
        # The pre-wiring behaviour, kept as the honest fallback: a card
        # with no reason must not invent one.
        html = self._html(None)
        self.assertIn("rate not resolvable from the current window", html)
        self.assertIn("trend unresolved", html)
        for body_comp, _vitals in _BW_REASON_LABELS.values():
            self.assertNotIn(body_comp, html)

    def test_a_resolved_rate_prints_the_number_on_both_cards(self) -> None:
        j = {
            "today": "2026-08-02",
            "bodyweight_latest": {"kg": 78.4},
            "bodyweight_trend_kg_per_week": 0.25,
            "bodyweight_trend": {"state": "resolved", "reason": None,
                                 "kg_per_week": 0.25},
            "bodyweight_weekly": [77.9, 78.1, 78.4],
            "health_metrics_weekly": [{"hrv_sdnn": 55}],
        }
        html = self.rd.render(j, {"headline": "h", "cards": {}}, "# plan", "P")
        self.assertIn("lean-bulk range", html)
        self.assertIn("+0.25 kg/wk", html)

    def test_the_renderer_passes_the_block_to_both_cards(self) -> None:
        # Structural guard: the two call sites are one keyword away from
        # silently reverting to the reason-less fallback.
        lines = RENDER_DASHBOARD.read_text(encoding="utf-8").splitlines()
        for call in ("card_body_comp_domain(", "card_vitals("):
            hits = [ln for ln in lines if call in ln and "import" not in ln]
            self.assertTrue(hits, f"no call site for {call}")
            for ln in hits:
                self.assertIn("bw_trend_block", ln,
                              f"{call} call site drops the trend block: {ln.strip()}")


# ---------------------------------------------------------------- task 5
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


class BlockPositionCardTests(unittest.TestCase):
    """The weekly block-position disclosure has somewhere to land.

    `SKILL.md` and `references/assessment-dashboard.md` both mark this
    REQUIRED every week, and there was no card and no `COACH_CARD_KEYS`
    entry, so the instruction pointed at nothing. The card exists to say
    out loud that mid-block repetition is deliberate: the SELECTION is
    held stable and the load and rep targets are what move. A week that
    looks like last week is the design working, and nobody had told the
    user that.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.rd = _load_render_dashboard()

    _MID_BLOCK = {"age_weeks": 1.1, "max_weeks": 6, "boundary_due": False,
                  "weeks_to_boundary": 4.9, "block_id": "2026-07-25",
                  "started": "2026-07-25"}

    _DOSE = {
        "from_plan": "2026-07-18", "to_plan": "2026-07-25",
        "carried_count": 4, "unchanged_count": 1, "unchanged_pct": 0.25,
        "target_max_pct": 0.40, "meets_target": True, "oscillating_count": 0,
        "carried": [
            {"exercise": "Barbell Back Squat", "dose_changed": True,
             "change_kind": "load_up", "generations_static": 0},
            {"exercise": "Leg Press", "dose_changed": True,
             "change_kind": "reps_up", "generations_static": 0},
            {"exercise": "Cable Lat Pulldown", "dose_changed": True,
             "change_kind": "load_up", "generations_static": 0},
            {"exercise": "Hip Adductor Machine", "dose_changed": False,
             "change_kind": "none", "generations_static": 3},
        ],
    }

    def _card(self, block, dose=None, coach=None) -> str:
        j = {"today": "2026-08-02", "block": block, "dose_staleness": dose,
             "health_metrics_weekly": [{"hrv_sdnn": 55}]}
        cards = {"block_position": coach} if coach else {}
        html = self.rd.render(j, {"headline": "h", "cards": cards},
                              "# plan", "P")
        start = html.index("<h2>Block position</h2>")
        return html[start:html.index("</section>", start)]

    @staticmethod
    def _text(fragment: str) -> str:
        import html as _html
        stripped = re.sub(r"<[^>]+>", " ", fragment)
        return re.sub(r"\s+", " ", _html.unescape(stripped)).strip()

    def test_it_renders_the_required_line(self) -> None:
        text = self._text(self._card(self._MID_BLOCK))
        # The exact disclosure the user asked for, in order: where they
        # are, why it looks the same, when it changes.
        self.assertIn("Week 2 of 6 in this block", text)
        self.assertIn("Exercise selection stays put by design, the load and "
                      "rep targets are what move.", text)
        self.assertIn("Next rotation in 4.9 weeks.", text)

    def test_the_week_number_is_the_week_they_are_in(self) -> None:
        # `age_weeks` is elapsed weeks: 0.0 on the day the block started,
        # so day one is week 1 and 1.1 elapsed weeks is week 2. Reading
        # it as the week number is off by one for the whole block.
        for age, expected in ((0.0, "Week 1 of 6"), (0.9, "Week 1 of 6"),
                              (1.1, "Week 2 of 6"), (5.4, "Week 6 of 6")):
            with self.subTest(age=age):
                block = dict(self._MID_BLOCK, age_weeks=age,
                             weeks_to_boundary=round(6 - age, 1))
                self.assertIn(expected, self._text(self._card(block)))

    def test_it_renders_on_a_week_where_nothing_changed(self) -> None:
        # The whole point. A card that only appears when there is news
        # cannot disclose that the absence of news is deliberate.
        stale = dict(self._DOSE, unchanged_count=4, unchanged_pct=1.0,
                     meets_target=False,
                     carried=[dict(c, dose_changed=False, change_kind="none")
                              for c in self._DOSE["carried"]])
        text = self._text(self._card(self._MID_BLOCK, stale))
        self.assertIn("Week 2 of 6 in this block", text)
        self.assertIn("Held at the same dose", text)
        self.assertIn("0 of 4 carried lifts", text)

    def test_boundary_due_replaces_the_countdown(self) -> None:
        block = dict(self._MID_BLOCK, boundary_due=True, age_weeks=6.0,
                     weeks_to_boundary=0.0)
        text = self._text(self._card(block))
        self.assertIn("Rotating this week.", text)
        self.assertNotIn("Next rotation in", text)

    def test_a_first_run_says_so_and_prints_no_countdown(self) -> None:
        # Two shapes reach here: no `block` key at all, and the block
        # payload `read_tracker` emits when nothing is on record, which
        # is a dict with a null `age_weeks`. Neither may invent a week
        # number or a countdown for a block that does not exist.
        for block in (None, {}, {"age_weeks": None, "max_weeks": 6,
                                 "boundary_due": True,
                                 "weeks_to_boundary": None,
                                 "source": "none"}):
            with self.subTest(block=block):
                text = self._text(self._card(block))
                self.assertIn("Block starts here", text)
                self.assertIn("with this plan", text)
                self.assertNotIn("Next rotation in", text)
                self.assertNotIn("Rotating this week", text)
                self.assertNotRegex(text, r"Week \d")

    def test_it_never_prints_a_date(self) -> None:
        # `block` deliberately carries a horizon and not a
        # `boundary_due_by` date: a payload anchored as-of cannot emit a
        # future-dated string without tripping the horizon rule. Deriving
        # one here from `today + weeks_to_boundary` would put it straight
        # back. `started` IS in the block and must not leak either.
        for block in (self._MID_BLOCK,
                      dict(self._MID_BLOCK, boundary_due=True),
                      None):
            with self.subTest(block=block):
                found = _ISO_DATE_RE.findall(self._card(block, self._DOSE))
                self.assertEqual(found, [], f"card printed a date: {found}")

    def test_the_dose_delta_says_what_actually_moved(self) -> None:
        # Without this, "selection is stable by design" reads as
        # "nothing changed", which is the opposite of true inside a
        # block.
        text = self._text(self._card(self._MID_BLOCK, self._DOSE))
        self.assertIn("3 of 4 carried lifts", text)
        self.assertIn("2 took weight", text)
        self.assertIn("1 took reps", text)
        self.assertIn("Held at the same dose", text)
        self.assertIn("Hip Adductor Machine", text)
        self.assertIn("Longest hold: 3 generations", text)

    def test_no_dose_history_is_stated_not_omitted(self) -> None:
        text = self._text(self._card(self._MID_BLOCK, None))
        self.assertIn("no earlier plan to compare", text)

    def test_the_coach_callout_key_is_wired(self) -> None:
        self.assertIn("block_position", render_validators.COACH_CARD_KEYS)
        # Not gated: the card renders every run, so a missing callout is
        # always a real gap and must warn.
        self.assertNotIn("block_position",
                         render_validators.GATED_COACH_CARD_KEYS)
        _, warnings = render_validators.validate_coach_reads(
            {"headline": "h", "cards": {}})
        self.assertTrue(any("cards.block_position" in w for w in warnings),
                        warnings)
        self.assertIn("holding at 90kg on purpose",
                      self._card(self._MID_BLOCK, self._DOSE,
                                 coach="Squat is holding at 90kg on purpose."))

    def test_the_renderer_passes_both_payload_blocks(self) -> None:
        # Structural guard, same class of bug as the bodyweight one
        # above: the card degrades silently to its first-run state if the
        # call site stops handing it `block`.
        lines = RENDER_DASHBOARD.read_text(encoding="utf-8").splitlines()
        hits = [ln for ln in lines
                if "card_block_position(" in ln and "import" not in ln]
        self.assertEqual(len(hits), 1, hits)
        self.assertIn('j.get("block")', hits[0])
        self.assertIn('j.get("dose_staleness")', hits[0])


# ---------------------------------------------------- real-data acceptance
_PLANS_DIR = SKILLS_ROOT.parent / "plans"


@unittest.skipUnless(_PLANS_DIR.is_dir(),
                     "uncommitted per-person plans are not present")
class RealPlanAcceptanceTests(unittest.TestCase):
    """The acceptance proof, run against the plan that started this.

    Skipped when the (deliberately uncommitted) plan tree is absent, so
    CI stays green on a bare checkout. No person name or profile fact is
    asserted here — only the shape of the findings.
    """

    def _newest_pair(self):
        """The two newest plan dates for the first person with two."""
        for person_dir in sorted(_PLANS_DIR.iterdir()):
            plans = sorted(person_dir.glob("*-workout.md")) \
                if person_dir.is_dir() else []
            if len(plans) >= 2:
                return plans[-2], plans[-1]
        return None, None

    def test_the_shipped_core_deficient_plan_is_now_rejected(self) -> None:
        # Every plan in the tree that repeats ONE core movement across
        # three or more sessions must now fail. Before this workstream
        # every one of them passed.
        offenders = 0
        for path in sorted(_PLANS_DIR.glob("*/*-workout.md")):
            errors, _ = validate_workout_plan(
                path.read_text(encoding="utf-8"))
            if any("distinct core exercises" in e for e in errors):
                offenders += 1
                self.assertTrue(
                    any("core pattern categories" in e for e in errors),
                    f"{path.name}: one core movement but pattern axis silent")
        self.assertGreater(offenders, 0,
                           "no plan in the tree trips the core spec; the "
                           "fixture this build was written against is gone")

    def test_a_real_half_volume_week_is_authorable_under_a_deload(self) -> None:
        # Finds the plan tree's own deload weeks by their set count
        # relative to their siblings, then asserts the split does its job
        # on real markdown: volume findings demote, structural ones do
        # not. Detection here is for FINDING a test fixture; the
        # validator itself never infers a deload from set counts.
        from workout_coach.lib.render_validators import (
            count_working_sets_per_workout)

        best = None
        for path in sorted(_PLANS_DIR.glob("*/*-workout.md")):
            text = path.read_text(encoding="utf-8")
            counts = list(count_working_sets_per_workout(text).values())
            if len(counts) < 2 or max(counts) > 14:
                continue
            strict, _ = validate_workout_plan(text, core_spec=CORE_WEEK_SPEC,
                                              arm_spec=ARM_WEEK_SPEC)
            volume = [e for e in strict if any(m in e for m in _VOLUME_MARKERS)]
            if volume:
                best = (path, text, strict, volume)
                break
        if best is None:
            self.skipTest("no low-volume week in the plan tree")
        path, text, strict, volume = best

        relaxed, warnings = validate_workout_plan(
            text, core_spec=CORE_WEEK_SPEC, arm_spec=ARM_WEEK_SPEC,
            deload_week=True)
        self.assertLess(len(relaxed), len(strict),
                        f"{path.name}: deload relief changed nothing")
        for e in relaxed:
            for marker in _VOLUME_MARKERS:
                self.assertNotIn(marker, e, f"{path.name}: {e}")
        self.assertEqual(
            len([w for w in warnings if "[advisory: deload week]" in w]),
            len(volume))
        # Structural findings are untouched by the relief.
        self.assertEqual(
            [e for e in strict if e not in volume], relaxed)

    def test_the_reference_deload_splits_as_the_docstring_claims(self) -> None:
        # The measurement behind `validate_workout_plan`'s deload
        # paragraph, re-derived rather than restated. Both trackers'
        # 2026-07-13 plan is a deliberate half-volume week.
        measured = 0
        for path in sorted(_PLANS_DIR.glob("*/2026-07-13-workout.md")):
            text = path.read_text(encoding="utf-8")
            strict, _ = validate_workout_plan(text)
            relaxed, warnings = validate_workout_plan(text, deload_week=True)
            advisory = [w for w in warnings if "[advisory: deload week]" in w]
            with self.subTest(plan=path.name):
                self.assertEqual(len(strict), 8)
                self.assertEqual(len(relaxed), 3)
                self.assertEqual(len(advisory), 5)
                # And the relief does NOT make it renderable: what
                # survives is core placement, which costs no fatigue.
                for e in relaxed:
                    self.assertIn("core is the last bullet", e)
            measured += 1
        if not measured:
            self.skipTest("no 2026-07-13 plan on disk")

    def test_consecutive_generations_trip_the_rotation_check(self) -> None:
        from workout_coach.lib.adherence import parse_plan_file
        from workout_coach.lib.blocks import (
            block_from_plan, load_pattern_catalog, rotation_diff_errors)
        from workout_coach.lib.extract import load_exercises_db
        from shared.exercises_database import DATABASE_PATH

        prev_path, new_path = self._newest_pair()
        if prev_path is None:
            self.skipTest("no person has two plans on disk")
        catalog = load_pattern_catalog(load_exercises_db(DATABASE_PATH))
        prev = block_from_plan(parse_plan_file(prev_path), catalog)
        new = block_from_plan(parse_plan_file(new_path), catalog,
                              prev_block=prev)
        self.assertTrue(rotation_diff_errors(prev, new, catalog),
                        f"{prev_path.name} -> {new_path.name} rotated cleanly, "
                        "which contradicts the measured 0.54 Jaccard baseline")


if __name__ == "__main__":
    unittest.main()
