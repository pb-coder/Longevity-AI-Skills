"""Calendar and observation context for planning the next strength week."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from .parsing import _parse_iso_date


def week_context(as_of: date, start: str | None, days: str | None,
                 session_count: int | None, target_minutes: float,
                 published: list[dict] | None = None) -> dict:
    """Plan Monday onward on weekends, or from the review date midweek."""
    if start is not None:
        week_start = _parse_iso_date(start)
    else:
        week_start = _default_start(as_of, published or [])
    if week_start is None:
        raise ValueError("--week-start must be a valid YYYY-MM-DD date")
    week_end = week_start + timedelta(days=6)
    if week_end < as_of:
        raise ValueError("the planning week must include or follow the review date")

    scheduled: list[date] = []
    if days is not None:
        retained = {
            day
            for record in published or []
            if record["prescription"]["week_start"] == week_start.isoformat()
            for session in record["prescription"]["sessions"]
            if (day := _parse_iso_date(session.get("date"))) is not None and day < as_of
        }
        for value in days.split(","):
            day = _parse_iso_date(value.strip())
            if day is None or not week_start <= day <= week_end or (day < as_of and day not in retained):
                raise ValueError("--training-days requires dates in the available planning period")
            scheduled.append(day)
       # A revision can list just the remaining dates.
        scheduled.extend(retained.difference(scheduled))
        if len(scheduled) != len(set(scheduled)):
            raise ValueError("--training-days requires distinct dates")
        if session_count is not None and session_count != len(scheduled):
            raise ValueError("--sessions must match the number of --training-days")
        session_count = len(scheduled)
    if session_count is not None and not 1 <= session_count <= 14:
        raise ValueError("weekly plans require 1 to 14 strength sessions")

    return {
        "as_of": as_of.isoformat(),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "session_count": session_count,
        "session_target_min": target_minutes,
        "training_days": [day.isoformat() for day in sorted(scheduled)],
    }


def _default_start(as_of: date, published: list[dict]) -> date:
    weekend = as_of.weekday() >= 5
    start = as_of + timedelta(days=7 - as_of.weekday()) if weekend else as_of
    for record in published:
        prescription = record["prescription"]
        previous_start = date.fromisoformat(prescription["week_start"])
        previous_end = date.fromisoformat(prescription["week_end"])
        if not weekend and previous_start <= as_of <= previous_end:
            return previous_start
        if as_of <= previous_start <= start + timedelta(days=6) and previous_end >= start:
            return previous_start
        if previous_start <= start <= previous_end:
            start = previous_end + timedelta(days=1)
    return start


def _observation_dates(rows: Iterable[dict], as_of: date,
                       key: str | None = None) -> set[date]:
    return {
        day for row in rows
        if (key is None or row.get(key) is not None)
        and (day := _parse_iso_date(row.get("date"))) is not None
        and day <= as_of
    }


def _coverage(dates: set[date], as_of: date) -> dict:
    latest = max(dates, default=None)
    window_start = as_of - timedelta(days=13)
    return {
        "state": "observed" if latest else "no_observations",
        "latest_observed": latest.isoformat() if latest else None,
        "days_since_observation": (as_of - latest).days if latest else None,
        "observed_days_14d": sum(day >= window_start for day in dates),
    }


def observation_coverage(as_of: date, health: list[dict], nights: list[dict],
                         recorded_workouts: list[dict], strength_sets: Iterable[dict],
                         capabilities: dict, receipts: list[dict]) -> dict:
    """Describe known samples and import ranges without treating blanks as rest."""
    metrics = {
        "strength_sets": _coverage(_observation_dates(strength_sets, as_of), as_of),
        "device_workouts": _coverage(_observation_dates(recorded_workouts, as_of), as_of),
        "bodyweight": _coverage(_observation_dates(health, as_of, "bodyweight_kg"), as_of),
        "resting_hr": _coverage(_observation_dates(health, as_of, "resting_hr"), as_of),
        "sleep": _coverage(
            _observation_dates(nights, as_of, "total_h")
            | _observation_dates(health, as_of, "sleep_total_h"),
            as_of,
        ),
    }
    for source_key, metric in (("hrv", "hrv_sdnn"), ("wrist_temp", "wrist_temp_c")):
        metrics[source_key] = (
            {"state": "source_unavailable"} if capabilities.get(source_key) is False
            else _coverage(_observation_dates(health, as_of, metric), as_of)
        )

    iso_date = as_of.isoformat()
    known = [
        row for row in receipts
        if row.get("source") and row.get("imported_at") and row.get("applied_through")
        and (imported_on := _parse_iso_date(row.get("imported_on"))) is not None
        and imported_on <= as_of
    ]
    import_info = {"state": "unknown"}
    if known:
        latest = max(known, key=lambda row: row["imported_at"])
        import_info = {
            "state": "recorded",
            "max_applied_through": min(iso_date, max(row["applied_through"] for row in known)),
            "latest_import": {
                key: latest[key] for key in (
                    "source", "exported_at", "export_start", "export_end",
                    "applied_from", "applied_through", "imported_at",
                ) if latest.get(key)
            },
        }
    return {
        "metrics": metrics,
        "health_imports": import_info,
        "unrecorded_training": "unknown",
    }
