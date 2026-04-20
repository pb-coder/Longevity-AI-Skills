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
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# ------------------------------------------------------------------ styles
HEADER_FILL = "FFBDC3C7"
DATA_FILL   = "FFF2F3F4"
NAVY        = "FF2C3E50"
LIGHT_GRAY  = "FFD5D8DC"
SUBSEC_FILL = "FFEAEDED"
BLACK = "FF000000"
WHITE = "FFFFFFFF"
SEP_COLOR = "FFBDC3C7"

font_header    = Font(bold=True, size=10, color=BLACK)
font_section_w = Font(bold=True, size=10, color=WHITE)
font_section_b = Font(bold=True, size=10, color=BLACK)
font_subsec    = Font(bold=True, italic=True, size=10, color=BLACK)
font_data      = Font(bold=False, size=10, color=BLACK)

fill_header = PatternFill("solid", fgColor=HEADER_FILL)
fill_navy   = PatternFill("solid", fgColor=NAVY)
fill_gray   = PatternFill("solid", fgColor=LIGHT_GRAY)
fill_subsec = PatternFill("solid", fgColor=SUBSEC_FILL)
fill_data   = PatternFill("solid", fgColor=DATA_FILL)

align_center = Alignment(horizontal="center", vertical="center", wrap_text=False)
align_left   = Alignment(horizontal="left",   vertical="center", wrap_text=False)

sep_side = Side(style="thin", color=SEP_COLOR)
border_session = Border(top=sep_side)
no_border = Border()

# Monthly sheet columns (A..L). Notes column reads better left-aligned.
MONTHLY_WIDTHS = {
    "A": 12, "B": 5,  "C": 28, "D": 5,  "E": 6,  "F": 6,
    "G": 9,  "H": 24, "I": 13, "J": 14, "K": 13, "L": 9,
}
MONTHLY_LEFT_COLS = {"H"}
MONTHLY_COLS = 12

# Exercises Database: 5 columns (Exercise | Type | Primary Muscle | Equipment | Variations).
DB_WIDTHS = {"A": 30, "B": 13, "C": 16, "D": 14, "E": 48}
DB_COLS = 5

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


def find_last_data_cell(ws):
    """Return (last_data_row, last_data_col) — the max row/col with any value."""
    last_r, last_c = 0, 0
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None and cell.value != "":
                if cell.row > last_r:
                    last_r = cell.row
                if cell.column > last_c:
                    last_c = cell.column
    return last_r, last_c


def current_month_key():
    """Return the YYYY.MM string for the current calendar month."""
    return datetime.now().strftime("%Y.%m")


# ------------------------------------------------------------------ styling
def style_monthly_sheet(ws):
    """Apply canonical styling to a YYYY.MM workout log sheet."""
    last_data_row, _ = find_last_data_cell(ws)
    if last_data_row < 1:
        last_data_row = 1

    # Header row
    for c in range(1, MONTHLY_COLS + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = no_border

    # Data rows
    prev_date = None
    for r in range(2, last_data_row + 1):
        date_val = ws.cell(row=r, column=1).value
        new_session = date_val is not None and date_val != prev_date
        if date_val is not None:
            prev_date = date_val
        for c in range(1, MONTHLY_COLS + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = font_data
            cell.fill = fill_data
            col = cell.column_letter
            cell.alignment = align_left if col in MONTHLY_LEFT_COLS else align_center
            cell.border = border_session if (new_session and r > 2) else no_border

    # Column widths + freeze pane
    for col, w in MONTHLY_WIDTHS.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


def style_db_sheet(ws):
    """Reapply header + column widths on the Exercises Database.

    Does NOT reorder or rewrite body rows — assumes the DB is already organized
    by muscle > pattern. Only enforces: header row 1, col widths, freeze pane,
    and data-row fills for any bare rows.
    """
    # Header row
    headers = ["Exercise", "Type", "Primary Muscle", "Equipment", "Variations"]
    for c, label in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center

    # Restyle any data rows that lack the canonical fill.
    # Section headers (navy/gray) and subsections (EAEDED) keep their existing styles.
    last_data_row, _ = find_last_data_cell(ws)
    for r in range(2, last_data_row + 1):
        name = ws.cell(row=r, column=1).value
        typ  = ws.cell(row=r, column=2).value
        if not name or not typ:
            continue  # section header row — leave as is
        for c in range(1, DB_COLS + 1):
            cell = ws.cell(row=r, column=c)
            if cell.fill.fgColor is None or cell.fill.fgColor.rgb != DATA_FILL:
                cell.fill = fill_data
            if cell.font.size != 10 or cell.font.bold:
                cell.font = font_data
            if cell.alignment.horizontal != "center":
                cell.alignment = align_center

    # Widths + freeze
    for col, w in DB_WIDTHS.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


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
