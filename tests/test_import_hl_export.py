from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILLS_ROOT))
sys.path.insert(0, str(SKILLS_ROOT / "shared"))

import import_hl_export  # noqa: E402


class HLExportTests(unittest.TestCase):
    def test_incidental_walk_uses_typed_flag_not_notes(self) -> None:
        row = import_hl_export.extract_hl_workout(
            "2026-05-17",
            datetime(2026, 5, 17, 9, 10, 0),
            "HKWorkoutActivityType(rawValue: 52), 10 min, 30 kcal, 0.5 km",
        )
        self.assertIsNotNone(row)
        self.assertIs(row["incidental"], True)
        self.assertIsNone(row["notes"])


if __name__ == "__main__":
    unittest.main()
