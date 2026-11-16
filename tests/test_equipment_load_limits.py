"""Explicit machine limits constrain progression within comparable contexts."""
from datetime import date
from pathlib import Path
import unittest

from shared.workout_context import equipment_limit_reached
from workout_coach.lib.adherence import parse_plan
from workout_coach.lib.blocks import load_pattern_catalog
from workout_coach.lib.extract import load_exercises_db
from workout_coach.lib.progression import build_next_dose


DB = load_exercises_db(Path(__file__).resolve().parents[1] / "shared/exercises-database.md")
CATALOG = load_pattern_catalog(DB)
NAME = "Cable Seated Row"


def session(day, load=40, notes=None, name=NAME, **context):
    return [dict(date=day, exercise=name, kg=load, reps=10,
                 notes=notes if index == 0 else None, **context) for index in range(2)]


def dose(rows, name=NAME, policy="progress", today=date(2026, 10, 14)):
    plan = parse_plan(f"## Workout 1: UPPER\n- {name}: 40kgx8-10\n", "2026-10-01", DB)
    result = build_next_dose(rows, CATALOG, [plan], None, {"policy": policy}, today)
    return next(e for e in result["exercises"] if e["exercise"] == name)


class EquipmentLoadLimitTests(unittest.TestCase):
    def test_recorded_limit_holds_an_earned_increment(self):
        entry = dose(session("2026-10-10", notes="machine limit reached"))
        self.assertEqual((entry["action"], entry["load_kg"], entry["load_limit_kg"]),
                         ("hold", 40, 40))
        self.assertIn("Equipment limit", entry["basis"])

    def test_cap_survives_later_unannotated_sessions(self):
        rows = session("2026-10-03", notes="machine limit reached") + session("2026-10-10")
        self.assertEqual(dose(rows)["action"], "hold")

    def test_cap_is_specific_to_gym_and_machine(self):
        old = session("2026-10-03", notes="machine limit reached", gym="A", machine="one")
        for gym, machine, action in (("A", "one", "hold"), ("B", "one", "add_load"),
                                     ("A", "two", "add_load")):
            with self.subTest(gym=gym, machine=machine):
                self.assertEqual(dose(old + session("2026-10-10", gym=gym, machine=machine))["action"], action)

    def test_later_heavier_log_supersedes_old_cap(self):
        rows = session("2026-10-03", notes="machine limit reached") + session("2026-10-10", 45)
        entry = dose(rows)
        self.assertEqual(entry["action"], "add_load")
        self.assertNotIn("load_limit_kg", entry)

    def test_free_weights_do_not_inherit_machine_limits(self):
        name = "Dumbbell Flat Bench Press"
        self.assertEqual(dose(session("2026-10-10", notes="machine limit reached", name=name), name)["action"], "add_load")

    def test_global_gym_change_clears_legacy_limit(self):
        rows = (session("2026-10-03", notes="machine limit reached")
                + session("2026-10-05", notes="new gym", name="Dumbbell Row")
                + session("2026-10-10"))
        self.assertEqual(dose(rows)["action"], "add_load")

    def test_later_other_lift_gym_visit_does_not_erase_reference_cap(self):
        rows = (session("2026-10-03", notes="machine limit reached")
                + session("2026-10-10", notes="different gym and machine", name="Cable Lateral Raise"))
        self.assertEqual((dose(rows)["action"], dose(rows)["load_kg"]), ("hold", 40))

    def test_partial_or_warmup_annotations_do_not_establish_limit(self):
        for context in ({"load_basis": "plates_only"}, {"notes": "machine limit reached (warmup)"}):
            rows = session("2026-10-03", **({"notes": "machine limit reached"} | context)) + session("2026-10-10")
            self.assertNotIn("load_limit_kg", dose(rows))

    def test_reduce_and_reentry_do_not_gain_load_from_a_cap(self):
        rows = session("2026-10-10", notes="machine limit reached")
        self.assertEqual(dose(rows, policy="reduce")["action"], "reduce")
        self.assertLessEqual(dose(rows, today=date(2026, 11, 20))["load_kg"], 40)

    def test_limit_annotation_is_not_exertion_or_negated(self):
        for note in ("limit reached", "max effort", "not machine limit reached", "near machine limit reached"):
            self.assertFalse(equipment_limit_reached(note))
        for note in ("Machine limit reached", "stack maxed out", "machine maximum hit"):
            self.assertTrue(equipment_limit_reached(note))


if __name__ == "__main__":
    unittest.main()
