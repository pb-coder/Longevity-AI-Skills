from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from shared import canonicalize_logs, monthly_csv, person_paths


class CanonicalizeLogsTests(unittest.TestCase):
    """Regression tests for shared/canonicalize_logs.py — the rename map that
    fixes historical typo'd exercise names in past monthly CSVs and clears
    stale '(not in database)' Notes. Previously only had a --help smoke test.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = person_paths.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = Path(self.tmp.name)
        self.canonical = canonicalize_logs.load_canonical_names(canonicalize_logs.DB_MD)

    def tearDown(self) -> None:
        person_paths.WORKOUT_TRACKER_ROOT = self.old_root
        self.tmp.cleanup()

    def write_month(self, ym: str, rows: list[list]) -> Path:
        path = person_paths.monthly_csv("Test", ym)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(monthly_csv.MONTHLY_HEADERS)
            writer.writerows(rows)
        return path

    def read_rows(self, path: Path) -> tuple[list[str], list[list[str]]]:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            return next(reader), list(reader)

    def test_typo_renamed_and_stale_not_in_database_note_cleared(self) -> None:
        # "Dips" is a real entry in canonicalize_logs.RENAMES -> "Dip", which
        # is itself the canonical name in exercises-database.md, so the
        # stale "(not in database)" note should also be cleared once the
        # post-rename name resolves to a known exercise.
        row = [
            "", "2026-05-14", "1", "Dips", "1", "10", "0", "",
            "(not in database)", "", "", "", "", "", "", "", "", "manual",
        ]
        path = self.write_month("2026.05", [row])

        renamed, cleared, ambiguous = canonicalize_logs.canonicalize_csv(path, self.canonical)

        self.assertEqual(renamed, 1)
        self.assertEqual(cleared, 1)
        self.assertEqual(ambiguous, [])

        _, rows = self.read_rows(path)
        self.assertEqual(rows[0][3], "Dip")
        self.assertEqual(rows[0][8], "")

    def test_ambiguous_leg_curl_is_reported_not_renamed(self) -> None:
        # Bare "Leg Curl" is in canonicalize_logs.AMBIGUOUS (could be Lying
        # or Seated) — it must be surfaced for manual disambiguation, never
        # auto-renamed.
        row = [
            "", "2026-05-14", "1", "Leg Curl", "1", "10", "20", "200",
            "", "", "", "", "", "", "", "", "", "manual",
        ]
        path = self.write_month("2026.05", [row])

        renamed, cleared, ambiguous = canonicalize_logs.canonicalize_csv(path, self.canonical)

        self.assertEqual(renamed, 0)
        self.assertEqual(cleared, 0)
        self.assertEqual(ambiguous, [(2, "Leg Curl")])

        _, rows = self.read_rows(path)
        self.assertEqual(rows[0][3], "Leg Curl")

    def test_rerun_is_idempotent(self) -> None:
        rows = [
            [
                "", "2026-05-14", "1", "Dips", "1", "10", "0", "",
                "(not in database)", "", "", "", "", "", "", "", "", "manual",
            ],
            [
                "", "2026-05-14", "2", "Leg Curl", "1", "10", "20", "200",
                "", "", "", "", "", "", "", "", "", "manual",
            ],
        ]
        path = self.write_month("2026.05", rows)

        first_counts = canonicalize_logs.canonicalize_csv(path, self.canonical)
        first_text = path.read_text(encoding="utf-8")

        second_counts = canonicalize_logs.canonicalize_csv(path, self.canonical)
        second_text = path.read_text(encoding="utf-8")

        self.assertEqual(first_counts, (1, 1, [(3, "Leg Curl")]))
        # Second pass: nothing left to rename or clear; the ambiguous row
        # is still surfaced every run (it is never silently dropped), but
        # the file content itself does not change.
        self.assertEqual(second_counts, (0, 0, [(3, "Leg Curl")]))
        self.assertEqual(first_text, second_text)


if __name__ == "__main__":
    unittest.main()
