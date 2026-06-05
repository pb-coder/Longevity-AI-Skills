"""Cardio + load analytics.

The cardio side of the analytics layer:

- ``cardio_last_28d(rows, today_d)`` — 4-week rollup of cardio sessions
  (distance, minutes, kcal, intervals-vs-non-interval split via Notes
  keywords + avg_hr ≥165 heuristic). Note: ``non_interval_minutes`` is
  *not* a true Zone-2 measurement — see ``cardio_hr_zones`` for that.
- ``cardio_hr_zones(monthly_sessions, today_d, max_hr, rest_hr)`` — time
  in HR zones using HRR (Karvonen). Coarse: each session's avg_hr
  determines its zone bucket; per-second HR isn't available.
- ``_trimp(...)`` / ``trimp_per_session(...)`` — Banister TRIMP score.
  Used by every load-tracking computation downstream.
- ``training_load_summary(trimps, today_d)`` — CTL/ATL/TSB
  (TrainingPeaks-standard 42d/7d EWMA over per-session TRIMP).
- ``auto_deload_candidates(monthly_sessions, deloads_logged, today_d)``
  — heuristic flag for unmarked deload weeks (≥35% volume drop AND
  ≥8 bpm avg-HR drop vs prior 4w).
- ``daily_activity_28d(health_all, workout_sessions_all, today_d)`` —
  NEAT rollup folding Apple exercise minutes + walking workouts into
  one ``assessment`` band.
"""
from __future__ import annotations

import math
from datetime import date, timedelta


from .health_windowing import _values_in_window
from .parsing import _parse_iso_date
from .sessions import _is_cardio_row


# Karvonen / HR-zone definitions (% of HRR — heart rate reserve).
HR_ZONES_PCT = [
    ("z1", 0.50, 0.60),
    ("z2", 0.60, 0.70),
    ("z3", 0.70, 0.80),
    ("z4", 0.80, 0.90),
    ("z5", 0.90, 1.00),
]


def _hr_zone_label_for_hrr_pct(hrr_pct: float) -> str:
    """Map an HRR percent (0.0–1.0) to a Z1/Z2/Z3/Z4/Z5 label.

    Below the Z1 floor (0.50 HRR — i.e. resting-ish activity) labels as
    "Z1" rather than something out-of-band, since the coaching consumer
    treats sub-50% HRR walks/commutes as base-aerobic context. Z1 also
    catches the very top of recovery rides.
    """
    if hrr_pct >= 0.90:
        return "Z5"
    if hrr_pct >= 0.80:
        return "Z4"
    if hrr_pct >= 0.70:
        return "Z3"
    if hrr_pct >= 0.60:
        return "Z2"
    return "Z1"


def _cardio_activity_bucket(name: str | None) -> str:
    """Coarse activity bucket for interpreting Zone-2 dose."""
    n = (name or "").strip().lower()
    if "swim" in n:
        return "swim"
    if "run" in n or "treadmill" in n:
        return "run"
    if "cycling" in n or "bike" in n or "bicycle" in n:
        return "cycle"
    if "walk" in n or "hike" in n:
        return "walk_hike"
    return "other"


def cardio_last_28d(rows: list[dict], today_d: date) -> dict:
    """4-week cardio rollup: total distance, total minutes, total cal, and
    a coarse intervals-vs-non-interval split.

    ``non_interval_minutes`` is the residual after subtracting interval
    sessions; it is *not* a true Zone-2 measurement. A 3h hike at
    avg_hr 110 (Z1) lands in the same bucket as a 45min Z2 ride. Use
    ``cardio_hr_zones_28d.z2`` for actual Zone-2 minutes when the
    source supplies per-workout HR; treat this field as a fallback for
    sources that don't.

    Now uses a 28d window (was 14d) to align with the strength-side
    weekly_volume window. Cardio rows are identified by distance or
    duration > 0; intervals are flagged from Notes keywords or avg_hr
    >= 165 (a rough ceiling that catches Z4+ work without the user
    having to annotate).
    """
    cutoff = today_d - timedelta(days=28)
    non_interval_min = 0.0
    intervals = 0
    distance = 0.0
    total_min = 0.0
    total_cal = 0.0
    sessions = 0
    for r in rows:
        d = _parse_iso_date(r.get("date"))
        if d is None:
            continue
        if d < cutoff:
            continue
        dur = r.get("duration_min") or 0
        dist = r.get("distance_km") or 0
        if not _is_cardio_row(r):
            continue
        sessions += 1
        distance += dist
        total_min += dur
        cal = r.get("active_cal") or 0
        total_cal += cal
        note = (r.get("notes") or "").lower()
        hr = r.get("avg_hr") or 0
        is_intervals = any(k in note for k in ("interval", "zone 4", "zone 5", "z4", "z5")) or hr >= 165
        if is_intervals:
            intervals += 1
        else:
            non_interval_min += dur
    return {
        "sessions":             sessions,
        "total_minutes":        round(total_min, 1),
        "total_distance_km":    round(distance, 2),
        "total_active_cal":     int(round(total_cal)) if total_cal else 0,
        "non_interval_minutes": round(non_interval_min, 1),
        "interval_sessions":    intervals,
    }


def _trimp(duration_min: float, avg_hr: float,
           rest_hr: float, max_hr: float) -> float:
    """Banister TRIMP. ``duration_min × HRr × 0.64 × e^(1.92×HRr)`` (men).

    Only positive when HR is above resting. Uses HRR (heart rate
    reserve) normalisation so the same TRIMP score means the same
    relative effort across users.
    """
    if not duration_min or not avg_hr or not max_hr or not rest_hr:
        return 0.0
    if max_hr <= rest_hr:
        return 0.0
    hrr = (avg_hr - rest_hr) / (max_hr - rest_hr)
    if hrr <= 0:
        return 0.0
    hrr = min(hrr, 1.0)
    return round(duration_min * hrr * 0.64 * math.exp(1.92 * hrr), 1)


def trimp_per_session(monthly_sessions: list[dict],
                      max_hr: float | None,
                      rest_hr: float | None) -> list[dict]:
    """Compute TRIMP for every session that has both avg_hr and duration.

    Returns one entry per session with ``date, kind, trimp, intensity_pct``
    (HRR percent), plus a ``load_band`` classification (light <50,
    moderate 50-100, hard 100-150, red-line >150) and an ``hr_zone_label``
    (Z1–Z5) for the session's average HR. The label is the per-session
    counterpart to ``cardio_hr_zones_28d`` (which buckets *time* in zones
    across the window); use it to say "this 35 min run was a Z3 grey-
    zone session" without re-deriving from avg HR each time.
    """
    if not max_hr or not rest_hr or max_hr <= rest_hr:
        return []
    out: list[dict] = []
    for s in monthly_sessions:
        avg_hr = s.get("avg_hr")
        dur = s.get("duration_min")
        if not avg_hr or not dur:
            continue
        try:
            avg_hr_f = float(avg_hr)
            dur_f = float(dur)
        except (TypeError, ValueError):
            continue
        trimp = _trimp(dur_f, avg_hr_f, rest_hr, max_hr)
        if trimp == 0:
            continue
        hrr_pct = (avg_hr_f - rest_hr) / (max_hr - rest_hr)
        hrr_pct = max(0.0, min(1.0, hrr_pct))
        if trimp < 50:
            band = "light"
        elif trimp < 100:
            band = "moderate"
        elif trimp < 150:
            band = "hard"
        else:
            band = "red-line"
        out.append({
            "date":          s["date"],
            "kind":          s.get("session_kind", "other"),
            "trimp":         trimp,
            "intensity_pct": round(hrr_pct * 100, 1),
            "load_band":     band,
            "hr_zone_label": _hr_zone_label_for_hrr_pct(hrr_pct),
        })
    out.sort(key=lambda e: e["date"])
    return out


def training_load_summary(trimps: list[dict], today_d: date) -> dict:
    """CTL (chronic, 42d EWMA), ATL (acute, 7d EWMA), TSB (form = CTL−ATL).

    Standard TrainingPeaks formulas. CTL ≈ fitness, ATL ≈ fatigue, TSB
    positive = peaked, negative = under load. Computed by walking each
    day from the earliest TRIMP to today and decaying yesterday's value.
    Returns the values *as of today_d*.
    """
    if not trimps:
        return {"ctl": None, "atl": None, "tsb": None, "trend_7d": None}
    # Convert to a date→trimp dict (sum if multiple sessions same day).
    by_date: dict[date, float] = {}
    for t in trimps:
        d = _parse_iso_date(t.get("date"))
        if d is None:
            continue
        by_date[d] = by_date.get(d, 0.0) + t["trimp"]
    if not by_date:
        return {"ctl": None, "atl": None, "tsb": None, "trend_7d": None}
    start = min(by_date.keys())
    ctl_alpha = 1.0 / 42.0  # ~time constant 42d
    atl_alpha = 1.0 / 7.0
    ctl = atl = 0.0
    history: list[tuple[date, float, float]] = []
    cur = start
    while cur <= today_d:
        load = by_date.get(cur, 0.0)
        ctl = ctl + ctl_alpha * (load - ctl)
        atl = atl + atl_alpha * (load - atl)
        history.append((cur, ctl, atl))
        cur += timedelta(days=1)
    today_ctl, today_atl = ctl, atl
    week_ago_ctl = next(
        (h[1] for h in reversed(history)
         if h[0] <= today_d - timedelta(days=7)),
        today_ctl
    )
    return {
        "ctl":      round(today_ctl, 1),
        "atl":      round(today_atl, 1),
        "tsb":      round(today_ctl - today_atl, 1),
        "trend_7d": round(today_ctl - week_ago_ctl, 1),
    }


def cardio_hr_zones(monthly_sessions: list[dict],
                    today_d: date,
                    max_hr: float | None,
                    rest_hr: float | None,
                    window_days: int = 28) -> dict:
    """Polarized-vs-pyramidal HR distribution across cardio sessions.

    Without per-second HR data we can't compute true time-in-zone, so we
    place each session entirely in the zone its avg_hr falls into.
    Coarse but useful for trend (has the user been doing too much Z3
    grey-zone work?). Returns ``{z1..z5: minutes, total_minutes,
    polarized_pct, pyramidal_pct, threshold_pct}``. Also includes
    ``z2_by_activity`` so short swims, runs, rides, and walk/hike time can
    be interpreted separately even when they share the same HR zone.
    """
    if not max_hr or not rest_hr or max_hr <= rest_hr:
        return {}
    cutoff = today_d - timedelta(days=window_days)
    zone_min: dict[str, float] = {z[0]: 0.0 for z in HR_ZONES_PCT}
    z2_by_activity: dict[str, float] = {}
    total = 0.0
    for s in monthly_sessions:
        if s.get("session_kind") != "cardio":
            continue
        d = _parse_iso_date(s.get("date"))
        if d is None:
            continue
        if d < cutoff:
            continue
        avg_hr = s.get("avg_hr")
        dur = s.get("duration_min")
        if not avg_hr or not dur:
            continue
        dur_f = float(dur)
        hrr = (float(avg_hr) - rest_hr) / (max_hr - rest_hr)
        hrr = max(0.0, min(1.0, hrr))
        for label, lo, hi in HR_ZONES_PCT:
            if hrr < hi or label == "z5":
                zone_min[label] += dur_f
                if label == "z2":
                    bucket = _cardio_activity_bucket(s.get("exercise_first"))
                    z2_by_activity[bucket] = z2_by_activity.get(bucket, 0.0) + dur_f
                total += dur_f
                break
    if total <= 0:
        return {}
    z1 = round(zone_min["z1"], 1)
    z2 = round(zone_min["z2"], 1)
    z3 = round(zone_min["z3"], 1)
    z4 = round(zone_min["z4"], 1)
    z5 = round(zone_min["z5"], 1)
    return {
        "window_days":    window_days,
        "total_minutes":  round(total, 1),
        "z1": z1, "z2": z2, "z3": z3, "z4": z4, "z5": z5,
        "z2_by_activity": {
            k: round(v, 1) for k, v in sorted(z2_by_activity.items())
        },
        "z2_pct": round((z2 / total) * 100, 1),
        "z3_pct": round((z3 / total) * 100, 1),
        "z4_z5_pct": round(((z4 + z5) / total) * 100, 1),
    }


def auto_deload_candidates(monthly_sessions: list[dict],
                           deloads_logged: list[str],
                           today_d: date,
                           window_weeks: int = 8) -> list[str]:
    """Detect strength-session weeks where volume + HR both dropped enough
    to look like a deload that the user didn't mark.

    Heuristic per week:
    - Median session volume ≤ 0.65 × prior 4-week median.
    - AND median session avg_hr ≤ prior_4wk_median - 8 bpm.
    - AND not already in ``deloads_logged``.

    Conservative — designed to surface candidates the user likely forgot
    to flag, not to second-guess intent.
    """
    cutoff = today_d - timedelta(days=window_weeks * 7)
    strength = []
    for s in monthly_sessions:
        if s.get("session_kind") != "strength":
            continue
        d = _parse_iso_date(s.get("date"))
        if d is None:
            continue
        if d < cutoff:
            continue
        vol = s.get("volume")
        hr = s.get("avg_hr")
        if not vol or not hr:
            continue
        strength.append((d, float(vol), float(hr)))
    if len(strength) < 6:
        return []
    strength.sort(key=lambda p: p[0])

    def median(xs):
        s = sorted(xs)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    candidates: list[str] = []
    for i, (d, vol, hr) in enumerate(strength):
        prior = [p for p in strength[:i]
                 if (d - p[0]).days <= 28 and (d - p[0]).days > 0]
        if len(prior) < 4:
            continue
        prior_vol = median([p[1] for p in prior])
        prior_hr = median([p[2] for p in prior])
        if prior_vol <= 0:
            continue
        date_str_form = d.strftime("%Y-%m-%d")
        if date_str_form in deloads_logged:
            continue
        if vol <= 0.65 * prior_vol and hr <= prior_hr - 8:
            candidates.append(date_str_form)
    return candidates


def compute_hr_recovery_summary(health_all: list[dict],
                                 today_d: date) -> dict | None:
    """Heart-Rate Recovery 1-min summary for the Cardiorespiratory card.

    Apple Health exposes per-day HRR values in ``hr_recovery_1min``. This
    helper rolls them up over the last 28 days and resolves the value to
    the Cole 1999 / Cleveland Clinic mortality bands (<12 = abnormal,
    12-15 borderline, 15-25 normal, ≥25 excellent). Returns ``None`` when
    no HRR readings exist in the window so ``_compact`` drops the key.

    Already wired as one of the recovery_score drivers (`hr_recovery_1min`
    in `health.py`). This standalone summary is what the Trajectory tab
    visualizes as a first-class metric.
    """
    from .constants import HRR_1MIN_NORMS  # local import to avoid cycle
    vals_28 = _values_in_window(health_all, "hr_recovery_1min", today_d, 28)
    if not vals_28:
        return None
    mean_28 = sum(vals_28) / len(vals_28)
    vals_7 = _values_in_window(health_all, "hr_recovery_1min", today_d, 7)
    mean_7 = (sum(vals_7) / len(vals_7)) if vals_7 else None
    latest = max(vals_28)  # most recent isn't trivially extractable; use peak
    # Band classification on the 28-day mean.
    if mean_28 < HRR_1MIN_NORMS["abnormal_below"]:
        band, label = "warn", "abnormal"
    elif mean_28 < HRR_1MIN_NORMS["borderline"]:
        band, label = "amber", "borderline"
    elif mean_28 < HRR_1MIN_NORMS["normal"]:
        band, label = "good", "normal"
    elif mean_28 < HRR_1MIN_NORMS["excellent"]:
        band, label = "good", "fit"
    else:
        band, label = "good", "excellent"
    return {
        "mean_28d":   round(mean_28, 1),
        "mean_7d":    round(mean_7, 1) if mean_7 is not None else None,
        "n_readings": len(vals_28),
        "band":       band,
        "label":      label,
        "norms":      HRR_1MIN_NORMS,
    }


def compute_acwr(trimps: list[dict], today_d: date) -> dict | None:
    """Training-load progression: ACWR (legacy) + week-over-week change
    (the cleaner replacement).

    The strict Gabbett 2016 ACWR 0.8–1.3 sweet-spot was substantially
    discredited by Impellizzeri et al. 2020 (IJSPP) and Lolli et al. 2020
    on statistical grounds (the ratio is mathematically coupled to the
    chronic-window denominator and adds spurious variance). What
    survived: the underlying intuition that **weekly training stress
    should not jump >10% week-over-week** is a defensible guardrail.

    We compute both so the renderer can show the WoW change as the
    primary signal and the ACWR ratio as a coarse trend indicator with a
    caveat.

    Returns ``None`` when either window is empty.
    """
    from .constants import ACWR_BANDS
    if not trimps:
        return None
    by_date: dict[date, float] = {}
    for t in trimps:
        d = _parse_iso_date(t.get("date"))
        if d is None:
            continue
        by_date[d] = by_date.get(d, 0.0) + float(t.get("trimp") or 0.0)

    acute = sum(v for d, v in by_date.items()
                if today_d - timedelta(days=7) < d <= today_d)
    prior_week = sum(v for d, v in by_date.items()
                     if today_d - timedelta(days=14) < d <= today_d - timedelta(days=7))
    chronic_total = sum(v for d, v in by_date.items()
                        if today_d - timedelta(days=28) < d <= today_d)
    chronic_weekly = chronic_total / 4.0
    if chronic_weekly <= 0:
        return None

    ratio = acute / chronic_weekly
    if ratio < ACWR_BANDS["detraining_below"]:
        band, label = "amber", "detraining"
    elif ratio <= ACWR_BANDS["sweet_spot_hi"]:
        band, label = "good", "in band"
    elif ratio <= ACWR_BANDS["caution_hi"]:
        band, label = "amber", "ramping high"
    else:
        band, label = "warn", "steep ramp"

    # Week-over-week percent change. The classic "10% rule" — what
    # survived ACWR's debunking. Treat ±10% as the green band, ±25% as
    # caution, anything beyond as high.
    wow_change_pct = None
    wow_band = None
    wow_label = None
    if prior_week > 0:
        wow_change_pct = ((acute - prior_week) / prior_week) * 100.0
        abs_pct = abs(wow_change_pct)
        if abs_pct <= 10.0:
            wow_band, wow_label = "good", "stable progression"
        elif abs_pct <= 25.0:
            wow_band, wow_label = "amber", "ramping fast" if wow_change_pct > 0 else "tapering"
        else:
            wow_band, wow_label = "warn", "ramp too steep" if wow_change_pct > 0 else "sharp drop"
    elif acute > 0:
        # Came back from a zero week — flag as fresh ramp.
        wow_band, wow_label = "amber", "returning from rest"

    return {
        "ratio":           round(ratio, 2),
        "acute_7d":        round(acute, 0),
        "prior_week":      round(prior_week, 0),
        "chronic_28d_avg": round(chronic_weekly, 0),
        "wow_change_pct":  round(wow_change_pct, 1) if wow_change_pct is not None else None,
        "wow_band":        wow_band,
        "wow_label":       wow_label,
        "band":            band,
        "label":           label,
        "bands":           ACWR_BANDS,
    }


def compute_movement_consistency_days(health_all: list[dict],
                                       today_d: date,
                                       threshold_min: int = 30) -> dict | None:
    """Behavioral consistency: days hitting Apple's exercise-minute threshold.

    We don't ingest a steps column — Apple's Activity ring exposes
    ``exercise_min`` instead (brisk-activity minutes). Threshold defaults
    to 30 (the Apple Move ring default; lines up with the WHO ≥150 min/wk
    recommendation as 5 days of 30 min). Returns counts for the current
    ISO week and the trailing 28 days.

    The Paluch 2022 / Saint-Maurice 2023 finding that *days at threshold*
    is dose-responsive even when the weekly mean is unchanged applies the
    same way here: one high-activity day still moves the mortality needle.
    Returns ``None`` when no exercise-minute data exists in the 28-day
    window (HL trackers, or no Watch wear).
    """
    iso = today_d.isocalendar()
    monday = today_d - timedelta(days=iso.weekday - 1)
    in_window = []
    in_week = []
    for e in health_all:
        d = _parse_iso_date(e.get("date"))
        if d is None:
            continue
        if today_d - timedelta(days=28) < d <= today_d:
            in_window.append(e)
        if monday <= d <= today_d:
            in_week.append(e)
    any_data = any(
        (e.get("exercise_min") is not None) for e in in_window
    )
    if not any_data:
        return None
    days_this_wk = sum(
        1 for e in in_week
        if (e.get("exercise_min") or 0) >= threshold_min
    )
    days_28d = sum(
        1 for e in in_window
        if (e.get("exercise_min") or 0) >= threshold_min
    )
    return {
        "threshold_min":  threshold_min,
        "days_this_wk":   days_this_wk,
        "days_28d":       days_28d,
        "target_per_wk":  5,
    }


def daily_activity_28d(health_all: list[dict],
                       workout_sessions_all: list[dict],
                       today_d: date) -> dict:
    """28-day rollup of all-day activity beyond logged workouts (NEAT).

    Folds two complementary signals:

    - Apple Activity ``exercise_min`` (XML only — Apple's "brisk activity"
      heuristic). Daily values from ``health_metrics`` are averaged across
      the last 28 days. HL trackers don't surface this, so the value falls
      through to None.
    - Walking sessions on ``Workout Sessions`` (apple_type == "Walking").
      Both XML and HL importers write these. Distance and minutes are
      summed; the importer's ``incidental walk`` flag (set on Walking
      workouts under 15 min) is exposed as a separate count so the LLM
      can distinguish a single 60-min city walk from twelve 5-min chore
      walks.

    The ``assessment`` band ("low" / "moderate" / "high") is the field the
    coach actually consumes. Thresholds line up with Apple's 30 min/day
    Exercise Ring guidance: <15 min/day = low, 15-45 = moderate, ≥45 =
    high. When ``exercise_min_daily_avg`` is missing (HL), the band falls
    back to walking_minutes_28d / 28 as a NEAT proxy — daily walks are
    the dominant non-exercise movement signal anyway.
    """
    cutoff = today_d - timedelta(days=28)

    # exercise_min daily mean across the last 28 days (XML only).
    exercise_min_vals = _values_in_window(health_all, "exercise_min", today_d, 28)
    exercise_min_daily_avg = (
        round(sum(exercise_min_vals) / len(exercise_min_vals), 1)
        if exercise_min_vals else None
    )

    # Walking workouts within the 28d window (both sources surface these).
    walking_workouts = []
    for s in workout_sessions_all:
        if s.get("apple_type") != "Walking":
            continue
        d = _parse_iso_date(s.get("date"))
        if d is None:
            continue
        if d < cutoff or d > today_d:
            continue
        walking_workouts.append(s)

    walking_minutes_28d = round(
        sum(float(w.get("duration_min") or 0) for w in walking_workouts), 1)
    walking_distance_km_28d = round(
        sum(float(w.get("distance_km") or 0) for w in walking_workouts), 2)
    incidental_walks = sum(
        1 for w in walking_workouts
        # Post-2026-05 schema: typed ``incidental`` column. Legacy
        # rows pre-migration carry the marker in ``notes``; fall back
        # so the count is stable across the schema flip.
        if w.get("incidental") is True
        or (w.get("notes") or "").startswith("incidental"))

    # Assessment basis: prefer Apple exercise_min when present, else use
    # walking minutes per day as a NEAT proxy. HL trackers still get a
    # band so the daily-activity gate in the coach doesn't quietly fall
    # through on <OtherPerson>-style sources.
    if exercise_min_daily_avg is not None:
        basis = exercise_min_daily_avg
    elif walking_minutes_28d > 0:
        basis = walking_minutes_28d / 28.0
    else:
        basis = None

    if basis is None:
        assessment = None
    elif basis < 15:
        assessment = "low"
    elif basis < 45:
        assessment = "moderate"
    else:
        assessment = "high"

    return {
        "exercise_min_daily_avg": exercise_min_daily_avg,
        "walking_workouts_count": len(walking_workouts),
        "walking_minutes_28d": walking_minutes_28d,
        "walking_distance_km_28d": walking_distance_km_28d,
        "incidental_walks_count": incidental_walks,
        "assessment": assessment,
    }
