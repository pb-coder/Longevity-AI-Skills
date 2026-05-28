"""Typed contracts for the tracker command boundaries.

The runtime still emits plain JSON-serializable dictionaries. These types
document the load-bearing shapes at construction and rendering boundaries.
Runtime validators in ``tracker.validation`` enforce the renderer seams; the
TypedDicts themselves are not a substitute for wiring a static checker into CI.
"""
from __future__ import annotations

from typing import Literal, TypedDict, Union

JsonScalar = Union[str, int, float, bool, None]
JsonValue = Union[JsonScalar, list["JsonValue"], dict[str, "JsonValue"]]

SessionKind = Literal["strength", "cardio", "other"]
Tier = Literal["A", "B", "C", "D", "E"]
Confidence = Literal["high", "medium", "low"]


class MonthlySession(TypedDict, total=False):
    date: str
    session_kind: SessionKind
    exercise_first: str | None
    active_cal: float | None
    total_cal: float | None
    elevation_m: float | None
    elapsed: str | None
    avg_hr: float | None
    duration_min: float | None
    volume: float
    max_hr: float
    is_deload: bool
    trimp: float
    load_band: str
    intensity_pct: float | None
    hr_zone_label: str | None


class RecoveryDriver(TypedDict, total=False):
    signal: str
    label: str
    value: float | None
    z: float | None
    effect: str | None
    confidence: Confidence | str
    reason: str | None


class Recovery(TypedDict, total=False):
    score: float | None
    confidence: Confidence | str
    drivers: list[RecoveryDriver]


class TrainingLoad(TypedDict, total=False):
    ctl: float | None
    atl: float | None
    tsb: float | None
    trend_7d: str | None
    load_band: str | None


SessionLabel = Literal[
    "rest",
    "reactive_deload",
    "downgrade",
    "green",
    "over_recovered",
]


class SessionSubstitute(TypedDict, total=False):
    kind: str
    prescription: str
    duration_min: float | int | None
    notes: str


class SessionRationaleEntry(TypedDict, total=False):
    signal: str
    value: JsonValue
    threshold: JsonValue
    note: str


class SessionRecommendation(TypedDict, total=False):
    tier: Tier
    label: SessionLabel
    headline: str
    substitute: SessionSubstitute | None
    rationale: list[SessionRationaleEntry]
    override_allowed: bool
    override_message: str


class CoachReads(TypedDict, total=False):
    headline: str
    cards: dict[str, str]


class TrackerJSON(TypedDict, total=False):
    today: str
    data_source: str
    capabilities: dict[str, bool]
    auto_cardio_enabled: bool
    monthly_sessions: list[MonthlySession]
    weekly_volume_per_muscle: dict[str, JsonValue]
    estimated_1rm: dict[str, JsonValue]
    progression_summary: list[dict[str, JsonValue]]
    stale_exercises: list[dict[str, JsonValue]]
    unknown_exercises: list[str]
    deloads: list[dict[str, JsonValue]]
    auto_deload_candidates: list[dict[str, JsonValue]]
    cardio_last_28d: dict[str, JsonValue]
    cardio_hr_zones_28d: dict[str, JsonValue]
    swim_summary: dict[str, JsonValue] | None
    sleep_summary: dict[str, JsonValue] | None
    thermal_summary: dict[str, JsonValue] | None
    light_therapy_summary: dict[str, JsonValue] | None
    nutrition_phase: dict[str, JsonValue] | None
    daily_activity_28d: dict[str, JsonValue]
    recovery: Recovery
    training_load: TrainingLoad
    hr_at_volume_divergence: dict[str, JsonValue]
    age_years: int | None
    estimated_max_hr: float | None
    estimated_rest_hr: float | None
    bodyweight_latest: dict[str, JsonValue] | None
    bodyweight_trend_kg_per_week: float | None
    bodyweight_weekly: list[float | None]
    health_metrics_weekly: list[dict[str, JsonValue]]
    health_metrics_recent: list[dict[str, JsonValue]] | None
    vo2max_latest: dict[str, JsonValue] | None
    vo2max_trend_per_4w: float | None
    week_over_week: dict[str, JsonValue]
    session_recommendation: SessionRecommendation
    tier_history: list[dict[str, JsonValue]]
    longevity_score: dict[str, JsonValue]
    longevity_state: dict[str, JsonValue] | None
    vo2_percentile: float | None
    hr_recovery: dict[str, JsonValue] | None
    acwr: dict[str, JsonValue] | None
    sleep_regularity: dict[str, JsonValue] | None
    rem_anomaly: dict[str, JsonValue] | None
    movement_consistency: dict[str, JsonValue] | None
    rows: list[dict[str, JsonValue]] | None
