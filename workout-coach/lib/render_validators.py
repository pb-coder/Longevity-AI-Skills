"""Coach-text validation + tooltip-term catalog for the renderer.

This module owns the strict copy rules the renderer enforces against
``coach_reads.json`` (no em-dashes, length caps) and the catalog of
abbreviations that get auto-wrapped in dotted-underline tooltips when
they appear in coach text.

Public surface:

- ``KNOWN_TERMS`` — abbreviation → (full name, plain-English
  explanation). Adding a new tooltip-able abbreviation: add an entry
  here, no other file needs changing.
- ``COACH_CARD_KEYS`` — the card-key tuple the validator uses to warn
  on missing optional callouts.
- ``EM_DASH``, ``COACH_STRING_MAX`` — constants for the validator.
- ``validate_coach_reads(coach) -> (errors, warnings)`` — hard errors
  vs. soft warnings. Errors fail the render with exit code 2; warnings
  print to stderr but allow the render to proceed.
- ``validate_workout_md(text) -> (errors, warnings)`` — validates the
  lean workout markdown before it is embedded in the dashboard.
- ``auto_wrap_terms(text)`` — wraps each ``KNOWN_TERMS`` key in a
  tooltip span. First-occurrence-only per string by design (avoids
  visual noise on lines that repeat a term).
"""
from __future__ import annotations

from functools import lru_cache
import re


from .render_helpers import esc


# Terms that get a dotted-underline tooltip when they appear in the
# coach text. The renderer auto-wraps them. The coach is encouraged
# to use the plain-English equivalent instead.
KNOWN_TERMS = {
    "CTL":    ("Chronic Training Load",
               "A 42-day moving average of your training stress. It moves slowly and represents your fitness baseline. On this dashboard the chart's blue line is your CTL."),
    "ATL":    ("Acute Training Load",
               "A 7-day moving average of your training stress. It moves quickly and represents your current fatigue. On this dashboard the chart's orange dashed line is your ATL."),
    "TSB":    ("Training Stress Balance",
               "Your fitness minus your current fatigue. Positive numbers mean you are fresh and ready, negative numbers mean fatigue is accumulating. Above +5 is fresh, below -10 starts to be tired."),
    "e1RM":   ("Estimated one-rep max",
               "Your single-rep capacity extrapolated from your working sets. It lets you track strength changes without ever doing a true one-rep test."),
    "MEV":    ("Minimum Effective Volume",
               "The smallest weekly set count that still drives growth in a muscle. Below this number, training does not produce a meaningful adaptation."),
    "MAV":    ("Maximum Adaptive Volume",
               "The upper end of the productive range for a muscle. Beyond this, extra sets cost more fatigue than they give back in growth."),
    "MRV":    ("Maximum Recoverable Volume",
               "The most weekly sets a muscle can take and still recover from. Above this you accumulate fatigue you cannot pay back, raising injury and overtraining risk."),
    "SDNN":   ("Standard deviation of NN intervals",
               "A measure of overnight heart-rate variability. It tracks how relaxed your nervous system was during sleep. Higher relative to your baseline is favorable."),
    "HRR":    ("Heart-rate recovery",
               "How many beats per minute your heart rate drops in the first minute after exercise. Higher means your autonomic system shifts back to rest faster."),
    "RHR":    ("Resting heart rate",
               "Your heart rate at rest, measured overnight. Lower relative to your 60-day baseline is favorable. A sustained rise of 5+ bpm often signals under-recovery or illness."),
    "HRV":    ("Heart rate variability",
               "The variation in the time between heartbeats overnight, measured here as SDNN. Higher relative to your baseline is favorable. Lower can mean under-recovery or stress."),
    "Z2":     ("Zone 2",
               "Aerobic cardio at roughly 60-70 percent of your maximum heart rate. You can hold a conversation. It builds mitochondrial density and the aerobic base."),
    "Z5":     ("Zone 5",
               "Near-maximal intervals at 90 percent or more of your maximum heart rate. The most efficient zone for raising your peak oxygen uptake."),
    "VO2max": ("Peak oxygen uptake",
               "The maximum rate at which your body can use oxygen during intense exercise. A standard fitness ceiling and one of the strongest predictors of long-term healthspan."),
    "HSP":    ("Heat Shock Proteins",
               "Molecular chaperones induced by heat exposure. They are linked to many of sauna's longevity-associated effects. Induction needs roughly 20 minutes at or above 80 degrees Celsius."),
    "ACWR":   ("Acute:Chronic Workload Ratio",
               "Last 7 days of training stress divided by the rolling 4-week average. Gabbett 2016 sweet spot is 0.8 to 1.3. Above 1.5 carries materially higher soft-tissue injury risk."),
    "SRI":    ("Sleep Regularity Index",
               "How consistent your sleep schedule is across consecutive days, scored 0 to 100. UK Biobank n=60,977: the top quintile has 20 to 48 percent lower all-cause mortality than the bottom."),
    "ApoB":   ("Apolipoprotein B",
               "The protein on every atherogenic lipoprotein particle. Better predictor of cardiovascular risk than LDL cholesterol alone."),
    "ALMI":   ("Appendicular Lean Mass Index",
               "DEXA-measured lean mass in arms plus legs, divided by height squared. Lower-than-cohort values predict sarcopenia and frailty risk decades out."),
    "BMD":    ("Bone Mineral Density",
               "DEXA-measured bone density. A baseline matters for anyone on tenofovir (PrEP) or with risk factors for osteoporosis."),
    "VAT":    ("Visceral Adipose Tissue",
               "Fat stored around abdominal organs. The metabolically dangerous fat depot. Above 100 cm² is the risk threshold; under 80 cm² is the Attia optimal target."),
    "eGFR":   ("Estimated Glomerular Filtration Rate",
               "Kidney filtration function. The cystatin-C variant is preferred when creatine supplementation can confound the serum-creatinine version."),
    "PrEP":   ("Pre-exposure Prophylaxis",
               "Daily HIV-prevention medication (tenofovir + emtricitabine). Requires eGFR and bone-density monitoring."),
}

EM_DASH = "—"
COACH_STRING_MAX = 280

WORKOUT_SUB_BULLET_LIMIT = 2
WORKOUT_SUB_BULLET_RE = re.compile(r"^\s{2,}" + re.escape(EM_DASH) + r"\s+")
WORKOUT_HEADING_RE = re.compile(r"^##\s+Workout\b", re.IGNORECASE)
SECTION_HEADING_RE = re.compile(r"^##\s+")
WORKOUT_EXERCISE_RE = re.compile(r"^-\s+([^:]+):")
WORKOUT_BANNED_SUB_BULLET_RE = re.compile(
    r"\b("
    r"last\s+time|last\s+logged|you(?:'|')?ve\s+been|stuck\s+at|"
    r"reintroduc(?:e|ing)|start\s+light|hold\s+loads?|no\s+pr\s+attempts?|"
    r"rationale|because|vs\s+mev|vs\s+mav|vs\s+mrv"
    r")\b",
    re.IGNORECASE,
)


# Card keys the renderer knows how to surface a coach callout for.
# Listed here so the validator can warn when one is missing; the
# corresponding card still renders (just without a callout) which is
# a softer failure than a hard validator error.
#
# Today + Trajectory tabs have their own per-tab keys. ``vitals``,
# ``sleep``, ``recovery_practices`` are retained where the corresponding
# cards still render (cross-tab — they appear on the Trajectory tab).
COACH_CARD_KEYS = (
    # TODAY tab
    "session_recommendation_callout",  # narrative gloss on the recovery gate
    "today_acwr",
    "recovery_drivers", "activity_rings", "training_load",
    "muscle_volume", "strength",
    # TRAJECTORY tab — domain callouts
    "trajectory_longevity_score", "trajectory_cardio", "trajectory_recovery",
    "trajectory_sleep", "trajectory_body_comp", "trajectory_metabolic",
    "trajectory_behavioral", "trajectory_risk_flags",
    # TRAJECTORY tab — gated cards (callout only rendered when card renders).
    # Missing keys are not a warning for these because the card itself may
    # not render this run (no swim data, no open nutrition phase).
    "swim_trajectory_callout",
    "nutrition_phase_callout",
    # Retained (cross-tab cards)
    "vitals", "sleep", "recovery_practices",
)


# Cards that ONLY render when a gating block exists in the tracker JSON.
# The validator skips "missing callout" warnings for these because the
# card may legitimately not render this turn — and a missing callout is
# only noise when there's no card to attach it to.
GATED_COACH_CARD_KEYS = frozenset({
    "swim_trajectory_callout",
    "nutrition_phase_callout",
    # Renders an empty-state card (and intentionally takes no callout) when no
    # sauna / cold / light sessions exist in the window, so a missing callout
    # is not a defect, only noise. See card_recovery_practices.
    "recovery_practices",
})


def validate_coach_reads(coach: dict) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)``.

    Errors are hard failures (the renderer refuses to write the HTML).
    Warnings are surfaced to stderr but don't block the render. A
    missing ``cards.<key>`` for a documented card is a warning, not an
    error, because the card itself still renders cleanly without a
    callout."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(coach, dict):
        return (["coach reads must be a JSON object"], warnings)

    headline = coach.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        errors.append("missing or empty `headline`")
    elif EM_DASH in headline:
        errors.append("`headline` contains an em-dash (—). Use a period or comma.")
    elif len(headline) > COACH_STRING_MAX * 2:
        errors.append(f"`headline` is over {COACH_STRING_MAX*2} characters")

    cards = coach.get("cards") or {}
    if not isinstance(cards, dict):
        errors.append("`cards` must be a JSON object")
        return (errors, warnings)

    for key, text in cards.items():
        if not isinstance(text, str):
            errors.append(f"cards.{key} must be a string")
            continue
        if EM_DASH in text:
            errors.append(f"cards.{key} contains an em-dash (—). Use a period or comma.")
        if len(text) > COACH_STRING_MAX:
            errors.append(
                f"cards.{key} is {len(text)} chars; max is {COACH_STRING_MAX}"
            )

    for key in COACH_CARD_KEYS:
        if key in GATED_COACH_CARD_KEYS:
            # Card only renders when its gating block is present in tracker
            # JSON; a missing callout is only meaningful when the card would
            # actually render. The renderer decides per-run via its own gate.
            continue
        if not cards.get(key):
            warnings.append(f"cards.{key} missing or empty; that card will render without a coach callout")

    return (errors, warnings)


@lru_cache(maxsize=1)
def _workout_exercise_name_set() -> set[str]:
    """Return normalized canonical + alias exercise names for this process."""
    from shared.exercises_database import known_name_set  # local import avoids CLI cost

    return known_name_set()


def _is_known_exercise_name(name: str, known_names: set[str]) -> bool:
    """Resolve a workout bullet name without reparsing the catalog."""
    from shared.exercises_database import is_known_name  # local import

    return is_known_name(name, known_names)


def validate_workout_md(text: str) -> tuple[list[str], list[str]]:
    """Validate lean workout markdown before dashboard rendering.

    Hard errors block render output when the markdown would create user
    friction later: off-catalog exercise names or em-dashes outside the
    allowed title/sub-bullet positions. Warnings flag coach-writing drift
    that should be fixed, but can still render.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(text, str) or not text.strip():
        return (["workout markdown is empty"], warnings)

    in_workout = False
    workout_title = ""
    sub_bullet_count = 0
    # Lazy: the exercise name set requires parsing exercises-database.md,
    # which is wasted work when the markdown has no exercise bullets
    # (the case for the benchmark fixture and any plain summary doc).
    known_exercise_names: set[str] | None = None

    def flush_workout() -> None:
        if workout_title and sub_bullet_count > WORKOUT_SUB_BULLET_LIMIT:
            warnings.append(
                f"{workout_title}: {sub_bullet_count} sub-bullets; "
                f"recommended max is {WORKOUT_SUB_BULLET_LIMIT}"
            )

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()

        if WORKOUT_HEADING_RE.match(line):
            flush_workout()
            in_workout = True
            workout_title = line.lstrip("# ").strip() or f"line {lineno}"
            sub_bullet_count = 0
        elif SECTION_HEADING_RE.match(line):
            flush_workout()
            in_workout = False
            workout_title = ""
            sub_bullet_count = 0

        if EM_DASH in line:
            allowed_title = lineno == 1 and line.startswith("# Workout plan ")
            allowed_sub_bullet = WORKOUT_SUB_BULLET_RE.match(line) is not None
            if not (allowed_title or allowed_sub_bullet):
                errors.append(
                    f"line {lineno}: contains an em-dash outside the title "
                    "or sub-bullet marker"
                )

        if not in_workout:
            continue

        if WORKOUT_SUB_BULLET_RE.match(line):
            sub_bullet_count += 1
            if WORKOUT_BANNED_SUB_BULLET_RE.search(line):
                warnings.append(
                    f"{workout_title} line {lineno}: sub-bullet contains "
                    "rationale or comparative-history phrasing"
                )
            continue

        m = WORKOUT_EXERCISE_RE.match(line)
        if not m:
            continue
        exercise_name = m.group(1).strip()
        if known_exercise_names is None:
            known_exercise_names = _workout_exercise_name_set()
        if not _is_known_exercise_name(exercise_name, known_exercise_names):
            errors.append(
                f"line {lineno}: exercise {exercise_name!r} is not in the "
                "canonical exercise catalog"
            )

    flush_workout()
    return (errors, warnings)


def count_working_sets_per_workout(text: str) -> "dict[str, int]":
    """Count working sets under each `## Workout` heading.

    A working set is a `///`-separated token on a loaded exercise bullet
    (body contains `kg` or `x`), excluding any token marked `(warmup)`.
    Pure prep bullets (`Jumping Jacks: 50`) carry no kg/x and count zero.
    This mirrors how session duration is actually driven (total working
    sets ~3.3 min each), so the budget check sees what the user will feel.
    """
    out: "dict[str, int]" = {}
    title = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = re.match(r"^##\s+(Workout\b.*)$", line, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
            out[title] = 0
            continue
        if title and line.startswith("- ") and ":" in line:
            body = line.split(":", 1)[1]
            if "kg" in body or "x" in body:
                toks = [t for t in body.split("///") if "warmup" not in t.lower()]
                out[title] += len(toks)
    return out


def workout_set_budget_warnings(text: str, target_working_sets,
                                low_tol: int = 3, high_tol: int = 5) -> "list[str]":
    """Warn when a workout's working-set count drifts from the budget.

    `target_working_sets` is the per-person, tier-adjusted set budget. The
    short side is the one that bit us (sessions silently shrank as
    sets-per-exercise drifted), so the low tolerance is tighter. Warning,
    not error: an intentional deload/downgrade legitimately undershoots and
    should still render, just visibly flagged.
    """
    warnings: "list[str]" = []
    if not target_working_sets or target_working_sets <= 0:
        return warnings
    for title, n in count_working_sets_per_workout(text).items():
        if n < target_working_sets - low_tol:
            warnings.append(
                f"{title}: {n} working sets vs budget {target_working_sets} "
                f"({target_working_sets - n} under) — confirm this is an "
                f"intentional deload/downgrade, else add sets to the main lifts")
        elif n > target_working_sets + high_tol:
            warnings.append(
                f"{title}: {n} working sets vs budget {target_working_sets} "
                f"({n - target_working_sets} over) — trim a set or two")
    return warnings


# Wrap KNOWN_TERMS with a tooltip span when they appear in any coach
# string. Whole-word, case-sensitive (so "Cold" doesn't match "CTL").
# Each term wraps at most once per string so we don't double-wrap when
# the user repeats a term.
# Pattern is lazy-compiled so a render whose coach_block calls all
# short-circuit on empty text (the benchmark fixture, plus any run where
# the LLM omitted card callouts) doesn't pay the alternation-compile.
_TERM_PATTERN: "re.Pattern[str] | None" = None


def _term_pattern() -> "re.Pattern[str]":
    global _TERM_PATTERN
    if _TERM_PATTERN is None:
        _TERM_PATTERN = re.compile(
            r"\b(" + "|".join(sorted(map(re.escape, KNOWN_TERMS.keys()), key=len, reverse=True)) + r")\b"
        )
    return _TERM_PATTERN


def auto_wrap_terms(text: str) -> str:
    """Wrap each known abbreviation in a tooltip span.

    Only the FIRST occurrence of each term per string is wrapped; later
    occurrences are left plain. This is intentional, not a bug: wrapping
    every occurrence creates dotted-underline visual noise on lines that
    repeat a term. Do not 'fix' this to wrap all occurrences."""
    seen: set[str] = set()

    def _sub(m):
        t = m.group(1)
        if t in seen:
            return t
        seen.add(t)
        full, expl = KNOWN_TERMS[t]
        return f'<span class="term" data-tip="{esc(full)}. {esc(expl)}">{esc(t)}</span>'

    return _term_pattern().sub(_sub, esc(text))
