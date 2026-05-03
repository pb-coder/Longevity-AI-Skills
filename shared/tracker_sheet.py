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
    "Active Cal", "Total Cal", "Elevation (m)", "Elapsed",
]

# Deload marker text — case-sensitive on write (canonical form), but
# substring-matched case-insensitively on read so user-edited variants
# ("deload workout", "DELOAD WORKOUT") still register. Lives on the
# TOTAL row's Notes column for strength sessions.
DELOAD_MARKER_TEXT = "Deload Workout"


def _extract_deload_marker(notes) -> tuple[bool, str | None]:
    """Inspect a Notes cell value and split out the Deload Workout marker.

    Returns ``(deload_present, remaining_notes)``:
    - ``deload_present``: True if ``DELOAD_MARKER_TEXT`` appears (case-insensitive).
    - ``remaining_notes``: the input minus the marker token, with empty
      separator detritus (``"; "``, ``" |"``) tidied. ``None`` if nothing
      meaningful remains.

    Used during the strength-session-metadata-to-TOTAL migration: the
    styler hoists the deload flag to the TOTAL row's Notes while
    preserving any user-written warmup comment on the original row.
    """
    if notes in (None, ""):
        return False, None
    s = str(notes)
    lower = s.lower()
    marker = DELOAD_MARKER_TEXT.lower()
    if marker not in lower:
        return False, s.strip() or None
    # Strip every occurrence + the separator that joined it to user text.
    import re
    pattern = re.compile(re.escape(DELOAD_MARKER_TEXT), re.IGNORECASE)
    cleaned = pattern.sub("", s)
    # Tidy joining separators around the now-removed token.
    cleaned = re.sub(r"\s*;\s*;\s*", "; ", cleaned)
    cleaned = re.sub(r"^\s*[;|,]\s*", "", cleaned)
    cleaned = re.sub(r"\s*[;|,]\s*$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return True, cleaned or None
MONTHLY_WIDTHS = {
    "A": 8,  "B": 12, "C": 5,  "D": 28, "E": 5,  "F": 6, "G": 6,
    "H": 9,  "I": 24, "J": 13, "K": 14, "L": 13, "M": 9,
    "N": 11, "O": 11, "P": 13, "Q": 11,
}
MONTHLY_LEFT_COLS = {"I"}
MONTHLY_COLS = 17
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

# Health Metrics sheet: per-source schema. The XML pipeline supplies the
# full 15-col surface; HLExport can never populate Resting HR / HRV SDNN /
# Walking HR / Sleep Deep / Sleep REM / Wrist Temp / Sleep Breath Dist /
# Exercise Min, so its tracker uses a 7-col slim schema that drops them.
# Sorted DESC. Sparse-merge upserts: an incoming None never overwrites an
# existing non-null value. Notes column is the only manual-input column;
# the importer never touches it.
HEALTH_METRICS_SHEET_NAME = "Health Metrics"

HEALTH_METRICS_HEADERS_BY_SOURCE = {
    "xml": [
        "Date", "Bodyweight (kg)", "VO2max", "Resting HR", "HRV SDNN",
        "Walking HR", "HR Recovery 1min", "Sleep Total", "Sleep Deep",
        "Sleep REM", "Resp Rate", "Wrist Temp", "Sleep Breath Dist",
        "Exercise Min", "Notes",
    ],
    "hl_export": [
        "Date", "Bodyweight (kg)", "VO2max", "HR Recovery 1min",
        "Sleep Total", "Resp Rate", "Notes",
    ],
}

# Field-name list (matches the dict keys from the importers' per-day emit).
# Position N corresponds to column N+1 (Date is col 1, fields[0] is col 2).
# The trailing Notes column is reserved for manual notes and is NOT in
# this list — upsert never touches it.
HEALTH_METRICS_FIELDS_BY_SOURCE = {
    "xml": [
        "bodyweight_kg", "vo2max", "resting_hr", "hrv_sdnn",
        "walking_hr", "hr_recovery_1min", "sleep_total_h", "sleep_deep_h",
        "sleep_rem_h", "resp_rate", "wrist_temp_c", "sleep_breath_dist",
        "exercise_min",
    ],
    "hl_export": [
        "bodyweight_kg", "vo2max", "hr_recovery_1min",
        "sleep_total_h", "resp_rate",
    ],
}

HEALTH_METRICS_WIDTHS_BY_SOURCE = {
    "xml": {
        "A": 12, "B": 14, "C": 9, "D": 11, "E": 10,
        "F": 11, "G": 16, "H": 11, "I": 11,
        "J": 11, "K": 11, "L": 11, "M": 17,
        "N": 13, "O": 30,
    },
    "hl_export": {
        "A": 12, "B": 14, "C": 9, "D": 16, "E": 11, "F": 11, "G": 30,
    },
}

HEALTH_METRICS_LEFT_COLS_BY_SOURCE = {
    "xml":       {"O"},
    "hl_export": {"G"},
}

HEALTH_METRICS_COLS_BY_SOURCE = {
    "xml":       15,
    "hl_export": 7,
}

# Back-compat aliases — callers that still import HEALTH_METRICS_HEADERS / etc.
# get the xml shape, matching today's behaviour for Nihad's tracker.
HEALTH_METRICS_HEADERS   = HEALTH_METRICS_HEADERS_BY_SOURCE["xml"]
HEALTH_METRICS_FIELDS    = HEALTH_METRICS_FIELDS_BY_SOURCE["xml"]
HEALTH_METRICS_WIDTHS    = HEALTH_METRICS_WIDTHS_BY_SOURCE["xml"]
HEALTH_METRICS_LEFT_COLS = HEALTH_METRICS_LEFT_COLS_BY_SOURCE["xml"]
HEALTH_METRICS_COLS      = HEALTH_METRICS_COLS_BY_SOURCE["xml"]

# Workout Sessions sheet: per-source schema. XML carries per-workout
# Avg/Max/Min HR; HL never does, so HL trackers drop those three columns
# (12 → 9). Dedupe key is (Date, Start). Sorted DESC by date then start.
WORKOUT_SESSIONS_SHEET_NAME = "Workout Sessions"

WORKOUT_SESSIONS_HEADERS_BY_SOURCE = {
    "xml": [
        "Date", "Start", "End", "Apple Type", "Duration (min)",
        "Avg HR (bpm)", "Max HR (bpm)", "Min HR (bpm)",
        "Active Cal (kcal)", "Distance (km)", "Source", "Notes",
    ],
    "hl_export": [
        "Date", "Start", "End", "Apple Type", "Duration (min)",
        "Active Cal (kcal)", "Distance (km)", "Source", "Notes",
    ],
}

# Field-name list per source, matching the XML/HL importer payload keys.
# Position N corresponds to column N+1.
WORKOUT_SESSIONS_FIELDS_BY_SOURCE = {
    "xml": [
        "start", "end", "apple_type", "duration_min",
        "avg_hr", "max_hr", "min_hr",
        "active_cal", "distance_km", "source", "notes",
    ],
    "hl_export": [
        "start", "end", "apple_type", "duration_min",
        "active_cal", "distance_km", "source", "notes",
    ],
}

WORKOUT_SESSIONS_WIDTHS_BY_SOURCE = {
    "xml": {
        "A": 12, "B": 7, "C": 7, "D": 22, "E": 14,
        "F": 13, "G": 13, "H": 13,
        "I": 17, "J": 13, "K": 18, "L": 28,
    },
    "hl_export": {
        "A": 12, "B": 7, "C": 7, "D": 22, "E": 14,
        "F": 17, "G": 13, "H": 18, "I": 28,
    },
}

WORKOUT_SESSIONS_LEFT_COLS_BY_SOURCE = {
    "xml":       {"D", "K", "L"},
    "hl_export": {"D", "H", "I"},
}

WORKOUT_SESSIONS_COLS_BY_SOURCE = {
    "xml":       12,
    "hl_export": 9,
}

# Back-compat aliases (xml-shaped).
WORKOUT_SESSIONS_HEADERS   = WORKOUT_SESSIONS_HEADERS_BY_SOURCE["xml"]
WORKOUT_SESSIONS_WIDTHS    = WORKOUT_SESSIONS_WIDTHS_BY_SOURCE["xml"]
WORKOUT_SESSIONS_LEFT_COLS = WORKOUT_SESSIONS_LEFT_COLS_BY_SOURCE["xml"]
WORKOUT_SESSIONS_COLS      = WORKOUT_SESSIONS_COLS_BY_SOURCE["xml"]

# Tombstones removed in 2026-05. The importers are now scoped to the
# current calendar month only — see ``_current_month_key`` plus the
# month-gate in ``upsert_monthly_cardio`` / ``upsert_monthly_strength_session``.
# Past months are never re-scanned, so a deleted row stays deleted
# without needing a separate tombstone record.


def _current_month_key(today_d: date | None = None) -> str:
    """Return ``YYYY.MM`` for the current calendar month.

    Single source of truth for the month-gate that bounds where the
    importers can write. ``today_d`` is overridable for tests; production
    callers leave it ``None`` and ``date.today()`` is used.
    """
    d = today_d or date.today()
    return f"{d.year:04d}.{d.month:02d}"


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


def _classify_session_rows(rows: list[dict]) -> tuple[list[str], bool]:
    """Classify a session's rows by kind, returning ``(kinds, is_strength)``.

    Per-row classification (preserves the convention used across both the
    monthly-sheet styler and downstream readers):
    - ``strength``: ``kg * reps > 0`` (user lifted weight).
    - ``cardio``:   ``distance > 0`` (Run / Cycle / Hike / Swim — has GPS).
    - ``other``:    no kg*reps and no distance (warmup, HIIT, yoga,
      bodyweight squat, etc.).

    ``is_strength`` is true when any row classifies as ``strength`` — used
    by the styler to decide whether to emit a TOTAL row and whether to
    blank session-level metadata cells on non-cardio rows.
    """
    kinds: list[str] = []
    for rd in rows:
        kg_v = _to_num(rd.get("kg"))
        reps_v = _to_num(rd.get("reps"))
        if kg_v * reps_v > 0:
            kinds.append("strength")
            continue
        dist_v = _to_num(rd.get("distance"))
        if dist_v > 0:
            kinds.append("cardio")
            continue
        kinds.append("other")
    return kinds, ("strength" in kinds)


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


# ============================================================ Monthly sheet
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
    # TOTAL rows are not appended to the session's data rows (they get
    # rebuilt) but their metadata + Notes are captured into the session's
    # ``total_meta`` dict — this is the canonical source for session-level
    # metadata after the move from warmup-row.
    last_r, _ = find_last_data_cell(ws)
    sessions: list[dict] = []
    current: dict | None = None
    for r in range(2, max(last_r, 1) + 1):
        date_val = date_str(ws.cell(row=r, column=2).value)
        ex_val = ws.cell(row=r, column=4).value

        # TOTAL row: harvest session-level metadata for the most recent
        # session before discarding the row. The TOTAL row's date may be
        # blank on legacy data; fall back to ``current["date"]``.
        if ex_val == TOTAL_LABEL:
            if current is not None:
                current["total_meta"] = {
                    "date":         date_val or current.get("date"),
                    "notes":        ws.cell(row=r, column=9).value,
                    "duration":     ws.cell(row=r, column=11).value,
                    "avg_hr":       ws.cell(row=r, column=13).value,
                    "active_cal":   ws.cell(row=r, column=14).value,
                    "total_cal":    ws.cell(row=r, column=15).value,
                    "elevation_m": ws.cell(row=r, column=16).value,
                    "elapsed":      ws.cell(row=r, column=17).value,
                }
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
            "active_cal":  ws.cell(row=r, column=14).value,
            "total_cal":   ws.cell(row=r, column=15).value,
            "elevation_m": ws.cell(row=r, column=16).value,
            "elapsed":     ws.cell(row=r, column=17).value,
        }

        if current is None or date_val != current["date"]:
            current = {"date": date_val, "rows": [], "total_meta": {}}
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
        slot = merged.setdefault(date, {"date": date, "rows": [], "total_meta": {}})
        slot["rows"].extend(sess["rows"])
        # If two same-date blocks each had a TOTAL row, prefer non-None
        # values from either (same merge semantics as the row-level data).
        for k, v in (sess.get("total_meta") or {}).items():
            if v not in (None, "") and slot["total_meta"].get(k) in (None, ""):
                slot["total_meta"][k] = v
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

        # Per-row + per-session classification via the shared helper.
        # Cols 11 (Duration), 13 (Avg HR), 14-17 placement:
        # - **Strength session**: session metadata lives on the TOTAL row
        #   only. All non-cardio rows (warmup + working sets) have those
        #   cells blank. Cardio rows mixed into a strength day keep their
        #   own per-row metadata (each Apple-recorded ride is independent).
        # - **Pure cardio session** (no strength rows): no TOTAL row;
        #   every row keeps its own per-row metadata.
        kinds, is_strength = _classify_session_rows(sess["rows"])

        # Hoist candidates for TOTAL row metadata. Priority order:
        #   1. The TOTAL row's existing values (canonical post-migration).
        #   2. Any non-cardio data row's value (legacy migration path,
        #      taken from the warmup row before this change).
        total_meta_in = sess.get("total_meta") or {}
        hoist_duration = total_meta_in.get("duration")
        hoist_avg_hr = total_meta_in.get("avg_hr")
        hoist_active = total_meta_in.get("active_cal")
        hoist_total = total_meta_in.get("total_cal")
        hoist_elev = total_meta_in.get("elevation_m")
        hoist_elapsed = total_meta_in.get("elapsed")
        # Hoisted Notes from TOTAL: split off the Deload Workout marker
        # so it survives independently of any user-added text on TOTAL.
        total_notes_in = total_meta_in.get("notes")
        deload_present, total_notes_remainder = _extract_deload_marker(total_notes_in)

        if is_strength:
            for i, rd in enumerate(sess["rows"]):
                if kinds[i] == "cardio":
                    continue
                if hoist_duration in (None, "") and rd.get("duration") not in (None, ""):
                    hoist_duration = rd["duration"]
                if hoist_avg_hr in (None, "") and rd.get("avg_hr") not in (None, ""):
                    hoist_avg_hr = _numeric_cell(rd["avg_hr"])
                if hoist_active in (None, "") and rd.get("active_cal") not in (None, ""):
                    hoist_active = _numeric_cell(rd["active_cal"])
                if hoist_total in (None, "") and rd.get("total_cal") not in (None, ""):
                    hoist_total = _numeric_cell(rd["total_cal"])
                if hoist_elev in (None, "") and rd.get("elevation_m") not in (None, ""):
                    hoist_elev = _numeric_cell(rd["elevation_m"])
                if hoist_elapsed in (None, "") and rd.get("elapsed") not in (None, ""):
                    hoist_elapsed = rd["elapsed"]
                # Inspect this row's Notes for any deload marker —
                # legacy /log convention put it on the warmup row. Strip
                # it out so only the user's per-exercise text remains;
                # raise the deload flag for the TOTAL row.
                row_deload, row_notes_remainder = _extract_deload_marker(rd.get("notes"))
                if row_deload:
                    deload_present = True
                    rd["notes"] = row_notes_remainder

        for idx, rd in enumerate(sess["rows"]):
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
            ws.cell(row=write_row, column=12, value=rd["pace"])
            if is_strength and kinds[idx] == "cardio":
                # Cardio row inside a mixed-session day — keep its own
                # per-row Duration / Avg HR / cols 14-17.
                ws.cell(row=write_row, column=11, value=rd["duration"])
                ws.cell(row=write_row, column=13, value=_numeric_cell(rd["avg_hr"]))
                ws.cell(row=write_row, column=14,
                        value=_numeric_cell(rd.get("active_cal")))
                ws.cell(row=write_row, column=15,
                        value=_numeric_cell(rd.get("total_cal")))
                ws.cell(row=write_row, column=16,
                        value=_numeric_cell(rd.get("elevation_m")))
                ws.cell(row=write_row, column=17, value=rd.get("elapsed"))
            elif is_strength:
                # Strength/other row — session metadata moved to TOTAL,
                # cells stay blank.
                ws.cell(row=write_row, column=11).value = None
                ws.cell(row=write_row, column=13).value = None
                ws.cell(row=write_row, column=14).value = None
                ws.cell(row=write_row, column=15).value = None
                ws.cell(row=write_row, column=16).value = None
                ws.cell(row=write_row, column=17).value = None
            else:
                # Pure cardio session — each row keeps its own metadata.
                ws.cell(row=write_row, column=11, value=rd["duration"])
                ws.cell(row=write_row, column=13, value=_numeric_cell(rd["avg_hr"]))
                ws.cell(row=write_row, column=14,
                        value=_numeric_cell(rd.get("active_cal")))
                ws.cell(row=write_row, column=15,
                        value=_numeric_cell(rd.get("total_cal")))
                ws.cell(row=write_row, column=16,
                        value=_numeric_cell(rd.get("elevation_m")))
                ws.cell(row=write_row, column=17, value=rd.get("elapsed"))
            write_row += 1
        last_set_row = write_row - 1

        if is_strength:
            # TOTAL row: Date, Volume formula, all session-level metadata,
            # and the Deload Workout marker on Notes when present. Merge
            # the SESSION column (col 1) through this row alongside the
            # data rows below.
            ws.cell(row=write_row, column=1, value=session_num)
            ws.cell(row=write_row, column=2, value=sess["date"])
            ws.cell(row=write_row, column=4, value=TOTAL_LABEL)
            ws.cell(row=write_row, column=8, value=f"=SUM(H{first_row}:H{last_set_row})")
            ws.cell(row=write_row, column=9,
                    value=DELOAD_MARKER_TEXT if deload_present else None)
            ws.cell(row=write_row, column=11, value=hoist_duration)
            ws.cell(row=write_row, column=13, value=hoist_avg_hr)
            ws.cell(row=write_row, column=14, value=hoist_active)
            ws.cell(row=write_row, column=15, value=hoist_total)
            ws.cell(row=write_row, column=16, value=hoist_elev)
            ws.cell(row=write_row, column=17, value=hoist_elapsed)
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


# ============================================================ Bodyweight sheet
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


# ============================================================ Health Metrics sheet
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


def _resolve_source(wb) -> str:
    """Return the active data source (``xml`` | ``hl_export``).

    Reads ``Profile.source``; defaults to ``"xml"`` if the Profile sheet is
    missing or the cell is uninitialised. Fabian's tracker has
    ``source = hl_export`` so its slim schemas apply; Nihad's defaults
    to ``xml`` so existing behaviour is preserved.
    """
    src = read_profile(wb).get("source")
    return src if src in ("xml", "hl_export") else "xml"


def style_health_metrics_sheet(ws, source: str = "xml"):
    """Apply canonical styling to the Health Metrics sheet. Idempotent.

    Layout depends on ``source``: 15 cols for ``xml``, 7 cols for
    ``hl_export``. Date in col A, Notes in the rightmost column
    (left-aligned). Data sorted DESC by ``upsert_health_metrics`` (the
    single writer). This function only enforces header + data styling,
    widths, and freeze pane; it does not reorder rows.
    """
    headers   = HEALTH_METRICS_HEADERS_BY_SOURCE[source]
    cols      = HEALTH_METRICS_COLS_BY_SOURCE[source]
    widths    = HEALTH_METRICS_WIDTHS_BY_SOURCE[source]
    left_cols = HEALTH_METRICS_LEFT_COLS_BY_SOURCE[source]

    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))

    # Trim any stray columns beyond the canonical layout.
    if ws.max_column > cols:
        ws.delete_cols(cols + 1, ws.max_column - cols)

    for c, label in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = no_border

    last_data_row, _ = find_last_data_cell(ws)
    for r in range(2, last_data_row + 1):
        for c in range(1, cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = font_data
            cell.fill = fill_data
            col = get_column_letter(c)
            cell.alignment = align_left if col in left_cols else align_center
            cell.border = no_border

    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


# ============================================================ Workout Sessions sheet
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


def style_workout_sessions_sheet(ws, source: str = "xml"):
    """Apply canonical styling to the Workout Sessions sheet. Idempotent.

    Layout depends on ``source``: 12 cols for ``xml`` (incl. Avg/Max/Min HR);
    9 cols for ``hl_export`` (HR cols dropped — HL never delivers them).
    Type / Source / Notes left-aligned; everything else centered. Data
    sorted DESC by ``upsert_workout_sessions`` (the single writer).
    """
    headers   = WORKOUT_SESSIONS_HEADERS_BY_SOURCE[source]
    cols      = WORKOUT_SESSIONS_COLS_BY_SOURCE[source]
    widths    = WORKOUT_SESSIONS_WIDTHS_BY_SOURCE[source]
    left_cols = WORKOUT_SESSIONS_LEFT_COLS_BY_SOURCE[source]

    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))

    if ws.max_column > cols:
        ws.delete_cols(cols + 1, ws.max_column - cols)

    for c, label in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = no_border

    last_data_row, _ = find_last_data_cell(ws)
    for r in range(2, last_data_row + 1):
        for c in range(1, cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = font_data
            cell.fill = fill_data
            col = get_column_letter(c)
            cell.alignment = align_left if col in left_cols else align_center
            cell.border = no_border

    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


# ============================================================ Upserts (HM + WS)
def ensure_health_metrics_sheet(wb):
    """Ensure the Health Metrics sheet exists with the per-source headers.

    Returns ``(ws, created)``. The header row is written using the schema
    matching the workbook's ``Profile.source`` (xml = 15 cols, hl_export
    = 7 cols).
    """
    source = _resolve_source(wb)
    if HEALTH_METRICS_SHEET_NAME in wb.sheetnames:
        return wb[HEALTH_METRICS_SHEET_NAME], False
    ws = wb.create_sheet(title=HEALTH_METRICS_SHEET_NAME)
    for col, header in enumerate(HEALTH_METRICS_HEADERS_BY_SOURCE[source], start=1):
        ws.cell(row=1, column=col, value=header)
    return ws, True


def ensure_workout_sessions_sheet(wb):
    """Ensure the Workout Sessions sheet exists with the per-source headers.

    xml = 12 cols (Avg/Max/Min HR included), hl_export = 9 cols (HR dropped).
    """
    source = _resolve_source(wb)
    if WORKOUT_SESSIONS_SHEET_NAME in wb.sheetnames:
        return wb[WORKOUT_SESSIONS_SHEET_NAME], False
    ws = wb.create_sheet(title=WORKOUT_SESSIONS_SHEET_NAME)
    for col, header in enumerate(WORKOUT_SESSIONS_HEADERS_BY_SOURCE[source], start=1):
        ws.cell(row=1, column=col, value=header)
    return ws, True


def upsert_health_metrics(wb, entries):
    """Sparse-merge per-date Health Metrics rows into the workbook.

    ``entries`` is a list of dicts. Each must have ``date`` (YYYY-MM-DD)
    and any subset of the per-source field keys. Missing or None values
    are treated as "no data this run" — they NEVER overwrite an existing
    non-null cell. The Notes column (rightmost) is preserved untouched on
    every upsert. Field list and column count are picked from the
    workbook's ``Profile.source`` (xml: 13 fields + Notes; hl_export:
    5 fields + Notes — the unsupported-by-HL fields silently never land).

    Returns a list of one summary string for the importer to print.
    """
    if not entries:
        return [f"{HEALTH_METRICS_SHEET_NAME}: 0 dates written / 0 updated"]
    ws, created = ensure_health_metrics_sheet(wb)
    source = _resolve_source(wb)
    fields = HEALTH_METRICS_FIELDS_BY_SOURCE[source]
    cols   = HEALTH_METRICS_COLS_BY_SOURCE[source]

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
        for i, key in enumerate(fields, start=1):
            v = row[i] if len(row) > i else None
            record[key] = v
        notes = row[cols - 1] if len(row) >= cols else None
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
            for key in fields:
                v = e.get(key)
                new_record[key] = v if v is not None else None
            existing[d] = new_record
            written += 1
            continue

        # Sparse-merge: incoming None never erases existing values; non-null
        # incoming overwrites only when the value differs.
        changed = False
        for key in fields:
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
        for col_idx, key in enumerate(fields, start=2):
            ws.cell(row=i, column=col_idx, value=rec.get(key))
        ws.cell(row=i, column=cols, value=rec.get("__notes"))

    style_health_metrics_sheet(ws, source=source)

    if seen_dates:
        date_range = f"{min(seen_dates)} → {max(seen_dates)}"
    else:
        date_range = "no rows"
    tag = " (new sheet)" if created else ""
    return [f"{HEALTH_METRICS_SHEET_NAME}{tag}: {written} dates written / {updated} updated (range {date_range})"]


def upsert_workout_sessions(wb, entries):
    """Insert or overwrite Workout Sessions rows by (date, start) dedupe key.

    ``entries`` is a list of dicts with workout keys (date, start, end,
    apple_type, duration_min, avg_hr, max_hr, min_hr, active_cal,
    distance_km, source, notes). For ``hl_export`` trackers the avg/max/min
    HR keys are silently dropped from the sheet (HL never delivers them).
    Re-running with the same export is a no-op. Sorts DESC by (date,
    start) on every write.

    Returns a list of one summary string for the importer to print.
    """
    if not entries:
        return [f"{WORKOUT_SESSIONS_SHEET_NAME}: 0 sessions written / 0 updated"]
    ws, created = ensure_workout_sessions_sheet(wb)
    source = _resolve_source(wb)
    fields = WORKOUT_SESSIONS_FIELDS_BY_SOURCE[source]

    existing: dict[tuple, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        d, s = ws_locate_date_start(row)
        if d is None:
            continue
        rec = {"date": d, "start": s}
        # Cell column N (1-based) = fields[N-2] for N >= 2 (col 1 is Date,
        # col 2 onwards is Start, End, …). Walk per-source so HL trackers
        # don't try to read non-existent HR columns.
        for i, key in enumerate(fields, start=1):
            rec[key] = row[i] if len(row) > i else None
        existing[(d, s)] = rec

    written = 0
    updated = 0
    incidental = 0
    for e in entries:
        d = str(e.get("date") or "")[:10]
        s = e.get("start")
        if not d or s is None:
            continue
        key = (d, str(s))
        new_rec = {"date": d, "start": str(s)}
        # Only persist fields the active source supports — HL writes drop
        # avg_hr / max_hr / min_hr automatically.
        for k in fields:
            new_rec[k] = e.get(k)
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
        ws.cell(row=i, column=1, value=rec["date"])
        # ``start`` is already in fields[0]; iterate fields to fill 2..N.
        for col_idx, k in enumerate(fields, start=2):
            ws.cell(row=i, column=col_idx, value=rec.get(k))

    style_workout_sessions_sheet(ws, source=source)

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
#
# ``auto_cardio_since`` was removed in 2026-05 alongside the Tombstones
# sheet — the importer is now scoped to the current calendar month, so a
# date cutoff is implicit and doesn't need a profile cell. Existing
# trackers that still have an ``auto_cardio_since`` row get cleaned up
# the next time ``style_profile_sheet`` runs (it drops keys not in
# PROFILE_KEYS).
PROFILE_KEYS = ("source", "auto_cardio", "birthday")

# Default values applied when ``ensure_profile_sheet`` creates the sheet
# from scratch. ``source`` left None so the caller can inject ``xml`` or
# ``hl_export`` based on the file extension that triggered the import.
# ``birthday`` (YYYY-MM-DD) lets the coach compute age dynamically for the
# max-HR fallback formula (208 − 0.7×age) when Apple per-workout HR isn't
# available. None → caller falls back to a generic age.
PROFILE_DEFAULTS = {
    "source":            None,
    "auto_cardio":       False,
    "birthday":          None,
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
        elif k == "birthday":
            if val is None or val == "":
                continue
            s = date_str(val)
            if s and len(s) == 10 and s[4] == "-" and s[7] == "-":
                out["birthday"] = s
    return out


def style_profile_sheet(ws):
    """Apply canonical styling to the Profile sheet. Idempotent.

    Two-column key/value layout. Header row, then one row per known key
    in ``PROFILE_KEYS`` order. Re-running rebuilds the sheet from the
    in-memory key/value snapshot — drops legacy keys (e.g. ``notes``)
    that were removed from the schema, and trims any stale rows or
    columns left behind.
    """
    for merged_range in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_range))

    # Snapshot existing key/value pairs so a re-style preserves user
    # edits while dropping deprecated keys / blank trailing rows.
    existing: dict[str, object] = {}
    for r in range(2, ws.max_row + 1):
        k = ws.cell(row=r, column=1).value
        v = ws.cell(row=r, column=2).value
        if k in (None, ""):
            continue
        key_norm = str(k).strip().lower()
        if key_norm in PROFILE_KEYS:
            existing[key_norm] = v

    # Trim columns beyond 2.
    if ws.max_column > 2:
        ws.delete_cols(3, ws.max_column - 2)

    # Trim rows beyond the canonical layout (1 header + len(PROFILE_KEYS)).
    target_rows = 1 + len(PROFILE_KEYS)
    if ws.max_row > target_rows:
        ws.delete_rows(target_rows + 1, ws.max_row - target_rows)

    # Rewrite header and key column from canonical PROFILE_KEYS so
    # legacy keys disappear on next re-style.
    for c, label in enumerate(PROFILE_HEADERS, 1):
        cell = ws.cell(row=1, column=c, value=label)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = no_border

    for r, key in enumerate(PROFILE_KEYS, start=2):
        ws.cell(row=r, column=1).value = key
        # Preserve existing value or re-apply default. Booleans stay as
        # "true"/"false" strings.
        if key in existing:
            ws.cell(row=r, column=2).value = existing[key]
        else:
            default = PROFILE_DEFAULTS.get(key)
            if isinstance(default, bool):
                ws.cell(row=r, column=2).value = "true" if default else "false"
            else:
                ws.cell(row=r, column=2).value = default

    for r in range(2, target_rows + 1):
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
_MONTH_RE_STR = r"^\d{4}\.\d{2}$"


def _is_monthly_sheet(name: str) -> bool:
    import re as _re
    return bool(_re.match(_MONTH_RE_STR, name))


def canonicalize_sheet_order(wb) -> None:
    """Re-order sheets to the canonical layout. Idempotent.

    Order: Exercises Database, Profile, Bodyweight (if present), Health
    Metrics, Workout Sessions, monthly sheets newest → oldest, anything
    else last. Used by every writer that may create a new sheet
    (``upsert_monthly_cardio``, ``append_workout``, the importers' bootstrap
    paths) so the tab strip stays canonical without waiting for ``/maintain``.
    """
    names = list(wb.sheetnames)
    db = [n for n in names if n == "Exercises Database"]
    pf = [n for n in names if n == PROFILE_SHEET_NAME]
    bw = [n for n in names if n == "Bodyweight"]
    hm = [n for n in names if n == HEALTH_METRICS_SHEET_NAME]
    ws = [n for n in names if n == WORKOUT_SESSIONS_SHEET_NAME]
    months = sorted((n for n in names if _is_monthly_sheet(n)), reverse=True)
    fixed = set(db + pf + bw + hm + ws + months)
    other = [n for n in names if n not in fixed]
    desired = db + pf + bw + hm + ws + months + other

    for target_idx, name in enumerate(desired):
        sheet_obj = wb[name]
        cur_idx = wb.sheetnames.index(name)
        if cur_idx != target_idx:
            wb.move_sheet(sheet_obj, offset=target_idx - cur_idx)


def _format_duration_mmss(duration_min) -> str | None:
    """Coerce a numeric or MM:SS duration to a canonical ``MM:SS`` string.

    - ``None`` / ``""`` → None
    - already a ``MM:SS`` string → returned verbatim (after a defensive
      sanity check that minutes are non-negative)
    - any numeric value (or numeric-looking string, incl. European comma) →
      formatted as ``MM:SS``
    Auto-cardio rows previously wrote raw float minutes (e.g. ``60.6``);
    this helper unifies them with manual-log MM:SS strings.
    """
    if duration_min in (None, ""):
        return None
    if isinstance(duration_min, str):
        s = duration_min.strip()
        if ":" in s:
            return s if s else None
        try:
            duration_min = float(s.replace(",", "."))
        except ValueError:
            return None
    try:
        f = float(duration_min)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return None
    whole = int(f)
    secs = int(round((f - whole) * 60))
    if secs == 60:
        whole += 1
        secs = 0
    return f"{whole}:{secs:02d}"


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

# When elapsed and active duration differ by less than this many minutes the
# elapsed-time field is dropped from the auto-cardio note (no meaningful pause
# happened, so showing both adds noise). Threshold matches the human eye —
# 1 min of stop time on a 30-min run isn't worth surfacing.
ELAPSED_TIME_MIN_DELTA = 1.0


def _format_elapsed_hms(elapsed_min: float | None) -> str | None:
    """Render elapsed minutes as ``H:MM:SS`` for long activities, else ``MM:SS``.

    Used by the auto-cardio note builder. Returns None on missing/zero input
    so the caller can omit the field entirely.
    """
    if elapsed_min in (None, "") or not isinstance(elapsed_min, (int, float)):
        return None
    if elapsed_min <= 0:
        return None
    total_seconds = int(round(elapsed_min * 60))
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def build_auto_cardio_note(
    *,
    active_cal: float | None = None,
    total_cal: float | None = None,
    elevation_m: float | None = None,
    duration_min: float | None = None,
    elapsed_min: float | None = None,
) -> str:
    """Build the structured Notes string for an auto-imported cardio row.

    Format: ``auto-imported from Apple | active 753 kcal | total 1041 kcal |
    elevation 73 m | elapsed 3:53:23``

    Each ``| field value`` is dropped when the source value is None or
    zero. ``elapsed`` is dropped when it differs from ``duration_min`` by
    less than ``ELAPSED_TIME_MIN_DELTA`` minutes (no meaningful pauses).
    Single source of truth — both importers and the backfill script call
    this helper so the format stays consistent.
    """
    parts: list[str] = [AUTO_IMPORT_NOTE]

    if active_cal not in (None, 0, 0.0):
        parts.append(f"active {int(round(active_cal))} kcal")
    if total_cal not in (None, 0, 0.0):
        # Skip the total field if it's not meaningfully larger than active —
        # otherwise we'd emit identical-looking active/total values.
        if active_cal is None or total_cal - active_cal >= 1:
            parts.append(f"total {int(round(total_cal))} kcal")
    if elevation_m not in (None, 0, 0.0):
        parts.append(f"elevation {int(round(elevation_m))} m")

    if elapsed_min not in (None, 0, 0.0):
        delta = abs(elapsed_min - (duration_min or 0))
        if duration_min is None or delta >= ELAPSED_TIME_MIN_DELTA:
            elapsed_str = _format_elapsed_hms(elapsed_min)
            if elapsed_str:
                parts.append(f"elapsed {elapsed_str}")

    return " | ".join(parts)


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


def upsert_monthly_cardio(wb, rows: list[dict], allow_past_months: bool = False) -> list[str]:
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

    ``allow_past_months`` (default False) bypasses the current-month gate
    and lets rows flow into prior YYYY.MM sheets too. Use sparingly — the
    gate is the whole reason past months are immune to re-scan drift.
    Intended for one-off backfills (e.g. enabling auto-cardio retroactively
    for a tracker that had it off).

    Returns one summary string per touched sheet, plus a roll-up. Empty
    input returns a no-op summary.
    """
    if not rows:
        return ["Auto-cardio: 0 rows considered"]

    # Bucket incoming rows by ``YYYY.MM`` once so we touch each sheet exactly
    # once (read existing → append new → restyle), regardless of how rows
    # were ordered.
    #
    # Current-month gate: importers only ever write into the current
    # calendar month's monthly sheet. Past months are "finished" and are
    # never re-scanned, so a row the user deleted from 2026.02 stays
    # deleted on the next import without needing a tombstone. This is the
    # whole reason the Tombstones sheet was removed in 2026-05.
    # ``allow_past_months=True`` opts out for one-off backfills.
    current_month = _current_month_key()
    skipped_past_month = 0
    by_month: dict[str, list[dict]] = {}
    for r in rows:
        d = str(r.get("date") or "")[:10]
        if not d or len(d) != 10:
            continue
        key = f"{d[:4]}.{d[5:7]}"
        if not allow_past_months and key != current_month:
            skipped_past_month += 1
            continue
        by_month.setdefault(key, []).append(r)

    if not by_month:
        if skipped_past_month:
            return [
                f"Auto-cardio: 0 rows considered "
                f"({skipped_past_month} skipped — past months are not re-scanned)"
            ]
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
        # (date, lowercased exercise) → list of (row_index, duration_min,
        # is_auto) so the manual-wins rule and the sparse-merge metadata
        # update both have access to the source row.
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
            # Case-insensitive substring check — both sides lowered.
            is_auto = AUTO_IMPORT_NOTE.lower() in str(notes_v or "").lower()
            key = (date_v, ex_str.lower())
            existing_index.setdefault(key, []).append((r, dur_f, is_auto))

        appended = 0
        skipped_dup = 0
        refreshed = 0
        # Track which existing rows have already been claimed by an input
        # workout so two near-duration Apple workouts can't both match the
        # same tracker row. Without this, fuzzy ±1-min matching causes
        # oscillation when Apple has more workouts than the tracker rows
        # for a date (e.g. 5 cycling segments vs 4 rows).
        claimed_rows: set = set()

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
            has_manual_match = any(
                (not is_auto) and (er not in claimed_rows)
                for er, _dur, is_auto in matches
            )
            matched_auto_row = None
            if not has_manual_match:
                # Pick the unclaimed auto row with the smallest duration
                # difference within tolerance — stable across re-runs and
                # prevents two near-duration Apple workouts from claiming
                # the same row.
                best = None
                best_diff = None
                for er, existing_dur, is_auto in matches:
                    if not is_auto or er in claimed_rows:
                        continue
                    if existing_dur is None or dur_f is None:
                        diff = 0.0
                    else:
                        diff = abs(existing_dur - dur_f)
                        if diff > CARDIO_DUPLICATE_DURATION_TOLERANCE_MIN:
                            continue
                    if best_diff is None or diff < best_diff:
                        best, best_diff = er, diff
                matched_auto_row = best
            if matched_auto_row is not None:
                claimed_rows.add(matched_auto_row)
                # Existing auto row — refresh stale cols 14-17 in place.
                # Historical importer bug copied the same Notes string to
                # every cardio row of a date; this sparse-merge corrects
                # those values from per-workout Apple data. Only updates
                # cells that are empty OR diverge from incoming by >=5%
                # (the manual-wins / drift threshold from Q6).
                incoming_meta = {
                    14: int(round(r.get("active_cal"))) if isinstance(r.get("active_cal"), (int, float)) and r.get("active_cal") else None,
                    15: int(round(r.get("total_cal"))) if isinstance(r.get("total_cal"), (int, float)) and r.get("total_cal") else None,
                    16: int(round(r.get("elevation_m"))) if isinstance(r.get("elevation_m"), (int, float)) and r.get("elevation_m") else None,
                    17: _format_elapsed_hms(r.get("elapsed_min")),
                }
                row_changed = False
                for col, new_val in incoming_meta.items():
                    if new_val in (None, ""):
                        continue
                    existing = ws.cell(row=matched_auto_row, column=col).value
                    if existing in (None, ""):
                        ws.cell(row=matched_auto_row, column=col).value = new_val
                        row_changed = True
                    elif _strength_metadata_drifts(existing, new_val):
                        ws.cell(row=matched_auto_row, column=col).value = new_val
                        row_changed = True
                if row_changed:
                    refreshed += 1
                else:
                    skipped_dup += 1
                continue
            if has_manual_match:
                skipped_dup += 1
                continue

            distance = r.get("distance_km")
            avg_hr = r.get("avg_hr")
            pace = _format_pace_min_per_km(dur_f, distance)

            # Compute the next free per-date # for this exercise. Manual
            # rows usually have a #; cardio is typically solo-per-day so
            # this lands at 1, but reuses an existing day's exercise count
            # if the user logged strength earlier the same date.
            existing_nums = []
            for er in range(2, ws.max_row + 1):
                if date_str(ws.cell(row=er, column=2).value) == d:
                    n = ws.cell(row=er, column=3).value
                    if isinstance(n, (int, float)):
                        existing_nums.append(int(n))
            next_num = (max(existing_nums) + 1) if existing_nums else 1

            ws.cell(row=write_row, column=1, value=None)        # SESSION (styler fills)
            ws.cell(row=write_row, column=2, value=d)
            ws.cell(row=write_row, column=3, value=next_num)
            ws.cell(row=write_row, column=4, value=ex)
            ws.cell(row=write_row, column=5, value=1)           # Set
            ws.cell(row=write_row, column=6, value=None)        # Reps (cardio: blank)
            ws.cell(row=write_row, column=7, value=None)        # kg
            ws.cell(row=write_row, column=8, value=f"=F{write_row}*G{write_row}")
            ws.cell(row=write_row, column=9, value=AUTO_IMPORT_NOTE)
            ws.cell(row=write_row, column=10, value=_numeric_cell(distance))
            ws.cell(row=write_row, column=11, value=_format_duration_mmss(dur_f))
            ws.cell(row=write_row, column=12, value=pace)
            ws.cell(row=write_row, column=13, value=_numeric_cell(avg_hr))
            # Apple-watch session metadata in cols 14-17 (single-row cardio
            # session — same row carries the metadata and the workout data).
            ac = r.get("active_cal")
            tc = r.get("total_cal")
            el = r.get("elevation_m")
            ws.cell(row=write_row, column=14,
                    value=int(round(ac)) if isinstance(ac, (int, float)) and ac else None)
            ws.cell(row=write_row, column=15,
                    value=int(round(tc)) if isinstance(tc, (int, float)) and tc else None)
            ws.cell(row=write_row, column=16,
                    value=int(round(el)) if isinstance(el, (int, float)) and el else None)
            ws.cell(row=write_row, column=17,
                    value=_format_elapsed_hms(r.get("elapsed_min")))

            # Track the new row in the dedupe index too so subsequent input
            # rows don't double-add for the same date.
            existing_index.setdefault((d, ex_lower), []).append((write_row, dur_f, True))

            write_row += 1
            appended += 1

        if appended or refreshed:
            style_monthly_sheet(ws)

        total_appended += appended
        total_skipped += skipped_dup
        tag = " (new sheet)" if sheet_created else ""
        refreshed_tag = f", {refreshed} refreshed" if refreshed else ""
        summaries.append(
            f"{month_key}{tag}: {appended} cardio rows appended, "
            f"{skipped_dup} skipped (already present){refreshed_tag}"
        )

    # Re-canonicalize tab order so newly-created month sheets land in the
    # correct position (newest first, after Workout Sessions). Without this,
    # a fresh month sits at the right end of the strip until /maintain runs.
    canonicalize_sheet_order(wb)

    summaries.append(
        f"Auto-cardio total: {total_appended} appended, "
        f"{total_skipped} skipped across {len(by_month)} month(s)"
    )
    if skipped_past_month:
        summaries.append(
            f"Auto-cardio: {skipped_past_month} input rows skipped "
            f"(dated outside the current month {current_month})"
        )
    return summaries


# Threshold for the manual-wins / sparse-update rule on strength session
# metadata cells. If an existing cell value differs from the incoming Apple
# value by < 5%, treat them as the same (idempotency / Apple jitter). If
# the difference is >= 5%, the existing value is treated as user-edited and
# the importer skips with a warning rather than overwriting.
STRENGTH_METADATA_DRIFT_THRESHOLD = 0.05


# ================================================== Strength upsert (monthly)
def _strength_metadata_drifts(existing, incoming) -> bool:
    """Return True if the two values disagree by >= 5% (manual-wins guard).

    Both arguments are numeric (int / float) or Elapsed strings. Strings
    are compared by re-parsing back to minutes via ``_parse_duration_minutes``
    so ``"1:29:18"`` and ``"1:29:20"`` don't trip on the second-level noise.
    None/blank existing → never drifts (fill it in). Equal values → no drift.
    """
    if existing in (None, ""):
        return False
    if incoming in (None, ""):
        return False
    if isinstance(existing, str) or isinstance(incoming, str):
        e_min = _parse_duration_minutes(existing)
        i_min = _parse_duration_minutes(incoming)
        if e_min is None or i_min is None:
            return str(existing).strip() != str(incoming).strip()
        existing_f, incoming_f = e_min, i_min
    else:
        try:
            existing_f = float(existing)
            incoming_f = float(incoming)
        except (TypeError, ValueError):
            return existing != incoming
    if existing_f == 0 and incoming_f == 0:
        return False
    denom = max(abs(existing_f), abs(incoming_f), 1e-9)
    return abs(existing_f - incoming_f) / denom >= STRENGTH_METADATA_DRIFT_THRESHOLD


def upsert_monthly_strength_session(wb, sessions: list[dict]) -> list[str]:
    """Write Apple-watch session metadata onto the first row of each
    matching strength session in the monthly sheets.

    ``sessions`` is a list of dicts:

      ``date`` (YYYY-MM-DD), ``active_cal``, ``total_cal``, ``elevation_m``
      (usually None for indoor strength), ``elapsed_min`` (numeric minutes;
      formatted to ``H:MM:SS`` or ``MM:SS`` on write), ``avg_hr`` (per-cluster
      duration-weighted average heart rate; XML only — HL doesn't carry
      per-workout HR).

    Behavior per session:
    - Locate the YYYY.MM sheet for the date. If missing, skip (the user
      hasn't logged this strength session yet — Apple ahead of manual).
    - Find the first non-TOTAL data row whose Date matches.
    - For each of the 4 metadata cells, apply the manual-wins / drift rule:
      * empty cell → fill with incoming value
      * existing value within 5% of incoming → no-op (idempotency)
      * existing value diverges >= 5% → skip that cell with a warning
    - After touching any cell, re-style the sheet via ``style_monthly_sheet``
      so the convention is enforced uniformly.

    Returns a list of human-readable summary lines, including any
    drift warnings, so the importer can surface them.
    """
    if not sessions:
        return ["Strength sessions: 0 considered"]

    summaries: list[str] = []
    written = 0
    skipped_no_match = 0
    skipped_no_change = 0
    skipped_past_month = 0
    drift_warnings: list[str] = []

    touched_sheets: set = set()

    # Current-month gate: the importer never writes session metadata
    # into past-month sheets. A session logged in 2026.04 stays at
    # whatever metadata the user logged manually; April is "finished".
    current_month = _current_month_key()

    for sess in sessions:
        d = str(sess.get("date") or "")[:10]
        if not d or len(d) != 10:
            continue
        month_key = f"{d[:4]}.{d[5:7]}"
        if month_key != current_month:
            skipped_past_month += 1
            continue
        if month_key not in wb.sheetnames:
            skipped_no_match += 1
            continue
        ws = wb[month_key]

        # Locate the TOTAL row for this date. The styler emits a TOTAL
        # row for every strength session (any kg*reps>0 row); session
        # metadata lives there. The TOTAL row's Date (col 2) was added
        # in this migration; legacy rows may still have a blank Date,
        # so fall back to the row directly above when the date matches.
        target_row = None
        last_r, _ = find_last_data_cell(ws)
        date_seen_above = False
        for r in range(2, last_r + 1):
            row_date = date_str(ws.cell(row=r, column=2).value)
            ex_val = ws.cell(row=r, column=4).value
            ex_str = str(ex_val).strip() if ex_val else ""
            if ex_str.upper() == TOTAL_LABEL:
                if row_date == d or (row_date in (None, "") and date_seen_above):
                    target_row = r
                    break
                date_seen_above = False
                continue
            if row_date == d:
                date_seen_above = True
            elif row_date not in (None, ""):
                date_seen_above = False

        if target_row is None:
            # No TOTAL row for this date — either the user hasn't logged
            # the strength session yet (Apple ahead of /log), or the
            # session has no kg*reps>0 row (the styler skipped TOTAL).
            skipped_no_match += 1
            continue

        ac = sess.get("active_cal")
        tc = sess.get("total_cal")
        el = sess.get("elevation_m")
        em = sess.get("elapsed_min")
        ah = sess.get("avg_hr")
        dur = sess.get("duration_min")

        incoming = {
            11: _format_duration_mmss(dur),  # Duration (col K) — active workout time, MM:SS
            13: round(float(ah), 1) if isinstance(ah, (int, float)) and ah else None,
            14: int(round(ac)) if isinstance(ac, (int, float)) and ac else None,
            15: int(round(tc)) if isinstance(tc, (int, float)) and tc else None,
            16: int(round(el)) if isinstance(el, (int, float)) and el else None,
            17: _format_elapsed_hms(em),
        }

        any_change = False
        for col, new_val in incoming.items():
            if new_val in (None, ""):
                continue
            existing = ws.cell(row=target_row, column=col).value
            if existing in (None, ""):
                ws.cell(row=target_row, column=col, value=new_val)
                any_change = True
            elif _strength_metadata_drifts(existing, new_val):
                drift_warnings.append(
                    f"  - {d} col {col}: kept manual value {existing!r} "
                    f"(Apple reports {new_val!r}, differs >=5%)"
                )
            # else: within tolerance → no-op (idempotency)

        if any_change:
            written += 1
            touched_sheets.add(month_key)
        else:
            skipped_no_change += 1

    for sheet_name in sorted(touched_sheets):
        style_monthly_sheet(wb[sheet_name])

    summaries.append(
        f"Strength sessions: {written} written, "
        f"{skipped_no_change} no-op (already up to date), "
        f"{skipped_no_match} skipped (no matching session row)"
    )
    if skipped_past_month:
        summaries.append(
            f"Strength sessions: {skipped_past_month} dated outside the "
            f"current month {current_month} — past months are not re-scanned"
        )
    if drift_warnings:
        summaries.append(
            f"Strength sessions: {len(drift_warnings)} manual-wins warnings:"
        )
        summaries.extend(drift_warnings)

    return summaries


# ============================================================ Exercises Database sheet
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
