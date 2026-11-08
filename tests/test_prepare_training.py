from __future__ import annotations
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_training', ROOT / 'shared' / 'prepare_training.py')
assert spec and spec.loader
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)

class PrepareTrainingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for p in ('Person', 'Other'):
            (self.root / p / 'data').mkdir(parents=True)
        self.workout = self.root / 'workout.json'
        self.workout.write_text(json.dumps({'rows': [{'date': '2026-11-03', 'num': 1,
            'exercise': 'Jumping Jacks', 'set': 1, 'reps': 60}]}))
        self.export = self.root / 'export.json'
        self.export.write_text('{}')
        person_patch = patch.object(prepare, 'person_dir', side_effect=lambda p: self.root / p)
        person_patch.start()
        self.addCleanup(person_patch.stop)

    def test_preview_checks_pairing_without_writes(self):
        with patch.object(prepare, 'import_export', return_value=['Dry run']) as preview, \
             patch.object(prepare.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            result = prepare.preflight([['Person', str(self.export), str(self.workout)]])
        self.assertEqual(result[0][0], 'Person')
        self.assertTrue(preview.call_args.kwargs['dry_run'])
        run.assert_not_called()
        self.assertEqual(self.export.read_text(), '{}')

    def test_rejects_shared_export_and_invalid_person(self):
        with patch.object(prepare, 'import_export', return_value=[]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'unique'):
                prepare.preflight([['Person', str(self.export), '-'], ['Other', str(self.export), '-']])
            with self.assertRaisesRegex(ValueError, 'unique'):
                prepare.preflight([['Person', '-', str(self.workout)], ['Other', '-', str(self.workout)]])
            with self.assertRaisesRegex(ValueError, 'Invalid person'):
                prepare.preflight([['../Other', '-', str(self.workout)]])

    def test_bad_later_entry_prevents_all_writes(self):
        args = ['prepare_training', '--entry', 'Person', '-', str(self.workout),
                '--entry', 'Other', '-', str(self.root / 'missing'), '--apply']
        with patch.object(sys, 'argv', args), patch.object(prepare.subprocess, 'run') as run, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(prepare.main(), 1)
        run.assert_not_called()

    def test_apply_calls_public_commands_with_explicit_paths(self):
        args = ['prepare_training', '--entry', 'Person', str(self.export), str(self.workout), '--apply']
        with patch.object(sys, 'argv', args), patch.object(prepare, 'import_export', return_value=[]), \
             patch.object(prepare.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            run.return_value.returncode = 0
            self.assertEqual(prepare.main(), 0)
        self.assertEqual(run.call_count, 2)
        self.assertIn(str(self.workout.resolve()), run.call_args_list[0].args[0])
        self.assertIn(str(self.export.resolve()), run.call_args_list[1].args[0])
        self.assertIn('--export', run.call_args_list[1].args[0])

    def test_preflight_detects_conflict_in_real_tracker_before_any_write(self):
        env = dict(os.environ, WORKOUT_TRACKER_ROOT=str(self.root))
        initial = self.root / 'initial.json'
        initial.write_text(self.workout.read_text())
        logger = ROOT / 'workout-logger' / 'scripts' / 'append_workout.py'
        first = subprocess.run([sys.executable, str(logger), '--person', 'Person', str(initial)],
                               env=env, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        conflict = self.root / 'conflict.json'
        conflict.write_text(json.dumps({'rows': [{'date': '2026-11-03', 'num': 1,
            'exercise': 'Jumping Jacks', 'set': 1, 'reps': 61}]}))
        before = (self.root / 'Person' / 'data' / 'monthly' / '2026.11.csv').read_bytes()
        run = subprocess.run([sys.executable, str(ROOT / 'shared' / 'prepare_training.py'),
            '--entry', 'Other', '-', str(self.workout), '--entry', 'Person', '-', str(conflict),
            '--apply'], env=env, capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0, run.stdout)
        self.assertIn('conflicts', run.stderr)
        self.assertEqual(before, (self.root / 'Person' / 'data' / 'monthly' / '2026.11.csv').read_bytes())
        self.assertFalse((self.root / 'Other' / 'data' / 'monthly').exists())

    def test_failure_stops_later_operations(self):
        args = ['prepare_training', '--entry', 'Person', str(self.export), str(self.workout), '--apply']
        with patch.object(sys, 'argv', args), patch.object(prepare, 'import_export', return_value=[]), \
             patch.object(prepare.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            run.return_value.returncode = 2
            self.assertEqual(prepare.main(), 2)
        self.assertEqual(run.call_count, 1)

if __name__ == '__main__':
    unittest.main()
