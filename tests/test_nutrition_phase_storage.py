"""Nutrition phase storage and logger round trips with synthetic values."""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from shared import csv_store_periodic as store

ROOT = Path(__file__).resolve().parents[1]
LOGGER = ROOT / 'workout-logger/scripts/append_workout.py'

class NutritionStorageTests(unittest.TestCase):
    def test_legacy_header_sparse_update_and_new_values(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'nutrition_phases.csv'
            with path.open('w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(store.NUTRITION_PHASES_HEADERS[:8])
                writer.writerow(['2026-01-01', '', 'cut', '', '', '-0.5', 'review', 'note'])
            with patch.object(store, 'nutrition_phases_csv', return_value=path), patch.object(store, 'ensure_data_dir'):
                old = store.read_nutrition_phases('Person')[0]
                self.assertIsNone(old['target_rate_percent_per_week'])
                store.upsert_nutrition_phases('Person', [{'start_date': '2026-01-01',
                    'target_rate_percent_per_week': -0.4, 'reference_weight_kg': 80}])
                row = store.read_nutrition_phases('Person')[0]
                self.assertEqual((row['target_rate_kg_per_wk'], row['target_rate_percent_per_week'],
                                  row['reference_weight_kg'], row['notes']), (-0.5, -0.4, 80, 'note'))
                store.upsert_nutrition_phases('Person', [{'start_date': '2026-01-01', 'end_date': '2026-02-01'}])
                self.assertEqual(store.read_nutrition_phases('Person')[0]['reference_weight_kg'], 80)

    def test_logger_payload_round_trip_and_rejects_invalid_reference(self):
        with tempfile.TemporaryDirectory() as td:
            payload = Path(td) / 'payload.json'
            item = {'start_date': '2026-01-01', 'phase_type': 'cut',
                    'target_rate_percent_per_week': -0.5, 'reference_weight_kg': 80}
            payload.write_text(json.dumps({'nutrition_phase': [item]}))
            env = dict(os.environ, WORKOUT_TRACKER_ROOT=td, PYTHONDONTWRITEBYTECODE='1')
            run = subprocess.run([sys.executable, str(LOGGER), '--person', 'Person', str(payload)],
                                 cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            files = list(Path(td).rglob('nutrition_phases.csv'))
            self.assertEqual(len(files), 1)
            with files[0].open(newline='') as f:
                saved = list(csv.DictReader(f))[0]
            self.assertEqual(saved['Target Rate (%/wk)'], '-0.5')
            self.assertEqual(saved['Reference Weight (kg)'], '80')
            item['reference_weight_kg'] = 0
            payload.write_text(json.dumps({'nutrition_phase': [item]}))
            invalid = subprocess.run([sys.executable, str(LOGGER), '--person', 'Person', str(payload)],
                                     cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertNotEqual(invalid.returncode, 0)

if __name__ == '__main__':
    unittest.main()
