"""W2 — the prescription ledger.

The fixture plan is a synthetic 4-workout Upper/Lower week shaped like
the real 2026-07-25 generation: 28 prescribed working sets per workout,
with two workouts executed (17 and 24 sets) and two never done. If the
ledger cannot reproduce 112 prescribed / 41 performed off that, it
cannot measure the thing the whole workstream exists to measure.
"""
from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from workout_coach.lib.adherence import (
    BENCH_THRESHOLD,
    build_adherence,
    dose_staleness,
    load_plans,
    parse_plan,
    plan_windows,
    read_bench_log,
    reconcile_plan,
    record_bench_response,
    session_type_from_title,
)
from workout_coach.lib.blocks import load_pattern_catalog
from workout_coach.lib.extract import load_exercises_db

_DB_PATH = Path(__file__).resolve().parents[1] / "shared" / "exercises-database.md"
_DB = load_exercises_db(_DB_PATH)
_CATALOG = load_pattern_catalog(_DB)


PLAN_0725 = """# Workout plan — 2026-07-25
> Today's call: Train as planned.

Assessment: ./2026-07-25-assessment.html

## Workout 1: LOWER A + CORE
Date: ___\\
Recovery: sauna ___ / cold ___ / rlt ___

- Rowing Machine: 3 min
- Bodyweight Squat: 15
- Barbell Back Squat: 45kgx5 (warmup) /// 65kgx3 (warmup) /// 90kgx8-10 /// 90kgx8-10 /// 90kgx8-10 /// 90kgx8-10
- Romanian Deadlift: 100kgx10-12 /// 100kgx10-12 /// 100kgx10-12 /// 100kgx10-12
  — rep range up, load has been flat three sessions
- Leg Press: 200kgx12-15 /// 200kgx12-15 /// 200kgx12-15 /// 200kgx12-15
- Leg Curl (Seated): 55kgx10-12 /// 55kgx10-12 /// 55kgx10-12 /// 55kgx10-12
- Dumbbell Standing Calf Raise: 50kgx12-15 /// 50kgx12-15 /// 50kgx12-15 /// 50kgx12-15
- Ab Crunch Machine: 30kgx12-15 /// 30kgx12-15
  — superset with the calf raise above
- Hip Abductor Machine: 25kgx12-15 /// 25kgx12-15 /// 25kgx12-15
- Hip Adductor Machine: 50kgx10-12 /// 50kgx10-12 /// 50kgx10-12

## Workout 2: UPPER A + CORE
Date: ___\\
Recovery: sauna ___ / cold ___ / rlt ___

- Jumping Jacks: 50
- Arm Circles: 20
- Dumbbell Flat Bench Press: 24kgx5 (warmup) /// 36kgx3 (warmup) /// 52kgx8-10 /// 52kgx8-10 /// 52kgx8-10 /// 52kgx8-10
- Chest Supported Row Machine: 70kgx10-12 /// 70kgx10-12 /// 70kgx10-12 /// 70kgx10-12
- Dumbbell Shrug: 68kgx10-12 /// 68kgx10-12 /// 68kgx10-12
- Cable Lateral Raise: 6.25kgx10-12 /// 6.25kgx10-12 /// 6.25kgx10-12 /// 6.25kgx10-12
- Ab Crunch Machine: 35kgx10-12 /// 35kgx10-12
  — superset with the lateral raise above
- Incline Dumbbell Curl: 14kgx8-10 /// 14kgx8-10 /// 14kgx8-10 /// 14kgx8-10
- Cable Overhead Tricep Extension: 29kgx8-10 /// 29kgx8-10 /// 29kgx8-10 /// 29kgx8-10
- Cable Face Pull: 25kgx12-15 /// 25kgx12-15 /// 25kgx12-15

## Workout 3: LOWER B + CORE
Date: ___\\
Recovery: sauna ___ / cold ___ / rlt ___

- Rowing Machine: 3 min
- Glute Bridge: 15
- Dumbbell Bulgarian Split Squat: 16kgx8-10 per side /// 16kgx8-10 per side /// 16kgx8-10 per side /// 16kgx8-10 per side
- Barbell Hip Thrust: 30kgx10-12 /// 30kgx10-12 /// 30kgx10-12 /// 30kgx10-12
- Leg Extension: 55kgx12-15 /// 55kgx12-15 /// 55kgx12-15 /// 55kgx12-15
- Leg Curl (Lying): 40kgx10-12 /// 40kgx10-12 /// 40kgx10-12 /// 40kgx10-12
- 45 Degree Back Extension: 12-15 /// 12-15 /// 12-15
- Seated Calf Raise: 85kgx12-15 /// 85kgx12-15 /// 85kgx12-15 /// 85kgx12-15
- Cable Reverse Crunch: 15kgx12-15 /// 15kgx12-15
  — superset with the calf raise above
- Hip Abductor Machine: 25kgx12-15 /// 25kgx12-15 /// 25kgx12-15

## Workout 4: UPPER B + CORE
Date: ___\\
Recovery: sauna ___ / cold ___ / rlt ___

- Jumping Jacks: 50
- Wall Slide: 15
- Wide Chest Press Machine: 60kgx10-12 /// 60kgx10-12 /// 60kgx10-12 /// 60kgx10-12
- Cable Lat Pulldown: 65kgx8-10 /// 65kgx8-10 /// 65kgx8-10 /// 65kgx8-10
- Dumbbell Row: 20kgx10-12 /// 20kgx10-12 /// 20kgx10-12
- Cable Shrug: 60kgx12-15 /// 60kgx12-15 /// 60kgx12-15
- Ab Crunch Machine: 35kgx10-12 /// 35kgx10-12
  — superset with the shrug above
- Rear Delt Fly Machine: 20kgx12-15 /// 20kgx12-15 /// 20kgx12-15
- Cable Rope Hammer Curl: 20kgx10-12 /// 20kgx10-12 /// 20kgx10-12
- Cable Tricep Pushdown: 34kgx8-10 /// 34kgx8-10 /// 34kgx8-10
- Dumbbell Lateral Raise: 16kgx8-10 /// 16kgx8-10 /// 16kgx8-10

## Cardio 1: Intervals (20 min total)

- Warmup: 5 min easy
- Work: 5 x 3 min at HR 158bpm plus (Zone 4-5), 2 min easy between
- Cooldown: 5 min easy
"""


def _sets(day: str, exercise: str, n: int, kg: float = 50.0,
          reps: int = 10, notes: str = "") -> list[dict]:
    return [{"date": day, "exercise": exercise, "kg": kg, "reps": reps,
             "notes": notes} for _ in range(n)]


# The two sessions actually performed against the 07-25 plan: LOWER A at
# 17 working sets (Leg Press and the calf raise dropped, Romanian
# Deadlift cut short) and UPPER A at 24 (Cable Lateral Raise dropped).
LOGGED = (
    _sets("2026-07-29", "Rowing Machine", 1, kg=0, reps=0)
    + _sets("2026-07-29", "Bodyweight Squat", 1, kg=0, reps=15)
    + _sets("2026-07-29", "Barbell Back Squat", 2, kg=45, reps=5, notes="warmup")
    + _sets("2026-07-29", "Barbell Back Squat", 4, kg=95, reps=8)
    + _sets("2026-07-29", "Romanian Deadlift", 3, kg=100, reps=8)
    + _sets("2026-07-29", "Leg Curl (Seated)", 4, kg=55)
    + _sets("2026-07-29", "Hip Adductor Machine", 3, kg=30)
    + _sets("2026-07-29", "Hip Abductor Machine", 3, kg=55)
    + _sets("2026-07-30", "Jumping Jacks", 1, kg=0, reps=50)
    + _sets("2026-07-30", "Arm Circles", 1, kg=0, reps=20)
    + _sets("2026-07-30", "Dumbbell Flat Bench Press", 2, kg=24, reps=5,
            notes="warmup")
    + _sets("2026-07-30", "Dumbbell Flat Bench Press", 4, kg=52, reps=8)
    + _sets("2026-07-30", "Chest Supported Row Machine", 4, kg=70)
    + _sets("2026-07-30", "Dumbbell Shrug", 3, kg=64, reps=12)
    + _sets("2026-07-30", "Ab Crunch Machine", 2, kg=35)
    + _sets("2026-07-30", "Incline Dumbbell Curl", 4, kg=14, reps=6)
    + _sets("2026-07-30", "Cable Overhead Tricep Extension", 4, kg=29)
    + _sets("2026-07-30", "Cable Face Pull", 3, kg=29)
)


class PlanParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = parse_plan(PLAN_0725, "2026-07-25")

    def test_four_workouts_and_no_cardio_section(self) -> None:
        self.assertEqual([w["index"] for w in self.plan["workouts"]],
                         [1, 2, 3, 4])
        self.assertEqual(self.plan["parse_errors"], [])

    def test_every_workout_prescribes_28_working_sets(self) -> None:
        # Warmup ramps carry the (warmup) marker and are not working sets;
        # Rowing Machine / Bodyweight Squat / Jumping Jacks are catalog
        # warmup or cardio entries and are excluded downstream.
        for w in self.plan["workouts"]:
            counted = sum(
                s["prescribed_sets"] for s in w["slots"]
                if not (_DB.get(s["exercise"].lower()) or {}).get("is_warmup")
                and not (_DB.get(s["exercise"].lower()) or {}).get("is_cardio")
            )
            self.assertEqual(counted, 28, f"workout {w['index']}")

    def test_warmup_ramps_are_split_out_not_counted(self) -> None:
        squat = self.plan["workouts"][0]["slots"][2]
        self.assertEqual(squat["exercise"], "Barbell Back Squat")
        self.assertEqual(squat["prescribed_sets"], 4)
        self.assertEqual(squat["warmup_sets"], 2)

    def test_load_and_rep_target_are_extracted(self) -> None:
        squat = self.plan["workouts"][0]["slots"][2]
        self.assertEqual(squat["load_kg"], 90.0)
        self.assertEqual(squat["rep_target"], "8-10")
        self.assertEqual((squat["rep_lo"], squat["rep_hi"]), (8, 10))

    def test_a_bodyweight_slot_has_reps_and_no_load(self) -> None:
        ext = [s for s in self.plan["workouts"][2]["slots"]
               if s["exercise"] == "45 Degree Back Extension"][0]
        self.assertEqual(ext["prescribed_sets"], 3)
        self.assertIsNone(ext["load_kg"])
        self.assertEqual(ext["rep_target"], "12-15")

    def test_a_minutes_bullet_is_not_a_prescribed_set(self) -> None:
        rowing = self.plan["workouts"][0]["slots"][0]
        self.assertEqual(rowing["exercise"], "Rowing Machine")
        self.assertEqual(rowing["prescribed_sets"], 0)

    def test_the_superset_note_is_captured(self) -> None:
        crunch = [s for s in self.plan["workouts"][0]["slots"]
                  if s["exercise"] == "Ab Crunch Machine"][0]
        self.assertEqual(crunch["superset_hint"], "calf raise")

    def test_a_timed_carry_multiplies_out(self) -> None:
        plan = parse_plan(
            "## Workout 1: LOWER\n- Suitcase Carry: 3 x 30m @ 24kg\n"
            "- Plank: 45s hold /// 45s hold\n", "2026-08-02")
        slots = {s["exercise"]: s for s in plan["workouts"][0]["slots"]}
        self.assertEqual(slots["Suitcase Carry"]["prescribed_sets"], 3)
        self.assertEqual(slots["Suitcase Carry"]["load_kg"], 24.0)
        self.assertEqual(slots["Suitcase Carry"]["metres"], 30.0)
        self.assertEqual(slots["Plank"]["prescribed_sets"], 2)
        self.assertEqual(slots["Plank"]["seconds"], 45.0)

    def test_a_deload_plan_parses_and_is_flagged(self) -> None:
        # `## Deload Session 1: PUSH` is a real second heading the coach
        # emits, not a typo. Matching only `## Workout N:` dropped whole
        # plans, which reads downstream as "nothing was prescribed that
        # week" rather than as a parse failure.
        plan = parse_plan(
            "# Workout plan — 2026-05-24\n"
            "## Deload Session 1: PUSH\n"
            "Date: ___\n"
            "- Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8\n"
            "  — hold load, halve sets\n", "2026-05-24")
        self.assertEqual(len(plan["workouts"]), 1)
        self.assertTrue(plan["is_deload"])
        self.assertTrue(plan["workouts"][0]["is_deload"])
        self.assertEqual(plan["workouts"][0]["slots"][0]["prescribed_sets"], 2)
        self.assertEqual(plan["parse_errors"], [])

    def test_a_plan_with_headings_but_no_sets_reports_a_parse_error(self) -> None:
        plan = parse_plan("## Workout 1: UPPER A\n- Notes: take it easy\n",
                          "2026-05-24")
        self.assertIn("no prescribed sets", " ".join(plan["parse_errors"]))

    def test_a_normal_plan_is_not_flagged_as_a_deload(self) -> None:
        self.assertFalse(parse_plan(PLAN_0725, "2026-07-25")["is_deload"])

    def test_the_heading_grammar_is_public(self) -> None:
        # `render_validators` has to recognise exactly what the ledger
        # recognises. It reached for the private regex because there was
        # no public name; a second copy of the pattern over there is how
        # the two drift.
        from workout_coach.lib import adherence as A
        self.assertTrue(hasattr(A, "WORKOUT_HEADING_RE"))
        self.assertTrue(callable(A.is_workout_heading))
        self.assertTrue(callable(A.workout_heading_title))

    def test_every_heading_form_in_the_corpus_is_recognised(self) -> None:
        from workout_coach.lib.adherence import (is_workout_heading,
                                                 workout_heading_title)
        for line, title in (
            ("## Workout 1: LOWER A + CORE", "Workout 1: LOWER A + CORE"),
            ("## Workout A: PUSH",           "Workout A: PUSH"),
            ("## Deload Session 2: PUSH",    "Deload Session 2: PUSH"),
            ("## Session 3: PULL",           "Session 3: PULL"),
        ):
            with self.subTest(line=line):
                self.assertTrue(is_workout_heading(line))
                self.assertEqual(workout_heading_title(line), title)

    def test_non_workout_headings_stay_out(self) -> None:
        from workout_coach.lib.adherence import is_workout_heading
        for line in ("## Cardio 1: Intervals (20 min total)",
                     "## Notes",
                     "## Zone 2 cardio + mobility (today)",
                     "## Workout Notes: not a workout",
                     "- Leg Press: 200kgx10"):
            with self.subTest(line=line):
                self.assertFalse(is_workout_heading(line))

    def test_a_lettered_workout_parses_and_keeps_an_ordinal_index(self) -> None:
        # `## Workout A: PUSH` is in the real corpus. Narrowing the
        # grammar to numbers silently disabled every check on it.
        plan = parse_plan(
            "## Workout A: PUSH\n- Dumbbell Flat Bench Press: 50kgx8\n\n"
            "## Workout B: PULL\n- Cable Lat Pulldown: 65kgx8\n", "2026-08-02")
        self.assertEqual([w["label"] for w in plan["workouts"]], ["A", "B"])
        # `index` stays an int so every consumer can sort and dict-key on it.
        self.assertEqual([w["index"] for w in plan["workouts"]], [1, 2])
        self.assertEqual(plan["workouts"][0]["title"], "PUSH")

    def test_the_ordinal_matches_the_label_for_numbered_plans(self) -> None:
        for w in parse_plan(PLAN_0725, "2026-07-25")["workouts"]:
            self.assertEqual(str(w["index"]), w["label"])

    def test_session_type_reads_off_the_heading(self) -> None:
        self.assertEqual(session_type_from_title("LOWER A + CORE"), "lower")
        self.assertEqual(session_type_from_title("UPPER B + CORE"), "upper")
        self.assertEqual(session_type_from_title("FULL BODY A"), "full")
        self.assertIsNone(session_type_from_title("SESSION ONE"))


class ReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = parse_plan(PLAN_0725, "2026-07-25")
        self.rec = reconcile_plan(self.plan, date(2026, 7, 25),
                                  date(2026, 8, 3), LOGGED, _DB, _CATALOG)

    def test_the_ledger_reproduces_the_measured_totals(self) -> None:
        self.assertEqual(self.rec["sets_prescribed"], 112)
        self.assertEqual(self.rec["sets_performed"], 41)
        self.assertEqual(self.rec["completion_rate"], 0.366)

    def test_sessions_planned_versus_performed(self) -> None:
        self.assertEqual(self.rec["sessions_planned"], 4)
        self.assertEqual(self.rec["sessions_performed"], 2)
        self.assertEqual(self.rec["workouts_never_done"], [3, 4])

    def test_logged_sessions_map_to_the_workout_they_cover(self) -> None:
        self.assertEqual(self.rec["_match"],
                         {"2026-07-29": 1, "2026-07-30": 2})

    def test_isolation_and_compound_are_reported_separately(self) -> None:
        # The load-bearing split: moving laggards earlier failed twice
        # because truncation is isolation-vs-compound, not positional.
        self.assertIsNotNone(self.rec["isolation_completion_rate"])
        self.assertIsNotNone(self.rec["compound_completion_rate"])
        self.assertNotEqual(self.rec["isolation_completion_rate"],
                            self.rec["compound_completion_rate"])

    def test_warmups_are_excluded_from_both_sides(self) -> None:
        names = {e["name"] for e in self.rec["per_exercise"]}
        self.assertNotIn("Jumping Jacks", names)
        self.assertNotIn("Bodyweight Squat", names)
        self.assertNotIn("Rowing Machine", names)

    def test_a_partially_completed_exercise_reports_its_rate(self) -> None:
        rdl = [e for e in self.rec["per_exercise"]
               if e["name"] == "Romanian Deadlift"][0]
        self.assertEqual((rdl["prescribed_sets"], rdl["performed_sets"]), (4, 3))
        self.assertEqual(rdl["completion_rate"], 0.75)

    def test_an_exercise_prescribed_in_two_workouts_aggregates(self) -> None:
        crunch = [e for e in self.rec["per_exercise"]
                  if e["name"] == "Ab Crunch Machine"][0]
        self.assertEqual(crunch["prescribed_sets"], 6)   # workouts 1, 2 and 4
        self.assertEqual(crunch["performed_sets"], 2)
        self.assertEqual(crunch["workouts"], [1, 2, 4])

    def test_a_session_outside_the_window_is_not_credited(self) -> None:
        rec = reconcile_plan(self.plan, date(2026, 7, 25), date(2026, 7, 30),
                             LOGGED, _DB, _CATALOG)
        self.assertEqual(rec["sets_performed"], 17)
        self.assertEqual(rec["sessions_performed"], 1)

    def test_an_unrelated_session_does_not_mark_a_workout_performed(self) -> None:
        rows = _sets("2026-07-28", "Swim", 1, kg=0, reps=0)
        rows += _sets("2026-07-28", "Dumbbell Fly", 3, kg=20)
        rec = reconcile_plan(self.plan, date(2026, 7, 25), date(2026, 8, 3),
                             rows, _DB, _CATALOG)
        self.assertEqual(rec["sessions_performed"], 0)
        self.assertEqual(rec["sets_off_plan"], 3)


class SubstitutionTests(unittest.TestCase):
    """A same-muscle alternative logged instead of the prescribed movement
    is not a skip. 14% of apparent misses were exactly this, and counting
    them as skips benches movements the user did do."""

    PLAN = ("## Workout 1: LOWER A\n"
            "- Barbell Back Squat: 90kgx8 /// 90kgx8\n"
            "- Leg Extension: 55kgx12 /// 55kgx12\n")

    def _rec(self, rows):
        plan = parse_plan(self.PLAN, "2026-07-01")
        return reconcile_plan(plan, date(2026, 7, 1), date(2026, 7, 8),
                              rows, _DB, _CATALOG)

    def test_a_same_muscle_alternative_is_counted_as_a_substitution(self) -> None:
        rows = (_sets("2026-07-02", "Barbell Back Squat", 2, kg=90, reps=8)
                + _sets("2026-07-02", "Leg Press", 2, kg=200, reps=12))
        rec = self._rec(rows)
        self.assertEqual(len(rec["substitutions"]), 1)
        sub = rec["substitutions"][0]
        self.assertEqual(sub["prescribed"], "Leg Extension")
        self.assertEqual(sub["performed"], "Leg Press")
        self.assertEqual(sub["muscle"], "quads")

    def test_a_different_muscle_is_not_a_substitution(self) -> None:
        rows = (_sets("2026-07-02", "Barbell Back Squat", 2, kg=90, reps=8)
                + _sets("2026-07-02", "Cable Face Pull", 2, kg=25, reps=12))
        self.assertEqual(self._rec(rows)["substitutions"], [])

    def test_one_alternative_cannot_excuse_two_skipped_slots(self) -> None:
        plan = parse_plan(
            "## Workout 1: LOWER A\n"
            "- Barbell Back Squat: 90kgx8 /// 90kgx8\n"
            "- Leg Extension: 55kgx12 /// 55kgx12\n"
            "- Hack Squat: 100kgx10 /// 100kgx10\n", "2026-07-01")
        rows = (_sets("2026-07-02", "Barbell Back Squat", 2, kg=90, reps=8)
                + _sets("2026-07-02", "Leg Press", 2, kg=200, reps=12))
        rec = reconcile_plan(plan, date(2026, 7, 1), date(2026, 7, 8),
                             rows, _DB, _CATALOG)
        self.assertEqual(len(rec["substitutions"]), 1)


# ---------------------------------------------------------------------------
class LedgerHarness(unittest.TestCase):
    """Writes a real plan series and a real bench log under a temp root."""

    PERSON = "TestPerson"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = os.environ.get("WORKOUT_TRACKER_ROOT")
        os.environ["WORKOUT_TRACKER_ROOT"] = self._tmp.name
        import shared.person_paths as pp
        importlib.reload(pp)
        self.pp = pp
        self.plans_dir = Path(self._tmp.name) / "plans" / self.PERSON
        self.plans_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("WORKOUT_TRACKER_ROOT", None)
        else:
            os.environ["WORKOUT_TRACKER_ROOT"] = self._prev
        import shared.person_paths as pp
        importlib.reload(pp)
        self._tmp.cleanup()

    def write_plan(self, plan_date: str, body: str) -> None:
        (self.plans_dir / f"{plan_date}-workout.md").write_text(
            body, encoding="utf-8")


class BenchTests(LedgerHarness):
    # Two flexion movements so the D8 route guard has somewhere to fall
    # back to: benching the LAST member of a core pattern category is
    # refused, and a fixture with one core movement would test the guard
    # rather than the bench rule.
    ONE = ("## Workout 1: UPPER A\n"
           "- Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8\n"
           "- Ab Crunch Machine: 30kgx12 /// 30kgx12\n"
           "- Kneeling Cable Crunch: 20kgx12 /// 20kgx12\n")

    def _series(self, n: int) -> list[dict]:
        """``n`` weekly plans; the crunch machine gets done, the cable one
        never does, and the session itself always happens."""
        rows: list[dict] = []
        for i in range(n):
            day = date(2026, 6, 1) + __import__("datetime").timedelta(days=7 * i)
            self.write_plan(day.isoformat(), self.ONE)
            trained = (day + __import__("datetime").timedelta(days=1)).isoformat()
            rows += _sets(trained, "Dumbbell Flat Bench Press", 2, kg=50, reps=8)
            rows += _sets(trained, "Ab Crunch Machine", 2, kg=30, reps=12)
        return rows

    def test_two_unperformed_prescriptions_bench_the_exercise(self) -> None:
        rows = self._series(3)
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 25),
                              _CATALOG)
        benched = {b["exercise"]: b for b in out["benched"]}
        self.assertIn("Kneeling Cable Crunch", benched)
        self.assertGreaterEqual(benched["Kneeling Cable Crunch"]["prescribed_count"],
                                BENCH_THRESHOLD)
        self.assertNotIn("Dumbbell Flat Bench Press", benched)

    def test_one_unperformed_prescription_does_not_bench(self) -> None:
        rows = self._series(1)
        # The single window is closed (7+ days elapsed) but one miss is not
        # a pattern.
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 15),
                              _CATALOG)
        self.assertEqual(out["benched"], [])

    def test_the_still_open_window_does_not_accrue_toward_the_bench(self) -> None:
        # One closed window plus one written yesterday. Benching off a
        # two-day-old window would retire a movement the day after
        # prescribing it, which is not what "two unperformed
        # prescriptions" means.
        rows = self._series(1)
        self.write_plan("2026-06-14", self.ONE)
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 15),
                              _CATALOG)
        self.assertTrue(out["window_open"])
        self.assertEqual(out["plans_reconciled"], 2)
        self.assertEqual(out["windows_closed"], 1)
        self.assertEqual(out["benched"], [])

    def test_the_same_evidence_benches_once_the_window_closes(self) -> None:
        rows = self._series(1)
        self.write_plan("2026-06-14", self.ONE)
        # The second session HAPPENED — the crunch machine and the bench
        # press were logged, the cable crunch was not. That is a refusal,
        # and once the window closes it is the second one.
        rows += _sets("2026-06-15", "Dumbbell Flat Bench Press", 2, kg=50, reps=8)
        rows += _sets("2026-06-15", "Ab Crunch Machine", 2, kg=30, reps=12)
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 22),
                              _CATALOG)
        self.assertFalse(out["window_open"])
        self.assertEqual([b["exercise"] for b in out["benched"]],
                         ["Kneeling Cable Crunch"])

    def test_exactly_one_question_is_asked(self) -> None:
        rows = self._series(3)
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 25),
                              _CATALOG)
        self.assertIsNotNone(out["bench_prompt"])
        self.assertEqual(out["bench_prompt"]["exercise"], "Kneeling Cable Crunch")
        self.assertTrue(out["bench_prompt"]["ask_once"])

    def test_a_recorded_answer_stops_the_question(self) -> None:
        rows = self._series(3)
        record_bench_response(self.PERSON, "Kneeling Cable Crunch",
                              answer="no cable station free at that time",
                              disposition="retired", on_date="2026-06-25")
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 25),
                              _CATALOG)
        self.assertIsNone(out["bench_prompt"])
        benched = {b["exercise"]: b for b in out["benched"]}
        self.assertEqual(benched["Kneeling Cable Crunch"]["disposition"], "retired")
        self.assertEqual(benched["Kneeling Cable Crunch"]["answer"],
                         "no cable station free at that time")

    def test_a_retry_disposition_releases_the_bench(self) -> None:
        rows = self._series(3)
        record_bench_response(self.PERSON, "Kneeling Cable Crunch",
                              answer="machine was under repair, back now",
                              disposition="retry", on_date="2026-06-25")
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 25),
                              _CATALOG)
        self.assertEqual([b["exercise"] for b in out["benched"]], [])

    def test_the_answer_store_round_trips_and_is_idempotent(self) -> None:
        record_bench_response(self.PERSON, "Kneeling Cable Crunch",
                              answer="first", disposition="pending",
                              on_date="2026-06-25")
        record_bench_response(self.PERSON, "Kneeling Cable Crunch",
                              answer="second", disposition="retired",
                              on_date="2026-07-02")
        log = read_bench_log(self.PERSON)
        self.assertEqual(len(log["entries"]), 1)
        entry = log["entries"][0]
        self.assertEqual(entry["answer"], "second")
        self.assertEqual(entry["disposition"], "retired")
        # The first question date is the one that matters for "ask once".
        self.assertEqual(entry["asked_on"], "2026-06-25")

    def test_an_unreadable_store_reads_as_empty_not_as_a_crash(self) -> None:
        self.pp.bench_log_json(self.PERSON).write_text("{ not json",
                                                       encoding="utf-8")
        self.assertEqual(read_bench_log(self.PERSON),
                         {"version": 1, "entries": []})

    def test_a_substitution_does_not_accrue_toward_the_bench(self) -> None:
        plan = ("## Workout 1: LOWER A\n"
                "- Barbell Back Squat: 90kgx8 /// 90kgx8\n"
                "- Leg Extension: 55kgx12 /// 55kgx12\n")
        rows: list[dict] = []
        import datetime as _dt
        for i in range(3):
            day = date(2026, 6, 1) + _dt.timedelta(days=7 * i)
            self.write_plan(day.isoformat(), plan)
            trained = (day + _dt.timedelta(days=1)).isoformat()
            rows += _sets(trained, "Barbell Back Squat", 2, kg=90, reps=8)
            rows += _sets(trained, "Leg Press", 2, kg=200, reps=12)
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 25),
                              _CATALOG)
        self.assertEqual([b["exercise"] for b in out["benched"]], [])
        self.assertNotIn("Leg Extension",
                         {n["exercise"] for n in out["never_performed"]})

    def test_never_performed_reports_whether_it_was_ever_logged(self) -> None:
        rows = self._series(3)
        # A real Pallof Press session, long before the plans that asked
        # for it. "Never performed" must not read as "never, ever".
        rows += _sets("2026-01-05", "Kneeling Cable Crunch", 3, kg=20, reps=12)
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 25),
                              _CATALOG)
        entry = [n for n in out["never_performed"]
                 if n["exercise"] == "Kneeling Cable Crunch"][0]
        self.assertTrue(entry["ever_logged"])
        self.assertEqual(entry["last_logged"], "2026-01-05")

    def test_no_plans_on_disk_returns_none_not_zero_percent(self) -> None:
        self.assertIsNone(
            build_adherence(self.PERSON, [], _DB, date(2026, 6, 25), _CATALOG))

    def test_benched_and_never_performed_are_different_sets(self) -> None:
        """They overlap but are not the same list, and the difference is
        load-bearing: a movement performed once and then skipped twice is
        benched, and saying it was "never performed" about it would be
        false. Four plans; the cable crunch happens in the first window
        only, then stops."""
        rows = self._series(4)
        rows += _sets("2026-06-02", "Kneeling Cable Crunch", 2, kg=20, reps=12)
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 25),
                              _CATALOG)
        self.assertIn("Kneeling Cable Crunch",
                      {b["exercise"] for b in out["benched"]})
        self.assertNotIn("Kneeling Cable Crunch",
                         {n["exercise"] for n in out["never_performed"]})
        entry = [b for b in out["benched"]
                 if b["exercise"] == "Kneeling Cable Crunch"][0]
        self.assertTrue(entry["ever_logged"])
        self.assertEqual(entry["last_logged"], "2026-06-02")
        self.assertIn("consecutive", entry["reason"])


class SkippedSessionTests(LedgerHarness):
    """A skipped SESSION is not a refused EXERCISE.

    Two never-performed workouts benched eleven exercises in one go on
    real data, including every route to two of the five emphasis muscles.
    The user did not decline those movements; the session did not happen.
    """

    TWO_DAY = ("## Workout 1: UPPER A\n"
               "- Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8\n"
               "- Ab Crunch Machine: 30kgx12 /// 30kgx12\n"
               "\n## Workout 2: LOWER A\n"
               "- Barbell Back Squat: 90kgx8 /// 90kgx8\n"
               "- Seated Calf Raise: 80kgx12 /// 80kgx12\n")

    def _series(self, n: int) -> list[dict]:
        """``n`` weekly plans; the upper day always happens, the lower day
        never does."""
        import datetime as _dt
        rows: list[dict] = []
        for i in range(n):
            day = date(2026, 6, 1) + _dt.timedelta(days=7 * i)
            self.write_plan(day.isoformat(), self.TWO_DAY)
            trained = (day + _dt.timedelta(days=1)).isoformat()
            rows += _sets(trained, "Dumbbell Flat Bench Press", 2, kg=50, reps=8)
            rows += _sets(trained, "Ab Crunch Machine", 2, kg=30, reps=12)
        return rows

    def test_exercises_in_a_never_performed_session_do_not_bench(self) -> None:
        out = build_adherence(self.PERSON, self._series(4), _DB,
                              date(2026, 6, 25), _CATALOG)
        names = {b["exercise"] for b in out["benched"]}
        self.assertNotIn("Seated Calf Raise", names,
                         "the lower day never happened; the calf raise was "
                         "never put to the question")
        self.assertNotIn("Barbell Back Squat", names)

    def test_the_skipped_session_is_reported_as_its_own_signal(self) -> None:
        out = build_adherence(self.PERSON, self._series(4), _DB,
                              date(2026, 6, 25), _CATALOG)
        missed = {m["session"]: m for m in out["missed_sessions"]}
        self.assertIn("lower_a", missed)
        self.assertEqual(missed["lower_a"]["missed"], missed["lower_a"]["planned"])
        self.assertNotIn("upper_a", missed)

    def test_the_untested_count_is_carried_per_exercise(self) -> None:
        out = build_adherence(self.PERSON, self._series(4), _DB,
                              date(2026, 6, 25), _CATALOG)
        rows = {e["name"]: e for e in out["per_exercise"]}
        calf = rows["Seated Calf Raise"]
        self.assertEqual(calf["consecutive_unperformed"], 0)
        self.assertEqual(calf["prescriptions_tested"], 0)
        self.assertGreaterEqual(calf["sessions_missed"], 3)

    def test_an_exercise_skipped_inside_a_performed_session_still_benches(self) -> None:
        # The control: same fixture, but the movement sits in the session
        # that DID happen.
        import datetime as _dt
        plan = ("## Workout 1: UPPER A\n"
                "- Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8\n"
                "- Ab Crunch Machine: 30kgx12 /// 30kgx12\n"
                "- Kneeling Cable Crunch: 20kgx12 /// 20kgx12\n"
                "\n## Workout 2: LOWER A\n"
                "- Barbell Back Squat: 90kgx8 /// 90kgx8\n")
        rows: list[dict] = []
        for i in range(4):
            day = date(2026, 6, 1) + _dt.timedelta(days=7 * i)
            self.write_plan(day.isoformat(), plan)
            trained = (day + _dt.timedelta(days=1)).isoformat()
            rows += _sets(trained, "Dumbbell Flat Bench Press", 2, kg=50, reps=8)
            rows += _sets(trained, "Ab Crunch Machine", 2, kg=30, reps=12)
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 25),
                              _CATALOG)
        self.assertIn("Kneeling Cable Crunch",
                      {b["exercise"] for b in out["benched"]})

    def test_two_completion_rates_split_attendance_from_truncation(self) -> None:
        out = build_adherence(self.PERSON, self._series(2), _DB,
                              date(2026, 6, 15), _CATALOG)
        # 8 prescribed across both workouts, 4 of them into the session
        # that happened, all 4 performed.
        self.assertEqual(out["sets_prescribed"], 8)
        self.assertEqual(out["sets_prescribed_tested"], 4)
        self.assertEqual(out["sets_performed"], 4)
        self.assertEqual(out["completion_rate"], 0.5)
        self.assertEqual(out["tested_completion_rate"], 1.0)

    def test_the_headline_denominator_still_counts_skipped_sessions(self) -> None:
        # Otherwise a coach could load volume into the session it expects
        # to be skipped and watch its adherence number improve.
        out = build_adherence(self.PERSON, self._series(2), _DB,
                              date(2026, 6, 15), _CATALOG)
        self.assertEqual(out["sets_prescribed"], 8)
        self.assertLess(out["completion_rate"], out["tested_completion_rate"])


class RouteGuardTests(LedgerHarness):
    """Benching must not collide with D8. Removing every route to an
    emphasis muscle while the same payload demands mid-MAV volume on it
    hands the coach two instructions it cannot both obey."""

    PLAN = ("## Workout 1: UPPER A\n"
            "- Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8\n"
            "- Cable Pallof Press: 20kgx12 /// 20kgx12\n"
            "- Kneeling Cable Crunch: 20kgx12 /// 20kgx12\n"
            "- Ab Crunch Machine: 30kgx12 /// 30kgx12\n")

    def _series(self, n: int = 4) -> list[dict]:
        import datetime as _dt
        rows: list[dict] = []
        for i in range(n):
            day = date(2026, 6, 1) + _dt.timedelta(days=7 * i)
            self.write_plan(day.isoformat(), self.PLAN)
            trained = (day + _dt.timedelta(days=1)).isoformat()
            rows += _sets(trained, "Dumbbell Flat Bench Press", 2, kg=50, reps=8)
            rows += _sets(trained, "Ab Crunch Machine", 2, kg=30, reps=12)
        return rows

    def test_the_last_member_of_a_core_category_is_not_benched(self) -> None:
        out = build_adherence(self.PERSON, self._series(), _DB,
                              date(2026, 6, 25), _CATALOG,
                              priority_tiers={"core": "emphasis"})
        blocked = {b["exercise"]: b for b in out["bench_blocked"]}
        self.assertIn("Cable Pallof Press", blocked)
        self.assertIn("Anti-Rotation", blocked["Cable Pallof Press"]["blocked_reason"])
        self.assertNotIn("Cable Pallof Press",
                         {b["exercise"] for b in out["benched"]})

    def test_a_category_with_alternatives_still_benches(self) -> None:
        # Kneeling Cable Crunch is flexion, and so is the Ab Crunch
        # Machine actually being done — benching it strands nothing.
        out = build_adherence(self.PERSON, self._series(), _DB,
                              date(2026, 6, 25), _CATALOG,
                              priority_tiers={"core": "emphasis"})
        self.assertIn("Kneeling Cable Crunch",
                      {b["exercise"] for b in out["benched"]})

    def test_an_emphasis_muscle_keeps_two_routes(self) -> None:
        # Only one hamstring movement is on record, so benching it would
        # leave an emphasis muscle with none.
        import datetime as _dt
        plan = ("## Workout 1: LOWER A\n"
                "- Barbell Back Squat: 90kgx8 /// 90kgx8\n"
                "- Leg Curl (Lying): 40kgx12 /// 40kgx12\n")
        rows: list[dict] = []
        for i in range(4):
            day = date(2026, 6, 1) + _dt.timedelta(days=7 * i)
            self.write_plan(day.isoformat(), plan)
            rows += _sets((day + _dt.timedelta(days=1)).isoformat(),
                          "Barbell Back Squat", 2, kg=90, reps=8)
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 25),
                              _CATALOG,
                              priority_tiers={"hamstrings": "emphasis"})
        blocked = {b["exercise"] for b in out["bench_blocked"]}
        self.assertIn("Leg Curl (Lying)", blocked)

    def test_a_maintenance_muscle_needs_only_one_route(self) -> None:
        import datetime as _dt
        plan = ("## Workout 1: LOWER A\n"
                "- Barbell Back Squat: 90kgx8 /// 90kgx8\n"
                "- Leg Curl (Lying): 40kgx12 /// 40kgx12\n"
                "- Leg Curl (Seated): 40kgx12 /// 40kgx12\n")
        rows: list[dict] = []
        for i in range(4):
            day = date(2026, 6, 1) + _dt.timedelta(days=7 * i)
            self.write_plan(day.isoformat(), plan)
            trained = (day + _dt.timedelta(days=1)).isoformat()
            rows += _sets(trained, "Barbell Back Squat", 2, kg=90, reps=8)
            rows += _sets(trained, "Leg Curl (Seated)", 2, kg=40, reps=12)
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 25),
                              _CATALOG,
                              priority_tiers={"hamstrings": "maintain"})
        self.assertIn("Leg Curl (Lying)",
                      {b["exercise"] for b in out["benched"]})

    def test_a_blocked_exercise_owns_the_question(self) -> None:
        out = build_adherence(self.PERSON, self._series(), _DB,
                              date(2026, 6, 25), _CATALOG,
                              priority_tiers={"core": "emphasis"})
        prompt = out["bench_prompt"]
        self.assertEqual(prompt["kind"], "route_blocked")
        self.assertEqual(prompt["exercise"], "Cable Pallof Press")
        self.assertIn("different exercise", prompt["question"])

    def test_without_tiers_everything_falls_to_the_permissive_floor(self) -> None:
        out = build_adherence(self.PERSON, self._series(), _DB,
                              date(2026, 6, 25), _CATALOG)
        # Core still has the Ab Crunch Machine, so the muscle floor of 1
        # is met; only the empty Anti-Rotation category blocks.
        self.assertEqual([b["exercise"] for b in out["bench_blocked"]],
                         ["Cable Pallof Press"])


class WindowTests(LedgerHarness):
    def test_a_window_ends_where_the_next_plan_begins(self) -> None:
        for d in ("2026-06-01", "2026-06-08", "2026-06-15"):
            self.write_plan(d, "## Workout 1: UPPER A\n- Dip: 10 /// 10\n")
        plans = load_plans(self.PERSON, date(2026, 6, 20))
        windows = plan_windows(plans, date(2026, 6, 20))
        self.assertEqual([(s.isoformat(), e.isoformat())
                          for _, s, e in windows],
                         [("2026-06-01", "2026-06-08"),
                          ("2026-06-08", "2026-06-15"),
                          ("2026-06-15", "2026-06-21")])

    def test_plans_after_the_anchor_are_invisible(self) -> None:
        self.write_plan("2026-06-01", "## Workout 1: UPPER A\n- Dip: 10\n")
        self.write_plan("2026-07-20", "## Workout 1: UPPER A\n- Dip: 10\n")
        plans = load_plans(self.PERSON, date(2026, 6, 20))
        self.assertEqual([p["plan_date"] for p in plans], ["2026-06-01"])


# ---------------------------------------------------------------------------
class DoseStalenessTests(unittest.TestCase):
    """70% of carried exercises returned with an unchanged load. The
    target is under 40%, and a target on 'did the number change' invites
    changing it by an amount no muscle can detect."""

    def _plans(self, doses: list[str]) -> list[dict]:
        out = []
        for i, dose in enumerate(doses):
            day = f"2026-06-{1 + 7 * i:02d}"
            out.append(parse_plan(
                f"## Workout 1: UPPER A\n- Dumbbell Flat Bench Press: {dose}\n",
                day))
        return out

    def test_an_unchanged_dose_is_reported_as_unchanged(self) -> None:
        out = dose_staleness(self._plans(["50kgx8 /// 50kgx8",
                                          "50kgx8 /// 50kgx8"]), _DB)
        c = out["carried"][0]
        self.assertFalse(c["dose_changed"])
        self.assertEqual(c["change_kind"], "none")
        self.assertEqual(out["unchanged_pct"], 1.0)
        self.assertFalse(out["meets_target"])

    def test_a_real_load_increase_counts(self) -> None:
        out = dose_staleness(self._plans(["50kgx8 /// 50kgx8",
                                          "55kgx8 /// 55kgx8"]), _DB)
        c = out["carried"][0]
        self.assertTrue(c["dose_changed"])
        self.assertEqual(c["change_kind"], "load_up")

    def test_a_sub_threshold_load_bump_is_cosmetic_not_a_change(self) -> None:
        # The cheapest way to satisfy "the dose must change" is to change
        # it by less than the plates allow.
        out = dose_staleness(self._plans(["100kgx8 /// 100kgx8",
                                          "100.5kgx8 /// 100.5kgx8"]), _DB)
        c = out["carried"][0]
        self.assertFalse(c["dose_changed"])
        self.assertEqual(c["change_kind"], "cosmetic")

    def test_a_rep_range_widened_by_half_a_rep_is_cosmetic(self) -> None:
        out = dose_staleness(self._plans(["50kgx8-10 /// 50kgx8-10",
                                          "50kgx8-11 /// 50kgx8-11"]), _DB)
        self.assertFalse(out["carried"][0]["dose_changed"])

    def test_a_whole_rep_of_midpoint_movement_counts(self) -> None:
        out = dose_staleness(self._plans(["50kgx8 /// 50kgx8",
                                          "50kgx10 /// 50kgx10"]), _DB)
        c = out["carried"][0]
        self.assertTrue(c["dose_changed"])
        self.assertEqual(c["change_kind"], "reps_up")

    def test_a_rep_only_progression_still_shows_as_unchanged_load(self) -> None:
        # The measured 70% baseline counted load only. Redefining the
        # metric to include rep moves is correct, and is also how a target
        # gets hit without the weight ever going up — so both are
        # reported, and this is the number that catches it.
        out = dose_staleness(self._plans(["50kgx8 /// 50kgx8",
                                          "50kgx10 /// 50kgx10"]), _DB)
        self.assertEqual(out["unchanged_pct"], 0.0)
        self.assertEqual(out["unchanged_load_pct"], 1.0)

    def test_generations_static_counts_the_trailing_run(self) -> None:
        out = dose_staleness(self._plans(["50kgx8", "55kgx8", "55kgx8",
                                          "55kgx8"]), _DB)
        self.assertEqual(out["carried"][0]["generations_static"], 2)

    def test_oscillating_between_two_loads_is_flagged(self) -> None:
        # 90 / 92.5 / 90 / 92.5 changes the dose every generation and
        # progresses nothing.
        out = dose_staleness(self._plans(["90kgx8", "92.5kgx8", "90kgx8",
                                          "92.5kgx8"]), _DB)
        self.assertTrue(out["carried"][0]["oscillating"])
        self.assertEqual(out["oscillating_count"], 1)

    def test_warmups_do_not_pad_the_denominator(self) -> None:
        plans = [parse_plan("## Workout 1: UPPER A\n"
                            "- Jumping Jacks: 50\n"
                            "- Dumbbell Flat Bench Press: 50kgx8\n", d)
                 for d in ("2026-06-01", "2026-06-08")]
        out = dose_staleness(plans, _DB)
        self.assertEqual([c["exercise"] for c in out["carried"]],
                         ["Dumbbell Flat Bench Press"])

    def test_an_exercise_not_carried_forward_is_excluded(self) -> None:
        plans = [
            parse_plan("## Workout 1: UPPER A\n- Dip: 10 /// 10\n", "2026-06-01"),
            parse_plan("## Workout 1: UPPER A\n- Pull-Up: 8 /// 8\n", "2026-06-08"),
        ]
        self.assertIsNone(dose_staleness(plans, _DB))

    def test_a_single_plan_has_nothing_to_compare(self) -> None:
        self.assertIsNone(dose_staleness(self._plans(["50kgx8"]), _DB))


# ---------------------------------------------------------------------------
class RetiredRouteTests(LedgerHarness):
    """The route pool was built from logged history and the newest plan
    alone. An exercise the D5 flow RETIRED still counted as a live route
    and kept protecting a muscle it can never be prescribed for again, so
    the guard refused the next bench while the muscle was in fact already
    stranded below its tier floor."""

    # Three routes into side delts. The cable raise is prescribed and
    # done; the machine is prescribed and never done, so it is the bench
    # candidate. The dumbbell raise is the interesting one — it has real
    # logged history but is no longer prescribed, so it sits in the pool
    # and is never itself a candidate, and `by_muscle.discard` (which
    # does work, and is not the bug) never touches it.
    PLAN = ("## Workout 1: UPPER A\n"
            "- Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8\n"
            "- Cable Lateral Raise: 10kgx12 /// 10kgx12\n"
            "- Lateral Raise Machine: 20kgx12 /// 20kgx12\n")

    def _series(self, n: int = 4) -> list[dict]:
        import datetime as _dt
        # Logged once, months ago, and never prescribed since.
        rows: list[dict] = _sets("2026-03-02", "Dumbbell Lateral Raise", 3,
                                 kg=10, reps=12)
        for i in range(n):
            day = date(2026, 6, 1) + _dt.timedelta(days=7 * i)
            self.write_plan(day.isoformat(), self.PLAN)
            trained = (day + _dt.timedelta(days=1)).isoformat()
            rows += _sets(trained, "Dumbbell Flat Bench Press", 2, kg=50, reps=8)
            rows += _sets(trained, "Cable Lateral Raise", 2, kg=10, reps=12)
        return rows

    TIERS = {"side_delts": "emphasis"}

    def test_before_any_answer_the_pool_has_room_for_the_bench(self) -> None:
        out = build_adherence(self.PERSON, self._series(), _DB,
                              date(2026, 6, 25), _CATALOG,
                              priority_tiers=self.TIERS)
        self.assertIn("Lateral Raise Machine",
                      {b["exercise"] for b in out["benched"]})
        self.assertFalse(out["bench_blocked"])

    def test_a_retired_exercise_stops_counting_as_a_route(self) -> None:
        # The user answers the D5 question: that movement is out for
        # good. Side delts are now down to two usable routes, and
        # benching the machine would leave one — under the emphasis
        # floor. The guard has to refuse it and ASK, which is the whole
        # point of the guard; instead it kept waving the bench through
        # because a movement the user had already refused still counted.
        record_bench_response(self.PERSON, "Dumbbell Lateral Raise",
                              answer="no space for it",
                              disposition="retired", on_date="2026-06-26")
        out = build_adherence(self.PERSON, self._series(), _DB,
                              date(2026, 6, 27), _CATALOG,
                              priority_tiers=self.TIERS)
        blocked = {b["exercise"]: b for b in out["bench_blocked"] or []}
        self.assertIn("Lateral Raise Machine", blocked)
        self.assertIn("side_delts", blocked["Lateral Raise Machine"]["blocked_reason"])
        self.assertIn("1 usable route",
                      blocked["Lateral Raise Machine"]["blocked_reason"])
        self.assertNotIn("Lateral Raise Machine",
                         {b["exercise"] for b in out["benched"]})

    def test_a_retry_disposition_keeps_the_route(self) -> None:
        # Only ``retired`` removes a route. ``retry`` says the obstacle
        # was circumstantial and the movement may come back, so it still
        # counts toward the floor and the bench goes through.
        record_bench_response(self.PERSON, "Dumbbell Lateral Raise",
                              answer="machine was taken",
                              disposition="retry", on_date="2026-06-26")
        out = build_adherence(self.PERSON, self._series(), _DB,
                              date(2026, 6, 27), _CATALOG,
                              priority_tiers=self.TIERS)
        self.assertIn("Lateral Raise Machine",
                      {b["exercise"] for b in out["benched"]})
        self.assertFalse(out["bench_blocked"])


# ---------------------------------------------------------------------------
class SilentParseFailureTests(unittest.TestCase):
    """Every one of these produced zero sets and no error. As long as one
    other workout in the file parsed, `parse_errors` stayed empty and the
    prescription vanished from the ledger — the same failure class as the
    `## Deload Session` bug this module was written to close."""

    GOOD = "## Workout 1: LOWER A\n- Barbell Back Squat: 90kgx8 /// 90kgx8\n"

    def test_a_heading_that_misses_the_grammar_is_reported(self) -> None:
        for heading in ("## Deload Workout 1: LOWER A",
                        "## Workout One: LOWER A",
                        "## Workout 1 - LOWER A"):
            with self.subTest(heading=heading):
                out = parse_plan(
                    self.GOOD + f"\n{heading}\n- Leg Press: 200kgx12\n",
                    "2026-08-02")
                self.assertEqual(len(out["workouts"]), 1,
                                 "the near-miss section is not walked")
                self.assertTrue(
                    any("does not match" in e for e in out["parse_errors"]),
                    out["parse_errors"])

    def test_a_real_heading_is_not_flagged(self) -> None:
        for heading in ("## Workout 2: UPPER A", "## Deload Session 2: PUSH",
                        "## Session 3: PULL", "## Workout A: PUSH"):
            with self.subTest(heading=heading):
                out = parse_plan(
                    self.GOOD + f"\n{heading}\n- Leg Press: 200kgx12\n",
                    "2026-08-02")
                self.assertEqual(out["parse_errors"], [])
                self.assertEqual(len(out["workouts"]), 2)

    def test_a_bullet_that_parses_to_nothing_is_reported(self) -> None:
        out = parse_plan(
            self.GOOD + "- Cable Pallof Press: as many as feel good\n",
            "2026-08-02")
        self.assertTrue(any("matched no known form" in e
                            for e in out["parse_errors"]), out["parse_errors"])

    def test_a_partial_failure_inside_one_bullet_is_reported(self) -> None:
        # The dangerous shape: half the spec parses, so the bullet has
        # sets and the shortfall is invisible.
        out = parse_plan(
            "## Workout 1: LOWER A\n"
            "- Barbell Back Squat: 90kgx8 /// as heavy as feels right\n",
            "2026-08-02")
        slot = out["workouts"][0]["slots"][0]
        self.assertEqual(slot["prescribed_sets"], 1)
        self.assertTrue(any("matched no known form" in e
                            for e in out["parse_errors"]), out["parse_errors"])

    def test_sets_x_reps_at_load_is_read_not_dropped(self) -> None:
        # `- Barbell Back Squat: 4 x 8 @ 90kg` gave 0 sets and no error.
        out = parse_plan("## Workout 1: LOWER A\n"
                         "- Barbell Back Squat: 4 x 8 @ 90kg\n", "2026-08-02")
        slot = out["workouts"][0]["slots"][0]
        self.assertEqual(slot["prescribed_sets"], 4)
        self.assertEqual(slot["load_kg"], 90.0)
        self.assertEqual(slot["rep_lo"], 8)
        self.assertEqual(out["parse_errors"], [])

    def test_a_bodyweight_prefix_is_read(self) -> None:
        # Three of the four movements W6a added to the catalog are [BW].
        out = parse_plan("## Workout 1: CORE\n"
                         "- Hanging Leg Raise: bodyweight x 12 "
                         "/// bodyweight x 12\n", "2026-08-02")
        self.assertEqual(out["workouts"][0]["slots"][0]["prescribed_sets"], 2)
        self.assertEqual(out["parse_errors"], [])

    def test_a_per_side_bodyweight_count_is_read(self) -> None:
        # Live in the corpus: `Dead Bug: 10 per side`, `Russian Twist: 15
        # per side`. Three real core prescriptions counted as zero sets,
        # on an emphasis muscle.
        out = parse_plan("## Workout 1: CORE\n"
                         "- Dead Bug: 10 per side /// 10 per side\n",
                         "2026-08-02")
        self.assertEqual(out["workouts"][0]["slots"][0]["prescribed_sets"], 2)
        self.assertEqual(out["parse_errors"], [])

    def test_a_duration_bullet_is_a_note_not_an_error(self) -> None:
        # `Rowing Machine: 3 min` is read and is correctly worth zero. It
        # is still said out loud, in the channel that does not cry wolf.
        out = parse_plan(self.GOOD + "- Rowing Machine: 3 min\n", "2026-08-02")
        self.assertEqual(out["parse_errors"], [])
        self.assertTrue(any("prescribes no working sets"
                            for n in out["parse_notes"]))
        self.assertEqual(out["workouts"][0]["slots"][1]["prescribed_sets"], 0)


# ---------------------------------------------------------------------------
class OvershootTests(unittest.TestCase):
    """`completion_rate` read 111% overall and 118% on isolation. The
    spec's success metric is "prescribed volume performed >= 85%", and a
    metric that can exceed 1.0 is not measuring that: extra curl sets
    were silently paying for skipped shrug sets."""

    PLAN = ("## Workout 1: UPPER A\n"
            "- Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8\n"
            "- Dumbbell Shrug: 60kgx12 /// 60kgx12\n")

    def _rec(self, bench_sets, shrug_sets):
        plan = parse_plan(self.PLAN, "2026-06-01")
        rows = (_sets("2026-06-02", "Dumbbell Flat Bench Press", bench_sets,
                      kg=50, reps=8)
                + _sets("2026-06-02", "Dumbbell Shrug", shrug_sets,
                        kg=60, reps=12))
        return reconcile_plan(plan, date(2026, 6, 1), date(2026, 6, 8),
                              rows, _DB, _CATALOG)

    def test_extra_sets_do_not_pay_for_skipped_ones(self) -> None:
        # Four bench sets against two prescribed, zero shrugs against
        # two. Four of four sets performed, half the prescription done.
        rec = self._rec(4, 0)
        self.assertEqual(rec["sets_prescribed"], 4)
        self.assertEqual(rec["sets_performed"], 4)
        self.assertEqual(rec["sets_credited"], 2)
        self.assertEqual(rec["sets_overshoot"], 2)
        self.assertEqual(rec["completion_rate"], 0.5)

    def test_no_per_exercise_rate_exceeds_one(self) -> None:
        rec = self._rec(4, 2)
        by = {e["name"]: e for e in rec["per_exercise"]}
        self.assertEqual(by["Dumbbell Flat Bench Press"]["completion_rate"], 1.0)
        self.assertEqual(by["Dumbbell Flat Bench Press"]["performed_sets"], 4)
        self.assertEqual(by["Dumbbell Flat Bench Press"]["overshoot_sets"], 2)
        self.assertEqual(rec["completion_rate"], 1.0)

    def test_the_isolation_split_is_capped_too(self) -> None:
        rec = self._rec(2, 6)
        self.assertLessEqual(rec["isolation_completion_rate"], 1.0)
        self.assertLessEqual(rec["compound_completion_rate"], 1.0)

    def test_an_exact_execution_still_reads_one(self) -> None:
        rec = self._rec(2, 2)
        self.assertEqual(rec["completion_rate"], 1.0)
        self.assertIsNone(rec["sets_overshoot"])


# ---------------------------------------------------------------------------
class ClosedWindowRateTests(LedgerHarness):
    """The headline rates describe the newest window, which is OPEN on
    the generation that writes it — so every one of them reads 0 that
    day. Any consumer thresholding on them flips answer depending on
    whether the plan file happens to exist yet: the block's at-risk set
    went from 17 findings to 23 on identical inputs."""

    PLAN = ("## Workout 1: UPPER A\n"
            "- Dumbbell Flat Bench Press: 50kgx8 /// 50kgx8\n"
            "- Dumbbell Shrug: 60kgx12 /// 60kgx12\n")

    def test_the_closed_rate_ignores_the_open_window(self) -> None:
        import datetime as _dt
        rows: list[dict] = []
        for i in range(3):
            day = date(2026, 6, 1) + _dt.timedelta(days=7 * i)
            self.write_plan(day.isoformat(), self.PLAN)
            trained = (day + _dt.timedelta(days=1)).isoformat()
            rows += _sets(trained, "Dumbbell Flat Bench Press", 2, kg=50, reps=8)
            rows += _sets(trained, "Dumbbell Shrug", 2, kg=60, reps=12)
        # A fourth plan written today: its window is one day old and
        # nothing in it has happened yet.
        self.write_plan("2026-06-22", self.PLAN)
        out = build_adherence(self.PERSON, rows, _DB, date(2026, 6, 22),
                              _CATALOG)
        self.assertTrue(out["window_open"])
        by = {e["name"]: e for e in out["per_exercise"]}
        self.assertEqual(by["Dumbbell Shrug"]["completion_rate"], 0.0,
                         "the open window is honestly empty")
        self.assertEqual(by["Dumbbell Shrug"]["closed_completion_rate"], 1.0,
                         "and the closed history says it happens every time")


if __name__ == "__main__":
    unittest.main()
