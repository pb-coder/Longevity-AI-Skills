"""Backfill Time in Bed (h) and Sleep Efficiency (%) on per-night sleep
CSVs by deriving the in-bed window from the per-night segment
timestamps that Apple Health does export.

Newer iOS (iOS 16+) stopped emitting ``HKCategoryValueSleepAnalysisInBed``
segments — only the per-stage segments (AsleepCore / AsleepDeep /
AsleepREM / Awake) come through. The importer used to fill
``time_in_bed_h`` exclusively from the InBed value; when it is absent
the column ends up blank and Sleep Efficiency cannot be auto-derived.

This script fills both fields retroactively. It is idempotent: rows
already populated are skipped. It also flags rows where the derived
in-bed window would be smaller than the total sleep (a data
inconsistency that the user may want to look at, but which the script
itself does not silently mutate).

The matching segment-span fallback is also applied inside
``import_apple_health.py`` so new imports stay consistent.

Usage:
    python3 Skills/shared/backfill_sleep_efficiency.py --person <Person> [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if __package__ in (None, ""):
    sys.path.insert(0, str(_HERE.parent))
    __package__ = "shared"

from .person_paths import list_sleep_night_months, sleep_nights_csv  # noqa: E402

# Column names as they appear in the per-night CSVs. Order does not
# matter for reading; for writing we preserve the existing header.
COL_TOTAL    = "Sleep Total (h)"
COL_TIB      = "Time in Bed (h)"
COL_EFF      = "Sleep Efficiency (%)"
COL_FIRST    = "First Segment Start"
COL_LAST     = "Last Segment End"


def _to_float(v):
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_dt(v):
    """Parse the segment-timestamp format the importer writes:
    ``YYYY-MM-DD HH:MM:SS``."""
    if not v:
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def backfill_one_file(path: Path, dry_run: bool) -> dict:
    """Walk one per-month CSV. Return a counts dict."""
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    headers = rows[0].keys() if rows else None
    filled = 0
    skipped_already = 0
    skipped_no_source = 0
    skipped_inconsistent: list[str] = []
    skipped_short: list[str] = []

    for row in rows:
        total = _to_float(row.get(COL_TOTAL))
        tib   = _to_float(row.get(COL_TIB))
        eff   = _to_float(row.get(COL_EFF))
        first = _parse_dt(row.get(COL_FIRST))
        last  = _parse_dt(row.get(COL_LAST))

        if tib is not None and eff is not None:
            skipped_already += 1
            continue

        if first is None or last is None or last <= first:
            skipped_no_source += 1
            continue

        derived_tib_h = (last - first).total_seconds() / 3600.0
        if derived_tib_h <= 0:
            skipped_no_source += 1
            continue

        # Data sanity: total sleep should never exceed time-in-bed.
        # If it does, the segment timestamps are likely from a nap
        # window not the full overnight session, or the parser missed
        # a segment. Skip and flag.
        if total is not None and total > derived_tib_h + 0.05:
            skipped_inconsistent.append(row.get("Date", "?"))
            continue

        # Sleep that is shorter than two hours rarely represents an
        # overnight session; flag and skip. Naps shouldn't get
        # efficiency.
        if total is not None and total < 2.0:
            skipped_short.append(row.get("Date", "?"))
            continue

        if tib is None:
            row[COL_TIB] = round(derived_tib_h, 2)
        if eff is None and total is not None and derived_tib_h > 0:
            row[COL_EFF] = round(total / derived_tib_h * 100.0, 1)
        filled += 1

    if filled and not dry_run:
        # Write back, preserving the original header order.
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(headers) if headers else [])
            w.writeheader()
            w.writerows(rows)

    return {
        "file": path.name,
        "filled": filled,
        "already": skipped_already,
        "no_source": skipped_no_source,
        "inconsistent": skipped_inconsistent,
        "short_nap": skipped_short,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--person", required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change without writing the CSVs.")
    args = ap.parse_args()

    months = list_sleep_night_months(args.person)
    if not months:
        print(f"No sleep CSVs found for {args.person}", file=sys.stderr)
        return 1

    total_filled = 0
    total_already = 0
    total_no_source = 0
    total_inconsistent: list[str] = []
    total_short: list[str] = []
    for ym in months:
        p = sleep_nights_csv(args.person, ym)
        result = backfill_one_file(p, args.dry_run)
        total_filled += result["filled"]
        total_already += result["already"]
        total_no_source += result["no_source"]
        total_inconsistent += result["inconsistent"]
        total_short += result["short_nap"]
        print(f'  {result["file"]:24s}'
              f' filled={result["filled"]:3d}'
              f' already_set={result["already"]:3d}'
              f' no_segments={result["no_source"]:3d}'
              f' inconsistent={len(result["inconsistent"])}'
              f' short_nap={len(result["short_nap"])}')

    print()
    print(f'Total filled:        {total_filled}')
    print(f'Already populated:   {total_already}')
    print(f'No segment data:     {total_no_source}')
    if total_inconsistent:
        print(f'Skipped, total > derived TiB ({len(total_inconsistent)}):',
              ", ".join(total_inconsistent[:10]),
              "..." if len(total_inconsistent) > 10 else "")
    if total_short:
        print(f'Skipped, short nap < 2h ({len(total_short)}):',
              ", ".join(total_short[:10]),
              "..." if len(total_short) > 10 else "")
    if args.dry_run:
        print("\n[dry-run] no files were written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
