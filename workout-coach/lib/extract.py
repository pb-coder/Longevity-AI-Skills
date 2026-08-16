"""CSV readers, exercises-database parser, profile + max-HR helpers.

Anything that reads the per-person CSV store lives here. Downstream
analytics modules consume the structured outputs (rows / health_all /
workout_sessions_all / swim_workouts / swim_laps / exercises DB /
max_hr) and never re-open the source files.

CSV readers:

- ``extract_rows(person, months_back, today_d)`` — walk every per-month
  CSV in ``<person>/data/monthly/``, return
  ``(rows, session_totals, session_summaries)``. Folds TOTAL-row
  metadata into the per-session summary dict.
- ``find_deloads(person)`` — dates whose TOTAL-row Notes contain the
  ``Deload Workout`` marker (case-insensitive).
- ``read_bodyweight(person)`` — bodyweight series sourced from
  ``health_metrics.csv`` col B, ASC.
- ``read_health_metrics(person)`` — Health Metrics rows, ASC, with
  missing-key backfill, so a tracker whose CSV predates a schema
  widening still presents the full key surface.
- ``read_workout_sessions(person)`` — Apple Workout Sessions rows, ASC.
- ``read_swim_workouts(person)`` / ``read_swim_laps(person)`` —
  per-swim aggregates and per-lap detail. Aggregates are written on
  every import; per-lap detail is frozen history from the retired XML
  path, so ``read_swim_laps`` returns ``[]`` on any month imported
  since the migration.

Exercises database:

- ``load_exercises_db(path)`` — parse ``shared/exercises-database.md``
  into a dict keyed by lowercased exercise name.
- ``_canon_muscle(tok)`` / ``_primary_from_note(note)`` — token-to-
  canonical-muscle helpers used by both the DB parser and the
  per-muscle volume / HR-divergence analytics.

Profile / HR estimation:

- ``_age_from_birthday(birthday_str, today_d)`` — dynamic age from
  ``Profile.birthday`` (clamped to a sane 5-100 range).
- ``estimate_max_hr(workout_sessions_all, today_d, profile, fallback_age)``
  — observed Apple peak when present, Tanaka fallback otherwise.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from datetime import date, timedelta

from .constants import (
    DELOAD_MARKER,
    MUSCLE_ALIASES,
    SECTION_PRIMARY,
    SUBSECTION_PRIMARY_HINTS,
    TOTAL_LABEL,
)
from .parsing import (
    _parse_iso_date,
    parse_distance_km,
    parse_duration_minutes,
    to_float,
    to_int_or_none,
)

# Monthly CSVs (post-PR3a) are the canonical authority for monthly
# workout data. Coercions (date_str, etc.) live in monthly_csv now.
from shared.monthly_csv import (
    date_str,
    list_year_months,
    read_monthly,
)
from shared import csv_store as _csv_store


def extract_rows(person: str, months_back: int, today_d: date) -> tuple[list[dict], dict, dict]:
    """Return (rows, session_totals, session_summaries).

    Reads per-month CSVs from ``<person>/data/monthly/YYYY.MM.csv``.
    ``rows`` excludes TOTAL summary rows — one entry per logged set.
    Keys: ``session, date, num, exercise, set, reps, kg, volume,
    notes, distance_km, duration_min, pace, avg_hr, active_cal,
    total_cal, elevation_m, elapsed``.

    ``session_totals`` maps ``YYYY-MM-DD`` → total volume lifted that
    session, populated from the per-month CSV's TOTAL rows.

    ``session_summaries`` maps ``YYYY-MM-DD`` → dict of session-level
    metadata harvested from the TOTAL row: ``volume`` (=session_totals
    value), ``notes`` (deload marker if present), ``duration_min``,
    ``avg_hr``, ``active_cal``, ``total_cal``, ``elevation_m``,
    ``elapsed``, ``is_deload`` (bool). Cardio-only dates (no TOTAL
    row) are absent from this dict.
    """
    cutoff = today_d - timedelta(days=months_back * 31)
    yms = sorted(list_year_months(person), reverse=True)

    rows: list[dict] = []
    session_totals: dict[str, float] = {}
    session_summaries: dict[str, dict] = {}
    for ym in yms:
        # Quick filter: month-key vs cutoff
        try:
            y, m = ym.split(".")
            first_of_month = date(int(y), int(m), 1)
        except ValueError:
            continue
        if first_of_month < cutoff.replace(day=1):
            continue

        for rd in read_monthly(person, ym):
            session = rd.get("session")
            date_val = rd.get("date")
            num = rd.get("num")
            exercise = rd.get("exercise")
            set_n = rd.get("set")
            reps = rd.get("reps")
            kg = rd.get("kg")
            volume = rd.get("volume")
            notes = rd.get("notes")
            distance = rd.get("distance")
            duration = rd.get("duration")
            pace = rd.get("pace")
            avg_hr = rd.get("avg_hr")
            active_cal = rd.get("active_cal")
            total_cal = rd.get("total_cal")
            elevation_m = rd.get("elevation_m")
            elapsed = rd.get("elapsed")

            current_date = date_str(date_val)

            if isinstance(exercise, str) and exercise.strip().upper() == TOTAL_LABEL:
                if current_date is not None:
                    if volume not in (None, ""):
                        session_totals[current_date] = to_float(volume)
                    notes_str = str(notes).strip() if notes else None
                    is_deload = bool(notes_str and DELOAD_MARKER in notes_str.lower())
                    session_summaries[current_date] = {
                        "volume":       session_totals.get(current_date),
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
                "source":      (str(rd.get("source")).strip().lower() if rd.get("source") not in (None, "") else None),
            })

    rows.sort(key=lambda r: (r["date"], r["num"] or 0, r["set"] or 0))

    # Fill in session_totals for any date whose TOTAL row lacked a Volume.
    cached_dates = set(session_totals.keys())
    for r in rows:
        if r["date"] in cached_dates:
            continue
        session_totals[r["date"]] = session_totals.get(r["date"], 0.0) + r["volume"]

    return rows, session_totals, session_summaries


def find_deloads(person: str) -> list[str]:
    """Return YYYY-MM-DD dates whose TOTAL row Notes contain 'Deload Workout'.

    Reads each per-month CSV; checks each TOTAL row's Notes for the
    deload marker (case-insensitive substring).
    """
    deloads: set[str] = set()
    for ym in list_year_months(person):
        for rd in read_monthly(person, ym):
            exercise = rd.get("exercise")
            if not (isinstance(exercise, str)
                    and exercise.strip().upper() == TOTAL_LABEL):
                continue
            target_date = date_str(rd.get("date"))
            notes = rd.get("notes")
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
    # One source, one field list. The padding loop below is kept because
    # a tracker whose CSV predates a schema widening still reads short,
    # and trend helpers want a uniform shape either way.
    active_keys = _csv_store.HEALTH_METRICS_FIELDS
    missing_keys: list[str] = []
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


def read_swim_workouts(person: str) -> list[dict]:
    """Return per-swim aggregate rows aggregated across all per-month
    ``swimming/YYYY.MM.workouts.csv`` files.

    Pass-through to ``csv_store.read_swim_workouts`` — the analytics
    layer doesn't reshape the schema, just consumes it.
    """
    return _csv_store.read_swim_workouts(person)


def read_swim_laps(person: str) -> list[dict]:
    """Return per-lap rows aggregated across all per-month
    ``swimming/YYYY.MM.laps.csv`` files."""
    return _csv_store.read_swim_laps(person)


def read_sleep_nights(person: str) -> list[dict]:
    """Return per-night aggregate rows from ``sleep/YYYY.MM.nights.csv``.

    Pass-through to ``csv_store.read_sleep_nights``. Empty list when
    the sleep folder is absent (a tracker that
    haven't imported / logged any sleep yet).
    """
    return _csv_store.read_sleep_nights(person)


def read_thermal_sessions(person: str) -> list[dict]:
    """Return per-session sauna + cold rows from
    ``thermal/YYYY.MM.sessions.csv``.

    Pass-through to ``csv_store.read_thermal_sessions``. Empty list
    when the thermal folder is absent (no manual /log sauna / cold
    entries yet).
    """
    return _csv_store.read_thermal_sessions(person)


def read_light_therapy_sessions(person: str) -> list[dict]:
    """Return per-session light-therapy (RLT / PBM / blue light) rows
    from ``light_therapy/YYYY.MM.sessions.csv``.

    Pass-through to ``csv_store.read_light_therapy_sessions``. Empty
    list when the light_therapy folder is absent (no manual /log
    light-therapy entries yet).
    """
    return _csv_store.read_light_therapy_sessions(person)


def read_nutrition_phases(person: str) -> list[dict]:
    """Return nutrition-phase rows from ``nutrition_phases.csv``.

    Pass-through to ``csv_store.read_nutrition_phases``. Empty list
    when the file is absent (no manual /log bulking/cutting entries
    yet). Sorted DESC by ``start_date``.
    """
    return _csv_store.read_nutrition_phases(person)


def read_workout_sessions(person: str) -> list[dict]:
    """Return Workout Sessions rows from the per-person CSV, ASC by date+start.

    Reads ``<person>/data/workout_sessions.csv`` via ``csv_store``, which
    carries Avg / Max / Min HR alongside duration, calories and distance.
    """
    rows = _csv_store.read_workout_sessions(person)
    if not rows:
        return []
    fields = _csv_store.WORKOUT_SESSIONS_FIELDS

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
        # (e.g. session-HR cross-check) doesn't KeyError on short rows.
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
    path = Path(path)
    if not path.exists():
        return {}
    stat = path.stat()
    cached = _load_exercises_db_cached(str(path), stat.st_mtime_ns, stat.st_size)
    # Defensively copy the mutable leaves so consumers cannot mutate the
    # process-wide parse cache.
    return {
        k: {
            **v,
            "synergists": list(v.get("synergists") or []),
        }
        for k, v in cached.items()
    }


@lru_cache(maxsize=8)
def _load_exercises_db_cached(path_str: str, _mtime_ns: int, _size: int) -> dict[str, dict]:
    path = Path(path_str)
    db: dict[str, dict] = {}

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
    1. A robust high observed ``max_hr`` across recent Apple workouts,
       using the 99th percentile instead of the lifetime max so one sensor
       spike does not permanently distort TRIMP/HR-zone math.
    2. Tanaka formula 208 − 0.7×age, with age computed dynamically from
       ``profile.birthday`` and ``today_d``. Falls back to ``fallback_age``
       (30) when birthday is missing or malformed.

    Returns ``None`` only when neither path can produce a number.
    """
    cutoff = today_d - timedelta(days=365)
    observed = []
    for s in (workout_sessions_all or []):
        d = _parse_iso_date(s.get("date"))
        if d is not None and d < cutoff:
            continue
        v = s.get("max_hr")
        if v and v >= 140:
            observed.append(float(v))
    if observed:
        observed.sort()
        idx = min(len(observed) - 1, int(round((len(observed) - 1) * 0.99)))
        return float(observed[idx])
    age = _age_from_birthday((profile or {}).get("birthday"), today_d)
    if age is None:
        age = fallback_age
    return float(round(208 - 0.7 * age, 1))
