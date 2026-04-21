"""Canonical Workout Tracker styling.

Shared between /log (applied on every append) and /maintain (full-sheet
restyle). Idempotent: running `style_monthly_sheet` twice in a row is a no-op.

Keep this module the single source of truth for fonts, fills, borders,
column widths, and alignment.
"""
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# ------------------------------------------------------------------ palette
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

# ------------------------------------------------------------------ structure
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

# Bodyweight sheet: 4 columns (Year | Date | Kg | Notes). Morning / empty-stomach
# weigh-ins. Sorted DESC (newest at the top). Column A holds the year label,
# merged vertically across all rows that share that year. Notes left-aligned;
# Year/Date/Kg centered.
BODYWEIGHT_WIDTHS = {"A": 7, "B": 12, "C": 7, "D": 40}
BODYWEIGHT_LEFT_COLS = {"D"}
BODYWEIGHT_COLS = 4
BODYWEIGHT_HEADERS = ["Year", "Date", "Kg", "Notes"]


# ------------------------------------------------------------------ helpers
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


def style_bodyweight_sheet(ws):
    """Apply canonical styling to the Bodyweight sheet.

    Layout: Year | Date | Kg | Notes. Data sorted DESC (newest on top) by the
    writers (seed_bodyweight.py, append_workout.upsert_bodyweight). This
    function restyles in place and re-applies the per-year vertical merge on
    column A based on whatever dates are present in column B. Idempotent.
    """
    # Unmerge any existing merges so we can re-apply cleanly.
    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))

    # Header row
    for c, label in enumerate(BODYWEIGHT_HEADERS, 1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = no_border

    # Data rows: style every cell, and populate column A with the year
    # derived from column B. We'll merge contiguous same-year runs below.
    last_data_row, _ = find_last_data_cell(ws)
    for r in range(2, last_data_row + 1):
        date_val = ws.cell(row=r, column=2).value
        year = None
        if date_val is not None and date_val != "":
            s = str(date_val)[:4]
            if s.isdigit() and len(s) == 4:
                year = int(s)
        ws.cell(row=r, column=1, value=year)

        for c in range(1, BODYWEIGHT_COLS + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = font_data
            cell.fill = fill_data
            col = cell.column_letter
            cell.alignment = align_left if col in BODYWEIGHT_LEFT_COLS else align_center
            cell.border = no_border

    # Merge column A in contiguous same-year runs. Requires DESC-sorted data
    # so that each year's rows are grouped; writers guarantee this.
    run_start = None
    run_year = None
    for r in range(2, last_data_row + 2):  # +2 to flush final run
        year = ws.cell(row=r, column=1).value if r <= last_data_row else None
        if year != run_year:
            if run_year is not None and run_start is not None and r - 1 > run_start:
                ws.merge_cells(
                    start_row=run_start, end_row=r - 1,
                    start_column=1, end_column=1,
                )
            run_start = r if year is not None else None
            run_year = year

    # Column widths + freeze pane
    for col, w in BODYWEIGHT_WIDTHS.items():
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
