"""The two render strings that became false when the bodyweight trend
moved to an OLS fit with an explicit resolved / unresolved state.

Both cards used to explain a null rate with a cause of their own
invention. "needs 8+ fasted entries" was the pre-2026-08 rule and no
longer exists; "no trend" collapses "no weigh-ins" and "four weeks of
data do not resolve a direction" into one word, and only one of those is
something the user can act on. A dashboard that explains a missing
number with a made-up reason is telling the user something false about
their own data.
"""
from __future__ import annotations

import unittest

from workout_coach.lib.render_cards_domains import card_body_comp_domain
from workout_coach.lib.render_cards_health import card_vitals

_BW = {"kg": 78.4, "date": "2026-08-01"}
_WEEKLY = [{"hrv_sdnn": 55, "resting_hr": 52, "wrist_temp_c": 36.1,
            "sleep_total_h": 7.2, "sleep_deep_h": 1.1, "sleep_rem_h": 1.4,
            "vo2max": 48.0}]


def _block(reason, note="", state="unresolved"):
    return {"state": state, "reason": reason, "note": note,
            "kg_per_week": None, "n_readings": 4, "window_days": 28}


class BodyCompCardTests(unittest.TestCase):
    def _html(self, bw_trend, block=None):
        return card_body_comp_domain(_BW, bw_trend, None, "", block)

    def test_the_retired_eight_entry_rule_is_gone(self) -> None:
        html = self._html(None, _block("ci_straddles_zero"))
        self.assertNotIn("8+ fasted entries", html)
        self.assertNotIn("no trend yet", html)

    def test_the_reason_comes_from_the_block(self) -> None:
        html = self._html(None, _block("ci_straddles_zero"))
        self.assertIn("95% interval spans zero", html)

        html = self._html(None, _block("too_few_readings"))
        self.assertIn("too few weigh-ins", html)

        html = self._html(None, _block("window_shorter_than_min"))
        self.assertIn("28-day minimum", html)

    def test_an_unknown_reason_falls_back_to_the_blocks_own_note(self) -> None:
        html = self._html(None, _block("some_future_reason",
                                       note="Scale battery died."))
        self.assertIn("Scale battery died.", html)

    def test_no_block_at_all_claims_nothing(self) -> None:
        html = self._html(None, None)
        self.assertIn("not resolvable", html)
        self.assertNotIn("8+ fasted entries", html)

    def test_a_resolved_rate_still_renders_its_band(self) -> None:
        self.assertIn("lean-bulk range", self._html(0.25))
        self.assertIn("cutting trajectory", self._html(-0.35))


class VitalsCardTests(unittest.TestCase):
    def _html(self, bw_trend, block=None):
        return card_vitals(_WEEKLY, {"value": 48.0}, 0.3, _BW, bw_trend,
                           [78.0, 78.2, 78.4], "", block)

    def test_a_bare_no_trend_is_no_longer_emitted(self) -> None:
        html = self._html(None, _block("ci_straddles_zero"))
        self.assertNotIn(">no trend<", html)
        self.assertIn("direction unresolved", html)

    def test_no_weigh_ins_and_no_resolution_read_differently(self) -> None:
        self.assertIn("no weigh-ins", self._html(None, _block("no_readings")))
        self.assertIn("direction unresolved",
                      self._html(None, _block("ci_straddles_zero")))

    def test_a_resolved_rate_prints_the_number(self) -> None:
        self.assertIn("kg/wk", self._html(-0.25))


if __name__ == "__main__":
    unittest.main()
