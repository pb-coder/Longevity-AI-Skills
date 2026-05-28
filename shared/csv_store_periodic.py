"""Periodic CSV stores for swim, sleep, thermal, light, and nutrition data."""
from __future__ import annotations

from typing import Iterable

from csv_store_common import (
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
from person_paths import (
    ensure_data_dir,
    ensure_light_therapy_dir,
    ensure_sleep_dir,
    ensure_swimming_dir,
    ensure_thermal_dir,
    light_therapy_sessions_csv,
    nutrition_phases_csv,
    sleep_nights_csv,
    swim_laps_csv,
    swim_workouts_csv,
    thermal_sessions_csv,
)

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

# Hardcoded default heat temperature (°C) by type. When a /log entry
# sets ``heat_type`` but leaves ``heat_temp_c`` blank, the upsert fills
# the value from this table. Explicit user input always wins.
#
# Anchors are broad facility norms, not a per-person venue profile:
# - ``dry`` 90°C — common hot dry-sauna range.
# - ``bio`` 55°C — lower-temperature bio-sauna / sanarium range.
# - ``steam`` 45°C — warm-damp steam-room range.
# - ``infrared`` 45°C — radiant-cabin ambient range.
# - ``banya`` 70°C — humid high-heat range.
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


# ============================================================ Nutrition Phases (bulk / cut / maintain / recomp)
# Per-phase row store. Phases are sparse (a handful per year) so this is
# a single flat CSV at <person>/data/nutrition_phases.csv — no per-month
# split. Mirrors the "manual /log only" pattern (thermal, light_therapy):
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
