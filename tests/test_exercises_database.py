from __future__ import annotations

import unittest

from shared.exercises_database import (
    is_known_name,
    known_name_set,
    lookup,
    validate_database,
)


class ExercisesDatabaseTests(unittest.TestCase):
    def test_known_name_set_contains_canonicals_and_alias_inputs(self) -> None:
        names = known_name_set()

        self.assertIn("dumbbell flat bench press", names)
        self.assertTrue(is_known_name("Dumbbell Flat Bench Press", names))
        self.assertTrue(is_known_name("Hanging Leg Raise", names))
        self.assertFalse(is_known_name("Standing Calf Raise", names))

    def test_hanging_leg_raise_resolves_to_its_own_canonical(self) -> None:
        self.assertEqual(lookup("hanging leg raise"), "Hanging Leg Raise")

    def test_full_body_entries_are_reachable_by_name(self) -> None:
        """The ``## FULL BODY (Compound)`` heading was unparseable, so its
        eight entries were filed under NECK. They resolved by name anyway
        (the flat name list does not care which muscle they sit under),
        which is why nothing caught it — assert the muscle, not the name.
        """
        names = known_name_set()
        for entry in ("Barbell Thruster", "Dumbbell Farmer Walk",
                      "Barbell Clean", "Tuck Jump"):
            self.assertTrue(is_known_name(entry, names), entry)

    def test_the_four_w6a_core_entries_are_known(self) -> None:
        names = known_name_set()
        for entry in ("Suitcase Carry", "Ab Wheel Rollout",
                      "Hanging Knee Raise", "Plate Around the World"):
            self.assertTrue(is_known_name(entry, names), entry)

    def test_farmers_walk_is_loggable_by_the_names_people_type(self) -> None:
        names = known_name_set()
        for typed in ("farmers walk", "farmer walk", "farmer's walk"):
            self.assertTrue(is_known_name(typed, names), typed)

    def test_band_pull_apart_stays_off_catalog(self) -> None:
        """Commit ff13d82 removed all four ``[Band]`` entries — "no band
        equipment available". ``known_name_set()`` carries alias INPUT
        strings and ``render_validators.validate_workout_md`` gates plan
        rendering on that set, so an alias row here would silently re-permit
        band prescriptions. Do not add one; see the "Deliberately NOT
        aliased" section in ``workout-logger/references/aliases.md``.
        """
        names = known_name_set()
        for typed in ("Band Pull-Apart", "band pull apart",
                      "Resistance Band Pull-Apart"):
            self.assertIsNone(lookup(typed), typed)
            self.assertFalse(is_known_name(typed, names), typed)

    def test_validate_database_is_clean(self) -> None:
        self.assertEqual(validate_database(), [])


if __name__ == "__main__":
    unittest.main()
