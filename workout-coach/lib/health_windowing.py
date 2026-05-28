"""Health time-series primitives and weekly aggregates."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

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
        # Post-2026-05 schema: typed ``incidental`` flag; legacy rows
        # still carry the marker in ``notes``.
        if s.get("incidental") is True \
                or (s.get("notes") or "").lower().startswith("incidental"):
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
        "time_in_bed_h",
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

