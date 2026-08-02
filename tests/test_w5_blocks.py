"""W5 — block rotation, the boundary, and the cold-start load.

Every test here corresponds to a hole that shipped: the frozen stale
pool, rotation satisfied by swapping a cable for a dumbbell, a six-week
ceiling that only existed in prose, and the absence of any rule for
deriving a starting weight — which made novelty literally unprescribable.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from workout_coach.lib.blocks import (
    ANCHOR_MAX_BLOCKS,
    deload_cadence,
    BLOCK_MAX_WEEKS,
    block_from_plan,
    block_status,
    derived_starting_load,
    load_pattern_catalog,
    new_block,
    pattern_group,
    read_block,
    reconcile_block_with_logs,
    rotation_candidates,
    rotation_diff_errors,
    rotation_diff_report,
    block_payload,
    session_key,
    write_block,
)
from workout_coach.lib.extract import load_exercises_db
from workout_coach.lib.strength import reintroduction_pool, stale_exercises

_DB_PATH = Path(__file__).resolve().parents[1] / "shared" / "exercises-database.md"
_DB = load_exercises_db(_DB_PATH)
_CATALOG = load_pattern_catalog(_DB)


def _set(day: str, exercise: str, kg: float = 40.0, reps: int = 10) -> dict:
    return {"date": day, "exercise": exercise, "kg": kg, "reps": reps,
            "notes": ""}


# ---------------------------------------------------------------------------
class StaleSortTests(unittest.TestCase):
    """The stale list is sliced by its caller, so the sort direction
    decides what the reintroduction pool contains."""

    def test_stale_list_is_sorted_newest_stale_first(self) -> None:
        today_d = date(2026, 8, 2)
        rows = [
            _set("2026-02-13", "Leg Extension"),      # ~24 weeks stale
            _set("2026-06-19", "Chest Press Machine"),  # ~6 weeks stale
        ]
        out = stale_exercises(rows, _DB, today_d, threshold_days=28)
        self.assertEqual([e["exercise"] for e in out],
                         ["Chest Press Machine", "Leg Extension"],
                         "oldest-first sorts the retirement pile to the top, "
                         "which is what froze the pool on February one-offs")

    def test_reintroduction_pool_prefers_history_over_bare_recency(self) -> None:
        # The measured case: an eleven-session movement ten weeks stale was
        # discarded by a five-item slice in favour of a single Plank
        # session eight weeks stale.
        today_d = date(2026, 8, 2)
        rows = [_set("2026-0%d-0%d" % (m, d), "Hanging Leg Raise", kg=0, reps=10)
                for m, d in ((1, 5), (1, 9), (2, 3), (2, 7), (3, 1), (3, 5),
                             (4, 2), (4, 6), (5, 1), (5, 5), (5, 9))]
        rows.append(_set("2026-06-10", "Plank", kg=0, reps=1))
        for i, day in enumerate(("2026-06-11", "2026-06-12", "2026-06-13",
                                 "2026-06-14", "2026-06-15")):
            rows.append(_set(day, "Leg Extension", kg=50 + i))
        stale = stale_exercises(rows, _DB, today_d, threshold_days=28)
        pool = reintroduction_pool(stale, limit=2)
        names = {e["exercise"] for e in pool}
        self.assertIn("Hanging Leg Raise", names,
                      "eleven sessions of history must beat a single lapsed "
                      "one-off for a reintroduction slot")
        self.assertNotIn("Plank", names)

    def test_pool_reports_the_score_it_ranked_on(self) -> None:
        today_d = date(2026, 8, 2)
        rows = [_set("2026-06-01", "Leg Extension")]
        pool = reintroduction_pool(
            stale_exercises(rows, _DB, today_d, 28), limit=5)
        self.assertIsNotNone(pool[0]["evidence_density"])


# ---------------------------------------------------------------------------
class PatternIdentityTests(unittest.TestCase):
    def test_pattern_comes_from_the_catalog_subsection(self) -> None:
        self.assertEqual(pattern_group("Barbell Back Squat", _CATALOG),
                         "QUADS/Squat Pattern (Compound)")
        self.assertEqual(pattern_group("Ab Crunch Machine", _CATALOG),
                         "CORE/Flexion")

    def test_equipment_flavours_share_one_pattern(self) -> None:
        self.assertEqual(pattern_group("Cable Lateral Raise", _CATALOG),
                         pattern_group("Dumbbell Lateral Raise", _CATALOG))

    def test_off_catalog_name_has_no_pattern(self) -> None:
        self.assertIsNone(pattern_group("Invented Machine Thing", _CATALOG))

    def test_compound_and_isolation_read_off_the_heading(self) -> None:
        self.assertTrue(_CATALOG["barbell back squat"]["is_compound"])
        self.assertFalse(_CATALOG["cable lateral raise"]["is_compound"])


# ---------------------------------------------------------------------------
def _block(slots, started="2026-06-01", prev=None):
    return new_block(started, {"upper_a": slots}, prev_block=prev)


def _slot(pos, exercise, tag="rotating", **kw):
    return dict(position=pos, exercise=exercise, tag=tag, **kw)


class RotationDiffTests(unittest.TestCase):
    """``rotation_diff_errors`` is the function W4's render validator
    calls. Each test is one way a plan-writing LLM could look like it
    rotated without rotating."""

    def _prev(self):
        return _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Cable Lateral Raise", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Ab Crunch Machine", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ])

    def test_a_clean_rotation_passes(self) -> None:
        prev = self._prev()
        new = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Cable Face Pull", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Cable Pallof Press", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ], started="2026-07-13", prev=prev)
        self.assertEqual(rotation_diff_errors(prev, new, _CATALOG), [])

    def test_equipment_swap_is_not_a_rotation(self) -> None:
        prev = self._prev()
        new = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Dumbbell Lateral Raise", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Cable Pallof Press", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ], started="2026-07-13", prev=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("differs only by equipment", errs)

    def test_an_unchanged_rotating_slot_fails(self) -> None:
        # The degenerate solution to a weekly distribution target: keep the
        # same three core movements forever, satisfy every weekly axis.
        prev = self._prev()
        new = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Cable Face Pull", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Ab Crunch Machine", "rotating"),
        ], started="2026-07-13", prev=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("unchanged from the previous block", errs)

    def test_cycling_back_to_a_recent_occupant_fails(self) -> None:
        # Alternating two movements changes the exercise every block and
        # rotates nothing. The slot's own history is what catches it.
        b1 = _block([_slot(1, "Dumbbell Flat Bench Press", "anchor"),
                     _slot(2, "Cable Lateral Raise", "rotating",
                           superset_with="Dumbbell Flat Bench Press")])
        b2 = _block([_slot(1, "Dumbbell Flat Bench Press", "anchor"),
                     _slot(2, "Cable Face Pull", "rotating",
                           superset_with="Dumbbell Flat Bench Press")],
                    started="2026-07-13", prev=b1)
        self.assertEqual(rotation_diff_errors(b1, b2, _CATALOG), [])
        b3 = _block([_slot(1, "Dumbbell Flat Bench Press", "anchor"),
                     _slot(2, "Cable Lateral Raise", "rotating",
                           superset_with="Dumbbell Flat Bench Press")],
                    started="2026-08-24", prev=b2)
        errs = "\n".join(rotation_diff_errors(b2, b3, _CATALOG))
        self.assertIn("within the last", errs)
        self.assertIn("Cycling between", errs)

    def test_a_rung_progression_inside_one_pattern_is_allowed(self) -> None:
        # Plank -> Ab Wheel Rollout stays in CORE/Anti-Extension. That is a
        # rung progression, not a flavour swap, and must stay legal — as
        # long as the session gains a pattern somewhere.
        prev = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Plank", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Ab Crunch Machine", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ])
        new = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Hollow Body Hold", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Cable Pallof Press", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ], started="2026-07-13", prev=prev)
        self.assertEqual(rotation_diff_errors(prev, new, _CATALOG), [])

    def test_all_rungs_and_no_new_pattern_fails(self) -> None:
        # Every slot progresses a rung inside its own category, so the
        # categories that are missing stay missing forever.
        prev = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Plank", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Ab Crunch Machine", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ])
        new = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Hollow Body Hold", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Kneeling Cable Crunch", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ], started="2026-07-13", prev=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("no rotating slot moved to a movement pattern", errs)

    def test_anchor_change_needs_a_named_reason(self) -> None:
        prev = self._prev()
        swapped = _block([
            _slot(1, "Flat Barbell Bench Press", "anchor"),
            _slot(2, "Cable Face Pull", "rotating",
                  superset_with="Flat Barbell Bench Press"),
            _slot(3, "Cable Pallof Press", "rotating",
                  superset_with="Flat Barbell Bench Press"),
        ], started="2026-07-13", prev=prev)
        errs = "\n".join(rotation_diff_errors(prev, swapped, _CATALOG))
        self.assertIn("anchor changed", errs)

        swapped["sessions"]["upper_a"][0]["anchor_change_reason"] = "stall_3_sessions"
        self.assertEqual(rotation_diff_errors(prev, swapped, _CATALOG), [])

    def test_rotated_in_movement_left_standalone_fails(self) -> None:
        prev = self._prev()
        new = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Cable Face Pull", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Cable Pallof Press", "rotating"),
        ], started="2026-07-13", prev=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("left standalone", errs)

    def test_superset_host_must_be_a_compound_and_come_first(self) -> None:
        prev = self._prev()
        new = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Cable Face Pull", "rotating",
                  superset_with="Cable Pallof Press"),
            _slot(3, "Cable Pallof Press", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ], started="2026-07-13", prev=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("is not a compound", errs)
        self.assertIn("not earlier in the session", errs)

    def test_a_newly_introduced_compound_needs_no_superset_host(self) -> None:
        # A compound is the host, not the guest.
        prev = self._prev()
        new = _block([
            _slot(1, "Cable Lat Pulldown", "anchor",
                  anchor_change_reason="stall_3_sessions"),
            _slot(2, "Cable Face Pull", "rotating",
                  superset_with="Cable Lat Pulldown"),
            _slot(3, "Cable Pallof Press", "rotating",
                  superset_with="Cable Lat Pulldown"),
        ], started="2026-07-13", prev=prev)
        self.assertEqual(rotation_diff_errors(prev, new, _CATALOG), [])

    def test_an_at_risk_carried_slot_must_be_supersetted(self) -> None:
        # The 28%-vs-11% drop rate is a property of isolation work, not of
        # novelty. `at_risk` is the seam for adherence data: this function
        # cannot see which movements keep going unperformed, so the caller
        # marks them and the rule then applies to a CARRIED slot too — one
        # that is in the same session it was in last block, so nothing
        # about novelty brings it under rule 6.
        #
        # Mid-block on purpose. Rule 6 is driven by adherence, not by the
        # calendar: gating it on the boundary would switch the protection
        # off for five weeks in six.
        prev = new_block("2026-07-01", {
            "upper_a": [
                _slot(1, "Dumbbell Flat Bench Press", "anchor"),
                _slot(2, "Cable Face Pull", "rotating",
                      superset_with="Dumbbell Flat Bench Press"),
            ],
        })
        new = new_block("2026-07-13", {
            "upper_a": [
                _slot(1, "Dumbbell Flat Bench Press", "anchor"),
                _slot(2, "Cable Face Pull", "rotating", at_risk=True),
            ],
        }, prev_block=prev)
        report = rotation_diff_report(prev, new, _CATALOG)
        self.assertFalse(report["boundary"], "1.7 weeks in is not a boundary")
        self.assertIn("keeps going unperformed", "\n".join(report["errors"]))

    def test_a_carried_slot_that_is_not_at_risk_may_stand_alone(self) -> None:
        # A blanket rule is not physical: a lower day has two compounds and
        # six accessories, and six accessories cannot all ride two hosts.
        prev = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Cable Face Pull", "rotating"),
            _slot(3, "Cable Pallof Press", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ])
        new = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Cable Face Pull", "rotating"),
            _slot(3, "Rear Delt Fly Machine", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ], started="2026-07-13", prev=prev)
        errs = rotation_diff_errors(prev, new, _CATALOG)
        self.assertEqual(
            [e for e in errs if "Superset it onto a compound" in e], [])

    def test_one_compound_cannot_host_the_whole_session(self) -> None:
        prev = _block([
            _slot(1, "Barbell Back Squat", "anchor"),
            _slot(2, "Leg Extension", "rotating"),
            _slot(3, "Leg Curl (Seated)", "rotating"),
            _slot(4, "Seated Calf Raise", "rotating"),
        ])
        new = _block([
            _slot(1, "Barbell Back Squat", "anchor"),
            _slot(2, "Hack Squat", "rotating",
                  superset_with="Barbell Back Squat"),
            _slot(3, "Leg Curl (Lying)", "rotating",
                  superset_with="Barbell Back Squat"),
            _slot(4, "Dumbbell Standing Calf Raise", "rotating",
                  superset_with="Barbell Back Squat"),
        ], started="2026-07-13", prev=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("which has room for 2", errs)

    def test_off_catalog_name_is_a_blocking_error(self) -> None:
        # Otherwise "invent a name" is the cheapest way past every rule
        # above, because an unknown name has no pattern to compare.
        prev = self._prev()
        new = _block([
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Super Delt Blaster 3000", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Cable Pallof Press", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ], started="2026-07-13", prev=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("not in the exercises catalog", errs)

    def test_no_proposed_block_is_an_error_not_a_pass(self) -> None:
        self.assertTrue(rotation_diff_errors(self._prev(), None, _CATALOG))


# ---------------------------------------------------------------------------
class BoundaryTests(unittest.TestCase):
    def test_boundary_is_not_due_inside_the_window(self) -> None:
        b = new_block("2026-07-01", {"upper_a": [_slot(1, "Pull-Up")]})
        st = block_status(b, date(2026, 7, 20), deloads=[])
        self.assertFalse(st["boundary_due"])
        self.assertEqual(st["age_weeks"], 2.7)

    def test_six_week_ceiling_fires_without_a_deload(self) -> None:
        # The rule exists precisely because the cadence deload has been
        # skipped twice; a ceiling that depends on the deload is no ceiling.
        b = new_block("2026-06-01", {"upper_a": [_slot(1, "Pull-Up")]})
        st = block_status(b, date(2026, 7, 13), deloads=[])
        self.assertTrue(st["boundary_due"])
        self.assertIn("ceiling", st["boundary_reason"])
        self.assertEqual(st["boundary_due_by"], "2026-07-13")
        self.assertEqual(BLOCK_MAX_WEEKS, 6)

    def test_a_deload_inside_the_block_fires_earlier(self) -> None:
        b = new_block("2026-06-01", {"upper_a": [_slot(1, "Pull-Up")]})
        st = block_status(b, date(2026, 6, 25), deloads=["2026-06-20"])
        self.assertTrue(st["boundary_due"])
        self.assertEqual(st["boundary_reason"], "deload_on_2026-06-20")

    def test_a_deload_before_the_block_does_not_fire(self) -> None:
        b = new_block("2026-06-01", {"upper_a": [_slot(1, "Pull-Up")]})
        st = block_status(b, date(2026, 6, 25), deloads=["2026-05-20"])
        self.assertFalse(st["boundary_due"])

    def test_no_block_on_record_reads_as_due(self) -> None:
        st = block_status(None, date(2026, 6, 25), deloads=[])
        self.assertTrue(st["boundary_due"])
        self.assertEqual(st["boundary_reason"], "no_block_on_record")


class DeloadCadenceTests(unittest.TestCase):
    """`deload_prescribed` means "this week's plan is intended to be low
    volume". `boundary_due` means "rotate the exercise selection". They
    run off different clocks and all four combinations occur."""

    DELOADS = ["2026-05-26", "2026-05-27", "2026-05-28"]

    def test_inside_the_cadence_nothing_is_prescribed(self) -> None:
        c = deload_cadence(self.DELOADS, date(2026, 7, 6),
                           prior_generation=date(2026, 6, 29))
        self.assertFalse(c["prescribed"])
        self.assertFalse(c["cadence_due"])
        self.assertEqual(c["weeks_since_deload"], 5.6)

    def test_the_generation_that_crosses_six_weeks_prescribes_it(self) -> None:
        c = deload_cadence(self.DELOADS, date(2026, 7, 13),
                           prior_generation=date(2026, 7, 6))
        self.assertTrue(c["prescribed"])
        self.assertTrue(c["cadence_due"])
        self.assertEqual(c["reason"], "cadence_6.6w_since_2026-05-28")

    def test_a_declined_deload_does_not_re_prescribe_every_week(self) -> None:
        # The measured case: 6.4, 7.0, 7.3 and 8.3 weeks across four
        # consecutive generations, of which exactly the first was a
        # deload plan. Flagging all four would demote the volume floors
        # to advisory on the three weeks that ran full volume — relaxing
        # the rules hardest where they matter most.
        for today, prior in ((date(2026, 7, 16), date(2026, 7, 13)),
                             (date(2026, 7, 18), date(2026, 7, 16)),
                             (date(2026, 7, 25), date(2026, 7, 18))):
            with self.subTest(today=today):
                c = deload_cadence(self.DELOADS, today, prior_generation=prior)
                self.assertFalse(c["prescribed"])
                self.assertTrue(c["cadence_due"],
                                "still owed, and worth saying so")

    def test_taking_the_deload_resets_the_counter(self) -> None:
        after = self.DELOADS + ["2026-07-14"]
        c = deload_cadence(after, date(2026, 7, 25),
                           prior_generation=date(2026, 7, 18))
        self.assertFalse(c["prescribed"])
        self.assertFalse(c["cadence_due"])
        self.assertEqual(c["last_deload"], "2026-07-14")

    def test_an_empty_deload_log_reads_as_owed(self) -> None:
        c = deload_cadence([], date(2026, 7, 13), prior_generation=None)
        self.assertTrue(c["prescribed"])
        self.assertEqual(c["reason"], "no_deload_on_record")
        self.assertIsNone(c["weeks_since_deload"])

    def test_a_deload_after_the_anchor_is_invisible(self) -> None:
        # Backtest honesty: a deload logged next week did not reset the
        # counter as of today.
        c = deload_cadence(self.DELOADS + ["2026-07-20"], date(2026, 7, 13),
                           prior_generation=date(2026, 7, 6))
        self.assertEqual(c["last_deload"], "2026-05-28")
        self.assertTrue(c["prescribed"])

    def test_boundary_and_deload_are_independent(self) -> None:
        """All four combinations, each reachable."""
        today, prior = date(2026, 7, 13), date(2026, 7, 6)
        young = new_block("2026-07-01", {"a": [_slot(1, "Pull-Up")]})
        old = new_block("2026-06-01", {"a": [_slot(1, "Pull-Up")]})
        before = ["2026-06-28"]   # cadence satisfied, predates `young`
        inside = ["2026-07-05"]   # cadence satisfied, falls inside `young`
        stale = ["2026-05-28"]    # cadence overdue

        def combo(block, deloads):
            return (block_status(block, today, deloads)["boundary_due"],
                    deload_cadence(deloads, today, prior)["prescribed"])

        # F/F — a normal week mid-block.
        self.assertEqual(combo(young, before), (False, False))
        # T/F — a deload taken inside the block ends the block, and does
        # not owe another one.
        self.assertEqual(combo(young, inside), (True, False))
        # F/T — a young block whose cadence counter is old. The real
        # 2026-07-13 case: the block reopened on a split change while the
        # deload counter kept running.
        self.assertEqual(combo(young, stale), (False, True))
        # T/T — end of a mesocycle: rotate the selection AND cut volume.
        self.assertEqual(combo(old, stale), (True, True))

    def test_the_flag_is_not_derived_from_plan_contents(self) -> None:
        # Halving the sets must not unlock the relaxed floors. The only
        # inputs are the deload log and two dates.
        import inspect
        sig = inspect.signature(deload_cadence)
        self.assertEqual(list(sig.parameters),
                         ["deloads", "today_d", "prior_generation"])


# ---------------------------------------------------------------------------
class BlockArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev_root = os.environ.get("WORKOUT_TRACKER_ROOT")
        os.environ["WORKOUT_TRACKER_ROOT"] = self._tmp.name
        import shared.person_paths as pp
        import importlib
        importlib.reload(pp)
        self.pp = pp

    def tearDown(self) -> None:
        if self._prev_root is None:
            os.environ.pop("WORKOUT_TRACKER_ROOT", None)
        else:
            os.environ["WORKOUT_TRACKER_ROOT"] = self._prev_root
        import shared.person_paths as pp
        import importlib
        importlib.reload(pp)
        self._tmp.cleanup()

    def test_write_then_read_round_trips(self) -> None:
        b = new_block("2026-07-01", {"upper_a": [_slot(1, "Pull-Up", "anchor")]})
        path = write_block("TestPerson", b)
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "block-2026-07-01.json")
        again = read_block("TestPerson")
        self.assertEqual(again["block_id"], "2026-07-01")
        self.assertEqual(again["sessions"]["upper_a"][0]["exercise"], "Pull-Up")

    def test_latest_block_wins(self) -> None:
        write_block("TestPerson", new_block("2026-06-01", {"a": [_slot(1, "Dip")]}))
        write_block("TestPerson", new_block("2026-07-13", {"a": [_slot(1, "Pull-Up")]}))
        self.assertEqual(read_block("TestPerson")["block_id"], "2026-07-13")

    def test_anchor_age_accumulates_across_blocks(self) -> None:
        b1 = new_block("2026-05-01", {"a": [_slot(1, "Pull-Up", "anchor")]})
        b2 = new_block("2026-06-12", {"a": [_slot(1, "Pull-Up", "anchor")]},
                       prev_block=b1)
        b3 = new_block("2026-07-24", {"a": [_slot(1, "Pull-Up", "anchor")]},
                       prev_block=b2)
        self.assertEqual(b3["sessions"]["a"][0]["blocks_held"], ANCHOR_MAX_BLOCKS)

    def test_slot_history_carries_forward(self) -> None:
        b1 = new_block("2026-05-01", {"a": [_slot(1, "Plank")]})
        b2 = new_block("2026-06-12", {"a": [_slot(1, "Dead Bug")]}, prev_block=b1)
        b3 = new_block("2026-07-24", {"a": [_slot(1, "Bird Dog")]}, prev_block=b2)
        self.assertEqual(b3["sessions"]["a"][0]["history"], ["Dead Bug", "Plank"])


# ---------------------------------------------------------------------------
class BlockFromPlanTests(unittest.TestCase):
    PLAN = """# Workout plan — 2026-07-25

## Workout 1: LOWER A + CORE
Date: ___\\

- Bodyweight Squat: 15
- Barbell Back Squat: 45kgx5 (warmup) /// 90kgx8-10 /// 90kgx8-10
- Dumbbell Standing Calf Raise: 50kgx12-15 /// 50kgx12-15
- Ab Crunch Machine: 30kgx12-15 /// 30kgx12-15
  — superset with the calf raise above

## Workout 2: UPPER A + CORE
Date: ___\\

- Dumbbell Flat Bench Press: 52kgx8-10 /// 52kgx8-10
- Cable Lateral Raise: 6.25kgx10-12 /// 6.25kgx10-12
"""

    def setUp(self) -> None:
        from workout_coach.lib.adherence import parse_plan
        self.plan = parse_plan(self.PLAN, "2026-07-25")

    def test_session_keys_drop_the_core_suffix(self) -> None:
        self.assertEqual(session_key("LOWER A + CORE", 1), "lower_a")
        self.assertEqual(session_key("UPPER B + CORE", 4), "upper_b")
        self.assertEqual(session_key("", 3), "workout_3")

    def test_warmups_are_not_block_slots(self) -> None:
        b = block_from_plan(self.plan, _CATALOG)
        names = [s["exercise"] for s in b["sessions"]["lower_a"]]
        self.assertNotIn("Bodyweight Squat", names)
        self.assertEqual(names[0], "Barbell Back Squat")

    def test_compounds_become_anchors_and_isolation_rotates(self) -> None:
        b = block_from_plan(self.plan, _CATALOG)
        tags = {s["exercise"]: s["tag"] for s in b["sessions"]["lower_a"]}
        self.assertEqual(tags["Barbell Back Squat"], "anchor")
        self.assertEqual(tags["Ab Crunch Machine"], "rotating")

    def test_the_superset_note_becomes_a_slot_link(self) -> None:
        # The plan's own prose is the only place the pairing is stated.
        b = block_from_plan(self.plan, _CATALOG)
        crunch = [s for s in b["sessions"]["lower_a"]
                  if s["exercise"] == "Ab Crunch Machine"][0]
        self.assertEqual(crunch["superset_with"], "Dumbbell Standing Calf Raise")


# ---------------------------------------------------------------------------
class ReconcileBlockTests(unittest.TestCase):
    def test_a_same_pattern_substitution_is_folded_in(self) -> None:
        b = new_block("2026-07-01", {"lower_a": [
            _slot(1, "Barbell Back Squat", "anchor"),
            _slot(2, "Leg Extension", "rotating"),
        ]})
        rows = [
            _set("2026-07-03", "Barbell Back Squat", 90, 8),
            _set("2026-07-03", "Leg Press", 200, 12),
        ]
        out, changes = reconcile_block_with_logs(
            b, rows, _DB, _CATALOG, date(2026, 7, 1), date(2026, 7, 31))
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["planned"], "Leg Extension")
        self.assertEqual(changes[0]["performed"], "Leg Press")
        slot = out["sessions"]["lower_a"][1]
        self.assertEqual(slot["exercise"], "Leg Press")
        self.assertEqual(slot["substituted_from"], "Leg Extension")
        # The input must not be mutated: the read path emits these as a
        # proposal, it does not rewrite the artifact.
        self.assertEqual(b["sessions"]["lower_a"][1]["exercise"], "Leg Extension")

    def test_a_performed_slot_is_left_alone(self) -> None:
        b = new_block("2026-07-01", {"lower_a": [_slot(1, "Leg Extension")]})
        rows = [_set("2026-07-03", "Leg Extension", 55, 12)]
        _, changes = reconcile_block_with_logs(
            b, rows, _DB, _CATALOG, date(2026, 7, 1), date(2026, 7, 31))
        self.assertEqual(changes, [])


# ---------------------------------------------------------------------------
class DerivedStartingLoadTests(unittest.TestCase):
    """Without a derived load there is no legal weight to write for a
    movement with no history, so rotation cannot actually be prescribed."""

    E1RM = {"Chest Supported Row Machine": {"current_e1rm_kg": 90.0,
                                            "last_date": "2026-07-30"}}

    def test_rep_matched_epley_with_equipment_transfer(self) -> None:
        got = derived_starting_load("Barbell Row", self.E1RM, _CATALOG, _DB,
                                    target_reps=10)
        # 90 / (1 + 10/30) = 67.5 -> x0.75 machine->BB -> 50.6 -> x0.85 -> 43.0
        # -> rounded to the 2.5kg barbell increment.
        self.assertEqual(got["load_kg"], 42.5)
        self.assertEqual(got["ref"], "Chest Supported Row Machine")
        self.assertEqual(got["target_reps"], 10)
        self.assertEqual(got["confidence"], "low")

    def test_higher_target_reps_derive_a_lighter_load(self) -> None:
        light = derived_starting_load("Barbell Row", self.E1RM, _CATALOG, _DB,
                                      target_reps=15)["load_kg"]
        heavy = derived_starting_load("Barbell Row", self.E1RM, _CATALOG, _DB,
                                      target_reps=5)["load_kg"]
        self.assertLess(light, heavy)

    def test_the_most_recent_sibling_is_the_reference(self) -> None:
        e1rm = {
            "Chest Supported Row Machine": {"current_e1rm_kg": 90.0,
                                            "last_date": "2026-05-01"},
            "Dumbbell Row": {"current_e1rm_kg": 40.0,
                             "last_date": "2026-07-30"},
        }
        got = derived_starting_load("Barbell Row", e1rm, _CATALOG, _DB)
        self.assertEqual(got["ref"], "Dumbbell Row")

    def test_bodyweight_movements_get_no_kilogram_figure(self) -> None:
        e1rm = {"Hanging Leg Raise": {"current_e1rm_kg": 5.0,
                                      "last_date": "2026-07-01"}}
        got = derived_starting_load("Hanging Knee Raise", e1rm, _CATALOG, _DB)
        if got is not None:      # entry exists only after the W6a catalog add
            self.assertIsNone(got["load_kg"])
            self.assertEqual(got["unit"], "bodyweight")

    def test_no_sibling_history_offers_no_number_rather_than_a_guess(self) -> None:
        # The movement is still OFFERED — dropping it entirely is what
        # closed the novelty channel for the emphasis patterns that are at
        # zero precisely because they are the gap — but with no weight
        # attached and a basis that says why.
        got = derived_starting_load("Barbell Row", {}, _CATALOG, _DB)
        self.assertIsNone(got["load_kg"])
        self.assertEqual(got["load_basis"], "no_reference")
        self.assertEqual(got["confidence"], "none")
        self.assertIsNone(got["ref"])

    def test_off_catalog_candidate_returns_none(self) -> None:
        self.assertIsNone(
            derived_starting_load("Nonexistent Lift", self.E1RM, _CATALOG, _DB))


class RotationCandidateTests(unittest.TestCase):
    def test_candidates_are_never_performed_movements_in_active_patterns(self) -> None:
        rows = [_set("2026-07-30", "Chest Supported Row Machine", 70, 10)]
        e1rm = {"Chest Supported Row Machine": {"current_e1rm_kg": 90.0,
                                                "last_date": "2026-07-30"}}
        out = rotation_candidates(rows, _DB, _CATALOG, e1rm, date(2026, 8, 2))
        cands = out["candidates"]
        names = {c["exercise"] for c in cands}
        self.assertNotIn("Chest Supported Row Machine", names,
                         "a movement with history is not a cold start")
        self.assertTrue(names, "an active pattern must offer siblings")
        self.assertTrue(all(c["load_kg"] is None or c["load_kg"] > 0
                            for c in cands))
        # The derivation rule is stated once, not on every candidate.
        self.assertIn("novelty_discount", out)
        self.assertEqual(out["target_reps"], 10)
        self.assertNotIn("target_reps", cands[0])

    def test_a_stale_pattern_offers_nothing(self) -> None:
        rows = [_set("2026-01-05", "Chest Supported Row Machine", 70, 10)]
        e1rm = {"Chest Supported Row Machine": {"current_e1rm_kg": 90.0,
                                                "last_date": "2026-01-05"}}
        out = rotation_candidates(rows, _DB, _CATALOG, e1rm, date(2026, 8, 2))
        self.assertEqual(out, {})


# ---------------------------------------------------------------------------
class BoundaryGatingTests(unittest.TestCase):
    """W5.4 is a BOUNDARY validator, and it was binding every week.

    The payload and the validator disagreed with each other on the same
    data: `block_payload` emitted `must_rotate: false` on all 33 slots
    1.1 weeks into a six-week block, and the validator then refused the
    render with 27 rotation errors and exit 2.
    """

    def _pair(self, prev_started, new_started, **prev_kw):
        prev = new_block(prev_started, {"upper_a": [
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Cable Lateral Raise", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Ab Crunch Machine", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ]})
        prev.update(prev_kw)
        new = new_block(new_started, {"upper_a": [
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Cable Lateral Raise", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
            _slot(3, "Ab Crunch Machine", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ]}, prev_block=prev)
        return prev, new

    def test_mid_block_an_unchanged_rotating_slot_is_correct(self) -> None:
        prev, new = self._pair("2026-07-25", "2026-08-02")
        report = rotation_diff_report(prev, new, _CATALOG)
        self.assertFalse(report["boundary"])
        self.assertEqual(report["boundary_basis"], "mid_block_1.1w")
        self.assertEqual(report["errors"], [],
                         "holding the selection mid-block IS the block model")

    def test_at_the_boundary_the_same_pair_is_rejected(self) -> None:
        prev, new = self._pair("2026-06-01", "2026-07-13")
        report = rotation_diff_report(prev, new, _CATALOG)
        self.assertTrue(report["boundary"])
        self.assertIn("ceiling", report["boundary_basis"])
        self.assertTrue(any("unchanged from the previous block" in e
                            for e in report["errors"]))

    def test_a_declared_boundary_fires_before_the_calendar_does(self) -> None:
        # A deload inside the block ends the block whatever the dates
        # say, and only `block_status` can see that. A stored True is
        # honoured; a stored False never suppresses, because the
        # persisted artifact freezes a False that was true when it was
        # written and stays false forever.
        prev, new = self._pair("2026-07-25", "2026-08-02",
                               boundary_due=True,
                               boundary_reason="deload_on_2026-07-30")
        report = rotation_diff_report(prev, new, _CATALOG)
        self.assertTrue(report["boundary"])
        self.assertEqual(report["boundary_basis"], "deload_on_2026-07-30")
        self.assertTrue(report["errors"])

        prev, new = self._pair("2026-06-01", "2026-07-13", boundary_due=False)
        self.assertTrue(rotation_diff_report(prev, new, _CATALOG)["boundary"],
                        "a stale stored False must not switch the check off")

    def test_unparseable_dates_fail_closed(self) -> None:
        prev, new = self._pair("not-a-date", "2026-08-02")
        report = rotation_diff_report(prev, new, _CATALOG)
        self.assertTrue(report["boundary"])
        self.assertEqual(report["boundary_basis"], "unknown_block_dates")

    def test_the_rules_that_are_not_about_the_calendar_still_bind(self) -> None:
        # Mid-block: an anchor may not be swapped (an anchor persists two
        # to three BLOCKS, so mid-block is the larger deviation), an
        # off-catalog name is still unverifiable, and one compound may
        # still not host the whole session.
        prev = new_block("2026-07-25", {"upper_a": [
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Cable Lateral Raise", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ]})
        new = new_block("2026-08-02", {"upper_a": [
            _slot(1, "Flat Barbell Bench Press", "anchor"),
            _slot(2, "Super Delt Blaster 3000", "rotating"),
        ]}, prev_block=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("anchor changed", errs)
        self.assertIn("not in the exercises catalog", errs)


# ---------------------------------------------------------------------------
class SelfDiffTests(unittest.TestCase):
    """A derived block rebuilt from the plan being validated is not a
    comparison, and saying "no errors" about it is a lie."""

    def test_a_block_diffed_against_itself_is_reported_not_passed(self) -> None:
        block = new_block("2026-08-02", {"upper_a": [
            _slot(1, "Dumbbell Flat Bench Press", "anchor"),
            _slot(2, "Cable Lateral Raise", "rotating",
                  superset_with="Dumbbell Flat Bench Press"),
        ]})
        block["source"] = "derived_from_plan"
        report = rotation_diff_report(block, block, _CATALOG)
        self.assertFalse(report["diffable"])
        self.assertIn("derived from this same plan", report["undiffable_reason"])
        self.assertTrue(any("derived from this same plan" in n
                            for n in report["notes"]))

    def test_a_real_pair_is_diffable(self) -> None:
        prev = new_block("2026-06-01", {"upper_a": [
            _slot(1, "Dumbbell Flat Bench Press", "anchor")]})
        new = new_block("2026-07-13", {"upper_a": [
            _slot(1, "Dumbbell Flat Bench Press", "anchor")]}, prev_block=prev)
        report = rotation_diff_report(prev, new, _CATALOG)
        self.assertTrue(report["diffable"])
        self.assertIsNone(report["undiffable_reason"])


# ---------------------------------------------------------------------------
class SessionMatchingTests(unittest.TestCase):
    """Renaming a heading changed the session key and exempted the whole
    session from every rotation rule. Measured: identical plan, headings
    renamed LOWER A -> LOWER 1, 27 errors became 0."""

    PREV = {
        "lower_a": [
            dict(position=1, exercise="Barbell Back Squat", tag="anchor"),
            dict(position=2, exercise="Leg Extension", tag="rotating",
                 superset_with="Barbell Back Squat"),
            dict(position=3, exercise="Ab Crunch Machine", tag="rotating",
                 superset_with="Barbell Back Squat"),
        ],
    }

    def _run(self, new_key):
        prev = new_block("2026-06-01", self.PREV)
        new = new_block("2026-07-13", {new_key: [
            _slot(1, "Barbell Back Squat", "anchor"),
            _slot(2, "Leg Extension", "rotating",
                  superset_with="Barbell Back Squat"),
            _slot(3, "Ab Crunch Machine", "rotating",
                  superset_with="Barbell Back Squat"),
        ]}, prev_block=prev)
        return rotation_diff_report(prev, new, _CATALOG)

    def test_a_renamed_heading_is_still_the_same_session(self) -> None:
        same = self._run("lower_a")
        renamed = self._run("lower_1")
        self.assertTrue(same["errors"])
        self.assertEqual(len(renamed["errors"]), len(same["errors"]),
                         "renaming the heading must not buy an exemption")
        self.assertEqual(renamed["sessions_matched"], {"lower_1": "lower_a"})

    def test_a_session_swap_is_reported_not_exempted(self) -> None:
        # Content matching cannot bridge this one: nothing overlaps. That
        # is a real structural change and it blocks with an actionable
        # remedy rather than passing in silence.
        prev = new_block("2026-06-01", self.PREV)
        new = new_block("2026-07-13", {"upper_z": [
            _slot(1, "Cable Lat Pulldown", "anchor"),
            _slot(2, "Cable Face Pull", "rotating",
                  superset_with="Cable Lat Pulldown"),
        ]}, prev_block=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("do not continue any session", errs)
        self.assertIn("lower_a", errs)

    def test_adding_a_session_is_a_note_not_a_block(self) -> None:
        # D7 contemplates the split changing. A pure addition has nothing
        # to rotate away from; it is reported and allowed.
        prev = new_block("2026-06-01", self.PREV)
        new = new_block("2026-07-13", {
            "lower_a": [
                _slot(1, "Barbell Back Squat", "anchor"),
                _slot(2, "Hack Squat", "rotating",
                      superset_with="Barbell Back Squat"),
                _slot(3, "Cable Pallof Press", "rotating",
                      superset_with="Barbell Back Squat"),
            ],
            "upper_z": [
                _slot(1, "Cable Lat Pulldown", "anchor"),
                _slot(2, "Cable Face Pull", "rotating",
                      superset_with="Cable Lat Pulldown"),
            ],
        }, prev_block=prev)
        report = rotation_diff_report(prev, new, _CATALOG)
        self.assertEqual(report["errors"], [])
        self.assertTrue(any("are new" in n for n in report["notes"]))


# ---------------------------------------------------------------------------
class AnchorIdentityTests(unittest.TestCase):
    """Anchors are matched by identity, not by ordinal. Positions come
    from counting non-warmup bullets, so inserting one accessory shifted
    every downstream position: 4 of the 14 real errors on the
    07-18 -> 07-25 transition were position shifts naming an
    unactionable remedy."""

    PREV = {"lower_a": [
        dict(position=1, exercise="Barbell Back Squat", tag="anchor"),
        dict(position=2, exercise="Romanian Deadlift", tag="anchor"),
        dict(position=3, exercise="Leg Extension", tag="rotating",
             superset_with="Barbell Back Squat"),
    ]}

    def test_inserting_an_accessory_does_not_invent_an_anchor_change(self) -> None:
        prev = new_block("2026-06-01", self.PREV)
        new = new_block("2026-07-13", {"lower_a": [
            _slot(1, "Barbell Back Squat", "anchor"),
            _slot(2, "Cable Pallof Press", "rotating",
                  superset_with="Barbell Back Squat"),
            _slot(3, "Romanian Deadlift", "anchor"),
            _slot(4, "Hack Squat", "rotating",
                  superset_with="Barbell Back Squat"),
        ]}, prev_block=prev)
        errs = rotation_diff_errors(prev, new, _CATALOG)
        self.assertEqual([e for e in errs if "anchor changed" in e], [],
                         "both anchors are still in the session")

    def test_a_real_anchor_drop_still_blocks_and_names_the_movement(self) -> None:
        prev = new_block("2026-06-01", self.PREV)
        new = new_block("2026-07-13", {"lower_a": [
            _slot(1, "Barbell Back Squat", "anchor"),
            _slot(2, "Hack Squat", "anchor"),
            _slot(3, "Cable Pallof Press", "rotating",
                  superset_with="Barbell Back Squat"),
        ]}, prev_block=prev)
        errs = [e for e in rotation_diff_errors(prev, new, _CATALOG)
                if "anchor changed" in e]
        self.assertEqual(len(errs), 1)
        self.assertIn("Romanian Deadlift", errs[0],
                      "name the anchor that went missing, not an ordinal")

    def test_appending_past_the_end_of_the_session_gains_nothing(self) -> None:
        # Position 9 of an 8-slot session had no counterpart at position
        # 9, so every rule skipped it. Two of ten bullets in one real
        # generation existed only to satisfy validator shape.
        prev = new_block("2026-06-01", self.PREV)
        new = new_block("2026-07-13", {"lower_a": [
            _slot(1, "Barbell Back Squat", "anchor"),
            _slot(2, "Romanian Deadlift", "anchor"),
            _slot(3, "Leg Extension", "rotating",
                  superset_with="Barbell Back Squat"),
            _slot(9, "Suitcase Carry", "rotating"),
        ]}, prev_block=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("Suitcase Carry", errs)
        self.assertIn("left standalone", errs)


# ---------------------------------------------------------------------------
class AnchorChangeReasonTests(unittest.TestCase):
    """`anchor_change_reason` was a field nothing in the pipeline could
    set, so the sanctioned response to a four-session stall was
    unreachable and the coach fell back to a load cut."""

    def _prev(self, **slot_kw):
        return new_block("2026-06-01", {"lower_a": [
            dict(position=1, exercise="Romanian Deadlift", tag="anchor",
                 **slot_kw),
            dict(position=2, exercise="Leg Extension", tag="rotating",
                 superset_with="Romanian Deadlift"),
        ]})

    def _new(self, prev, **anchor_kw):
        return new_block("2026-07-13", {"lower_a": [
            dict(position=1, exercise="Barbell Good Morning", tag="anchor",
                 **anchor_kw),
            _slot(2, "Cable Pallof Press", "rotating",
                  superset_with="Barbell Good Morning"),
        ]}, prev_block=prev)

    def test_a_stall_on_the_dropped_anchor_qualifies_the_change(self) -> None:
        prev = self._prev(stalled_sessions=4)
        report = rotation_diff_report(prev, self._new(prev), _CATALOG)
        self.assertEqual([e for e in report["errors"] if "anchor changed" in e],
                         [])
        self.assertTrue(any("stall_3_sessions" in n for n in report["notes"]),
                        "say which evidence excused it")

    def test_two_stalled_sessions_is_not_enough(self) -> None:
        prev = self._prev(stalled_sessions=2)
        errs = rotation_diff_errors(prev, self._new(prev), _CATALOG)
        self.assertTrue(any("anchor changed" in e for e in errs))

    def test_an_anchor_at_its_age_limit_qualifies(self) -> None:
        prev = self._prev()
        prev["sessions"]["lower_a"][0]["blocks_held"] = ANCHOR_MAX_BLOCKS
        report = rotation_diff_report(prev, self._new(prev), _CATALOG)
        self.assertEqual([e for e in report["errors"] if "anchor changed" in e],
                         [])
        self.assertTrue(any("age_3_blocks" in n for n in report["notes"]))

    def test_injury_comes_from_the_plans_own_sub_bullet(self) -> None:
        # The one reason nothing can derive. Parsed alongside the
        # superset hint, so a human channel exists at all.
        from workout_coach.lib.adherence import parse_plan
        plan = parse_plan(
            "## Workout 1: LOWER A\n"
            "- Barbell Good Morning: 40kgx10 /// 40kgx10\n"
            "  — anchor change: injury\n"
            "- Cable Pallof Press: 15kgx12 /// 15kgx12\n"
            "  — superset with the good morning above\n",
            "2026-07-13")
        prev = self._prev()
        new = block_from_plan(plan, _CATALOG, start_date="2026-07-13",
                              prev_block=prev)
        self.assertEqual(
            new["sessions"]["lower_a"][0]["anchor_change_reason"], "injury")
        self.assertEqual(
            [e for e in rotation_diff_errors(prev, new, _CATALOG)
             if "anchor changed" in e], [])


# ---------------------------------------------------------------------------
class AtRiskPropagationTests(unittest.TestCase):
    """Rule 6's adherence half was dead code: it read `at_risk` off the
    NEW block, and the new block always comes from `block_from_plan`,
    which never set it. 23 slots carried the flag on the previous
    artifact and 0 on the proposal."""

    def test_at_risk_travels_from_the_previous_block_by_name(self) -> None:
        from workout_coach.lib.adherence import parse_plan
        prev = new_block("2026-07-01", {"lower_a": [
            dict(position=1, exercise="Barbell Back Squat", tag="anchor"),
            dict(position=2, exercise="Leg Extension", tag="rotating",
                 at_risk=True, superset_with="Barbell Back Squat"),
        ]})
        # A DIFFERENT session, so nothing but the name can carry it.
        plan = parse_plan(
            "## Workout 1: LOWER B\n"
            "- Barbell Back Squat: 90kgx8 /// 90kgx8\n"
            "- Leg Extension: 55kgx12 /// 55kgx12\n",
            "2026-07-13")
        new = block_from_plan(plan, _CATALOG, start_date="2026-07-13",
                              prev_block=prev)
        slot = [s for s in new["sessions"]["lower_b"]
                if s["exercise"] == "Leg Extension"][0]
        self.assertTrue(slot.get("at_risk"),
                        "a movement the user keeps skipping stays flagged "
                        "when it is re-prescribed")

    def test_the_flag_is_what_makes_rule_6_fire_on_a_carried_slot(self) -> None:
        # Mutating AT_RISK_COMPLETION from 0.5 to 0.0 survived all 630
        # tests. This is the assertion that would have caught it: the
        # only difference between the two blocks below is the flag.
        def run(at_risk):
            prev = new_block("2026-07-01", {"lower_a": [
                dict(position=1, exercise="Barbell Back Squat", tag="anchor"),
                dict(position=2, exercise="Leg Extension", tag="rotating",
                     superset_with="Barbell Back Squat"),
            ]})
            slots = [_slot(1, "Barbell Back Squat", "anchor"),
                     _slot(2, "Leg Extension", "rotating")]
            if at_risk:
                slots[1]["at_risk"] = True
            new = new_block("2026-07-13", {"lower_a": slots}, prev_block=prev)
            return rotation_diff_errors(prev, new, _CATALOG)

        self.assertEqual(run(False), [])
        self.assertTrue(any("keeps going unperformed" in e for e in run(True)))


# ---------------------------------------------------------------------------
class ShufflingTests(unittest.TestCase):
    """Moving an exercise between days satisfied every rule while the
    block trained exactly what it trained before — the cheapest possible
    way to comply, and one an evaluated coach reached for about ten
    times in a single generation."""

    def _prev(self):
        return new_block("2026-06-01", {
            "lower_a": [_slot(1, "Barbell Back Squat", "anchor"),
                        _slot(2, "Leg Extension", "rotating",
                              superset_with="Barbell Back Squat"),
                        _slot(3, "Ab Crunch Machine", "rotating",
                              superset_with="Barbell Back Squat")],
            "lower_b": [_slot(1, "Romanian Deadlift", "anchor"),
                        _slot(2, "Leg Curl (Seated)", "rotating",
                              superset_with="Romanian Deadlift"),
                        _slot(3, "Plank", "rotating",
                              superset_with="Romanian Deadlift")],
        })

    def test_swapping_two_days_worth_of_accessories_is_rejected(self) -> None:
        prev = self._prev()
        new = new_block("2026-07-13", {
            "lower_a": [_slot(1, "Barbell Back Squat", "anchor"),
                        _slot(2, "Leg Curl (Seated)", "rotating",
                              superset_with="Barbell Back Squat"),
                        _slot(3, "Plank", "rotating",
                              superset_with="Barbell Back Squat")],
            "lower_b": [_slot(1, "Romanian Deadlift", "anchor"),
                        _slot(2, "Leg Extension", "rotating",
                              superset_with="Romanian Deadlift"),
                        _slot(3, "Ab Crunch Machine", "rotating",
                              superset_with="Romanian Deadlift")],
        }, prev_block=prev)
        errs = rotation_diff_errors(prev, new, _CATALOG)
        moved = [e for e in errs if "Moving a movement between sessions" in e]
        self.assertEqual(len(moved), 4, errs)

    def test_a_genuine_rotation_is_still_authorable(self) -> None:
        prev = self._prev()
        new = new_block("2026-07-13", {
            "lower_a": [_slot(1, "Barbell Back Squat", "anchor"),
                        _slot(2, "Hack Squat", "rotating",
                              superset_with="Barbell Back Squat"),
                        _slot(3, "Cable Pallof Press", "rotating",
                              superset_with="Barbell Back Squat")],
            "lower_b": [_slot(1, "Romanian Deadlift", "anchor"),
                        _slot(2, "Cable Standing Leg Curl", "rotating",
                              superset_with="Romanian Deadlift"),
                        _slot(3, "Suitcase Carry", "rotating",
                              superset_with="Romanian Deadlift")],
        }, prev_block=prev)
        report = rotation_diff_report(prev, new, _CATALOG)
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["boundary"])

    def test_a_reconciled_substitution_is_not_a_failure_to_rotate(self) -> None:
        # The ledger recorded that the user performed the dumbbell
        # version where the machine one was prescribed. Rejecting it as
        # "differs only by equipment" is the system arguing with its own
        # observations.
        prev = new_block("2026-06-01", {"upper_b": [
            dict(position=1, exercise="Cable Lat Pulldown", tag="anchor"),
            dict(position=2, exercise="Rear Delt Fly Machine", tag="rotating",
                 superset_with="Cable Lat Pulldown",
                 performed_instead="Dumbbell Rear Delt Fly"),
        ]})
        new = new_block("2026-07-13", {"upper_b": [
            _slot(1, "Cable Lat Pulldown", "anchor"),
            _slot(2, "Dumbbell Rear Delt Fly", "rotating",
                  superset_with="Cable Lat Pulldown"),
        ]}, prev_block=prev)
        errs = rotation_diff_errors(prev, new, _CATALOG)
        self.assertEqual([e for e in errs if "differs only by equipment" in e],
                         [], errs)

    def test_without_that_record_the_flavour_swap_is_still_rejected(self) -> None:
        prev = new_block("2026-06-01", {"upper_b": [
            _slot(1, "Cable Lat Pulldown", "anchor"),
            _slot(2, "Rear Delt Fly Machine", "rotating",
                  superset_with="Cable Lat Pulldown"),
        ]})
        new = new_block("2026-07-13", {"upper_b": [
            _slot(1, "Cable Lat Pulldown", "anchor"),
            _slot(2, "Dumbbell Rear Delt Fly", "rotating",
                  superset_with="Cable Lat Pulldown"),
        ]}, prev_block=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("differs only by equipment", errs)


# ---------------------------------------------------------------------------
class CatalogClassificationTests(unittest.TestCase):
    def test_a_loaded_carry_is_not_a_compound(self) -> None:
        # `Suitcase Carry` carries `+traps, +forearms` under a heading
        # that says neither "compound" nor "isolation", so the synergist
        # fallback made it an anchor — exempt from the superset rule, and
        # it left Anti-Lateral-Flexion with a one-member rotating pool.
        self.assertIsNone(_CATALOG["suitcase carry"]["is_compound"])
        self.assertEqual(_CATALOG["suitcase carry"]["pattern"],
                         "CORE/Anti-Lateral-Flexion")

    def test_no_core_entry_is_a_compound(self) -> None:
        core = [m for m in _CATALOG.values() if m["muscle"] == "CORE"]
        self.assertTrue(core)
        self.assertEqual([m["name"] for m in core if m["is_compound"]], [])

    def test_the_synergist_fallback_still_works_outside_core(self) -> None:
        self.assertTrue(_CATALOG["trap bar deadlift"]["is_compound"])
        self.assertTrue(_CATALOG["dumbbell farmer walk"]["is_compound"])


# ---------------------------------------------------------------------------
class RotationCandidateSelectionTests(unittest.TestCase):
    """The offer list was `sorted(catalog.items())[:3]` — the first three
    ALPHABETICALLY. Same defect class as the stale-pool sort this
    workstream exists to fix."""

    ROWS = [_set("2026-07-30", "Ab Crunch Machine", 30, 12),
            _set("2026-07-30", "Hanging Leg Raise", 0, 12),
            _set("2026-07-30", "Barbell Back Squat", 90, 8)]
    E1RM = {"Ab Crunch Machine": {"current_e1rm_kg": 46.7,
                                  "last_date": "2026-07-30"},
            "Barbell Back Squat": {"current_e1rm_kg": 120.3,
                                   "last_date": "2026-07-30"}}
    TIERS = {"core": "emphasis", "quads": "maintain"}

    def _out(self, **kw):
        return rotation_candidates(self.ROWS, _DB, _CATALOG, self.E1RM,
                                   date(2026, 8, 2), **kw)

    def test_an_emphasis_pattern_at_zero_is_still_offered(self) -> None:
        # The 56-day gate excluded exactly the categories
        # `min_pattern_categories_per_week` forces the coach to add: for
        # both people Anti-Rotation, Anti-Lateral-Flexion and Rotation
        # offered ZERO candidates. A pattern is at zero because it is the
        # gap.
        without = {c["pattern"] for c in self._out().get("candidates") or []}
        self.assertNotIn("CORE/Anti-Rotation", without)
        with_tiers = {c["pattern"] for c in
                      self._out(priority_tiers=self.TIERS)["candidates"]}
        for pattern in ("CORE/Anti-Rotation", "CORE/Anti-Lateral-Flexion",
                        "CORE/Rotation"):
            self.assertIn(pattern, with_tiers)

    def test_a_candidate_with_no_derivable_load_is_offered_anyway(self) -> None:
        cands = self._out(priority_tiers=self.TIERS)["candidates"]
        carry = [c for c in cands if c["exercise"] == "Suitcase Carry"]
        self.assertEqual(len(carry), 1)
        self.assertIsNone(carry[0]["load_kg"])
        self.assertEqual(carry[0]["load_basis"], "no_reference")

    def test_the_slice_is_not_alphabetical(self) -> None:
        # CORE/Flexion has eight never-performed bodyweight entries. The
        # shipped code took the first three by letter, which put Bicycle
        # Crunch in the payload and cut the hanging progression the user
        # has eleven logged sessions of. The ranking now prefers the
        # nearest neighbour of work the person already does, because a
        # rotated-in movement's measured failure is going unperformed.
        flexion = [c["exercise"] for c in
                   self._out(priority_tiers=self.TIERS)["candidates"]
                   if c["pattern"] == "CORE/Flexion"]
        self.assertIn("Leg Raise", flexion,
                      "the closest neighbour of a logged Hanging Leg Raise")
        self.assertNotIn("Bicycle Crunch", flexion,
                         "the alphabetically first entry, and nothing else")

    def test_one_equipment_class_cannot_take_every_slot(self) -> None:
        # Five bodyweight entries in the squat pattern otherwise took all
        # three slots and hid the only barbell option in the group.
        squat = [c["exercise"] for c in
                 self._out()["candidates"]
                 if c["pattern"] == "QUADS/Squat Pattern (Compound)"]
        equips = {(_CATALOG[e.lower()]["equipment"]) for e in squat}
        self.assertGreater(len(equips), 1, squat)

    def test_a_benched_movement_is_never_offered(self) -> None:
        # The payload named `Leg Curl (Lying)` under `adherence.benched`
        # ("must not re-prescribe") and offered it here at a derived
        # 45.0 kg in the same breath.
        rows = self.ROWS + [_set("2026-07-30", "Leg Curl (Seated)", 55, 12)]
        e1rm = dict(self.E1RM,
                    **{"Leg Curl (Seated)": {"current_e1rm_kg": 73.3,
                                             "last_date": "2026-07-30"}})
        plain = {c["exercise"] for c in rotation_candidates(
            rows, _DB, _CATALOG, e1rm, date(2026, 8, 2))["candidates"]}
        self.assertIn("Leg Curl (Lying)", plain)
        excluded = {c["exercise"] for c in rotation_candidates(
            rows, _DB, _CATALOG, e1rm, date(2026, 8, 2),
            exclude={"Leg Curl (Lying)"})["candidates"]}
        self.assertNotIn("Leg Curl (Lying)", excluded)


# ---------------------------------------------------------------------------
class TrapsRotationPoolTests(unittest.TestCase):
    """Reported, not fixed. `SHOULDERS/Traps` has exactly two members and
    they differ only by an equipment word, so rule 3 rejects the only
    move a traps rotating slot could make — and traps is an emphasis
    muscle. Closing it needs a catalog entry, not code."""

    def test_the_traps_pool_cannot_legally_rotate(self) -> None:
        traps = sorted(m["name"] for m in _CATALOG.values()
                       if m["pattern"] == "SHOULDERS/Traps")
        self.assertEqual(traps, ["Cable Shrug", "Dumbbell Shrug"])
        prev = new_block("2026-06-01", {"upper_a": [
            _slot(1, "Cable Lat Pulldown", "anchor"),
            _slot(2, "Dumbbell Shrug", "rotating",
                  superset_with="Cable Lat Pulldown")]})
        new = new_block("2026-07-13", {"upper_a": [
            _slot(1, "Cable Lat Pulldown", "anchor"),
            _slot(2, "Cable Shrug", "rotating",
                  superset_with="Cable Lat Pulldown")]}, prev_block=prev)
        errs = "\n".join(rotation_diff_errors(prev, new, _CATALOG))
        self.assertIn("differs only by equipment", errs,
                      "if this ever passes, a third traps movement was "
                      "added and this test should be deleted")

# ---------------------------------------------------------------------------
class BlockPayloadDiffBasisTests(unittest.TestCase):
    """The derived block must not be rebuilt from the plan being
    validated. `block_payload` bootstraps from the newest plan on disk,
    and on the generation that WRITES a plan that plan is the newest —
    so the "previous" block became a copy of the proposal, the render
    validator correctly refused to diff a plan against itself, and the
    whole rotation check passed. Measured on real inputs: the same plan
    and the same logs gave 27 rotation errors before the file existed
    and 0 after, which is precisely the agent's recovery loop."""

    PERSON = "TestPerson"
    PLAN = ("## Workout 1: LOWER A + CORE\n"
            "- Barbell Back Squat: 90kgx8 /// 90kgx8 /// 90kgx8\n"
            "- Leg Extension: 55kgx12 /// 55kgx12\n"
            "- Ab Crunch Machine: 30kgx12 /// 30kgx12\n")

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev_root = os.environ.get("WORKOUT_TRACKER_ROOT")
        os.environ["WORKOUT_TRACKER_ROOT"] = self._tmp.name
        import importlib
        import shared.person_paths as pp
        importlib.reload(pp)
        self.pp = pp
        self.plans = Path(self._tmp.name) / "plans" / self.PERSON
        self.plans.mkdir(parents=True)

    def tearDown(self) -> None:
        if self._prev_root is None:
            os.environ.pop("WORKOUT_TRACKER_ROOT", None)
        else:
            os.environ["WORKOUT_TRACKER_ROOT"] = self._prev_root
        import importlib
        import shared.person_paths as pp
        importlib.reload(pp)
        self._tmp.cleanup()

    def _write(self, plan_date: str) -> None:
        (self.plans / f"{plan_date}-workout.md").write_text(self.PLAN,
                                                            encoding="utf-8")

    def _payload(self, today):
        return block_payload(self.PERSON, [], _DB, _CATALOG, today, [])

    def test_todays_own_plan_is_not_the_block_it_differs_from(self) -> None:
        self._write("2026-07-18")
        self._write("2026-07-25")
        before = self._payload(date(2026, 8, 2))
        self.assertEqual(before["started"], "2026-07-25")
        # /coach writes the new plan; the render fails; the agent re-runs.
        self._write("2026-08-02")
        after = self._payload(date(2026, 8, 2))
        self.assertEqual(after["started"], "2026-07-25",
                         "the block must not restart on the plan being "
                         "validated")
        self.assertEqual(after["diff_basis"], before["diff_basis"])
        self.assertTrue(after["diffable"])

    def test_the_block_clock_does_not_reset_every_generation(self) -> None:
        # The same bug, seen from the boundary side: bootstrapping from
        # the newest plan set `age_weeks` to 0.0 on every run, so the
        # six-week ceiling could never be reached.
        self._write("2026-06-20")
        self._write("2026-08-02")
        payload = self._payload(date(2026, 8, 2))
        self.assertEqual(payload["started"], "2026-06-20")
        self.assertTrue(payload["boundary_due"])
        self.assertIn("ceiling", payload["boundary_reason"])

    def test_a_single_plan_written_today_is_reported_undiffable(self) -> None:
        # Nothing earlier exists. That is honest emptiness, not a pass.
        self._write("2026-08-02")
        payload = self._payload(date(2026, 8, 2))
        self.assertFalse(payload["diffable"])
        self.assertIn("no earlier generation", payload["undiffable_reason"])
        self.assertEqual(payload["source"], "none")

    def test_the_payload_carries_the_artifact_shape_as_well(self) -> None:
        # `slots` is the flat view the coach reads; `sessions` is the
        # shape a rotation check needs, and it is what carries the
        # per-slot provenance a flattening drops.
        self._write("2026-07-18")
        self._write("2026-07-25")
        payload = self._payload(date(2026, 8, 2))
        self.assertIsInstance(payload["sessions"], dict)
        self.assertEqual(
            {s["exercise"] for s in payload["sessions"]["lower_a"]},
            {s["exercise"] for s in payload["slots"]})

    def test_a_stalled_anchor_reaches_the_slot(self) -> None:
        self._write("2026-07-18")
        self._write("2026-07-25")
        payload = block_payload(
            self.PERSON, [], _DB, _CATALOG, date(2026, 8, 2), [],
            e1rm={"Barbell Back Squat": {"stalled_sessions": 4}})
        squat = [s for s in payload["slots"]
                 if s["exercise"] == "Barbell Back Squat"][0]
        self.assertEqual(squat["stalled_sessions"], 4)


if __name__ == "__main__":
    unittest.main()
