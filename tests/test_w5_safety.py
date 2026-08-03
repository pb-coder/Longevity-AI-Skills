"""W5 safety — the cold-start load, and every way it could hurt someone.

`derived_starting_load` is the only legal source of a weight for a
movement with no history, so whatever it says is what gets written into
a plan and lifted. It shipped with its confidence band inverted: a
transfer coefficient that defaulted to 1.0 because no coefficient
existed read as MORE confident than one that had been thought about, and
an 80kg x 10 barbell good morning went out as `medium` on a first
exposure — a movement conventionally loaded at a third of the deadlift it
was derived from.

Every test here is one number that was wrong in the dangerous direction,
or one rule that keeps it from going wrong again. The rule throughout:
a missing suggestion costs a conservative first session, a confident
wrong one costs an injury.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from workout_coach.lib.blocks import (
    NOVEL_COMPOUND_CAP,
    NOVELTY_DISCOUNT,
    UNILATERAL_FROM_BILATERAL,
    derived_starting_load,
    is_unilateral,
    load_pattern_catalog,
    rotation_candidates,
)
from workout_coach.lib.extract import load_exercises_db

_DB_PATH = Path(__file__).resolve().parents[1] / "shared" / "exercises-database.md"
_DB = load_exercises_db(_DB_PATH)
_CATALOG = load_pattern_catalog(_DB)


def _e1rm(name: str, kg: float, last: str = "2026-07-29") -> dict:
    return {name: {"current_e1rm_kg": kg, "last_date": last}}


def _derive(candidate: str, ref: str, kg: float, reps: int = 10) -> dict:
    return derived_starting_load(candidate, _e1rm(ref, kg), _CATALOG, _DB, reps)


# ---------------------------------------------------------------------------
class ConfidenceBandTests(unittest.TestCase):
    """`transfer == 1.0` had two meanings and the code read them as one."""

    def test_a_defaulted_coefficient_is_not_a_confident_derivation(self) -> None:
        # Machine -> Cable is in no coefficient table. The shipped code
        # defaulted `transfer` to 1.0 and then read `transfer == 1.0` as
        # the CONFIDENT case, shipping a 47.5kg cable hip abduction at
        # `medium` off a bilateral machine.
        got = _derive("Cable Hip Abduction", "Hip Abductor Machine", 73.3)
        self.assertIsNone(got["load_kg"],
                          "no coefficient for the pair means no number")
        self.assertEqual(got["load_basis"], "unknown_transfer")
        self.assertEqual(got["confidence"], "none")
        self.assertIn("no transfer coefficient", got["note"])

    def test_same_equipment_is_a_fact_and_keeps_its_number(self) -> None:
        # The other way to reach 1.0: the two really are the same
        # equipment class. That is a fact about the pair, not a default,
        # and it must stay prescribable — suppressing it would close the
        # novelty channel far wider than the bug it fixes.
        got = _derive("Cable Close-Grip Pulldown", "Cable Lat Pulldown", 78.0)
        self.assertEqual(got["load_basis"], "like_for_like")
        self.assertEqual(got["confidence"], "medium")
        self.assertGreater(got["load_kg"], 0)

    def test_only_a_like_for_like_derivation_may_claim_medium(self) -> None:
        # Anything resting on a coefficient, a laterality share or a cap
        # is one band down. Nothing in this module claims "high".
        for candidate, ref, kg in (
            ("Barbell Row", "Chest Supported Row Machine", 93.3),
            ("Barbell Good Morning", "Romanian Deadlift", 126.7),
            ("Cable Kickback", "Cable Tricep Pushdown", 44.2),
        ):
            with self.subTest(candidate=candidate):
                got = _derive(candidate, ref, kg)
                self.assertEqual(got["confidence"], "low")
                self.assertNotEqual(got["load_basis"], "like_for_like")


# ---------------------------------------------------------------------------
class LateralityTests(unittest.TestCase):
    """One limb does not lift what two limbs lift."""

    # Pinned in BOTH directions. The catalog has no laterality column, so
    # `is_unilateral` reads names, and a name it reads wrong doubles a
    # starting load. Every catalog entry the rule currently decides is
    # listed here; a future entry that breaks the heuristic fails this
    # test instead of shipping.
    UNILATERAL = (
        "Cable Single Arm Row", "Single Leg Romanian Deadlift",
        "Single Arm Cable Press", "Single Leg Hip Thrust",
        "Suitcase Carry", "Cable Kickback", "Dumbbell Kickback",
        "Cable Kickback (Glutes)", "Glute Kickback Machine (Kneeling)",
        "Cable Hip Abduction", "Cable Hip Adduction",
        "Dumbbell Bulgarian Split Squat", "Dumbbell Split Squat",
        "Dumbbell Lunge", "Cable Reverse Lunge", "Pistol Squat",
        "Cable Concentration Curl",
    )
    BILATERAL = (
        # The catalog spells the two-limb machines "Abductor" / "Adductor"
        # and the one-limb cable moves "Abduction" / "Adduction". That
        # distinction is the whole reason the rule can tell them apart,
        # and it is exactly the kind of thing that breaks silently.
        "Hip Abductor Machine", "Hip Adductor Machine",
        "Barbell Back Squat", "Romanian Deadlift", "Leg Press",
        "Dumbbell Flat Bench Press", "Cable Lat Pulldown",
        "Dumbbell Standing Calf Raise", "Chest Supported Row Machine",
        "Dumbbell Farmer Walk", "Ab Crunch Machine", "Cable Face Pull",
    )

    def test_single_limb_names_are_recognised(self) -> None:
        for name in self.UNILATERAL:
            with self.subTest(name=name):
                self.assertIn(name.lower(), _CATALOG, "catalog entry moved")
                self.assertTrue(is_unilateral(name))

    def test_two_limb_names_are_not_mistaken_for_single_limb(self) -> None:
        for name in self.BILATERAL:
            with self.subTest(name=name):
                self.assertIn(name.lower(), _CATALOG, "catalog entry moved")
                self.assertFalse(is_unilateral(name))

    def test_a_unilateral_candidate_does_not_inherit_a_bilateral_load(self) -> None:
        # Cable Kickback off a two-arm Cable Tricep Pushdown. Same
        # equipment class, so nothing else in the derivation moves — the
        # shipped code handed the whole two-arm load to one arm and
        # called it `medium`.
        got = _derive("Cable Kickback", "Cable Tricep Pushdown", 44.2)
        self.assertEqual(got["load_basis"], "unilateral_from_bilateral")
        self.assertAlmostEqual(got["transfer"], UNILATERAL_FROM_BILATERAL)
        two_arm = _derive("Cable Overhead Extension",
                          "Cable Overhead Tricep Extension", 44.2)
        self.assertLess(got["load_kg"], two_arm["load_kg"])

    def test_a_bilateral_candidate_is_never_scaled_up_off_one_limb(self) -> None:
        # The reverse direction would mean multiplying a per-limb load by
        # two on a movement the person has never done. Refused, not
        # guessed: where the only squat-pattern history on record is a
        # single-leg movement, the shipped code derived a barbell back
        # squat from it.
        got = _derive("Barbell Back Squat", "Dumbbell Bulgarian Split Squat", 18.7)
        self.assertIsNone(got["load_kg"])
        self.assertEqual(got["load_basis"], "unknown_transfer")
        self.assertIn("one limb at a time", got["note"])


# ---------------------------------------------------------------------------
class CompoundCapTests(unittest.TestCase):
    """Two axially loaded compounds in one pattern group are not one
    movement with two names."""

    def test_the_good_morning_no_longer_inherits_the_deadlift(self) -> None:
        # The shipped number, verbatim: RDL e1RM 126.7 -> 80.0kg x 10 on a
        # first-ever good morning, labelled `medium`. Conventional
        # loading is 30-50% of an RDL.
        got = _derive("Barbell Good Morning", "Romanian Deadlift", 126.7)
        self.assertEqual(got["load_basis"], "compound_capped")
        self.assertEqual(got["confidence"], "low")
        self.assertLessEqual(got["load_kg"], 45.0)
        rdl_ten_rep = 126.7 / (1 + 10 / 30)
        self.assertLessEqual(got["load_kg"] / rdl_ten_rep, 0.50)

    def test_the_front_squat_is_capped_too(self) -> None:
        got = _derive("Barbell Front Squat", "Barbell Back Squat", 120.3)
        self.assertEqual(got["load_basis"], "compound_capped")
        self.assertLessEqual(got["load_kg"], 45.0)

    def test_a_guided_compound_is_not_capped(self) -> None:
        # On a pin stack the variants inside one pattern group load
        # comparably. Capping them buys no safety and throws away the
        # only prescribable number the pattern has.
        got = _derive("Cable Close-Grip Pulldown", "Cable Lat Pulldown", 78.0)
        self.assertNotEqual(got["load_basis"], "compound_capped")
        self.assertGreater(got["load_kg"], 45.0)

    def test_a_free_weight_press_is_not_capped(self) -> None:
        # Not axially loaded and not where the spread is: an incline
        # press sits at 85-90% of a flat press. Capping it produced a
        # 22kg prescription for a 52kg presser and bought nothing.
        got = _derive("Dumbbell Incline Bench Press",
                      "Dumbbell Flat Bench Press", 65.9)
        self.assertNotEqual(got["load_basis"], "compound_capped")
        self.assertGreater(got["load_kg"], 35.0)

    def test_a_coefficient_below_one_is_not_capped_again(self) -> None:
        # Machine -> BB is 0.75 precisely because the barbell version is
        # less supported. Stacking the 0.50 ceiling on top of it
        # double-discounts and lands under the empty bar.
        got = _derive("Barbell Row", "Chest Supported Row Machine", 93.3)
        self.assertEqual(got["load_basis"], "equipment_coefficient")
        self.assertEqual(got["load_kg"], 45.0)

    def test_the_cap_is_the_bottom_of_the_observed_spread(self) -> None:
        self.assertEqual(NOVEL_COMPOUND_CAP, 0.50)
        self.assertEqual(NOVELTY_DISCOUNT, 0.85)


# ---------------------------------------------------------------------------
class PhysicalFloorTests(unittest.TestCase):
    def test_a_barbell_prescription_never_lands_under_the_bar(self) -> None:
        # Where the only hinge on record is a light dumbbell one, the
        # conservative chain derived "Romanian Deadlift: 15kg" — five
        # kilos less than the bar it would be loaded on.
        got = _derive("Romanian Deadlift", "Dumbbell Romanian Deadlift", 42.7)
        self.assertEqual(got["load_kg"], 20.0)
        self.assertEqual(got["load_basis"], "bar_mass_floor")
        self.assertEqual(got["confidence"], "low")

    def test_the_floor_does_not_lift_a_load_that_clears_the_bar(self) -> None:
        got = _derive("Barbell Good Morning", "Romanian Deadlift", 126.7)
        self.assertNotEqual(got["load_basis"], "bar_mass_floor")


# ---------------------------------------------------------------------------
class NoNumberIsAnAnswerTests(unittest.TestCase):
    def test_bodyweight_carries_no_kilogram_figure(self) -> None:
        got = _derive("Ab Wheel Rollout", "Plank", 5.0)
        self.assertIsNone(got["load_kg"])
        self.assertEqual(got["unit"], "bodyweight")
        self.assertEqual(got["load_basis"], "bodyweight")

    def test_every_suppressed_load_says_which_kind_of_ignorance(self) -> None:
        for candidate, ref, kg, basis in (
            ("Cable Single Arm Row", "Chest Supported Row Machine", 93.3,
             "unknown_transfer"),
            ("Suitcase Carry", "Ab Crunch Machine", 46.7, "no_reference"),
            ("Ab Wheel Rollout", "Plank", 5.0, "bodyweight"),
        ):
            with self.subTest(candidate=candidate):
                got = _derive(candidate, ref, kg)
                self.assertIsNone(got["load_kg"])
                self.assertEqual(got["load_basis"], basis)

    def test_an_off_catalog_name_is_the_only_none(self) -> None:
        self.assertIsNone(
            derived_starting_load("Nonexistent Lift", {}, _CATALOG, _DB))


# ---------------------------------------------------------------------------
class RealPayloadSanityTests(unittest.TestCase):
    """No candidate derived WITHOUT an upward equipment coefficient may
    exceed the rep-matched load of its reference.

    An invariant rather than a list of names. It is scoped to the
    derivations that made no upward equipment claim — same class, a
    laterality share, a cap, the bar floor — because those are the ones
    where "heavier than the movement it came from" cannot be justified
    by anything. A stated coefficient above 1.0 (a machine stack against
    dumbbell totals) is allowed to exceed it; that is what the
    coefficient is for, and it ships as `low`.
    """

    NO_UPWARD_CLAIM = ("like_for_like", "compound_capped",
                       "unilateral_from_bilateral", "bar_mass_floor")

    def _all_candidates(self, e1rm, rows):
        out = rotation_candidates(rows, _DB, _CATALOG, e1rm,
                                  __import__("datetime").date(2026, 8, 2),
                                  per_pattern=99)
        return out.get("candidates") or []

    def test_no_derived_load_exceeds_its_rep_matched_reference(self) -> None:
        rows = [{"date": "2026-07-29", "exercise": name, "kg": 60, "reps": 8,
                 "notes": ""}
                for name in ("Romanian Deadlift", "Barbell Back Squat",
                             "Cable Lat Pulldown", "Hip Abductor Machine",
                             "Cable Tricep Pushdown", "Dumbbell Flat Bench Press")]
        e1rm = {"Romanian Deadlift": {"current_e1rm_kg": 126.7,
                                      "last_date": "2026-07-29"},
                "Barbell Back Squat": {"current_e1rm_kg": 120.3,
                                       "last_date": "2026-07-29"},
                "Cable Lat Pulldown": {"current_e1rm_kg": 78.0,
                                       "last_date": "2026-07-29"},
                "Hip Abductor Machine": {"current_e1rm_kg": 73.3,
                                         "last_date": "2026-07-29"},
                "Cable Tricep Pushdown": {"current_e1rm_kg": 44.2,
                                          "last_date": "2026-07-29"},
                "Dumbbell Flat Bench Press": {"current_e1rm_kg": 65.9,
                                              "last_date": "2026-07-29"}}
        offenders = []
        for cand in self._all_candidates(e1rm, rows):
            if cand.get("load_kg") is None or not cand.get("ref_e1rm_kg"):
                continue
            if cand["load_basis"] not in self.NO_UPWARD_CLAIM:
                continue
            rep_matched = cand["ref_e1rm_kg"] / (1 + 10 / 30)
            if cand["load_kg"] > rep_matched:
                offenders.append((cand["exercise"], cand["load_kg"],
                                  round(rep_matched, 1), cand["load_basis"]))
        self.assertEqual(offenders, [],
                         "a first exposure prescribed heavier than the "
                         "movement it was derived from")

    def test_no_unilateral_candidate_outweighs_its_bilateral_reference(self) -> None:
        rows = [{"date": "2026-07-29", "exercise": "Hip Abductor Machine",
                 "kg": 60, "reps": 8, "notes": ""}]
        e1rm = {"Hip Abductor Machine": {"current_e1rm_kg": 73.3,
                                         "last_date": "2026-07-29"}}
        half = 73.3 / (1 + 10 / 30) * UNILATERAL_FROM_BILATERAL
        for cand in self._all_candidates(e1rm, rows):
            if cand.get("load_kg") is None or not is_unilateral(cand["exercise"]):
                continue
            with self.subTest(exercise=cand["exercise"]):
                self.assertLessEqual(cand["load_kg"], half + 0.01)


_SKILL_MD = Path(__file__).resolve().parents[1] / "workout-coach" / "SKILL.md"
_BLOCKS_PY = (Path(__file__).resolve().parents[1] / "workout-coach" / "lib"
              / "blocks.py")


class SkillDocMatchesTheNullLoadContractTests(unittest.TestCase):
    """The coach is told what a null `load_kg` actually means.

    `SKILL.md` documented ONE null case, bodyweight, back when that was
    the only one. There are three now, and the other two — `no_reference`
    and `unknown_transfer` — mean "we could not derive a safe number",
    which is the opposite instruction. A coach that reads a null as
    "bodyweight" strips the load off a loaded lift; a coach that reads it
    as "pick something conservative" does the safe thing. The doc is the
    only place that distinction reaches the coach, because the coach is
    an LLM reading `SKILL.md` and not this module's docstrings.
    """

    #: Every ``load_basis`` that ships with ``load_kg: None``. Read from
    #: `derived_starting_load`'s `_blank` helper rather than restated, so
    #: adding a fourth null case fails this test instead of silently
    #: leaving the doc a case short.
    @property
    def null_bases(self) -> set:
        src = _BLOCKS_PY.read_text(encoding="utf-8")
        found = set(re.findall(r'_blank\(\s*"([a-z_]+)"', src))
        self.assertTrue(found, "no `_blank(...)` call sites found")
        return found

    def test_the_null_cases_are_the_three_we_think_they_are(self) -> None:
        self.assertEqual(self.null_bases,
                         {"bodyweight", "no_reference", "unknown_transfer"})

    def test_every_null_basis_is_named_in_the_skill_doc(self) -> None:
        doc = _SKILL_MD.read_text(encoding="utf-8")
        for basis in sorted(self.null_bases):
            with self.subTest(basis=basis):
                self.assertIn(basis, doc,
                              f"`load_basis: {basis}` produces a null "
                              f"load_kg and SKILL.md never mentions it")

    def test_the_doc_does_not_equate_a_null_load_with_bodyweight(self) -> None:
        # The two shipped sentences that did exactly that. Either one
        # coming back means the coach is being told a null is bodyweight.
        doc = _SKILL_MD.read_text(encoding="utf-8")
        for stale in (
                '`load_kg` (null with `unit: "bodyweight"` for bodyweight '
                'movements)',
                'Bodyweight candidates come back as `load_kg: null` with '
                '`unit: "bodyweight"` — prescribe reps or seconds, not a '
                'weight. A movement with no candidate entry'):
            self.assertNotIn(stale, doc)

    def test_both_sites_tell_the_coach_to_pick_a_conservative_load(self) -> None:
        # Both places a coach can land on the null rule have to carry the
        # instruction; fixing one leaves the other teaching the bug.
        doc = _SKILL_MD.read_text(encoding="utf-8")
        payload_site = doc[doc.index("- `rotation_candidates`:"):]
        payload_site = payload_site[:payload_site.index("\n**")]
        coldstart_site = doc[doc.index("**Cold-start escape hatch.**"):]
        coldstart_site = coldstart_site[:coldstart_site.index("\n  - `recovery")]
        for name, site in (("payload reference", payload_site),
                           ("cold-start rule", coldstart_site)):
            with self.subTest(site=name):
                for basis in ("no_reference", "unknown_transfer"):
                    self.assertIn(basis, site)
                self.assertIn("conservative", site)
                self.assertIn("2-3 reps in reserve", site)


if __name__ == "__main__":
    unittest.main()
