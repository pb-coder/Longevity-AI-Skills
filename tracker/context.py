"""Execution context for person-scoped tracker operations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


def default_root() -> Path:
    """Return the Workout Tracker root for this checked-out Skills package."""
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TrackerContext:
    """Explicit person/root/today bundle used by package-level code.

    Existing command-line tools still accept ``--person`` and default to the
    current checkout root plus ``date.today()``. This object gives refactored
    internals a single value to pass around instead of rediscovering those
    facts from module globals.
    """

    person: str
    root: Path | None = None
    today: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root or default_root()).resolve())
        object.__setattr__(self, "today", self.today or date.today())

    @property
    def person_dir(self) -> Path:
        return self.root / self.person

    @property
    def data_dir(self) -> Path:
        return self.person_dir / "data"

    @property
    def monthly_dir(self) -> Path:
        return self.data_dir / "monthly"

    def monthly_csv(self, year_month: str) -> Path:
        return self.monthly_dir / f"{year_month}.csv"

    def swim_workouts_csv(self, year_month: str) -> Path:
        return self.data_dir / "swimming" / f"{year_month}.workouts.csv"

    def swim_laps_csv(self, year_month: str) -> Path:
        return self.data_dir / "swimming" / f"{year_month}.laps.csv"

    def sleep_nights_csv(self, year_month: str) -> Path:
        return self.data_dir / "sleep" / f"{year_month}.nights.csv"

    def thermal_sessions_csv(self, year_month: str) -> Path:
        return self.data_dir / "thermal" / f"{year_month}.sessions.csv"
