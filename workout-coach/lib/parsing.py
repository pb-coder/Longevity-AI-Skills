"""Parsing and coercion helpers used across the /coach read pipeline.

Every analytics module ends up needing one of these. Keeping them in a
single tiny module avoids circular imports and makes the dependency
graph clearly bottom-up: ``parsing`` depends on nothing else in
``lib/``; everything else can depend on ``parsing``.

Functions:

- ``to_float(v)`` — lenient float coercion. Returns 0.0 on None / "" /
  ``ValueError`` instead of raising. Used by the sheet readers where
  empty cells are common.
- ``to_int_or_none(v)`` — same shape but returns ``None`` for unparsable
  inputs so the JSON layer can distinguish "absent" from "zero".
- ``_parse_iso_date(s)`` — single source for the ``YYYY-MM-DD`` parse;
  returns ``None`` on failure. Replaces the duplicated try/except
  blocks that used to live throughout the read pipeline.
- ``_compact(obj)`` — recursive None-stripper applied once at the top
  before serialisation. Drops null keys; preserves ``0`` / ``""`` /
  ``False`` / empty collections (they carry meaning).
- ``parse_duration_minutes(raw)`` — accepts ``"30:00"``, ``"28:30"``,
  ``"30"``, ``30``, ``30.0`` — returns minutes as float.
- ``parse_distance_km(raw)`` — accepts plain numbers and German-decimal
  strings (``"8,79"``).
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache


def to_float(v) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def to_int_or_none(v):
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# Memoizes this hot, pure parse keyed on the date string — called 10-20k
# times per /coach run over only ~300-500 distinct date strings.
@lru_cache(maxsize=2048)
def _parse_iso_date(s) -> date | None:
    """Parse a ``YYYY-MM-DD`` string to a date, returning None on failure.

    Single replacement for the ``try: datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError: None`` pattern that was duplicated ~10× across the
    read pipeline. Accepts ``None`` (returns None) so callers can chain
    with optional date fields.
    """
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _compact(obj):
    """Recursively drop ``None``-valued keys from dicts.

    Applied once to the top-level payload before serialisation so every
    row, summary entry, and nested dict sheds its ``None`` ballast.
    ``0``, ``""``, ``False``, and empty collections are preserved —
    they carry meaning. An absent key and a key set to ``null`` are
    equivalent to an LLM reading the JSON as prose.
    """
    if isinstance(obj, dict):
        return {k: _compact(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_compact(v) for v in obj]
    return obj


def parse_duration_minutes(raw) -> float:
    """Accept '30:00', '28:30', '30', 30, 30.0 — return minutes as float."""
    if raw in (None, ""):
        return 0.0
    s = str(raw).strip()
    if ":" in s:
        parts = s.split(":")
        try:
            mm = int(parts[0])
            ss = int(parts[1]) if len(parts) > 1 else 0
            return mm + ss / 60.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_distance_km(raw) -> float:
    """Accept '5', '5.0', '8,79' (German decimal), 5, 5.0."""
    if raw in (None, ""):
        return 0.0
    s = str(raw).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0
