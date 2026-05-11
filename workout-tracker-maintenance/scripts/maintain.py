"""Workout Tracker monthly maintenance.

Idempotent. Safe to re-run. Performs:
  1. Canonicalize every per-month workout CSV (sort, recompute Volume/
     Pace/SESSION, rebuild TOTAL rows, hoist deload markers).
  2. Validate all CSVs (header schema match, monotonic date order,
     row counts).
  3. Optional ``--fix-distance-units`` swim sweep (legacy meter-as-km
     bug across monthly CSVs + workout_sessions.csv + swim_workouts.csv).

Post-PR3a: there is no xlsx anywhere. Per-month workout data lives in
``<Person>/data/monthly/YYYY.MM.csv``. Health Metrics, Workout Sessions,
Profile, swim_workouts, swim_laps live alongside in ``<Person>/data/``.

Usage:
    python3 maintain.py --person Nihad
    python3 maintain.py --person Nihad --dry-run
    python3 maintain.py --person Nihad --fix-distance-units
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from monthly_csv import (  # noqa: E402
    MONTHLY_HEADERS,
    TOTAL_LABEL,
    _format_pace_min_per_km,
    _parse_duration_minutes,
    canonicalize_monthly_csv,
    list_year_months,
)
from csv_store import (  # noqa: E402
    HEALTH_METRICS_HEADERS_BY_SOURCE,
    SWIM_LAPS_HEADERS,
    SWIM_WORKOUTS_HEADERS,
    WORKOUT_SESSIONS_HEADERS_BY_SOURCE,
    read_profile,
)
from person_paths import (  # noqa: E402
    health_metrics_csv,
    monthly_csv as monthly_csv_path,
    monthly_dir,
    profile_csv,
    swim_laps_csv,
    swim_workouts_csv,
    workout_sessions_csv,
)


# ------------------------------------------------------------------ run
def run(person: str, dry_run: bool = False) -> int:
    """Canonicalize every per-month CSV + validate the per-person CSV store."""
    md = monthly_dir(person)
    if not md.exists():
        print(f"ERROR: no monthly CSV directory: {md}", file=sys.stderr)
        return 1

    yms = list_year_months(person)
    if not yms:
        print(f"WARN: no monthly CSVs found in {md}", file=sys.stderr)

    print("Canonicalize:")
    for ym in yms:
        path = monthly_csv_path(person, ym)
        before_size = path.stat().st_size if path.exists() else 0
        before_rows = _row_count(path)
        if not dry_run:
            canonicalize_monthly_csv(person, ym)
        after_size = path.stat().st_size if path.exists() else 0
        after_rows = _row_count(path)
        delta = "no change" if (
            before_size == after_size and before_rows == after_rows
        ) else f"{before_rows} → {after_rows} rows"
        print(f"  {ym}: {delta}")

    print("\nCSV checks:")
    for line in validate_csvs(person):
        print(f"  {line}")

    if dry_run:
        print("\nDry run — no writes performed.")
    return 0


def _row_count(path: Path) -> int:
    """Count data rows (excluding header)."""
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        return sum(1 for row in reader if any(c.strip() for c in row))


# ------------------------------------------------------------------ validate
def validate_csvs(person: str) -> list[str]:
    """Sanity-check the per-person CSV store.

    Reports header schema match, monotonic date order, and row counts.
    Read-only — never rewrites the CSVs; the importers' upsert helpers
    own the rewrite path.
    """
    out: list[str] = []
    profile = read_profile(person)
    source = profile.get("source") or "xml"
    if source not in HEALTH_METRICS_HEADERS_BY_SOURCE:
        source = "xml"

    targets: dict[str, tuple] = {
        "health_metrics.csv":   (health_metrics_csv(person),
                                 HEALTH_METRICS_HEADERS_BY_SOURCE[source],
                                 "desc"),
        "workout_sessions.csv": (workout_sessions_csv(person),
                                 WORKOUT_SESSIONS_HEADERS_BY_SOURCE[source],
                                 "desc"),
        "profile.csv":          (profile_csv(person),
                                 ["key", "value"],
                                 None),
    }
    # Per-month swim CSVs (XML trackers only — HL exports omit lap data).
    from person_paths import list_swim_workout_months, list_swim_lap_months
    for ym in list_swim_workout_months(person):
        targets[f"swimming/{ym}.workouts.csv"] = (
            swim_workouts_csv(person, ym), SWIM_WORKOUTS_HEADERS, "desc"
        )
    for ym in list_swim_lap_months(person):
        targets[f"swimming/{ym}.laps.csv"] = (
            swim_laps_csv(person, ym), SWIM_LAPS_HEADERS, "asc"
        )

    for label, (path, expected_header, order) in targets.items():
        if not path.exists():
            out.append(f"{label}: missing")
            continue
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                out.append(f"{label}: empty (no header)")
                continue
            rows = list(reader)
        if header != expected_header:
            out.append(
                f"{label}: header mismatch — got {header}, "
                f"expected {expected_header}"
            )
            continue
        if order in ("desc", "asc"):
            dates = [row[0] for row in rows if row and row[0]]
            if dates:
                if order == "desc" and any(
                    dates[i] < dates[i + 1] for i in range(len(dates) - 1)
                ):
                    out.append(f"{label}: WARN dates not strictly DESC")
                elif order == "asc" and any(
                    dates[i] > dates[i + 1] for i in range(len(dates) - 1)
                ):
                    out.append(f"{label}: WARN dates not strictly ASC")
        out.append(f"{label}: {len(rows)} rows ok")

    # Per-month workout CSVs.
    for ym in list_year_months(person):
        path = monthly_csv_path(person, ym)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            rows = list(reader)
        if header != MONTHLY_HEADERS:
            out.append(
                f"monthly/{ym}.csv: header mismatch — got {header}, "
                f"expected {MONTHLY_HEADERS}"
            )
            continue
        # Monotonic-ASC date check (skip TOTAL rows since they share
        # the session date with the data rows above them).
        dates = [
            row[1] for row in rows
            if len(row) > 3 and row[1]
            and (row[3] or "").strip().upper() != TOTAL_LABEL
        ]
        if dates and any(dates[i] > dates[i + 1] for i in range(len(dates) - 1)):
            out.append(f"monthly/{ym}.csv: WARN dates not strictly ASC")
        out.append(f"monthly/{ym}.csv: {len(rows)} rows ok")

    return out


# ------------------------------------------------------------------ historical fix
SUSPICIOUS_SWIM_DISTANCE_KM = 10.0


def _is_swim_label(exercise) -> bool:
    return isinstance(exercise, str) and exercise.strip().lower() == "swim"


def _is_swim_session_type(apple_type) -> bool:
    return isinstance(apple_type, str) and "swimming" in apple_type.lower()


def fix_distance_units(person: str, dry_run: bool = False) -> int:
    """Sweep all CSVs for the legacy meter-as-km swim distance bug.

    Auto-fix any swim row whose Distance (km) > 10 (almost certainly
    metres mis-stored as km): divide by 1000, recompute pace via the
    shared formatter. Print every change. For other activities (Run /
    Cycle / Walk / Hike), only flag suspicious rows where pace is
    implausibly fast — never auto-mutate them.

    Idempotent: a clean tracker prints "no fixes needed".
    """
    fixes: list[tuple[str, int, str]] = []
    flags: list[tuple[str, int, str]] = []

    # 1. Per-month workout CSVs.
    for ym in list_year_months(person):
        path = monthly_csv_path(person, ym)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            rows = list(reader)
        if header != MONTHLY_HEADERS:
            continue
        try:
            ex_idx = header.index("Exercise")
            dist_idx = header.index("Distance (km)")
            dur_idx = header.index("Duration (min)")
            pace_idx = header.index("Pace (min/km)")
        except ValueError:
            continue
        changed = False
        for i, row in enumerate(rows):
            if len(row) <= max(ex_idx, dist_idx, dur_idx, pace_idx):
                continue
            exercise = row[ex_idx]
            distance_v = row[dist_idx]
            duration_v = row[dur_idx]
            if not distance_v:
                continue
            try:
                distance = float(distance_v)
            except ValueError:
                continue

            if _is_swim_label(exercise) and distance > SUSPICIOUS_SWIM_DISTANCE_KM:
                new_distance = round(distance / 1000.0, 3)
                dur_min = _parse_duration_minutes(duration_v)
                new_pace = _format_pace_min_per_km(dur_min, new_distance)
                old_pace = row[pace_idx]
                row[dist_idx] = str(new_distance)
                row[pace_idx] = new_pace or ""
                fixes.append((
                    f"monthly/{ym}.csv", i + 2,
                    f"Swim {row[1]}: distance {distance} → {new_distance} km, "
                    f"pace {old_pace!r} → {new_pace!r}"
                ))
                changed = True
                continue

            dur_min = _parse_duration_minutes(duration_v)
            if dur_min and distance > 0:
                pace = dur_min / distance
                if pace < 0.5:
                    flags.append((
                        f"monthly/{ym}.csv", i + 2,
                        f"{exercise} {row[1]}: pace {pace:.3f} min/km — "
                        f"verify distance/duration"
                    ))
        if changed and not dry_run:
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(rows)
            canonicalize_monthly_csv(person, ym)

    # 2. Workout Sessions CSV.
    ws_path = workout_sessions_csv(person)
    if ws_path.exists():
        with ws_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            csv_rows = list(reader)
        if header:
            try:
                date_idx = header.index("Date")
                type_idx = header.index("Apple Type")
                dist_idx = header.index("Distance (km)")
            except ValueError:
                date_idx = type_idx = dist_idx = -1
            if date_idx >= 0 and type_idx >= 0 and dist_idx >= 0:
                csv_changed = False
                for i, row in enumerate(csv_rows):
                    if len(row) <= max(date_idx, type_idx, dist_idx):
                        continue
                    apple_type = row[type_idx]
                    if not _is_swim_session_type(apple_type):
                        continue
                    if not row[dist_idx]:
                        continue
                    try:
                        distance = float(row[dist_idx])
                    except ValueError:
                        continue
                    if distance > SUSPICIOUS_SWIM_DISTANCE_KM:
                        new_distance = round(distance / 1000.0, 3)
                        if not dry_run:
                            row[dist_idx] = str(new_distance)
                            csv_changed = True
                        fixes.append((
                            "workout_sessions.csv", i + 2,
                            f"Swimming {row[date_idx]}: "
                            f"distance {distance} → {new_distance} km"
                        ))
                if csv_changed and not dry_run:
                    with ws_path.open("w", encoding="utf-8", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow(header)
                        writer.writerows(csv_rows)

    # 3. Per-month Swim Workouts CSVs.
    from person_paths import list_swim_workout_months
    for ym in list_swim_workout_months(person):
        sw_path = swim_workouts_csv(person, ym)
        if not sw_path.exists():
            continue
        with sw_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            sw_header = next(reader, [])
            sw_csv_rows = list(reader)
        if not sw_header:
            continue
        try:
            sw_date_idx = sw_header.index("Date")
            sw_dist_idx = sw_header.index("Distance (km)")
        except ValueError:
            continue
        sw_changed = False
        for i, row in enumerate(sw_csv_rows):
            if len(row) <= max(sw_date_idx, sw_dist_idx):
                continue
            if not row[sw_dist_idx]:
                continue
            try:
                distance = float(row[sw_dist_idx])
            except ValueError:
                continue
            if distance > SUSPICIOUS_SWIM_DISTANCE_KM:
                new_distance = round(distance / 1000.0, 3)
                if not dry_run:
                    row[sw_dist_idx] = str(new_distance)
                    sw_changed = True
                fixes.append((
                    f"swimming/{ym}.workouts.csv", i + 2,
                    f"Swim {row[sw_date_idx]}: "
                    f"distance {distance} → {new_distance} km"
                ))
        if sw_changed and not dry_run:
            with sw_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(sw_header)
                writer.writerows(sw_csv_rows)

    if not fixes and not flags:
        print(f"{person}: no fixes needed")
        return 0

    print(f"{person}:")
    for label, row, msg in fixes:
        print(f"  fix [{label} row {row}]: {msg}")
    for label, row, msg in flags:
        print(f"  flag [{label} row {row}]: {msg}")
    if dry_run:
        print(f"\nDry run — {len(fixes)} fixes would be applied, "
              f"{len(flags)} flags reviewed (no save).")
    else:
        print(f"\n{len(fixes)} fixes applied, {len(flags)} flags reviewed.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", required=True,
                    help="Tracker owner (e.g. Nihad or Fabian).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fix-distance-units", action="store_true",
                    help="Run the meter-as-km historical sweep across all CSVs")
    args = ap.parse_args()
    if args.fix_distance_units:
        sys.exit(fix_distance_units(args.person, args.dry_run))
    sys.exit(run(args.person, args.dry_run))
