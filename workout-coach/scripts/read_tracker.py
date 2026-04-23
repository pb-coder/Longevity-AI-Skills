"""Read Workout Tracker.xlsx for /coach analysis.

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
from tracker_sheet import bw_locate_date, date_str  # noqa: E402

MONTHLY_RE = re.compile(r"^\d{4}\.\d{2}$")
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
def extract_rows(wb, months_back: int, today_d: date) -> tuple[list[dict], dict]:
    """Return (rows, session_totals).

    ``rows`` excludes TOTAL summary rows — one entry per logged set. Keys:
    ``session, date, num, exercise, set, reps, kg, volume, notes,
    distance_km, duration_min, pace, avg_hr``.

    ``session_totals`` maps ``YYYY-MM-DD`` → total volume lifted that session,
    populated from the sheet's TOTAL rows (formula-driven). The coach should
    use this instead of summing ``rows`` per date.
    """
    cutoff = today_d - timedelta(days=months_back * 31)
    data_sheets = sorted(
        [s for s in wb.sheetnames if MONTHLY_RE.match(s)],
        reverse=True,
    )

    rows: list[dict] = []
    session_totals: dict[str, float] = {}
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
            (session, date_val, num, exercise, set_n, reps, kg, volume,
             notes, *rest) = (list(raw) + [None] * 13)[:13]
            distance, duration, pace, avg_hr = rest[:4] if len(rest) >= 4 else (None, None, None, None)

            if date_val is None and exercise is None:
                empty_streak += 1
                if empty_streak >= EMPTY_STREAK_STOP:
                    break
                continue
            empty_streak = 0

            if date_val is not None:
                current_date = date_str(date_val)

            # TOTAL rows carry the session's total volume. Capture it, skip the row.
            # Note: openpyxl with data_only=True returns None for formula cells
            # whose cached value hasn't been written by Excel yet. We fall back
            # to summing row volumes below if the cached TOTAL is missing.
            if isinstance(exercise, str) and exercise.strip().upper() == TOTAL_LABEL:
                if current_date is not None and volume not in (None, ""):
                    session_totals[current_date] = to_float(volume)
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

    return rows, session_totals


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
    """Dates whose first populated row has Notes containing 'Deload Workout'."""
    deloads: set[str] = set()
    for name in wb.sheetnames:
        if not MONTHLY_RE.match(name):
            continue
        ws = wb[name]
        current_date: str | None = None
        seen_dates: set[str] = set()
        empty_streak = 0
        for raw in ws.iter_rows(min_row=2, values_only=True):
            vals = list(raw) + [None] * 13
            # SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | ...
            _session, date_val, _num, exercise, _set_n, _reps, _kg, _vol, notes = vals[:9]
            if date_val is None and exercise is None:
                empty_streak += 1
                if empty_streak >= EMPTY_STREAK_STOP:
                    break
                continue
            empty_streak = 0
            if date_val is not None:
                current_date = date_str(date_val)
            if current_date is None or exercise is None:
                continue
            # TOTAL rows never carry a deload marker; skip without consuming "first row".
            if isinstance(exercise, str) and exercise.strip().upper() == TOTAL_LABEL:
                continue
            # Only the first row of a date can mark the session as a deload.
            if current_date in seen_dates:
                continue
            seen_dates.add(current_date)
            if notes and DELOAD_MARKER in str(notes).lower():
                deloads.add(current_date)
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


def estimated_1rm(rows: list[dict]) -> dict:
    """Epley 1RM projection per exercise.

    For each exercise, take the heaviest projected e1RM per date (over all
    working sets that session), then report current/prev/best/last_date and
    the current-vs-prev delta in kg. Bodyweight and warmup sets excluded.
    """
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
        by_ex.setdefault(key, []).append({"date": r["date"], "e1rm": e1rm})

    out: dict[str, dict] = {}
    for key, entries in by_ex.items():
        # Per date, keep the heaviest projected e1RM.
        per_date: dict[str, float] = {}
        for e in entries:
            if e["e1rm"] > per_date.get(e["date"], -1):
                per_date[e["date"]] = e["e1rm"]
        dates_desc = sorted(per_date.keys(), reverse=True)
        if not dates_desc:
            continue
        current = per_date[dates_desc[0]]
        prev = per_date[dates_desc[1]] if len(dates_desc) >= 2 else None
        best = max(per_date.values())
        out[canonical_name[key]] = {
            "current_e1rm_kg": round(current, 1),
            "prev_e1rm_kg":    round(prev, 1) if prev is not None else None,
            "best_e1rm_kg":    round(best, 1),
            "last_date":       dates_desc[0],
            "delta_vs_prev_kg":(round(current - prev, 1) if prev is not None else None),
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
    ap.add_argument("--months", type=int, default=3, help="How many months back to include in rows")
    ap.add_argument("--today", default=None, help="Override today's date (YYYY-MM-DD) for testing")
    args = ap.parse_args()

    if not args.tracker.exists():
        print(f"ERROR: tracker not found: {args.tracker}", file=sys.stderr)
        return 1

    today_d = (
        datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    )

    wb = openpyxl.load_workbook(args.tracker, data_only=True, read_only=True)
    rows, session_totals = extract_rows(wb, args.months, today_d)
    deloads = find_deloads(wb)

    last_session = max((r["date"] for r in rows), default=None)
    days_since = None
    if last_session:
        d = datetime.strptime(last_session, "%Y-%m-%d").date()
        days_since = (today_d - d).days

    weeks_since_deload = None
    if deloads:
        d = datetime.strptime(deloads[-1], "%Y-%m-%d").date()
        weeks_since_deload = round((today_d - d).days / 7.0, 1)

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
    e1rm = estimated_1rm(rows)
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
        "last_session_date": last_session,
        "days_since_last_session": days_since,
        "deloads": deloads,
        "weeks_since_last_deload": weeks_since_deload,
        "cardio_last_14d": cardio_last_14d(rows, today_d),
        "bodyweight_latest": bw_latest,
        "bodyweight_trend_kg_per_week": bodyweight_trend_kg_per_week(bw_all),
        "bodyweight_recent": bw_recent,
        "progression_summary": progression_summary(rows),
        "session_totals": session_totals,
        "weekly_volume_per_muscle": weekly_volume,
        "estimated_1rm": e1rm,
        "stale_exercises": stale,
        "unknown_exercises": sorted(unknown_set),
        "rows": rows,
    }
    json.dump(_compact(out), sys.stdout, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
