"""Dense per-person CSV stores: health metrics and workout sessions."""
from __future__ import annotations

from typing import Iterable

from .csv_store_common import _date_str, _parse_value, _read_csv_rows, _write_csv
from .csv_store_profile import read_profile
from .person_paths import health_metrics_csv, workout_sessions_csv

__all__ = [
    "HEALTH_METRICS_HEADERS_BY_SOURCE",
    "HEALTH_METRICS_FIELDS_BY_SOURCE",
    "WORKOUT_SESSIONS_HEADERS_BY_SOURCE",
    "WORKOUT_SESSIONS_FIELDS_BY_SOURCE",
    "STRENGTH_METADATA_DRIFT_THRESHOLD",
    "read_health_metrics",
    "upsert_health_metrics",
    "read_workout_sessions",
    "upsert_workout_sessions",
]

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


def _resolve_source(person: str) -> str:
    """Read the active source from the person's profile.

    Falls back to ``xml`` when the profile is missing or unset — matches
    today's xlsx behaviour and keeps <Person>'s tracker on the full schema
    by default.
    """
    src = read_profile(person).get("source")
    return src if src in HEALTH_METRICS_HEADERS_BY_SOURCE else "xml"


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
    by_key: dict[tuple, dict] = {
        (r["date"], str(r.get("start") or "")): r for r in existing_rows
    }

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
            existing = by_key[key]
            if existing.get("notes") not in (None, "") and new_rec.get("notes") in (None, ""):
                new_rec["notes"] = existing.get("notes")
            if existing.get("incidental") is not None and new_rec.get("incidental") in (None, False, ""):
                new_rec["incidental"] = existing.get("incidental")
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
