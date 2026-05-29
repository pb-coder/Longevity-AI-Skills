"""canonicalize_logs.py — Rename typo'd exercise names in past monthly CSVs and
strip stale '(not in database)' notes for rows whose exercise is now canonical.

Iterates every per-month CSV (``<Person>/data/monthly/YYYY.MM.csv``),
applies the rename map (case-insensitive) to the Exercise column, and
removes '(not in database)' from the Notes column whenever the
(post-rename) exercise name is in the canonical exercises-database.md.
After all edits, calls ``canonicalize_monthly_csv`` so SESSION
numbering, sort, and TOTAL rows self-heal.

Ambiguous names (e.g. bare 'Leg Curl' which could be Lying or Seated)
are reported but not auto-renamed.

Usage:
    python3 canonicalize_logs.py --person <Person>
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if __package__ in (None, ""):
    sys.path.insert(0, str(THIS_DIR.parent))
    __package__ = "shared"

from .monthly_csv import (  # noqa: E402
    MONTHLY_HEADERS,
    canonicalize_monthly_csv,
    list_year_months,
)
from .person_paths import monthly_csv as monthly_csv_path  # noqa: E402

# --- canonical-name source --------------------------------------------------

DB_MD = THIS_DIR / "exercises-database.md"


def load_canonical_names(md_path: Path) -> set[str]:
    """Lowercased set of canonical exercise names from exercises-database.md."""
    names: set[str] = set()
    for raw in md_path.read_text().splitlines():
        s = raw.rstrip()
        if not s.startswith("- "):
            continue
        body = s[2:].strip()
        if body.startswith("(") or ":" in body.split("[", 1)[0]:
            continue
        if "[" in body:
            head = body.split("[", 1)[0]
        elif "—" in body:
            head = body.split("—", 1)[0]
        else:
            head = body
        head = head.strip()
        if head:
            names.add(head.lower())
    return names


# --- rename rules -----------------------------------------------------------

RENAMES: dict[str, str] = {
    "deadhang": "Dead Hang",
    "dead hang": "Dead Hang",
    "dips": "Dip",
    "triceps pushdown": "Cable Tricep Pushdown",
    "tricep pushdown": "Cable Tricep Pushdown",
    "scapular pull ups": "Scapular Pull-Up",
    "scapular pullups": "Scapular Pull-Up",
    "hanging leg raise": "Leg Raise",
    "lying leg curl": "Leg Curl (Lying)",
    "stomach crunch": "Ab Crunch Machine",
    "stomach crunches": "Ab Crunch Machine",
    "crunch": "Ab Crunch Machine",
    "stomach press": "Ab Crunch Machine",
    "stomach press vertical": "Ab Crunch Machine",
    "stomach press vertical machine": "Ab Crunch Machine",
}

AMBIGUOUS = {"leg curl"}

RENAME_NOTE: dict[str, str] = {
    "hanging leg raise": "hanging",
}

NOT_IN_DB_RE = re.compile(r"\s*\(\s*not in database\s*\)\s*", re.IGNORECASE)

# Column indices (0-based) in the per-month CSV.
EXERCISE_IDX = MONTHLY_HEADERS.index("Exercise")
NOTES_IDX = MONTHLY_HEADERS.index("Notes")


# --- core --------------------------------------------------------------------

def canonicalize_csv(path: Path, canonical: set[str]) -> tuple[int, int, list[tuple[int, str]]]:
    """Apply renames and clear stale notes on a single per-month CSV.

    Returns (renamed_count, cleared_notes_count, ambiguous_rows).
    ``ambiguous_rows`` is [(row_idx, original_name)] for caller-side
    reporting.
    """
    renamed = 0
    cleared = 0
    ambiguous: list[tuple[int, str]] = []

    if not path.exists():
        return renamed, cleared, ambiguous

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        rows = list(reader)
    if header != MONTHLY_HEADERS:
        return renamed, cleared, ambiguous

    for i, row in enumerate(rows):
        if len(row) <= max(EXERCISE_IDX, NOTES_IDX):
            continue
        ex_val = row[EXERCISE_IDX]
        if not ex_val or not isinstance(ex_val, str):
            continue
        key = ex_val.strip().lower()

        if key in AMBIGUOUS:
            ambiguous.append((i + 2, ex_val))  # +2 for 1-indexed + header

        if key in RENAMES:
            row[EXERCISE_IDX] = RENAMES[key]
            renamed += 1
            note_addition = RENAME_NOTE.get(key)
            if note_addition:
                cur = (row[NOTES_IDX] or "").strip()
                if note_addition not in cur.lower():
                    row[NOTES_IDX] = (
                        note_addition if not cur else f"{cur}; {note_addition}"
                    )

        post_name = (row[EXERCISE_IDX] or "").strip().lower()
        if post_name in canonical:
            notes_val = row[NOTES_IDX]
            if isinstance(notes_val, str) and NOT_IN_DB_RE.search(notes_val):
                cleaned = NOT_IN_DB_RE.sub("", notes_val).strip().strip(";").strip()
                row[NOTES_IDX] = cleaned
                cleared += 1

    if renamed or cleared:
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
    return renamed, cleared, ambiguous


def main(person: str) -> int:
    canonical = load_canonical_names(DB_MD)
    yms = list_year_months(person)
    if not yms:
        print(f"{person}: no monthly CSVs found")
        return 0

    total_renamed = 0
    total_cleared = 0
    all_ambiguous: list[tuple[str, int, str]] = []

    for ym in yms:
        path = monthly_csv_path(person, ym)
        renamed, cleared, amb = canonicalize_csv(path, canonical)
        if renamed or cleared or amb:
            print(f"  {ym}: renamed={renamed} cleared_notes={cleared} ambiguous={len(amb)}")
        total_renamed += renamed
        total_cleared += cleared
        for r, nm in amb:
            all_ambiguous.append((ym, r, nm))
        if renamed or cleared:
            canonicalize_monthly_csv(person, ym)

    print(f"{person}: total renamed={total_renamed} cleared_notes={total_cleared}")

    if all_ambiguous:
        print("\nAmbiguous rows (manual disambiguation needed):")
        print(f"  {'Month':<10} {'Row':>4}  Exercise (decide Lying vs Seated)")
        for ym, row, nm in all_ambiguous:
            print(f"  {ym:<10} {row:>4}  {nm}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", required=True,
                    help="Tracker owner (<Person> or <OtherPerson>).")
    args = ap.parse_args()
    sys.exit(main(args.person))
