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
- ``auto_wrap_terms(text)`` — wraps each ``KNOWN_TERMS`` key in a
  tooltip span. First-occurrence-only per string by design (avoids
  visual noise on lines that repeat a term).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Sibling lib/ on sys.path so this module is importable on its own.
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from render_helpers import esc


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
}

EM_DASH = "—"
COACH_STRING_MAX = 280


# Card keys the renderer knows how to surface a coach callout for.
# Listed here so the validator can warn when one is missing; the
# corresponding card still renders (just without a callout) which is
# a softer failure than a hard validator error.
COACH_CARD_KEYS = (
    "recovery_drivers", "activity_rings", "training_load", "muscle_volume",
    "strength", "vitals", "sleep", "recovery_practices",
)


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
        if not cards.get(key):
            warnings.append(f"cards.{key} missing or empty; that card will render without a coach callout")

    return (errors, warnings)


# Wrap KNOWN_TERMS with a tooltip span when they appear in any coach
# string. Whole-word, case-sensitive (so "Cold" doesn't match "CTL").
# Each term wraps at most once per string so we don't double-wrap when
# the user repeats a term.
_TERM_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, KNOWN_TERMS.keys()), key=len, reverse=True)) + r")\b"
)


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

    return _TERM_PATTERN.sub(_sub, esc(text))
