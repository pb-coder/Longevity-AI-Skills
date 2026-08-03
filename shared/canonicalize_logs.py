"""canonicalize_logs.py — Rename typo'd exercise names in past monthly CSVs,
strip stale '(not in database)' notes, and move hold / carry times out of
Notes into the typed ``Duration (min)`` column.

Iterates every per-month CSV (``<Person>/data/monthly/YYYY.MM.csv``),
applies the rename map (case-insensitive) to the Exercise column,
removes '(not in database)' from the Notes column whenever the
(post-rename) exercise name is in the canonical exercises-database.md,
and backfills ``Duration (min)`` for rep-less hold / carry rows whose
time was written to Notes instead. After all edits, calls
``canonicalize_monthly_csv`` so SESSION numbering, sort, and TOTAL rows
self-heal.

Nothing is guessed, and nothing is skipped in silence. Ambiguous names
(e.g. bare 'Leg Curl' which could be Lying or Seated) are reported and
left alone, as is any note whose time cannot be recovered safely: one
that names no time ('max hold'), one whose number is a pace or a rest
rather than work ('5:30 pace', 'rest 90s between sets'), one that holds
two per-side times that must not be collapsed, and one carrying a token
this parser will not convert ('3x30s', '30m each hand').

Renames apply to user-owned rows only. An importer-written row keeps its
own Exercise cell; rewriting one would just be undone by the next import.

Re-runnable: a second pass over a cleaned file is a no-op.

Usage:
    python3 canonicalize_logs.py --person <Person> [--dry-run]
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
    _format_duration_mmss,
    _parse_duration_minutes,
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
    # Casing fixes: a lowercase second word split the same lift across two
    # keys downstream (e.g. estimated_1rm kept the raw "Leg extension" while
    # progression_summary title-cased to "Leg Extension"), so the two signals
    # no longer joined. Normalize the stored name to the canonical casing.
    "leg extension": "Leg Extension",
    "arm circles": "Arm Circles",
    "high knees": "High Knees",
    "jumping jacks": "Jumping Jacks",
    # Orphan cardio name with no catalog match — the erg is "Rowing Machine".
    # "Rowing" is absent from apple_workout_types.CARDIO_AUTOLOG_TYPES, so the
    # auto-cardio path will not emit it into a monthly CSV. That is NOT the
    # same as "no importer emits it": <Person>'s workout_sessions.csv holds
    # four Apple `Rowing` sessions (three in July 2026) and one Apple-sourced
    # `Rowing` row already sits in a monthly CSV. Renaming an importer-owned
    # row means fighting its writer on the next import, so RENAMES is gated on
    # Source below — same gate the duration backfill uses.
    "rowing": "Rowing Machine",
}

# A rename only ever touches a row the user owns. Importer-written rows carry
# an importer identity in `Source` (`apple` / `gymkit:<Device>`, optionally
# with an `@HH:MM` suffix); rewriting one puts this script in a rename war with
# the next import, and the honest outcome for an unmapped importer name is that
# it surfaces in `unknown_exercises` instead.


def _is_manual_row(source_value: str) -> bool:
    """True when the row is user-owned (blank or `manual` Source)."""
    source = (source_value or "").strip().lower()
    return not source or source == "manual"


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
REPS_IDX = MONTHLY_HEADERS.index("Reps")
DURATION_IDX = MONTHLY_HEADERS.index("Duration (min)")
DISTANCE_IDX = MONTHLY_HEADERS.index("Distance (km)")
SOURCE_IDX = MONTHLY_HEADERS.index("Source")


# --- hold / carry time backfill ---------------------------------------------
#
# `/log` is supposed to write hold and carry time to `Duration (min)`
# (`workout-logger/references/parsing-rules.md`, "Holds and carries"). It
# historically wrote strings like "30s hold" to Notes instead. That is two
# bugs at once: `sessions.py::_is_working_set` only counts a `reps == 0`
# row when `duration_min > 0`, so the set scores zero; and a string that
# repeats across ~20 rows is a category, not an annotation, which is the
# Notes-hygiene rule in `Skills/CLAUDE.md`.

# One duration token. Bare "m" is deliberately NOT a minutes unit — on a
# carry row it means metres, and guessing wrong turns 30 metres into 30
# minutes.
#
# The ``H:MM:SS`` branch must come FIRST. Without it ``"1:00:00"`` matched the
# ``MM:SS`` branch on its leading ``1:00``, wrote a one-minute hold for a
# one-hour value (wrong by 60x) and left ``"00"`` behind in Notes.
# ``parsing-rules.md`` already promises ``H:MM:SS`` support, so parse it.
_DUR_TOKEN_RE = re.compile(
    r"(?<![\w.])"
    r"(?:"
    r"(?P<h>\d{1,2}):(?P<h_min>[0-5]\d):(?P<h_sec>[0-5]\d)"  # 1:00:00
    r"|(?P<mmss_min>\d{1,2}):(?P<mmss_sec>[0-5]\d)(?![:\d])"  # 1:30
    r"|(?P<sec>\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)\b"
    r"|(?P<min>\d+(?:\.\d+)?)\s*(?:min|mins|minute|minutes)\b"
    r")",
    re.IGNORECASE,
)

# Anything time-or-distance shaped, with none of the guards above: no
# preceding-character lookbehind (so ``3x30s`` is seen) and bare ``m``
# included (so ``30m each hand`` is seen). Nothing here is ever converted —
# it exists purely so an unconvertible token is REPORTED instead of the row
# being skipped in silence, which is how ``3x30s`` and ``30m each hand``
# vanished without a line of output.
_LOOSE_TIMEISH_RE = re.compile(
    r"\d+(?:\.\d+)?\s*"
    r"(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes"
    r"|metre|metres|meter|meters)\b"
    r"|\d{1,2}:\d{2}",
    re.IGNORECASE,
)

# Notes that describe a hold / carry but may name no time.
_HOLD_WORD_RE = re.compile(
    r"\b(hold|holds|held|hang|hanging|carry|carries|isometric)\b",
    re.IGNORECASE,
)

# Words that re-purpose a nearby number as something OTHER than work time.
# ``"5:30 pace"`` is a speed and ``"rest 90s between sets"`` is recovery; both
# parsed cleanly and both became Duration (min), i.e. credited work. There is
# no safe way to convert a note carrying one of these, so the row is reported
# and left alone — the module's standing contract ("nothing is guessed").
_CONTEXT_WORD_RE = re.compile(
    r"\b(pace|paces|rest|rests|rested|resting|break|breaks|between"
    r"|tempo|cadence|rpm|spm|per\s*km|min/km)\b",
    re.IGNORECASE,
)

# Laterality markers. With TWO time tokens present these mean two separate
# holds, one per side — ``"left side 30s right side 30s"`` is a minute of work
# in two rows' worth of prescription, and collapsing it to a single ``0:30``
# throws half of it away. With ONE token there is nothing to lose and the
# marker is just prose, which is the ``"40sec per side"`` case parsing-rules.md
# documents.
_SIDE_MARKER_RE = re.compile(
    r"\b(each|per|both|either|left|right|alternating|alt)\b"
    r"|\bl/r\b|\br/l\b",
    re.IGNORECASE,
)

# Residue that carries no information once the time is extracted.
#
# ``each`` and ``x`` are NOT filler: stripping ``each`` reduced
# ``"30s hold each side"`` to the bare word ``"side"``, which is worse than
# leaving the note alone. Only words that are pure restatements of "this was a
# hold" belong here.
_FILLER_WORDS = "hold|holds|held|hang|hanging|isometric|carry|for"
_EMPTY_RESIDUE = {""} | set(_FILLER_WORDS.split("|"))
_LEADING_FILLER_RE = re.compile(rf"^(?:{_FILLER_WORDS})\b[\s,;:.-]*",
                                re.IGNORECASE)
_TRAILING_FILLER_RE = re.compile(rf"[\s,;:.-]*\b(?:{_FILLER_WORDS})$",
                                 re.IGNORECASE)

# A plausible per-set hold or carry, in minutes. Above this it is almost
# certainly a mis-parse (a session length, a pace, a distance, a heart rate).
# 60 was far too generous: a 20-minute upper bound is already well past any
# real plank, dead hang, or loaded carry, and it turns a mis-read session
# length such as ``"1:00:00"`` into a report instead of a silent write.
MAX_HOLD_MIN = 20.0


def _tidy_residue(text: str) -> str:
    """Clean up what is left of a Note after the time has been excised.

    Collapses whitespace, strips separator debris, then drops a leading or
    trailing filler word — ``"30s hold, felt easy"`` leaves ``"felt easy"``,
    not ``"hold, felt easy"``. Filler is only removed at the edges; a word
    in the middle of a sentence is the user's prose and stays.
    """
    s = re.sub(r"\s+", " ", text).strip()
    s = s.strip(" ,;:.-–—x×").strip()
    prev = None
    while s and s != prev:
        prev = s
        s = _LEADING_FILLER_RE.sub("", s)
        s = _TRAILING_FILLER_RE.sub("", s)
        s = s.strip(" ,;:.-–—").strip()
    return re.sub(r"\s+", " ", s).strip()


def extract_hold_duration(notes: str) -> tuple[float | None, str, str | None]:
    """Pull a single hold / carry duration out of a Notes string.

    Returns ``(minutes, remaining_notes, ambiguity_reason)``.

    - ``minutes`` is set only when exactly one unambiguous token is found.
    - ``ambiguity_reason`` is set when the note is *about* a hold but the
      time cannot be recovered safely. Both are never set together, and a
      note with neither is simply not a hold note.

    Refusals, each one a demonstrated mis-conversion rather than a
    hypothetical:

    ==============================  ================================
    Note                            Outcome
    ==============================  ================================
    ``1:00:00``                     60 min, over ``MAX_HOLD_MIN`` →
                                    reported (used to write ``1:00``)
    ``5:30 pace``                   pace context → reported
    ``rest 90s between sets``       rest context → reported
    ``left side 30s right side      two per-side holds → reported
    30s``
    ``3x30s``                       set-count prefix → reported
    ``30m each hand``               bare ``m`` ambiguous → reported
    ``30s hold each side``          ``0:30`` + Notes ``each side``
    ==============================  ================================
    """
    text = notes or ""
    matches = list(_DUR_TOKEN_RE.finditer(text))
    if not matches:
        loose = _LOOSE_TIMEISH_RE.search(text)
        if loose:
            return None, text, (
                f"unconverted duration-shaped token {loose.group(0)!r} "
                f"(bare 'm' is ambiguous, and a set-count prefix such as "
                f"'3x30s' describes several rows, not one)"
            )
        if _HOLD_WORD_RE.search(text):
            return None, text, "hold note names no time"
        return None, text, None

    context = _CONTEXT_WORD_RE.search(text)
    if context:
        return None, text, (
            f"{context.group(0)!r} makes this a pace / rest, not work time"
        )

    values: list[float] = []
    for m in matches:
        if m.group("h") is not None:
            values.append(int(m.group("h")) * 60
                          + int(m.group("h_min"))
                          + int(m.group("h_sec")) / 60.0)
        elif m.group("mmss_min") is not None:
            values.append(int(m.group("mmss_min"))
                          + int(m.group("mmss_sec")) / 60.0)
        elif m.group("sec") is not None:
            values.append(float(m.group("sec")) / 60.0)
        else:
            values.append(float(m.group("min")))

    if len({round(v, 6) for v in values}) > 1:
        return None, text, f"{len(matches)} different durations in one note"

    if len(matches) > 1 and _SIDE_MARKER_RE.search(text):
        return None, text, (
            f"{len(matches)} per-side durations; collapsing them to one "
            f"would drop {len(matches) - 1}"
        )

    minutes = values[0]
    if not 0 < minutes <= MAX_HOLD_MIN:
        return None, text, (
            f"implausible duration {minutes:.2f} min "
            f"(max {MAX_HOLD_MIN:g} for a single hold or carry)"
        )

    # Excise every occurrence (they all carry the same value).
    remaining = text
    for m in reversed(matches):
        remaining = remaining[:m.start()] + " " + remaining[m.end():]
    remaining = _tidy_residue(remaining)
    if remaining.lower() in _EMPTY_RESIDUE:
        remaining = ""
    return minutes, remaining, None


def _is_repless(value: str) -> bool:
    """True when the Reps cell is blank or zero."""
    s = (value or "").strip()
    if not s:
        return True
    try:
        return float(s.replace(",", ".")) == 0
    except ValueError:
        return False


# --- core --------------------------------------------------------------------

def canonicalize_csv(path: Path, canonical: set[str],
                     dry_run: bool = False) -> dict:
    """Apply renames, clear stale notes, and backfill hold durations.

    Returns a report dict::

        {"renamed": int, "cleared": int, "durations": int,
         "ambiguous": [(row_idx, name)],
         "duration_moves": [(row_idx, exercise, old_notes, mmss, new_notes)],
         "duration_ambiguous": [(row_idx, exercise, notes, reason)]}

    ``row_idx`` is the 1-indexed spreadsheet row (header counted), so it
    lines up with what the user sees opening the CSV. With ``dry_run``
    nothing is written; the report is identical either way.
    """
    report: dict = {
        "renamed": 0, "cleared": 0, "durations": 0,
        "ambiguous": [], "duration_moves": [], "duration_ambiguous": [],
    }

    if not path.exists():
        return report

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        rows = list(reader)
    if header != MONTHLY_HEADERS:
        return report

    renamed = 0
    cleared = 0
    durations = 0
    ambiguous: list[tuple[int, str]] = report["ambiguous"]

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
        # A short legacy (17-col) row has no Source cell at all; the schema
        # migration pads it to blank, i.e. user-owned, so treat it that way
        # rather than freezing those rows out of the rename map.
        row_is_manual = _is_manual_row(
            row[SOURCE_IDX] if len(row) > SOURCE_IDX else "")
        if key in RENAMES and RENAMES[key] != ex_val and row_is_manual:
            row[EXERCISE_IDX] = RENAMES[key]
            renamed += 1

        post_name = (row[EXERCISE_IDX] or "").strip().lower()
        if post_name in canonical:
            notes_val = row[NOTES_IDX]
            if isinstance(notes_val, str) and NOT_IN_DB_RE.search(notes_val):
                cleaned = NOT_IN_DB_RE.sub("", notes_val).strip().strip(";").strip()
                row[NOTES_IDX] = cleaned
                cleared += 1

        # Hold / carry time stranded in Notes → Duration (min).
        moved = _backfill_row_duration(row, i + 2, report)
        if moved:
            durations += 1

    report["renamed"] = renamed
    report["cleared"] = cleared
    report["durations"] = durations
    if (renamed or cleared or durations) and not dry_run:
        write_csv_atomic(path, header, rows)
    return report


def _backfill_row_duration(row: list[str], row_no: int, report: dict) -> bool:
    """Move a parseable hold / carry time from Notes to Duration (min).

    Returns True when the row was changed. Ambiguous rows are appended to
    ``report["duration_ambiguous"]`` and left exactly as they were — this
    script never guesses, same contract as ``AMBIGUOUS`` above.
    """
    if len(row) <= max(DURATION_IDX, SOURCE_IDX):
        return False
    notes = row[NOTES_IDX] or ""
    if not notes.strip():
        return False
    # Rep-less rows only. A row with reps > 0 is a normal set whose Notes
    # may legitimately mention a tempo or a rep range.
    if not _is_repless(row[REPS_IDX]):
        return False
    # Importer-owned rows keep their own Duration cell; never rewrite one.
    if not _is_manual_row(row[SOURCE_IDX]):
        return False

    minutes, remaining, reason = extract_hold_duration(notes)
    existing = _parse_duration_minutes(row[DURATION_IDX])

    if existing is not None:
        # Duration is already typed, so there is nothing to rescue. Only a
        # genuine disagreement is worth reporting — an unparseable note on
        # an already-correct row is noise, not a finding.
        if minutes is not None and abs(existing - minutes) > 1 / 60.0:
            report["duration_ambiguous"].append(
                (row_no, row[EXERCISE_IDX], notes,
                 f"Duration already {row[DURATION_IDX]!r}, note says "
                 f"{_format_duration_mmss(minutes)}"))
        return False
    if reason:
        report["duration_ambiguous"].append(
            (row_no, row[EXERCISE_IDX], notes, reason))
        return False
    if minutes is None:
        return False

    mmss = _format_duration_mmss(minutes)
    if mmss is None:  # pragma: no cover — guarded by 0 < m <= MAX_HOLD_MIN
        return False
    row[DURATION_IDX] = mmss
    row[NOTES_IDX] = remaining
    report["duration_moves"].append(
        (row_no, row[EXERCISE_IDX], notes, mmss, remaining))
    return True


def main(person: str, dry_run: bool = False) -> int:
    canonical = load_canonical_names(DB_MD)
    yms = list_year_months(person)
    if not yms:
        print(f"{person}: no monthly CSVs found")
        return 0

    total_renamed = 0
    total_cleared = 0
    total_durations = 0
    all_ambiguous: list[tuple[str, int, str]] = []
    all_moves: list[tuple[str, int, str, str, str, str]] = []
    all_dur_ambiguous: list[tuple[str, int, str, str, str]] = []

    if dry_run:
        print(f"{person}: DRY RUN — no files will be written")

    for ym in yms:
        path = monthly_csv_path(person, ym)
        rep = canonicalize_csv(path, canonical, dry_run=dry_run)
        renamed, cleared = rep["renamed"], rep["cleared"]
        durations = rep["durations"]
        amb = rep["ambiguous"]
        if renamed or cleared or durations or amb or rep["duration_ambiguous"]:
            print(f"  {ym}: renamed={renamed} cleared_notes={cleared} "
                  f"durations_moved={durations} ambiguous="
                  f"{len(amb) + len(rep['duration_ambiguous'])}")
        total_renamed += renamed
        total_cleared += cleared
        total_durations += durations
        for r, nm in amb:
            all_ambiguous.append((ym, r, nm))
        for r, ex, old, mmss, new in rep["duration_moves"]:
            all_moves.append((ym, r, ex, old, mmss, new))
        for r, ex, notes, reason in rep["duration_ambiguous"]:
            all_dur_ambiguous.append((ym, r, ex, notes, reason))
        if (renamed or cleared or durations) and not dry_run:
            canonicalize_monthly_csv(person, ym)

    print(f"{person}: total renamed={total_renamed} "
          f"cleared_notes={total_cleared} durations_moved={total_durations}")

    if all_moves:
        verb = "would move" if dry_run else "moved"
        print(f"\nHold / carry time {verb} from Notes to Duration (min):")
        print(f"  {'Month':<10} {'Row':>4}  {'Exercise':<14} "
              f"{'Notes was':<20} -> Duration  Notes now")
        for ym, row, ex, old, mmss, new in all_moves:
            print(f"  {ym:<10} {row:>4}  {ex:<14} {old!r:<20} -> "
                  f"{mmss:<9} {new!r}")

    if all_ambiguous:
        print("\nAmbiguous rows (manual disambiguation needed):")
        print(f"  {'Month':<10} {'Row':>4}  Exercise (decide Lying vs Seated)")
        for ym, row, nm in all_ambiguous:
            print(f"  {ym:<10} {row:>4}  {nm}")

    if all_dur_ambiguous:
        print("\nHold / carry notes left alone (not guessed):")
        print(f"  {'Month':<10} {'Row':>4}  {'Exercise':<14} "
              f"{'Notes':<16} Reason")
        for ym, row, ex, notes, reason in all_dur_ambiguous:
            print(f"  {ym:<10} {row:>4}  {ex:<14} {notes!r:<16} {reason}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", required=True,
                    help="Tracker owner (<Person> or <OtherPerson>).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report every change without writing any file.")
    args = ap.parse_args()
    sys.exit(main(args.person, dry_run=args.dry_run))
