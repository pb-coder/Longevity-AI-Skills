from __future__ import annotations

import unittest

from tracker.csv_table import date_str


class CsvTableDateStrTests(unittest.TestCase):
    def test_date_str_rejects_impossible_calendar_dates(self) -> None:
        self.assertIsNone(date_str("2026-13-40"))
        self.assertIsNone(date_str("2026-02-30"))

    def test_date_str_accepts_valid_dates_and_trims_time_component(self) -> None:
        self.assertEqual(date_str("2026-06-15"), "2026-06-15")
        self.assertEqual(date_str("2026-06-15T10:30:00"), "2026-06-15")

    def test_date_str_rejects_empty_and_unpadded_values(self) -> None:
        self.assertIsNone(date_str(""))
        self.assertIsNone(date_str(None))
        self.assertIsNone(date_str("2026-6-5"))


if __name__ == "__main__":
    unittest.main()
