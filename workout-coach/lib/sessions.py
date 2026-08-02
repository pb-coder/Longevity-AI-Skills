"""Session-level aggregation, working-set classification, bodyweight trend.

Inputs are the flat ``rows`` list from ``extract.extract_rows`` (one
entry per logged set) plus the Apple workout sessions and TOTAL-row
summaries. Outputs are session-keyed dicts that the strength + cardio
analytics layer consumes.

Functions:

- ``progression_summary(rows)`` — last vs prior heaviest working set per
  exercise.
- ``_is_flagged_nonfasted(entry)`` — bodyweight-row note filter; pulls
  out non-morning/non-fasted entries so the trend slope isn't distorted.
- ``smoothed_rate_per_week(points, smooth_n)`` — weekly rate of change
  between mean-of-N smoothed endpoints, over their centroid span.
- ``ols_rate_per_week(points)`` — least-squares weekly rate with its
  standard error and 95% confidence interval.
- ``_trend_verdict(points, anchor, start_d, ...)`` — the shared window /
  sample-size / SPAN / recency / interval gate every measurement trend
  below runs through. Window length and reading span are separate
  requirements: readings can sit inside a long window and span three
  days, and only the span belongs in the SE arithmetic.
- ``bodyweight_trend(entries, today_d, start_date)`` — OLS weekly slope
  over a minimum-28-day TIME window, with an explicit
  ``resolved`` / ``unresolved`` state.
- ``bodyweight_trend_kg_per_week(entries)`` — the scalar from that
  block: the rate when it resolves, ``None`` when it does not.
- ``waist_trend(readings, today_d)`` — the same gate over waist
  circumference, reported in cm per 4 weeks over a minimum-56-day
  window.
- ``build_monthly_sessions(rows, summaries, totals, apple_sessions)`` —
  one entry per session-date with the kind (strength / cardio / other),
  TOTAL-row metadata, volume, and Apple-observed max HR folded in.
- ``_is_working_set(r)`` — shared filter used by every working-volume
  calculation downstream.
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta


from .parsing import _parse_iso_date


# Single source of truth for warmup detection on a Notes cell.
#
# ``_WARMUP_MARKER_RE`` matches the structured ``(warmup)`` token the plan /
# log writer emits — the authoritative tag.
#
# ``_WARMUP_WORD_RE`` matches word-bounded free-text variants ("warm-up",
# "warm up", "warmup"). Word boundaries are the fix for the prior bare-
# substring rule, which both let "warm-up"/"warm up" slip through (the space
# / hyphen broke the literal "warmup" match) and could false-exclude.
#
# ``_WARMUP_NEGATED_RE`` guards the one phrase the bug calls out explicitly:
# a real working set annotated "no warmup needed" must NOT be excluded just
# because the token appears. A "no"/"without"/"skip" qualifier immediately
# before the token negates it.
_WARMUP_MARKER_RE = re.compile(r"\(\s*warm[\s-]?up\s*\)", re.IGNORECASE)
_WARMUP_WORD_RE = re.compile(r"\bwarm[\s-]?up\b", re.IGNORECASE)
_WARMUP_NEGATED_RE = re.compile(
    r"\b(?:no|without|skip(?:ped|ping)?|don'?t|not?)\s+warm[\s-]?up\b",
    re.IGNORECASE,
)


def _notes_has_warmup(notes) -> bool:
    """True when a Notes cell flags the row as a warmup ramp set.

    Detects the structured ``(warmup)`` marker and word-bounded text
    variants ("warm-up", "warm up", "warmup"), case-insensitive. A negated
    mention ("no warmup needed") is NOT a warmup tag and returns False —
    that's a real working set whose note merely references warmup.
    """
    if not notes:
        return False
    s = str(notes)
    if _WARMUP_MARKER_RE.search(s):
        return True
    if _WARMUP_NEGATED_RE.search(s):
        return False
    return bool(_WARMUP_WORD_RE.search(s))


def _is_cardio_row(r: dict) -> bool:
    """A row is cardio if it has positive *unloaded* distance, OR a
    duration paired with cardio context (avg HR or auto-import source).

    A loaded carry (Farmer Walk: kg>0 + distance) is strength work, not
    cardio — the distance→cardio gate only fires when kg is zero. A manual
    isometric hold (Dead Hang 0:30, Plank 1:00) has duration but no HR and
    no auto-import source — that's a strength-session "other" row too.
    """
    if (r.get("distance_km") or 0) > 0 and (r.get("kg") or 0) <= 0:
        return True
    if (r.get("duration_min") or 0) <= 0:
        return False
    if (r.get("avg_hr") or 0) > 0:
        return True
    src = (r.get("source") or "").strip().lower()
    if src == "apple" or src.startswith("apple@") or src.startswith("gymkit:"):
        return True
    return False


def progression_summary(rows: list[dict]) -> list[dict]:
    """Last and previous best working set per exercise (warmups excluded)."""
    by_ex: dict[str, list[dict]] = {}
    for r in rows:
        if _notes_has_warmup(r.get("notes")):
            continue
        if not r.get("kg") or not r.get("reps"):
            continue
        by_ex.setdefault(r["exercise"].lower(), []).append(r)

    summary = []
    for canon_lower, sets in by_ex.items():
        # Group by date, pick heaviest (kg, then reps) per session.
        by_date: dict[str, dict] = {}
        for s in sets:
            cur = by_date.get(s["date"])
            if cur is None or (s["kg"], s["reps"]) > (cur["kg"], cur["reps"]):
                by_date[s["date"]] = s
        dates_desc = sorted(by_date.keys(), reverse=True)
        if len(dates_desc) < 1:
            continue
        last = by_date[dates_desc[0]]
        prev = by_date[dates_desc[1]] if len(dates_desc) >= 2 else None
        last_notes = last.get("notes")
        summary.append({
            "exercise": last["exercise"],
            "sessions_logged": len(dates_desc),
            "last": f"{dates_desc[0]} → {last['kg']:g}kg x {last['reps']}",
            "prev": f"{dates_desc[1]} → {prev['kg']:g}kg x {prev['reps']}" if prev else None,
            "last_notes": last_notes if last_notes else None,
        })

    summary.sort(key=lambda s: s["exercise"].lower())
    return summary


def _is_flagged_nonfasted(entry: dict) -> bool:
    notes = (entry.get("notes") or "").lower()
    return any(k in notes for k in ("not fasted", "evening", "after", "post-meal"))


def smoothed_rate_per_week(points: list[tuple[date, float]],
                           smooth_n: int = 3) -> float | None:
    """Weekly rate of change from mean-of-N smoothed endpoints.

    ``points`` is ``[(date, value), ...]``; it is sorted internally. The
    head mean is the first ``n`` values, the tail mean the last ``n``, and
    the denominator is the span between the two groups' MEAN DATES — not
    between the outermost dates. Dividing a centroid-to-centroid change by
    the full first-to-last span is the classic smoothing bug: it shrinks
    every rate toward zero by the amount of series the smoothing consumed.

    ``n`` is clamped to ``len(points) // 2`` so the head and tail groups
    never overlap.

    Raw endpoints are the wrong tool for a noisy daily series. A single
    high or low reading at either end of the window swings the answer by
    more than the real weekly signal. Clamping ``n`` all the way down to 1
    — which is what a 3-point series used to do — silently hands back
    exactly those raw endpoints under a name that promises smoothing, so
    the caller has no way to tell a smoothed rate from an unsmoothed one.
    We refuse instead: the clamp floors at 2, and a series too short to
    form two disjoint pairs returns None.

    Returns None when the clamped ``n`` would fall below 2 (fewer than 4
    points) or the centroid span is under a day.
    """
    pts = sorted(points, key=lambda p: p[0])
    n = min(smooth_n, len(pts) // 2)
    if n < 2:
        return None
    head, tail = pts[:n], pts[-n:]
    head_mean = sum(v for _, v in head) / n
    tail_mean = sum(v for _, v in tail) / n
    base = pts[0][0]
    head_day = sum((d - base).days for d, _ in head) / n
    tail_day = sum((d - base).days for d, _ in tail) / n
    span_days = tail_day - head_day
    if span_days < 1:
        return None
    return (tail_mean - head_mean) / span_days * 7.0


# Two-tailed 95% Student-t critical values by degrees of freedom. A
# bodyweight slope is fitted on a handful of noisy morning weigh-ins, so the
# normal quantile (1.96) understates the interval badly at the sample sizes
# that actually occur: at df=13 the correct multiplier is 2.160, which is 10%
# wider. Past df=30 the two agree to under 3% and the table falls back.
_T_CRIT_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
    14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
    20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}
_Z_CRIT_95 = 1.96


def _t_crit_95(dof: int) -> float:
    """Two-tailed 95% critical value for ``dof`` degrees of freedom."""
    if dof < 1:
        return float("inf")
    return _T_CRIT_95.get(dof, _Z_CRIT_95)


def ols_rate_per_week(points: list[tuple[date, float]],
                      noise_sd_floor: float | None = None) -> dict | None:
    """Least-squares weekly rate of change, with its uncertainty.

    ``points`` is ``[(date, value), ...]``; it is sorted internally. Returns
    ``None`` when there are fewer than 3 points or every reading falls on the
    same day (no x-variance to regress against). Otherwise returns::

        {"per_week", "se_per_week", "ci95_low", "ci95_high",
         "n", "dof", "span_days", "residual_sd", "noise_floored"}

    Every point in the window contributes, which is the difference that
    matters against endpoint or mean-of-N smoothing: one aberrant weigh-in
    moves an OLS slope by ``O(1/n)`` instead of by ``O(1/3)``.

    The interval is the classic ``b ± t(0.975, n-2) · SE(b)``. It is the
    load-bearing output, not decoration — a weekly bodyweight rate whose
    interval spans zero has no resolved sign, and reporting the point
    estimate as though it did is exactly the failure this replaces.

    ``noise_sd_floor`` is a LOWER BOUND on the residual SD, in the unit of
    ``points``. It exists because the fitted residual SD is not a
    measurement of the instrument — it is a ``chi²(n-2)`` estimate from
    the same handful of points that produced the slope, and at the sample
    sizes this gate admits (``dof`` as low as 2) it can land anywhere,
    including exactly zero. Four tape readings that happen to sit on a
    straight line yield ``residual_sd = 0``, hence ``SE = 0``, hence a
    zero-width 95% interval that "excludes zero" and reads as certainty.
    That is not certainty; it is a sample too small to see its own noise.
    No series can be quieter than the device that produced it, so the
    caller supplies the device's documented test-retest SD and the fit
    refuses to claim less noise than that. When the floor binds,
    ``noise_floored`` is ``True`` and ``residual_sd`` reports the floor.
    Default ``None`` leaves the classic estimator untouched.
    """
    pts = sorted(points, key=lambda p: p[0])
    n = len(pts)
    if n < 3:
        return None
    base = pts[0][0]
    xs = [float((d - base).days) for d, _ in pts]
    ys = [float(v) for _, v in pts]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    slope_per_day = sxy / sxx
    intercept = my - slope_per_day * mx
    dof = n - 2
    resid_ss = sum(
        (ys[i] - (intercept + slope_per_day * xs[i])) ** 2 for i in range(n)
    )
    resid_var = resid_ss / dof
    noise_floored = False
    if noise_sd_floor is not None and resid_var < noise_sd_floor ** 2:
        resid_var = float(noise_sd_floor) ** 2
        noise_floored = True
    se_per_day = math.sqrt(resid_var / sxx)
    per_week = slope_per_day * 7.0
    se_per_week = se_per_day * 7.0
    half = _t_crit_95(dof) * se_per_week
    return {
        "per_week":      per_week,
        "se_per_week":   se_per_week,
        "ci95_low":      per_week - half,
        "ci95_high":     per_week + half,
        "n":             n,
        "dof":           dof,
        "span_days":     int((pts[-1][0] - pts[0][0]).days),
        "residual_sd":   math.sqrt(resid_var),
        "noise_floored": noise_floored,
    }


# A weekly bodyweight rate is only resolvable over a long enough baseline.
# With the residual SD this tracker actually shows (~1.2 kg on morning
# weigh-ins) the standard error of a weekly slope runs ~0.55 kg/wk over 14
# days, ~0.30 over 21, ~0.20 over 28 and ~0.14 over 35. A 0.25 kg/wk target
# is therefore not detectable below roughly four weeks, so 28 days is the
# floor — and it is a floor in DAYS, not in readings. The estimator this
# replaces took "the last 8 clean readings", which spanned 16 days at one
# anchor and 9 days at another six weeks later: the same field silently
# changed what period it described.
BODYWEIGHT_TREND_MIN_WINDOW_DAYS = 28
# Below 3 readings there is no slope at all. At exactly 3 there is one degree
# of freedom, where the 95% t-multiplier is 12.7 and the interval is so wide
# it can only ever say "unresolved" — so 4 is the floor, and the reason
# reported is the honest one (too few readings) rather than a CI verdict
# dressed up as a measurement.
BODYWEIGHT_TREND_MIN_READINGS = 4
# The window floor above is a floor on the WINDOW. The SE arithmetic it was
# derived from is about T, the spread of the readings themselves, and those
# are not the same quantity: four weigh-ins taken on four consecutive days
# sit inside a 28-day window and span three days. The reported rate is then
# pure ``1/T`` extrapolation — the same 0.3 kg of drift reads as one rate
# over 3 days and a tenth of it over 28 — so the span needs its own floor.
#
# The floor is the REPORTING HORIZON: this estimator reports kg per WEEK,
# so it must observe at least a week. Below that it is stating a change
# over a period longer than the one it measured.
#
# The SE-derived floor is HIGHER than that and is not reachable here, which
# is worth writing down rather than hiding. Bodyweight's own numbers are
# sigma ≈ 1.2 kg residual on morning weigh-ins and a 0.25 kg/wk target:
#
#   * at the gate's minimum sample size (n = 4),
#     T ≥ 7·1.2·sqrt(12) / (sqrt(4)·0.25) = 58 days;
#   * at the near-daily cadence the comment above actually assumes (n = T),
#     29.10/T^1.5 ≤ 0.25 → T ≥ 23.6 → 24 days.
#
# A 28-day window holds at most a 27-day span, so 58 is impossible and 24
# would unresolve a real, well-sampled trend (11 weigh-ins over an 18-day
# span, SE 0.23 kg/wk, interval comfortably clear of zero). Bodyweight's
# signal-to-noise is simply too poor for a span gate to carry detectability;
# that job belongs to the interval, which does it correctly. The span gate
# here only guarantees the estimator is not extrapolating.
BODYWEIGHT_TREND_MIN_SPAN_DAYS = 7
# Recency, same horizon and same reason. The field is labelled "per week";
# if the newest weigh-in is more than a week old the fit does not overlap
# the period the label names, and the dashboard prints a current-sounding
# rate for a stretch that has ended.
BODYWEIGHT_TREND_MAX_STALE_DAYS = 7
# Lower bound on the residual SD (see ``ols_rate_per_week``). Note what
# this floor is a bound on. Waist's floor is the TAPE — an instrument
# error. Bodyweight's scale is accurate to ~0.1 kg, so a scale-only floor
# would be ~0.05 kg and would still let four perfectly collinear weekly
# weigh-ins claim +0.10 kg/wk to within ±0.10, which is the false
# certainty being removed. The residual in this model is not the scale;
# it is everything that is not the trend, and for bodyweight that is
# dominated by the day-to-day water and gut movement the docstring above
# puts at ±1 kg. Read as a ~95% band about trend, that is an SD of
# 1.0/1.96 ≈ 0.5 kg.
#
# Sizing check against the live trackers: observed residual SD is 0.89 kg
# on one series and 0.54 kg on the other. The floor is BELOW both, so it
# does not bind today — but the 0.54 is only 8% clear of it, so a quieter
# month on that series would floor. The consequence there is bounded: at
# a residual of 0.45 the interval widens ~11%, and a rate large enough to
# have resolved before still resolves. A small rate resting on a residual
# too low to be believed is the case that stops resolving, which is the
# intent.
BODYWEIGHT_MEASUREMENT_SD_KG = 0.5


def _trend_verdict(clean: list[tuple[date, float]],
                   anchor: date | None,
                   start_d: date | None,
                   min_window_days: int,
                   min_readings: int,
                   min_span_days: int = 0,
                   max_stale_days: int | None = None,
                   noise_sd_floor: float | None = None) -> tuple:
    """Run the window / sample-size / span / recency / interval gate.

    ``clean`` is ``[(date, value), ...]`` in whatever unit the caller
    measures, sorted internally. Returns
    ``(state, reason, window_start, window_end, window_days, n_readings,
    fit, span_days, stale_days)`` where ``fit`` is an
    ``ols_rate_per_week`` result or ``None``, ``span_days`` is the actual
    spread of the in-window readings (``0`` when fewer than two survive)
    and ``stale_days`` is the gap between the newest in-window reading
    and the anchor (``None`` when there are none).

    This is the ONE gate behind every measurement trend in this module,
    and it is deliberately not parameterised by unit: the caller supplies
    only its own thresholds and, afterwards, its own wording. The failure
    that motivated the gate — a two-point slope reporting −0.37 kg/wk over
    a stretch whose honest fit was +0.07 ± 0.25 — is a property of the
    estimator, not of kilograms. A second column that grows its own,
    laxer copy of this logic reproduces that bug somewhere new, so new
    measurements route through here and add wording only.

    Three of the checks are about the READINGS rather than the window,
    and they live here for that same reason — a per-column copy of them
    is how the window/span confusion got in:

    * ``readings_stale`` — the newest reading is older than
      ``max_stale_days``. Without it, four measurements clustered eight
      weeks ago resolve to a rate the dashboard prints as current.
    * ``span_shorter_than_min`` — the readings spread across fewer than
      ``min_span_days``. Without it, the window length stands in for the
      spread and a three-day cluster is extrapolated to a monthly rate.
    * ``noise_sd_floor`` — passed through to the fit so a degenerate
      residual cannot masquerade as a narrow interval. This is NOT a
      separate unresolved state, deliberately: a long, dense, genuinely
      clean series has the strongest evidence in the file and must be
      allowed to resolve. Flooring the noise widens the interval to what
      the instrument can actually support and then lets the ordinary
      ``ci_straddles_zero`` test decide — which is the same verdict every
      other series gets, reached the same way.

    Order matters. Window, presence and sample size come first because
    they are facts about whether there is anything to fit at all.
    Staleness precedes span because "your last measurement is two months
    old" is both true and actionable when a series is stale AND short,
    and telling someone to measure over a longer stretch when the real
    problem is that they stopped measuring sends them the wrong way.
    ``no_time_variance`` is kept ahead of the span check so the
    all-on-one-day case keeps its own precise wording instead of being
    absorbed into a generic "too short".

    ``window_start`` / ``window_end`` are ``None`` in exactly one case:
    there is no anchor at all (no ``today_d`` and no readings to fall
    back on), so there is no window to describe. Callers distinguish
    "nothing was ever measured" from "nothing inside the window" on that.
    """
    pts_sorted = sorted(clean, key=lambda p: p[0])
    if anchor is None:
        # No explicit anchor: fall back to the newest reading so the
        # helper stays usable on a bare series.
        anchor = pts_sorted[-1][0] if pts_sorted else None
    if anchor is None:
        return ("unresolved", "no_readings", None, None, 0, 0, None, 0, None)

    window_start = (
        start_d if start_d is not None
        else anchor - timedelta(days=min_window_days - 1)
    )
    window_days = (anchor - window_start).days + 1
    pts = [p for p in pts_sorted if window_start <= p[0] <= anchor]
    span_days = (pts[-1][0] - pts[0][0]).days if pts else 0
    stale_days = (anchor - pts[-1][0]).days if pts else None
    tail = (window_start, anchor, window_days, len(pts))
    measured = (span_days, stale_days)

    if window_days < min_window_days:
        return ("unresolved", "window_shorter_than_min", *tail, None, *measured)
    if not pts:
        return ("unresolved", "no_readings", *tail, None, *measured)
    if len(pts) < min_readings:
        return ("unresolved", "too_few_readings", *tail, None, *measured)
    if max_stale_days is not None and stale_days > max_stale_days:
        return ("unresolved", "readings_stale", *tail, None, *measured)
    if span_days <= 0:
        return ("unresolved", "no_time_variance", *tail, None, *measured)
    if span_days < min_span_days:
        return ("unresolved", "span_shorter_than_min", *tail, None, *measured)

    fit = ols_rate_per_week(pts, noise_sd_floor=noise_sd_floor)
    if fit is None:
        return ("unresolved", "no_time_variance", *tail, None, *measured)
    if fit["ci95_low"] <= 0.0 <= fit["ci95_high"]:
        return ("unresolved", "ci_straddles_zero", *tail, fit, *measured)
    return ("resolved", None, *tail, fit, *measured)


def _noise_floor_clause(fit: dict | None, sd_text: str, source: str) -> str:
    """One sentence, appended only when the noise floor actually bound.

    Silence when it did not bind is the point: a caveat printed on every
    fit is wallpaper. When it DID bind the reader needs to know the
    interval is the known spread of ``source`` talking, not the sample's
    — the readings came out too clean to have measured their own error,
    which at four points is a sample-size artifact and not a fact about
    the body.
    """
    if not fit or not fit.get("noise_floored"):
        return ""
    return (f" These readings fit too cleanly to estimate their own error, "
            f"so the interval uses the {sd_text} spread {source} is known "
            f"to carry rather than a residual this sample is too small to "
            f"see.")


def _bw_trend_block(state: str, reason: str | None, note: str,
                    window_start: date | None, window_end: date | None,
                    window_days: int, n_readings: int,
                    fit: dict | None = None,
                    span_days: int = 0,
                    stale_days: int | None = None) -> dict:
    """Assemble the ``bodyweight_trend`` state block.

    ``span_days`` and ``days_since_last_reading`` are emitted beside
    ``window_days`` because they are different quantities and the
    difference is load-bearing: the window is what the estimator LOOKED
    at, the span is what it actually FIT. A consumer that reads only
    ``window_days`` cannot tell a month of weigh-ins from four of them
    taken on one weekend.
    """
    resolved = state == "resolved"
    return {
        "state":             state,
        "reason":            reason,
        "note":              note,
        # The headline scalar. Populated ONLY when the sign is resolved;
        # ``None`` is the honest answer the rest of the time.
        "kg_per_week":       (round(fit["per_week"], 3)
                              if resolved and fit else None),
        # The point estimate is still reported when unresolved so a human
        # can see which way the (statistically indistinguishable) fit leans.
        "point_kg_per_week": round(fit["per_week"], 3) if fit else None,
        "se_kg_per_week":    round(fit["se_per_week"], 3) if fit else None,
        "ci95_kg_per_week":  ([round(fit["ci95_low"], 3),
                               round(fit["ci95_high"], 3)] if fit else None),
        "n_readings":        n_readings,
        "window_start":      window_start.isoformat() if window_start else None,
        "window_end":        window_end.isoformat() if window_end else None,
        "window_days":       window_days,
        # What the readings themselves cover, which is the quantity the
        # SE arithmetic is about. Never inferred from ``window_days``.
        "span_days":         span_days,
        "days_since_last_reading": stale_days,
        "method":            "ols_min_28d_window_7d_span",
    }


def bodyweight_trend(
    entries: list[dict],
    today_d: date | str | None = None,
    start_date: str | date | None = None,
    min_window_days: int = BODYWEIGHT_TREND_MIN_WINDOW_DAYS,
) -> dict:
    """Weekly bodyweight slope over a minimum-28-day TIME window.

    Always returns a block; read ``state`` before ``kg_per_week``.

      * ``state == "resolved"`` — the 95% interval excludes zero, so the
        sign is real. ``kg_per_week`` carries the rate.
      * ``state == "unresolved"`` — ``kg_per_week`` is ``None`` and
        ``reason`` says why: ``no_readings`` / ``too_few_readings`` /
        ``window_shorter_than_min`` / ``readings_stale`` /
        ``span_shorter_than_min`` / ``no_time_variance`` /
        ``ci_straddles_zero``.

    The window is ``[today_d - (min_window_days - 1), today_d]``, or the
    whole open phase when ``start_date`` is supplied — a phase is judged
    inside its own window, and a phase shorter than ``min_window_days``
    cannot be judged yet at all. Entries whose notes flag a non-morning /
    non-fasted weigh-in are excluded first.

    Being inside the window is necessary and not sufficient. The weigh-ins
    must also SPAN at least ``BODYWEIGHT_TREND_MIN_SPAN_DAYS`` and the
    newest of them must be no more than ``BODYWEIGHT_TREND_MAX_STALE_DAYS``
    old, because a window is not a measurement: four weigh-ins on four
    consecutive days sit inside a 28-day window and say nothing about
    28 days.

    ``unresolved`` is a real answer, not a failure. Bodyweight moves ±1 kg
    a day on water and gut content; over four weeks that noise is the same
    size as a deliberate 0.25 kg/wk cut. Emitting ``None`` with a reason is
    strictly better than emitting a confident sign the data cannot support
    — the shipped estimator read −0.37 kg/wk over a stretch whose honest
    fit was +0.07 ± 0.25, and the coach reported fat loss across a
    stretch the user actually gained weight over.
    """
    start_d = (
        start_date if isinstance(start_date, date)
        else _parse_iso_date(start_date) if start_date else None
    )
    anchor = (
        today_d if isinstance(today_d, date)
        else _parse_iso_date(today_d) if today_d else None
    )

    clean: list[tuple[date, float]] = []
    for e in entries or []:
        if _is_flagged_nonfasted(e):
            continue
        d = _parse_iso_date(e.get("date"))
        kg = e.get("kg")
        if d is None or kg is None:
            continue
        try:
            clean.append((d, float(kg)))
        except (TypeError, ValueError):
            continue
    clean.sort(key=lambda p: p[0])

    (state, reason, w_start, w_end, window_days, n_pts, fit,
     span_days, stale_days) = _trend_verdict(
        clean, anchor, start_d,
        min_window_days, BODYWEIGHT_TREND_MIN_READINGS,
        min_span_days=BODYWEIGHT_TREND_MIN_SPAN_DAYS,
        max_stale_days=BODYWEIGHT_TREND_MAX_STALE_DAYS,
        noise_sd_floor=BODYWEIGHT_MEASUREMENT_SD_KG,
    )

    if reason == "no_readings" and w_start is None:
        note = "No usable bodyweight readings."
    elif reason == "no_readings":
        note = "No bodyweight readings inside the window."
    elif reason == "window_shorter_than_min":
        note = (f"Window is {window_days} days; a weekly rate needs at least "
                f"{min_window_days} days of baseline to separate signal from "
                f"day-to-day fluctuation.")
    elif reason == "too_few_readings":
        note = (f"{n_pts} reading(s) in a {window_days}-day window; "
                f"{BODYWEIGHT_TREND_MIN_READINGS} are needed to fit a rate "
                "and its error.")
    elif reason == "readings_stale":
        note = (f"Newest weigh-in is {stale_days} days old; a weekly rate is "
                f"only current while the last reading is within "
                f"{BODYWEIGHT_TREND_MAX_STALE_DAYS} days. Weigh in to "
                "resolve it.")
    elif reason == "no_time_variance":
        note = "All readings in the window fall on one day."
    elif reason == "span_shorter_than_min":
        note = (f"{n_pts} weigh-ins spanning {span_days} days; a weekly rate "
                f"needs at least {BODYWEIGHT_TREND_MIN_SPAN_DAYS} days of "
                "spread. Fitting a shorter stretch and reporting it per week "
                "extrapolates rather than measures.")
    elif reason == "ci_straddles_zero":
        note = (f"Fit is {fit['per_week']:+.2f} kg/wk but the 95% interval "
                f"[{fit['ci95_low']:+.2f}, {fit['ci95_high']:+.2f}] includes "
                "zero — the direction is not resolved by this data. Do not "
                "report a gain or a loss."
                + _noise_floor_clause(fit, "0.5 kg/day", "morning bodyweight"))
    else:
        direction = "gaining" if fit["per_week"] > 0 else "losing"
        note = (f"{direction} {abs(fit['per_week']):.2f} kg/wk "
                f"(95% CI [{fit['ci95_low']:+.2f}, {fit['ci95_high']:+.2f}] "
                f"over {fit['n']} readings spanning {span_days} days)."
                + _noise_floor_clause(fit, "0.5 kg/day", "morning bodyweight"))

    return _bw_trend_block(state, reason, note,
                           w_start, w_end, window_days, n_pts, fit,
                           span_days, stale_days)


def bodyweight_trend_kg_per_week(
    entries: list[dict],
    start_date: str | date | None = None,
    today_d: date | str | None = None,
) -> float | None:
    """Resolved weekly bodyweight slope, or ``None``.

    Thin scalar accessor over ``bodyweight_trend`` — see that function for
    the window rule and for why ``None`` is a first-class answer rather
    than a failure. Callers that need the reason must read the block.
    """
    return bodyweight_trend(
        entries, today_d=today_d, start_date=start_date,
    )["kg_per_week"]


# Waist circumference moves slowly and is read off a tape, so its window
# floor is HIGHER than bodyweight's, not lower.
#
# Self-measured waist reproducibility is roughly 0.5-1.0 cm (test-retest
# SD; tape height and tension are the error, not the body). The standard
# error of an OLS slope over ``n`` readings spread across ``T`` days is
# about ``sigma * sqrt(12) / (sqrt(n) * T)`` per day. At sigma = 0.8 cm,
# expressed per 4 weeks:
#
#     T = 28d, n = 4   ->  SE ~= 1.4 cm / 4wk
#     T = 56d, n = 8   ->  SE ~= 0.5 cm / 4wk
#     T = 84d, n = 12  ->  SE ~= 0.3 cm / 4wk
#
# A real waist change during a cut runs about 1 cm per 4 weeks. At a
# 28-day window the 95% half-interval is over 5 cm, so nothing honest
# ever resolves there and anything that DOES resolve is a tape artifact
# wearing a confidence interval. 56 days is the floor at which the
# interval starts to be narrower than the effect it is trying to detect.
WAIST_TREND_MIN_WINDOW_DAYS = 56
# Same reasoning as BODYWEIGHT_TREND_MIN_READINGS: 3 points leave one
# degree of freedom, where the 95% t-multiplier is 12.7 and the verdict
# can only ever be "unresolved" for a reason that has nothing to do with
# the body. 4 is the floor, and below it the reason reported is the
# honest one.
WAIST_TREND_MIN_READINGS = 4
# T in the SE table above is the SPREAD OF THE READINGS. The window floor
# is not that quantity, and substituting one for the other is what let
# four tape readings taken over three days report −2.80 cm/4wk with a
# zero-width interval: 0.3 cm of drift divided by a 3-day span and
# multiplied back up to 28.
#
# Solve the same expression the table is built from for T, at the sample
# size this gate actually admits (n = 4) and against the effect the
# comment names (1 cm per 4 weeks):
#
#     SE_4w = 28·sigma·sqrt(12) / (sqrt(n)·T) ≤ 1.0 cm
#           = 28·0.8·3.4641 / (2·T)          ≤ 1.0
#     ->  T ≥ 38.80  ->  39 days
#
# which reproduces the table exactly: T = 28, n = 4 gives 1.39 cm (the
# comment's "~1.4", and its reason for refusing a 28-day floor), and 39
# is where that curve crosses the 1 cm effect. The window still holds it
# — 56 days of window admits a 55-day span — so weekly (49 d) and
# fortnightly (42 d) cadences both clear it, and only a burst of readings
# crammed into part of the window does not.
WAIST_TREND_MIN_SPAN_DAYS = 39
# Recency. The field is labelled "per 4 weeks"; if the newest measurement
# is older than 4 weeks the fit describes a period that does not overlap
# the one the label names. This is the second half of the same defect:
# four readings clustered 52-55 days ago resolved to a rate the dashboard
# printed beside a sparkline that had nothing in it.
WAIST_TREND_MAX_STALE_DAYS = 28
# Lower bound on the residual SD (see ``ols_rate_per_week``). The
# test-retest band cited above is 0.5-1.0 cm; the LOW end is the right
# floor because a floor asserts what the tape cannot go below, not what
# it typically is. Tape readings rounded to 0.1 cm on a slowly-moving
# body land on a straight line often enough that the degenerate
# zero-residual fit is a realistic input, not a synthetic one.
WAIST_MEASUREMENT_SD_CM = 0.5

# Keys ``waist_trend`` will read a value from, in order. ``cm`` is what
# ``read_tracker`` passes; ``value`` is what
# ``csv_store_dense.read_body_composition`` already returns; ``waist_cm``
# is the raw health_metrics row key. Accepting all three means the second
# tracked person's importer needs no adapter to reach this function.
_WAIST_VALUE_KEYS = ("cm", "value", "waist_cm")


def _waist_trend_block(state: str, reason: str | None, note: str,
                       window_start: date | None, window_end: date | None,
                       window_days: int, n_readings: int,
                       fit: dict | None = None,
                       span_days: int = 0,
                       stale_days: int | None = None) -> dict:
    """Assemble the ``waist_trend_cm_per_4w`` state block.

    Field-for-field the shape ``_bw_trend_block`` emits, with the rate
    rescaled from per-week to per-4-week and the unit in the key names.
    Reading one of these teaches you how to read the other, which is the
    point: the coach must check ``state`` before the number in both.
    """
    resolved = state == "resolved"
    per_4w = fit["per_week"] * 4.0 if fit else None
    se_4w = fit["se_per_week"] * 4.0 if fit else None
    return {
        "state":            state,
        "reason":           reason,
        "note":             note,
        # The headline scalar. Populated ONLY when the sign is resolved;
        # ``None`` is the honest answer the rest of the time.
        "cm_per_4w":        round(per_4w, 3) if resolved and fit else None,
        # The point estimate is still reported when unresolved so a human
        # can see which way the (indistinguishable-from-flat) fit leans.
        "point_cm_per_4w":  round(per_4w, 3) if fit else None,
        "se_cm_per_4w":     round(se_4w, 3) if fit else None,
        "ci95_cm_per_4w":   ([round(fit["ci95_low"] * 4.0, 3),
                              round(fit["ci95_high"] * 4.0, 3)]
                             if fit else None),
        "n_readings":       n_readings,
        "window_start":     window_start.isoformat() if window_start else None,
        "window_end":       window_end.isoformat() if window_end else None,
        "window_days":      window_days,
        # What the measurements themselves cover. ``window_days`` is what
        # was searched; this is what was fitted, and the two are only
        # equal by accident.
        "span_days":        span_days,
        "days_since_last_reading": stale_days,
        "method":           "ols_min_56d_window_39d_span",
    }


def waist_trend(
    readings: list[dict],
    today_d: date | str | None = None,
    min_window_days: int = WAIST_TREND_MIN_WINDOW_DAYS,
) -> dict:
    """Waist circumference slope in cm per 4 weeks, with its state.

    ``readings`` is ``[{"date": "YYYY-MM-DD", "cm": 87.0}, ...]`` (``value``
    and ``waist_cm`` are accepted as aliases for ``cm``). Order does not
    matter; the series is sorted internally.

    Always returns a block; read ``state`` before ``cm_per_4w``.

      * ``state == "resolved"`` — the 95% interval excludes zero, so the
        sign is real. ``cm_per_4w`` carries the rate.
      * ``state == "unresolved"`` — ``cm_per_4w`` is ``None`` and
        ``reason`` says why: ``no_readings`` / ``too_few_readings`` /
        ``readings_stale`` / ``no_time_variance`` /
        ``span_shorter_than_min`` / ``ci_straddles_zero``. (The gate's
        remaining reason, ``window_shorter_than_min``, needs a
        caller-supplied window start the way bodyweight takes one from an
        open nutrition phase; waist has no equivalent scoping and so
        cannot emit it.)

    The window is ``[today_d - (min_window_days - 1), today_d]``, so a
    reading dated after ``today_d`` is outside it by construction and a
    backtest cannot see a measurement that had not been taken yet.

    Landing inside the window is not the same as describing it. Four
    measurements taken over one weekend sit inside a 56-day window and
    span three days; dividing their drift by three days and multiplying
    it back up to four weeks is extrapolation, and the reported rate
    changes by a factor of nine depending on which weekend it was. So
    the measurements must also spread across at least
    ``WAIST_TREND_MIN_SPAN_DAYS`` and end no more than
    ``WAIST_TREND_MAX_STALE_DAYS`` before the anchor. ``note`` reports
    the SPAN, never the window: a fit over three days that announces
    itself as "over 56 days" is worse than no note at all.

    It is a fixed period, not a "last N measurements" rule, for the same
    reason bodyweight's is: an elastic window makes the same key describe
    a different stretch of time from run to run without saying so. The
    cost is real and is the honest one to pay — someone who measures
    monthly never has four measurements inside 56 days and gets
    ``too_few_readings`` indefinitely. The fix for that is a denser
    measuring cadence, which ``note`` asks for, not a wider window fitted
    behind the user's back.

    ONE reading is not a trend and this returns ``too_few_readings`` for
    it, not ``0.0``. That distinction is the whole reason this routes
    through ``_trend_verdict`` instead of subtracting two numbers: the
    naive version of this function, applied to bodyweight, once reported
    a confident loss across a stretch the user gained weight over.

    Unit-confused input is not filtered here — ``apple_health_core``'s
    ``PLAUSIBLE_RANGES`` is the single corruption gate and it runs at
    import. What this estimator adds is that one surviving bad reading
    inflates the residual spread and widens the interval, so the verdict
    degrades to ``ci_straddles_zero`` rather than to a confident slope.
    """
    anchor = (
        today_d if isinstance(today_d, date)
        else _parse_iso_date(today_d) if today_d else None
    )

    clean: list[tuple[date, float]] = []
    for e in readings or []:
        d = _parse_iso_date(e.get("date"))
        if d is None:
            continue
        raw = next(
            (e[k] for k in _WAIST_VALUE_KEYS
             if e.get(k) is not None),
            None,
        )
        if raw is None:
            continue
        try:
            clean.append((d, float(raw)))
        except (TypeError, ValueError):
            continue
    clean.sort(key=lambda p: p[0])

    (state, reason, w_start, w_end, window_days, n_pts, fit,
     span_days, stale_days) = _trend_verdict(
        clean, anchor, None, min_window_days, WAIST_TREND_MIN_READINGS,
        min_span_days=WAIST_TREND_MIN_SPAN_DAYS,
        max_stale_days=WAIST_TREND_MAX_STALE_DAYS,
        noise_sd_floor=WAIST_MEASUREMENT_SD_CM,
    )

    if reason == "no_readings" and w_start is None:
        note = "No waist measurements on file."
    elif reason == "no_readings":
        note = "No waist measurements inside the window."
    elif reason == "window_shorter_than_min":
        note = (f"Window is {window_days} days; a waist rate needs at least "
                f"{min_window_days} days of baseline, because tape-measure "
                "error is about the size of a month of real change.")
    elif reason == "too_few_readings":
        lead = ("A single measurement is a value, not a trend. "
                if n_pts <= 1 else "")
        note = (f"{n_pts} measurement(s) in a {window_days}-day window; "
                f"{WAIST_TREND_MIN_READINGS} are needed to fit a rate and "
                f"its error. {lead}Measuring weekly makes this resolvable "
                f"within {window_days} days.")
    elif reason == "readings_stale":
        note = (f"Newest measurement is {stale_days} days old; a cm/4wk rate "
                f"describes the last 4 weeks and cannot be read off "
                f"measurements that stop more than "
                f"{WAIST_TREND_MAX_STALE_DAYS} days back. Measure again to "
                "resolve it.")
    elif reason == "no_time_variance":
        note = "All measurements in the window fall on one day."
    elif reason == "span_shorter_than_min":
        note = (f"{n_pts} measurements spanning {span_days} days inside a "
                f"{window_days}-day window; a cm/4wk rate needs at least "
                f"{WAIST_TREND_MIN_SPAN_DAYS} days of spread. Over a shorter "
                "stretch the tape's own error is larger than the change, and "
                "dividing it by the span inflates it into a monthly rate.")
    elif reason == "ci_straddles_zero":
        note = (f"Fit is {fit['per_week'] * 4.0:+.2f} cm/4wk but the 95% "
                f"interval [{fit['ci95_low'] * 4.0:+.2f}, "
                f"{fit['ci95_high'] * 4.0:+.2f}] includes zero, so the "
                "direction is not resolved by this data. Do not report a "
                "gain or a loss."
                + _noise_floor_clause(fit, "0.5 cm", "a tape measure"))
    else:
        direction = "widening" if fit["per_week"] > 0 else "narrowing"
        note = (f"{direction} {abs(fit['per_week'] * 4.0):.2f} cm/4wk "
                f"(95% CI [{fit['ci95_low'] * 4.0:+.2f}, "
                f"{fit['ci95_high'] * 4.0:+.2f}] over {fit['n']} "
                f"measurements spanning {span_days} days)."
                + _noise_floor_clause(fit, "0.5 cm", "a tape measure"))

    return _waist_trend_block(state, reason, note,
                              w_start, w_end, window_days, n_pts, fit,
                              span_days, stale_days)


def build_monthly_sessions(rows: list[dict],
                            session_summaries: dict[str, dict] | None = None,
                            session_totals: dict[str, float] | None = None,
                            apple_sessions: list[dict] | None = None,
                            ) -> list[dict]:
    """Aggregate per-set rows into one entry per session-date.

    Strength sessions: metadata sourced from the TOTAL row's summary
    record in ``session_summaries`` (Active Cal, Total Cal, Elevation,
    Elapsed, Avg HR, Duration). Cardio-only sessions don't have a TOTAL
    row, so their metadata is read directly from the cardio rows.

    Folds in:
    - ``volume`` for strength sessions from ``session_totals`` (so the
      caller doesn't need to ship ``session_totals`` separately).
    - ``max_hr`` per session from ``apple_sessions`` (Apple's per-workout
      max HR — only present for XML; HL surfaces None and the field is
      stripped by ``_compact``).

    Returns a list sorted by date ascending.
    """
    summaries = session_summaries or {}
    totals = session_totals or {}
    apple = apple_sessions or []

    # date → max_hr lookup. Apple may record multiple workouts per date
    # (Core + Functional + cardio rides); we keep the largest max_hr seen
    # across all of them as the session's peak. We deliberately don't
    # surface ``apple_type`` here because it conflates strength and
    # cardio for mixed days — ``session_kind`` is the authoritative tag.
    by_date_apple: dict[str, float] = {}
    for ap in apple:
        d = ap.get("date")
        if not d:
            continue
        mh = ap.get("max_hr")
        if mh and mh > by_date_apple.get(d, 0):
            by_date_apple[d] = mh

    # Pass 1: scan rows to learn, per date, which kinds of rows are present
    # and capture each kind's first-appearance exercise name for
    # ``exercise_first``. A date with both strength and cardio rows will
    # emit TWO entries downstream (one per kind) so per-session TRIMP and
    # CTL/ATL/TSB don't lose the day's cardio when a strength session also
    # happened.
    date_kinds: dict[str, dict] = {}
    for r in rows:
        d = r.get("date")
        if not d:
            continue
        is_strength_row = (r.get("kg") or 0) * (r.get("reps") or 0) > 0
        is_cardio_row = _is_cardio_row(r)
        bucket = date_kinds.setdefault(d, {
            "has_strength": False, "has_cardio": False,
            "has_other": False,
            "strength_first": None, "cardio_first": None, "other_first": None,
        })
        if is_strength_row:
            bucket["has_strength"] = True
            if bucket["strength_first"] is None:
                bucket["strength_first"] = r.get("exercise")
        if is_cardio_row:
            bucket["has_cardio"] = True
            if bucket["cardio_first"] is None:
                bucket["cardio_first"] = r.get("exercise")
        if not is_strength_row and not is_cardio_row:
            bucket["has_other"] = True
            if bucket["other_first"] is None:
                bucket["other_first"] = r.get("exercise")

    # Pass 2: build the entries, keyed by ``(date, kind)``. Each date with
    # both kinds yields two entries; pure days yield one.
    by_key: dict[tuple, dict] = {}
    for d, bucket in date_kinds.items():
        if bucket["has_strength"]:
            by_key[(d, "strength")] = {
                "date": d,
                "session_kind": "strength",
                "exercise_first": bucket["strength_first"],
                "active_cal":  None, "total_cal":   None,
                "elevation_m": None, "elapsed":     None,
                "avg_hr":      None, "duration_min": None,
            }
        if bucket["has_cardio"]:
            by_key[(d, "cardio")] = {
                "date": d,
                "session_kind": "cardio",
                "exercise_first": bucket["cardio_first"],
                "active_cal":  None, "total_cal":   None,
                "elevation_m": None, "elapsed":     None,
                "avg_hr":      None, "duration_min": None,
            }
        if bucket["has_other"] and not bucket["has_strength"] and not bucket["has_cardio"]:
            by_key[(d, "other")] = {
                "date": d,
                "session_kind": "other",
                "exercise_first": bucket["other_first"],
                "active_cal":  None, "total_cal":   None,
                "elevation_m": None, "elapsed":     None,
                "avg_hr":      None, "duration_min": None,
            }

    # Pass 3: AGGREGATE all cardio rows on each date into the single
    # ``(date, "cardio")`` entry. A day can hold several bouts (an easy
    # swim, a commute ride, an interval run); the old "fill if empty" rule
    # kept only the FIRST bout and silently dropped the rest, undercounting
    # cardio minutes by 23-37% on multi-bout days and corrupting every
    # downstream cardio metric (HR-zones, per-session TRIMP, CTL/ATL/TSB,
    # week-over-week). We instead SUM the additive quantities (duration,
    # calories, distance), take the MAX elevation, the duration-weighted
    # mean HR, and the first non-empty elapsed string. Strength entries are
    # left alone here; their metadata comes from the TOTAL-row summary.
    #
    # ``_hr_num`` / ``_hr_den`` accumulate the duration-weighted HR. A bout
    # with HR but no duration still contributes its HR with unit weight so
    # it isn't silently dropped; a bout with neither is ignored for HR.
    cardio_agg: dict[str, dict] = {}
    for r in rows:
        d = r.get("date")
        if not d or not _is_cardio_row(r):
            continue
        if (d, "cardio") not in by_key:
            continue
        agg = cardio_agg.setdefault(d, {
            "duration_min": 0.0, "active_cal": 0.0, "total_cal": 0.0,
            "distance_km": 0.0, "elevation_m": None, "elapsed": None,
            "_hr_num": 0.0, "_hr_den": 0.0,
            "_has_duration": False, "_has_active_cal": False,
            "_has_total_cal": False, "_has_distance": False,
        })
        dur = r.get("duration_min")
        if dur not in (None, ""):
            agg["duration_min"] += float(dur)
            agg["_has_duration"] = True
        for key, flag in (("active_cal", "_has_active_cal"),
                          ("total_cal", "_has_total_cal"),
                          ("distance_km", "_has_distance")):
            v = r.get(key)
            if v not in (None, ""):
                agg[key] += float(v)
                agg[flag] = True
        elev = r.get("elevation_m")
        if elev not in (None, ""):
            elev_f = float(elev)
            if agg["elevation_m"] is None or elev_f > agg["elevation_m"]:
                agg["elevation_m"] = elev_f
        if agg["elapsed"] in (None, "") and r.get("elapsed") not in (None, ""):
            agg["elapsed"] = r.get("elapsed")
        hr = r.get("avg_hr")
        if hr not in (None, "") and float(hr) > 0:
            w = float(dur) if dur not in (None, "") and float(dur) > 0 else 1.0
            agg["_hr_num"] += float(hr) * w
            agg["_hr_den"] += w

    for d, agg in cardio_agg.items():
        s = by_key[(d, "cardio")]
        if agg["_has_duration"]:
            s["duration_min"] = agg["duration_min"]
        if agg["_has_active_cal"]:
            s["active_cal"] = agg["active_cal"]
        if agg["_has_total_cal"]:
            s["total_cal"] = agg["total_cal"]
        if agg["_has_distance"]:
            s["distance_km"] = agg["distance_km"]
        if agg["elevation_m"] is not None:
            s["elevation_m"] = agg["elevation_m"]
        if agg["elapsed"] not in (None, ""):
            s["elapsed"] = agg["elapsed"]
        if agg["_hr_den"] > 0:
            s["avg_hr"] = agg["_hr_num"] / agg["_hr_den"]

    # Pass 4: fold TOTAL-row session summaries into the strength entries
    # (TOTAL rows are not emitted for pure cardio).
    for d, summary in summaries.items():
        s = by_key.get((d, "strength"))
        if s is None:
            continue
        if summary.get("active_cal") is not None:
            s["active_cal"] = summary["active_cal"]
        if summary.get("total_cal") is not None:
            s["total_cal"] = summary["total_cal"]
        if summary.get("elevation_m") is not None:
            s["elevation_m"] = summary["elevation_m"]
        if summary.get("elapsed"):
            s["elapsed"] = summary["elapsed"]
        if summary.get("avg_hr") is not None:
            s["avg_hr"] = summary["avg_hr"]
        if summary.get("duration_min") is not None:
            s["duration_min"] = summary["duration_min"]
        if summary.get("is_deload"):
            s["is_deload"] = True

    # Emit sorted by (date, kind) with strength before cardio on mixed days.
    kind_order = {"strength": 0, "cardio": 1, "other": 2}
    out: list[dict] = []
    for d, kind in sorted(by_key.keys(), key=lambda k: (k[0], kind_order.get(k[1], 9))):
        s = by_key[(d, kind)]
        if kind == "strength" and d in totals:
            s["volume"] = totals[d]
        max_hr = by_date_apple.get(d)
        if max_hr:
            s["max_hr"] = max_hr
        out.append(s)
    return out


def _is_working_set(r: dict) -> bool:
    """True when a row is a counted hard SET.

    Three shapes count as one set each:

    1. A positive-rep set. Bodyweight (kg=0, reps>0 like Pull-Up) counts.
    2. A duration hold with reps==0 — an isometric (Plank, Side Plank) or
       a timed carry — *provided* it is not a cardio bout and not a pure
       distance row. The hold time substitutes for reps as the work unit;
       per-muscle attribution still requires a DB primary at the consumer,
       so an unknown/cardio-section exercise contributes zero there.
    3. A LOADED CARRY with reps==0: ``kg > 0`` plus either a duration or a
       distance (Suitcase Carry 3 × 30m @ 24kg, Farmer Walk 2 × 40s @ 48kg).
       The load is the work unit here, so a carry measured in metres rather
       than seconds must not score zero. ``kg > 0`` is exactly what keeps
       this clause disjoint from the distance→cardio gate in
       ``_is_cardio_row``, which only fires on UNLOADED distance.

    Cardio rows and warmup-tagged rows (structured ``(warmup)`` marker or
    word-bounded "warm-up"/"warm up") are always excluded. Isometrics stay
    out of e1RM/progression — those paths gate on ``kg > 0`` independently.

    Known gap: a carry logged with a load but with NO duration and NO
    distance carries no work unit at all and still scores zero. The logger
    writes carry time to ``Duration (min)``; rows predating that rule need
    a data fix, not a code one.
    """
    if _notes_has_warmup(r.get("notes")):
        return False
    reps = r.get("reps") or 0
    if reps > 0:
        return True
    # reps == 0 (or missing). A LOADED carry counts on either work unit.
    if (r.get("kg") or 0) > 0 and (
        (r.get("duration_min") or 0) > 0 or (r.get("distance_km") or 0) > 0
    ):
        return True
    # Otherwise only a non-cardio duration hold counts.
    if (r.get("duration_min") or 0) <= 0:
        return False
    if _is_cardio_row(r):
        return False
    return True
