"""Check a `/coach` assessment and workout plan.

Inputs:
  --tracker     path to JSON from read_tracker.py (or "-" for stdin)
  --coach       path to coach_reads.json
  --workout-md  path to <date>-workout.md

Runs the shared plan checks, prints warnings and errors to stderr, and
writes nothing. Exit 0 means the plan passed every blocking check; exit
2 means fix the plan and rerun. The assessment must be saved before the
workout markdown because the plan builds on the saved assessment.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(_SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILLS_ROOT))

from workout_coach.lib.plan_checks import run_plan_checks


def order_error(coach_path, workout_md_path) -> "str | None":
    """Why the files are in the wrong order on disk, or None."""
    coach_m = Path(coach_path).stat().st_mtime
    plan_m = Path(workout_md_path).stat().st_mtime
    if coach_m < plan_m:
        return None
    return (f"{coach_path} is not older than {workout_md_path}. The plan "
            "must be written after coach_reads.json is saved: re-read "
            "coach_reads.json and rewrite the plan.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", required=True, help="Path to tracker JSON, or - for stdin")
    ap.add_argument("--coach", required=True, help="Path to coach_reads.json")
    ap.add_argument("--workout-md", required=True, help="Path to the workout markdown")
    args = ap.parse_args(argv)

    if args.tracker == "-":
        j = json.load(sys.stdin)
    else:
        j = json.loads(Path(args.tracker).read_text(encoding="utf-8"))

    problem = order_error(args.coach, args.workout_md)
    if problem:
        print(f"file order error: {problem}", file=sys.stderr)
        return 2

    checks = run_plan_checks(j, args.coach, args.workout_md)
    if checks.exit_code:
        return checks.exit_code
    print(f"plan checks passed: {args.workout_md} "
          f"({len(checks.warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
