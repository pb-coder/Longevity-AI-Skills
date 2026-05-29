from __future__ import annotations

import unittest


from workout_coach.lib.render_validators import (
    COACH_STRING_MAX,
    auto_wrap_terms,
    validate_coach_reads,
)


class RenderValidatorTests(unittest.TestCase):
    def test_rejects_em_dash_in_headline_and_cards(self) -> None:
        errors, _ = validate_coach_reads({
            "headline": "Train — but gently",
            "cards": {"strength": "Good — enough"},
        })
        self.assertTrue(any("headline" in e and "em-dash" in e for e in errors))
        self.assertTrue(any("cards.strength" in e and "em-dash" in e for e in errors))

    def test_rejects_overlong_card_text(self) -> None:
        errors, _ = validate_coach_reads({
            "headline": "Valid",
            "cards": {"strength": "x" * (COACH_STRING_MAX + 1)},
        })
        self.assertTrue(any("cards.strength" in e and "max" in e for e in errors))

    def test_missing_required_callouts_are_warnings(self) -> None:
        errors, warnings = validate_coach_reads({"headline": "Valid", "cards": {}})
        self.assertEqual(errors, [])
        self.assertTrue(any("cards.strength missing" in w for w in warnings))

    def test_auto_wrap_terms_wraps_first_occurrence_only(self) -> None:
        wrapped = auto_wrap_terms("CTL is up; CTL matters.")
        self.assertEqual(wrapped.count('class="term"'), 1)
        self.assertIn("Chronic Training Load", wrapped)


if __name__ == "__main__":
    unittest.main()
