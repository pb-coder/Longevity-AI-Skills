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
- ``validate_coach_reads(coach, payload=None) -> (errors, warnings)`` —
  hard errors vs. soft warnings. Errors fail the render with exit code 2;
  warnings print to stderr but allow the render to proceed. Pass the
  tracker payload to also cross-check the numbers the coach WROTE against
  the numbers the payload HOLDS — see `coach_number_findings`. Optional,
  and a caller that has the payload and omits it silently keeps the old
  behaviour, which is that a fabricated recovery score renders.
- ``coach_number_findings(payload, texts) -> (errors, warnings)`` — the
  cross-check itself, over any labelled coach-authored strings. The only
  rule in this file that reads coach text for TRUTH rather than for form.
  A mismatch is an ERROR when the two numbers fall on opposite sides of a
  documented decision threshold (`recovery_decision_boundaries`) and a
  warning otherwise; magnitude is a noise floor, not the instrument.
- ``recovery_decision_boundaries()`` — those thresholds, derived from
  ``constants.SESSION_GATE_THRESHOLDS`` plus one anti-fabrication edge
  (`COACH_SCORE_TOP_BAND_EDGE`).
- ``validate_workout_md(text) -> (errors, warnings)`` — validates the
  lean workout markdown's COPY (em-dashes, off-catalog names) before it
  is embedded in the dashboard.
- ``validate_workout_plan(text, ...) -> (errors, warnings)`` — validates
  the plan's CONTENT against the prescription specs in ``constants`` and
  against the previous training block. Dose and distribution findings
  come back as errors, not warnings; see its docstring for why.
- ``BLOCK_ROTATION_ENFORCED`` — the stage-two switch. ``False`` this
  release, which routes rotation findings to warnings instead of errors.
  One name, one read site (`validate_workout_plan`).
- ``ROTATION_ADVISORY_TAG`` — the suffix stamped on a rotation finding
  while the switch is off.
- ``muscle_floor_errors(text, payload) -> [str]`` — the one weekly
  direct-set floor every muscle gets; the rule is in the block comment
  above `_primary_muscle_by_exercise`.
- ``payload_spec_errors(tracker_json) -> [str]`` — the tracker payload's
  ``core_week_spec`` / ``arm_week_spec`` are REPORTS of the constants,
  never gate inputs. This checks they are well formed so a corrupt one
  is a clean exit 2 rather than a traceback, and `SpecError` is what any
  caller that passes its own spec gets instead of a ``KeyError``.
- ``block_rotation_errors(text, prev_block, ...)`` — the W5 rotation
  diff, run against a block derived from the plan markdown itself.
- ``tier_budget_by_index(session_recommendation, base_budget)`` — the
  per-workout-index working-set budget the recovery gate implies.
- ``auto_wrap_terms(text)`` — wraps each ``KNOWN_TERMS`` key in a
  tooltip span. First-occurrence-only per string by design (avoids
  visual noise on lines that repeat a term).

This module reaches into the analytics side (``constants``, ``extract``,
``adherence``, ``blocks``) where a rule needs the catalog, the plan
parser or the block model. That is deliberate and narrow: the
alternative is a second copy of catalog parsing, heading classification
and pattern identity inside the renderer, which `Skills/CLAUDE.md`
forbids outright. Those imports are function-local so a render that
never validates a plan does not pay for them.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from math import ceil
import re


from .constants import (
    ARM_WEEK_SPEC,
    CORE_WEEK_SPEC,
    DELOAD_WEEK_LABELS,
    FLOOR_REFERENCE_SESSIONS,
    cadence_deload_week,
    floor_scale,
    full_block_deload,
)
from .render_helpers import esc


class SpecError(ValueError):
    """A prescription spec that cannot be used as one.

    Raised in place of the ``KeyError`` / ``TypeError`` that a bare
    ``spec["sets_per_session"]`` produced for every caller that supplied
    a spec of the wrong shape. Those escaped as an unhandled traceback
    and exit code 1, and 1 means *this program crashed*; a spec the
    validator refuses to run against is a validation refusal, which is
    exit 2. A typed exception is what lets a CLI tell those apart.
    """


def _spec_value_type_ok(value, want) -> bool:
    """Whether ``value`` may stand in for the default ``want``.

    Numeric-tolerant on purpose: a share written ``1`` instead of ``1.0``
    is the same share, and refusing it would be pedantry. ``bool`` is
    excluded from the numeric case because ``isinstance(True, int)`` is
    True and ``"min_flexion_sets_per_week": True`` is not a set count.
    """
    if isinstance(want, bool):
        return isinstance(value, bool)
    if isinstance(want, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, type(want))


def _resolved_spec(spec: "dict | None", default: dict, label: str) -> dict:
    """``default`` overlaid with ``spec``. Never raises ``KeyError``.

    Two properties, and both are load-bearing:

    * **Merge, do not replace.** A partial spec fills in from the
      constant, one level deep (so ``{"sets_per_session": {"lower": 5}}``
      keeps ``upper``). ``tracker/validation.py`` accepts these fields as
      free dicts and ``test_tracker_validators`` pins a partial one as a
      VALID payload, so a partial spec is legal input and must not be
      able to crash a consumer.
    * **Refuse the unusable loudly.** A non-mapping, or a known key
      carrying the wrong type, raises `SpecError` naming the field and
      what was expected. Silently falling back to the default here would
      be worse than the crash: the caller would believe its spec was in
      force.

    Unknown keys are carried through untouched rather than rejected. They
    are inert to every consumer, and refusing them would make a payload
    written by an older or newer `read_tracker` unrenderable for a
    cosmetic reason.
    """
    if spec is None:
        return default
    if not isinstance(spec, dict):
        raise SpecError(
            f"{label} must be a mapping of spec keys, got "
            f"{type(spec).__name__} ({spec!r:.60}). It is a restatement of "
            f"the constant of the same name in `workout_coach.lib.constants`; "
            f"fix the producer, or drop the key to use the constant.")
    if not spec:
        return default
    merged = dict(default)
    for key, value in spec.items():
        want = default.get(key)
        if key not in default:
            merged[key] = value            # inert; see the docstring
            continue
        if isinstance(want, dict) and isinstance(value, dict):
            merged[key] = {**want, **value}
            continue
        if not _spec_value_type_ok(value, want):
            raise SpecError(
                f"{label}.{key} must be {type(want).__name__}, got "
                f"{type(value).__name__} ({value!r:.40}). Expected shape is "
                f"the constant of the same name in "
                f"`workout_coach.lib.constants`.")
        merged[key] = value
    return merged


def payload_spec_errors(payload: "dict | None") -> "list[str]":
    """Actionable errors for the tracker payload's prescription specs.

    ``core_week_spec`` / ``arm_week_spec`` travel in the tracker JSON so
    the coach can READ its targets while authoring a plan. They are
    reports, not gate inputs — `validate_workout_plan` takes its
    thresholds from `constants`, so a payload cannot lower the bar it is
    about to be judged against by editing the copy it ships with. See
    that function's docstring for why that ownership is not negotiable.

    A report still has to be well formed, though. A payload whose
    ``core_week_spec`` is a string is a corrupt payload, and it reaches
    the coach, which reads it as a prescription. Refusing it is exit 2
    (a validation refusal), which is what this list is for; ignoring it
    would ship the corruption onward to the one consumer that acts on it.
    """
    out: "list[str]" = []
    for key, default in (("core_week_spec", CORE_WEEK_SPEC),
                         ("arm_week_spec", ARM_WEEK_SPEC)):
        try:
            _resolved_spec((payload or {}).get(key), default, key)
        except SpecError as exc:
            out.append(str(exc))
    return out


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

# Sub-bullets that are STRUCTURE, not commentary, and therefore do not
# count against `WORKOUT_SUB_BULLET_LIMIT`.
#
# The limit exists to stop rationale creep — "last time you did X",
# "we're holding here because…" — in a file the user reads mid-workout.
# An anchor-change declaration is not that: it is the plan's only channel
# for a required field, not prose the coach chose to add. So is the
# `other gym: X kg` cue, which SKILL.md requires whenever `next_dose` has an
# `other_gym_load_kg`.
#
# ANCHORED AT THE START OF THE SUB-BULLET, and that is not cosmetic. A
# `.search()` over the whole line would make any sub-bullet CONTAINING
# the phrase uncountable, so the exemption for a structural line would
# also exempt a paragraph of rationale with the token buried in the
# middle. Matched against the sub-bullet's body — the text after the
# `  — ` marker — not the raw line.
#
# The `other gym:` cue is exempt only in its whole, fixed form: a number and
# `kg`, then the end of the line (`other gym: 55 kg`). Anything after the
# number, or a cue with words instead of one, is prose that happens to start
# with the phrase, and counts like any other sub-bullet.
WORKOUT_STRUCTURAL_SUB_BULLET_RE = re.compile(
    r"^\s*(?:anchor\s+change\s*:"
    r"|other\s+gym\s*:\s*\d+(?:\.\d+)?\s*kg\s*$)",
    re.IGNORECASE,
)
# NOTE: the plan's workout-heading grammar lives in `adherence` and is
# reached through `_plan_workout_heading_re()`. This name is retained only
# for callers outside this module; do not use it for new checks. Matching
# `Workout` alone let an off-catalog exercise inside a `## Deload Session`
# heading render clean — four real plans use that heading.
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
    "recovery_drivers", "activity_rings",
    # NOT gated. `card_block_position` renders on every run, including
    # the first (where it says the block starts with this plan), because
    # the disclosure it carries is needed most on the weeks that look
    # identical to last week. A missing callout here is always a real
    # gap, so it always warns.
    "block_position",
    "training_load",
    "muscle_volume", "strength",
    # TRAJECTORY tab — domain callouts
    "trajectory_longevity_score", "trajectory_cardio", "trajectory_recovery",
    "trajectory_sleep", "trajectory_body_comp", "trajectory_metabolic",
    "trajectory_behavioral", "trajectory_risk_flags",
    # TRAJECTORY tab — gated cards (callout only rendered when card renders).
    # Missing keys are not a warning for these because the card itself may
    # not render this run (no swim data, no open nutrition phase, no
    # energy-expenditure block).
    "swim_trajectory_callout",
    "nutrition_phase_callout",
    "trajectory_energy",
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
    # `card_energy` renders only when the payload carries `energy_28d`, and
    # that block is ABSENT rather than null when there is no energy data.
    "trajectory_energy",
    # Renders an empty-state card (and intentionally takes no callout) when no
    # sauna / cold / light sessions exist in the window, so a missing callout
    # is not a defect, only noise. See card_recovery_practices.
    "recovery_practices",
})


# ------------------------------------ coach numbers against the payload
#
# THE EXPLOIT THIS CLOSES, reproduced end to end before the fix: a
# ``coach_reads.json`` of
#
#     {"headline": "Everything is fine. Recovery is 10 out of 10. Train
#      hard.", "cards": {}}
#
# rendered at exit 0 against a payload whose ``recovery.score`` was 5.6,
# and the fabricated "10 out of 10" appeared TWICE in the finished page,
# directly beside the real 5.6. Forty-four soft warnings fired, every one
# of them "card missing or empty", none about the contradiction. Every
# copy rule in this module — em-dashes, length caps, missing callouts —
# polices the FORM of coach text and nothing polices its truth, so the
# single most dangerous artifact the pipeline can produce is a
# confidently wrong dashboard.
#
# WHY THIS ONE NUMBER AND NOT A GENERAL FACT-CHECKER. The check has to be
# high-precision: a false positive here refuses a legitimate plan, and a
# gate that cries wolf gets routed around. ``recovery.score`` is the
# number the whole dashboard is framed around, so getting it wrong is the
# failure with the most downstream consequence. A rule per payload scalar
# was considered and deliberately not written: the rule below is one rule
# because one rule is what the evidence supports.
#
# THE PREMISE THAT WAS FALSE, and the false positive it caused. The first
# version claimed ``recovery.score`` "has a shape nothing else in the
# vocabulary shares" and anchored on the word "recovery" within 40
# characters of any ``N/10``. Both halves were wrong. The payload carries
# five more 0-10 scalars — ``recovery.drivers[].component_score`` — and
# SKILL.md REQUIRES the drivers card (§ Recovery state) to print them in
# exactly that shape, one per driver, ending ``component {n}/10``. Its own
# worked example is ``component 1.6/10``. So the prompt-faithful card
#
#     "Recovery 5.4 out of 10. HR recovery is the drag at 1.6 out of 10."
#
# was refused with exit 2, because "recovery" sits four characters from
# the 1.6. The shipped plans survived only by accident: their drivers
# cards happen to quote bpm and hours instead of the documented ``/10``
# form. One prompt-compliant rewrite would have refused the render.
#
# THE ANCHOR THAT REPLACED PROXIMITY. Two rules, both narrow on purpose.
#
#   Rule A, the metric noun. "recovery" (optionally "recovery score") has
#   to be the noun GOVERNING the number, joined to it by a short closed
#   set of connectives and no sentence break: "Recovery 5.4/10",
#   "recovery is 5.4 out of 10", "Recovery: 5.4/10". A component score
#   reads "HR recovery is the drag at 1.6 out of 10" or "(z -1.35, weight
#   0.10, component 1.6/10)" — in the first the noun is "HR recovery",
#   which is a DIFFERENT metric (`hr_recovery_1min`) and is excluded by
#   lookbehind; in the second "recovery" is not adjacent at all.
#
#   Rule B, the card label. The validator already holds the label and
#   never read it. On the surfaces whose entire subject is the composite
#   — the headline, the session-gate callout, the plan opener — the FIRST
#   ``N/10`` is the composite whether or not the coach names it, which
#   catches "Readiness is 10 out of 10". Rule B deliberately does NOT
#   cover ``cards.recovery_drivers`` / ``cards.trajectory_recovery``: a
#   bare ``N/10`` on those two is legitimately a component score, and
#   claiming otherwise is the F1 false positive again.
#
# WHAT REMAINS UNCOVERED, stated plainly rather than chased, and probed
# adversarially rather than assumed. A coach that writes any of these is
# not checked at all:
#
#   * every non-``/10`` rendering of the number — "a 10 today", "ten out
#     of ten", "96 out of 100", "98% of your baseline". The regex cannot
#     see them and no amount of widening it stays precise;
#   * a bare ``N/10`` on any card outside `RECOVERY_SCORE_SURFACES`,
#     including the two recovery cards (see above for why). On the drivers
#     cards this is the deliberate price of not repeating F1;
#   * ``recovery is 10 out of 10 sets`` — the counted-ratio tail
#     (`_COUNTED_RATIO_TAIL_RE`) silences BOTH rules, because "N out of 10
#     sets" is a completion ratio and reading it as a score is the false
#     positive that broke the pinned tests. Appending a counting noun to a
#     score claim is therefore a way past the check, at the cost of
#     writing a sentence that no longer claims the score;
#   * under Rule B only, a decoy: "Your sleep scored 5.4 out of 10.
#     Readiness is a 10 out of 10." spends the first match on a number
#     that happens to agree with the payload, and Rule B looks no
#     further. Checking every match instead would flag the sleep and HRV
#     component scores a headline may legitimately quote, which is F1
#     again on a different card.
#
# Narrow and honest beats broad and false-positive. A check that refuses
# the card SKILL.md mandates gets switched off, and then none of the
# above is covered either.

# Labels whose whole subject is the COMPOSITE score, where a bare
# ``N/10`` needs no metric noun to be read as a claim about it. Matches
# the labels `_coach_strings` and `_plan_texts` emit, exactly.
RECOVERY_SCORE_SURFACES = frozenset({
    "`headline`",
    "cards.session_recommendation_callout",
    "plan opener",
})

# "8/10", "8.5 / 10", "8 out of 10". The denominator is pinned to 10 so a
# rep scheme ("3/10 RPE" aside, the plan writes reps as "8-10") and a date
# cannot match, and the numerator is capped at two digits for the same
# reason.
_SCORE_OUT_OF_TEN_RE = re.compile(
    r"(\d{1,2}(?:\.\d{1,2})?)\s*(?:/|\s+out\s+of\s+)\s*10\b", re.IGNORECASE)

# Rule A. "recovery" as the governing noun, NOT preceded by a qualifier
# that names a different metric (`hr recovery` is `hr_recovery_1min`, a
# driver), joined to the number by a closed connective set.
_RECOVERY_SCORE_RE = re.compile(
    r"(?<!\bhr )(?<!\bh\.r\. )(?<!\bheart rate )"
    r"\brecovery(?:\s+score)?\b"
    r"\s*(?:is|was|sits\s+at|sits|reads|scored|came\s+in\s+at|at|of|:|,|-)?\s*"
    r"((\d{1,2}(?:\.\d{1,2})?)\s*(?:/|\s+out\s+of\s+)\s*10)\b",
    re.IGNORECASE)

# Float determinism. ``abs(4.9 - 3.9)`` is 1.0000000000000004 and
# ``abs(6.4 - 5.4)`` is exactly 1.0, so an un-rounded magnitude compare
# gave two different verdicts for the same one-point disagreement. Every
# comparison below rounds to this many places first.
_SCORE_ROUND_PLACES = 3

# The re-derivation noise floor, MEASURED, not chosen. `recovery.score` is
# a rolling composite over a live window, so the same plan re-rendered
# hours later is scored against a payload that has moved. Observed on this
# tracker pair: three mismatches of 0.1 across eight historical
# generations, 0.2 on both people when a 2026-08-02 plan was re-rendered
# against a payload rebuilt after that afternoon's health import (the
# shipped plan's opener says 5.6; the payload now says 5.4). None of those
# is a false statement by the coach.
#
# It is a FLOOR, not the instrument. The instrument is decision
# equivalence (below); this only keeps a disagreement that is entirely
# inside the pipeline's own noise from being called a lie. The most a
# coach can buy with it is 0.2 of a point, which changes no prescription
# it could not already have justified.
COACH_SCORE_REDERIVE_NOISE = 0.2

# The one boundary in `recovery_decision_boundaries` with no gate threshold
# behind it, and NOT a load decision: the load policy's green line is the
# gate's own 5.5 (`tier_d_recovery_score_min`). Every gate threshold sits at
# or below 5.5, so without this edge the band from 5.5 to 10 is one band and
# a fabricated "10 out of 10" against a real 5.6 would only warn, which is
# the exploit G-07 closed. It exists to keep a claim from hiding in that
# wide top band, and it used to be borrowed from a SKILL.md recovery rule
# that no code ever enforced; that rule is gone, this edge is not.
COACH_SCORE_TOP_BAND_EDGE = 6.5


@lru_cache(maxsize=1)
def recovery_decision_boundaries() -> "tuple[float, ...]":
    """Every ``recovery.score`` value at which a documented decision flips.

    DERIVED, not restated. The old instrument was a magnitude —
    ``COACH_SCORE_MAX_DRIFT = 1.0`` — justified by a comment claiming a
    full point "spans two of SKILL.md's recovery tiers (5.0 / 5.5
    boundaries)" and that "anything under it changes no decision". Both
    claims were false. 5.0 is not a decision point anywhere, and at 1.0 a
    coach could write 6.4 against a real 5.4, crossing
    ``tier_d_recovery_score_min``, and only warn. Magnitude was never the
    question: 0.2 across 5.5 changes a prescription and 1.4 inside one
    band changes nothing.

    The set comes from `constants.SESSION_GATE_THRESHOLDS` — every
    threshold whose key names ``recovery`` and whose value is on the 0-10
    scale — so adding or moving a gate threshold moves this set with it
    and no copy can drift. Today that yields 3.0
    (``tier_a_recovery_score_crash`` / ``tier_c_recovery_score_lo``), 4.0
    (``tier_c_recovery_hard_floor``) and 5.5
    (``tier_d_recovery_score_min``), plus 5.0
    (``tier_c_recovery_score_hi``).

    ``COACH_SCORE_TOP_BAND_EDGE`` is unioned in for the reason given
    there: it is not a gate threshold, it is what stops a high claim from
    hiding in the single band above the green line.
    """
    from .constants import SESSION_GATE_THRESHOLDS

    out = {COACH_SCORE_TOP_BAND_EDGE}
    for key, value in SESSION_GATE_THRESHOLDS.items():
        if "recovery" not in key:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if 0.0 <= float(value) <= 10.0:
            out.add(round(float(value), _SCORE_ROUND_PLACES))
    return tuple(sorted(out))


def _payload_recovery_score(payload: "dict | None") -> "float | None":
    rec = (payload or {}).get("recovery")
    score = rec.get("score") if isinstance(rec, dict) else None
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return float(score)


def _boundaries_between(a: float, b: float) -> "list[float]":
    """The decision boundaries that ``a`` and ``b`` sit on opposite sides of.

    A boundary ``t`` is used the way the code that owns it uses it —
    ``score >= t`` is one decision, ``score < t`` is another — so two
    values straddle it when exactly one of them clears it. Rounded first;
    see `_SCORE_ROUND_PLACES`.
    """
    lo = round(min(a, b), _SCORE_ROUND_PLACES)
    hi = round(max(a, b), _SCORE_ROUND_PLACES)
    return [t for t in recovery_decision_boundaries() if lo < t <= hi]


# A ``N/10`` followed by one of these is a RATIO, not the score: "8 out
# of 10 prescribed sets", "8 out of 10 sessions". Both rules skip it.
# Without this, Rule B read the completion ratios the headline routinely
# quotes as claims about recovery — the same class of false positive that
# broke the drivers card, found by the tests that pinned the old anchor.
_COUNTED_RATIO_TAIL_RE = re.compile(
    r"^\s*(?:prescribed|planned|scheduled|working|hard|logged)?\s*"
    r"(?:sets?|sessions?|workouts?|reps?|days?|nights?|weeks?|exercises?"
    r"|movements?|lifts?)\b",
    re.IGNORECASE)


def _recovery_score_claims(label: str, text: str) -> "list[tuple[str, str]]":
    """``[(quoted_fragment, written_value)]`` the string claims about the score.

    Rule A over the whole string, plus Rule B's first bare ``N/10`` on the
    composite surfaces. See the section comment above for both rules and
    for what neither covers.
    """
    claims = [(m.group(1), m.group(2)) for m in _RECOVERY_SCORE_RE.finditer(text)
              if not _COUNTED_RATIO_TAIL_RE.match(text[m.end():])]
    if claims or label not in RECOVERY_SCORE_SURFACES:
        return claims
    for m in _SCORE_OUT_OF_TEN_RE.finditer(text):
        if _COUNTED_RATIO_TAIL_RE.match(text[m.end():]):
            continue
        return [(m.group(0), m.group(1))]
    return []


def coach_number_findings(payload: "dict | None",
                          texts: "list[tuple[str, str]]"
                          ) -> "tuple[list[str], list[str]]":
    """``(errors, warnings)`` for coach-authored scores vs the payload.

    ``texts`` is ``[(label, text), ...]`` — the label names the string for
    the message (``` `headline` ```, ``cards.recovery_drivers``, ``plan
    opener``) and, for the labels in `RECOVERY_SCORE_SURFACES`, also
    anchors the check. See the section comment above for the anchor rules
    and for what they do not cover.

    ROUNDING IS ACCEPTED, contradiction is not. The written value is
    compared at ITS OWN precision first, so "6/10" is a legal rendering of
    5.6 and "5.6/10" is exact, while "10/10" is neither.

    WHEN A MISMATCH IS AN ERROR: when the two numbers imply DIFFERENT
    DECISIONS. `_boundaries_between` asks whether any documented threshold
    separates them; if one does, the coach has told the user a different
    thing about their training than the payload says, whatever the
    arithmetic gap. A 1.4-point disagreement inside one band warns; a
    0.3-point disagreement across ``tier_d_recovery_score_min`` errors.

    The one exception is `COACH_SCORE_REDERIVE_NOISE`: a straddle whose
    whole magnitude is inside the measured re-derivation band is reported
    as a warning that NAMES the boundary, because the alternative is
    refusing to re-render an honest page whose payload moved under it —
    which is what the shipped 2026-08-02 plan does (opener 5.6, payload
    re-derived at 5.4 after that afternoon's import, straddling 5.5).

    WHAT THIS DELIBERATELY LETS THROUGH. A disagreement INSIDE one band is
    a warning however large it is, and the top band is wide: the highest
    boundary is 6.5, so "9.9 out of 10" against a real 6.6 warns. That is
    what decision equivalence means — both numbers prescribe green-light
    programming — but it is a factual overstatement on the page, and the
    warning is the only thing that says so. If a rule against overstating
    the score itself is wanted, it is a separate rule with a separate
    justification, not a magnitude smuggled back into this one.

    Silent when the payload carries no ``recovery.score``: there is then
    nothing to contradict, and inventing a finding from a missing input
    is how a gate starts blocking on unrelated payload gaps.
    """
    score = _payload_recovery_score(payload)
    errors: "list[str]" = []
    warnings: "list[str]" = []
    if score is None:
        return (errors, warnings)
    # One message per distinct claim. A plan opener states the day's call
    # and then repeats the number in its `> Why:` line, which is two
    # matches of the same claim and would otherwise print the identical
    # line twice; a claim of a DIFFERENT number produces a different
    # message and still prints.
    seen: "set[str]" = set()

    def _add(bucket: "list[str]", message: str) -> None:
        if message not in seen:
            seen.add(message)
            bucket.append(message)

    for label, text in texts:
        if not isinstance(text, str) or not text:
            continue
        for matched, written in _recovery_score_claims(label, text):
            places = len(written.split(".")[1]) if "." in written else 0
            if round(float(written), places) == round(score, places):
                continue
            value = float(written)
            straddled = _boundaries_between(value, score)
            gap = round(abs(value - score), _SCORE_ROUND_PLACES)
            if not straddled:
                _add(warnings,
                     f"{label}: says recovery is {matched}; the payload's "
                     f"`recovery.score` is {score:g}. No decision threshold "
                     f"separates them, so this reads as a re-derived payload "
                     f"rather than a wrong number.")
                continue
            crossed = ", ".join(f"{t:g}" for t in straddled)
            if gap <= COACH_SCORE_REDERIVE_NOISE:
                _add(warnings,
                     f"{label}: says recovery is {matched}; the payload's "
                     f"`recovery.score` is {score:g}. That straddles {crossed}, "
                     f"but the whole gap is {gap:g}, inside the measured "
                     f"re-derivation band of {COACH_SCORE_REDERIVE_NOISE:g}, so "
                     f"it reads as a payload that moved rather than a wrong "
                     f"number. Re-generate the page against the current "
                     f"payload.")
                continue
            _add(errors,
                 f"{label}: says recovery is {matched}, but the payload's "
                 f"`recovery.score` is {score:g}. Those fall on opposite sides "
                 f"of {crossed}, so they prescribe different training. Coach "
                 f"text may round the score, not contradict it.")
    return (errors, warnings)


def _coach_strings(coach: dict) -> "list[tuple[str, str]]":
    """Every coach-authored string in ``coach``, labelled for messages."""
    out: "list[tuple[str, str]]" = []
    headline = coach.get("headline")
    if isinstance(headline, str):
        out.append(("`headline`", headline))
    cards = coach.get("cards")
    if isinstance(cards, dict):
        out += [(f"cards.{k}", v) for k, v in sorted(cards.items())
                if isinstance(v, str)]
    return out


def validate_coach_reads(coach: dict,
                         payload: "dict | None" = None
                         ) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)``.

    Errors are hard failures (the renderer refuses to write the HTML).
    Warnings are surfaced to stderr but don't block the render. A
    missing ``cards.<key>`` for a documented card is a warning, not an
    error, because the card itself still renders cleanly without a
    callout.

    ``payload`` is the tracker JSON. When given, coach-authored scores are
    cross-checked against it (`coach_number_findings`) and a contradiction
    is an ERROR — a dashboard that states a recovery score the payload
    disagrees with is worse than no dashboard. It is optional so that
    every existing caller and every unit test that only has coach text
    keeps working; a caller that HAS the payload and does not pass it gets
    the pre-2026-08 behaviour, which is that the exploit above renders.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(coach, dict):
        return (["coach reads must be a JSON object"], warnings)
    num_errors, num_warnings = coach_number_findings(payload,
                                                     _coach_strings(coach))
    errors += num_errors
    warnings += num_warnings

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
                f"{workout_title}: {sub_bullet_count} rationale sub-bullets; "
                f"recommended max is {WORKOUT_SUB_BULLET_LIMIT} "
                f"(anchor-change and other-gym lines do not count)"
            )

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()

        if _workout_heading_title(line) is not None:
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

        marker = WORKOUT_SUB_BULLET_RE.match(line)
        if marker:
            # Structural lines are not rationale; see
            # WORKOUT_STRUCTURAL_SUB_BULLET_RE. The exemption is decided on
            # the sub-bullet's BODY and must match at its start, so a line
            # that merely mentions "anchor change:" halfway through a
            # paragraph of rationale is counted like any other. They are
            # still scanned for banned rationale phrasing below, so
            # appending a "because …" to one does not buy an exemption
            # either.
            if not WORKOUT_STRUCTURAL_SUB_BULLET_RE.match(line[marker.end():]):
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


# Shared by `_iter_workout_exercise_bullets` (and therefore by both
# `count_working_sets_per_workout` and `workout_core_warnings`): a working
# set is a `///`-separated rep/load token on an exercise bullet, excluding
# any token marked `(warmup)`. One definition, every consumer.
_WORKOUT_HAS_DIGIT_RE = re.compile(r"\d")
# loaded = an explicit kg load, or a digit-x-digit rep/load token
# (e.g. "8x3", "40 x 8"). NOT a bare "x" anywhere in the line.
_WORKOUT_LOADED_RE = re.compile(r"kg|\d\s*[x×]\s*\d", re.IGNORECASE)
# An EXTERNAL load specifically: a number immediately before `kg`.
# Narrower than `_WORKOUT_LOADED_RE`, which also accepts a bare `3 x 12`
# rep token — that says nothing about load. Used only where "is this
# movement loaded?" is the actual question (the core spec's
# loaded-flexion requirement).
#
# No trailing `\b`: the canonical dose format is `30kgx10-12`, where `kg`
# runs straight into the rep separator. Requiring a boundary there scored
# every loaded set in every real plan as unloaded.
_WORKOUT_EXTERNAL_LOAD_RE = re.compile(r"\d\s*kg", re.IGNORECASE)

# Time- and distance-denominated work. Isometric holds and loaded carries
# are prescribed in seconds and metres, not reps, and before 2026-08 they
# scored ZERO working sets: the token test accepted only `kg` or
# digit-x-digit. A documented, correctly-written hold bullet therefore
# produced a false "0 core sets, under-allocated" warning, which is a
# validator arguing against the very movements the core spec exists to
# introduce.
#
# `MM:SS` is accepted alongside `45s` / `45 sec` / `45 seconds` because
# that is the unit `duration_min` stores. Metres are accepted for carries.
_HOLD_SECONDS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*s(?:ec|ecs|econd|econds)?\b", re.IGNORECASE)
_HOLD_CLOCK_RE = re.compile(r"\b(\d+):([0-5]\d)\b")
# Metres, NOT minutes: `\b` after `m` is what stops `3 min` matching, since
# `i` is a word character. Keep that boundary — without it every cardio-style
# `5 min easy` bullet becomes a working set.
_CARRY_METRES_RE = re.compile(r"(\d+(?:\.\d+)?)\s*m\b", re.IGNORECASE)

# Floors below which a timed or measured token is a technique drill, not a
# working set. Accepting seconds as work without a floor would hand the
# coach a new degenerate solution — `4 x 5s` satisfies a 4-set core budget
# for 20 seconds of total work. Deliberately low so a beginner's shortest
# legitimate hold still counts; raise only with evidence.
MIN_CREDITED_HOLD_SECONDS = 10.0
MIN_CREDITED_CARRY_METRES = 10.0


def _token_hold_seconds(token: str) -> "float | None":
    """Seconds of hold/carry time in a set token, or None if it has none."""
    m = _HOLD_CLOCK_RE.search(token)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = _HOLD_SECONDS_RE.search(token)
    return float(m.group(1)) if m else None


def _token_carry_metres(token: str) -> "float | None":
    """Metres of carry distance in a set token, or None if it has none."""
    m = _CARRY_METRES_RE.search(token)
    return float(m.group(1)) if m else None


def _token_is_working_set(token: str, multi: bool) -> bool:
    """Whether one `///`-separated token is a working set.

    Order matters. A token carrying a real load or rep-x-load pair is work
    regardless of anything else on it — that check comes first so a cue
    like `(3s pause)` riding along on a loaded set cannot drag the set
    under the hold floor and delete it.

    ``multi`` is "this bullet lists several `///` sets", which is what
    makes a bare bodyweight rep token (`8-10`) count. A single unloaded,
    untimed token is prep, not work.
    """
    if "warmup" in token.lower():
        return False
    if not _WORKOUT_HAS_DIGIT_RE.search(token):
        return False
    if _WORKOUT_LOADED_RE.search(token):
        return True
    seconds = _token_hold_seconds(token)
    if seconds is not None:
        return seconds >= MIN_CREDITED_HOLD_SECONDS
    metres = _token_carry_metres(token)
    if metres is not None:
        return metres >= MIN_CREDITED_CARRY_METRES
    return multi


def _bullet_working_set_tokens(body: str) -> "list[str]":
    """Return the working-set tokens in a bullet body.

    A token counts when it is loaded (`kg` or a rep-x-load pair), or is a
    qualifying timed hold / carry distance, or is a bare rep token on a
    bullet that lists several `///` sets. The `///` clause is what catches
    bodyweight multi-set work like `Dip: 8-10 /// 8-10 /// 8-10`, which a
    bare `kg`/`x`-substring test scores as zero (silently shrinking the
    budget). Pure prep bullets (`Jumping Jacks: 50`, a single bodyweight
    line with no load, no time and no `///`) return `[]`.
    """
    multi = "///" in body
    return [t for t in body.split("///") if _token_is_working_set(t, multi)]


@lru_cache(maxsize=1)
def _plan_workout_heading_re() -> "re.Pattern[str]":
    """The plan's workout-heading grammar, borrowed from `adherence`.

    `## Workout N:`, `## Deload Session N:` and `## Session N:` are all
    real headings the coach emits, and `adherence._WORKOUT_HEADING_RE`
    is where that fact is written down — the ledger had to learn it the
    hard way when matching only ``Workout`` silently parsed two of one
    person's fourteen plans to zero prescribed slots.

    This module used to match ``^##\\s+Workout\\b`` and nothing else,
    which produced two OPPOSITE failures from one inconsistency: a
    deload plan written with `## Workout N:` got judged against
    full-volume specs, while one written with `## Session N:` bypassed
    the core and arm checks completely. One grammar, one place.

    Imported through a cached accessor rather than at module scope
    because pulling in `adherence` costs a parse on every cold render,
    and a render that validates no plan should not pay it.
    """
    from .adherence import WORKOUT_HEADING_RE as LEDGER_HEADING_RE
    return LEDGER_HEADING_RE


# The validator recognises a deliberately broader grammar than the ledger's.
#
# The ledger needs kind + index + title to build a stable slot identity,
# so it insists on the colon. The validator only needs to know "a workout
# block starts here", and the asymmetry of being wrong is not symmetric:
# over-recognising costs a spurious finding a human reads and dismisses,
# while under-recognising silently disables every check on that workout —
# the exact failure this workstream exists to remove.
#
# Both directions have now bitten in practice. Matching `Workout` alone
# let an off-catalog exercise inside a `## Deload Session` heading render
# clean (four real plans use that heading). Narrowing to the ledger's
# grammar instead dropped `## Workout 1` with no colon, which the old
# gate caught. Hence: ledger grammar first for the display form, this
# permissive form as the fallback.
# The index token is required and is a single character, which is what
# keeps `## Workout Notes:` out: `N` is not followed by a word boundary.
# The colon and title are optional, which is the only way this differs
# from the ledger's grammar.
_ANY_WORKOUT_HEADING_RE = re.compile(
    r"^##\s+((?:Deload\s+Session|Workout|Session)\s+(?:[0-9]+|[A-Za-z])\b.*)$",
    re.IGNORECASE)


def _workout_heading_title(line: str) -> "str | None":
    """The workout title on ``line``, or ``None`` if it is not one."""
    from .adherence import workout_heading_title
    title = workout_heading_title(line)
    if title is not None:
        return title
    m = _ANY_WORKOUT_HEADING_RE.match(line)
    return m.group(1).strip() if m else None


def _iter_workout_exercise_bullets(text: str) -> "dict[str, list[dict]]":
    """Walk workout blocks into an ordered list of exercise-bullet
    records per title:
    ``{"name": str, "sets": int, "loaded": bool, "raw": str}``.

    A "workout block" is whatever `_plan_workout_heading_re` recognises:
    `## Workout N:`, `## Deload Session N:`, `## Session N:`.

    ``loaded`` means the bullet prescribes an external kg load. It is a
    separate flag from ``sets`` because the core spec asks two different
    questions of the same bullet — "how much work?" and "is this movement
    carrying load?" — and the second must not be inferred from a rep-count
    format.

    This is the single pass over the markdown that both
    `count_working_sets_per_workout` (aggregate per-workout set count)
    and `workout_core_warnings` (per-bullet core checks) build on, so
    workout-scope handling and the working-set-token rule
    (`_bullet_working_set_tokens`) live in exactly one place.

    Any other `##` heading (e.g. `## Cardio 1:`, `## Notes`) resets the
    active title so its bullets never leak into a workout's bullets.
    Deeper headings (`###`, `####`, ...) are treated as sub-sections
    within the current workout block and do NOT reset the scope.
    """
    out: "dict[str, list[dict]]" = {}
    title = None
    for raw in text.splitlines():
        line = raw.rstrip()
        heading = _workout_heading_title(line)
        if heading is not None:
            title = heading
            out[title] = []
            continue
        # only a ## heading (not a workout heading, handled above) ends
        # the current workout's bullet scope.  ### and deeper headings
        # (e.g. ### Accessories) are sub-sections within a workout block
        # and must NOT clear the active title.
        if re.match(r"^##\s+", line):
            title = None
            continue
        if title and line.startswith("- ") and ":" in line:
            head, body = line.split(":", 1)
            out[title].append({
                "name": head[2:].strip(),
                "sets": len(_bullet_working_set_tokens(body)),
                "loaded": bool(_WORKOUT_EXTERNAL_LOAD_RE.search(body)),
                "raw": line,
            })
    return out


def count_working_sets_per_workout(text: str) -> "dict[str, int]":
    """Count working sets under each `## Workout` heading.

    See `_iter_workout_exercise_bullets` and `_bullet_working_set_tokens`
    for what counts as a working set and where a workout's bullet scope
    starts/ends.
    """
    return {
        title: sum(b["sets"] for b in bullets)
        for title, bullets in _iter_workout_exercise_bullets(text).items()
    }


# The session working-set band, both sides, in sets.
#
# SKILL.md: "`target_working_sets` is a floor to hit, not a ceiling to
# fear. Land within ±2 of it." The gate allowed 21-29 on a 24 budget while
# the prompt asked for 22-26, and targets are floors, so the coach
# maximises above them until a band stops it. Measured on the shipped
# 2026-08-02 plans: four of eight sessions across two people landed
# EXACTLY on the old +5 ceiling, which is the signature of a tolerance
# being used as the target. One plan ran 29/28/27/29 against a 24 budget
# and warned on nothing, on a green tier with no carve-out, while clearing
# every emphasis floor with room — so the overshoot was not forced by the
# volume floors either. That budget was cut to 24 in the first place
# BECAUSE the user truncates long sessions at ~64% completion; a 29-set
# session re-creates the problem the cut addressed.
#
# Symmetric at 2, not tighter on the short side. SKILL.md calls
# undershooting "the failure mode that under-serves the user", so the low
# side must be at least as tight as the high side; ±2 is what the prompt
# says, and there is no evidence for going narrower than the instruction
# the plan was written against.
#
# THIS STAYS A WARNING. `validate_workout_plan` routes it into
# ``warnings``, never ``errors``, and tightening a band that cannot block
# a render cannot break a plan — it can only make an existing silence
# audible. Both directions need to stay renderable: a deload legitimately
# undershoots, and SKILL.md's own conflict rule ("when the budget and the
# volume floors cannot both be met, the budget loses") requires a legal
# way to go over.
SET_BUDGET_UNDER_TOL = 2
SET_BUDGET_OVER_TOL = 2


def workout_set_budget_warnings(text: str, target_working_sets,
                                low_tol: int = SET_BUDGET_UNDER_TOL,
                                high_tol: int = SET_BUDGET_OVER_TOL,
                                budget_by_index=None) -> "list[str]":
    """Warn when a workout's working-set count drifts from the budget.

    `target_working_sets` is the per-person, tier-adjusted set budget.
    Both tolerances default to `SET_BUDGET_UNDER_TOL` /
    `SET_BUDGET_OVER_TOL` — see those for why the band is SKILL.md's ±2
    rather than the old asymmetric 3/5. Warning, not error: an intentional
    deload/downgrade legitimately undershoots and an emphasis-heavy
    downgraded week legitimately overshoots, and both should still render,
    just visibly flagged.

    `budget_by_index`, when given, is a callable ``idx -> budget`` that
    returns the budget for the workout at position ``idx`` (0-based, in
    file order). This is needed for a Tier C downgrade, where only the
    first ``expected_rebound_by_session`` workouts are trimmed while later
    ones keep the FULL budget. Without it, a single global scale judged the
    full-volume later sessions against the shrunken early-session budget
    and falsely flagged them as "over" (which would tempt a coach to trim a
    correct, full session back down).
    """
    warnings: "list[str]" = []
    for idx, (title, n) in enumerate(count_working_sets_per_workout(text).items()):
        budget = budget_by_index(idx) if budget_by_index else target_working_sets
        if not budget or budget <= 0:
            continue
        if n < budget - low_tol:
            warnings.append(
                f"{title}: {n} working sets vs budget {budget} "
                f"({budget - n} under) — confirm this is an "
                f"intentional deload/downgrade, else add sets to the main lifts")
        elif n > budget + high_tol:
            warnings.append(
                f"{title}: {n} working sets vs budget {budget} "
                f"({n - budget} over) — trim a set or two")
    return warnings


# A core bullet may not carry the "optional last set" qualifier that
# `SKILL.md`'s per-set-qualifier convention sanctions elsewhere. §24:
# "Never mark a core set optional."
CORE_OPTIONAL_QUALIFIER_RE = re.compile(
    r"\b(if you can make it|optional)\b", re.IGNORECASE
)


# ---------------------------------------------------------------------
# Finding axes. Every prescription finding is tagged with one, and the
# tag answers exactly one question: DOES SATISFYING THIS COST FATIGUE?
#
# That question is the whole deload story. A planned deload is a
# deliberate whole-week volume reduction, so a floor on how much work
# there is contradicts the intent of the week and must not block. A
# floor on how MANY DIFFERENT movements, in how many patterns, and how
# often any one of them repeats costs nothing at all — three sessions at
# two core sets each still comfortably allows three distinct movements
# across three categories. A deload is not a licence to go back to four
# sets of the same crunch, which is the failure this build exists to
# stop.
#
# So: volume floors are demotable, everything else is not.
AXIS_VOLUME = "volume"        # a floor on HOW MUCH work. Costs fatigue.
AXIS_STRUCTURE = "structure"  # diversity, identity, placement, ceilings.

# Recovery-gate labels that mean "this whole week is a prescribed volume
# reduction". Read off `session_recommendation`, which is where
# `tier_budget_by_index` already reads the same decision from — one
# source, two questions asked of it.
#
# `downgrade` (Tier C) is deliberately NOT here, and that is the load-
# bearing exclusion. Tier C fires on poor systemic recovery, and the
# right response is to cut the systemically expensive work (compound
# volume), not the cheap work. Core and direct-arm sets are low-fatigue
# and are precisely the chronically under-dosed categories this build
# exists to protect; halving them on a bad-recovery day would re-create
# the under-dosing, on exactly the days a coach is most likely to reach
# for it. Under Tier C the isolation cut comes out of the rest of the
# accessory block and the per-muscle floors and `core_week_spec` stay
# enforced.
# The set itself is `constants.DELOAD_WEEK_LABELS` (imported above), so the
# tracker can read the same decision when it scales the payload's floors.


# The smallest per-exercise dose a diversity axis may force a week into.
#
# "Diversity costs no fatigue" is true only while satisfying it still
# leaves a sensible dose on each movement. Splitting 2 sets across 2
# exercises yields two 1-set doses, which is WORSE training than one
# 2-set dose — so at that volume the axis is not costless and must not
# block. Splitting 6 sets across 3 categories yields 2 sets each, which
# is a fine minimum dose, so there it is costless and must block.
#
# Two is the floor because one set of anything is a rehearsal, not a
# dose. Raise it only with evidence.
MIN_SETS_PER_DISTINCT_EXERCISE = 2


def _dose_aware_distinct_floor(spec_min: int, available_sets: int) -> int:
    """How many distinct movements this week can be REQUIRED to contain.

    ``min(spec_min, available_sets // MIN_SETS_PER_DISTINCT_EXERCISE)``.

    A dose-aware floor rather than a deload carve-out, and the shape
    matters:

    * It fires on a deload AND on any other genuinely low-volume week,
      including ones nobody has enumerated.
    * It cannot be gamed the way a blanket demotion can. Prescribing
      fewer sets lowers the distinct-exercise requirement but does NOT
      lower the volume floors, which stay blocking on a normal week — so
      a coach cutting volume to escape the diversity axis walks straight
      into the volume axis.
    * It is one rule instead of two.
    """
    if spec_min <= 0 or available_sets <= 0:
        return 0
    return min(spec_min, available_sets // MIN_SETS_PER_DISTINCT_EXERCISE)


def _required_flexion_sets(total_core_sets: int, spec: dict) -> int:
    """How many of the week's core sets must be spinal flexion.

    ``max(min_flexion_sets_per_week, ceil(share x total_core_sets))`` —
    the two conditions are an AND, so the share binds on a normal week
    and the absolute floor binds on a small one. See
    `constants.CORE_WEEK_SPEC` for why the share is a third and the
    absolute floor is three, and `_core_week_findings` for why the two
    halves are reported under DIFFERENT axes despite this one number:
    reallocating a set into flexion costs no fatigue, adding one does.

    Zero core sets returns zero, and that is not a loophole. A week with
    no core at all is already named by three louder findings ("no core
    exercise", "0 core sets, under-allocated", "0 distinct core
    exercises"); adding "0 of 0 core sets are flexion" to the pile says
    nothing new and reads like a bug. The distribution question only has
    an answer once there is something to distribute.

    Deliberately NOT dose-capped the way `_dose_aware_distinct_floor` is.
    That cap exists because forcing diversity onto a small dose produces
    1-set rehearsals — a real training cost. Concentrating a small dose
    onto one pattern has no such cost, so the floor stands at every
    volume. Below three total core sets it simply cannot be met, which is
    correct: three core sets is not a core week.
    """
    if total_core_sets <= 0:
        return 0
    share = spec["min_flexion_share_of_core_sets"]
    return max(spec["min_flexion_sets_per_week"],
               ceil(share * total_core_sets))


def _dose_cap_note(spec_min: int, effective_min: int, available_sets: int,
                   unit: str) -> str:
    """Why the required count is below the spec's, when it is."""
    if effective_min >= spec_min:
        return ""
    return (f" (spec floor {spec_min}, capped by {available_sets} {unit} at "
            f"{MIN_SETS_PER_DISTINCT_EXERCISE} sets per exercise)")


def is_deload_week(session_recommendation: "dict | None") -> bool:
    """Whether this week is a FULL-BLOCK volume cut: every session halved.

    Only then are the volume findings advisory (`validate_workout_plan`'s
    ``deload_week``). It is the recovery gate's call, read off
    ``session_recommendation`` (`constants.full_block_deload`): Tier A, a
    `DELOAD_WEEK_LABELS` label, or a load policy of ``reduce`` (Tier A/B, or
    strength TSB in the high-fatigue band). Tier C ``downgrade`` is NOT one;
    see `DELOAD_WEEK_LABELS`.

    The block's CADENCE deload ("six weeks since the last, cut one session
    in half") is NOT a full-block deload and does not come through here: it
    is ONE halved session in an otherwise normal week, so it must not switch
    the floors off for the whole week. See `is_cadence_deload_week`.

    Deliberately NOT inferred from set counts. "This plan looks light, so it
    must be a deload" is the gaming vector that would let any under-dosed
    week excuse itself; the deload has to be DECLARED upstream, by whoever
    decided it.
    """
    return full_block_deload(session_recommendation)


def is_cadence_deload_week(session_recommendation: "dict | None",
                           block: "dict | None") -> bool:
    """Whether this week carries the block's cadence deload session.

    ``block.deload_prescribed``, written by `blocks.block_payload` on the
    generation where weeks-since-the-last-deload first crosses
    `blocks.DELOAD_CADENCE_WEEKS`. It is a block decision, not a recovery
    one, and on those runs `session_recommendation` reads ``tier: D, label:
    green``. ONE session is halved (SKILL.md, Deload and re-entry), so the
    week keeps every volume floor, scaled by (n - 0.5) / n
    (`constants.floor_scale`), and the core dose in full: core is exempt from
    the halving. False when a full-block deload already applies, which
    subsumes it. The ``.get`` stays a ``.get`` because this is also called
    with a raw on-disk block artifact, which carries no cadence fields.
    """
    return cadence_deload_week(session_recommendation, block)


@lru_cache(maxsize=1)
def _core_pattern_categories() -> "tuple[set[str], dict[str, set[str]]]":
    """Return ``(core exercise names, {pattern category: names})``, all
    lowercased canonical names read from the exercise catalog.

    Neither structure is a hardcoded list (`Skills/CLAUDE.md`: *"Do not
    copy ... exercise catalog parsing into another module."*):

    - **Core membership** comes from `load_exercises_db` — the coach's
      own catalog parser (`workout_coach.lib.extract`) — filtered to
      entries whose resolved ``primary`` muscle is ``"core"``. This is
      also what implements D4 without a special case: a two-handed
      farmer's walk is catalogued under FULL BODY with no core credit, so
      it never enters ``core_names`` and cannot satisfy a core target,
      while a one-handed suitcase carry is catalogued under CORE and does.
      The distinction lives in the catalog, where the evidence for it is
      written down, not in a list here.
    - **Pattern categories** come from a *different* existing parser:
      `shared.exercises_database.parse_database()`. This is deliberate,
      not redundant. `load_exercises_db` resolves every CORE subsection
      to the same ``primary: "core"`` — `SUBSECTION_PRIMARY_HINTS` has no
      core-specific entries, so once ``primary`` is resolved the
      subsection identity is discarded. It cannot answer "which movement
      pattern is this." That information only survives in
      `parse_database()`, which preserves the catalog's full
      ``{muscle: {section: [entries]}}`` structure — the same parser
      `/log`'s proposal flow and the catalog CLI already read. Reading
      its ``muscles["CORE"]["sections"]`` is reuse of an existing parser,
      not a second literal list or a parallel one.

    Category keys are the subsection headings, lowercased and stripped
    (``flexion``, ``anti-extension``, ``anti-rotation``,
    ``anti-lateral-flexion``, ``rotation``). They are read, not enumerated
    here: adding a subsection to the catalog adds a category, and the
    ``min_pattern_categories_per_week`` axis picks it up with no code
    change.
    """
    from shared.exercises_database import entry_canonical_name, parse_database

    core_names = {name for name, muscle in _primary_muscle_by_exercise().items()
                  if muscle == "core"}

    sections = (
        parse_database().get("muscles", {}).get("CORE", {})
        .get("sections", {})
    )
    categories: "dict[str, set[str]]" = {}
    for heading, entries in sections.items():
        key = (heading or "").strip().lower()
        if not key:
            continue
        names = {entry_canonical_name(e).strip().lower() for e in entries}
        if names:
            categories.setdefault(key, set()).update(names)

    return core_names, categories


def _session_core_set_bounds(title: str, spec: dict,
                             bullets=None) -> "tuple[int, int]":
    """``(min_sets, max_sets)`` of core work for one workout heading.

    Which per-session core budget a workout gets (D3). Read off the
    workout heading AND the session's own bullets, through
    ``adherence.session_type_from_title``, the repo's one classifier for
    that question.

    ``bullets`` is what closes the last free-text hole. The heading is
    written by the party being policed, and ``upper`` is the only session
    type whose budget (2) sits BELOW the fail-safe the other three share
    (4) — so it is the only answer a name can profit from. A leg day
    named ``PUSH`` classified confidently as upper and bought the 2-set
    budget; ``FULL BODY`` and unclassifiable headings had already been
    closed by failing safe, but a confident wrong answer is not fixable
    by a fail-safe. Passing the bullets lets the classifier check the
    claim against the catalog-derived regions of the movements actually
    prescribed, which the coach does not author. Content may move the
    answer to a MORE demanding budget, never to a cheaper one — the
    reverse would be the same exploit running backwards. This module used to carry a second pair of heading
    regexes; two vocabularies for one concept is how the ledger and the
    validator end up disagreeing about which sessions are lower days,
    and the answer drives the 4-on-lower / 2-on-upper budget.

    A heading the classifier cannot place (``None``), or one it places as
    ``full``, gets the LARGER of the two budgets as its floor and the
    larger as its ceiling — i.e. the lower-day band. D3 names no budget
    for a full-body session, so something has to be assumed, and the two
    directions are not symmetric.

    Until 2026-08-02 this returned ``min(lower, upper)`` as the floor,
    reasoning that a loose bound beats a fabricated one. That is true of
    a CEILING and false of a FLOOR, and the asymmetry is exploitable:
    ``session_type_from_title`` answers ``full`` for any heading naming
    both halves, and the heading is free text the coach writes. So a
    coach could pick its own core budget by naming the session — the
    measured exploit renamed four sessions ``FULL BODY A..D`` and halved
    the week's core floor from 12 sets to 8 without changing a single
    bullet. A validator whose thresholds are chosen by the artifact it is
    validating is not a validator.

    Choosing the lower-day floor rather than the upper-day one is the
    conservative direction for the same reason the whole build exists:
    the measured failure is chronic UNDER-dosing, and a full-body session
    has at least as much room for core as a lower day does. Over-asking
    costs a coach one extra core set on an unclassified heading, and it
    is fixable by naming the session honestly; under-asking is invisible.
    """
    from .adherence import session_type_from_title  # local: analytics import

    per_session = spec["sets_per_session"]
    lower, upper = per_session["lower"], per_session["upper"]
    tol = spec.get("session_set_overshoot_tolerance", 0)
    stype = session_type_from_title(title, bullets)
    if stype == "lower":
        return lower, lower + tol
    if stype == "upper":
        return upper, upper + tol
    return max(lower, upper), max(lower, upper) + tol


def workout_core_warnings(text: str, spec: "dict | None" = None,
                          min_sets: "int | None" = None,
                          max_sets: "int | None" = None) -> "list[str]":
    """PER-SESSION core checks. Returns a list of finding strings.

    These are the `core_week_spec` axes that can be judged on a single
    `## Workout` block. The weekly axes — distinct exercises, pattern
    categories, per-exercise frequency, the loaded-flexion requirement —
    live in `core_week_errors`, because none of them is answerable from
    one session. `validate_workout_plan` runs both and returns the union
    as BLOCKING errors.

    The name is historical. These findings stopped being advisory on
    2026-08-02: the July fix made them stderr warnings and the next
    generated plan ignored them, which is what an advisory warning
    mid-pipeline buys you. Callers that still print to stderr are the
    remaining wiring gap, not a statement about severity.

    ``spec`` defaults to `constants.CORE_WEEK_SPEC`. The per-session dose
    is D3's 4-on-lower / 2-on-upper, resolved from the workout heading by
    `_session_core_set_bounds`. ``min_sets`` / ``max_sets``, when BOTH are
    given, override that with a flat band for every session — an escape
    hatch for a caller with a genuinely different budget, not a default.

    Per `## Workout` block, reports when:
      1. there is no core bullet at all;
      2. the LAST bullet in the workout is a core bullet (§24.2: core
         belongs inside the isolation block, never the terminal slot);
      3. total core working sets fall outside the session's band;
      4. a core bullet carries an "(if you can make it)" / "optional"
         qualifier (§24: never mark a core set optional).

    REMOVED 2026-08-02: "at least one spinal-flexion movement per
    session". It was one of the three rules that produced the outcome
    this workstream exists to fix — 94% of six months of logged core work
    spinal or hip flexion, anti-rotation 0 sets, loaded carry 0 sets.

    The arithmetic: on the D3 budget a four-day week is 4+2+4+2 = 12 core
    sets. Requiring a flexion movement in every session spends at least
    one bullet per session on flexion, which on a two-set upper day is
    half the session's entire core allocation. The best case a scheduler
    can do under both that rule and `min_pattern_categories_per_week` is
    a 50% flexion floor, reached only by prescribing one-set bullets. The
    rule cannot coexist with a distribution target; it IS a distribution
    target, pointed at a single pattern.

    Flexion is still mandatory — as a WEEKLY requirement, and a stricter
    one, in `core_week_errors`: at least one flexion movement carrying an
    external load. One concept, one source of truth, and the source is
    the axis that can express "some, not all".

    If the catalog can't resolve any core movement (an empty
    `core_names`, e.g. the CORE section was renamed out from under
    `SECTION_PRIMARY`), this fails open and returns nothing rather than
    flagging every workout as missing core — a validator that cannot
    identify core exercises must not pretend every session lacks one.
    """
    return [msg for _axis, msg in _core_session_findings(
        text, spec=spec, min_sets=min_sets, max_sets=max_sets)]


def _core_session_findings(text: str, spec: "dict | None" = None,
                           min_sets: "int | None" = None,
                           max_sets: "int | None" = None):
    """`workout_core_warnings`'s body, yielding ``(axis, message)``.

    The public wrapper flattens this to strings so every existing caller
    and test keeps its signature; `validate_workout_plan` consumes the
    tags so a deload can demote the volume findings without anyone
    string-matching on the message text.
    """
    spec = _resolved_spec(spec, CORE_WEEK_SPEC, "core_week_spec")
    flat_band = min_sets is not None and max_sets is not None

    core_names, _categories = _core_pattern_categories()
    if not core_names:
        return

    for title, bullets in _iter_workout_exercise_bullets(text).items():
        if not bullets:
            continue
        # A block that prescribes no working sets at all is not a
        # strength session — `## Session 1: Zone 2 cardio + mobility` is
        # a real heading under the shared grammar, and asking it for a
        # core budget invents a violation. Not an escape hatch: a
        # session with zero sets also contributes zero to every weekly
        # axis (those already ignore zero-set bullets), so nothing can
        # be hidden here, and the set-budget check will say the session
        # is empty far more loudly than a core finding would.
        if not any(b["sets"] for b in bullets):
            continue
        lo, hi = ((min_sets, max_sets) if flat_band
                  else _session_core_set_bounds(title, spec, bullets))

        core_bullets = [b for b in bullets if b["name"].lower() in core_names]
        if not core_bullets:
            # The zero case of the dose floor, so it demotes with it.
            yield (AXIS_VOLUME,
                   f"{title}: no core exercise — the core spec budgets "
                   f"{lo} sets on this session type")
            continue

        if bullets[-1]["name"].lower() in core_names:
            yield (AXIS_STRUCTURE,
                   f"{title}: core is the last bullet — §24 requires it "
                   f"inside the isolation block")

        total_core_sets = sum(b["sets"] for b in core_bullets)
        if total_core_sets < lo:
            yield (AXIS_VOLUME,
                   f"{title}: {total_core_sets} core sets — the core spec "
                   f"budgets {lo}-{hi} on this session type, under-allocated")
        elif total_core_sets > hi:
            # A CEILING, not a floor. A deload reduces volume; it cannot
            # produce an overshoot, so this never needs demoting and
            # must not be demotable.
            yield (AXIS_STRUCTURE,
                   f"{title}: {total_core_sets} core sets — the core spec "
                   f"budgets {lo}-{hi} on this session type, over-allocated")

        for b in core_bullets:
            if CORE_OPTIONAL_QUALIFIER_RE.search(b["raw"]):
                yield (AXIS_STRUCTURE,
                       f"{title}: {b['name']} is marked optional — §24 says "
                       f"never mark a core set optional")


def core_week_errors(text: str, spec: "dict | None" = None) -> "list[str]":
    """WEEKLY core checks — the distribution axes. Blocking.

    A quantity-only target is always satisfiable by the cheapest legal
    item times N; the measured proof is `Ab Crunch Machine x2 sets x4
    sessions`, which cleared every validator the system had while
    producing a training week that is 100% spinal flexion. These are the
    three axes that make that plan illegal:

      * ``min_distinct_exercises_per_week``   — diversity of movement
      * ``min_pattern_categories_per_week``   — diversity of PATTERN,
        read from the catalog's own CORE subsections. This is the axis
        that survives equipment-flavour gaming: two cable woodchop
        directions are two distinct exercises but one category.
      * ``max_sessions_per_exercise_per_week`` — identity. Caps how much
        of the week any single movement may be.

    Plus two flexion requirements, which are separate constraints and
    not a duplicate:

      * ``min_loaded_flexion_exercises_per_week`` — identity. At least
        one flexion movement carrying an external kg load. Without it a
        week of bodyweight holds satisfies every count above while
        dropping the only progressively-loadable pattern.
      * ``min_flexion_share_of_core_sets`` / ``min_flexion_sets_per_week``
        — quantity, on the pattern. The identity axis counts EXERCISES,
        so one bullet at one set clears it, and a week of 8 core sets
        carrying a single flexion set cleared every other axis in this
        file while being 12.5% flexion. See `_required_flexion_sets`.

    A core bullet contributing ZERO working sets does not count toward
    any axis. Naming a movement is not performing it, and a spec that
    counted names would be satisfiable by listing three exercises at
    zero sets each.

    Fails open (returns nothing) when the catalog resolves no core
    movement, and when the markdown contains no `## Workout` block with
    bullets — a weekly distribution is not a question you can ask of a
    document that prescribes no week.
    """
    return [msg for _axis, msg in _core_week_findings(text, spec=spec)]


def _core_week_findings(text: str, spec: "dict | None" = None):
    """`core_week_errors`'s body, yielding ``(axis, message)``.

    The three distribution axes are `AXIS_STRUCTURE`: they cost no
    fatigue, so a deload does not excuse them. The loaded-flexion
    identity requirement is `AXIS_VOLUME` — it asks for a specific kind
    of work to be PRESENT, and a week that has deliberately cut work
    cannot be made to answer for its absence. The flexion set floor
    straddles the two and is tagged per threshold; see below.
    """
    spec = _resolved_spec(spec, CORE_WEEK_SPEC, "core_week_spec")
    core_names, categories = _core_pattern_categories()
    if not core_names:
        return

    per_workout = _iter_workout_exercise_bullets(text)
    if not any(bullets for bullets in per_workout.values()):
        return

    name_to_category = {name: cat
                        for cat, names in categories.items()
                        for name in names}
    flexion_key = spec["flexion_category"]

    sessions_per_exercise: "Counter[str]" = Counter()
    display_name: "dict[str, str]" = {}
    categories_seen: "set[str]" = set()
    distinct: "set[str]" = set()
    loaded_flexion: "set[str]" = set()
    total_core_sets = 0
    flexion_sets = 0

    for bullets in per_workout.values():
        in_this_session: "set[str]" = set()
        for b in bullets:
            name = b["name"].lower()
            if name not in core_names or b["sets"] <= 0:
                continue
            display_name.setdefault(name, b["name"])
            distinct.add(name)
            in_this_session.add(name)
            total_core_sets += b["sets"]
            category = name_to_category.get(name)
            if category:
                categories_seen.add(category)
                if category == flexion_key:
                    flexion_sets += b["sets"]
                    if b["loaded"]:
                        loaded_flexion.add(name)
        for name in in_this_session:
            sessions_per_exercise[name] += 1

    # How many distinct core movements this week's volume can carry at a
    # sensible dose. Every diversity axis below is capped by it.
    capacity = total_core_sets // MIN_SETS_PER_DISTINCT_EXERCISE

    # At ZERO core sets the relaxation does not apply and the spec stands
    # in full. The dose-aware floor answers "how finely can I slice the
    # volume I have"; with no volume there is nothing to slice, and a
    # week that prescribes no core at all is not a low-dose week, it is a
    # week with no core.
    #
    # This guard is load-bearing rather than tidy. The per-session
    # findings that would otherwise name the absence ("no core exercise",
    # "0 core sets, under-allocated") are both `AXIS_VOLUME` and demote
    # on a deload, so without it a "deload" listing three core movements
    # at zero credited sets each would clear every axis in the file.
    min_distinct = spec["min_distinct_exercises_per_week"]
    effective_distinct = (
        _dose_aware_distinct_floor(min_distinct, total_core_sets)
        if total_core_sets else min_distinct)
    if len(distinct) < effective_distinct:
        yield (AXIS_STRUCTURE,
               f"Week: {len(distinct)} distinct core exercises across the plan "
               f"— the core spec requires {effective_distinct}"
               + _dose_cap_note(min_distinct, effective_distinct,
                                total_core_sets, "core sets"))

    # Pattern categories get the same treatment. The instruction named
    # only the two `min_distinct` axes, but this one is the same shape —
    # "the week must contain N different things" — and leaving it out
    # would be incoherent: on a 3-set week the distinct floor would
    # relax to 1 while the category floor still demanded 3, forcing
    # exactly the three 1-set doses the rule exists to prevent.
    min_categories = spec["min_pattern_categories_per_week"]
    effective_categories = (
        _dose_aware_distinct_floor(min_categories, total_core_sets)
        if total_core_sets else min_categories)
    if categories and len(categories_seen) < effective_categories:
        listed = ", ".join(sorted(categories_seen)) or "none"
        yield (AXIS_STRUCTURE,
               f"Week: {len(categories_seen)} core pattern categories "
               f"({listed}) — the core spec requires {effective_categories} of "
               f"{len(categories)} available"
               + _dose_cap_note(min_categories, effective_categories,
                                total_core_sets, "core sets"))

    # The per-exercise session cap. Unlike the floors above, this one
    # gets MORE satisfiable as volume drops (with two core sessions a
    # 2-session cap cannot bind at all), so it never becomes
    # unsatisfiable from lack of volume in the way a floor does.
    #
    # It can still force a sub-minimal dose in one narrow case: an
    # exercise in K > max_sessions sessions has to be split into
    # ceil(K / max_sessions) movements, and if the week has too few sets
    # to give each of those a real dose, obeying the cap means
    # prescribing 1-set bullets. Same capacity, same test.
    max_sessions = spec["max_sessions_per_exercise_per_week"]
    for name, count in sorted(sessions_per_exercise.items()):
        if count <= max_sessions:
            continue
        needed = -(-count // max_sessions)      # ceil
        if capacity < needed:
            continue
        yield (AXIS_STRUCTURE,
               f"Week: {display_name[name]} appears in {count} sessions "
               f"— the core spec caps one exercise at {max_sessions} "
               f"sessions per week")

    min_loaded_flexion = spec["min_loaded_flexion_exercises_per_week"]
    if flexion_key in categories and len(loaded_flexion) < min_loaded_flexion:
        yield (AXIS_VOLUME,
               f"Week: {len(loaded_flexion)} loaded flexion movements — the "
               f"core spec requires {min_loaded_flexion} (a flexion exercise "
               f"carrying an external kg load, not bodyweight only)")

    # The flexion SET floor. The axis immediately above counts EXERCISES,
    # so one bullet at one set clears it; this one asks how much of the
    # week's core volume the pattern actually got. Without it the two
    # axes together permit a 12.5% flexion week, which is the exploit
    # this gate closes. Not folded into the exercise axis: "at least one
    # loadable flexion movement exists" and "flexion is a third of the
    # work" are different claims, and a week can satisfy either alone.
    #
    # TWO THRESHOLDS, TWO AXES, and the split is load-bearing rather than
    # fussy. Run the axis question ("does satisfying this cost fatigue?")
    # over each half separately and they answer differently:
    #
    #   * the SHARE is `AXIS_STRUCTURE`. Moving a set that already exists
    #     from anti-extension to flexion costs nothing at all — it is a
    #     reallocation, the same shape as every other distribution axis
    #     here. Tagging the whole floor as volume was tried first and
    #     handed the exploit a complete bypass: all five of its findings
    #     were volume, so a payload declaring `reactive_deload` demoted
    #     every one and the 12.5%-flexion week rendered at exit 0 again.
    #     A gate the artifact's own payload can disarm is the defect
    #     class this build removes.
    #   * the ABSOLUTE floor is `AXIS_VOLUME`. Below 9 core sets, getting
    #     to three flexion sets means ADDING work, and a deload will
    #     legitimately not. Demoting it is what keeps a half-volume week
    #     authorable — measured on the real 2026-07-13 plan, which sits
    #     at 2 flexion sets of 6 and satisfies the share exactly.
    #
    # One finding, not two: they are the same gap seen at two thresholds,
    # and reporting both for one shortfall is noise. Whichever binds is
    # the one reported, and it carries its own axis.
    if flexion_sets < _required_flexion_sets(total_core_sets, spec) \
            and flexion_key in categories:
        share = spec["min_flexion_share_of_core_sets"]
        by_share = ceil(share * total_core_sets)
        by_floor = spec["min_flexion_sets_per_week"]
        if flexion_sets < by_share:
            yield (AXIS_STRUCTURE,
                   f"Week: {flexion_sets} of {total_core_sets} core sets are "
                   f"{flexion_key} — the core spec requires {by_share}, at "
                   f"least {share:.0%} of core volume. Flexion is the pattern "
                   f"that loads the rectus abdominis; the other categories "
                   f"are anti-movement work and do not substitute for it")
        else:
            yield (AXIS_VOLUME,
                   f"Week: {flexion_sets} flexion sets across the plan — the "
                   f"core spec floor is {by_floor}/wk (the {share:.0%} share "
                   f"is met; the absolute floor is not)")


# ---------------------------------------------------------------------
# The weekly per-muscle floor. Every muscle but core, one rule; it replaces
# the arm-only weekly floor.
#
# That floor, and core's, were written for one reason: the volume model credits ~0.5 set per
# synergist, so a muscle can read "on target" with no direct set at all,
# and a muscle nobody floors is the first thing cut when the budget is
# tight. The 2026-10-10 plan dropped rear delt fly, shrugs and Y-T-W to
# fit 27 arm sets, and the only floor in force (arms) was satisfied.
#
# THE RULE. A muscle's DIRECT sets across the plan (bullets whose catalog
# ``primary`` is that muscle; synergist credit never counts) must reach:
#
#   emphasis tier -> its MEV in DIRECT sets (biceps 8, chest 8, triceps 6)
#   anything else -> its MV in DIRECT sets
#
# The function is `constants.muscle_floors`; `read_tracker` emits its result
# as ``payload["muscle_floors"]``, so the coach reads the number this check
# enforces. ``payload["muscle_volume_targets"][muscle]["tier"]`` picks the
# branch. The numbers come from ``constants.RP_DIRECT_SET_LANDMARKS``, not
# from the payload's ``target_sets``: that is in the tracker's FRACTIONAL
# unit (direct + the typical synergist credit, ``SYNERGIST_CREDIT_OFFSET``),
# and a direct count compared with it would ask biceps for 3 sets only a row
# can supply. It also keeps the bar out of the artifact under review: a
# payload that rewrites its tiers can lower a floor to MV, never below it,
# and this check ignores a ``muscle_floors`` key in the payload altogether.
#
# WHY THE FLOOR IS MEV FOR EMPHASIS AND MV FOR THE REST, AND NOT THE TIER
# TARGET. As of 2026-10-14 the tier targets (mid-MAV / MEV / MV) of the
# muscles a direct count can serve sum to 85 sets a week for Nihad and 86
# for Fabian, against set budgets of 24 and 21 a session (96 and 84 over
# four sessions): as a blocking floor that leaves Nihad 11 sets to place by
# judgement and Fabian none. The tier targets stay the aim for spare sets,
# per SKILL.md; the floor keeps a muscle from being dropped. Emphasis sits
# one band above the rest because the person named those muscles as the
# point of the block, and MEV is the smallest dose that grows them.
#
# CORE is not a row of this table. Its weekly dose is `CORE_WEEK_SPEC`
# (4 per lower day, 2 per upper day, so 12 on a two-and-two week, plus the
# flexion floor), which is what the weekly core floor was before this rule
# existed and is higher than core's generic MEV of 4. It is still enforced,
# per session, by `workout_core_warnings` and `core_week_errors`.
#
# SESSIONS, DELOADS AND TIERS. The landmarks are a four-session week's, so
# the floor is scaled by min(1, sessions / 4), rounded down
# (`constants.floor_scale`): a two-session week cannot carry 52 direct sets.
# AXIS_VOLUME, so a FULL-BLOCK deload (`is_deload_week`) demotes it to an
# advisory. A cadence deload (one halved session) does not: the floor stays
# blocking, scaled by (n - 0.5) / n more. A Tier C downgrade does neither
# (`DELOAD_WEEK_LABELS`). The floor is never scaled by tier; the set budget
# is, and when it cannot hold the floors the budget loses (SKILL.md).

# `constants.FLOOR_EXEMPT_MUSCLES` (erectors, forearms, core) are never
# floored here, and a muscle the catalog has no primary entry for (external
# rotators) is skipped for the opposite reason: it cannot be hit.


@lru_cache(maxsize=1)
def _primary_muscle_by_exercise() -> "dict[str, str]":
    """Lowercased canonical exercise name -> its resolved primary muscle.

    From `load_exercises_db`, the coach's own catalog parser. Primary
    only: synergist credit never sets ``primary``, which keeps the floor
    from counting the credit it exists to look past.
    """
    from .extract import load_exercises_db
    from shared.exercises_database import DATABASE_PATH

    return {name: meta["primary"]
            for name, meta in load_exercises_db(DATABASE_PATH).items()
            if meta.get("primary")}


def _direct_sets_by_muscle(text: str) -> "dict[str, Counter]":
    """``{muscle: Counter({exercise: working sets})}`` across the whole plan.

    A zero-set bullet is absent: naming a movement is not performing it.
    Empty for a document with no workout bullets, so every weekly check
    fails open on a summary doc.
    """
    primary = _primary_muscle_by_exercise()
    out: "dict[str, Counter]" = {}
    for bullets in _iter_workout_exercise_bullets(text).values():
        for b in bullets:
            name = b["name"].lower()
            if b["sets"] > 0 and name in primary:
                out.setdefault(primary[name], Counter())[name] += b["sets"]
    return out


def muscle_floors(tiers: dict, sessions_per_week: "int | None" = None,
                  cadence_deload: bool = False) -> "dict[str, int]":
    """Weekly direct-set floor per hittable muscle in ``tiers``.

    `constants.muscle_floors` restricted to the muscles the catalog has a
    primary entry for, scaled for the week's session count and for a cadence
    deload (`constants.floor_scale`). See the block comment above.
    """
    from .constants import muscle_floors as _muscle_floors

    return _muscle_floors(
        tiers, servable=set(_primary_muscle_by_exercise().values()),
        sessions_per_week=sessions_per_week, cadence_deload=cadence_deload)


def muscle_floor_errors(text: str, payload: "dict | None",
                        cadence_deload: bool = False) -> "list[str]":
    """Blocking per-muscle weekly floor findings, as plain strings."""
    return [msg for _axis, msg in _muscle_floor_findings(
        text, payload, cadence_deload=cadence_deload)]


def _muscle_floor_findings(text: str, payload: "dict | None",
                           cadence_deload: bool = False):
    """`muscle_floor_errors`'s body, yielding ``(axis, message)``.

    Driven by the muscles ``payload["muscle_volume_targets"]`` lists; with
    none, `validate_workout_plan` says the floor did not run. Fails open
    on a document with no workout bullets, and per muscle when the catalog
    has no primary entry for it (such a muscle has no floor).

    The floors are the payload's ``strength_sessions_per_week`` worth
    (`constants.floor_scale`), and ``cadence_deload`` scales them by
    (n - 0.5) / n more, so the halved session does not fail its own week. The
    session count is read from the payload because it comes from the
    profile or the user's request, not from the plan under review: a plan
    that wrote itself fewer sessions would otherwise lower its own bar. A
    payload without the field is a four-session week.
    """
    targets = (payload or {}).get("muscle_volume_targets")
    if not isinstance(targets, dict) or not targets:
        return
    sets = _direct_sets_by_muscle(text)
    if not sets:
        return
    tiers = {m: v.get("tier") if isinstance(v, dict) else None
             for m, v in targets.items()}
    n = (payload or {}).get("strength_sessions_per_week")
    scale = floor_scale(n, cadence_deload)
    if scale == 1:
        why = ""
    else:
        why = (f"; scaled x{float(scale):.3g} for "
               f"{n or FLOOR_REFERENCE_SESSIONS} sessions a week"
               + (" with a cadence deload session" if cadence_deload else ""))
    for muscle, floor in sorted(muscle_floors(
            tiers, n, cadence_deload).items()):
        total = sum(sets.get(muscle, {}).values())
        if total < floor:
            yield (AXIS_VOLUME,
                   f"Week: {total} direct {muscle} sets across the plan — "
                   f"floor is {floor} ({tiers[muscle] or 'maintain'} tier"
                   f"{why}; synergist credit does not count, add direct "
                   f"{muscle} work)")


def arm_week_errors(text: str, spec: "dict | None" = None) -> "list[str]":
    """WEEKLY direct-arm diversity check. Blocking.

    The arm volume floor is two rows of the per-muscle floor
    (`muscle_floor_errors`). What stays is what a set count cannot say,
    ``min_distinct_exercises_per_week``: 6 sets of one pushdown is a
    quantity target met and a training target missed. Sums across the
    whole plan, primary-muscle bullets only; zero-set bullets count
    toward nothing.
    """
    return [msg for _axis, msg in _arm_week_findings(text, spec=spec)]


def _arm_week_findings(text: str, spec: "dict | None" = None):
    """`arm_week_errors`'s body, yielding ``(axis, message)``.

    `AXIS_STRUCTURE`: two curls at one set each is a legal deload; six
    sets of one pushdown is not.
    """
    spec = _resolved_spec(spec, ARM_WEEK_SPEC, "arm_week_spec")
    min_distinct = spec["min_distinct_exercises_per_week"]
    sets = _direct_sets_by_muscle(text)
    for muscle in ("biceps", "triceps"):
        exercises = sets.get(muscle, {})
        total, n_distinct = sum(exercises.values()), len(exercises)
        # Dose-aware, same rule as core: at 2 sets the floor resolves to
        # 1, because splitting 2 sets into two 1-set curls is worse
        # training than one 2-set curl. Silent at zero: the muscle floor
        # already names a total absence, once.
        effective_distinct = _dose_aware_distinct_floor(min_distinct, total)
        if total > 0 and n_distinct < effective_distinct:
            yield (AXIS_STRUCTURE,
                   f"Week: {n_distinct} distinct direct {muscle} exercises "
                   f"across the plan — the arm spec requires "
                   f"{effective_distinct}"
                   + _dose_cap_note(min_distinct, effective_distinct, total,
                                    f"direct {muscle} sets"))


def workout_arm_dose_warnings(text: str, spec: "dict | None" = None
                              ) -> "list[str]":
    """Direct-arm findings: the per-workout placement check plus every
    `arm_week_errors` finding. Returns a list of strings.

    The LAST bullet of a workout must not be a direct-arm exercise (same
    rationale as core's last-bullet rule: the terminal slot is where a
    truncated session drops work). The name is historical: these became
    blocking on 2026-08-02, in `validate_workout_plan`.
    """
    return [msg for _axis, msg in _arm_findings(text, spec=spec)]


def _arm_findings(text: str, spec: "dict | None" = None):
    """`workout_arm_dose_warnings`'s body, yielding ``(axis, message)``.

    Placement is `AXIS_STRUCTURE`: it costs no fatigue to fix, so a
    deload does not excuse it.
    """
    primary = _primary_muscle_by_exercise()
    for title, bullets in _iter_workout_exercise_bullets(text).items():
        if not bullets:
            continue
        muscle = primary.get(bullets[-1]["name"].lower())
        if muscle in ("biceps", "triceps"):
            yield (AXIS_STRUCTURE,
                   f"{title}: {muscle} is the last bullet — arms must sit "
                   f"inside the isolation block, not the terminal slot")

    yield from _arm_week_findings(text, spec=spec)


@lru_cache(maxsize=1)
def _pattern_catalog() -> dict:
    """The block-rotation pattern catalog, built ONCE per process.

    ``blocks.rotation_diff_errors`` accepts ``catalog=None`` and builds
    its own, but it builds it on every call, and building it reparses
    ``exercises-database.md``. `Skills/CLAUDE.md`: *"Optimize by removing
    wasted work first: ... reparsing static markdown inside one
    command."* One render is one parse.
    """
    from .blocks import load_pattern_catalog
    from .extract import load_exercises_db
    from shared.exercises_database import DATABASE_PATH

    return load_pattern_catalog(load_exercises_db(DATABASE_PATH))


def _artifact_from_payload_block(block: "dict | None") -> "dict | None":
    """The block artifact shape, rebuilt from the tracker payload's block.

    ``blocks.block_payload`` flattens ``sessions: {type: [slot, ...]}``
    into a single ``slots`` list carrying ``session_type`` per entry,
    because a flat list is what the coach reads. ``rotation_diff_errors``
    is a pure function over the ARTIFACT shape. This is the adapter
    between the two, and it lives on the consumer side rather than in
    ``blocks`` so the artifact stays the one canonical shape.

    Returns ``None`` when there is no usable previous block — before the
    first plan there is nothing to rotate away from, and a rotation check
    against nothing must be silent rather than inventive.
    """
    if not isinstance(block, dict):
        return None
    sessions = block.get("sessions")
    if isinstance(sessions, dict) and sessions:
        return block                       # already an artifact on disk
    slots = block.get("slots")
    if not isinstance(slots, list) or not slots:
        return None
    rebuilt: "dict[str, list[dict]]" = {}
    for s in slots:
        if not isinstance(s, dict):
            continue
        stype = s.get("session_type")
        exercise = (s.get("exercise") or "").strip()
        if not stype or not exercise:
            continue
        entry = {"exercise": exercise,
                 "tag": s.get("tag") or "rotating",
                 "position": s.get("position") or len(rebuilt.get(stype, [])) + 1}
        for opt in ("pattern", "blocks_held", "history", "dose",
                    "stalled_sessions", "performed_instead"):
            if s.get(opt) is not None:
                entry[opt] = s[opt]
        rebuilt.setdefault(stype, []).append(entry)
    if not rebuilt:
        return None
    return {
        "block_id":  block.get("block_id"),
        "started":   block.get("started"),
        "source":    block.get("source"),
        "sessions":  rebuilt,
    }


# ------------------------------------------------- the stage-two switch
#
# THE ONE SWITCH. Set to ``True`` to make block-rotation findings refuse
# a render again; that is the entire stage-two change on this side.
#
# Rotation is ADVISORY for this release. It is not that the rule is
# wrong — `rotation_diff_errors` is a thoroughly tested pure function and
# on the real 2026-07-18 -> 2026-07-25 transition it finds 14 genuine
# violations. It is that every defect three reviewers found in this
# workstream lived in the surface this check reads: the coach-authored
# plan markdown and the block derived from it. Stage one ships the gates
# whose inputs are the tracker's own data (core dose, weekly core
# distribution, direct-arm dose and diversity); stage two ships this one,
# once its input surface has been through the same hardening.
#
# Demoted, not disabled. `block_rotation_errors` still runs on every
# render, the payload still carries the full ``block`` state, and the
# findings still reach stderr. They are tagged with
# `ROTATION_ADVISORY_TAG` so a reader can tell an unenforced finding from
# a finding that is inherently advisory.
#
# One name, read in exactly one place (`validate_workout_plan`). The
# alternative — an ``if`` at each call site, or deleting the call — is
# what makes re-enabling a piece of archaeology instead of a one-line
# edit, and it is how a check quietly stays off past the release that
# meant to turn it back on.
BLOCK_ROTATION_ENFORCED = False

# Mirrors the ``[advisory: deload week]`` tag used for VOLUME findings
# demoted by a prescribed deload. Same reason: a demoted finding must
# still read as demoted, not vanish and not masquerade as a rule that was
# never checked.
ROTATION_ADVISORY_TAG = "[advisory: rotation, not enforced this release]"


def block_rotation_errors(text: str, prev_block: "dict | None",
                          plan_date: "str | None" = None,
                          catalog: "dict | None" = None) -> "list[str]":
    """W5 rotation findings for this plan against the block it replaces.

    ``prev_block`` is the tracker payload's ``block`` (or a raw artifact).
    The proposed block is derived from the plan markdown itself with
    ``blocks.block_from_plan`` — the plan IS the proposal, and deriving it
    here is what lets a rotation rule bind at render time instead of
    waiting for someone to hand-write an artifact.

    The findings this returns are real findings; whether they BLOCK is
    not decided here. `validate_workout_plan` routes them by
    `BLOCK_ROTATION_ENFORCED`, which is ``False`` this release — see that
    constant. The name is kept for its callers and its history.

    Returns ``[]`` (not a finding) when:

    * there is no previous block — the first plan under this system has
      nothing to differ from;
    * the previous block STARTED on ``plan_date``. That block was derived
      from this very plan, so the diff would compare the plan against
      itself and report every rotating slot as unchanged. A tautology is
      not a finding. This is the re-render case (the plan file is already
      on disk when ``read_tracker`` runs again), not a way past the check:
      a genuinely new plan carries a new date and its previous block does
      not.
    """
    prev = _artifact_from_payload_block(prev_block)
    if prev is None:
        return []
    if plan_date and prev.get("started") == plan_date:
        return []

    from .adherence import parse_plan
    from .blocks import block_from_plan, rotation_diff_errors

    if catalog is None:
        catalog = _pattern_catalog()
    plan = parse_plan(text, plan_date or "")
    if not any(w.get("slots") for w in plan.get("workouts") or []):
        # No parsed prescription at all (a summary doc, the benchmark
        # fixture). `rotation_diff_errors` would answer "no proposed
        # block", which is true of the artifact and false of the plan.
        return []
    proposed = block_from_plan(plan, catalog, start_date=plan_date,
                               prev_block=prev)
    return rotation_diff_errors(prev, proposed, catalog)


# ---------------------------------------------------------------------
# Three advisory plan checks. They find what the coach is told to do and
# nothing enforced: copy `next_dose`, keep the four main patterns in the
# week, write no cardio. The original failures were all drift from a
# written rule (a bench weight that never rose, an overhead press that
# dropped out with a split change), and none of them was ever visible to
# `check_plan`. WARNINGS, not errors: the owner approved advisory output,
# and a coach that has a reason says so in the plan's opener. Each is
# tagged so a reader can tell it from an enforced finding.
NEXT_DOSE_DRIFT_TAG = "[advisory: next_dose drift]"
MAIN_PATTERN_TAG = "[advisory: main pattern]"
CARDIO_SECTION_TAG = "[advisory: cardio section]"

_REP_RANGE_RE = re.compile(r"^\s*(\d+)(?:\s*[-\u2013]\s*(\d+))?\s*$")


def _rep_range_bounds(rep_range) -> "tuple[int, int] | None":
    """``(lo, hi)`` of a ``next_dose`` rep range (``"10-12"`` or ``"12"``)."""
    m = _REP_RANGE_RE.match(rep_range) if isinstance(rep_range, str) else None
    if not m:
        return None
    lo = int(m.group(1))
    return lo, int(m.group(2)) if m.group(2) else lo


def _cadence_deload_index(workouts: "list[dict]") -> "int | None":
    """Index of the session the cadence deload halves (SKILL.md, Deload and
    re-entry): the first lower-body session, else the first session. A
    full-body session trains the lower body, so it counts as one."""
    for w in workouts:
        if w.get("session_type") in ("lower", "full"):
            return w["index"]
    return workouts[0]["index"] if workouts else None


def next_dose_drift_warnings(text: str, payload: "dict | None", *,
                             plan_date: "str | None" = None,
                             deload_week: bool = False,
                             cadence_deload: bool = False) -> "list[str]":
    """One line per exercise whose written dose differs from ``next_dose``.

    The working-set load must equal ``load_kg`` and the working-set rep
    target must sit inside ``rep_range`` (a single number is a range of one).
    Per side and ``10-12`` ranges parse through the ledger's own set
    grammar (`adherence.parse_plan`), the same one the dose was learned
    from. Not compared: warmup sets, an entry without a load
    (``no_history``), and an exercise the plan does not prescribe.

    Exempt, because the dose is not the instruction there:

    * a full-block deload (``deload_week``, or ``next_dose.load_policy``
      ``reduce``): loads are held and sets halved;
    * a `## Deload Session` heading, and on a cadence-deload week the
      session `_cadence_deload_index` names: loads may be ``last_load_kg``;
    * a load equal to the entry's ``other_gym_load_kg``: the plan is
      written for the other gym, which the entry names;
    * a lift the plan prescribes in two workouts with different rep ranges
      (a deliberate heavy and light day): `next_dose` carries one dose per
      lift, so it is silent when any occurrence matches it and reported once
      when none does.
    """
    nd = (payload or {}).get("next_dose") or {}
    entries = {}
    for e in nd.get("exercises") or []:
        if isinstance(e, dict) and e.get("exercise") \
                and e.get("load_kg") is not None:
            entries[e["exercise"].strip().lower()] = e
    if not entries or deload_week or nd.get("load_policy") == "reduce":
        return []

    from .adherence import parse_plan
    from .strength import loads_equal

    workouts = parse_plan(text, plan_date or "").get("workouts") or []
    skip = _cadence_deload_index(workouts) if cadence_deload else None
    live = [w for w in workouts if not w.get("is_deload")
            and w["index"] != skip]

    # Every occurrence of a lift the payload has an entry for. A lift written
    # with two different REP RANGES (a heavy 6-8 and a light 12-15, on
    # purpose; the same key `progression` uses to tell the doses apart) holds
    # two intentional doses and `next_dose` carries one, so comparing only the
    # first occurrence would call the other half a deviation and push the
    # coach to collapse them. It is checked as a whole instead: silent when
    # ANY occurrence matches `next_dose` on load and rep range, one line when
    # none does. A lift with one rep range is compared occurrence by occurrence
    # (a stale load in a second workout is drift).
    occurrences: "dict[str, list[tuple]]" = {}
    for w in live:
        for slot in w["slots"]:
            key = slot["exercise"].strip().lower()
            if key not in entries or not slot["prescribed_sets"] \
                    or (slot["load_kg"] is None and slot["rep_target"] is None):
                continue        # (timed work has no load or rep target)
            occurrences.setdefault(key, []).append((w, slot))

    def _diffs(slot: dict, e: dict) -> "list[str]":
        out = []
        plan_load = slot["load_kg"]
        if plan_load is None or not (
                loads_equal(plan_load, e["load_kg"])
                or loads_equal(plan_load, e.get("other_gym_load_kg"))):
            out.append("load")
        bounds = _rep_range_bounds(e.get("rep_range"))
        if bounds and slot["rep_lo"] is not None and not (
                bounds[0] <= slot["rep_lo"] and slot["rep_hi"] <= bounds[1]):
            out.append("reps")
        return out

    def _dose_s(slot: dict) -> str:
        out = (f"{slot['load_kg']:g}kg" if slot["load_kg"] is not None
               else "no load")
        return out + (f" x {slot['rep_target']}" if slot["rep_target"] else "")

    lines: "dict[str, str]" = {}
    for key, occ in occurrences.items():
        e = entries[key]
        nd_s = f"{e['load_kg']:g}kg"
        if e.get("rep_range"):
            nd_s += f" x {e['rep_range']}"
        if len({(s["rep_lo"], s["rep_hi"]) for _w, s in occ}) > 1:
            if any(not _diffs(s, e) for _w, s in occ):
                continue
            parts = "; ".join(f"Workout {w['index']}: {_dose_s(s)}"
                              for w, s in occ)
            lines[key] = (
                f"{e['exercise']}: written with different rep ranges in "
                f"different workouts ({parts}), and none matches next_dose "
                f"{nd_s} ({e.get('action')}); next_dose carries one dose per "
                f"lift, so match one of them to it and keep the other "
                f"{NEXT_DOSE_DRIFT_TAG}")
            continue
        for w, slot in occ:
            diffs = _diffs(slot, e)
            if diffs:
                lines[key] = (
                    f"{e['exercise']} (Workout {w['index']}: {w['title']}): "
                    f"plan {_dose_s(slot)} vs next_dose {nd_s} "
                    f"({e.get('action')}); differs in {' and '.join(diffs)} "
                    f"{NEXT_DOSE_DRIFT_TAG}")
                break
    return list(lines.values())


def missing_main_pattern_warnings(text: str, *, plan_date: "str | None" = None,
                                  deload_week: bool = False,
                                  catalog: "dict | None" = None) -> "list[str]":
    """One line per `blocks.MAIN_PATTERNS` entry the week's plan lacks.

    SKILL.md: every week holds a horizontal push, a vertical push, a
    horizontal pull and a vertical pull. A pattern counts when any exercise
    with working sets maps to it in the catalog. Silent on a plan with no
    parsed workout (a rest day) and on a full-block deload, where the week
    is a volume cut and the selection is the user's call. Nothing in the
    payload says "travel" or "bodyweight only", so those plans are not
    special-cased: the catalog lists bodyweight movements under the same
    patterns (Push-Up, Pike Push-Up, Table Inverted Row).
    """
    if deload_week:
        return []
    from .adherence import parse_plan
    from .blocks import MAIN_PATTERNS, pattern_group

    workouts = parse_plan(text, plan_date or "").get("workouts") or []
    slots = [s for w in workouts for s in w["slots"] if s["prescribed_sets"]]
    if not slots:
        return []
    if catalog is None:
        catalog = _pattern_catalog()
    present = {pattern_group(s["exercise"], catalog) for s in slots}
    return [f"week has no {pattern} exercise: add one to a session with "
            f"room, sets from its isolation block (rotation_candidates "
            f"offers one) {MAIN_PATTERN_TAG}"
            for pattern in MAIN_PATTERNS if pattern not in present]


# What SKILL.md forbids in the workout markdown: "no cardio sections, no
# Zone 2 or interval prescriptions" and cardio as a "section, bullet or
# instruction". A heading that names cardio, Zone 2 or intervals (`## Cardio
# 1: Zone 2`, `## Session 1: Zone 2 cardio + mobility`), or a bullet that
# prescribes by Zone 2 or heart rate. Cardio in the opener's prose is
# analysis and is not read.
_CARDIO_HEADING_RE = re.compile(
    r"\b(cardio|zone\s*2|z2|hiit|intervals?)\b", re.IGNORECASE)
_CARDIO_PRESCRIPTION_RE = re.compile(
    r"\b(zone\s*2|z2|hiit)\b|\d\s*bpm\b", re.IGNORECASE)


def cardio_section_warnings(text: str) -> "list[str]":
    """One line per cardio heading, and per bullet that prescribes cardio
    outside one (the bullets of a flagged section are not repeated).

    The plan is strength only (SKILL.md, Output files). Cardio data feeds
    the assessment and is never prescribed, even when the person is behind
    the Zone 2 target.
    """
    out: "list[str]" = []
    in_body = in_flagged = False
    for lineno, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.rstrip()
        if re.match(r"^#{2,6}\s", line):
            in_body = True
            in_flagged = bool(_CARDIO_HEADING_RE.search(line))
            if in_flagged:
                out.append(f"line {lineno}: {line.strip()!r} is a cardio "
                           f"section: the plan is strength only, so delete "
                           f"it and state any cardio shortfall on the "
                           f"assessment card {CARDIO_SECTION_TAG}")
        elif in_body and not in_flagged \
                and line.lstrip().startswith(("-", "\u2014")) \
                and _CARDIO_PRESCRIPTION_RE.search(line):
            out.append(f"line {lineno}: {line.strip()!r} prescribes cardio: "
                       f"the plan is strength only {CARDIO_SECTION_TAG}")
    return out


# The plan markdown's own opener, split out so the coach-number
# cross-check can reach it. See `validate_workout_plan`.
_PLAN_OPENER_END_RE = re.compile(r"^##\s", re.MULTILINE)


def _plan_texts(text: str) -> "list[tuple[str, str]]":
    """The plan markdown as labelled strings, for `coach_number_findings`.

    Two entries, because the two halves earn different anchors. The
    OPENER — everything above the first ``##`` heading, which is the title,
    the ``> Today's call`` / ``> Why`` lines and the framing paragraph — is
    a `RECOVERY_SCORE_SURFACES` label: its whole subject is the day's
    call, so a bare ``N/10`` there is a claim about the composite. The
    BODY is exercise bullets, where a bare ``N/10`` is far more likely a
    rep or RIR note, so only the metric-noun anchor applies.
    """
    if not isinstance(text, str) or not text:
        return []
    m = _PLAN_OPENER_END_RE.search(text)
    cut = m.start() if m else len(text)
    return [("plan opener", text[:cut]), ("plan body", text[cut:])]


def tier_budget_by_index(session_recommendation: "dict | None",
                         base_budget) -> "callable | None":
    """``idx -> working-set budget`` for the workout at position ``idx``.

    Session length is set-count driven, and a deload / downgrade
    legitimately trims, so the budget is scaled by the recovery gate's
    tier before anything is compared against it.

    The scale is PER WORKOUT INDEX, not global. A ``reactive_deload`` or
    a Tier A rest scales the whole week, but a Tier C ``downgrade`` trims
    only the first ``expected_rebound_by_session`` workouts — the later
    ones keep the full budget. A single global scale judged those full
    later sessions against the shrunken early-session budget and flagged
    them as "over", which invites a coach to trim a correct session.

    Returns ``None`` when there is no base budget to scale, which is the
    signal to skip the budget check rather than compare against zero.
    """
    if not base_budget:
        return None
    from .constants import SESSION_GATE_THRESHOLDS as T
    sr = session_recommendation or {}
    label = sr.get("label")
    tier = sr.get("tier")
    rebound = sr.get("expected_rebound_by_session") or 1

    def _budget_for(idx: int) -> int:
        # Tier A is a rest call, but the user may choose lighter strength
        # when asked (`substitute-protocols.md`, option 2). A rest-day plan
        # has no workout headings, so this budget is only ever read on
        # that lighter plan. It used to be 0, which the budget check
        # reads as "no budget" and skips, so a lighter Tier A week had
        # no set ceiling at all. Same half-volume as a reactive deload.
        if tier == "A" or label == "reactive_deload":   # whole-week deload
            return round(base_budget * 0.5)
        if label == "downgrade":              # only first `rebound` trim
            return (round(base_budget * T["tier_c_session_budget_scale"])
                    if idx < rebound else base_budget)
        return base_budget

    return _budget_for


def validate_workout_plan(
    text: str,
    *,
    core_spec: "dict | None" = None,
    arm_spec: "dict | None" = None,
    target_working_sets=None,
    budget_by_index=None,
    prev_block: "dict | None" = None,
    plan_date: "str | None" = None,
    deload_week: bool = False,
    cadence_deload: bool = False,
    payload: "dict | None" = None,
) -> "tuple[list[str], list[str]]":
    """Return ``(errors, warnings)`` for a whole workout-plan markdown.

    THE blocking entry point for prescription content, and the reason it
    exists: `workout_core_warnings` and `workout_arm_dose_warnings` were
    printed to stderr and nothing acted on them. An advisory warning
    mid-pipeline is noise — the plan that shipped on 2026-07-18 met every
    numeric target the system checked and was still the plan the user
    rejected. Dose and distribution findings are now errors.

    Errors (render must not proceed):
      * per-session core dose and shape (`workout_core_warnings`)
      * weekly core distribution (`core_week_errors`)
      * direct-arm diversity and placement (`workout_arm_dose_warnings`)
      * the weekly per-muscle direct-set floor (`muscle_floor_errors`),
        for the muscles ``payload["muscle_volume_targets"]`` lists. A
        payload without that key gets a warning instead.
      * a recovery score in the plan's own opener that contradicts the
        payload (`coach_number_findings`), evaluated only when
        ``payload`` is given. The plan opener is the string the user
        reads mid-workout and it shipped unchecked while the dashboard's
        coach text did not: the same page could state one score in the
        opener, another in a card callout and a third in the payload. An
        error here means the two numbers fall on opposite sides of a
        documented decision threshold; a re-derived payload warns.

    Warnings (render proceeds, finding is surfaced):
      * working-set budget drift (`workout_set_budget_warnings`), which
        stays advisory because an intentional deload legitimately
        undershoots it. Only evaluated when ``target_working_sets`` is
        given.
      * three advisory checks of rules the coach is told to follow:
        a written dose that differs from ``payload["next_dose"]``
        (`next_dose_drift_warnings`), a week without one of the four main
        patterns (`missing_main_pattern_warnings`), and a cardio section
        (`cardio_section_warnings`). Never errors; tagged `NEXT_DOSE_DRIFT_TAG`
        etc.
      * every `AXIS_VOLUME` finding above, when ``deload_week`` (a
        FULL-BLOCK deload only; see below for the cadence deload).
      * block rotation against the previous block
        (`block_rotation_errors`), evaluated only when ``prev_block``
        carries one — see that function for the two silent cases.
        Advisory THIS RELEASE ONLY, and routed by the single named
        constant `BLOCK_ROTATION_ENFORCED`; flip that to ``True`` and
        these become errors again with no other edit. Tagged with
        `ROTATION_ADVISORY_TAG` on the way out.

    ``deload_week`` demotes the VOLUME axis and nothing else. Without it
    the new specs punished a legitimate deload for being one. Measured on
    the real 2026-07-13 plan — a correct, deliberate half-volume week —
    on both trackers, strict and then relaxed, without a payload (so no
    per-muscle floor; with one, each muscle under its floor demotes too):

        6 blocking errors  ->  3 errors + 3 advisory

    The ones that demote are the ones that say the week contains less
    work (an under-allocated session, no loaded flexion movement, too few
    flexion sets, and a muscle under its weekly floor), which is what a
    deload IS. With the relief the diversity and identity axes still bite,
    because they cost no fatigue: a deload is not a licence to go back to
    four sets of the same crunch.

    **The relief does not make that plan renderable, and it is not meant
    to.** The three errors that survive are core-placement findings —
    core is the last bullet in all three sessions, §24 — so the reference
    deload still exits 2. Placement costs nothing to fix and a deload is
    the last week to relax it; the relief is about volume, not about
    getting a known-bad plan through. See `AXIS_VOLUME` for the full
    split and `is_deload_week` for what may set this.

    **This is not the Tier C case.** A recovery downgrade keeps every
    volume floor blocking; the isolation cut comes out of the rest of the
    accessory block, not out of core and direct arms. `is_deload_week`
    returns False for ``downgrade`` on purpose.

    THE TWO KINDS OF DELOAD ARE DIFFERENT SIZES, and only the big one
    switches the floors off. ``deload_week`` is the FULL-BLOCK deload
    (`is_deload_week`: the gate's Tier A, a `DELOAD_WEEK_LABELS` label or a
    load policy of ``reduce``), where every session is halved, so the volume
    findings are advisory. ``cadence_deload`` is the block's cadence deload
    (`is_cadence_deload_week`, ``block.deload_prescribed``), which halves ONE
    session of an otherwise normal week. Demoting every floor for the whole
    week on that signal made a week of 3 normal sessions and 1 halved one
    exempt from all of its volume. So on a cadence week the volume findings
    STAY BLOCKING, and the one that counts sets per muscle (the weekly
    floor) is scaled by (n - 0.5) / n for the n sessions of the week
    (`constants.floor_scale`), rounded down. Core is not scaled: it is
    exempt from the halving (SKILL.md, Deload and re-entry: the deload
    session keeps its full per-session core dose), so the per-session core
    dose, the loaded-flexion movement and the flexion set floor keep their
    spec numbers. ``block.deload_source`` names which clock called the
    cadence deload. The two clocks stay separate: ``deload_prescribed`` is
    "cut the volume", ``boundary_due`` is "rotate the selection" — see
    `blocks.deload_cadence` for why all four combinations occur.

    Copy rules (em-dashes, off-catalog exercise names) are NOT re-checked
    here; `validate_workout_md` owns those and callers run it first.
    """
    errors: "list[str]" = []
    warnings: "list[str]" = []

    def _route(findings) -> None:
        for axis, msg in findings:
            if deload_week and axis == AXIS_VOLUME:
                # Tagged, not silently dropped. A reader has to be able
                # to tell a demoted finding from an inherently advisory
                # one, and to see what the deload is costing.
                warnings.append(f"{msg} [advisory: deload week]")
            else:
                errors.append(msg)

    _route(_core_session_findings(text, spec=core_spec))
    _route(_core_week_findings(text, spec=core_spec))
    _route(_arm_findings(text, spec=arm_spec))
    _route(_muscle_floor_findings(text, payload,
                                  cadence_deload=cadence_deload))
    if payload is not None and not payload.get("muscle_volume_targets"):
        warnings.append("payload has no muscle_volume_targets: the "
                        "per-muscle weekly floor was not checked")

    # The numbers the plan itself states, against the payload it was
    # written from. Same function, same severities and the same
    # decision-equivalence rule the dashboard's coach text gets.
    if payload is not None:
        num_errors, num_warnings = coach_number_findings(payload,
                                                         _plan_texts(text))
        errors += num_errors
        warnings += num_warnings

    # The ONLY read of `BLOCK_ROTATION_ENFORCED`. Keep it that way: the
    # switch is worth having only while it is a single branch.
    rotation = block_rotation_errors(text, prev_block, plan_date=plan_date)
    if BLOCK_ROTATION_ENFORCED:
        errors += rotation
    else:
        warnings += [f"{m} {ROTATION_ADVISORY_TAG}" for m in rotation]

    if target_working_sets:
        warnings += workout_set_budget_warnings(
            text, target_working_sets, budget_by_index=budget_by_index)

    warnings += next_dose_drift_warnings(
        text, payload, plan_date=plan_date, deload_week=deload_week,
        cadence_deload=cadence_deload)
    # Evaluated only with a payload, like the cross-checks above: a bare
    # plan fragment (the core-spec fixtures) is not a week.
    if payload is not None:
        warnings += missing_main_pattern_warnings(
            text, plan_date=plan_date, deload_week=deload_week)
    warnings += cardio_section_warnings(text)

    return errors, warnings


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
