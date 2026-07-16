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
from tracker.csv_table import write_csv_atomic  # noqa: E402

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
    "lying leg curl": "Leg Curl (Lying)",
    "stomach crunch": "Ab Crunch Machine",
    "stomach crunches": "Ab Crunch Machine",
    # "Stomach Press" is a DISTINCT machine from the ab-crunch machine, not a
    # synonym for it. Collapsing the two merged one 65-85kg series with a
    # 25-35kg one into a single exercise, producing a phantom e1RM (105 kg)
    # and an uninterpretable slope. They are separate canonicals now.
    "stomach press": "Stomach Press Machine",
    "stomach press vertical": "Stomach Press Machine",
    "stomach press vertical machine": "Stomach Press Machine",
}

# Names that cannot be resolved to a canonical from the row alone. Reported,
# never guessed. A bare "crunch" is NOT listed here: it resolves to the
# `Crunch` canonical (the bodyweight movement). Deciding whether a user who
# typed "crunch" meant the machine is a LOG-time question, and it belongs to
# workout-logger/references/aliases.md, which flags it. It used to rename to
# `Ab Crunch Machine` unconditionally — that is what filed unloaded bodyweight
# sets as 0 kg machine rows and corrupted the machine's progression series.
AMBIGUOUS = {"leg curl"}

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

        # Only report when the name isn't already a resolved canonical —
        # otherwise an AMBIGUOUS entry that later becomes a catalog name
        # would be re-reported on every run and the script would never
        # converge to a clean no-op.
        if key in AMBIGUOUS and key not in canonical:
            ambiguous.append((i + 2, ex_val))  # +2 for 1-indexed + header

        # Only count a rename that actually changes the cell. Several RENAMES
        # entries exist to fix *casing* ("dead hang" -> "Dead Hang"); once a
        # row is already canonical the lookup still hits, and counting it
        # rewrote the file and reported ~20 phantom renames on every run, so
        # the script never converged to a clean no-op.
        if key in RENAMES and RENAMES[key] != ex_val:
            row[EXERCISE_IDX] = RENAMES[key]
            renamed += 1

        post_name = (row[EXERCISE_IDX] or "").strip().lower()
        if post_name in canonical:
            notes_val = row[NOTES_IDX]
            if isinstance(notes_val, str) and NOT_IN_DB_RE.search(notes_val):
                cleaned = NOT_IN_DB_RE.sub("", notes_val).strip().strip(";").strip()
                row[NOTES_IDX] = cleaned
                cleared += 1

    if renamed or cleared:
        write_csv_atomic(path, header, rows)
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
