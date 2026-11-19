"""Private tracker paths. See docs/WORKFLOW.md for the workspace layout."""
from __future__ import annotations

import os
from pathlib import Path

# This file lives at Workout Tracker/Skills/shared/person_paths.py.
# parents[0] = shared, [1] = Skills, [2] = Workout Tracker root.
WORKOUT_TRACKER_ROOT = Path(
    os.environ.get("WORKOUT_TRACKER_ROOT", Path(__file__).resolve().parents[2])
).resolve()


def person_dir(person: str) -> Path:
    """Return the per-person folder, e.g. ``<root>/<Person>``.

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
    sheet name. The CSV uses the canonical monthly schema
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


def nutrition_phases_csv(person: str) -> Path:
    """Per-person nutrition-phase tracker (bulk / cut / maintain / recomp).

    ``<person>/data/nutrition_phases.csv``. One row per phase, keyed by
    ``Start Date``. ``End Date`` blank ≡ the phase is still open. Manual
    /log only — no importer writes this file. Absent until the user
    starts logging phases.
    """
    return data_dir(person) / "nutrition_phases.csv"


def plans_dir(person: str) -> Path:
    """Private weekly, legacy, and block artifacts alongside the tracker data."""
    return WORKOUT_TRACKER_ROOT / "plans" / person


def ensure_plans_dir(person: str) -> Path:
    """Create ``<root>/plans/<person>`` if missing and return it."""
    d = plans_dir(person)
    d.mkdir(parents=True, exist_ok=True)
    return d


def weekly_plans_dir(person: str) -> Path:
    return plans_dir(person) / "weekly"


def list_workout_plans(person: str) -> list[tuple[str, Path]]:
    """Historical Markdown prescriptions in generation-date order."""
    import re as _re
    d = plans_dir(person)
    if not d.exists():
        return []
    pat = _re.compile(r"^(\d{4}-\d{2}-\d{2})-workout\.md$")
    out: list[tuple[str, Path]] = []
    for p in d.glob("*-workout.md"):
        m = pat.match(p.name)
        if m:
            out.append((m.group(1), p))
    out.sort(key=lambda t: t[0])
    return out


def block_json(person: str, start_date: str) -> Path:
    """Path to a training-block artifact, ``plans/<Person>/block-<start>.json``.

    ``start_date`` is the ISO date the block opened and is the block's
    identity: one file per block, never rewritten in place once the next
    block opens, so the rotation history stays auditable.
    """
    return plans_dir(person) / f"block-{start_date}.json"


def list_blocks(person: str) -> list[tuple[str, Path]]:
    """Every persisted block for ``person`` as ``(start_date, path)``, ASC."""
    import re as _re
    d = plans_dir(person)
    if not d.exists():
        return []
    pat = _re.compile(r"^block-(\d{4}-\d{2}-\d{2})\.json$")
    out: list[tuple[str, Path]] = []
    for p in d.glob("block-*.json"):
        m = pat.match(p.name)
        if m:
            out.append((m.group(1), p))
    out.sort(key=lambda t: t[0])
    return out


def bench_log_json(person: str) -> Path:
    """Path to the benched-exercise response log, ``plans/<Person>/bench-log.json``.

    D5 store. When an exercise has been prescribed twice and performed
    zero times, the coach benches it and asks WHY exactly once. The
    answer has to outlive the conversation or the next run asks again
    (and the run after that), which is how "ask once" becomes "nag
    forever". This file is that memory: one entry per benched exercise
    with the question date, the user's answer, and the disposition it
    routed to (``retired`` / ``retry``).

    It lives beside the plans rather than in ``<person>/data/`` because
    it is coach state, not tracker data — no importer writes it and no
    CSV consumer reads it.
    """
    return plans_dir(person) / "bench-log.json"
