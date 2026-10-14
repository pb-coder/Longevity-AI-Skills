"""Double progression from the log: ``progression.build_next_dose``.

The failure this pins: a lift sat at one weight for fifteen sessions while
every plan widened its rep range (8-10, then 10-12, then 12-14), because the
bump was gated behind prose thresholds the code never used and the fallback
under "hold" had no ceiling. The load decision now lives in one function that
reads the log, the range in force and the gate's ``load_policy``.

Also here: the load-based stall count (``strength.load_stall_sessions``),
which replaced an e1RM-flatness count that read rising reps at an unchanged
weight as progress, and the gym-change exemption for free weights.

Every fixture is synthetic and written in this file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from workout_coach.lib.adherence import parse_plan
from workout_coach.lib.blocks import load_pattern_catalog
from workout_coach.lib.constants import (
    REP_CEILING_RANGE,
    RP_DIRECT_SET_LANDMARKS,
)
from workout_coach.lib.extract import load_exercises_db
from workout_coach.lib.progression import build_next_dose
from workout_coach.lib.strength import (
    estimated_1rm,
    exercise_class,
    load_stall_sessions,
    session_history,
)

SKILLS_ROOT = Path(__file__).resolve().parents[1]
_DB = load_exercises_db(SKILLS_ROOT / "shared" / "exercises-database.md")
_CATALOG = load_pattern_catalog(_DB)

BENCH = "Dumbbell Flat Bench Press"
TODAY = date(2026, 10, 14)

PROGRESS = {"policy": "progress", "reason": "Tier D (green)"}
REDUCE = {"policy": "reduce", "reason": "Tier B (reactive_deload)"}


def sets(day: str, exercise: str, kg: float, reps, notes=None) -> list[dict]:
    """One row per entry of ``reps``, all at ``kg`` (or a list of loads)."""
    loads = kg if isinstance(kg, (list, tuple)) else [kg] * len(reps)
    return [{"date": day, "exercise": exercise, "kg": k, "reps": r,
             "notes": notes if i == 0 else None}
            for i, (k, r) in enumerate(zip(loads, reps))]


def plan(day: str, *bullets: str) -> dict:
    body = "".join(f"- {b}\n" for b in bullets)
    return parse_plan(f"## Workout 1: UPPER A\n{body}", day, _DB)


def dose(rows, plans=(), block=None, policy=PROGRESS, today=TODAY,
         deloads=()) -> dict:
    return build_next_dose(rows, _CATALOG, list(plans), block, policy, today,
                           deload_dates=list(deloads))


def entry(out: dict, exercise: str) -> dict:
    found = [e for e in out["exercises"] if e["exercise"] == exercise]
    assert len(found) == 1, (exercise, [e["exercise"] for e in out["exercises"]])
    return found[0]


class TopOfRangeAddsLoadTests(unittest.TestCase):
    def test_every_set_at_the_top_adds_the_increment_and_resets_the_range(self):
        rows = sets("2026-10-03", BENCH, 44, [12, 12, 12, 12])
        out = dose(rows, [plan("2026-10-02", f"{BENCH}: 44kgx10-12 /// 44kgx10-12")])
        e = entry(out, BENCH)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("add_load", 48.0, "10-12"))
        self.assertIn("top of 10-12", e["basis"])
        self.assertEqual(e["range_from"], "plan 2026-10-02")

    def test_the_increment_is_the_equipments(self):
        cases = [
            ("Barbell Back Squat", 90, [8, 8, 8], "8", 92.5),         # BB
            ("Cable Lat Pulldown", 65, [12, 12, 12], "10-12", 67.5),  # Cable
            ("Seated Row Machine", 70, [10, 10, 10], "8-10", 75.0),   # Machine
            (BENCH, 44, [10, 10, 10], "8-10", 48.0),                  # 2 DB
            ("Dumbbell Row", 24, [10, 10, 10], "8-10", 26.0),         # 1 DB
        ]
        for name, kg, reps, rng, expected in cases:
            with self.subTest(name):
                out = dose(sets("2026-10-03", name, kg, reps),
                           [plan("2026-10-02", f"{name}: {kg}kgx{rng}")])
                e = entry(out, name)
                self.assertEqual((e["action"], e["load_kg"]),
                                 ("add_load", expected))

    def test_the_new_load_is_on_the_old_loads_grid_not_absolute_multiples(self):
        # A cable stack that reads 36.25 steps to 38.75; rounding to a
        # multiple of 2.5 would land it on 37.5 or 40.
        name = "Cable Shrug"
        out = dose(sets("2026-10-09", name, 36.25, [18, 18]),
                   [plan("2026-10-02", f"{name}: 36.25kgx16-18")])
        self.assertEqual(entry(out, name)["load_kg"], 38.75)

    def test_short_of_the_top_keeps_the_load_and_asks_for_reps(self):
        rows = sets("2026-10-03", BENCH, 44, [12, 12, 12, 10])
        out = dose(rows, [plan("2026-10-02", f"{BENCH}: 44kgx10-12")])
        e = entry(out, BENCH)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("add_reps", 44.0, "10-12"))

    def test_a_range_is_judged_by_the_plan_the_session_followed(self):
        # The later plan widened the range to 12-14. That is a guess about
        # the next session and says nothing about whether this one earned
        # a bump; the 10-12 the athlete actually followed does.
        rows = sets("2026-10-03", BENCH, 44, [12, 12, 12, 12])
        plans = [plan("2026-10-02", f"{BENCH}: 44kgx10-12"),
                 plan("2026-10-10", f"{BENCH}: 44kgx12-14")]
        e = entry(dose(rows, plans), BENCH)
        self.assertEqual((e["action"], e["rep_range"]), ("add_load", "10-12"))
        self.assertEqual(e["range_from"], "plan 2026-10-02")

    def test_a_plan_dated_today_or_later_is_ignored(self):
        rows = sets("2026-10-03", BENCH, 44, [12, 12, 12, 12])
        plans = [plan("2026-10-02", f"{BENCH}: 44kgx10-12"),
                 plan("2026-10-14", f"{BENCH}: 44kgx6-8")]
        self.assertEqual(entry(dose(rows, plans), BENCH)["rep_range"], "10-12")


class CeilingTests(unittest.TestCase):
    def test_a_compound_range_above_12_resets_to_the_ceiling_range(self):
        rows = sets("2026-10-03", BENCH, 44, [12, 12, 12, 12])
        out = dose(rows, [plan("2026-10-02", f"{BENCH}: 44kgx12-14")])
        e = entry(out, BENCH)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("add_load", 48.0, "10-12"))
        self.assertIn("compound ceiling of 12", e["basis"])

    def test_an_isolation_range_above_20_resets_to_15_20(self):
        name = "Dumbbell Standing Calf Raise"
        out = dose(sets("2026-10-05", name, 32, [26, 26, 26]),
                   [plan("2026-10-02", f"{name}: 32kgx24-26")])
        e = entry(out, name)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("add_load", 36.0, "15-20"))

    def test_the_ceiling_is_not_a_free_bump_when_the_reps_were_missed(self):
        # Prescribed 14-16 on a compound, managed 10: the lift has not
        # outgrown the load, it was asked for reps it never had.
        name = "Cable Seated Row"
        out = dose(sets("2026-10-03", name, 50, [10, 10, 10]),
                   [plan("2026-10-02", f"{name}: 50kgx14-16")])
        e = entry(out, name)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("add_reps", 50.0, "10-12"))

    def test_the_ceiling_ranges_are_the_ones_named_in_constants(self):
        self.assertEqual(REP_CEILING_RANGE,
                         {"compound": (10, 12), "isolation": (15, 20)})

    def test_the_class_comes_from_the_catalog(self):
        self.assertEqual(exercise_class(BENCH, _CATALOG), "compound")
        self.assertEqual(exercise_class("Dumbbell Fly", _CATALOG), "isolation")
        self.assertIsNone(exercise_class("Not A Real Lift", _CATALOG))


class WorkingLoadTests(unittest.TestCase):
    def test_one_heavier_set_is_not_the_load_the_session_was_built_on(self):
        name = "Cable Standing Calf Raise"
        rows = sets("2026-10-09", name, [40, 40, 43.75], [26, 26, 22])
        out = dose(rows, [plan("2026-10-02", f"{name}: 40kgx15-20")])
        e = entry(out, name)
        # Judged on the two sets at 40, and the bump is from THAT load: the
        # lone 43.75 set is a top set, not the working load, so it does not
        # set the floor of the next dose (40 + 2.5, not 43.75).
        self.assertEqual((e["action"], e["load_kg"]), ("add_load", 42.5))

    def test_a_session_with_no_load_carrying_two_sets_cannot_earn_a_bump(self):
        name = "Dumbbell Row"
        rows = sets("2026-10-09", name, [20, 22, 24], [12, 12, 12])
        out = dose(rows, [plan("2026-10-02", f"{name}: 22kgx10-12")])
        self.assertEqual(entry(out, name)["action"], "add_reps")


class LoadPolicyTests(unittest.TestCase):
    ROWS = sets("2026-10-03", BENCH, 44, [12, 12, 12, 12])
    PLANS = [plan("2026-10-02", f"{BENCH}: 44kgx10-12")]

    def test_progress_gives_the_earned_bump(self):
        e = entry(dose(self.ROWS, self.PLANS, policy=PROGRESS), BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("add_load", 48.0))

    def test_progress_still_asks_for_reps_where_nothing_was_earned(self):
        rows = sets("2026-10-03", BENCH, 44, [10, 10, 10, 10])
        e = entry(dose(rows, self.PLANS, policy=PROGRESS), BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 44.0))


    def test_reduce_is_a_deload_that_holds_the_load(self):
        out = dose(self.ROWS, self.PLANS, policy=REDUCE)
        e = entry(out, BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("reduce", 44.0))
        self.assertEqual(out["load_policy"], "reduce")
        self.assertIn("load policy is reduce", e["basis"])


class IncrementTests(unittest.TestCase):
    """The step a lift takes: its own most common jump, else the equipment's."""

    PLAN = "2026-09-01"

    def _next(self, name, loads, reps=12, rng="10-12", notes=None, deloads=()):
        """Sessions at ``loads`` in turn, 4 days apart; the last is the
        reference and every set of it is at the top of the range."""
        rows = []
        for i, kg in enumerate(loads):
            day = f"2026-09-{1 + 4 * i:02d}"
            rows += sets(day, name, kg, [reps] * 3,
                         notes=(notes or {}).get(i))
        out = dose(rows, [plan(self.PLAN, f"{name}: {loads[-1]}kgx{rng}")],
                   deloads=deloads, today=date(2026, 9, 28))
        return entry(out, name)

    def test_two_dumbbell_lifts_step_four_kg_from_their_own_log(self):
        e = self._next(BENCH, [36, 40, 44])
        self.assertEqual((e["action"], e["load_kg"]), ("add_load", 48.0))
        self.assertEqual(e["increment_kg"], 4.0)
        self.assertIn("log: 4kg in 2 of 2", e["increment_basis"])

    def test_a_single_dumbbell_lift_steps_two_kg_from_its_own_log(self):
        e = self._next("Dumbbell Row", [14, 16, 18, 20])
        self.assertEqual((e["load_kg"], e["increment_kg"]), (22.0, 2.0))

    def test_the_log_beats_the_equipment_table(self):
        # A machine this gym steps 2.5kg (a half plate), not the 5 of the
        # table; a single dumbbell steps 4kg, not the 2 of the table.
        m = self._next("Seated Row Machine", [60, 62.5, 65], reps=10,
                       rng="8-10")
        self.assertEqual((m["load_kg"], m["increment_kg"]), (67.5, 2.5))
        d = self._next("Dumbbell Row", [12, 16, 20])
        self.assertEqual((d["load_kg"], d["increment_kg"]), (24.0, 4.0))

    def test_a_logged_two_kg_step_on_a_two_dumbbell_lift_is_used_as_is(self):
        # Light dumbbells really do come in 1 kg-a-hand steps, so a majority
        # step of 2 kg in the log is a step, not noise: the log beats the
        # table's 4 kg.
        e = self._next("Dumbbell Lateral Raise", [14, 16, 18], reps=20,
                       rng="15-20")
        self.assertEqual((e["load_kg"], e["increment_kg"]), (20.0, 2.0))
        self.assertIn("log: 2kg in 2 of 2", e["increment_basis"])
        self.assertNotIn("raised", e["increment_basis"])
        # The bench-shaped case: 2kg again and again between two loads.
        b = self._next(BENCH, [50, 52, 50, 52])
        self.assertEqual((b["load_kg"], b["increment_kg"]), (54.0, 2.0))

    def test_the_four_kg_and_two_kg_values_are_only_the_fallback(self):
        from workout_coach.lib.constants import equipment_increment_kg
        self.assertEqual(equipment_increment_kg("DB", BENCH.lower()), 4.0)
        self.assertEqual(equipment_increment_kg("DB", "dumbbell row"), 2.0)
        # No majority in the log: the table stands and says why.
        e = self._next("Dumbbell Rear Delt Fly", [8, 10, 13, 17], reps=20,
                       rng="15-20")
        self.assertEqual(e["increment_kg"], 4.0)
        self.assertIn("equipment table", e["increment_basis"])
        # The clamp is gone from the constants too.
        import workout_coach.lib.constants as constants
        self.assertFalse(hasattr(constants, "minimum_increment_kg"))
        # A single dumbbell and a cable keep their small learned step.
        r = self._next("Dumbbell Row", [14, 16, 18, 20])
        self.assertEqual(r["increment_kg"], 2.0)
        c = self._next("Cable Lateral Raise", [5, 6.25, 7.5, 8.75], reps=20,
                       rng="15-20")
        self.assertEqual(c["increment_kg"], 1.25)
        # A learned step above the table's is untouched.
        from workout_coach.lib.progression import observed_increment
        hist = [{"context_change": False, "top_load_kg": kg, "sets": 3,
                 "loads": [kg] * 3, "reps": [10] * 3}
                for kg in (20, 26, 32)]
        self.assertEqual(observed_increment(hist, 4.0)[0], 6)

    def test_the_most_common_jump_wins_and_a_tie_takes_the_smaller(self):
        e = self._next("Dumbbell Row", [8, 10, 12, 16, 18, 20])
        self.assertEqual(e["increment_kg"], 2.0)             # 2,2,4,2,2
        t = self._next("Dumbbell Row", [8, 10, 14, 16, 20])
        self.assertEqual(t["increment_kg"], 2.0)             # 2,4,2,4 tied

    def test_jumps_that_never_repeat_have_no_usual_step(self):
        # 2, 3, 4 kg: the smallest would be noise, not the step.
        e = self._next("Dumbbell Rear Delt Fly", [8, 10, 13, 17], reps=20,
                       rng="15-20")
        self.assertEqual((e["load_kg"], e["increment_kg"]), (21.0, 4.0))
        self.assertIn("all different sizes", e["increment_basis"])

    def test_fewer_than_two_jumps_falls_back_to_the_table_and_says_so(self):
        e = self._next(BENCH, [40, 44])
        self.assertEqual((e["load_kg"], e["increment_kg"]), (48.0, 4.0))
        self.assertIn("equipment table", e["increment_basis"])
        self.assertIn("1 usable load jump", e["increment_basis"])
        r = self._next("Dumbbell Row", [20, 22])
        self.assertEqual((r["load_kg"], r["increment_kg"]), (24.0, 2.0))
        b = self._next("Barbell Back Squat", [90, 92.5], reps=8, rng="8")
        self.assertEqual(b["increment_kg"], 2.5)
        m = self._next("Seated Row Machine", [70], reps=10, rng="8-10")
        self.assertEqual((m["load_kg"], m["increment_kg"]), (75.0, 5.0))

    def test_an_implausible_jump_is_not_a_step(self):
        # 25 -> 40 is a missed stretch of sessions or a change of
        # convention. Without it only one jump is left, so the table stands.
        e = self._next("Dumbbell Shrug", [25, 40, 44], reps=15, rng="12-15")
        self.assertEqual(e["increment_kg"], 4.0)
        self.assertIn("1 usable load jump", e["increment_basis"])

    def test_a_large_step_on_a_light_cable_is_plausible(self):
        # 5 -> 7.5 is +50% of the load but one stack plate.
        e = self._next("Cable Lateral Raise", [5, 7.5, 10, 12.5], reps=20,
                       rng="15-20")
        self.assertEqual(e["increment_kg"], 2.5)
        self.assertIn("3 of 3", e["increment_basis"])

    def test_gym_flagged_sessions_do_not_count_toward_the_step(self):
        note = "different gym and machine"
        # The flagged session's own load (another gym's stack: 30, 60) is not
        # a step of this one, and the sessions after it count.
        e = self._next("Cable Seated Row", [30, 50, 52.5, 55], notes={0: note})
        self.assertEqual(e["increment_kg"], 2.5)
        self.assertIn("2 of 2", e["increment_basis"])
        flagged = self._next("Cable Seated Row", [60, 50, 52.5, 55],
                             notes={0: note})
        self.assertEqual(flagged["increment_kg"], 2.5)
        self.assertIn("2 of 2", flagged["increment_basis"])

    def test_a_deload_session_does_not_count_toward_the_step(self):
        # 32 -> 36 is the climb back out of a deload (2026-09-05), not a
        # step: with it counted the log would show two jumps of 4.
        e = self._next(BENCH, [36, 32, 36, 40], deloads=["2026-09-05"])
        self.assertEqual(e["increment_kg"], 4.0)
        self.assertIn("equipment table: 1 usable load jump",
                      e["increment_basis"])
        counted = self._next(BENCH, [36, 32, 36, 40])
        self.assertIn("log: 4kg in 2 of 2", counted["increment_basis"])

    def test_the_single_dumbbell_set_is_explicit_and_small(self):
        from workout_coach.lib.constants import (
            SINGLE_DUMBBELL_LIFTS,
            equipment_increment_kg,
        )
        self.assertLessEqual(len(SINGLE_DUMBBELL_LIFTS), 10)
        # One arm at a time / one dumbbell by definition.
        self.assertIn("dumbbell kickback", SINGLE_DUMBBELL_LIFTS)
        self.assertIn("suitcase carry", SINGLE_DUMBBELL_LIFTS)
        for name in SINGLE_DUMBBELL_LIFTS:
            with self.subTest(name):
                meta = _CATALOG.get(name)
                self.assertIsNotNone(meta, f"{name} is not a catalog entry")
                self.assertEqual(meta["equipment"], "DB")
                self.assertEqual(equipment_increment_kg("DB", name), 2.0)
        self.assertEqual(equipment_increment_kg("DB", BENCH.lower()), 4.0)
        self.assertEqual(equipment_increment_kg("Cable", "x"), 2.5)
        self.assertEqual(equipment_increment_kg(None, "x"), 2.5)

    def test_the_derived_starting_loads_round_to_the_same_table(self):
        from workout_coach.lib.constants import LOAD_INCREMENT_KG
        self.assertEqual(LOAD_INCREMENT_KG["DB"], 4.0)

    def test_a_one_dumbbell_starting_load_rounds_to_two_kg(self):
        # `derived_starting_load` reads the same `equipment_increment_kg`, so
        # a one-dumbbell lift is not forced onto the two-dumbbell 4kg grid.
        from workout_coach.lib.blocks import derived_starting_load
        row = {"Dumbbell Row": {"current_e1rm_kg": 40.0,
                                "last_date": "2026-10-01"}}
        single = derived_starting_load("Dumbbell Row", row, _CATALOG, _DB)
        self.assertEqual(single["load_kg"], 26.0, single)   # 25.5; 24 or 28 on 4
        pair = derived_starting_load(
            "Dumbbell Incline Bench Press",
            {BENCH: {"current_e1rm_kg": 70.0, "last_date": "2026-10-01"}},
            _CATALOG, _DB)
        self.assertEqual(pair["load_kg"] % 4.0, 0.0, pair)


class GymChangeTests(unittest.TestCase):
    NOTE = "different gym and machine"

    def test_a_dumbbell_lift_on_a_gym_change_day_is_treated_normally(self):
        rows = sets("2026-10-03", BENCH, 44, [12, 12, 12, 12], notes=self.NOTE)
        out = dose(rows, [plan("2026-10-02", f"{BENCH}: 44kgx10-12")])
        self.assertEqual(entry(out, BENCH)["action"], "add_load")

    def test_a_cable_lift_is_judged_on_the_usual_gym(self):
        name = "Cable Overhead Tricep Extension"
        rows = (sets("2026-09-20", name, 17.5, [10, 10, 10])
                + sets("2026-10-03", name, 30, [12, 12, 12], notes=self.NOTE))
        out = dose(rows, [plan("2026-09-18", f"{name}: 17.5kgx10-12")])
        e = entry(out, name)
        # load_kg is the usual gym's: the flagged session is not the basis.
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 17.5))
        self.assertEqual(e["last_load_kg"], 17.5)
        self.assertIn("2026-09-20", e["last"])
        # The other gym's load rides beside it, as a number, either way.
        self.assertEqual(e["other_gym_load_kg"], 30.0)
        self.assertNotIn("comparable_load_kg", e)

    def test_the_other_gym_can_be_lower_and_is_omitted_when_equal(self):
        name = "Cable Seated Row"
        low = (sets("2026-09-20", name, 50, [10, 10, 10])
               + sets("2026-10-03", name, 36.25, [12, 12, 12], notes=self.NOTE))
        e = entry(dose(low, [plan("2026-09-18", f"{name}: 50kgx10-12")]), name)
        self.assertEqual((e["load_kg"], e["other_gym_load_kg"]), (50.0, 36.25))
        same = (sets("2026-09-20", name, 50, [10, 10, 10])
                + sets("2026-10-03", name, 50, [10, 10, 10], notes=self.NOTE))
        e = entry(dose(same, [plan("2026-09-18", f"{name}: 50kgx10-12")]), name)
        self.assertNotIn("other_gym_load_kg", e)

    def test_the_most_recent_flagged_load_is_the_other_gyms(self):
        name = "Cable Seated Row"
        rows = (sets("2026-09-14", name, 50, [10, 10, 10])
                + sets("2026-09-24", name, 30, [10, 10, 10], notes=self.NOTE)
                + sets("2026-10-01", name, 64, [10, 10, 10], notes=self.NOTE)
                + sets("2026-10-05", name, 52.5, [10, 10, 10]))
        e = entry(dose(rows, [plan("2026-09-12", f"{name}: 50kgx10-12")]), name)
        self.assertEqual((e["load_kg"], e["other_gym_load_kg"]), (52.5, 64.0))

    def test_a_lift_with_no_usual_gym_session_holds_and_says_so(self):
        name = "Cable Seated Row"
        rows = sets("2026-10-03", name, 30, [12, 12, 12], notes=self.NOTE)
        e = entry(dose(rows, [plan("2026-09-18", f"{name}: 30kgx10-12")]), name)
        self.assertEqual((e["action"], e["load_kg"]), ("hold", 30.0))
        self.assertIn("different gym or machine", e["basis"])
        self.assertNotIn("other_gym_load_kg", e)

    def test_free_weights_have_no_other_gym(self):
        rows = sets("2026-10-03", BENCH, 44, [12, 12, 12, 12], notes=self.NOTE)
        e = entry(dose(rows, [plan("2026-10-02", f"{BENCH}: 44kgx10-12")]),
                  BENCH)
        self.assertNotIn("other_gym_load_kg", e)

    def test_the_session_after_a_gym_change_progresses_normally(self):
        name = "Cable Overhead Tricep Extension"
        rows = (sets("2026-10-03", name, 30, [12, 12, 12], notes=self.NOTE)
                + sets("2026-10-07", name, 30, [12, 12, 12]))
        out = dose(rows, [plan("2026-10-02", f"{name}: 30kgx10-12")])
        self.assertEqual(entry(out, name)["action"], "add_load")


class HistoryTests(unittest.TestCase):
    def test_a_lift_with_nothing_logged_gets_no_number(self):
        block = {"slots": [{"exercise": "Barbell Back Squat",
                            "dose": {"rep_lo": 8, "rep_hi": 10}}]}
        out = dose([], block=block)
        e = entry(out, "Barbell Back Squat")
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("no_history", None, "8-10"))
        self.assertIn("rotation_candidates", e["basis"])

    def test_a_lift_not_worked_for_a_month_is_a_reentry_not_a_bump(self):
        rows = sets("2026-09-08", BENCH, 44, [12, 12, 12, 12])
        out = dose(rows, [plan("2026-09-02", f"{BENCH}: 44kgx10-12")])
        e = entry(out, BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("hold", 44.0))
        self.assertIn("36 days ago", e["basis"])

    def test_a_deload_session_is_not_the_reference(self):
        rows = (sets("2026-10-01", BENCH, 44, [12, 12, 12, 12])
                + sets("2026-10-08", BENCH, 30, [8, 8]))
        out = dose(rows, [plan("2026-09-28", f"{BENCH}: 44kgx10-12")],
                   deloads=["2026-10-08"])
        e = entry(out, BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("add_load", 48.0))

    def test_no_range_on_record_says_so_instead_of_inventing_one(self):
        rows = sets("2026-10-03", BENCH, 44, [12, 12, 12, 12])
        e = entry(dose(rows), BENCH)
        self.assertEqual((e["action"], e["load_kg"], e.get("rep_range")),
                         ("hold", 44.0, None))
        self.assertIn("no rep range is on record", e["basis"])

    def test_the_blocks_dose_is_the_range_of_last_resort(self):
        rows = sets("2026-10-03", BENCH, 44, [12, 12, 12, 12])
        block = {"slots": [{"exercise": BENCH,
                            "dose": {"rep_lo": 10, "rep_hi": 12}}]}
        e = entry(dose(rows, block=block), BENCH)
        self.assertEqual((e["action"], e["range_from"]), ("add_load", "block"))

    def test_unloaded_work_is_listed_not_given_a_dose(self):
        rows = sets("2026-10-03", "Plank", 0, [0, 0])
        rows[0]["duration_min"] = 1.0
        rows[1]["duration_min"] = 1.0
        rows += sets("2026-10-03", "Pull-Up", 0, [8, 8, 8])
        out = dose(rows)
        self.assertEqual([e["exercise"] for e in out["exercises"]], [])
        self.assertEqual(
            out["uncovered"]["exercises"],
            [{"exercise": "Plank", "last_prescription": None},
             {"exercise": "Pull-Up", "last_prescription": None}])

    def test_stall_and_sessions_at_load_ride_on_the_entry(self):
        rows = []
        for i, day in enumerate(["2026-09-20", "2026-09-24", "2026-09-28",
                                 "2026-10-02", "2026-10-06"]):
            rows += sets(day, BENCH, 44, [10, 10, 10, 10])
        e = entry(dose(rows, [plan("2026-09-18", f"{BENCH}: 44kgx8-12")]),
                  BENCH)
        self.assertEqual(e["sessions_at_load"], 5)
        self.assertEqual(e["stalled_sessions"], 4)


def _hist(*sessions, ctx=()):
    """``(date, [reps])`` pairs at one load, as `session_history` records."""
    return [{"date": d, "exercise": "x", "sets": len(r), "loads": [44.0] * len(r),
             "reps": r, "top_load_kg": 44.0, "reps_at_top": r,
             "context_change": d in ctx}
            for d, r in sessions]


class LoadStallTests(unittest.TestCase):
    def test_reps_that_keep_arriving_are_not_a_stall(self):
        h = _hist(("2026-09-01", [6, 6]), ("2026-09-04", [7, 7]),
                  ("2026-09-08", [8, 8]))
        self.assertEqual(load_stall_sessions(h, set(), 12), 0)

    def test_reps_that_stop_arriving_at_one_load_count_each_session(self):
        h = _hist(("2026-09-01", [8, 8]), ("2026-09-04", [8, 8]),
                  ("2026-09-08", [8, 7]), ("2026-09-11", [8, 8]))
        self.assertEqual(load_stall_sessions(h, set(), 12), 3)

    def test_at_the_ceiling_further_reps_are_not_credited(self):
        h = _hist(("2026-09-01", [10, 10]), ("2026-09-04", [12, 12]),
                  ("2026-09-08", [13, 13]), ("2026-09-11", [14, 14]))
        # 12 was the ceiling: the 13 and the 14 are not progress.
        self.assertEqual(load_stall_sessions(h, set(), 12), 2)
        # With no ceiling known, they are.
        self.assertEqual(load_stall_sessions(h, set(), None), 0)

    def test_a_new_load_starts_a_new_run(self):
        h = _hist(("2026-09-01", [8, 8]), ("2026-09-04", [8, 8]))
        h.append({**h[0], "date": "2026-09-08", "top_load_kg": 46.0,
                  "reps_at_top": [8, 8]})
        self.assertEqual(load_stall_sessions(h, set(), 12), 0)

    def test_a_deload_between_two_sessions_ends_the_run(self):
        h = _hist(("2026-09-01", [8, 8]), ("2026-09-04", [8, 8]),
                  ("2026-09-11", [8, 8]))
        self.assertEqual(load_stall_sessions(h, {"2026-09-07"}, 12), 0)

    def test_a_gym_tagged_session_is_not_comparable(self):
        h = _hist(("2026-09-01", [8, 8]), ("2026-09-04", [8, 8]),
                  ("2026-09-08", [8, 8]), ctx={"2026-09-04"})
        self.assertEqual(load_stall_sessions(h, set(), 12), 0)

    def test_rising_reps_at_an_unchanged_weight_were_invisible_to_e1rm(self):
        """The regression this replaced: Epley credits the extra reps."""
        rows = []
        for day, reps in (("2026-09-01", 8), ("2026-09-04", 9),
                          ("2026-09-08", 10), ("2026-09-11", 12),
                          ("2026-09-15", 12), ("2026-09-18", 12)):
            rows += sets(day, BENCH, 44, [reps] * 3)
        out = estimated_1rm(rows, catalog=_CATALOG)[BENCH]
        # Two sessions with nothing left to gain at the 12-rep ceiling.
        self.assertEqual(out["stalled_sessions"], 2)


class GymChangeE1rmTests(unittest.TestCase):
    NOTE = "different gym and machine"

    def _rows(self, name):
        return (sets("2026-09-20", name, 20, [10, 10])
                + sets("2026-09-27", name, 20, [10, 10], notes=self.NOTE))

    def test_free_weights_are_not_excluded_by_a_gym_note(self):
        out = estimated_1rm(self._rows(BENCH), catalog=_CATALOG)[BENCH]
        self.assertEqual(out["context_change_excluded"], 0)

    def test_a_cable_still_is(self):
        name = "Cable Tricep Pushdown"
        out = estimated_1rm(self._rows(name), catalog=_CATALOG)[name]
        self.assertEqual(out["context_change_excluded"], 1)

    def test_without_a_catalog_the_old_behaviour_holds(self):
        out = estimated_1rm(self._rows(BENCH))[BENCH]
        self.assertEqual(out["context_change_excluded"], 1)

    def test_the_session_history_carries_the_same_flag(self):
        h = session_history(self._rows(BENCH), _CATALOG)["dumbbell flat bench press"]
        self.assertEqual([s["context_change"] for s in h], [False, False])
        c = session_history(self._rows("Cable Tricep Pushdown"),
                            _CATALOG)["cable tricep pushdown"]
        self.assertEqual([s["context_change"] for s in c], [False, True])


class StallConsumerTests(unittest.TestCase):
    """`stalled_sessions` now includes a lift parked at the top of its range
    waiting for weight. The bulk stop-signal quotes strength that is not
    climbing, so it must not read that count raw: five such lifts once
    turned a healthy bulk into "end now"."""

    @staticmethod
    def _lift(slope, stalled=6):
        return {"stalled_sessions": stalled, "current_e1rm_kg": 100.0,
                "best_e1rm_kg": 100.0, "slope_kg_per_4w": slope}

    def _signals(self, lifts):
        from workout_coach.lib.nutrition_phase import _detect_stop_signals
        return _detect_stop_signals("bulk", "on_track", 6.0, 0.25, lifts)

    def test_lifts_waiting_for_weight_are_not_a_stalled_bulk(self):
        lifts = {f"L{i}": self._lift(slope=3.0) for i in range(5)}
        self.assertEqual(self._signals(lifts), [])

    def test_lifts_that_are_flat_and_near_best_still_are(self):
        lifts = {f"L{i}": self._lift(slope=0.0) for i in range(3)}
        signals = self._signals(lifts)
        self.assertEqual(len(signals), 1)
        self.assertIn("3 compound lifts stalled", signals[0])


class ReentryAndShortfallLoadTests(unittest.TestCase):
    """A load the lifter cannot do is re-derived, never repeated."""

    CURL = "Incline Dumbbell Curl"

    def test_a_reentry_load_comes_from_the_best_set_at_the_bottom_of_the_range(self):
        # The reviewer's case: 4/4/5 at 32 kg, then `hold` at 32 kg for 10-12.
        # Best set 5 x 32 projects 37.3; at 10 reps that is 28.0, which is on
        # the 4 kg grid. Six weeks away: inside the 56 days, so no discount.
        rows = sets("2026-09-01", self.CURL, 32, [4, 4, 5])
        out = dose(rows, [plan("2026-08-25", f"{self.CURL}: 24kgx10-12")])
        e = entry(out, self.CURL)
        self.assertEqual((e["action"], e["load_kg"]), ("hold", 28.0))
        self.assertEqual((e["last_load_kg"], e["last_reps"]), (32.0, [4, 4, 5]))
        self.assertIn("e1RM of 37.3kg", e["basis"])
        self.assertIn("rounds that to the nearest", e["basis"])

    def test_it_rounds_to_the_nearest_step_on_the_lifts_own_grid(self):
        # 36.25 logged on a cable that steps 2.5: the result is 36.25 - k*2.5,
        # not a multiple of 2.5 the stack does not have.
        name = "Cable Shrug"
        rows = sets("2026-09-01", name, 36.25, [8, 8, 9])
        e = entry(dose(rows, [plan("2026-08-25", f"{name}: 36.25kgx16-18")]),
                  name)
        # 9 x 36.25 -> e1RM 47.1 -> 16 reps -> 30.7 -> nearest of the grid
        # 36.25 - 2.5k is 31.25.
        self.assertEqual(e["load_kg"], 31.25)
        self.assertAlmostEqual((36.25 - e["load_kg"]) / 2.5 % 1, 0, places=6)

    def test_a_reentry_that_could_do_the_range_is_not_raised(self):
        # 12/12/12/12 at 44 for 10-12 is within reach: repeat, do not bump.
        rows = sets("2026-09-08", BENCH, 44, [12, 12, 12, 12])
        e = entry(dose(rows, [plan("2026-09-02", f"{BENCH}: 44kgx10-12")]),
                  BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("hold", 44.0))
        self.assertNotIn("e1RM", e["basis"])

    def test_one_session_below_the_range_keeps_the_load(self):
        # A bench at 52 for a 10-12, best set under 10. One bad session does not
        # cut the weight; the basis says the next miss at 52 does.
        rows = sets("2026-10-06", BENCH, 52, [9, 8, 6])
        e = entry(dose(rows, [plan("2026-10-05", f"{BENCH}: 52kgx10-12")]),
                  BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 52.0))
        self.assertIn("same load", e["basis"])
        self.assertIn("next miss at 52kg drops it", e["basis"])
        self.assertNotIn("e1RM", e["basis"])

    def test_two_sessions_below_the_range_at_one_load_lower_it(self):
        # 7 x 52 -> e1RM 64.1 -> 10 reps 48.1: one whole 4 kg step down.
        rows = (sets("2026-09-29", BENCH, 52, [7, 6, 5])
                + sets("2026-10-06", BENCH, 52, [7, 6, 5]))
        e = entry(dose(rows, [plan("2026-09-28", f"{BENCH}: 52kgx10-12"),
                              plan("2026-10-05", f"{BENCH}: 52kgx10-12")]),
                  BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 48.0))
        self.assertIn("last two sessions at 52kg", e["basis"])
        self.assertIn("e1RM", e["basis"])
        self.assertIn("to the nearest", e["basis"])
        self.assertNotIn("same load", e["basis"])

    def test_a_small_shortfall_twice_keeps_the_load_and_says_so(self):
        # A 10 kg cable lateral, 11/11/11 against a bottom of 12, twice: the
        # best set projects 9.8 kg for 12, under half of the 2.5 kg step
        # away, so the lift stays at 10 (not 7.5) and the basis says so.
        name = "Cable Lateral Raise"
        rows = (sets("2026-09-29", name, 10, [11, 11, 11])
                + sets("2026-10-06", name, 10, [11, 11, 11]))
        e = entry(dose(rows, [plan("2026-09-28", f"{name}: 10kgx12-15"),
                              plan("2026-10-05", f"{name}: 10kgx12-15")]),
                  name)
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 10.0))
        self.assertIn("last two sessions at 10kg", e["basis"])
        self.assertIn("back to the last load: 10kg stays", e["basis"])
        self.assertIn("stall rule", e["basis"])

    def test_a_larger_shortfall_twice_drops_to_the_nearest_step(self):
        # 5/5/5 at 10 kg against 12: the best set projects 8.3 kg, which is
        # nearer 7.5 than 10, and never above the last load.
        name = "Cable Lateral Raise"
        rows = (sets("2026-09-29", name, 10, [5, 5, 5])
                + sets("2026-10-06", name, 10, [5, 5, 5]))
        e = entry(dose(rows, [plan("2026-09-28", f"{name}: 10kgx12-15"),
                              plan("2026-10-05", f"{name}: 10kgx12-15")]),
                  name)
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 7.5))

    def test_the_earlier_miss_must_be_at_the_same_load(self):
        # Missed at 48, then moved to 52 and missed once: one miss at 52.
        rows = (sets("2026-09-29", BENCH, 48, [9, 8, 6])
                + sets("2026-10-06", BENCH, 52, [9, 8, 6]))
        e = entry(dose(rows, [plan("2026-09-28", f"{BENCH}: 48kgx10-12"),
                              plan("2026-10-05", f"{BENCH}: 52kgx10-12")]),
                  BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 52.0))

    def test_a_miss_after_a_session_inside_the_range_keeps_the_load(self):
        rows = (sets("2026-09-29", BENCH, 52, [11, 10, 9])
                + sets("2026-10-06", BENCH, 52, [9, 8, 6]))
        e = entry(dose(rows, [plan("2026-09-28", f"{BENCH}: 52kgx10-12")]),
                  BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 52.0))

    def test_a_gym_tagged_session_does_not_count_as_the_earlier_miss(self):
        # A cable at another gym: its session is not comparable, so the
        # usual-gym history has one miss only.
        name = "Cable Lat Pulldown"
        rows = (sets("2026-09-29", name, 65, [7, 6, 5],
                     notes="different gym")
                + sets("2026-10-06", name, 65, [7, 6, 5]))
        e = entry(dose(rows, [plan("2026-09-28", f"{name}: 65kgx10-12")]),
                  name)
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 65.0))

    def test_a_single_number_prescription_is_the_top_not_the_bottom(self):
        # The 2026-10-05 plan wrote a bare "12". Read as a range with no
        # room, 10/8/6 "missed the bottom"; read as the top of 10-12 the
        # best set is 10, inside it.
        rows = sets("2026-10-06", BENCH, 52, [10, 8, 6])
        e = entry(dose(rows, [plan("2026-10-05", f"{BENCH}: 52kgx12")]), BENCH)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("add_reps", 52.0, "10-12"))
        self.assertIn("single number", e["basis"])
        self.assertNotIn("drops it", e["basis"])

    def test_a_single_number_at_the_top_still_earns_the_bump(self):
        rows = sets("2026-10-06", BENCH, 52, [12, 12, 12])
        e = entry(dose(rows, [plan("2026-10-05", f"{BENCH}: 52kgx12")]), BENCH)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("add_load", 56.0, "10-12"))

    def test_a_bare_number_is_n_minus_2_to_n_on_any_lift(self):
        # (exercise, last session reps, bare target, range, action)
        cases = [
            ("Barbell Back Squat", [5, 5, 5], 5, "3-5", "add_load"),
            ("Barbell Back Squat", [7, 7, 7], 8, "6-8", "add_reps"),
            ("Cable Lateral Raise", [11, 11, 10], 12, "10-12", "add_reps"),
            ("Cable Lateral Raise", [12, 12, 12], 12, "10-12", "add_load"),
        ]
        for name, reps, n, rng, action in cases:
            with self.subTest(name=name, n=n):
                rows = sets("2026-10-06", name, 20, reps)
                e = entry(dose(rows, [plan("2026-10-05",
                                           f"{name}: 20kgx{n}")]), name)
                self.assertEqual((e["action"], e["rep_range"]), (action, rng))
                self.assertIn("single number", e["basis"])
                self.assertNotIn("drops it", e["basis"])
                self.assertEqual(e["range_from"],
                                 f"plan 2026-10-05; bare {n} read as {rng}")

    def test_a_bare_one_stays_one_rep_and_a_range_is_untouched(self):
        rows = sets("2026-10-06", "Barbell Back Squat", 100, [1, 1, 1])
        e = entry(dose(rows, [plan("2026-10-05", "Barbell Back Squat: 100kgx1")]),
                  "Barbell Back Squat")
        self.assertEqual(e["rep_range"], "1")
        rows = sets("2026-10-06", "Barbell Back Squat", 100, [6, 6, 6])
        e = entry(dose(rows, [plan("2026-10-05",
                                   "Barbell Back Squat: 100kgx6-8")]),
                  "Barbell Back Squat")
        self.assertEqual((e["rep_range"], e["range_from"]),
                         ("6-8", "plan 2026-10-05"))

    def test_a_reentry_still_lowers_on_one_session(self):
        rows = sets("2026-09-01", self.CURL, 32, [4, 4, 5])
        e = entry(dose(rows, [plan("2026-08-25", f"{self.CURL}: 24kgx10-12")]),
                  self.CURL)
        self.assertEqual((e["action"], e["load_kg"]), ("hold", 28.0))

    def test_one_weak_set_in_the_range_does_not_trigger_it(self):
        # The best set reached the bottom of 10-12: same load, more reps.
        rows = sets("2026-10-06", BENCH, 52, [11, 10, 8])
        e = entry(dose(rows, [plan("2026-10-05", f"{BENCH}: 52kgx10-12")]),
                  BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 52.0))
        self.assertIn("same load", e["basis"])

    def test_a_reentry_with_no_range_on_record_gets_the_range_it_was_done_in(self):
        # The Shoulder Press Machine case: 55 kg x 10/10/10/7, 90 days ago,
        # no plan or block ever prescribed a range. It used to `hold` at
        # 55 kg with no range, while rotation_candidates priced the same lift
        # at 45. The median of the last session's reps is 10, so 8-10 stands
        # in; the best set at 8 reps is 57.9 kg, x 0.85 = 49.2, rounded to
        # the nearest 5 kg step: 50.
        name = "Shoulder Press Machine"
        out = dose(sets("2026-07-16", name, 55, [10, 10, 10, 7]))
        e = entry(out, name)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("hold", 50.0, "8-10"))
        self.assertEqual(e["range_from"],
                         "derived from last session reps (median 10)")
        for part in ("90 days ago", "e1RM of 73.3kg", "0.85", "8-10",
                     "median of 10 reps", "nearest"):
            self.assertIn(part, e["basis"])

    def test_the_default_range_is_the_first_ladder_range_that_holds_the_median(self):
        from workout_coach.lib.progression import (REP_RANGE_LADDER,
                                                   _ladder_range)
        self.assertEqual(REP_RANGE_LADDER,
                         ((6, 8), (8, 10), (10, 12), (12, 15), (15, 20)))
        cases = [
            # (median reps, class, expected)
            (5, "compound", (6, 8)), (8, "compound", (6, 8)),
            (10, "compound", (8, 10)), (11, "compound", (10, 12)),
            (12, "compound", (10, 12)),
            # a compound is capped at 12: 15 reps is endurance, not a range
            (15, "compound", REP_CEILING_RANGE["compound"]),
            (10, "isolation", (8, 10)), (12, "isolation", (10, 12)),
            (15, "isolation", (12, 15)), (18, "isolation", (15, 20)),
            (30, "isolation", REP_CEILING_RANGE["isolation"]),
        ]
        for median, cls, expected in cases:
            with self.subTest(median=median, cls=cls):
                self.assertEqual(_ladder_range(median, cls), expected)

    def test_a_reentry_range_follows_the_median_of_the_last_session(self):
        # 15 reps a set on an isolation lift: 12-15, not the 15-20 ceiling.
        name = "Dumbbell Fly"
        e = entry(dose(sets("2026-08-20", name, 14, [15, 15, 14, 12])), name)
        self.assertEqual(e["rep_range"], "12-15")
        self.assertEqual(e["range_from"],
                         "derived from last session reps (median 14.5)")

    def test_an_isolation_reentry_with_no_range_is_not_pushed_to_the_ceiling(self):
        rows = sets("2026-07-16", self.CURL, 32, [10, 10, 10])
        e = entry(dose(rows), self.CURL)
        self.assertEqual(e["rep_range"], "8-10")
        # 10 x 32 -> e1RM 42.7 -> 8 reps 33.7 x 0.85 = 28.6 -> nearest step
        # of the 4 kg grid: 28.
        self.assertEqual(e["load_kg"], 28.0)

    def test_the_first_exposure_discount_starts_after_56_days(self):
        # 44 kg x 10/10/10 on a 10-12: the range is reachable, so the load
        # is repeated up to 56 days and discounted (44 x 0.85 = 37.4, rounded
        # down on the 4 kg grid) after.
        from workout_coach.lib.blocks import (NOVELTY_DISCOUNT,
                                              ROTATION_CANDIDATE_WINDOW_DAYS)
        self.assertEqual(ROTATION_CANDIDATE_WINDOW_DAYS, 56)
        for gap, expected in ((56, 44.0), (57, 36.0)):
            with self.subTest(days=gap):
                day = date.fromordinal(TODAY.toordinal() - gap).isoformat()
                out = dose(sets(day, BENCH, 44, [10, 10, 10]),
                           [plan("2026-07-01", f"{BENCH}: 44kgx10-12")])
                e = entry(out, BENCH)
                self.assertEqual((e["action"], e["load_kg"]),
                                 ("hold", expected))
                self.assertEqual(f"{NOVELTY_DISCOUNT:g} first-exposure" in
                                 e["basis"], gap > 56)

    def test_a_reentry_load_is_never_raised_above_the_last_load(self):
        # 15 reps at 44 on a 10-12 projects 49.5 at 10 reps, above the load
        # that was lifted: the re-entry repeats 44 rather than raising it.
        # Past 56 days the discount gives 42.1, which is nearer 44 than 40
        # on the 4 kg grid.
        for gap, expected in ((40, 44.0), (90, 44.0)):
            with self.subTest(days=gap):
                day = date.fromordinal(TODAY.toordinal() - gap).isoformat()
                out = dose(sets(day, BENCH, 44, [15, 15, 15]),
                           [plan("2026-07-01", f"{BENCH}: 44kgx10-12")])
                self.assertEqual(entry(out, BENCH)["load_kg"], expected)

    def test_a_recent_lift_with_no_range_on_record_is_still_a_plain_hold(self):
        # The default range is for a re-entry only: inside 28 days a lift
        # with no range keeps its load and gets no range.
        rows = sets("2026-10-06", self.CURL, 32, [10, 10, 10])
        e = entry(dose(rows), self.CURL)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("hold", 32.0, None))
        self.assertIsNone(e["range_from"])
        self.assertIn("rep range is on record", e["basis"])

    def test_every_entry_with_a_last_session_has_numeric_last_fields(self):
        rows = (sets("2026-10-03", BENCH, 44, [12, 12, 12, 12])
                + sets("2026-09-01", "Dumbbell Row", 24, [10, 10, 12])
                + sets("2026-10-08", "Cable Shrug", 36.25, [18, 18]))
        out = dose(rows, [plan("2026-10-02", f"{BENCH}: 44kgx10-12")])
        self.assertGreaterEqual(len(out["exercises"]), 3)
        for e in out["exercises"]:
            with self.subTest(e["exercise"]):
                self.assertIsInstance(e["last_load_kg"], (int, float))
                self.assertTrue(e["last_reps"])
                self.assertTrue(all(isinstance(r, int) for r in e["last_reps"]))
        self.assertEqual(entry(out, BENCH)["last_load_kg"], 44.0)
        self.assertEqual(entry(out, "Dumbbell Row")["last_reps"], [10, 10, 12])


class BumpRuleTests(unittest.TestCase):
    def test_a_single_working_set_never_earns_a_bump(self):
        rows = sets("2026-10-03", BENCH, 44, [12])
        e = entry(dose(rows, [plan("2026-10-02", f"{BENCH}: 44kgx10-12")]),
                  BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 44.0))
        self.assertIn("only 1 working set", e["basis"])

    def test_two_working_sets_at_the_top_do(self):
        rows = sets("2026-10-03", BENCH, 44, [12, 12])
        e = entry(dose(rows, [plan("2026-10-02", f"{BENCH}: 44kgx10-12")]),
                  BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("add_load", 48.0))

    def test_a_lone_top_set_adds_the_step_to_the_working_load(self):
        name = "Cable Standing Calf Raise"
        rows = sets("2026-10-09", name, [40, 40, 43.75], [26, 26, 22])
        e = entry(dose(rows, [plan("2026-10-02", f"{name}: 40kgx15-20")]), name)
        self.assertEqual(e["load_kg"], 42.5)


class LoadEqualityTests(unittest.TestCase):
    def test_a_real_step_is_not_the_same_load(self):
        from workout_coach.lib.strength import loads_equal
        self.assertFalse(loads_equal(100, 101.25))
        self.assertFalse(loads_equal(60, 61.25))
        self.assertFalse(loads_equal(36.25, 38.75))
        self.assertTrue(loads_equal(100, 100.0))
        self.assertTrue(loads_equal(100, 100.4))       # float / rounding noise
        self.assertTrue(loads_equal(None, None))
        self.assertFalse(loads_equal(None, 5))

    def test_the_tolerance_is_absolute_and_under_the_smallest_step(self):
        from workout_coach.lib.constants import (
            LOAD_EQUAL_TOLERANCE_KG,
            LOAD_INCREMENT_KG,
        )
        self.assertLess(LOAD_EQUAL_TOLERANCE_KG, min(LOAD_INCREMENT_KG.values()))
        import workout_coach.lib.constants as constants
        self.assertFalse(hasattr(constants, "LOAD_EQUAL_TOLERANCE"))

    def test_a_small_plate_step_is_learned_on_a_heavy_lift(self):
        # 100 -> 101.25 -> 102.5 was "the same load" under the 2% tolerance,
        # so no increment was learned and the lift read as stalled.
        name = "Barbell Back Squat"
        rows = []
        for i, kg in enumerate([100, 101.25, 102.5]):
            rows += sets(f"2026-09-{1 + 4 * i:02d}", name, kg, [8, 8, 8])
        e = entry(dose(rows, [plan("2026-09-01", f"{name}: 102.5kgx8")],
                       today=date(2026, 9, 28)), name)
        self.assertEqual(e["increment_kg"], 1.25)
        self.assertEqual(e["load_kg"], 103.75)
        self.assertEqual(e.get("stalled_sessions"), None)


class HistoryWindowTests(unittest.TestCase):
    def test_a_lift_last_worked_months_ago_still_gets_a_reentry_entry(self):
        # 13 weeks: past the old 56-day window, inside the 120-day history.
        name = "Chest Supported Row Machine"
        rows = sets("2026-07-14", name, 70, [10, 10, 10])
        e = entry(dose(rows, [plan("2026-07-10", f"{name}: 70kgx10-12")]), name)
        # Past 56 days the re-derived load also takes the 0.85 first-exposure
        # discount: 70 x 0.85 = 59.5, rounded to the nearest 5 kg step.
        self.assertEqual((e["action"], e["load_kg"]), ("hold", 60.0))
        self.assertIn("92 days ago", e["basis"])

    def test_beyond_the_history_window_there_is_nothing_to_progress_from(self):
        rows = sets("2026-05-01", BENCH, 44, [12, 12, 12])
        out = dose(rows)
        self.assertEqual(out["exercises"], [])

    def test_stale_and_hold_share_one_boundary(self):
        # Exactly STALE_EXERCISE_DAYS ago: stale in the reintroduction list
        # AND a re-entry hold in next_dose. One day less: neither.
        from workout_coach.lib.constants import STALE_EXERCISE_DAYS
        from workout_coach.lib.strength import stale_exercises
        self.assertEqual(STALE_EXERCISE_DAYS, 28)
        for gap, stale in ((STALE_EXERCISE_DAYS, True),
                           (STALE_EXERCISE_DAYS - 1, False)):
            with self.subTest(days=gap):
                day = date.fromordinal(TODAY.toordinal() - gap).isoformat()
                rows = sets(day, BENCH, 44, [12, 12, 12])
                out = dose(rows, [plan("2026-08-01", f"{BENCH}: 44kgx10-12")])
                e = entry(out, BENCH)
                listed = stale_exercises(
                    rows, _DB, TODAY, STALE_EXERCISE_DAYS)
                self.assertEqual(bool(listed), stale)
                self.assertEqual(e["action"] == "hold", stale)


class RetiredMovementTests(unittest.TestCase):
    def test_a_retired_movement_has_no_entry_anywhere(self):
        name = "Ab Wheel Rollout"
        block = {"slots": [{"exercise": name,
                            "dose": {"rep_lo": 8, "rep_hi": 10}}]}
        out = dose([], block=block)
        self.assertEqual(entry(out, name)["action"], "no_history")
        out = build_next_dose([], _CATALOG, [], block, PROGRESS, TODAY,
                              retired={"ab wheel rollout"})
        self.assertEqual(out["exercises"], [])

    def test_a_retired_lift_with_history_and_a_retired_carry_are_dropped(self):
        rows = (sets("2026-10-03", BENCH, 44, [12, 12, 12])
                + sets("2026-10-03", "Suitcase Carry", 20, [0, 0]))
        out = build_next_dose(rows, _CATALOG, [], None, PROGRESS, TODAY,
                              retired={BENCH.lower(), "suitcase carry"})
        self.assertEqual(out["exercises"], [])
        self.assertIsNone(out["uncovered"])

    def test_the_retired_set_is_read_from_the_bench_log(self):
        from workout_coach.lib.adherence import retired_movements
        # `person_paths` read the env var once, at import: patch the module's
        # root (as test_data_git does) so nothing lands in the real plans/.
        from shared import person_paths
        with tempfile.TemporaryDirectory() as tmp:
            old_root = person_paths.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = Path(tmp)
            try:
                from workout_coach.lib.adherence import record_bench_response
                record_bench_response("p1", "Ab Wheel Rollout", "no equipment",
                                      "retired", "2026-10-02")
                record_bench_response("p1", "Hack Squat", "retry", "retry",
                                      "2026-10-02")
                self.assertEqual(retired_movements("p1"), {"ab wheel rollout"})
                self.assertTrue(
                    (Path(tmp) / "plans" / "p1" / "bench-log.json").exists())
            finally:
                person_paths.WORKOUT_TRACKER_ROOT = old_root


class UncoveredPrescriptionTests(unittest.TestCase):
    def test_uncovered_work_carries_the_last_written_dose(self):
        rows = sets("2026-10-03", "Bird Dog", 0, [12, 12])
        plans = [plan("2026-09-20", "Bird Dog: 20 /// 20"),
                 plan("2026-10-02", "Bird Dog: 22-25 /// 22-25",
                      f"{BENCH}: 44kgx10-12"),
                 plan("2026-10-14", "Bird Dog: 99 /// 99")]       # today: ignored
        out = dose(rows, plans)
        self.assertEqual(out["uncovered"]["exercises"],
                         [{"exercise": "Bird Dog",
                           "last_prescription": "22-25 /// 22-25"}])

    def test_never_prescribed_is_null(self):
        rows = sets("2026-10-03", "Dead Bug", 0, [12, 12])
        out = dose(rows, [plan("2026-10-02", f"{BENCH}: 44kgx10-12")])
        self.assertEqual(out["uncovered"]["exercises"],
                         [{"exercise": "Dead Bug", "last_prescription": None}])


class StallVersusOwedWeightTests(unittest.TestCase):
    def test_the_weight_owed_flag_matches_next_dose_add_load(self):
        # A lift whose next dose adds load is waiting for weight; the gate
        # and the nutrition stop signal must not count it as stalled.
        from workout_coach.lib.health_session_rec import _genuinely_stalled_lifts
        rows = []
        for day in ("2026-09-20", "2026-09-24", "2026-09-28", "2026-10-02"):
            rows += sets(day, BENCH, 44, [12, 12, 12, 12])
        out = dose(rows, [plan("2026-09-18", f"{BENCH}: 44kgx10-12")])
        self.assertEqual(entry(out, BENCH)["action"], "add_load")
        e1rm = estimated_1rm(rows, catalog=_CATALOG)
        lift = e1rm[BENCH]
        self.assertGreaterEqual(lift["stalled_sessions"], 2)
        lift["slope_kg_per_4w"] = 0.0
        self.assertEqual(_genuinely_stalled_lifts({BENCH: dict(lift)}), 1)
        lift["weight_owed"] = True
        self.assertEqual(_genuinely_stalled_lifts({BENCH: lift}), 0)


class OwedLiftIsNotSwappableTests(unittest.TestCase):
    """An owed lift is bumped, so it must not earn `stall_3_sessions`."""

    def test_withhold_owed_stalls_clears_both_block_shapes(self):
        from workout_coach.lib.blocks import (
            _anchor_change_excuse,
            withhold_owed_stalls,
        )

        def slot(name, stalled):
            return {"exercise": name, "tag": "anchor", "blocks_held": 1,
                    "stalled_sessions": stalled}
        block = {"slots": [slot("Dumbbell Row", 4), slot(BENCH, 6)],
                 "sessions": {"upper_a": [slot("Dumbbell Row", 4),
                                          slot(BENCH, 6)]}}
        self.assertEqual(
            _anchor_change_excuse(block["sessions"]["upper_a"][1]),
            "stall_3_sessions")
        n = withhold_owed_stalls(block, {BENCH.lower()})
        self.assertEqual(n, 2)
        for slots in (block["slots"], block["sessions"]["upper_a"]):
            self.assertEqual([s["stalled_sessions"] for s in slots], [4, None])
        self.assertIsNone(_anchor_change_excuse(block["sessions"]["upper_a"][1]))
        self.assertEqual(
            _anchor_change_excuse(block["sessions"]["upper_a"][0]),
            "stall_3_sessions")
        # Nothing owed, no block: nothing to do.
        self.assertEqual(withhold_owed_stalls(block, set()), 0)
        self.assertEqual(withhold_owed_stalls(None, {"x"}), 0)

    def test_the_payload_block_does_not_stamp_a_stall_on_an_owed_lift(self):
        row = "Dumbbell Row"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "p1" / "data"
            (data / "monthly").mkdir(parents=True)
            months = {"2026.09": "", "2026.10": ""}
            for n, day in enumerate(("2026-09-26", "2026-09-30", "2026-10-03",
                                     "2026-10-06"), start=1):
                body = ""
                for s_ in range(1, 4):      # every set at the top of 12-14
                    body += f"{n},{day},1,{BENCH},{s_},14,44,616,,,,,,,,,,manual\n"
                for s_ in range(1, 4):      # reps flat and short of the top
                    body += f"{n},{day},2,{row},{s_},9,24,216,,,,,,,,,,manual\n"
                body += (f"{n},{day},,TOTAL,,,,2000,,,60:00,,126,360,430,,"
                         f"60:00,manual\n")
                months[day[:4] + "." + day[5:7]] += body
            for ym, body in months.items():
                (data / "monthly" / f"{ym}.csv").write_text(
                    MONTHLY_HEADER + body, encoding="utf-8")
            (data / "profile.csv").write_text(PROFILE, encoding="utf-8")
            plans = root / "plans" / "p1"
            plans.mkdir(parents=True)
            (plans / "2026-09-20-workout.md").write_text(
                f"# Workout plan\n\n## Workout 1: UPPER A\n\n"
                f"- {BENCH}: 44kgx12-14 /// 44kgx12-14\n"
                f"- {row}: 24kgx8-10 /// 24kgx8-10\n", encoding="utf-8")
            env = os.environ.copy()
            env["WORKOUT_TRACKER_ROOT"] = str(root)
            proc = subprocess.run(
                [sys.executable,
                 str(SKILLS_ROOT / "workout-coach" / "scripts"
                     / "read_tracker.py"),
                 "--person", "p1", "--today", "2026-10-08"],
                cwd=str(root), env=env, text=True, capture_output=True,
                check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
        nd = payload["next_dose"]
        self.assertEqual(entry(nd, BENCH)["action"], "add_load")
        self.assertEqual(entry(nd, row)["action"], "add_reps")
        stalled = {s["exercise"]: s.get("stalled_sessions")
                   for s in payload["block"]["slots"]}
        self.assertIsNone(stalled[BENCH])            # owed: bumped, not swapped
        self.assertGreaterEqual(stalled[row], 3)     # genuinely stuck
        sessions = {x["exercise"]: x.get("stalled_sessions")
                    for v in payload["block"]["sessions"].values() for x in v}
        self.assertIsNone(sessions[BENCH])
        self.assertGreaterEqual(sessions[row], 3)
        # The e1RM entry still says what happened.
        self.assertTrue(payload["estimated_1rm"][BENCH]["weight_owed"])


class BlockCardCountTests(unittest.TestCase):
    def test_the_card_counts_the_blocks_lifts_not_every_next_dose_entry(self):
        from workout_coach.lib.render_cards_today import _dose_delta_rows
        nd = {"load_policy": "progress", "exercises": [
            {"exercise": "A", "action": "add_load"},
            {"exercise": "B", "action": "add_reps"},
            {"exercise": "C", "action": "add_load"},      # not in the block
            {"exercise": "D", "action": "hold"}]}          # not in the block
        block = {"slots": [{"exercise": "A"}, {"exercise": "b"},
                           {"exercise": "A"}]}
        html = _dose_delta_rows(nd, block)
        self.assertIn("1 of 2 lifts", html)
        # Without a block, every entry counts.
        self.assertIn("2 of 4 lifts", _dose_delta_rows(nd, None))


class RotationGapTests(unittest.TestCase):
    def test_pattern_untrained_days_is_the_real_gap(self):
        from workout_coach.lib.blocks import rotation_candidates
        rows = (sets("2026-07-16", "Dumbbell Shoulder Press", 24, [10, 10, 10])
                + sets("2026-10-03", BENCH, 44, [12, 12, 12]))
        e1rm = estimated_1rm(rows, catalog=_CATALOG)
        out = rotation_candidates(rows, _DB, _CATALOG, e1rm, TODAY,
                                  priority_tiers={})
        pushes = [c for c in out["candidates"]
                  if c["pattern"] == "SHOULDERS/Vertical Push (Compound)"]
        self.assertTrue(pushes)
        for c in pushes:
            self.assertEqual(c["pattern_untrained_days"], 90, c)
            self.assertNotIn("pattern_never_logged", c)

    def test_a_pattern_never_logged_is_a_lower_bound_and_says_so(self):
        from workout_coach.lib.blocks import rotation_candidates
        rows = (sets("2026-07-16", "Dumbbell Shoulder Press", 24, [10, 10, 10])
                + sets("2026-10-03", BENCH, 44, [12, 12, 12]))
        e1rm = estimated_1rm(rows, catalog=_CATALOG)
        out = rotation_candidates(rows, _DB, _CATALOG, e1rm, TODAY,
                                  priority_tiers={"chest": "emphasis",
                                                  "core": "emphasis"})
        never = [c for c in out["candidates"]
                 if c.get("pattern_never_logged")]
        self.assertTrue(never)
        for c in never:
            self.assertEqual(c["pattern_untrained_days"], 90)


class RecentIncrementTests(unittest.TestCase):
    """The step is learned at the CURRENT gym, from the recent log."""

    NOTE = "different gym"

    def _lift(self, name, loads, notes=None, reps=12, rng="10-12",
              start="2026-09-01", gap=4, today=date(2026, 9, 28), extra=()):
        rows = list(extra)
        for i, kg in enumerate(loads):
            day = (date.fromisoformat(start) + timedelta(days=gap * i)
                   ).isoformat()
            rows += sets(day, name, kg, [reps] * 3, notes=(notes or {}).get(i))
        out = dose(rows, [plan("2026-08-30", f"{name}: {loads[-1]}kgx{rng}")],
                   today=today)
        return entry(out, name)

    def test_jumps_before_the_latest_gym_note_on_a_cable_are_not_learned(self):
        # The old gym's stack stepped 5 kg and its sessions are untagged;
        # the move is tagged on the session of 2026-09-13 (idx 3).
        e = self._lift("Cable Seated Row", [50, 55, 60, 30, 35, 40],
                       notes={3: self.NOTE})
        self.assertEqual(e["increment_kg"], 2.5)             # the table
        self.assertEqual(e["load_kg"], 42.5)
        self.assertIn("equipment table", e["increment_basis"])
        self.assertIn("since 2026-09-13", e["increment_basis"])
        # Two jumps after the move are enough to learn the new step.
        e = self._lift("Cable Seated Row", [50, 55, 60, 30, 35, 40, 45],
                       notes={3: self.NOTE}, today=date(2026, 9, 30))
        self.assertEqual(e["increment_kg"], 5.0)
        self.assertIn("log: 5kg in 2 of 2", e["increment_basis"])

    def test_the_note_of_any_lift_that_day_moves_the_cutoff_for_a_cable(self):
        # The note sits on a squat, not on the cable: the whole day is at
        # the new gym.
        squat = sets("2026-09-13", "Barbell Back Squat", 100, [8, 8],
                     notes=self.NOTE)
        e = self._lift("Cable Seated Row", [50, 55, 60, 30, 35], extra=squat)
        self.assertEqual(e["increment_kg"], 2.5)
        self.assertIn("1 usable load jump", e["increment_basis"])
        self.assertIn("since 2026-09-13", e["increment_basis"])

    def test_a_free_weight_step_is_not_cut_at_a_gym_note(self):
        # A dumbbell weighs what it weighs at any gym, and a person who tags
        # the odd day at a second gym would otherwise never learn one.
        squat = sets("2026-09-13", "Barbell Back Squat", 100, [8, 8],
                     notes=self.NOTE)
        e = self._lift(BENCH, [36, 40, 44, 48, 52], extra=squat)
        self.assertEqual(e["increment_kg"], 4.0)
        self.assertIn("log: 4kg in 4 of 4", e["increment_basis"])

    def test_old_jumps_still_count_when_no_gym_note_cuts_them(self):
        # No age limit: a lift that steps once a month keeps its history.
        old = []
        for i, kg in enumerate((40, 44, 48)):
            old += sets(f"2026-05-{1 + 4 * i:02d}", BENCH, kg, [12] * 3)
        e = self._lift(BENCH, [52, 56], extra=old)
        self.assertIn("log: 4kg in 4 of 4", e["increment_basis"])
        old = []
        for i, kg in enumerate((40, 45, 50)):
            old += sets(f"2026-05-{1 + 4 * i:02d}", "Cable Seated Row", kg,
                        [12] * 3)
        e = self._lift("Cable Seated Row", [55, 60], extra=old)
        self.assertEqual(e["increment_kg"], 5.0)
        self.assertNotIn("since", e["increment_basis"])

    def test_free_weight_steps_are_learned_across_a_gym_move(self):
        # Light dumbbells step 2 kg (1 kg a hand) before and after the day
        # tagged at another gym: the whole history counts.
        squat = sets("2026-09-13", "Barbell Back Squat", 100, [8, 8],
                     notes=self.NOTE)
        e = self._lift("Dumbbell Lateral Raise", [10, 12, 14, 16], reps=20,
                       rng="15-20", extra=squat)
        self.assertEqual((e["increment_kg"], e["load_kg"]), (2.0, 18.0))
        self.assertIn("log: 2kg in 3 of 3", e["increment_basis"])
        self.assertNotIn("since", e["increment_basis"])

    def test_a_half_kilo_a_hand_is_noise_not_a_step_on_two_dumbbells(self):
        # 64 <-> 65 kg of dumbbells logged back and forth: re-weighing.
        name = "Dumbbell Shrug"
        e = self._lift(name, [64, 65, 64, 65, 64, 65], reps=15, rng="12-15")
        self.assertEqual(e["increment_kg"], 4.0)             # the table
        self.assertIn("equipment table", e["increment_basis"])
        self.assertIn("3 jumps ignored as re-weighing", e["increment_basis"])
        # A real 2 kg step amid the noise still wins.
        e = self._lift(name, [60, 62, 62.5, 64, 66], reps=15, rng="12-15")
        self.assertEqual(e["increment_kg"], 2.0)
        self.assertIn("log: 2kg in 2 of 2", e["increment_basis"])

    def test_a_single_dumbbell_floor_is_one_kilo_and_a_cable_keeps_small_steps(self):
        e = self._lift("Dumbbell Row", [14, 14.5, 14, 14.5, 14, 14.5])
        self.assertEqual(e["increment_kg"], 2.0)             # the table
        self.assertIn("jumps ignored as re-weighing", e["increment_basis"])
        e = self._lift("Dumbbell Row", [14, 15, 16, 17])
        self.assertEqual(e["increment_kg"], 1.0)
        c = self._lift("Cable Lateral Raise", [5, 6.25, 7.5, 8.75], reps=20,
                       rng="15-20")
        self.assertEqual(c["increment_kg"], 1.25)
        # Real 1 kg cable steps at a light load (25% of 4 kg) are steps: the
        # next load is +1, not the table's +2.5 (a 42% jump).
        c = self._lift("Cable Lateral Raise", [4, 5, 6, 6], reps=20,
                       rng="15-20")
        self.assertEqual((c["increment_kg"], c["load_kg"]), (1.0, 7.0))
        self.assertIn("log: 1kg in 2 of 2", c["increment_basis"])
        # The same 1 kg on a heavy stack (1.8% of 55 kg) is re-weighing.
        c = self._lift("Cable Seated Row", [55, 56, 55, 56, 55, 56])
        self.assertEqual(c["increment_kg"], 2.5)
        self.assertIn("ignored as re-weighing", c["increment_basis"])

    def test_the_floor_is_the_smallest_real_step_by_equipment(self):
        from workout_coach.lib.constants import (
            is_reweigh_jump,
            smallest_real_step_kg,
        )
        self.assertEqual(smallest_real_step_kg("DB", BENCH.lower()), 2.0)
        self.assertEqual(smallest_real_step_kg("DB", "dumbbell row"), 1.0)
        for equipment in ("BB", "Machine", "Cable", "Smith", "Plate", "LM",
                          None):
            self.assertEqual(smallest_real_step_kg(equipment, "x"), 1.0)
        # Noise is "no bigger than the smallest step AND under 5% of the load".
        self.assertFalse(is_reweigh_jump(1, 4, "Cable"))        # 25%
        self.assertTrue(is_reweigh_jump(1, 55, "Cable"))        # 1.8%
        self.assertTrue(is_reweigh_jump(1, 64, "DB", BENCH.lower()))
        self.assertFalse(is_reweigh_jump(2, 60, "DB", BENCH.lower()))  # real
        self.assertFalse(is_reweigh_jump(1, 14, "DB", "dumbbell row"))
        self.assertTrue(is_reweigh_jump(0.5, 14, "DB", "dumbbell row"))
        self.assertFalse(is_reweigh_jump(2.5, 100, "BB"))       # above the step


class SplitDoseTests(unittest.TestCase):
    """A lift prescribed twice is judged against the dose it was done as."""

    SQUAT = "Barbell Back Squat"
    PLAN = ("## Workout 1: LOWER A\n"
            "- Barbell Back Squat: 100kgx6-8 /// 100kgx6-8 /// 100kgx6-8\n"
            "- Leg Extension: 55kgx10-12 /// 55kgx10-12\n"
            "## Workout 2: LOWER B\n"
            "- Barbell Back Squat: 70kgx12-15 /// 70kgx12-15 /// 70kgx12-15\n"
            "- Leg Curl (Seated): 50kgx10-12 /// 50kgx10-12\n")

    def _out(self, rows, text=None):
        p = parse_plan(text or self.PLAN, "2026-10-05", _DB)
        return entry(dose(rows, [p]), self.SQUAT)

    def test_a_light_day_is_judged_against_the_light_dose(self):
        rows = (sets("2026-10-08", self.SQUAT, 100, [6, 6, 6])
                + sets("2026-10-08", "Leg Extension", 55, [10, 10])
                + sets("2026-10-11", self.SQUAT, 70, [15, 15, 15])
                + sets("2026-10-11", "Leg Curl (Seated)", 50, [10, 10]))
        e = self._out(rows)
        # 15s at 70 kg hit the top of the light dose (12-15, capped to the
        # compound ceiling 10-12): that is a bump. It was a 72.5 kg x 6-8
        # prescription before: the heavy slot's range on the light day's load.
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("add_load", 72.5, "10-12"))
        self.assertIn("workout 2: LOWER B", e["range_from"])

    def test_a_heavy_day_is_judged_against_the_heavy_dose(self):
        rows = (sets("2026-10-08", self.SQUAT, 70, [15, 15, 15])
                + sets("2026-10-08", "Leg Curl (Seated)", 50, [10, 10])
                + sets("2026-10-11", self.SQUAT, 100, [6, 6, 7])
                + sets("2026-10-11", "Leg Extension", 55, [10, 10]))
        e = self._out(rows)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("add_reps", 100.0, "6-8"))
        self.assertIn("workout 1: LOWER A", e["range_from"])

    def test_workouts_that_tie_on_coverage_are_told_apart_by_the_dose_done(self):
        text = ("## Workout 1: LOWER A\n"
                "- Barbell Back Squat: 100kgx6-8 /// 100kgx6-8\n"
                "## Workout 2: LOWER B\n"
                "- Barbell Back Squat: 70kgx12-15 /// 70kgx12-15\n")
        light = self._out(sets("2026-10-11", self.SQUAT, 70, [15, 15, 15]),
                          text)
        self.assertIn("workout 2", light["range_from"])
        self.assertEqual((light["action"], light["load_kg"]),
                         ("add_load", 72.5))
        heavy = self._out(sets("2026-10-11", self.SQUAT, 100, [8, 8, 8]),
                          text)
        self.assertIn("workout 1", heavy["range_from"])
        self.assertEqual((heavy["action"], heavy["load_kg"], heavy["rep_range"]),
                         ("add_load", 102.5, "6-8"))

    def test_a_session_that_matches_no_workout_gets_the_largest_dose_and_says_so(self):
        # Squat is one of three exercises done: 1/3 coverage of either
        # workout, under the ledger's 0.34 floor, so nothing matched.
        rows = (sets("2026-10-11", self.SQUAT, 100, [8, 8, 8])
                + sets("2026-10-11", BENCH, 44, [10, 10])
                + sets("2026-10-11", "Dumbbell Row", 24, [10, 10]))
        e = self._out(rows)
        self.assertIn("matched no workout that holds it", e["range_from"])
        self.assertEqual(e["rep_range"], "6-8")

    def test_one_dose_in_two_workouts_is_unchanged(self):
        text = self.PLAN.replace("70kgx12-15", "100kgx6-8")
        e = self._out(sets("2026-10-11", self.SQUAT, 100, [8, 8, 8]), text)
        self.assertEqual(e["range_from"], "plan 2026-10-05")


class RecencyTests(unittest.TestCase):
    NAME = "Cable Seated Row"

    def test_a_lift_done_last_week_at_the_other_gym_is_not_a_reentry(self):
        rows = (sets("2026-08-23", self.NAME, 50, [10, 10, 10])
                + sets("2026-10-09", self.NAME, 30, [12, 12],
                       notes="different gym"))
        e = entry(dose(rows, [plan("2026-08-20", f"{self.NAME}: 50kgx10-12")]),
                  self.NAME)
        self.assertEqual((e["action"], e["load_kg"]), ("add_reps", 50.0))
        self.assertNotIn("re-entry", e["basis"])
        self.assertIn("Reference session 2026-08-23 (52 days ago)", e["basis"])
        self.assertIn("the newer session on 2026-10-09 was at the other gym",
                      e["basis"])
        self.assertEqual(e["other_gym_load_kg"], 30.0)
        self.assertIn("2026-08-23", e["last"])

    def test_a_marked_deload_session_counts_as_practice(self):
        rows = (sets("2026-08-23", self.NAME, 50, [10, 10, 10])
                + sets("2026-10-02", self.NAME, 30, [12, 12],
                       notes="different gym"))
        e = entry(dose(rows, [plan("2026-08-20", f"{self.NAME}: 50kgx10-12")],
                       deloads=["2026-10-02"]), self.NAME)
        self.assertNotEqual(e["action"], "hold")
        self.assertNotIn("re-entry", e["basis"])
        self.assertIn("the newer session on 2026-10-02 was a marked deload "
                      "at the other gym", e["basis"])

    def test_a_newer_plain_deload_is_named_as_one(self):
        rows = (sets("2026-08-23", self.NAME, 50, [10, 10, 10])
                + sets("2026-10-02", self.NAME, 40, [12, 12]))
        e = entry(dose(rows, [plan("2026-08-20", f"{self.NAME}: 50kgx10-12")],
                       deloads=["2026-10-02"]), self.NAME)
        self.assertIn("Reference session 2026-08-23 (52 days ago); the newer "
                      "session on 2026-10-02 was a marked deload", e["basis"])
        self.assertNotIn("other gym", e["basis"])

    def test_a_lift_not_done_anywhere_for_a_month_is_still_a_reentry(self):
        rows = (sets("2026-08-23", self.NAME, 50, [10, 10, 10])
                + sets("2026-09-02", self.NAME, 30, [12, 12],
                       notes="different gym"))
        e = entry(dose(rows, [plan("2026-08-20", f"{self.NAME}: 50kgx10-12")]),
                  self.NAME)
        self.assertEqual(e["action"], "hold")
        self.assertIn("42 days ago", e["basis"])
        self.assertIn("reference session was 2026-08-23, 52 days ago", e["basis"])
        self.assertIn("the newer session on 2026-09-02 was at the other gym",
                      e["basis"])


class LowRepPrescriptionTests(unittest.TestCase):
    B = "Barbell Back Squat"

    def test_a_bare_one_or_two_is_never_bumped_automatically(self):
        for spec, top in (("100kgx1", "1 rep"), ("100kgx2", "2 reps"),
                          ("100kgx1-2", "2 reps")):
            with self.subTest(spec):
                rows = sets("2026-10-10", self.B, 100, [top and int(spec[-1])] * 3)
                e = entry(dose(rows, [plan("2026-10-01", f"{self.B}: {spec}")]),
                          self.B)
                self.assertEqual((e["action"], e["load_kg"]), ("hold", 100.0))
                self.assertIn(f"tops out at {top}", e["basis"])

    def test_three_reps_and_up_still_earn_a_bump(self):
        rows = sets("2026-10-10", self.B, 100, [5, 5, 5])
        e = entry(dose(rows, [plan("2026-10-01", f"{self.B}: 100kgx3-5")]),
                  self.B)
        self.assertEqual((e["action"], e["load_kg"]), ("add_load", 102.5))
        rows = sets("2026-10-10", self.B, 100, [3, 3])
        e = entry(dose(rows, [plan("2026-10-01", f"{self.B}: 100kgx3")]),
                  self.B)
        self.assertEqual(e["action"], "add_load")

    def test_the_policy_and_a_reentry_still_come_first(self):
        rows = sets("2026-10-10", self.B, 100, [1, 1])
        e = entry(dose(rows, [plan("2026-10-01", f"{self.B}: 100kgx1")],
                       policy=REDUCE), self.B)
        self.assertEqual(e["action"], "reduce")


class NoHistoryRangeTests(unittest.TestCase):
    def test_a_lift_with_no_history_takes_its_range_from_the_newest_plan(self):
        name = "Barbell Back Squat"
        # The block names the lift but carries no dose for it.
        block = {"slots": [{"exercise": name, "dose": {}}]}
        out = dose([], [plan("2026-09-20", f"{name}: 90kgx6-8"),
                        plan("2026-10-02", f"{name}: 90kgx8-10")], block=block)
        e = entry(out, name)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("no_history", None, "8-10"))

    def test_the_block_is_the_range_of_last_resort(self):
        name = "Barbell Back Squat"
        block = {"slots": [{"exercise": name,
                            "dose": {"rep_lo": 10, "rep_hi": 12}}]}
        plans = [plan("2026-10-02", f"{BENCH}: 44kgx10-12")]
        self.assertEqual(entry(dose([], plans, block=block), name)["rep_range"],
                         "10-12")
        plans = [plan("2026-10-02", f"{name}: 90kgx6-8")]
        self.assertEqual(entry(dose([], plans, block=block), name)["rep_range"],
                         "6-8")

    def test_a_deload_only_history_says_so(self):
        rows = sets("2026-10-02", BENCH, 30, [8, 8])
        e = entry(dose(rows, [plan("2026-09-28", f"{BENCH}: 44kgx10-12")],
                       deloads=["2026-10-02"]), BENCH)
        self.assertEqual((e["action"], e["load_kg"]), ("no_history", None))
        self.assertIn("was a marked deload", e["basis"])
        self.assertNotIn("no working set logged", e["basis"])
        self.assertEqual(e["rep_range"], "10-12")
        self.assertIn("rotation_candidates", e["basis"])
        # Nothing at all keeps the old wording.
        none = entry(dose([], block={"slots": [
            {"exercise": BENCH, "dose": {"rep_lo": 8, "rep_hi": 10}}]}), BENCH)
        self.assertIn("no working set logged", none["basis"])


# ---------------------------------------------------------------- end to end
MONTHLY_HEADER = (
    "SESSION,Date,#,Exercise,Set,Reps,kg,Volume,Notes,Distance (km),"
    "Duration (min),Pace (min/km),Avg HR,Active Cal,Total Cal,"
    "Elevation (m),Elapsed,Source\n"
)
PROFILE = ("key,value\nsource,health_auto_export\nauto_cardio,true\n"
           "birthday,1995-01-01\nstrength_sessions_per_week,3\n")


class PayloadTests(unittest.TestCase):
    """read_tracker emits next_dose and the gate's load_policy together."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        data = root / "p1" / "data"
        (data / "monthly").mkdir(parents=True)
        body = ""
        for n, day in enumerate(("2026-10-05", "2026-10-09"), start=1):
            for s in range(1, 5):
                body += f"{n},{day},1,{BENCH},{s},12,44,528,,,,,,,,,,manual\n"
            body += f"{n},{day},,TOTAL,,,,2112,,,60:00,,126,360,430,,60:00,manual\n"
        (data / "monthly" / "2026.10.csv").write_text(
            MONTHLY_HEADER + body, encoding="utf-8")
        (data / "profile.csv").write_text(PROFILE, encoding="utf-8")
        plans = root / "plans" / "p1"
        plans.mkdir(parents=True)
        (plans / "2026-10-04-workout.md").write_text(
            f"# Workout plan\n\n## Workout 1: UPPER A\n\n"
            f"- {BENCH}: 44kgx12-14 /// 44kgx12-14\n", encoding="utf-8")
        cls._env = os.environ.copy()
        cls._env["WORKOUT_TRACKER_ROOT"] = str(root)
        cls._root = root
        cls.payload = cls._read()

    @classmethod
    def _read(cls, *extra: str) -> dict:
        proc = subprocess.run(
            [sys.executable,
             str(SKILLS_ROOT / "workout-coach" / "scripts" / "read_tracker.py"),
             "--person", "p1", "--today", "2026-10-12", *extra],
            cwd=str(cls._root), env=cls._env, text=True, capture_output=True,
            check=False)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_the_bench_is_owed_weight_and_the_range_is_reset(self):
        nd = self.payload["next_dose"]
        e = entry(nd, BENCH)
        self.assertEqual((e["action"], e["load_kg"], e["rep_range"]),
                         ("add_load", 48.0, "10-12"))

    def test_the_gate_emits_the_policy_the_next_dose_applies(self):
        rec = self.payload["session_recommendation"]
        self.assertEqual(self.payload["next_dose"]["load_policy"],
                         rec["load_policy"]["policy"])

    def test_a_missing_recovery_score_is_labelled_not_substituted(self):
        policy = self.payload["session_recommendation"]["load_policy"]
        self.assertFalse(policy["recovery_available"])
        self.assertNotIn("recovery_score", policy)      # null, dropped
        self.assertIn("neither a recovery score nor a strength TSB",
                      policy["reason"])

    def test_muscle_floors_are_the_numbers_the_validator_enforces(self):
        from workout_coach.lib.constants import floor_scale
        from workout_coach.lib.render_validators import muscle_floors
        floors = self.payload["muscle_floors"]
        tiers = {m: v["tier"]
                 for m, v in self.payload["muscle_volume_targets"].items()}
        n = self.payload["strength_sessions_per_week"]
        cadence = bool(self.payload["block"].get("deload_prescribed"))
        self.assertEqual(floors, muscle_floors(tiers, n, cadence))
        # Direct-set integers, one per muscle that has a floor.
        for muscle, sets_ in floors.items():
            self.assertIsInstance(sets_, int, muscle)
            self.assertGreater(sets_, 0, muscle)
        # Absent, never 0: core (its dose is core_week_spec), the two
        # no-direct-supply muscles, MV-0 muscles, and external rotators
        # (the catalog has no exercise that serves them directly).
        for muscle in ("core", "erectors", "forearms", "glutes",
                       "front_delts", "adductors", "neck",
                       "external_rotators"):
            self.assertNotIn(muscle, floors)
        # Emphasis is MEV, anything else MV, in the direct unit, scaled to
        # the week (3 of 4 sessions) and rounded down.
        scale = floor_scale(n, cadence)
        for muscle, sets_ in floors.items():
            band = ("mev" if tiers[muscle] == "emphasis" else "mv")
            self.assertEqual(
                sets_, int(RP_DIRECT_SET_LANDMARKS[muscle][band] * scale))

    def test_the_floors_scale_with_the_session_count(self):
        self.assertEqual(self.payload["strength_sessions_per_week"], 3)
        two = self._read("--sessions", "2")
        self.assertEqual(two["strength_sessions_per_week"], 2)
        four = self._read("--sessions", "4")
        for muscle, full in four["muscle_floors"].items():
            self.assertEqual(two["muscle_floors"].get(muscle, 0), full // 2,
                             muscle)
            self.assertLessEqual(
                self.payload["muscle_floors"].get(muscle, 0), full, muscle)

    def test_the_session_count_flag_rejects_nonsense(self):
        proc = subprocess.run(
            [sys.executable,
             str(SKILLS_ROOT / "workout-coach" / "scripts" / "read_tracker.py"),
             "--person", "p1", "--sessions", "0"],
            cwd=str(self._root), env=self._env, text=True,
            capture_output=True, check=False)
        self.assertEqual(proc.returncode, 2)

    def test_the_last_session_type_is_the_matched_workout(self):
        last = self.payload["last_session_type"]
        self.assertEqual((last["type"], last["title"], last["date"],
                          last["plan_date"]),
                         ("upper", "UPPER A", "2026-10-09", "2026-10-04"))
        self.assertNotIn("last_session_type_reason", self.payload)

    def test_the_new_top_level_keys_are_declared(self):
        from tracker.validation import validate_tracker_json
        errors, warnings = validate_tracker_json(self.payload)
        self.assertEqual(errors, [])
        for key in ("strength_sessions_per_week", "last_session_type"):
            self.assertFalse([w for w in warnings if key in w], warnings)

    def test_a_lift_owed_weight_is_flagged_on_the_e1rm_entry(self):
        self.assertTrue(self.payload["estimated_1rm"][BENCH]["weight_owed"])

    def test_without_a_matching_plan_the_last_session_type_says_why(self):
        proc_root = self._root / "plans" / "p1"
        plan_file = proc_root / "2026-10-04-workout.md"
        saved = plan_file.read_text(encoding="utf-8")
        plan_file.unlink()
        try:
            payload = self._read()
        finally:
            plan_file.write_text(saved, encoding="utf-8")
        self.assertNotIn("last_session_type", payload)
        self.assertIn("no plan on disk", payload["last_session_type_reason"])

    def test_arm_week_spec_no_longer_carries_a_set_floor(self):
        self.assertEqual(self.payload["arm_week_spec"],
                         {"min_distinct_exercises_per_week": 2})

    def test_the_removed_dose_staleness_block_is_gone(self):
        self.assertNotIn("dose_staleness", self.payload)


if __name__ == "__main__":                                # pragma: no cover
    unittest.main()
