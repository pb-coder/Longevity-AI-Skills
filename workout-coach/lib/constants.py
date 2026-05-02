"""Constants and capability tables for the /coach read pipeline.

Pure data — no functions. Everything here is module-level so it can be
imported once and referenced cheaply from every analytics module.

Three groups:

- **Source capabilities**: per-data-source feature map
  (``SOURCE_CAPABILITIES``) plus the ``DEFAULT_DATA_SOURCE`` fallback for
  legacy trackers without a Profile sheet.
- **Sheet conventions**: ``MONTHLY_RE`` (the YYYY.MM sheet-name regex),
  ``DELOAD_MARKER`` (case-insensitive substring on TOTAL-row Notes),
  ``EMPTY_STREAK_STOP`` (max consecutive blank rows scanned), and
  ``TOTAL_LABEL`` (the canonical TOTAL-row exercise sentinel).
- **Volume + muscle taxonomy**: ``VOLUME_LANDMARKS`` (per-muscle MV/MEV/
  MAV/MRV bands), ``MUSCLE_ALIASES`` (database-token → snake_case key),
  ``SECTION_PRIMARY`` (## SECTION header → primary muscle), and
  ``SUBSECTION_PRIMARY_HINTS`` (subsection-substring overrides).
"""
from __future__ import annotations

import re

# Per-source capability map. The coach reads this to decide which sections of
# the report to write. ``xml`` is Apple's native zipped export (Nihad);
# ``hl_export`` is the HLExport text dump (Fabian) — much lighter, but no HRV,
# no wrist temp, no per-workout HR, no sleep stages, no Apple-aggregate RHR /
# walking HR / exercise-minute. The coach should distinguish ``unsupported``
# (data source can't provide it) from ``not yet collected`` (data source can,
# but the user hasn't logged enough yet).
SOURCE_CAPABILITIES = {
    "xml": {
        "hrv":                True,
        "wrist_temp":         True,
        "resting_hr_daily":   True,
        "walking_hr":         True,
        "sleep_stages":       True,
        "sleep_breath_dist":  True,
        "exercise_min_daily": True,
        "per_workout_hr":     True,
    },
    "hl_export": {
        "hrv":                False,
        "wrist_temp":         False,
        "resting_hr_daily":   False,
        "walking_hr":         False,
        "sleep_stages":       False,
        "sleep_breath_dist":  False,
        "exercise_min_daily": False,
        "per_workout_hr":     False,
    },
}

# Applied when the Profile sheet is missing or unset — treat the data as
# coming from XML so existing Nihad trackers (created before the Profile
# sheet existed) keep their full capability surface. New Fabian trackers
# get bootstrapped to ``hl_export`` by ``import_hl_export.py``.
DEFAULT_DATA_SOURCE = "xml"

MONTHLY_RE = re.compile(r"^\d{4}\.\d{2}$")
# Deload marker now lives on the TOTAL row's Notes column (col 9). The
# marker text is canonical "Deload Workout"; matching is case-insensitive.
DELOAD_MARKER = "deload workout"
EMPTY_STREAK_STOP = 10
TOTAL_LABEL = "TOTAL"

# Per-muscle weekly volume landmarks (hard sets). Source: references/training-
# science.md §1 + RP Strength tables. MV=maintenance, MEV=minimum effective,
# MAV=maximum adaptive, MRV=maximum recoverable. Numbers are individual and
# approximate; the coach uses them to name the band the current volume sits in.
VOLUME_LANDMARKS = {
    "chest":        {"mv": 6,  "mev": 10, "mav": 16, "mrv": 22},
    "back":         {"mv": 6,  "mev": 10, "mav": 18, "mrv": 25},
    "lats":         {"mv": 6,  "mev": 10, "mav": 16, "mrv": 22},
    "quads":        {"mv": 6,  "mev": 10, "mav": 18, "mrv": 22},
    "hamstrings":   {"mv": 4,  "mev": 8,  "mav": 14, "mrv": 18},
    "glutes":       {"mv": 4,  "mev": 8,  "mav": 14, "mrv": 18},
    "front_delts":  {"mv": 4,  "mev": 6,  "mav": 12, "mrv": 16},
    "side_delts":   {"mv": 6,  "mev": 8,  "mav": 16, "mrv": 22},
    "rear_delts":   {"mv": 6,  "mev": 8,  "mav": 16, "mrv": 22},
    "biceps":       {"mv": 5,  "mev": 8,  "mav": 14, "mrv": 20},
    "triceps":      {"mv": 4,  "mev": 6,  "mav": 12, "mrv": 18},
    "calves":       {"mv": 6,  "mev": 8,  "mav": 16, "mrv": 22},
    "forearms":     {"mv": 2,  "mev": 4,  "mav": 8,  "mrv": 12},
    "abs":          {"mv": 0,  "mev": 4,  "mav": 16, "mrv": 25},
    "core":         {"mv": 0,  "mev": 4,  "mav": 16, "mrv": 25},
    "erectors":     {"mv": 2,  "mev": 4,  "mav": 10, "mrv": 16},
    "traps":        {"mv": 2,  "mev": 4,  "mav": 10, "mrv": 16},
    "adductors":    {"mv": 0,  "mev": 2,  "mav": 8,  "mrv": 12},
    "neck":         {"mv": 0,  "mev": 2,  "mav": 6,  "mrv": 12},
}

# Canonicalise the muscle tokens that appear in exercises-database.md to the
# snake_case keys used everywhere else (and in VOLUME_LANDMARKS).
MUSCLE_ALIASES = {
    "chest": "chest", "upper chest": "upper_chest",
    "back": "back", "lats": "lats",
    "biceps": "biceps", "triceps": "triceps",
    "quads": "quads", "hamstrings": "hamstrings",
    "glutes": "glutes", "adductors": "adductors",
    "calves": "calves", "forearms": "forearms",
    "abs": "abs", "core": "core",
    "erectors": "erectors", "traps": "traps",
    "neck": "neck",
    "front delt": "front_delts", "front delts": "front_delts",
    "side delt": "side_delts",  "side delts":  "side_delts",
    "rear delt": "rear_delts",  "rear delts":  "rear_delts",
    "external rotators": "external_rotators",
    "shoulders": "shoulders",   "full body": "full_body",
    "posterior chain": None,    # too broad to assign — skip as primary
}

# Which ## SECTION header implies which primary muscle. None means "use
# subsection hint or parenthetical override". SHOULDERS is deliberately None
# because its subsections route to specific delt regions.
SECTION_PRIMARY = {
    "WARMUP": None, "CARDIO": None, "FULL BODY": None, "FULL BODY (COMPOUND)": None,
    "CHEST": "chest", "BACK": "back",
    "SHOULDERS": None,
    "BICEPS": "biceps", "TRICEPS": "triceps",
    "QUADS": "quads", "HAMSTRINGS": "hamstrings",
    "GLUTES": "glutes", "ADDUCTORS": "adductors",
    "CALVES": "calves", "CORE": "core",
    "NECK": "neck",
}

# Subsection hints that override the section heading (used inside SHOULDERS
# and for the stray "Forearms" subsection under BICEPS). Matched by substring
# against the lowercased subsection header.
SUBSECTION_PRIMARY_HINTS = [
    ("lateral delt", "side_delts"),
    ("rear delt",    "rear_delts"),
    ("vertical push","front_delts"),  # overhead press etc. primarily hit front delts
    ("traps",        "traps"),
    ("forearms",     "forearms"),
]
