"""Monthly workout CSV schema constants."""
from __future__ import annotations

__all__ = [
    "MONTHLY_HEADERS",
    "MONTHLY_FIELDS",
    "TOTAL_LABEL",
    "DELOAD_MARKER_TEXT",
    "MONTHLY_COLS",
    "AUTO_IMPORT_NOTE",
    "CARDIO_DUPLICATE_DURATION_TOLERANCE_MIN",
    "STRENGTH_METADATA_DRIFT_THRESHOLD",
]

# ============================================================ Schema
# Order matches the historical xlsx columns A..Q plus Source — readers and
# writers across the codebase still treat column index as semantic.
# (PR4: ``Laps`` was removed in 2026-05; swim lap count is now sourced
# exclusively from ``<Person>/data/swimming/YYYY.MM.workouts.csv``. Old
# 17-col rows pad Source to None on read and self-migrate on the next
# canonicalize pass.)
# Version 2 appends optional context columns to the 18-column v1 schema.
# Prefixes remain positional and legacy rows are padded on read.
MONTHLY_SCHEMA_VERSION = 2
LEGACY_MONTHLY_COLUMN_COUNTS = (17, 18)

MONTHLY_HEADERS = [
    "SESSION", "Date", "#", "Exercise", "Set", "Reps", "kg", "Volume", "Notes",
    "Distance (km)", "Duration (min)", "Pace (min/km)", "Avg HR",
    "Active Cal", "Total Cal", "Elevation (m)", "Elapsed",
    "Source", "Gym", "Machine", "Load Basis",
]

# Internal keys mirroring header order, for dict↔row translation.
# ``source`` (added 2026-05): ``manual`` or an importer identity:
# ``apple[@HH:MM[:SS]]`` / ``gymkit:<DeviceName>[@HH:MM[:SS]]``.
# The optional time suffix is the row identity for same-day same-type
# auto-cardio workouts; it is part of the Source contract. Replaces the
# historic anti-pattern of stashing
# "auto-imported from Apple [ | source: <DeviceName>]" in the Notes
# column — pipeline-state strings belong in typed columns, not Notes.
# Pre-existing 17-col rows pad to None on read; canonicalize migrates
# them in one pass (Notes prefix → Source column; Notes returns to
# user-supplied annotations only).
MONTHLY_FIELDS = [
    "session", "date", "num", "exercise", "set", "reps", "kg", "volume", "notes",
    "distance", "duration", "pace", "avg_hr",
    "active_cal", "total_cal", "elevation_m", "elapsed",
    "source", "gym", "machine", "load_basis",
]


def supported_monthly_header(header: list[str]) -> bool:
    """Accept only current or exact append-only legacy schema prefixes."""
    return header == MONTHLY_HEADERS or any(
        header == MONTHLY_HEADERS[:n] for n in LEGACY_MONTHLY_COLUMN_COUNTS)

TOTAL_LABEL = "TOTAL"
DELOAD_MARKER_TEXT = "Deload Workout"

# Column counts useful for sanity checks.
MONTHLY_COLS = len(MONTHLY_HEADERS)


AUTO_IMPORT_NOTE = "auto-imported from Apple"
CARDIO_DUPLICATE_DURATION_TOLERANCE_MIN = 1.0
STRENGTH_METADATA_DRIFT_THRESHOLD = 0.05
