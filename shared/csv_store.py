"""Compatibility facade for CSV-backed tracker stores.

The implementation is split by data domain:
- ``csv_store_profile``: profile key/value store.
- ``csv_store_dense``: dense health metrics and workout sessions.
- ``csv_store_periodic``: monthly/periodic swim, sleep, thermal, light, and nutrition stores.

Keep importing ``csv_store`` from scripts and tests; new code should place
behavior in the focused modules above.
"""
from __future__ import annotations

from .csv_store_common import (  # noqa: F401
    CsvTableSpec,
    _date_str,
    _parse_value,
    _read_csv_rows,
    _serialize_value,
    _write_csv,
    ensure_data_dir_for,
    replace_upsert_records,
    sparse_upsert_records,
)
from .csv_store_dense import (  # noqa: F401
    HEALTH_METRICS_FIELDS_BY_SOURCE,
    HEALTH_METRICS_HEADERS_BY_SOURCE,
    STRENGTH_METADATA_DRIFT_THRESHOLD,
    WORKOUT_SESSIONS_FIELDS_BY_SOURCE,
    WORKOUT_SESSIONS_HEADERS_BY_SOURCE,
    read_health_metrics,
    read_workout_sessions,
    upsert_health_metrics,
    upsert_workout_sessions,
)
from .csv_store_periodic import (  # noqa: F401
    COLD_TYPES,
    HEATED_CABIN_AMBIENT_TEMP_C,
    HEAT_TYPES,
    HEAT_TYPE_DEFAULT_TEMP_C,
    LIGHT_BODY_AREAS,
    LIGHT_MODALITIES,
    LIGHT_THERAPY_SESSIONS_FIELDS,
    LIGHT_THERAPY_SESSIONS_HEADERS,
    LIGHT_TYPES,
    NUTRITION_PHASES_FIELDS,
    NUTRITION_PHASES_HEADERS,
    NUTRITION_PHASE_TYPES,
    SLEEP_NIGHTS_FIELDS,
    SLEEP_NIGHTS_HEADERS,
    SWIM_LAPS_FIELDS,
    SWIM_LAPS_HEADERS,
    SWIM_WORKOUTS_FIELDS,
    SWIM_WORKOUTS_HEADERS,
    THERMAL_SESSIONS_FIELDS,
    THERMAL_SESSIONS_HEADERS,
    read_light_therapy_sessions,
    read_nutrition_phases,
    read_sleep_nights,
    read_swim_laps,
    read_swim_workouts,
    read_thermal_sessions,
    upsert_light_therapy_sessions,
    upsert_nutrition_phases,
    upsert_sleep_nights,
    upsert_swim_laps,
    upsert_swim_workouts,
    upsert_thermal_sessions,
)
from .csv_store_profile import (  # noqa: F401
    PROFILE_DEFAULTS,
    PROFILE_KEYS,
    ensure_profile,
    read_profile,
    write_profile,
)

# Back-compat private re-exports for existing scripts:
# - ``shared/maintain.py`` imports ``_resolve_source``.
# - ``shared/import_health_auto_export.py`` imports ``_write_csv``.
from .csv_store_dense import _resolve_source  # noqa: F401,E402

__all__ = [
    "CsvTableSpec",
    "ensure_data_dir_for",
    "replace_upsert_records",
    "sparse_upsert_records",
    "HEALTH_METRICS_FIELDS_BY_SOURCE",
    "HEALTH_METRICS_HEADERS_BY_SOURCE",
    "STRENGTH_METADATA_DRIFT_THRESHOLD",
    "WORKOUT_SESSIONS_FIELDS_BY_SOURCE",
    "WORKOUT_SESSIONS_HEADERS_BY_SOURCE",
    "read_health_metrics",
    "read_workout_sessions",
    "upsert_health_metrics",
    "upsert_workout_sessions",
    "COLD_TYPES",
    "HEATED_CABIN_AMBIENT_TEMP_C",
    "HEAT_TYPES",
    "HEAT_TYPE_DEFAULT_TEMP_C",
    "LIGHT_BODY_AREAS",
    "LIGHT_MODALITIES",
    "LIGHT_THERAPY_SESSIONS_FIELDS",
    "LIGHT_THERAPY_SESSIONS_HEADERS",
    "LIGHT_TYPES",
    "NUTRITION_PHASES_FIELDS",
    "NUTRITION_PHASES_HEADERS",
    "NUTRITION_PHASE_TYPES",
    "SLEEP_NIGHTS_FIELDS",
    "SLEEP_NIGHTS_HEADERS",
    "SWIM_LAPS_FIELDS",
    "SWIM_LAPS_HEADERS",
    "SWIM_WORKOUTS_FIELDS",
    "SWIM_WORKOUTS_HEADERS",
    "THERMAL_SESSIONS_FIELDS",
    "THERMAL_SESSIONS_HEADERS",
    "read_light_therapy_sessions",
    "read_nutrition_phases",
    "read_sleep_nights",
    "read_swim_laps",
    "read_swim_workouts",
    "read_thermal_sessions",
    "upsert_light_therapy_sessions",
    "upsert_nutrition_phases",
    "upsert_sleep_nights",
    "upsert_swim_laps",
    "upsert_swim_workouts",
    "upsert_thermal_sessions",
    "PROFILE_DEFAULTS",
    "PROFILE_KEYS",
    "ensure_profile",
    "read_profile",
    "write_profile",
    "_resolve_source",
    "_write_csv",
]
