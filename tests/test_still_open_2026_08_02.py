"""The three block/ledger defects left open after the 2026-08-02 fix round.

R-05, R-13 and R-01 from ``GATE-GAPS-2026-08-02.md``'s STILL OPEN
section. Each class below pins one of them with the reproduction that
found it, so the fix cannot regress quietly.

The governing rule every test here is written against: an enforcement
input is safe iff it was written by someone other than the party being
policed, or derived from such a source. User logs and the exercise
catalog are trustworthy; COACH-WRITTEN FREE TEXT IS ADVERSARIAL. Two of
these three defects are free text choosing its own threshold — a workout
heading picking the core budget (R-13), and a block artifact the coach is
told to copy contradicting the spec it ships beside (R-05). The third is
an enforcement input read out of two coach-authored plans (R-01).
"""
from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from workout_coach.lib.adherence import (
    DOSE_LOAD_MIN_PCT,
    LEDGER_LOAD_STALL_SESSIONS,
    SESSION_CONTENT_MIN_SETS,
    expected_next_dose,
    ledger_progression,
    ledger_reference,
    parse_plan,
    performed_sessions,
    progression_verdict,
    session_content_regions,
    session_type_from_content,
    session_type_from_title,
)
from workout_coach.lib.blocks import (
    block_from_plan,
    block_payload,
    core_spec_conflicts,
    load_pattern_catalog,
    new_block,
    strip_benched_slots,
)
from workout_coach.lib.constants import CORE_WEEK_SPEC
from workout_coach.lib.extract import load_exercises_db
from workout_coach.lib.render_validators import _session_core_set_bounds

_DB_PATH = Path(__file__).resolve().parents[1] / "shared" / "exercises-database.md"
_DB = load_exercises_db(_DB_PATH)
_CATALOG = load_pattern_catalog(_DB)

# The band a lower / full / unclassifiable session gets. Read off the one
# implementation rather than restated, so a spec change moves both.
_LOWER_BAND = _session_core_set_bounds("LOWER A + CORE", CORE_WEEK_SPEC)
_UPPER_BAND = _session_core_set_bounds("UPPER A + CORE", CORE_WEEK_SPEC)


def _slot(name: str, sets: int = 3, **kw) -> dict:
    return {"exercise": name, "prescribed_sets": sets, **kw}


# A leg day. Every movement resolves to a lower-body ``primary`` in the
# catalog; the one core bullet is neutral and does not vote.
_LEG_DAY = [
    _slot("Barbell Back Squat", 4),
    _slot("Leg Press", 4),
    _slot("Romanian Deadlift", 3),
    _slot("Leg Curl (Seated)", 3),
    _slot("Ab Crunch Machine", 2),
]
# A real push day.
_PUSH_DAY = [
    _slot("Dumbbell Flat Bench Press", 4),
    _slot("Dumbbell Shoulder Press", 3),
    _slot("Cable Lateral Raise", 3),
    _slot("Cable Tricep Pushdown", 3),
    _slot("Ab Crunch Machine", 2),
]
# A real PPL pull day, carrying one hinge. This is the case a naive
# "any lower-body movement vetoes the upper budget" rule would break.
_PULL_DAY_WITH_HINGE = [
    _slot("Romanian Deadlift", 4),
    _slot("Cable Lat Pulldown", 3),
    _slot("Seated Row Machine", 3),
    _slot("Barbell Curl", 3),
    _slot("Rear Delt Fly Machine", 3),
]


# ===========================================================================
# R-13 — a leg day named PUSH buys the 2-set upper core budget
# ===========================================================================
class SessionTypeCannotBeAssertedByItsNameTests(unittest.TestCase):
    """The heading decides the per-session core budget and the coach
    writes the heading.

    Reproduced before the fix, against the live spec::

        'FULL BODY'    -> full   -> bounds (4,5)   # fails safe
        'Gibberish'    -> None   -> bounds (4,5)   # fails safe
        'PUSH'         -> upper  -> bounds (2,3)   # confidently WRONG
        'LOWER 1'      -> lower  -> bounds (4,5)

    ``FULL BODY`` and unclassifiable headings had been closed by failing
    safe to the lower-day dose. ``PUSH`` / ``PULL`` had not, because they
    resolve confidently to ``upper`` while a push or pull day may well be
    a leg day.
    """

    def test_the_name_alone_still_answers_from_the_name(self) -> None:
        """The title-only read is unchanged, and it is the exploit.

        Kept deliberately: a caller with no access to the bullets gets
        the same answer it always did, so nothing silently changes
        meaning. The fix is that the answer is no longer FINAL.
        """
        self.assertEqual(session_type_from_title("PUSH"), "upper")
        self.assertEqual(session_type_from_title("PULL"), "upper")
        self.assertEqual(_session_core_set_bounds("PUSH", CORE_WEEK_SPEC),
                         _UPPER_BAND)

    def test_a_leg_day_named_push_is_a_leg_day(self) -> None:
        """THE DEFECT. Squats and leg presses under a PUSH heading."""
        self.assertEqual(session_type_from_title("PUSH", _LEG_DAY), "lower")
        self.assertEqual(session_type_from_title("PULL", _LEG_DAY), "lower")
        self.assertEqual(session_type_from_title("UPPER A + CORE", _LEG_DAY),
                         "lower")

    def test_the_resolved_type_carries_the_demanding_budget(self) -> None:
        """The fix is only worth anything if it moves the band.

        Asserted through `_session_core_set_bounds` rather than against
        the literal numbers, so a spec edit moves the expectation with
        it. The 4-set lower band is what a leg day must get, whatever it
        is called.
        """
        resolved = session_type_from_title("PUSH", _LEG_DAY)
        self.assertEqual(resolved, "lower")
        self.assertEqual(_session_core_set_bounds("LOWER 1", CORE_WEEK_SPEC),
                         _LOWER_BAND)
        self.assertGreater(_LOWER_BAND[0], _UPPER_BAND[0])

    def test_a_real_push_day_keeps_the_upper_budget(self) -> None:
        """The regression that matters. Over-vetoing is its own defect."""
        self.assertEqual(session_type_from_title("PUSH", _PUSH_DAY), "upper")
        self.assertEqual(session_type_from_title("UPPER B + CORE", _PUSH_DAY),
                         "upper")

    def test_a_pull_day_carrying_one_hinge_is_still_an_upper_day(self) -> None:
        """A PPL pull day with a Romanian Deadlift in it.

        4 lower sets against 12 upper is 0.75 upper — over the dominance
        threshold, so the session keeps the budget its name claims. A
        rule that vetoed on ANY lower-body movement would have broken
        this, which is why the threshold is a share and not a presence
        test.
        """
        regions = session_content_regions(_PULL_DAY_WITH_HINGE)
        self.assertEqual(regions["lower_sets"], 4)
        self.assertEqual(regions["upper_sets"], 12)
        self.assertEqual(session_type_from_title("PULL",
                                                 _PULL_DAY_WITH_HINGE), "upper")

    def test_content_may_never_grant_the_cheaper_budget(self) -> None:
        """The invariant, in both directions.

        ``upper`` is the only session type whose core budget sits below
        the fail-safe, so it is the only answer a name can profit from
        and the only one content is allowed to overturn. Content that
        says ``upper`` against a heading claiming otherwise is REFUSED —
        honouring it would hand the cheap budget to a session that asked
        for the dear one, which is the exploit running backwards.
        """
        self.assertEqual(session_type_from_title("LOWER 1", _PUSH_DAY), "lower")
        self.assertEqual(session_type_from_title("FULL BODY A", _PUSH_DAY),
                         "full")
        self.assertIsNone(session_type_from_title("Gibberish", _PUSH_DAY))

    def test_an_unclassifiable_heading_takes_the_content_when_it_is_dearer(self):
        self.assertEqual(session_type_from_title("Gibberish", _LEG_DAY), "lower")

    def test_a_mixed_session_reads_as_full_body(self) -> None:
        mixed = [_slot("Barbell Back Squat", 4), _slot("Dumbbell Flat Bench Press", 4),
                 _slot("Seated Row Machine", 3), _slot("Leg Curl (Seated)", 3)]
        self.assertEqual(session_type_from_content(mixed), "full")
        self.assertEqual(session_type_from_title("PUSH", mixed), "full")

    def test_too_little_content_leaves_the_heading_standing(self) -> None:
        """No signal is not the same answer as a signal that says upper.

        A session below `SESSION_CONTENT_MIN_SETS` classifiable sets — a
        mobility block, an all-core session — cannot refuse anything, so
        the heading stands exactly as it did before this existed.
        """
        thin = [_slot("Ab Crunch Machine", 2), _slot("Plank", 2)]
        self.assertEqual(session_content_regions(thin)["classified_sets"], 0)
        self.assertIsNone(session_type_from_content(thin))
        self.assertEqual(session_type_from_title("PUSH", thin), "upper")
        one_set = [_slot("Barbell Back Squat", SESSION_CONTENT_MIN_SETS - 1)]
        self.assertIsNone(session_type_from_content(one_set))

    def test_core_and_cardio_do_not_vote(self) -> None:
        """Padding cannot move the verdict.

        Core is the very thing being budgeted and cardio belongs to no
        region, so both are excluded from the denominator rather than
        counted as neutral evidence for whichever side is behind.
        """
        padded = _LEG_DAY + [_slot("Ab Crunch Machine", 20),
                             _slot("Plank", 20)]
        regions = session_content_regions(padded)
        self.assertEqual(regions["upper_sets"], 0)
        self.assertEqual(session_type_from_content(padded), "lower")

    def test_full_body_compounds_cannot_hide_a_leg_day(self) -> None:
        """Found by attacking the first version of this fix.

        Treating a catalog entry the catalog assigns to neither half as
        NEUTRAL reopened the defect through a different door: a PUSH day
        of four FULL BODY (Compound) movements — 16 working sets, every
        name legal — produced zero region-classifiable sets, so the
        content could not answer and the heading kept the 2-set budget on
        a session that is at least half legs.

        Counting them on BOTH sides is honest (a thruster is a squat and
        a press) and can only pull the share toward 0.5, which resolves
        as ``full`` and carries the demanding budget.
        """
        full_body = [_slot("Barbell Clean", 4), _slot("Barbell Thruster", 4),
                     _slot("Box Jump", 4), _slot("Dumbbell Farmer Walk", 4)]
        regions = session_content_regions(full_body)
        self.assertEqual(regions["both_halves_sets"], 16)
        self.assertEqual(regions["lower_sets"], regions["upper_sets"])
        self.assertEqual(session_type_from_title("PUSH", full_body), "full")

    def test_both_halves_sets_cannot_manufacture_an_upper_verdict(self) -> None:
        """The invariant that makes "both" safe. Adding an equal amount
        to each side moves the share toward 0.5 and never past it."""
        for pad in range(0, 40, 4):
            slots = _LEG_DAY + [_slot("Barbell Thruster", pad)] if pad else _LEG_DAY
            self.assertNotEqual(session_type_from_title("PUSH", slots), "upper",
                                f"pad={pad}")

    def test_a_back_extension_does_not_flip_a_legitimate_pull_day(self) -> None:
        """``erectors`` is one of the unassigned primaries, so it counts
        both ways. Three sets of it on a real pull day must not tip the
        session out of the upper budget it has earned."""
        slots = _PULL_DAY_WITH_HINGE + [_slot("45 Degree Back Extension", 3)]
        self.assertEqual(session_type_from_title("PULL", slots), "upper")

    def test_the_min_sets_gate_counts_each_set_once(self) -> None:
        """``classified_sets`` double-counts both-halves work by design;
        the "is there enough to judge" floor must not."""
        two_sets = [_slot("Barbell Thruster", SESSION_CONTENT_MIN_SETS - 1)]
        self.assertIsNone(session_type_from_content(two_sets))

    def test_off_catalog_names_are_reported_not_counted(self) -> None:
        slots = _LEG_DAY + [_slot("Invented Movement", 40)]
        regions = session_content_regions(slots)
        self.assertIn("Invented Movement", regions["unclassified"])
        self.assertEqual(session_type_from_content(slots), "lower")

    def test_a_missing_set_count_still_votes_once(self) -> None:
        slots = [{"exercise": "Barbell Back Squat"},
                 {"exercise": "Leg Press"},
                 {"exercise": "Leg Curl (Seated)"}]
        self.assertEqual(session_content_regions(slots)["lower_sets"], 3)
        self.assertEqual(session_type_from_content(slots), "lower")

    def test_the_gate_s_own_bullet_shape_is_accepted(self) -> None:
        """`render_validators._iter_workout_exercise_bullets` says
        ``name`` / ``sets``; this module says ``exercise`` /
        ``prescribed_sets``. Both are exercise bullets with a working-set
        count, and the classifier has to read the shape the GATE holds —
        otherwise wiring it up needs a translation layer, and a
        translation layer is where the two drift.
        """
        gate_shape = [{"name": s["exercise"], "sets": s["prescribed_sets"]}
                      for s in _LEG_DAY]
        self.assertEqual(session_type_from_title("PUSH", gate_shape), "lower")


class ParsedPlansCarryTheCheckedTypeTests(unittest.TestCase):
    PLAN = (
        "# Plan\n\n"
        "## Workout 1: PUSH\n"
        "- Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8 /// 90kgx8\n"
        "- Leg Press: 150kgx10 /// 150kgx10 /// 150kgx10 /// 150kgx10\n"
        "- Romanian Deadlift: 100kgx8 /// 100kgx8 /// 100kgx8\n"
        "- Ab Crunch Machine: 30kgx12 /// 30kgx12\n"
        "\n## Workout 2: PUSH B\n"
        "- Dumbbell Flat Bench Press: 52kgx8 /// 52kgx8 /// 52kgx8 /// 52kgx8\n"
        "- Dumbbell Shoulder Press: 40kgx10 /// 40kgx10 /// 40kgx10\n"
        "- Cable Tricep Pushdown: 30kgx12 /// 30kgx12 /// 30kgx12\n"
    )

    def test_parse_plan_resolves_the_type_off_the_bullets(self) -> None:
        plan = parse_plan(self.PLAN, "2026-08-02", _DB)
        leg, push = plan["workouts"]
        self.assertEqual(leg["session_type"], "lower")
        self.assertEqual(leg["session_type_heading"], "upper")
        self.assertEqual(leg["session_type_content"], "lower")
        self.assertEqual(leg["session_type_basis"], "content_override")
        self.assertEqual(push["session_type"], "upper")
        self.assertEqual(push["session_type_basis"], "heading_corroborated")

    def test_the_override_is_reported_not_silent(self) -> None:
        plan = parse_plan(self.PLAN, "2026-08-02", _DB)
        self.assertTrue(any("resolved as lower from the bullets" in n
                            for n in plan["parse_notes"]))
        # A quiet channel, not an error: nothing was lost, and an error
        # that fires on a legal plan is how a channel stops being read.
        self.assertFalse(plan["parse_errors"])

    def test_the_catalog_loads_itself_when_no_db_is_threaded(self) -> None:
        """A caller that does not hold a catalog still gets the checked
        answer. The alternative — falling back to the heading — would
        leave the exploit open on every path that forgot to plumb one.
        """
        plan = parse_plan(self.PLAN, "2026-08-02")
        self.assertEqual(plan["workouts"][0]["session_type"], "lower")

    def test_the_block_artifact_records_the_checked_type(self) -> None:
        plan = parse_plan(self.PLAN, "2026-08-02", _DB)
        block = block_from_plan(plan, _CATALOG)
        self.assertEqual(block["session_types"]["push"], "lower")
        self.assertEqual(block["session_types"]["push_b"], "upper")


# ===========================================================================
# R-05 — the block artifact violates the core spec it ships beside
# ===========================================================================
# The live 2026-08-02 payload, both people, reduced to the shape that
# matters. `Ab Crunch Machine` in three sessions against a cap of two,
# two distinct core exercises against a floor of three, one pattern
# category against a floor of three, and two core sets on a lower day
# against a floor of four.
def _core(name: str, sets: int, position: int = 5) -> dict:
    return {"position": position, "exercise": name, "tag": "rotating",
            "dose": {"load_kg": 30.0, "rep_lo": 10, "rep_hi": 12,
                     "prescribed_sets": sets}}


def _leg_slots(core_name: str, core_sets: int = 2) -> list:
    return [
        {"position": 1, "exercise": "Barbell Back Squat", "tag": "anchor",
         "dose": {"load_kg": 90.0, "rep_lo": 8, "rep_hi": 8,
                  "prescribed_sets": 4}},
        {"position": 2, "exercise": "Leg Press", "tag": "anchor",
         "dose": {"load_kg": 150.0, "rep_lo": 10, "rep_hi": 10,
                  "prescribed_sets": 4}},
        {"position": 3, "exercise": "Leg Curl (Seated)", "tag": "rotating",
         "dose": {"load_kg": 50.0, "rep_lo": 12, "rep_hi": 12,
                  "prescribed_sets": 3}},
        _core(core_name, core_sets),
    ]


def _upper_slots(core_name: str, core_sets: int = 2) -> list:
    return [
        {"position": 1, "exercise": "Dumbbell Flat Bench Press", "tag": "anchor",
         "dose": {"load_kg": 80.0, "rep_lo": 8, "rep_hi": 8,
                  "prescribed_sets": 4}},
        {"position": 2, "exercise": "Cable Lat Pulldown", "tag": "anchor",
         "dose": {"load_kg": 65.0, "rep_lo": 8, "rep_hi": 10,
                  "prescribed_sets": 4}},
        {"position": 3, "exercise": "Cable Lateral Raise", "tag": "rotating",
         "dose": {"load_kg": 10.0, "rep_lo": 12, "rep_hi": 15,
                  "prescribed_sets": 3}},
        _core(core_name, core_sets),
    ]


_LIVE_SHAPED_BLOCK = {
    "version": 1, "block_id": "2026-07-25", "started": "2026-07-25",
    "sessions": {
        "lower_a": _leg_slots("Ab Crunch Machine"),
        "lower_b": _leg_slots("Cable Reverse Crunch"),
        "upper_a": _upper_slots("Ab Crunch Machine"),
        "upper_b": _upper_slots("Ab Crunch Machine"),
    },
}


class BlockMustNotContradictTheCoreSpecTests(unittest.TestCase):
    """Verified on the live payload before the fix, both people::

        lower_a core: ['Ab Crunch Machine']    upper_a core: ['Ab Crunch Machine']
        lower_b core: ['Cable Reverse Crunch'] upper_b core: ['Ab Crunch Machine']
        distinct core exercises: 2   (spec floor 3)
        max sessions for one exercise: Ab Crunch Machine x3   (cap 2)

    SKILL.md tells the coach an in-flight block outranks the
    frequency-derived split, which reads as "copy the slots" — and
    copying them fails the gate on every axis above.
    """

    def _conflicts(self, block):
        return core_spec_conflicts(block, _CATALOG, db=_DB)

    def _axes(self, block):
        return {c["axis"] for c in self._conflicts(block)["conflicts"]}

    def test_the_live_shaped_block_is_reported_as_uncopyable(self) -> None:
        out = self._conflicts(_LIVE_SHAPED_BLOCK)
        self.assertFalse(out["compliant"])
        self.assertFalse(out["copy_core_slots"])
        self.assertIn("DO NOT COPY", out["directive"])

    def test_every_violated_axis_is_named(self) -> None:
        self.assertEqual(
            self._axes(_LIVE_SHAPED_BLOCK),
            {"sets_per_session", "min_distinct_exercises_per_week",
             "max_sessions_per_exercise_per_week",
             "min_pattern_categories_per_week"})

    def test_the_numbers_match_the_reproduction(self) -> None:
        conflicts = {c["axis"]: c
                     for c in self._conflicts(_LIVE_SHAPED_BLOCK)["conflicts"]
                     if c["axis"] != "sets_per_session"}
        distinct = conflicts["min_distinct_exercises_per_week"]
        self.assertEqual(distinct["observed"], 2)
        self.assertEqual(distinct["required"],
                         CORE_WEEK_SPEC["min_distinct_exercises_per_week"])
        cap = conflicts["max_sessions_per_exercise_per_week"]
        self.assertEqual(cap["exercise"], "Ab Crunch Machine")
        self.assertEqual(cap["observed"], 3)
        self.assertEqual(cap["required"],
                         CORE_WEEK_SPEC["max_sessions_per_exercise_per_week"])

    def test_the_per_session_dose_uses_the_content_derived_type(self) -> None:
        """R-05 and R-13 meet here.

        A block's own ``session_types`` is a stored claim; the dose axis
        reads the session's slots instead. ``lower_a`` is full of squats
        and leg presses, so it is judged against the 4-set lower budget
        whatever the artifact calls it — and ``upper_a``, which carries
        two core sets against the 2-set upper budget, is NOT reported.
        """
        sessions = {c.get("session")
                    for c in self._conflicts(_LIVE_SHAPED_BLOCK)["conflicts"]
                    if c["axis"] == "sets_per_session"}
        self.assertEqual(sessions, {"lower_a", "lower_b"})

    def test_a_lying_session_types_map_cannot_buy_the_cheap_budget(self) -> None:
        lying = dict(_LIVE_SHAPED_BLOCK)
        lying["session_types"] = {"lower_a": "upper", "lower_b": "upper",
                                  "upper_a": "upper", "upper_b": "upper"}
        sessions = {c.get("session") for c in self._conflicts(lying)["conflicts"]
                    if c["axis"] == "sets_per_session"}
        self.assertEqual(sessions, {"lower_a", "lower_b"})

    def test_a_compliant_block_is_carried_forward(self) -> None:
        """The other direction. A marker that always fires is noise."""
        block = {
            "started": "2026-07-25",
            "sessions": {
                "lower_a": _leg_slots("Ab Crunch Machine", 4),
                "lower_b": _leg_slots("Hanging Leg Raise", 4),
                "upper_a": _upper_slots("Cable Pallof Press", 2),
                "upper_b": _upper_slots("Side Plank", 2),
            },
        }
        out = self._conflicts(block)
        self.assertEqual(out["conflicts"], [])
        self.assertTrue(out["compliant"])
        self.assertTrue(out["copy_core_slots"])
        self.assertNotIn("DO NOT COPY", out["directive"])

    def test_compliant_never_means_every_axis_was_checked(self) -> None:
        """The three flexion axes have one implementation, in
        `render_validators`, and a second copy here is how the two end up
        disagreeing about the number that decides a render. They are
        named rather than silently omitted.
        """
        out = self._conflicts(_LIVE_SHAPED_BLOCK)
        self.assertIn("min_flexion_sets_per_week", out["axes_not_checked"])
        self.assertIn("min_flexion_share_of_core_sets", out["axes_not_checked"])
        self.assertIn("min_loaded_flexion_exercises_per_week",
                      out["axes_not_checked"])
        self.assertTrue(set(out["axes_checked"]).isdisjoint(
            out["axes_not_checked"]))

    def test_a_session_with_no_recorded_dose_is_skipped_not_invented(self) -> None:
        """This marker is read by a coach. A fabricated conflict tells it
        not to copy a block that was fine, which is its own defect.
        """
        block = {"started": "2026-07-25", "sessions": {
            "lower_a": [{"position": 1, "exercise": "Barbell Back Squat",
                         "tag": "anchor"},
                        {"position": 2, "exercise": "Leg Press", "tag": "anchor"},
                        {"position": 3, "exercise": "Leg Curl (Seated)",
                         "tag": "rotating"},
                        {"position": 4, "exercise": "Ab Crunch Machine",
                         "tag": "rotating"}]}}
        out = self._conflicts(block)
        self.assertEqual([c for c in out["conflicts"]
                          if c["axis"] == "sets_per_session"], [])
        self.assertIn("lower_a", out["sessions_undetermined"])

    def test_no_block_means_no_marker(self) -> None:
        self.assertIsNone(core_spec_conflicts(None, _CATALOG, db=_DB))
        self.assertIsNone(core_spec_conflicts({}, _CATALOG, db=_DB))

    def test_the_artifact_itself_is_not_rewritten(self) -> None:
        """The chosen approach, asserted.

        The block is a RECORD, and it is the basis every rotation check
        differs the next generation against. Reconciling it into
        compliance would invent core slots nobody prescribed and leave
        generation N+1 compared against a block that was never written.
        """
        before = _LIVE_SHAPED_BLOCK["sessions"]["upper_b"][-1]["exercise"]
        self._conflicts(_LIVE_SHAPED_BLOCK)
        self.assertEqual(
            _LIVE_SHAPED_BLOCK["sessions"]["upper_b"][-1]["exercise"], before)


class BenchedMovementsMustNotSurviveInASlotTests(unittest.TestCase):
    """``Leg Curl (Lying)`` was in the live block AND on
    ``adherence.benched`` ("must not re-prescribe"), on the same payload.

    The trap is the SLOT PRESENCE. All three benched entries carry
    ``still_prescribed: False`` — the newest plan had already dropped the
    movement — so a reader checking that field concludes there is nothing
    wrong. The block is a separate surface and it was still offering the
    movement to be copied.
    """

    def _block(self):
        b = new_block("2026-07-25", {
            "lower_a": [{"position": 1, "exercise": "Barbell Back Squat",
                         "tag": "anchor"},
                        {"position": 2, "exercise": "Leg Curl (Lying)",
                         "tag": "rotating"}],
            "upper_a": [{"position": 1, "exercise": "Dumbbell Flat Bench Press",
                         "tag": "anchor"}]})
        return b

    def test_the_benched_slot_is_removed(self) -> None:
        out, removed = strip_benched_slots(
            self._block(),
            [{"exercise": "Leg Curl (Lying)", "still_prescribed": False}])
        names = [s["exercise"] for slots in out["sessions"].values()
                 for s in slots]
        self.assertNotIn("Leg Curl (Lying)", names)
        self.assertIn("Barbell Back Squat", names)
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]["exercise"], "Leg Curl (Lying)")
        self.assertEqual(removed[0]["session_type"], "lower_a")
        self.assertEqual(removed[0]["reason"], "benched")

    def test_still_prescribed_false_does_not_exempt_the_slot(self) -> None:
        """An earlier reading of this defect stopped at that field."""
        _out, removed = strip_benched_slots(
            self._block(),
            [{"exercise": "Leg Curl (Lying)", "still_prescribed": False,
              "disposition": "unasked"}])
        self.assertEqual(len(removed), 1)

    def test_the_input_block_is_not_mutated(self) -> None:
        block = self._block()
        strip_benched_slots(block, ["Leg Curl (Lying)"])
        self.assertEqual(len(block["sessions"]["lower_a"]), 2)

    def test_bare_names_and_empty_lists_are_accepted(self) -> None:
        out, removed = strip_benched_slots(self._block(), ["Leg Curl (Lying)"])
        self.assertEqual(len(removed), 1)
        self.assertEqual(len(out["sessions"]["lower_a"]), 1)
        same, none = strip_benched_slots(self._block(), [])
        self.assertEqual(none, [])
        self.assertEqual(len(same["sessions"]["lower_a"]), 2)

    def test_positions_are_left_alone(self) -> None:
        """Renumbering would make a removal look like a reshuffle to the
        next generation's rotation diff."""
        out, _ = strip_benched_slots(
            self._block(), ["Barbell Back Squat"])
        self.assertEqual(out["sessions"]["lower_a"][0]["position"], 2)


class BlockPayloadCarriesBothFindingsTests(unittest.TestCase):
    """End to end: nothing benched reaches either projection, and the
    core-spec marker rides on the payload the coach reads."""

    PERSON = "R05TestPerson"
    PLAN = (
        "# Plan\n\n"
        "## Workout 1: LOWER A + CORE\n"
        "- Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8 /// 90kgx8\n"
        "- Leg Press: 150kgx10 /// 150kgx10 /// 150kgx10 /// 150kgx10\n"
        "- Leg Curl (Lying): 45kgx12 /// 45kgx12 /// 45kgx12\n"
        "- Ab Crunch Machine: 30kgx12 /// 30kgx12\n"
        "\n## Workout 2: UPPER A + CORE\n"
        "- Dumbbell Flat Bench Press: 52kgx8 /// 52kgx8 /// 52kgx8 /// 52kgx8\n"
        "- Cable Lat Pulldown: 65kgx8 /// 65kgx8 /// 65kgx8\n"
        "- Ab Crunch Machine: 30kgx12 /// 30kgx12\n"
    )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev_root = os.environ.get("WORKOUT_TRACKER_ROOT")
        os.environ["WORKOUT_TRACKER_ROOT"] = self._tmp.name
        import shared.person_paths as pp
        importlib.reload(pp)
        self.plans = Path(self._tmp.name) / "plans" / self.PERSON
        self.plans.mkdir(parents=True)
        for d in ("2026-07-18", "2026-07-25"):
            (self.plans / f"{d}-workout.md").write_text(self.PLAN,
                                                        encoding="utf-8")

    def tearDown(self) -> None:
        if self._prev_root is None:
            os.environ.pop("WORKOUT_TRACKER_ROOT", None)
        else:
            os.environ["WORKOUT_TRACKER_ROOT"] = self._prev_root
        import shared.person_paths as pp
        importlib.reload(pp)
        self._tmp.cleanup()

    def _payload(self, benched=()):
        return block_payload(
            self.PERSON, [], _DB, _CATALOG, date(2026, 8, 2), [],
            adherence={"benched": list(benched)})

    def test_a_benched_movement_reaches_neither_projection(self) -> None:
        payload = self._payload([{"exercise": "Leg Curl (Lying)"}])
        flat = [s["exercise"] for s in payload["slots"]]
        nested = [s["exercise"] for slots in payload["sessions"].values()
                  for s in slots]
        self.assertNotIn("Leg Curl (Lying)", flat)
        self.assertNotIn("Leg Curl (Lying)", nested)
        self.assertEqual(payload["benched_slots_removed"][0]["exercise"],
                         "Leg Curl (Lying)")

    def test_the_removal_is_reported_not_silent(self) -> None:
        clean = self._payload()
        self.assertIsNone(clean["benched_slots_removed"])
        self.assertIn("Leg Curl (Lying)",
                      [s["exercise"] for s in clean["slots"]])

    def test_the_core_spec_marker_rides_on_the_payload(self) -> None:
        marker = self._payload()["core_spec"]
        self.assertEqual(marker["spec"], "core_week_spec")
        self.assertFalse(marker["copy_core_slots"])
        # Two sessions, one core movement, two sets on a lower day.
        axes = {c["axis"] for c in marker["conflicts"]}
        self.assertIn("min_distinct_exercises_per_week", axes)
        self.assertIn("sets_per_session", axes)


# ===========================================================================
# R-01 — the progression increment, derived from the LEDGER
# ===========================================================================
def _log(day: str, exercise: str, kg: float, reps: int, n: int = 3) -> list:
    return [{"date": day, "exercise": exercise, "kg": kg, "reps": reps,
             "notes": ""} for _ in range(n)]


def _presc(load=None, lo=None, hi=None, sets=3, name="Barbell Back Squat"):
    return {"exercise": name, "load_kg": load, "rep_lo": lo, "rep_hi": hi,
            "rep_target": (f"{lo}-{hi}" if lo != hi else str(lo)),
            "prescribed_sets": sets}


def _history(*sessions):
    """``(date, kg, reps)`` triples into the shape the verdict reads."""
    rows = []
    for day, kg, reps in sessions:
        rows += _log(day, "Barbell Back Squat", kg, reps)
    return performed_sessions(rows, _DB)["barbell back squat"]


class ProgressionIsJudgedAgainstTheLedgerTests(unittest.TestCase):
    """`dose_staleness` compares two COACH-AUTHORED plans, so shifting
    every rep window up one (``x8-10`` -> ``x9-11``) reads as material
    without a kilo being added. That is why
    `render_validators.DOSE_PROGRESSION_ENFORCED` is False.

    Everything here reads the logged sets instead and asks a different
    question: does this prescription ask for anything the person has not
    already done?
    """

    def test_the_rep_window_shuffle_is_not_a_progression(self) -> None:
        """THE BYPASS, by name.

        Ten reps at 90kg for three sessions running: the reps have
        stopped arriving at this load. Widening the window to 9-11 asks
        again for exactly what stopped happening.
        """
        history = _history(("2026-07-08", 90, 10), ("2026-07-15", 90, 10),
                           ("2026-07-22", 90, 10))
        out = progression_verdict(history, _presc(90, 9, 11))
        self.assertEqual(out["verdict"], "cosmetic")
        self.assertEqual(out["kind"], "rep_window_shift")
        self.assertFalse(out["material"])

    def test_the_same_two_prescriptions_get_two_verdicts_on_two_ledgers(self):
        """THE STRUCTURAL POINT.

        ``x8-10`` -> ``x9-11`` at a held load is one written change. It
        is a progression when the reps at that load are still climbing
        and it is not when they have stopped — and nothing about the two
        prescriptions distinguishes those. Only the ledger does, which is
        the whole reason this function exists.
        """
        stalled = _history(("2026-07-08", 90, 10), ("2026-07-15", 90, 10),
                           ("2026-07-22", 90, 10))
        climbing = _history(("2026-07-08", 90, 8), ("2026-07-15", 90, 9),
                            ("2026-07-22", 90, 10))
        presc = _presc(90, 9, 11)
        self.assertEqual(progression_verdict(stalled, presc)["verdict"],
                         "cosmetic")
        self.assertEqual(progression_verdict(climbing, presc)["verdict"],
                         "progression")

    def test_adding_load_is_a_progression(self) -> None:
        history = _history(("2026-07-15", 90, 10), ("2026-07-22", 90, 10))
        out = progression_verdict(history, _presc(95, 8, 10))
        self.assertEqual((out["verdict"], out["kind"]), ("progression", "load_up"))
        self.assertTrue(out["material"])

    def test_a_load_move_inside_the_granularity_floor_is_not_one(self) -> None:
        history = _history(("2026-07-15", 90, 10), ("2026-07-22", 90, 10))
        nudge = 90 * (1 + DOSE_LOAD_MIN_PCT / 2)
        self.assertNotEqual(
            progression_verdict(history, _presc(nudge, 8, 10))["verdict"],
            "progression")

    def test_working_up_through_a_range_is_a_legitimate_hold(self) -> None:
        """``65kgx6-8`` against six reps performed.

        Reading this as a cosmetic re-copy was wrong on three real
        prescriptions in the shipped 2026-08-02 plan before the boundary
        was fixed to ``<=``. The lift is at the floor of its range with
        room above it; re-asking IS the instruction.
        """
        history = _history(("2026-07-15", 65, 6), ("2026-07-23", 65, 6))
        out = progression_verdict(history, _presc(65, 6, 8))
        self.assertEqual(out["verdict"], "hold")
        self.assertEqual(out["kind"], "working_up_through_range")
        self.assertTrue(out["material"])

    def test_a_prescription_the_ledger_never_met_is_a_hold(self) -> None:
        history = _history(("2026-07-22", 90, 6))
        self.assertEqual(progression_verdict(history, _presc(90, 8, 10))
                         ["verdict"], "hold")

    def test_re_asking_for_what_was_already_done_is_cosmetic(self) -> None:
        history = _history(("2026-07-15", 90, 12), ("2026-07-22", 90, 12))
        out = progression_verdict(history, _presc(90, 10, 12))
        self.assertEqual((out["verdict"], out["kind"]),
                         ("cosmetic", "repeat_of_performed"))

    def test_a_deload_reads_as_a_regression_and_is_not_judged(self) -> None:
        """Deliberately NOT a verdict on legitimacy. This function does
        not know whether a deload was prescribed; the caller pairs it
        with ``block.deload_prescribed``.
        """
        history = _history(("2026-07-22", 100, 8))
        out = progression_verdict(history, _presc(70, 8, 10))
        self.assertEqual((out["verdict"], out["kind"]),
                         ("regression", "load_down"))
        self.assertIn("deload", out["why"])

    def test_no_logged_history_is_unknown_not_a_failure(self) -> None:
        out = progression_verdict([], _presc(90, 8, 10))
        self.assertEqual(out["verdict"], "unknown")
        self.assertIsNone(out["performed"])
        self.assertIsNone(out["expected"])

    def test_a_timed_hold_has_nothing_to_compare(self) -> None:
        rows = [{"date": "2026-07-22", "exercise": "Plank", "kg": 0,
                 "reps": 0, "duration_min": 1.0, "notes": ""}]
        history = performed_sessions(rows, _DB)["plank"]
        out = progression_verdict(history, _presc(None, None, None, name="Plank"))
        self.assertEqual(out["verdict"], "unknown")
        self.assertEqual(out["kind"], "no_rep_comparison")

    def test_bodyweight_progression_reads_off_reps(self) -> None:
        rows = _log("2026-07-15", "Pull-Up", 0, 8) + _log("2026-07-22", "Pull-Up", 0, 8)
        history = performed_sessions(rows, _DB)["pull-up"]
        # Eight reps for two sessions running, and the window shifts up
        # around them: the floor drops under what was performed and the
        # top asks for one more. Same shape as the loaded bypass.
        stalled = progression_verdict(history, _presc(None, 7, 9, name="Pull-Up"))
        self.assertEqual(stalled["verdict"], "cosmetic")
        self.assertEqual(stalled["kind"], "rep_window_shift")
        # The honest case: the ledger sits at the floor of the range.
        self.assertEqual(
            progression_verdict(history, _presc(None, 8, 10, name="Pull-Up"))
            ["verdict"], "hold")


class LedgerReferenceTests(unittest.TestCase):
    def test_reps_stalled_needs_a_run_at_one_load(self) -> None:
        """One session at a load is the load being INTRODUCED."""
        one = _history(("2026-07-22", 90, 10))
        self.assertFalse(ledger_reference(one)["reps_stalled"])
        self.assertEqual(ledger_reference(one)["reps_trend"],
                         "first_session_at_load")
        run = _history(*[("2026-07-%02d" % (8 + 7 * i), 90, 10)
                         for i in range(LEDGER_LOAD_STALL_SESSIONS)])
        self.assertTrue(ledger_reference(run)["reps_stalled"])

    def test_a_load_change_resets_the_run(self) -> None:
        history = _history(("2026-07-01", 85, 10), ("2026-07-08", 85, 10),
                           ("2026-07-15", 90, 8))
        ref = ledger_reference(history)
        self.assertEqual(ref["load_kg"], 90)
        self.assertEqual(ref["sessions_at_load"], 1)
        self.assertFalse(ref["reps_stalled"])

    def test_reps_at_top_takes_the_best_set(self) -> None:
        """The generous reading of what the person managed, because it is
        the number a claimed progression has to beat."""
        rows = (_log("2026-07-22", "Barbell Back Squat", 90, 8, n=2)
                + _log("2026-07-22", "Barbell Back Squat", 90, 10, n=1))
        history = performed_sessions(rows, _DB)["barbell back squat"]
        self.assertEqual(history[-1]["reps_at_top"], 10)

    def test_the_lever_names_what_the_ledger_can_actually_say(self) -> None:
        """Flat reps mean the load has stopped yielding. They do NOT mean
        the lift earned more weight — a person capped at the top of their
        range and a person stuck under a load that is too heavy look
        identical here, because the range that separates them is
        coach-authored.
        """
        climbing = _history(("2026-07-08", 90, 8), ("2026-07-15", 90, 9),
                            ("2026-07-22", 90, 10))
        self.assertEqual(expected_next_dose(climbing)["lever"], "reps")
        stalled = _history(("2026-07-08", 90, 10), ("2026-07-15", 90, 10),
                           ("2026-07-22", 90, 10))
        self.assertEqual(expected_next_dose(stalled)["lever"],
                         "load_or_variation")

    def test_the_expected_load_floor_is_a_percentage_not_a_plate(self) -> None:
        stalled = _history(("2026-07-15", 90, 10), ("2026-07-22", 90, 10))
        self.assertAlmostEqual(expected_next_dose(stalled)["min_load_kg"],
                               round(90 * (1 + DOSE_LOAD_MIN_PCT), 2))

    def test_warmups_and_cardio_never_enter_the_history(self) -> None:
        rows = _log("2026-07-22", "Barbell Back Squat", 90, 10)
        rows[0] = {**rows[0], "notes": "warm-up"}
        history = performed_sessions(rows, _DB)["barbell back squat"]
        self.assertEqual(history[-1]["sets"], 2)


class LedgerProgressionPayloadTests(unittest.TestCase):
    PLAN = (
        "# Plan\n\n"
        "## Workout 1: LOWER A + CORE\n"
        "- Barbell Back Squat: 90kgx9-11 /// 90kgx9-11 /// 90kgx9-11\n"
        "- Leg Press: 160kgx10 /// 160kgx10 /// 160kgx10\n"
        "- Cable Reverse Crunch: 30kgx10 /// 30kgx10\n"
    )

    def _rows(self):
        return (_log("2026-07-08", "Barbell Back Squat", 90, 10)
                + _log("2026-07-15", "Barbell Back Squat", 90, 10)
                + _log("2026-07-22", "Barbell Back Squat", 90, 10)
                + _log("2026-07-22", "Leg Press", 150, 10))

    def test_the_bypass_survives_the_whole_pipeline(self) -> None:
        plan = parse_plan(self.PLAN, "2026-08-02", _DB)
        out = ledger_progression(plan, self._rows(), _DB,
                                 today_d=date(2026, 8, 2))
        by_name = {e["exercise"]: e for e in out["exercises"]}
        self.assertEqual(by_name["Barbell Back Squat"]["kind"],
                         "rep_window_shift")
        self.assertEqual(by_name["Leg Press"]["verdict"], "progression")
        self.assertEqual(by_name["Cable Reverse Crunch"]["verdict"], "unknown")

    def test_unknowns_stay_out_of_the_denominator(self) -> None:
        """A rotated-in movement has no ledger. Counting it as a failure
        would make rotation itself look like a progression defect.
        """
        plan = parse_plan(self.PLAN, "2026-08-02", _DB)
        out = ledger_progression(plan, self._rows(), _DB,
                                 today_d=date(2026, 8, 2))
        self.assertEqual(out["counts"]["unknown"], 1)
        self.assertEqual(out["judged_count"], 2)
        self.assertEqual(out["material_pct"], 0.5)

    def test_the_actionable_findings_sort_first(self) -> None:
        plan = parse_plan(self.PLAN, "2026-08-02", _DB)
        out = ledger_progression(plan, self._rows(), _DB,
                                 today_d=date(2026, 8, 2))
        self.assertEqual(out["exercises"][0]["verdict"], "cosmetic")
        self.assertEqual(out["exercises"][-1]["verdict"], "unknown")

    def test_a_reference_outside_the_window_is_not_evidence(self) -> None:
        """A load last touched four months ago does not describe the
        person now."""
        old = _log("2026-01-05", "Barbell Back Squat", 90, 10)
        plan = parse_plan(self.PLAN, "2026-08-02", _DB)
        out = ledger_progression(plan, old, _DB, today_d=date(2026, 8, 2))
        by_name = {e["exercise"]: e for e in out["exercises"]}
        self.assertEqual(by_name["Barbell Back Squat"]["verdict"], "unknown")

    def test_nothing_judgeable_returns_none(self) -> None:
        self.assertIsNone(ledger_progression({"workouts": []}, [], _DB))

    def test_it_reads_the_block_artifact_shape_too(self) -> None:
        """The consumer contract names
        `render_validators._block_as_plan` as an accepted input, so the
        block's own ``dose`` dicts have to survive the trip.
        """
        from workout_coach.lib.render_validators import _block_as_plan
        as_plan = _block_as_plan(_LIVE_SHAPED_BLOCK)
        out = ledger_progression(
            as_plan,
            _log("2026-07-22", "Barbell Back Squat", 90, 8),
            _DB, today_d=date(2026, 8, 2))
        by_name = {e["exercise"]: e for e in out["exercises"]}
        self.assertEqual(by_name["Barbell Back Squat"]["verdict"], "hold")

    def test_it_is_not_wired_into_the_gate(self) -> None:
        """Groundwork only. `DOSE_PROGRESSION_ENFORCED` and the findings
        that read it live in `render_validators`, which a later round
        owns — this pins that no wiring happened by accident.
        """
        import workout_coach.lib.render_validators as rv
        self.assertFalse(rv.DOSE_PROGRESSION_ENFORCED)
        source = Path(rv.__file__).read_text(encoding="utf-8")
        self.assertNotIn("ledger_progression", source)


if __name__ == "__main__":                                # pragma: no cover
    unittest.main()
