"""The assessment and workout plan checks run without writing files."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_w3a_enforcement import _PLAN_COMPLIANT, _PLAN_CORE_DEFICIENT

SKILLS_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILLS_ROOT / "workout-coach" / "scripts"
CHECK_PLAN = SCRIPTS / "check_plan.py"

_GOOD_COACH = {"headline": "Train as planned.", "cards": {}}


def _write_inputs(tmp: Path, tracker, coach, workout_md: str) -> None:
    (tmp / "tracker.json").write_text(json.dumps(tracker), encoding="utf-8")
    (tmp / "coach.json").write_text(json.dumps(coach), encoding="utf-8")
    (tmp / "workout.md").write_text(workout_md, encoding="utf-8")
    # The plan is written after the assessment, as the pipeline requires.
    now = time.time()
    os.utime(tmp / "coach.json", (now - 60, now - 60))
    os.utime(tmp / "workout.md", (now, now))


def _check(tmp: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK_PLAN),
         "--tracker", str(tmp / "tracker.json"),
         "--coach", str(tmp / "coach.json"),
         "--workout-md", str(tmp / "workout.md")],
        cwd=SKILLS_ROOT, capture_output=True, text=True)




class PlanCheckFindingsTests(unittest.TestCase):
    """Passing and rejected plans keep their diagnostic behavior."""

    CASES = {
        "passing plan": (
            {"today": "2026-08-02", "target_working_sets": 24},
            _GOOD_COACH, _PLAN_COMPLIANT, 0),
        "core floor blocks": (
            {"today": "2026-08-02", "target_working_sets": 24},
            _GOOD_COACH, _PLAN_CORE_DEFICIENT, 2),
        "coach copy blocks": (
            {"today": "2026-08-02"},
            {"headline": "Train — as planned.", "cards": {}},
            _PLAN_COMPLIANT, 2),
        "tracker payload blocks": (
            {"today": "2026-08-02", "core_week_spec": "nope"},
            _GOOD_COACH, _PLAN_COMPLIANT, 2),
    }

    def test_each_case_returns_the_expected_result(self) -> None:
        for name, (tracker, coach, md, expected) in self.CASES.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                _write_inputs(tmp, tracker, coach, md)
                checked = _check(tmp)
                self.assertEqual(checked.returncode, expected, checked.stderr)
                if expected:
                    self.assertTrue(checked.stderr.strip(),
                                    "a refusal must say why")

    def test_a_passing_plan_still_reports_its_warnings(self) -> None:
        # The set budget is advisory: an over-budget plan passes, and the
        # warning is printed on the default path too, not only in the report.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write_inputs(tmp, {"today": "2026-08-02", "target_working_sets": 4},
                          _GOOD_COACH, _PLAN_COMPLIANT)
            checked = _check(tmp)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("workout_md plan warning:", checked.stderr)


class WritesNothingTests(unittest.TestCase):

    def test_no_html_and_no_other_file_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write_inputs(tmp, {"today": "2026-08-02", "target_working_sets": 24},
                          _GOOD_COACH, _PLAN_COMPLIANT)
            before = sorted(p.name for p in tmp.iterdir())
            proc = _check(tmp)
            after = sorted(p.name for p in tmp.iterdir())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(before, after)
        self.assertIn("plan checks passed:", proc.stdout)


class FileOrderTests(unittest.TestCase):
    """coach_reads.json must be saved before the plan is written."""

    def _run_with_mtimes(self, coach_age: float, plan_age: float):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write_inputs(tmp, {"today": "2026-08-02", "target_working_sets": 24},
                          _GOOD_COACH, _PLAN_COMPLIANT)
            now = time.time()
            os.utime(tmp / "coach.json", (now - coach_age, now - coach_age))
            os.utime(tmp / "workout.md", (now - plan_age, now - plan_age))
            return _check(tmp)

    def test_a_plan_older_than_its_assessment_is_refused(self) -> None:
        checked = self._run_with_mtimes(coach_age=0, plan_age=60)
        self.assertEqual(checked.returncode, 2)
        self.assertIn("file order error:", checked.stderr)

    def test_equal_timestamps_are_refused(self) -> None:
        checked = self._run_with_mtimes(coach_age=30, plan_age=30)
        self.assertEqual(checked.returncode, 2)
        self.assertIn("file order error:", checked.stderr)


class OneSourceOfTruthTests(unittest.TestCase):
    """The public CLI calls the shared sequence without copying it."""

    _VALIDATORS = ("validate_tracker_json(", "payload_spec_errors(",
                   "validate_coach_reads(", "validate_workout_md(",
                   "validate_workout_plan(")

    def test_cli_runs_the_shared_sequence(self) -> None:
        for script in (CHECK_PLAN,):
            with self.subTest(script=script.name):
                src = script.read_text(encoding="utf-8")
                self.assertIn("run_plan_checks(j, args.coach, args.workout_md)", src)
                for name in self._VALIDATORS:
                    self.assertNotIn(name, src,
                                     f"{script.name} calls {name} directly")


class TierAbLighterStrengthTests(unittest.TestCase):
    """Option 2 on a Tier A / B ask must be a plan the checks accept.

    `substitute-protocols.md` tells the coach to write lighter strength
    against the unmodified tracker JSON. Both tiers are declared
    deloads, so a lighter plan must pass rather than be refused.
    """

    def _run(self, session_rec):
        tracker = {"today": "2026-08-02", "target_working_sets": 24,
                   "session_recommendation": session_rec}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _write_inputs(tmp, tracker, _GOOD_COACH, _PLAN_COMPLIANT)
            return _check(tmp)

    def test_tier_b_judges_sessions_against_the_halved_budget(self) -> None:
        proc = self._run({"tier": "B", "label": "reactive_deload"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("vs budget 12", proc.stderr)

    def test_tier_a_judges_sessions_against_the_halved_budget(self) -> None:
        # It used to be 0, which the budget check skips, so lighter
        # strength on a Tier A day had no set ceiling at all.
        proc = self._run({"tier": "A", "label": "rest"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("vs budget 12", proc.stderr)


class NoCardioInPlanDocsTests(unittest.TestCase):
    """Plans are strength only; the authoring docs must not say otherwise.

    The fix is in how plans are generated, so the guard is on the
    instructions the coach writes from.
    """

    COACH = SKILLS_ROOT / "workout-coach"

    def _read(self, rel: str) -> str:
        return (self.COACH / rel).read_text(encoding="utf-8")

    def test_no_template_carries_a_cardio_section(self) -> None:
        for rel in ("SKILL.md", "references/substitute-protocols.md"):
            with self.subTest(doc=rel):
                headings = [ln for ln in self._read(rel).splitlines()
                            if ln.startswith("## ")
                            and any(w in ln.lower() for w in
                                    ("cardio", "zone 2", "interval"))]
                self.assertEqual(headings, [])

    def test_no_template_prescribes_zone_2_or_a_walk(self) -> None:
        text = self._read("references/substitute-protocols.md")
        bullets = [ln for ln in text.splitlines()
                   if ln.lstrip().startswith(("- ", "— "))
                   and any(w in ln.lower() for w in ("zone 2", "walk"))]
        self.assertEqual(bullets, [])

    def test_the_old_cardio_default_is_gone(self) -> None:
        self.assertNotIn("Cardio-in-plan is the default",
                         self._read("references/common-mistakes.md"))
        self.assertNotIn("add cardio sessions to the plan",
                         self._read("SKILL.md"))

    def test_the_pipeline_checks_every_run(self) -> None:
        skill = self._read("SKILL.md")
        self.assertIn("scripts/check_plan.py", skill)
        self.assertNotIn("scripts/render_dashboard.py", skill)
        self.assertIn("Tier A or B: stop here and ask", skill)


if __name__ == "__main__":
    unittest.main()
