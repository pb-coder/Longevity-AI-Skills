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

import re
from datetime import date  # noqa: F401  (kept for type-hint forward-compat)


from .parsing import _parse_iso_date


# Single source of truth for warmup detection on a Notes cell.
#
# ``_WARMUP_MARKER_RE`` matches the structured ``(warmup)`` token the plan /
# log writer emits — the authoritative tag.
#
# ``_WARMUP_WORD_RE`` matches word-bounded free-text variants ("warm-up",
# "warm up", "warmup"). Word boundaries are the fix for the prior bare-
# substring rule, which both let "warm-up"/"warm up" slip through (the space
# / hyphen broke the literal "warmup" match) and could false-exclude.
#
# ``_WARMUP_NEGATED_RE`` guards the one phrase the bug calls out explicitly:
# a real working set annotated "no warmup needed" must NOT be excluded just
# because the token appears. A "no"/"without"/"skip" qualifier immediately
# before the token negates it.
_WARMUP_MARKER_RE = re.compile(r"\(\s*warm[\s-]?up\s*\)", re.IGNORECASE)
_WARMUP_WORD_RE = re.compile(r"\bwarm[\s-]?up\b", re.IGNORECASE)
_WARMUP_NEGATED_RE = re.compile(
    r"\b(?:no|without|skip(?:ped|ping)?|don'?t|not?)\s+warm[\s-]?up\b",
    re.IGNORECASE,
)


def _notes_has_warmup(notes) -> bool:
    """True when a Notes cell flags the row as a warmup ramp set.

    Detects the structured ``(warmup)`` marker and word-bounded text
    variants ("warm-up", "warm up", "warmup"), case-insensitive. A negated
    mention ("no warmup needed") is NOT a warmup tag and returns False —
    that's a real working set whose note merely references warmup.
    """
    if not notes:
        return False
    s = str(notes)
    if _WARMUP_MARKER_RE.search(s):
        return True
    if _WARMUP_NEGATED_RE.search(s):
        return False
    return bool(_WARMUP_WORD_RE.search(s))


def _is_cardio_row(r: dict) -> bool:
    """A row is cardio if it has positive *unloaded* distance, OR a
    duration paired with cardio context (avg HR or auto-import source).

    A loaded carry (Farmer Walk: kg>0 + distance) is strength work, not
    cardio — the distance→cardio gate only fires when kg is zero. A manual
    isometric hold (Dead Hang 0:30, Plank 1:00) has duration but no HR and
    no auto-import source — that's a strength-session "other" row too.
    """
    if (r.get("distance_km") or 0) > 0 and (r.get("kg") or 0) <= 0:
        return True
    if (r.get("duration_min") or 0) <= 0:
        return False
    if (r.get("avg_hr") or 0) > 0:
        return True
    src = (r.get("source") or "").strip().lower()
    if src == "apple" or src.startswith("apple@") or src.startswith("gymkit:"):
        return True
    return False


def progression_summary(rows: list[dict]) -> list[dict]:
    """Last and previous best working set per exercise (warmups excluded)."""
    by_ex: dict[str, list[dict]] = {}
    for r in rows:
        if _notes_has_warmup(r.get("notes")):
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
            "last": f"{dates_desc[0]} → {last['kg']:g}kg x {last['reps']}",
            "prev": f"{dates_desc[1]} → {prev['kg']:g}kg x {prev['reps']}" if prev else None,
            "last_notes": last_notes if last_notes else None,
        })

    summary.sort(key=lambda s: s["exercise"].lower())
    return summary


def _is_flagged_nonfasted(entry: dict) -> bool:
    notes = (entry.get("notes") or "").lower()
    return any(k in notes for k in ("not fasted", "evening", "after", "post-meal"))


def bodyweight_trend_kg_per_week(
    entries: list[dict],
    start_date: str | date | None = None,
) -> float | None:
    """Simple slope over the last 8 entries: (last_kg - first_kg) / weeks_between.

    Returns None if fewer than 3 entries or the span is <7 days (too noisy).
    Excludes entries with notes flagging non-morning/non-fasted context. When
    ``start_date`` is supplied, the 8-entry window starts no earlier than that
    date so active nutrition phases are judged inside their own window.
    """
    start_d = (
        start_date if isinstance(start_date, date)
        else _parse_iso_date(start_date) if start_date else None
    )
    clean = []
    for e in entries:
        if _is_flagged_nonfasted(e):
            continue
        if start_d is not None:
            d = _parse_iso_date(e.get("date"))
            if d is None or d < start_d:
                continue
        clean.append(e)
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

    # Pass 1: scan rows to learn, per date, which kinds of rows are present
    # and capture each kind's first-appearance exercise name for
    # ``exercise_first``. A date with both strength and cardio rows will
    # emit TWO entries downstream (one per kind) so per-session TRIMP and
    # CTL/ATL/TSB don't lose the day's cardio when a strength session also
    # happened.
    date_kinds: dict[str, dict] = {}
    for r in rows:
        d = r.get("date")
        if not d:
            continue
        is_strength_row = (r.get("kg") or 0) * (r.get("reps") or 0) > 0
        is_cardio_row = _is_cardio_row(r)
        bucket = date_kinds.setdefault(d, {
            "has_strength": False, "has_cardio": False,
            "has_other": False,
            "strength_first": None, "cardio_first": None, "other_first": None,
        })
        if is_strength_row:
            bucket["has_strength"] = True
            if bucket["strength_first"] is None:
                bucket["strength_first"] = r.get("exercise")
        if is_cardio_row:
            bucket["has_cardio"] = True
            if bucket["cardio_first"] is None:
                bucket["cardio_first"] = r.get("exercise")
        if not is_strength_row and not is_cardio_row:
            bucket["has_other"] = True
            if bucket["other_first"] is None:
                bucket["other_first"] = r.get("exercise")

    # Pass 2: build the entries, keyed by ``(date, kind)``. Each date with
    # both kinds yields two entries; pure days yield one.
    by_key: dict[tuple, dict] = {}
    for d, bucket in date_kinds.items():
        if bucket["has_strength"]:
            by_key[(d, "strength")] = {
                "date": d,
                "session_kind": "strength",
                "exercise_first": bucket["strength_first"],
                "active_cal":  None, "total_cal":   None,
                "elevation_m": None, "elapsed":     None,
                "avg_hr":      None, "duration_min": None,
            }
        if bucket["has_cardio"]:
            by_key[(d, "cardio")] = {
                "date": d,
                "session_kind": "cardio",
                "exercise_first": bucket["cardio_first"],
                "active_cal":  None, "total_cal":   None,
                "elevation_m": None, "elapsed":     None,
                "avg_hr":      None, "duration_min": None,
            }
        if bucket["has_other"] and not bucket["has_strength"] and not bucket["has_cardio"]:
            by_key[(d, "other")] = {
                "date": d,
                "session_kind": "other",
                "exercise_first": bucket["other_first"],
                "active_cal":  None, "total_cal":   None,
                "elevation_m": None, "elapsed":     None,
                "avg_hr":      None, "duration_min": None,
            }

    # Pass 3: AGGREGATE all cardio rows on each date into the single
    # ``(date, "cardio")`` entry. A day can hold several bouts (an easy
    # swim, a commute ride, an interval run); the old "fill if empty" rule
    # kept only the FIRST bout and silently dropped the rest, undercounting
    # cardio minutes by 23-37% on multi-bout days and corrupting every
    # downstream cardio metric (HR-zones, per-session TRIMP, CTL/ATL/TSB,
    # week-over-week). We instead SUM the additive quantities (duration,
    # calories, distance), take the MAX elevation, the duration-weighted
    # mean HR, and the first non-empty elapsed string. Strength entries are
    # left alone here; their metadata comes from the TOTAL-row summary.
    #
    # ``_hr_num`` / ``_hr_den`` accumulate the duration-weighted HR. A bout
    # with HR but no duration still contributes its HR with unit weight so
    # it isn't silently dropped; a bout with neither is ignored for HR.
    cardio_agg: dict[str, dict] = {}
    for r in rows:
        d = r.get("date")
        if not d or not _is_cardio_row(r):
            continue
        if (d, "cardio") not in by_key:
            continue
        agg = cardio_agg.setdefault(d, {
            "duration_min": 0.0, "active_cal": 0.0, "total_cal": 0.0,
            "distance_km": 0.0, "elevation_m": None, "elapsed": None,
            "_hr_num": 0.0, "_hr_den": 0.0,
            "_has_duration": False, "_has_active_cal": False,
            "_has_total_cal": False, "_has_distance": False,
        })
        dur = r.get("duration_min")
        if dur not in (None, ""):
            agg["duration_min"] += float(dur)
            agg["_has_duration"] = True
        for key, flag in (("active_cal", "_has_active_cal"),
                          ("total_cal", "_has_total_cal"),
                          ("distance_km", "_has_distance")):
            v = r.get(key)
            if v not in (None, ""):
                agg[key] += float(v)
                agg[flag] = True
        elev = r.get("elevation_m")
        if elev not in (None, ""):
            elev_f = float(elev)
            if agg["elevation_m"] is None or elev_f > agg["elevation_m"]:
                agg["elevation_m"] = elev_f
        if agg["elapsed"] in (None, "") and r.get("elapsed") not in (None, ""):
            agg["elapsed"] = r.get("elapsed")
        hr = r.get("avg_hr")
        if hr not in (None, "") and float(hr) > 0:
            w = float(dur) if dur not in (None, "") and float(dur) > 0 else 1.0
            agg["_hr_num"] += float(hr) * w
            agg["_hr_den"] += w

    for d, agg in cardio_agg.items():
        s = by_key[(d, "cardio")]
        if agg["_has_duration"]:
            s["duration_min"] = agg["duration_min"]
        if agg["_has_active_cal"]:
            s["active_cal"] = agg["active_cal"]
        if agg["_has_total_cal"]:
            s["total_cal"] = agg["total_cal"]
        if agg["_has_distance"]:
            s["distance_km"] = agg["distance_km"]
        if agg["elevation_m"] is not None:
            s["elevation_m"] = agg["elevation_m"]
        if agg["elapsed"] not in (None, ""):
            s["elapsed"] = agg["elapsed"]
        if agg["_hr_den"] > 0:
            s["avg_hr"] = agg["_hr_num"] / agg["_hr_den"]

    # Pass 4: fold TOTAL-row session summaries into the strength entries
    # (TOTAL rows are not emitted for pure cardio).
    for d, summary in summaries.items():
        s = by_key.get((d, "strength"))
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

    # Emit sorted by (date, kind) with strength before cardio on mixed days.
    kind_order = {"strength": 0, "cardio": 1, "other": 2}
    out: list[dict] = []
    for d, kind in sorted(by_key.keys(), key=lambda k: (k[0], kind_order.get(k[1], 9))):
        s = by_key[(d, kind)]
        if kind == "strength" and d in totals:
            s["volume"] = totals[d]
        max_hr = by_date_apple.get(d)
        if max_hr:
            s["max_hr"] = max_hr
        out.append(s)
    return out


def _is_working_set(r: dict) -> bool:
    """True when a row is a counted hard SET.

    Two shapes count as one set each:

    1. A positive-rep set. Bodyweight (kg=0, reps>0 like Pull-Up) counts.
    2. A duration hold with reps==0 — an isometric (Plank, Side Plank) or
       a loaded carry (Farmer Walk) — *provided* it is not a cardio bout
       and not a pure distance row. The hold time substitutes for reps as
       the work unit; per-muscle attribution still requires a DB primary
       at the consumer, so an unknown/cardio-section exercise contributes
       zero there.

    Cardio rows and warmup-tagged rows (structured ``(warmup)`` marker or
    word-bounded "warm-up"/"warm up") are always excluded. Isometrics stay
    out of e1RM/progression — those paths gate on ``kg > 0`` independently.
    """
    if _notes_has_warmup(r.get("notes")):
        return False
    reps = r.get("reps") or 0
    if reps > 0:
        return True
    # reps == 0 (or missing): only a non-cardio duration hold counts.
    if (r.get("duration_min") or 0) <= 0:
        return False
    if _is_cardio_row(r):
        return False
    return True
