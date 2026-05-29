"""Compatibility facade for health analytics modules.

The implementation is split by responsibility:
- health_windowing: time-series primitives and weekly aggregates
- health_recovery: recovery score and recovery drivers
- health_longevity: longevity score and longevity-state parsing
- health_session_rec: five-tier session gate and tier history

Keep importing from ``health`` in existing scripts; new code should prefer the
focused module that owns the behavior being changed.
"""
from __future__ import annotations



from .health_windowing import (
    _mean_or_none,
    _values_in_window,
    baseline_60d,
    health_metrics_weekly,
    latest_metric,
    metric_trend_per_4w,
    workout_sessions_in_window,
)
from .health_recovery import (
    RECENT_SAMPLE_SUFFICIENCY,
    SIGNAL_WEIGHT_FLOOR_FOR_GATE,
    _z_score_signal,
    recovery_score,
)
from .health_longevity import (
    _safe_norm,
    compute_longevity_score,
    read_longevity_state,
    vo2_percentile_age_sex,
)
from .health_session_rec import (
    _count_stalled_lifts,
    _muscles_over_mrv,
    _rhr_sustained_elevation_days,
    _tsb_sustained_days,
    _wrist_temp_deviation_c,
    _z_for,
    compute_session_recommendation,
    compute_tier_history,
)

__all__ = [
    "_mean_or_none",
    "_values_in_window",
    "baseline_60d",
    "health_metrics_weekly",
    "latest_metric",
    "metric_trend_per_4w",
    "workout_sessions_in_window",
    "RECENT_SAMPLE_SUFFICIENCY",
    "SIGNAL_WEIGHT_FLOOR_FOR_GATE",
    "_z_score_signal",
    "recovery_score",
    "_safe_norm",
    "compute_longevity_score",
    "read_longevity_state",
    "vo2_percentile_age_sex",
    "_count_stalled_lifts",
    "_muscles_over_mrv",
    "_rhr_sustained_elevation_days",
    "_tsb_sustained_days",
    "_wrist_temp_deviation_c",
    "_z_for",
    "compute_session_recommendation",
    "compute_tier_history",
]
