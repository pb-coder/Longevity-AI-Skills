"""Append parsed workout rows to the right monthly sheet in Workout Tracker.xlsx.

Routes each row to the YYYY.MM sheet matching its date. Creates the sheet
(headers only) if missing. Leaves styling alone — /maintain handles that.

Input JSON schema (list of row dicts):
    [
      {
        "date": "2026-04-20",          # required, YYYY-MM-DD
        "num": 1,                      # exercise index within the session
        "exercise": "Dumbbell Flat Bench Press",
        "set": 1,
        "reps": 10,
        "kg": 52,
        "volume": 520,
        "notes": "",
        "distance_km": null,           # optional cardio fields
        "duration_min": null,
        "pace": null,                  # string "MM:SS"
        "avg_hr": null
      },
      ...
    ]

Rows must arrive pre-sorted: by date ascending, then by num ascending, then by set.
The script does not re-sort — it trusts the caller.

Usage:
    python3 append_workout.py <tracker_path> <rows_json_path>
    python3 append_workout.py <tracker_path> -    # read JSON from stdin
"""
import json
import sys
from pathlib import Path

import openpyxl

HEADERS = [
    "Date", "#", "Exercise", "Set", "Reps", "kg", "Volume", "Notes",
    "Distance (km)", "Duration (min)", "Pace (min/km)", "Avg HR",
]


def sheet_for_date(date_str: str) -> str:
    """'2026-04-20' -> '2026.04'."""
    y, m, _ = date_str.split("-")
    return f"{y}.{m}"


def find_last_data_row(ws) -> int:
    """Return the last row containing any value. 1 if only headers / empty."""
    last = 1
    for row in ws.iter_rows(min_row=2):
        if any(c.value is not None and c.value != "" for c in row):
            last = row[0].row
    return last


def ensure_sheet(wb, name: str):
    """Return the sheet, creating it with headers if missing."""
    if name in wb.sheetnames:
        return wb[name], False
    ws = wb.create_sheet(title=name)
    for col, header in enumerate(HEADERS, start=1):
        ws.cell(row=1, column=col, value=header)
    return ws, True


def row_values(r: dict):
    """Build the 12-col row. Date/#/Exercise populated on every row (tracker convention)."""
    return [
        r["date"],
        r["num"],
        r["exercise"],
        r["set"],
        r.get("reps"),
        r.get("kg"),
        r.get("volume"),
        r.get("notes") or None,
        r.get("distance_km"),
        r.get("duration_min"),
        r.get("pace"),
        r.get("avg_hr"),
    ]


def append_rows(tracker_path: Path, rows: list[dict]) -> list[str]:
    """Append rows grouped by sheet. Return human-readable status lines."""
    wb = openpyxl.load_workbook(tracker_path)
    status = []

    # Group by target sheet, preserving input order within each group.
    by_sheet: dict[str, list[dict]] = {}
    for r in rows:
        by_sheet.setdefault(sheet_for_date(r["date"]), []).append(r)

    for sheet_name, sheet_rows in by_sheet.items():
        ws, created = ensure_sheet(wb, sheet_name)

        last_row = find_last_data_row(ws)
        write_row = last_row + 1

        for r in sheet_rows:
            for col, val in enumerate(row_values(r), start=1):
                ws.cell(row=write_row, column=col, value=val)
            write_row += 1

        dates = sorted({r["date"] for r in sheet_rows})
        tag = " (new sheet)" if created else ""
        status.append(
            f"Appended {len(sheet_rows)} row(s) to {sheet_name}{tag} "
            f"for {', '.join(dates)}"
        )

    wb.save(tracker_path)
    return status


def load_rows(source: str) -> list[dict]:
    if source == "-":
        data = json.load(sys.stdin)
    else:
        data = json.loads(Path(source).read_text())
    if not isinstance(data, list):
        raise ValueError("rows JSON must be a list of row dicts")
    for r in data:
        if "date" not in r or "exercise" not in r or "set" not in r or "num" not in r:
            raise ValueError(f"row missing required field: {r!r}")
    return data


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    tracker = Path(sys.argv[1])
    if not tracker.exists():
        print(f"ERROR: tracker not found: {tracker}", file=sys.stderr)
        return 1
    rows = load_rows(sys.argv[2])
    if not rows:
        print("No rows to append.")
        return 0
    for line in append_rows(tracker, rows):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
