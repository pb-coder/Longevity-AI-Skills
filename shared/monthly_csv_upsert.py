"""Monthly CSV upsert operations."""
from __future__ import annotations

import re
from datetime import date

from .monthly_csv_canonicalize import canonicalize_monthly_csv
from .monthly_csv_io import _dict_to_row, _read_csv_rows, _row_to_dict, _write_csv_atomic
from .monthly_csv_schema import (
    CARDIO_DUPLICATE_DURATION_TOLERANCE_MIN,
    TOTAL_LABEL,
)
from .monthly_csv_values import (
    _current_month_key,
    _format_duration_mmss,
    _format_elapsed_hms,
    _format_pace_min_per_km,
    _is_auto_imported,
    _numeric_cell,
    _parse_duration_minutes,
    _strength_metadata_drifts,
    date_str,
)
from .person_paths import ensure_monthly_dir, monthly_csv as monthly_csv_path, monthly_dir

__all__ = [
    "upsert_rows",
    "upsert_monthly_cardio",
    "upsert_monthly_strength_session",
    "list_year_months",
]

# ============================================================ upsert_rows
def upsert_rows(person: str, year_month: str, rows: list[dict]) -> None:
    """Append a batch of dict-rows to the per-month CSV, then canonicalize.

    ``rows`` is a list of dicts using ``MONTHLY_FIELDS`` keys (subset
    is fine — missing keys serialize as blank). Used by ``/log`` and by
    the migrator. Caller is responsible for the row-shape contract;
    canonicalize handles sort + computed cells + TOTAL rebuild.
    """
    if not rows:
        return
    path = monthly_csv_path(person, year_month)
    ensure_monthly_dir(person)
    # Read-existing-or-empty, then append.
    header, existing = _read_csv_rows(path)
    out = list(existing)
    for r in rows:
        out.append(_dict_to_row(r))
    _write_csv_atomic(path, out)
    canonicalize_monthly_csv(person, year_month)


# ============================================================ upsert cardio
def upsert_monthly_cardio(person: str,
                          rows: list[dict],
                          allow_past_months: bool = False,
                          today_d: date | None = None) -> list[str]:
    """Append Apple cardio rows with manual-wins dedupe + canonicalize.

    Same semantics as the xlsx-era ``tracker_sheet.upsert_monthly_cardio``,
    but writes to ``<person>/data/monthly/YYYY.MM.csv``. Each input row
    has the keys: ``date``, ``exercise``, ``duration_min``, ``distance_km``,
    ``avg_hr``, plus optional ``active_cal``, ``total_cal``, ``elevation_m``,
    ``elapsed_min``, ``machine_tag``. (``laps``, if present, is dropped
    here — swim lap count is sourced from
    ``<Person>/data/swimming/YYYY.MM.workouts.csv`` only.)

    Dedupe rule:
    - Any existing manual row on (date, exercise) wins unconditionally.
    - An existing AUTO row with (date, exercise, duration ±1 min) is the
      idempotency path: re-runs are no-ops; metadata cells (cols 14-18)
      sparse-merge with the 5% drift guard.
    - Otherwise the new row is appended; canonicalize then sorts +
      recomputes Volume / Pace / Total Cal / SESSION / TOTAL.

    Current-month gate: rows dated outside the current calendar month
    are dropped unless ``allow_past_months=True``. Past months are
    "finished"; deleted rows stay deleted on re-import.
    """
    if not rows:
        return ["Auto-cardio: 0 rows considered"]

    current_month = _current_month_key(today_d)
    skipped_past_month = 0
    skipped_past_by_month: dict[str, dict[str, int]] = {}

    def _past_month_skip_summaries() -> list[str]:
        if not skipped_past_month:
            return []
        out = [
            f"Auto-cardio: {skipped_past_month} input rows skipped "
            f"(dated outside the current month {current_month})"
        ]
        breakdown_parts = []
        for month_key in sorted(skipped_past_by_month):
            exercise_counts = skipped_past_by_month[month_key]
            type_bits = ", ".join(
                f"{name}={exercise_counts[name]}"
                for name in sorted(exercise_counts)
            )
            breakdown_parts.append(
                f"{month_key}: {sum(exercise_counts.values())}"
                + (f" ({type_bits})" if type_bits else "")
            )
        if breakdown_parts:
            out.append(
                "Auto-cardio past-month skipped breakdown: "
                + "; ".join(breakdown_parts)
                + ". Rerun with --allow-past-months for an intentional backfill."
            )
        return out

    by_month: dict[str, list[dict]] = {}
    for r in rows:
        d = str(r.get("date") or "")[:10]
        if not d or len(d) != 10:
            continue
        key = f"{d[:4]}.{d[5:7]}"
        if not allow_past_months and key != current_month:
            skipped_past_month += 1
            exercise = str(r.get("exercise") or "unknown").strip() or "unknown"
            month_counts = skipped_past_by_month.setdefault(key, {})
            month_counts[exercise] = month_counts.get(exercise, 0) + 1
            continue
        by_month.setdefault(key, []).append(r)

    if not by_month:
        if skipped_past_month:
            return [
                f"Auto-cardio: 0 rows considered "
                f"({skipped_past_month} skipped — past months are not re-scanned)"
            ] + _past_month_skip_summaries()
        return ["Auto-cardio: 0 rows considered (no valid dates)"]

    summaries: list[str] = []
    total_appended = 0
    total_skipped = 0

    for month_key in sorted(by_month.keys()):
        month_rows = by_month[month_key]
        path = monthly_csv_path(person, month_key)
        ensure_monthly_dir(person)
        sheet_created = not path.exists()

        # Load existing rows (skipping TOTAL rows for the dedupe index).
        header, existing_raw = _read_csv_rows(path)
        existing_dicts: list[dict] = []
        for raw in existing_raw:
            rd = _row_to_dict(raw)
            existing_dicts.append(rd)

        # Build dedupe index: (date, exercise.lower) → list of
        # (idx_in_existing_dicts, duration_min, is_auto).
        existing_index: dict[tuple, list[tuple]] = {}
        for idx, rd in enumerate(existing_dicts):
            ex_v = rd.get("exercise")
            if not ex_v:
                continue
            ex_str = str(ex_v).strip()
            if not ex_str or ex_str.upper() == TOTAL_LABEL:
                continue
            date_v = date_str(rd.get("date"))
            if not date_v:
                continue
            dur_f = _parse_duration_minutes(rd.get("duration"))
            is_auto = _is_auto_imported(rd)
            existing_index.setdefault((date_v, ex_str.lower()), []).append(
                (idx, dur_f, is_auto)
            )

        appended = 0
        skipped_dup = 0
        refreshed = 0
        claimed_rows: set = set()

        new_rows_to_append: list[dict] = []

        for r in month_rows:
            d = str(r.get("date") or "")[:10]
            ex = r.get("exercise")
            if not d or not ex:
                continue
            ex_lower = ex.strip().lower()
            dur = r.get("duration_min")
            try:
                dur_f = float(dur) if dur is not None else None
            except (TypeError, ValueError):
                dur_f = None

            matches = existing_index.get((d, ex_lower), [])
            has_manual_match = any(
                (not is_auto) and (idx not in claimed_rows)
                for idx, _dur, is_auto in matches
            )
            matched_auto_idx = None
            if not has_manual_match:
                best = None
                best_diff = None
                for idx, existing_dur, is_auto in matches:
                    if not is_auto or idx in claimed_rows:
                        continue
                    if existing_dur is None or dur_f is None:
                        diff = 0.0
                    else:
                        diff = abs(existing_dur - dur_f)
                        if diff > CARDIO_DUPLICATE_DURATION_TOLERANCE_MIN:
                            continue
                    if best_diff is None or diff < best_diff:
                        best, best_diff = idx, diff
                matched_auto_idx = best

            if matched_auto_idx is not None:
                claimed_rows.add(matched_auto_idx)
                if matched_auto_idx >= len(existing_dicts):
                    # Match is against a row queued earlier in this same
                    # batch, not one already stored on disk. Treat as an
                    # in-batch duplicate; the queued row will be written once.
                    skipped_dup += 1
                    continue
                cur = existing_dicts[matched_auto_idx]
                incoming_meta = {
                    "active_cal":  int(round(r["active_cal"])) if isinstance(r.get("active_cal"), (int, float)) and r.get("active_cal") else None,
                    "total_cal":   int(round(r["total_cal"])) if isinstance(r.get("total_cal"), (int, float)) and r.get("total_cal") else None,
                    "elevation_m": int(round(r["elevation_m"])) if isinstance(r.get("elevation_m"), (int, float)) and r.get("elevation_m") else None,
                    "elapsed":     _format_elapsed_hms(r.get("elapsed_min")),
                }
                row_changed = False
                for key, new_val in incoming_meta.items():
                    if new_val in (None, ""):
                        continue
                    existing_val = cur.get(key)
                    if existing_val in (None, ""):
                        cur[key] = new_val
                        row_changed = True
                    elif _strength_metadata_drifts(existing_val, new_val):
                        cur[key] = new_val
                        row_changed = True
                if row_changed:
                    refreshed += 1
                else:
                    skipped_dup += 1
                continue

            if has_manual_match:
                skipped_dup += 1
                continue

            # Genuinely new row — assemble and queue.
            distance = r.get("distance_km")
            avg_hr = r.get("avg_hr")
            machine_tag = r.get("machine_tag")
            source_value = (
                f"gymkit:{machine_tag}" if machine_tag else "apple"
            )

            # Per-date # auto-increment (re-uses an existing day's counter
            # if the user logged strength earlier the same date).
            existing_nums: list[int] = []
            for rd in existing_dicts + new_rows_to_append:
                if date_str(rd.get("date")) == d:
                    n = _numeric_cell(rd.get("num"))
                    if isinstance(n, (int, float)):
                        existing_nums.append(int(n))
            next_num = (max(existing_nums) + 1) if existing_nums else 1

            new_row = {
                "session":     None,  # canonicalize will fill
                "date":        d,
                "num":         next_num,
                "exercise":    ex,
                "set":         1,
                "reps":        None,
                "kg":          None,
                "volume":      None,
                "notes":       None,  # was auto-import boilerplate; now Source column
                "distance":    _numeric_cell(distance),
                "duration":    _format_duration_mmss(dur_f),
                "pace":        _format_pace_min_per_km(dur_f, distance),
                "avg_hr":      _numeric_cell(avg_hr),
                "active_cal":  int(round(r["active_cal"])) if isinstance(r.get("active_cal"), (int, float)) and r.get("active_cal") else None,
                "total_cal":   int(round(r["total_cal"])) if isinstance(r.get("total_cal"), (int, float)) and r.get("total_cal") else None,
                "elevation_m": int(round(r["elevation_m"])) if isinstance(r.get("elevation_m"), (int, float)) and r.get("elevation_m") else None,
                "elapsed":     _format_elapsed_hms(r.get("elapsed_min")),
                "source":      source_value,
            }
            new_rows_to_append.append(new_row)
            # Track the new row in the dedupe index too so two near-duration
            # Apple workouts in the same input batch don't both land.
            existing_index.setdefault((d, ex_lower), []).append(
                (len(existing_dicts) + len(new_rows_to_append) - 1, dur_f, True)
            )
            appended += 1

        if appended or refreshed:
            # Combine existing (with any in-place metadata refreshes) + new rows.
            all_dicts = existing_dicts + new_rows_to_append
            out = [_dict_to_row(rd) for rd in all_dicts]
            _write_csv_atomic(path, out)
            canonicalize_monthly_csv(person, month_key)

        total_appended += appended
        total_skipped += skipped_dup
        tag = " (new sheet)" if sheet_created else ""
        refreshed_tag = f", {refreshed} refreshed" if refreshed else ""
        summaries.append(
            f"{month_key}{tag}: {appended} cardio rows appended, "
            f"{skipped_dup} skipped (already present){refreshed_tag}"
        )

    summaries.append(
        f"Auto-cardio total: {total_appended} appended, "
        f"{total_skipped} skipped across {len(by_month)} month(s)"
    )
    summaries.extend(_past_month_skip_summaries())
    return summaries


# ============================================================ upsert strength
def upsert_monthly_strength_session(person: str,
                                    sessions: list[dict],
                                    today_d: date | None = None,
                                    allow_past_months: bool = False) -> list[str]:
    """Annotate the TOTAL row of each matching strength session with
    Apple-watch session metadata (Duration, Avg HR, Active/Total Cal,
    Elevation, Elapsed). Sparse-merge + 5% drift guard preserves manual edits.

    Same contract as the xlsx-era ``upsert_monthly_strength_session``;
    only the storage backend changed. Current-month gate enforced unless
    ``allow_past_months=True`` for a deliberate source backfill.
    """
    if not sessions:
        return ["Strength sessions: 0 considered"]

    summaries: list[str] = []
    written = 0
    skipped_no_match = 0
    skipped_no_change = 0
    skipped_past_month = 0
    drift_warnings: list[str] = []

    current_month = _current_month_key(today_d)
    touched_months: set = set()

    for sess in sessions:
        d = str(sess.get("date") or "")[:10]
        if not d or len(d) != 10:
            continue
        month_key = f"{d[:4]}.{d[5:7]}"
        if not allow_past_months and month_key != current_month:
            skipped_past_month += 1
            continue

        path = monthly_csv_path(person, month_key)
        if not path.exists():
            skipped_no_match += 1
            continue

        header, raw_rows = _read_csv_rows(path)
        if not header:
            skipped_no_match += 1
            continue
        existing_dicts = [_row_to_dict(raw) for raw in raw_rows]

        # Locate the TOTAL row for the date. Mirrors the xlsx version's
        # date_seen_above tolerance for legacy rows whose TOTAL Date is blank.
        target_idx = None
        date_seen_above = False
        for i, rd in enumerate(existing_dicts):
            row_date = date_str(rd.get("date"))
            ex_val = rd.get("exercise")
            ex_str = str(ex_val).strip() if ex_val else ""
            if ex_str.upper() == TOTAL_LABEL:
                if row_date == d or (row_date in (None, "") and date_seen_above):
                    target_idx = i
                    break
                date_seen_above = False
                continue
            if row_date == d:
                date_seen_above = True
            elif row_date not in (None, ""):
                date_seen_above = False

        if target_idx is None:
            skipped_no_match += 1
            continue

        ac = sess.get("active_cal")
        tc = sess.get("total_cal")
        el = sess.get("elevation_m")
        em = sess.get("elapsed_min")
        ah = sess.get("avg_hr")
        dur = sess.get("duration_min")

        incoming = {
            "duration":    _format_duration_mmss(dur),
            "avg_hr":      round(float(ah), 1) if isinstance(ah, (int, float)) and ah else None,
            "active_cal":  int(round(ac)) if isinstance(ac, (int, float)) and ac else None,
            "total_cal":   int(round(tc)) if isinstance(tc, (int, float)) and tc else None,
            "elevation_m": int(round(el)) if isinstance(el, (int, float)) and el else None,
            "elapsed":     _format_elapsed_hms(em),
        }

        target = existing_dicts[target_idx]
        any_change = False
        for key, new_val in incoming.items():
            if new_val in (None, ""):
                continue
            existing_val = _numeric_cell(target.get(key)) \
                if key not in ("duration", "elapsed") else target.get(key)
            if existing_val in (None, ""):
                target[key] = new_val
                any_change = True
            elif _strength_metadata_drifts(existing_val, new_val):
                drift_warnings.append(
                    f"  - {d} {key}: kept manual value {existing_val!r} "
                    f"(Apple reports {new_val!r}, differs >=5%)"
                )
            # else: idempotency no-op.

        if any_change:
            out = [_dict_to_row(rd) for rd in existing_dicts]
            _write_csv_atomic(path, out)
            touched_months.add(month_key)
            written += 1
        else:
            skipped_no_change += 1

    for month_key in sorted(touched_months):
        canonicalize_monthly_csv(person, month_key)

    summaries.append(
        f"Strength sessions: {written} written, "
        f"{skipped_no_change} no-op (already up to date), "
        f"{skipped_no_match} skipped (no matching session row)"
    )
    if skipped_past_month:
        summaries.append(
            f"Strength sessions: {skipped_past_month} dated outside the "
            f"current month {current_month} — past months are not re-scanned"
        )
    if drift_warnings:
        summaries.append(
            f"Strength sessions: {len(drift_warnings)} manual-wins warnings:"
        )
        summaries.extend(drift_warnings)
    return summaries


# ============================================================ Discovery
def list_year_months(person: str) -> list[str]:
    """Return all ``YYYY.MM`` keys for which a per-month CSV exists, ASC."""
    d = monthly_dir(person)
    if not d.exists():
        return []
    keys = []
    for p in d.glob("*.csv"):
        stem = p.stem
        if re.match(r"^\d{4}\.\d{2}$", stem):
            keys.append(stem)
    return sorted(keys)
