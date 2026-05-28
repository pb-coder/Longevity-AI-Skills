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
MONTHLY_HEADERS = [
    "SESSION", "Date", "#", "Exercise", "Set", "Reps", "kg", "Volume", "Notes",
    "Distance (km)", "Duration (min)", "Pace (min/km)", "Avg HR",
    "Active Cal", "Total Cal", "Elevation (m)", "Elapsed",
    "Source",
]

# Internal keys mirroring header order, for dict↔row translation.
# ``source`` (added 2026-05): one of ``manual`` / ``apple`` /
# ``gymkit:<DeviceName>``. Replaces the historic anti-pattern of stashing
# "auto-imported from Apple [ | source: <DeviceName>]" in the Notes
# column — pipeline-state strings belong in typed columns, not Notes.
# Pre-existing 17-col rows pad to None on read; canonicalize migrates
# them in one pass (Notes prefix → Source column; Notes returns to
# user-supplied annotations only).
MONTHLY_FIELDS = [
    "session", "date", "num", "exercise", "set", "reps", "kg", "volume", "notes",
    "distance", "duration", "pace", "avg_hr",
    "active_cal", "total_cal", "elevation_m", "elapsed",
    "source",
]

TOTAL_LABEL = "TOTAL"
DELOAD_MARKER_TEXT = "Deload Workout"

# Column counts useful for sanity checks.
MONTHLY_COLS = len(MONTHLY_HEADERS)


AUTO_IMPORT_NOTE = "auto-imported from Apple"
CARDIO_DUPLICATE_DURATION_TOLERANCE_MIN = 1.0
STRENGTH_METADATA_DRIFT_THRESHOLD = 0.05
