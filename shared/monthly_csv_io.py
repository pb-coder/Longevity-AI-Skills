"""Monthly CSV file I/O and row translation."""
from __future__ import annotations

from pathlib import Path

from tracker.csv_table import (
    read_csv_rows as _table_read_csv_rows,
    write_csv_atomic as _table_write_csv_atomic,
)

from .monthly_csv_schema import MONTHLY_COLS, MONTHLY_FIELDS, MONTHLY_HEADERS, TOTAL_LABEL
from .monthly_csv_values import _numeric_cell
from .person_paths import monthly_csv as monthly_csv_path

__all__ = [
    "read_monthly",
]

# ============================================================ CSV I/O
def _serialize_value(v) -> str:
    """Inverse of ``_numeric_cell`` for CSV output."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return repr(v) if abs(v) > 1e15 else f"{v:g}"
    return str(v)


def _read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """Return ``(header, rows)``. Missing or empty file → ``([], [])``."""
    return _table_read_csv_rows(path)


def _row_to_dict(row: list[str]) -> dict:
    """Convert a raw CSV row (list of strings) to a dict by MONTHLY_FIELDS."""
    out: dict = {}
    padded = list(row) + [""] * (MONTHLY_COLS - len(row))
    for i, key in enumerate(MONTHLY_FIELDS):
        v = padded[i] if i < len(padded) else ""
        if v == "":
            out[key] = None
        else:
            out[key] = v
    return out


def _dict_to_row(d: dict) -> list[str]:
    """Convert a dict back to a CSV row (in MONTHLY_FIELDS order)."""
    return [_serialize_value(d.get(k)) for k in MONTHLY_FIELDS]


def _write_csv_atomic(path: Path, rows: list[list[str]]) -> None:
    """Write header + rows atomically (tmp + rename)."""
    _table_write_csv_atomic(path, MONTHLY_HEADERS, rows)


# ============================================================ read_monthly
def read_monthly(person: str, year_month: str) -> list[dict]:
    """Return all rows (incl. TOTAL) from the per-month CSV as dicts.

    Each dict has the 18 keys from ``MONTHLY_FIELDS``. TOTAL rows are
    distinguished by ``exercise == "TOTAL"``. Missing file → ``[]``.
    Coerces numeric columns to int/float; leaves duration/pace/notes/
    elapsed as strings.
    """
    path = monthly_csv_path(person, year_month)
    header, rows = _read_csv_rows(path)
    if not header:
        return []
    out: list[dict] = []
    numeric_keys = {"session", "num", "set", "reps", "kg", "volume",
                    "distance", "avg_hr", "active_cal", "total_cal",
                    "elevation_m"}
    for raw in rows:
        d = _row_to_dict(raw)
        # Date stays as YYYY-MM-DD string; coerce numerics.
        for k in numeric_keys:
            v = d.get(k)
            if v is None:
                continue
            d[k] = _numeric_cell(v)
        out.append(d)
    return out
