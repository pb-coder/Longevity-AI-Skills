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
- ``bodyweight_trend(entries, today_d, start_date)`` — OLS weekly slope
  over a minimum-28-day TIME window, with an explicit
  ``resolved`` / ``unresolved`` state.
- ``bodyweight_trend_kg_per_week(entries)`` — the scalar from that
  block: the rate when it resolves, ``None`` when it does not.
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


def ols_rate_per_week(points: list[tuple[date, float]]) -> dict | None:
    """Least-squares weekly rate of change, with its uncertainty.

    ``points`` is ``[(date, value), ...]``; it is sorted internally. Returns
    ``None`` when there are fewer than 3 points or every reading falls on the
    same day (no x-variance to regress against). Otherwise returns::

        {"per_week", "se_per_week", "ci95_low", "ci95_high",
         "n", "dof", "span_days", "residual_sd"}

    Every point in the window contributes, which is the difference that
    matters against endpoint or mean-of-N smoothing: one aberrant weigh-in
    moves an OLS slope by ``O(1/n)`` instead of by ``O(1/3)``.

    The interval is the classic ``b ± t(0.975, n-2) · SE(b)``. It is the
    load-bearing output, not decoration — a weekly bodyweight rate whose
    interval spans zero has no resolved sign, and reporting the point
    estimate as though it did is exactly the failure this replaces.
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
    se_per_day = math.sqrt(resid_var / sxx)
    per_week = slope_per_day * 7.0
    se_per_week = se_per_day * 7.0
    half = _t_crit_95(dof) * se_per_week
    return {
        "per_week":    per_week,
        "se_per_week": se_per_week,
        "ci95_low":    per_week - half,
        "ci95_high":   per_week + half,
        "n":           n,
        "dof":         dof,
        "span_days":   int((pts[-1][0] - pts[0][0]).days),
        "residual_sd": math.sqrt(resid_var),
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


def _bw_trend_block(state: str, reason: str | None, note: str,
                    window_start: date | None, window_end: date | None,
                    window_days: int, n_readings: int,
                    fit: dict | None = None) -> dict:
    """Assemble the ``bodyweight_trend`` state block."""
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
        "method":            "ols_min_28d_window",
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
        ``window_shorter_than_min`` / ``no_time_variance`` /
        ``ci_straddles_zero``.

    The window is ``[today_d - (min_window_days - 1), today_d]``, or the
    whole open phase when ``start_date`` is supplied — a phase is judged
    inside its own window, and a phase shorter than ``min_window_days``
    cannot be judged yet at all. Entries whose notes flag a non-morning /
    non-fasted weigh-in are excluded first.

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

    if anchor is None:
        # No explicit anchor: fall back to the newest clean reading so the
        # helper stays usable on a bare series.
        anchor = clean[-1][0] if clean else None
    if anchor is None:
        return _bw_trend_block(
            "unresolved", "no_readings",
            "No usable bodyweight readings.",
            None, None, 0, 0,
        )

    window_start = (
        start_d if start_d is not None
        else anchor - timedelta(days=min_window_days - 1)
    )
    window_days = (anchor - window_start).days + 1
    pts = [p for p in clean if window_start <= p[0] <= anchor]

    if window_days < min_window_days:
        return _bw_trend_block(
            "unresolved", "window_shorter_than_min",
            (f"Window is {window_days} days; a weekly rate needs at least "
             f"{min_window_days} days of baseline to separate signal from "
             f"day-to-day fluctuation."),
            window_start, anchor, window_days, len(pts),
        )
    if not pts:
        return _bw_trend_block(
            "unresolved", "no_readings",
            "No bodyweight readings inside the window.",
            window_start, anchor, window_days, 0,
        )
    if len(pts) < BODYWEIGHT_TREND_MIN_READINGS:
        return _bw_trend_block(
            "unresolved", "too_few_readings",
            (f"{len(pts)} reading(s) in a {window_days}-day window; "
             f"{BODYWEIGHT_TREND_MIN_READINGS} are needed to fit a rate and "
             "its error."),
            window_start, anchor, window_days, len(pts),
        )

    fit = ols_rate_per_week(pts)
    if fit is None:
        return _bw_trend_block(
            "unresolved", "no_time_variance",
            "All readings in the window fall on one day.",
            window_start, anchor, window_days, len(pts),
        )
    if fit["ci95_low"] <= 0.0 <= fit["ci95_high"]:
        return _bw_trend_block(
            "unresolved", "ci_straddles_zero",
            (f"Fit is {fit['per_week']:+.2f} kg/wk but the 95% interval "
             f"[{fit['ci95_low']:+.2f}, {fit['ci95_high']:+.2f}] includes "
             "zero — the direction is not resolved by this data. Do not "
             "report a gain or a loss."),
            window_start, anchor, window_days, len(pts), fit,
        )
    direction = "gaining" if fit["per_week"] > 0 else "losing"
    return _bw_trend_block(
        "resolved", None,
        (f"{direction} {abs(fit['per_week']):.2f} kg/wk "
         f"(95% CI [{fit['ci95_low']:+.2f}, {fit['ci95_high']:+.2f}] over "
         f"{fit['n']} readings / {window_days} days)."),
        window_start, anchor, window_days, len(pts), fit,
    )


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
