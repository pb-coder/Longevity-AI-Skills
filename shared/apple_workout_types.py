"""Apple workout type mappings — single source of truth.

Used by both importers:

- ``import_apple_health.py`` (XML): Apple emits ``HKWorkoutActivityTypeRunning``
  style strings; the importer strips the prefix and the canonical names below
  are the result (``Running``, ``Hiking``, ...).
- ``import_hl_export.py`` (HLExport text): Apple emits
  ``HKWorkoutActivityType(rawValue: 35)``; ``RAWVALUE_TO_TYPE`` maps the int
  back to the same canonical name string.

Both importers feed the same downstream:

- ``CARDIO_AUTOLOG_TYPES`` — canonical names that are eligible for auto-append
  to the monthly ``YYYY.MM`` sheets when ``Profile.auto_cardio`` is True.
- ``APPLE_TO_TRACKER_EXERCISE`` — maps each auto-loggable canonical name to
  the exercise name that exists in ``shared/exercises-database.md`` under
  ``## CARDIO``.

Append-only: when a new rawValue shows up in the wild, add it here and ship.
``Unknown(rawValue:N)`` falls through if the dictionary doesn't cover it,
which is fine — the workout still lands in ``Workout Sessions``, it just
won't be auto-logged as cardio.
"""
from __future__ import annotations


# ---------------------------------------------------------- raw int → name
# Apple's HKWorkoutActivityType enum. Values seen in real exports plus a
# small set of common ones we'd autolog if encountered. See:
# https://developer.apple.com/documentation/healthkit/hkworkoutactivitytype
RAWVALUE_TO_TYPE: dict[int, str] = {
    13: "Cycling",
    24: "Hiking",
    35: "Running",
    37: "Swimming",
    50: "TraditionalStrengthTraining",
    52: "Walking",
    63: "FunctionalStrengthTraining",
    71: "MixedCardio",
    79: "HighIntensityIntervalTraining",
    80: "Yoga",
}


def rawvalue_name(raw: int | str | None) -> str:
    """Return the canonical name for an Apple rawValue, or ``Unknown(rawValue:N)``.

    Accepts int or string ``"35"``. Returns the fallback string unchanged
    so callers don't need to second-guess unknown types — they still flow
    into the Workout Sessions sheet, just without auto-cardio handling.
    """
    if raw is None:
        return "Unknown(rawValue:?)"
    try:
        i = int(raw)
    except (TypeError, ValueError):
        return f"Unknown(rawValue:{raw})"
    return RAWVALUE_TO_TYPE.get(i, f"Unknown(rawValue:{i})")


# --------------------------------------------------- auto-cardio eligibility
# Walking is excluded — incidental walks dominate the daily count and would
# pollute the monthly sheet. Strength-training types are excluded because
# Apple doesn't capture sets; the user logs those manually via /log. Yoga,
# MixedCardio, and Pilates are excluded for now (ambiguous; user can opt
# in later by editing this set).
CARDIO_AUTOLOG_TYPES: frozenset[str] = frozenset({
    "Running",
    "IndoorRunning",
    "Hiking",
    "Cycling",
    "IndoorCycling",
    "Swimming",
    "HighIntensityIntervalTraining",
})


# ------------------------------------ canonical name → tracker exercise name
# Apple uses the same activity-type enum for indoor + outdoor running /
# cycling / walking; the XML importer specialises the canonical name to
# ``IndoorRunning`` / ``IndoorCycling`` / ``IndoorWalking`` when
# ``HKIndoorWorkout=1`` metadata is present (HL .txt export doesn't carry
# this flag). Each name below must exist in ``shared/exercises-database.md``
# under ``## CARDIO``; otherwise the coach flags the monthly row as
# "(not in database)".
APPLE_TO_TRACKER_EXERCISE: dict[str, str] = {
    "Running":                       "Outdoor Run",
    "IndoorRunning":                 "Treadmill Run",
    "Hiking":                        "Hike",
    "Cycling":                       "Outdoor Cycling",
    "IndoorCycling":                 "Indoor Cycling",
    "Swimming":                      "Swim",
    "HighIntensityIntervalTraining": "HIIT",
}


# ---------------------------------------------------- swim stroke-style enum
# Apple's HKSwimmingStrokeStyle is a small int recorded per
# ``HKWorkoutEventTypeLap`` event on swim workouts. We keep the enum value
# verbatim in ``swimming/YYYY.MM.laps.csv`` (Apple's mapping is the contract; future
# iOS versions may extend this) and decode at coach-read time. See:
# https://developer.apple.com/documentation/healthkit/hkswimmingstrokestyle
HK_SWIMMING_STROKE_STYLE: dict[int, str] = {
    0: "Unknown",
    1: "Mixed",
    2: "Freestyle",
    3: "Backstroke",
    4: "Breaststroke",
    5: "Butterfly",
    6: "Kickboard",
}
