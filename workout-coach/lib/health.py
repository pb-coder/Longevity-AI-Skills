"""Health time-series helpers + weekly aggregates + recovery score.

Three layers:

1. **Time-series primitives** that the rest of the analytics layer
   consumes (``_values_in_window``, ``_mean_or_none``, ``baseline_60d``,
   ``metric_trend_per_4w``, ``latest_metric``, ``workout_sessions_in_window``).
2. **Weekly rollup** (``health_metrics_weekly``) that the LLM reads as
   the default lens — replaces the raw daily dump.
3. **Recovery score** (``recovery_score``) — the headline derived
   signal. Composes ~9 capability-gated drivers (HRV, RHR, sleep total,
   sleep depth, sleep REM, sleep consistency, wrist temp, HR Recovery,
   VO2max trend) into a 0-10 score with a named-driver list.

All dates use the shared ``_parse_iso_date`` from ``parsing``. Recovery
gates each capability-dependent driver on the ``capabilities`` dict so
HL trackers automatically degrade to the metrics their source supports
without the helper having to know about source types.
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


def _values_in_window(entries: list[dict], key: str, today_d: date, days: int) -> list[float]:
    cutoff = today_d - timedelta(days=days)
    out = []
    for e in entries:
        v = e.get(key)
        if v is None:
            continue
        d = _parse_iso_date(e.get("date"))
        if d is None:
            continue
        if d < cutoff:
            continue
        out.append(float(v))
    return out


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def metric_trend_per_4w(entries: list[dict], key: str) -> float | None:
    """OLS slope of ``key`` over time, scaled to a 4-week window.

    Returns None unless there are ≥4 non-null entries spanning ≥21 days.
    Used for HRV / RHR / VO2max / sleep trends. Negative is improving for
    RHR (lower resting HR = better cardio fitness); positive is improving
    for HRV and VO2max.
    """
    pts: list[tuple[date, float]] = []
    for e in entries:
        v = e.get(key)
        if v is None:
            continue
        d = _parse_iso_date(e.get("date"))
        if d is None:
            continue
        pts.append((d, float(v)))
    if len(pts) < 4:
        return None
    pts.sort(key=lambda p: p[0])
    span_days = (pts[-1][0] - pts[0][0]).days
    if span_days < 21:
        return None
    base = pts[0][0]
    xs = [(p[0] - base).days for p in pts]
    ys = [p[1] for p in pts]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    if den <= 0:
        return None
    return round((num / den) * 28.0, 2)


def latest_metric(entries: list[dict], key: str) -> dict | None:
    """Most recent (date, value) pair for ``key``, or None if absent."""
    for e in reversed(entries):
        v = e.get(key)
        if v is not None:
            return {"date": e["date"], "value": round(float(v), 2)}
    return None


def baseline_60d(entries: list[dict], key: str, today_d: date) -> float | None:
    """Mean of ``key`` over the last 60 days. Used as anomaly baseline."""
    return _mean_or_none(_values_in_window(entries, key, today_d, 60))


def workout_sessions_in_window(sessions: list[dict], today_d: date, days: int) -> list[dict]:
    cutoff = today_d - timedelta(days=days)
    out = []
    for s in sessions:
        d = _parse_iso_date(s.get("date"))
        if d is None:
            continue
        if d < cutoff:
            continue
        # Filter out incidental walks — those aren't training.
        if (s.get("notes") or "").lower().startswith("incidental"):
            continue
        out.append({
            "date":         s["date"],
            "type":         s.get("apple_type"),
            "duration":     s.get("duration_min"),
            "avg_hr":       s.get("avg_hr"),
            "max_hr":       s.get("max_hr"),
            "cal":          s.get("active_cal"),
        })
    return out


def health_metrics_weekly(health_all: list[dict],
                          today_d: date, weeks: int = 4) -> list[dict]:
    """Per-week aggregates of Health Metrics for the last N weeks.

    Replaces the 8 KB raw daily dump with a compact 4-week snapshot. Each
    entry is the mean of available daily values that landed in that ISO
    week (Mon-Sun). Only fields with at least one value in the window are
    emitted; sources that structurally can't provide a metric (HL slim
    schema) yield None for that key, which ``_compact`` strips.
    """
    if not health_all:
        return []
    cutoff = today_d - timedelta(days=weeks * 7)
    keys = [
        "vo2max", "resting_hr", "hrv_sdnn", "walking_hr",
        "hr_recovery_1min", "sleep_total_h", "sleep_deep_h", "sleep_rem_h",
        "resp_rate", "wrist_temp_c", "exercise_min",
    ]
    by_week: dict[tuple[int, int], dict[str, list[float]]] = {}
    for e in health_all:
        d = _parse_iso_date(e.get("date"))
        if d is None:
            continue
        if d < cutoff:
            continue
        iso = d.isocalendar()
        wk = (iso.year, iso.week)
        bucket = by_week.setdefault(wk, {})
        for k in keys:
            v = e.get(k)
            if v is None:
                continue
            bucket.setdefault(k, []).append(float(v))

    out: list[dict] = []
    for wk in sorted(by_week.keys()):
        # Monday of the ISO week — readable anchor for the LLM.
        monday = datetime.fromisocalendar(wk[0], wk[1], 1).date()
        entry: dict = {"week_start": monday.strftime("%Y-%m-%d"),
                       "n_days": max(len(v) for v in by_week[wk].values())}
        for k in keys:
            vals = by_week[wk].get(k)
            if not vals:
                entry[k] = None
                continue
            entry[k] = round(sum(vals) / len(vals), 2)
        out.append(entry)
    return out


def recovery_score(health_all: list[dict], today_d: date,
                   capabilities: dict) -> dict:
    """Compute a 0-10 recovery score from HRV, RHR, sleep, wrist temp,
    HR Recovery 1-min, and VO2max trend.

    Each signal contributes a clamped delta to a baseline of 5; the final
    score is clamped to [0, 10]. Drivers list shows which signals
    dominated so the coach can explain *why*.
    Returns ``{"score": float, "drivers": list[dict], "confidence": str}``.
    """
    drivers: list[dict] = []
    score = 5.0
    sample_count = 0

    # HRV: reading vs personal 60d baseline. ±10% baseline = ±2 score swing.
    if capabilities.get("hrv"):
        recent = _values_in_window(health_all, "hrv_sdnn", today_d, 7)
        baseline = baseline_60d(health_all, "hrv_sdnn", today_d)
        if recent and baseline and baseline > 0:
            recent_avg = sum(recent) / len(recent)
            delta = (recent_avg - baseline) / baseline
            contrib = max(-2.0, min(2.0, delta / 0.05))  # ±5% baseline → ±1
            score += contrib
            sample_count += 1
            drivers.append({
                "metric":     "hrv_sdnn",
                "recent_avg": round(recent_avg, 1),
                "baseline":   round(baseline, 1),
                "delta_pct":  round(delta * 100, 1),
                "contrib":    round(contrib, 2),
            })

    # Resting HR: lower is better. ±5 bpm vs 28d typical → ±2 swing.
    rhr_recent = _values_in_window(health_all, "resting_hr", today_d, 7)
    rhr_typical = _values_in_window(health_all, "resting_hr", today_d, 28)
    if rhr_recent and rhr_typical:
        recent_avg = sum(rhr_recent) / len(rhr_recent)
        typical_avg = sum(rhr_typical) / len(rhr_typical)
        delta = recent_avg - typical_avg
        contrib = max(-2.0, min(2.0, -delta / 2.5))  # +2.5 bpm → -1
        score += contrib
        sample_count += 1
        drivers.append({
            "metric":      "resting_hr",
            "recent_avg":  round(recent_avg, 1),
            "typical_avg": round(typical_avg, 1),
            "delta_bpm":   round(delta, 1),
            "contrib":     round(contrib, 2),
        })

    # Sleep: 7h target. ±1h → ±1 swing (clamped ±2).
    sleep = _values_in_window(health_all, "sleep_total_h", today_d, 7)
    if sleep:
        recent_avg = sum(sleep) / len(sleep)
        delta = recent_avg - 7.0
        contrib = max(-2.0, min(2.0, delta))
        score += contrib
        sample_count += 1
        drivers.append({
            "metric":     "sleep_total_h",
            "recent_avg": round(recent_avg, 2),
            "target":     7.0,
            "delta_h":    round(delta, 2),
            "contrib":    round(contrib, 2),
        })

    # Sleep depth: deep + REM percentages of total sleep over the last 7
    # nights. Deep healthy band 13-23%, REM 20-25% (Walker 2017, AASM).
    # Capability-gated on ``sleep_stages`` (HL doesn't supply stages and
    # falls through silently). Weight ±0.4 each — small contributions but
    # they catch chronic deep-sleep deficits that total hours hide.
    if capabilities.get("sleep_stages"):
        deep_vals = _values_in_window(health_all, "sleep_deep_h", today_d, 7)
        rem_vals  = _values_in_window(health_all, "sleep_rem_h", today_d, 7)
        # Need matched-day total + stage values for a percentage. Pull
        # paired entries from the underlying rows directly so a bad night
        # with missing stage data doesn't poison the average.
        deep_pcts: list[float] = []
        rem_pcts:  list[float] = []
        cutoff = today_d - timedelta(days=7)
        for e in health_all:
            d = _parse_iso_date(e.get("date"))
            if d is None:
                continue
            if d < cutoff:
                continue
            tot = e.get("sleep_total_h")
            if not tot or tot <= 0:
                continue
            dh = e.get("sleep_deep_h")
            rh = e.get("sleep_rem_h")
            if dh is not None:
                deep_pcts.append(float(dh) / float(tot))
            if rh is not None:
                rem_pcts.append(float(rh) / float(tot))
        if deep_pcts:
            recent_avg = sum(deep_pcts) / len(deep_pcts)
            # Healthy 0.13-0.23. <0.13 → negative; >0.23 → small positive.
            if recent_avg < 0.13:
                contrib = max(-0.4, (recent_avg - 0.13) / 0.05 * 0.4)
            elif recent_avg > 0.23:
                contrib = min(0.4, (recent_avg - 0.23) / 0.05 * 0.4)
            else:
                contrib = 0.0
            score += contrib
            if abs(contrib) > 0.0:
                sample_count += 1
            drivers.append({
                "metric":      "sleep_deep_pct",
                "recent_avg":  round(recent_avg, 3),
                "healthy_min": 0.13,
                "healthy_max": 0.23,
                "contrib":     round(contrib, 2),
            })
        if rem_pcts:
            recent_avg = sum(rem_pcts) / len(rem_pcts)
            # Healthy 0.20-0.25.
            if recent_avg < 0.20:
                contrib = max(-0.4, (recent_avg - 0.20) / 0.05 * 0.4)
            elif recent_avg > 0.25:
                contrib = min(0.4, (recent_avg - 0.25) / 0.05 * 0.4)
            else:
                contrib = 0.0
            score += contrib
            if abs(contrib) > 0.0:
                sample_count += 1
            drivers.append({
                "metric":      "sleep_rem_pct",
                "recent_avg":  round(recent_avg, 3),
                "healthy_min": 0.20,
                "healthy_max": 0.25,
                "contrib":     round(contrib, 2),
            })

    # Sleep consistency: stdev of nightly totals over the last 7 nights.
    # >1.5h stdev = irregular sleep is its own stressor regardless of
    # average. Source-agnostic; HL surfaces sleep_total_h, so this driver
    # also fires on Fabian-style trackers.
    if len(sleep) >= 4:
        mean = sum(sleep) / len(sleep)
        var = sum((x - mean) ** 2 for x in sleep) / len(sleep)
        stdev = var ** 0.5
        contrib = 0.0
        if stdev > 1.5:
            contrib = max(-0.4, (1.5 - stdev) / 0.5 * 0.4)
        score += contrib
        if abs(contrib) > 0.0:
            sample_count += 1
        drivers.append({
            "metric":   "sleep_consistency_7d_stdev_h",
            "stdev":    round(stdev, 2),
            "threshold": 1.5,
            "contrib":  round(contrib, 2),
        })

    # Wrist temp: deviation from 60d baseline. >+0.3°C is a stress/illness
    # signal; weight modestly (max ±1.5).
    if capabilities.get("wrist_temp"):
        wt_recent = _values_in_window(health_all, "wrist_temp_c", today_d, 3)
        wt_base = baseline_60d(health_all, "wrist_temp_c", today_d)
        if wt_recent and wt_base:
            recent_avg = sum(wt_recent) / len(wt_recent)
            delta = recent_avg - wt_base
            contrib = max(-1.5, min(1.5, -delta / 0.2))
            score += contrib
            sample_count += 1
            drivers.append({
                "metric":     "wrist_temp_c",
                "recent_avg": round(recent_avg, 2),
                "baseline":   round(wt_base, 2),
                "delta_c":    round(delta, 2),
                "contrib":    round(contrib, 2),
            })

    # HR Recovery 1-min (count/min HR drop after exercise). Higher is
    # better — parasympathetic re-activation. Weight ±0.75. Compare
    # recent (5d) vs 28d typical; ±5 bpm = ±0.75.
    hrr_recent = _values_in_window(health_all, "hr_recovery_1min", today_d, 5)
    hrr_typical = _values_in_window(health_all, "hr_recovery_1min", today_d, 28)
    if hrr_recent and hrr_typical:
        recent_avg = sum(hrr_recent) / len(hrr_recent)
        typical_avg = sum(hrr_typical) / len(hrr_typical)
        delta = recent_avg - typical_avg
        contrib = max(-0.75, min(0.75, delta / 6.7))  # +5 bpm → +0.75
        score += contrib
        sample_count += 1
        drivers.append({
            "metric":      "hr_recovery_1min",
            "recent_avg":  round(recent_avg, 1),
            "typical_avg": round(typical_avg, 1),
            "delta_bpm":   round(delta, 1),
            "contrib":     round(contrib, 2),
        })

    # VO2max trend per 4 weeks. Slow-moving signal — folding it in gives
    # credit for fitness improvements / penalises drift. Weight ±0.75;
    # ±2 ml/kg/min over 4w → ±0.75.
    vo2_slope = metric_trend_per_4w(health_all, "vo2max")
    if vo2_slope is not None:
        contrib = max(-0.75, min(0.75, vo2_slope / 2.7))
        score += contrib
        sample_count += 1
        drivers.append({
            "metric":      "vo2max_trend_per_4w",
            "slope":       round(vo2_slope, 2),
            "contrib":     round(contrib, 2),
        })

    score = max(0.0, min(10.0, score))
    confidence = "high" if sample_count >= 3 else ("medium" if sample_count == 2 else "low")
    return {
        "score":      round(score, 1),
        "confidence": confidence,
        "drivers":    drivers,
    }
