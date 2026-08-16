"""Import HealthAutoExport data into the tracker CSV store.

The only importer. It reads two archive layouts, selected by which member
the ZIP carries:

- **JSON** (``HealthAutoExport-*.json``) — the supported format. One
  document holds every metric series, every workout and every sleep
  night, under canonical English names regardless of phone locale. Route
  GPX files may sit alongside it and are ignored.
- **CSV** (``HealthAutoExport-*.csv`` + ``Workouts-*.csv``) — deprecated,
  kept alive only until every tracker's phone settings have moved to
  JSON. It is localised and carries no sleep timestamps, so the Sleep
  Regularity Index cannot be computed from it.

Both paths write the same surface: daily HRV / resting HR / walking HR /
wrist temp / breathing disturbances / exercise minutes / body
composition, per-night sleep architecture, per-workout sessions with
average / max / min HR, and per-workout swim aggregates.

Usage:
    python3 import_health_auto_export.py --person <Person> \\
        --zip HealthAutoExport_20260815173415.zip \\
        --since 2026-04-01 --until 2026-05-17 \\
        --allow-past-months --replace-range
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(SKILLS_ROOT))
    __package__ = "shared"

from tracker import TrackerContext  # noqa: E402
from tracker.importing import build_auto_cardio_payload  # noqa: E402
from .health_units import (  # noqa: E402
    LENGTH_UNIT_TO_CM,
    MASS_UNIT_TO_KG,
    TEMP_UNIT_TO_C,
    convert_unit,
    normalize_body_fat_pct,
    plausible_or_none,
)
from .apple_workout_types import (  # noqa: E402
    APPLE_TO_TRACKER_EXERCISE,
    CARDIO_AUTOLOG_TYPES,
)
from .csv_store import (  # noqa: E402
    HEALTH_METRICS_FIELDS,
    HEALTH_METRICS_HEADERS,
    WORKOUT_SESSIONS_FIELDS,
    WORKOUT_SESSIONS_HEADERS,
    body_composition_lines,
    ensure_profile,
    read_health_metrics,
    read_profile,
    read_workout_sessions,
    upsert_health_metrics,
    upsert_sleep_nights,
    upsert_swim_workouts,
    upsert_workout_sessions,
    write_profile,
    _write_csv as _write_store_csv,
)
from .data_git import commit_data  # noqa: E402
from .strength_sessions import cluster_strength_sessions  # noqa: E402
from .monthly_csv import (  # noqa: E402
    TOTAL_LABEL,
    _dict_to_row,
    _is_auto_imported,
    _read_csv_rows,
    _row_to_dict,
    _write_csv_atomic,
    canonicalize_monthly_csv,
    date_str,
    list_year_months,
    upsert_monthly_cardio,
    upsert_monthly_strength_session,
)
from .person_paths import (  # noqa: E402
    WORKOUT_TRACKER_ROOT,
    monthly_csv as monthly_csv_path,
)


SOURCE_NAME = "health_auto_export"
WORKOUT_SOURCE_LABEL = "HealthAutoExport"


class EmptyImportError(RuntimeError):
    """Raised when an export yields neither health metrics nor sleep nights.

    Exit 0 on a zero-row import is a silent failure that reads as success:
    pointing the importer at a localised CSV export produced
    ``Health Metrics: 0 dates written`` and a clean exit, and nothing
    downstream noticed the tracker had not moved. Every real export
    carries at least one of the two, so the empty case is a wrong file or
    a wrong date window, never a legitimate no-op. Raised before anything
    is written, so a failed run leaves the store untouched.
    """
KJ_TO_KCAL = 1.0 / 4.184
INCIDENTAL_WALK_MAX_MIN = 15.0

PER_WORKOUT_FILE_RE = re.compile(
    r"^(?P<type>.+?)-(?P<metric>.+)-(?P<stamp>\d{8}_\d{6})\.(?P<ext>csv|gpx)$"
)

WORKOUT_TYPE_MAP = {
    "Outdoor Cycling": "Cycling",
    "Indoor Cycling": "IndoorCycling",
    "Outdoor Walk": "Walking",
    "Indoor Walk": "IndoorWalking",
    "Traditional Strength Training": "TraditionalStrengthTraining",
    "Functional Strength Training": "FunctionalStrengthTraining",
    "Hiking": "Hiking",
    "Indoor Run": "IndoorRunning",
    "Outdoor Run": "Running",
    "HIIT": "HighIntensityIntervalTraining",
    "High Intensity Interval Training": "HighIntensityIntervalTraining",
    "Swimming": "Swimming",
    "Pool Swim": "Swimming",
    "Open Water Swim": "Swimming",
}

DAILY_COLUMNS = {
    "bodyweight_kg": "Weight (kg)",
    "vo2max": "VO2 Max (ml/(kg·min))",
    "resting_hr": "Resting Heart Rate (count/min)",
    "hrv_sdnn": "Heart Rate Variability (ms)",
    "walking_hr": "Walking Heart Rate Average (count/min)",
    "hr_recovery_1min": "Cardio Recovery (count/min)",
    "sleep_total_h": "Sleep Analysis [Total] (hr)",
    "sleep_deep_h": "Sleep Analysis [Deep] (hr)",
    "sleep_rem_h": "Sleep Analysis [REM] (hr)",
    "time_in_bed_h": "Sleep Analysis [In Bed] (hr)",
    "resp_rate": "Respiratory Rate (count/min)",
    "wrist_temp_c": "Apple Sleeping Wrist Temperature (degC)",
    "sleep_breath_dist": "Breathing Disturbances (count)",
    "exercise_min": "Apple Exercise Time (min)",
}

# Body-composition columns. HealthAutoExport exposes all three metrics the
# native XML path reads — verified against a real export's header:
# ``Waist Circumference (cm)``, ``Body Fat Percentage (%)``,
# ``Lean Body Mass (kg)`` — so the two sources stay symmetric.
#
# These are resolved by header *prefix* rather than by fixed name because
# HealthAutoExport bakes the user's in-app unit preference into the header
# ("Waist Circumference (in)" on an imperial export). A fixed metric-only
# lookup would silently miss those rows. ``converters=None`` means the
# value is not a unit conversion but an encoding normalisation — see
# ``normalize_body_fat_pct``.
BODY_COMPOSITION_COLUMNS = {
    "waist_cm": ("Waist Circumference", LENGTH_UNIT_TO_CM, 1),
    "body_fat_pct": ("Body Fat Percentage", None, 2),
    "lean_body_mass_kg": ("Lean Body Mass", MASS_UNIT_TO_KG, 2),
}

_UNIT_SUFFIX_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<unit>[^()]*)\)\s*$")

WORKOUT_REQUIRED_COLUMNS = [
    "Workout Type",
    "Start",
    "Duration",
    "Active Energy (kJ)",
    "Resting Energy (kJ)",
]

# Fields ``--replace-range`` wipes before re-importing a window. Body
# composition is deliberately absent, for the same reason ``bodyweight_kg``
# always has been: those cells hold user-entered readings, and a range
# clear would destroy data the export cannot regenerate.
#
# The manual route today is Apple's own Health app — Browse › Body
# Measurements › Waist Circumference / Body Fat Percentage / Lean Body
# Mass — which the next export then carries into this importer. A
# tape-measure reading typed there is indistinguishable from a
# scale-sourced one in the export, so ``--replace-range`` cannot tell
# them apart and must not clear either. ``/log`` has no waist / body-fat
# / lean-mass path: ``append_workout.py`` accepts ``bodyweight`` only.
# Wiring one is Wave-2 work; when it lands, this list stays as it is.
RANGE_FIELDS_TO_CLEAR = [
    "vo2max", "resting_hr", "hrv_sdnn", "walking_hr",
    "hr_recovery_1min", "sleep_total_h", "sleep_deep_h", "sleep_rem_h",
    "time_in_bed_h", "resp_rate", "wrist_temp_c", "sleep_breath_dist",
    "exercise_min",
]

MONTHLY_TOTAL_METADATA_FIELDS = [
    "duration", "avg_hr", "active_cal", "total_cal", "elevation_m", "elapsed",
]


def to_float(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def round_or_none(v, digits: int = 2):
    f = to_float(v)
    if f is None:
        return None
    return round(f, digits)


def positive_or_none(v, digits: int = 2):
    f = to_float(v)
    if f is None or f <= 0:
        return None
    return round(f, digits)


def parse_since(s: str | None) -> date | None:
    if s is None:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"date must be YYYY-MM-DD ({e})")


def default_since() -> date:
    return date.today() - timedelta(days=183)


def _date_in_range(d: str | None, since: date | None, until: date | None) -> bool:
    if not d:
        return False
    try:
        cur = datetime.strptime(d[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    if since and cur < since:
        return False
    if until and cur > until:
        return False
    return True


def _find_one(names: list[str], prefix: str) -> str:
    matches = [n for n in names if n.startswith(prefix) and n.endswith(".csv")]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {prefix}*.csv, found {len(matches)}")
    return matches[0]


def _parse_daily_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _resolve_unit_column(columns, prefix: str) -> tuple[str | None, str | None]:
    """Locate a ``<prefix> (<unit>)`` column in a HealthAutoExport header.

    Returns ``(column_name, unit)``, or ``(None, None)`` when the export
    does not carry the metric. HealthAutoExport writes the unit the user
    picked in the app, so the unit token cannot be assumed.
    """
    for name in columns:
        if not name or not name.startswith(prefix):
            continue
        m = _UNIT_SUFFIX_RE.match(name)
        if m and m.group("name").strip() == prefix:
            return name, m.group("unit").strip()
    return None, None


def _resolve_body_composition_columns(header_row: dict) -> dict[str, tuple]:
    """Map each body-composition field to its ``(column, unit)`` in this export."""
    return {
        key: _resolve_unit_column(header_row.keys(), prefix)
        for key, (prefix, _conv, _digits) in BODY_COMPOSITION_COLUMNS.items()
    }


def _body_composition_values(row: dict, resolved: dict[str, tuple]) -> dict:
    """Read + convert the body-composition cells of one daily row.

    An absent column, a blank cell, or a non-positive reading all yield
    None so the sparse-merge upsert leaves the stored cell untouched
    instead of stamping a zero over it.

    Converted values pass a plausibility gate before they are returned —
    the header unit is the user's in-app preference, so an export can
    hand over a perfectly well-formed ``Waist Circumference (m)`` column
    whose values are three orders of magnitude off. See
    ``health_units.PLAUSIBLE_RANGES``.
    """
    out: dict = {}
    for key, (prefix, converters, digits) in BODY_COMPOSITION_COLUMNS.items():
        column, unit = resolved.get(key, (None, None))
        raw = to_float(row.get(column)) if column else None
        if raw is None or raw <= 0:
            out[key] = None
            continue
        if converters is None:
            # Body fat: an encoding normalisation, not a unit conversion.
            # The header unit still has to be read and gated, or a
            # "Body Fat Percentage (cubits)" column would be accepted as
            # percent while the waist column beside it drops loudly.
            out[key] = normalize_body_fat_pct(raw, unit)
            continue
        converted = convert_unit(raw, unit, converters, prefix.lower())
        if converted is None:
            out[key] = None
            continue
        out[key] = plausible_or_none(
            round(converted, digits), key, prefix.lower(), unit
        )
    return out


def parse_daily_rows(rows: list[dict], since: date | None, until: date | None) -> tuple[list[dict], list[dict]]:
    metric_entries: list[dict] = []
    sleep_entries: list[dict] = []
    body_comp_columns: dict[str, tuple] = {k: (None, None) for k in BODY_COMPOSITION_COLUMNS}
    if rows:
        missing = [col for col in DAILY_COLUMNS.values() if col not in rows[0]]
        body_comp_columns = _resolve_body_composition_columns(rows[0])
        missing.extend(
            f"{prefix} (<unit>)"
            for key, (prefix, _conv, _digits) in BODY_COMPOSITION_COLUMNS.items()
            if body_comp_columns[key][0] is None
        )
        for col in missing:
            print(f"WARN: HealthAutoExport daily column missing: {col}", file=sys.stderr)
    for row in rows:
        d = _parse_daily_date(row.get("Date/Time"))
        if not _date_in_range(d, since, until):
            continue

        time_in_bed = positive_or_none(row.get(DAILY_COLUMNS["time_in_bed_h"]), 2)
        metric_entries.append({
            **_body_composition_values(row, body_comp_columns),
            "date": d,
            "bodyweight_kg": round_or_none(row.get(DAILY_COLUMNS["bodyweight_kg"]), 2),
            "vo2max": round_or_none(row.get(DAILY_COLUMNS["vo2max"]), 2),
            "resting_hr": round_or_none(row.get(DAILY_COLUMNS["resting_hr"]), 1),
            "hrv_sdnn": round_or_none(row.get(DAILY_COLUMNS["hrv_sdnn"]), 2),
            "walking_hr": round_or_none(row.get(DAILY_COLUMNS["walking_hr"]), 1),
            "hr_recovery_1min": round_or_none(row.get(DAILY_COLUMNS["hr_recovery_1min"]), 1),
            "sleep_total_h": round_or_none(row.get(DAILY_COLUMNS["sleep_total_h"]), 2),
            "sleep_deep_h": round_or_none(row.get(DAILY_COLUMNS["sleep_deep_h"]), 2),
            "sleep_rem_h": round_or_none(row.get(DAILY_COLUMNS["sleep_rem_h"]), 2),
            "time_in_bed_h": time_in_bed,
            "resp_rate": round_or_none(row.get(DAILY_COLUMNS["resp_rate"]), 2),
            "wrist_temp_c": round_or_none(row.get(DAILY_COLUMNS["wrist_temp_c"]), 2),
            "sleep_breath_dist": round_or_none(row.get(DAILY_COLUMNS["sleep_breath_dist"]), 2),
            "exercise_min": round_or_none(row.get(DAILY_COLUMNS["exercise_min"]), 1),
        })

        total = round_or_none(row.get("Sleep Analysis [Total] (hr)"), 2)
        core = round_or_none(row.get("Sleep Analysis [Core] (hr)"), 2)
        deep = round_or_none(row.get("Sleep Analysis [Deep] (hr)"), 2)
        rem = round_or_none(row.get("Sleep Analysis [REM] (hr)"), 2)
        awake = round_or_none(row.get("Sleep Analysis [Awake] (hr)"), 2)
        unspecified = None
        if total is not None:
            known = sum(v or 0.0 for v in (core, deep, rem))
            residual = round(total - known, 2)
            if residual > 0.01:
                unspecified = residual
        if any(v is not None for v in (total, core, deep, rem, awake, time_in_bed)):
            sleep_entries.append({
                "date": d,
                "total_h": total,
                "core_h": core,
                "deep_h": deep,
                "rem_h": rem,
                "unspecified_h": unspecified,
                "awake_h": awake,
                "time_in_bed_h": time_in_bed,
                "efficiency_pct": None,
                "n_segments": None,
                "first_segment_start": None,
                "last_segment_end": None,
            })
    return metric_entries, sleep_entries


def _duration_minutes(value: str | None) -> float | None:
    if not value:
        return None
    parts = value.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60.0
        if len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60.0
    except ValueError:
        return None
    return to_float(value)


def _parse_workout_minute(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _parse_stamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d_%H%M%S")


def _hhmmss(value: datetime | None) -> str | None:
    return value.strftime("%H:%M:%S") if value else None


def _canonical_workout_type(raw_type: str) -> str:
    return WORKOUT_TYPE_MAP.get(raw_type, raw_type.replace(" ", ""))


def _stamp_index(infos: list[zipfile.ZipInfo]) -> dict[tuple[str, str], set[str]]:
    index: dict[tuple[str, str], set[str]] = defaultdict(set)
    for info in infos:
        m = PER_WORKOUT_FILE_RE.match(info.filename)
        if not m:
            continue
        stamp = m.group("stamp")
        index[(m.group("type"), stamp[:13])].add(stamp)
    return index


def _heart_rate_stats(zf: zipfile.ZipFile) -> dict[tuple[str, str], dict]:
    stats: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: {"min": [], "max": [], "avg": []}
    )
    for info in zf.infolist():
        m = PER_WORKOUT_FILE_RE.match(info.filename)
        if not m or m.group("metric") != "Heart Rate" or m.group("ext") != "csv":
            continue
        with zf.open(info) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""))
            for row in reader:
                for out_key, col in (
                    ("min", "Min (count/min)"),
                    ("max", "Max (count/min)"),
                    ("avg", "Avg (count/min)"),
                ):
                    v = to_float(row.get(col))
                    if v is not None:
                        stats[(m.group("type"), m.group("stamp"))][out_key].append(v)
    out: dict[tuple[str, str], dict] = {}
    for key, values in stats.items():
        mins = values["min"]
        maxes = values["max"]
        avgs = values["avg"]
        out[key] = {
            "min_hr": int(round(min(mins))) if mins else None,
            "max_hr": int(round(max(maxes))) if maxes else None,
            "avg_hr": round(sum(avgs) / len(avgs), 1) if avgs else None,
        }
    return out


def parse_workout_rows(
    rows: list[dict],
    stamp_index: dict[tuple[str, str], set[str]],
    hr_stats: dict[tuple[str, str], dict],
    since: date | None,
    until: date | None,
) -> list[dict]:
    out: list[dict] = []
    if rows:
        missing = [col for col in WORKOUT_REQUIRED_COLUMNS if col not in rows[0]]
        for col in missing:
            print(f"WARN: HealthAutoExport workout column missing: {col}", file=sys.stderr)
    for row in rows:
        raw_type = (row.get("Workout Type") or "").strip()
        start_minute = _parse_workout_minute(row.get("Start"))
        if start_minute is None:
            continue
        minute_key = start_minute.strftime("%Y%m%d_%H%M")
        stamps = sorted(stamp_index.get((raw_type, minute_key), set()))
        start_dt = start_minute
        d = start_dt.date().isoformat()
        if not _date_in_range(d, since, until):
            continue

        duration = _duration_minutes(row.get("Duration"))
        end_dt = start_dt + timedelta(minutes=duration) if duration else _parse_workout_minute(row.get("End"))
        apple_type = _canonical_workout_type(raw_type)

        active_cal = None
        active_kj = to_float(row.get("Active Energy (kJ)"))
        if active_kj is not None:
            active_cal = round(active_kj * KJ_TO_KCAL, 1)
        basal_cal = None
        basal_kj = to_float(row.get("Resting Energy (kJ)"))
        if basal_kj is not None:
            basal_cal = round(basal_kj * KJ_TO_KCAL, 1)
        total_cal = None
        if active_cal is not None and basal_cal is not None:
            total_cal = round(active_cal + basal_cal, 1)

        stamp_key = (raw_type, stamps[0]) if len(stamps) == 1 else None
        hr = hr_stats.get(stamp_key, {}) if stamp_key else {}
        avg_hr = round_or_none(row.get("Avg. Heart Rate (count/min)"), 1) or hr.get("avg_hr")
        max_hr = round_or_none(row.get("Max. Heart Rate (count/min)"), 0) or hr.get("max_hr")
        min_hr = hr.get("min_hr")
        distance_km = positive_or_none(row.get("Distance (km)"), 3)
        elevation_m = positive_or_none(row.get("Elevation Ascended (m)"), 1)
        incidental = (
            "Walking" in apple_type
            and duration is not None
            and duration < INCIDENTAL_WALK_MAX_MIN
        )

        out.append({
            "date": d,
            "start": _hhmmss(start_dt),
            "end": _hhmmss(end_dt),
            "apple_type": apple_type,
            "duration_min": round(duration, 1) if duration is not None else None,
            "avg_hr": round(float(avg_hr), 1) if avg_hr is not None else None,
            "max_hr": int(round(float(max_hr))) if max_hr is not None else None,
            "min_hr": int(round(float(min_hr))) if min_hr is not None else None,
            "active_cal": active_cal,
            "basal_cal": basal_cal,
            "total_cal": total_cal,
            "elevation_m": elevation_m,
            "elapsed_min": round(duration, 1) if duration is not None else None,
            "distance_km": distance_km,
            "source": WORKOUT_SOURCE_LABEL,
            "incidental": incidental,
            "notes": None,
            "stamp_status": "ambiguous" if len(stamps) > 1 else None,
        })
    return out


# ============================================================ JSON reader
# HealthAutoExport's JSON mode is the supported export format. Metric and
# workout names are canonical English even on a localised phone (the CSV
# export writes "Aktive Energie (kJ)" and "Traditionelles Krafttraining"
# on a German device and would need a translation layer), sleep carries
# the segment timestamps the Sleep Regularity Index is computed from, and
# the export is windowed rather than full-history.
#
# Metric points come in exactly three shapes:
#   {date, qty, source}                          every scalar metric
#   {date, Min, Max, Avg, source}                heart_rate only
#   {date, source, totalSleep, core, deep, rem,
#    awake, asleep, inBed, sleepStart, sleepEnd,
#    inBedStart, inBedEnd}                       sleep_analysis only
#
# ``date`` is "YYYY-MM-DD HH:MM:SS +HHMM". The offset is stripped and the
# stamp read as naive local wall-clock, which is what the CSV store and
# compute_sleep_regularity_index already assume end to end.

AGG_MEAN = "mean"
AGG_SUM = "sum"
AGG_LATEST = "latest"
AGG_MAX = "max"

# Daily roll-up strategy per metric, and the parity contract with the
# retired XML importer. This is the highest-risk table in the importer:
# rolling HRV up as latest-of-day instead of mean, or resting HR as mean
# instead of latest, yields numbers that look entirely plausible while
# silently shifting every recovery z-score, and no downstream assertion
# would catch it.
#
# Each entry below mirrors the ``DayAggregator`` handler of the same name
# one for one, with a single deliberate exception: ``cardio_recovery`` is
# MAX, not LATEST. The XML handler for HeartRateRecoveryOneMinute kept
# the *largest* reading of the day rather than the last one, so
# best-recovery-of-day is the quantity the recovery model was calibrated
# against and the quantity that has to keep arriving.
#
# The SUM group beyond ``apple_exercise_time`` is new surface: those
# record types were never in the XML importer's WANTED_RECORD_TYPES, so
# there is no prior behaviour to match and cumulative quantity samples
# sum by definition.
METRIC_AGGREGATION = {
    # --- mean of the day
    "heart_rate_variability": AGG_MEAN,
    "respiratory_rate": AGG_MEAN,
    "blood_oxygen_saturation": AGG_MEAN,
    "physical_effort": AGG_MEAN,
    "walking_speed": AGG_MEAN,
    "walking_step_length": AGG_MEAN,
    "walking_double_support_percentage": AGG_MEAN,
    "walking_asymmetry_percentage": AGG_MEAN,
    "stair_speed_up": AGG_MEAN,
    "stair_speed_down": AGG_MEAN,
    # --- latest of the day, by timestamp
    "resting_heart_rate": AGG_LATEST,
    "walking_heart_rate_average": AGG_LATEST,
    "vo2_max": AGG_LATEST,
    "weight_body_mass": AGG_LATEST,
    "waist_circumference": AGG_LATEST,
    "body_fat_percentage": AGG_LATEST,
    "lean_body_mass": AGG_LATEST,
    "apple_sleeping_wrist_temperature": AGG_LATEST,
    "breathing_disturbances": AGG_LATEST,
    # --- best of the day (see the cardio_recovery note above)
    "cardio_recovery": AGG_MAX,
    # --- sum of the day
    "active_energy": AGG_SUM,
    "basal_energy_burned": AGG_SUM,
    "step_count": AGG_SUM,
    "flights_climbed": AGG_SUM,
    "apple_exercise_time": AGG_SUM,
    "apple_stand_time": AGG_SUM,
    "apple_stand_hour": AGG_SUM,
    "time_in_daylight": AGG_SUM,
    "walking_running_distance": AGG_SUM,
    "cycling_distance": AGG_SUM,
    "swimming_distance": AGG_SUM,
    "swimming_stroke_count": AGG_SUM,
    # --- present in the export, deliberately not stored daily.
    # ``underwater_temperature`` is read per workout window rather than
    # per day (see ``parse_json_workouts``); the rest are listed so a
    # genuinely new metric name still trips the warning below instead of
    # being lost among four that are simply not wanted.
    "underwater_temperature": AGG_MEAN,
    "underwater_depth": AGG_MAX,
    # An occasional Watch estimate, not a series — latest wins, as for vo2_max.
    "six_minute_walking_test_distance": AGG_LATEST,
    "environmental_audio_exposure": AGG_MEAN,
    "headphone_audio_exposure": AGG_MEAN,
}

# Metrics stamped at sleep ONSET that belong to the night's WAKE date.
#
# The XML aggregator bucketed these two — and only these two — by the
# record's ``endDate`` rather than its start (``_set_latest(store,
# d_end or d, ...)``), precisely so an overnight reading landed on the
# morning it belongs to. HealthAutoExport collapses each reading to a
# single timestamp taken at sleep onset: 24 of 31 wrist-temperature
# stamps in the reference export fall between 22:00 and 23:59. Bucketing
# those by their own calendar day files every pre-midnight bedtime one
# night early, so the row for a given date carries the *next* night's
# wrist temperature beside that date's sleep totals — and
# ``recovery_score``'s wrist-temp deviation reads it per date.
#
# The 18:00 rollover is the same cutoff the XML sleep aggregator used to
# decide which night a segment belonged to, so both stores agree on where
# a night begins.
SLEEP_ONSET_METRICS = frozenset({
    "apple_sleeping_wrist_temperature",
    "breathing_disturbances",
})
SLEEP_NIGHT_ROLLOVER_HOUR = 18

# A record shorter than this is a nap, not a night. HealthAutoExport's
# in-bed window equals the sleep window, so a nap would derive a 100%
# efficiency and pull the efficiency trend up for a reason unrelated to
# sleep quality. Same floor the XML aggregator applied to its derived
# in-bed span.
MIN_DERIVED_TIME_IN_BED_H = 2.0

# ``heart_rate`` carries Min/Max/Avg per point rather than ``qty``: the
# day's mean is the mean of Avg and the day's peak is the max of Max. No
# daily HR column exists on health_metrics.csv, so nothing is stored
# today; the aggregation is spelled out here so that adding one is a
# mapping change rather than a fresh derivation.
HEART_RATE_AGGREGATION = {"mean": ("Avg", AGG_MEAN), "max": ("Max", AGG_MAX)}

# Aggregated metric -> health_metrics.csv payload field, with the
# rounding and unit handling the stored column expects. ``converters``
# None means the metric arrives in the stored unit already;
# ``plausible_key`` names a PLAUSIBLE_RANGES entry applied after
# conversion. Metrics aggregated above but absent here are rolled up and
# then dropped: they are either consumed elsewhere (the energy and step
# fields are added in the daily-TDEE phase) or carried for future use.
JSON_METRIC_FIELDS = {
    "weight_body_mass": ("bodyweight_kg", 2, MASS_UNIT_TO_KG, "body mass", None),
    "vo2_max": ("vo2max", 2, None, None, None),
    "resting_heart_rate": ("resting_hr", 1, None, None, None),
    "heart_rate_variability": ("hrv_sdnn", 2, None, None, None),
    "walking_heart_rate_average": ("walking_hr", 1, None, None, None),
    "cardio_recovery": ("hr_recovery_1min", 1, None, None, None),
    "respiratory_rate": ("resp_rate", 2, None, None, None),
    "apple_sleeping_wrist_temperature": ("wrist_temp_c", 3, TEMP_UNIT_TO_C, "temperature", None),
    "breathing_disturbances": ("sleep_breath_dist", 4, None, None, None),
    "apple_exercise_time": ("exercise_min", 1, None, None, None),
    "waist_circumference": ("waist_cm", 1, LENGTH_UNIT_TO_CM, "waist circumference", "waist_cm"),
    "lean_body_mass": ("lean_body_mass_kg", 2, MASS_UNIT_TO_KG, "lean body mass", "lean_body_mass_kg"),
    "step_count": ("steps", 0, None, None, None),
}

# Daily energy. Stored as two components rather than one TDEE, in kcal.
# Both arrive as kilojoules — HealthAutoExport reports every energy
# quantity in kJ, workouts included — so the conversion is not optional.
JSON_ENERGY_FIELDS = {
    "active_energy": "active_energy_kcal",
    "basal_energy_burned": "basal_energy_kcal",
}

# Body fat is an encoding normalisation rather than a unit conversion, so
# it takes the same dedicated path the CSV reader uses instead of a
# converter table. See ``normalize_body_fat_pct``.
JSON_BODY_FAT_METRIC = "body_fat_percentage"

# Swim workout names, for routing to the swimming/ store.
SWIM_WORKOUT_NAMES = {"Pool Swim", "Open Water Swim", "Swimming"}


_HAE_OFFSET_RE = re.compile(r"([+-])(\d{2})(\d{2})\s*$")

_WARNED_BAD_STAMPS: set[str] = set()


def parse_hae_dt(value: str | None) -> datetime | None:
    """Parse a HealthAutoExport timestamp as naive local wall clock.

    ``"2026-08-14 06:03:42 +0200"`` -> ``datetime(2026, 8, 14, 6, 3, 42)``.
    The offset is deliberately discarded: every stored clock time in this
    tracker is the Health app's local wall clock, and the sleep
    regularity index compares wake/sleep clock times across nights, where
    re-basing to UTC would manufacture a two-hour shift at each DST edge.

    Use ``parse_hae_instant`` when the question is which of two readings
    happened later; wall clock cannot answer that across a time-zone
    change. A malformed stamp warns once and returns None rather than
    dropping the whole series in silence.
    """
    if not value:
        return None
    text = str(value)
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        key = text[:32]
        if key not in _WARNED_BAD_STAMPS:
            _WARNED_BAD_STAMPS.add(key)
            print(
                f"WARN: unparsable HealthAutoExport timestamp {key!r}; point skipped",
                file=sys.stderr,
            )
        return None


def parse_hae_instant(value: str | None) -> datetime | None:
    """Parse a HealthAutoExport timestamp as an absolute instant.

    Keeps the UTC offset so two readings can be ordered correctly across
    a time-zone change: ``22:00 +0200`` is genuinely *earlier* than
    ``20:00 -0400`` on the same local date, and latest-of-day would
    otherwise keep the wrong one. Falls back to the naive stamp when the
    export carries no offset.
    """
    naive = parse_hae_dt(value)
    if naive is None:
        return None
    m = _HAE_OFFSET_RE.search(str(value))
    if not m:
        return naive
    sign = 1 if m.group(1) == "+" else -1
    delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    return naive - sign * delta


def _hae_day(value: str | None) -> str | None:
    """Return the local calendar day a metric point belongs to."""
    dt = parse_hae_dt(value)
    return dt.date().isoformat() if dt else None


def aggregate_metric_points(
    points: list[dict],
    strategy: str,
    value_key: str = "qty",
    *,
    night_bucket: bool = False,
) -> dict[str, float]:
    """Roll per-point readings up to one value per local calendar day.

    ``strategy`` is one of the ``AGG_*`` constants and comes from
    ``METRIC_AGGREGATION``; ``value_key`` selects the reading on each
    point (``qty`` for scalar metrics, ``Avg`` / ``Max`` for heart rate).
    Points with no parsable timestamp or no numeric reading are skipped
    rather than counted as zero, so a day whose only reading is malformed
    yields no entry at all and the sparse-merge upsert leaves the stored
    cell alone.

    ``night_bucket`` files an evening reading under the following day,
    which is the wake date of the night it was taken during. See
    ``SLEEP_ONSET_METRICS``. Ordering still uses the true timestamp, so
    ``latest`` and ``max`` compare the readings themselves rather than
    their buckets.
    """
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    best: dict[str, tuple[datetime, float]] = {}
    for point in points:
        dt = parse_hae_dt(point.get("date"))
        if dt is None:
            continue
        value = to_float(point.get(value_key))
        if value is None:
            continue
        bucket_date = dt.date()
        if night_bucket and dt.hour >= SLEEP_NIGHT_ROLLOVER_HOUR:
            bucket_date = bucket_date + timedelta(days=1)
        day = bucket_date.isoformat()
        if strategy in (AGG_SUM, AGG_MEAN):
            sums[day] += value
            counts[day] += 1
        elif strategy == AGG_LATEST:
            # Ordered by absolute instant, bucketed by wall clock: across
            # a time-zone change the later reading is not the one with
            # the larger local clock time.
            instant = parse_hae_instant(point.get("date")) or dt
            current = best.get(day)
            if current is None or instant > current[0]:
                best[day] = (instant, value)
        elif strategy == AGG_MAX:
            current = best.get(day)
            if current is None or value > current[1]:
                best[day] = (dt, value)
        else:
            raise ValueError(f"unknown aggregation strategy {strategy!r}")
    if strategy == AGG_SUM:
        return dict(sums)
    if strategy == AGG_MEAN:
        return {d: sums[d] / counts[d] for d in sums if counts[d]}
    return {d: v for d, (_dt, v) in best.items()}


def aggregate_json_metrics(metrics: list[dict]) -> dict[str, dict]:
    """Roll every metric series in the export down to per-day values.

    Returns ``{metric_name: {"units": str, "daily": {day: value}}}``.
    ``sleep_analysis`` is passed through as its raw per-night points —
    it is a per-night record, not a series to average — and an unknown
    metric name is reported once and skipped rather than guessed at.
    """
    # A metric may appear as more than one block — the exporter can split
    # a series by source device. Concatenating rather than last-wins is
    # what the XML aggregator did implicitly: it accumulated across every
    # record regardless of grouping, so two ``apple_exercise_time`` blocks
    # of 30 and 20 minutes are 50 minutes, not 20.
    merged: dict[str, dict] = {}
    for metric in metrics:
        name = metric.get("name")
        if not name:
            continue
        entry = merged.setdefault(name, {"name": name, "units": metric.get("units"), "data": []})
        entry["data"].extend(metric.get("data") or [])
        if entry["units"] is None:
            entry["units"] = metric.get("units")

    out: dict[str, dict] = {}
    for metric in merged.values():
        name = metric["name"]
        points = metric["data"]
        if name == "sleep_analysis":
            out[name] = {"units": metric.get("units"), "nights": points}
            continue
        if name == "heart_rate":
            out[name] = {
                "units": metric.get("units"),
                "daily": aggregate_metric_points(points, AGG_MEAN, "Avg"),
                "daily_max": aggregate_metric_points(points, AGG_MAX, "Max"),
            }
            continue
        strategy = METRIC_AGGREGATION.get(name)
        if strategy is None:
            print(
                f"WARN: HealthAutoExport metric {name!r} has no aggregation rule; skipped",
                file=sys.stderr,
            )
            continue
        out[name] = {
            "units": metric.get("units"),
            "daily": aggregate_metric_points(
                points, strategy, night_bucket=name in SLEEP_ONSET_METRICS
            ),
        }
    return out


def build_health_payload(
    aggregated: dict[str, dict],
    sleep_entries: list[dict],
    since: date | None,
    until: date | None,
) -> list[dict]:
    """Build the health_metrics.csv payload from aggregated metric days.

    Sleep headline fields are mirrored in from ``sleep_entries`` so the
    recovery path reads them off health_metrics.csv without a join, the
    same way both older importers behaved.
    """
    by_date: dict[str, dict] = {}

    def slot(day: str) -> dict:
        return by_date.setdefault(day, {"date": day})

    for metric_name, (field, digits, converters, label, plausible_key) in JSON_METRIC_FIELDS.items():
        entry = aggregated.get(metric_name)
        if not entry:
            continue
        unit = entry.get("units")
        for day, raw in entry.get("daily", {}).items():
            if not _date_in_range(day, since, until):
                continue
            value = raw
            # An absent ``units`` key means the export did not say, not
            # that the unit is wrong. The XML aggregator defaulted to the
            # stored unit in exactly this case (``attrib.get("unit") or
            # "kg"``); dropping the reading instead would lose a whole
            # metric over a missing field.
            if converters is not None and unit:
                value = convert_unit(value, unit, converters, label)
                if value is None:
                    continue
            # digits == 0 means a whole-number column (steps), not a
            # float rounded to zero places — 12345.0 in a CSV cell reads
            # as a measurement precision the count does not have.
            value = int(round(value)) if digits == 0 else round(value, digits)
            if plausible_key is not None:
                value = plausible_or_none(value, plausible_key, label, unit)
                if value is None:
                    continue
            slot(day)[field] = value

    for metric_name, field in JSON_ENERGY_FIELDS.items():
        entry = aggregated.get(metric_name)
        if not entry:
            continue
        unit = (entry.get("units") or "kJ").strip()
        for day, raw in entry.get("daily", {}).items():
            if not _date_in_range(day, since, until):
                continue
            if unit.lower() in ("kj", "kilojoule", "kilojoules"):
                value = raw * KJ_TO_KCAL
            elif unit.lower() in ("kcal", "cal", "calorie", "calories"):
                value = raw
            else:
                print(
                    f"WARN: unknown energy unit {unit!r} on {metric_name}; value skipped",
                    file=sys.stderr,
                )
                continue
            slot(day)[field] = int(round(value))

    body_fat = aggregated.get(JSON_BODY_FAT_METRIC)
    if body_fat:
        unit = body_fat.get("units") or "%"
        for day, raw in body_fat.get("daily", {}).items():
            if not _date_in_range(day, since, until):
                continue
            value = normalize_body_fat_pct(raw, unit)
            if value is not None:
                slot(day)["body_fat_pct"] = value

    for night in sleep_entries:
        day = night.get("date")
        if not day or not _date_in_range(day, since, until):
            continue
        # Only populated headline fields are mirrored. Writing a None
        # would be harmless to the sparse merge but would create a
        # date-only row out of a night that carried nothing.
        for field, key in (
            ("sleep_total_h", "total_h"),
            ("sleep_deep_h", "deep_h"),
            ("sleep_rem_h", "rem_h"),
            ("time_in_bed_h", "time_in_bed_h"),
        ):
            value = night.get(key)
            if value is not None:
                slot(day)[field] = value

    # A row holding nothing but a date serialises as a fully blank CSV
    # line. The XML aggregator emitted no row at all in that case.
    return [by_date[d] for d in sorted(by_date) if len(by_date[d]) > 1]


def build_sleep_payload(
    nights: list[dict],
    since: date | None,
    until: date | None,
) -> list[dict]:
    """Build the sleep/YYYY.MM.nights.csv payload from sleep_analysis points.

    One point per night, stamped at midnight of the wake date, which is
    the bucket the XML aggregator also used. ``inBed`` and ``asleep`` are
    durations rather than the timestamps that matter: ``asleep`` is the
    unspecified-stage bucket (``core + deep + rem + asleep == totalSleep``
    holds exactly across the observed nights) and ``inBed`` reads 0, so
    time in bed is derived from the ``inBedStart`` / ``inBedEnd`` span.

    That span equals the sleep period rather than real bed occupancy, so
    the efficiency the store derives from it stays a continuity proxy and
    the existing ``derived_sleep_period`` caveat continues to apply.

    ``n_segments`` is left blank permanently: HealthAutoExport reports one
    aggregate row per night with no segment breakdown. The index treats a
    night as one interval so it is unaffected; ``sleep_summary``'s
    fragmentation reader is the only consumer and must degrade to null.
    """
    # Two sleep points on one date (a night plus an evening nap) must
    # accumulate, the way the XML aggregator's per-segment ``+=`` did.
    # Overwriting would erase the night and leave the nap standing as the
    # whole of it.
    merged: dict[str, dict] = {}
    for point in nights:
        day = _hae_day(point.get("date"))
        if day is None:
            continue
        prior = merged.get(day)
        if prior is None:
            merged[day] = dict(point)
            continue
        for key in ("totalSleep", "core", "deep", "rem", "awake", "asleep", "inBed"):
            prior[key] = (to_float(prior.get(key)) or 0.0) + (to_float(point.get(key)) or 0.0)
        for key in ("sleepStart", "inBedStart"):
            if point.get(key) and (not prior.get(key) or str(point[key])[:19] < str(prior[key])[:19]):
                prior[key] = point[key]
        for key in ("sleepEnd", "inBedEnd"):
            if point.get(key) and (not prior.get(key) or str(point[key])[:19] > str(prior[key])[:19]):
                prior[key] = point[key]

    out: list[dict] = []
    for day, night in merged.items():
        if not _date_in_range(day, since, until):
            continue
        # ``positive_or_none`` throughout, not ``round_or_none``: the XML
        # aggregator emitted None for a stage that never occurred
        # (``round(x/60, 2) if x else None``), and the difference is not
        # cosmetic. ``upsert_health_metrics`` skips None but writes 0.0,
        # so a night with no REM would stamp a real zero over a populated
        # cell — permanent under a sparse merge — and drag the coach's
        # REM mean down, since ``sleep_summary`` includes any non-None.
        total = positive_or_none(night.get("totalSleep"), 2)
        core = positive_or_none(night.get("core"), 2)
        deep = positive_or_none(night.get("deep"), 2)
        rem = positive_or_none(night.get("rem"), 2)
        awake = positive_or_none(night.get("awake"), 2)
        unspecified = positive_or_none(night.get("asleep"), 2)
        if unspecified is None and total is not None:
            known = sum(v or 0.0 for v in (core, deep, rem))
            residual = round(total - known, 2)
            if residual > 0.01:
                unspecified = residual

        in_bed_start = parse_hae_dt(night.get("inBedStart"))
        in_bed_end = parse_hae_dt(night.get("inBedEnd"))
        time_in_bed = None
        if in_bed_start and in_bed_end and in_bed_end > in_bed_start:
            span = (in_bed_end - in_bed_start).total_seconds() / 3600.0
            # Same floor the XML aggregator put on its derived in-bed
            # span. Below it the record is a nap, and a nap whose in-bed
            # window equals its sleep window derives a 100% efficiency
            # that would drag the efficiency trend upward for a reason
            # that has nothing to do with sleep quality.
            if total is not None and total >= MIN_DERIVED_TIME_IN_BED_H:
                time_in_bed = round(span, 2)

        sleep_start = parse_hae_dt(night.get("sleepStart"))
        sleep_end = parse_hae_dt(night.get("sleepEnd"))
        if not any(v is not None for v in (total, core, deep, rem, awake, time_in_bed)):
            continue
        out.append({
            "date": day,
            "total_h": total,
            "core_h": core,
            "deep_h": deep,
            "rem_h": rem,
            "unspecified_h": unspecified,
            "awake_h": awake,
            "time_in_bed_h": time_in_bed,
            "efficiency_pct": None,
            "n_segments": None,
            "first_segment_start": sleep_start.strftime("%Y-%m-%d %H:%M:%S") if sleep_start else None,
            "last_segment_end": sleep_end.strftime("%Y-%m-%d %H:%M:%S") if sleep_end else None,
        })
    out.sort(key=lambda e: e["date"])
    return out


def _qty(value, digits: int | None = None, expect_units: tuple[str, ...] | None = None,
         label: str | None = None):
    """Read ``{"qty": …, "units": …}`` or a bare number off a workout field.

    ``expect_units`` gates the reading on the unit the caller expects,
    warning and dropping on anything else. The daily-metric path routes
    every conversion through ``convert_unit``; workout scalars need the
    same discipline, because HealthAutoExport bakes the user's in-app
    unit preference into its output and its unit strings are not always
    honest — ``lapLength`` is labelled "m" and carries kilometres. An
    imperial export would otherwise hand over ``distance`` in miles under
    a field this code reads as kilometres.
    """
    raw = value.get("qty") if isinstance(value, dict) else value
    f = to_float(raw)
    if f is None:
        return None
    if expect_units is not None and isinstance(value, dict):
        unit = str(value.get("units") or "").strip().lower()
        if unit and unit not in expect_units:
            print(
                f"WARN: unexpected {label or 'workout'} unit {unit!r} "
                f"(expected {'/'.join(expect_units)}); value skipped",
                file=sys.stderr,
            )
            return None
    return round(f, digits) if digits is not None else f


def _workout_pool_length_m(workout: dict) -> float | None:
    """Return the pool length in metres, or None when it is unusable.

    HealthAutoExport labels ``lapLength`` "m" and sends kilometres — a
    20 m pool arrives as ``0.02`` — so the value is scaled by 1000 and
    then gated against PLAUSIBLE_RANGES. An export that ever starts
    sending true metres drops here with a warning instead of turning a
    25 m pool into a 25000 m one.
    """
    raw = _qty(workout.get("lapLength"))
    if raw is None or raw <= 0:
        return None
    return plausible_or_none(round(raw * 1000.0, 1), "swim_pool_length_m", "pool length", "m")


def _swim_location(workout: dict) -> str | None:
    """Return the swim's Location, or None when it cannot be established.

    The store's Location column has three values — ``Open Water``,
    ``Pool`` and ``Outdoor Pool`` — which the XML importer derived from
    ``HKSwimmingLocationType`` and ``HKIndoorWorkout`` together.
    HealthAutoExport carries only a two-value ``location`` plus
    ``isIndoor``, and the two disagree with the XML on the one swim both
    sources describe: HAE reports ``isIndoor: true`` for a workout the
    XML recorded as an outdoor pool.

    So ``Open Water`` is written, because that value is unambiguous in
    both sources, and a pool swim is left blank rather than labelled
    ``Pool``. The upsert is a sparse merge, so a blank preserves the
    richer ``Outdoor Pool`` already stored on the five XML-era rows,
    where a confident ``Pool`` would overwrite it. Distinguishing an
    indoor pool from an outdoor one is a permanent loss on this export,
    the same as SWOLF and stroke mix, and a blank cell says that
    honestly.
    """
    location = str(workout.get("location") or "").strip()
    if location.lower() == "open water":
        return "Open Water"
    return None


def _window_points(points: list[dict], start: datetime, end: datetime) -> list[dict]:
    """The metric points falling inside one workout's time window.

    The window start is floored to the minute because HealthAutoExport
    stamps metric points on minute boundaries: a swim starting at
    12:30:45 has its 12:30:00 reading inside it, and a strict comparison
    would silently clip the first minute of every windowed metric.
    """
    lo = start.replace(second=0, microsecond=0)
    out = []
    for point in points:
        dt = parse_hae_dt(point.get("date"))
        if dt is None or dt < lo or dt > end:
            continue
        out.append(point)
    return out


def _window_metric_mean(points: list[dict], start: datetime, end: datetime) -> float | None:
    """Mean of a daily metric series over one workout's time window."""
    values = [to_float(p.get("qty")) for p in _window_points(points, start, end)]
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _window_metric_sum(points: list[dict], start: datetime, end: datetime) -> float | None:
    """Sum of a cumulative metric series over one workout's time window."""
    values = [to_float(p.get("qty")) for p in _window_points(points, start, end)]
    values = [v for v in values if v is not None]
    return sum(values) if values else None


def _window_heart_rate(points: list[dict], start: datetime, end: datetime) -> dict:
    """Average / peak / trough heart rate over one workout's window.

    **This is the primary heart-rate source, not a fallback.** The
    per-workout ``heartRate`` object is computed by HealthAutoExport from
    its own ``heartRateData`` series, and that series is truncated in
    practice: a 15-minute run can carry 25 samples covering two minutes,
    which drags Apple's stated average far off. Measured against the
    workout-sessions rows the retired XML importer wrote, the windowed
    top-level series lands within 0.84 bpm on average where the
    per-workout object is 2.47 bpm out and peaks at 25 bpm wrong. The
    windowed series also covers 119 of 121 workouts against the object's
    69, so 52 workouts would otherwise store no heart rate at all and
    lose their TRIMP, load band and intensity.
    """
    window = _window_points(points, start, end)
    avgs = [to_float(p.get("Avg")) for p in window]
    maxes = [to_float(p.get("Max")) for p in window]
    mins = [to_float(p.get("Min")) for p in window]
    avgs = [v for v in avgs if v is not None]
    maxes = [v for v in maxes if v is not None]
    mins = [v for v in mins if v is not None]
    return {
        "avg": sum(avgs) / len(avgs) if avgs else None,
        "max": max(maxes) if maxes else None,
        "min": min(mins) if mins else None,
    }


def parse_json_workouts(
    workouts: list[dict],
    aggregated: dict[str, dict],
    raw_metrics: dict[str, list[dict]],
    since: date | None,
    until: date | None,
) -> list[dict]:
    """Build workout_sessions rows (plus swim extras) from JSON workouts.

    ``avgSpeed`` / ``maxSpeed`` are deliberately never read. They are
    wrist-underwater GPS artifacts on swims — the open-water swim reports
    1819 and 4367 under ``units: "m"`` — and nothing downstream consumes
    a stored speed: pace is recomputed from distance and duration on
    canonicalize. Not reading them is a stronger gate than bounding them.
    """
    out: list[dict] = []
    water_temp_points = raw_metrics.get("underwater_temperature") or []
    heart_rate_points = raw_metrics.get("heart_rate") or []
    stroke_points = raw_metrics.get("swimming_stroke_count") or []
    for workout in workouts:
        start_dt = parse_hae_dt(workout.get("start"))
        if start_dt is None:
            continue
        day = start_dt.date().isoformat()
        if not _date_in_range(day, since, until):
            continue
        end_dt = parse_hae_dt(workout.get("end"))
        raw_name = (workout.get("name") or "").strip()
        apple_type = _canonical_workout_type(raw_name)

        duration_sec = to_float(workout.get("duration"))
        duration_min = round(duration_sec / 60.0, 1) if duration_sec else None
        elapsed_min = None
        if end_dt and end_dt > start_dt:
            elapsed_min = round((end_dt - start_dt).total_seconds() / 60.0, 1)

        active_kj = _qty(workout.get("activeEnergyBurned"), expect_units=("kj",),
                         label="active energy")
        active_cal = round(active_kj * KJ_TO_KCAL, 1) if active_kj is not None else None
        total_kj = _qty(workout.get("totalEnergy"), expect_units=("kj",),
                        label="total energy")
        total_cal = round(total_kj * KJ_TO_KCAL, 1) if total_kj is not None else None
        basal_cal = None
        if total_cal is not None and active_cal is not None:
            basal_cal = round(total_cal - active_cal, 1)
            if basal_cal < 0:
                # Basal is what the body would have burned anyway, so it
                # cannot be negative. The XML path added active and basal
                # rather than subtracting and could never produce this;
                # here it means the two scalars disagree, and a negative
                # resting burn on the monthly TOTAL row is worse than a
                # blank one.
                print(
                    f"WARN: {raw_name or 'workout'} on {day} reports total energy below "
                    f"active ({total_cal} < {active_cal} kcal); basal and total skipped",
                    file=sys.stderr,
                )
                basal_cal = None
                total_cal = None
        # No fallback when ``totalEnergy`` is absent. It is missing on 51
        # of the 121 workouts in the reference export, and on the 70 that
        # carry it basal accounts for 23% of the total, so defaulting the
        # total to the active figure would understate those rows by about
        # a quarter while reading as a measurement. Those workouts carry
        # no ``basalEnergy`` series either, so the datum genuinely does
        # not exist and a blank cell is the honest answer. This matches
        # the CSV reader, which leaves ``total_cal`` None in the same
        # situation.

        # Heart rate: the windowed top-level series is primary, the
        # per-workout object is the fallback. See _window_heart_rate.
        hr = workout.get("heartRate") if isinstance(workout.get("heartRate"), dict) else {}
        windowed = _window_heart_rate(heart_rate_points, start_dt, end_dt or start_dt)
        avg_hr = windowed["avg"]
        if avg_hr is None:
            avg_hr = _qty(workout.get("avgHeartRate")) or _qty(hr.get("avg"))
        avg_hr = round(avg_hr, 1) if avg_hr is not None else None

        # A peak is a maximum and a trough a minimum, so where both
        # sources have a reading the extreme of the two is the one the
        # wrist actually saw. Under-sampling can only miss a beat, never
        # invent one, and estimated_max_hr is derived from this column.
        max_candidates = [v for v in (windowed["max"], _qty(workout.get("maxHeartRate")),
                                      _qty(hr.get("max"))) if v is not None]
        min_candidates = [v for v in (windowed["min"], _qty(hr.get("min"))) if v is not None]
        max_hr = max(max_candidates) if max_candidates else None
        min_hr = min(min_candidates) if min_candidates else None

        distance_km = _qty(workout.get("distance"), 3, expect_units=("km",), label="distance")
        if distance_km is not None and distance_km <= 0:
            distance_km = None
        elevation_m = _qty(workout.get("elevationUp"), 1, expect_units=("m",), label="elevation")
        if elevation_m is not None and elevation_m <= 0:
            elevation_m = None

        incidental = (
            "Walking" in apple_type
            and duration_min is not None
            and duration_min < INCIDENTAL_WALK_MAX_MIN
        )

        row = {
            "date": day,
            "start": _hhmmss(start_dt),
            "end": _hhmmss(end_dt),
            "apple_type": apple_type,
            "duration_min": duration_min,
            "avg_hr": avg_hr,
            "max_hr": int(round(max_hr)) if max_hr is not None else None,
            "min_hr": int(round(min_hr)) if min_hr is not None else None,
            "active_cal": active_cal,
            "basal_cal": basal_cal,
            "total_cal": total_cal,
            "elevation_m": elevation_m,
            "elapsed_min": elapsed_min if elapsed_min is not None else duration_min,
            "distance_km": distance_km,
            "source": WORKOUT_SOURCE_LABEL,
            "incidental": incidental,
            "notes": None,
            "stamp_status": None,
        }

        if raw_name in SWIM_WORKOUT_NAMES or apple_type == "Swimming":
            pool_length_m = _workout_pool_length_m(workout)
            strokes = _qty(workout.get("totalSwimmingStrokeCount"))
            if strokes is None:
                # Open-water swims carry no per-workout stroke total, but
                # the top-level swimming_stroke_count series still runs
                # through the workout window.
                strokes = _window_metric_sum(stroke_points, start_dt, end_dt or start_dt)
            strokes = int(round(strokes)) if strokes is not None else None
            laps = None
            if pool_length_m and distance_km:
                # Round half up rather than to even: banker's rounding
                # flips direction at every half length, so 50 m in a 20 m
                # pool would give 2 laps while 70 m gives 4.
                laps = int((distance_km * 1000.0 / pool_length_m) + 0.5) or None
            water_temp = _window_metric_mean(
                water_temp_points, start_dt,
                end_dt or (start_dt + timedelta(seconds=duration_sec or 0)),
            )
            row.update({
                "pool_length_m": int(round(pool_length_m)) if pool_length_m else None,
                "laps": laps,
                "stroke_count_total": strokes,
                "swim_location": _swim_location(workout),
                "water_temp_c": round(water_temp, 2) if water_temp is not None else None,
            })
        out.append(row)
    out.sort(key=lambda r: (r["date"], r.get("start") or ""))
    return out


def build_swim_payload(workout_rows: list[dict]) -> list[dict]:
    """Build the swimming/YYYY.MM.workouts.csv payload from JSON workouts.

    Laps are derived as ``distance / pool length`` and SPL as
    ``strokes / laps``; both were read straight off Apple's lap events on
    the XML path and neither is exposed directly by HealthAutoExport.

    ``Avg SWOLF`` and ``Stroke Mix`` stay blank going forward: both are
    per-lap quantities and there is no per-lap payload in this export.
    For the same reason no ``swimming/*.laps.csv`` is written at all — an
    empty lap file would read as "this swim had no laps" to every
    consumer, which is worse than an absent one. Existing XML-era rows
    keep the values they already have; the sparse-merge upsert does not
    blank them.
    """
    rows: list[dict] = []
    for w in workout_rows:
        if (w.get("apple_type") or "") != "Swimming":
            continue
        laps = w.get("laps")
        strokes = w.get("stroke_count_total")
        rows.append({
            "date": w.get("date"),
            "start": w.get("start"),
            "end": w.get("end"),
            "duration_min": w.get("duration_min"),
            "distance_km": w.get("distance_km"),
            "pool_length_m": w.get("pool_length_m"),
            "laps": laps,
            "strokes": strokes,
            "spl": round(strokes / laps, 1) if (strokes and laps) else None,
            "avg_swolf": None,
            "stroke_mix": None,
            "location": w.get("swim_location"),
            "water_temp_c": w.get("water_temp_c"),
            "avg_hr": w.get("avg_hr"),
            "active_cal": int(round(w["active_cal"])) if w.get("active_cal") is not None else None,
        })
    return rows


def parse_health_auto_export_json(
    payload: dict,
    since: date | None,
    until: date | None,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Parse one HealthAutoExport JSON document into store payloads."""
    data = payload.get("data") or {}
    metrics = data.get("metrics") or []
    raw_metrics = {m.get("name"): (m.get("data") or []) for m in metrics if m.get("name")}
    aggregated = aggregate_json_metrics(metrics)
    sleep_nights = (aggregated.get("sleep_analysis") or {}).get("nights") or []
    sleep = build_sleep_payload(sleep_nights, since, until)
    health = build_health_payload(aggregated, sleep, since, until)
    workouts = parse_json_workouts(
        data.get("workouts") or [], aggregated, raw_metrics, since, until
    )
    swim = build_swim_payload(workouts)
    return health, sleep, workouts, swim


def _find_json_member(names: list[str]) -> str | None:
    matches = sorted(
        n for n in names
        if n.rsplit("/", 1)[-1].startswith("HealthAutoExport-") and n.endswith(".json")
    )
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(
            f"expected exactly one HealthAutoExport-*.json, found {len(matches)}"
        )
    return matches[0]


def parse_health_auto_export_zip(
    zip_path: Path,
    since: date | None,
    until: date | None,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Parse a HealthAutoExport archive, dispatching on member extension.

    A ``HealthAutoExport-*.json`` member selects the JSON reader; anything
    else falls back to the legacy CSV reader. Route GPX files sit
    alongside the JSON in the same archive and are ignored.
    """
    if zip_path.suffix.lower() == ".json":
        with zip_path.open(encoding="utf-8") as f:
            return parse_health_auto_export_json(json.load(f), since, until)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        json_name = _find_json_member(names)
        if json_name is not None:
            with zf.open(json_name) as f:
                payload = json.load(io.TextIOWrapper(f, encoding="utf-8-sig"))
            return parse_health_auto_export_json(payload, since, until)
        print(
            "WARN: HealthAutoExport CSV export is deprecated; switch the app to "
            "JSON, hourly metrics, per-minute workouts, routes off",
            file=sys.stderr,
        )
        daily_name = _find_one(names, "HealthAutoExport-")
        workout_name = _find_one(names, "Workouts-")
        with zf.open(daily_name) as f:
            daily_rows = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline="")))
        with zf.open(workout_name) as f:
            workout_rows_raw = list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline="")))
        metrics, sleep = parse_daily_rows(daily_rows, since, until)
        workouts = parse_workout_rows(
            workout_rows_raw,
            _stamp_index(zf.infolist()),
            _heart_rate_stats(zf),
            since,
            until,
        )
    return metrics, sleep, workouts, []


def _write_health_records(person: str, records: list[dict]) -> None:
    fields = HEALTH_METRICS_FIELDS
    headers = HEALTH_METRICS_HEADERS
    rows = []
    by_date = {r["date"]: r for r in records if r.get("date")}
    for d in sorted(by_date, reverse=True):
        rec = by_date[d]
        rows.append([d] + [rec.get(k) for k in fields] + [rec.get("notes")])
    _write_store_csv(Path(WORKOUT_TRACKER_ROOT) / person / "data" / "health_metrics.csv", headers, rows)


def _write_workout_records(person: str, records: list[dict]) -> None:
    fields = WORKOUT_SESSIONS_FIELDS
    headers = WORKOUT_SESSIONS_HEADERS
    rows = []
    for rec in sorted(records, key=lambda r: (r["date"], str(r.get("start") or "")), reverse=True):
        rows.append([rec["date"]] + [rec.get(k) for k in fields])
    _write_store_csv(Path(WORKOUT_TRACKER_ROOT) / person / "data" / "workout_sessions.csv", headers, rows)


def clear_health_metrics_range(person: str, since: date | None, until: date | None) -> str:
    records = read_health_metrics(person)
    if not records:
        return "Replace Health Metrics: no existing rows"
    cleared = 0
    for rec in records:
        if not _date_in_range(rec.get("date"), since, until):
            continue
        for key in RANGE_FIELDS_TO_CLEAR:
            if rec.get(key) is not None:
                rec[key] = None
                cleared += 1
    _write_health_records(person, records)
    return f"Replace Health Metrics: cleared {cleared} machine value(s)"


def clear_workout_sessions_range(person: str, since: date | None, until: date | None) -> str:
    records = read_workout_sessions(person)
    if not records:
        return "Replace Workout Sessions: no existing rows"
    kept = []
    removed = 0
    for rec in records:
        source = str(rec.get("source") or "").lower()
        if _date_in_range(rec.get("date"), since, until) and source not in ("", "manual"):
            removed += 1
            continue
        kept.append(rec)
    _write_workout_records(person, kept)
    return f"Replace Workout Sessions: removed {removed} machine row(s)"


def _month_intersects(ym: str, since: date | None, until: date | None) -> bool:
    try:
        y, m = ym.split(".")
        first = date(int(y), int(m), 1)
        last = date(int(y) + (int(m) == 12), 1 if int(m) == 12 else int(m) + 1, 1) - timedelta(days=1)
    except ValueError:
        return False
    if since and last < since:
        return False
    if until and first > until:
        return False
    return True


def clear_monthly_machine_range(person: str, since: date | None, until: date | None) -> list[str]:
    summaries: list[str] = []
    for ym in list_year_months(person):
        if not _month_intersects(ym, since, until):
            continue
        path = monthly_csv_path(person, ym)
        header, raw_rows = _read_csv_rows(path)
        if not header:
            continue
        kept_rows = []
        removed = 0
        cleared_totals = 0
        changed = False
        for raw in raw_rows:
            rd = _row_to_dict(raw)
            d = date_str(rd.get("date"))
            ex = str(rd.get("exercise") or "").strip()
            if _date_in_range(d, since, until):
                if ex.upper() == TOTAL_LABEL:
                    had_meta = any(rd.get(k) not in (None, "") for k in MONTHLY_TOTAL_METADATA_FIELDS)
                    for key in MONTHLY_TOTAL_METADATA_FIELDS:
                        rd[key] = None
                    if had_meta:
                        cleared_totals += 1
                        changed = True
                elif _is_auto_imported(rd):
                    removed += 1
                    changed = True
                    continue
            kept_rows.append(_dict_to_row(rd))
        if changed:
            _write_csv_atomic(path, kept_rows)
            canonicalize_monthly_csv(person, ym)
        summaries.append(
            f"Replace monthly/{ym}: removed {removed} auto row(s), "
            f"cleared {cleared_totals} TOTAL row(s)"
        )
    return summaries


def _range_text(entries: list[dict]) -> str:
    dates = [e.get("date") for e in entries if e.get("date")]
    return f"{min(dates)} -> {max(dates)}" if dates else "-"


def dry_run_lines(
    zip_path: Path,
    metrics: list[dict],
    sleep: list[dict],
    workouts: list[dict],
    swim: list[dict] | None = None,
) -> list[str]:
    eligible = [
        w for w in workouts
        if (w.get("apple_type") or "") in CARDIO_AUTOLOG_TYPES
        and APPLE_TO_TRACKER_EXERCISE.get(w.get("apple_type") or "")
    ]
    strength_sessions, _ = cluster_strength_sessions(workouts)
    incidental = sum(1 for w in workouts if w.get("incidental") is True)
    ambiguous_stamps = sum(1 for w in workouts if w.get("stamp_status") == "ambiguous")
    return [
        f"HealthAutoExport file: {zip_path.name}",
        f"Health Metrics: {len(metrics)} dates would be written (range {_range_text(metrics)})",
        *body_composition_lines(metrics),
        f"Sleep Nights: {len(sleep)} nights would be written (range {_range_text(sleep)})",
        f"Swim Workouts: {len(swim or [])} swims would be written",
        f"Workout Sessions: {len(workouts)} sessions would be written ({incidental} walks flagged incidental)",
        f"HealthAutoExport: {ambiguous_stamps} workout minute(s) had ambiguous per-workout stamp matches",
        f"Auto-cardio: {len(eligible)} rows would be considered",
        f"Strength sessions: {len(strength_sessions)} sessions would be considered",
    ]


def import_archive(
    person: str,
    zip_path: Path,
    since: date | None,
    until: date | None,
    *,
    allow_past_months: bool = False,
    replace_range: bool = False,
    dry_run: bool = False,
    keep_export: bool = False,
) -> list[str]:
    metrics, sleep, workouts, swim = parse_health_auto_export_zip(zip_path, since, until)
    ambiguous_stamps = sum(1 for w in workouts if w.get("stamp_status") == "ambiguous")
    if dry_run:
        return dry_run_lines(zip_path, metrics, sleep, workouts, swim)

    if not metrics and not sleep:
        raise EmptyImportError(
            f"{zip_path.name} yielded 0 health metric dates and 0 sleep nights "
            f"in the selected window; nothing was written"
        )

    out_lines: list[str] = []
    if ambiguous_stamps:
        out_lines.append(
            f"HealthAutoExport: {ambiguous_stamps} workout minute(s) had ambiguous per-workout stamp matches"
        )
    profile, created = ensure_profile(person, default_source=SOURCE_NAME, default_auto_cardio=True)
    if created:
        out_lines.append("Profile: created (source=health_auto_export, auto_cardio=true)")
    if profile.get("source") != SOURCE_NAME:
        write_profile(person, source=SOURCE_NAME)
        out_lines.append(f"Profile: source {profile.get('source') or 'unset'} -> {SOURCE_NAME}")
        profile = read_profile(person)

    if replace_range:
        current_month_start = date.today().replace(day=1)
        if not allow_past_months and (since is None or since < current_month_start):
            raise ValueError(
                "--replace-range spanning past months requires --allow-past-months"
            )
        out_lines.append(clear_health_metrics_range(person, since, until))
        out_lines.append(clear_workout_sessions_range(person, since, until))
        out_lines.extend(clear_monthly_machine_range(person, since, until))

    out_lines.extend(upsert_health_metrics(person, metrics))
    out_lines.extend(body_composition_lines(metrics))
    out_lines.extend(upsert_sleep_nights(person, sleep))
    if swim:
        out_lines.extend(upsert_swim_workouts(person, swim))
    out_lines.extend(upsert_workout_sessions(person, workouts))

    if profile.get("auto_cardio"):
        cardio_payload = build_auto_cardio_payload(
            workouts,
            eligible_types=CARDIO_AUTOLOG_TYPES,
            type_to_exercise=APPLE_TO_TRACKER_EXERCISE,
        )
        out_lines.extend(upsert_monthly_cardio(
            person,
            cardio_payload,
            allow_past_months=allow_past_months,
        ))
    else:
        out_lines.append("Auto-cardio: skipped (Profile.auto_cardio=false)")

    strength_sessions, strength_warnings = cluster_strength_sessions(workouts)
    if strength_warnings:
        out_lines.append("Strength clustering warnings:")
        out_lines.extend(strength_warnings)
    out_lines.extend(upsert_monthly_strength_session(
        person,
        strength_sessions,
        allow_past_months=allow_past_months,
    ))

    if not keep_export:
        # The consumed export used to be moved to ``<root>/.processed/``
        # as a rollback path if a downstream bug damaged the CSVs. The
        # data directories are versioned in git now, so the commit
        # history serves that purpose better and at a thousandth of the
        # size: the archive had reached 966 MB against a live store of
        # well under a megabyte. ``--keep-export`` remains the escape
        # hatch for anyone who wants the file kept.
        try:
            zip_path.unlink()
            out_lines.append(f"Deleted source export: {zip_path.name}")
        except OSError as e:
            out_lines.append(f"WARN: could not delete {zip_path.name}: {e}")

    # After the writes are confirmed. One import is one commit.
    sha = commit_data(person, f"import: {zip_path.name}")
    if sha:
        out_lines.append(f"Committed {person} data: {sha}")

    return out_lines


def resolve_zip(pattern: str | None) -> Path | None:
    if pattern:
        p = Path(pattern)
        if p.exists():
            return p
        matches = sorted((Path(m) for m in glob.glob(pattern)), key=lambda x: x.stat().st_mtime, reverse=True)
        return matches[0] if matches else None
    matches = sorted(
        WORKOUT_TRACKER_ROOT.glob("HealthAutoExport*.zip"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--person", required=True, help="Tracker owner, e.g. <OtherPerson>.")
    ap.add_argument("--zip", default=None, help="HealthAutoExport ZIP path or glob. Defaults to latest HealthAutoExport*.zip.")
    ap.add_argument("--since", default=None, type=parse_since, help="Start date, YYYY-MM-DD. Default: 6 months back.")
    ap.add_argument("--until", default=None, type=parse_since, help="End date, YYYY-MM-DD. Default: no upper bound.")
    ap.add_argument("--allow-past-months", action="store_true", help="Allow monthly backfill into past YYYY.MM files.")
    ap.add_argument("--replace-range", action="store_true", help="Clear old machine-imported values in the selected date range before import.")
    ap.add_argument("--keep-export", action="store_true", help="Keep the ZIP in place instead of deleting it after a successful import.")
    ap.add_argument("--dry-run", action="store_true", help="Parse and summarize; do not write anything.")
    args = ap.parse_args()

    ctx = TrackerContext(args.person)
    zip_path = resolve_zip(args.zip)
    if zip_path is None or not zip_path.exists():
        print(f"ERROR: HealthAutoExport ZIP not found: {args.zip or 'HealthAutoExport*.zip'}", file=sys.stderr)
        return 1

    since = args.since or default_since()
    try:
        lines = import_archive(
            ctx.person,
            zip_path,
            since,
            args.until,
            allow_past_months=args.allow_past_months,
            replace_range=args.replace_range,
            dry_run=args.dry_run,
            keep_export=args.keep_export,
        )
    except EmptyImportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
