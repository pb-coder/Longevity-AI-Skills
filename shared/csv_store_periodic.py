"""Periodic CSV stores for swim, sleep, and nutrition data."""
from __future__ import annotations

from typing import Iterable

from .csv_store_common import (
    CsvTableSpec,
    _date_str,
    _group_entries_by_month,
    _parse_value,
    _read_csv_rows,
    _read_periodic_records,
    _write_csv,
    _write_periodic_records,
    replace_upsert_records,
    sparse_upsert_records,
)
from .person_paths import (
    ensure_data_dir,
    ensure_sleep_dir,
    ensure_swimming_dir,
    nutrition_phases_csv,
    sleep_nights_csv,
    swim_laps_csv,
    swim_workouts_csv,
)

__all__ = [
    "SWIM_WORKOUTS_HEADERS",
    "SWIM_WORKOUTS_FIELDS",
    "SWIM_LAPS_HEADERS",
    "SWIM_LAPS_FIELDS",
    "SLEEP_NIGHTS_HEADERS",
    "SLEEP_NIGHTS_FIELDS",
    "NUTRITION_PHASE_TYPES",
    "NUTRITION_PHASES_HEADERS",
    "NUTRITION_PHASES_FIELDS",
    "read_swim_workouts",
    "upsert_swim_workouts",
    "read_swim_laps",
    "upsert_swim_laps",
    "read_sleep_nights",
    "upsert_sleep_nights",
    "read_nutrition_phases",
    "upsert_nutrition_phases",
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
    """Return per-swim aggregate rows aggregated across all per-month
    swim CSVs (``<person>/data/swimming/YYYY.MM.workouts.csv``).
    Sorted DESC by (date, start).

    No swim files → ``[]``. Each dict has ``date`` plus the fields in
    ``SWIM_WORKOUTS_FIELDS`` plus ``notes``.
    """
    from .person_paths import list_swim_workout_months
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
    from .person_paths import list_swim_lap_months
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
        sort_fields=("date", "workout_start", "lap_num"),
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
# ``swimming/YYYY.MM.workouts.csv`` for scalability.
#
# Segment-level detail (the individual stage intervals) is NOT stored here,
# and is no longer recoverable. The per-night row does carry the count
# (N Segments) and the schedule (First/Last Segment Start): the Health
# Export Kit importer fills both (``n_segments`` = stage entries across the
# night's sessions; ``sleepStart`` / ``sleepEnd`` are what the Sleep
# Regularity Index reads). N Segments was blank on rows written by the
# retired HealthAutoExport (one aggregate row per night) and stays blank on
# manual ``/log`` nights, so ``sleep_summary``'s fragmentation reader
# degrades to null when no night in the window has a count rather than
# report a fabricated zero. A night that has no segment count did not
# become less fragmented.
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
    from .person_paths import list_sleep_night_months
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


# ============================================================ Nutrition Phases (bulk / cut / maintain / recomp)
# Per-phase row store. Phases are sparse (a handful per year) so this is
# a single flat CSV at <person>/data/nutrition_phases.csv — no per-month
# split. Uses the manual /log only pattern:
# the file is absent until the user logs their first phase via /log.
#
# Schema (one row per phase):
#   Start Date | End Date | Phase Type | Target Surplus/Deficit (kcal) |
#   Target Protein (g/kg) | Target Rate (kg/wk) | Stop Conditions | Notes
#
# Dedupe key = Start Date. An "open" phase has End Date blank. Closing a
# phase = an `upsert` with `end_date` set on the matching start_date row.
# The coach derives actuals (weeks elapsed, observed rate) from
# health_metrics.csv bodyweight trend, so daily macro logging is NOT
# required — phase metadata alone gives the coaching signal.
NUTRITION_PHASE_TYPES = {"bulk", "cut", "maintain", "recomp"}

NUTRITION_PHASES_HEADERS = [
    "Start Date", "End Date", "Phase Type",
    "Target Surplus/Deficit (kcal)", "Target Protein (g/kg)",
    "Target Rate (kg/wk)", "Stop Conditions", "Notes",
]

NUTRITION_PHASES_FIELDS = [
    "start_date", "end_date", "phase_type",
    "target_kcal_delta", "target_protein_g_per_kg",
    "target_rate_kg_per_wk", "stop_conditions", "notes",
]


def read_nutrition_phases(person: str) -> list[dict]:
    """Return every nutrition phase for ``person``, sorted DESC by start_date.

    Each dict has the ``NUTRITION_PHASES_FIELDS`` keys. ``end_date`` is
    None when the phase is open. Missing file → ``[]``. Stop conditions
    and notes are passthrough strings.
    """
    path = nutrition_phases_csv(person)
    header, rows = _read_csv_rows(path)
    if not header:
        return []
    out: list[dict] = []
    for row in rows:
        if not row or not row[0].strip():
            continue
        start = _date_str(row[0])
        if start is None:
            continue
        end = _date_str(row[1]) if len(row) > 1 and row[1].strip() else None
        phase_type = (row[2].strip().lower() if len(row) > 2 and row[2].strip() else None)
        rec = {
            "start_date": start,
            "end_date": end,
            "phase_type": phase_type,
            "target_kcal_delta": _parse_value(row[3]) if len(row) > 3 else None,
            "target_protein_g_per_kg": _parse_value(row[4]) if len(row) > 4 else None,
            "target_rate_kg_per_wk": _parse_value(row[5]) if len(row) > 5 else None,
            "stop_conditions": (row[6] or None) if len(row) > 6 else None,
            "notes": (row[7] or None) if len(row) > 7 else None,
        }
        out.append(rec)
    out.sort(key=lambda r: r["start_date"], reverse=True)
    return out


def upsert_nutrition_phases(person: str, entries: Iterable[dict]) -> list[str]:
    """Sparse-merge nutrition-phase rows into ``nutrition_phases.csv``.

    Dedupe key = ``start_date`` (one phase per start_date). For an
    existing row, incoming non-None fields overwrite (this is the
    "close a phase" path — caller passes ``{"start_date": ..., "end_date": ...}``);
    incoming None never overwrites a populated cell (sparse-merge).
    Notes is manual-wins (incoming wins only when provided non-empty).

    Validates ``phase_type`` against ``NUTRITION_PHASE_TYPES``. Unknown
    values raise ValueError so bad parser output never gets persisted.
    """
    entries = list(entries or [])
    if not entries:
        return ["Nutrition Phases: 0 phases written / 0 updated"]

    existing = read_nutrition_phases(person)
    by_start: dict[str, dict] = {r["start_date"]: dict(r) for r in existing}

    written = 0
    updated = 0
    for e in entries:
        start = _date_str(e.get("start_date"))
        if start is None:
            raise ValueError(f"nutrition phase missing start_date: {e!r}")
        pt = e.get("phase_type")
        if pt is not None:
            pt = str(pt).strip().lower()
            if pt not in NUTRITION_PHASE_TYPES:
                raise ValueError(f"unknown phase_type: {pt!r}")
        sanitized = {
            "start_date":              start,
            "end_date":                _date_str(e.get("end_date")) if e.get("end_date") else None,
            "phase_type":              pt,
            "target_kcal_delta":       e.get("target_kcal_delta"),
            "target_protein_g_per_kg": e.get("target_protein_g_per_kg"),
            "target_rate_kg_per_wk":   e.get("target_rate_kg_per_wk"),
            "stop_conditions":         e.get("stop_conditions"),
            "notes":                   e.get("notes"),
        }
        prev = by_start.get(start)
        if prev is None:
            by_start[start] = sanitized
            written += 1
        else:
            for k, v in sanitized.items():
                if v is not None and v != "":
                    prev[k] = v
            updated += 1

    # Sort DESC by start_date for on-disk stability.
    records = sorted(by_start.values(), key=lambda r: r["start_date"], reverse=True)

    rows = []
    for r in records:
        rows.append([
            r.get("start_date") or "",
            r.get("end_date") or "",
            r.get("phase_type") or "",
            r.get("target_kcal_delta") if r.get("target_kcal_delta") is not None else "",
            r.get("target_protein_g_per_kg") if r.get("target_protein_g_per_kg") is not None else "",
            r.get("target_rate_kg_per_wk") if r.get("target_rate_kg_per_wk") is not None else "",
            r.get("stop_conditions") or "",
            r.get("notes") or "",
        ])

    ensure_data_dir(person)
    _write_csv(nutrition_phases_csv(person), NUTRITION_PHASES_HEADERS, rows)

    return [f"Nutrition Phases: {written} written / {updated} updated"]
