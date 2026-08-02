"""The gate gaps found by the 2026-08-02 blind-coach eval (G-05..G-09).

One file per finding-set rather than edits spread across the four suites
that already touch these modules, because every test here answers the
same question: the eval showed a rule that was documented, or assumed, or
outright exploited, and was not actually enforced. Grouping them keeps
the evidence next to the fix.

The findings, and what each class pins:

  G-05  the session set budget allowed +5 while SKILL.md asked for +-2.
  G-06  dose staleness and the stall response were never checked at all.
  G-07  a fabricated recovery score rendered at exit 0 beside the real one.
  G-09  a superset sub-bullet parsed only when it was the whole sub-bullet.
  ----  the sub-bullet counter counted structure as rationale creep.
  ----  `anchor_change_reason` had no honest token for a logged
        gym-floor substitution.

THE SECOND ROUND, same day. An adversarial review of the fixes above
found confirmed false positives and confirmed bypasses in them, and the
classes at the bottom of this file pin the repairs. Grouped here for the
same reason as the first round: the evidence belongs next to the fix.

  F1    G-07 refused the recovery-drivers card SKILL.md REQUIRES,
        because a per-driver `component {n}/10` sits next to the word
        "recovery".
  F2/F3 G-06 refused a SKILL.md-compliant one-session cadence deload AND
        was walked past by a rep-range shuffle. Demoted to advisory.
  P2    the drift threshold was a magnitude with a false justification.
        Replaced by decision equivalence.
  F4    G-07's proximity anchor was coach-controlled, and the check never
        read the card label it already held.
  F5    the plan markdown's own opener was never number-checked.
  F6    the stall response was laundered by one token bullet in another
        workout.
  F7    G-09's prefix backoff resolved hints to the WRONG host when the
        intended host was absent.
  F8    the structural-sub-bullet exemption was a `.search()` and so a
        smuggling channel.
  F9    G-06 crashed (exit 1) on a malformed dose dict.
  F10   `anchor_change_hint` was filtered against the full enum instead of
        the coach-declarable one.
  F11   SKILL.md says set churn is not a dose change; the code said it was.

Nothing here reads per-person tracker data: every fixture is written in
the file. The real 2026-08-02 plans were checked by hand against these
rules and pass all of them; see the branch notes.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from workout_coach.lib import render_validators as rv
from workout_coach.lib.adherence import _dose_delta, dose_staleness, parse_plan
from workout_coach.lib.blocks import (
    ANCHOR_CHANGE_REASONS,
    COACH_DECLARABLE_ANCHOR_CHANGE_REASONS,
    block_from_plan,
    load_pattern_catalog,
    new_block,
    rotation_diff_errors,
    rotation_diff_report,
)
from workout_coach.lib.constants import DOSE_PROGRESSION_SPEC
from workout_coach.lib.extract import load_exercises_db
from workout_coach.lib.render_validators import (
    coach_number_findings,
    dose_progression_findings,
    validate_coach_reads,
    validate_workout_md,
    validate_workout_plan,
    workout_set_budget_warnings,
)

_DB_PATH = Path(__file__).resolve().parents[1] / "shared" / "exercises-database.md"
_DB = load_exercises_db(_DB_PATH)
_CATALOG = load_pattern_catalog(_DB)


def _plan(date: str, body: str) -> str:
    return f"# Workout plan {date}\n\n## Workout 1: LOWER A + CORE\n\n{body}"


# Six carried exercises, which clears `min_carried_for_share`. Loads and
# rep ranges are the real 2026-07-25 prescriptions so the deltas below are
# the ones a coach would actually be writing.
_PREV_BODY = """- Barbell Back Squat: 100kgx8-10 /// 100kgx8-10 /// 100kgx8-10
- Romanian Deadlift: 100kgx10-12 /// 100kgx10-12 /// 100kgx10-12
- Leg Extension: 55kgx10-12 /// 55kgx10-12
- Calf Raise Machine: 55kgx12-15 /// 55kgx12-15
- Ab Crunch Machine: 35kgx12-15 /// 35kgx12-15
- Dumbbell Shrug: 60kgx12-15 /// 60kgx12-15
"""

_PROGRESSED_BODY = """- Barbell Back Squat: 105kgx8-10 /// 105kgx8-10 /// 105kgx8-10
- Romanian Deadlift: 85kgx6-8 /// 85kgx6-8 /// 85kgx6-8
- Leg Extension: 60kgx10-12 /// 60kgx10-12
- Calf Raise Machine: 60kgx12-15 /// 60kgx12-15
- Ab Crunch Machine: 40kgx12-15 /// 40kgx12-15
- Dumbbell Shrug: 64kgx12-15 /// 64kgx12-15
"""

_PREV_PLAN = _plan("2026-07-25", _PREV_BODY)
_RECOPIED_PLAN = _plan("2026-08-02", _PREV_BODY)
_PROGRESSED_PLAN = _plan("2026-08-02", _PROGRESSED_BODY)


def _prev_block(stalled: "dict | None" = None) -> dict:
    """The previous generation's block, doses and all.

    Built the way the pipeline builds it — `block_from_plan` over a parsed
    plan — rather than hand-written, so a change to what the artifact
    carries breaks these tests instead of quietly bypassing them.
    """
    block = block_from_plan(parse_plan(_PREV_PLAN, "2026-07-25"), _CATALOG)
    for slots in block["sessions"].values():
        for s in slots:
            n = (stalled or {}).get(s["exercise"])
            if n:
                s["stalled_sessions"] = n
    return block


# ---------------------------------------------------------------------------
class SetBudgetBandTests(unittest.TestCase):
    """G-05 — the prompt said land within +-2, the gate allowed 21-29.

    Four of the eight sessions the eval scored landed EXACTLY on the old
    +5 ceiling, which is what a band being used as a target looks like.
    """

    def test_the_band_is_symmetric_and_two(self) -> None:
        self.assertEqual(rv.SET_BUDGET_UNDER_TOL, 2)
        self.assertEqual(rv.SET_BUDGET_OVER_TOL, 2)
        self.assertLessEqual(rv.SET_BUDGET_UNDER_TOL, rv.SET_BUDGET_OVER_TOL,
                             "SKILL.md calls undershooting the worse failure, "
                             "so the low side may never be looser")

    def _sets(self, n: int) -> str:
        sets = " /// ".join(["50kgx8"] * n)
        return _plan("2026-08-02", f"- Barbell Back Squat: {sets}\n")

    def test_five_over_now_warns(self) -> None:
        # The shipped shape: 29 working sets against a 24 budget, silent
        # under the old 3/5 tolerances.
        warns = workout_set_budget_warnings(self._sets(29), 24)
        self.assertTrue(any("29 working sets vs budget 24" in w
                            for w in warns), warns)

    def test_two_over_is_still_inside_the_band(self) -> None:
        self.assertEqual(workout_set_budget_warnings(self._sets(26), 24), [])

    def test_two_under_is_still_inside_the_band(self) -> None:
        self.assertEqual(workout_set_budget_warnings(self._sets(22), 24), [])

    def test_three_under_warns(self) -> None:
        warns = workout_set_budget_warnings(self._sets(21), 24)
        self.assertTrue(any("3 under" in w for w in warns), warns)

    def test_tightening_it_can_never_block_a_render(self) -> None:
        """The whole safety argument for G-05 in one assertion.

        A budget finding must reach `warnings` and never `errors`, or
        tightening the band would have made four shipped sessions
        unrenderable.
        """
        errors, warnings = validate_workout_plan(self._sets(40),
                                                 target_working_sets=24)
        self.assertEqual([e for e in errors if "working sets vs budget" in e],
                         [])
        self.assertTrue(any("working sets vs budget" in w for w in warnings))


# ---------------------------------------------------------------------------
class DoseProgressionTests(unittest.TestCase):
    """G-06 — "every plan is the same plan", and the gate could not see it.

    `dose_staleness` and `stalled_sessions` were both computed into the
    payload and neither was ever read by a validator.
    """

    def test_a_re_copied_plan_is_refused(self) -> None:
        findings = dose_progression_findings(_RECOPIED_PLAN, _prev_block(),
                                             plan_date="2026-08-02")
        msgs = [m for _axis, m in findings]
        self.assertTrue(any("dose staleness" in m for m in msgs), msgs)
        self.assertTrue(any("100%" in m for m in msgs), msgs)

    def test_a_progressed_plan_is_clean(self) -> None:
        self.assertEqual(
            dose_progression_findings(_PROGRESSED_PLAN, _prev_block(),
                                      plan_date="2026-08-02"), [])

    def test_a_stalled_lift_re_prescribed_identically_is_refused(self) -> None:
        findings = dose_progression_findings(
            _RECOPIED_PLAN, _prev_block({"Romanian Deadlift": 4}),
            plan_date="2026-08-02")
        msgs = [m for _axis, m in findings]
        self.assertTrue(any(m.startswith("Romanian Deadlift: 4 sessions "
                                         "stalled") for m in msgs), msgs)

    def test_the_stall_response_must_be_a_number_not_a_sentence(self) -> None:
        """A sub-bullet saying the dose changed is not the dose changing.

        This is the whole reason the check reads the prescription and not
        the prose: the deciding input has to be something the coach
        cannot satisfy by writing a claim.
        """
        said_so = _RECOPIED_PLAN.replace(
            "- Romanian Deadlift: 100kgx10-12 /// 100kgx10-12 /// 100kgx10-12",
            "- Romanian Deadlift: 100kgx10-12 /// 100kgx10-12 /// 100kgx10-12"
            "\n  — anchor change: stall_3_sessions, rep range shifted")
        msgs = [m for _a, m in dose_progression_findings(
            said_so, _prev_block({"Romanian Deadlift": 4}),
            plan_date="2026-08-02")]
        self.assertTrue(any("Romanian Deadlift" in m for m in msgs), msgs)

    def test_a_cosmetic_bump_is_not_a_stall_response(self) -> None:
        # 0.5kg on 100kg is 0.5%, inside `adherence.DOSE_LOAD_MIN_PCT`.
        cosmetic = _RECOPIED_PLAN.replace("100kgx10-12", "100.5kgx10-12")
        msgs = [m for _a, m in dose_progression_findings(
            cosmetic, _prev_block({"Romanian Deadlift": 4}),
            plan_date="2026-08-02")]
        self.assertTrue(any("Romanian Deadlift" in m for m in msgs), msgs)

    def test_dropping_the_stalled_lift_is_a_response(self) -> None:
        dropped = _plan("2026-08-02", "\n".join(
            ln for ln in _PROGRESSED_BODY.splitlines()
            if "Romanian Deadlift" not in ln))
        msgs = [m for _a, m in dose_progression_findings(
            dropped, _prev_block({"Romanian Deadlift": 4}),
            plan_date="2026-08-02")]
        self.assertEqual([m for m in msgs if "Romanian Deadlift" in m], [])

    def test_silent_with_no_previous_block(self) -> None:
        self.assertEqual(
            dose_progression_findings(_RECOPIED_PLAN, None,
                                      plan_date="2026-08-02"), [])

    def test_silent_on_a_block_carrying_no_doses(self) -> None:
        """A block persisted before `dose` existed must not read as stale.

        "No comparison possible" and "compared and clean" have to be the
        same OUTPUT here, and they are; the payload's own `dose_staleness`
        block is where a reader tells them apart.
        """
        stripped = _prev_block()
        for slots in stripped["sessions"].values():
            for s in slots:
                s.pop("dose", None)
        self.assertEqual(
            dose_progression_findings(_RECOPIED_PLAN, stripped,
                                      plan_date="2026-08-02"), [])

    def test_silent_when_the_block_came_from_this_same_plan(self) -> None:
        """The self-diff guard `block_rotation_errors` already documents.

        Without it a re-render compares the plan against itself and every
        carried exercise reads unchanged.
        """
        self.assertEqual(
            dose_progression_findings(_RECOPIED_PLAN, _prev_block(),
                                      plan_date="2026-07-25"), [])

    def test_an_undated_pair_does_not_crash(self) -> None:
        """`dose_staleness` keys its series by plan date.

        Two plans on one date collapse to a one-item series and its
        ``slots[-2]`` indexes past the front of the list. Reachable with
        no ``plan_date`` against a block with no ``started``. An
        IndexError here would exit 1, and 1 means the program broke, not
        that the plan was refused.
        """
        undated = _prev_block()
        undated["started"] = None
        self.assertEqual(
            dose_progression_findings(_RECOPIED_PLAN, undated), [])

    def test_it_surfaces_through_validate_workout_plan_as_advisory(self) -> None:
        """ADVISORY, not blocking, and the switch is the only reason.

        It shipped blocking on 2026-08-02 and was demoted the same day:
        `DOSE_PROGRESSION_ENFORCED` records the SKILL.md-compliant cadence
        deload it refuses and the rep-range shuffle that walks past it.
        `DemotionIsOneSwitchTests` below pins that flipping the constant is
        the whole of re-arming it.
        """
        errors, warnings = validate_workout_plan(
            _RECOPIED_PLAN, prev_block=_prev_block(), plan_date="2026-08-02")
        self.assertEqual([e for e in errors if "dose staleness" in e], [])
        self.assertTrue(any("dose staleness" in w and rv.DOSE_ADVISORY_TAG in w
                            for w in warnings), warnings)

    def test_a_deload_week_does_not_relax_it(self) -> None:
        """Changing a load costs no fatigue, so this is not a VOLUME axis.

        The deload relief is `AXIS_VOLUME` only, so it must not touch
        these findings whether they are routed as errors or as advisories.
        This is ALSO why the demotion was needed rather than a deload
        exemption: SKILL.md's cadence deload holds loads by instruction, so
        no volume-axis relief could ever have reached it.
        """
        with patch.object(rv, "DOSE_PROGRESSION_ENFORCED", True):
            errors, _ = validate_workout_plan(
                _RECOPIED_PLAN, prev_block=_prev_block(),
                plan_date="2026-08-02", deload_week=True)
        self.assertTrue(any("dose staleness" in e for e in errors), errors)

    def test_the_target_is_one_number_read_by_two_modules(self) -> None:
        """The gate's threshold and the payload's reported target agree.

        `adherence.dose_staleness` reports `target_max_pct` to the coach
        while it is authoring; `DOSE_PROGRESSION_SPEC` is what refuses the
        result. If those two ever drift, the coach is told it passed and
        the render says otherwise.
        """
        report = dose_staleness(
            [parse_plan(_PREV_PLAN, "2026-07-25"),
             parse_plan(_PROGRESSED_PLAN, "2026-08-02")], _DB)
        self.assertEqual(report["target_max_pct"],
                         DOSE_PROGRESSION_SPEC["max_unchanged_share"])

    def test_a_short_carry_list_does_not_bind(self) -> None:
        """Below `min_carried_for_share` the ratio measures arithmetic.

        Two carried lifts, both held: 100% unchanged, and a deload or
        comeback week routinely looks like that. The per-exercise stall
        rule still bites there; the rate does not.
        """
        two = "- Leg Extension: 55kgx10-12 /// 55kgx10-12\n" \
              "- Dumbbell Shrug: 60kgx12-15 /// 60kgx12-15\n"
        self.assertLess(2, DOSE_PROGRESSION_SPEC["min_carried_for_share"])
        self.assertEqual(
            dose_progression_findings(_plan("2026-08-02", two), _prev_block(),
                                      plan_date="2026-08-02"), [])


# ---------------------------------------------------------------------------
class CoachNumberCrossCheckTests(unittest.TestCase):
    """G-07 — the reproduced exploit: a made-up score rendered at exit 0.

    The payload's real `recovery.score` was 5.6; the headline claimed 10
    out of 10; the finished page showed both, 118 KB of it, and the 44
    warnings that fired were all "card missing or empty".
    """

    PAYLOAD = {"recovery": {"score": 5.6}}
    EXPLOIT = {"headline": "Everything is fine. Recovery is 10 out of 10. "
                           "Train hard.", "cards": {}}

    def test_the_reproduced_exploit_is_refused(self) -> None:
        errors, _ = validate_coach_reads(self.EXPLOIT, self.PAYLOAD)
        self.assertTrue(any("recovery.score" in e for e in errors), errors)

    def test_it_renders_when_the_payload_is_not_passed(self) -> None:
        """Back-compat, stated out loud because it is a live hole.

        `validate_coach_reads(coach)` with no payload cannot cross-check
        anything, so the exploit above still renders through that call.
        Any caller that HAS the payload must pass it.
        """
        errors, _ = validate_coach_reads(self.EXPLOIT)
        self.assertEqual([e for e in errors if "recovery.score" in e], [])

    def test_the_exact_number_passes(self) -> None:
        errors, warnings = validate_coach_reads(
            {"headline": "Recovery 5.6 out of 10, green.", "cards": {}},
            self.PAYLOAD)
        self.assertEqual([e for e in errors if "recovery" in e], [])
        self.assertEqual([w for w in warnings if "recovery is" in w], [])

    def test_an_honest_round_passes(self) -> None:
        # Compared at the precision the coach wrote, so "6/10" is a legal
        # rendering of 5.6. Refusing it would be the false positive that
        # gets the check turned off.
        errors, _ = validate_coach_reads(
            {"headline": "Recovery is 6/10 today.", "cards": {}}, self.PAYLOAD)
        self.assertEqual([e for e in errors if "recovery" in e], [])

    def test_a_card_callout_is_checked_too(self) -> None:
        errors, _ = validate_coach_reads(
            {"headline": "ok",
             "cards": {"recovery_drivers": "Your recovery sits at 9/10."}},
            self.PAYLOAD)
        self.assertTrue(any("cards.recovery_drivers" in e for e in errors))

    def test_an_unrelated_out_of_ten_is_ignored(self) -> None:
        """Precision, not recall. The anchor is the word "recovery"."""
        errors, warnings = validate_coach_reads(
            {"headline": "You logged 8 out of 10 prescribed sets.",
             "cards": {}}, self.PAYLOAD)
        self.assertEqual(errors, [])
        self.assertEqual([w for w in warnings if "recovery is" in w], [])

    def test_the_word_has_to_be_near_the_number(self) -> None:
        far = ("Recovery is the theme this week. " + "x" * 60
               + " You completed 8 out of 10 sessions.")
        errors, _ = validate_coach_reads({"headline": far, "cards": {}},
                                         self.PAYLOAD)
        self.assertEqual(errors, [])

    def test_a_tenth_of_a_point_warns_instead_of_blocking(self) -> None:
        """Measured: re-deriving old payloads moved scores by 0.1.

        Those pages were written against a payload built before the
        2026-08 data migrations. That is a re-derived number, not a false
        one, and refusing to re-render for it is the false positive worth
        avoiding.
        """
        errors, warnings = coach_number_findings(
            self.PAYLOAD, [("`headline`", "Recovery 5.5 out of 10.")])
        self.assertEqual(errors, [])
        self.assertTrue(any("re-derived payload" in w for w in warnings))

    def test_a_missing_score_is_not_a_finding(self) -> None:
        self.assertEqual(coach_number_findings(
            {"recovery": {}}, [("`headline`", "Recovery 9/10.")]), ([], []))
        self.assertEqual(coach_number_findings(
            None, [("`headline`", "Recovery 9/10.")]), ([], []))


# ---------------------------------------------------------------------------
class SupersetHintParseTests(unittest.TestCase):
    """G-09 — the pairing was written; only the parse failed.

    The resulting error then told the coach the slot was "left
    standalone", which was false, and the documented remedy (split the
    note in two) inflated the sub-bullet-count warning. One bad warning
    manufactured another.
    """

    def _hosts(self, note: str) -> dict:
        text = _plan("2026-08-02", (
            "- Cable Lat Pulldown: 65kgx6-8 /// 65kgx6-8 /// 65kgx6-8\n"
            "- Dumbbell Lateral Raise: 16kgx10 /// 16kgx10\n"
            f"  {note}\n"))
        block = block_from_plan(parse_plan(text, "2026-08-02"), _CATALOG)
        return {s["exercise"]: s.get("superset_with")
                for s in block["sessions"]["lower_a"]}

    def test_the_bare_form_still_resolves(self) -> None:
        hosts = self._hosts("— superset with the cable lat pulldown above")
        self.assertEqual(hosts["Dumbbell Lateral Raise"], "Cable Lat Pulldown")

    def test_a_trailing_clause_no_longer_defeats_it(self) -> None:
        hosts = self._hosts("— superset with the cable lat pulldown above, "
                            "leave 2-3 in the tank")
        self.assertEqual(hosts["Dumbbell Lateral Raise"], "Cable Lat Pulldown")

    def test_an_ambiguous_hint_still_refuses_to_guess(self) -> None:
        """Backing off a word can only ADD candidates, never resolve a tie."""
        text = _plan("2026-08-02", (
            "- Cable Standing Calf Raise: 50kgx10 /// 50kgx10\n"
            "- Calf Raise Machine: 55kgx10 /// 55kgx10\n"
            "- Dumbbell Lateral Raise: 16kgx10 /// 16kgx10\n"
            "  — superset with the calf raise above, keep it tight\n"))
        block = block_from_plan(parse_plan(text, "2026-08-02"), _CATALOG)
        slot = [s for s in block["sessions"]["lower_a"]
                if s["exercise"] == "Dumbbell Lateral Raise"][0]
        self.assertIsNone(slot.get("superset_with"))

    def test_an_unresolvable_hint_gets_an_honest_message(self) -> None:
        """Not "left standalone" — the pairing was written."""
        text = _plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8 /// 100kgx8\n"
            "- Dumbbell Lateral Raise: 16kgx10 /// 16kgx10\n"
            "  — superset with the overhead press, keep 2 in reserve\n"))
        new = block_from_plan(parse_plan(text, "2026-08-02"), _CATALOG)
        errors = rotation_diff_errors(None, new, _CATALOG)
        pairing = [e for e in errors if "Dumbbell Lateral Raise" in e]
        self.assertTrue(any("does not resolve to any exercise" in e
                            for e in pairing), pairing)
        self.assertEqual([e for e in pairing if "left standalone" in e], [])


# ---------------------------------------------------------------------------
class SubBulletCounterTests(unittest.TestCase):
    """The counter fired on every compliant plan.

    It counted structural routing lines against a cap meant for rationale
    creep, so satisfying the block rules on two slots spent the entire
    annotation budget and SKILL.md had to tell the coach to ignore the
    warning. A warning that is always wrong trains a reader to skip the
    ones that are right.
    """

    def test_superset_routing_does_not_count(self) -> None:
        # The verified shape: four sub-bullets, two of them superset
        # routing, so the real annotation count is 2 — at the limit.
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "- Cable Standing Calf Raise: 50kgx10 /// 50kgx10\n"
            "  — superset with the back squat above\n"
            "- Romanian Deadlift: 85kgx8 /// 85kgx8\n"
            "  — load cut, four sessions flat\n"
            "- Ab Crunch Machine: 35kgx12 /// 35kgx12\n"
            "  — superset with the back squat above\n"
            "- Suitcase Carry: 24kgx30m /// 24kgx30m\n"
            "  — both sides every set\n")))
        self.assertEqual([w for w in warnings if "sub-bullets" in w], [])

    def test_three_rationale_sub_bullets_still_warn(self) -> None:
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "  — knees track over toes\n"
            "- Romanian Deadlift: 85kgx8 /// 85kgx8\n"
            "  — brace before the first rep\n"
            "- Leg Extension: 55kgx10 /// 55kgx10\n"
            "  — slow on the way down\n")))
        self.assertTrue(any("3 rationale sub-bullets" in w for w in warnings),
                        warnings)

    def test_an_anchor_change_line_is_structure_too(self) -> None:
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "  — anchor change: injury\n"
            "- Romanian Deadlift: 85kgx8 /// 85kgx8\n"
            "  — anchor change: stall_3_sessions\n"
            "- Leg Extension: 55kgx10 /// 55kgx10\n"
            "  — anchor change: age_3_blocks\n")))
        self.assertEqual([w for w in warnings if "sub-bullets" in w], [])

    def test_rationale_bolted_onto_a_superset_line_still_warns(self) -> None:
        """The exemption is for structure, not for a smuggling channel."""
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "- Cable Standing Calf Raise: 50kgx10 /// 50kgx10\n"
            "  — superset with the back squat above because you have been "
            "stuck at 50kg\n")))
        self.assertTrue(any("comparative-history" in w for w in warnings),
                        warnings)


# ---------------------------------------------------------------------------
class UserSubstitutionReasonTests(unittest.TestCase):
    """The missing vocabulary: the ledger records real gym-floor swaps.

    Prescribing what the user demonstrably performs is what SKILL.md asks
    for, and the enum had no token for it, so both eval agents chose
    between taking a spurious warning and writing a lie. The token now
    exists and is DERIVED ONLY — the deciding input is the ledger, not the
    coach.
    """

    def _prev(self, **slot_kw) -> dict:
        return new_block("2026-06-01", {"lower_a": [
            dict(position=1, exercise="Barbell Hip Thrust", tag="anchor",
                 **slot_kw),
            dict(position=2, exercise="Leg Extension", tag="rotating",
                 superset_with="Barbell Hip Thrust"),
        ]})

    def _new(self, prev, replacement="Dumbbell Hip Thrust", **anchor_kw):
        return new_block("2026-07-13", {"lower_a": [
            dict(position=1, exercise=replacement, tag="anchor", **anchor_kw),
            dict(position=2, exercise="Cable Pallof Press", tag="rotating",
                 superset_with=replacement),
        ]}, prev_block=prev)

    def test_the_token_exists(self) -> None:
        self.assertIn("user_substitution", ANCHOR_CHANGE_REASONS)

    def test_the_coach_may_not_declare_it(self) -> None:
        """The provenance rule, as an assertion.

        Every other reason is either a payload fact or a one-off human
        statement. This one is a claim ABOUT the ledger, so only the
        ledger may make it.
        """
        self.assertNotIn("user_substitution",
                         COACH_DECLARABLE_ANCHOR_CHANGE_REASONS)
        for r in COACH_DECLARABLE_ANCHOR_CHANGE_REASONS:
            self.assertIn(r, ANCHOR_CHANGE_REASONS)

    def test_a_logged_substitution_qualifies_the_change(self) -> None:
        prev = self._prev(performed_instead="Dumbbell Hip Thrust")
        report = rotation_diff_report(prev, self._new(prev), _CATALOG)
        self.assertEqual([e for e in report["errors"] if "anchor changed" in e],
                         [])
        self.assertTrue(any("user_substitution" in n and "ledger" in n
                            for n in report["notes"]), report["notes"])

    def test_declaring_it_without_the_ledger_does_not_work(self) -> None:
        prev = self._prev()                      # no performed_instead
        errs = rotation_diff_errors(
            prev, self._new(prev, anchor_change_reason="user_substitution"),
            _CATALOG)
        self.assertTrue(any("anchor changed" in e for e in errs), errs)

    def test_it_only_excuses_prescribing_what_was_performed(self) -> None:
        """The ledger's claim is narrow: the user did X instead of Y.

        Dropping Y for something the user never performed is a different
        decision and needs a different reason.
        """
        prev = self._prev(performed_instead="Dumbbell Hip Thrust")
        errs = rotation_diff_errors(
            prev, self._new(prev, replacement="Barbell Good Morning"),
            _CATALOG)
        self.assertTrue(any("anchor changed" in e for e in errs), errs)

    def test_the_remedy_text_does_not_advertise_it(self) -> None:
        prev = self._prev()
        errs = [e for e in rotation_diff_errors(prev, self._new(prev),
                                                _CATALOG)
                if "anchor changed" in e]
        self.assertTrue(errs)
        self.assertIn("stall_3_sessions, injury, age_3_blocks", errs[0])
        self.assertIn("not declarable", errs[0])


# ===========================================================================
# The second round: the review of the fixes above.
# ===========================================================================
class ComponentScoreIsNotTheCompositeTests(unittest.TestCase):
    """F1 — G-07 blocked the card SKILL.md marks REQUIRED.

    The drivers card must print every driver, and the mandated line format
    ends `component {component_score}/10` with a worked example of
    `component 1.6/10`. `recovery.drivers[].component_score` is a 0-10
    scalar, so the docstring's premise — that `recovery.score` "has a shape
    nothing else in the vocabulary shares" — was false about the very
    payload block the card renders. A prompt-faithful card was exit 2.
    """

    PAYLOAD = {"recovery": {"score": 5.4, "drivers": [
        {"metric": "hr_recovery_1min", "component_score": 1.6},
        {"metric": "wrist_temp_c", "component_score": 3.4},
    ]}}

    def test_the_prompt_faithful_drivers_card_renders(self) -> None:
        card = ("Recovery 5.4 out of 10, moderate. HR recovery is the drag at "
                "1.6 out of 10; wrist temp sits at 3.4 out of 10.")
        errors, warnings = validate_coach_reads(
            {"headline": "ok", "cards": {"recovery_drivers": card}},
            self.PAYLOAD)
        self.assertEqual([e for e in errors if "recovery" in e], [])
        self.assertEqual([w for w in warnings if "says recovery" in w], [])

    def test_the_documented_line_format_renders(self) -> None:
        """SKILL.md's own worked example, verbatim."""
        card = ("HR Recovery: 35.5bpm recent vs personal baseline 37.4 "
                "(z -1.35, weight 0.10, component 1.6/10)")
        errors, _ = coach_number_findings(self.PAYLOAD,
                                          [("cards.recovery_drivers", card)])
        self.assertEqual(errors, [])

    def test_hr_recovery_is_a_different_metric(self) -> None:
        """The lookbehind, on its own. `hr_recovery_1min` is a DRIVER."""
        errors, _ = coach_number_findings(
            self.PAYLOAD, [("cards.recovery_drivers",
                            "HR recovery is 1.6 out of 10.")])
        self.assertEqual(errors, [])

    def test_contradicting_the_headline_score_is_still_refused(self) -> None:
        """The other half of F1: legal to cite, illegal to contradict."""
        card = ("Recovery 9.9 out of 10, green. HR recovery is the drag at "
                "1.6 out of 10.")
        errors, _ = coach_number_findings(self.PAYLOAD,
                                          [("cards.recovery_drivers", card)])
        self.assertTrue(any("9.9 out of 10" in e for e in errors), errors)


# ---------------------------------------------------------------------------
class RecoveryScoreAnchorTests(unittest.TestCase):
    """F4 — the anchor was coach-controlled, and the label went unread.

    Moving the word "recovery" more than `COACH_SCORE_PROXIMITY_CHARS`
    from the number silenced the check, and so did every paraphrase of the
    number. 7 of 8 probed variants were silent. The proximity window is
    gone; the label is read.
    """

    PAYLOAD = {"recovery": {"score": 5.4}}
    SURFACE = "`headline`"
    DRIVERS = "cards.recovery_drivers"

    def _verdict(self, label: str, text: str) -> str:
        errors, warnings = coach_number_findings(self.PAYLOAD, [(label, text)])
        return "error" if errors else ("warn" if warnings else "silent")

    def test_the_label_anchors_what_prose_does_not(self) -> None:
        """The variants that carry an ``N/10`` are now caught by label."""
        for text in ("Readiness is 10 out of 10.",
                     "Sitting at 10 out of 10 across the board.",
                     "Recovery is the theme this week. " + "x" * 60
                     + " You are a 9 out of 10."):
            self.assertEqual(self._verdict(self.SURFACE, text), "error", text)

    def test_the_surfaces_are_the_composite_ones_only(self) -> None:
        self.assertEqual(rv.RECOVERY_SCORE_SURFACES, frozenset({
            "`headline`", "cards.session_recommendation_callout",
            "plan opener"}))
        self.assertNotIn(self.DRIVERS, rv.RECOVERY_SCORE_SURFACES)

    def test_the_drivers_cards_are_deliberately_not_label_anchored(self) -> None:
        """The F1 trade, pinned so it cannot be "fixed" back into a bug.

        A bare ``N/10`` on the drivers card is legitimately a component
        score. Anchoring those two cards on the label would refuse the
        card SKILL.md mandates, which is the exact defect F1 records.
        """
        self.assertEqual(self._verdict(self.DRIVERS, "Readiness is 10 out of 10."),
                         "silent")
        self.assertEqual(self._verdict(self.DRIVERS, "Recovery is 10 out of 10."),
                         "error")

    def test_a_counted_ratio_is_not_the_score(self) -> None:
        """The false positive the label anchor would otherwise create."""
        for text in ("You logged 8 out of 10 prescribed sets.",
                     "You completed 8 out of 10 sessions.",
                     "Recovery: 3 out of 10 sessions this week."):
            self.assertEqual(self._verdict(self.SURFACE, text), "silent", text)

    def test_what_is_still_uncovered_is_stated_and_true(self) -> None:
        """Narrow and honest. These are silent BY DESIGN, not by accident.

        Pinned so a later reader finds the residual in a test rather than
        discovering it adversarially, and so the docstring's list of what
        the anchor does not cover cannot rot away from the code.
        """
        for text in ("Recovery: you are a 10 today.",
                     "Recovery is ten out of ten.",
                     "Recovery is 96 out of 100.",
                     "Recovery is 98% of your baseline.",
                     # The counted-ratio tail silences both rules. Reading
                     # "N out of 10 sets" as a score is the false positive
                     # `test_a_counted_ratio_is_not_the_score` pins.
                     "Recovery is 10 out of 10 sets.",
                     # Rule B spends its one look on a decoy that agrees.
                     "Your sleep scored 5.4 out of 10. Readiness is a 10 "
                     "out of 10."):
            self.assertEqual(self._verdict(self.SURFACE, text), "silent", text)
        self.assertIn("WHAT REMAINS UNCOVERED",
                      Path(rv.__file__).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
class DecisionBoundaryDriftTests(unittest.TestCase):
    """P2 — the drift threshold was a magnitude with a false rationale.

    `COACH_SCORE_MAX_DRIFT = 1.0` was justified by a comment claiming a
    full point "spans two of SKILL.md's recovery tiers (5.0 / 5.5
    boundaries)" and that "anything under it changes no decision". 5.0 is
    not a boundary in SKILL.md at all, and at 1.0 a coach could write 6.4
    against a real 5.4 — across `tier_d_recovery_score_min` — and only
    warn. Magnitude was the wrong instrument.
    """

    def _verdict(self, written, score) -> str:
        errors, warnings = coach_number_findings(
            {"recovery": {"score": score}},
            [("`headline`", f"Recovery {written} out of 10.")])
        return "error" if errors else ("warn" if warnings else "silent")

    def test_the_five_verification_cases(self) -> None:
        self.assertEqual(self._verdict(5.2, 5.4), "warn")   # measured drift
        self.assertEqual(self._verdict(4.5, 4.7), "warn")   # measured drift
        self.assertEqual(self._verdict(6.4, 5.4), "error")  # crosses 5.5
        self.assertEqual(self._verdict(10, 5.4), "error")   # crosses 5.5, 6.5
        self.assertEqual(self._verdict(3.9, 2.9), "error")  # crosses 3.0

    def test_magnitude_alone_decides_nothing(self) -> None:
        """Both directions of the point the old threshold got backwards."""
        # 1.4 points apart, no boundary between them: not a different claim.
        self.assertEqual(self._verdict(5.1, 3.7), "error")  # crosses 4.0, 5.0
        self.assertEqual(self._verdict(6.6, 8.0), "warn")   # 1.4, above 6.5
        # 0.3 apart, across the Tier D floor: a different claim.
        self.assertEqual(self._verdict(5.7, 5.4), "error")

    def test_the_float_verdict_is_deterministic(self) -> None:
        """`abs(4.9 - 3.9)` is 1.0000000000000004; `abs(6.4 - 5.4)` is 1.0.

        The old magnitude compare gave those two the same-sized gap and
        different verdicts. Whatever the rule decides, it must decide the
        same thing for both.
        """
        self.assertEqual(self._verdict(4.9, 3.9), self._verdict(6.4, 5.4))
        self.assertNotEqual(abs(4.9 - 3.9), abs(6.4 - 5.4))

    def test_the_boundaries_are_derived_from_constants(self) -> None:
        """Not a restated copy. Move a threshold, move the boundary."""
        from workout_coach.lib.constants import SESSION_GATE_THRESHOLDS
        boundaries = rv.recovery_decision_boundaries()
        for key in ("tier_a_recovery_score_crash", "tier_c_recovery_hard_floor",
                    "tier_d_recovery_score_min", "tier_c_recovery_score_hi"):
            self.assertIn(SESSION_GATE_THRESHOLDS[key], boundaries, key)
        for edge in rv.SKILL_RECOVERY_BAND_EDGES:
            self.assertIn(edge, boundaries)

    def test_a_moved_threshold_moves_the_gate(self) -> None:
        moved = dict(
            __import__("workout_coach.lib.constants", fromlist=["x"]
                       ).SESSION_GATE_THRESHOLDS)
        moved["tier_d_recovery_score_min"] = 7.5
        rv.recovery_decision_boundaries.cache_clear()
        try:
            with patch("workout_coach.lib.constants.SESSION_GATE_THRESHOLDS",
                       moved):
                self.assertIn(7.5, rv.recovery_decision_boundaries())
                self.assertNotIn(5.5, rv.recovery_decision_boundaries())
        finally:
            rv.recovery_decision_boundaries.cache_clear()
        self.assertIn(5.5, rv.recovery_decision_boundaries())

    def test_the_noise_floor_only_ever_downgrades_a_straddle(self) -> None:
        """The measured case: the shipped opener says 5.6, the payload 5.4.

        The plan was authored that afternoon against a payload that said
        5.6; a health import landed hours later and the composite moved to
        5.4, straddling 5.5. Refusing to re-render an honest page for 0.2
        of re-derivation is the false positive that gets a gate switched
        off, so it warns — and the warning NAMES the boundary, because
        "inside the noise" is not the same as "agrees".
        """
        errors, warnings = coach_number_findings(
            {"recovery": {"score": 5.4}},
            [("plan opener", "Recovery 5.6 out of 10, green.")])
        self.assertEqual(errors, [])
        self.assertTrue(any("straddles 5.5" in w for w in warnings), warnings)
        self.assertLessEqual(rv.COACH_SCORE_REDERIVE_NOISE, 0.2,
                             "the floor is a measurement, not a budget")

    def test_the_widest_band_is_what_this_lets_through(self) -> None:
        """Stated, not hidden: decision equivalence permits overstatement.

        The highest boundary is 6.5, so everything from there to 10 is one
        band and "9.9" against a real 6.6 only warns. Both numbers
        prescribe green-light programming, which is the rule working as
        specified — and it is still an overstatement on the page, so the
        warning is the only thing that says so.
        """
        self.assertEqual(max(rv.recovery_decision_boundaries()), 6.5)
        self.assertEqual(self._verdict(9.9, 6.6), "warn")

    def test_the_old_constant_is_gone(self) -> None:
        self.assertFalse(hasattr(rv, "COACH_SCORE_MAX_DRIFT"))
        self.assertFalse(hasattr(rv, "COACH_SCORE_PROXIMITY_CHARS"))


# ---------------------------------------------------------------------------
class PlanOpenerIsNumberCheckedTests(unittest.TestCase):
    """F5 — the string the user reads mid-workout shipped unchecked.

    `validate_coach_reads` got the payload; the two plan-markdown
    validators did not. One published page carried three different
    recovery numbers: 5.6 in the opener, 5.2 in a card callout, 5.4 in the
    payload, and the render exited 0.
    """

    PAYLOAD = {"recovery": {"score": 5.4}}

    def _plan_with(self, opener: str) -> str:
        return (f"# Workout plan 2026-08-02\n> Why: {opener}\n\n"
                "## Workout 1: LOWER A + CORE\n\n"
                "- Barbell Back Squat: 100kgx8 /// 100kgx8 /// 100kgx8\n")

    def test_a_fabricated_opener_is_refused(self) -> None:
        errors, _ = validate_workout_plan(
            self._plan_with("Recovery 9.8 out of 10, green light."),
            payload=self.PAYLOAD)
        self.assertTrue(any(e.startswith("plan opener:") for e in errors), errors)

    def test_the_honest_opener_passes(self) -> None:
        errors, warnings = validate_workout_plan(
            self._plan_with("Recovery 5.4 out of 10, moderate."),
            payload=self.PAYLOAD)
        self.assertEqual([e for e in errors if e.startswith("plan opener")], [])
        self.assertEqual([w for w in warnings if w.startswith("plan opener")], [])

    def test_a_caller_without_the_payload_keeps_the_old_behaviour(self) -> None:
        """Stated out loud, because it is the same live hole G-07 has.

        Every existing caller and every test that only has markdown keeps
        working; a caller that HAS the payload must pass it, and
        `render_dashboard` does.
        """
        errors, _ = validate_workout_plan(
            self._plan_with("Recovery 9.8 out of 10, green light."))
        self.assertEqual([e for e in errors if e.startswith("plan opener")], [])

    def test_the_renderer_passes_it(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "workout-coach"
                  / "scripts" / "render_dashboard.py").read_text(encoding="utf-8")
        self.assertIn("payload=j,", source)

    def test_the_body_is_split_from_the_opener(self) -> None:
        """A rep scheme in a bullet must never read as a recovery claim."""
        labels = [lab for lab, _t in rv._plan_texts(
            self._plan_with("Recovery 5.4 out of 10."))]
        self.assertEqual(labels, ["plan opener", "plan body"])
        self.assertNotIn("plan body", rv.RECOVERY_SCORE_SURFACES)


# ---------------------------------------------------------------------------
class DoseGateDemotionTests(unittest.TestCase):
    """F2 + F3 — the worst combination: false positives AND a bypass.

    SKILL.md's cadence deload is ONE session with its sets halved and its
    loads HELD ("hold loads" is binding). Build exactly that and the rate
    finding fires, and `deload_week=True` gives no relief because these
    are structure-axis findings. The same SKILL.md paragraph also says a
    lift with nowhere to go may "read as stale". Meanwhile the check is
    walked past by shifting rep ranges one midpoint and back again.
    """

    def test_the_switch_exists_and_is_off(self) -> None:
        self.assertFalse(rv.DOSE_PROGRESSION_ENFORCED)
        self.assertIn("advisory", rv.DOSE_ADVISORY_TAG)

    def test_flipping_the_constant_is_the_whole_of_re_arming_it(self) -> None:
        """The `BLOCK_ROTATION_ENFORCED` precedent, followed exactly."""
        args = dict(prev_block=_prev_block(), plan_date="2026-08-02")

        errors, warnings = validate_workout_plan(_RECOPIED_PLAN, **args)
        self.assertEqual([e for e in errors if "dose staleness" in e], [])
        tagged = [w for w in warnings if rv.DOSE_ADVISORY_TAG in w]
        self.assertTrue(tagged, warnings)

        with patch.object(rv, "DOSE_PROGRESSION_ENFORCED", True):
            on_errors, on_warnings = validate_workout_plan(_RECOPIED_PLAN, **args)
        self.assertTrue(any("dose staleness" in e for e in on_errors), on_errors)
        self.assertEqual(
            [w for w in on_warnings if rv.DOSE_ADVISORY_TAG in w], [])

    def test_the_findings_are_the_same_either_way(self) -> None:
        """Demotion changes the ROUTE, not the rule."""
        bare = [m for _axis, m in dose_progression_findings(
            _RECOPIED_PLAN, _prev_block(), plan_date="2026-08-02")]
        self.assertTrue(bare)
        _errors, warnings = validate_workout_plan(
            _RECOPIED_PLAN, prev_block=_prev_block(), plan_date="2026-08-02")
        tagged = [w[:-len(rv.DOSE_ADVISORY_TAG) - 1] for w in warnings
                  if w.endswith(rv.DOSE_ADVISORY_TAG)]
        self.assertEqual(tagged, bare)

    def test_a_compliant_cadence_deload_cannot_exit_2(self) -> None:
        """F2, as the plan SKILL.md actually asks for.

        One session's working sets halved, every load held. Under the old
        routing this was exit 2 on a plan built to instruction.
        """
        held = _plan("2026-08-02", _PREV_BODY.replace(
            "- Leg Extension: 55kgx10-12 /// 55kgx10-12",
            "- Leg Extension: 55kgx10-12"))
        errors, warnings = validate_workout_plan(
            held, prev_block=_prev_block(), plan_date="2026-08-02")
        self.assertEqual([e for e in errors if "dose staleness" in e], [])
        self.assertTrue(any("dose staleness" in w for w in warnings), warnings)

    def test_the_bypass_is_recorded_where_the_switch_is(self) -> None:
        """The rep-range shuffle still passes; that is why it is advisory.

        A reader who flips the constant has to meet this test and the
        comment beside it, both of which say the ledger-side rewrite comes
        first.
        """
        shuffled = _plan("2026-08-02", _PREV_BODY.replace("x8-10", "x9-11")
                         .replace("x10-12", "x11-13").replace("x12-15", "x13-16"))
        with patch.object(rv, "DOSE_PROGRESSION_ENFORCED", True):
            errors, _ = validate_workout_plan(
                shuffled, prev_block=_prev_block(), plan_date="2026-08-02")
        self.assertEqual([e for e in errors if "dose staleness" in e], [],
                         "the bypass is real; the comment on "
                         "DOSE_PROGRESSION_ENFORCED must keep saying so")
        source = Path(rv.__file__).read_text(encoding="utf-8")
        self.assertIn("THE REAL FIX IS NOT THIS", source)

    def _oscillating_payload(self) -> dict:
        """A payload whose own `dose_staleness` saw 90 / 92.5 / 90 / 92.5."""
        plans = [parse_plan(_plan(d, f"- Leg Extension: {kg}kgx10-12 /// "
                                     f"{kg}kgx10-12\n"), d)
                 for d, kg in zip(("2026-07-05", "2026-07-12", "2026-07-19",
                                   "2026-07-26"), ("90", "92.5", "90", "92.5"))]
        report = dose_staleness(plans, _DB)
        self.assertEqual(report["oscillating_count"], 1)
        return {"dose_staleness": report}

    def test_the_oscillation_detector_is_finally_consumed(self) -> None:
        """`dose_staleness.oscillating` existed and no gate read it.

        90 / 92.5 / 90 / 92.5 changes the dose every generation and
        progresses nothing, which satisfies both other findings forever.
        """
        msgs = [m for _a, m in dose_progression_findings(
            _RECOPIED_PLAN, None, plan_date="2026-08-02",
            payload=self._oscillating_payload())]
        self.assertTrue(any("alternated between two values" in m
                            for m in msgs), msgs)

    def test_it_cannot_be_computed_from_the_two_generations_here(self) -> None:
        """The trap the first draft of this finding fell into.

        `dose_progression_findings` holds the block artifact plus the plan
        under validation — two generations — and `oscillating` needs four.
        Computed locally it is dead code that always answers "no". Pinned
        so nobody moves it back.
        """
        self.assertEqual(
            [m for _a, m in dose_progression_findings(
                _RECOPIED_PLAN, _prev_block(), plan_date="2026-08-02")
             if "alternated" in m], [])

    def test_it_reaches_stderr_as_an_advisory(self) -> None:
        errors, warnings = validate_workout_plan(
            _RECOPIED_PLAN, prev_block=_prev_block(), plan_date="2026-08-02",
            payload=self._oscillating_payload())
        self.assertEqual([e for e in errors if "alternated" in e], [])
        self.assertTrue(any("alternated" in w and rv.DOSE_ADVISORY_TAG in w
                            for w in warnings), warnings)


# ---------------------------------------------------------------------------
class StallLaunderingTests(unittest.TestCase):
    """F6 — one token bullet in another workout erased the finding.

    `dose_staleness` collapsed an exercise to its HEAVIEST prescription in
    the plan, so a stalled lift kept identical in Workout 1 plus a single
    set five kilos heavier in Workout 3 read as "the dose moved" while the
    session the user performs was untouched.
    """

    def _laundered(self, tail: str) -> list[str]:
        text = _plan("2026-08-02", _PROGRESSED_BODY.replace(
            "- Romanian Deadlift: 85kgx6-8 /// 85kgx6-8 /// 85kgx6-8",
            "- Romanian Deadlift: 100kgx10-12 /// 100kgx10-12 /// 100kgx10-12")
            ) + f"\n## Workout 3: LOWER B + CORE\n\n{tail}"
        return [m for _a, m in dose_progression_findings(
            text, _prev_block({"Romanian Deadlift": 4}),
            plan_date="2026-08-02")]

    def test_a_token_heavier_set_no_longer_answers_the_stall(self) -> None:
        msgs = self._laundered("- Romanian Deadlift: 105kgx8\n")
        self.assertTrue(any(m.startswith("Romanian Deadlift: 4 sessions "
                                         "stalled") for m in msgs), msgs)

    def test_a_real_second_exposure_still_counts(self) -> None:
        """Three sets at a new load is a prescription, not a token."""
        msgs = self._laundered("- Romanian Deadlift: 105kgx8 /// 105kgx8 "
                               "/// 105kgx8\n")
        self.assertEqual([m for m in msgs if m.startswith("Romanian Deadlift:")],
                         [])

    def test_the_selected_dose_is_the_one_that_carries_the_sets(self) -> None:
        plans = [parse_plan(_plan("2026-07-25",
                                  "- Leg Extension: 55kgx10-12 /// 55kgx10-12\n"),
                            "2026-07-25"),
                 parse_plan(_plan("2026-08-02",
                                  "- Leg Extension: 55kgx10-12 /// 55kgx10-12\n"
                                  "\n## Workout 3: LOWER B + CORE\n\n"
                                  "- Leg Extension: 70kgx6\n"), "2026-08-02")]
        report = dose_staleness(plans, _DB)
        carried = report["carried"][0]
        self.assertEqual(carried["load_kg"], 55.0)
        self.assertFalse(carried["dose_changed"])


# ---------------------------------------------------------------------------
class SupersetBackoffGuardTests(unittest.TestCase):
    """F7 — the backoff resolved hints to the WRONG host.

    The old docstring proved the backoff "cannot resolve an ambiguity",
    which was the wrong question. The failure is a hint whose intended
    host is ABSENT, where a generic leading word manufactures a unique
    hit. All three cases below answered `None` before the backoff existed,
    so the fix for G-09 made them worse than the bug it closed.
    """

    def _host(self, body: str, of: str = "Dumbbell Lateral Raise") -> "str | None":
        text = _plan("2026-08-02", body)
        block = block_from_plan(parse_plan(text, "2026-08-02"), _CATALOG)
        slot = [s for s in block["sessions"]["lower_a"] if s["exercise"] == of]
        return slot[0].get("superset_with") if slot else None

    def test_an_absent_host_resolves_to_nothing(self) -> None:
        cases = [
            ("- Leg Extension: 55kgx10 /// 55kgx10\n"
             "- Dumbbell Lateral Raise: 16kgx10 /// 16kgx10\n"
             "  — superset with the leg press above\n"),
            ("- Seated Cable Row: 60kgx10 /// 60kgx10\n"
             "- Dumbbell Lateral Raise: 16kgx10 /// 16kgx10\n"
             "  — superset with the seated calf raise above\n"),
            ("- Chest Supported Row Machine: 70kgx10 /// 70kgx10\n"
             "- Dumbbell Lateral Raise: 16kgx10 /// 16kgx10\n"
             "  — superset with the chest press above\n"),
        ]
        for body in cases:
            self.assertIsNone(self._host(body), body)

    def test_an_under_specified_reference_still_resolves(self) -> None:
        """The whole point of the backoff, kept.

        What follows the winning prefix here is prose, not a dropped name
        word, so nothing was truncated to force the hit.
        """
        self.assertEqual(
            self._host("- Dumbbell Flat Bench Press: 52kgx8 /// 52kgx8\n"
                       "- Dumbbell Lateral Raise: 16kgx10 /// 16kgx10\n"
                       "  — superset with the bench press above\n"),
            "Dumbbell Flat Bench Press")
        self.assertEqual(
            self._host("- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
                       "- Dumbbell Lateral Raise: 16kgx10 /// 16kgx10\n"
                       "  — superset with the squat above\n"),
            "Barbell Back Squat")
        self.assertEqual(
            self._host("- Dumbbell Bulgarian Split Squat: 16kgx10 /// 16kgx10\n"
                       "- Dumbbell Lateral Raise: 16kgx10 /// 16kgx10\n"
                       "  — superset with the split squat above, keep it tight\n"),
            "Dumbbell Bulgarian Split Squat")

    def test_the_guard_reads_the_catalog_not_the_session(self) -> None:
        """The session's own words cannot see that "press" is an exercise.

        A caller that supplies no vocabulary gets the weaker session-word
        fallback; `block_from_plan` supplies the catalog, which is why the
        leg-press case above resolves to nothing.
        """
        from workout_coach.lib.blocks import (_catalog_identity_vocabulary,
                                              _match_superset_host)
        slots = [{"exercise": "Leg Extension"}]
        self.assertEqual(_match_superset_host("leg press above", slots),
                         "Leg Extension")
        self.assertIsNone(_match_superset_host(
            "leg press above", slots, _catalog_identity_vocabulary(_CATALOG)))


# ---------------------------------------------------------------------------
class SubBulletSmugglingTests(unittest.TestCase):
    """F8 — the structural exemption was a `.search()` over the whole line.

    Any sub-bullet CONTAINING "superset with" anywhere became uncountable,
    so the exemption for a routing line was also an exemption for a
    paragraph of rationale with the token buried in it. Measured on the
    2026-08-02 corpus: 24 of 28 sub-bullets invisible, three of eight
    workouts counting zero.
    """

    def test_a_buried_token_no_longer_buys_silence(self) -> None:
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "  — knees track over toes, and this pairs as a superset with "
            "the calf raise later so the rest period is not wasted\n"
            "- Leg Extension: 55kgx10 /// 55kgx10\n"
            "  — squeeze at the top, the machine is a superset with nothing\n"
            "- Calf Raise Machine: 55kgx12 /// 55kgx12\n"
            "  — pause at the bottom; superset with is a phrase that buys "
            "silence\n")))
        self.assertTrue(any("3 rationale sub-bullets" in w for w in warnings),
                        warnings)

    def test_the_leading_form_is_still_exempt(self) -> None:
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "- Cable Standing Calf Raise: 50kgx10 /// 50kgx10\n"
            "  — superset with the back squat above\n"
            "- Ab Crunch Machine: 35kgx12 /// 35kgx12\n"
            "  — superset with the back squat above\n"
            "- Leg Extension: 55kgx10 /// 55kgx10\n"
            "  — anchor change: injury\n")))
        self.assertEqual([w for w in warnings if "sub-bullets" in w], [])


# ---------------------------------------------------------------------------
class MalformedDoseTests(unittest.TestCase):
    """F9 — a crash is not a validation verdict.

    `prescribed_sets` is the one dose field `dose_staleness` indexed
    rather than `.get`, and the dose dict is JSON off a block artifact on
    disk. A missing key exited 1 with a KeyError; a null one exited 1 with
    a TypeError. Exit 1 means the program broke.
    """

    def _block(self, mutate) -> dict:
        block = _prev_block()
        for slots in block["sessions"].values():
            for s in slots:
                mutate(s["dose"])
        return block

    def test_a_missing_prescribed_sets_is_not_a_crash(self) -> None:
        block = self._block(lambda d: d.pop("prescribed_sets", None))
        self.assertEqual(
            dose_progression_findings(_RECOPIED_PLAN, block,
                                      plan_date="2026-08-02"), [])

    def test_a_null_prescribed_sets_is_not_a_crash(self) -> None:
        block = self._block(lambda d: d.update(prescribed_sets=None))
        self.assertEqual(
            dose_progression_findings(_RECOPIED_PLAN, block,
                                      plan_date="2026-08-02"), [])

    def test_a_string_prescribed_sets_is_not_a_crash(self) -> None:
        block = self._block(lambda d: d.update(prescribed_sets="three"))
        self.assertEqual(
            dose_progression_findings(_RECOPIED_PLAN, block,
                                      plan_date="2026-08-02"), [])

    def test_it_still_reads_a_well_formed_block(self) -> None:
        """The guard must not turn every block into "cannot compare"."""
        self.assertTrue(dose_progression_findings(
            _RECOPIED_PLAN, _prev_block(), plan_date="2026-08-02"))


# ---------------------------------------------------------------------------
class DerivedOnlyReasonIsReadFromTheRightTupleTests(unittest.TestCase):
    """F10 — `block_from_plan` filtered against the full enum.

    Inert today only because `adherence._ANCHOR_CHANGE_RE` refuses the
    token, which is one parser edit away from being untrue. The tuple that
    exists to make this decision is `COACH_DECLARABLE_...`; read it.
    """

    def _block_with_hint(self, hint: str) -> "str | None":
        plan = parse_plan(_PREV_PLAN, "2026-07-25")
        plan["workouts"][0]["slots"][0]["anchor_change_hint"] = hint
        block = block_from_plan(plan, _CATALOG)
        return block["sessions"]["lower_a"][0].get("anchor_change_reason")

    def test_a_plan_dict_cannot_assert_the_derived_reason(self) -> None:
        self.assertIsNone(self._block_with_hint("user_substitution"))

    def test_the_declarable_reasons_still_work(self) -> None:
        for reason in COACH_DECLARABLE_ANCHOR_CHANGE_REASONS:
            self.assertEqual(self._block_with_hint(reason), reason)


# ---------------------------------------------------------------------------
class SetChurnIsNotProgressionTests(unittest.TestCase):
    """F11 — the prompt and the code disagreed, and the code was wrong.

    SKILL.md, on the hold-loads band: advancing the rep target "is a real
    dose change and it counts as one. Churning set counts to move the
    metric does not: adding or dropping a set purely to make the
    prescription differ changes weekly volume for no training reason and
    breaks the tier targets." `_dose_delta` counted ANY set-count change
    as material, with no magnitude floor at all.
    """

    BASE = {"load_kg": 100.0, "rep_lo": 8, "rep_hi": 10, "prescribed_sets": 3}

    def _delta(self, **over):
        return _dose_delta(self.BASE, {**self.BASE, **over})

    def test_adding_a_set_is_not_a_dose_change(self) -> None:
        kind, changed = self._delta(prescribed_sets=4)
        self.assertFalse(changed)
        self.assertEqual(kind, "sets_up")

    def test_dropping_a_set_is_not_a_dose_change(self) -> None:
        kind, changed = self._delta(prescribed_sets=2)
        self.assertFalse(changed)
        self.assertEqual(kind, "sets_down")

    def test_the_kind_is_still_reported(self) -> None:
        """Counted as unchanged, not made invisible. Same as `cosmetic`."""
        self.assertNotEqual(self._delta(prescribed_sets=4)[0], "none")

    def test_load_and_reps_are_untouched(self) -> None:
        self.assertEqual(self._delta(load_kg=105.0), ("load_up", True))
        self.assertEqual(self._delta(rep_lo=9, rep_hi=11), ("reps_up", True))

    def test_the_cost_is_stated_where_the_rule_is(self) -> None:
        """A real volume cut now reads as unchanged. Say so in the code."""
        self.assertIn("cadence deload", _dose_delta.__doc__)


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
