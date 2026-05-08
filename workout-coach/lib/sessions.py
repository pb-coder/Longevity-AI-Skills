"""Session-level aggregation, working-set classification, bodyweight trend.

Inputs are the flat ``rows`` list from ``extract.extract_rows`` (one
entry per logged set) plus the Apple workout sessions and TOTAL-row
summaries. Outputs are session-keyed dicts that the strength + cardio
analytics layer consumes.

Functions:

- ``progression_summary(rows)`` — last vs prior heaviest working set per
  exercise.
- ``_is_flagged_nonfasted(entry)`` — bodyweight-row note filter; pulls
  out non-morning/non-fasted entries so the trend slope isn't distorted.
- ``bodyweight_trend_kg_per_week(entries)`` — slope over the last clean
  8 entries.
- ``build_monthly_sessions(rows, summaries, totals, apple_sessions)`` —
  one entry per session-date with the kind (strength / cardio / other),
  TOTAL-row metadata, volume, and Apple-observed max HR folded in.
- ``_is_working_set(r)`` — shared filter used by every working-volume
  calculation downstream.
"""
from __future__ import annotations

import sys
from datetime import date  # noqa: F401  (kept for type-hint forward-compat)
from pathlib import Path

# Sibling lib/ on sys.path so this module is importable on its own.
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from parsing import _parse_iso_date


def progression_summary(rows: list[dict]) -> list[dict]:
    """Last and previous best working set per exercise (warmups excluded)."""
    by_ex: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("notes") and "warmup" in r["notes"].lower():
            continue
        if not r.get("kg") or not r.get("reps"):
            continue
        by_ex.setdefault(r["exercise"].lower(), []).append(r)

    summary = []
    for canon_lower, sets in by_ex.items():
        # Group by date, pick heaviest (kg, then reps) per session.
        by_date: dict[str, dict] = {}
        for s in sets:
            cur = by_date.get(s["date"])
            if cur is None or (s["kg"], s["reps"]) > (cur["kg"], cur["reps"]):
                by_date[s["date"]] = s
        dates_desc = sorted(by_date.keys(), reverse=True)
        if len(dates_desc) < 1:
            continue
        last = by_date[dates_desc[0]]
        prev = by_date[dates_desc[1]] if len(dates_desc) >= 2 else None
        last_notes = last.get("notes")
        summary.append({
            "exercise": last["exercise"],
            "sessions_logged": len(dates_desc),
            "last": f"{dates_desc[0]} → {int(last['kg'])}kg x {last['reps']}",
            "prev": f"{dates_desc[1]} → {int(prev['kg'])}kg x {prev['reps']}" if prev else None,
            "last_notes": last_notes if last_notes else None,
        })

    summary.sort(key=lambda s: s["exercise"].lower())
    return summary


def _is_flagged_nonfasted(entry: dict) -> bool:
    notes = (entry.get("notes") or "").lower()
    return any(k in notes for k in ("not fasted", "evening", "after", "post-meal"))


def bodyweight_trend_kg_per_week(entries: list[dict]) -> float | None:
    """Simple slope over the last 8 entries: (last_kg - first_kg) / weeks_between.

    Returns None if fewer than 3 entries or the span is <7 days (too noisy).
    Excludes entries with notes flagging non-morning/non-fasted context.
    """
    clean = [e for e in entries if not _is_flagged_nonfasted(e)]
    window = clean[-8:]
    if len(window) < 3:
        return None
    first_d = _parse_iso_date(window[0]["date"])
    last_d = _parse_iso_date(window[-1]["date"])
    if first_d is None or last_d is None:
        return None
    days = (last_d - first_d).days
    if days < 7:
        return None
    weeks = days / 7.0
    return round((window[-1]["kg"] - window[0]["kg"]) / weeks, 3)


def build_monthly_sessions(rows: list[dict],
                            session_summaries: dict[str, dict] | None = None,
                            session_totals: dict[str, float] | None = None,
                            apple_sessions: list[dict] | None = None,
                            ) -> list[dict]:
    """Aggregate per-set rows into one entry per session-date.

    Strength sessions: metadata sourced from the TOTAL row's summary
    record in ``session_summaries`` (Active Cal, Total Cal, Elevation,
    Elapsed, Avg HR, Duration). Cardio-only sessions don't have a TOTAL
    row, so their metadata is read directly from the cardio rows.

    Folds in:
    - ``volume`` for strength sessions from ``session_totals`` (so the
      caller doesn't need to ship ``session_totals`` separately).
    - ``max_hr`` per session from ``apple_sessions`` (Apple's per-workout
      max HR — only present for XML; HL surfaces None and the field is
      stripped by ``_compact``).

    Returns a list sorted by date ascending.
    """
    summaries = session_summaries or {}
    totals = session_totals or {}
    apple = apple_sessions or []

    # date → max_hr lookup. Apple may record multiple workouts per date
    # (Core + Functional + cardio rides); we keep the largest max_hr seen
    # across all of them as the session's peak. We deliberately don't
    # surface ``apple_type`` here because it conflates strength and
    # cardio for mixed days — ``session_kind`` is the authoritative tag.
    by_date_apple: dict[str, float] = {}
    for ap in apple:
        d = ap.get("date")
        if not d:
            continue
        mh = ap.get("max_hr")
        if mh and mh > by_date_apple.get(d, 0):
            by_date_apple[d] = mh

    by_date: dict[str, dict] = {}
    for r in rows:
        d = r.get("date")
        if not d:
            continue
        is_strength_row = (r.get("kg") or 0) * (r.get("reps") or 0) > 0
        is_cardio_row = (r.get("distance_km") or 0) > 0 or (r.get("duration_min") or 0) > 0

        s = by_date.get(d)
        if s is None:
            s = {
                "date": d,
                "exercise_first": r.get("exercise"),
                "active_cal":  None,
                "total_cal":   None,
                "elevation_m": None,
                "elapsed":     None,
                "avg_hr":      None,
                "duration_min": None,
                "laps":        None,
                "_has_strength": is_strength_row,
                "_has_cardio":   is_cardio_row,
            }
            by_date[d] = s
        else:
            if is_strength_row:
                s["_has_strength"] = True
            if is_cardio_row:
                s["_has_cardio"] = True

        # For cardio-only sessions: fill metadata from each cardio row.
        # For mixed/strength sessions, the TOTAL row summary is canonical
        # and is folded in below.
        if is_cardio_row and not is_strength_row:
            for k in ("active_cal", "total_cal", "elevation_m", "elapsed", "avg_hr", "laps"):
                if s.get(k) in (None, "") and r.get(k) not in (None, ""):
                    s[k] = r.get(k)
            if s.get("duration_min") in (None, "") and r.get("duration_min"):
                s["duration_min"] = r.get("duration_min")

    # Fold TOTAL-row session summaries (strength sessions only — TOTAL
    # rows are not emitted for pure cardio).
    for d, summary in summaries.items():
        s = by_date.get(d)
        if s is None:
            continue
        if summary.get("active_cal") is not None:
            s["active_cal"] = summary["active_cal"]
        if summary.get("total_cal") is not None:
            s["total_cal"] = summary["total_cal"]
        if summary.get("elevation_m") is not None:
            s["elevation_m"] = summary["elevation_m"]
        if summary.get("elapsed"):
            s["elapsed"] = summary["elapsed"]
        if summary.get("avg_hr") is not None:
            s["avg_hr"] = summary["avg_hr"]
        if summary.get("duration_min") is not None:
            s["duration_min"] = summary["duration_min"]
        if summary.get("is_deload"):
            s["is_deload"] = True

    out: list[dict] = []
    for d in sorted(by_date.keys()):
        s = by_date[d]
        kind = "strength" if s.pop("_has_strength") else (
            "cardio" if s.pop("_has_cardio") else "other")
        s.pop("_has_cardio", None)
        s["session_kind"] = kind
        # Fold in volume (strength only) and Apple max_hr.
        if kind == "strength" and d in totals:
            s["volume"] = totals[d]
        max_hr = by_date_apple.get(d)
        if max_hr:
            s["max_hr"] = max_hr
        out.append(s)
    return out


def _is_working_set(r: dict) -> bool:
    """A working set has a positive rep count and no 'warmup' in Notes.
    Bodyweight sets (kg=0, reps>0 like Pull-Up or Plank) count. Cardio rows
    (reps=0) and warmup-tagged rows are skipped."""
    reps = r.get("reps") or 0
    if reps <= 0:
        return False
    notes = (r.get("notes") or "").lower()
    if "warmup" in notes:
        return False
    return True
