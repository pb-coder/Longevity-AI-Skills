"""Planning projection of a weekly tracker snapshot.

The full snapshot remains available for detailed review. This projection keeps
prescriptions, restrictions, progression and reference evidence intact.
"""
from __future__ import annotations

from datetime import date, timedelta

# Only fields used in planning belong in this view. New report fields stay
# out until explicitly selected, including fields with private profile details.
_PLANNING_FIELDS = frozenset({
    "today", "weekly_plan", "observation_coverage", "existing_week",
    "exercise_fit", "data_source", "capabilities", "auto_cardio_enabled",
    "monthly_sessions", "weekly_volume_per_muscle", "estimated_1rm",
    "progression_summary", "stale_exercises", "unknown_exercises", "adherence",
    "next_dose", "block", "rotation_candidates", "muscle_priority_tiers",
    "muscle_volume_targets", "strength_sessions_per_week", "last_session_type",
    "last_session_type_reason", "volume_landmark_unit", "deloads",
    "auto_deload_candidates", "cardio_last_28d", "cardio_hr_zones_28d",
    "swim_summary", "sleep_summary", "nutrition_phase", "daily_activity_28d",
    "energy_28d", "recovery", "training_load", "training_load_by_modality",
    "hr_at_volume_divergence", "bodyweight_latest", "bodyweight_trend_kg_per_week",
    "bodyweight_trend", "waist_latest", "waist_trend_cm_per_4w", "body_fat_latest",
    "body_fat_trend_pct_per_4w", "lean_mass_latest", "lean_mass_trend_kg_per_4w",
    "vo2max_latest", "vo2max_trend_per_4w", "session_target_min",
    "target_working_sets", "session_time_model", "hr_recovery", "acwr",
    "sleep_regularity",
})


def _flat_slots_cover_sessions(block: dict) -> bool:
    """Remove grouped duplication only when every grouped field survives."""
    sessions, slots = block.get("sessions"), block.get("slots")
    if not isinstance(sessions, dict) or not isinstance(slots, list):
        return False
    for session_type, entries in sessions.items():
        if not isinstance(entries, list):
            return False
        for entry in entries:
            if not isinstance(entry, dict) or not any(
                isinstance(slot, dict) and slot.get("session_type") == session_type
                and all(slot.get(k) == v for k, v in entry.items())
                for slot in slots
            ):
                return False
    return True


def coach_context(snapshot: dict) -> dict:
    """Return a compact planning projection without mutating the snapshot."""
    result = {key: value for key, value in snapshot.items() if key in _PLANNING_FIELDS}
    weekly = result.get("weekly_plan")
    if isinstance(weekly, dict):
        existing = result.get("existing_week") or {}
        result["weekly_plan"] = {**weekly, "observed_revision": existing.get("revision", 0)}
    rotation = result.get("rotation_candidates")
    if isinstance(rotation, dict):
        result["rotation_candidates"] = {
            key: value for key, value in rotation.items() if key != "derivation"
        }
    block = result.get("block")
    if isinstance(block, dict) and _flat_slots_cover_sessions(block):
        result["block"] = {key: value for key, value in block.items() if key != "sessions"}
    sessions = result.get("monthly_sessions")
    try:
        as_of = date.fromisoformat(result["today"])
    except (KeyError, TypeError, ValueError):
        as_of = None
    if isinstance(sessions, list) and as_of:
        start = (as_of - timedelta(days=27)).isoformat()
        # Keep malformed dates instead of silently losing potentially relevant data.
        recent = []
        for entry in sessions:
            try:
                day = date.fromisoformat(entry.get("date"))
            except (AttributeError, TypeError, ValueError):
                recent.append(entry)
            else:
                if day.isoformat() >= start:
                    recent.append(entry)
        result["monthly_sessions"] = recent
        result["monthly_sessions_coverage"] = {
            "start_date": start, "end_date": as_of.isoformat(),
            "omitted_older_count": len(sessions) - len(recent),
            "note": "Summaries are limited to the last 28 days; see the full weekly snapshot for older history.",
        }
    return result
