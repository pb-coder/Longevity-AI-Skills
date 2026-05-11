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


def _z_score_signal(health_all: list[dict], key: str, today_d: date,
                    recent_days: int, baseline_days: int,
                    invert: bool = False, min_baseline_n: int = 7) -> dict | None:
    """Personal z-score for one signal: ``(recent_avg − baseline_mean) /
    baseline_stdev``, clamped to ±2σ. ``invert=True`` for signals where
    lower is better (RHR, wrist temp). Returns ``None`` when the recent
    window is empty, the baseline window has fewer than ``min_baseline_n``
    readings, or baseline stdev is 0 (degenerate)."""
    recent = _values_in_window(health_all, key, today_d, recent_days)
    baseline = _values_in_window(health_all, key, today_d, baseline_days)
    if not recent or len(baseline) < min_baseline_n:
        return None
    recent_avg = sum(recent) / len(recent)
    baseline_mean = sum(baseline) / len(baseline)
    var = sum((v - baseline_mean) ** 2 for v in baseline) / len(baseline)
    baseline_stdev = var ** 0.5
    if baseline_stdev <= 0:
        return None
    z = (recent_avg - baseline_mean) / baseline_stdev
    if invert:
        z = -z
    z = max(-2.0, min(2.0, z))
    return {
        "recent_avg":     recent_avg,
        "baseline_mean":  baseline_mean,
        "baseline_stdev": baseline_stdev,
        "n_recent":       len(recent),
        "n_baseline":     len(baseline),
        "z":              z,
    }


# Per-signal recent-sample sufficiency thresholds. When a contributing
# signal whose renormalized weight is ≥0.10 falls below its threshold,
# confidence drops one band (high→medium, medium→low). Catches cases where
# a high-weight signal is hanging off a single reading and inflating the
# composite's apparent precision (e.g., one HR-Recovery sample swinging the
# score and being labelled "high confidence").
RECENT_SAMPLE_SUFFICIENCY = {
    "hrv_sdnn":         5,   # of 7
    "resting_hr":       5,   # of 7
    "sleep_total_h":    5,   # of 7
    "sleep_deep_h":     5,   # of 7
    "sleep_rem_h":      5,   # of 7
    "wrist_temp_c":     2,   # of 3 (overnight-only, allow misses)
    "hr_recovery_1min": 3,   # of 5
}
SIGNAL_WEIGHT_FLOOR_FOR_GATE = 0.10


def recovery_score(health_all: list[dict], today_d: date,
                   capabilities: dict) -> dict:
    """Renormalized weighted-average composite of per-signal personal
    z-scores, mapped to [0, 10]. Score = 5 means "average for this user
    across whatever signals are available", *not* "base 5 minus what's
    missing" — so trackers with fewer signals (HL) aren't structurally
    biased downward.

    Architecture (matches Polar Nightly Recharge / Oura Readiness /
    HRV4Training conventions):
      1. Each signal: z-score against rolling personal baseline+stdev,
         clamped to ±2σ (per Andrew Flatt's HRV monitoring approach —
         within-individual deviations, not population norms).
      2. Map each signal's z to a [0, 10] component score:
         ``component = 5.0 + clamp(z, -2, 2) × 2.5``.
         So z = 0 → 5, z = +2σ → 10, z = -2σ → 0.
      3. Composite = weighted average of component scores over signals
         that have sufficient sample (≥7 readings in baseline window),
         with weights renormalized to sum to 1.0 over present signals.
         Missing signals don't pull the score downward — they just leave
         the remaining ones to vote.

    Signals + raw weights (renormalized at runtime):
      HRV (rMSSD/SDNN)         0.30   capability-gated
      Resting HR  (inverted)   0.15
      Sleep total              0.20
      Sleep deep h             0.05   capability-gated
      Sleep REM h              0.05   capability-gated
      Wrist temp  (inverted)   0.10   capability-gated
      HR Recovery 1-min        0.10
      Sleep consistency        0.05   penalty-only

    VO2max trend is **not** a contributor. It's a chronic fitness signal
    with measurement noise that exceeds plausible week-to-week true
    change; including it conflates "am I getting fitter" with "should I
    train hard today" (matches Garmin Training Readiness, WHOOP, Oura,
    Polar Nightly Recharge — none use VO2max in acute readiness). The
    coach reads ``vo2max_latest`` / ``vo2max_trend_per_4w`` for the
    fitness check separately.

    Confidence (from contributor count, ignoring weights):
      ≥4 contributors → ``high``
      2-3 contributors → ``medium``
      <2 contributors → ``low``

    Returns ``{"score": float|None, "confidence": str, "drivers": [...]}``.
    Each driver entry has ``metric``, ``component_score`` (0-10),
    ``weight`` (renormalized share, sums to 1.0 across drivers),
    ``z`` + baseline stats for z-scored signals, or stdev + threshold for
    sleep consistency. Drivers are sorted by ``|component_score - 5|``
    descending so the most "interesting" ones surface first.
    """
    # (signal_key, recent_days, baseline_days, invert, raw_weight, capability_gate)
    SIGNALS = [
        ("hrv_sdnn",         7,  60, False, 0.30, "hrv"),
        ("resting_hr",       7,  28, True,  0.15, None),
        ("sleep_total_h",    7,  28, False, 0.20, None),
        ("sleep_deep_h",     7,  28, False, 0.05, "sleep_stages"),
        ("sleep_rem_h",      7,  28, False, 0.05, "sleep_stages"),
        ("wrist_temp_c",     3,  60, True,  0.10, "wrist_temp"),
        ("hr_recovery_1min", 5,  28, False, 0.10, None),
    ]

    # Each entry: (metric_key, raw_weight, component_score, info_dict, invert)
    raw_drivers: list[tuple] = []

    for key, recent_d, baseline_d, invert, weight, gate in SIGNALS:
        if gate and not capabilities.get(gate):
            continue
        s = _z_score_signal(health_all, key, today_d, recent_d, baseline_d,
                            invert=invert)
        if s is None:
            continue
        component_score = 5.0 + s["z"] * 2.5
        raw_drivers.append((key, weight, component_score, s, invert))

    # Sleep consistency: penalty-only contributor (low stdev = neutral 5,
    # high stdev pulls the score component toward 0). Stays a hard
    # threshold rather than a personal z-score because everyone wants
    # consistent sleep — there's no "personal normal of irregular".
    sleep_7d = _values_in_window(health_all, "sleep_total_h", today_d, 7)
    if len(sleep_7d) >= 4:
        mean = sum(sleep_7d) / len(sleep_7d)
        var = sum((x - mean) ** 2 for x in sleep_7d) / len(sleep_7d)
        stdev = var ** 0.5
        if stdev <= 1.5:
            cs = 5.0
        else:
            cs = max(0.0, 5.0 - (stdev - 1.5) * 5.0)
        info = {"stdev": stdev, "threshold": 1.5, "n": len(sleep_7d)}
        raw_drivers.append(("sleep_consistency_7d_stdev_h", 0.05, cs, info, False))

    if not raw_drivers:
        return {"score": None, "confidence": "low", "drivers": []}

    weight_sum = sum(w for _, w, _, _, _ in raw_drivers)
    weighted = sum(w * cs for _, w, cs, _, _ in raw_drivers) / weight_sum
    score = max(0.0, min(10.0, weighted))

    drivers: list[dict] = []
    for key, weight, cs, info, invert in raw_drivers:
        weight_norm = weight / weight_sum
        if "z" in info:  # standard z-scored signal
            d = {
                "metric":          key,
                "recent_avg":      round(info["recent_avg"], 2),
                "baseline_mean":   round(info["baseline_mean"], 2),
                "baseline_stdev":  round(info["baseline_stdev"], 3),
                "z":               round(info["z"], 2),
                "component_score": round(cs, 2),
                "weight":          round(weight_norm, 3),
                "n_recent":        info["n_recent"],
                "n_baseline":      info["n_baseline"],
            }
            if invert:
                d["invert"] = True
        else:  # sleep consistency penalty
            d = {
                "metric":          key,
                "stdev":           round(info["stdev"], 2),
                "threshold":       info["threshold"],
                "component_score": round(cs, 2),
                "weight":          round(weight_norm, 3),
                "n_recent":        info["n"],
            }
        drivers.append(d)

    # Most-driving signals first.
    drivers.sort(key=lambda d: abs(d["component_score"] - 5.0), reverse=True)

    n_contrib = len(drivers)
    confidence = ("high" if n_contrib >= 4
                  else "medium" if n_contrib >= 2
                  else "low")

    # Per-signal sufficiency gate: if any high-weight z-scored driver is
    # under-sampled in the recent window, drop confidence one band. The
    # `stdev` shape (sleep consistency penalty) is exempt — its `n_recent`
    # is the 7-day window count and isn't a precision proxy in the same
    # way the z-scored signals are.
    under_sampled = [
        d for d in drivers
        if d.get("weight", 0) >= SIGNAL_WEIGHT_FLOOR_FOR_GATE
        and "z" in d
        and d.get("n_recent", 0) < RECENT_SAMPLE_SUFFICIENCY.get(d["metric"], 0)
    ]
    if under_sampled:
        confidence = {"high": "medium",
                      "medium": "low",
                      "low": "low"}[confidence]

    return {
        "score":      round(score, 1),
        "confidence": confidence,
        "drivers":    drivers,
    }
