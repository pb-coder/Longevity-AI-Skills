"""Execution context for person-scoped tracker operations."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class TrackerContext:
    """Explicit person/today bundle used by command-line entry points.

    Existing command-line tools still accept ``--person`` and default to the
    current date. The storage layer still resolves paths through
    ``person_paths``; keep this object small until the whole stack is ready to
    accept a threaded context.
    """

    person: str
    today: date = field(default_factory=date.today)
