"""The heading/content policy never lowers a session's core allocation."""
from itertools import product
import unittest
from unittest.mock import patch

from workout_coach.lib import adherence
from workout_coach.lib.constants import CORE_WEEK_SPEC
from workout_coach.lib.plan_validators import _session_core_set_bounds


class SessionClassifierMatrixTests(unittest.TestCase):
    def test_all_heading_content_combinations(self):
        # Rows are the heading's claim, columns are the content's verdict.
        cases = {
            None: (None, None, "lower", "full"),
            "upper": ("upper", "upper", "lower", "full"),
            "lower": ("lower", "lower", "lower", "lower"),
            "full": ("full", "full", "full", "full"),
        }
        states = (None, "upper", "lower", "full")
        for named, content in product(states, repeat=2):
            with self.subTest(named=named, content=content), \
                 patch.object(adherence, "_session_type_from_name", return_value=named), \
                 patch.object(adherence, "session_type_from_content", return_value=content):
                self.assertEqual(adherence.session_type_from_title("title", []),
                                 cases[named][states.index(content)])

    def test_heading_resolution_and_safe_core_bands(self):
        cases = [(None, None), ("Mobility", None), ("Push", "upper"),
                 ("Legs", "lower"), ("Full Body", "full"),
                 ("Upper + Legs", "full")]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(adherence.session_type_from_title(title), expected)
                dose = (CORE_WEEK_SPEC["sets_per_session"]["upper"] if expected == "upper"
                        else max(CORE_WEEK_SPEC["sets_per_session"].values()))
                self.assertEqual(_session_core_set_bounds(title, CORE_WEEK_SPEC)[0], dose)

    def test_omitted_slots_do_not_run_content_classifier(self):
        with patch.object(adherence, "session_type_from_content") as content:
            self.assertEqual(adherence.session_type_from_title("Upper"), "upper")
            content.assert_not_called()


if __name__ == "__main__":
    unittest.main()
