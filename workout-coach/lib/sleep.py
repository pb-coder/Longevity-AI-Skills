"""Sleep analytics for the coach.

Consumes the per-night CSVs at ``<person>/data/sleep/YYYY.MM.nights.csv``
and returns a structured ``sleep_summary`` block that the coach prompt
threads into its sleep section. Returns ``None`` when there are no
nights in the 28-day window — ``_compact`` then drops the key from the
JSON output and the prompt's sleep section stays silent (HL trackers
or XML trackers with no recent sleep data).

Public surface:

- ``recent_sleep_nights(nights, today_d, days)`` — windowed list.
- ``sleep_summary(nights, today_d)`` — the full block (stage means,
  efficiency mean + trend, fragmentation, schedule consistency,
  outlier nights).
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Sibling lib/ on sys.path so this module is importable on its own.
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from parsing import _parse_iso_date


# Clinical / consumer-grade Sleep Efficiency thresholds. >85% is the
# textbook "healthy adult" anchor; <80% is the cutoff that sleep clinics
# flag as disturbed in screening tools (PSQI, ISI). Used to surface
# outlier nights without making a per-driver recovery-score weighting
# decision here — that lives in health.py once we have 4-6w of data.
EFFICIENCY_HEALTHY_MIN_PCT = 85.0
EFFICIENCY_DISTURBED_MAX_PCT = 80.0
WASO_OUTLIER_MIN_H = 1.0


def recent_sleep_nights(nights: list[dict], today_d: date,
                        days: int = 28) -> list[dict]:
    """Filter ``nights`` to the last ``days`` (inclusive of today)."""
    if not nights:
        return []
    cutoff = today_d - timedelta(days=days)
    out = []
    for n in nights:
        d = _parse_iso_date(n.get("date"))
        if d is None:
            continue
        if d < cutoff or d > today_d:
            continue
        out.append(n)
    return out


def _mean(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def _stdev(vals: list[float]) -> float | None:
    """Population stdev (matches sleep consistency in health.py)."""
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    var = sum((v - m) ** 2 for v in vals) / len(vals)
    return round(var ** 0.5, 2)


def _slope_per_week(points: list[tuple[date, float]]) -> float | None:
    """Linear-regression slope in units per week. None if <3 points or
    zero variance in dates. Mirrors the swim.py helper to keep the
    coach's trend math consistent across summaries."""
    if len(points) < 3:
        return None
    base = points[0][0]
    xs = [(p[0] - base).days for p in points]
    ys = [p[1] for p in points]
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(xs[i] * ys[i] for i in range(n))
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    slope_per_day = (n * sxy - sx * sy) / denom
    return round(slope_per_day * 7.0, 3)


def _parse_clock_to_min_of_day(stamp: str | None) -> int | None:
    """Parse ``YYYY-MM-DD HH:MM:SS`` (Apple importer format) → minutes
    of the day [0, 1440). Returns None on malformed input. For bedtime
    stdev we want clock-time-of-day, not absolute datetime — a 23:30
    bedtime and a 23:45 bedtime should compare cleanly even though they
    technically belong to different calendar dates.
    """
    if not stamp:
        return None
    try:
        dt = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    return dt.hour * 60 + dt.minute


def _circular_stdev_min(times_min: list[int]) -> float | None:
    """Circular stdev of minute-of-day values, accounting for the
    midnight wraparound. A bedtime of 23:50 and 00:10 should report a
    20-minute stdev (around midnight), not a 23-hour stdev.

    Returns minutes. None if fewer than 2 samples.
    """
    if len(times_min) < 2:
        return None
    import math
    angles = [(t / 1440.0) * 2 * math.pi for t in times_min]
    sin_sum = sum(math.sin(a) for a in angles)
    cos_sum = sum(math.cos(a) for a in angles)
    n = len(angles)
    r = (sin_sum ** 2 + cos_sum ** 2) ** 0.5 / n
    # Guard against r ≈ 1 (no variance) and r ≈ 0 (degenerate / uniform).
    if r >= 1.0:
        return 0.0
    if r <= 0.0:
        return None
    # Circular stdev in radians → convert back to minutes.
    sigma_rad = (-2 * math.log(r)) ** 0.5
    sigma_min = sigma_rad / (2 * math.pi) * 1440.0
    return round(sigma_min, 1)


def sleep_summary(nights: list[dict], today_d: date) -> dict | None:
    """28-day per-night sleep summary, or None when no nights in window.

    Returned shape (keys absent when their source data is null):

        {
          "n_nights_28d": int,
          "means_h": {
              "total": float, "core": float, "deep": float, "rem": float,
              "unspecified": float, "awake": float, "time_in_bed": float
          },
          "sleep_efficiency_pct": {"mean": float, "trend_per_week": float|None},
          "waso_h_mean": float|None,       # alias for means_h.awake
          "fragmentation": {
              "n_segments_mean": float|None,
              "n_segments_trend_per_week": float|None
          },
          "schedule_consistency": {
              "bedtime_clock_stdev_min": float|None,
              "waketime_clock_stdev_min": float|None
          },
          "outliers": [ {date, reason, efficiency_pct, awake_h} ... ]  # last 14d
        }
    """
    recent = recent_sleep_nights(nights, today_d, 28)
    if not recent:
        return None

    def vals(key: str) -> list[float]:
        out = []
        for n in recent:
            v = n.get(key)
            if v is not None:
                try:
                    out.append(float(v))
                except (TypeError, ValueError):
                    continue
        return out

    means_h = {
        "total":       _mean(vals("total_h")),
        "core":        _mean(vals("core_h")),
        "deep":        _mean(vals("deep_h")),
        "rem":         _mean(vals("rem_h")),
        "unspecified": _mean(vals("unspecified_h")),
        "awake":       _mean(vals("awake_h")),
        "time_in_bed": _mean(vals("time_in_bed_h")),
    }

    eff_points: list[tuple[date, float]] = []
    eff_vals: list[float] = []
    for n in recent:
        d = _parse_iso_date(n.get("date"))
        v = n.get("efficiency_pct")
        if d is None or v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        eff_points.append((d, f))
        eff_vals.append(f)

    eff_block = {
        "mean":           _mean(eff_vals),
        "trend_per_week": _slope_per_week(sorted(eff_points)),
    }

    n_seg_points: list[tuple[date, float]] = []
    n_seg_vals: list[float] = []
    for n in recent:
        d = _parse_iso_date(n.get("date"))
        v = n.get("n_segments")
        if d is None or v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        n_seg_points.append((d, f))
        n_seg_vals.append(f)
    fragmentation = {
        "n_segments_mean":           _mean(n_seg_vals),
        "n_segments_trend_per_week": _slope_per_week(sorted(n_seg_points)),
    }

    bedtime_mins: list[int] = []
    waketime_mins: list[int] = []
    for n in recent:
        b = _parse_clock_to_min_of_day(n.get("first_segment_start"))
        w = _parse_clock_to_min_of_day(n.get("last_segment_end"))
        if b is not None:
            bedtime_mins.append(b)
        if w is not None:
            waketime_mins.append(w)
    schedule = {
        "bedtime_clock_stdev_min":  _circular_stdev_min(bedtime_mins),
        "waketime_clock_stdev_min": _circular_stdev_min(waketime_mins),
    }

    # Outliers from the last 14 days only — the actionable window for a
    # "look at pre-bed routine" nudge. Two reasons can apply to the same
    # night; surface the worst one.
    cutoff_14d = today_d - timedelta(days=14)
    outliers: list[dict] = []
    for n in recent:
        d = _parse_iso_date(n.get("date"))
        if d is None or d < cutoff_14d:
            continue
        eff = n.get("efficiency_pct")
        awake = n.get("awake_h")
        reason = None
        if eff is not None:
            try:
                if float(eff) < EFFICIENCY_DISTURBED_MAX_PCT:
                    reason = "efficiency<80%"
            except (TypeError, ValueError):
                pass
        if reason is None and awake is not None:
            try:
                if float(awake) >= WASO_OUTLIER_MIN_H:
                    reason = "WASO≥1h"
            except (TypeError, ValueError):
                pass
        if reason:
            outliers.append({
                "date":           n.get("date"),
                "reason":         reason,
                "efficiency_pct": eff,
                "awake_h":        awake,
            })
    outliers.sort(key=lambda o: o["date"], reverse=True)

    return {
        "n_nights_28d":         len(recent),
        "means_h":              means_h,
        "sleep_efficiency_pct": eff_block,
        "waso_h_mean":          means_h["awake"],
        "fragmentation":        fragmentation,
        "schedule_consistency": schedule,
        "outliers":             outliers,
    }
