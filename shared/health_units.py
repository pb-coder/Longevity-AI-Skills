"""Unit conversion, plausibility gating, and timestamp primitives.

Source-agnostic. These tables and gates are the single place either
import path decides what a measurement means, so a unit the tracker
cannot interpret drops in exactly one function rather than in each
caller's own way.
"""
from __future__ import annotations

import sys


def hhmm(dt):
    """Return ``HH:MM:SS`` for a datetime, preserving second-level keys."""
    if dt is None:
        return None
    return f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"


def to_float(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------- units
# Both import paths carry a unit alongside every measurement: Apple's XML
# puts it in the ``unit`` attribute, HealthAutoExport bakes it into the CSV
# column header ("Waist Circumference (cm)" vs "(in)"). Neither is
# guaranteed metric — the user's in-app unit preference decides — and
# assuming metric has already cost this repo one silent corruption (swim
# distances stored as ``550 km`` because the ``m`` unit was ignored).
# Read the unit, always. These tables are the single source of truth for
# both importers.

MASS_UNIT_TO_KG = {
    "kg": lambda v: v,
    "g": lambda v: v / 1000.0,
    "lb": lambda v: v * 0.45359237,
    "lbs": lambda v: v * 0.45359237,
    "st": lambda v: v * 6.35029318,
}

TEMP_UNIT_TO_C = {
    "degc": lambda v: v,
    "c": lambda v: v,
    "degf": lambda v: (v - 32.0) * 5.0 / 9.0,
    "f": lambda v: (v - 32.0) * 5.0 / 9.0,
}

LENGTH_UNIT_TO_CM = {
    "cm": lambda v: v,
    "mm": lambda v: v / 10.0,
    "m": lambda v: v * 100.0,
    "in": lambda v: v * 2.54,
    "inch": lambda v: v * 2.54,
    "ft": lambda v: v * 30.48,
}

# Body fat carries no real unit conversion — HealthKit and
# HealthAutoExport both label it percent, and the fraction-vs-points
# question is an *encoding* question the value itself answers (see
# normalize_body_fat_pct). The table exists anyway so that an unexpected
# token drops loudly through the same ``convert_unit`` path the waist and
# mass handlers use, instead of being waved through as if it said "%".
BODY_FAT_UNITS = {
    "%": lambda v: v,
    "percent": lambda v: v,
    "pct": lambda v: v,
}

# Above this a body-fat reading is already in percentage points; at or
# below it, it is HealthKit's fraction encoding. See normalize_body_fat_pct.
BODY_FAT_FRACTION_MAX = 1.0

# ------------------------------------------------------- plausible ranges
# Applied AFTER unit conversion, per stored field.
#
# A unit table alone cannot catch a mis-encoded reading: ``Waist
# Circumference (m) = 84.5`` converts cleanly to 8450 cm and ``Lean Body
# Mass (g) = 63.2`` to 0.0632 kg, and a plain ``(cm) = 8450`` needs no
# bad unit at all. Because ``upsert_health_metrics`` is a sparse merge,
# a poisoned cell is permanent: a later import that carries the correct
# reading updates it, but one that carries *nothing* — the normal case
# for a metric measured once a week — leaves the garbage in place
# forever. Only a hand edit of the CSV recovers it. This is the same
# failure class as the swim distances once stored as ``550 km``.
#
# The bounds are a corruption gate, not a health assessment: they are
# set wide enough that no reading a human body can actually present is
# rejected, and narrow enough that an order-of-magnitude unit error
# cannot survive. Both ends are inclusive.
PLAUSIBLE_RANGES = {
    "waist_cm": (30.0, 250.0),
    "lean_body_mass_kg": (20.0, 150.0),
    # HealthAutoExport labels ``lapLength`` "m" and sends kilometres: a
    # 20 m pool arrives as ``0.02``. The importer multiplies by 1000 and
    # gates the result here, so both halves of that trap — a missing
    # x1000 and a genuinely odd pool — land as a blank cell rather than
    # a Laps count divided by 0.02.
    "swim_pool_length_m": (10.0, 60.0),
    # Essential fat is ~3% (men) and a fraction never exceeds 1.0, so the
    # floor also closes the fraction-heuristic dead zone: a raw reading in
    # (1.0, 3.0) is neither a plausible percentage nor a fraction this
    # code will scale, and now drops loudly instead of storing "2%".
    "body_fat_pct": (3.0, 75.0),
}

_WARNED_UNKNOWN_UNITS: set[tuple[str, str]] = set()


def reset_unit_warnings() -> None:
    """Clear the warn-once registry used by ``convert_unit``.

    Production keeps warn-once semantics: an unrecognised unit is a
    property of the export's header or of the user's in-app preference,
    so it repeats identically on every row and one line of stderr says
    everything. That state is process-global, which makes it a hidden
    dependency between tests — whether a test sees its warning depends
    on whether an earlier test happened to pick the same unit string.
    Tests call this in ``setUp`` so their order stops mattering.
    """
    _WARNED_UNKNOWN_UNITS.clear()


def _warn_drop(label, value, reason) -> None:
    """Emit the one-line stderr notice that accompanies every dropped value.

    Rejections are announced, never swallowed: a blank cell the user can
    see is recoverable, a silently missing reading is not.
    """
    print(f"WARN: {label} {value!r} {reason}; value skipped", file=sys.stderr)


def convert_unit(value, unit, converters, label):
    """Convert ``value`` from ``unit`` into the converter table's base unit.

    A converter table entry is either a callable or a plain multiplier.
    An unrecognised unit drops the value with a one-time stderr warning
    rather than writing it through unconverted — a blank cell is
    recoverable, a wrong number silently is not.
    """
    if value is None:
        return None
    key = (unit or "").strip().lower()
    conv = converters.get(key)
    if conv is None:
        warn_key = (label, key)
        if warn_key not in _WARNED_UNKNOWN_UNITS:
            print(f"WARN: unknown {label} unit {key!r}; value skipped", file=sys.stderr)
            _WARNED_UNKNOWN_UNITS.add(warn_key)
        return None
    return conv(value) if callable(conv) else value * conv


def plausible_or_none(value, field, label=None, unit=None):
    """Drop ``value`` unless it lands inside ``field``'s plausible range.

    Call this on the *converted* value — the range is expressed in the
    stored unit, and catching the error post-conversion is the whole
    point (see ``PLAUSIBLE_RANGES``). ``unit`` is the source unit, quoted
    back in the warning because it is usually the culprit.

    Warns on every rejection rather than once per field. An unknown unit
    is a header-level fact that repeats identically on every row, so
    ``convert_unit`` warns once; an implausible value is a property of
    that one reading, and collapsing them would hide how much of the
    import is bad.
    """
    if value is None:
        return None
    lo, hi = PLAUSIBLE_RANGES[field]
    if lo <= value <= hi:
        return value
    detail = f" after converting from {unit!r}" if unit else ""
    _warn_drop(
        label or field, value,
        f"outside the plausible {lo:g}-{hi:g} range{detail}",
    )
    return None


def normalize_body_fat_pct(value, unit="%"):
    """Return body fat in percentage points (``18.0``), never a fraction.

    **Stored unit decision: percentage points.** ``Body Fat %`` on
    health_metrics.csv holds ``18.0``, not ``0.18`` — it reads the way a
    human expects in Quick Look / Numbers and matches the existing
    ``efficiency_pct`` convention on the sleep store.

    The fraction heuristic is an **assumption, not a verified fact**.
    HealthKit's ``HKUnit.percent()`` is documented as a fraction, so an
    Apple XML export of an 18% reading *should* read
    ``value="0.18" unit="%"``, while HealthAutoExport labels its column
    ``Body Fat Percentage (%)`` over the same HealthKit quantity. No
    record of either type exists in either tracker today, so neither
    encoding has been observed here — the code cannot cite an example it
    has seen. What makes the assumption safe to act on is that the two
    encodings occupy disjoint ranges: a fraction never exceeds 1.0 and a
    real body-fat percentage never sits that low, so each reading
    identifies its own encoding regardless of which source sent it. If a
    real export ever contradicts this, the plausibility gate below turns
    the mistake into a dropped cell and a warning, not a stored number.

    ``unit`` is read and gated, symmetrically with the waist and lean-mass
    handlers: an unexpected token drops the value instead of having it
    quietly treated as percent. Every rejection warns; only an absent
    value (``None`` / blank) is silent, because that means "no reading",
    not "bad reading".
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    v = to_float(value)
    if v is None:
        _warn_drop("body fat percentage", value, "is not a number")
        return None
    v = convert_unit(v, unit or "%", BODY_FAT_UNITS, "body fat percentage")
    if v is None:
        return None  # convert_unit already warned about the unit
    if v <= BODY_FAT_FRACTION_MAX:
        v *= 100.0
    return plausible_or_none(round(v, 2), "body_fat_pct", "body fat percentage")
