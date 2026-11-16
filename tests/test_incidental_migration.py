from __future__ import annotations

import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared import maintain, person_paths
from shared.csv_store import WORKOUT_SESSIONS_HEADERS


class IncidentalMigrationTests(unittest.TestCase):
    def test_legacy_header_migrates_and_pads_incidental(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.object(person_paths, "WORKOUT_TRACKER_ROOT", Path(td)):
            path = person_paths.workout_sessions_csv("Person")
            path.parent.mkdir(parents=True)
            legacy_header = [h for h in WORKOUT_SESSIONS_HEADERS if h != "Incidental"]
            row = ["2026-05-01", "08:00:00", "08:30:00", "Walking", "30", "120",
                   "140", "100", "75", "2.5", "apple", "incidental walk; easy"]
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(legacy_header)
                writer.writerow(row)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(maintain.migrate_incidental_flag("Person"), 0)
            with path.open(newline="", encoding="utf-8") as stream:
                actual = list(csv.reader(stream))
            self.assertEqual(actual, [WORKOUT_SESSIONS_HEADERS, row[:11] + ["true", "easy"]])

    def test_migration_preserves_fields_sorts_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.object(person_paths, "WORKOUT_TRACKER_ROOT", Path(td)):
            path = person_paths.workout_sessions_csv("Person")
            path.parent.mkdir(parents=True)
            rows = [
                ["2026-05-01", "08:00:00", "08:30:00", "Walking", "30", "120", "140", "100", "75", "2.5", "apple", "false", "incidental walk; easy"],
                ["2026-05-02", "09:00:00", "09:10:00", "Running", "10", "", "", "", "", "", "apple", "true", "already flagged"],
            ]
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(WORKOUT_SESSIONS_HEADERS)
                writer.writerows(rows)
            original = path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(maintain.migrate_incidental_flag("Person", dry_run=True), 0)
            self.assertEqual(path.read_bytes(), original)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(maintain.migrate_incidental_flag("Person"), 0)
            with path.open(newline="", encoding="utf-8") as stream:
                actual = list(csv.reader(stream))
            self.assertEqual(actual[0], WORKOUT_SESSIONS_HEADERS)
            self.assertEqual(actual[1], rows[1])
            self.assertEqual(actual[2], rows[0][:11] + ["true", "easy"])
            migrated = path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(maintain.migrate_incidental_flag("Person"), 0)
            self.assertEqual(path.read_bytes(), migrated)


if __name__ == "__main__":
    unittest.main()
