"""Workout Tracker monthly maintenance.

Idempotent. Safe to re-run. Performs:
  1. Restyle all sheets to the canonical look
  2. Trim empty trailing rows/columns (with buffer for monthly sheets)
  3. Reorder sheets: Exercises Database, Bodyweight, months newest → oldest
  4. Report row counts and verify data integrity

Usage:
    python3 maintain.py "/path/to/Workout Tracker - <Person>.xlsx"
    python3 maintain.py "/path/to/Workout Tracker - <Person>.xlsx" --dry-run
"""
import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from tracker_sheet import (  # noqa: E402
    MONTHLY_COLS,
    DB_COLS,
    BODYWEIGHT_COLS,
    HEALTH_METRICS_COLS_BY_SOURCE,
    HEALTH_METRICS_SHEET_NAME,
    PROFILE_SHEET_NAME,
    WORKOUT_SESSIONS_COLS_BY_SOURCE,
    WORKOUT_SESSIONS_SHEET_NAME,
    _format_pace_min_per_km,
    _parse_duration_minutes,
    canonicalize_sheet_order,
    date_str,
    find_last_data_cell,
    read_profile,
    style_monthly_sheet,
    style_db_sheet,
    style_bodyweight_sheet,
    style_health_metrics_sheet,
    style_profile_sheet,
    style_workout_sessions_sheet,
)

# Row buffer policy when trimming empty rows.
# Current-month sheet: leave a generous buffer since the user is actively logging.
# Past-month sheets: 2 blank rows.
# Exercises Database: 0 (static-ish lookup table).
# Bodyweight: 10 (small buffer for upcoming entries).
# Health Metrics + Workout Sessions: 30 (Apple emits daily, fills fast).
CURRENT_MONTH_BUFFER = 50
PAST_MONTH_BUFFER = 2
DB_BUFFER = 0
BODYWEIGHT_BUFFER = 10
HEALTH_METRICS_BUFFER = 30
WORKOUT_SESSIONS_BUFFER = 30
# Profile holds a fixed set of key/value rows; no buffer needed because the
# sheet is configuration, not a growing log.
PROFILE_BUFFER = 0
PROFILE_COLS = 2


# ------------------------------------------------------------------ helpers
def is_monthly(sheet_name: str) -> bool:
    return bool(re.match(r"^\d{4}\.\d{2}$", sheet_name))


def current_month_key():
    """Return the YYYY.MM string for the current calendar month."""
    return datetime.now().strftime("%Y.%m")


# ------------------------------------------------------------------ trim
def trim_sheet(ws, buffer: int, target_cols: int):
    """Drop trailing empty rows (keeping `buffer` extras) and cap columns at `target_cols`."""
    last_r, last_c = find_last_data_cell(ws)
    if last_r < 1:
        last_r = 1
    target_last_row = last_r + buffer

    if ws.max_row > target_last_row:
        ws.delete_rows(target_last_row + 1, ws.max_row - target_last_row)
    if ws.max_column > target_cols:
        ws.delete_cols(target_cols + 1, ws.max_column - target_cols)


# ------------------------------------------------------------------ reorder
def reorder_sheets(wb):
    """Delegate to the shared canonicalize_sheet_order helper.

    Kept as a thin wrapper so existing callers (and tests, if any) don't
    need to update their call sites — the canonical order logic lives in
    ``tracker_sheet`` so writers (`/log`, importers, /maintain) all use
    the same code path.
    """
    canonicalize_sheet_order(wb)


# ------------------------------------------------------------------ main
def run(path: Path, dry_run: bool = False) -> int:
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1

    # Safety backup before any write.
    if not dry_run:
        backup = path.with_suffix(".maintain-backup.xlsx")
        shutil.copy2(path, backup)
        print(f"Backup: {backup.name}")

    wb = openpyxl.load_workbook(path)

    # 0. Drop empty monthly sheets that aren't the current month — keeps the
    # workbook lean. Empty sheets get created by accident (e.g. a future-month
    # placeholder) and clutter the tab bar. The current month is preserved
    # even when empty because /log may write to it any moment.
    current = current_month_key()
    for name in list(wb.sheetnames):
        if is_monthly(name) and name != current:
            if count_nonempty_rows(wb[name]) == 0:
                del wb[name]
                print(f"Dropped empty sheet: {name}")

    before_counts = {name: count_nonempty_rows(wb[name]) for name in wb.sheetnames}

    # Resolve the data source once — drives the slim/full schema for the
    # Health Metrics + Workout Sessions sheets.
    src = read_profile(wb).get("source") or "xml"
    if src not in HEALTH_METRICS_COLS_BY_SOURCE:
        src = "xml"
    hm_cols = HEALTH_METRICS_COLS_BY_SOURCE[src]
    ws_cols = WORKOUT_SESSIONS_COLS_BY_SOURCE[src]

    # 1. Style + trim every sheet
    for name in list(wb.sheetnames):
        ws = wb[name]
        if name == "Exercises Database":
            style_db_sheet(ws)
            trim_sheet(ws, buffer=DB_BUFFER, target_cols=DB_COLS)
        elif name == PROFILE_SHEET_NAME:
            style_profile_sheet(ws)
            trim_sheet(ws, buffer=PROFILE_BUFFER, target_cols=PROFILE_COLS)
        elif name == "Bodyweight":
            style_bodyweight_sheet(ws)
            trim_sheet(ws, buffer=BODYWEIGHT_BUFFER, target_cols=BODYWEIGHT_COLS)
        elif name == HEALTH_METRICS_SHEET_NAME:
            style_health_metrics_sheet(ws, source=src)
            trim_sheet(ws, buffer=HEALTH_METRICS_BUFFER, target_cols=hm_cols)
        elif name == WORKOUT_SESSIONS_SHEET_NAME:
            style_workout_sessions_sheet(ws, source=src)
            trim_sheet(ws, buffer=WORKOUT_SESSIONS_BUFFER, target_cols=ws_cols)
        elif is_monthly(name):
            style_monthly_sheet(ws)
            buf = CURRENT_MONTH_BUFFER if name == current else PAST_MONTH_BUFFER
            trim_sheet(ws, buffer=buf, target_cols=MONTHLY_COLS)

    # 2. Reorder
    reorder_sheets(wb)

    # 3. Verify data integrity (nonempty row counts should be preserved)
    after_counts = {name: count_nonempty_rows(wb[name]) for name in wb.sheetnames}
    mismatches = [n for n in before_counts if before_counts[n] != after_counts.get(n)]
    if mismatches:
        print(f"ERROR: nonempty row count changed: {mismatches}", file=sys.stderr)
        for n in mismatches:
            print(f"  {n}: before={before_counts[n]} after={after_counts.get(n)}")
        return 2

    # 4. Write
    if dry_run:
        print("Dry run — not saving.")
    else:
        wb.save(path)
        print(f"Saved: {path.name}")

    print("\nFinal sheet order:", list(wb.sheetnames))
    print("\nRow counts per sheet:")
    for name in wb.sheetnames:
        ws = wb[name]
        last_r, last_c = find_last_data_cell(ws)
        print(f"  {name}: data rows={after_counts[name]:4d}  max_row={ws.max_row:4d}  max_col={ws.max_column}")
    return 0


def count_nonempty_rows(ws) -> int:
    """Count non-empty rows.

    Monthly sheets: count rows with an Exercise value populated, excluding
    TOTAL summary rows. Exercise sits at col C pre-migration, col D post-
    migration; we read both and take whichever is populated. This ignores
    legacy trailing rows that only held a carried-down Volume formula —
    they have no exercise name, so they don't represent logged sets either
    before or after migration. Keeps the before/after verify stable.

    Other sheets: count any row with content.
    """
    if is_monthly(ws.title):
        count = 0
        for row in ws.iter_rows(min_row=2):
            ex_c = row[2].value if len(row) > 2 else None  # col C
            ex_d = row[3].value if len(row) > 3 else None  # col D
            exercise = ex_c if isinstance(ex_c, str) else ex_d
            if not isinstance(exercise, str) or not exercise.strip():
                continue
            if exercise.strip().upper() == "TOTAL":
                continue
            count += 1
        return count

    count = 0
    for row in ws.iter_rows():
        if any(c.value is not None and c.value != "" for c in row):
            count += 1
    return count


# ------------------------------------------------------------------ historical fix
# Distance threshold above which a Swim row's value is almost certainly a
# meter-as-km bug. Open-water records exceed 30 km but the tracker's user
# base is pool-only; >10 km is functionally never legitimate here.
SUSPICIOUS_SWIM_DISTANCE_KM = 10.0


def _is_swim(exercise) -> bool:
    return isinstance(exercise, str) and exercise.strip().lower() == "swim"


def _is_swim_session_type(apple_type) -> bool:
    return isinstance(apple_type, str) and "swimming" in apple_type.lower()


def fix_distance_units(path: Path, dry_run: bool = False) -> int:
    """Scan all monthly + Workout Sessions rows for the meter-as-km bug.

    Auto-fix swim rows whose Distance (km) > 10 (almost certainly metres):
    divide by 1000, recompute pace via the shared formatter (which now
    blanks degenerate ``0:01`` outputs). Print every change. For other
    activities (Run / Cycle / Walk / Hike), only flag suspicious rows
    where pace is implausibly fast — never auto-mutate them, since the
    XML importer never had the unit bug for non-swims.

    Idempotent: re-runs on a clean tracker print "no fixes needed" and
    don't touch the file.
    """
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1

    wb = openpyxl.load_workbook(path)
    fixes: list[tuple[str, int, str]] = []
    flags: list[tuple[str, int, str]] = []

    for name in wb.sheetnames:
        if is_monthly(name):
            ws = wb[name]
            for r in range(2, ws.max_row + 1):
                exercise = ws.cell(row=r, column=4).value
                distance_v = ws.cell(row=r, column=10).value
                duration_v = ws.cell(row=r, column=11).value
                if distance_v in (None, ""):
                    continue
                try:
                    distance = float(distance_v)
                except (TypeError, ValueError):
                    continue

                if _is_swim(exercise) and distance > SUSPICIOUS_SWIM_DISTANCE_KM:
                    new_distance = round(distance / 1000.0, 3)
                    dur_min = _parse_duration_minutes(duration_v)
                    new_pace = _format_pace_min_per_km(dur_min, new_distance)
                    old_pace = ws.cell(row=r, column=12).value
                    if not dry_run:
                        ws.cell(row=r, column=10).value = new_distance
                        ws.cell(row=r, column=12).value = new_pace
                    fixes.append((
                        name, r,
                        f"Swim {date_str(ws.cell(row=r, column=2).value)}: "
                        f"distance {distance} → {new_distance} km, "
                        f"pace {old_pace!r} → {new_pace!r}"
                    ))
                    continue

                # Sanity-flag non-swim rows where pace is implausibly fast.
                # Don't mutate — these almost never come from a unit bug
                # (Apple records run/cycle in km already), so an outlier
                # here is more likely a manual typo worth human review.
                dur_min = _parse_duration_minutes(duration_v)
                if dur_min and distance > 0:
                    pace = dur_min / distance
                    if pace < 0.5:
                        flags.append((
                            name, r,
                            f"{exercise} {date_str(ws.cell(row=r, column=2).value)}: "
                            f"pace {pace:.3f} min/km — verify distance/duration"
                        ))

        elif name == WORKOUT_SESSIONS_SHEET_NAME:
            # Same rule on the Workout Sessions sheet's Distance (km) col J,
            # filtered to Swimming rows. Schema differs per source; pull the
            # column index by header name to stay schema-agnostic.
            ws = wb[name]
            header_to_col: dict[str, int] = {}
            for c in range(1, ws.max_column + 1):
                v = ws.cell(row=1, column=c).value
                if isinstance(v, str):
                    header_to_col[v.strip()] = c
            type_col = header_to_col.get("Apple Type")
            dist_col = header_to_col.get("Distance (km)")
            date_col = header_to_col.get("Date")
            if not (type_col and dist_col):
                continue
            for r in range(2, ws.max_row + 1):
                apple_type = ws.cell(row=r, column=type_col).value
                if not _is_swim_session_type(apple_type):
                    continue
                distance_v = ws.cell(row=r, column=dist_col).value
                if distance_v in (None, ""):
                    continue
                try:
                    distance = float(distance_v)
                except (TypeError, ValueError):
                    continue
                if distance > SUSPICIOUS_SWIM_DISTANCE_KM:
                    new_distance = round(distance / 1000.0, 3)
                    if not dry_run:
                        ws.cell(row=r, column=dist_col).value = new_distance
                    d = ws.cell(row=r, column=date_col).value if date_col else "?"
                    fixes.append((
                        name, r,
                        f"Swimming {d}: distance {distance} → {new_distance} km"
                    ))

    if not fixes and not flags:
        print(f"{path.name}: no fixes needed")
        return 0

    print(f"{path.name}:")
    for sheet, row, msg in fixes:
        print(f"  fix [{sheet} row {row}]: {msg}")
    for sheet, row, msg in flags:
        print(f"  flag [{sheet} row {row}]: {msg}")

    # Re-style every monthly sheet that received a fix so the corrected
    # Pace cell is laid out properly. Cheap and idempotent.
    if fixes and not dry_run:
        touched_monthly = sorted({s for s, _r, _m in fixes if is_monthly(s)})
        for s in touched_monthly:
            style_monthly_sheet(wb[s])

    if dry_run:
        print(f"\nDry run — {len(fixes)} fixes would be applied, "
              f"{len(flags)} flags reviewed (no save).")
    else:
        if fixes:
            backup = path.with_suffix(".fix-units-backup.xlsx")
            shutil.copy2(path, backup)
            print(f"\nBackup: {backup.name}")
            wb.save(path)
            print(f"Saved: {path.name} ({len(fixes)} fixes applied, "
                  f"{len(flags)} flags reviewed)")
        else:
            print(f"\n{len(flags)} flags reviewed; no auto-fixes applied.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--fix-distance-units", action="store_true",
        help="Run the meter-as-km historical sweep for swim rows",
    )
    args = ap.parse_args()
    if args.fix_distance_units:
        sys.exit(fix_distance_units(args.xlsx, args.dry_run))
    sys.exit(run(args.xlsx, args.dry_run))
