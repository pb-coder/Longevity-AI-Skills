"""Read the given tracker xlsx for /coach analysis.

Emits one JSON blob on stdout with everything the coach needs:
  - today, days_since_last_session, last_session_date
  - rows: flat list of every set from the last N months (default 3)
  - progression_summary: last vs. previous working set per exercise
  - deloads: dates whose first row has Notes 'Deload Workout'
  - weeks_since_last_deload: float, or null if no deload on record
  - cardio_last_14d: zone2_minutes, interval_sessions, total_distance_km
  - bodyweight_recent: last 12 weigh-ins from the Bodyweight sheet
  - bodyweight_trend_kg_per_week: slope over the last 8 entries, or null
  - bodyweight_latest: {date, kg} of the most recent entry, or null

Usage:
    python3 read_tracker.py "<tracker path>" [--months 3] [--today YYYY-MM-DD]

Keeping the model out of the weeds on format quirks (string vs datetime dates,
stringified numbers, casing inconsistency, empty-row streaks) is the whole
point — the skill body points at this script instead of redoing it each run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from tracker_sheet import (  # noqa: E402
    HEALTH_METRICS_COLS_BY_SOURCE,
    HEALTH_METRICS_FIELDS_BY_SOURCE,
    HEALTH_METRICS_SHEET_NAME,
    WORKOUT_SESSIONS_FIELDS_BY_SOURCE,
    WORKOUT_SESSIONS_SHEET_NAME,
    bw_locate_date,
    date_str,
    hm_locate_date,
    read_profile,
    ws_locate_date_start,
)

# Per-source capability map. The coach reads this to decide which sections of
# the report to write. ``xml`` is Apple's native zipped export (Nihad);
# ``hl_export`` is the HLExport text dump (Fabian) — much lighter, but no HRV,
# no wrist temp, no per-workout HR, no sleep stages, no Apple-aggregate RHR /
# walking HR / exercise-minute. The coach should distinguish ``unsupported``
# (data source can't provide it) from ``not yet collected`` (data source can,
# but the user hasn't logged enough yet).
SOURCE_CAPABILITIES = {
    "xml": {
        "hrv":                True,
        "wrist_temp":         True,
        "resting_hr_daily":   True,
        "walking_hr":         True,
        "sleep_stages":       True,
        "sleep_breath_dist":  True,
        "exercise_min_daily": True,
        "per_workout_hr":     True,
    },
    "hl_export": {
        "hrv":                False,
        "wrist_temp":         False,
        "resting_hr_daily":   False,
        "walking_hr":         False,
        "sleep_stages":       False,
        "sleep_breath_dist":  False,
        "exercise_min_daily": False,
        "per_workout_hr":     False,
    },
}

# Applied when the Profile sheet is missing or unset — treat the data as
# coming from XML so existing Nihad trackers (created before the Profile
# sheet existed) keep their full capability surface. New Fabian trackers
# get bootstrapped to ``hl_export`` by ``import_hl_export.py``.
DEFAULT_DATA_SOURCE = "xml"

MONTHLY_RE = re.compile(r"^\d{4}\.\d{2}$")
# Deload marker now lives on the TOTAL row's Notes column (col 9). The
# marker text is canonical "Deload Workout"; matching is case-insensitive.
DELOAD_MARKER = "deload workout"
EMPTY_STREAK_STOP = 10
TOTAL_LABEL = "TOTAL"

# Per-muscle weekly volume landmarks (hard sets). Source: references/training-
# science.md §1 + RP Strength tables. MV=maintenance, MEV=minimum effective,
# MAV=maximum adaptive, MRV=maximum recoverable. Numbers are individual and
# approximate; the coach uses them to name the band the current volume sits in.
VOLUME_LANDMARKS = {
    "chest":        {"mv": 6,  "mev": 10, "mav": 16, "mrv": 22},
    "back":         {"mv": 6,  "mev": 10, "mav": 18, "mrv": 25},
    "lats":         {"mv": 6,  "mev": 10, "mav": 16, "mrv": 22},
    "quads":        {"mv": 6,  "mev": 10, "mav": 18, "mrv": 22},
    "hamstrings":   {"mv": 4,  "mev": 8,  "mav": 14, "mrv": 18},
    "glutes":       {"mv": 4,  "mev": 8,  "mav": 14, "mrv": 18},
    "front_delts":  {"mv": 4,  "mev": 6,  "mav": 12, "mrv": 16},
    "side_delts":   {"mv": 6,  "mev": 8,  "mav": 16, "mrv": 22},
    "rear_delts":   {"mv": 6,  "mev": 8,  "mav": 16, "mrv": 22},
    "biceps":       {"mv": 5,  "mev": 8,  "mav": 14, "mrv": 20},
    "triceps":      {"mv": 4,  "mev": 6,  "mav": 12, "mrv": 18},
    "calves":       {"mv": 6,  "mev": 8,  "mav": 16, "mrv": 22},
    "forearms":     {"mv": 2,  "mev": 4,  "mav": 8,  "mrv": 12},
    "abs":          {"mv": 0,  "mev": 4,  "mav": 16, "mrv": 25},
    "core":         {"mv": 0,  "mev": 4,  "mav": 16, "mrv": 25},
    "erectors":     {"mv": 2,  "mev": 4,  "mav": 10, "mrv": 16},
    "traps":        {"mv": 2,  "mev": 4,  "mav": 10, "mrv": 16},
    "adductors":    {"mv": 0,  "mev": 2,  "mav": 8,  "mrv": 12},
    "neck":         {"mv": 0,  "mev": 2,  "mav": 6,  "mrv": 12},
}

# Canonicalise the muscle tokens that appear in exercises-database.md to the
# snake_case keys used everywhere else (and in VOLUME_LANDMARKS).
MUSCLE_ALIASES = {
    "chest": "chest", "upper chest": "upper_chest",
    "back": "back", "lats": "lats",
    "biceps": "biceps", "triceps": "triceps",
    "quads": "quads", "hamstrings": "hamstrings",
    "glutes": "glutes", "adductors": "adductors",
    "calves": "calves", "forearms": "forearms",
    "abs": "abs", "core": "core",
    "erectors": "erectors", "traps": "traps",
    "neck": "neck",
    "front delt": "front_delts", "front delts": "front_delts",
    "side delt": "side_delts",  "side delts":  "side_delts",
    "rear delt": "rear_delts",  "rear delts":  "rear_delts",
    "external rotators": "external_rotators",
    "shoulders": "shoulders",   "full body": "full_body",
    "posterior chain": None,    # too broad to assign — skip as primary
}

# Which ## SECTION header implies which primary muscle. None means "use
# subsection hint or parenthetical override". SHOULDERS is deliberately None
# because its subsections route to specific delt regions.
SECTION_PRIMARY = {
    "WARMUP": None, "CARDIO": None, "FULL BODY": None, "FULL BODY (COMPOUND)": None,
    "CHEST": "chest", "BACK": "back",
    "SHOULDERS": None,
    "BICEPS": "biceps", "TRICEPS": "triceps",
    "QUADS": "quads", "HAMSTRINGS": "hamstrings",
    "GLUTES": "glutes", "ADDUCTORS": "adductors",
    "CALVES": "calves", "CORE": "core",
    "NECK": "neck",
}

# Subsection hints that override the section heading (used inside SHOULDERS
# and for the stray "Forearms" subsection under BICEPS). Matched by substring
# against the lowercased subsection header.
SUBSECTION_PRIMARY_HINTS = [
    ("lateral delt", "side_delts"),
    ("rear delt",    "rear_delts"),
    ("vertical push","front_delts"),  # overhead press etc. primarily hit front delts
    ("traps",        "traps"),
    ("forearms",     "forearms"),
]


# ---------- helpers ----------
def to_float(v) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def to_int_or_none(v):
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _compact(obj):
    """Recursively drop ``None``-valued keys from dicts.

    Applied once to the top-level payload before serialisation so every
    row, summary entry, and nested dict sheds its ``None`` ballast.
    ``0``, ``""``, ``False``, and empty collections are preserved —
    they carry meaning. An absent key and a key set to ``null`` are
    equivalent to an LLM reading the JSON as prose.
    """
    if isinstance(obj, dict):
        return {k: _compact(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_compact(v) for v in obj]
    return obj


def parse_duration_minutes(raw) -> float:
    """Accept '30:00', '28:30', '30', 30, 30.0 — return minutes as float."""
    if raw in (None, ""):
        return 0.0
    s = str(raw).strip()
    if ":" in s:
        parts = s.split(":")
        try:
            mm = int(parts[0])
            ss = int(parts[1]) if len(parts) > 1 else 0
            return mm + ss / 60.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_distance_km(raw) -> float:
    """Accept '5', '5.0', '8,79' (German decimal), 5, 5.0."""
    if raw in (None, ""):
        return 0.0
    s = str(raw).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


# ---------- extraction ----------
def extract_rows(wb, months_back: int, today_d: date) -> tuple[list[dict], dict, dict]:
    """Return (rows, session_totals, session_summaries).

    ``rows`` excludes TOTAL summary rows — one entry per logged set. Keys:
    ``session, date, num, exercise, set, reps, kg, volume, notes,
    distance_km, duration_min, pace, avg_hr, active_cal, total_cal,
    elevation_m, elapsed``.

    ``session_totals`` maps ``YYYY-MM-DD`` → total volume lifted that session,
    populated from the sheet's TOTAL rows (formula-driven).

    ``session_summaries`` maps ``YYYY-MM-DD`` → dict of session-level
    metadata harvested from the TOTAL row: ``volume`` (=session_totals
    value), ``notes`` (deload marker if present), ``duration_min``,
    ``avg_hr``, ``active_cal``, ``total_cal``, ``elevation_m``,
    ``elapsed``, ``is_deload`` (bool). Cardio-only dates (no TOTAL row)
    are absent from this dict.
    """
    cutoff = today_d - timedelta(days=months_back * 31)
    data_sheets = sorted(
        [s for s in wb.sheetnames if MONTHLY_RE.match(s)],
        reverse=True,
    )

    rows: list[dict] = []
    session_totals: dict[str, float] = {}
    session_summaries: dict[str, dict] = {}
    for name in data_sheets:
        # Quick filter: sheet YYYY.MM vs cutoff
        y, m = name.split(".")
        first_of_month = date(int(y), int(m), 1)
        if first_of_month < cutoff.replace(day=1):
            continue

        ws = wb[name]
        current_date: str | None = None
        empty_streak = 0

        for raw in ws.iter_rows(min_row=2, values_only=True):
            padded = list(raw) + [None] * 17
            (session, date_val, num, exercise, set_n, reps, kg, volume,
             notes, distance, duration, pace, avg_hr,
             active_cal, total_cal, elevation_m, elapsed) = padded[:17]

            if date_val is None and exercise is None:
                empty_streak += 1
                if empty_streak >= EMPTY_STREAK_STOP:
                    break
                continue
            empty_streak = 0

            if date_val is not None:
                current_date = date_str(date_val)

            # TOTAL rows now carry the session's full summary record:
            # Date (col 2 may be set), Volume (col 8), Notes (col 9 —
            # carries the Deload Workout marker), Duration (col 11),
            # Avg HR (col 13), Active/Total Cal (cols 14-15), Elevation
            # (col 16), Elapsed (col 17). Harvest those into
            # session_summaries keyed by date.
            if isinstance(exercise, str) and exercise.strip().upper() == TOTAL_LABEL:
                # Prefer the TOTAL row's own Date if set; fall back to
                # current_date from the preceding non-TOTAL rows for
                # legacy data.
                total_date = current_date
                if date_val is not None:
                    parsed = date_str(date_val)
                    if parsed:
                        total_date = parsed
                if total_date is not None:
                    if volume not in (None, ""):
                        session_totals[total_date] = to_float(volume)
                    notes_str = str(notes).strip() if notes else None
                    is_deload = bool(notes_str and DELOAD_MARKER in notes_str.lower())
                    session_summaries[total_date] = {
                        "volume":       session_totals.get(total_date),
                        "notes":        notes_str,
                        "is_deload":    is_deload,
                        "duration_min": parse_duration_minutes(duration) if duration else None,
                        "avg_hr":       to_float(avg_hr) if avg_hr is not None else None,
                        "active_cal":   to_float(active_cal) if active_cal not in (None, "") else None,
                        "total_cal":    to_float(total_cal) if total_cal not in (None, "") else None,
                        "elevation_m":  to_float(elevation_m) if elevation_m not in (None, "") else None,
                        "elapsed":      str(elapsed).strip() if elapsed not in (None, "") else None,
                    }
                continue

            if exercise is None or current_date is None:
                continue

            # Volume is formula-driven in the sheet; if Excel hasn't cached it,
            # recompute from kg × reps so downstream consumers never see None.
            reps_i = to_int_or_none(reps)
            kg_f = to_float(kg)
            if volume in (None, ""):
                vol_f = kg_f * (reps_i or 0)
            else:
                vol_f = to_float(volume)

            rows.append({
                "session": to_int_or_none(session),
                "date": current_date,
                "num": num,
                "exercise": str(exercise).strip(),
                "set": set_n,
                "reps": reps_i,
                "kg": kg_f,
                "volume": vol_f,
                "notes": (str(notes).strip() if notes else None),
                "distance_km": parse_distance_km(distance) if distance else None,
                "duration_min": parse_duration_minutes(duration) if duration else None,
                "pace": str(pace).strip() if pace else None,
                "avg_hr": to_int_or_none(avg_hr),
                "active_cal":  to_float(active_cal) if active_cal not in (None, "") else None,
                "total_cal":   to_float(total_cal) if total_cal not in (None, "") else None,
                "elevation_m": to_float(elevation_m) if elevation_m not in (None, "") else None,
                "elapsed":     str(elapsed).strip() if elapsed not in (None, "") else None,
            })

    rows.sort(key=lambda r: (r["date"], r["num"] or 0, r["set"] or 0))

    # Fill in session_totals for any date whose TOTAL cell lacked a cached
    # value (common when openpyxl reads formulas Excel hasn't saved yet).
    # Trust the sheet first — only sum rows for dates the sheet didn't cover.
    cached_dates = set(session_totals.keys())
    for r in rows:
        if r["date"] in cached_dates:
            continue
        session_totals[r["date"]] = session_totals.get(r["date"], 0.0) + r["volume"]

    return rows, session_totals, session_summaries


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
        summary.append({
            "exercise": last["exercise"],
            "sessions_logged": len(dates_desc),
            "last": f"{dates_desc[0]} → {int(last['kg'])}kg x {last['reps']}",
            "prev": f"{dates_desc[1]} → {int(prev['kg'])}kg x {prev['reps']}" if prev else None,
        })

    summary.sort(key=lambda s: s["exercise"].lower())
    return summary


def find_deloads(wb) -> list[str]:
    """Dates whose strength session's TOTAL row has Notes containing 'Deload Workout'.

    Deload marker now lives on the TOTAL row's Notes column (col 9),
    consistent with the other session-level metadata. The TOTAL row's
    Date (col 2) is the canonical date; fall back to ``current_date``
    from preceding rows for legacy data.
    """
    deloads: set[str] = set()
    for name in wb.sheetnames:
        if not MONTHLY_RE.match(name):
            continue
        ws = wb[name]
        current_date: str | None = None
        empty_streak = 0
        for raw in ws.iter_rows(min_row=2, values_only=True):
            vals = list(raw) + [None] * 13
            _session, date_val, _num, exercise, _set_n, _reps, _kg, _vol, notes = vals[:9]
            if date_val is None and exercise is None:
                empty_streak += 1
                if empty_streak >= EMPTY_STREAK_STOP:
                    break
                continue
            empty_streak = 0
            if date_val is not None:
                parsed = date_str(date_val)
                if parsed:
                    current_date = parsed
            if exercise is None:
                continue
            if isinstance(exercise, str) and exercise.strip().upper() == TOTAL_LABEL:
                target_date = current_date
                if date_val is not None:
                    parsed = date_str(date_val)
                    if parsed:
                        target_date = parsed
                if target_date and notes and DELOAD_MARKER in str(notes).lower():
                    deloads.add(target_date)
    return sorted(deloads)


def read_bodyweight(wb) -> list[dict]:
    """Return all Bodyweight entries sorted ascending by date.

    Each entry: {"date": "YYYY-MM-DD", "kg": float, "notes": str|None}.
    Returns [] if the sheet is missing. The sheet stores newest-first with
    a per-year merge on column A, but this function re-sorts ascending so
    the trend/recent helpers see a stable chronological order.
    """
    if "Bodyweight" not in wb.sheetnames:
        return []
    ws = wb["Bodyweight"]
    out: list[dict] = []
    for raw in ws.iter_rows(min_row=2, values_only=True):
        if not raw:
            continue
        d, date_idx = bw_locate_date(raw)
        if d is None:
            continue
        kg_raw = raw[date_idx + 1] if len(raw) > date_idx + 1 else None
        try:
            kg = float(kg_raw) if kg_raw not in (None, "") else None
        except (TypeError, ValueError):
            continue
        if kg is None:
            continue
        notes = raw[date_idx + 2] if len(raw) > date_idx + 2 else None
        out.append({
            "date": d,
            "kg": kg,
            "notes": (str(notes).strip() if notes else None),
        })
    out.sort(key=lambda e: e["date"])
    return out


def bodyweight_trend_kg_per_week(entries: list[dict]) -> float | None:
    """Simple slope over the last 8 entries: (last_kg - first_kg) / weeks_between.

    Returns None if fewer than 3 entries or the span is <7 days (too noisy).
    Excludes entries with notes flagging non-morning/non-fasted context.
    """
    clean = [e for e in entries if not _is_flagged_nonfasted(e)]
    window = clean[-8:]
    if len(window) < 3:
        return None
    first_d = datetime.strptime(window[0]["date"], "%Y-%m-%d").date()
    last_d = datetime.strptime(window[-1]["date"], "%Y-%m-%d").date()
    days = (last_d - first_d).days
    if days < 7:
        return None
    weeks = days / 7.0
    return round((window[-1]["kg"] - window[0]["kg"]) / weeks, 3)


def _is_flagged_nonfasted(entry: dict) -> bool:
    notes = (entry.get("notes") or "").lower()
    return any(k in notes for k in ("not fasted", "evening", "after", "post-meal"))


def build_monthly_sessions(rows: list[dict],
                            session_summaries: dict[str, dict] | None = None
                            ) -> list[dict]:
    """Aggregate per-set rows into one entry per session-date.

    Strength sessions: metadata sourced from the TOTAL row's summary
    record in ``session_summaries`` (Active Cal, Total Cal, Elevation,
    Elapsed, Avg HR, Duration). Cardio-only sessions don't have a TOTAL
    row, so their metadata is read directly from the cardio rows.

    Returns a list sorted by date ascending.
    """
    summaries = session_summaries or {}

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
            for k in ("active_cal", "total_cal", "elevation_m", "elapsed", "avg_hr"):
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
        out.append(s)
    return out


def cardio_last_14d(rows: list[dict], today_d: date) -> dict:
    cutoff = today_d - timedelta(days=14)
    zone2_min = 0.0
    intervals = 0
    distance = 0.0
    for r in rows:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            continue
        # Cardio rows have non-zero distance or duration.
        dur = r.get("duration_min") or 0
        dist = r.get("distance_km") or 0
        if dur == 0 and dist == 0:
            continue
        distance += dist
        note = (r.get("notes") or "").lower()
        hr = r.get("avg_hr") or 0
        is_intervals = any(k in note for k in ("interval", "zone 4", "zone 5", "z4", "z5")) or hr >= 165
        if is_intervals:
            intervals += 1
        else:
            zone2_min += dur
    return {
        "zone2_minutes": round(zone2_min, 1),
        "interval_sessions": intervals,
        "total_distance_km": round(distance, 2),
    }


# ---------- health metrics ----------
def read_health_metrics(wb) -> list[dict]:
    """Return all Health Metrics rows sorted ascending by date.

    Each entry: ``{"date": "YYYY-MM-DD", <field>: <value>|None, ...}``,
    with one key per ``HEALTH_METRICS_FIELDS`` plus ``notes`` from the
    sheet's manual Notes column. Returns ``[]`` if the sheet is missing
    or empty.

    The sheet stores newest-first (the importer writes DESC); this
    function re-sorts ascending so trend/rolling helpers see a stable
    chronological order.
    """
    if HEALTH_METRICS_SHEET_NAME not in wb.sheetnames:
        return []
    src = read_profile(wb).get("source") or "xml"
    if src not in HEALTH_METRICS_FIELDS_BY_SOURCE:
        src = "xml"
    fields = HEALTH_METRICS_FIELDS_BY_SOURCE[src]
    notes_idx = HEALTH_METRICS_COLS_BY_SOURCE[src] - 1  # zero-based notes col
    # Keys callers may legitimately query but that the active source can't
    # populate (HL slim schema). Surface them as None so downstream
    # capability gates and trend helpers don't KeyError.
    all_xml_keys = HEALTH_METRICS_FIELDS_BY_SOURCE["xml"]
    missing_keys = [k for k in all_xml_keys if k not in fields]

    ws = wb[HEALTH_METRICS_SHEET_NAME]
    out: list[dict] = []
    for raw in ws.iter_rows(min_row=2, values_only=True):
        if not raw:
            continue
        d, _ = hm_locate_date(raw)
        if d is None:
            continue
        entry = {"date": d}
        for i, key in enumerate(fields, start=1):
            v = raw[i] if len(raw) > i else None
            if v in (None, ""):
                entry[key] = None
            else:
                try:
                    entry[key] = float(v)
                except (TypeError, ValueError):
                    entry[key] = None
        for k in missing_keys:
            entry[k] = None
        notes = raw[notes_idx] if len(raw) > notes_idx else None
        entry["notes"] = (str(notes).strip() if notes else None)
        out.append(entry)
    out.sort(key=lambda e: e["date"])
    return out


def read_workout_sessions(wb) -> list[dict]:
    """Return all Workout Sessions rows sorted ascending by date+start.

    Each entry has the per-source columns of the sheet (xml: 12 cols incl.
    Avg/Max/Min HR; hl_export: 9 cols, HR fields surfaced as None).
    Returns ``[]`` if the sheet is missing.
    """
    if WORKOUT_SESSIONS_SHEET_NAME not in wb.sheetnames:
        return []
    src = read_profile(wb).get("source") or "xml"
    if src not in WORKOUT_SESSIONS_FIELDS_BY_SOURCE:
        src = "xml"
    fields = WORKOUT_SESSIONS_FIELDS_BY_SOURCE[src]

    # Per-key coercer. Keys absent from the active source's field list
    # (HL: avg/max/min HR) get None.
    numeric_keys = {"duration_min", "avg_hr", "active_cal", "distance_km"}
    int_keys     = {"max_hr", "min_hr"}

    ws = wb[WORKOUT_SESSIONS_SHEET_NAME]
    out: list[dict] = []
    for raw in ws.iter_rows(min_row=2, values_only=True):
        d, s = ws_locate_date_start(raw)
        if d is None:
            continue
        entry = {"date": d, "start": s}
        # Map fields[i] → raw[i+1] (col 1 is Date, col 2..N is fields[0..N-1]).
        for i, key in enumerate(fields, start=1):
            v = raw[i] if len(raw) > i else None
            if key in numeric_keys:
                entry[key] = to_float(v) if v is not None else 0.0
            elif key in int_keys:
                entry[key] = to_int_or_none(v) if v is not None else None
            elif key == "notes":
                entry[key] = str(v).strip() if v else None
            else:
                entry[key] = v
        # Backfill keys missing from the active schema so downstream code
        # (e.g. session-HR cross-check) doesn't KeyError on HL trackers.
        for missing in ("avg_hr", "max_hr", "min_hr",
                        "duration_min", "active_cal", "distance_km",
                        "end", "apple_type", "source", "notes"):
            entry.setdefault(missing,
                             0.0 if missing in numeric_keys else None)
        out.append(entry)
    out.sort(key=lambda e: (e["date"], e["start"] or ""))
    return out


def _values_in_window(entries: list[dict], key: str, today_d: date, days: int) -> list[float]:
    cutoff = today_d - timedelta(days=days)
    out = []
    for e in entries:
        v = e.get(key)
        if v is None:
            continue
        try:
            d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            continue
        out.append(float(v))
    return out


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def metric_trend_per_4w(entries: list[dict], key: str) -> float | None:
    """OLS slope of ``key`` over time, scaled to a 4-week window.

    Returns None unless there are ≥4 non-null entries spanning ≥21 days.
    Used for HRV / RHR / VO2max / sleep trends. Negative is improving for
    RHR (lower resting HR = better cardio fitness); positive is improving
    for HRV and VO2max.
    """
    pts: list[tuple[date, float]] = []
    for e in entries:
        v = e.get(key)
        if v is None:
            continue
        try:
            d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        pts.append((d, float(v)))
    if len(pts) < 4:
        return None
    pts.sort(key=lambda p: p[0])
    span_days = (pts[-1][0] - pts[0][0]).days
    if span_days < 21:
        return None
    base = pts[0][0]
    xs = [(p[0] - base).days for p in pts]
    ys = [p[1] for p in pts]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    if den <= 0:
        return None
    return round((num / den) * 28.0, 2)


def latest_metric(entries: list[dict], key: str) -> dict | None:
    """Most recent (date, value) pair for ``key``, or None if absent."""
    for e in reversed(entries):
        v = e.get(key)
        if v is not None:
            return {"date": e["date"], "value": round(float(v), 2)}
    return None


def baseline_60d(entries: list[dict], key: str, today_d: date) -> float | None:
    """Mean of ``key`` over the last 60 days. Used as anomaly baseline."""
    return _mean_or_none(_values_in_window(entries, key, today_d, 60))


def workout_sessions_in_window(sessions: list[dict], today_d: date, days: int) -> list[dict]:
    cutoff = today_d - timedelta(days=days)
    out = []
    for s in sessions:
        try:
            d = datetime.strptime(s["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            continue
        # Filter out incidental walks — those aren't training.
        if (s.get("notes") or "").lower().startswith("incidental"):
            continue
        out.append({
            "date":         s["date"],
            "type":         s.get("apple_type"),
            "duration":     s.get("duration_min"),
            "avg_hr":       s.get("avg_hr"),
            "max_hr":       s.get("max_hr"),
            "cal":          s.get("active_cal"),
        })
    return out


def strength_session_avg_hr_trend(
    sessions: list[dict],
    strength_dates: set[str],
) -> float | None:
    """Slope per 4 weeks of avg HR over the last 8 strength sessions.

    Matches Apple workouts to logged strength sessions by date. A rising
    avg HR on a stable load is a fatigue signal; the planning rule uses
    this to hold load when HR is creeping up.
    """
    matched: list[tuple[date, float]] = []
    for s in sessions:
        if s.get("date") not in strength_dates:
            continue
        avg = s.get("avg_hr")
        if avg in (None, 0):
            continue
        try:
            d = datetime.strptime(s["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        matched.append((d, float(avg)))
    if len(matched) < 4:
        return None
    matched.sort(key=lambda p: p[0])
    matched = matched[-8:]
    span_days = (matched[-1][0] - matched[0][0]).days
    if span_days < 21:
        return None
    base = matched[0][0]
    xs = [(p[0] - base).days for p in matched]
    ys = [p[1] for p in matched]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    if den <= 0:
        return None
    return round((num / den) * 28.0, 2)


# ---------- exercises database ----------
_BULLET_RE = re.compile(
    r"^\s*-\s+"
    r"(?P<name>.+?)"                                 # exercise name
    r"(?:\s+\[(?P<equip>[^\]]+)\])?"                # [EQUIPMENT] optional
    r"(?:\s*—\s*(?P<syn>[^◆(]+?))?"                 # synergist list after em-dash
    r"(?P<leng>\s*◆)?"                              # optional lengthened flag
    r"(?:\s*\((?P<note>[^)]+)\))?"                  # optional parenthetical note
    r"\s*$"
)


def _canon_muscle(tok: str) -> str | None:
    """Map a raw muscle token from the database to a canonical key (or None)."""
    t = tok.strip().lower()
    # Strip trailing "s" pluralisation only for a short whitelist — avoid
    # collapsing "lats" and "hamstrings" which are already plural canonical.
    if t in MUSCLE_ALIASES:
        return MUSCLE_ALIASES[t]
    # Secondary pass: split on "/" for things like "erectors/lower back".
    for part in re.split(r"[/,]", t):
        p = part.strip()
        if p in MUSCLE_ALIASES:
            return MUSCLE_ALIASES[p]
    return None


def _primary_from_note(note: str | None) -> str | None:
    """If the bullet has ``(primary: X)``, return X's canonical muscle."""
    if not note:
        return None
    m = re.match(r"\s*primary:\s*(.+)$", note.strip(), re.IGNORECASE)
    if not m:
        return None
    return _canon_muscle(m.group(1))


def load_exercises_db(path: Path) -> dict[str, dict]:
    """Parse ``exercises-database.md`` into a dict keyed by lowercased
    exercise name. Each value:
      ``{"primary": str|None, "synergists": [str], "lengthened": bool,
         "equipment": str|None, "is_warmup": bool}``

    Unknown muscle tokens are silently dropped (not mapped) — the caller
    can detect gaps by comparing logged exercise names against this dict
    and surfacing anything missing as ``unknown_exercises``.
    """
    db: dict[str, dict] = {}
    if not path.exists():
        return db

    section = None        # e.g. "CHEST"
    subsection_primary = None  # regional override from a ### hint
    section_primary = None     # derived from SECTION_PRIMARY[section]

    for line in path.read_text().splitlines():
        s = line.rstrip()
        if s.startswith("## "):
            section = s[3:].strip().upper()
            section_primary = SECTION_PRIMARY.get(section)
            subsection_primary = None
            continue
        if s.startswith("### "):
            sub = s[4:].strip().lower()
            subsection_primary = None
            for key, muscle in SUBSECTION_PRIMARY_HINTS:
                if key in sub:
                    subsection_primary = muscle
                    break
            continue
        m = _BULLET_RE.match(s)
        if not m:
            continue

        name = m.group("name").strip()
        # Bullets in prose paragraphs (e.g. "(Biceps receive ~0.5 sets from…)")
        # are parenthetical, not exercises.
        if name.startswith("(") or ":" in name:
            continue

        equip = (m.group("equip") or "").strip() or None
        lengthened = m.group("leng") is not None
        note = m.group("note")
        raw_syn = m.group("syn") or ""

        synergists: list[str] = []
        for tok in raw_syn.split(","):
            tok = tok.strip()
            if not tok:
                continue
            # Each synergist in the database is written as "+muscle".
            if tok.startswith("+"):
                tok = tok[1:].strip()
            canon = _canon_muscle(tok)
            if canon:
                synergists.append(canon)

        # Primary resolution order: (primary: X) override → subsection hint
        # → section heading. None falls through for untagged sections (WARMUP,
        # CARDIO, FULL BODY) — those exercises get zero volume attribution.
        primary = (
            _primary_from_note(note)
            or subsection_primary
            or section_primary
        )

        db[name.lower()] = {
            "primary": primary,
            "synergists": synergists,
            "lengthened": lengthened,
            "equipment": equip,
            "is_warmup": section == "WARMUP",
            "is_cardio": section == "CARDIO",
        }
    return db


# ---------- derived coach features ----------
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


def weekly_volume_per_muscle(
    rows: list[dict],
    db: dict[str, dict],
    today_d: date,
    window_days: int,
    unknown_out: set[str],
) -> dict:
    """Fractional hard-set count per muscle over the last ``window_days``.

    Primary muscle = 1.0 set, each synergist = 0.5 set (per training-science
    §1). Warmup exercises (database section) and warmup-marked sets are
    skipped. Unknown exercises — logged names that don't appear in the db —
    are collected into ``unknown_out`` for the caller to surface.
    """
    cutoff = today_d - timedelta(days=window_days)
    sets: dict[str, float] = defaultdict(float)
    for r in rows:
        if not _is_working_set(r):
            continue
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            continue
        entry = db.get(r["exercise"].lower())
        if entry is None:
            unknown_out.add(r["exercise"])
            continue
        if entry.get("is_warmup"):
            continue
        if entry["primary"]:
            sets[entry["primary"]] += 1.0
        for syn in entry["synergists"]:
            sets[syn] += 0.5

    current = {m: round(v, 1) for m, v in sets.items()}
    landmarks = {m: VOLUME_LANDMARKS[m] for m in current if m in VOLUME_LANDMARKS}
    return {
        "window_days": window_days,
        "current": current,
        "landmarks": landmarks,
    }


# History length cap for ``estimated_1rm[exercise].e1rm_history``. The slope
# field already summarises the trajectory; the LLM rarely needs more than the
# top of the list to spot-check confidence and grain. Cutting from 6 → 3
# entries removes ~50% of the per-exercise payload.
E1RM_HISTORY_LIMIT = 3


def estimated_1rm(rows: list[dict], deload_dates: list[str] | None = None) -> dict:
    """Epley 1RM projection per exercise, with trajectory and confidence.

    For each exercise, take the heaviest projected e1RM per date (over all
    working sets that session) and report:
      - current/prev/best/last_date and current-vs-prev delta in kg
      - e1rm_history: last 6 sessions newest-first, each with the top set
        that produced the e1RM (so the coach can judge rep-range quality)
      - slope_kg_per_4w: OLS slope over the last 6 sessions, scaled to a
        4-week window. Null if fewer than 3 sessions.
      - confidence: high|medium|low based on the rep ranges of the last
        3 top sets — Epley is most accurate at 3-8 reps.
      - stalled_sessions: count of consecutive most-recent sessions with
        |Δe1RM| ≤ 0.5kg, broken by any deload that falls in the window.

    Bodyweight and warmup sets excluded (kg must be > 0).
    """
    deload_set = set(deload_dates or [])

    by_ex: dict[str, list[dict]] = {}
    canonical_name: dict[str, str] = {}
    for r in rows:
        if not _is_working_set(r):
            continue
        kg = r.get("kg") or 0
        reps = r.get("reps") or 0
        if kg <= 0 or reps <= 0:
            continue
        key = r["exercise"].lower()
        canonical_name.setdefault(key, r["exercise"])
        e1rm = kg * (1.0 + reps / 30.0)
        by_ex.setdefault(key, []).append({
            "date": r["date"], "e1rm": e1rm, "reps": reps, "kg": kg,
        })

    out: dict[str, dict] = {}
    for key, entries in by_ex.items():
        # Per date, keep the heaviest projected e1RM and remember the
        # (reps, kg) that produced it — needed for the history block and
        # for the confidence judgement.
        per_date: dict[str, dict] = {}
        for e in entries:
            top = per_date.get(e["date"])
            if top is None or e["e1rm"] > top["e1rm"]:
                per_date[e["date"]] = {
                    "e1rm": e["e1rm"], "reps": e["reps"], "kg": e["kg"],
                }
        dates_desc = sorted(per_date.keys(), reverse=True)
        if not dates_desc:
            continue
        current = per_date[dates_desc[0]]["e1rm"]
        prev = per_date[dates_desc[1]]["e1rm"] if len(dates_desc) >= 2 else None
        best = max(d["e1rm"] for d in per_date.values())

        # Slope is computed over the last 6 sessions for stability, even
        # though the emitted history is capped at E1RM_HISTORY_LIMIT.
        slope_dates = dates_desc[:6]
        history_full = [
            {
                "date":         d,
                "e1rm_kg":      round(per_date[d]["e1rm"], 1),
                "top_set_reps": per_date[d]["reps"],
                "top_set_kg":   per_date[d]["kg"],
            }
            for d in slope_dates
        ]
        history = history_full[:E1RM_HISTORY_LIMIT]

        # OLS slope (kg per 28 days) over the last 6 sessions. Use
        # ``history_full``, not the emitted ``history`` — the trim is
        # cosmetic for the JSON output, but the trend should still see all
        # six sessions to stay stable.
        slope = None
        if len(history_full) >= 3:
            pts: list[tuple[date, float]] = []
            for h in history_full:
                try:
                    pts.append((datetime.strptime(h["date"], "%Y-%m-%d").date(), h["e1rm_kg"]))
                except ValueError:
                    continue
            if len(pts) >= 3:
                pts.sort(key=lambda p: p[0])
                base = pts[0][0]
                xs = [(p[0] - base).days for p in pts]
                ys = [p[1] for p in pts]
                n = len(xs)
                mx = sum(xs) / n
                my = sum(ys) / n
                num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
                den = sum((xs[i] - mx) ** 2 for i in range(n))
                if den > 0:
                    slope = round((num / den) * 28.0, 2)

        # Confidence from rep ranges of the last 3 sessions' top sets.
        # Epley is calibrated best for low-rep sets; 12+ rep top sets
        # give a noisy projection. Pulled from the un-capped history so
        # confidence is consistent regardless of the emitted limit.
        recent_reps = [h["top_set_reps"] for h in history_full[:3]]
        if len(recent_reps) < 2:
            confidence = "low"
        elif any(r >= 13 for r in recent_reps):
            confidence = "low"
        elif all(3 <= r <= 8 for r in recent_reps):
            confidence = "high"
        else:
            confidence = "medium"

        # Stalled: walk back through consecutive sessions while the
        # e1RM swing is within ±0.5kg. Break on the first deload that
        # falls inside (or at either end of) the gap between two
        # consecutive sessions — a deliberate volume cut isn't a stall.
        stalled = 0
        for i in range(len(dates_desc) - 1):
            this_date = dates_desc[i]
            prev_date = dates_desc[i + 1]
            crossed_deload = any(
                prev_date <= d <= this_date for d in deload_set
            )
            if crossed_deload:
                break
            this_e = per_date[this_date]["e1rm"]
            prev_e = per_date[prev_date]["e1rm"]
            if abs(this_e - prev_e) <= 0.5:
                stalled += 1
            else:
                break

        # Drop e1rm_history entirely when the signal is noise: low confidence
        # AND no slope (fewer than 3 sessions). The summary fields already
        # convey the state; the history is just pad in this case.
        emit_history = not (confidence == "low" and slope is None)

        out[canonical_name[key]] = {
            "current_e1rm_kg":  round(current, 1),
            "prev_e1rm_kg":     round(prev, 1) if prev is not None else None,
            "best_e1rm_kg":     round(best, 1),
            "last_date":        dates_desc[0],
            "delta_vs_prev_kg": (round(current - prev, 1) if prev is not None else None),
            "e1rm_history":     history if emit_history else None,
            "slope_kg_per_4w":  slope,
            "confidence":       confidence,
            "stalled_sessions": stalled,
        }
    return out


def stale_exercises(
    rows: list[dict], db: dict[str, dict], today_d: date, threshold_days: int
) -> list[dict]:
    """Exercises whose last appearance is ≥ ``threshold_days`` ago.

    Warmup-section exercises are excluded — those cycle on and off by
    design. Useful for spotting movements that were tried once or twice and
    dropped; the coach can decide whether to retire or reintroduce them.
    """
    last_seen: dict[str, str] = {}
    sessions_count: dict[str, set[str]] = defaultdict(set)
    canonical: dict[str, str] = {}
    for r in rows:
        if not _is_working_set(r):
            continue
        key = r["exercise"].lower()
        entry = db.get(key)
        if entry and (entry.get("is_warmup") or entry.get("is_cardio")):
            continue
        canonical.setdefault(key, r["exercise"])
        if r["date"] > last_seen.get(key, ""):
            last_seen[key] = r["date"]
        sessions_count[key].add(r["date"])

    out = []
    for key, last in last_seen.items():
        try:
            d = datetime.strptime(last, "%Y-%m-%d").date()
        except ValueError:
            continue
        days = (today_d - d).days
        if days < threshold_days:
            continue
        out.append({
            "exercise":        canonical[key],
            "last_date":       last,
            "weeks_since":     round(days / 7.0, 1),
            "sessions_logged": len(sessions_count[key]),
        })
    out.sort(key=lambda e: e["weeks_since"], reverse=True)
    return out


# ---------- main ----------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tracker", type=Path)
    ap.add_argument("--months", type=int, default=3,
                    help="How many months back to load from monthly sheets. The data is used internally for "
                         "all roll-ups regardless of --include-rows.")
    ap.add_argument("--today", default=None, help="Override today's date (YYYY-MM-DD) for testing")
    ap.add_argument("--include-rows", action="store_true",
                    help="Include the flat `rows` array (~63%% of payload) in the JSON. Off by default — the "
                         "coach already exposes pre-aggregated `progression_summary`, `session_totals`, "
                         "`weekly_volume_per_muscle`, and `estimated_1rm`. Pass this only for debug deep-dives.")
    ap.add_argument("--pretty", action="store_true",
                    help="Pretty-print the JSON (indent=2). Off by default — compact form saves ~20%% of "
                         "tokens for the LLM consumer. Use for human inspection.")
    args = ap.parse_args()

    if not args.tracker.exists():
        print(f"ERROR: tracker not found: {args.tracker}", file=sys.stderr)
        return 1

    today_d = (
        datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    )

    wb = openpyxl.load_workbook(args.tracker, data_only=True, read_only=True)
    rows, session_totals, session_summaries = extract_rows(wb, args.months, today_d)
    deloads = find_deloads(wb)

    profile = read_profile(wb)
    data_source = profile.get("source") or DEFAULT_DATA_SOURCE
    capabilities = SOURCE_CAPABILITIES.get(data_source, SOURCE_CAPABILITIES[DEFAULT_DATA_SOURCE])

    last_session = max((r["date"] for r in rows), default=None)
    days_since = None
    if last_session:
        d = datetime.strptime(last_session, "%Y-%m-%d").date()
        days_since = (today_d - d).days

    weeks_since_deload = None
    if deloads:
        d = datetime.strptime(deloads[-1], "%Y-%m-%d").date()
        weeks_since_deload = round((today_d - d).days / 7.0, 1)

    health_all = read_health_metrics(wb)
    # Per-day rows go into health_metrics_recent. ``bodyweight_kg`` is dropped
    # because it duplicates the dedicated ``bodyweight_recent`` series — the
    # coach reads daily metrics for HRV / VO2max / sleep / wrist temp, not
    # weight. Keeping it here costs ~600 bytes for no signal.
    health_recent = [
        {k: v for k, v in entry.items() if k != "bodyweight_kg"}
        for entry in health_all[-30:]
    ]

    workout_sessions_all = read_workout_sessions(wb)
    sessions_28d = workout_sessions_in_window(workout_sessions_all, today_d, 28)

    # Strength session dates: any logged date with at least one working set
    # carrying weight × reps. Used to match Apple workouts back to training.
    strength_dates: set[str] = set()
    for r in rows:
        if not _is_working_set(r):
            continue
        if (r.get("kg") or 0) > 0 and (r.get("reps") or 0) > 0:
            strength_dates.add(r["date"])

    bw_all = read_bodyweight(wb)
    bw_recent = bw_all[-12:]
    bw_latest = (
        {"date": bw_all[-1]["date"], "kg": bw_all[-1]["kg"]}
        if bw_all else None
    )

    # Parse the exercises database once; it's read-only for this run.
    db_path = Path(__file__).resolve().parents[2] / "shared" / "exercises-database.md"
    db = load_exercises_db(db_path)

    unknown_set: set[str] = set()
    weekly_volume = weekly_volume_per_muscle(rows, db, today_d, 28, unknown_set)
    e1rm = estimated_1rm(rows, deloads)
    stale = stale_exercises(rows, db, today_d, 28)

    # Surface any logged exercise across the full loaded window that doesn't
    # match an entry in the database — not just the 28-day volume window.
    # Catches typos/rename drift (e.g. "Deadhang" vs "Dead Hang") that would
    # otherwise silently under-count volume and dodge rotation decisions.
    for r in rows:
        if not _is_working_set(r):
            continue
        if r["exercise"].lower() not in db:
            unknown_set.add(r["exercise"])

    out = {
        "today": today_d.strftime("%Y-%m-%d"),
        "data_source": data_source,
        "capabilities": capabilities,
        "auto_cardio_enabled": bool(profile.get("auto_cardio")),
        "last_session_date": last_session,
        "days_since_last_session": days_since,
        "deloads": deloads,
        "weeks_since_last_deload": weeks_since_deload,
        "cardio_last_14d": cardio_last_14d(rows, today_d),
        "monthly_sessions": build_monthly_sessions(rows, session_summaries),
        "bodyweight_latest": bw_latest,
        "bodyweight_trend_kg_per_week": bodyweight_trend_kg_per_week(bw_all),
        "bodyweight_recent": bw_recent,
        "progression_summary": progression_summary(rows),
        "session_totals": session_totals,
        "weekly_volume_per_muscle": weekly_volume,
        "estimated_1rm": e1rm,
        "stale_exercises": stale,
        "unknown_exercises": sorted(unknown_set),
        # ---- Apple Health: recovery + cardio outcomes -------------------
        "health_metrics_recent": health_recent,
        "vo2max_latest": latest_metric(health_all, "vo2max"),
        "vo2max_trend_per_4w": metric_trend_per_4w(health_all, "vo2max"),
        "resting_hr_recent_avg": _mean_or_none(_values_in_window(health_all, "resting_hr", today_d, 7)),
        "resting_hr_trend_per_4w": metric_trend_per_4w(health_all, "resting_hr"),
        "hrv_recent_avg": _mean_or_none(_values_in_window(health_all, "hrv_sdnn", today_d, 7)),
        "hrv_trend_per_4w": metric_trend_per_4w(health_all, "hrv_sdnn"),
        "hrv_baseline_60d": baseline_60d(health_all, "hrv_sdnn", today_d),
        "sleep_avg_last_7d": _mean_or_none(_values_in_window(health_all, "sleep_total_h", today_d, 7)),
        "sleep_avg_last_28d": _mean_or_none(_values_in_window(health_all, "sleep_total_h", today_d, 28)),
        "wrist_temp_baseline_60d": baseline_60d(health_all, "wrist_temp_c", today_d),
        "wrist_temp_recent_avg": _mean_or_none(_values_in_window(health_all, "wrist_temp_c", today_d, 3)),
        "hr_recovery_recent_avg": _mean_or_none(
            [v for v in (e.get("hr_recovery_1min") for e in health_all[-5:]) if v is not None]
        ),
        "workout_sessions_last_28d": sessions_28d,
        "strength_session_avg_hr_trend": strength_session_avg_hr_trend(workout_sessions_all, strength_dates),
        # ``rows`` is the flat per-set list. Off by default — see --include-rows.
        # _compact will drop the key entirely when value is None.
        "rows": rows if args.include_rows else None,
    }
    if args.pretty:
        json.dump(_compact(out), sys.stdout, ensure_ascii=False, indent=2)
    else:
        # Compact form: no whitespace between separators. Saves ~20% of
        # bytes vs indent=2 for an LLM consumer that doesn't render the
        # whitespace anyway.
        json.dump(_compact(out), sys.stdout, ensure_ascii=False,
                  separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
