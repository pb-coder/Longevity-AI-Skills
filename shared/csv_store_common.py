"""Shared CSV-store primitives used by the focused store modules."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker.csv_table import (  # noqa: E402
    CsvTableSpec,
    date_str as _date_str,
    parse_value as _parse_value,
    read_csv_rows as _table_read_csv_rows,
    replace_upsert_records,
    serialize_value as _serialize_value,
    sparse_upsert_records,
    write_csv_atomic as _table_write_csv_atomic,
)


def _read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """Return ``(header, rows)`` from a CSV. Empty file -> ``([], [])``."""
    return _table_read_csv_rows(path)


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    """Atomic CSV write through the central table writer."""
    _table_write_csv_atomic(path, header, rows)


def ensure_data_dir_for(path: Path) -> None:
    """Internal helper: create the parent directory of a CSV path."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _date_to_year_month(date_str: str) -> str:
    """Convert ``YYYY-MM-DD`` to ``YYYY.MM`` (per-month CSV key)."""
    return f"{date_str[:4]}.{date_str[5:7]}"


def _group_entries_by_month(entries: Iterable[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for e in entries or []:
        d = _date_str(e.get("date"))
        if not d:
            continue
        item = dict(e)
        item["date"] = d
        grouped.setdefault(_date_to_year_month(d), []).append(item)
    return grouped


def _read_periodic_records(path: Path,
                           fields: list[str],
                           headers: list[str],
                           *,
                           string_fields: set[str] | None = None,
                           field_parsers: dict[str, Callable] | None = None,
                           include_notes: bool = True) -> list[dict]:
    string_fields = string_fields or set()
    field_parsers = field_parsers or {}
    header, rows = _read_csv_rows(path)
    if not header:
        return []
    out: list[dict] = []
    for row in rows:
        d = _date_str(row[0]) if row else None
        if d is None:
            continue
        rec: dict = {"date": d}
        for i, key in enumerate(fields, start=1):
            v = row[i] if len(row) > i else None
            if key in field_parsers:
                rec[key] = field_parsers[key](v)
            elif key in string_fields:
                rec[key] = v if v not in (None, "") else None
            else:
                rec[key] = _parse_value(v)
        if include_notes:
            notes_idx = len(headers) - 1
            notes = row[notes_idx] if len(row) > notes_idx else None
            rec["notes"] = notes if notes else None
        out.append(rec)
    return out


def _write_periodic_records(path: Path,
                            headers: list[str],
                            fields: list[str],
                            records: list[dict],
                            *,
                            field_serializers: dict[str, Callable] | None = None,
                            include_notes: bool = True) -> None:
    field_serializers = field_serializers or {}
    row_fields = ["date"] + fields + (["notes"] if include_notes else [])
    rows = []
    for rec in records:
        row = []
        for field in row_fields:
            v = rec.get(field)
            if field in field_serializers:
                v = field_serializers[field](v)
            row.append(v)
        rows.append(row)
    _write_csv(path, headers, rows)
