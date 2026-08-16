"""Sleep analytics for the coach.

Consumes the per-night CSVs at ``<person>/data/sleep/YYYY.MM.nights.csv``
and returns a structured ``sleep_summary`` block that the coach prompt
threads into its sleep section. Returns ``None`` when there are no
nights in the 28-day window — ``_compact`` then drops the key from the
JSON output and the prompt's sleep section stays silent (trackers
or XML trackers with no recent sleep data).

Public surface:

- ``recent_sleep_nights(nights, today_d, days)`` — windowed list.
- ``sleep_summary(nights, today_d)`` — the full block (stage means,
  efficiency mean + trend, fragmentation, schedule consistency,
  outlier nights).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


from .constants import SLEEP_TARGETS
from .parsing import _parse_iso_date


# Clinical / consumer-grade Sleep Efficiency and REM thresholds. The values
# are sourced from SLEEP_TARGETS in constants.py (the single source of truth
# for sleep norms); these module names are local aliases used by the anomaly
# checks below. >85% efficiency is the textbook "healthy adult" anchor; <80%
# is the cutoff sleep clinics flag as disturbed (PSQI, ISI); <20% REM is the
# low-REM threshold. Surfacing outlier nights only — the per-driver
# recovery-score weighting lives in health.py once we have 4-6w of data.
EFFICIENCY_DISTURBED_MAX_PCT = SLEEP_TARGETS["efficiency_pct_disturbed"]
WASO_OUTLIER_MIN_H = 1.0  # sleep.py-specific; no SLEEP_TARGETS equivalent
# The threshold used to count low-REM nights AND reported as target_min_pct
# in flag_rem_sleep_anomalies().
REM_TARGET_MIN_PCT = SLEEP_TARGETS["rem_pct_min"]


def recent_sleep_nights(nights: list[dict], today_d: date,
                        days: int = 28) -> list[dict]:
    """Filter ``nights`` to the last ``days`` (inclusive of today)."""
    if not nights:
        return []
    cutoff = today_d - timedelta(days=max(days - 1, 0))
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
        "source":         "derived_sleep_period",
        "caveat":         (
            "Derived from sleep-stage total divided by stored time-in-bed; "
            "when true Apple InBed is absent this is continuity, not a clinical sleep-efficiency denominator."
        ) if eff_vals else None,
    }
    short_sleep_note = None
    total_mean = means_h.get("total")
    if total_mean is not None and total_mean < 7.0:
        short_sleep_note = (
            "Average sleep is below 7h/night in the 28-day window; do not frame high efficiency as a recovery bright spot by itself."
        )

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
    cutoff_14d = today_d - timedelta(days=13)
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
        "absolute_sleep_note":  short_sleep_note,
    }


def compute_sleep_regularity_index(nights: list[dict], today_d: date,
                                    window_days: int = 14) -> dict | None:
    """Sleep Regularity Index (Phillips 2017 / Windred 2024 eLife).

    SRI scores how consistently a person is asleep at the same wall-clock
    minute on consecutive days, scaled 0-100 (100 = identical schedule
    every day). Computed by sampling each minute of the day across the
    window and asking, for every pair of consecutive days, "was the
    person asleep at minute m on both days?"

    UK Biobank (n=60,977): top-quintile SRI vs bottom = 20-48% lower
    all-cause mortality. Stronger mortality predictor than total sleep.

    We approximate the per-minute asleep state from each night's
    ``first_segment_start`` (sleep onset) and ``last_segment_end`` (final
    wake), treating the interval as asleep. This is a reasonable proxy
    for SRI's intent without per-stage hypnogram data (Apple importer
    drops segment-level detail). Returns ``None`` if fewer than 3 nights
    in the window have both timestamps.
    """
    if not nights:
        return None
    cutoff = today_d - timedelta(days=max(window_days - 1, 0))
    spans: list[tuple[date, int, int]] = []
    for n in nights:
        d = _parse_iso_date(n.get("date"))
        if d is None or d < cutoff or d > today_d:
            continue
        start = _parse_clock_to_min_of_day(n.get("first_segment_start"))
        end = _parse_clock_to_min_of_day(n.get("last_segment_end"))
        if start is None or end is None:
            continue
        spans.append((d, start, end))
    if len(spans) < 3:
        return None
    spans.sort(key=lambda s: s[0])
    # Build per-night asleep bitmap over a 1440-minute day. The sleep
    # interval often crosses midnight (start near 23:00, end near 07:00);
    # treat each night's interval as belonging to the second calendar day
    # so consecutive nights' bitmaps align.
    by_day: dict[date, list[bool]] = {}
    for d, start, end in spans:
        asleep = [False] * 1440
        if end >= start:
            # No wrap (e.g. 01:30 → 09:00). Rare but possible (nap).
            for m in range(start, end):
                asleep[m] = True
        else:
            # Crosses midnight: [start..1440) on prior day + [0..end) on d.
            for m in range(start, 1440):
                asleep[m] = True
            for m in range(0, end):
                asleep[m] = True
        by_day[d] = asleep
    sorted_days = sorted(by_day.keys())
    if len(sorted_days) < 2:
        return None
    # For each consecutive day-pair within 1 day apart, count agreement.
    total = 0
    agree = 0
    pairs = 0
    for i in range(1, len(sorted_days)):
        if (sorted_days[i] - sorted_days[i - 1]).days != 1:
            continue
        a = by_day[sorted_days[i - 1]]
        b = by_day[sorted_days[i]]
        for m in range(1440):
            if a[m] == b[m]:
                agree += 1
            total += 1
        pairs += 1
    if total == 0:
        return None
    sri = 200.0 * (agree / total) - 100.0  # Phillips 2017 formula
    sri = max(0.0, min(100.0, sri))
    # UK Biobank band thresholds (Windred 2024 eLife).
    if sri >= 87.0:
        band, label = "good", "top quintile"
    elif sri >= 78.0:
        band, label = "good", "above median"
    elif sri >= 71.0:
        band, label = "amber", "below median"
    else:
        band, label = "warn", "bottom quintile"
    return {
        "sri":                round(sri, 1),
        "n_nights":           len(spans),
        "n_consecutive_pairs": pairs,
        "window_days":        window_days,
        "band":               band,
        "label":              label,
    }


def flag_rem_sleep_anomalies(nights: list[dict], today_d: date,
                              window_days: int = 28) -> dict | None:
    """REM-sleep anomaly count for profile-gated surveillance signals.

    We do not have movement-during-REM hypnograms; this only counts
    nights where REM dropped below 15% of total sleep in the window.
    Returns ``None`` if no REM data exists in the window.
    """
    if not nights:
        return None
    cutoff = today_d - timedelta(days=max(window_days - 1, 0))
    n_with_rem = 0
    low_rem_nights = 0
    rem_pcts: list[float] = []
    for n in nights:
        d = _parse_iso_date(n.get("date"))
        if d is None or d < cutoff or d > today_d:
            continue
        rem = n.get("rem_h")
        total = n.get("total_h")
        if rem is None or total is None or total <= 0:
            continue
        try:
            rem_f = float(rem)
            total_f = float(total)
        except (TypeError, ValueError):
            continue
        if total_f <= 0:
            continue
        n_with_rem += 1
        pct = (rem_f / total_f) * 100.0
        rem_pcts.append(pct)
        if pct < REM_TARGET_MIN_PCT:
            low_rem_nights += 1
    if n_with_rem == 0:
        return None
    mean_rem_pct = sum(rem_pcts) / len(rem_pcts)
    return {
        "window_days":       window_days,
        "n_nights":          n_with_rem,
        "mean_rem_pct":      round(mean_rem_pct, 1),
        "low_rem_nights":    low_rem_nights,
        "target_min_pct":    REM_TARGET_MIN_PCT,
    }
