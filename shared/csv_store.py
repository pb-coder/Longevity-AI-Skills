"""CSV-backed store for the dense, machine-only tracker data.

Replaces the xlsx ``Health Metrics``, ``Workout Sessions``, and
``Profile`` sheets with flat CSVs in ``<person>/data/``. Same functional
surface (sparse-merge upserts, schema-by-source, manual-wins drift
guard, dedupe by date+start, sort DESC on every write) — only the
on-disk format changed.

Why CSV: openpyxl is ~10× slower than the stdlib ``csv`` module on
dense rectangular data, the dense tables aren't human-glanceable in
Excel anyway (15 cols × hundreds of rows), and CSVs are diffable in
git. The monthly ``YYYY.MM`` workout sheets stay in xlsx — they're
sparse and the styler / merge / SESSION numbering is what makes them
readable.

Functional surface mirrors the old ``tracker_sheet.upsert_*`` helpers
so importers / coach / logger swap one import line and otherwise keep
their internal call shapes.
"""
from __future__ import annotations

import csv
from datetime import date as date_cls
from pathlib import Path
from typing import Iterable

from person_paths import (
    ensure_data_dir,
    ensure_swimming_dir,
    health_metrics_csv,
    profile_csv,
    swim_laps_csv,
    swim_workouts_csv,
    workout_sessions_csv,
)

# ============================================================ Schema (HM + WS)
# Source-aware column sets. ``xml`` is Apple's native export (full HRV /
# Resting HR / Wrist Temp / sleep stages / per-workout HR). ``hl_export``
# is HLExport's text dump — a structurally lighter feed; the unsupported
# columns simply aren't part of the slim schema.

HEALTH_METRICS_HEADERS_BY_SOURCE = {
    "xml": [
        "Date", "Bodyweight (kg)", "VO2max", "Resting HR", "HRV SDNN",
        "Walking HR", "HR Recovery 1min", "Sleep Total", "Sleep Deep",
        "Sleep REM", "Resp Rate", "Wrist Temp", "Sleep Breath Dist",
        "Exercise Min", "Notes",
    ],
    "hl_export": [
        "Date", "Bodyweight (kg)", "VO2max", "HR Recovery 1min",
        "Sleep Total", "Resp Rate", "Notes",
    ],
}

# Importer payload field names, in the same order as the headers above
# (with the leading ``Date`` and trailing ``Notes`` columns dropped —
# Date is the dedupe key, Notes is reserved for manual annotation and
# the importer never touches it).
HEALTH_METRICS_FIELDS_BY_SOURCE = {
    "xml": [
        "bodyweight_kg", "vo2max", "resting_hr", "hrv_sdnn",
        "walking_hr", "hr_recovery_1min", "sleep_total_h", "sleep_deep_h",
        "sleep_rem_h", "resp_rate", "wrist_temp_c", "sleep_breath_dist",
        "exercise_min",
    ],
    "hl_export": [
        "bodyweight_kg", "vo2max", "hr_recovery_1min",
        "sleep_total_h", "resp_rate",
    ],
}

WORKOUT_SESSIONS_HEADERS_BY_SOURCE = {
    "xml": [
        "Date", "Start", "End", "Apple Type", "Duration (min)",
        "Avg HR (bpm)", "Max HR (bpm)", "Min HR (bpm)",
        "Active Cal (kcal)", "Distance (km)", "Source", "Notes",
    ],
    "hl_export": [
        "Date", "Start", "End", "Apple Type", "Duration (min)",
        "Active Cal (kcal)", "Distance (km)", "Source", "Notes",
    ],
}

WORKOUT_SESSIONS_FIELDS_BY_SOURCE = {
    "xml": [
        "start", "end", "apple_type", "duration_min",
        "avg_hr", "max_hr", "min_hr",
        "active_cal", "distance_km", "source", "notes",
    ],
    "hl_export": [
        "start", "end", "apple_type", "duration_min",
        "active_cal", "distance_km", "source", "notes",
    ],
}

# Strength-metadata drift threshold (preserved verbatim from
# ``tracker_sheet.STRENGTH_METADATA_DRIFT_THRESHOLD``). Used by Workout
# Sessions sparse-merge and by the importer's monthly metadata writer.
STRENGTH_METADATA_DRIFT_THRESHOLD = 0.05


# ============================================================ Helpers
def _date_str(v) -> str | None:
    """Coerce a date-shaped value to ``YYYY-MM-DD`` or return None.

    Accepts datetime/date objects, an already-formatted ``YYYY-MM-DD``
    string, and a ``YYYY-MM-DD ...`` prefix (Apple's full ISO datetime).
    """
    if v in (None, ""):
        return None
    if isinstance(v, date_cls):
        return v.isoformat()
    s = str(v).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _parse_value(v: str | None):
    """Parse a CSV cell back into its native type.

    CSVs round-trip as strings; reverse the import-time coercion so
    downstream consumers see ints, floats, and Nones rather than the
    string ``"None"`` or numeric strings. Anything that can't be coerced
    stays as the original string (notes, source labels, etc.).
    """
    if v is None or v == "":
        return None
    s = str(v)
    # Try int, then float, then leave as string. Match openpyxl's
    # idiomatic typing so the rest of the pipeline doesn't care which
    # backend produced the value.
    try:
        if "." not in s and "e" not in s and "E" not in s:
            return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _serialize_value(v) -> str:
    """Inverse of ``_parse_value``: CSV-friendly string for any value."""
    if v is None:
        return ""
    if isinstance(v, bool):
        # str(True) = "True" — keep the lowercase form so the file
        # remains diffable across runs.
        return "true" if v else "false"
    return str(v)


def _strength_metadata_drifts(existing, incoming) -> bool:
    """5% threshold check for the manual-wins guard.

    Used only on Workout Sessions cells that already have a value; an
    incoming value within ±5% is treated as Apple jitter (no-op),
    outside ±5% is treated as a user-edited value the importer must
    not overwrite.
    """
    if existing in (None, ""):
        return False
    if incoming in (None, ""):
        return False
    try:
        e = float(existing)
        i = float(incoming)
    except (TypeError, ValueError):
        return str(existing).strip() != str(incoming).strip()
    if e == 0 and i == 0:
        return False
    denom = max(abs(e), abs(i), 1e-9)
    return abs(e - i) / denom >= STRENGTH_METADATA_DRIFT_THRESHOLD


# ============================================================ Profile (CSV)
PROFILE_KEYS = (
    "source", "auto_cardio", "birthday",
    "swim_css_sec_per_100m", "swim_css_set_at", "swim_pool_length_default",
)
PROFILE_DEFAULTS = {
    "source":                   None,
    "auto_cardio":              False,
    "birthday":                 None,
    "swim_css_sec_per_100m":    None,
    "swim_css_set_at":          None,
    "swim_pool_length_default": None,
}


def _coerce_bool(v):
    """Permissive bool coercion for hand-edited cells.

    Accepts ``True``/``False``, ``1``/``0``, ``"true"``/``"false"``,
    ``"yes"``/``"no"``, ``"y"``/``"n"`` (case-insensitive). Anything
    else returns ``None`` so the caller can re-apply the default
    rather than silently treating a typo as ``False``.
    """
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "yes", "y", "1", "on"):
        return True
    if s in ("false", "no", "n", "0", "off"):
        return False
    return None


def _coerce_float(v):
    """Permissive float coercion. Returns None on failure / empty / NaN."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        try:
            f = float(str(v).strip())
        except (TypeError, ValueError):
            return None
    if f != f:  # NaN
        return None
    return f


def _coerce_int(v):
    """Permissive int coercion. Accepts ``"25"``, ``25.0``, ``25``."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    f = _coerce_float(v)
    if f is None:
        return None
    return int(round(f))


def read_profile(person: str) -> dict:
    """Return the per-person profile dict.

    Missing CSV → all defaults. Missing or unrecognised value → that
    key's default. ``source`` stays ``None`` if the file is empty so
    callers can treat that as "not yet configured" and inject the
    inferred source from the export file extension.
    """
    out = dict(PROFILE_DEFAULTS)
    path = profile_csv(person)
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return out
        # Permissive: if the header is missing, treat the first row as
        # data too. Common when the file was hand-edited.
        if header and (header[0] or "").strip().lower() != "key":
            f.seek(0)
            reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            k = (row[0] or "").strip().lower()
            v = row[1] if len(row) > 1 else None
            if k == "key" and (v or "").strip().lower() == "value":
                continue  # header
            if k == "source":
                if v is None or v == "":
                    continue
                s = str(v).strip().lower()
                if s in ("xml", "hl_export"):
                    out["source"] = s
            elif k == "auto_cardio":
                b = _coerce_bool(v)
                if b is not None:
                    out["auto_cardio"] = b
            elif k == "birthday":
                d = _date_str(v)
                if d:
                    out["birthday"] = d
            elif k == "swim_css_sec_per_100m":
                f = _coerce_float(v)
                if f is not None:
                    out["swim_css_sec_per_100m"] = f
            elif k == "swim_css_set_at":
                d = _date_str(v)
                if d:
                    out["swim_css_set_at"] = d
            elif k == "swim_pool_length_default":
                i = _coerce_int(v)
                if i is not None:
                    out["swim_pool_length_default"] = i
    return out


def write_profile(person: str, **updates) -> None:
    """Update one or more profile keys; create the file if missing.

    Unknown keys are ignored. Booleans are written as lowercase
    ``true``/``false`` strings so the file stays diffable.
    """
    ensure_data_dir(person)
    current = read_profile(person)
    for k, v in updates.items():
        norm = k.strip().lower()
        if norm not in PROFILE_KEYS:
            continue
        current[norm] = v

    path = profile_csv(person)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["key", "value"])
        for key in PROFILE_KEYS:
            v = current.get(key)
            writer.writerow([key, _serialize_value(v)])


def ensure_profile(person: str,
                   default_source: str | None = None,
                   default_auto_cardio: bool | None = None) -> tuple[dict, bool]:
    """Bootstrap the profile CSV if missing; return ``(profile, created)``.

    ``default_source`` / ``default_auto_cardio`` are applied only when
    creating a fresh file — existing files are left alone (their values
    stand). Mirrors ``tracker_sheet.ensure_profile_sheet``.
    """
    path = profile_csv(person)
    if path.exists():
        return read_profile(person), False
    seeded = dict(PROFILE_DEFAULTS)
    if default_source is not None:
        seeded["source"] = default_source
    if default_auto_cardio is not None:
        seeded["auto_cardio"] = default_auto_cardio
    write_profile(person, **seeded)
    return seeded, True


# ============================================================ Health Metrics
def _resolve_source(person: str) -> str:
    """Read the active source from the person's profile.

    Falls back to ``xml`` when the profile is missing or unset — matches
    today's xlsx behaviour and keeps Nihad's tracker on the full schema
    by default.
    """
    src = read_profile(person).get("source")
    return src if src in ("xml", "hl_export") else "xml"


def _read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """Return ``(header, rows)`` from a CSV. Empty file → ``([], [])``."""
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return [], []
        return header, [row for row in reader if any(c.strip() for c in row)]


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    """Atomic-ish CSV write: full rewrite via tmp file + rename.

    All values are passed through ``_serialize_value`` so None becomes
    empty cells, booleans become lowercase strings, and numbers retain
    their native repr.
    """
    ensure_data_dir_for(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            writer.writerow([_serialize_value(v) for v in row])
    tmp.replace(path)


def ensure_data_dir_for(path: Path) -> None:
    """Internal helper: create the parent directory of a CSV path."""
    path.parent.mkdir(parents=True, exist_ok=True)


def read_health_metrics(person: str) -> list[dict]:
    """Return the Health Metrics rows as a list of dicts.

    Each dict has the per-source field keys (e.g. ``vo2max``,
    ``resting_hr``, ``sleep_total_h``) plus ``date`` and ``notes``.
    Sorted DESC by date (matches the on-disk order). Missing file →
    empty list.
    """
    source = _resolve_source(person)
    fields = HEALTH_METRICS_FIELDS_BY_SOURCE[source]
    headers = HEALTH_METRICS_HEADERS_BY_SOURCE[source]
    path = health_metrics_csv(person)
    header, rows = _read_csv_rows(path)
    if not header:
        return []
    out: list[dict] = []
    for row in rows:
        d = _date_str(row[0]) if row else None
        if d is None:
            continue
        rec: dict = {"date": d}
        for i, key in enumerate(fields, start=1):
            v = row[i] if len(row) > i else None
            rec[key] = _parse_value(v)
        notes = row[len(headers) - 1] if len(row) >= len(headers) else None
        rec["notes"] = notes if notes else None
        out.append(rec)
    return out


def upsert_health_metrics(person: str, entries: Iterable[dict]) -> list[str]:
    """Sparse-merge per-date Health Metrics rows into the CSV.

    Identical semantics to the old xlsx upsert: missing or None fields
    in ``entries`` never overwrite a populated cell, the rightmost
    ``Notes`` column is preserved, the file is sorted DESC by date on
    every write. Returns one summary string for the importer to print.
    """
    entries = list(entries or [])
    if not entries:
        return ["Health Metrics: 0 dates written / 0 updated"]

    source = _resolve_source(person)
    fields = HEALTH_METRICS_FIELDS_BY_SOURCE[source]
    headers = HEALTH_METRICS_HEADERS_BY_SOURCE[source]

    existing_rows = read_health_metrics(person)
    by_date: dict[str, dict] = {r["date"]: r for r in existing_rows}

    written = 0
    updated = 0
    seen_dates: set[str] = set()
    for e in entries:
        d = _date_str(e.get("date"))
        if not d:
            continue
        seen_dates.add(d)
        cur = by_date.get(d)
        if cur is None:
            new_record = {"date": d, "notes": None}
            for key in fields:
                v = e.get(key)
                new_record[key] = v if v is not None else None
            by_date[d] = new_record
            written += 1
            continue
        # Sparse-merge: incoming None never erases existing values.
        changed = False
        for key in fields:
            v = e.get(key)
            if v is None:
                continue
            if cur.get(key) != v:
                cur[key] = v
                changed = True
        if changed:
            updated += 1

    rows = []
    for d in sorted(by_date.keys(), reverse=True):
        rec = by_date[d]
        row = [d] + [rec.get(k) for k in fields] + [rec.get("notes")]
        rows.append(row)
    _write_csv(health_metrics_csv(person), headers, rows)

    if seen_dates:
        rng = f"{min(seen_dates)} → {max(seen_dates)}"
    else:
        rng = "no rows"
    return [f"Health Metrics: {written} dates written / {updated} updated (range {rng})"]


# ============================================================ Workout Sessions
def read_workout_sessions(person: str) -> list[dict]:
    """Return the Workout Sessions rows as a list of dicts.

    Each dict has ``date`` + the per-source field keys. Sorted DESC by
    (date, start). Missing file → empty list.
    """
    source = _resolve_source(person)
    fields = WORKOUT_SESSIONS_FIELDS_BY_SOURCE[source]
    path = workout_sessions_csv(person)
    header, rows = _read_csv_rows(path)
    if not header:
        return []
    out: list[dict] = []
    for row in rows:
        d = _date_str(row[0]) if row else None
        if d is None:
            continue
        rec: dict = {"date": d}
        for i, key in enumerate(fields, start=1):
            v = row[i] if len(row) > i else None
            rec[key] = _parse_value(v)
        out.append(rec)
    return out


def upsert_workout_sessions(person: str, entries: Iterable[dict]) -> list[str]:
    """Insert or overwrite Workout Sessions rows by (date, start) dedupe key.

    Same semantics as the old xlsx upsert: idempotent re-import is a
    no-op, identical (date, start) replaces the row entirely (used by
    the unit-aware distance refresh — when the importer fixes a 550
    km swim to 0.55 km, the existing record is replaced, not merged).
    Returns one summary line.
    """
    entries = list(entries or [])
    if not entries:
        return ["Workout Sessions: 0 sessions written / 0 updated"]

    source = _resolve_source(person)
    fields = WORKOUT_SESSIONS_FIELDS_BY_SOURCE[source]
    headers = WORKOUT_SESSIONS_HEADERS_BY_SOURCE[source]

    existing_rows = read_workout_sessions(person)
    by_key: dict[tuple, dict] = {(r["date"], r.get("start")): r for r in existing_rows}

    written = 0
    updated = 0
    incidental = 0
    for e in entries:
        d = _date_str(e.get("date"))
        s = e.get("start")
        if not d or s is None:
            continue
        key = (d, str(s))
        new_rec = {"date": d}
        for k in fields:
            new_rec[k] = e.get(k)
        if (e.get("notes") or "").lower().startswith("incidental"):
            incidental += 1
        if key in by_key:
            if by_key[key] != new_rec:
                by_key[key] = new_rec
                updated += 1
            # else: silent no-op (idempotency).
        else:
            by_key[key] = new_rec
            written += 1

    rows = []
    for k in sorted(by_key.keys(), reverse=True):
        rec = by_key[k]
        row = [rec["date"]] + [rec.get(field) for field in fields]
        rows.append(row)
    _write_csv(workout_sessions_csv(person), headers, rows)

    return [
        f"Workout Sessions: {written} sessions written / "
        f"{updated} updated ({incidental} walks flagged incidental)"
    ]


# ============================================================ Swim (per-workout)
# Per-swim aggregate row. Dedupe key = (date, start). Sorted DESC by
# date+start to mirror workout_sessions.csv layout. Notes is reserved
# for manual annotations and is preserved on every upsert (manual wins).
SWIM_WORKOUTS_HEADERS = [
    "Date", "Start", "End", "Duration (min)", "Distance (km)",
    "Pool Length (m)", "Laps", "Strokes", "SPL", "Avg SWOLF",
    "Stroke Mix", "Location", "Water Temp (°C)", "Avg HR (bpm)",
    "Active Cal", "Notes",
]

SWIM_WORKOUTS_FIELDS = [
    "start", "end", "duration_min", "distance_km",
    "pool_length_m", "laps", "strokes", "spl", "avg_swolf",
    "stroke_mix", "location", "water_temp_c", "avg_hr",
    "active_cal",
]

# Per-lap detail. Dedupe key = (date, workout_start, lap_num). Sorted
# ASC by (date, lap_num) for chart-friendliness. Replace-on-match
# (no sparse-merge) since lap data is fully Apple-sourced — there's no
# manual lap entry path today, and a re-export with corrected stroke
# styles must overwrite rather than preserve stale values.
SWIM_LAPS_HEADERS = [
    "Date", "Workout Start", "Lap #", "Stroke (raw)",
    "Stroke (decoded)", "Duration (sec)", "SWOLF", "Source",
]

SWIM_LAPS_FIELDS = [
    "workout_start", "lap_num", "stroke_raw", "stroke_decoded",
    "duration_sec", "swolf", "source",
]


def read_swim_workouts(person: str) -> list[dict]:
    """Return per-swim aggregate rows. Sorted DESC by (date, start).

    Missing file → ``[]``. Each dict has ``date`` plus the fields in
    ``SWIM_WORKOUTS_FIELDS`` plus ``notes``.
    """
    path = swim_workouts_csv(person)
    header, rows = _read_csv_rows(path)
    if not header:
        return []
    out: list[dict] = []
    for row in rows:
        d = _date_str(row[0]) if row else None
        if d is None:
            continue
        rec: dict = {"date": d}
        for i, key in enumerate(SWIM_WORKOUTS_FIELDS, start=1):
            v = row[i] if len(row) > i else None
            if key in ("start", "end", "stroke_mix", "location"):
                rec[key] = v if v not in (None, "") else None
            else:
                rec[key] = _parse_value(v)
        notes_idx = len(SWIM_WORKOUTS_HEADERS) - 1
        notes = row[notes_idx] if len(row) > notes_idx else None
        rec["notes"] = notes if notes else None
        out.append(rec)
    return out


def upsert_swim_workouts(person: str, entries: Iterable[dict]) -> list[str]:
    """Sparse-merge per-swim rows into ``swim_workouts.csv``.

    Dedupe by ``(date, start)``. Notes column is preserved untouched
    (manual annotation wins). Incoming None never overwrites a populated
    cell — the importer always writes complete records, but if Apple
    re-exports a swim with one field newly missing, we don't erase the
    stored value.
    """
    entries = list(entries or [])
    if not entries:
        return ["Swim Workouts: 0 sessions written / 0 updated"]

    existing = read_swim_workouts(person)
    by_key: dict[tuple, dict] = {(r["date"], r.get("start")): r for r in existing}

    written = 0
    updated = 0
    for e in entries:
        d = _date_str(e.get("date"))
        s = e.get("start")
        if not d or s is None:
            continue
        key = (d, str(s))
        cur = by_key.get(key)
        if cur is None:
            new_record = {"date": d, "notes": None}
            for k in SWIM_WORKOUTS_FIELDS:
                new_record[k] = e.get(k)
            by_key[key] = new_record
            written += 1
            continue
        changed = False
        for k in SWIM_WORKOUTS_FIELDS:
            v = e.get(k)
            if v is None:
                continue
            if cur.get(k) != v:
                cur[k] = v
                changed = True
        if changed:
            updated += 1

    ensure_swimming_dir(person)
    rows = []
    for k in sorted(by_key.keys(), reverse=True):
        rec = by_key[k]
        row = [rec["date"]] + [rec.get(field) for field in SWIM_WORKOUTS_FIELDS] \
            + [rec.get("notes")]
        rows.append(row)
    _write_csv(swim_workouts_csv(person), SWIM_WORKOUTS_HEADERS, rows)
    return [f"Swim Workouts: {written} sessions written / {updated} updated"]


def read_swim_laps(person: str) -> list[dict]:
    """Return per-lap rows sorted ASC by (date, lap_num).

    Missing file → ``[]``. Each dict has ``date`` plus the fields in
    ``SWIM_LAPS_FIELDS``.
    """
    path = swim_laps_csv(person)
    header, rows = _read_csv_rows(path)
    if not header:
        return []
    out: list[dict] = []
    for row in rows:
        d = _date_str(row[0]) if row else None
        if d is None:
            continue
        rec: dict = {"date": d}
        for i, key in enumerate(SWIM_LAPS_FIELDS, start=1):
            v = row[i] if len(row) > i else None
            if key in ("workout_start", "stroke_decoded", "source"):
                rec[key] = v if v not in (None, "") else None
            else:
                rec[key] = _parse_value(v)
        out.append(rec)
    out.sort(key=lambda r: (r["date"], r.get("lap_num") or 0))
    return out


def upsert_swim_laps(person: str, entries: Iterable[dict]) -> list[str]:
    """Replace-on-match upsert for ``swim_laps.csv``.

    Dedupe by ``(date, workout_start, lap_num)``. Lap data is fully
    Apple-sourced — there's no manual lap entry today — so re-imports
    are treated as authoritative replacement rather than sparse-merge.
    Sparse-merge would be active harm here: it'd preserve a stale
    stroke style if Apple corrects it in a later re-export.
    """
    entries = list(entries or [])
    if not entries:
        return ["Swim Laps: 0 laps written / 0 updated"]

    existing = read_swim_laps(person)
    by_key: dict[tuple, dict] = {
        (r["date"], r.get("workout_start"), r.get("lap_num")): r
        for r in existing
    }

    written = 0
    updated = 0
    for e in entries:
        d = _date_str(e.get("date"))
        ws = e.get("workout_start")
        ln = e.get("lap_num")
        if not d or ws is None or ln is None:
            continue
        key = (d, str(ws), int(ln))
        new_rec = {"date": d}
        for k in SWIM_LAPS_FIELDS:
            new_rec[k] = e.get(k)
        if key in by_key:
            if by_key[key] != new_rec:
                by_key[key] = new_rec
                updated += 1
        else:
            by_key[key] = new_rec
            written += 1

    ensure_swimming_dir(person)
    rows = []
    for k in sorted(by_key.keys(), key=lambda t: (t[0], t[2])):
        rec = by_key[k]
        row = [rec["date"]] + [rec.get(field) for field in SWIM_LAPS_FIELDS]
        rows.append(row)
    _write_csv(swim_laps_csv(person), SWIM_LAPS_HEADERS, rows)
    return [f"Swim Laps: {written} laps written / {updated} updated"]