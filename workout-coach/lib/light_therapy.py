"""Light-therapy / photobiomodulation analytics for the coach.

Consumes per-session rows from
``<person>/data/light_therapy/YYYY.MM.sessions.csv`` and returns a
structured ``light_therapy_summary`` block. Returns ``None`` when no
sessions sit in the 28-day window — ``_compact`` then drops the key
from the JSON output and the coach prompt's light-therapy section stays
silent.

Public surface:

- ``recent_light_therapy_sessions(sessions, today_d, days)`` — windowed list.
- ``light_therapy_summary(sessions, today_d, target_per_week,
  target_min_per_session)`` — the full block.

Adherence defaults are deliberately conservative — the evidence base for
light-therapy dosing is far less settled than for sauna's HSP induction.
Defaults are tunable per tracker via ``profile.csv``.
"""
from __future__ import annotations

from datetime import date, timedelta


from .parsing import _parse_iso_date


DEFAULT_LT_TARGET_PER_WEEK = 3
DEFAULT_LT_TARGET_MIN_PER_SESSION = 10


def recent_light_therapy_sessions(sessions: list[dict], today_d: date,
                                  days: int = 28) -> list[dict]:
    """Filter ``sessions`` to the last ``days`` (inclusive of today)."""
    if not sessions:
        return []
    cutoff = today_d - timedelta(days=days)
    out = []
    for s in sessions:
        d = _parse_iso_date(s.get("date"))
        if d is None:
            continue
        if d < cutoff or d > today_d:
            continue
        out.append(s)
    return out


def _dominant(counter: dict) -> str | None:
    """Return the key with the highest count, or None when empty."""
    if not counter:
        return None
    return max(counter.items(), key=lambda kv: kv[1])[0]


def _coerce_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def light_therapy_summary(
    sessions: list[dict],
    today_d: date,
    target_per_week: int = DEFAULT_LT_TARGET_PER_WEEK,
    target_min_per_session: int = DEFAULT_LT_TARGET_MIN_PER_SESSION,
) -> dict | None:
    """28-day per-session light-therapy summary, or None when no
    sessions in window.

    Returned shape (keys with None / empty distributions dropped by the
    caller's ``_compact`` helper):

        {
          "n_sessions_28d": int,
          "n_sessions_per_week": float,
          "total_minutes_28d": float,
          "minutes_per_week": float,
          "avg_session_minutes": float | None,
          "light_type_distribution": {"red+ir": int, ...} | None,
          "modality_distribution": {"cabin": int, ...} | None,
          "body_area_distribution": {"full_body": int, ...} | None,
          "adherence": {
              "target_per_week": int,
              "actual_per_week": float,
              "status": "below-target" | "on-target" | "above-target",
              "session_dose_status":
                  "below-min" | "on-target" | "above-min" | "unknown",
          }
        }
    """
    recent = recent_light_therapy_sessions(sessions, today_d, 28)
    if not recent:
        return None

    type_dist: dict[str, int] = {}
    modality_dist: dict[str, int] = {}
    area_dist: dict[str, int] = {}
    durations: list[float] = []
    total_min = 0.0

    for r in recent:
        lt = r.get("light_type")
        if lt:
            type_dist[lt] = type_dist.get(lt, 0) + 1
        md = r.get("modality")
        if md:
            modality_dist[md] = modality_dist.get(md, 0) + 1
        ba = r.get("body_area")
        if ba:
            area_dist[ba] = area_dist.get(ba, 0) + 1
        dur = _coerce_float(r.get("duration_min"))
        if dur is not None:
            durations.append(dur)
            total_min += dur

    n = len(recent)
    per_week = round(n / 4.0, 2)
    avg_session_min = (sum(durations) / len(durations)) if durations else None

    if per_week < target_per_week - 0.5:
        status = "below-target"
    elif per_week > target_per_week + 1.5:
        status = "above-target"
    else:
        status = "on-target"

    if avg_session_min is None:
        dose_status = "unknown"
    elif avg_session_min < target_min_per_session - 1:
        dose_status = "below-min"
    elif avg_session_min > target_min_per_session * 2:
        dose_status = "above-min"
    else:
        dose_status = "on-target"

    return {
        "n_sessions_28d":          n,
        "n_sessions_per_week":     per_week,
        "total_minutes_28d":       round(total_min, 1) if durations else None,
        "minutes_per_week":        round(total_min / 4.0, 1) if durations else None,
        "avg_session_minutes":     round(avg_session_min, 1) if avg_session_min is not None else None,
        "light_type_distribution": type_dist or None,
        "modality_distribution":   modality_dist or None,
        "body_area_distribution":  area_dist or None,
        "dominant_light_type":     _dominant(type_dist),
        "dominant_modality":       _dominant(modality_dist),
        "adherence": {
            "target_per_week":       target_per_week,
            "actual_per_week":       per_week,
            "status":                status,
            "target_min_per_session": target_min_per_session,
            "session_dose_status":   dose_status,
        },
    }
