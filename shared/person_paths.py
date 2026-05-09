"""Per-person path resolver.

Single source of truth for where a person's CSV store lives. Used by
every script that needs to find files.

Layout (post-PR3a — pure CSV, no xlsx):

    Workout Tracker/                       ← WORKOUT_TRACKER_ROOT
    ├── Nihad/
    │   └── data/
    │       ├── health_metrics.csv
    │       ├── workout_sessions.csv
    │       ├── profile.csv
    │       ├── monthly/
    │       │   ├── 2026.05.csv
    │       │   └── …                      # one CSV per YYYY.MM
    │       └── swimming/                  # XML-only; absent on HL trackers
    │           ├── swim_workouts.csv
    │           └── swim_laps.csv
    ├── Fabian/
    │   └── (same; no swimming/ for HL)
    ├── Skills/
    │   └── shared/                        ← this file
    └── Export.zip / health_export_*.txt   (transient; deleted on success)

Every importer / logger / coach / maintain script accepts ``--person
<Name>`` (e.g. ``--person Nihad``) and resolves the rest via this
module. No raw filesystem paths in the CLI surface.
"""
from __future__ import annotations

from pathlib import Path

# This file lives at Workout Tracker/Skills/shared/person_paths.py.
# parents[0] = shared, [1] = Skills, [2] = Workout Tracker root.
WORKOUT_TRACKER_ROOT = Path(__file__).resolve().parents[2]


def person_dir(person: str) -> Path:
    """Return the per-person folder, e.g. ``<root>/Nihad``.

    The folder is *not* created here — callers that write should use
    ``ensure_data_dir`` instead, which creates ``<person>/data/``.
    """
    return WORKOUT_TRACKER_ROOT / person


def data_dir(person: str) -> Path:
    """Return ``<person>/data`` — the CSV store directory."""
    return person_dir(person) / "data"


def ensure_data_dir(person: str) -> Path:
    """Create ``<person>/data`` if missing and return it.

    Idempotent. The person folder itself is created as a side-effect of
    ``mkdir(parents=True)``.
    """
    d = data_dir(person)
    d.mkdir(parents=True, exist_ok=True)
    return d


def health_metrics_csv(person: str) -> Path:
    return data_dir(person) / "health_metrics.csv"


def workout_sessions_csv(person: str) -> Path:
    return data_dir(person) / "workout_sessions.csv"


def profile_csv(person: str) -> Path:
    return data_dir(person) / "profile.csv"


def monthly_dir(person: str) -> Path:
    """Per-person directory holding one CSV per month (``YYYY.MM.csv``)."""
    return data_dir(person) / "monthly"


def monthly_csv(person: str, year_month: str) -> Path:
    """Path to the per-month workout CSV (``YYYY.MM.csv``).

    ``year_month`` is the same ``YYYY.MM`` key the xlsx-era code used as
    sheet name. The CSV preserves the 18-column monthly schema; rows
    are sorted ASC by (Date, num, set), with a TOTAL row appended at
    each strength session boundary.
    """
    return monthly_dir(person) / f"{year_month}.csv"


def ensure_monthly_dir(person: str) -> Path:
    """Create ``<person>/data/monthly`` if missing and return it."""
    d = monthly_dir(person)
    d.mkdir(parents=True, exist_ok=True)
    return d


def swim_workouts_csv(person: str) -> Path:
    """Per-swim aggregate CSV under ``<person>/data/swimming/``."""
    return data_dir(person) / "swimming" / "swim_workouts.csv"


def swim_laps_csv(person: str) -> Path:
    """Per-lap detail CSV under ``<person>/data/swimming/``."""
    return data_dir(person) / "swimming" / "swim_laps.csv"


def ensure_swimming_dir(person: str) -> Path:
    """Create ``<person>/data/swimming/`` if missing and return it."""
    d = data_dir(person) / "swimming"
    d.mkdir(parents=True, exist_ok=True)
    return d