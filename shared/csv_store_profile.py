"""Profile CSV store."""
from __future__ import annotations

import csv
from functools import lru_cache

from .csv_store_common import _date_str, _serialize_value
from .person_paths import ensure_data_dir, profile_csv
from tracker.csv_table import write_csv_atomic

__all__ = [
    "PROFILE_KEYS",
    "PROFILE_DEFAULTS",
    "read_profile",
    "write_profile",
    "ensure_profile",
]

# ============================================================ Profile (CSV)
PROFILE_KEYS = (
    "source", "auto_cardio", "birthday", "sex",
    "swim_css_sec_per_100m", "swim_css_set_at", "swim_pool_length_default",
    "light_therapy_target_per_week", "light_therapy_target_min_per_session",
    "sauna_target_per_week", "session_target_min",
)
PROFILE_DEFAULTS = {
    "source":                              None,
    "auto_cardio":                         False,
    "birthday":                            None,
    "sex":                                 None,
    "swim_css_sec_per_100m":               None,
    "swim_css_set_at":                     None,
    "swim_pool_length_default":            None,
    "light_therapy_target_per_week":       None,
    "light_therapy_target_min_per_session": None,
    "sauna_target_per_week":               None,
    # Target strength-session length in minutes. Drives the coach's
    # working-set budget (duration is set-count-driven, not exercise-count
    # driven). Default 60; override per person.
    "session_target_min":                  60,
}


def _coerce_bool(v):
    """Permissive bool coercion for hand-edited cells.

    Accepts ``True``/``False``, ``1``/``0``, ``"true"``/``"false"``,
    ``"yes"``/``"no"``, ``"y"``/``"n"`` (case-insensitive). Anything
    else returns ``None`` so the caller can re-apply the default
    rather than silently treating a typo as ``False``.
    """
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "yes", "y", "1", "on"):
        return True
    if s in ("false", "no", "n", "0", "off"):
        return False
    return None


def _coerce_float(v):
    """Permissive float coercion. Returns None on failure / empty / NaN."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        try:
            f = float(str(v).strip())
        except (TypeError, ValueError):
            return None
    if f != f:  # NaN
        return None
    return f


def _coerce_int(v):
    """Permissive int coercion. Accepts ``"25"``, ``25.0``, ``25``."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    f = _coerce_float(v)
    if f is None:
        return None
    return int(round(f))


@lru_cache(maxsize=8)
def _read_profile_cached(person: str) -> dict:
    """Cached read of the per-person profile dict.

    The read path of ``read_tracker.py`` calls ``read_profile`` directly
    plus indirectly via ``_resolve_source`` for both Health Metrics and
    Workout Sessions, so the same tiny CSV gets parsed 3-4 times per
    cold-CLI invocation. The cache returns the same dict object on hits;
    ``read_profile`` clones it so callers can mutate safely. Writes call
    ``_read_profile_cached.cache_clear()`` to invalidate.
    """
    out = dict(PROFILE_DEFAULTS)
    out["_unknown_rows"] = []
    path = profile_csv(person)
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return out
        # Permissive: if the header is missing, treat the first row as
        # data too. Common when the file was hand-edited.
        if header and (header[0] or "").strip().lower() != "key":
            f.seek(0)
            reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            k = (row[0] or "").strip().lower()
            v = row[1] if len(row) > 1 else None
            if k == "key" and (v or "").strip().lower() == "value":
                continue  # header
            if k == "source":
                if v is None or v == "":
                    continue
                s = str(v).strip().lower()
                if s in ("xml", "health_auto_export", "hl_export"):
                    out["source"] = s
            elif k == "auto_cardio":
                b = _coerce_bool(v)
                if b is not None:
                    out["auto_cardio"] = b
            elif k == "birthday":
                d = _date_str(v)
                if d:
                    out["birthday"] = d
            elif k == "sex":
                if v is None or v == "":
                    continue
                s = str(v).strip().lower()
                if s in ("m", "male"):
                    out["sex"] = "male"
                elif s in ("f", "female"):
                    out["sex"] = "female"
            elif k == "swim_css_sec_per_100m":
                f = _coerce_float(v)
                if f is not None:
                    out["swim_css_sec_per_100m"] = f
            elif k == "swim_css_set_at":
                d = _date_str(v)
                if d:
                    out["swim_css_set_at"] = d
            elif k == "swim_pool_length_default":
                i = _coerce_int(v)
                if i is not None:
                    out["swim_pool_length_default"] = i
            elif k == "light_therapy_target_per_week":
                i = _coerce_int(v)
                if i is not None:
                    out["light_therapy_target_per_week"] = i
            elif k == "light_therapy_target_min_per_session":
                i = _coerce_int(v)
                if i is not None:
                    out["light_therapy_target_min_per_session"] = i
            elif k == "sauna_target_per_week":
                i = _coerce_int(v)
                if i is not None:
                    out["sauna_target_per_week"] = i
            elif k == "session_target_min":
                i = _coerce_int(v)
                if i is not None and 20 <= i <= 180:
                    out["session_target_min"] = i
            else:
                out["_unknown_rows"].append([row[0], v])
    return out


def read_profile(person: str) -> dict:
    """Return the per-person profile dict (fresh shallow copy)."""
    out = dict(_read_profile_cached(person))
    out.pop("_unknown_rows", None)
    return out


def write_profile(person: str, **updates) -> None:
    """Update one or more profile keys; create the file if missing.

    Unknown keys are ignored. Booleans are written as lowercase
    ``true``/``false`` strings so the file stays diffable.
    """
    ensure_data_dir(person)
    cached = dict(_read_profile_cached(person))
    unknown_rows = list(cached.pop("_unknown_rows", []))
    current = dict(cached)
    for k, v in updates.items():
        norm = k.strip().lower()
        if norm not in PROFILE_KEYS:
            continue
        current[norm] = v

    path = profile_csv(person)
    rows = []
    for key in PROFILE_KEYS:
        v = current.get(key)
        rows.append([key, _serialize_value(v)])
    known = set(PROFILE_KEYS)
    for row in unknown_rows:
        if row and str(row[0]).strip().lower() not in known:
            rows.append(row)
    write_csv_atomic(path, ["key", "value"], rows)
    _read_profile_cached.cache_clear()


def ensure_profile(person: str,
                   default_source: str | None = None,
                   default_auto_cardio: bool | None = None) -> tuple[dict, bool]:
    """Bootstrap the profile CSV if missing; return ``(profile, created)``.

    ``default_source`` / ``default_auto_cardio`` are applied only when
    creating a fresh file — existing files are left alone (their values
    stand). Mirrors ``tracker_sheet.ensure_profile_sheet``.
    """
    path = profile_csv(person)
    if path.exists():
        return read_profile(person), False
    seeded = dict(PROFILE_DEFAULTS)
    if default_source is not None:
        seeded["source"] = default_source
    if default_auto_cardio is not None:
        seeded["auto_cardio"] = default_auto_cardio
    write_profile(person, **seeded)
    return seeded, True
