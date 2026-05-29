"""Expose ``workout-coach/lib`` as ``workout_coach.lib``.

The on-disk skill directory keeps its historical hyphenated name because
the slash-command metadata and public script paths depend on it. Python
package imports use this underscore facade instead.
"""
from __future__ import annotations

from pathlib import Path

_REAL_LIB = Path(__file__).resolve().parents[2] / "workout-coach" / "lib"
__path__ = [str(_REAL_LIB)]

