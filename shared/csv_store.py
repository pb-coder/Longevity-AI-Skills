"""Compatibility facade for CSV-backed tracker stores.

The implementation is split by data domain:
- ``csv_store_profile``: profile key/value store.
- ``csv_store_dense``: dense health metrics and workout sessions.
- ``csv_store_periodic``: monthly/periodic swim, sleep, thermal, light, and nutrition stores.

Keep importing ``csv_store`` from scripts and tests; new code should place
behavior in the focused modules above.
"""
from __future__ import annotations

from csv_store_common import (  # noqa: F401
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
from csv_store_dense import _resolve_source, _strength_metadata_drifts  # noqa: F401
from csv_store_dense import *  # noqa: F401,F403
from csv_store_periodic import *  # noqa: F401,F403
from csv_store_profile import _coerce_bool, _coerce_float, _coerce_int  # noqa: F401
from csv_store_profile import *  # noqa: F401,F403
