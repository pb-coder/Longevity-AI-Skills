"""Import HealthAutoExport ZIP data into the tracker CSV store.

HealthAutoExport exports a daily aggregate CSV plus a workout aggregate CSV
and optional per-workout metric files. This importer treats that export as the
rich source for Fabian: daily HRV / resting HR / walking HR / wrist temp /
sleep stages / exercise minutes, plus per-workout average/max HR.

Usage:
    python3 import_health_auto_export.py --person Fabian \\
        --zip HealthAutoExport_20260517143632-1.zip \\
        --since 2026-04-01 --until 2026-05-17 \\
        --allow-past-months --replace-range
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILLS_ROOT))
sys.path.insert(0, str(SKILLS_ROOT / "shared"))

from tracker import TrackerContext  # noqa: E402
from tracker.importing import build_auto_cardio_payload  # noqa: E402
from apple_workout_types import (  # noqa: E402
    APPLE_TO_TRACKER_EXERCISE,
    CARDIO_AUTOLOG_TYPES,
)
from csv_store import (  # noqa: E402
    HEALTH_METRICS_FIELDS_BY_SOURCE,
    HEALTH_METRICS_HEADERS_BY_SOURCE,
    WORKOUT_SESSIONS_FIELDS_BY_SOURCE,
    WORKOUT_SESSIONS_HEADERS_BY_SOURCE,
    ensure_profile,
    read_health_metrics,
    read_profile,
    read_workout_sessions,
    upsert_health_metrics,
    upsert_sleep_nights,
    upsert_workout_sessions,
    write_profile,
    _write_csv as _write_store_csv,
)
from import_apple_health import cluster_strength_sessions  # noqa: E402
from monthly_csv import (  # noqa: E402
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
from person_paths import (  # noqa: E402
    WORKOUT_TRACKER_ROOT,
    archive_processed_export,
    monthly_csv as monthly_csv_path,
)


SOURCE_NAME = "health_auto_export"
WORKOUT_SOURCE_LABEL = "HealthAutoExport"
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


def parse_daily_rows(rows: list[dict], since: date | None, until: date | None) -> tuple[list[dict], list[dict]]:
    metric_entries: list[dict] = []
    sleep_entries: list[dict] = []
    for row in rows:
        d = _parse_daily_date(row.get("Date/Time"))
        if not _date_in_range(d, since, until):
            continue

        time_in_bed = positive_or_none(row.get(DAILY_COLUMNS["time_in_bed_h"]), 2)
        metric_entries.append({
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
    for row in rows:
        raw_type = (row.get("Workout Type") or "").strip()
        start_minute = _parse_workout_minute(row.get("Start"))
        if start_minute is None:
            continue
        minute_key = start_minute.strftime("%Y%m%d_%H%M")
        stamps = sorted(stamp_index.get((raw_type, minute_key), set()))
        start_dt = _parse_stamp(stamps[0]) if len(stamps) == 1 else start_minute
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
        })
    return out


def parse_health_auto_export_zip(
    zip_path: Path,
    since: date | None,
    until: date | None,
) -> tuple[list[dict], list[dict], list[dict]]:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
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
    return metrics, sleep, workouts


def _write_health_records(person: str, records: list[dict]) -> None:
    fields = HEALTH_METRICS_FIELDS_BY_SOURCE[SOURCE_NAME]
    headers = HEALTH_METRICS_HEADERS_BY_SOURCE[SOURCE_NAME]
    rows = []
    for d in sorted((r["date"] for r in records), reverse=True):
        rec = next(r for r in records if r["date"] == d)
        rows.append([d] + [rec.get(k) for k in fields] + [rec.get("notes")])
    _write_store_csv(Path(WORKOUT_TRACKER_ROOT) / person / "data" / "health_metrics.csv", headers, rows)


def _write_workout_records(person: str, records: list[dict]) -> None:
    fields = WORKOUT_SESSIONS_FIELDS_BY_SOURCE[SOURCE_NAME]
    headers = WORKOUT_SESSIONS_HEADERS_BY_SOURCE[SOURCE_NAME]
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
        if _date_in_range(rec.get("date"), since, until) and str(rec.get("source") or "").lower() != "manual":
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


def dry_run_lines(zip_path: Path, metrics: list[dict], sleep: list[dict], workouts: list[dict]) -> list[str]:
    eligible = [
        w for w in workouts
        if (w.get("apple_type") or "") in CARDIO_AUTOLOG_TYPES
        and APPLE_TO_TRACKER_EXERCISE.get(w.get("apple_type") or "")
    ]
    strength_sessions, _ = cluster_strength_sessions(workouts)
    incidental = sum(1 for w in workouts if w.get("incidental") is True)
    return [
        f"HealthAutoExport file: {zip_path.name}",
        f"Health Metrics: {len(metrics)} dates would be written (range {_range_text(metrics)})",
        f"Sleep Nights: {len(sleep)} nights would be written (range {_range_text(sleep)})",
        f"Workout Sessions: {len(workouts)} sessions would be written ({incidental} walks flagged incidental)",
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
    metrics, sleep, workouts = parse_health_auto_export_zip(zip_path, since, until)
    if dry_run:
        return dry_run_lines(zip_path, metrics, sleep, workouts)

    out_lines: list[str] = []
    profile, created = ensure_profile(person, default_source=SOURCE_NAME, default_auto_cardio=True)
    if created:
        out_lines.append("Profile: created (source=health_auto_export, auto_cardio=true)")
    if profile.get("source") != SOURCE_NAME:
        write_profile(person, source=SOURCE_NAME)
        out_lines.append(f"Profile: source {profile.get('source') or 'unset'} -> {SOURCE_NAME}")
        profile = read_profile(person)

    if replace_range:
        out_lines.append(clear_health_metrics_range(person, since, until))
        out_lines.append(clear_workout_sessions_range(person, since, until))
        out_lines.extend(clear_monthly_machine_range(person, since, until))

    out_lines.extend(upsert_health_metrics(person, metrics))
    out_lines.extend(upsert_sleep_nights(person, sleep))
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
        try:
            archived = archive_processed_export(zip_path)
            out_lines.append(f"Archived source export: {zip_path.name} -> {archived.parent.name}/{archived.name}")
        except OSError as e:
            out_lines.append(f"WARN: could not archive {zip_path.name}: {e}")

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
    ap.add_argument("--person", required=True, help="Tracker owner, e.g. Fabian.")
    ap.add_argument("--zip", default=None, help="HealthAutoExport ZIP path or glob. Defaults to latest HealthAutoExport*.zip.")
    ap.add_argument("--since", default=None, type=parse_since, help="Start date, YYYY-MM-DD. Default: 6 months back.")
    ap.add_argument("--until", default=None, type=parse_since, help="End date, YYYY-MM-DD. Default: no upper bound.")
    ap.add_argument("--allow-past-months", action="store_true", help="Allow monthly backfill into past YYYY.MM files.")
    ap.add_argument("--replace-range", action="store_true", help="Clear old machine-imported values in the selected date range before import.")
    ap.add_argument("--keep-export", action="store_true", help="Keep the ZIP in place instead of archiving it after a successful import.")
    ap.add_argument("--dry-run", action="store_true", help="Parse and summarize; do not write anything.")
    args = ap.parse_args()

    ctx = TrackerContext(args.person)
    zip_path = resolve_zip(args.zip)
    if zip_path is None or not zip_path.exists():
        print(f"ERROR: HealthAutoExport ZIP not found: {args.zip or 'HealthAutoExport*.zip'}", file=sys.stderr)
        return 1

    since = args.since or default_since()
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
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
