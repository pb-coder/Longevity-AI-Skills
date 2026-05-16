"""Shared importer transforms.

Parsers stay source-specific, but transforms that turn canonical workout rows
into tracker write payloads belong here so Apple XML and HLExport do not drift.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping


def build_auto_cardio_payload(
    workout_rows: Iterable[dict],
    *,
    eligible_types: set[str],
    type_to_exercise: Mapping[str, str],
    machine_tag_for: Callable[[dict], str | None] | None = None,
) -> list[dict]:
    """Convert workout-session rows into ``upsert_monthly_cardio`` payloads."""
    payload: list[dict] = []
    for workout in workout_rows:
        apple_type = workout.get("apple_type") or ""
        if apple_type not in eligible_types:
            continue
        tracker_name = type_to_exercise.get(apple_type)
        if not tracker_name:
            continue
        machine_tag = machine_tag_for(workout) if machine_tag_for else None
        row = {
            "date":         workout.get("date"),
            "exercise":     tracker_name,
            "duration_min": workout.get("duration_min"),
            "distance_km":  workout.get("distance_km"),
            "avg_hr":       workout.get("avg_hr"),
            "active_cal":   workout.get("active_cal"),
            "total_cal":    workout.get("total_cal"),
            "elevation_m":  workout.get("elevation_m"),
            "elapsed_min":  workout.get("elapsed_min"),
        }
        if machine_tag:
            row["machine_tag"] = machine_tag
        payload.append(row)
    return payload
