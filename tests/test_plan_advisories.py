"""Three advisory plan checks: next_dose drift, main patterns, cardio.

The coach is told to copy ``next_dose``, to keep a horizontal push, a
vertical push, a horizontal pull and a vertical pull in every week, and to
write no cardio. Nothing checked any of the three, and each drifted: a bench
weight that never rose, an overhead press that dropped out with a split
change, Zone 2 sections in a strength plan. They are WARNINGS (exit code
unchanged), tagged so a reader can tell them from an enforced finding.

Every fixture is synthetic and written in this file.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from test_check_plan import _GOOD_COACH, _check, _write_inputs
from test_w3a_enforcement import _PLAN_COMPLIANT

from workout_coach.lib.render_validators import (
    CARDIO_SECTION_TAG,
    MAIN_PATTERN_TAG,
    NEXT_DOSE_DRIFT_TAG,
    cardio_section_warnings,
    missing_main_pattern_warnings,
    next_dose_drift_warnings,
    validate_workout_plan,
)

BENCH = "Dumbbell Flat Bench Press"


def week(*workouts: "tuple[str, list[str]]") -> str:
    out = "# Workout plan — 2026-10-14\n\nOpener.\n\n"
    for title, bullets in workouts:
        out += f"## {title}\n" + "".join(f"- {b}\n" for b in bullets) + "\n"
    return out


def nd(*entries: dict, policy: str = "progress") -> dict:
    return {"next_dose": {"load_policy": policy, "exercises": list(entries)}}


def entry(exercise: str, load: float, rep_range: str, action="add_reps",
          **extra) -> dict:
    return {"exercise": exercise, "load_kg": load, "rep_range": rep_range,
            "action": action, **extra}


def drift(text: str, payload: dict, **kw) -> list[str]:
    return next_dose_drift_warnings(text, payload, **kw)


UPPER = ("Workout 1: UPPER A", [f"{BENCH}: 52kgx10-12 /// 52kgx10-12"])


class NextDoseDriftTests(unittest.TestCase):
    def test_a_plan_that_copies_the_dose_is_silent(self):
        self.assertEqual(drift(week(UPPER), nd(entry(BENCH, 52, "10-12"))), [])

    def test_a_different_load_is_named_with_both_values(self):
        # The original failure: next_dose says add_load, the plan repeats.
        text = week(("Workout 1: UPPER A",
                     [f"{BENCH}: 52kgx10-12 /// 52kgx10-12"]))
        out = drift(text, nd(entry(BENCH, 56, "10-12", "add_load")))
        self.assertEqual(len(out), 1)
        self.assertIn(BENCH, out[0])
        self.assertIn("plan 52kg x 10-12 vs next_dose 56kg x 10-12", out[0])
        self.assertIn("(add_load)", out[0])
        self.assertIn("differs in load", out[0])
        self.assertTrue(out[0].endswith(NEXT_DOSE_DRIFT_TAG))

    def test_a_rep_target_outside_the_range_is_a_drift(self):
        text = week(("Workout 1: UPPER A", [f"{BENCH}: 52kgx8-10 /// 52kgx8-10"]))
        out = drift(text, nd(entry(BENCH, 52, "10-12")))
        self.assertEqual(len(out), 1)
        self.assertIn("plan 52kg x 8-10 vs next_dose 52kg x 10-12", out[0])
        self.assertIn("differs in reps", out[0])

    def test_load_and_reps_are_one_line(self):
        text = week(("Workout 1: UPPER A", [f"{BENCH}: 50kgx8-10"]))
        out = drift(text, nd(entry(BENCH, 52, "10-12")))
        self.assertEqual(len(out), 1)
        self.assertIn("differs in load and reps", out[0])

    def test_a_target_inside_the_range_or_equal_to_it_is_fine(self):
        for written in ("52kgx12", "52kgx11-12", "52kgx10-12", "52kgx10"):
            with self.subTest(written=written):
                text = week(("Workout 1: UPPER A", [f"{BENCH}: {written}"]))
                self.assertEqual(drift(text, nd(entry(BENCH, 52, "10-12"))), [])

    def test_a_single_number_range_means_that_number(self):
        payload = nd(entry(BENCH, 52, "12"))
        ok = week(("Workout 1: UPPER A", [f"{BENCH}: 52kgx12 /// 52kgx12"]))
        wide = week(("Workout 1: UPPER A", [f"{BENCH}: 52kgx10-12"]))
        self.assertEqual(drift(ok, payload), [])
        self.assertEqual(len(drift(wide, payload)), 1)

    def test_per_side_and_a_dash_in_the_range_parse(self):
        name = "Dumbbell Bulgarian Split Squat"
        text = week(("Workout 1: LOWER A", [f"{name}: 16kgx10-12 per side "
                                            f"/// 16kgx10-12 per side"]))
        self.assertEqual(drift(text, nd(entry(name, 16, "10-12"))), [])
        # An en dash in the payload's range still parses as a range.
        self.assertEqual(drift(text, nd(entry(name, 16, "10\u201312"))), [])
        out = drift(text, nd(entry(name, 18, "10-12")))
        self.assertEqual(len(out), 1)
        self.assertIn("plan 16kg x 10-12 vs next_dose 18kg x 10-12", out[0])

    def test_warmup_sets_are_not_compared(self):
        text = week(("Workout 1: UPPER A",
                     [f"{BENCH}: 26kgx5 (warmup) /// 36kgx3 (warmup) "
                      f"/// 52kgx10-12 /// 52kgx10-12 /// 52kgx10-12"]))
        self.assertEqual(drift(text, nd(entry(BENCH, 52, "10-12"))), [])

    def test_the_load_the_plan_uses_is_the_one_carrying_the_sets(self):
        text = week(("Workout 1: UPPER A",
                     [f"{BENCH}: 52kgx10-12 /// 52kgx10-12 /// 56kgx10-12"]))
        self.assertEqual(drift(text, nd(entry(BENCH, 52, "10-12"))), [])

    def test_one_line_per_exercise_even_in_two_workouts(self):
        text = week(UPPER,
                    ("Workout 2: UPPER B", [f"{BENCH}: 52kgx10-12"]),)
        out = drift(text, nd(entry(BENCH, 56, "10-12")))
        self.assertEqual(len(out), 1)
        self.assertIn("Workout 1", out[0])
        self.assertIn("differs in load", out[0])

    def test_two_deliberate_doses_are_silent_when_one_matches_next_dose(self):
        # A heavy day and a light day for one lift is a plan, not a
        # deviation, and next_dose holds one dose per lift.
        text = week(("Workout 1: UPPER A",
                     [f"{BENCH}: 56kgx6-8 /// 56kgx6-8"]),
                    ("Workout 2: UPPER B",
                     [f"{BENCH}: 40kgx12-15 /// 40kgx12-15"]))
        self.assertEqual(
            drift(text, nd(entry(BENCH, 56, "6-8", "add_load"))), [])
        # ... whichever workout the matching one is in.
        self.assertEqual(
            drift(text, nd(entry(BENCH, 40, "12-15"))), [])

    def test_two_doses_none_of_which_matches_next_dose_are_reported_once(self):
        text = week(("Workout 1: UPPER A",
                     [f"{BENCH}: 44kgx6-8 /// 44kgx6-8"]),
                    ("Workout 2: UPPER B",
                     [f"{BENCH}: 30kgx12-15 /// 30kgx12-15"]))
        out = drift(text, nd(entry(BENCH, 56, "6-8", "add_load")))
        self.assertEqual(len(out), 1)
        self.assertIn("Workout 1: 44kg x 6-8", out[0])
        self.assertIn("Workout 2: 30kg x 12-15", out[0])
        self.assertIn("none matches next_dose 56kg x 6-8", out[0])
        self.assertTrue(out[0].endswith(NEXT_DOSE_DRIFT_TAG))

    def test_a_stale_load_in_a_second_workout_at_the_same_reps_is_drift(self):
        # One rep range is one dose: 56 kg matches, the 50 kg one is stale.
        text = week(("Workout 1: UPPER A",
                     [f"{BENCH}: 56kgx10-12 /// 56kgx10-12"]),
                    ("Workout 2: UPPER B",
                     [f"{BENCH}: 50kgx10-12 /// 50kgx10-12"]))
        out = drift(text, nd(entry(BENCH, 56, "10-12", "add_load")))
        self.assertEqual(len(out), 1)
        self.assertIn("Workout 2", out[0])
        self.assertIn("plan 50kg x 10-12 vs next_dose 56kg x 10-12", out[0])
        self.assertIn("differs in load", out[0])

    def test_a_split_lift_does_not_hide_a_drift_in_another_lift(self):
        row = "Seated Row Machine"
        text = week(("Workout 1: UPPER A",
                     [f"{BENCH}: 52kgx6-8", f"{row}: 60kgx10-12"]),
                    ("Workout 2: UPPER B", [f"{BENCH}: 40kgx12-15"]))
        out = drift(text, nd(entry(BENCH, 52, "6-8"),
                             entry(row, 65, "10-12", "add_load")))
        self.assertEqual(len(out), 1)
        self.assertTrue(row in out[0] and "differs in load" in out[0])

    def test_an_entry_the_plan_does_not_prescribe_is_ignored(self):
        self.assertEqual(
            drift(week(UPPER), nd(entry("Cable Lat Pulldown", 65, "10-12"))),
            [])

    def test_an_entry_with_no_load_is_ignored(self):
        e = {"exercise": BENCH, "load_kg": None, "rep_range": "8-10",
             "action": "no_history"}
        self.assertEqual(drift(week(UPPER), nd(e)), [])

    def test_no_next_dose_in_the_payload_is_silent(self):
        for payload in (None, {}, {"next_dose": None},
                        {"next_dose": {"exercises": []}}):
            with self.subTest(payload=payload):
                self.assertEqual(drift(week(UPPER), payload), [])

    def test_timed_work_is_not_compared(self):
        name = "Side Plank"
        text = week(("Workout 1: LOWER A", [f"{name}: 30s /// 30s"]))
        self.assertEqual(drift(text, nd(entry(name, 5, "10-12"))), [])

    def test_the_other_gym_load_is_accepted_when_the_plan_uses_it(self):
        name = "Cable Lat Pulldown"
        text = week(("Workout 1: UPPER A", [f"{name}: 55kgx10-12 /// 55kgx10-12"]))
        e = entry(name, 65, "10-12", other_gym_load_kg=55)
        self.assertEqual(drift(text, nd(e)), [])
        text = week(("Workout 1: UPPER A", [f"{name}: 60kgx10-12"]))
        self.assertEqual(len(drift(text, nd(e))), 1)

    def test_a_full_block_deload_is_exempt(self):
        text = week(("Workout 1: UPPER A", [f"{BENCH}: 40kgx10-12"]))
        payload = nd(entry(BENCH, 56, "10-12", "add_load"))
        self.assertEqual(len(drift(text, payload)), 1)
        self.assertEqual(drift(text, payload, deload_week=True), [])
        reduce_ = nd(entry(BENCH, 56, "10-12", "reduce"), policy="reduce")
        self.assertEqual(drift(text, reduce_), [])

    def test_a_deload_session_heading_is_exempt(self):
        text = week(("Deload Session 1: LOWER A",
                     [f"{BENCH}: 40kgx10-12"]),)
        self.assertEqual(drift(text, nd(entry(BENCH, 56, "10-12"))), [])

    def test_the_cadence_deload_session_is_exempt_and_only_that_one(self):
        squat = "Barbell Back Squat"
        text = week(
            ("Workout 1: UPPER A", [f"{BENCH}: 50kgx10-12"]),
            ("Workout 2: LOWER A", [f"{squat}: 90kgx8 /// 90kgx8"]),
            ("Workout 3: LOWER B", [f"{squat}: 90kgx8"]),
        )
        payload = nd(entry(BENCH, 56, "10-12", "add_load"),
                     entry(squat, 95, "8", "add_load"))
        # Without the cadence flag both exercises drift.
        self.assertEqual(len(drift(text, payload)), 2)
        # With it, the first lower-body session (Workout 2) is the deload:
        # the squat there is exempt, the bench in the normal session is not.
        out = drift(text, payload, cadence_deload=True)
        self.assertEqual(len(out), 2)         # Workout 3 repeats the squat
        self.assertIn("Workout 3", [o for o in out if squat in o][0])
        self.assertTrue(any(BENCH in o for o in out))

    def test_cadence_deload_with_no_lower_session_exempts_the_first(self):
        text = week(("Workout 1: UPPER A", [f"{BENCH}: 44kgx10-12"]),
                    ("Workout 2: UPPER B", [f"{BENCH}: 44kgx10-12"]))
        out = drift(text, nd(entry(BENCH, 56, "10-12", "add_load")),
                    cadence_deload=True)
        self.assertEqual(len(out), 1)
        self.assertIn("Workout 2", out[0])


class MainPatternTests(unittest.TestCase):
    FOUR = [
        ("Workout 1: UPPER A", [f"{BENCH}: 50kgx10-12 /// 50kgx10-12",
                                "Shoulder Press Machine: 45kgx10-12",
                                "Cable Lat Pulldown: 65kgx10-12"]),
        ("Workout 2: UPPER B", ["Seated Row Machine: 60kgx10-12"]),
    ]

    def test_a_week_with_all_four_is_silent(self):
        self.assertEqual(missing_main_pattern_warnings(week(*self.FOUR)), [])

    def test_a_missing_vertical_push_is_named(self):
        text = week(("Workout 1: UPPER A", [f"{BENCH}: 50kgx10-12",
                                            "Cable Lat Pulldown: 65kgx10-12"]),
                    ("Workout 2: UPPER B", ["Seated Row Machine: 60kgx10-12"]))
        out = missing_main_pattern_warnings(text)
        self.assertEqual(len(out), 1)
        self.assertIn("SHOULDERS/Vertical Push (Compound)", out[0])
        self.assertTrue(out[0].endswith(MAIN_PATTERN_TAG))

    def test_every_missing_pattern_gets_its_own_line(self):
        text = week(("Workout 1: UPPER A", [f"{BENCH}: 50kgx10-12"]))
        out = missing_main_pattern_warnings(text)
        self.assertEqual(len(out), 3)
        for pattern in ("SHOULDERS/Vertical Push (Compound)",
                        "BACK/Horizontal Pull (Compound)",
                        "BACK/Vertical Pull (Compound)"):
            self.assertTrue(any(pattern in o for o in out), pattern)

    def test_a_pattern_only_counts_with_working_sets(self):
        text = week(*self.FOUR[:1], ("Workout 2: UPPER B",
                                     ["Seated Row Machine: 60kgx10-12"]))
        text = text.replace("Shoulder Press Machine: 45kgx10-12",
                            "Shoulder Press Machine: 3 min")
        out = missing_main_pattern_warnings(text)
        self.assertEqual(len(out), 1)
        self.assertIn("SHOULDERS/Vertical Push", out[0])

    def test_a_full_block_deload_is_exempt(self):
        text = week(("Workout 1: UPPER A", [f"{BENCH}: 50kgx10-12"]))
        self.assertEqual(
            missing_main_pattern_warnings(text, deload_week=True), [])

    def test_a_plan_with_no_workouts_is_not_a_week(self):
        self.assertEqual(missing_main_pattern_warnings("# Rest day\n"), [])

    def test_bodyweight_movements_satisfy_their_patterns(self):
        text = week(("Workout 1: UPPER A", [
            "Push-Up: 12 /// 12", "Pike Push-Up: 8 /// 8",
            "Table Inverted Row: 10 /// 10", "Pull-Up: 6 /// 6"]))
        self.assertEqual(missing_main_pattern_warnings(text), [])

    def test_it_runs_only_when_the_payload_is_given(self):
        text = week(("Workout 1: UPPER A", [f"{BENCH}: 50kgx10-12"]))
        _, bare = validate_workout_plan(text)
        _, with_payload = validate_workout_plan(text, payload={})
        self.assertFalse(any(MAIN_PATTERN_TAG in w for w in bare))
        self.assertEqual(
            len([w for w in with_payload if MAIN_PATTERN_TAG in w]), 3)


class CardioSectionTests(unittest.TestCase):
    def test_a_strength_only_plan_is_silent(self):
        self.assertEqual(cardio_section_warnings(week(UPPER)), [])

    def test_a_cardio_heading_is_flagged_with_its_line(self):
        text = week(UPPER) + "## Cardio 1: Zone 2 (35-40 min)\n\n- Ride\n"
        out = cardio_section_warnings(text)
        self.assertEqual(len(out), 1)
        self.assertIn("## Cardio 1: Zone 2 (35-40 min)", out[0])
        self.assertIn(f"line {text.splitlines().index('## Cardio 1: Zone 2 (35-40 min)') + 1}",
                      out[0])
        self.assertTrue(out[0].endswith(CARDIO_SECTION_TAG))

    def test_a_workout_heading_whose_type_is_cardio_is_flagged(self):
        for heading in ("## Session 1: Zone 2 cardio + mobility",
                        "## Workout 5: Intervals",
                        "## Cardio: optional"):
            with self.subTest(heading=heading):
                text = week(UPPER) + f"{heading}\n- Easy\n"
                self.assertEqual(len(cardio_section_warnings(text)), 1)

    def test_the_bullets_of_a_flagged_section_are_not_repeated(self):
        text = (week(UPPER) + "## Cardio 2: Intervals (20 min total)\n"
                "- Work: 4 x 3 min @ HR 154-166bpm\n- Zone 2 cooldown\n")
        self.assertEqual(len(cardio_section_warnings(text)), 1)

    def test_a_cardio_bullet_inside_a_strength_workout_is_flagged(self):
        text = week(("Workout 1: UPPER A", [f"{BENCH}: 52kgx10-12",
                                            "Finisher: 10 min Zone 2 on the bike"]))
        out = cardio_section_warnings(text)
        self.assertEqual(len(out), 1)
        self.assertIn("prescribes cardio", out[0])

    def test_prose_about_cardio_in_the_opener_is_analysis_not_a_section(self):
        text = ("# Workout plan\n\nZone 2 is behind target and VO2max is the "
                "gap; cardio stays on the assessment card.\n\n"
                + week(UPPER).split("Opener.\n\n", 1)[1])
        self.assertEqual(cardio_section_warnings(text), [])

    def test_a_rest_interval_cue_is_not_cardio(self):
        text = week(("Workout 1: UPPER A", [
            f"{BENCH}: 52kgx10-12", "  — 90s rest interval between sets"]))
        self.assertEqual(cardio_section_warnings(text), [])


class NeverBlocksTests(unittest.TestCase):
    """Warnings only: all three together cannot produce an error or an exit 2."""

    def test_they_arrive_as_warnings_from_the_shared_entry_point(self):
        text = week(("Workout 1: UPPER A", [f"{BENCH}: 40kgx8-10"])) \
            + "## Cardio 1: Zone 2\n- Ride\n"
        payload = nd(entry(BENCH, 56, "10-12", "add_load"))
        errors, warnings = validate_workout_plan(text, payload=payload)
        for tag in (NEXT_DOSE_DRIFT_TAG, MAIN_PATTERN_TAG, CARDIO_SECTION_TAG):
            with self.subTest(tag=tag):
                self.assertTrue(any(tag in w for w in warnings), warnings)
                self.assertFalse(any(tag in e for e in errors), errors)

    def test_check_plan_prints_them_and_still_exits_zero(self):
        plan = _PLAN_COMPLIANT + "## Cardio 1: Zone 2 (30 min)\n\n- Easy ride\n"
        tracker = {"today": "2026-08-02", "target_working_sets": 24,
                   **nd(entry("Dumbbell Flat Bench Press", 56, "8", "add_load"))}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write_inputs(tmp, tracker, _GOOD_COACH, plan)
            proc = _check(tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for tag in (NEXT_DOSE_DRIFT_TAG, MAIN_PATTERN_TAG, CARDIO_SECTION_TAG):
            self.assertIn(f"workout_md plan warning:", proc.stderr)
            self.assertIn(tag, proc.stderr)


if __name__ == "__main__":
    unittest.main()
