"""Workout Tracker package.

The package contains behavior-compatible implementations behind the
historical skill entrypoints. Public scripts under ``shared/``,
``workout-coach/scripts/``, and ``workout-logger/scripts/`` remain as
compatibility wrappers.
"""
from __future__ import annotations

__all__ = ["TrackerContext"]

from .context import TrackerContext
