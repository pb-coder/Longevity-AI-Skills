"""Tiny formatters used across the dashboard renderer.

Every render_* module ends up needing one of these. Keeping them in a
single dependency-free module avoids circular imports: `render_helpers`
depends on nothing else in `lib/`; every other render_* module can
depend on it.

Functions:

- ``esc(s)`` — HTML-escape any value; ``None`` becomes ``""``.
- ``fmt(v, digits, default)`` — number formatter with optional decimal
  digits. Returns ``default`` (default ``"·"``) when ``v`` is ``None``
  or NaN. Integers are rendered without trailing decimals regardless of
  ``digits``.
- ``signed(v, digits, default)`` — signed number formatter (always
  prints leading ``+``/``-`` sign).
- ``parse_date(s)`` — single source for ``YYYY-MM-DD`` parsing in the
  renderer; returns ``None`` for falsy input.
"""
from __future__ import annotations

import html
import math
from datetime import datetime


def esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def fmt(v, digits=1, default="·"):
    if v is None:
        return default
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if math.isnan(v):
            return default
        if isinstance(v, int) or digits == 0:
            return f"{v:.0f}"
        return f"{v:.{digits}f}"
    return str(v)


def signed(v, digits=1, default="·"):
    if v is None:
        return default
    return f"{v:+.{digits}f}"


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None
