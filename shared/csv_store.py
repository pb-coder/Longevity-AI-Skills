"""CSV-backed store for the dense, machine-only tracker data.

Handles the ``Health Metrics``, ``Workout Sessions``, and ``Profile``
files in ``<person>/data/`` (sparse-merge upserts, schema-by-source,
manual-wins drift guard, dedupe by date+start, sort DESC on every
write). Post-PR3a everything is flat CSV — the monthly
``YYYY.MM.csv`` files are handled separately by ``monthly_csv.py``.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.csv_table import (  # noqa: E402
    CsvTableSpec,
    date_str as _date_str,
    parse_value as _parse_value,
    read_csv_rows as _table_read_csv_rows,
    replace_upsert_records,
    serialize_value as _serialize_value,
    sparse_upsert_records,
    write_csv_atomic as _table_write_csv_atomic,
)

from person_paths import (
    ensure_data_dir,
    ensure_light_therapy_dir,
    ensure_sleep_dir,
    ensure_swimming_dir,
    ensure_thermal_dir,
    health_metrics_csv,
    light_therapy_sessions_csv,
    profile_csv,
    sleep_nights_csv,
    swim_laps_csv,
    swim_workouts_csv,
    thermal_sessions_csv,
    workout_sessions_csv,
)

# ============================================================ Schema (HM + WS)
# Source-aware column sets. ``xml`` is Apple's native export (full HRV /
# Resting HR / Wrist Temp / sleep stages / per-workout HR).
# ``health_auto_export`` is HealthAutoExport's ZIP export; for the tracker
# fields we consume, it has the same rich surface as ``xml``. ``hl_export``
# is the retired HLExport text dump — kept only so old CSVs can still be read
# during migration.

HEALTH_METRICS_HEADERS_BY_SOURCE = {
    "xml": [
        "Date", "Bodyweight (kg)", "VO2max", "Resting HR", "HRV SDNN",
        "Walking HR", "HR Recovery 1min", "Sleep Total", "Sleep Deep",
        "Sleep REM", "Time in Bed", "Resp Rate", "Wrist Temp",
        "Sleep Breath Dist", "Exercise Min", "Notes",
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
        "sleep_rem_h", "time_in_bed_h", "resp_rate", "wrist_temp_c",
        "sleep_breath_dist", "exercise_min",
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
        "Active Cal (kcal)", "Distance (km)", "Source", "Incidental",
        "Notes",
    ],
    "hl_export": [
        "Date", "Start", "End", "Apple Type", "Duration (min)",
        "Active Cal (kcal)", "Distance (km)", "Source", "Incidental",
        "Notes",
    ],
}

WORKOUT_SESSIONS_FIELDS_BY_SOURCE = {
    "xml": [
        "start", "end", "apple_type", "duration_min",
        "avg_hr", "max_hr", "min_hr",
        "active_cal", "distance_km", "source", "incidental", "notes",
    ],
    "hl_export": [
        "start", "end", "apple_type", "duration_min",
        "active_cal", "distance_km", "source", "incidental", "notes",
    ],
}

# HealthAutoExport stores the same tracker fields as the native Apple XML path.
HEALTH_METRICS_HEADERS_BY_SOURCE["health_auto_export"] = HEALTH_METRICS_HEADERS_BY_SOURCE["xml"]
HEALTH_METRICS_FIELDS_BY_SOURCE["health_auto_export"] = HEALTH_METRICS_FIELDS_BY_SOURCE["xml"]
WORKOUT_SESSIONS_HEADERS_BY_SOURCE["health_auto_export"] = WORKOUT_SESSIONS_HEADERS_BY_SOURCE["xml"]
WORKOUT_SESSIONS_FIELDS_BY_SOURCE["health_auto_export"] = WORKOUT_SESSIONS_FIELDS_BY_SOURCE["xml"]

# Strength-metadata drift threshold (preserved verbatim from
# ``tracker_sheet.STRENGTH_METADATA_DRIFT_THRESHOLD``). Used by Workout
# Sessions sparse-merge and by the importer's monthly metadata writer.
STRENGTH_METADATA_DRIFT_THRESHOLD = 0.05


# ============================================================ Helpers
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
    "light_therapy_target_per_week", "light_therapy_target_min_per_session",
)
PROFILE_DEFAULTS = {
    "source":                              None,
    "auto_cardio":                         False,
    "birthday":                            None,
    "swim_css_sec_per_100m":               None,
    "swim_css_set_at":                     None,
    "swim_pool_length_default":            None,
    "light_therapy_target_per_week":       None,
    "light_therapy_target_min_per_session": None,
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
                if s in ("xml", "health_auto_export", "hl_export"):
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
    return src if src in HEALTH_METRICS_HEADERS_BY_SOURCE else "xml"


def _read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """Return ``(header, rows)`` from a CSV. Empty file → ``([], [])``."""
    return _table_read_csv_rows(path)


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    """Atomic-ish CSV write: full rewrite via tmp file + rename.

    All values are passed through ``_serialize_value`` so None becomes
    empty cells, booleans become lowercase strings, and numbers retain
    their native repr.
    """
    _table_write_csv_atomic(path, header, rows)


def ensure_data_dir_for(path: Path) -> None:
    """Internal helper: create the parent directory of a CSV path."""
    path.parent.mkdir(parents=True, exist_ok=True)


def read_health_metrics(person: str) -> list[dict]:
    """Return the Health Metrics rows as a list of dicts.

    Each dict has the per-source field keys (e.g. ``vo2max``,
    ``resting_hr``, ``sleep_total_h``) plus ``date`` and ``notes``.
    Sorted DESC by date (matches the on-disk order). Missing file →
    empty list.

    Header-name-aware: the on-disk header is matched by column name
    against the expected schema, so adding columns to the schema in
    code does not require migrating old rows. Fields whose header is
    not present on disk read as None for every row.
    """
    source = _resolve_source(person)
    fields = HEALTH_METRICS_FIELDS_BY_SOURCE[source]
    expected_headers = HEALTH_METRICS_HEADERS_BY_SOURCE[source]
    path = health_metrics_csv(person)
    header, rows = _read_csv_rows(path)
    if not header:
        return []
    # Build {field_name: on_disk_column_index | None} using the field
    # ↔ header position alignment in the schema constants. Skip index 0
    # (Date) and the trailing Notes column.
    field_to_disk_idx: dict[str, int | None] = {}
    for schema_idx, fname in enumerate(fields, start=1):
        header_name = expected_headers[schema_idx]
        try:
            field_to_disk_idx[fname] = header.index(header_name)
        except ValueError:
            field_to_disk_idx[fname] = None
    # Locate Notes on disk by name (falls back to last column).
    try:
        notes_disk_idx = header.index("Notes")
    except ValueError:
        notes_disk_idx = len(header) - 1
    out: list[dict] = []
    for row in rows:
        d = _date_str(row[0]) if row else None
        if d is None:
            continue
        rec: dict = {"date": d}
        for fname, disk_idx in field_to_disk_idx.items():
            if disk_idx is None or disk_idx >= len(row):
                rec[fname] = None
            else:
                rec[fname] = _parse_value(row[disk_idx])
        notes = row[notes_disk_idx] if notes_disk_idx < len(row) else None
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

    Header-name-aware: the on-disk header is matched by column name
    against the expected schema, so adding columns to the schema in
    code does not require migrating old rows. Fields whose header is
    not present on disk read as None for every row. Used for the
    ``Incidental`` column added 2026-05; pre-existing 12-col rows
    read with ``incidental=None`` and the coach falls back to the
    legacy Notes-prefix check.
    """
    source = _resolve_source(person)
    fields = WORKOUT_SESSIONS_FIELDS_BY_SOURCE[source]
    expected_headers = WORKOUT_SESSIONS_HEADERS_BY_SOURCE[source]
    path = workout_sessions_csv(person)
    header, rows = _read_csv_rows(path)
    if not header:
        return []
    # Build {field_name: on_disk_column_index | None} using the field
    # ↔ header position alignment in the schema constants. Skip index 0
    # (Date).
    field_to_disk_idx: dict[str, int | None] = {}
    for schema_idx, fname in enumerate(fields, start=1):
        header_name = expected_headers[schema_idx]
        try:
            field_to_disk_idx[fname] = header.index(header_name)
        except ValueError:
            field_to_disk_idx[fname] = None
    out: list[dict] = []
    for row in rows:
        d = _date_str(row[0]) if row else None
        if d is None:
            continue
        rec: dict = {"date": d}
        for fname, disk_idx in field_to_disk_idx.items():
            if disk_idx is None or disk_idx >= len(row):
                rec[fname] = None
            else:
                rec[fname] = _parse_value(row[disk_idx])
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
        if e.get("incidental") is True:
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


def _date_to_year_month(date_str: str) -> str:
    """Convert ``YYYY-MM-DD`` to ``YYYY.MM`` (per-month CSV key)."""
    return f"{date_str[:4]}.{date_str[5:7]}"


def _group_entries_by_month(entries: Iterable[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for e in entries or []:
        d = _date_str(e.get("date"))
        if not d:
            continue
        item = dict(e)
        item["date"] = d
        grouped.setdefault(_date_to_year_month(d), []).append(item)
    return grouped


def _read_periodic_records(path: Path,
                           fields: list[str],
                           headers: list[str],
                           *,
                           string_fields: set[str] | None = None,
                           field_parsers: dict[str, callable] | None = None,
                           include_notes: bool = True) -> list[dict]:
    string_fields = string_fields or set()
    field_parsers = field_parsers or {}
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
            if key in field_parsers:
                rec[key] = field_parsers[key](v)
            elif key in string_fields:
                rec[key] = v if v not in (None, "") else None
            else:
                rec[key] = _parse_value(v)
        if include_notes:
            notes_idx = len(headers) - 1
            notes = row[notes_idx] if len(row) > notes_idx else None
            rec["notes"] = notes if notes else None
        out.append(rec)
    return out


def _write_periodic_records(path: Path,
                            headers: list[str],
                            fields: list[str],
                            records: list[dict],
                            *,
                            field_serializers: dict[str, callable] | None = None,
                            include_notes: bool = True) -> None:
    field_serializers = field_serializers or {}
    row_fields = ["date"] + fields + (["notes"] if include_notes else [])
    rows = []
    for rec in records:
        row = []
        for field in row_fields:
            v = rec.get(field)
            if field in field_serializers:
                v = field_serializers[field](v)
            row.append(v)
        rows.append(row)
    _write_csv(path, headers, rows)


def read_swim_workouts(person: str) -> list[dict]:
    """Return per-swim aggregate rows aggregated across all per-month
    swim CSVs (``<person>/data/swimming/YYYY.MM.workouts.csv``).
    Sorted DESC by (date, start).

    No swim files → ``[]``. Each dict has ``date`` plus the fields in
    ``SWIM_WORKOUTS_FIELDS`` plus ``notes``.
    """
    from person_paths import list_swim_workout_months
    out: list[dict] = []
    for ym in list_swim_workout_months(person):
        out.extend(_read_periodic_records(
            swim_workouts_csv(person, ym),
            SWIM_WORKOUTS_FIELDS,
            SWIM_WORKOUTS_HEADERS,
            string_fields={"start", "end", "stroke_mix", "location"},
        ))
    out.sort(key=lambda r: (r["date"], str(r.get("start") or "")), reverse=True)
    return out


def upsert_swim_workouts(person: str, entries: Iterable[dict]) -> list[str]:
    """Sparse-merge per-swim rows into the relevant
    ``<person>/data/swimming/YYYY.MM.workouts.csv``.

    Each entry is routed to its month by ``date``. Dedupe by
    ``(date, start)`` within that month. Notes column is preserved
    untouched (manual annotation wins). Incoming None never overwrites
    a populated cell.
    """
    entries = list(entries or [])
    if not entries:
        return ["Swim Workouts: 0 sessions written / 0 updated"]

    by_month_entries = _group_entries_by_month(entries)

    total_written = 0
    total_updated = 0
    summaries: list[str] = []
    spec = CsvTableSpec(
        headers=SWIM_WORKOUTS_HEADERS,
        fields=["date"] + SWIM_WORKOUTS_FIELDS + ["notes"],
        key_fields=("date", "start"),
        sort_fields=("date", "start"),
        sort_reverse=True,
    )
    for ym, month_entries in sorted(by_month_entries.items()):
        path = swim_workouts_csv(person, ym)
        existing = _read_periodic_records(
            path,
            SWIM_WORKOUTS_FIELDS,
            SWIM_WORKOUTS_HEADERS,
            string_fields={"start", "end", "stroke_mix", "location"},
        )
        records, written, updated = sparse_upsert_records(existing, month_entries, spec)
        ensure_swimming_dir(person)
        _write_periodic_records(path, SWIM_WORKOUTS_HEADERS, SWIM_WORKOUTS_FIELDS, records)
        total_written += written
        total_updated += updated
        summaries.append(f"  {ym}: {written} written / {updated} updated")

    return [f"Swim Workouts: {total_written} sessions written / "
            f"{total_updated} updated across {len(by_month_entries)} month(s)"] + summaries


def read_swim_laps(person: str) -> list[dict]:
    """Return per-lap rows aggregated across all per-month swim-laps
    CSVs (``<person>/data/swimming/YYYY.MM.laps.csv``).
    Sorted ASC by (date, lap_num).

    No swim files → ``[]``. Each dict has ``date`` plus the fields in
    ``SWIM_LAPS_FIELDS``.
    """
    from person_paths import list_swim_lap_months
    out: list[dict] = []
    for ym in list_swim_lap_months(person):
        out.extend(_read_periodic_records(
            swim_laps_csv(person, ym),
            SWIM_LAPS_FIELDS,
            SWIM_LAPS_HEADERS,
            string_fields={"workout_start", "stroke_decoded", "source"},
            include_notes=False,
        ))
    out.sort(key=lambda r: (r["date"], r.get("lap_num") or 0))
    return out


def upsert_swim_laps(person: str, entries: Iterable[dict]) -> list[str]:
    """Replace-on-match upsert into per-month
    ``<person>/data/swimming/YYYY.MM.laps.csv``.

    Each entry is routed to its month by ``date``. Dedupe within the
    month by ``(date, workout_start, lap_num)``. Lap data is fully
    Apple-sourced — there's no manual lap entry today — so re-imports
    are treated as authoritative replacement rather than sparse-merge.
    """
    entries = list(entries or [])
    if not entries:
        return ["Swim Laps: 0 laps written / 0 updated"]

    by_month_entries = _group_entries_by_month(entries)

    total_written = 0
    total_updated = 0
    summaries: list[str] = []
    spec = CsvTableSpec(
        headers=SWIM_LAPS_HEADERS,
        fields=["date"] + SWIM_LAPS_FIELDS,
        key_fields=("date", "workout_start", "lap_num"),
        sort_fields=("date", "lap_num"),
        sort_reverse=False,
        notes_field=None,
    )

    def _sanitize_lap(e: dict) -> dict | None:
        if e.get("workout_start") is None or e.get("lap_num") is None:
            return None
        out = {"date": e["date"]}
        for k in SWIM_LAPS_FIELDS:
            out[k] = e.get(k)
        out["workout_start"] = str(out["workout_start"])
        out["lap_num"] = int(out["lap_num"])
        return out

    for ym, month_entries in sorted(by_month_entries.items()):
        path = swim_laps_csv(person, ym)
        existing = _read_periodic_records(
            path,
            SWIM_LAPS_FIELDS,
            SWIM_LAPS_HEADERS,
            string_fields={"workout_start", "stroke_decoded", "source"},
            include_notes=False,
        )
        records, written, updated = replace_upsert_records(
            existing, month_entries, spec, sanitize=_sanitize_lap,
        )
        ensure_swimming_dir(person)
        _write_periodic_records(
            path, SWIM_LAPS_HEADERS, SWIM_LAPS_FIELDS, records,
            include_notes=False,
        )
        total_written += written
        total_updated += updated
        summaries.append(f"  {ym}: {written} written / {updated} updated")

    return [f"Swim Laps: {total_written} laps written / "
            f"{total_updated} updated across {len(by_month_entries)} month(s)"] + summaries


# ============================================================ Sleep (per-night)
# Per-night aggregate row. Dedupe key = ``Date`` (wake-up date). Sorted
# DESC by date. Sparse-merge with manual-wins on Notes. Mirrors the
# per-month-CSV pattern of ``monthly/YYYY.MM.csv`` and
# ``swimming/YYYY.MM.workouts.csv`` for scalability. XML-only — HL
# trackers never populate this folder. Segment-level detail is NOT
# stored here; the per-night row captures fragmentation via N Segments
# and schedule via First/Last Segment Start. Raw segments stay in the
# archived Apple XML at ``<root>/.processed/Export*.zip`` and can be
# re-extracted if a future need arises.
SLEEP_NIGHTS_HEADERS = [
    "Date",
    "Sleep Total (h)", "Sleep Core (h)", "Sleep Deep (h)",
    "Sleep REM (h)", "Sleep Unspecified (h)", "Sleep Awake (h)",
    "Time in Bed (h)", "Sleep Efficiency (%)",
    "N Segments", "First Segment Start", "Last Segment End",
    "Notes",
]

SLEEP_NIGHTS_FIELDS = [
    "total_h", "core_h", "deep_h", "rem_h", "unspecified_h",
    "awake_h", "time_in_bed_h", "efficiency_pct",
    "n_segments", "first_segment_start", "last_segment_end",
]


def _compute_sleep_efficiency(total_h, time_in_bed_h):
    """Return Sleep Efficiency % rounded to 1dp, or None if either input
    is missing / zero."""
    if total_h is None or time_in_bed_h is None:
        return None
    try:
        if float(time_in_bed_h) <= 0:
            return None
        return round(float(total_h) / float(time_in_bed_h) * 100.0, 1)
    except (TypeError, ValueError):
        return None


def read_sleep_nights(person: str) -> list[dict]:
    """Return per-night aggregate rows across all per-month sleep CSVs
    (``<person>/data/sleep/YYYY.MM.nights.csv``). Sorted DESC by ``date``.

    No sleep files → ``[]``. Each dict has ``date`` plus the fields in
    ``SLEEP_NIGHTS_FIELDS`` plus ``notes``.
    """
    from person_paths import list_sleep_night_months
    out: list[dict] = []
    for ym in list_sleep_night_months(person):
        out.extend(_read_periodic_records(
            sleep_nights_csv(person, ym),
            SLEEP_NIGHTS_FIELDS,
            SLEEP_NIGHTS_HEADERS,
            string_fields={"first_segment_start", "last_segment_end"},
        ))
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def upsert_sleep_nights(person: str, entries: Iterable[dict]) -> list[str]:
    """Sparse-merge per-night rows into the relevant
    ``<person>/data/sleep/YYYY.MM.nights.csv``.

    Each entry is routed to its month by ``date``. Dedupe by ``date``
    within that month. Notes column is preserved untouched (manual
    annotation wins). Incoming None never overwrites a populated cell.

    Sleep Efficiency is auto-derived when ``total_h`` and
    ``time_in_bed_h`` are both present and ``efficiency_pct`` wasn't
    supplied explicitly. ``n_segments`` and the first/last segment
    clock times stay blank on manual-only rows (only the Apple
    importer carries that metadata).
    """
    entries = list(entries or [])
    if not entries:
        return ["Sleep Nights: 0 nights written / 0 updated"]

    by_month_entries = _group_entries_by_month(entries)

    total_written = 0
    total_updated = 0
    summaries: list[str] = []
    spec = CsvTableSpec(
        headers=SLEEP_NIGHTS_HEADERS,
        fields=["date"] + SLEEP_NIGHTS_FIELDS + ["notes"],
        key_fields=("date",),
        sort_fields=("date",),
        sort_reverse=True,
    )

    def _derive_sleep(rec: dict, entry: dict | None) -> None:
        if entry and entry.get("efficiency_pct") is not None:
            return
        derived = _compute_sleep_efficiency(
            rec.get("total_h"), rec.get("time_in_bed_h"),
        )
        if derived is not None:
            rec["efficiency_pct"] = derived

    for ym, month_entries in sorted(by_month_entries.items()):
        path = sleep_nights_csv(person, ym)
        existing = _read_periodic_records(
            path,
            SLEEP_NIGHTS_FIELDS,
            SLEEP_NIGHTS_HEADERS,
            string_fields={"first_segment_start", "last_segment_end"},
        )
        records, written, updated = sparse_upsert_records(
            existing, month_entries, spec, derive=_derive_sleep,
        )
        ensure_sleep_dir(person)
        _write_periodic_records(path, SLEEP_NIGHTS_HEADERS, SLEEP_NIGHTS_FIELDS, records)
        total_written += written
        total_updated += updated
        summaries.append(f"  {ym}: {written} written / {updated} updated")

    return [f"Sleep Nights: {total_written} nights written / "
            f"{total_updated} updated across {len(by_month_entries)} month(s)"] + summaries


# ============================================================ Thermal (sauna + cold)
# Per-session row capturing one heat-and/or-cold protocol session. Manual
# /log only — Apple Health doesn't reliably surface sauna or cold-exposure
# sessions. One row can be heat-only (sauna without cold), cold-only
# (e.g. standalone morning cold shower), or paired (sauna → cold exposure).
# Mirrors the per-month-CSV pattern of ``monthly/``, ``swimming/``, and
# ``sleep/`` for scalability.
#
# Multi-round saunas ("2 saunas after each other") are stored as a single
# row with ``Heat Round Durations (min)`` = comma-separated per-round
# minutes (e.g. ``"12,8"``). ``Heat Total (min)`` is the sum, written on
# every upsert for cheap reads.
THERMAL_SESSIONS_HEADERS = [
    "Date", "Start",
    "Heat Type", "Heat Temp (°C)", "Heat Rounds",
    "Heat Round Durations (min)", "Heat Total (min)",
    "Cold Type", "Cold Duration (sec)", "Cold Temp (°C)",
    "Notes",
]

THERMAL_SESSIONS_FIELDS = [
    "start",
    "heat_type", "heat_temp_c", "heat_rounds",
    "heat_round_durations_min", "heat_total_min",
    "cold_type", "cold_duration_sec", "cold_temp_c",
]

# Enum constants. Kept here so the parser and the coach can import a
# single source of truth and refuse unknown values.
HEAT_TYPES = {"dry", "bio", "steam", "infrared", "banya", "none"}
COLD_TYPES = {"none", "cold_air", "cold_shower", "cold_plunge", "cold_water"}

# Hardcoded default heat temperature (°C) by type, anchored to Germany /
# Holmes Place practice (the user's primary gym chain). When a /log
# entry sets ``heat_type`` but leaves ``heat_temp_c`` blank, the upsert
# fills the value from this table. Explicit user input always wins.
#
# Anchors:
# - ``dry`` 90°C — Finnische Sauna at Holmes Place Potsdamer Platz;
#   Bismarckstraße runs ~95°C. Range 80-100°C across German clubs.
# - ``bio`` 55°C — Sanarium / Bio-Sauna, ~45-60°C / ~50% RH. Distinct
#   German wellness type; Holmes Place Potsdamer Platz operates one.
# - ``steam`` 45°C — Dampfbad. Warm-damp, ~40-50°C, ~100% RH.
# - ``infrared`` 45°C — Infrarotkabine. Heat is radiant (IR rays
#   warming the body, not the air); ambient ~40-50°C. Common
#   misconception puts this at 60°C — the cabinet feels hotter than
#   the air reads.
# - ``banya`` 70°C — Russian banya; humid, löyly culture.
#
# A per-tracker override via ``profile.csv`` (e.g.
# ``sauna_default_temp_c``) is a future-easy follow-up if needed.
HEAT_TYPE_DEFAULT_TEMP_C: dict[str, int | None] = {
    "dry":      90,
    "bio":      55,
    "steam":    45,
    "infrared": 45,
    "banya":    70,
    "none":     None,
}


def _format_round_durations(value) -> str | None:
    """Serialize the round-durations list to the CSV cell string.

    Accepts a list of numbers (``[12, 8]``), a string already in
    canonical form (``"12,8"``), or None. Returns the CSV cell value.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    if isinstance(value, (list, tuple)):
        parts = [str(int(x)) if float(x).is_integer() else str(x) for x in value]
        return ",".join(parts) if parts else None
    return None


def _parse_round_durations(cell) -> list[float] | None:
    """Inverse of ``_format_round_durations``: cell string → list of floats."""
    if cell is None or cell == "":
        return None
    if isinstance(cell, (list, tuple)):
        return [float(x) for x in cell]
    out: list[float] = []
    for part in str(cell).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            return None
    return out or None


def _sum_round_durations(durations) -> float | None:
    """Return the sum of round durations as the Heat Total cell value."""
    parsed = _parse_round_durations(durations)
    if not parsed:
        return None
    total = sum(parsed)
    return round(total, 2) if total else None


def read_thermal_sessions(person: str) -> list[dict]:
    """Return per-session thermal rows across all per-month CSVs.

    Sorted DESC by ``(date, start)``. Each dict has ``date`` plus the
    fields in ``THERMAL_SESSIONS_FIELDS`` plus ``notes``. Empty when
    the ``thermal/`` folder is absent.
    """
    from person_paths import list_thermal_session_months
    out: list[dict] = []
    for ym in list_thermal_session_months(person):
        out.extend(_read_periodic_records(
            thermal_sessions_csv(person, ym),
            THERMAL_SESSIONS_FIELDS,
            THERMAL_SESSIONS_HEADERS,
            string_fields={"start", "heat_type", "cold_type"},
            field_parsers={"heat_round_durations_min": _parse_round_durations},
        ))
    out.sort(key=lambda r: (r["date"], str(r.get("start") or "")), reverse=True)
    return out


def upsert_thermal_sessions(person: str, entries: Iterable[dict]) -> list[str]:
    """Sparse-merge per-session thermal rows into the right
    ``<person>/data/thermal/YYYY.MM.sessions.csv``.

    Dedupe key = ``(date, start)`` within the month. Notes is manual-wins.
    ``heat_total_min`` is auto-derived from
    ``heat_round_durations_min`` on every write (whether the caller
    supplied it or not) so the file is internally consistent.

    Validates ``heat_type`` against ``HEAT_TYPES`` and ``cold_type``
    against ``COLD_TYPES``. Unknown values raise ``ValueError`` so bad
    parser output does not disappear during a write.
    """
    entries = list(entries or [])
    if not entries:
        return ["Thermal Sessions: 0 sessions written / 0 updated"]

    by_month_entries = _group_entries_by_month(entries)

    total_written = 0
    total_updated = 0
    summaries: list[str] = []
    spec = CsvTableSpec(
        headers=THERMAL_SESSIONS_HEADERS,
        fields=["date"] + THERMAL_SESSIONS_FIELDS + ["notes"],
        key_fields=("date", "start"),
        sort_fields=("date", "start"),
        sort_reverse=True,
    )

    def _sanitize_thermal(e: dict) -> dict:
        ht = e.get("heat_type")
        if ht is not None and ht not in HEAT_TYPES:
            raise ValueError(f"unknown heat_type: {ht!r}")
        ct = e.get("cold_type")
        if ct is not None and ct not in COLD_TYPES:
            raise ValueError(f"unknown cold_type: {ct!r}")

        durations = _parse_round_durations(e.get("heat_round_durations_min"))
        heat_total = _sum_round_durations(durations) if durations else (
            _parse_value(e.get("heat_total_min"))
        )
        heat_temp = e.get("heat_temp_c")
        if heat_temp is None and ht is not None and ht != "none":
            heat_temp = HEAT_TYPE_DEFAULT_TEMP_C.get(ht)

        return {
            "date": e["date"],
            "start": e.get("start") or "",
            "heat_type": ht,
            "heat_temp_c": heat_temp,
            "heat_rounds": (
                e.get("heat_rounds")
                if e.get("heat_rounds") is not None
                else (len(durations) if durations else None)
            ),
            "heat_round_durations_min": durations,
            "heat_total_min": heat_total,
            "cold_type": ct,
            "cold_duration_sec": e.get("cold_duration_sec"),
            "cold_temp_c": e.get("cold_temp_c"),
            "notes": e.get("notes"),
        }

    def _derive_thermal(rec: dict, _entry: dict | None) -> None:
        derived = _sum_round_durations(rec.get("heat_round_durations_min"))
        if derived is not None:
            rec["heat_total_min"] = derived

    for ym, month_entries in sorted(by_month_entries.items()):
        path = thermal_sessions_csv(person, ym)
        existing = _read_periodic_records(
            path,
            THERMAL_SESSIONS_FIELDS,
            THERMAL_SESSIONS_HEADERS,
            string_fields={"start", "heat_type", "cold_type"},
            field_parsers={"heat_round_durations_min": _parse_round_durations},
        )
        records, written, updated = sparse_upsert_records(
            existing, month_entries, spec,
            sanitize=_sanitize_thermal,
            derive=_derive_thermal,
        )
        ensure_thermal_dir(person)
        _write_periodic_records(
            path,
            THERMAL_SESSIONS_HEADERS,
            THERMAL_SESSIONS_FIELDS,
            records,
            field_serializers={"heat_round_durations_min": _format_round_durations},
        )
        total_written += written
        total_updated += updated
        summaries.append(f"  {ym}: {written} written / {updated} updated")

    return [f"Thermal Sessions: {total_written} sessions written / "
            f"{total_updated} updated across {len(by_month_entries)} month(s)"] + summaries


# ============================================================ Light therapy (photobiomodulation)
# Per-session row for any light-based recovery / wellness protocol —
# red-light therapy (RLT) cabins, near-IR probes, blue-light SAD lamps,
# etc. Manual-/log-only — Apple Health doesn't classify these.
#
# Schema is intentionally lean: ``duration_min`` is the only required
# operational field. Wavelength, body area, modality, and ambient temp
# are optional descriptors most users won't bother to record. The store
# is broad enough to cover future wavelengths (blue/green/white)
# without schema churn.
LIGHT_THERAPY_SESSIONS_HEADERS = [
    "Date", "Start",
    "Duration (min)",
    "Light Type", "Wavelength (nm)",
    "Body Area", "Modality",
    "Ambient Temp (°C)",
    "Notes",
]

LIGHT_THERAPY_SESSIONS_FIELDS = [
    "start",
    "duration_min",
    "light_type", "wavelength_nm",
    "body_area", "modality",
    "ambient_temp_c",
]

# Enum constants. Imported by the logger parser and the coach so all
# three layers refuse unknown values from a single source of truth.
LIGHT_TYPES = {
    "red", "near_ir", "red+ir", "far_ir",
    "blue", "green", "white", "other",
}
LIGHT_BODY_AREAS = {
    "full_body", "face", "back", "torso",
    "arms", "legs", "head", "localized",
}
LIGHT_MODALITIES = {
    "panel", "mask", "wand", "cabin", "device", "sauna_integrated",
}

# Threshold above which a session is assumed to be in a heated walk-in
# cabin (commercial RLT cabins typically run ~40-50°C). When the user
# logs an ambient temp at/above this and didn't specify a modality, the
# upsert defaults ``modality`` to ``cabin``.
HEATED_CABIN_AMBIENT_TEMP_C = 30


def read_light_therapy_sessions(person: str) -> list[dict]:
    """Return per-session light-therapy rows across all per-month CSVs.

    Sorted DESC by ``(date, start)``. Each dict has ``date`` plus the
    fields in ``LIGHT_THERAPY_SESSIONS_FIELDS`` plus ``notes``. Empty
    when the ``light_therapy/`` folder is absent.
    """
    from person_paths import list_light_therapy_session_months
    out: list[dict] = []
    for ym in list_light_therapy_session_months(person):
        out.extend(_read_periodic_records(
            light_therapy_sessions_csv(person, ym),
            LIGHT_THERAPY_SESSIONS_FIELDS,
            LIGHT_THERAPY_SESSIONS_HEADERS,
            string_fields={"start", "light_type", "body_area", "modality"},
        ))
    out.sort(key=lambda r: (r["date"], str(r.get("start") or "")), reverse=True)
    return out


def upsert_light_therapy_sessions(person: str, entries: Iterable[dict]) -> list[str]:
    """Sparse-merge per-session light-therapy rows into the right
    ``<person>/data/light_therapy/YYYY.MM.sessions.csv``.

    Dedupe key = ``(date, start)`` within the month. Notes is manual-wins.
    ``modality`` defaults to ``cabin`` when the user supplied an ambient
    temp at/above the heated-cabin threshold and left modality blank.

    Validates ``light_type`` against ``LIGHT_TYPES``, ``body_area``
    against ``LIGHT_BODY_AREAS``, and ``modality`` against
    ``LIGHT_MODALITIES``. Unknown values raise ``ValueError`` so bad
    parser output doesn't disappear into the CSV.
    """
    entries = list(entries or [])
    if not entries:
        return ["Light Therapy Sessions: 0 sessions written / 0 updated"]

    by_month_entries = _group_entries_by_month(entries)

    total_written = 0
    total_updated = 0
    summaries: list[str] = []
    spec = CsvTableSpec(
        headers=LIGHT_THERAPY_SESSIONS_HEADERS,
        fields=["date"] + LIGHT_THERAPY_SESSIONS_FIELDS + ["notes"],
        key_fields=("date", "start"),
        sort_fields=("date", "start"),
        sort_reverse=True,
    )

    def _sanitize_light(e: dict) -> dict:
        lt = e.get("light_type")
        if lt is not None and lt not in LIGHT_TYPES:
            raise ValueError(f"unknown light_type: {lt!r}")
        ba = e.get("body_area")
        if ba is not None and ba not in LIGHT_BODY_AREAS:
            raise ValueError(f"unknown body_area: {ba!r}")
        md = e.get("modality")
        if md is not None and md not in LIGHT_MODALITIES:
            raise ValueError(f"unknown modality: {md!r}")

        ambient = e.get("ambient_temp_c")
        if md is None and ambient is not None:
            try:
                if float(ambient) >= HEATED_CABIN_AMBIENT_TEMP_C:
                    md = "cabin"
            except (TypeError, ValueError):
                pass

        return {
            "date": e["date"],
            "start": e.get("start") or "",
            "duration_min": e.get("duration_min"),
            "light_type": lt,
            "wavelength_nm": e.get("wavelength_nm"),
            "body_area": ba,
            "modality": md,
            "ambient_temp_c": ambient,
            "notes": e.get("notes"),
        }

    for ym, month_entries in sorted(by_month_entries.items()):
        path = light_therapy_sessions_csv(person, ym)
        existing = _read_periodic_records(
            path,
            LIGHT_THERAPY_SESSIONS_FIELDS,
            LIGHT_THERAPY_SESSIONS_HEADERS,
            string_fields={"start", "light_type", "body_area", "modality"},
        )
        records, written, updated = sparse_upsert_records(
            existing, month_entries, spec,
            sanitize=_sanitize_light,
        )
        ensure_light_therapy_dir(person)
        _write_periodic_records(
            path,
            LIGHT_THERAPY_SESSIONS_HEADERS,
            LIGHT_THERAPY_SESSIONS_FIELDS,
            records,
        )
        total_written += written
        total_updated += updated
        summaries.append(f"  {ym}: {written} written / {updated} updated")

    return [f"Light Therapy Sessions: {total_written} sessions written / "
            f"{total_updated} updated across {len(by_month_entries)} month(s)"] + summaries
