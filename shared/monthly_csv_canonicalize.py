"""Monthly CSV canonicalization."""
from __future__ import annotations

from .person_paths import ensure_monthly_dir, monthly_csv as monthly_csv_path
from .monthly_csv_io import _dict_to_row, _read_csv_rows, _row_to_dict, _write_csv_atomic
from .monthly_csv_schema import DELOAD_MARKER_TEXT, TOTAL_LABEL
from .monthly_csv_values import (
    _classify_session_rows,
    _extract_deload_marker,
    _format_duration_mmss,
    _format_pace_min_per_km,
    _is_isometric_hold,
    _migrate_source_from_notes,
    _numeric_cell,
    _parse_duration_minutes,
    _reconcile_duration_and_elapsed,
    _renumber_in_emit_order,
    _to_num,
    date_str,
)

__all__ = [
    "canonicalize_monthly_csv",
]

# ============================================================ canonicalize
def _build_data_row(session_num: int, rd: dict, kind: str,
                    is_strength: bool) -> dict:
    """Build a canonical data-row dict from a parsed row."""
    reps = _numeric_cell(rd.get("reps"))
    kg = _numeric_cell(rd.get("kg"))
    distance = _numeric_cell(rd.get("distance"))
    duration_min = _parse_duration_minutes(rd.get("duration"))

    # Volume = reps × kg (numeric) — replaces =F*G formula.
    if isinstance(reps, (int, float)) and isinstance(kg, (int, float)) \
            and reps and kg:
        volume = round(reps * kg, 2)
    else:
        volume = None

    # Pace recomputed from duration + distance with the [0.5, 60] guard.
    pace = _format_pace_min_per_km(duration_min, distance)

    out = {
        "session":     session_num,
        "date":        rd.get("date"),
        "num":         _numeric_cell(rd.get("num")),
        "exercise":    rd.get("exercise"),
        "set":         _numeric_cell(rd.get("set")),
        "reps":        reps,
        "kg":          kg,
        "volume":      volume,
        "notes":       rd.get("notes"),
        "distance":    distance,
        "pace":        pace,
        "duration":    None,
        "avg_hr":      None,
        "active_cal":  None,
        "total_cal":   None,
        "elevation_m": None,
        "elapsed":     None,
        # Preserve the row's origin tag through canonicalize. Set by
        # the importer (``apple`` / ``gymkit:<Device>``) or the
        # legacy-Notes migration helper (``manual`` for hand-logged
        # rows). TOTAL rows leave this blank.
        "source":      rd.get("source") or None,
    }

    if is_strength and kind == "cardio":
        # Cardio inside a mixed-day strength session — keep per-row metadata.
        out["duration"] = _format_duration_mmss(duration_min) \
            if duration_min is not None \
            else (rd.get("duration") if rd.get("duration") else None)
        out["avg_hr"] = _numeric_cell(rd.get("avg_hr"))
        out["active_cal"] = _numeric_cell(rd.get("active_cal"))
        out["total_cal"] = _numeric_cell(rd.get("total_cal"))
        out["elevation_m"] = _numeric_cell(rd.get("elevation_m"))
        out["elapsed"] = rd.get("elapsed")
    elif is_strength:
        # Strength / other rows: session metadata moved to TOTAL row.
        # Exception: isometric holds (reps=0, kg=0 + duration) keep
        # their per-set duration — it's hold time, not session time.
        if _is_isometric_hold(rd) and duration_min is not None:
            out["duration"] = _format_duration_mmss(duration_min)
    else:
        # Pure cardio session — every row keeps its own metadata.
        out["duration"] = _format_duration_mmss(duration_min) \
            if duration_min is not None \
            else (rd.get("duration") if rd.get("duration") else None)
        out["avg_hr"] = _numeric_cell(rd.get("avg_hr"))
        out["active_cal"] = _numeric_cell(rd.get("active_cal"))
        out["total_cal"] = _numeric_cell(rd.get("total_cal"))
        out["elevation_m"] = _numeric_cell(rd.get("elevation_m"))
        out["elapsed"] = rd.get("elapsed")

    return out


def _build_total_row(session_num: int, sess: dict, hoist: dict,
                     volume_sum: float | None,
                     deload_present: bool) -> dict:
    """Build the canonical TOTAL row dict for a strength session."""
    return {
        "session":     session_num,
        "date":        sess["date"],
        "num":         None,
        "exercise":    TOTAL_LABEL,
        "set":         None,
        "reps":        None,
        "kg":          None,
        "volume":      round(volume_sum, 2) if volume_sum else None,
        "notes":       DELOAD_MARKER_TEXT if deload_present else None,
        "distance":    None,
        "duration":    hoist.get("duration"),
        "pace":        None,
        "avg_hr":      hoist.get("avg_hr"),
        "active_cal":  hoist.get("active_cal"),
        "total_cal":   hoist.get("total_cal"),
        "elevation_m": hoist.get("elevation_m"),
        "elapsed":     hoist.get("elapsed"),
    }


def canonicalize_monthly_csv(person: str, year_month: str) -> None:
    """Re-sort, recompute computed cells, rebuild TOTAL rows. Idempotent.

    Equivalent of the xlsx ``style_monthly_sheet`` pass:
    1. Load all rows; pull TOTAL-row metadata aside per session.
    2. Drop empty rows; group by Date.
    3. Merge same-date sessions (handles backfill landing as separate
       blocks).
    4. Sort sessions ASC by date; sort each session's rows by (#, set).
    5. For each session: classify rows, hoist Apple-watch metadata to
       TOTAL, recompute Volume + Pace per row, blank session-metadata
       cells on non-cardio rows of strength sessions.
    6. Emit a TOTAL row at every strength-session boundary with the
       computed Volume sum + hoisted metadata.
    7. Write back atomically.
    """
    path = monthly_csv_path(person, year_month)
    if not path.exists():
        return
    header, raw_rows = _read_csv_rows(path)
    if not header:
        return

    # Parse rows into session blocks.
    sessions: list[dict] = []
    current: dict | None = None
    for raw in raw_rows:
        rd = _row_to_dict(raw)
        date_v = date_str(rd.get("date"))
        ex_v = rd.get("exercise")
        if isinstance(ex_v, str) and ex_v.strip().upper() == TOTAL_LABEL:
            if current is not None:
                current["total_meta"] = {
                    "date":         date_v or current.get("date"),
                    "notes":        rd.get("notes"),
                    "duration":     rd.get("duration"),
                    "avg_hr":       rd.get("avg_hr"),
                    "active_cal":   rd.get("active_cal"),
                    "total_cal":    rd.get("total_cal"),
                    "elevation_m":  rd.get("elevation_m"),
                    "elapsed":      rd.get("elapsed"),
                }
            continue
        if (date_v in (None, "")) and (ex_v in (None, "")):
            continue
        rd["date"] = date_v
        # Migrate legacy Notes-prefix → Source column on the fly. First
        # canonicalize pass after the 2026-05 schema change cleans every
        # row; subsequent passes are no-ops.
        _migrate_source_from_notes(rd)
        if current is None or date_v != current["date"]:
            current = {"date": date_v, "rows": [], "total_meta": {}}
            sessions.append(current)
        current["rows"].append(rd)

    # Merge same-date sessions (backfill rows can land non-contiguously).
    merged: dict = {}
    for s in sessions:
        slot = merged.setdefault(
            s["date"], {"date": s["date"], "rows": [], "total_meta": {}}
        )
        slot["rows"].extend(s["rows"])
        for k, v in (s.get("total_meta") or {}).items():
            if v not in (None, "") and slot["total_meta"].get(k) in (None, ""):
                slot["total_meta"][k] = v
    sessions = sorted(
        merged.values(),
        key=lambda s: (s["date"] is None, s["date"] or ""),
    )

    # Sort each session's rows by (num, set) ASC.
    for s in sessions:
        s["rows"].sort(key=lambda r: (
            _to_num(r.get("num")),
            _to_num(r.get("set")),
        ))

    # Build output.
    out_rows: list[list[str]] = []
    for session_num, sess in enumerate(sessions, start=1):
        kinds, is_strength = _classify_session_rows(sess["rows"])

        total_meta = sess.get("total_meta") or {}
        hoist = {
            "duration":    total_meta.get("duration"),
            "avg_hr":      _numeric_cell(total_meta.get("avg_hr")),
            "active_cal":  _numeric_cell(total_meta.get("active_cal")),
            "total_cal":   _numeric_cell(total_meta.get("total_cal")),
            "elevation_m": _numeric_cell(total_meta.get("elevation_m")),
            "elapsed":     total_meta.get("elapsed"),
        }
        deload_present, _ = _extract_deload_marker(total_meta.get("notes"))

        # Hoist from data rows where the TOTAL row didn't already carry
        # the value (legacy rows had warmup-row session metadata).
        # Skip isometric-hold rows (reps=0, kg=0, distance=0 + duration):
        # their Duration cell is per-set hold time (e.g. "Dead Hang 0:30"),
        # not the session total. Those keep duration on the row in
        # ``_build_data_row``.
        if is_strength:
            for i, rd in enumerate(sess["rows"]):
                if kinds[i] == "cardio":
                    continue
                if _is_isometric_hold(rd):
                    continue
                if hoist["duration"] in (None, "") and rd.get("duration") not in (None, ""):
                    hoist["duration"] = rd["duration"]
                if hoist["avg_hr"] in (None, "") and rd.get("avg_hr") not in (None, ""):
                    hoist["avg_hr"] = _numeric_cell(rd["avg_hr"])
                if hoist["active_cal"] in (None, "") and rd.get("active_cal") not in (None, ""):
                    hoist["active_cal"] = _numeric_cell(rd["active_cal"])
                if hoist["total_cal"] in (None, "") and rd.get("total_cal") not in (None, ""):
                    hoist["total_cal"] = _numeric_cell(rd["total_cal"])
                if hoist["elevation_m"] in (None, "") and rd.get("elevation_m") not in (None, ""):
                    hoist["elevation_m"] = _numeric_cell(rd["elevation_m"])
                if hoist["elapsed"] in (None, "") and rd.get("elapsed") not in (None, ""):
                    hoist["elapsed"] = rd["elapsed"]
                row_deload, row_remainder = _extract_deload_marker(rd.get("notes"))
                if row_deload:
                    deload_present = True
                    rd["notes"] = row_remainder

        # Sanity-check Duration vs Elapsed on the hoisted TOTAL-row metadata.
        # When a Duration cell is corrupt (single-cell typos like 0.5 against
        # an Elapsed of 1:03:54), prefer Elapsed and self-heal the cell.
        if hoist.get("duration") not in (None, "") \
                and hoist.get("elapsed") not in (None, ""):
            hoist["duration"] = _reconcile_duration_and_elapsed(
                hoist["duration"], hoist["elapsed"],
                context=f"{person} {sess.get('date') or year_month}",
            )

        # Emit data rows + accumulate volume sum for strength sessions.
        # On mixed strength+cardio days, the TOTAL row summarizes the
        # strength session only (volume + hoisted strength-watch metadata),
        # so it goes immediately after the last strength/other row and
        # before any auto-imported cardio rows — anchoring it visually
        # to the session it describes.
        built = [
            _build_data_row(session_num, rd, kinds[idx], is_strength)
            for idx, rd in enumerate(sess["rows"])
        ]
        volume_sum = sum(
            float(b["volume"]) for b in built if b.get("volume")
        )

        # Renumber ``#`` in emit order: strength/other rows first, then
        # cardio rows. Same exercise shares a num across all its sets.
        # Self-heals duplicates that arise when /log writes strength
        # after the auto-cardio importer has already numbered cardio
        # rows on the same date.
        strength_built = [b for idx, b in enumerate(built) if kinds[idx] != "cardio"]
        cardio_built = [b for idx, b in enumerate(built) if kinds[idx] == "cardio"]
        _renumber_in_emit_order(strength_built, cardio_built)

        if is_strength:
            for data_row in strength_built:
                out_rows.append(_dict_to_row(data_row))
            total_row = _build_total_row(
                session_num, sess, hoist,
                volume_sum if volume_sum else None,
                deload_present,
            )
            out_rows.append(_dict_to_row(total_row))
            for data_row in cardio_built:
                out_rows.append(_dict_to_row(data_row))
        else:
            for data_row in strength_built + cardio_built:
                out_rows.append(_dict_to_row(data_row))

    ensure_monthly_dir(person)
    _write_csv_atomic(path, out_rows)
