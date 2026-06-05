from __future__ import annotations

import unittest

from shared.exercises_database import is_known_name, known_name_set


class ExercisesDatabaseTests(unittest.TestCase):
    def test_known_name_set_contains_canonicals_and_alias_inputs(self) -> None:
        names = known_name_set()

        self.assertIn("dumbbell flat bench press", names)
        self.assertTrue(is_known_name("Dumbbell Flat Bench Press", names))
        self.assertTrue(is_known_name("Hanging Leg Raise", names))
        self.assertFalse(is_known_name("Standing Calf Raise", names))


if __name__ == "__main__":
    unittest.main()
