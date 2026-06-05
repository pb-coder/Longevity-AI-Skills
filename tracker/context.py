"""Execution context for person-scoped tracker operations."""
from __future__ import annotations

from datetime import date


class TrackerContext:
    """Explicit person/today bundle used by command-line entry points.

    Existing command-line tools still accept ``--person`` and default to the
    current date. The storage layer still resolves paths through
    ``person_paths``; keep this object small until the whole stack is ready to
    accept a threaded context.

    Implemented as a frozen ``__slots__`` class rather than a
    ``@dataclass(frozen=True)`` so the read entrypoint doesn't have to load
    the ``dataclasses`` module just to bundle two attributes. Same fields,
    same frozen semantics, same default for ``today``.
    """

    __slots__ = ("person", "today")

    def __init__(self, person: str, today: date | None = None) -> None:
        object.__setattr__(self, "person", person)
        object.__setattr__(
            self, "today", today if today is not None else date.today()
        )

    def __setattr__(self, name: str, value) -> None:
        raise AttributeError(
            f"cannot assign to field {name!r}; TrackerContext is frozen"
        )

    def __delattr__(self, name: str) -> None:
        raise AttributeError(
            f"cannot delete field {name!r}; TrackerContext is frozen"
        )

    def __eq__(self, other) -> bool:
        if not isinstance(other, TrackerContext):
            return NotImplemented
        return self.person == other.person and self.today == other.today

    def __hash__(self) -> int:
        return hash((self.person, self.today))

    def __repr__(self) -> str:
        return f"TrackerContext(person={self.person!r}, today={self.today!r})"
