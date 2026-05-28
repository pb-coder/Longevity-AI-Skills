"""Runtime validators for JSON handed between tracker commands."""
from __future__ import annotations

import re
from typing import Any

from tracker.contracts import (
    Recovery,
    SessionRecommendation,
    SessionSubstitute,
    TrackerJSON,
    TrainingLoad,
)


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FLOAT_OR_NONE_KEYS: dict[type, set[str]] = {
    Recovery: {"score"},
    TrainingLoad: {"ctl", "atl", "tsb"},
}


def _declared_keys(contract: type) -> set[str]:
    return set(getattr(contract, "__optional_keys__", set())) | set(
        getattr(contract, "__required_keys__", set())
    )


def _warn_unknown_keys(
    obj: Any,
    contract: type,
    label: str,
    warnings: list[str],
) -> None:
    if not isinstance(obj, dict):
        return
    allowed = _declared_keys(contract)
    for key in sorted(set(obj) - allowed):
        warnings.append(f"{label}.{key} is not declared in {contract.__name__}")


def _expects_float_or_none(contract: type, key: str) -> bool:
    return key in _FLOAT_OR_NONE_KEYS.get(contract, set())


def _validate_float_or_none(
    obj: dict[str, Any],
    contract: type,
    label: str,
    errors: list[str],
) -> None:
    for key in _declared_keys(contract):
        if key not in obj or not _expects_float_or_none(contract, key):
            continue
        value = obj[key]
        if value is not None and not isinstance(value, (int, float)):
            errors.append(f"{label}.{key} must be a number or null")


def _validate_nested_dict(
    obj: Any,
    contract: type,
    label: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    if obj is None:
        return
    if not isinstance(obj, dict):
        errors.append(f"{label} must be an object")
        return
    _warn_unknown_keys(obj, contract, label, warnings)
    _validate_float_or_none(obj, contract, label, errors)


def validate_tracker_json(j: TrackerJSON) -> tuple[list[str], list[str]]:
    """Validate tracker JSON before dashboard rendering.

    Unknown keys are warnings so newer producer fields do not break older
    renderers. Missing or invalid load-bearing fields are errors because the
    renderer cannot produce a coherent dashboard without them.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(j, dict):
        return (["tracker JSON must be a JSON object"], warnings)

    _warn_unknown_keys(j, TrackerJSON, "tracker", warnings)

    today = j.get("today")
    if not isinstance(today, str) or not _ISO_DATE_RE.match(today):
        errors.append("tracker.today must be a YYYY-MM-DD string")

    _validate_nested_dict(j.get("recovery"), Recovery, "tracker.recovery", errors, warnings)
    _validate_nested_dict(
        j.get("training_load"),
        TrainingLoad,
        "tracker.training_load",
        errors,
        warnings,
    )
    _validate_nested_dict(
        j.get("session_recommendation"),
        SessionRecommendation,
        "tracker.session_recommendation",
        errors,
        warnings,
    )
    session_rec = j.get("session_recommendation")
    if isinstance(session_rec, dict) and isinstance(session_rec.get("substitute"), dict):
        _warn_unknown_keys(
            session_rec["substitute"],
            SessionSubstitute,
            "tracker.session_recommendation.substitute",
            warnings,
        )

    return (errors, warnings)
