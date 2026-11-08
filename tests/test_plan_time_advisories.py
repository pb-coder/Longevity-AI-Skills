"""Advisory checks for session timing and repeated compounds."""
import unittest

from workout_coach.lib.plan_validators import (
    adjacent_compound_warnings, workout_duration_warnings, validate_workout_plan,
)


def workout(index, exercise, sets):
    return (f"## Workout {index}: UPPER\n- {exercise}: "
            + " /// ".join(["20kgx10"] * sets) + "\n")


class TimeAdvisories(unittest.TestCase):
    def setUp(self):
        self.payload = {"session_target_min": 70,
                        "session_time_model": {"overhead_min": 10,
                                               "min_per_working_set": 3}}

    def test_warns_even_within_the_set_count_tolerance(self):
        plan = workout(1, "Dumbbell Flat Bench Press", 21)
        warnings = workout_duration_warnings(plan, self.payload)
        self.assertEqual(len(warnings), 1)
        self.assertIn("estimated 73.0 min vs 70 min target", warnings[0])
        self.assertIn("actual time varies", warnings[0])
        _, all_warnings = validate_workout_plan(
            plan, target_working_sets=20, payload=self.payload)
        self.assertTrue(any("[advisory: session duration]" in w for w in all_warnings))

    def test_target_at_or_below_limit_is_silent(self):
        self.assertEqual(workout_duration_warnings(
            workout(1, "Dumbbell Flat Bench Press", 20), self.payload), [])

    def test_old_payload_and_invalid_model(self):
        plan = workout(1, "Dumbbell Flat Bench Press", 20)
        self.assertEqual(workout_duration_warnings(plan, {}), [])
        for value in (None, {}, {"overhead_min": 0, "min_per_working_set": float("nan")}):
            payload = {"session_target_min": 70, "session_time_model": value}
            self.assertIn("unavailable", workout_duration_warnings(plan, payload)[0])

    def test_zero_overhead_is_valid(self):
        payload = {"session_target_min": 60,
                   "session_time_model": {"overhead_min": 0, "min_per_working_set": 3}}
        self.assertIn("estimated 63.0 min", workout_duration_warnings(
            workout(1, "Dumbbell Flat Bench Press", 21), payload)[0])

    def test_consecutive_compound_warns_without_assuming_days(self):
        plan = (workout(1, "Dumbbell Flat Bench Press", 2)
                + workout(2, "Dumbbell Flat Bench Press", 4))
        warnings = adjacent_compound_warnings(plan)
        self.assertEqual(len(warnings), 1)
        self.assertIn("consecutive workouts", warnings[0])
        self.assertNotIn("consecutive days", warnings[0])

    def test_single_set_or_isolation_does_not_warn(self):
        single = (workout(1, "Dumbbell Flat Bench Press", 1)
                  + workout(2, "Dumbbell Flat Bench Press", 2))
        isolation = (workout(1, "Incline Dumbbell Curl", 3)
                     + workout(2, "Incline Dumbbell Curl", 3))
        self.assertEqual(adjacent_compound_warnings(single), [])
        self.assertEqual(adjacent_compound_warnings(isolation), [])


if __name__ == "__main__":
    unittest.main()
