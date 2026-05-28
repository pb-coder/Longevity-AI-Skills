"""Compatibility facade for monthly workout CSV operations.

The implementation is split by responsibility:
- ``monthly_csv_schema``: schema and policy constants.
- ``monthly_csv_values``: coercion, formatting, and row classification.
- ``monthly_csv_io``: row translation and atomic file I/O.
- ``monthly_csv_canonicalize``: canonical monthly rebuilds.
- ``monthly_csv_upsert``: append/import upsert operations and discovery.

Keep public imports from ``monthly_csv`` stable.
"""
from __future__ import annotations

from monthly_csv_canonicalize import canonicalize_monthly_csv  # noqa: F401
from monthly_csv_io import (  # noqa: F401
    _dict_to_row,
    _read_csv_rows,
    _row_to_dict,
    _serialize_value,
    _write_csv_atomic,
    read_monthly,
)
from monthly_csv_schema import (  # noqa: F401
    AUTO_IMPORT_NOTE,
    CARDIO_DUPLICATE_DURATION_TOLERANCE_MIN,
    DELOAD_MARKER_TEXT,
    MONTHLY_COLS,
    MONTHLY_FIELDS,
    MONTHLY_HEADERS,
    STRENGTH_METADATA_DRIFT_THRESHOLD,
    TOTAL_LABEL,
)
from monthly_csv_upsert import (  # noqa: F401
    list_year_months,
    upsert_monthly_cardio,
    upsert_monthly_strength_session,
    upsert_rows,
)
from monthly_csv_values import (  # noqa: F401
    DURATION_VS_ELAPSED_RATIO_THRESHOLD,
    PACE_MIN_PER_KM_LOWER,
    PACE_MIN_PER_KM_UPPER,
    _classify_session_rows,
    _current_month_key,
    _extract_deload_marker,
    _format_duration_mmss,
    _format_elapsed_hms,
    _format_pace_min_per_km,
    _is_auto_imported,
    _is_isometric_hold,
    _migrate_source_from_notes,
    _numeric_cell,
    _parse_duration_minutes,
    _reconcile_duration_and_elapsed,
    _renumber_in_emit_order,
    _strength_metadata_drifts,
    _to_num,
    date_str,
)

# Back-compat private re-exports for existing scripts:
# - ``shared/import_health_auto_export.py`` imports row I/O helpers.
# - ``shared/maintain.py`` imports duration/pace formatting helpers.
# - legacy monthly CSV tests import classification/canonicalization helpers.
from monthly_csv_canonicalize import _build_data_row, _build_total_row  # noqa: F401,E402

__all__ = [
    "canonicalize_monthly_csv",
    "read_monthly",
    "AUTO_IMPORT_NOTE",
    "CARDIO_DUPLICATE_DURATION_TOLERANCE_MIN",
    "DELOAD_MARKER_TEXT",
    "MONTHLY_COLS",
    "MONTHLY_FIELDS",
    "MONTHLY_HEADERS",
    "STRENGTH_METADATA_DRIFT_THRESHOLD",
    "TOTAL_LABEL",
    "list_year_months",
    "upsert_monthly_cardio",
    "upsert_monthly_strength_session",
    "upsert_rows",
    "DURATION_VS_ELAPSED_RATIO_THRESHOLD",
    "PACE_MIN_PER_KM_LOWER",
    "PACE_MIN_PER_KM_UPPER",
    "date_str",
    "_build_data_row",
    "_build_total_row",
    "_dict_to_row",
    "_read_csv_rows",
    "_row_to_dict",
    "_serialize_value",
    "_write_csv_atomic",
    "_classify_session_rows",
    "_current_month_key",
    "_extract_deload_marker",
    "_format_duration_mmss",
    "_format_elapsed_hms",
    "_format_pace_min_per_km",
    "_is_auto_imported",
    "_is_isometric_hold",
    "_migrate_source_from_notes",
    "_numeric_cell",
    "_parse_duration_minutes",
    "_reconcile_duration_and_elapsed",
    "_renumber_in_emit_order",
    "_strength_metadata_drifts",
    "_to_num",
]
