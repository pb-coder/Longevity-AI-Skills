"""Compatibility facade for dashboard CSS and JavaScript assets.

The large inline assets live in focused modules so styling and behavior
can be edited independently:
- ``render_styles.STYLESHEET``
- ``render_scripts.INLINE_JS``
"""
from __future__ import annotations

from render_scripts import INLINE_JS  # noqa: F401
from render_styles import STYLESHEET  # noqa: F401
