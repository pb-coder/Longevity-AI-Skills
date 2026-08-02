"""Nutrition-phase analytics for the coach.

Consumes the nutrition_phases CSV (``<person>/data/nutrition_phases.csv``)
plus the bodyweight series from ``health_metrics.csv`` and returns a
structured ``nutrition_phase`` block that the renderer and the LLM
coach both consume. Returns ``None`` when there is no open phase —
``_compact`` then drops the key from the JSON output and the
nutrition_phase card stays hidden.

The summary answers, per the bulking-science reference:

  * Is the current phase on-track vs its target rate?
  * Have any pre-committed stop conditions triggered?
  * What is the coach's action hint
    (``continue`` / ``slow_intake`` / ``add_calories`` /
    ``consider_ending`` / ``end_now``)?

Output is structured so the renderer can build the card without any
re-derivation, AND so the LLM coach can author a ≤280-char callout
keyed on a single ``coach_action_hint`` value.

Public surface:

- ``nutrition_phase_summary(phases, bodyweight_series, today_d)`` —
  full block, or None when no open phase.
- ``recent_phase_rate_kg_per_wk(bodyweight_series, start_d, today_d,
  window_days)`` — observed rate over the trailing window.
"""
from __future__ import annotations

from datetime import date, timedelta


from .parsing import _parse_iso_date
from .sessions import smoothed_rate_per_week


# Default rate-band classifiers (kg/wk). Anchored on the lean-bulk
# evidence base (Helms / Aragon / Schoenfeld): ~0.25-0.5% bodyweight/wk
# for trained lifters. We use absolute thresholds because the user's
# bodyweight is already in the input and rate-as-percent doesn't add
# much signal for the coach's purpose.
_BULK_TARGET_DEFAULT_KG_PER_WK = 0.25
_BULK_TOO_FAST_KG_PER_WK = 0.5    # >+0.5 kg/wk is excess fat partitioning territory
_CUT_TARGET_DEFAULT_KG_PER_WK = -0.5
_CUT_TOO_FAST_KG_PER_WK = -1.0    # <-1 kg/wk risks lean tissue loss
_MAINTAIN_BAND_KG_PER_WK = 0.15   # +/- 0.15 kg/wk is "flat enough"


def _current_open_phase(phases: list[dict]) -> dict | None:
    """Return the most recent phase with no end_date (the open one).

    Phases come in DESC-by-start_date order from the reader; the open
    phase is the first one with ``end_date is None``. Multiple open
    phases would be a data error — pick the most recent.
    """
    if not phases:
        return None
    for p in phases:
        if not p.get("end_date"):
            return p
    return None


def recent_phase_rate_kg_per_wk(bodyweight_series: list[dict],
                                start_d: date,
                                today_d: date,
                                window_days: int = 14) -> float | None:
    """Slope of bodyweight (kg) over the trailing ``window_days``.

    Falls back to phase-elapsed-days when the phase is shorter than the
    window. Delegates the arithmetic to
    ``sessions.smoothed_rate_per_week``: mean-of-3 smoothed endpoints
    divided by the span between the two groups' MEAN dates.

    This used to be a second copy of that arithmetic, and the copy divided
    the centroid-to-centroid change by the OUTER first-to-last span. That
    is the classic smoothing bug — it shrinks every rate toward zero by
    however much series the smoothing consumed, up to 42% on this
    tracker's own data. Because this number drives ``coach_action_hint``
    and the pre-committed stop conditions ("loss faster than 0.5 kg/wk for
    2 weeks"), a shrunk rate makes those stop conditions fire late, which
    is the direction you least want to be wrong in. One helper, one
    definition of "rate".

    Returns None when fewer than 4 bodyweight readings exist in the
    window, or when the time span is too short (< 7 days).
    """
    if not bodyweight_series:
        return None

    effective_window = min(window_days, (today_d - start_d).days)
    if effective_window < 7:
        return None

    cutoff = today_d - timedelta(days=effective_window)
    in_window = []
    for entry in bodyweight_series:
        d = _parse_iso_date(entry.get("date"))
        if d is None:
            continue
        kg = entry.get("kg")
        if kg is None:
            continue
        if d < cutoff or d > today_d:
            continue
        in_window.append((d, float(kg)))

    if len(in_window) < 4:
        return None

    in_window.sort()
    if (in_window[-1][0] - in_window[0][0]).days < 7:
        return None

    rate = smoothed_rate_per_week(in_window)
    return None if rate is None else round(rate, 3)


def _consecutive_rate_breaches(bodyweight_series: list[dict],
                               start_d: date,
                               today_d: date,
                               *,
                               threshold: float,
                               direction: str,
                               windows: int = 3) -> int:
    """Count trailing weekly windows breaching a gain/loss threshold."""
    count = 0
    for offset in range(windows):
        end = today_d - timedelta(days=offset * 7)
        begin = max(start_d, end - timedelta(days=6))
        points = []
        for entry in bodyweight_series:
            d = _parse_iso_date(entry.get("date"))
            kg = entry.get("kg")
            if d is None or kg is None or d < begin or d > end:
                continue
            points.append((d, float(kg)))
        if len(points) < 2:
            break
        points.sort()
        span = (points[-1][0] - points[0][0]).days
        if span < 3:
            break
        rate = (points[-1][1] - points[0][1]) / span * 7.0
        breached = rate >= threshold if direction == "above" else rate <= threshold
        if not breached:
            break
        count += 1
    return count


def _phase_target_rate(phase: dict) -> float | None:
    """Resolve the target rate for a phase, falling back to type defaults."""
    explicit = phase.get("target_rate_kg_per_wk")
    if explicit is not None:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            pass
    pt = phase.get("phase_type")
    if pt == "bulk":
        return _BULK_TARGET_DEFAULT_KG_PER_WK
    if pt == "cut":
        return _CUT_TARGET_DEFAULT_KG_PER_WK
    if pt == "maintain":
        return 0.0
    return None


def _classify_status(phase_type: str | None,
                     observed: float | None,
                     target: float | None) -> str:
    """Classify the observed rate against the target band.

    Returns ``insufficient_data`` when observed is None (not enough
    bodyweight readings yet). Otherwise one of: ``on_track`` /
    ``too_fast`` / ``too_slow`` / ``flat`` / ``regressing``.

    The thresholds intentionally match the bulking-science off-ramp
    rules so the renderer's status pill colour matches the coach's
    action hint.
    """
    if observed is None:
        return "insufficient_data"
    if phase_type == "bulk":
        if observed >= _BULK_TOO_FAST_KG_PER_WK:
            return "too_fast"
        if target is not None and observed >= target * 0.6:
            return "on_track"
        if -_MAINTAIN_BAND_KG_PER_WK <= observed <= _MAINTAIN_BAND_KG_PER_WK:
            return "flat"
        if observed < -_MAINTAIN_BAND_KG_PER_WK:
            return "regressing"
        return "too_slow"
    if phase_type == "cut":
        if observed <= _CUT_TOO_FAST_KG_PER_WK:
            return "too_fast"
        if target is not None and observed <= target * 0.6:
            return "on_track"
        if -_MAINTAIN_BAND_KG_PER_WK <= observed <= _MAINTAIN_BAND_KG_PER_WK:
            return "flat"
        if observed > _MAINTAIN_BAND_KG_PER_WK:
            return "regressing"
        return "too_slow"
    if phase_type == "maintain":
        if abs(observed) <= _MAINTAIN_BAND_KG_PER_WK:
            return "on_track"
        return "too_fast" if observed > 0 else "regressing"
    # recomp / unknown: just report flat vs not.
    if abs(observed) <= _MAINTAIN_BAND_KG_PER_WK:
        return "flat"
    return "regressing"


def _detect_stop_signals(phase_type: str | None,
                         status: str,
                         weeks_in_phase: float,
                         observed: float | None,
                         estimated_1rm: dict | None,
                         consecutive_rate_breaches: int = 0) -> list[str]:
    """Compose the list of pre-committed stop-condition triggers that
    currently match. The conditions mirror the bulking-science doc so a
    triggered signal can be quoted verbatim in the coach callout.
    """
    triggered: list[str] = []
    if phase_type == "bulk":
        if status == "too_fast" and consecutive_rate_breaches >= 3:
            triggered.append(
                f"observed rate {observed:+.2f} kg/wk exceeds the 0.5 kg/wk "
                "fat-partitioning threshold for 3 consecutive weekly windows "
                "(cite bulking-science.md)"
            )
        # Lifts stalled 2+ weeks: count exercises with stalled_sessions >= 2.
        if estimated_1rm:
            stalled_two_plus = sum(
                1 for v in estimated_1rm.values()
                if isinstance(v, dict) and (v.get("stalled_sessions") or 0) >= 2
            )
            if stalled_two_plus >= 3 and weeks_in_phase >= 3:
                triggered.append(
                    f"{stalled_two_plus} compound lifts stalled 2+ sessions while "
                    f"in week {weeks_in_phase:.0f} of bulk — surplus may no longer "
                    "be driving hypertrophy"
                )
    elif phase_type == "cut":
        if status == "too_fast" and consecutive_rate_breaches >= 2:
            triggered.append(
                f"observed rate {observed:+.2f} kg/wk exceeds the -1 kg/wk "
                "lean-tissue-loss threshold for consecutive weekly windows "
                "(cite bulking-science.md)"
            )
    return triggered


def _coach_action_hint(status: str, triggered: list[str], weeks_in_phase: float,
                       phase_type: str | None = None) -> str:
    """Map status + stop-signals into a single binding action token.

    The LLM coach is expected to honor this token in its callout the
    same way it honors the 5-tier session_recommendation gate. Tokens:

      - ``continue``         — phase is on-track, hold course
      - ``add_calories``     — observed rate below target, surplus too small
      - ``slow_intake``      — observed rate above target, dial back surplus
      - ``consider_ending``  — at least one stop signal triggered, but not yet
                                terminal (e.g. one bad week)
      - ``end_now``          — multiple stop signals OR a single hard one
                                with phase length over 8 weeks
    """
    if not triggered:
        if status == "too_slow":
            return "add_calories"
        if status == "too_fast":
            return "slow_intake"
        if status == "regressing":
            # Regressing means losing on a bulk or gaining on a cut — the
            # opposite of the intended direction. This is the same class of
            # fall-through bug as insufficient_data: a missing explicit case
            # that silently became "continue". Handle it explicitly here.
            if phase_type == "bulk":
                return "add_calories"
            if phase_type == "cut":
                return "slow_intake"
        # on_track, flat, insufficient_data, or any other non-terminal
        # status with zero stop signals: hold course. A brand-new phase
        # has insufficient bodyweight history and MUST read as "continue",
        # never "consider_ending" (telling someone to quit a phase they
        # just started). "consider_ending" is reserved for an actual
        # stop-signal breach below.
        return "continue"
    if len(triggered) >= 2 or weeks_in_phase >= 8:
        return "end_now"
    return "consider_ending"


def nutrition_phase_summary(phases: list[dict],
                            bodyweight_series: list[dict],
                            today_d: date,
                            estimated_1rm: dict | None = None) -> dict | None:
    """Aggregated nutrition-phase block. Returns None when no open phase.

    Output shape (compact, LLM-friendly):
      current:
        start_date, end_date (always None when open), phase_type,
        days_elapsed, weeks_in_phase
      targets:
        rate_kg_per_wk, kcal_delta, protein_g_per_kg,
        stop_conditions (passthrough text)
      actuals:
        rate_kg_per_wk_14d, rate_vs_target_ratio (or None when no target)
      status: on_track / too_fast / too_slow / flat / regressing /
              insufficient_data
      stop_signals_triggered: list of strings (always present, [] when none)
      coach_action_hint: continue / add_calories / slow_intake /
                        consider_ending / end_now
      history: prior phases as [{start_date, end_date, phase_type,
        duration_days, target_rate_kg_per_wk, notes}], DESC by start.
        Provides "have I done this before?" signal. [] when none.
    """
    open_phase = _current_open_phase(phases)
    if open_phase is None:
        return None

    start_d = _parse_iso_date(open_phase.get("start_date"))
    if start_d is None:
        return None

    days_elapsed = max(0, (today_d - start_d).days)
    weeks = round(days_elapsed / 7.0, 1)

    target_rate = _phase_target_rate(open_phase)
    observed = recent_phase_rate_kg_per_wk(
        bodyweight_series, start_d, today_d, window_days=14
    )

    ratio = None
    if observed is not None and target_rate not in (None, 0):
        ratio = round(observed / target_rate, 2)

    status = _classify_status(open_phase.get("phase_type"), observed, target_rate)
    phase_type = open_phase.get("phase_type")
    if phase_type == "bulk":
        consecutive_rate_breaches = _consecutive_rate_breaches(
            bodyweight_series, start_d, today_d,
            threshold=_BULK_TOO_FAST_KG_PER_WK,
            direction="above",
        )
    elif phase_type == "cut":
        consecutive_rate_breaches = _consecutive_rate_breaches(
            bodyweight_series, start_d, today_d,
            threshold=_CUT_TOO_FAST_KG_PER_WK,
            direction="below",
        )
    else:
        consecutive_rate_breaches = 0
    triggered = _detect_stop_signals(
        phase_type, status, weeks, observed, estimated_1rm,
        consecutive_rate_breaches=consecutive_rate_breaches,
    )
    hint = _coach_action_hint(status, triggered, weeks, phase_type=phase_type)

    # Prior phases (everything not currently open). Useful for the
    # coach to say "this is your second bulk" or compare current rate
    # to prior bulk's outcome.
    history = []
    for p in phases:
        if p is open_phase:
            continue
        p_start = _parse_iso_date(p.get("start_date"))
        p_end = _parse_iso_date(p.get("end_date")) if p.get("end_date") else None
        duration = None
        if p_start and p_end:
            duration = (p_end - p_start).days
        history.append({
            "start_date":            p.get("start_date"),
            "end_date":              p.get("end_date"),
            "phase_type":            p.get("phase_type"),
            "duration_days":         duration,
            "target_rate_kg_per_wk": p.get("target_rate_kg_per_wk"),
            "notes":                 p.get("notes"),
        })

    return {
        "current": {
            "start_date":     open_phase.get("start_date"),
            "end_date":       None,
            "phase_type":     open_phase.get("phase_type"),
            "days_elapsed":   days_elapsed,
            "weeks_in_phase": weeks,
        },
        "targets": {
            "rate_kg_per_wk":      target_rate,
            "kcal_delta":          open_phase.get("target_kcal_delta"),
            "protein_g_per_kg":    open_phase.get("target_protein_g_per_kg"),
            "stop_conditions":     open_phase.get("stop_conditions"),
            "protein_tracking_status": (
                "target_only" if open_phase.get("target_protein_g_per_kg") is not None else None
            ),
            "protein_caveat": (
                "Protein is a configured target only; no intake log is stored here, so do not claim adherence."
                if open_phase.get("target_protein_g_per_kg") is not None else None
            ),
        },
        "actuals": {
            "rate_kg_per_wk_14d":   observed,
            "rate_vs_target_ratio": ratio,
            "consecutive_rate_breach_weeks": consecutive_rate_breaches,
        },
        "status":                  status,
        "stop_signals_triggered":  triggered,  # always a list (possibly empty)
        "coach_action_hint":       hint,
        "history":                 history,
    }
