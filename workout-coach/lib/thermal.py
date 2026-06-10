"""Thermal (sauna + cold exposure) analytics for the coach.

Consumes per-session rows from ``<person>/data/thermal/YYYY.MM.sessions.csv``
and returns a structured ``thermal_summary`` block. Returns ``None`` when
there are no sessions in the 28-day window — ``_compact`` then drops the
key from the JSON output and the coach prompt's heat / cold section stays
silent (e.g. HL trackers and XML trackers that haven't started logging).

Public surface:

- ``recent_thermal_sessions(sessions, today_d, days)`` — windowed list.
- ``thermal_summary(sessions, today_d, target_per_week)`` — the full
  block (heat block + cold block + adherence subblock).

Adherence anchors:
- **Frequency target** defaults to 4 sessions/week (Laukkanen KIHD
  mid-band; user's ``interventions.md`` cites 4-6×/week). Caller can
  override via ``target_per_week``.
- **HSP-induction threshold** is duration ≥20 min at ≥80°C
  (mechanistic + cohort sub-analysis consensus). Sessions below either
  bound count toward frequency but not toward "HSP-grade dose."
"""
from __future__ import annotations

from datetime import date, timedelta


from .parsing import _parse_iso_date


# Anchors. Kept as module constants so the coach prompt can cite them by
# name without re-deriving the math.
HSP_TEMP_THRESHOLD_C = 80
HSP_DURATION_THRESHOLD_MIN = 20
DEFAULT_HEAT_TARGET_PER_WEEK = 4
HSP_APPLICABLE_HEAT_TYPES = {"dry", "banya"}

# Cold-air dose anchor. Above this temperature, a "cold_air" session is
# barely a cold stressor — adaptation evidence is thin and norepinephrine
# response negligible. The dashboard surfaces an "amber" hint when a
# cold_air session was logged at or above this; the user knows the
# session counts as habit but not as dose. The wind/cloud/humidity caveats
# are real but a single scalar threshold is honest enough for tracking.
COLD_AIR_DOSE_FLOOR_C = 18


def recent_thermal_sessions(sessions: list[dict], today_d: date,
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


def _heat_total_min(row: dict) -> float | None:
    """Return the row's total heat minutes. Prefer the stored
    ``heat_total_min``; fall back to summing the per-round durations.
    """
    stored = row.get("heat_total_min")
    if stored is not None:
        try:
            return float(stored)
        except (TypeError, ValueError):
            pass
    durations = row.get("heat_round_durations_min") or []
    if isinstance(durations, list) and durations:
        try:
            return float(sum(float(x) for x in durations))
        except (TypeError, ValueError):
            return None
    return None


def _is_heat_session(row: dict) -> bool:
    """A row counts as a heat session when ``heat_type`` is set and not
    ``"none"`` AND it has some heat duration."""
    ht = row.get("heat_type")
    if not ht or ht == "none":
        return False
    return (_heat_total_min(row) or 0) > 0


def _is_cold_session(row: dict) -> bool:
    """A row counts as a cold session when ``cold_type`` is set and not
    ``"none"``."""
    ct = row.get("cold_type")
    return bool(ct) and ct != "none"


def _dominant(counter: dict) -> str | None:
    """Return the key with the highest count, or None when empty."""
    if not counter:
        return None
    return max(counter.items(), key=lambda kv: kv[1])[0]


def thermal_summary(
    sessions: list[dict],
    today_d: date,
    target_per_week: int = DEFAULT_HEAT_TARGET_PER_WEEK,
) -> dict | None:
    """28-day per-session heat + cold summary, or None when no sessions
    in window.

    Returned shape (compact; keys with None/empty values dropped by the
    caller's ``_compact`` helper):

        {
          "n_sessions_28d": int,
          "heat": {
              "n_sessions_28d": int,
              "n_sessions_per_week": float,
              "total_minutes_28d": float,
              "minutes_per_week": float,
              "minutes_above_hsp_threshold_per_week": float,
              "hsp_applicable_minutes_per_week": float,
              "steam_minutes_per_week": float,
              "type_distribution": {"dry": int, "steam": int, ...},
              "multi_round_sessions_pct": float,   # 0-100
              "avg_temp_c": float | None,
              "avg_session_minutes": float | None,
          },
          "cold": {
              "n_sessions_28d": int,
              "n_sessions_per_week": float,
              "type_distribution": {"cold_air": int, "cold_shower": int, ...},
              "paired_with_heat_pct": float,   # 0-100
              "dominant_type": str | None,
              "avg_cold_air_temp_c": float | None,   # mean for cold_air rows
              "avg_cold_water_temp_c": float | None, # mean for cold_plunge / cold_water rows
              "cold_air_above_dose_floor_pct": float | None,  # 0-100; flag dashboard amber when high
              "missing_temp_pct": float,             # 0-100; rows without a temp
              "recent_sessions": [                    # 1 entry per cold session, newest first
                  {
                      "date": "YYYY-MM-DD",
                      "cold_type": "cold_air",
                      "cold_duration_sec": int | None,
                      "cold_temp_c": float | None,
                      "dose_hint": "amber" | None,    # set when cold_air >= COLD_AIR_DOSE_FLOOR_C
                  },
                  …
              ],
          },
          "adherence": {
              "heat_target_per_week": int,
              "heat_actual_per_week": float,
              "heat_status": "on-target" | "below-target" | "above-target",
              "duration_status": "below-HSP-threshold" | "in-band" | "above-band",
          }
        }
    """
    recent = recent_thermal_sessions(sessions, today_d, 28)
    if not recent:
        return None

    heat_rows = [r for r in recent if _is_heat_session(r)]
    cold_rows = [r for r in recent if _is_cold_session(r)]

    # ---- Heat block ----
    heat_type_dist: dict[str, int] = {}
    heat_total_min = 0.0
    minutes_above_hsp = 0.0
    hsp_applicable_min = 0.0
    steam_min = 0.0
    multi_round_count = 0
    temp_vals: list[float] = []
    session_mins: list[float] = []
    for r in heat_rows:
        ht = r.get("heat_type") or "unknown"
        heat_type_dist[ht] = heat_type_dist.get(ht, 0) + 1
        m = _heat_total_min(r) or 0.0
        heat_total_min += m
        session_mins.append(m)
        temp = r.get("heat_temp_c")
        try:
            temp_f = float(temp) if temp is not None else None
        except (TypeError, ValueError):
            temp_f = None
        if temp_f is not None:
            temp_vals.append(temp_f)
        hsp_applicable = ht in HSP_APPLICABLE_HEAT_TYPES
        if hsp_applicable:
            hsp_applicable_min += m
            # HSP-induction band: simultaneously >= duration threshold AND
            # >= temp threshold. Without the temp we can't claim it's in band.
            if (m >= HSP_DURATION_THRESHOLD_MIN
                    and temp_f is not None
                    and temp_f >= HSP_TEMP_THRESHOLD_C):
                minutes_above_hsp += m
        elif ht == "steam":
            steam_min += m
        rounds = r.get("heat_round_durations_min") or []
        if isinstance(rounds, list) and len(rounds) > 1:
            multi_round_count += 1

    heat_block: dict = {
        "n_sessions_28d":                    len(heat_rows),
        "n_sessions_per_week":               round(len(heat_rows) / 4.0, 2),
        "total_minutes_28d":                 round(heat_total_min, 1),
        "minutes_per_week":                  round(heat_total_min / 4.0, 1),
        "minutes_above_hsp_threshold_per_week": round(minutes_above_hsp / 4.0, 1),
        "hsp_applicable_minutes_per_week":   round(hsp_applicable_min / 4.0, 1),
        "steam_minutes_per_week":            round(steam_min / 4.0, 1),
        "hsp_threshold_note":                (
            "HSP threshold applies only to dry/banya heat; steam is reported as heat habit minutes, not >=80C HSP dose."
            if steam_min else None
        ),
        "type_distribution":                 heat_type_dist or None,
        "multi_round_sessions_pct":          (
            round(multi_round_count / len(heat_rows) * 100.0, 1)
            if heat_rows else None
        ),
        "avg_temp_c":                        (
            round(sum(temp_vals) / len(temp_vals), 1) if temp_vals else None
        ),
        "avg_session_minutes":               (
            round(sum(session_mins) / len(session_mins), 1) if session_mins else None
        ),
    } if heat_rows else None

    # ---- Cold block ----
    cold_type_dist: dict[str, int] = {}
    paired_with_heat = 0
    cold_air_temps: list[float] = []
    cold_water_temps: list[float] = []
    cold_air_above_floor = 0
    cold_air_total = 0
    missing_temp = 0
    recent_cold: list[dict] = []
    for r in cold_rows:
        ct = r.get("cold_type") or "unknown"
        cold_type_dist[ct] = cold_type_dist.get(ct, 0) + 1
        if _is_heat_session(r):
            paired_with_heat += 1

        raw_temp = r.get("cold_temp_c")
        try:
            temp_f = float(raw_temp) if raw_temp not in (None, "") else None
        except (TypeError, ValueError):
            temp_f = None
        if temp_f is None:
            missing_temp += 1

        if ct == "cold_air":
            cold_air_total += 1
            if temp_f is not None:
                cold_air_temps.append(temp_f)
                if temp_f >= COLD_AIR_DOSE_FLOOR_C:
                    cold_air_above_floor += 1
        elif ct in ("cold_plunge", "cold_water"):
            if temp_f is not None:
                cold_water_temps.append(temp_f)

        raw_dur = r.get("cold_duration_sec")
        try:
            dur_i = int(round(float(raw_dur))) if raw_dur not in (None, "") else None
        except (TypeError, ValueError):
            dur_i = None

        dose_hint = "amber" if (ct == "cold_air"
                                and temp_f is not None
                                and temp_f >= COLD_AIR_DOSE_FLOOR_C) else None

        recent_cold.append({
            "date":              r.get("date"),
            "cold_type":         ct,
            "cold_duration_sec": dur_i,
            "cold_temp_c":       temp_f,
            "dose_hint":         dose_hint,
        })

    # Newest first for the dashboard's "recent sessions" card.
    recent_cold.sort(key=lambda s: s.get("date") or "", reverse=True)

    cold_block: dict = {
        "n_sessions_28d":                    len(cold_rows),
        "n_sessions_per_week":               round(len(cold_rows) / 4.0, 2),
        "type_distribution":                 cold_type_dist or None,
        "paired_with_heat_pct":              (
            round(paired_with_heat / len(cold_rows) * 100.0, 1)
            if cold_rows else None
        ),
        "dominant_type":                     _dominant(cold_type_dist),
        "avg_cold_air_temp_c":               (
            round(sum(cold_air_temps) / len(cold_air_temps), 1)
            if cold_air_temps else None
        ),
        "avg_cold_water_temp_c":             (
            round(sum(cold_water_temps) / len(cold_water_temps), 1)
            if cold_water_temps else None
        ),
        "cold_air_above_dose_floor_pct":     (
            round(cold_air_above_floor / cold_air_total * 100.0, 1)
            if cold_air_total else None
        ),
        "missing_temp_pct":                  (
            round(missing_temp / len(cold_rows) * 100.0, 1)
            if cold_rows else None
        ),
        "recent_sessions":                   recent_cold,
    } if cold_rows else None

    # ---- Adherence ----
    heat_per_week = len(heat_rows) / 4.0 if heat_rows else 0.0
    if heat_per_week < target_per_week - 0.5:
        heat_status = "below-target"
    elif heat_per_week > target_per_week + 1.5:
        heat_status = "above-target"
    else:
        heat_status = "on-target"

    hsp_rows = [
        r for r in heat_rows
        if (r.get("heat_type") or "unknown") in HSP_APPLICABLE_HEAT_TYPES
    ]
    hsp_session_mins = [_heat_total_min(r) or 0.0 for r in hsp_rows]
    hsp_temp_vals = []
    for r in hsp_rows:
        try:
            if r.get("heat_temp_c") is not None:
                hsp_temp_vals.append(float(r.get("heat_temp_c")))
        except (TypeError, ValueError):
            pass
    avg_session_min = (
        sum(hsp_session_mins) / len(hsp_session_mins)
        if hsp_session_mins else 0.0
    )
    avg_temp_c = (sum(hsp_temp_vals) / len(hsp_temp_vals)) if hsp_temp_vals else None
    if not heat_rows:
        duration_status = "no-heat-data"
    elif heat_rows and not hsp_rows:
        duration_status = "not-applicable"
    elif (avg_temp_c is None
          or avg_temp_c < HSP_TEMP_THRESHOLD_C
          or avg_session_min < HSP_DURATION_THRESHOLD_MIN):
        duration_status = "below-HSP-threshold"
    elif avg_session_min > HSP_DURATION_THRESHOLD_MIN * 1.75:
        duration_status = "above-band"
    else:
        duration_status = "in-band"

    adherence: dict = {
        "heat_target_per_week":  target_per_week,
        "heat_actual_per_week":  round(heat_per_week, 2),
        "heat_status":           heat_status,
        "duration_status":       duration_status,
    }

    return {
        "n_sessions_28d": len(recent),
        "heat":           heat_block,
        "cold":           cold_block,
        "adherence":      adherence,
    }
