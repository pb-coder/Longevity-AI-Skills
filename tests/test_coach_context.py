"""The model-facing weekly projection keeps decision and revision evidence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from workout_coach.lib.coach_context import coach_context
from workout_coach.lib.weekly_prescription import validate_week

ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / 'workout-coach/scripts/read_tracker.py'
FIXTURES = ROOT / 'tests/fixtures'


class CoachContextTests(unittest.TestCase):
    def test_revision_and_scoped_restrictions_are_untouched(self):
        snapshot = {
            'existing_week': {'prescription': {'sessions': [
                {'id': 'retained', 'date': '2026-05-18', 'exercises': [{'exercise': 'Example'}]}]}},
            'exercise_fit': {'restrictions': [{'exercise': 'Example', 'location': 'Gym',
                                                'start_date': '2026-05-19'}]},
            'next_dose': {'exercises': [{'exercise': 'Example',
                                         'equipment_context': {'gym': 'Gym'}}]},
        }
        original = {**snapshot, 'new_private_report': {'detail': 'Private note'}}
        self.assertEqual(coach_context(original), snapshot)

    def run_reader(self, *flags, tracker_root=FIXTURES):
        env = {**os.environ, 'WORKOUT_TRACKER_ROOT': str(tracker_root)}
        return subprocess.run([sys.executable, str(READER), '--person', 'person_a',
                               '--today', '2026-05-17', *flags], env=env,
                              text=True, capture_output=True)

    def test_projection_preserves_decision_evidence(self):
        full = self.run_reader('--weekly', '--months', '6')
        projected = self.run_reader('--weekly', '--months', '6', '--for-coach')
        self.assertEqual(full.returncode, 0, full.stderr)
        self.assertEqual(projected.returncode, 0, projected.stderr)
        original, compact = json.loads(full.stdout), json.loads(projected.stdout)
        for key in ('observation_coverage', 'exercise_fit',
                    'next_dose', 'adherence',
                    'nutrition_phase', 'existing_week', 'session_time_model'):
            if key in original:
                self.assertEqual(original[key], compact[key], key)
        self.assertEqual(original['rotation_candidates']['candidates'],
                         compact['rotation_candidates']['candidates'])
        self.assertNotIn('derivation', compact['rotation_candidates'])
        self.assertNotIn('longevity_state', compact)
        self.assertNotIn('longevity_score', compact)
        self.assertEqual(compact['weekly_plan']['observed_revision'], 0)
        self.assertIn('monthly_sessions_coverage', compact)
        self.assertLess(len(projected.stdout), len(full.stdout))

    def test_history_window_and_grouped_block_safety(self):
        entry = {'position': 1, 'exercise': 'Example', 'dose': {'machine': 'A'}}
        snapshot = {'today': '2026-05-28', 'monthly_sessions': [
            {'date': '2026-04-30'}, {'date': '2026-05-01'}, {'date': '2026-05-28'}],
            'block': {'sessions': {'upper': [entry]},
                      'slots': [{'session_type': 'upper', **entry}]}}
        compact = coach_context(snapshot)
        self.assertEqual([x['date'] for x in compact['monthly_sessions']], ['2026-05-01', '2026-05-28'])
        self.assertEqual(compact['monthly_sessions_coverage']['omitted_older_count'], 1)
        self.assertNotIn('sessions', compact['block'])
        snapshot['block']['slots'][0]['dose'] = {'machine': 'B'}
        self.assertIn('sessions', coach_context(snapshot)['block'])

    def test_field_projection(self):
        full = json.loads(self.run_reader('--weekly').stdout)
        result = self.run_reader('--weekly', '--field', 'bodyweight_latest', '--field', 'next_dose')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {k: full[k] for k in ('bodyweight_latest', 'next_dose') if k in full})
        self.assertEqual(self.run_reader('--field', 'unknown_field').returncode, 2)
        self.assertEqual(self.run_reader('--weekly', '--for-coach', '--field', 'next_dose').returncode, 2)

    def test_planning_and_selected_metrics_skip_longevity_markdown(self):
        with tempfile.TemporaryDirectory() as tracker_root:
            person = Path(tracker_root) / 'person_a'
            shutil.copytree(FIXTURES / 'person_a', person)
            longevity = person / 'data/longevity'
            longevity.mkdir()
            (longevity / 'state.md').write_bytes(b'\xff')
            for flags in (('--for-coach',), ('--field', 'bodyweight_latest')):
                with self.subTest(flags=flags):
                    result = self.run_reader('--weekly', *flags, tracker_root=tracker_root)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn('longevity_state', json.loads(result.stdout))

    def test_validator_equivalence(self):
        doc = {'week_start': '2026-11-23', 'week_end': '2026-11-29', 'as_of': '2026-11-19',
               'sessions': [{'id': 'a', 'type': 'Upper', 'duration_min': 60,
                             'exercises': [{'name': 'Flat Barbell Bench Press', 'sets': [{'reps': 8, 'load_kg': 40}]}]}]}
        tracker = {'weekly_plan': {'week_start': '2026-11-23', 'week_end': '2026-11-29',
                                   'as_of': '2026-11-19', 'session_count': 1, 'session_target_min': 60},
                   'exercise_fit': {'excluded': ['Flat Barbell Bench Press']},
                   'next_dose': {'exercises': []}, 'target_working_sets': 4,
                   'existing_week': {'revision': 3, 'prescription': doc}}
        projection = coach_context(tracker)
        self.assertEqual(projection['weekly_plan']['observed_revision'], 3)
        self.assertEqual(validate_week(doc, tracker), validate_week(doc, projection))

    def test_projection_requires_weekly_and_rejects_detail_flags(self):
        for flags in [('--for-coach',), ('--weekly', '--for-coach', '--include-rows'),
                      ('--weekly', '--for-coach', '--include-1rm-history'),
                      ('--weekly', '--for-coach', '--include-daily-health')]:
            with self.subTest(flags=flags):
                self.assertEqual(self.run_reader(*flags).returncode, 2)


if __name__ == '__main__':
    unittest.main()
