"""Workout Tracker monthly maintenance.

Idempotent. Safe to re-run. Performs:
  1. Restyle all sheets to the canonical look
  2. Trim empty trailing rows/columns (with buffer for monthly sheets)
  3. Reorder sheets: Exercises Database first, months newest → oldest
  4. Report row counts and verify data integrity

Usage:
    python3 maintain.py "/path/to/Workout Tracker.xlsx"
    python3 maintain.py "/path/to/Workout Tracker.xlsx" --dry-run
"""
import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from sheet_styles import (  # noqa: E402
    MONTHLY_COLS,
    DB_COLS,
    find_last_data_cell,
    style_monthly_sheet,
    style_db_sheet,
)

# Row buffer policy when trimming empty rows.
# Current-month sheet: leave a generous buffer since the user is actively logging.
# Past-month sheets: 2 blank rows.
# Exercises Database: 0 (static-ish lookup table).
CURRENT_MONTH_BUFFER = 50
PAST_MONTH_BUFFER = 2
DB_BUFFER = 0


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
    """Put Exercises Database first, then monthly sheets newest → oldest."""
    names = list(wb.sheetnames)
    db = [n for n in names if n == "Exercises Database"]
    months = sorted((n for n in names if is_monthly(n)), reverse=True)
    other = [n for n in names if n not in db and n not in months]
    desired = db + months + other

    # Use move_sheet: openpyxl needs the sheet object and an index.
    for target_idx, name in enumerate(desired):
        ws = wb[name]
        cur_idx = wb.sheetnames.index(name)
        if cur_idx != target_idx:
            wb.move_sheet(ws, offset=target_idx - cur_idx)


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
    before_counts = {name: count_nonempty_rows(wb[name]) for name in wb.sheetnames}

    # 1. Style + trim every sheet
    current = current_month_key()
    for name in list(wb.sheetnames):
        ws = wb[name]
        if name == "Exercises Database":
            style_db_sheet(ws)
            trim_sheet(ws, buffer=DB_BUFFER, target_cols=DB_COLS)
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
    count = 0
    for row in ws.iter_rows():
        if any(c.value is not None and c.value != "" for c in row):
            count += 1
    return count


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sys.exit(run(args.xlsx, args.dry_run))
