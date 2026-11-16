"""A repeated stall must change load or movement, not merely its prose."""
import unittest

from workout_coach.lib.plan_validators import (
    stalled_lift_findings, validate_workout_plan, workout_set_budget_warnings,
)

LIFT = "Cable Lateral Raise"


def payload(**changes):
    entry = {"exercise": LIFT, "action": "add_reps", "stalled_sessions": 3,
             "load_kg": 15.0, "rep_range": "12-15"}
    entry.update(changes)
    return {"next_dose": {"load_policy": "progress", "exercises": [entry]}}


def plan(body, heading="Workout 1: UPPER"):
    return f"## {heading}\n- {LIFT}: {body}\n"


class StalledLiftTests(unittest.TestCase):
    def test_each_working_set_is_checked_not_only_the_modal_dose(self):
        for body in ("12kgx12 /// 12kgx12 /// 15kgx12",
                     "15kgx12 /// 12kgx12 /// 12kgx12",
                     "12-15kgx12 /// 12kgx12"):
            with self.subTest(body=body):
                errors, warnings = stalled_lift_findings(plan(body), payload())
                self.assertEqual(len(errors), 1)
                self.assertEqual(warnings, [])
                self.assertIn("stalled for 3 sessions", errors[0])

    def test_lower_loads_and_warmup_at_previous_load_are_not_blocked(self):
        self.assertEqual(stalled_lift_findings(
            plan("15kgx5 (warmup) /// 12kgx12 /// 12kgx12"), payload()), ([], []))

    def test_progression_already_reduced_from_the_recorded_stalled_load(self):
        lowered = payload(load_kg=12, last_load_kg=15)
        self.assertEqual(stalled_lift_findings(plan("12kgx12 /// 12kgx12"), lowered),
                         ([], []))
        errors, warnings = stalled_lift_findings(plan("15kgx12"), lowered)
        self.assertEqual(len(errors), 1)
        self.assertEqual(warnings, [])
        # Old payloads without a usable last load retain the existing check.
        self.assertEqual(len(stalled_lift_findings(
            plan("12kgx12"), payload(load_kg=12, last_load_kg=None))[0]), 1)

    def test_only_three_session_add_reps_or_hold_entries_apply(self):
        text = plan("15kgx12 /// 15kgx12")
        for changes in ({"stalled_sessions": 2}, {"action": "add_load"},
                        {"action": "no_history"}, {"stalled_sessions": None}):
            with self.subTest(changes=changes):
                self.assertEqual(stalled_lift_findings(text, payload(**changes)), ([], []))
        self.assertEqual(len(stalled_lift_findings(text, payload(action="hold"))[0]), 1)
        other = text.replace(LIFT, "Dumbbell Lateral Raise")
        self.assertEqual(stalled_lift_findings(other, payload()), ([], []))

    def test_only_declared_deloads_are_exempt(self):
        text = (plan("15kgx12", "Workout 1: UPPER") +
                plan("15kgx12", "Workout 2: LOWER") +
                plan("15kgx12", "Workout 3: UPPER"))
        self.assertEqual(stalled_lift_findings(text, payload(), deload_week=True), ([], []))
        errors, _ = stalled_lift_findings(text, payload(), cadence_deload=True)
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("Workout 1" in e for e in errors))
        self.assertTrue(any("Workout 3" in e for e in errors))
        self.assertEqual(len(stalled_lift_findings(
            plan("15kgx12", "Deload Session 1: UPPER"), payload())[0]), 1)

    def test_two_gym_loads_and_unknown_load_are_not_guessed(self):
        two = payload(load_kg=15, other_gym_load_kg=25)
        for load in (25, 30):
            self.assertEqual(len(stalled_lift_findings(plan(f"{load}kgx12"), two)[0]), 1)
        self.assertEqual(stalled_lift_findings(plan("10kgx12"), two), ([], []))
        for load in (15, 20):
            errors, warnings = stalled_lift_findings(plan(f"{load}kgx12"), two)
            self.assertEqual(errors, [])
            self.assertEqual(len(warnings), 1)
        errors, warnings = stalled_lift_findings(plan("12 /// 12"), payload(load_kg=None))
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)

    def test_unparseable_heading_does_not_silently_skip_stall_check(self):
        text = plan("15kgx12", "Workout 1 - UPPER")
        errors, warnings = stalled_lift_findings(text, payload())
        self.assertEqual(errors, [])
        self.assertTrue(any("could not be fully checked" in w for w in warnings))

    def test_short_session_advisory_does_not_demand_filler(self):
        warnings = workout_set_budget_warnings(plan("15kgx12 /// 15kgx12"), 20)
        self.assertEqual(len(warnings), 1)
        self.assertIn("do not add filler sets", warnings[0])
        self.assertIn("weekly targets", warnings[0])

    def test_plan_validation_routes_stall_to_blocking_errors(self):
        errors, _ = validate_workout_plan(plan("15kgx12 /// 15kgx12"), payload=payload())
        self.assertTrue(any("stalled for 3 sessions" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
