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


def vo2_percentile_age_sex(value: float | None, sex: str | None,
                            age: int | None) -> dict | None:
    """Resolve a VO2 max reading to its age-cohort percentile band.

    Returns a dict with the four reference points (p50/p75/p95/longevity)
    plus the user's current bucket and a human-readable label
    ("median for your age", "above average", "elite", "longevity-target").
    Returns ``None`` when sex/age unknown or no value provided.
    """
    from constants import VO2MAX_NORMS, age_band  # local import
    if value is None:
        return None
    bands = age_band(VO2MAX_NORMS, sex or "", age if age is not None else 0)
    if not bands:
        return None
    p50, p75, p95, longevity = bands["p50"], bands["p75"], bands["p95"], bands["longevity"]
    if value < p50:
        label, status = "below median", "warn"
    elif value < p75:
        label, status = "above median", "amber"
    elif value < p95:
        label, status = "above-average", "good"
    elif value < longevity:
        label, status = "elite", "good"
    else:
        label, status = "longevity-target reached", "good"
    return {
        "value":       round(value, 1),
        "p50":         p50,
        "p75":         p75,
        "p95":         p95,
        "longevity":   longevity,
        "label":       label,
        "status":      status,
    }


def _safe_norm(value: float | None, lo: float, hi: float) -> float:
    """Linear normalize ``value`` from [lo, hi] to [0, 1], clamped."""
    if value is None or hi <= lo:
        return 0.0
    x = (value - lo) / (hi - lo)
    return max(0.0, min(1.0, x))


def compute_longevity_score(*, vo2_percentile: dict | None,
                            recovery: dict | None,
                            sleep_summary: dict | None,
                            sleep_regularity: dict | None,
                            acwr: dict | None,
                            cardio_zones: dict | None,
                            movement_consistency: dict | None,
                            bodyweight_trend_kg_per_week: float | None,
                            estimated_1rm: dict | None,
                            capabilities: dict | None = None) -> dict | None:
    """Composite Longevity Score (0-100) — the Trajectory tab headline.

    Weighted average of normalized inputs from ``LONGEVITY_SCORE_WEIGHTS``.
    Weights are renormalized to the subset of inputs that are present so
    a person with missing data isn't structurally penalized (same shape
    as ``recovery_score``).

    Returns ``{"score": float, "components": [...], "n_components": int,
    "bloodwork_pending": True}`` with per-component attribution
    (contribution to the final score) so the dashboard can render
    "what's pulling you up / down".

    The ``bloodwork_pending`` flag is always True until biomarker
    ingestion lands — the score is honest about what it doesn't see.
    """
    from constants import LONGEVITY_SCORE_WEIGHTS
    components: dict[str, float] = {}

    # 1. VO2 percentile (longevity-most-predictive single signal)
    if vo2_percentile:
        v = vo2_percentile.get("value")
        p50, p95 = vo2_percentile.get("p50"), vo2_percentile.get("p95")
        long_t = vo2_percentile.get("longevity")
        if v is not None and p50 is not None and long_t is not None:
            # 50 baseline at p50, 100 at longevity target, 0 well below.
            if v >= long_t:
                components["vo2_percentile"] = 100.0
            elif v >= p95:
                components["vo2_percentile"] = 85.0 + 15.0 * (v - p95) / max(long_t - p95, 0.1)
            elif v >= p50:
                components["vo2_percentile"] = 50.0 + 35.0 * (v - p50) / max(p95 - p50, 0.1)
            else:
                components["vo2_percentile"] = max(0.0, 50.0 * (v / p50))

    # 2. HRV trend (recovery_score driver). Use the HRV component score
    # directly (0-10 mapped to 0-100).
    drivers = (recovery or {}).get("drivers") or []
    hrv_d = next((d for d in drivers if d.get("metric") == "hrv_sdnn"), None)
    if hrv_d and hrv_d.get("component_score") is not None:
        components["hrv_trend"] = hrv_d["component_score"] * 10.0
    rhr_d = next((d for d in drivers if d.get("metric") == "resting_hr"), None)
    if rhr_d and rhr_d.get("component_score") is not None:
        components["rhr_trend"] = rhr_d["component_score"] * 10.0

    # 3. Sleep regularity (UK Biobank mortality-relevant)
    if sleep_regularity and sleep_regularity.get("sri") is not None:
        sri = sleep_regularity["sri"]
        components["sleep_regularity"] = max(0.0, min(100.0, sri))

    # 4. Sleep quality (duration × deep+REM × efficiency)
    if sleep_summary:
        means = sleep_summary.get("means_h") or {}
        eff_block = sleep_summary.get("sleep_efficiency_pct") or {}
        total = means.get("total") or 0.0
        deep = means.get("deep") or 0.0
        rem = means.get("rem") or 0.0
        eff_mean = (eff_block.get("mean") if isinstance(eff_block, dict) else None)
        # Each sub-input normalized to [0, 1], averaged into a 0-100 score.
        dur_n = _safe_norm(total, 5.0, 8.0)
        dr_n = _safe_norm(deep + rem, 1.0, 3.0)
        eff_n = _safe_norm(eff_mean, 75.0, 95.0) if eff_mean is not None else None
        parts = [v for v in (dur_n, dr_n, eff_n) if v is not None]
        if parts:
            components["sleep_quality"] = 100.0 * sum(parts) / len(parts)

    # 5. ACWR sweet-spot adherence (closer to 1.0 in [0.8, 1.3] = higher)
    if acwr and acwr.get("ratio") is not None:
        r = acwr["ratio"]
        if 0.8 <= r <= 1.3:
            components["training_load_in_band"] = 100.0
        elif 0.5 <= r < 0.8:
            components["training_load_in_band"] = 50.0 + 50.0 * (r - 0.5) / 0.3
        elif 1.3 < r <= 1.5:
            components["training_load_in_band"] = 100.0 - 30.0 * (r - 1.3) / 0.2
        else:
            components["training_load_in_band"] = max(0.0, 50.0 - 25.0 * abs(r - 1.0))

    # 6. Z2 weekly minutes adherence (target 150)
    if cardio_zones:
        z2 = cardio_zones.get("z2") or 0
        z2_per_wk = z2 / 4.0  # cardio_zones is 28d window
        components["z2_weekly_adherence"] = _safe_norm(z2_per_wk, 0, 200.0) * 100.0

    # 7. Body composition trend (directional: depends on bw goal — without a
    # goal field we treat ANY directional change as informative; small
    # gains in a lean-bulk context = good. 0 weight change = 60 baseline.
    if bodyweight_trend_kg_per_week is not None:
        bt = bodyweight_trend_kg_per_week
        # +0.0 to +0.4 kg/wk = lean-bulk healthy range; >0.6 fat-mass risk;
        # negative = cutting or unintentional loss. Without goal context,
        # tight neutral band gets the highest score.
        if -0.1 <= bt <= 0.4:
            components["body_comp_trend"] = 75.0
        elif 0.4 < bt <= 0.6:
            components["body_comp_trend"] = 60.0
        else:
            components["body_comp_trend"] = 50.0

    # 8. Behavioral consistency (movement-min days ≥ threshold per week)
    if movement_consistency:
        days_28 = movement_consistency.get("days_28d") or 0
        # Target: 5 days/wk × 4 = 20 days in 28; floor 0 = 0 score.
        components["behavioral_consistency"] = _safe_norm(days_28, 0, 20.0) * 100.0

    # 9. Strength progression: average slope direction across tracked lifts.
    if estimated_1rm:
        slopes = [v.get("slope_kg_per_4w") for v in estimated_1rm.values()
                  if isinstance(v, dict) and v.get("slope_kg_per_4w") is not None]
        if slopes:
            pos = sum(1 for s in slopes if s > 0.0)
            neutral = sum(1 for s in slopes if -0.5 <= s <= 0.5)
            pos_share = (pos + 0.5 * neutral) / len(slopes)
            components["strength_progression"] = pos_share * 100.0

    if not components:
        return None

    weights = {k: LONGEVITY_SCORE_WEIGHTS[k] for k in components.keys()
               if k in LONGEVITY_SCORE_WEIGHTS}
    total_w = sum(weights.values())
    if total_w <= 0:
        return None
    score = sum(weights[k] * components[k] for k in weights) / total_w

    # Per-component attribution for the dashboard's drilldown.
    attribution: list[dict] = []
    for k, v in components.items():
        norm_w = weights[k] / total_w
        attribution.append({
            "name":         k,
            "score":        round(v, 1),
            "weight":       round(norm_w, 3),
            "contribution": round(v * norm_w, 2),
        })
    attribution.sort(key=lambda a: a["contribution"], reverse=True)

    if score >= 80.0:
        band = "good"
        label = "excellent trajectory"
    elif score >= 65.0:
        band = "good"
        label = "on a good trajectory"
    elif score >= 50.0:
        band = "amber"
        label = "average trajectory"
    else:
        band = "warn"
        label = "needs attention"

    # Status classification — honest about gaps.
    #
    # Cornerstone = VO2 percentile (the single strongest longevity
    # predictor; the score loses most of its meaning without it).
    # Tracked = every other input. When some tracked inputs are missing
    # the score still computes but we surface what's absent so the user
    # can populate them.
    CORNERSTONE = "vo2_percentile"
    TRACKED_INPUTS = list(LONGEVITY_SCORE_WEIGHTS.keys())
    present_names = set(components.keys())
    missing_names = [n for n in TRACKED_INPUTS if n not in present_names]

    # Friendly hints for each missing input — only shown when the user
    # can actually act on them. Structural source limitations (e.g. SRI
    # requires segment-level sleep timestamps that HealthAutoExport
    # doesn't produce) are filtered out below via INPUT_CAPABILITY_REQ so
    # the dashboard doesn't punish people for a tooling boundary they
    # can't move.
    HINTS = {
        "vo2_percentile":         "Needs both age (from profile.csv birthday) AND sex (profile.csv sex field). Apple Health typically logs VO2max within a week of any outdoor run.",
        "hrv_trend":              "Needs ~7 consecutive nights of HRV (SDNN) data from the Apple Watch.",
        "rhr_trend":              "Needs ~7 consecutive days of resting heart rate readings from the Apple Watch.",
        "sleep_regularity":       "Needs ~14 consecutive nights of sleep data with per-segment bedtime / waketime timestamps.",
        "sleep_quality":          "Needs at least one logged sleep night with total / deep / REM in the 28-day window.",
        "training_load_in_band":  "Needs at least one cardio session with average HR in the last 28 days to compute the ACWR.",
        "z2_weekly_adherence":    "Needs at least one cardio session with average HR in the last 28 days.",
        "body_comp_trend":        "Needs at least 8 fasted bodyweight readings to compute a per-week trend.",
        "behavioral_consistency": "Needs daily Apple exercise minutes from the last 28 days.",
        "strength_progression":   "Needs at least 4 weeks of strength logs with progressive weights or reps.",
    }
    # Each input maps to the SOURCE_CAPABILITIES flag it depends on (or
    # None if it's source-independent / user-populatable). When the
    # current source returns False for the required flag, the input is
    # filtered from the user-facing missing list — it's structurally
    # unavailable, not "not yet populated".
    INPUT_CAPABILITY_REQ = {
        "sleep_regularity": "sleep_regularity",
    }
    caps = capabilities or {}
    missing_inputs = []
    for n in missing_names:
        req = INPUT_CAPABILITY_REQ.get(n)
        if req is not None and caps.get(req) is False:
            continue
        missing_inputs.append({"name": n, "hint": HINTS.get(n, "")})

    if CORNERSTONE not in present_names:
        status = "incomplete"
        status_label = "Incomplete"
        # When the cornerstone is missing the score still computes but it
        # leans on the wrong signals (e.g. Apple-ring movement count
        # carrying outsized weight). Suppress the confident band/label.
        band = "muted"
        label = "Incomplete — VO2 max percentile cannot be resolved"
    elif missing_names:
        status = "partial"
        status_label = f"Partial — {len(present_names)} of {len(TRACKED_INPUTS)} inputs"
    else:
        status = "complete"
        status_label = "Complete"

    return {
        "score":             round(score, 1),
        "band":              band,
        "label":             label,
        "status":            status,
        "status_label":      status_label,
        "n_components":      len(components),
        "n_tracked_total":   len(TRACKED_INPUTS),
        "components":        attribution,
        "missing_inputs":    missing_inputs,
        "bloodwork_pending": True,
        "note":              "Score excludes biomarkers (lipids, glucose, ApoB, hsCRP) until a panel is on file.",
    }


# =============================================================================
# 5-tier session recommendation gate
# =============================================================================
#
# The Today tab calls this BEFORE generating any workout. It decides which of
# Tier A (rest) / B (reactive deload) / C (downgrade) / D (green) / E
# (over-recovered) the user is in, based on the existing signals already in
# the JSON. The SKILL.md Phase 2 prompt is required to honor the result —
# this is the deterministic single source of truth so the LLM can't
# rationalize past it.

def _muscles_over_mrv(weekly_volume: dict | None) -> list[str]:
    """Return the list of muscle names whose per-week volume exceeds MRV."""
    if not weekly_volume:
        return []
    current = weekly_volume.get("current") or {}
    landmarks = weekly_volume.get("landmarks") or {}
    window_days = weekly_volume.get("window_days") or 28
    weeks_in_window = max(window_days / 7.0, 1.0)
    out = []
    for m, sets_in_window in current.items():
        per_wk = sets_in_window / weeks_in_window
        mrv = (landmarks.get(m) or {}).get("mrv")
        if mrv and per_wk > mrv:
            out.append(m)
    return sorted(out)


def _rhr_sustained_elevation_days(health_all: list[dict], today_d: date,
                                   bpm_above_baseline: float,
                                   baseline_days: int = 14) -> int:
    """Number of consecutive most-recent days where RHR >= baseline + threshold.

    Used by Tier A's "RHR sustained +10 bpm for 3 days" trigger.
    """
    baseline = _mean_or_none(
        _values_in_window(health_all, "resting_hr", today_d, baseline_days)
    )
    if baseline is None:
        return 0
    threshold = baseline + bpm_above_baseline
    by_date: dict[date, float] = {}
    for e in health_all:
        v = e.get("resting_hr")
        if v is None:
            continue
        d = _parse_iso_date(e.get("date"))
        if d is None or d > today_d:
            continue
        try:
            by_date[d] = float(v)
        except (TypeError, ValueError):
            continue
    streak = 0
    cur = today_d
    while True:
        v = by_date.get(cur)
        if v is None or v < threshold:
            break
        streak += 1
        cur = cur - timedelta(days=1)
    return streak


def _wrist_temp_deviation_c(health_all: list[dict], today_d: date) -> float | None:
    """Latest wrist temp minus the 60-day mean. Positive = above baseline."""
    latest = latest_metric(health_all, "wrist_temp_c")
    baseline = baseline_60d(health_all, "wrist_temp_c", today_d)
    if not latest or baseline is None:
        return None
    return round(latest["value"] - baseline, 2)


def _z_for(health_all: list[dict], key: str, today_d: date,
           recent_days: int = 7, baseline_days: int = 60,
           invert: bool = False) -> float | None:
    """Personal z-score for a single signal. Thin wrapper around
    `_z_score_signal` that returns just the z value."""
    info = _z_score_signal(health_all, key, today_d, recent_days, baseline_days, invert=invert)
    return info["z"] if info else None


def _count_stalled_lifts(estimated_1rm: dict | None) -> int:
    """Count lifts with stalled_sessions >= 2 (the Tuchscherer reactive-deload
    trigger). Uses already-computed `estimated_1rm[ex].stalled_sessions`."""
    if not estimated_1rm:
        return 0
    n = 0
    for v in estimated_1rm.values():
        if not isinstance(v, dict):
            continue
        stalled = v.get("stalled_sessions")
        try:
            if stalled is not None and int(stalled) >= 2:
                n += 1
        except (TypeError, ValueError):
            continue
    return n


def _tsb_sustained_days(today_tsb: float | None, training_load: dict | None,
                        threshold: float, direction: str = "above") -> int:
    """Approximation: returns 1 when the current TSB hits the threshold
    in the given direction, otherwise 0. We don't have day-by-day TSB
    history in `training_load` (only today), so over-recovered "sustained"
    is approximated by current TSB + 7-day trend slope. The render layer
    computes the proper 14-day strip from `compute_tier_history`."""
    if today_tsb is None:
        return 0
    if direction == "above" and today_tsb >= threshold:
        return 1
    if direction == "below" and today_tsb <= threshold:
        return 1
    return 0


def compute_session_recommendation(*,
                                    recovery: dict | None,
                                    training_load: dict | None,
                                    acwr: dict | None,
                                    weekly_volume: dict | None,
                                    sleep_regularity: dict | None,
                                    sleep_summary: dict | None,
                                    estimated_1rm: dict | None,
                                    hr_at_volume_divergence: dict | None,
                                    deloads: list[str] | None,
                                    auto_deload_candidates: list[str] | None,
                                    health_all: list[dict],
                                    today_d: date,
                                    estimated_max_hr: float | None) -> dict:
    """Top-down 5-tier gate. First gate to fire wins. Returns the
    operational recommendation that the SKILL.md prompt MUST honor before
    generating any workout.

    Tiers (highest priority first):
      A — illness / acute rest
      B — reactive deload (HRV crash, TSB high fatigue, MRV breach,
          spike, stalled lifts, unmarked deload candidate)
      C — downgrade (modified strength is OK)
      D — green (train as planned)
      E — over-recovered (train normal + taper warning)

    Returns a dict with `tier`, `label`, `headline`, `substitute`,
    `rationale` list, and `override_*` fields.
    """
    from constants import SESSION_GATE_THRESHOLDS as T  # local import

    drivers = (recovery or {}).get("drivers") or []
    hrv_d = next((d for d in drivers if d.get("metric") == "hrv_sdnn"), None)
    rhr_d = next((d for d in drivers if d.get("metric") == "resting_hr"), None)
    hrv_z = hrv_d.get("z") if hrv_d else None
    rhr_z = rhr_d.get("z") if rhr_d else None
    recovery_score = (recovery or {}).get("score")

    tsb = (training_load or {}).get("tsb")
    wow_pct = (acwr or {}).get("wow_change_pct")

    over_mrv_muscles = _muscles_over_mrv(weekly_volume)
    n_over_mrv = len(over_mrv_muscles)

    wrist_temp_dev = _wrist_temp_deviation_c(health_all, today_d)
    rhr_streak = _rhr_sustained_elevation_days(
        health_all, today_d, T["tier_a_rhr_dev_bpm"], baseline_days=14)
    stalled = _count_stalled_lifts(estimated_1rm)

    sleep_means = (sleep_summary or {}).get("means_h") or {}
    sleep_7d_mean = sleep_means.get("total")
    sleep_last_night = None
    # Latest sleep_total_h value (within the last 2 days)
    for e in reversed(health_all):
        d = _parse_iso_date(e.get("date"))
        v = e.get("sleep_total_h")
        if d is None or v is None:
            continue
        if (today_d - d).days <= 1:
            try:
                sleep_last_night = float(v)
            except (TypeError, ValueError):
                pass
            break
        if (today_d - d).days > 2:
            break
    sri = (sleep_regularity or {}).get("sri")

    unmarked_deload_recent = False
    if auto_deload_candidates:
        for ds in auto_deload_candidates:
            d = _parse_iso_date(ds)
            if d is None:
                continue
            if (today_d - d).days <= 7:
                unmarked_deload_recent = True
                break

    hr_creep_muscles = []
    for muscle, info in (hr_at_volume_divergence or {}).items():
        hint = (info or {}).get("hint") or ""
        if hint.startswith("rising"):
            hr_creep_muscles.append(muscle)

    rationale: list[dict] = []

    def add(signal, value, threshold, note):
        rationale.append({
            "signal": signal, "value": value,
            "threshold": threshold, "note": note,
        })

    # ---- TIER A: illness / acute rest ----
    tier_a_fired = False
    if (wrist_temp_dev is not None and wrist_temp_dev >= T["tier_a_wrist_temp_dev_c"]
            and hrv_z is not None and hrv_z <= T["tier_a_hrv_z_paired_with_temp"]):
        tier_a_fired = True
        add("wrist_temp_c", wrist_temp_dev, T["tier_a_wrist_temp_dev_c"],
            f"+{wrist_temp_dev:.2f}°C vs 60-day baseline (pre-illness range per Oura)")
        add("hrv_sdnn_z", round(hrv_z, 2), T["tier_a_hrv_z_paired_with_temp"],
            "autonomic suppression alongside temperature rise")
    if rhr_streak >= T["tier_a_rhr_sustained_days"]:
        tier_a_fired = True
        add("rhr_sustained_days", rhr_streak, T["tier_a_rhr_sustained_days"],
            f"RHR sustained ≥+{T['tier_a_rhr_dev_bpm']:.0f} bpm above 14-day baseline for {rhr_streak} consecutive days")
    if (recovery_score is not None and recovery_score < T["tier_a_recovery_score_crash"]
            and hrv_z is not None and hrv_z <= T["tier_a_hrv_z_crash"]
            and rhr_z is not None and rhr_z >= T["tier_a_rhr_z_crash"]):
        tier_a_fired = True
        add("recovery_crash", recovery_score, T["tier_a_recovery_score_crash"],
            f"Recovery {recovery_score:.1f}/10 with HRV z {hrv_z:+.2f} and RHR z {rhr_z:+.2f} — autonomic crash triad")

    if tier_a_fired:
        return {
            "tier": "A",
            "label": "rest",
            "headline": "Rest today.",
            "substitute": {
                "kind": "rest",
                "prescription": "20-min easy walk · hydration · sleep priority · no structured exercise",
                "duration_min": 20,
                "notes": "Re-evaluate tomorrow. Resume normal training only when wrist temp + RHR return to baseline and HRV is back in the 60-day band.",
            },
            "rationale": rationale[:5],
            "override_allowed": True,
            "override_message": "If you insist on training, hold to RPE ≤6 and Zone 2 only. The default recommendation is rest.",
        }

    # ---- TIER B: reactive deload ----
    tier_b_fired = False
    tier_b_kind = None  # zone_2 / reactive_deload_week / mobility_sauna
    if tsb is not None and tsb <= T["tier_b_tsb_high_fatigue"]:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "zone_2"
        add("tsb", tsb, T["tier_b_tsb_high_fatigue"],
            f"Freshness (TSB) {tsb:+.1f} ≤ {T['tier_b_tsb_high_fatigue']:.0f} — high accumulated fatigue")
    if hrv_z is not None and hrv_z <= T["tier_b_hrv_z_sustained"]:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "zone_2"
        add("hrv_sdnn_z", round(hrv_z, 2), T["tier_b_hrv_z_sustained"],
            f"HRV z {hrv_z:+.2f} sustained below 60-day baseline (Altini maladaptation signal)")
    if n_over_mrv >= T["tier_b_muscles_over_mrv_count"]:
        tier_b_fired = True
        tier_b_kind = "reactive_deload_week"  # MRV breach forces the week-long deload
        names = ", ".join(over_mrv_muscles[:5])
        add("muscles_over_mrv", n_over_mrv, T["tier_b_muscles_over_mrv_count"],
            f"{n_over_mrv} muscles over MRV ({names}) — RP MRV-breach protocol triggers a reactive deload")
    if unmarked_deload_recent:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "reactive_deload_week"
        add("auto_deload_candidate", "yes", "—",
            "auto-deload candidate flagged in the last 7 days; the data already looked like a deload was needed")
    if wow_pct is not None and wow_pct >= T["tier_b_wow_spike_pct"]:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "zone_2"
        add("wow_change_pct", round(wow_pct, 1), T["tier_b_wow_spike_pct"],
            f"week-over-week training stress +{wow_pct:.0f}% — sharp ramp into red, cap the next 7 days at +10%")
    if stalled >= T["tier_b_stalled_lifts_count"]:
        tier_b_fired = True
        tier_b_kind = tier_b_kind or "reactive_deload_week"
        add("stalled_lifts", stalled, T["tier_b_stalled_lifts_count"],
            f"{stalled} top lifts have stalled (≥2 consecutive sessions of regression) — Tuchscherer reactive-deload trigger")

    if tier_b_fired:
        if tier_b_kind == "reactive_deload_week":
            substitute = {
                "kind": "reactive_deload_week",
                "prescription": "deload week: cut working-set count to ~50%, hold loads, drop conditioning finishers, rotate over-MRV exercises to a different movement pattern",
                "duration_min": None,
                "notes": "Return to normal volume next week if recovery score ≥6 and HRV trend back in band.",
            }
            headline = "Reactive deload this week."
        else:
            zone2_hr = int((estimated_max_hr or 195) * 0.65) if estimated_max_hr else None
            zone2_hint = f" at ~{zone2_hr} bpm" if zone2_hr else ""
            substitute = {
                "kind": "zone_2",
                "prescription": f"Zone 2 cardio 45–60 min{zone2_hint} · mobility 15 min · sauna 15 min optional · no strength today",
                "duration_min": 60,
                "notes": "Re-evaluate tomorrow. If HRV recovers and TSB lifts, you can resume strength.",
            }
            headline = "Zone 2 day, not strength."
        return {
            "tier": "B",
            "label": "reactive_deload",
            "headline": headline,
            "substitute": substitute,
            "rationale": rationale[:5],
            "override_allowed": True,
            "override_message": "If you insist on strength, cap at RPE 6, drop volume by 50%, and skip the finisher.",
        }

    # ---- TIER C: downgrade (modified strength is fine) ----
    tier_c_fired = False
    if recovery_score is not None and T["tier_c_recovery_score_lo"] <= recovery_score <= T["tier_c_recovery_score_hi"]:
        tier_c_fired = True
        add("recovery_score", recovery_score, T["tier_c_recovery_score_hi"],
            f"Recovery {recovery_score:.1f}/10 — moderate (not critically low)")
    if hrv_z is not None and T["tier_c_hrv_z_lo"] < hrv_z <= T["tier_c_hrv_z_hi"]:
        tier_c_fired = True
        add("hrv_sdnn_z", round(hrv_z, 2), T["tier_c_hrv_z_hi"],
            f"HRV z {hrv_z:+.2f} mildly below baseline")
    if sleep_last_night is not None and sleep_last_night < T["tier_c_sleep_total_h_floor"]:
        tier_c_fired = True
        add("sleep_last_night_h", round(sleep_last_night, 2), T["tier_c_sleep_total_h_floor"],
            f"last night {sleep_last_night:.2f}h, below the {T['tier_c_sleep_total_h_floor']:.0f}h floor")
    elif sleep_7d_mean is not None and sleep_7d_mean < T["tier_c_sleep_7d_mean_floor"]:
        tier_c_fired = True
        add("sleep_7d_mean_h", round(sleep_7d_mean, 2), T["tier_c_sleep_7d_mean_floor"],
            f"7-day sleep mean {sleep_7d_mean:.2f}h below the {T['tier_c_sleep_7d_mean_floor']:.0f}h floor")
    if sri is not None and sri < T["tier_c_sri_floor"]:
        tier_c_fired = True
        add("sleep_regularity_index", round(sri, 1), T["tier_c_sri_floor"],
            f"SRI {sri:.0f} below UK Biobank bottom-quintile cutoff ({T['tier_c_sri_floor']:.0f})")
    if rhr_z is not None and rhr_z >= T["tier_c_rhr_z_floor"]:
        tier_c_fired = True
        add("rhr_z", round(rhr_z, 2), T["tier_c_rhr_z_floor"],
            f"RHR z {rhr_z:+.2f} above baseline")
    if n_over_mrv >= T["tier_c_muscles_over_mrv_count"]:
        tier_c_fired = True
        names = ", ".join(over_mrv_muscles[:5])
        add("muscles_over_mrv", n_over_mrv, T["tier_c_muscles_over_mrv_count"],
            f"{n_over_mrv} muscle(s) over MRV ({names}) — modify the affected groups")
    if hr_creep_muscles:
        tier_c_fired = True
        names = ", ".join(hr_creep_muscles[:5])
        add("hr_at_volume_divergence", len(hr_creep_muscles), 1,
            f"HR rising at constant volume on {names} — hold loads on those groups")

    if tier_c_fired:
        return {
            "tier": "C",
            "label": "downgrade",
            "headline": "Modified strength: hold loads, cut accessories.",
            "substitute": {
                "kind": "modified_strength",
                "prescription": f"keep the planned session pattern · −{T['tier_c_downgrade_volume_pct']:.0f}% volume on secondary lifts · hold loads on every working set · drop conditioning finisher · no PR attempts",
                "duration_min": None,
                "notes": "Compound lifts stay at planned volume; isolations halve. Re-assess tomorrow.",
            },
            "rationale": rationale[:5],
            "override_allowed": True,
            "override_message": "If recovery rebounds tomorrow, resume full volume.",
        }

    # ---- TIER E: over-recovered taper warning ----
    if tsb is not None and tsb >= T["tier_e_tsb_high"]:
        add("tsb", tsb, T["tier_e_tsb_high"],
            f"Freshness (TSB) {tsb:+.1f} ≥ {T['tier_e_tsb_high']:.0f} — fitness is bleeding off, you've been over-recovered")
        return {
            "tier": "E",
            "label": "over_recovered",
            "headline": "Train as planned — but you've been over-recovered, fitness is bleeding off.",
            "substitute": {
                "kind": "normal_strength",
                "prescription": "resume normal training load · don't sit in the taper any longer",
                "duration_min": None,
                "notes": "If TSB stays above +10 for another week without a race, you're losing CTL needlessly.",
            },
            "rationale": rationale[:3],
            "override_allowed": True,
            "override_message": "",
        }

    # ---- TIER D: green ----
    if recovery_score is not None:
        add("recovery_score", recovery_score, T["tier_d_recovery_score_min"],
            f"Recovery {recovery_score:.1f}/10 — green")
    if tsb is not None:
        add("tsb", tsb, None,
            f"Freshness (TSB) {tsb:+.1f} in the productive zone")
    return {
        "tier": "D",
        "label": "green",
        "headline": "Train as planned.",
        "substitute": {
            "kind": "normal_strength",
            "prescription": "execute the planned session with the load rules from SKILL.md §6",
            "duration_min": None,
            "notes": "Green light. Hard training is on the table today.",
        },
        "rationale": rationale[:3],
        "override_allowed": True,
        "override_message": "",
    }


# Tier-history strip: walk back N days, re-running the gate against a
# rolling-window view of `today`. Used for the Trajectory tab's
# "Decision history" component (last 14 days of tier classifications).

def compute_tier_history(*,
                         days: int = 14,
                         today_d: date,
                         health_all: list[dict],
                         monthly_sessions: list[dict],
                         weekly_volume: dict | None,
                         sleep_nights_all: list[dict],
                         sleep_regularity_today: dict | None,
                         sleep_summary_today: dict | None,
                         estimated_1rm: dict | None,
                         hr_at_volume_divergence: dict | None,
                         deloads: list[str] | None,
                         auto_deload_candidates: list[str] | None,
                         capabilities: dict,
                         estimated_max_hr: float | None,
                         estimated_rest_hr: float | None) -> list[dict]:
    """For each of the last ``days`` days, recompute the recovery score,
    training load (CTL/ATL/TSB), ACWR, and run the gate to determine that
    day's tier. Returns a list of ``{date, tier, dominant_signal}`` entries
    sorted oldest first.

    Approximation: weekly_volume, sleep_regularity, sleep_summary,
    estimated_1rm, hr_at_volume_divergence, deloads, and
    auto_deload_candidates use TODAY's snapshot at every back-step (these
    move slowly and a per-day recompute would be expensive). The history
    is most accurate for the fast-moving signals (recovery, TSB, ACWR) —
    which dominate Tier A/B classification anyway.
    """
    from cardio import compute_acwr, training_load_summary, trimp_per_session  # local
    out: list[dict] = []
    # Recompute per-session TRIMPs once over the full window; faster than
    # per-day. Then build training load and ACWR per back-step.
    trimps = trimp_per_session(monthly_sessions, estimated_max_hr, estimated_rest_hr)
    for offset in range(days - 1, -1, -1):
        d = today_d - timedelta(days=offset)
        # Lightweight per-day re-computations of the fast signals
        rec_d = recovery_score(health_all, d, capabilities)
        tl_d = training_load_summary(trimps, d)
        acwr_d = compute_acwr(trimps, d)
        rec_dict = compute_session_recommendation(
            recovery=rec_d,
            training_load=tl_d,
            acwr=acwr_d,
            weekly_volume=weekly_volume,
            sleep_regularity=sleep_regularity_today,
            sleep_summary=sleep_summary_today,
            estimated_1rm=estimated_1rm,
            hr_at_volume_divergence=hr_at_volume_divergence,
            deloads=deloads,
            auto_deload_candidates=auto_deload_candidates,
            health_all=health_all,
            today_d=d,
            estimated_max_hr=estimated_max_hr,
        )
        dominant_signal = ""
        rationale = rec_dict.get("rationale") or []
        if rationale:
            dominant_signal = rationale[0].get("signal") or ""
        out.append({
            "date": d.isoformat(),
            "tier": rec_dict["tier"],
            "label": rec_dict["label"],
            "dominant_signal": dominant_signal,
        })
    return out


def read_longevity_state(person: str, today_d: date) -> dict | None:
    """Parse the person's longevity ``.md`` files into a structured state
    block for the Trajectory tab's personalized risk panel.

    Reads (where present) ``profile.md``, ``state.md``, ``interventions.md``,
    ``biomarkers.md`` from ``<root>/<Person>/data/longevity/`` and surfaces:

    - ``has_profile``: whether a longevity profile exists for this person
    - ``age`` computed from DOB
    - ``sex``, ``height_cm``, ``location``
    - ``family_history``: list of strings
    - ``constraints``: long-term constraints (vegan, alcohol-free, etc.)
    - ``active_conditions``: list of strings
    - ``medications``: list of strings
    - ``bloodwork_status``: "none-yet" / "panel-on-file"
    - ``risk_flags``: list of dicts {key, label, status, hint} where
      ``status`` is one of "tracked" / "due" / "overdue" / "active".

    Returns ``None`` when the directory doesn't exist (so Fabian without a
    longevity/ folder gets a clean "no profile" state). Renderer reads
    this directly.
    """
    from pathlib import Path as _Path
    skills_root = _Path(__file__).resolve().parents[3]
    person_root = skills_root / person / "data" / "longevity"
    if not person_root.exists():
        return None

    def _read(name: str) -> str:
        path = person_root / name
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    profile_md = _read("profile.md")
    state_md = _read("state.md")
    interventions_md = _read("interventions.md")
    biomarkers_md = _read("biomarkers.md")

    out: dict = {"has_profile": True}

    # Parse DOB / sex / height / location
    import re as _re
    dob_match = _re.search(r"Date of birth.*?(\d{4}-\d{2}-\d{2})", profile_md)
    if dob_match:
        try:
            dob = datetime.strptime(dob_match.group(1), "%Y-%m-%d").date()
            out["dob"] = dob.isoformat()
            out["age"] = (today_d - dob).days // 365
        except ValueError:
            pass
    sex_match = _re.search(r"Sex.*?:\s*([A-Za-z]+)", profile_md)
    if sex_match:
        out["sex"] = sex_match.group(1).strip().lower()
    height_match = _re.search(r"Height.*?:\s*([\d.]+)\s*cm", profile_md)
    if height_match:
        out["height_cm"] = float(height_match.group(1))
    loc_match = _re.search(r"Location.*?:\s*([^\n]+)", profile_md)
    if loc_match:
        out["location"] = loc_match.group(1).strip()

    # Family history block
    fam_lines: list[str] = []
    in_fam = False
    for ln in profile_md.splitlines():
        if ln.strip().lower().startswith("# family history"):
            in_fam = True
            continue
        if in_fam:
            if ln.startswith("#"):
                break
            if ln.strip().startswith("- "):
                fam_lines.append(ln.strip()[2:].strip())
    out["family_history"] = fam_lines

    # Long-term constraints
    cons_lines: list[str] = []
    in_cons = False
    for ln in profile_md.splitlines():
        if ln.strip().lower().startswith("# long-term constraints"):
            in_cons = True
            continue
        if in_cons:
            if ln.startswith("#"):
                break
            if ln.strip().startswith("- "):
                cons_lines.append(ln.strip()[2:].strip())
    out["constraints"] = cons_lines

    # Active conditions
    cond_lines: list[str] = []
    in_cond = False
    for ln in state_md.splitlines():
        if ln.strip().lower().startswith("# active conditions"):
            in_cond = True
            continue
        if in_cond:
            if ln.startswith("# ") and "active conditions" not in ln.lower():
                break
            if ln.strip().startswith("- "):
                cond_lines.append(ln.strip()[2:].strip())
    out["active_conditions"] = cond_lines

    # Medications
    med_lines: list[str] = []
    in_med = False
    for ln in state_md.splitlines():
        if ln.strip().lower().startswith("# current medications"):
            in_med = True
            continue
        if in_med:
            if ln.startswith("# ") and "medication" not in ln.lower():
                break
            if ln.strip().startswith("- "):
                med_lines.append(ln.strip()[2:].strip())
    out["medications"] = med_lines

    # Bloodwork status: heuristic — "No blood work conducted yet" / dated panel
    if "no blood work" in biomarkers_md.lower() or "first panel planned" in biomarkers_md.lower():
        out["bloodwork_status"] = "none-yet"
    elif _re.search(r"##\s+\d{4}-\d{2}-\d{2}", biomarkers_md):
        out["bloodwork_status"] = "panel-on-file"
    else:
        out["bloodwork_status"] = "unknown"

    # Build personalized risk flags from parsed text.
    flags: list[dict] = []
    profile_text = (profile_md + state_md).lower()
    family_text = " ".join(fam_lines).lower()
    cond_text = " ".join(cond_lines).lower()
    med_text = " ".join(med_lines).lower()
    constraints_text = " ".join(cons_lines).lower()

    if "parkinson" in family_text:
        flags.append({
            "key":    "parkinson_surveillance",
            "label":  "Parkinson early-marker watch",
            "status": "tracked",
            "hint":   "Two-generation paternal family history. Watch REM sleep behavior (acted-out dreams), olfactory function, autonomic symptoms.",
        })
    if "prep" in med_text or "prep" in (state_md.lower()):
        flags.append({
            "key":    "prep_monitoring",
            "label":  "PrEP renal + BMD monitoring",
            "status": "due" if out.get("bloodwork_status") == "none-yet" else "tracked",
            "hint":   "Tenofovir is associated with renal and bone-density changes. eGFR (cystatin-C variant) + DEXA recommended at baseline and periodically.",
        })
    if "vegan" in constraints_text or "vegan" in profile_text:
        flags.append({
            "key":    "vegan_micronutrient_panel",
            "label":  "Vegan micronutrient panel",
            "status": "due" if out.get("bloodwork_status") == "none-yet" else "tracked",
            "hint":   "Test ferritin (not just hemoglobin), homocysteine (functional B12), serum + spot urine zinc / iodine, omega-3 index, 25-OH-D.",
        })
    # Berlin / 52°N vitamin D winter window.
    location_text = (out.get("location") or "").lower()
    if "berlin" in location_text or "52°n" in location_text or "52n" in location_text:
        month = today_d.month
        in_winter = month <= 3 or month >= 10
        flags.append({
            "key":    "vitamin_d_winter",
            "label":  "Vitamin D supplementation window",
            "status": "active" if in_winter else "tracked",
            "hint":   ("Cutaneous synthesis is ~0 from October through March at 52°N. "
                       "Test 25-OH-D late winter to isolate the supplementation effect.")
                       if in_winter else "Outside the supplementation-mandatory window.",
        })
    if "atopic dermatitis" in cond_text and "active" in cond_text:
        flags.append({
            "key":    "atopic_dermatitis",
            "label":  "Atopic dermatitis",
            "status": "active",
            "hint":   "Active on hands. Topical cortisone for flares, hand cream 2-3x/day. Watch for sleep impact from itch.",
        })
    if out.get("bloodwork_status") == "none-yet":
        flags.append({
            "key":    "first_blood_panel",
            "label":  "First lab panel",
            "status": "due",
            "hint":   "Foundational longevity panel: lipids (ApoB, Lp(a), LDL, HDL, TG), fasting glucose, HbA1c, fasting insulin, hsCRP, eGFR, ferritin, B12, 25-OH-D.",
        })
    out["risk_flags"] = flags

    return out
