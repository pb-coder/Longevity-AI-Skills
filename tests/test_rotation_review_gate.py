"""Rotation heuristics require review without becoming hard prescription rules."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_check_plan import CHECK_PLAN, SKILLS_ROOT, _GOOD_COACH, _write_inputs
from test_w3a_enforcement import (_PLAN_COMPLIANT, _PLAN_CORE_DEFICIENT,
                                  _ROTATION_PREV_BLOCK)


class RotationReviewGateTests(unittest.TestCase):
    def check(self, plan, *, block=True, accept=False):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            tracker = {"today": "2026-08-02", "target_working_sets": 24}
            if block:
                tracker["block"] = _ROTATION_PREV_BLOCK
            _write_inputs(tmp, tracker, _GOOD_COACH, plan)
            command = [sys.executable, str(CHECK_PLAN),
                       "--tracker", str(tmp / "tracker.json"),
                       "--coach", str(tmp / "coach.json"),
                       "--workout-md", str(tmp / "workout.md")]
            if accept:
                command.append("--accept-rotation-advisories")
            return subprocess.run(command, cwd=SKILLS_ROOT, capture_output=True, text=True)

    def test_findings_require_explicit_review(self):
        result = self.check(_PLAN_COMPLIANT)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("rotation review required", result.stderr)
        self.assertIn("unchanged from the previous block", result.stderr)
        self.assertNotIn("plan checks passed", result.stdout)

    def test_acceptance_preserves_warnings_and_never_bypasses_errors(self):
        accepted = self.check(_PLAN_COMPLIANT, accept=True)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("unchanged from the previous block", accepted.stderr)
        invalid = self.check(_PLAN_CORE_DEFICIENT, accept=True)
        self.assertEqual(invalid.returncode, 2, invalid.stderr)
        self.assertIn("workout_md validation error", invalid.stderr)

    def test_no_previous_block_has_no_rotation_review(self):
        result = self.check(_PLAN_COMPLIANT, block=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("rotation review required", result.stderr)


if __name__ == "__main__":
    unittest.main()
