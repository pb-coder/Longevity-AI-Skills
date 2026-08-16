"""Tests for the Trajectory tab's Energy expenditure card (`card_energy`).

The card renders ONLY when the payload carries a top-level `energy_28d`
block, and its one coloured signal is an amber basal-trend row that fires
when resting burn falls while a cut is open. Both of those are gates, and
a gate that is not pinned is a gate that quietly stops gating.
"""
from __future__ import annotations

import unittest

from workout_coach.lib.render_cards_programs import card_energy
from workout_coach.lib.render_validators import (
    COACH_CARD_KEYS,
    COACH_STRING_MAX,
    EM_DASH,
    GATED_COACH_CARD_KEYS,
)


ENERGY_28D = {
    "tdee_kcal_daily_avg": 3204,
    "active_kcal_daily_avg": 1058,
    "basal_kcal_daily_avg": 2146,
    "n_days": 28,
    "tdee_trend_kcal_per_week": -18.4,
    "basal_trend_kcal_per_week": -9.1,
}


def _phase(phase_type, *, energy=None):
    """A minimal `nutrition_phase` block for an OPEN phase of `phase_type`."""
    block = {
        "current": {
            "start_date": "2026-08-03",
            "end_date": None,
            "phase_type": phase_type,
            "days_elapsed": 12,
            "weeks_in_phase": 1.7,
        },
        "targets": {},
        "actuals": {},
        "status": "on_track",
        "stop_signals_triggered": [],
        "coach_action_hint": "continue",
    }
    if energy is not None:
        block["energy"] = energy
    return block


def _basal_row(html):
    """The Basal trend row's markup, sliced out of the card."""
    start = html.index("Basal trend")
    end = html.find("secondary-metric", start)
    return html[start:end if end != -1 else len(html)]


class CardEnergyRenderTests(unittest.TestCase):
    def test_renders_hero_with_tdee_and_active_basal_split(self) -> None:
        html = card_energy(ENERGY_28D, None, None)
        self.assertIn("Energy expenditure", html)
        self.assertIn("metric-hero", html)
        # Hero value is TDEE; the split rides beneath it in the sublabel.
        self.assertIn("3,204", html)
        self.assertIn("kcal/day", html)
        self.assertIn("1,058 kcal active", html)
        self.assertIn("2,146 kcal basal", html)
        self.assertIn("28 day average", html)
        # Both trend rows render off the block alone, no phase required.
        self.assertIn("Basal trend", html)
        self.assertIn("-9.1", html)
        self.assertIn("Total trend", html)
        self.assertIn("-18.4", html)

    def test_suppressed_when_energy_block_absent(self) -> None:
        # The block is ABSENT, not null, when there is no energy data
        # (`_compact` drops it), so `.get` returns None.
        self.assertEqual(card_energy(None, None, None), "")
        self.assertEqual(card_energy({}, None, None), "")
        self.assertEqual(
            card_energy(None, _phase("cut"), "some coach text"), ""
        )

    def test_coach_callout_renders_when_supplied(self) -> None:
        html = card_energy(ENERGY_28D, None, "Hold the deficit where it is.")
        self.assertIn("Hold the deficit where it is.", html)
        self.assertIn('class="coach"', html)
        # No callout, no empty aside.
        self.assertNotIn('class="coach"', card_energy(ENERGY_28D, None, None))

    def test_card_literal_copy_obeys_the_coach_copy_rules(self) -> None:
        """Em-dash ban and the 280-char cap apply to the card's own strings."""
        variants = [
            card_energy(ENERGY_28D, None, None),
            card_energy(ENERGY_28D, _phase("cut"), None),
            card_energy(
                ENERGY_28D,
                _phase("bulk", energy={
                    "tdee_kcal": 3204,
                    "target_deficit_kcal": -400,
                    "implied_intake_kcal": 3604,
                    "basis": "measured_28d",
                }),
                None,
            ),
        ]
        for html in variants:
            self.assertNotIn(EM_DASH, html)
            for sublabel in ("metric-hero-sub", "secondary-sub"):
                for chunk in html.split(f'class="{sublabel} muted">')[1:]:
                    self.assertLessEqual(
                        len(chunk.split("</div>")[0]), COACH_STRING_MAX
                    )


class CardEnergyBasalFlagTests(unittest.TestCase):
    def test_amber_when_basal_falls_during_an_open_cut(self) -> None:
        html = card_energy(ENERGY_28D, _phase("cut"), None)
        row = _basal_row(html)
        self.assertIn('secondary-value amber', row)
        self.assertIn("metabolic adaptation", row)

    def test_no_amber_when_no_phase_is_open(self) -> None:
        row = _basal_row(card_energy(ENERGY_28D, None, None))
        self.assertNotIn("amber", row)
        self.assertIn('secondary-value muted', row)
        self.assertNotIn("metabolic adaptation", row)

    def test_no_amber_when_the_open_phase_is_not_a_cut(self) -> None:
        for phase_type in ("bulk", "maintain", "recomp"):
            with self.subTest(phase_type=phase_type):
                row = _basal_row(card_energy(ENERGY_28D, _phase(phase_type), None))
                self.assertNotIn("amber", row)
                self.assertNotIn("metabolic adaptation", row)

    def test_no_amber_when_basal_is_flat_or_rising_during_a_cut(self) -> None:
        for trend in (0.0, 12.5):
            with self.subTest(trend=trend):
                block = dict(ENERGY_28D, basal_trend_kcal_per_week=trend)
                row = _basal_row(card_energy(block, _phase("cut"), None))
                self.assertNotIn("amber", row)
                self.assertIn("holding or rising", row)

    def test_no_amber_when_the_cut_is_closed(self) -> None:
        closed = _phase("cut")
        closed["current"]["end_date"] = "2026-08-14"
        row = _basal_row(card_energy(ENERGY_28D, closed, None))
        self.assertNotIn("amber", row)

    def test_basal_row_omitted_when_the_trend_is_absent(self) -> None:
        block = {k: v for k, v in ENERGY_28D.items()
                 if k != "basal_trend_kcal_per_week"}
        html = card_energy(block, _phase("cut"), None)
        self.assertNotIn("Basal trend", html)
        self.assertIn("Total trend", html)


class CardEnergyImpliedIntakeTests(unittest.TestCase):
    ENERGY_SUB = {
        "tdee_kcal": 3204,
        "target_deficit_kcal": 550,
        "implied_intake_kcal": 2654,
        "basis": "measured_28d",
    }

    def test_implied_intake_row_renders_with_the_phase_energy_sub_block(self) -> None:
        html = card_energy(ENERGY_28D, _phase("cut", energy=self.ENERGY_SUB), None)
        self.assertIn("Implied intake target", html)
        self.assertIn("2,654", html)
        self.assertIn("550 kcal deficit", html)
        self.assertIn("measured over the last 28 days", html)

    def test_implied_intake_row_omitted_when_the_sub_block_is_absent(self) -> None:
        # The sub-block is optional; the card must not synthesise one.
        self.assertNotIn(
            "Implied intake target", card_energy(ENERGY_28D, _phase("cut"), None)
        )
        self.assertNotIn(
            "Implied intake target", card_energy(ENERGY_28D, None, None)
        )

    def test_negative_deficit_reads_as_a_surplus(self) -> None:
        sub = dict(self.ENERGY_SUB, target_deficit_kcal=-400,
                   implied_intake_kcal=3604)
        html = card_energy(ENERGY_28D, _phase("bulk", energy=sub), None)
        self.assertIn("400 kcal surplus", html)
        self.assertNotIn("-400 kcal", html)

    def test_unrecognised_basis_falls_back_to_its_own_text(self) -> None:
        sub = dict(self.ENERGY_SUB, basis="modelled_from_bodyweight")
        html = card_energy(ENERGY_28D, _phase("cut", energy=sub), None)
        self.assertIn("modelled from bodyweight", html)


class CardEnergyRegistrationTests(unittest.TestCase):
    def test_trajectory_energy_is_a_documented_coach_card_key(self) -> None:
        self.assertIn("trajectory_energy", COACH_CARD_KEYS)

    def test_trajectory_energy_is_gated_so_a_missing_callout_is_silent(self) -> None:
        self.assertIn("trajectory_energy", GATED_COACH_CARD_KEYS)
        self.assertTrue(GATED_COACH_CARD_KEYS <= set(COACH_CARD_KEYS))

    def test_missing_callout_does_not_warn_for_the_gated_key(self) -> None:
        from workout_coach.lib.render_validators import validate_coach_reads

        errors, warnings = validate_coach_reads(
            {"headline": "Train as planned.", "cards": {}}
        )
        self.assertEqual(errors, [])
        self.assertFalse([w for w in warnings if "trajectory_energy" in w])

    def test_documented_import_path_resolves_through_the_facade(self) -> None:
        from workout_coach.lib import render_cards_trajectory

        self.assertIs(render_cards_trajectory.card_energy, card_energy)
        self.assertIn("card_energy", render_cards_trajectory.__all__)

    def test_render_dashboard_wires_the_card_above_nutrition_phase(self) -> None:
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1]
               / "workout-coach" / "scripts" / "render_dashboard.py"
               ).read_text(encoding="utf-8")
        self.assertIn('card_energy(j.get("energy_28d")', src)
        self.assertLess(src.index('{card_energy(j.get("energy_28d")'),
                        src.index('{card_nutrition_phase('))


if __name__ == "__main__":
    unittest.main()
