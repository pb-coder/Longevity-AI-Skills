"""The gate gaps found by the 2026-08-02 blind-coach eval (G-05..G-07).

One file per finding-set rather than edits spread across the four suites
that already touch these modules, because every test here answers the
same question: the eval showed a rule that was documented, or assumed, or
outright exploited, and was not actually enforced. Grouping them keeps
the evidence next to the fix.

The findings, and what each class pins:

  G-05  the session set budget allowed +5 while SKILL.md asked for +-2.
  G-06  (dose staleness and the stall response: removed with `dose_staleness`;
        `progression.next_dose` derives the increment from the log instead.)
  G-07  a fabricated recovery score rendered at exit 0 beside the real one.
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
  P2    the drift threshold was a magnitude with a false justification.
        Replaced by decision equivalence.
  F4    G-07's proximity anchor was coach-controlled, and the check never
        read the card label it already held.
  F5    the plan markdown's own opener was never number-checked.
  F8    the structural-sub-bullet exemption was a `.search()` and so a
        smuggling channel.
  F10   `anchor_change_hint` was filtered against the full enum instead of
        the coach-declarable one.

Nothing here reads per-person tracker data: every fixture is written in
the file. The real 2026-08-02 plans were checked by hand against these
rules and pass all of them; see the branch notes.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from workout_coach.lib import render_validators as rv
from workout_coach.lib.adherence import parse_plan
from workout_coach.lib.blocks import (
    ANCHOR_CHANGE_REASONS,
    COACH_DECLARABLE_ANCHOR_CHANGE_REASONS,
    block_from_plan,
    load_pattern_catalog,
    new_block,
    rotation_diff_errors,
    rotation_diff_report,
)
from workout_coach.lib.extract import load_exercises_db
from workout_coach.lib.render_validators import (
    coach_number_findings,
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


# Real prescriptions from the 2026-07-25 plan, so the parser tests below see
# the shapes a coach actually writes.
_PREV_BODY = """- Barbell Back Squat: 100kgx8-10 /// 100kgx8-10 /// 100kgx8-10
- Romanian Deadlift: 100kgx10-12 /// 100kgx10-12 /// 100kgx10-12
- Leg Extension: 55kgx10-12 /// 55kgx10-12
- Calf Raise Machine: 55kgx12-15 /// 55kgx12-15
- Ab Crunch Machine: 35kgx12-15 /// 35kgx12-15
- Dumbbell Shrug: 60kgx12-15 /// 60kgx12-15
"""

_PREV_PLAN = _plan("2026-07-25", _PREV_BODY)


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
class SubBulletCounterTests(unittest.TestCase):
    """The counter fired on every compliant plan.

    It counted structural lines against a cap meant for rationale creep,
    so declaring a required field spent the annotation budget. A warning
    that is always wrong trains a reader to skip the ones that are right.
    """

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

    def test_rationale_bolted_onto_an_anchor_change_line_still_warns(self) -> None:
        """The exemption is for structure, not for a smuggling channel."""
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "  — anchor change: injury because you have been "
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
            dict(position=2, exercise="Leg Extension", tag="rotating"),
        ]})

    def _new(self, prev, replacement="Dumbbell Hip Thrust", **anchor_kw):
        return new_block("2026-07-13", {"lower_a": [
            dict(position=1, exercise=replacement, tag="anchor", **anchor_kw),
            dict(position=2, exercise="Cable Pallof Press", tag="rotating"),
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
        # The one edge that is not a gate threshold, named as such.
        self.assertIn(rv.COACH_SCORE_TOP_BAND_EDGE, boundaries)

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
        self.assertEqual(max(rv.recovery_decision_boundaries()),
                         rv.COACH_SCORE_TOP_BAND_EDGE)
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
        # The call lives in the shared check sequence that both
        # `render_dashboard.py` and `check_plan.py` run.
        source = (Path(__file__).resolve().parents[1] / "workout-coach"
                  / "lib" / "plan_checks.py").read_text(encoding="utf-8")
        self.assertIn("payload=j,", source)

    def test_the_body_is_split_from_the_opener(self) -> None:
        """A rep scheme in a bullet must never read as a recovery claim."""
        labels = [lab for lab, _t in rv._plan_texts(
            self._plan_with("Recovery 5.4 out of 10."))]
        self.assertEqual(labels, ["plan opener", "plan body"])
        self.assertNotIn("plan body", rv.RECOVERY_SCORE_SURFACES)


# ---------------------------------------------------------------------------
class SubBulletSmugglingTests(unittest.TestCase):
    """F8 — the structural exemption was a `.search()` over the whole line.

    Any sub-bullet CONTAINING the structural token anywhere became
    uncountable, so the exemption for a structural line was also an
    exemption for a paragraph of rationale with the token buried in it.
    """

    def test_a_buried_token_no_longer_buys_silence(self) -> None:
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "  — knees track over toes, and this is no anchor change: injury "
            "talk belongs on the dashboard\n"
            "- Leg Extension: 55kgx10 /// 55kgx10\n"
            "  — squeeze at the top, nothing here is an anchor change: none\n"
            "- Calf Raise Machine: 55kgx12 /// 55kgx12\n"
            "  — pause at the bottom; anchor change: is a phrase that buys "
            "silence\n")))
        self.assertTrue(any("3 rationale sub-bullets" in w for w in warnings),
                        warnings)

    def test_the_leading_form_is_still_exempt(self) -> None:
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "  — anchor change: injury\n"
            "- Romanian Deadlift: 85kgx8 /// 85kgx8\n"
            "  — anchor change: stall_3_sessions\n"
            "- Leg Extension: 55kgx10 /// 55kgx10\n"
            "  — anchor change: injury\n")))
        self.assertEqual([w for w in warnings if "sub-bullets" in w], [])

    def test_the_other_gym_cue_is_exempt_too(self) -> None:
        # Two form cues fill the cap; the mandatory `other gym:` cue on a
        # third and fourth bullet must not tip the workout over it.
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "  — brace before the first rep\n"
            "- Cable Lat Pulldown: 65kgx10 /// 65kgx10\n"
            "  — other gym: 55 kg\n"
            "- Leg Extension: 55kgx10 /// 55kgx10\n"
            "  — squeeze at the top\n"
            "  — other gym: 45 kg\n")))
        self.assertEqual([w for w in warnings if "sub-bullets" in w], [])

    def test_an_other_gym_cue_with_anything_after_the_number_counts(self) -> None:
        # Only the whole fixed cue (`other gym: <number> kg`) is structure.
        # Prose that starts with the phrase must not buy an exemption.
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "  — other gym: 55 kg, the stack there is lighter and the "
            "pulley is smoother\n"
            "- Leg Extension: 55kgx10 /// 55kgx10\n"
            "  — other gym: much lighter\n"
            "- Calf Raise Machine: 55kgx12 /// 55kgx12\n"
            "  — other gym: 55\n")))
        self.assertTrue(any("3 rationale sub-bullets" in w for w in warnings),
                        warnings)

    def test_the_whole_other_gym_cue_is_exempt_with_a_decimal(self) -> None:
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "  — brace before the first rep\n"
            "  — squeeze at the top\n"
            "  — other gym: 36.25 kg\n"
            "  — other gym: 36.25 KG  \n")))
        self.assertEqual([w for w in warnings if "sub-bullets" in w], [])

    def test_a_buried_other_gym_token_still_counts(self) -> None:
        _errors, warnings = validate_workout_md(_plan("2026-08-02", (
            "- Barbell Back Squat: 100kgx8 /// 100kgx8\n"
            "  — brace before the first rep, not other gym: stuff\n"
            "- Leg Extension: 55kgx10 /// 55kgx10\n"
            "  — squeeze at the top\n"
            "- Calf Raise Machine: 55kgx12 /// 55kgx12\n"
            "  — pause at the bottom\n")))
        self.assertTrue(any("3 rationale sub-bullets" in w for w in warnings),
                        warnings)


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


if __name__ == "__main__":                                  # pragma: no cover
    unittest.main()
