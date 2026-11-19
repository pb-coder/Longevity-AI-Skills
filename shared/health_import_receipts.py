"""Applied Health Export Kit coverage, independent of individual measurements."""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from tracker.csv_table import write_csv_atomic

from .hek_time import local_range
from .person_paths import data_dir

_FIELDS = (
    "source", "exported_at", "export_start", "export_end",
    "applied_from", "applied_through", "imported_at", "imported_on",
)
_RECEIPT_FILE = "health_imports.csv"


def read_health_import_receipts(person: str) -> list[dict[str, str]]:
    path = data_dir(person) / _RECEIPT_FILE
    try:
        with path.open(encoding="utf-8", newline="") as reader:
            return list(csv.DictReader(reader))
    except FileNotFoundError:
        return []


def record_health_import(person: str, source: str, meta: dict,
                         since: date | None, until: date | None) -> None:
    """Record an applied range after the observation stores finish updating."""
    start, end = local_range(meta)
    applied_from = max(start.date(), since) if since else start.date()
    applied_through = min(end.date(), until) if until else end.date()
    if applied_from > applied_through:
        return

    identity = {
        "source": source,
        "exported_at": meta["exportedAt"],
        "export_start": meta["rangeStart"],
        "export_end": meta["rangeEnd"],
        "applied_from": applied_from.isoformat(),
        "applied_through": applied_through.isoformat(),
    }
    rows = read_health_import_receipts(person)
    if any(all(row.get(key) == value for key, value in identity.items()) for row in rows):
        return

    imported_at = datetime.now(timezone.utc)
    rows.append({
        **identity,
        "imported_at": imported_at.isoformat(timespec="seconds"),
        "imported_on": imported_at.astimezone(ZoneInfo(meta["timeZone"])).date().isoformat(),
    })
    write_csv_atomic(
        data_dir(person) / _RECEIPT_FILE, _FIELDS,
        ([row.get(field, "") for field in _FIELDS] for row in rows),
    )
