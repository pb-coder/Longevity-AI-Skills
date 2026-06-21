"""Swim analytics for the coach.

Consumes the per-swim and per-lap CSVs (``<person>/data/swimming/``) and
returns a structured swim_summary block that the coach prompt threads
into its swim section. Returns ``None`` when there are no swims in the
28-day window — ``_compact`` then drops the key from the JSON output
and the prompt's swim section stays silent.

Public surface:

- ``recent_swim_workouts(swim_workouts, today_d, days)`` — windowed list.
- ``pace_per_100m(distance_km, duration_min)`` — sec/100m or None.
- ``swim_summary(workouts, laps, today_d, profile, max_hr)`` — the full
  block (totals + trends + CSS classification + retest prompt).
- ``detect_css_test(workouts)`` — pull a CSS value out of a 400m + 200m
  TT pair logged within the same 30-min window. The coach uses this to
  prompt the user to write CSS to profile; we never auto-write.
"""
from __future__ import annotations

from datetime import date, timedelta


from .parsing import _parse_iso_date


# Stroke labels that indicate butterfly / kickboard misclassification
# candidates. The dominant stroke is almost always Freestyle for our
# users; isolated Butterfly / Kickboard / Mixed laps in a Freestyle
# session are usually watch confusion, not real strokes.
_DOMINANT_OUTLIER_THRESHOLD = 0.85


def recent_swim_workouts(swim_workouts: list[dict],
                         today_d: date,
                         days: int = 28) -> list[dict]:
    """Filter swim_workouts to the last ``days`` (inclusive of today)."""
    if not swim_workouts:
        return []
    cutoff = today_d - timedelta(days=max(days - 1, 0))
    out = []
    for w in swim_workouts:
        d = _parse_iso_date(w.get("date"))
        if d is None:
            continue
        if d < cutoff or d > today_d:
            continue
        out.append(w)
    return out


PACE_MIN_SEC_PER_100M = 20.0   # faster than world-record territory — unit error
PACE_MAX_SEC_PER_100M = 600.0  # 10 min/100m — implausibly slow for a swim workout


def pace_per_100m(distance_km: float | None,
                  duration_min: float | None) -> float | None:
    """Return seconds per 100m, or None when either input is missing/zero or
    the computed pace falls outside the plausible band [20, 600] sec/100m.

    Values below 20 sec/100m indicate a unit error (e.g. metres stored as km).
    Values above 600 sec/100m indicate data corruption or a near-stationary
    reading that should not be treated as a swim pace.
    """
    if not distance_km or not duration_min:
        return None
    if distance_km <= 0 or duration_min <= 0:
        return None
    # distance_km × 10 = number of 100m blocks. duration_min × 60 = sec.
    pace = (duration_min * 60.0) / (distance_km * 10.0)
    if pace < PACE_MIN_SEC_PER_100M or pace > PACE_MAX_SEC_PER_100M:
        return None
    return round(pace, 1)


def _slope_per_week(points: list[tuple[date, float]]) -> float | None:
    """Simple linear-regression slope (units per day × 7) from (date, value).

    Returns None when fewer than 3 points or zero variance in dates.
    """
    if len(points) < 3:
        return None
    base = points[0][0]
    xs = [(p[0] - base).days for p in points]
    ys = [p[1] for p in points]
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    slope_per_day = (n * sxy - sx * sy) / denom
    return round(slope_per_day * 7.0, 3)


def _classify_css_zone(pace_sec_per_100m: float | None,
                       css: float | None) -> str | None:
    """CSS-relative zone label.

    Lower sec/100m = faster. CSS is the threshold pace; recovery sits
    above it (slower), VO2 sits below (faster).
    """
    if pace_sec_per_100m is None or css is None or css <= 0:
        return None
    ratio = pace_sec_per_100m / css
    if ratio > 1.10:
        return "Recovery"
    if ratio > 1.00:
        return "Aerobic"
    if ratio > 0.90:
        return "Threshold"
    return "VO2"


def _stroke_outliers(laps: list[dict]) -> dict:
    """Per-session count of laps whose stroke != session-modal stroke.

    Only meaningful when the session has a strong dominant stroke
    (≥ 85% of laps). Otherwise — true mixed-stroke session — return
    empty so we don't surface noise.
    """
    if not laps:
        return {"modal_stroke": None, "outlier_laps": []}
    counts: dict[str, int] = {}
    for lap in laps:
        s = lap.get("stroke_decoded")
        if not s:
            continue
        counts[s] = counts.get(s, 0) + 1
    total = sum(counts.values())
    if total == 0:
        return {"modal_stroke": None, "outlier_laps": []}
    modal, modal_n = max(counts.items(), key=lambda kv: kv[1])
    if modal_n / total < _DOMINANT_OUTLIER_THRESHOLD:
        return {"modal_stroke": modal, "outlier_laps": []}
    outliers = [
        {
            "lap_num": lap.get("lap_num"),
            "stroke": lap.get("stroke_decoded"),
            "swolf":  lap.get("swolf"),
        }
        for lap in laps
        if lap.get("stroke_decoded") and lap.get("stroke_decoded") != modal
    ]
    return {"modal_stroke": modal, "outlier_laps": outliers}


def detect_css_test(swim_workouts: list[dict]) -> dict | None:
    """Find a 400m + 200m TT pair within 30 minutes on the same date.

    Returns ``{"date": <ISO>, "css_sec_per_100m": <float>, "t400_sec":
    ..., "t200_sec": ...}`` for the first hit, or None. Distance
    tolerance ±5%. Doesn't auto-write CSS — the coach uses this to
    prompt the user.

    CSS = (t400 - t200) / 2  (in sec per 100m equivalent — the formula
    sits on per-100m units once you note that 400m - 200m = 200m, so
    dividing the time delta by 2 yields seconds per 100m).
    """
    if not swim_workouts:
        return None
    by_date: dict[str, list[dict]] = {}
    for w in swim_workouts:
        d = w.get("date")
        if not d:
            continue
        by_date.setdefault(d, []).append(w)

    for d in sorted(by_date.keys(), reverse=True):
        candidates = by_date[d]
        # Look for a 400m + 200m pair (each ±5%).
        c400 = [c for c in candidates
                if c.get("distance_km")
                and 0.38 <= float(c["distance_km"]) <= 0.42]
        c200 = [c for c in candidates
                if c.get("distance_km")
                and 0.19 <= float(c["distance_km"]) <= 0.21]
        if not c400 or not c200:
            continue
        for w400 in c400:
            for w200 in c200:
                # Same-day, within 30 minutes by start time.
                s400 = (w400.get("start") or "")
                s200 = (w200.get("start") or "")
                if not s400 or not s200:
                    continue
                try:
                    h4, m4 = s400.split(":")[:2]
                    h2, m2 = s200.split(":")[:2]
                    minutes_apart = abs(
                        (int(h4) * 60 + int(m4)) - (int(h2) * 60 + int(m2))
                    )
                except ValueError:
                    continue
                if minutes_apart > 30:
                    continue
                # Need durations.
                d400 = w400.get("duration_min")
                d200 = w200.get("duration_min")
                if not d400 or not d200:
                    continue
                t400_sec = float(d400) * 60.0
                t200_sec = float(d200) * 60.0
                # CSS = (t400 - t200) / 2
                css = (t400_sec - t200_sec) / 2.0
                if css <= 0:
                    continue
                return {
                    "date": d,
                    "css_sec_per_100m": round(css, 1),
                    "t400_sec": round(t400_sec, 1),
                    "t200_sec": round(t200_sec, 1),
                }
    return None


def _window_aggregates(window: list[dict]) -> dict:
    """Compute (n_sessions, total_distance_km, total_minutes, avg_pace,
    avg_spl, avg_swolf) for a windowed list of swims. Empty window → all
    None (sessions = 0). Pace uses sum(time)/sum(distance), not the
    mean-of-pace, so a short slow swim doesn't drag the average.
    """
    if not window:
        return {
            "n_sessions":     0,
            "total_distance_km": 0.0,
            "total_minutes":  0.0,
            "avg_pace_sec_per_100m": None,
            "avg_spl":        None,
            "avg_swolf":      None,
        }
    total_dist = round(sum(float(w.get("distance_km") or 0) for w in window), 2)
    total_min = round(sum(float(w.get("duration_min") or 0) for w in window), 1)

    pace_dist = pace_time = 0.0
    for w in window:
        d = w.get("distance_km")
        m = w.get("duration_min")
        if d and m and float(d) > 0 and float(m) > 0:
            pace_dist += float(d)
            pace_time += float(m)
    avg_pace = pace_per_100m(pace_dist, pace_time)

    spl_vals = [float(w["spl"]) for w in window if w.get("spl")]
    swolf_vals = [float(w["avg_swolf"]) for w in window if w.get("avg_swolf")]
    return {
        "n_sessions":             len(window),
        "total_distance_km":      total_dist,
        "total_minutes":          total_min,
        "avg_pace_sec_per_100m":  avg_pace,
        "avg_spl":                round(sum(spl_vals) / len(spl_vals), 1) if spl_vals else None,
        "avg_swolf":              round(sum(swolf_vals) / len(swolf_vals), 1) if swolf_vals else None,
    }


def _delta(curr: float | None, prev: float | None) -> float | None:
    """Return curr - prev rounded, or None if either side is missing."""
    if curr is None or prev is None:
        return None
    return round(curr - prev, 2)


def _best_pace(window: list[dict]) -> float | None:
    """Best (lowest) per-session pace_per_100m in the window, or None."""
    paces = []
    for w in window:
        p = pace_per_100m(w.get("distance_km"), w.get("duration_min"))
        if p is not None:
            paces.append(p)
    return min(paces) if paces else None


def _best_swolf(window: list[dict]) -> float | None:
    """Best (lowest) per-session avg_swolf in the window, or None."""
    swolfs = [float(w["avg_swolf"]) for w in window if w.get("avg_swolf")]
    return round(min(swolfs), 1) if swolfs else None


def _improvement_verdict(curr: dict, prev: dict) -> str:
    """Classify 14d-vs-prior-14d movement into a single verdict token.

    Tokens (LLM-friendly):
      - ``insufficient_data`` — fewer than 2 sessions in either window
      - ``improving``         — at least 2 of {pace, SPL, SWOLF} moved
                                in the improving direction (lower = better
                                for all three); pace must be one of them
      - ``regressing``        — at least 2 of {pace, SPL, SWOLF} got worse;
                                pace must be one of them
      - ``mixed``             — non-trivial movement in both directions
      - ``flat``              — no metric moved more than ~1%
    """
    if curr["n_sessions"] < 2 or prev["n_sessions"] < 2:
        return "insufficient_data"

    deltas = {
        "pace":  _delta(curr["avg_pace_sec_per_100m"], prev["avg_pace_sec_per_100m"]),
        "spl":   _delta(curr["avg_spl"], prev["avg_spl"]),
        "swolf": _delta(curr["avg_swolf"], prev["avg_swolf"]),
    }

    # Significance threshold: ~1 sec/100m for pace, ~0.3 strokes for SPL,
    # ~0.5 for SWOLF. Below these floors, treat as noise, not movement.
    thresholds = {"pace": 1.0, "spl": 0.3, "swolf": 0.5}
    significant = {
        k: v for k, v in deltas.items()
        if v is not None and abs(v) >= thresholds[k]
    }

    if not significant:
        return "flat"

    improving = {k for k, v in significant.items() if v < 0}
    regressing = {k for k, v in significant.items() if v > 0}

    if len(improving) >= 2 and "pace" in improving:
        return "improving"
    if len(regressing) >= 2 and "pace" in regressing:
        return "regressing"
    if improving and regressing:
        return "mixed"
    if improving:
        return "improving" if "pace" in improving else "mixed"
    return "regressing" if "pace" in regressing else "mixed"


def swim_summary(swim_workouts: list[dict],
                 swim_laps: list[dict],
                 today_d: date,
                 profile: dict,
                 max_hr: float | None) -> dict | None:
    """Aggregated swim block. Returns None when no swims in 28-day window.

    Output shape (compact, LLM-friendly):
      window_days, sessions, total_distance_km, total_minutes,
      total_laps, avg_pace_sec_per_100m, avg_spl, avg_swolf,
      spl_trend_4w_per_week, swolf_trend_8w_per_week,
      window_14d: {n_sessions, total_distance_km, total_minutes,
        avg_pace_sec_per_100m, avg_spl, avg_swolf,
        delta_vs_prior_14d: {pace, spl, swolf},
        best_pace_sec_per_100m, best_swolf, prior_best_pace,
        prior_best_swolf, pace_pr, swolf_pr (bool flags),
        improvement_verdict},
      sessions_detail (per-session: date, distance_km, duration_min,
        pace, css_zone, modal_stroke, outlier_count),
      stroke_outliers (sessions with at least one outlier lap),
      css_zone_distribution (count by zone, when CSS set),
      css (sec/100m + set_at, or None),
      css_retest_due (bool),
      css_test_detected (most recent inferred CSS, or None).
    """
    recent = recent_swim_workouts(swim_workouts, today_d, days=28)
    if not recent:
        return None

    css = profile.get("swim_css_sec_per_100m")
    css_set_at = profile.get("swim_css_set_at")

    sessions = len(recent)
    total_dist = round(sum(float(w.get("distance_km") or 0) for w in recent), 2)
    total_min = round(sum(float(w.get("duration_min") or 0) for w in recent), 1)
    total_laps = sum(int(w.get("laps") or 0) for w in recent)

    # Workout-weighted avg pace per 100m: sum(time)/sum(distance).
    # Skip sessions missing either field rather than imputing.
    total_dist_for_pace = 0.0
    total_time_for_pace = 0.0
    for w in recent:
        d = w.get("distance_km")
        m = w.get("duration_min")
        if d and m and float(d) > 0 and float(m) > 0:
            total_dist_for_pace += float(d)
            total_time_for_pace += float(m)
    avg_pace = pace_per_100m(total_dist_for_pace, total_time_for_pace)

    spl_vals = [float(w["spl"]) for w in recent if w.get("spl")]
    swolf_vals = [float(w["avg_swolf"]) for w in recent if w.get("avg_swolf")]
    avg_spl = round(sum(spl_vals) / len(spl_vals), 1) if spl_vals else None
    avg_swolf = round(sum(swolf_vals) / len(swolf_vals), 1) if swolf_vals else None

    # 4-week SPL trend / 8-week SWOLF trend (units / week).
    cutoff_4w = today_d - timedelta(days=27)
    cutoff_8w = today_d - timedelta(days=55)
    spl_pts: list[tuple[date, float]] = []
    swolf_pts: list[tuple[date, float]] = []
    for w in swim_workouts:
        d_w = _parse_iso_date(w.get("date"))
        if d_w is None or d_w > today_d:
            continue
        if d_w >= cutoff_4w and w.get("spl"):
            spl_pts.append((d_w, float(w["spl"])))
        if d_w >= cutoff_8w and w.get("avg_swolf"):
            swolf_pts.append((d_w, float(w["avg_swolf"])))
    spl_trend = _slope_per_week(sorted(spl_pts))
    swolf_trend = _slope_per_week(sorted(swolf_pts))

    # Per-session detail + stroke outliers.
    laps_by_session: dict[tuple, list[dict]] = {}
    for lap in swim_laps:
        key = (lap.get("date"), lap.get("workout_start"))
        laps_by_session.setdefault(key, []).append(lap)

    sessions_detail = []
    css_zone_counts: dict[str, int] = {}
    outlier_sessions = []
    for w in recent:
        sess_pace = pace_per_100m(w.get("distance_km"), w.get("duration_min"))
        zone = _classify_css_zone(sess_pace, css) if css else None
        if zone:
            css_zone_counts[zone] = css_zone_counts.get(zone, 0) + 1
        sess_laps = laps_by_session.get(
            (w.get("date"), w.get("start")), []
        )
        outlier_info = _stroke_outliers(sess_laps)
        sessions_detail.append({
            "date":          w.get("date"),
            "start":         w.get("start"),
            "distance_km":   w.get("distance_km"),
            "duration_min":  w.get("duration_min"),
            "pace_sec_per_100m": sess_pace,
            "spl":           w.get("spl"),
            "avg_swolf":     w.get("avg_swolf"),
            "stroke_mix":    w.get("stroke_mix"),
            "location":      w.get("location"),
            "css_zone":      zone,
            "modal_stroke":  outlier_info["modal_stroke"],
            "outlier_count": len(outlier_info["outlier_laps"]),
        })
        if outlier_info["outlier_laps"]:
            outlier_sessions.append({
                "date":          w.get("date"),
                "modal_stroke":  outlier_info["modal_stroke"],
                "outlier_laps":  outlier_info["outlier_laps"],
            })

    # CSS retest prompt: True when CSS missing OR > 56 days old AND
    # user has at least 4 swims in the past 28 days.
    retest_due = False
    if sessions >= 4:
        if css_set_at is None:
            retest_due = True
        else:
            set_d = _parse_iso_date(css_set_at)
            if set_d is None or (today_d - set_d).days > 56:
                retest_due = True

    css_test_detected = detect_css_test(swim_workouts)

    # ---- 14d window: "am I getting better?" headline. ----
    # Compared against the prior 14d (days 14-28 ago) for a delta-driven
    # improvement verdict the renderer + LLM both consume. Falls back to
    # insufficient_data when either window has < 2 swims.
    window_14d = recent_swim_workouts(swim_workouts, today_d, days=14)
    prior_14d_start = today_d - timedelta(days=27)
    prior_14d_end = today_d - timedelta(days=14)
    prior_14d = []
    for w in swim_workouts:
        d_w = _parse_iso_date(w.get("date"))
        if d_w is None or d_w > today_d:
            continue
        if d_w < prior_14d_start or d_w > prior_14d_end:
            continue
        prior_14d.append(w)

    curr_agg = _window_aggregates(window_14d)
    prev_agg = _window_aggregates(prior_14d)
    verdict = _improvement_verdict(curr_agg, prev_agg)

    best_pace_curr = _best_pace(window_14d)
    best_pace_prev = _best_pace(prior_14d)
    best_swolf_curr = _best_swolf(window_14d)
    best_swolf_prev = _best_swolf(prior_14d)

    window_14d_block = {
        "n_sessions":              curr_agg["n_sessions"],
        "total_distance_km":       curr_agg["total_distance_km"],
        "total_minutes":           curr_agg["total_minutes"],
        "avg_pace_sec_per_100m":   curr_agg["avg_pace_sec_per_100m"],
        "avg_spl":                 curr_agg["avg_spl"],
        "avg_swolf":               curr_agg["avg_swolf"],
        "delta_vs_prior_14d": {
            "pace":  _delta(curr_agg["avg_pace_sec_per_100m"],
                            prev_agg["avg_pace_sec_per_100m"]),
            "spl":   _delta(curr_agg["avg_spl"], prev_agg["avg_spl"]),
            "swolf": _delta(curr_agg["avg_swolf"], prev_agg["avg_swolf"]),
        },
        "best_pace_sec_per_100m":  best_pace_curr,
        "best_swolf":              best_swolf_curr,
        "prior_best_pace":         best_pace_prev,
        "prior_best_swolf":        best_swolf_prev,
        "pace_pr":  bool(
            best_pace_curr is not None
            and best_pace_prev is not None
            and best_pace_curr < best_pace_prev
        ),
        "swolf_pr": bool(
            best_swolf_curr is not None
            and best_swolf_prev is not None
            and best_swolf_curr < best_swolf_prev
        ),
        "improvement_verdict":     verdict,
    }

    return {
        "window_days":              28,
        "window_14d":               window_14d_block,
        "sessions":                 sessions,
        "total_distance_km":        total_dist,
        "total_minutes":            total_min,
        "total_laps":               total_laps if total_laps else None,
        "avg_pace_sec_per_100m":    avg_pace,
        "avg_spl":                  avg_spl,
        "avg_swolf":                avg_swolf,
        "spl_trend_4w_per_week":    spl_trend,
        "swolf_trend_8w_per_week":  swolf_trend,
        "sessions_detail":          sessions_detail,
        "stroke_outliers":          outlier_sessions or None,
        "css_zone_distribution":    css_zone_counts or None,
        "css": (
            {"sec_per_100m": css, "set_at": css_set_at} if css else None
        ),
        "css_retest_due":           retest_due,
        "css_missing_nudge":        (
            "Swims are logged but no CSS pace is set in profile.csv; log a 400m + 200m CSS test so zones are not guessed."
            if not css else None
        ),
        "css_test_detected":        css_test_detected,
    }
