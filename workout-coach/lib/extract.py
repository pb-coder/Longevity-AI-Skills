"""Sheet readers, exercises-database parser, profile + max-HR helpers.

Anything that touches the workbook directly lives here. Downstream
analytics modules consume the structured outputs (rows / health_all /
workout_sessions_all / exercises DB / max_hr) and never re-open the
xlsx.

Sheet readers:

- ``extract_rows(wb, months_back, today_d)`` — walk YYYY.MM monthly
  sheets, return ``(rows, session_totals, session_summaries)``. Folds
  TOTAL-row metadata into the per-session summary dict.
- ``find_deloads(wb)`` — dates whose TOTAL-row Notes contain the
  ``Deload Workout`` marker (case-insensitive).
- ``read_bodyweight(wb)`` — Bodyweight sheet rows, ASC.
- ``read_health_metrics(wb)`` — Health Metrics rows, ASC, with
  source-aware column mapping and missing-key backfill so HL trackers
  surface the same key surface as XML.
- ``read_workout_sessions(wb)`` — Apple Workout Sessions rows, ASC.

Exercises database:

- ``load_exercises_db(path)`` — parse ``shared/exercises-database.md``
  into a dict keyed by lowercased exercise name.
- ``_canon_muscle(tok)`` / ``_primary_from_note(note)`` — token-to-
  canonical-muscle helpers used by both the DB parser and the
  per-muscle volume / HR-divergence analytics.

Profile / HR estimation:

- ``_percentile(values, pct)`` — linear-interp percentile, used by HR
  estimation and a few session-distribution checks.
- ``_age_from_birthday(birthday_str, today_d)`` — dynamic age from
  ``Profile.birthday`` (clamped to a sane 5-100 range).
- ``estimate_max_hr(workout_sessions_all, today_d, profile, fallback_age)``
  — observed Apple peak when present, Tanaka fallback otherwise.
"""
from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

# Sibling lib/ modules + shared/ on sys.path so this module is importable
# both via the read_tracker entry point (which sets these up) and on its
# own (for unit tests / REPL inspection).
_LIB = Path(__file__).resolve().parent
_SHARED = _LIB.parents[1] / "shared"
for p in (_LIB, _SHARED):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from constants import (
    DELOAD_MARKER,
    EMPTY_STREAK_STOP,
    MONTHLY_RE,
    MUSCLE_ALIASES,
    SECTION_PRIMARY,
    SUBSECTION_PRIMARY_HINTS,
    TOTAL_LABEL,
)
from parsing import (
    _parse_iso_date,
    parse_distance_km,
    parse_duration_minutes,
    to_float,
    to_int_or_none,
)

# tracker_sheet is the canonical authority for sheet schemas; import
# directly so the analytics layer doesn't fork field lists.
from tracker_sheet import (  # type: ignore[import-not-found]
    date_str,
)
import csv_store as _csv_store  # noqa: E402  — CSV-backed HM/WS/Profile reads


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
            padded = list(raw) + [None] * 18
            (session, date_val, num, exercise, set_n, reps, kg, volume,
             notes, distance, duration, pace, avg_hr,
             active_cal, total_cal, elevation_m, elapsed, laps) = padded[:18]

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
                "laps":        to_int_or_none(laps) if laps not in (None, "") else None,
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


def read_bodyweight(person: str) -> list[dict]:
    """Return bodyweight entries sorted ascending by date.

    Sourced from the ``Bodyweight (kg)`` column on the per-person
    ``health_metrics.csv``. Returns ``[{"date": ..., "kg": ..., "notes": None}]``.
    Bodyweight no longer has a dedicated sheet — manual /log entries
    flow through ``upsert_health_metrics`` (sparse-merge), so the same
    source covers both manual and Apple-Watch readings.
    """
    out: list[dict] = []
    for entry in read_health_metrics(person):
        kg = entry.get("bodyweight_kg")
        if kg is None:
            continue
        out.append({"date": entry["date"], "kg": kg, "notes": None})
    out.sort(key=lambda e: e["date"])
    return out


def read_health_metrics(person: str) -> list[dict]:
    """Return Health Metrics rows from the per-person CSV, ASC by date.

    Reads ``<person>/data/health_metrics.csv`` via ``csv_store``. Each
    entry has one key per ``HEALTH_METRICS_FIELDS_BY_SOURCE[source]``
    field, plus ``date`` and ``notes``. Keys absent from the active
    source's slim schema (HL drops resting_hr, hrv_sdnn, etc.) are
    surfaced as None so downstream capability checks don't KeyError.
    """
    rows = _csv_store.read_health_metrics(person)
    if not rows:
        return []
    src = _csv_store.read_profile(person).get("source") or "xml"
    if src not in _csv_store.HEALTH_METRICS_FIELDS_BY_SOURCE:
        src = "xml"
    all_xml_keys = _csv_store.HEALTH_METRICS_FIELDS_BY_SOURCE["xml"]
    active_keys = _csv_store.HEALTH_METRICS_FIELDS_BY_SOURCE[src]
    missing_keys = [k for k in all_xml_keys if k not in active_keys]
    out = []
    for entry in rows:
        # csv_store returns floats / ints / None already; pad missing
        # keys so trend helpers see a uniform shape.
        rec = dict(entry)
        for k in missing_keys:
            rec.setdefault(k, None)
        # Coerce numeric strings (in case a hand-edited CSV slipped a
        # locale-formatted value through).
        for k in active_keys:
            v = rec.get(k)
            if v is None or isinstance(v, (int, float)):
                continue
            try:
                rec[k] = float(v)
            except (TypeError, ValueError):
                rec[k] = None
        out.append(rec)
    out.sort(key=lambda e: e["date"])
    return out


def read_workout_sessions(person: str) -> list[dict]:
    """Return Workout Sessions rows from the per-person CSV, ASC by date+start.

    Reads ``<person>/data/workout_sessions.csv`` via ``csv_store``. The
    schema follows ``Profile.source`` (xml: 12 cols including
    Avg/Max/Min HR; hl_export: 9 cols, HR fields absent).
    """
    rows = _csv_store.read_workout_sessions(person)
    if not rows:
        return []
    src = _csv_store.read_profile(person).get("source") or "xml"
    if src not in _csv_store.WORKOUT_SESSIONS_FIELDS_BY_SOURCE:
        src = "xml"
    fields = _csv_store.WORKOUT_SESSIONS_FIELDS_BY_SOURCE[src]

    numeric_keys = {"duration_min", "avg_hr", "active_cal", "distance_km"}
    int_keys     = {"max_hr", "min_hr"}

    out = []
    for entry in rows:
        d = entry.get("date")
        if not d:
            continue
        # Coerce per-key types into the shape the rest of the analytics
        # pipeline expects. csv_store hands us native ints/floats already
        # for numeric cells; this normalises stringy edge-cases (locale-
        # comma decimals, hand-edited cells).
        for key in fields:
            v = entry.get(key)
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
    out.sort(key=lambda e: (e["date"], e.get("start") or ""))
    return out


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


# ---------- profile / HR estimation ----------
def _percentile(values: list[float], pct: float) -> float | None:
    """Return the ``pct`` percentile (0-100) of a numeric list, linear-interp."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (pct / 100.0) * (len(s) - 1)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def _age_from_birthday(birthday_str: str | None, today_d: date) -> int | None:
    """Return integer age in years from a YYYY-MM-DD birthday + today, or None."""
    bd = _parse_iso_date(birthday_str)
    if bd is None:
        return None
    age = today_d.year - bd.year - ((today_d.month, today_d.day) < (bd.month, bd.day))
    if age < 5 or age > 100:
        return None
    return age


def estimate_max_hr(workout_sessions_all: list[dict],
                    today_d: date,
                    profile: dict | None = None,
                    fallback_age: int = 30) -> float | None:
    """Estimate the user's peak HR.

    Priority:
    1. Highest observed ``max_hr`` across all Apple workouts — Apple's
       per-workout max is conservative (it reflects what the watch saw,
       not theoretical max), so the absolute observed peak is a sound
       lower-bound estimate of true max.
    2. Tanaka formula 208 − 0.7×age, with age computed dynamically from
       ``profile.birthday`` and ``today_d``. Falls back to ``fallback_age``
       (30) when birthday is missing or malformed.

    Returns ``None`` only when neither path can produce a number.
    """
    observed = [
        s.get("max_hr") for s in (workout_sessions_all or [])
        if s.get("max_hr") and s.get("max_hr") >= 140
    ]
    if observed:
        return float(max(observed))
    age = _age_from_birthday((profile or {}).get("birthday"), today_d)
    if age is None:
        age = fallback_age
    return float(round(208 - 0.7 * age, 1))
