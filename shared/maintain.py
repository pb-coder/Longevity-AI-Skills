"""Workout Tracker monthly maintenance.

Idempotent. Safe to re-run. Performs:
  1. Canonicalize every per-month workout CSV (sort, recompute Volume/
     Pace/SESSION, rebuild TOTAL rows, hoist deload markers).
  2. Validate all CSVs (header schema match, monotonic date order,
     row counts). A header mismatch is reported and the remaining
     checks still run.
  3. Optional ``--fix-distance-units`` swim sweep (legacy meter-as-km
     bug across monthly CSVs + workout_sessions.csv +
     swimming/YYYY.MM.workouts.csv).
  4. Optional ``--fix-header`` health_metrics.csv schema-header rewrite.

Steps 1 and 2 are the default run; steps 3 and 4 mutate and only happen
when asked for by name. Validation itself never writes.

Post-PR3a: there is no xlsx anywhere. Per-month workout data lives in
``<Person>/data/monthly/YYYY.MM.csv``. Health Metrics, Workout Sessions,
and Profile live in ``<Person>/data/`` directly; per-month swim data
lives in ``<Person>/data/swimming/YYYY.MM.{workouts,laps}.csv``;
per-month sleep data in ``<Person>/data/sleep/YYYY.MM.nights.csv``.

Usage (from the workout-tracker root):
    python3 Skills/shared/maintain.py --person <Person>
    python3 Skills/shared/maintain.py --person <Person> --dry-run
    python3 Skills/shared/maintain.py --person <Person> --fix-distance-units
    python3 Skills/shared/maintain.py --person <Person> --fix-header
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(SKILLS_ROOT))
    __package__ = "shared"
from tracker import TrackerContext  # noqa: E402
from tracker.csv_table import write_csv_atomic  # noqa: E402
from .monthly_csv import (  # noqa: E402
    MONTHLY_HEADERS,
    TOTAL_LABEL,
    _format_pace_min_per_km,
    _parse_duration_minutes,
    canonicalize_monthly_csv,
    list_year_months,
)
from .csv_store import (  # noqa: E402
    HEALTH_METRICS_HEADERS_BY_SOURCE,
    LIGHT_THERAPY_SESSIONS_HEADERS,
    SLEEP_NIGHTS_HEADERS,
    SWIM_LAPS_HEADERS,
    SWIM_WORKOUTS_HEADERS,
    THERMAL_SESSIONS_HEADERS,
    WORKOUT_SESSIONS_HEADERS_BY_SOURCE,
    migrate_health_metrics_header,
    read_profile,
)
from .person_paths import (  # noqa: E402
    health_metrics_csv,
    light_therapy_sessions_csv,
    monthly_csv as monthly_csv_path,
    monthly_dir,
    profile_csv,
    sleep_nights_csv,
    swim_laps_csv,
    swim_workouts_csv,
    thermal_sessions_csv,
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
# Files whose header drift has a wired migration. The hint is appended to
# the mismatch line so the validator names the remedy instead of leaving
# the reader to find it. Nothing here runs automatically — see
# ``validate_csvs``.
HEADER_FIX_HINTS = {
    "health_metrics.csv": " — run with --fix-header to migrate",
}


def validate_csvs(person: str) -> list[str]:
    """Sanity-check the per-person CSV store.

    Reports header schema match, monotonic date order, and row counts.
    Read-only — never rewrites the CSVs; the importers' upsert helpers
    own the rewrite path, and ``--fix-header`` is the opt-in migration.

    A header mismatch is reported and validation continues. Aborting the
    file on mismatch (the old behaviour) meant both real trackers, sitting
    on a 16-column health_metrics.csv against a 19-column schema, got the
    mismatch line and nothing else — no sort-order check, no row count —
    for as long as the migration went unrun.
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
    from .person_paths import (
        list_light_therapy_session_months,
        list_sleep_night_months,
        list_swim_lap_months,
        list_swim_workout_months,
        list_thermal_session_months,
    )
    for ym in list_swim_workout_months(person):
        targets[f"swimming/{ym}.workouts.csv"] = (
            swim_workouts_csv(person, ym), SWIM_WORKOUTS_HEADERS, "desc"
        )
    for ym in list_swim_lap_months(person):
        targets[f"swimming/{ym}.laps.csv"] = (
            swim_laps_csv(person, ym), SWIM_LAPS_HEADERS, "asc"
        )
    # Per-month sleep CSVs (XML trackers only — HL exports omit per-stage data;
    # also present on any tracker that has manual /log sleep entries).
    for ym in list_sleep_night_months(person):
        targets[f"sleep/{ym}.nights.csv"] = (
            sleep_nights_csv(person, ym), SLEEP_NIGHTS_HEADERS, "desc"
        )
    # Per-month thermal (sauna + cold) CSVs — manual /log only; absent
    # until first sauna / cold session is logged.
    for ym in list_thermal_session_months(person):
        targets[f"thermal/{ym}.sessions.csv"] = (
            thermal_sessions_csv(person, ym), THERMAL_SESSIONS_HEADERS, "desc"
        )
    # Per-month light-therapy (RLT / PBM / blue light) CSVs — manual
    # /log only; absent until first light-therapy session is logged.
    for ym in list_light_therapy_session_months(person):
        targets[f"light_therapy/{ym}.sessions.csv"] = (
            light_therapy_sessions_csv(person, ym),
            LIGHT_THERAPY_SESSIONS_HEADERS, "desc"
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
            # Report and keep going. A header mismatch used to abort this
            # file's checks entirely, which silenced the sort-order and
            # row-count lines during a schema migration — precisely the
            # window in which they are most worth reading. Date is column
            # 0 in every schema in ``targets``, so the order check below
            # stays meaningful under a mismatch.
            out.append(
                f"{label}: WARN header mismatch — got {len(header)} cols "
                f"{header}, expected {len(expected_header)} cols "
                f"{expected_header}{HEADER_FIX_HINTS.get(label, '')}"
            )
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
            write_csv_atomic(path, header, rows)
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
                    write_csv_atomic(ws_path, header, csv_rows)

    # 3. Per-month Swim Workouts CSVs.
    from .person_paths import list_swim_workout_months
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
            write_csv_atomic(sw_path, sw_header, sw_csv_rows)

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


def fix_health_metrics_header(person: str, dry_run: bool = False) -> int:
    """Opt-in: rewrite health_metrics.csv under the current schema header.

    Deliberately a flag rather than something ``run()`` does on its own.
    ``maintain.py`` is documented as diagnostics and ``validate_csvs`` is
    read-only; silently rewriting the user's real CSV as a side effect of
    asking "is anything wrong?" would violate both, and would do it at the
    one moment — mid-schema-change — when an unreviewed rewrite is most
    likely to be the wrong move. ``--fix-distance-units`` set the
    precedent: detect and report by default, mutate only when asked.

    Idempotent. Honours ``--dry-run``.
    """
    print(migrate_health_metrics_header(person, dry_run))
    return 0


def migrate_incidental_flag(person: str, dry_run: bool = False) -> int:
    """One-shot 2026-05 migration: move the ``"incidental walk"`` Notes
    string to the new ``Incidental`` boolean column on workout_sessions.csv.

    Per the 2026-05 Notes-hygiene cleanup: pipeline-state strings don't
    belong in Notes (they recur, are invisible to filtering, and crowd
    out user annotations). Walks are now flagged via the typed
    ``Incidental`` column; this function back-fills existing rows.

    Idempotent — re-running on already-migrated rows is a no-op. Safe
    to call from cron / re-imports.

    Returns 0 on success.
    """
    from .csv_store import read_workout_sessions, _resolve_source  # noqa
    import csv

    path = workout_sessions_csv(person)
    if not path.exists():
        print(f"workout_sessions.csv not found for {person}: {path}")
        return 0

    source = _resolve_source(person)
    headers = WORKOUT_SESSIONS_HEADERS_BY_SOURCE[source]
    # Use the header-aware reader (handles legacy 12-col rows).
    rows = read_workout_sessions(person)

    migrated = 0
    already = 0
    untouched = 0
    out_rows: list[list] = []
    fields = list(headers[1:])  # everything except Date
    field_keys: list[str] = []
    # Map header → internal field key (same order as csv_store
    # WORKOUT_SESSIONS_FIELDS_BY_SOURCE; explicit map for clarity).
    HEADER_TO_FIELD = {
        "Start": "start", "End": "end", "Apple Type": "apple_type",
        "Duration (min)": "duration_min",
        "Avg HR (bpm)": "avg_hr", "Max HR (bpm)": "max_hr",
        "Min HR (bpm)": "min_hr",
        "Active Cal (kcal)": "active_cal", "Distance (km)": "distance_km",
        "Source": "source", "Incidental": "incidental", "Notes": "notes",
    }
    for h in fields:
        field_keys.append(HEADER_TO_FIELD.get(h, h.lower().replace(" ", "_")))

    for rec in rows:
        notes = (rec.get("notes") or "")
        already_flagged = rec.get("incidental") is True
        looks_incidental = notes.lower().startswith("incidental")
        if looks_incidental and not already_flagged:
            rec["incidental"] = True
            # Strip the prefix from Notes. The marker on every observed
            # row is exactly "incidental walk" with no trailing
            # annotation, but be defensive in case future text appears
            # after the marker (e.g. "incidental walk; lower back").
            after = notes[len("incidental"):].removeprefix(" walk").lstrip(" -;,")
            rec["notes"] = after.strip() or None
            migrated += 1
        elif already_flagged:
            already += 1
        else:
            untouched += 1
        # Build the output row in HEADER order.
        out_row = [rec.get("date")]
        for key in field_keys:
            v = rec.get(key)
            if v is None:
                out_row.append("")
            elif isinstance(v, bool):
                out_row.append("true" if v else "false")
            else:
                out_row.append(v)
        out_rows.append(out_row)

    summary = (
        f"workout_sessions.csv ({person}): {migrated} migrated to incidental=True, "
        f"{already} already flagged, {untouched} untouched ({len(rows)} total)"
    )
    print(summary)
    if dry_run:
        print("Dry run — no writes performed.")
        return 0
    if migrated == 0:
        print("No rows to migrate; file already clean.")
        return 0

    # Sort DESC by (date, start) to match the existing convention.
    out_rows.sort(key=lambda r: (str(r[0] or ""), str(r[1] or "")), reverse=True)
    write_csv_atomic(path, headers, out_rows)
    print(f"Wrote {len(out_rows)} rows back to {path.name}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", required=True,
                    help="Tracker owner (e.g. <Person> or <OtherPerson>).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fix-distance-units", action="store_true",
                    help="Run the meter-as-km historical sweep across all CSVs")
    ap.add_argument("--fix-header", action="store_true",
                    help="Rewrite health_metrics.csv under the current schema "
                         "header. Opt-in: a plain validate run only reports "
                         "the mismatch. Idempotent.")
    ap.add_argument("--migrate-incidental-flag", action="store_true",
                    help="One-shot 2026-05 migration: move 'incidental walk' "
                         "from Notes to the new Incidental column on "
                         "workout_sessions.csv. Idempotent.")
    args = ap.parse_args()
    ctx = TrackerContext(args.person)
    if args.fix_distance_units:
        return fix_distance_units(ctx.person, args.dry_run)
    if args.fix_header:
        return fix_health_metrics_header(ctx.person, args.dry_run)
    if args.migrate_incidental_flag:
        return migrate_incidental_flag(ctx.person, args.dry_run)
    return run(ctx.person, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
