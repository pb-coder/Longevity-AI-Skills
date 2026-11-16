"""Preview populated cells that a Health Export Kit import would replace."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation

from .csv_store import (
    HEALTH_METRICS_FIELDS, SLEEP_NIGHTS_FIELDS, SWIM_WORKOUTS_FIELDS,
    WORKOUT_SESSIONS_FIELDS, read_health_metrics, read_sleep_nights,
    read_swim_workouts, read_workout_sessions,
)
from .csv_store_periodic import _compute_sleep_efficiency


def _equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if a == b:
        return True
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except InvalidOperation:
        return False


def _key(row, fields):
    return tuple(str(row.get(field) or "") for field in fields)


def _merge_sparse(index, entries, keys, fields):
    for row in entries:
        key = _key(row, keys)
        if not key[0]:
            continue
        target = index.setdefault(key, dict(zip(keys, key)))
        for field in fields:
            if row.get(field) is not None:
                target[field] = row[field]


def _merge_sleep(index, entries, keys, fields):
    for row in entries:
        _merge_sparse(index, [row], keys, fields)
        target = index.get(_key(row, keys))
        if target is not None and row.get("efficiency_pct") is None:
            derived = _compute_sleep_efficiency(target.get("total_h"), target.get("time_in_bed_h"))
            if derived is not None:
                target["efficiency_pct"] = derived


def find_import_conflicts(person, health, nights, swims, workouts, *, bodyweight=(), sleep=()):
    """Return populated cells an import changes after projected manual writes."""
    specs = (
        ("Health Metrics", ("date",), HEALTH_METRICS_FIELDS, read_health_metrics, health),
        ("Sleep Nights", ("date",), SLEEP_NIGHTS_FIELDS, read_sleep_nights, nights),
        ("Swim Workouts", ("date", "start"), SWIM_WORKOUTS_FIELDS, read_swim_workouts, swims),
        ("Workout Sessions", ("date", "start"), WORKOUT_SESSIONS_FIELDS, read_workout_sessions, workouts),
    )
    result = []
    for label, keys, fields, reader, incoming in specs:
        if not incoming:
            continue
        before = {_key(row, keys): dict(row) for row in reader(person)}
        if label == "Health Metrics":
            _merge_sparse(before, ({"date": r["date"], "bodyweight_kg": r.get("kg")} for r in bodyweight), keys, fields)
            mirror = {"total_h": "sleep_total_h", "deep_h": "sleep_deep_h", "rem_h": "sleep_rem_h", "time_in_bed_h": "time_in_bed_h"}
            _merge_sparse(before, ({"date": r["date"], **{dst: r.get(src) for src, dst in mirror.items()}} for r in sleep), keys, fields)
        elif label == "Sleep Nights":
            _merge_sleep(before, sleep, keys, fields)
        after = {k: dict(v) for k, v in before.items()}
        if label == "Sleep Nights":
            _merge_sleep(after, incoming, keys, fields)
        elif label != "Workout Sessions":
            _merge_sparse(after, incoming, keys, fields)
        else:
            for row in incoming:
                if not row.get("date") or row.get("start") is None:
                    continue
                key = _key(row, keys)
                old = after.get(key, {})
                new = {field: row.get(field) for field in fields}
                for field in ("notes", "avg_hr", "max_hr", "min_hr"):
                    if old.get(field) not in (None, "") and new.get(field) in (None, ""):
                        new[field] = old[field]
                if old.get("incidental") is not None and new.get("incidental") in (None, False, ""):
                    new["incidental"] = old["incidental"]
                after[key] = new
        for key, old in before.items():
            new = after.get(key, {})
            for field in fields:
                if field in keys or field == "notes":
                    continue
                prior, value = old.get(field), new.get(field)
                if prior not in (None, "") and not _equal(prior, value):
                    result.append((label, key, field, prior, value))
    return result


def format_import_conflicts(conflicts):
    if not conflicts:
        return []
    counts = Counter(row[0] for row in conflicts)
    lines = ["Import conflicts: " + str(len(conflicts)) + " populated cell(s) would change (" +
             ", ".join(f"{name}: {count}" for name, count in sorted(counts.items())) + ")"]
    for label, key, field, old, new in conflicts:
        lines.append(f"  {label} {' '.join(key)} {field}: {old!r} -> {new!r}")
    return lines
