from __future__ import annotations

import unittest
from datetime import date


from tracker.contracts import SessionRecommendation
from workout_coach.lib.health_session_rec import (
    _genuinely_stalled_lifts,
    _muscles_over_mrv,
    apply_user_override,
    compute_load_policy,
    compute_session_recommendation,
)


def _genuine_stall():
    """A lift flat at/near its best and not progressing — a true plateau."""
    return {"stalled_sessions": 3, "current_e1rm_kg": 100.0,
            "best_e1rm_kg": 100.0, "slope_kg_per_4w": 0.0}


def _comeback_lift():
    """Flat but well below best — being re-built after a layoff, not a stall."""
    return {"stalled_sessions": 3, "current_e1rm_kg": 60.0,
            "best_e1rm_kg": 100.0, "slope_kg_per_4w": 0.0}


def _rising_hr(*muscles):
    return {m: {"hint": "rising HR at constant volume — fatigue or under-recovery"}
            for m in muscles}


def recommendation(**overrides):
    args = {
        "recovery": {"score": 7.2, "drivers": []},
        "training_load": {"tsb": 0},
        "acwr": {},
        "weekly_volume": {},
        "sleep_regularity": {},
        "sleep_summary": {},
        "estimated_1rm": {},
        "hr_at_volume_divergence": {},
        "deloads": [],
        "auto_deload_candidates": [],
        "health_all": [],
        "today_d": date(2026, 5, 28),
        "estimated_max_hr": 190,
    }
    args.update(overrides)
    return compute_session_recommendation(**args)


class SessionRecommendationTests(unittest.TestCase):
    def test_green_tier_when_no_gate_fires(self) -> None:
        rec = recommendation()
        self.assertEqual(rec["tier"], "D")
        self.assertEqual(rec["headline"], "Train as planned.")

    def test_recommendation_keys_match_declared_contract(self) -> None:
        rec = recommendation()
        declared = set(SessionRecommendation.__optional_keys__)
        self.assertTrue(set(rec.keys()).issubset(declared), set(rec.keys()) - declared)

    def test_high_fatigue_triggers_zone_2_reactive_deload(self) -> None:
        rec = recommendation(training_load={"tsb": -16})
        self.assertEqual(rec["tier"], "B")
        self.assertEqual(rec["label"], "reactive_deload")
        self.assertEqual(rec["substitute"]["kind"], "zone_2")

    def test_tier_c_includes_expected_rebound_slot(self) -> None:
        # Genuinely low recovery (below the hard floor) fires Tier C alone.
        # A very low score (<= 5.0) extends the modified window to slot 2.
        rec = recommendation(recovery={"score": 3.5, "drivers": []})
        self.assertEqual(rec["tier"], "C")
        self.assertEqual(rec["label"], "downgrade")
        self.assertEqual(rec["expected_rebound_by_session"], 2)
        self.assertIn("workout 2", rec["override_message"])

    def test_tier_c_recent_deload_extends_modification_window(self) -> None:
        rec = recommendation(
            recovery={"score": 3.5, "drivers": []},
            deloads=["2026-05-25"],
        )
        self.assertEqual(rec["tier"], "C")
        self.assertEqual(rec["expected_rebound_by_session"], 2)

    def test_over_recovered_triggers_taper_warning(self) -> None:
        rec = recommendation(training_load={"tsb": 16})
        self.assertEqual(rec["tier"], "E")
        self.assertEqual(rec["label"], "over_recovered")

    def test_recovery_between_tier_c_and_green_is_hold_load(self) -> None:
        # Just below the green floor downgrades to hold_load ONLY when
        # corroborated by negative freshness (strength TSB -8 here).
        rec = recommendation(recovery={"score": 5.2, "drivers": []},
                             training_load={"tsb": -8})
        self.assertEqual(rec["tier"], "C")
        self.assertEqual(rec["label"], "hold_load")
        # The label is historical: the call does not hold loads any more,
        # and its text must not tell the coach to.
        self.assertEqual(rec["load_policy"]["policy"], "progress")
        text = " ".join([rec["headline"], rec["substitute"]["prescription"],
                         rec["substitute"]["notes"], rec["override_message"]]
                        + [r["note"] for r in rec["rationale"]])
        self.assertNotIn("hold load", text.lower())
        self.assertNotIn("no PR", text)
        self.assertIn("next_dose", text)

    def test_recovery_floor_only_bites_when_corroborated(self) -> None:
        # Below the 5.5 green floor but FRESH (TSB 0) is green; the soft
        # floor only holds loads when corroborated by negative freshness.
        fresh = recommendation(recovery={"score": 5.49, "drivers": []})
        under_load = recommendation(recovery={"score": 5.49, "drivers": []},
                                    training_load={"tsb": -8})
        at_floor = recommendation(recovery={"score": 5.5, "drivers": []})
        self.assertEqual(fresh["tier"], "D")
        self.assertEqual(under_load["tier"], "C")
        self.assertEqual(at_floor["tier"], "D")

    def test_moderate_recovery_while_fresh_is_green(self) -> None:
        # Regression lock for the over-firing bug: recovery 4.8 with a
        # mildly-low HRV reading (-0.41) while freshness is positive must be
        # GREEN, not a Tier C downgrade. A single soft dip is not fatigue.
        rec = recommendation(
            recovery={"score": 4.8,
                      "drivers": [{"metric": "hrv_sdnn", "z": -0.41},
                                  {"metric": "resting_hr", "z": 0.41}]},
            training_load={"tsb": 0.2},
        )
        self.assertEqual(rec["tier"], "D")
        self.assertEqual(rec["label"], "green")

    def test_moderate_recovery_under_real_load_downgrades(self) -> None:
        # Same moderate recovery, but freshness is negative (carrying load):
        # the soft dip is now corroborated, so Tier C is correct.
        rec = recommendation(
            recovery={"score": 4.8, "drivers": [{"metric": "hrv_sdnn", "z": -0.41}]},
            training_load={"tsb": -8},
        )
        self.assertEqual(rec["tier"], "C")

    def test_mild_hrv_dip_with_strong_recovery_is_green(self) -> None:
        # Great recovery (7.2) plus one mildly-low HRV reading is noise; it
        # must not downgrade a fresh athlete.
        rec = recommendation(recovery={
            "score": 7.2, "drivers": [{"metric": "hrv_sdnn", "z": -0.5}]})
        self.assertEqual(rec["tier"], "D")

    def test_mrv_gate_uses_current_sets_per_week(self) -> None:
        self.assertEqual(
            _muscles_over_mrv({
                "window_days": 28,
                "current": {"chest": 24.0},
                "landmarks": {"chest": {"mrv": 22}},
            }),
            ["chest"],
        )

    # ---- Regression net: the gate must be able to return to green ----

    def test_flat_isolations_with_green_recovery_not_deload(self) -> None:
        # Returning trainee: flat-at-ceiling lifts + green recovery + balanced freshness.
        e1rm = {f"L{i}": _genuine_stall() for i in range(4)}
        rec = recommendation(
            estimated_1rm=e1rm,
            recovery={"score": 6.5, "drivers": []},
            training_load={"tsb": 1.5},
        )
        self.assertNotEqual(rec["tier"], "B")

    def test_genuine_stall_with_fatigue_triggers_deload(self) -> None:
        # The legit Tuchscherer path stays alive: ceiling-stall + real fatigue.
        e1rm = {f"L{i}": _genuine_stall() for i in range(4)}
        rec = recommendation(
            estimated_1rm=e1rm,
            recovery={"score": 4.0, "drivers": []},
            training_load={"tsb": -2},
        )
        self.assertEqual(rec["tier"], "B")
        self.assertEqual(rec["label"], "reactive_deload")
        self.assertEqual(rec["substitute"]["kind"], "reactive_deload_week")

    def test_comeback_lifts_excluded_from_stall_count(self) -> None:
        self.assertEqual(
            _genuinely_stalled_lifts({f"L{i}": _comeback_lift() for i in range(4)}),
            0,
        )
        self.assertEqual(
            _genuinely_stalled_lifts({f"G{i}": _genuine_stall() for i in range(4)}),
            4,
        )

    def test_a_lift_owed_weight_is_not_a_stall(self) -> None:
        # Every set at the top of the range means next_dose adds load: the
        # lift is waiting for the weight to go up, not stuck. It must not
        # count toward the reactive-deload trigger or the nutrition stop
        # signal, which both read this count. Reps did not improve AND no
        # bump was earned is what a stall is.
        owed = {**_genuine_stall(), "weight_owed": True}
        self.assertEqual(_genuinely_stalled_lifts({"A": owed}), 0)
        mixed = {"A": owed, "B": _genuine_stall(), "C": _genuine_stall()}
        self.assertEqual(_genuinely_stalled_lifts(mixed), 2)
        # Three genuine stalls plus one owed lift stay under the trigger
        # count that four owed-or-stalled lifts used to reach.
        rec = recommendation(
            estimated_1rm={"A": owed, "B": owed, "C": owed,
                           "D": _genuine_stall()},
            recovery={"score": 4.0, "drivers": []},
            training_load={"tsb": -2})
        self.assertNotIn("stalled_lifts",
                         [r["signal"] for r in rec["rationale"]])

    def test_hr_creep_during_bulk_not_downgrade(self) -> None:
        # Bulking athlete: systemic HR creep on a bulk is a confounder, not fatigue.
        hv = _rising_hr("chest", "triceps", "side_delts")
        hv["systemic_session_hr"] = {
            "hint": "session HR rose across many muscles — check bodyweight, "
                    "deload boundary, heat, or generic fatigue"}
        rec = recommendation(
            hr_at_volume_divergence=hv,
            recovery={"score": None, "drivers": []},
            training_load={"tsb": 6},
            bodyweight_trend=0.25,
        )
        self.assertNotEqual(rec["tier"], "C")

    def test_over_recovered_dominates_hr_creep(self) -> None:
        rec = recommendation(
            hr_at_volume_divergence=_rising_hr("chest", "triceps"),
            recovery={"score": 7.0, "drivers": []},
            training_load={"tsb": 13},
        )
        self.assertIn(rec["tier"], {"D", "E"})

    def test_hr_creep_without_corroboration_does_not_downgrade(self) -> None:
        # Localized HR creep while overall recovery is fine (5.2) and strength
        # freshness is positive must NOT escalate to a session-wide volume cut.
        rec = recommendation(
            hr_at_volume_divergence=_rising_hr("chest", "triceps", "side_delts"),
            recovery={"score": 5.2, "drivers": []},
            training_load={"tsb": 1.5},
        )
        signals = [r.get("signal") for r in rec.get("rationale", [])]
        self.assertNotIn("hr_at_volume_divergence", signals)

    def test_hr_creep_with_negative_strength_tsb_downgrades(self) -> None:
        # Corroborated by negative strength freshness -> the legit downgrade fires.
        rec = recommendation(
            hr_at_volume_divergence=_rising_hr("chest", "triceps", "side_delts"),
            recovery={"score": 6.5, "drivers": []},
            training_load={"tsb": -2},
        )
        self.assertEqual(rec["tier"], "C")
        signals = [r.get("signal") for r in rec.get("rationale", [])]
        self.assertIn("hr_at_volume_divergence", signals)

    def test_recovery_none_high_tsb_returns_green(self) -> None:
        rec = recommendation(
            recovery={"score": None, "drivers": []},
            training_load={"tsb": 6},
        )
        self.assertEqual(rec["tier"], "D")
        self.assertTrue(
            any(r.get("signal") == "recovery_unavailable"
                for r in rec.get("rationale", [])))

    def test_favorable_rhr_does_not_downgrade(self) -> None:
        # rhr_z is inverted: +0.75 means RHR is BELOW baseline (good). A good
        # RHR must not trip the Tier C "RHR elevated" downgrade.
        rec = recommendation(
            recovery={"score": 6.5,
                      "drivers": [{"metric": "resting_hr", "z": 0.75}]},
            training_load={"tsb": 1.5},
        )
        self.assertEqual(rec["tier"], "D")

    def test_elevated_rhr_still_downgrades(self) -> None:
        # The legit case: RHR elevated above baseline (negative inverted z).
        rec = recommendation(
            recovery={"score": 6.5,
                      "drivers": [{"metric": "resting_hr", "z": -0.75}]},
            training_load={"tsb": 1.5},
        )
        self.assertEqual(rec["tier"], "C")

    def test_exit_ramp_clears_served_deload(self) -> None:
        # Recent deload + rebounded → a stale auto-candidate must not re-loop.
        rec = recommendation(
            recovery={"score": 6.5, "drivers": [{"metric": "hrv_sdnn", "z": 0.0}]},
            training_load={"tsb": 0},
            deloads=["2026-05-25"],
            auto_deload_candidates=["2026-05-26"],
            today_d=date(2026, 5, 28),
        )
        self.assertNotEqual(rec["tier"], "B")


class GateStringsTests(unittest.TestCase):
    """SKILL tells the coach to quote `rationale[i].note`, and the plan
    validator rejects an em dash, so the gate must not emit one anywhere a
    string reaches the user. It also must not point at a section that does
    not exist."""

    SCENARIOS = {
        "tier_b_tsb": dict(training_load={"tsb": -16}),
        "tier_b_mrv": dict(weekly_volume={
            "current": {"chest": 30, "back": 40},
            "landmarks": {"chest": {"mrv": 20}, "back": {"mrv": 25}}}),
        "tier_c_recovery": dict(recovery={"score": 3.5, "drivers": []}),
        "tier_c_hold_load": dict(recovery={"score": 5.2, "drivers": []},
                                 training_load={"tsb": -8}),
        "tier_c_rhr": dict(recovery={
            "score": 6.5, "drivers": [{"metric": "resting_hr", "z": -0.75}]},
            training_load={"tsb": 1.5}),
        "tier_c_hr_creep": dict(
            hr_at_volume_divergence=_rising_hr("chest", "triceps"),
            recovery={"score": 5.0, "drivers": []},
            training_load={"tsb": -2}),
        "tier_b_stall": dict(
            estimated_1rm={f"L{i}": _genuine_stall() for i in range(4)},
            recovery={"score": 4.0, "drivers": []},
            training_load={"tsb": -2}),
        "tier_b_candidate": dict(auto_deload_candidates=["2026-05-26"]),
        "tier_d": dict(),
        "tier_d_no_recovery": dict(recovery={"score": None, "drivers": []},
                                   training_load={"tsb": 3}),
        "tier_d_below_floor": dict(recovery={"score": 5.0, "drivers": []},
                                   training_load={"tsb": 0}),
        "tier_e": dict(training_load={"tsb": 13}),
        "tier_e_no_recovery": dict(recovery={"score": None, "drivers": []},
                                   training_load={"tsb": 13}),
    }

    @staticmethod
    def _strings(obj):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from GateStringsTests._strings(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                yield from GateStringsTests._strings(v)

    def test_no_em_dash_in_anything_the_gate_emits(self) -> None:
        for name, kwargs in self.SCENARIOS.items():
            with self.subTest(name):
                rec = recommendation(**kwargs)
                for text in self._strings(rec):
                    self.assertNotIn("\u2014", text, f"{name}: {text!r}")
        # Tier A has to be reached through its own signal.
        crash = recommendation(
            recovery={"score": 2.0, "drivers": [
                {"metric": "hrv_sdnn", "z": -3.0},
                {"metric": "resting_hr", "z": -3.0}]})
        self.assertEqual(crash["tier"], "A")
        for text in self._strings(crash):
            self.assertNotIn("\u2014", text, text)

    def test_the_scenarios_reach_the_tiers_they_name(self) -> None:
        # Guard against the sweep above silently testing a single tier.
        reached = {recommendation(**kw)["tier"] for kw in
                   self.SCENARIOS.values()}
        self.assertEqual(reached, {"B", "C", "D", "E"})

    def test_tier_d_points_loads_at_next_dose(self) -> None:
        rec = recommendation()
        text = rec["substitute"]["prescription"]
        self.assertIn("next_dose", text)
        self.assertNotIn("SKILL.md", text)
        self.assertNotIn("\u00a76", text)


class LoadPolicyTests(unittest.TestCase):
    """The gate's ``load_policy``: the one answer to "may a weight go up".

    Recovery reaches it through the tier (the gate's own 4.0 / 5.0 / 5.5
    lines), strength TSB through its band; the stricter of the two wins.
    """

    def policy(self, **overrides) -> str:
        return recommendation(**overrides)["load_policy"]["policy"]

    def test_the_mapping_table(self) -> None:
        """Only red-flag days reduce; every other tier and TSB band progresses."""
        cases = [
            # (recovery score, strength TSB) -> (tier, policy)
            ((7.2, 0),     ("D", "progress")),     # green
            ((5.5, 0),     ("D", "progress")),     # exactly on the floor
            ((5.2, 0),     ("D", "progress")),     # under it, but fresh
            ((7.2, 12),    ("E", "progress")),     # over-recovered
            ((7.2, 5.0),   ("D", "progress")),     # well rested
            ((7.2, -4.9),  ("D", "progress")),     # balanced edge
            ((7.2, -7.5),  ("D", "progress")),     # carrying load
            ((7.2, -12),   ("D", "progress")),     # fatigued
            ((7.2, -14.9), ("D", "progress")),     # one step short of red
            ((7.2, -15),   ("B", "reduce")),       # high fatigue edge
            ((7.2, -16),   ("B", "reduce")),       # high fatigue
            ((3.5, 0),     ("C", "progress")),     # genuinely low recovery
            ((5.2, -8),    ("C", "progress")),     # hold_load floor guard
            ((3.5, -12),   ("C", "progress")),     # low and fatigued
        ]
        for (score, tsb), (tier, policy) in cases:
            with self.subTest(score=score, tsb=tsb):
                rec = recommendation(recovery={"score": score, "drivers": []},
                                     training_load={"tsb": tsb})
                self.assertEqual((rec["tier"], rec["load_policy"]["policy"]),
                                 (tier, policy))

    def test_no_row_of_the_mapping_is_a_hold(self) -> None:
        from workout_coach.lib import constants
        self.assertEqual(constants.LOAD_REDUCE_TIERS, {"A", "B"})
        self.assertEqual(constants.LOAD_REDUCE_TSB_BANDS, {"high_fatigue"})
        for tsb in range(-30, 30):
            for tier in "ABCDE":
                out = compute_load_policy({"tier": tier, "label": "x"},
                                          {"score": 5.0}, {"tsb": tsb})
                self.assertIn(out["policy"], ("progress", "reduce"))

    def test_a_normal_day_is_not_a_hold(self) -> None:
        """Recovery is scored so 5 is the person's own average. The old
        prose rule held every load below 6.5, so an average day froze them."""
        self.assertEqual(self.policy(recovery={"score": 5.0, "drivers": []},
                                     training_load={"tsb": 1.0}), "progress")

    def test_a_consistent_trainer_in_negative_tsb_still_progresses(self) -> None:
        """The reported bug: a bench sat at 44 kg for twelve weeks because
        carrying-load / fatigued freshness and Tier C kept holding it."""
        for tsb in (-6, -9.4, -11.8, -14):
            with self.subTest(tsb=tsb):
                rec = recommendation(recovery={"score": 4.6, "drivers": []},
                                     training_load={"tsb": tsb})
                self.assertEqual(rec["tier"], "C")
                self.assertEqual(rec["load_policy"]["policy"], "progress")
                self.assertIn("volume, not load", rec["load_policy"]["reason"])

    def test_tier_a_and_b_are_a_reduce_whatever_freshness_says(self) -> None:
        for tier in ("A", "B"):
            with self.subTest(tier=tier):
                out = compute_load_policy({"tier": tier, "label": "x"},
                                          {"score": 7.0}, {"tsb": 3})
                self.assertEqual(out["policy"], "reduce")
                self.assertIn(f"Tier {tier}", out["reason"])
                self.assertNotIn("TSB", out["reason"].split(";")[0])

    def test_tier_c_is_not_a_reduce(self) -> None:
        out = compute_load_policy({"tier": "C", "label": "downgrade"},
                                  {"score": 3.5}, {"tsb": -9.4})
        self.assertEqual(out["policy"], "progress")
        self.assertIn("not red flags", out["reason"])
        self.assertIn("set budget by x0.6", out["reason"])

    def test_high_fatigue_tsb_reduces_even_on_a_green_tier(self) -> None:
        out = compute_load_policy({"tier": "D", "label": "green"},
                                  {"score": 7.0}, {"tsb": -16.6})
        self.assertEqual(out["policy"], "reduce")
        self.assertIn("high fatigue band", out["reason"])

    def test_an_override_is_a_normal_block_whatever_the_tsb(self) -> None:
        # The user saw the call and chose to train normally, so the policy
        # is `progress` even with strength TSB in the high-fatigue band. The
        # reason still says what the TSB was and that the user overrode it.
        overridden = {"tier": "D", "label": "green", "rationale": [
            {"signal": "user_override"}]}
        red = compute_load_policy(overridden, {"score": 4.7}, {"tsb": -16})
        self.assertEqual(red["policy"], "progress")
        self.assertIn("overrode the gate", red["reason"])
        self.assertIn("-16.0", red["reason"])
        self.assertIn("high fatigue", red["reason"])
        self.assertNotIn("did not downgrade", red["reason"])
        for tsb in (-7.5, 0):
            with self.subTest(tsb=tsb):
                ok = compute_load_policy(overridden, {"score": 4.7},
                                         {"tsb": tsb})
                self.assertEqual(ok["policy"], "progress")
                self.assertIn("overrode the gate", ok["reason"])
                self.assertIn(f"{tsb:+.1f}", ok["reason"])
        gone = compute_load_policy(overridden, {"score": 4.7}, {"tsb": None})
        self.assertEqual(gone["policy"], "progress")
        self.assertIn("overrode the gate", gone["reason"])

    def test_read_trackers_override_path_ends_in_progress(self) -> None:
        # The path `--override-gate` takes: a Tier B call with strength TSB
        # -20 used to come back as a Tier D whose load_policy was `reduce`,
        # turning every next_dose entry into a deload under a "normal block".
        gate = recommendation(recovery={"score": 4.7, "drivers": []},
                              training_load={"tsb": -20})
        self.assertEqual((gate["tier"], gate["load_policy"]["policy"]),
                         ("B", "reduce"))
        out = apply_user_override(gate, {"score": 4.7}, {"tsb": -20})
        self.assertEqual((out["tier"], out["label"]), ("D", "green"))
        self.assertEqual(out["load_policy"]["policy"], "progress")
        self.assertIn("-20.0", out["load_policy"]["reason"])
        self.assertIn("overrode", out["load_policy"]["reason"])
        self.assertEqual(out["rationale"][0]["signal"], "user_override")
        # The gate's own rationale is kept behind it.
        self.assertGreater(len(out["rationale"]), 1)

    def test_a_call_that_is_already_normal_is_not_overridden(self) -> None:
        green = recommendation()
        self.assertIs(apply_user_override(green, {"score": 7.2}, {"tsb": 0}),
                      green)

    def test_the_policy_names_its_inputs(self) -> None:
        lp = recommendation(recovery={"score": 7.2, "drivers": []},
                            training_load={"tsb": -7.5})["load_policy"]
        self.assertEqual((lp["tier"], lp["tsb_band"], lp["strength_tsb"],
                          lp["recovery_available"]),
                         ("D", "carrying_load", -7.5, True))
        self.assertIn("(carrying load)", lp["reason"])

    def test_a_missing_recovery_score_is_a_named_data_gap(self) -> None:
        lp = recommendation(recovery={"score": None, "drivers": []},
                            training_load={"tsb": 3})["load_policy"]
        self.assertFalse(lp["recovery_available"])
        self.assertIsNone(lp["recovery_score"])
        self.assertIn("recovery score unavailable", lp["reason"])
        self.assertIn("strength TSB alone", lp["reason"])

    def test_a_missing_tsb_is_named_too(self) -> None:
        lp = recommendation(training_load={"tsb": None})["load_policy"]
        self.assertIn("strength TSB unavailable", lp["reason"])

    def test_over_recovered_on_tsb_alone_is_presented_as_a_data_gap(self) -> None:
        rec = recommendation(recovery={"score": None, "drivers": []},
                             training_load={"tsb": 10.5})
        self.assertEqual((rec["tier"], rec["label"]), ("E", "over_recovered"))
        self.assertIn("Recovery data is missing", rec["headline"])
        self.assertNotIn("you've been over-recovered", rec["headline"])
        # TSB is what put the day in Tier E, so it leads; the data gap
        # follows. `compute_tier_history` reads rationale[0] as the
        # dominant signal.
        self.assertEqual([r["signal"] for r in rec["rationale"]],
                         ["tsb", "recovery_unavailable"])

    def test_the_tier_history_names_tsb_as_the_dominant_signal_of_tier_e(self) -> None:
        from unittest import mock

        from workout_coach.lib.health_session_rec import compute_tier_history
        today = date(2026, 10, 14)
        with mock.patch("workout_coach.lib.health_session_rec.recovery_score",
                        return_value={"score": None, "drivers": []}), \
                mock.patch("workout_coach.lib.cardio.training_load_summary",
                           return_value={"tsb": 12.0}), \
                mock.patch("workout_coach.lib.cardio.compute_acwr",
                           return_value={}):
            hist = compute_tier_history(
                days=1, today_d=today, health_all=[], monthly_sessions=[],
                weekly_volume={}, sleep_nights_all=[],
                sleep_regularity_today={}, sleep_summary_today={},
                estimated_1rm={}, hr_at_volume_divergence={}, deloads=[],
                auto_deload_candidates=[], capabilities={},
                estimated_max_hr=190, estimated_rest_hr=55)
        self.assertEqual(
            hist, [{"date": "2026-10-14", "tier": "E",
                    "label": "over_recovered", "dominant_signal": "tsb"}])

    def test_over_recovered_with_a_real_score_keeps_its_call(self) -> None:
        rec = recommendation(training_load={"tsb": 10.5})
        self.assertIn("you've been over-recovered", rec["headline"])

    def test_below_the_floor_is_not_called_green(self) -> None:
        rec = recommendation(recovery={"score": 5.0, "drivers": []},
                             training_load={"tsb": 0})
        self.assertEqual(rec["tier"], "D")
        note = rec["rationale"][0]["note"]
        self.assertNotIn("green", note.replace("green line", ""))
        self.assertIn("under the 5.5 green line", note)
        self.assertIn("under the 5.5 green line", rec["load_policy"]["reason"])

    def test_at_or_above_the_floor_is_green(self) -> None:
        rec = recommendation(recovery={"score": 5.5, "drivers": []})
        self.assertIn("green", rec["rationale"][0]["note"])


class TierCVolumeTextTests(unittest.TestCase):
    """The payload text and the validator enforce the SAME cut."""

    def test_the_text_states_the_scale_the_validator_applies(self) -> None:
        from workout_coach.lib.constants import SESSION_GATE_THRESHOLDS as T
        from workout_coach.lib.render_validators import tier_budget_by_index
        rec = recommendation(recovery={"score": 3.5, "drivers": []})
        scale = T["tier_c_session_budget_scale"]
        text = rec["substitute"]["prescription"]
        self.assertIn(f"x{scale:g}", text)
        self.assertNotIn("25%", text)
        self.assertNotIn("secondary", text)
        budget = tier_budget_by_index(rec, 30)
        self.assertEqual(budget(0), round(30 * scale))
        self.assertEqual(budget(rec["expected_rebound_by_session"]), 30)


if __name__ == "__main__":
    unittest.main()
