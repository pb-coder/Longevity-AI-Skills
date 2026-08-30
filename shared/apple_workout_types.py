"""Apple workout type mappings — single source of truth.

The module keeps Apple's own name because it genuinely models Apple's
activity-type enum, which HealthAutoExport's workout names still map
onto. ``import_health_auto_export.py`` maps each export name to the
canonical string below (``Running``, ``Hiking``, ...) before anything
downstream sees it. ``RAWVALUE_TO_TYPE`` is retained for rows written by
the retired XML importer, whose ``HKWorkoutActivityTypeRunning``-style
raw values still sit in the stored history.

The canonical names feed:

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


# ------------------------------------------- Health Export Kit type names
# Health Export Kit uses its own display names and carries indoor/outdoor
# as a separate boolean, where HealthAutoExport folded both into one string
# ("Indoor Run", "Outdoor Walk"). Every pair below was confirmed by matching
# 663 stored workouts against a full-history export; no observed combination
# fell through to the fallback.
HEK_TYPE_MAP: dict[tuple[str, bool], str] = {
    ("Walking", False):            "Walking",
    ("Walking", True):             "IndoorWalking",
    ("Running", False):            "Running",
    ("Running", True):             "IndoorRunning",
    ("Cycling", False):            "Cycling",
    ("Cycling", True):             "IndoorCycling",
    ("Swimming", False):           "Swimming",
    ("Swimming", True):            "Swimming",
    ("Hiking", False):             "Hiking",
    ("Hiking", True):              "Hiking",
    ("Rowing", False):             "Rowing",
    ("Rowing", True):              "Rowing",
    ("HIIT", False):               "HighIntensityIntervalTraining",
    ("HIIT", True):                "HighIntensityIntervalTraining",
    ("Strength Training", False):  "TraditionalStrengthTraining",
    ("Strength Training", True):   "TraditionalStrengthTraining",
    ("Functional Strength", False): "FunctionalStrengthTraining",
    ("Functional Strength", True):  "FunctionalStrengthTraining",
    ("Core Training", False):      "CoreTraining",
    ("Core Training", True):       "CoreTraining",
}


def hek_canonical_type(raw: str, is_indoor: bool | None) -> str:
    """Canonical stored name for a Health Export Kit workout.

    ``is_indoor`` is absent on a small number of workouts (1 of 698 in the
    reference export); absent reads as outdoor, which is the safe default
    for every type whose indoor variant is a distinct stored name.

    An unmapped type still produces a storable name rather than raising, the
    way the retired importer handled types it had never seen: the workout
    lands in Workout Sessions, it just misses auto-cardio handling until
    someone adds it here.
    """
    indoor = bool(is_indoor)
    mapped = HEK_TYPE_MAP.get((raw, indoor))
    if mapped:
        return mapped
    return (raw or "").replace(" ", "")
