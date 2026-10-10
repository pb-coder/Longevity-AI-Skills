"""The one check sequence every `/coach` plan must pass.

Two scripts run it and neither owns it:

* ``scripts/check_plan.py`` — the default `/coach` path. Runs these
  checks and writes nothing.
* ``scripts/render_dashboard.py`` — the opt-in report. Runs the SAME
  checks, and renders only when they pass.

The checks used to live inline in the renderer's ``main()``, so making
the report optional would have made the checks optional with it: a plan
written without a report would ship with no core / arm floor, no set
budget and no opener cross-check. One function, two callers, so the two
paths cannot drift apart.

Stage order and early exit are part of the contract: tracker payload,
then ``coach_reads.json``, then the workout markdown's copy, then the
prescription content. A failing stage stops the sequence, and the files
for later stages are not even read, so a broken tracker JSON reports as
a tracker error and not as whatever the next stage trips on.

Every message is printed to stderr with the same prefix the renderer
has always used, so a coach reading the output sees the same lines
whichever script ran.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from tracker.validation import validate_tracker_json
from .render_validators import (
    is_deload_week,
    payload_spec_errors,
    tier_budget_by_index,
    validate_coach_reads,
    validate_workout_md,
    validate_workout_plan,
)


@dataclass
class PlanCheckResult:
    """Outcome of `run_plan_checks`.

    ``exit_code`` is 0 (every blocking check passed) or 2 (a blocking
    check failed; the messages are already printed). ``coach`` and
    ``workout_md`` are the loaded inputs, so the renderer does not read
    the files a second time; either is ``None`` when the sequence
    stopped before reaching it.
    """
    exit_code: int
    coach: "dict | None" = None
    workout_md: "str | None" = None
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def run_plan_checks(j: dict, coach_path, workout_md_path,
                    *, stream: "TextIO | None" = None) -> PlanCheckResult:
    """Run every plan check, print each finding, return the outcome.

    ``j`` is the parsed tracker JSON (the caller parses it because the
    renderer also accepts it on stdin). ``coach_path`` and
    ``workout_md_path`` are read here, in stage order.
    """
    out = stream if stream is not None else sys.stderr
    result = PlanCheckResult(exit_code=0)

    def warn(prefix: str, items) -> None:
        for w in items:
            line = f"{prefix}: {w}"
            result.warnings.append(line)
            print(line, file=out)

    def fail(prefix: str, items) -> PlanCheckResult:
        for e in items:
            line = f"{prefix}: {e}"
            result.errors.append(line)
            print(line, file=out)
        result.exit_code = 2
        return result

    tracker_errors, tracker_warnings = validate_tracker_json(j)
    # `tracker.validation` types the prescription specs as free dicts, so
    # a corrupt one reaches the coach as a prescription. Checked here
    # rather than there because the expected shape is the coach's
    # constant and `tracker/` must not import the coach.
    tracker_errors = list(tracker_errors) + payload_spec_errors(j)
    warn("tracker_json warning", tracker_warnings)
    if tracker_errors:
        return fail("tracker_json validation error", tracker_errors)

    coach = json.loads(Path(coach_path).read_text(encoding="utf-8"))
    result.coach = coach
    # Pass the payload so coach-authored scores are checked against the
    # numbers they claim to report. Without it the cross-check is inert:
    # a card may state a recovery score the tracker contradicts, and the
    # dashboard renders both, side by side, at exit 0.
    errors, warnings = validate_coach_reads(coach, j)
    warn("coach_reads warning", warnings)
    if errors:
        return fail("coach_reads validation error", errors)

    workout_md = Path(workout_md_path).read_text(encoding="utf-8")
    result.workout_md = workout_md
    workout_errors, workout_warnings = validate_workout_md(workout_md)
    warn("workout_md warning", workout_warnings)
    if workout_errors:
        return fail("workout_md validation error", workout_errors)

    # Prescription-CONTENT validation: core dose + weekly core
    # distribution, direct-arm dose + diversity, block rotation against
    # the previous block, and the tier-scaled working-set budget.
    #
    # The core and arm findings are BLOCKING, and that is the change.
    # They were printed to stderr and the next generated plan ignored
    # them; the 2026-07-18 plan met every numeric target the system
    # checked and was still wrong. The core and arm checks also used to
    # sit behind `if base_budget:`, so a payload without
    # `target_working_sets` skipped core and arm validation entirely —
    # an unrelated missing key silently disabling the checks that matter
    # most.
    #
    # ROTATION IS ADVISORY THIS RELEASE and this module does not decide
    # that. `validate_workout_plan` routes rotation findings by the one
    # named constant `render_validators.BLOCK_ROTATION_ENFORCED`, so they
    # arrive here in `plan_warnings` and no rotation finding can produce
    # an exit 2. Nothing below needs to change when stage two flips it:
    # the findings simply arrive in `plan_errors` instead.
    #
    # A prescribed whole-week deload demotes the VOLUME findings to
    # warnings, because cutting volume is what a deload IS. Diversity and
    # placement stay blocking — they cost no fatigue. A Tier C recovery
    # downgrade is NOT a deload and keeps every floor: see
    # `render_validators.DELOAD_WEEK_LABELS`.
    #
    # THE SPECS ARE NOT PASSED IN, and that is deliberate. `read_tracker`
    # writes `core_week_spec` / `arm_week_spec` into the payload straight
    # from `constants`, which is the same constant `render_validators`
    # already imports, so this call used to hand the validator back its
    # own defaults — a measured no-op (passing `None` instead changed no
    # output anywhere). It was not a harmless one, though: it made the
    # gate's thresholds an input to the gate, so a payload could have
    # lowered the bar it was about to be judged against, and every key
    # access downstream was unguarded (a partial spec exited 1 on a
    # KeyError, which claims "crash" where "refusal" was meant). One
    # concept, one source of truth, and for a merge gate that source
    # cannot be the artifact under review. The payload copy stays — the
    # coach reads it while authoring — and `payload_spec_errors` above
    # keeps it well formed.
    base_budget = j.get("target_working_sets")
    session_rec = j.get("session_recommendation")
    block = j.get("block")
    plan_errors, plan_warnings = validate_workout_plan(
        workout_md,
        target_working_sets=base_budget,
        budget_by_index=tier_budget_by_index(session_rec, base_budget),
        prev_block=block,
        plan_date=j.get("today"),
        deload_week=is_deload_week(session_rec, block),
        # The plan's own opener states the recovery score to the user
        # mid-workout and shipped unchecked while `coach_reads` did not,
        # so one page could carry three different numbers for it: 5.6 in
        # the opener, 5.2 in a card callout, 5.4 in the payload. Same
        # payload, same cross-check, same severities.
        payload=j,
    )
    warn("workout_md plan warning", plan_warnings)
    if plan_errors:
        return fail("workout_md validation error", plan_errors)
    return result
