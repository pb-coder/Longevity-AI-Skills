"""Tests of the weekly nutrition review, with synthetic data."""
import unittest
from datetime import date, timedelta
from workout_coach.lib.nutrition_phase import weekly_nutrition_review

TODAY = date(2026, 11, 19)
START = TODAY - timedelta(days=30)

def phase(kind="cut", target=-0.5):
    return [{"start_date": START.isoformat(), "phase_type": kind,
             "target_rate_kg_per_wk": target}]

def weights(rate, offsets=(14, 10, 4, 0)):
    return [{"date": (TODAY - timedelta(days=i)).isoformat(),
             "kg": 80 + rate * (14 - i) / 7} for i in offsets]

class WeeklyNutritionReviewTests(unittest.TestCase):
    def test_cut_and_gain_directions_are_review_only(self):
        for kind, target, rate, action in (
            ("cut", -0.5, -1.5, "review_ease_deficit"),
            ("cut", -0.5, -0.05, "review_cut_consistency"),
            ("bulk", 0.25, 1.0, "review_reduce_surplus"),
            ("bulk", 0.25, 0.01, "review_gain_consistency"),
        ):
            with self.subTest(kind=kind, rate=rate):
                result = weekly_nutrition_review(phase(kind, target), weights(rate), TODAY)
                self.assertEqual(result["coach_action_hint"], action)
                self.assertNotIn("energy", result)

    def test_insufficient_stale_and_prephase_defer(self):
        sparse = weekly_nutrition_review(phase(), weights(-0.5, (1, 0)), TODAY)
        self.assertEqual(sparse["coach_action_hint"], "defer")
        stale = weekly_nutrition_review(phase(), weights(-0.5, (20, 17, 14, 10)), TODAY)
        self.assertIn("more than seven days", stale["decision_reason"])
        old = [{"date": (START - timedelta(days=i)).isoformat(), "kg": 80} for i in range(1, 8)]
        self.assertEqual(weekly_nutrition_review(phase(), old, TODAY)["coach_action_hint"], "defer")

    def test_duplicate_dates_and_wrong_sign_defer(self):
        one = weights(-0.5, (0,)) * 8
        self.assertEqual(weekly_nutrition_review(phase(), one, TODAY)["coach_action_hint"], "defer")
        wrong = weekly_nutrition_review(phase("cut", 0.5), weights(-0.5), TODAY)
        self.assertEqual(wrong["coach_action_hint"], "defer")
        self.assertIn("sign", wrong["decision_reason"])

    def test_percent_target_and_legacy_conversion(self):
        result = weekly_nutrition_review(phase(), weights(-0.5), TODAY)
        self.assertEqual(result["targets"]["basis"], "legacy_kg_converted")
        self.assertAlmostEqual(result["targets"]["rate_percent_per_week"], -0.625)
        declared = phase()
        declared[0]["target_rate_percent_per_week"] = -0.5
        result = weekly_nutrition_review(declared, weights(-0.5), TODAY)
        self.assertEqual(result["targets"]["basis"], "declared_percent")
        self.assertAlmostEqual(result["targets"]["rate_kg_per_wk"], -0.4)

    def test_explicit_reference_stays_fixed(self):
        declared = phase()
        declared[0].update(target_rate_percent_per_week=-0.5, reference_weight_kg=100)
        result = weekly_nutrition_review(declared, weights(-0.5), TODAY)
        self.assertEqual(result["targets"]["reference_weight_kg"], 100)
        self.assertEqual(result["targets"]["rate_kg_per_wk"], -0.5)

    def test_nonfasted_and_old_measurements(self):
        readings = weights(-0.5)
        readings[-1]['notes'] = 'evening, not fasted'
        result = weekly_nutrition_review(phase(), readings, TODAY)
        self.assertEqual(result['actuals']['measurement_count'], 3)
        self.assertEqual(result['coach_action_hint'], 'defer')
        old = weights(-0.5, (29, 25, 20, 16))
        result = weekly_nutrition_review(phase(), old, TODAY)
        self.assertEqual(result['actuals']['latest_measurement_date'],
                         (TODAY - timedelta(days=16)).isoformat())
        self.assertIn('more than seven days', result['decision_reason'])

    def test_missing_reference_is_not_wrong_sign(self):
        result = weekly_nutrition_review(phase(), [], TODAY)
        self.assertIn('reference weight', result['decision_reason'])
        self.assertEqual(result['targets']['rate_kg_per_wk'], -0.5)

    def test_spread_overlapping_target_boundary_defers(self):
        readings = weights(-0.5, (14, 13, 1, 0))
        readings[0]["kg"] += 0.8
        readings[-1]["kg"] += 0.8
        review = weekly_nutrition_review(phase(), readings, TODAY)
        self.assertEqual(review["coach_action_hint"], "defer")
        self.assertEqual(review["status"], "unresolved")

    def test_conflicting_same_day_readings_do_not_count(self):
        readings = weights(-0.5)
        readings.append({"date": readings[-1]["date"], "kg": 100})
        review = weekly_nutrition_review(phase(), readings, TODAY)
        self.assertEqual(review["coach_action_hint"], "defer")
        self.assertEqual(review["actuals"]["measurement_count"], 3)

    def test_missing_target_and_no_phase(self):
        self.assertIsNone(weekly_nutrition_review([], [], TODAY))
        self.assertEqual(weekly_nutrition_review(phase(target=None), weights(-0.5), TODAY)["coach_action_hint"], "defer")

if __name__ == "__main__":
    unittest.main()
