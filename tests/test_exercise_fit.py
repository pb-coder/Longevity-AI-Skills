"""Private exercise profile behavior, using synthetic fixtures."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from workout_coach.lib import exercise_fit as fit

START = date(2026, 11, 23)
END = date(2026, 11, 29)

class ExerciseFitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'coach_profile.json'
        self.commit = patch.object(fit, "commit_data").start()
        self.addCleanup(patch.stopall)
        self.path_patch = patch.object(fit, 'profile_path', return_value=self.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.legacy = patch.object(fit, 'read_bench_log', return_value={'entries': [], 'current_gym': 'Main'})
        self.legacy.start()
        self.addCleanup(self.legacy.stop)

    def test_no_profile_is_zero_friction(self):
        result = fit.exercise_fit_summary('Person', START, END)
        self.assertEqual(result['goals'], [])
        self.assertEqual(result['excluded'], [])
        self.assertFalse(self.path.exists())

    def test_profile_roundtrip_and_scoped_restrictions(self):
        fit.save_profile('Person', {
            'goals': [{'type': 'strength', 'exercise': 'Dead Hang'}, {'type': 'swim'}],
            'default_gym': 'Main', 'equipment': {'Main': ['bar']},
            'preferences': [{'exercise': 'Dead Hang', 'location': 'Main'}],
            'observations': [{'exercise': 'Dead Hang', 'type': 'discomfort', 'date': '2026-11-01'}],
            'restrictions': [
                {'exercise': 'Dead Hang', 'type': 'avoid', 'location': 'Main', 'start_date': '2026-11-25'},
                {'exercise': 'Pull-Up', 'type': 'unavailable', 'location': 'Other'},
            ]})
        result = fit.exercise_fit_summary('Person', START, END)
        self.assertEqual([g['type'] for g in result['goals']], ['strength', 'swim'])
        self.assertEqual(result['excluded'], [])
        self.assertEqual(fit.excluded_for_session(result, '2026-11-26', 'Main'), ['Dead Hang'])
        self.assertEqual(fit.excluded_for_session(result, '2026-11-23', 'Main'), [])
        self.assertEqual(fit.excluded_for_session(result, None, 'Main'), [])
        self.assertEqual(fit.excluded_for_session(result, '2026-11-26', None), [])
        self.assertEqual(fit.excluded_for_session(result, '2026-11-26', 'Other'), ['Pull-Up'])
        self.assertEqual(len(result['observations']), 1)

    def test_legacy_and_variant_scope(self):
        self.legacy.stop()
        self.legacy = patch.object(fit, 'read_bench_log', return_value={'current_gym': None, 'entries': [
            {'exercise': 'Dead Hang', 'disposition': 'retired'},
            {'exercise': 'Pull-Up', 'disposition': 'unavailable', 'unavailable_gyms': [None]}]})
        self.legacy.start()
        fit.save_profile('Person', {'restrictions': [{'exercise': 'Pull-Up', 'type': 'limitation', 'variant': 'wide grip'}]})
        result = fit.exercise_fit_summary('Person', START, END)
        self.assertEqual(result['default_gym'], '')
        self.assertEqual(result['excluded'], ['Dead Hang', 'Pull-Up'])
        self.assertEqual(fit.excluded_for_session(result, START, None), ['Dead Hang'])
        self.assertEqual(fit.excluded_for_session(result, START, 'Other', variant='wide grip'), ['Dead Hang', 'Pull-Up'])
        self.assertEqual(fit.excluded_for_session(result, START, ''), ['Dead Hang', 'Pull-Up'])

    def test_history_counts_sessions_without_inferred_fit(self):
        rows = [{'exercise': 'Dead Hang', 'date': '2026-11-20', 'outcome': 'completed'}] * 3
        rows += [{'exercise': 'Pull-Up', 'date': '2026-11-18', 'outcome': 'omitted'},
                 {'exercise': 'Pull-Up', 'date': '2026-11-19', 'outcome': 'swapped'}]
        result = fit.exercise_fit_summary('Person', START, END, history=rows)
        records = {r['exercise']: r for r in result['history']}
        self.assertEqual(records['Dead Hang']['completed'], 1)
        self.assertEqual(records['Dead Hang']['fit'], 'unknown')
        self.assertEqual(records['Pull-Up']['fit'], 'uncertain')
        self.assertEqual(result['excluded'], [])

    def test_atomic_save_is_idempotent_and_records_history(self):
        profile = {'goals': [{'type': 'swim'}]}
        fit.save_profile('Person', profile)
        self.assertEqual(self.commit.call_count, 1)
        first_stat = self.path.stat().st_mtime_ns
        fit.save_profile('Person', profile)
        self.assertEqual(self.commit.call_count, 1)
        self.assertEqual(self.path.stat().st_mtime_ns, first_stat)
        self.assertEqual(list(self.path.parent.glob('.coach-profile-*')), [])

    def test_as_of_and_unknown_gym(self):
        fit.save_profile('Person', {'default_gym': None, 'observations': [
            {'exercise': 'Dead Hang', 'type': 'effort', 'date': '2026-11-25'},
            {'exercise': 'Dead Hang', 'type': 'preference', 'date': None}],
            'restrictions': [{'exercise': 'Dead Hang', 'type': 'avoid', 'location': 'Main'}]})
        result = fit.exercise_fit_summary('Person', START, END, as_of='2026-11-23')
        self.assertEqual(len(result['observations']), 1)
        self.assertEqual(result['excluded'], [])
        self.assertEqual(fit.excluded_for_session(result, None, None), [])

    def test_person_is_single_directory(self):
        for name in ('', ' ', '.', '..', '../other', 'a/b', 'a\\b', '\x00'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                fit.validate_person(name)
        self.assertEqual(fit.validate_person('Person A'), 'Person A')

    def test_invalid_profile_rejected(self):
        with self.assertRaises(ValueError):
            fit.save_profile('Person', {'restrictions': [{'exercise': 'Imaginary Exercise', 'type': 'avoid'}]})
        with self.assertRaises(ValueError):
            fit.save_profile('Person', {'goals': [{'type': 'strength'}]})
        self.path.write_text('{broken')
        with self.assertRaises(ValueError):
            fit.exercise_fit_summary('Person', START, END)

if __name__ == '__main__':
    unittest.main()
