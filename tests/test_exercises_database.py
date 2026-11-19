from __future__ import annotations

import unittest
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from shared.exercises_database import (
    is_known_name,
    known_name_set,
    lookup,
    fuzzy_match,
    resolve_names,
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
        strings and ``plan_validators.validate_workout_md`` gates plan
        rendering on that set, so an alias row here would silently re-permit
        band prescriptions. Do not add one; see the "Deliberately NOT
        aliased" section in ``workout-logger/references/aliases.md``.
        """
        names = known_name_set()
        for typed in ("Band Pull-Apart", "band pull apart",
                      "Resistance Band Pull-Apart"):
            self.assertIsNone(lookup(typed), typed)
            self.assertFalse(is_known_name(typed, names), typed)

    def test_batch_matches_existing_lookup_and_fuzzy_with_one_catalog_read(self) -> None:
        from shared import exercises_database as db

        names = ["HANGING LEG RAISE", "farmer walk", "belt squad", "belt squad", ""]
        with patch.object(db, "parse_database", wraps=db.parse_database) as catalog, \
             patch.object(db, "parse_aliases", wraps=db.parse_aliases) as aliases:
            results = resolve_names(names)
        self.assertEqual(catalog.call_count, 1)
        self.assertEqual(aliases.call_count, 1)
        self.assertEqual([r["input"] for r in results], names[:3] + [""])
        for result in results:
            name = result["input"]
            canonical = lookup(name)
            if canonical:
                self.assertEqual(result["status"], "known")
                self.assertEqual(result["canonical"], canonical)
            else:
                matches = fuzzy_match(name, k=1)
                expected = {"canonical": matches[0][0], "similarity": matches[0][1]} if matches else None
                self.assertEqual(result, {"input": name, "status": "unknown", "candidate": expected})

    def test_batch_keeps_contextual_alias_guidance(self) -> None:
        result, = resolve_names(["Abdominal crunch"])
        self.assertEqual(result["canonical"], "Ab Crunch Machine")
        self.assertIn("only when load/equipment context implies", result["alias_note"])

    def test_batch_cli_validates_input_and_outputs_json(self) -> None:
        script = Path(__file__).resolve().parents[1] / "shared" / "exercises_database.py"
        def run(value):
            return subprocess.run([sys.executable, str(script), "resolve-batch"],
                                  input=value, text=True, capture_output=True)
        result = run(json.dumps(["HANGING LEG RAISE", "HANGING LEG RAISE"]))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), [{"input": "HANGING LEG RAISE", "status": "known", "canonical": "Hanging Leg Raise"}])
        self.assertEqual(run('{"name": "x"}').returncode, 2)
        self.assertEqual(run('[1]').returncode, 2)
        self.assertEqual(run('{').returncode, 2)

    def test_validate_database_is_clean(self) -> None:
        self.assertEqual(validate_database(), [])


if __name__ == "__main__":
    unittest.main()
