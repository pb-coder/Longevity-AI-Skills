from __future__ import annotations

"""Canonical Workout Tracker sheet module.

Single source of truth for:

- **Layout**: headers, column counts, widths (monthly / bodyweight / DB).
- **Coercions**: ``date_str`` for Date cells, ``_numeric_cell`` for
  stringified numbers, ``bw_locate_date`` for the bodyweight row layout.
- **Styling**: fonts, fills, borders, alignment, freeze pane.

Shared by ``/log`` (applied on every append) and ``/maintain`` (full-sheet
restyle). ``/coach`` imports the coercion helpers only. Every
``style_*_sheet`` function is idempotent — running it twice in a row is a
no-op.
"""
from datetime import datetime, date
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

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
font_total     = Font(bold=True, size=10, color=BLACK)

fill_header = PatternFill("solid", fgColor=HEADER_FILL)
fill_navy   = PatternFill("solid", fgColor=NAVY)
fill_gray   = PatternFill("solid", fgColor=LIGHT_GRAY)
fill_subsec = PatternFill("solid", fgColor=SUBSEC_FILL)
fill_data   = PatternFill("solid", fgColor=DATA_FILL)
fill_total  = PatternFill("solid", fgColor=LIGHT_GRAY)

align_center = Alignment(horizontal="center", vertical="center", wrap_text=False)
align_left   = Alignment(horizontal="left",   vertical="center", wrap_text=False)

sep_side = Side(style="thin", color=SEP_COLOR)
border_session = Border(top=sep_side)
no_border = Border()

# ------------------------------------------------------------------ structure
# Monthly sheet columns (A..M). A=SESSION (per-month number, merged per date).
# Notes column reads better left-aligned. Volume holds a formula, not a number.
MONTHLY_HEADERS = [
    "SESSION", "Date", "#", "Exercise", "Set", "Reps", "kg", "Volume", "Notes",
    "Distance (km)", "Duration (min)", "Pace (min/km)", "Avg HR",
]
MONTHLY_WIDTHS = {
    "A": 8,  "B": 12, "C": 5,  "D": 28, "E": 5,  "F": 6, "G": 6,
    "H": 9,  "I": 24, "J": 13, "K": 14, "L": 13, "M": 9,
}
MONTHLY_LEFT_COLS = {"I"}
MONTHLY_COLS = 13
TOTAL_LABEL = "TOTAL"

# Exercises Database: 5 columns (Exercise | Type | Primary Muscle | Equipment | Variations).
DB_WIDTHS = {"A": 30, "B": 13, "C": 16, "D": 14, "E": 48}
DB_COLS = 5

# Bodyweight sheet: 3 columns (Date | Kg | Notes). Morning / empty-stomach
# weigh-ins. Sorted DESC (newest at the top). Notes left-aligned; Date/Kg
# centered.
BODYWEIGHT_WIDTHS = {"A": 12, "B": 7, "C": 40}
BODYWEIGHT_LEFT_COLS = {"C"}
BODYWEIGHT_COLS = 3
BODYWEIGHT_HEADERS = ["Date", "Kg", "Notes"]

# Health Metrics sheet: 15 columns of daily aggregates from Apple Health.
# Sorted DESC. Sparse-merge upserts: an incoming None never overwrites an
# existing non-null value. Notes column is the only manual-input column;
# the importer never touches it.
HEALTH_METRICS_SHEET_NAME = "Health Metrics"
HEALTH_METRICS_HEADERS = [
    "Date", "Bodyweight (kg)", "VO2max", "Resting HR", "HRV SDNN",
    "Walking HR", "HR Recovery 1min", "Sleep Total", "Sleep Deep",
    "Sleep REM", "Resp Rate", "Wrist Temp", "Sleep Breath Dist",
    "Exercise Min", "Notes",
]
HEALTH_METRICS_WIDTHS = {
    "A": 12, "B": 14, "C": 9, "D": 11, "E": 10,
    "F": 11, "G": 16, "H": 11, "I": 11,
    "J": 11, "K": 11, "L": 11, "M": 17,
    "N": 13, "O": 30,
}
HEALTH_METRICS_LEFT_COLS = {"O"}
HEALTH_METRICS_COLS = 15

# Workout Sessions sheet: 12 columns, one row per Apple Workout record.
# Dedupe key is (Date, Start). Sorted DESC by date then start time.
WORKOUT_SESSIONS_SHEET_NAME = "Workout Sessions"
WORKOUT_SESSIONS_HEADERS = [
    "Date", "Start", "End", "Apple Type", "Duration (min)",
    "Avg HR (bpm)", "Max HR (bpm)", "Min HR (bpm)",
    "Active Cal (kcal)", "Distance (km)", "Source", "Notes",
]
WORKOUT_SESSIONS_WIDTHS = {
    "A": 12, "B": 7, "C": 7, "D": 22, "E": 14,
    "F": 13, "G": 13, "H": 13,
    "I": 17, "J": 13, "K": 18, "L": 28,
}
WORKOUT_SESSIONS_LEFT_COLS = {"D", "K", "L"}
WORKOUT_SESSIONS_COLS = 12


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
def _to_num(v):
    """Coerce to float for strength-session detection. Blank/None → 0."""
    if v in (None, ""):
        return 0.0
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def date_str(v):
    """Coerce a Date cell value to a canonical ``YYYY-MM-DD`` string.

    Contract:
    - ``None`` or ``""`` → ``None``
    - ``datetime`` / ``date`` → ``"YYYY-MM-DD"``
    - anything else → ``str(v).strip()[:10]`` (covers bare strings, the
      ``"2026-04-20 00:00:00"`` form Excel sometimes emits, and stray
      non-string values).

    Legacy rows imported via Numbers/Excel autoformat can land as
    ``datetime`` objects; mixing types breaks any comparison (sort,
    dict-key merge, equality-based session grouping). Callers coerce
    unconditionally and rely on the ``None`` sentinel for empty cells.
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()[:10]


def bw_locate_date(row):
    """Find the date in a Bodyweight row, return ``(date, date_idx)``.

    The current 3-col layout is ``Date | Kg | Notes`` (date at index 0); the
    legacy 4-col layout kept ``Year | Date | Kg | Notes`` (date at index 1).
    Scanning both positions lets callers read either cleanly.

    Returns ``(None, None)`` if no date-shaped value is found. ``Kg`` is at
    ``date_idx + 1`` and ``Notes`` at ``date_idx + 2`` in both layouts.
    """
    for i, v in enumerate(row[:2]):
        s = date_str(v)
        if s and len(s) == 10 and s[4] == "-" and s[7] == "-":
            return s, i
    return None, None


def _numeric_cell(v):
    """Coerce stringified numbers (incl. European comma decimals like ``"67,5"``)
    to int or float. Returns the original value for anything that isn't purely
    numeric — MM:SS durations, blank cells, text notes — so callers can apply
    this indiscriminately to numeric columns without destroying non-numeric
    entries that happen to share a column historically.

    Excel requires real numbers in cells consumed by arithmetic formulas;
    ``=F*G`` on text returns #VALUE! (see the 2026-04-06 regression where
    legacy data imported kg as string ``"67,5"``). Normalising here keeps the
    sheet arithmetic-safe regardless of how the value was originally logged.
    """
    if v in (None, ""):
        return v
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if not s:
        return v
    try:
        f = float(s.replace(",", "."))
    except ValueError:
        return v
    return int(f) if f.is_integer() else f


def style_monthly_sheet(ws):
    """Apply canonical styling to a YYYY.MM workout log sheet.

    Idempotent. Running twice in a row is a no-op. Responsibilities:

    - Migrate legacy 12-col layout (A="Date") to the 13-col layout by
      inserting a leftmost SESSION column.
    - Normalise Date cells to ``YYYY-MM-DD`` strings (legacy datetime cells
      are coerced), then sort sessions by date ascending and merge any
      same-date sessions that became non-contiguous on disk — e.g. after a
      backfill row got appended at the bottom instead of into its day's
      block.
    - Rebuild SESSION column: per-month session numbers (1..N, chronological
      after the sort), merged vertically across each session's rows.
    - Rebuild TOTAL row at the end of each strength session with
      ``=SUM(H{first}:H{last})`` in the Volume column. Cardio-only sessions
      (every row has kg=0 and reps=0) get no TOTAL row.
    - Rewrite the Volume column on every set row as ``=F{r}*G{r}``
      (reps × kg) — the old hard-coded numeric volumes are discarded.
    - Apply header/data/TOTAL fills, fonts, widths, freeze pane.

    The data-row region is cleared and rebuilt from parsed rows so merges,
    TOTAL row placement, and session numbering can't drift out of sync with
    the data.
    """
    # ---- Migration: legacy layout had A="Date". Shift everything one col right.
    if ws.cell(row=1, column=1).value == "Date":
        ws.insert_cols(1)

    # ---- Unmerge any existing ranges so we can re-apply cleanly.
    for mr in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(mr))

    # ---- Pass 1: read all data rows into memory, grouped by contiguous date.
    last_r, _ = find_last_data_cell(ws)
    sessions: list[dict] = []
    current: dict | None = None
    for r in range(2, max(last_r, 1) + 1):
        date_val = date_str(ws.cell(row=r, column=2).value)
        ex_val = ws.cell(row=r, column=4).value

        # Drop pre-existing TOTAL rows; we'll rebuild them.
        if ex_val == TOTAL_LABEL:
            continue
        # Drop fully-empty rows.
        if date_val in (None, "") and ex_val in (None, ""):
            continue

        row_data = {
            "date":      date_val,
            "num":       ws.cell(row=r, column=3).value,
            "exercise":  ex_val,
            "set":       ws.cell(row=r, column=5).value,
            "reps":      ws.cell(row=r, column=6).value,
            "kg":        ws.cell(row=r, column=7).value,
            "notes":     ws.cell(row=r, column=9).value,
            "distance":  ws.cell(row=r, column=10).value,
            "duration":  ws.cell(row=r, column=11).value,
            "pace":      ws.cell(row=r, column=12).value,
            "avg_hr":    ws.cell(row=r, column=13).value,
        }

        if current is None or date_val != current["date"]:
            current = {"date": date_val, "rows": []}
            sessions.append(current)
        current["rows"].append(row_data)

    # ---- Sort sessions by date ascending and merge any that share a date.
    # A shared-date pair happens when a backfill row (earlier than existing
    # data) got appended to the end of the sheet and is no longer contiguous
    # with that date's original block. Without this, backfilled workouts end
    # up stranded at the bottom and SESSION numbers drift out of chronological
    # order.
    merged: dict = {}
    for sess in sessions:
        date = sess["date"]
        merged.setdefault(date, {"date": date, "rows": []})["rows"].extend(sess["rows"])
    sessions = sorted(
        merged.values(),
        key=lambda s: (s["date"] is None, s["date"] or ""),
    )

    # ---- Clear data area.
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)

    # ---- Pass 2: write header + data back with SESSION numbers, merges,
    # Volume formulas, TOTAL rows.
    for c, label in enumerate(MONTHLY_HEADERS, 1):
        ws.cell(row=1, column=c, value=label)

    write_row = 2
    for session_num, sess in enumerate(sessions, start=1):
        first_row = write_row

        # Strength session if any row contributes non-zero kg*reps volume.
        is_strength = any(
            _to_num(r["kg"]) * _to_num(r["reps"]) > 0 for r in sess["rows"]
        )

        for rd in sess["rows"]:
            ws.cell(row=write_row, column=1, value=session_num)
            ws.cell(row=write_row, column=2, value=rd["date"])
            ws.cell(row=write_row, column=3, value=_numeric_cell(rd["num"]))
            ws.cell(row=write_row, column=4, value=rd["exercise"])
            ws.cell(row=write_row, column=5, value=_numeric_cell(rd["set"]))
            ws.cell(row=write_row, column=6, value=_numeric_cell(rd["reps"]))
            ws.cell(row=write_row, column=7, value=_numeric_cell(rd["kg"]))
            ws.cell(row=write_row, column=8, value=f"=F{write_row}*G{write_row}")
            ws.cell(row=write_row, column=9, value=rd["notes"])
            ws.cell(row=write_row, column=10, value=_numeric_cell(rd["distance"]))
            ws.cell(row=write_row, column=11, value=rd["duration"])
            ws.cell(row=write_row, column=12, value=rd["pace"])
            ws.cell(row=write_row, column=13, value=_numeric_cell(rd["avg_hr"]))
            write_row += 1
        last_set_row = write_row - 1

        if is_strength:
            ws.cell(row=write_row, column=1, value=session_num)
            ws.cell(row=write_row, column=4, value=TOTAL_LABEL)
            ws.cell(row=write_row, column=8, value=f"=SUM(H{first_row}:H{last_set_row})")
            merge_last = write_row
            write_row += 1
        else:
            merge_last = last_set_row

        if merge_last > first_row:
            ws.merge_cells(
                start_row=first_row, end_row=merge_last,
                start_column=1, end_column=1,
            )

    last_written = write_row - 1

    # ---- Styling: header.
    for c in range(1, MONTHLY_COLS + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = no_border

    # ---- Styling: data rows + TOTAL rows. Skip merged follower cells —
    # openpyxl MergedCell objects don't accept style writes.
    for r in range(2, last_written + 1):
        is_total = ws.cell(row=r, column=4).value == TOTAL_LABEL
        for c in range(1, MONTHLY_COLS + 1):
            cell = ws.cell(row=r, column=c)
            if cell.__class__.__name__ == "MergedCell":
                continue
            cell.font = font_total if is_total else font_data
            cell.fill = fill_total if is_total else fill_data
            col = get_column_letter(c)
            cell.alignment = align_left if col in MONTHLY_LEFT_COLS else align_center
            cell.border = no_border

    # ---- Column widths + freeze pane.
    for col, w in MONTHLY_WIDTHS.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


def style_bodyweight_sheet(ws):
    """Apply canonical styling to the Bodyweight sheet.

    Layout: Date | Kg | Notes. Data sorted DESC (newest on top) by
    ``append_workout.upsert_bodyweight`` (the single writer). Idempotent.

    Migrates the legacy 4-col layout (Year | Date | Kg | Notes) by dropping
    the leading Year column — Year was derivable from Date and added noise.
    """
    # Unmerge any existing merges (including legacy year merges) before edits.
    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))

    # Migration: legacy layout had column A = "Year". Drop it.
    if ws.cell(row=1, column=1).value == "Year":
        ws.delete_cols(1)

    # Trim any stale column beyond the new layout (e.g. leftover col D="Notes"
    # after the Year delete shifts Notes to col C).
    if ws.max_column > BODYWEIGHT_COLS:
        ws.delete_cols(BODYWEIGHT_COLS + 1, ws.max_column - BODYWEIGHT_COLS)

    # Header row
    for c, label in enumerate(BODYWEIGHT_HEADERS, 1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = no_border

    # Data rows: style every cell.
    last_data_row, _ = find_last_data_cell(ws)
    for r in range(2, last_data_row + 1):
        for c in range(1, BODYWEIGHT_COLS + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = font_data
            cell.fill = fill_data
            col = get_column_letter(c)
            cell.alignment = align_left if col in BODYWEIGHT_LEFT_COLS else align_center
            cell.border = no_border

    # Column widths + freeze pane
    for col, w in BODYWEIGHT_WIDTHS.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


def hm_locate_date(row):
    """Find the date in a Health Metrics row, return ``(date, date_idx)``.

    Layout is fixed (Date in column A), but follow the bodyweight pattern of
    scanning the leading cells defensively in case a future migration shifts
    the column. Returns ``(None, None)`` if no date-shaped value is found.
    """
    for i, v in enumerate(row[:1]):
        s = date_str(v)
        if s and len(s) == 10 and s[4] == "-" and s[7] == "-":
            return s, i
    return None, None


def style_health_metrics_sheet(ws):
    """Apply canonical styling to the Health Metrics sheet. Idempotent.

    Layout: 15 columns, Date in col A, Notes in col O (left-aligned). Data
    sorted DESC by ``upsert_health_metrics`` (the single writer). This
    function only enforces header + data styling, widths, and freeze pane;
    it does not reorder rows.
    """
    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))

    # Trim any stray columns beyond the canonical layout.
    if ws.max_column > HEALTH_METRICS_COLS:
        ws.delete_cols(HEALTH_METRICS_COLS + 1, ws.max_column - HEALTH_METRICS_COLS)

    for c, label in enumerate(HEALTH_METRICS_HEADERS, 1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = no_border

    last_data_row, _ = find_last_data_cell(ws)
    for r in range(2, last_data_row + 1):
        for c in range(1, HEALTH_METRICS_COLS + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = font_data
            cell.fill = fill_data
            col = get_column_letter(c)
            cell.alignment = align_left if col in HEALTH_METRICS_LEFT_COLS else align_center
            cell.border = no_border

    for col, w in HEALTH_METRICS_WIDTHS.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


def ws_locate_date_start(row):
    """Find the (date, start) dedupe key in a Workout Sessions row.

    Layout: Date in col A, Start (HH:MM string) in col B. Returns
    ``(date, start)`` strings or ``(None, None)`` if either is missing.
    """
    if not row:
        return None, None
    d = date_str(row[0]) if row[0] is not None else None
    s = row[1] if len(row) > 1 else None
    s = str(s).strip() if s not in (None, "") else None
    if d is None or s is None:
        return None, None
    return d, s


def style_workout_sessions_sheet(ws):
    """Apply canonical styling to the Workout Sessions sheet. Idempotent.

    Layout: 12 columns, Date / Start / End / Apple Type / Duration / HR /
    Calories / Distance / Source / Notes. Type, Source, and Notes are
    left-aligned; everything else centered. Data sorted DESC by
    ``upsert_workout_sessions`` (the single writer).
    """
    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))

    if ws.max_column > WORKOUT_SESSIONS_COLS:
        ws.delete_cols(WORKOUT_SESSIONS_COLS + 1, ws.max_column - WORKOUT_SESSIONS_COLS)

    for c, label in enumerate(WORKOUT_SESSIONS_HEADERS, 1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = no_border

    last_data_row, _ = find_last_data_cell(ws)
    for r in range(2, last_data_row + 1):
        for c in range(1, WORKOUT_SESSIONS_COLS + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = font_data
            cell.fill = fill_data
            col = get_column_letter(c)
            cell.alignment = align_left if col in WORKOUT_SESSIONS_LEFT_COLS else align_center
            cell.border = no_border

    for col, w in WORKOUT_SESSIONS_WIDTHS.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


def ensure_health_metrics_sheet(wb):
    if HEALTH_METRICS_SHEET_NAME in wb.sheetnames:
        return wb[HEALTH_METRICS_SHEET_NAME], False
    ws = wb.create_sheet(title=HEALTH_METRICS_SHEET_NAME)
    for col, header in enumerate(HEALTH_METRICS_HEADERS, start=1):
        ws.cell(row=1, column=col, value=header)
    return ws, True


def ensure_workout_sessions_sheet(wb):
    if WORKOUT_SESSIONS_SHEET_NAME in wb.sheetnames:
        return wb[WORKOUT_SESSIONS_SHEET_NAME], False
    ws = wb.create_sheet(title=WORKOUT_SESSIONS_SHEET_NAME)
    for col, header in enumerate(WORKOUT_SESSIONS_HEADERS, start=1):
        ws.cell(row=1, column=col, value=header)
    return ws, True


# Order of metric fields in HEALTH_METRICS_HEADERS, by sheet column index.
# Used by upsert_health_metrics to map dict keys → cells. The `notes` slot
# is intentionally absent: incoming entries never carry notes, and the
# Notes column is reserved for manual annotations.
HEALTH_METRICS_FIELDS = [
    "bodyweight_kg", "vo2max", "resting_hr", "hrv_sdnn",
    "walking_hr", "hr_recovery_1min", "sleep_total_h", "sleep_deep_h",
    "sleep_rem_h", "resp_rate", "wrist_temp_c", "sleep_breath_dist",
    "exercise_min",
]


def upsert_health_metrics(wb, entries):
    """Sparse-merge per-date Health Metrics rows into the workbook.

    ``entries`` is a list of dicts. Each must have ``date`` (YYYY-MM-DD)
    and any subset of the keys in ``HEALTH_METRICS_FIELDS``. Missing or
    None values are treated as "no data this run" — they NEVER overwrite
    an existing non-null cell. The Notes column (col O) is preserved
    untouched on every upsert.

    Returns a list of one summary string for the importer to print.
    """
    if not entries:
        return [f"{HEALTH_METRICS_SHEET_NAME}: 0 dates written / 0 updated"]
    ws, created = ensure_health_metrics_sheet(wb)

    # Read existing rows: keep the full per-field dict + the Notes cell so
    # we can faithfully rewrite the sheet without dropping manual notes.
    existing: dict[str, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row:
            continue
        d, _ = hm_locate_date(row)
        if d is None:
            continue
        record = {}
        for i, key in enumerate(HEALTH_METRICS_FIELDS, start=1):
            v = row[i] if len(row) > i else None
            record[key] = v
        notes = row[HEALTH_METRICS_COLS - 1] if len(row) >= HEALTH_METRICS_COLS else None
        record["__notes"] = notes
        existing[d] = record

    written = 0  # new dates
    updated = 0  # existing dates whose values changed
    seen_dates: set[str] = set()
    for e in entries:
        d = str(e.get("date") or "")[:10]
        if not d or len(d) != 10:
            continue
        seen_dates.add(d)
        cur = existing.get(d)
        if cur is None:
            new_record = {"__notes": None}
            for key in HEALTH_METRICS_FIELDS:
                v = e.get(key)
                new_record[key] = v if v is not None else None
            existing[d] = new_record
            written += 1
            continue

        # Sparse-merge: incoming None never erases existing values; non-null
        # incoming overwrites only when the value differs.
        changed = False
        for key in HEALTH_METRICS_FIELDS:
            v = e.get(key)
            if v is None:
                continue
            if cur.get(key) != v:
                cur[key] = v
                changed = True
        if changed:
            updated += 1

    # Rewrite sheet body in DESC date order.
    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    for i, d in enumerate(sorted(existing.keys(), reverse=True), start=2):
        rec = existing[d]
        ws.cell(row=i, column=1, value=d)
        for col_idx, key in enumerate(HEALTH_METRICS_FIELDS, start=2):
            ws.cell(row=i, column=col_idx, value=rec.get(key))
        ws.cell(row=i, column=HEALTH_METRICS_COLS, value=rec.get("__notes"))

    style_health_metrics_sheet(ws)

    if seen_dates:
        date_range = f"{min(seen_dates)} → {max(seen_dates)}"
    else:
        date_range = "no rows"
    tag = " (new sheet)" if created else ""
    return [f"{HEALTH_METRICS_SHEET_NAME}{tag}: {written} dates written / {updated} updated (range {date_range})"]


def upsert_workout_sessions(wb, entries):
    """Insert or overwrite Workout Sessions rows by (date, start) dedupe key.

    ``entries`` is a list of dicts with keys: ``date``, ``start``, ``end``,
    ``apple_type``, ``duration_min``, ``avg_hr``, ``max_hr``, ``min_hr``,
    ``active_cal``, ``distance_km``, ``source``, ``notes``. Re-running with
    the same export is a no-op (same dedupe key → same payload). Sorts DESC
    by (date, start) on every write.

    Returns a list of one summary string for the importer to print.
    """
    if not entries:
        return [f"{WORKOUT_SESSIONS_SHEET_NAME}: 0 sessions written / 0 updated"]
    ws, created = ensure_workout_sessions_sheet(wb)

    existing: dict[tuple, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        d, s = ws_locate_date_start(row)
        if d is None:
            continue
        existing[(d, s)] = {
            "date": d, "start": s,
            "end":          row[2]  if len(row) > 2  else None,
            "apple_type":   row[3]  if len(row) > 3  else None,
            "duration_min": row[4]  if len(row) > 4  else None,
            "avg_hr":       row[5]  if len(row) > 5  else None,
            "max_hr":       row[6]  if len(row) > 6  else None,
            "min_hr":       row[7]  if len(row) > 7  else None,
            "active_cal":   row[8]  if len(row) > 8  else None,
            "distance_km":  row[9]  if len(row) > 9  else None,
            "source":       row[10] if len(row) > 10 else None,
            "notes":        row[11] if len(row) > 11 else None,
        }

    written = 0
    updated = 0
    incidental = 0
    for e in entries:
        d = str(e.get("date") or "")[:10]
        s = e.get("start")
        if not d or s is None:
            continue
        key = (d, str(s))
        new_rec = {
            "date": d, "start": str(s),
            "end":          e.get("end"),
            "apple_type":   e.get("apple_type"),
            "duration_min": e.get("duration_min"),
            "avg_hr":       e.get("avg_hr"),
            "max_hr":       e.get("max_hr"),
            "min_hr":       e.get("min_hr"),
            "active_cal":   e.get("active_cal"),
            "distance_km":  e.get("distance_km"),
            "source":       e.get("source"),
            "notes":        e.get("notes"),
        }
        if (e.get("notes") or "").lower().startswith("incidental"):
            incidental += 1
        if key in existing:
            if existing[key] != new_rec:
                existing[key] = new_rec
                updated += 1
            # Same payload → silent no-op (idempotency path).
        else:
            existing[key] = new_rec
            written += 1

    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    sorted_keys = sorted(existing.keys(), reverse=True)
    for i, key in enumerate(sorted_keys, start=2):
        rec = existing[key]
        ws.cell(row=i, column=1,  value=rec["date"])
        ws.cell(row=i, column=2,  value=rec["start"])
        ws.cell(row=i, column=3,  value=rec["end"])
        ws.cell(row=i, column=4,  value=rec["apple_type"])
        ws.cell(row=i, column=5,  value=rec["duration_min"])
        ws.cell(row=i, column=6,  value=rec["avg_hr"])
        ws.cell(row=i, column=7,  value=rec["max_hr"])
        ws.cell(row=i, column=8,  value=rec["min_hr"])
        ws.cell(row=i, column=9,  value=rec["active_cal"])
        ws.cell(row=i, column=10, value=rec["distance_km"])
        ws.cell(row=i, column=11, value=rec["source"])
        ws.cell(row=i, column=12, value=rec["notes"])

    style_workout_sessions_sheet(ws)

    tag = " (new sheet)" if created else ""
    return [
        f"{WORKOUT_SESSIONS_SHEET_NAME}{tag}: {written} sessions written / "
        f"{updated} updated ({incidental} walks flagged incidental)"
    ]


# ============================================================ Profile sheet
# Per-person source profile. Two cells the importers and coach actually read
# (``source``, ``auto_cardio``); ``notes`` is free text. Hidden by default
# is a v2 nice-to-have — for now the sheet ships visible so the user can see
# and override directly.
PROFILE_SHEET_NAME = "Profile"
PROFILE_HEADERS = ["Key", "Value"]
PROFILE_WIDTHS = {"A": 14, "B": 40}
PROFILE_LEFT_COLS = {"B"}

# Every key the profile sheet recognises. Listed in the order they should
# appear on disk. Adding a new key here + giving it a default in
# ``ensure_profile_sheet`` is the whole change required to ship a new
# capability flag.
PROFILE_KEYS = ("source", "auto_cardio", "notes")

# Default values applied when ``ensure_profile_sheet`` creates the sheet
# from scratch. ``source`` left None so the caller can inject ``xml`` or
# ``hl_export`` based on the file extension that triggered the import.
PROFILE_DEFAULTS = {
    "source":      None,
    "auto_cardio": False,
    "notes":       None,
}


def _coerce_bool(v):
    """Permissive bool coercion for cells that may have been edited by hand.

    Accepts: True/False, ``1``/``0``, ``"true"``/``"false"``, ``"yes"``/``"no"``,
    ``"y"``/``"n"`` (case-insensitive). Falls back to ``None`` for anything
    unrecognised so the caller can re-apply the default rather than treating
    a typo as ``False``.
    """
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "yes", "y", "1", "on"):
        return True
    if s in ("false", "no", "n", "0", "off"):
        return False
    return None


def read_profile(wb) -> dict:
    """Return ``{source, auto_cardio, notes}`` from the Profile sheet.

    Missing sheet → all defaults. Missing or unrecognised cell value →
    that key's default. ``source`` stays ``None`` if the sheet was never
    initialised — callers should treat that as "not yet configured" and
    inject the inferred source (xml vs hl_export) based on what they've
    been handed.
    """
    out = dict(PROFILE_DEFAULTS)
    if PROFILE_SHEET_NAME not in wb.sheetnames:
        return out
    ws = wb[PROFILE_SHEET_NAME]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row:
            continue
        key = row[0]
        val = row[1] if len(row) > 1 else None
        if key is None:
            continue
        k = str(key).strip().lower()
        if k == "source":
            if val is None or val == "":
                continue
            s = str(val).strip().lower()
            if s in ("xml", "hl_export"):
                out["source"] = s
        elif k == "auto_cardio":
            b = _coerce_bool(val)
            if b is not None:
                out["auto_cardio"] = b
        elif k == "notes":
            out["notes"] = str(val).strip() if val not in (None, "") else None
    return out


def style_profile_sheet(ws):
    """Apply canonical styling to the Profile sheet. Idempotent.

    Two-column key/value layout. Header row, then one row per known key.
    Re-running this function reasserts header cells, widths, and freeze
    pane without disturbing the values.
    """
    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))

    if ws.max_column > 2:
        ws.delete_cols(3, ws.max_column - 2)

    for c, label in enumerate(PROFILE_HEADERS, 1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = no_border

    last_data_row, _ = find_last_data_cell(ws)
    for r in range(2, last_data_row + 1):
        for c in range(1, 3):
            cell = ws.cell(row=r, column=c)
            cell.font = font_data
            cell.fill = fill_data
            col = get_column_letter(c)
            cell.alignment = align_left if col in PROFILE_LEFT_COLS else align_center
            cell.border = no_border

    for col, w in PROFILE_WIDTHS.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


def ensure_profile_sheet(wb, default_source: str | None = None,
                         default_auto_cardio: bool | None = None) -> tuple:
    """Create the Profile sheet if missing, otherwise leave existing values alone.

    Returns ``(ws, created)``. When created, populates rows for every key in
    ``PROFILE_KEYS`` using ``PROFILE_DEFAULTS``, with ``default_source`` and
    ``default_auto_cardio`` overriding the dict defaults — the importer passes
    ``"xml"`` / ``"hl_export"`` based on the file extension it dispatched, and
    ``True`` / ``False`` for the matching auto-cardio default (Nihad opts in,
    Fabian opts out initially per the plan).

    Existing sheets are not migrated — if the layout drifted, ``style_profile_sheet``
    enforces the styling, but cell values stay untouched. Callers update via
    ``write_profile`` for explicit edits.
    """
    if PROFILE_SHEET_NAME in wb.sheetnames:
        return wb[PROFILE_SHEET_NAME], False

    ws = wb.create_sheet(title=PROFILE_SHEET_NAME)
    for c, label in enumerate(PROFILE_HEADERS, start=1):
        ws.cell(row=1, column=c, value=label)

    seeded = dict(PROFILE_DEFAULTS)
    if default_source is not None:
        seeded["source"] = default_source
    if default_auto_cardio is not None:
        seeded["auto_cardio"] = default_auto_cardio

    for r, key in enumerate(PROFILE_KEYS, start=2):
        ws.cell(row=r, column=1, value=key)
        v = seeded.get(key)
        if isinstance(v, bool):
            ws.cell(row=r, column=2, value="true" if v else "false")
        else:
            ws.cell(row=r, column=2, value=v)

    style_profile_sheet(ws)
    return ws, True


def write_profile(wb, **updates) -> None:
    """Update one or more Profile keys in place.

    Creates the sheet if missing (with no defaults — caller is doing an
    explicit set, not a bootstrap). Unknown keys are ignored. Boolean
    values are stored as the lowercase strings ``"true"`` / ``"false"``
    so a user opening the sheet sees something readable; ``read_profile``
    coerces back to bool on the way in.
    """
    if PROFILE_SHEET_NAME not in wb.sheetnames:
        ws, _ = ensure_profile_sheet(wb)
    else:
        ws = wb[PROFILE_SHEET_NAME]

    # Build map of existing key → row.
    existing: dict[str, int] = {}
    for r in range(2, ws.max_row + 1):
        k = ws.cell(row=r, column=1).value
        if k is None:
            continue
        existing[str(k).strip().lower()] = r

    for key, value in updates.items():
        k = key.strip().lower()
        if k not in PROFILE_KEYS:
            continue
        if isinstance(value, bool):
            cell_val = "true" if value else "false"
        else:
            cell_val = value
        if k in existing:
            ws.cell(row=existing[k], column=2, value=cell_val)
        else:
            new_row = ws.max_row + 1
            ws.cell(row=new_row, column=1, value=k)
            ws.cell(row=new_row, column=2, value=cell_val)

    style_profile_sheet(ws)


# ================================================== Auto-cardio: monthly append
def _format_pace_min_per_km(duration_min: float | None,
                            distance_km: float | None) -> str | None:
    """Return a ``MM:SS`` per-km pace string, or None if not computable.

    Mirrors the manual-log pace format. We only emit a pace when both
    distance and duration are positive — bare-duration cardio (HIIT,
    swim laps without distance) leaves the cell blank.
    """
    if not duration_min or not distance_km:
        return None
    if duration_min <= 0 or distance_km <= 0:
        return None
    pace_min = duration_min / distance_km
    whole = int(pace_min)
    secs = int(round((pace_min - whole) * 60))
    if secs == 60:
        whole += 1
        secs = 0
    return f"{whole}:{secs:02d}"


# Tolerance used when matching an Apple workout to an existing manual cardio
# row on the same date + exercise. Apple sometimes records 28.0 min for what
# the user logged as 30 min; ±1 min absorbs the rounding without merging
# genuinely different sessions (a manual 25-min run and an Apple 35-min run
# on the same day are different workouts).
CARDIO_DUPLICATE_DURATION_TOLERANCE_MIN = 1.0

AUTO_IMPORT_NOTE = "auto-imported from Apple"


def _parse_duration_minutes(v):
    """Coerce a Duration-column value to float minutes.

    Manual logs use MM:SS strings (``"60:33"`` for one hour and 33s).
    Auto-imports use floats (``60.6``). Any other shape returns None so the
    caller's dedupe falls back to a date+exercise match (manual-wins).
    """
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")
        try:
            mm = int(parts[0])
            ss = int(parts[1]) if len(parts) > 1 else 0
            return mm + ss / 60.0
        except ValueError:
            return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def upsert_monthly_cardio(wb, rows: list[dict]) -> list[str]:
    """Append cardio rows to ``YYYY.MM`` sheets with dedupe + restyle.

    ``rows`` is a list of dicts with keys:

      ``date`` (YYYY-MM-DD), ``exercise`` (canonical name from
      ``apple_workout_types.APPLE_TO_TRACKER_EXERCISE``),
      ``duration_min``, ``distance_km``, ``avg_hr``.

    For each row:

    - The target sheet is the ``YYYY.MM`` matching the row's date. Created
      with the canonical 13-col header if missing.
    - Dedupe rule: skip if the sheet already has a row matching ALL of:
      same date, same exercise (case-insensitive), and duration within
      ±1.0 min. Manual entries (no ``auto-imported from Apple`` note) win
      — never overwritten. A previously auto-imported row with the same
      key is also a no-op (idempotency).
    - Otherwise the new row is appended at the bottom; the styler
      (called once per touched sheet at the end) sorts and rewrites it
      into chronological order, populates ``SESSION``, and writes the
      ``=F*G`` Volume formula. The note column carries
      ``"auto-imported from Apple"`` so the manual-wins rule can find it.

    Returns one summary string per touched sheet, plus a roll-up. Empty
    input returns a no-op summary.
    """
    if not rows:
        return ["Auto-cardio: 0 rows considered"]

    # Bucket incoming rows by ``YYYY.MM`` once so we touch each sheet exactly
    # once (read existing → append new → restyle), regardless of how rows
    # were ordered.
    by_month: dict[str, list[dict]] = {}
    for r in rows:
        d = str(r.get("date") or "")[:10]
        if not d or len(d) != 10:
            continue
        key = f"{d[:4]}.{d[5:7]}"
        by_month.setdefault(key, []).append(r)

    if not by_month:
        return ["Auto-cardio: 0 rows considered (no valid dates)"]

    summaries: list[str] = []
    total_appended = 0
    total_skipped = 0

    for month_key in sorted(by_month.keys()):
        month_rows = by_month[month_key]
        if month_key in wb.sheetnames:
            ws = wb[month_key]
            sheet_created = False
        else:
            ws = wb.create_sheet(title=month_key)
            for c, label in enumerate(MONTHLY_HEADERS, 1):
                ws.cell(row=1, column=c, value=label)
            sheet_created = True

        # Snapshot existing rows for dedupe lookup. Index by
        # (date, lowercased exercise) → list of (duration_min, is_auto)
        # so the manual-wins rule has every match available.
        existing_index: dict[tuple, list[tuple]] = {}
        last_r, _ = find_last_data_cell(ws)
        for r in range(2, last_r + 1):
            date_v = date_str(ws.cell(row=r, column=2).value)
            ex_v = ws.cell(row=r, column=4).value
            if not date_v or not ex_v:
                continue
            ex_str = str(ex_v).strip()
            if not ex_str or ex_str.upper() == TOTAL_LABEL:
                continue
            dur_f = _parse_duration_minutes(ws.cell(row=r, column=11).value)
            notes_v = ws.cell(row=r, column=9).value
            is_auto = AUTO_IMPORT_NOTE in str(notes_v or "").lower()
            key = (date_v, ex_str.lower())
            existing_index.setdefault(key, []).append((dur_f, is_auto))

        appended = 0
        skipped_dup = 0

        # Determine where to start writing — append after the last data row
        # the styler will sort+merge afterwards anyway. But if the sheet
        # contains TOTAL rows or merged SESSION cells, ``ws.max_row`` is the
        # safer bottom anchor.
        write_row = max(ws.max_row + 1, 2)

        for r in month_rows:
            d = str(r.get("date") or "")[:10]
            ex = r.get("exercise")
            if not d or not ex:
                continue
            ex_lower = ex.strip().lower()
            dur = r.get("duration_min")
            try:
                dur_f = float(dur) if dur is not None else None
            except (TypeError, ValueError):
                dur_f = None

            # Dedupe rule:
            #   - Any existing MANUAL row on the same date + exercise wins
            #     unconditionally — Apple frequently splits a single workout
            #     into multiple short segments (a 0.6-min preamble + the
            #     main 159-min session, both tagged Hiking), and the user
            #     only logged the workout once. Manual-wins is the right
            #     behavior here even though it discards the auxiliary
            #     segments.
            #   - Otherwise: an existing AUTO row with the same date +
            #     exercise + duration (±1 min tolerance) is the
            #     idempotency path. Re-imports of the same export must
            #     produce zero appends.
            matches = existing_index.get((d, ex_lower), [])
            has_manual_match = any(not is_auto for _dur, is_auto in matches)
            has_auto_dup = False
            if not has_manual_match:
                for existing_dur, is_auto in matches:
                    if not is_auto:
                        continue
                    if existing_dur is None or dur_f is None:
                        has_auto_dup = True
                        break
                    if abs(existing_dur - dur_f) <= CARDIO_DUPLICATE_DURATION_TOLERANCE_MIN:
                        has_auto_dup = True
                        break
            if has_manual_match or has_auto_dup:
                skipped_dup += 1
                continue

            distance = r.get("distance_km")
            avg_hr = r.get("avg_hr")
            pace = _format_pace_min_per_km(dur_f, distance)

            ws.cell(row=write_row, column=1, value=None)        # SESSION (styler fills)
            ws.cell(row=write_row, column=2, value=d)
            ws.cell(row=write_row, column=3, value=None)        # # (styler fills)
            ws.cell(row=write_row, column=4, value=ex)
            ws.cell(row=write_row, column=5, value=1)           # Set
            ws.cell(row=write_row, column=6, value=None)        # Reps (cardio: blank)
            ws.cell(row=write_row, column=7, value=None)        # kg
            ws.cell(row=write_row, column=8, value=f"=F{write_row}*G{write_row}")
            ws.cell(row=write_row, column=9, value=AUTO_IMPORT_NOTE)
            ws.cell(row=write_row, column=10, value=_numeric_cell(distance))
            ws.cell(row=write_row, column=11, value=_numeric_cell(dur_f))
            ws.cell(row=write_row, column=12, value=pace)
            ws.cell(row=write_row, column=13, value=_numeric_cell(avg_hr))

            # Track the new row in the dedupe index too so subsequent input
            # rows don't double-add for the same date.
            existing_index.setdefault((d, ex_lower), []).append((dur_f, True))

            write_row += 1
            appended += 1

        if appended:
            style_monthly_sheet(ws)

        total_appended += appended
        total_skipped += skipped_dup
        tag = " (new sheet)" if sheet_created else ""
        summaries.append(
            f"{month_key}{tag}: {appended} cardio rows appended, "
            f"{skipped_dup} skipped (already present)"
        )

    summaries.append(
        f"Auto-cardio total: {total_appended} appended, "
        f"{total_skipped} skipped across {len(by_month)} month(s)"
    )
    return summaries


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
