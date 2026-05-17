"""Small table primitives for the tracker CSV stores.

The tracker has several per-person and per-month CSV files with the same
mechanics: atomic rewrites, typed round-tripping, key-based upserts, sparse
merge, and sorted output. This module centralizes those mechanics while
leaving domain policy in the caller.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date as date_cls, datetime as datetime_cls
from pathlib import Path
from typing import Callable, Iterable, Sequence


@dataclass(frozen=True)
class CsvTableSpec:
    headers: Sequence[str]
    fields: Sequence[str]
    key_fields: Sequence[str]
    sort_fields: Sequence[str] = ("date",)
    sort_reverse: bool = True
    notes_field: str | None = "notes"


def date_str(value) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime_cls):
        return value.date().isoformat()
    if isinstance(value, date_cls):
        return value.isoformat()
    s = str(value).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def parse_value(value: str | None):
    if value is None or value == "":
        return None
    s = str(value)
    lower = s.strip().lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        if "." not in s and "e" not in s and "E" not in s:
            return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def serialize_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return [], []
        return header, [row for row in reader if any(c.strip() for c in row)]


def write_csv_atomic(path: Path, header: Sequence[str], rows: Iterable[Sequence]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(list(header))
        for row in rows:
            writer.writerow([serialize_value(v) for v in row])
    tmp.replace(path)


def record_key(record: dict, key_fields: Sequence[str]) -> tuple:
    return tuple(record.get(field) or "" for field in key_fields)


def sort_records(records: Iterable[dict], spec: CsvTableSpec) -> list[dict]:
    return sorted(
        records,
        key=lambda rec: tuple(rec.get(field) or "" for field in spec.sort_fields),
        reverse=spec.sort_reverse,
    )


def records_to_rows(records: Iterable[dict], fields: Sequence[str]) -> list[list]:
    return [[rec.get(field) for field in fields] for rec in records]


def sparse_upsert_records(
    existing: Iterable[dict],
    entries: Iterable[dict],
    spec: CsvTableSpec,
    *,
    sanitize: Callable[[dict], dict | None] | None = None,
    derive: Callable[[dict, dict | None], None] | None = None,
) -> tuple[list[dict], int, int]:
    """Sparse-merge entries into existing records by ``spec.key_fields``.

    Incoming ``None`` values never overwrite populated cells. ``notes`` uses
    manual-wins semantics when ``spec.notes_field`` is set: an incoming note
    only fills a missing note.
    """
    by_key = {record_key(r, spec.key_fields): dict(r) for r in existing}
    written = 0
    updated = 0
    for raw in entries or []:
        entry = dict(raw)
        if sanitize:
            entry = sanitize(entry)
            if entry is None:
                continue
        key = record_key(entry, spec.key_fields)
        if not key or key[0] in (None, ""):
            continue
        cur = by_key.get(key)
        if cur is None:
            cur = {field: entry.get(field) for field in spec.fields}
            if derive:
                derive(cur, entry)
            by_key[key] = cur
            written += 1
            continue
        changed = False
        for field in spec.fields:
            if field in spec.key_fields:
                continue
            if field == spec.notes_field:
                incoming_note = entry.get(field)
                if incoming_note and not cur.get(field):
                    cur[field] = incoming_note
                    changed = True
                continue
            value = entry.get(field)
            if value is None:
                continue
            if cur.get(field) != value:
                cur[field] = value
                changed = True
        before = dict(cur)
        if derive:
            derive(cur, entry)
            changed = changed or cur != before
        if changed:
            updated += 1
    return sort_records(by_key.values(), spec), written, updated


def replace_upsert_records(
    existing: Iterable[dict],
    entries: Iterable[dict],
    spec: CsvTableSpec,
    *,
    sanitize: Callable[[dict], dict | None] | None = None,
) -> tuple[list[dict], int, int]:
    """Replace records on key match; insert otherwise."""
    by_key = {record_key(r, spec.key_fields): dict(r) for r in existing}
    written = 0
    updated = 0
    for raw in entries or []:
        entry = dict(raw)
        if sanitize:
            entry = sanitize(entry)
            if entry is None:
                continue
        key = record_key(entry, spec.key_fields)
        if not key or key[0] in (None, ""):
            continue
        if key in by_key:
            if by_key[key] != entry:
                by_key[key] = entry
                updated += 1
        else:
            by_key[key] = entry
            written += 1
    return sort_records(by_key.values(), spec), written, updated
