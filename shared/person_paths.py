"""Per-person path resolver.

Single source of truth for where a person's workout xlsx and CSV
data folder live. Used by every script that needs to find files.

Layout (post-PR1):

    Workout Tracker/                  ← WORKOUT_TRACKER_ROOT
    ├── Nihad/
    │   ├── Workout Tracker - Nihad.xlsx
    │   └── data/
    │       ├── health_metrics.csv
    │       ├── workout_sessions.csv
    │       └── profile.csv
    ├── Fabian/
    │   └── (same)
    ├── Skills/
    │   └── shared/                   ← this file
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


def tracker_for(person: str) -> Path:
    """Return the path to the person's workout xlsx.

    Naming convention preserved from the pre-migration layout
    (``Workout Tracker - <Person>.xlsx``) so git history and any
    external references survive the folder reshuffle.
    """
    return person_dir(person) / f"Workout Tracker - {person}.xlsx"


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


# Per-person legacy xlsx that may still sit at the root before the
# migration script runs. Returned by ``legacy_tracker_for`` so the
# migration helper can find it. Once migrated, this path no longer
# exists and the resolver returns ``tracker_for(person)`` exclusively.
def legacy_root_tracker_for(person: str) -> Path:
    return WORKOUT_TRACKER_ROOT / f"Workout Tracker - {person}.xlsx"