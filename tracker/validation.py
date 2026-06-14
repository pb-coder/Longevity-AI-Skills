"""Runtime validators for JSON handed between tracker commands."""
from __future__ import annotations

import re

# Hardcoded mirror of the TypedDict surface in ``tracker.contracts``. Keyed by
# contract name so the validator never has to import ``tracker.contracts`` (or
# the stdlib ``typing`` module that comes with it) at runtime. The cumulative
# import cost on the render cold path is ~4ms across ``typing`` + ``tracker``
# + ``tracker.contracts``; switching to string-keyed metadata + a string
# type-annotation surface lets ``tracker.validation`` import nothing beyond
# ``re``. When a TypedDict field is added or removed in ``tracker.contracts``,
# update the matching entry here -- ``test_tracker_validators.py`` exercises
# the unknown-key warning paths.
_CONTRACT_DECLARED_KEYS: "dict[str, frozenset[str]]" = {
    "TrackerJSON": frozenset({
        "today", "data_source", "capabilities", "auto_cardio_enabled",
        "monthly_sessions", "weekly_volume_per_muscle", "estimated_1rm",
        "progression_summary", "stale_exercises", "unknown_exercises",
        "deloads", "auto_deload_candidates", "cardio_last_28d",
        "cardio_hr_zones_28d", "swim_summary", "sleep_summary",
        "thermal_summary", "light_therapy_summary", "nutrition_phase",
        "daily_activity_28d", "recovery", "training_load",
        "training_load_by_modality",
        "hr_at_volume_divergence", "age_years", "estimated_max_hr",
        "estimated_rest_hr", "bodyweight_latest",
        "bodyweight_trend_kg_per_week", "bodyweight_weekly",
        "health_metrics_weekly", "health_metrics_recent",
        "vo2max_latest", "vo2max_trend_per_4w", "week_over_week",
        "session_recommendation", "tier_history", "longevity_score",
        "longevity_state", "vo2_percentile", "hr_recovery", "acwr",
        "sleep_regularity", "rem_anomaly", "movement_consistency", "rows",
    }),
    "Recovery": frozenset({"score", "confidence", "drivers"}),
    "TrainingLoad": frozenset({"ctl", "atl", "tsb", "trend_7d", "load_band"}),
    "SessionRecommendation": frozenset({
        "tier", "label", "headline", "substitute", "rationale",
        "override_allowed", "override_message",
        "expected_rebound_by_session",
    }),
    "SessionSubstitute": frozenset({
        "kind", "prescription", "duration_min", "notes",
    }),
}

_FLOAT_OR_NONE_KEYS: "dict[str, frozenset[str]]" = {
    "Recovery": frozenset({"score"}),
    "TrainingLoad": frozenset({"ctl", "atl", "tsb"}),
}

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _declared_keys(contract_name):
    return _CONTRACT_DECLARED_KEYS.get(contract_name, frozenset())


def _warn_unknown_keys(obj, contract_name, label, warnings):
    if not isinstance(obj, dict):
        return
    allowed = _declared_keys(contract_name)
    for key in sorted(set(obj) - allowed):
        warnings.append(f"{label}.{key} is not declared in {contract_name}")


def _expects_float_or_none(contract_name, key):
    return key in _FLOAT_OR_NONE_KEYS.get(contract_name, frozenset())


def _validate_float_or_none(obj, contract_name, label, errors):
    for key in _declared_keys(contract_name):
        if key not in obj or not _expects_float_or_none(contract_name, key):
            continue
        value = obj[key]
        if value is not None and not isinstance(value, (int, float)):
            errors.append(f"{label}.{key} must be a number or null")


def _validate_nested_dict(obj, contract_name, label, errors, warnings):
    if obj is None:
        return
    if not isinstance(obj, dict):
        errors.append(f"{label} must be an object")
        return
    _warn_unknown_keys(obj, contract_name, label, warnings)
    _validate_float_or_none(obj, contract_name, label, errors)


def validate_tracker_json(j):
    """Validate tracker JSON before dashboard rendering.

    Unknown keys are warnings so newer producer fields do not break older
    renderers. Missing or invalid load-bearing fields are errors because the
    renderer cannot produce a coherent dashboard without them.
    """
    errors = []
    warnings = []

    if not isinstance(j, dict):
        return (["tracker JSON must be a JSON object"], warnings)

    _warn_unknown_keys(j, "TrackerJSON", "tracker", warnings)

    today = j.get("today")
    if not isinstance(today, str) or not _ISO_DATE_RE.match(today):
        errors.append("tracker.today must be a YYYY-MM-DD string")

    _validate_nested_dict(j.get("recovery"), "Recovery", "tracker.recovery", errors, warnings)
    _validate_nested_dict(
        j.get("training_load"),
        "TrainingLoad",
        "tracker.training_load",
        errors,
        warnings,
    )
    _validate_nested_dict(
        j.get("session_recommendation"),
        "SessionRecommendation",
        "tracker.session_recommendation",
        errors,
        warnings,
    )
    session_rec = j.get("session_recommendation")
    if isinstance(session_rec, dict) and isinstance(session_rec.get("substitute"), dict):
        _warn_unknown_keys(
            session_rec["substitute"],
            "SessionSubstitute",
            "tracker.session_recommendation.substitute",
            warnings,
        )

    return (errors, warnings)
