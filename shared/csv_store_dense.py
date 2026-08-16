"""Dense per-person CSV stores: health metrics and workout sessions."""
from __future__ import annotations

from typing import Iterable

from .csv_store_common import _date_str, _parse_value, _read_csv_rows, _write_csv
from .person_paths import health_metrics_csv, workout_sessions_csv

__all__ = [
    "DATA_SOURCE",
    "HEALTH_METRICS_HEADERS",
    "HEALTH_METRICS_FIELDS",
    "WORKOUT_SESSIONS_HEADERS",
    "WORKOUT_SESSIONS_FIELDS",
    "HEALTH_METRICS_HEADERS_BY_SOURCE",
    "HEALTH_METRICS_FIELDS_BY_SOURCE",
    "WORKOUT_SESSIONS_HEADERS_BY_SOURCE",
    "WORKOUT_SESSIONS_FIELDS_BY_SOURCE",
    "BODY_COMPOSITION_FIELDS",
    "BODY_COMPOSITION_LABELS",
    "body_composition_lines",
    "STRENGTH_METADATA_DRIFT_THRESHOLD",
    "read_health_metrics",
    "read_body_composition",
    "upsert_health_metrics",
    "migrate_health_metrics_header",
    "read_workout_sessions",
    "upsert_workout_sessions",
]

# ============================================================ Schema (HM + WS)
# HealthAutoExport is the only source. The ``*_BY_SOURCE`` mappings are
# retained as the public names every caller already imports, but they now
# hold a single canonical entry rather than a per-source variant.

# Schema migration 2026-08: ``Waist (cm)`` / ``Body Fat %`` /
# ``Lean Mass (kg)`` were appended immediately before ``Notes``, matching
# the ``Source``-column precedent on the monthly CSV. Older 16-column rows
# pad the three new cells to blank and self-migrate on the next write:
# ``read_health_metrics`` resolves every column by header *name*, so a file
# still carrying the old header keeps parsing and the missing fields read
# as None. Nothing reads this CSV positionally outside this module.

DATA_SOURCE = "health_auto_export"

# Schema migration 2026-08 (energy + steps): ``Steps`` /
# ``Active Energy (kcal)`` / ``Basal Energy (kcal)`` appended immediately
# before ``Notes``, the same position the body-composition columns took.
#
# The two energy components are stored rather than a single TDEE. TDEE is
# their sum and trivially derived, but the split carries information the
# sum destroys: active energy is a training-load signal, and basal energy
# trending down during a cut is adaptive thermogenesis — the single most
# useful thing this data can tell a cutting athlete, and invisible if
# only the total is kept.
HEALTH_METRICS_HEADERS = [
    "Date", "Bodyweight (kg)", "VO2max", "Resting HR", "HRV SDNN",
    "Walking HR", "HR Recovery 1min", "Sleep Total", "Sleep Deep",
    "Sleep REM", "Time in Bed", "Resp Rate", "Wrist Temp",
    "Sleep Breath Dist", "Exercise Min",
    "Waist (cm)", "Body Fat %", "Lean Mass (kg)",
    "Steps", "Active Energy (kcal)", "Basal Energy (kcal)", "Notes",
]

# Importer payload field names, in the same order as the headers above
# (with the leading ``Date`` and trailing ``Notes`` columns dropped —
# Date is the dedupe key, Notes is reserved for manual annotation and
# the importer never touches it).
HEALTH_METRICS_FIELDS = [
    "bodyweight_kg", "vo2max", "resting_hr", "hrv_sdnn",
    "walking_hr", "hr_recovery_1min", "sleep_total_h", "sleep_deep_h",
    "sleep_rem_h", "time_in_bed_h", "resp_rate", "wrist_temp_c",
    "sleep_breath_dist", "exercise_min",
    "waist_cm", "body_fat_pct", "lean_body_mass_kg",
    "steps", "active_energy_kcal", "basal_energy_kcal",
]

HEALTH_METRICS_HEADERS_BY_SOURCE = {DATA_SOURCE: HEALTH_METRICS_HEADERS}
HEALTH_METRICS_FIELDS_BY_SOURCE = {DATA_SOURCE: HEALTH_METRICS_FIELDS}

# Body-composition fields on health_metrics.csv, in schema order.
# ``bodyweight_kg`` is included: it is the same kind of measurement, and
# ``read_body_composition`` is the one read path for all four.
#
# Units: waist in centimetres, body fat in **percentage points** (18.0,
# not 0.18 — see health_units.normalize_body_fat_pct), lean mass and
# bodyweight in kilograms.
#
# All four accept manual entry, but not through ``/log``:
# ``append_workout.py`` takes ``bodyweight`` and nothing else, so waist,
# body fat and lean mass are typed into Apple's Health app (Browse ›
# Body Measurements) and reach this CSV on the next import. A ``/log``
# path for them is Wave-2 work and is not wired yet.
#
# Both importers write all four sparse-merged, so a hand-typed waist
# reading and a scale-sourced one land in the same column without either
# clobbering the other.
BODY_COMPOSITION_FIELDS = (
    "bodyweight_kg", "waist_cm", "body_fat_pct", "lean_body_mass_kg",
)

BODY_COMPOSITION_LABELS = {
    "bodyweight_kg": "Bodyweight",
    "waist_cm": "Waist",
    "body_fat_pct": "Body Fat",
    "lean_body_mass_kg": "Lean Mass",
}


def body_composition_lines(metric_entries: list[dict]) -> list[str]:
    """Report per-field body-composition coverage in the parsed window.

    Leanness is the one signal the tracker was blind to, and the exports
    seen so far carry Body Mass only. Printing an explicit ``0 dates`` for
    the fields that never appear keeps that gap visible as a
    data-collection problem instead of letting it read as a clean import.
    """
    lines = []
    for field in BODY_COMPOSITION_FIELDS:
        label = BODY_COMPOSITION_LABELS[field]
        dates = [e["date"] for e in metric_entries if e.get(field) is not None]
        if dates:
            lines.append(
                f"Body composition / {label}: {len(dates)} dates "
                f"(latest {max(dates)})"
            )
        else:
            lines.append(
                f"Body composition / {label}: 0 dates — not recorded in this export"
            )
    return lines

WORKOUT_SESSIONS_HEADERS = [
    "Date", "Start", "End", "Apple Type", "Duration (min)",
    "Avg HR (bpm)", "Max HR (bpm)", "Min HR (bpm)",
    "Active Cal (kcal)", "Distance (km)", "Source", "Incidental",
    "Notes",
]

WORKOUT_SESSIONS_FIELDS = [
    "start", "end", "apple_type", "duration_min",
    "avg_hr", "max_hr", "min_hr",
    "active_cal", "distance_km", "source", "incidental", "notes",
]

WORKOUT_SESSIONS_HEADERS_BY_SOURCE = {DATA_SOURCE: WORKOUT_SESSIONS_HEADERS}
WORKOUT_SESSIONS_FIELDS_BY_SOURCE = {DATA_SOURCE: WORKOUT_SESSIONS_FIELDS}

STRENGTH_METADATA_DRIFT_THRESHOLD = 0.05


# ============================================================ Helpers
def _resolve_source(_person: str) -> str:
    """Return the schema key for a person's stores.

    One source survives, so this is a constant. It stays a function
    because every read and write path calls it, and a tracker whose
    profile has not been migrated yet must still resolve to a real
    schema rather than raising a KeyError mid-read.
    """
    return DATA_SOURCE


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


def read_body_composition(person: str, field: str = "waist_cm") -> list[dict]:
    """Return the populated readings for one body-composition field, ASC by date.

    ``field`` is one of ``BODY_COMPOSITION_FIELDS`` — ``waist_cm``,
    ``body_fat_pct``, ``lean_body_mass_kg`` or ``bodyweight_kg``. Each
    entry is ``{"date": "YYYY-MM-DD", "value": <float>}``, the same shape
    and ascending-date contract the coach's ``extract.read_bodyweight``
    already returns for ``bodyweight_kg`` off this very CSV — so a trend
    helper written against one works against all four.

    Blank cells are skipped rather than yielded as ``0``: a column nobody
    has measured yet returns ``[]``, which reads as "no data" downstream
    instead of "flat at zero". Unknown field names raise ``ValueError``
    rather than silently returning ``[]``.
    """
    if field not in BODY_COMPOSITION_FIELDS:
        raise ValueError(
            f"unknown body-composition field {field!r}; "
            f"expected one of {', '.join(BODY_COMPOSITION_FIELDS)}"
        )
    out: list[dict] = []
    for entry in read_health_metrics(person):
        value = entry.get(field)
        if value is None:
            continue
        out.append({"date": entry["date"], "value": value})
    out.sort(key=lambda e: e["date"])
    return out


def migrate_health_metrics_header(person: str, dry_run: bool = False) -> str:
    """Rewrite health_metrics.csv under the current schema header.

    Reads are header-name-matched, so a file still on an older, narrower
    header parses correctly and the newer fields come back as None — the
    migration is not required for correctness. It matters only because
    ``maintain.py``'s validator compares the on-disk header to the schema
    by strict equality, and because the file self-migrates on the next
    importer or ``/log`` write anyway. This performs that same rewrite on
    demand: existing cells are re-serialised untouched and new columns pad
    to blank. Idempotent; a file already on the current header is left
    alone (no write, no mtime churn).

    Mutating, so it is never called from ``maintain.validate_csvs`` — the
    validator is diagnostics and stays read-only. ``maintain.py
    --fix-header`` is the opt-in entry point, matching the
    ``--fix-distance-units`` precedent. ``dry_run`` reports the rewrite
    it would perform and writes nothing.
    """
    source = _resolve_source(person)
    headers = HEALTH_METRICS_HEADERS_BY_SOURCE[source]
    fields = HEALTH_METRICS_FIELDS_BY_SOURCE[source]
    path = health_metrics_csv(person)
    on_disk, _rows = _read_csv_rows(path)
    if not on_disk:
        return "Health Metrics: no file to migrate"
    if on_disk == headers:
        return "Health Metrics: header already current"
    records = read_health_metrics(person)
    if dry_run:
        return (
            f"Health Metrics: header would migrate "
            f"({len(on_disk)} -> {len(headers)} columns, "
            f"{len(records)} rows preserved) — dry run, nothing written"
        )
    rows = [
        [rec["date"]] + [rec.get(k) for k in fields] + [rec.get("notes")]
        for rec in sorted(records, key=lambda r: r["date"], reverse=True)
    ]
    _write_csv(path, headers, rows)
    return (
        f"Health Metrics: header migrated "
        f"({len(on_disk)} -> {len(headers)} columns, {len(rows)} rows preserved)"
    )


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
