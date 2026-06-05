"""Workout Tracker package.

The package contains behavior-compatible implementations behind the
historical skill entrypoints. Public scripts under ``shared/``,
``workout-coach/scripts/``, and ``workout-logger/scripts/`` remain as
compatibility wrappers.
"""
from __future__ import annotations

__all__ = ["TrackerContext"]


def __getattr__(name):
    """Lazy-load ``TrackerContext`` on first attribute access.

    Importing ``tracker.contracts`` or ``tracker.validation`` (done by the
    render entrypoint) runs ``tracker/__init__.py`` as a side effect of
    parent-package initialization. Loading ``tracker.context`` here would
    pull in ``dataclasses`` for a subprocess that never builds a
    ``TrackerContext``. Defer the import to the first attribute lookup so
    ``from tracker import TrackerContext`` still works for the read
    entrypoint while render skips the cost.
    """
    if name == "TrackerContext":
        from .context import TrackerContext
        return TrackerContext
    raise AttributeError(f"module 'tracker' has no attribute {name!r}")
