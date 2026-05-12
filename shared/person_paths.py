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
    │       ├── swimming/                  # XML-only; absent on HL trackers
    │       │   ├── YYYY.MM.workouts.csv
    │       │   └── YYYY.MM.laps.csv
    │       ├── sleep/                     # XML-only; absent on HL trackers
    │       │   └── YYYY.MM.nights.csv
    │       └── thermal/                   # manual /log only; absent until first sauna / cold log
    │           └── YYYY.MM.sessions.csv
    ├── Fabian/
    │   └── (same; no swimming/, sleep/, or thermal/ until populated)
    ├── Skills/
    │   └── shared/                        ← this file
    ├── Export.zip / health_export_*.txt   (transient; archived on success)
    └── .processed/                        ← consumed export archive

Every importer / logger / coach / maintain script accepts ``--person
<Name>`` (e.g. ``--person Nihad``) and resolves the rest via this
module. No raw filesystem paths in the CLI surface.
"""
from __future__ import annotations

from datetime import datetime
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
    sheet name. The CSV uses the canonical 17-column monthly schema
    (Laps column retired 2026-05); rows are sorted ASC by
    (Date, num, set), with a TOTAL row appended at each strength
    session boundary.
    """
    return monthly_dir(person) / f"{year_month}.csv"


def ensure_monthly_dir(person: str) -> Path:
    """Create ``<person>/data/monthly`` if missing and return it."""
    d = monthly_dir(person)
    d.mkdir(parents=True, exist_ok=True)
    return d


def swim_workouts_csv(person: str, year_month: str) -> Path:
    """Per-month swim-aggregate CSV under ``<person>/data/swimming/``.

    Naming pattern mirrors ``monthly/YYYY.MM.csv`` so the swim store
    stays sustainable as sessions accumulate (single-file store retired
    in PR5, 2026-05): ``<person>/data/swimming/YYYY.MM.workouts.csv``.
    """
    return data_dir(person) / "swimming" / f"{year_month}.workouts.csv"


def swim_laps_csv(person: str, year_month: str) -> Path:
    """Per-month swim-lap detail CSV under ``<person>/data/swimming/``.

    ``<person>/data/swimming/YYYY.MM.laps.csv``.
    """
    return data_dir(person) / "swimming" / f"{year_month}.laps.csv"


def ensure_swimming_dir(person: str) -> Path:
    """Create ``<person>/data/swimming/`` if missing and return it."""
    d = data_dir(person) / "swimming"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_swim_workout_months(person: str) -> list[str]:
    """Return ``YYYY.MM`` keys for which a per-month swim-workouts CSV exists, ASC."""
    d = data_dir(person) / "swimming"
    if not d.exists():
        return []
    import re as _re
    return sorted(
        p.name[:-len(".workouts.csv")]
        for p in d.glob("*.workouts.csv")
        if _re.match(r"^\d{4}\.\d{2}\.workouts\.csv$", p.name)
    )


def list_swim_lap_months(person: str) -> list[str]:
    """Return ``YYYY.MM`` keys for which a per-month swim-laps CSV exists, ASC."""
    d = data_dir(person) / "swimming"
    if not d.exists():
        return []
    import re as _re
    return sorted(
        p.name[:-len(".laps.csv")]
        for p in d.glob("*.laps.csv")
        if _re.match(r"^\d{4}\.\d{2}\.laps\.csv$", p.name)
    )


def sleep_nights_csv(person: str, year_month: str) -> Path:
    """Per-month sleep nights CSV under ``<person>/data/sleep/``.

    ``<person>/data/sleep/YYYY.MM.nights.csv``. One row per wake-up
    date with the full 6-stage breakdown, Time in Bed, Sleep
    Efficiency, fragmentation count, and first/last segment clock
    times.
    """
    return data_dir(person) / "sleep" / f"{year_month}.nights.csv"


def ensure_sleep_dir(person: str) -> Path:
    """Create ``<person>/data/sleep/`` if missing and return it."""
    d = data_dir(person) / "sleep"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_sleep_night_months(person: str) -> list[str]:
    """Return ``YYYY.MM`` keys for which a per-month sleep-nights CSV exists, ASC."""
    d = data_dir(person) / "sleep"
    if not d.exists():
        return []
    import re as _re
    return sorted(
        p.name[:-len(".nights.csv")]
        for p in d.glob("*.nights.csv")
        if _re.match(r"^\d{4}\.\d{2}\.nights\.csv$", p.name)
    )


def thermal_sessions_csv(person: str, year_month: str) -> Path:
    """Per-month thermal (sauna + cold exposure) sessions CSV.

    ``<person>/data/thermal/YYYY.MM.sessions.csv``. One row per heat
    and/or cold protocol session. Manual-/log-only — Apple Health
    doesn't expose sauna or cold-exposure sessions reliably.
    """
    return data_dir(person) / "thermal" / f"{year_month}.sessions.csv"


def ensure_thermal_dir(person: str) -> Path:
    """Create ``<person>/data/thermal/`` if missing and return it."""
    d = data_dir(person) / "thermal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_thermal_session_months(person: str) -> list[str]:
    """Return ``YYYY.MM`` keys for which a per-month thermal-sessions CSV exists, ASC."""
    d = data_dir(person) / "thermal"
    if not d.exists():
        return []
    import re as _re
    return sorted(
        p.name[:-len(".sessions.csv")]
        for p in d.glob("*.sessions.csv")
        if _re.match(r"^\d{4}\.\d{2}\.sessions\.csv$", p.name)
    )


def archive_processed_export(path: Path) -> Path:
    """Move a consumed Apple/HL export into ``<root>/.processed/`` and
    return its new path.

    Used in place of ``unlink()`` so a downstream bug that damages the
    monthly CSVs leaves the source file recoverable. On basename
    collision the archived copy is suffixed with the move timestamp
    (``health_export_….txt`` → ``health_export_….txt.20260509T114205``).
    Idempotent in spirit — the destination directory is created on
    demand.
    """
    archive_dir = WORKOUT_TRACKER_ROOT / ".processed"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / path.name
    if dest.exists():
        dest = archive_dir / f"{path.name}.{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    path.replace(dest)
    return dest