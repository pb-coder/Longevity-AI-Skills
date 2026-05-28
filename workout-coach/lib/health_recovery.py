"""Recovery score computation from health time series."""
from __future__ import annotations

from datetime import date

from health_windowing import _values_in_window


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


# =============================================================================
# Longevity score, percentile resolver, state parser (Trajectory tab)
# =============================================================================

