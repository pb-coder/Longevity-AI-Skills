"""Per-month workout CSV: read, upsert, canonicalize.

Replaces the xlsx-era ``tracker_sheet.py`` for the monthly ``YYYY.MM``
workout sheets. One CSV per month at
``<person>/data/monthly/YYYY.MM.csv``, 18-column schema preserved
verbatim from the xlsx layout. Header row 1; data rows ASC by
(Date, #, Set); TOTAL rows interleaved at strength-session boundaries.

Computed cells are pre-evaluated on every canonicalize pass:
- ``Volume = reps × kg`` (was ``=F*G`` formula).
- ``Pace (min/km) = duration_min / distance_km``, MM:SS string with
  the existing [0.5, 60] guard (blank outside).
- ``SESSION`` = per-month counter (1..N), same date → same number.
  Was a merged cell range; now repeated on every row of the same date.
- ``TOTAL`` rows hold the strength session's volume sum, hoisted
  Apple-watch metadata (Duration, Avg HR, Active/Total Cal, Elevation,
  Elapsed), and the ``Deload Workout`` marker on Notes when present.

The CSV is the canonical source. Anything that touches a monthly file
must call ``canonicalize_monthly_csv`` after writing — same idempotency
contract the xlsx styler had.

Public surface:
- ``read_monthly(person, year_month)`` → list[dict] (data + TOTAL rows).
- ``upsert_rows(person, year_month, rows)`` → append manual /log rows.
- ``upsert_monthly_cardio(person, payload, allow_past_months=False)`` →
  Apple cardio rows with manual-wins dedupe.
- ``upsert_monthly_strength_session(person, sessions)`` → annotate the
  TOTAL row with Apple-watch session metadata (sparse-merge + drift
  guard).
- ``canonicalize_monthly_csv(person, year_month)`` → re-sort, recompute
  computed cells, rebuild TOTAL rows, hoist deload markers.
- ``MONTHLY_HEADERS`` / ``MONTHLY_FIELDS`` / ``TOTAL_LABEL`` /
  ``DELOAD_MARKER_TEXT`` constants.
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from person_paths import (
    ensure_monthly_dir,
    monthly_csv as monthly_csv_path,
    monthly_dir,
)


# ============================================================ Schema
# Order matches the historical xlsx columns A..Q 1:1 — readers and
# writers across the codebase still treat column index as semantic.
# (PR4: ``Laps`` was removed in 2026-05; swim lap count is now sourced
# exclusively from ``<Person>/data/swimming/swim_workouts.csv``. Old
# 18-col rows self-truncate on the next canonicalize pass because
# ``_row_to_dict`` only iterates MONTHLY_FIELDS.)
MONTHLY_HEADERS = [
    "SESSION", "Date", "#", "Exercise", "Set", "Reps", "kg", "Volume", "Notes",
    "Distance (km)", "Duration (min)", "Pace (min/km)", "Avg HR",
    "Active Cal", "Total Cal", "Elevation (m)", "Elapsed",
]

# Internal keys mirroring header order, for dict↔row translation.
MONTHLY_FIELDS = [
    "session", "date", "num", "exercise", "set", "reps", "kg", "volume", "notes",
    "distance", "duration", "pace", "avg_hr",
    "active_cal", "total_cal", "elevation_m", "elapsed",
]

TOTAL_LABEL = "TOTAL"
DELOAD_MARKER_TEXT = "Deload Workout"

# Column counts useful for sanity checks.
MONTHLY_COLS = len(MONTHLY_HEADERS)


# ============================================================ Helpers
def date_str(v):
    """Coerce a Date cell value to a canonical ``YYYY-MM-DD`` string.

    - ``None`` / ``""`` → ``None``.
    - ``datetime`` / ``date`` → ``"YYYY-MM-DD"``.
    - String → first 10 chars after strip (covers ``"2026-04-20"`` and
      ``"2026-04-20 00:00:00"``).
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()[:10]


def _to_num(v) -> float:
    """Float coercion for strength-session classification. Blank → 0.0."""
    if v in (None, ""):
        return 0.0
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _numeric_cell(v):
    """Coerce a stringy number (incl. European comma decimals) to int/float.

    Returns the original value for anything not purely numeric (MM:SS,
    text notes, blanks). On CSV write we serialize numbers without
    string decoration; on read this is the inverse path.
    """
    if v in (None, ""):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    s = str(v).strip()
    if not s:
        return v
    try:
        f = float(s.replace(",", "."))
    except ValueError:
        return v
    return int(f) if f.is_integer() else f


def _parse_duration_minutes(v):
    """Coerce a Duration value to float minutes.

    Accepts MM:SS / H:MM:SS strings and bare numerics. Returns None when
    nothing parseable.
    """
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) + int(parts[1]) / 60.0
            if len(parts) == 3:
                return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60.0
        except ValueError:
            return None
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _format_duration_mmss(duration_min) -> str | None:
    """Format minutes as ``MM:SS``. ``None``/``""`` / ≤0 → None."""
    if duration_min in (None, ""):
        return None
    if isinstance(duration_min, str):
        s = duration_min.strip()
        if ":" in s:
            return s if s else None
        try:
            duration_min = float(s.replace(",", "."))
        except ValueError:
            return None
    try:
        f = float(duration_min)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return None
    whole = int(f)
    secs = int(round((f - whole) * 60))
    if secs == 60:
        whole += 1
        secs = 0
    return f"{whole}:{secs:02d}"


PACE_MIN_PER_KM_LOWER = 0.5
PACE_MIN_PER_KM_UPPER = 60.0


def _format_pace_min_per_km(duration_min, distance_km) -> str | None:
    """Pace MM:SS or None. Blanks outside [0.5, 60] min/km."""
    if not duration_min or not distance_km:
        return None
    try:
        d = float(duration_min)
        k = float(distance_km)
    except (TypeError, ValueError):
        return None
    if d <= 0 or k <= 0:
        return None
    pace = d / k
    if pace < PACE_MIN_PER_KM_LOWER or pace > PACE_MIN_PER_KM_UPPER:
        return None
    whole = int(pace)
    secs = int(round((pace - whole) * 60))
    if secs == 60:
        whole += 1
        secs = 0
    return f"{whole}:{secs:02d}"


# Threshold: prefer Elapsed when Duration disagrees by ≥3× in either direction.
# Catches "0.5 min vs 1:03:54 elapsed" and similar single-cell corruption that
# slips past _parse_duration_minutes (which trusts whatever literal it's given).
DURATION_VS_ELAPSED_RATIO_THRESHOLD = 3.0


def _reconcile_duration_and_elapsed(duration_raw, elapsed_raw,
                                    *, context: str = "") -> str | None:
    """Cross-check Duration against Elapsed; prefer Elapsed when they diverge.

    Returns a Duration string formatted MM:SS / H:MM:SS suitable for the
    Duration cell. Emits a one-line stderr warning when it overrides the
    stored Duration. Returns the original duration_raw unchanged when no
    correction is needed.
    """
    duration_min = _parse_duration_minutes(duration_raw)
    elapsed_min = _parse_duration_minutes(elapsed_raw)
    if duration_min is None or elapsed_min is None:
        return duration_raw
    if duration_min <= 0 or elapsed_min <= 0:
        return duration_raw
    ratio = elapsed_min / duration_min
    if ratio < DURATION_VS_ELAPSED_RATIO_THRESHOLD \
            and ratio > 1.0 / DURATION_VS_ELAPSED_RATIO_THRESHOLD:
        return duration_raw
    corrected = _format_duration_mmss(elapsed_min)
    print(
        f"[canonicalize] {context}: Duration {duration_raw!r} "
        f"({duration_min:.2f} min) inconsistent with Elapsed "
        f"{elapsed_raw!r} ({elapsed_min:.2f} min); preferring Elapsed.",
        file=sys.stderr,
    )
    return corrected


def _format_elapsed_hms(elapsed_min) -> str | None:
    """Render elapsed minutes as H:MM:SS (or MM:SS when under an hour)."""
    if elapsed_min in (None, "") or not isinstance(elapsed_min, (int, float)):
        return None
    if elapsed_min <= 0:
        return None
    total_seconds = int(round(elapsed_min * 60))
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _extract_deload_marker(notes) -> tuple[bool, str | None]:
    """Pull ``Deload Workout`` out of a Notes cell. Returns (present, remainder)."""
    if notes in (None, ""):
        return False, None
    s = str(notes)
    if DELOAD_MARKER_TEXT.lower() not in s.lower():
        return False, s.strip() or None
    pattern = re.compile(re.escape(DELOAD_MARKER_TEXT), re.IGNORECASE)
    cleaned = pattern.sub("", s)
    cleaned = re.sub(r"\s*;\s*;\s*", "; ", cleaned)
    cleaned = re.sub(r"^\s*[;|,]\s*", "", cleaned)
    cleaned = re.sub(r"\s*[;|,]\s*$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return True, cleaned or None


def _classify_session_rows(rows: list[dict]) -> tuple[list[str], bool]:
    """Per-row strength/cardio/other classification + is_strength bool.

    A row is ``cardio`` if it has any of: positive distance, a populated
    duration cell, or the auto-import note. The duration / auto-note
    branches catch indoor / commute cycling and HIIT sessions where the
    source provides time + calories but no distance — without them, those
    rows would fall through to ``other`` and have their session-metadata
    cells wiped on a mixed-day strength session (see ``_build_data_row``).
    """
    kinds: list[str] = []
    for rd in rows:
        kg_v = _to_num(rd.get("kg"))
        reps_v = _to_num(rd.get("reps"))
        if kg_v * reps_v > 0:
            kinds.append("strength")
            continue
        dist_v = _to_num(rd.get("distance"))
        if dist_v > 0:
            kinds.append("cardio")
            continue
        if _parse_duration_minutes(rd.get("duration")):
            kinds.append("cardio")
            continue
        notes_v = rd.get("notes") or ""
        if AUTO_IMPORT_NOTE.lower() in str(notes_v).lower():
            kinds.append("cardio")
            continue
        kinds.append("other")
    return kinds, ("strength" in kinds)


# ============================================================ Auto-cardio + drift
AUTO_IMPORT_NOTE = "auto-imported from Apple"
CARDIO_DUPLICATE_DURATION_TOLERANCE_MIN = 1.0
STRENGTH_METADATA_DRIFT_THRESHOLD = 0.05


def _strength_metadata_drifts(existing, incoming) -> bool:
    """5% manual-wins guard. True when existing diverges from incoming."""
    if existing in (None, ""):
        return False
    if incoming in (None, ""):
        return False
    if isinstance(existing, str) or isinstance(incoming, str):
        e_min = _parse_duration_minutes(existing)
        i_min = _parse_duration_minutes(incoming)
        if e_min is None or i_min is None:
            return str(existing).strip() != str(incoming).strip()
        existing_f, incoming_f = e_min, i_min
    else:
        try:
            existing_f = float(existing)
            incoming_f = float(incoming)
        except (TypeError, ValueError):
            return existing != incoming
    if existing_f == 0 and incoming_f == 0:
        return False
    denom = max(abs(existing_f), abs(incoming_f), 1e-9)
    return abs(existing_f - incoming_f) / denom >= STRENGTH_METADATA_DRIFT_THRESHOLD


def _current_month_key(today_d: date | None = None) -> str:
    d = today_d or date.today()
    return f"{d.year:04d}.{d.month:02d}"


# ============================================================ CSV I/O
def _serialize_value(v) -> str:
    """Inverse of ``_numeric_cell`` for CSV output."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return repr(v) if abs(v) > 1e15 else f"{v:g}"
    return str(v)


def _read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """Return ``(header, rows)``. Missing or empty file → ``([], [])``."""
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return [], []
        return header, [row for row in reader if any(c.strip() for c in row)]


def _row_to_dict(row: list[str]) -> dict:
    """Convert a raw CSV row (list of strings) to a dict by MONTHLY_FIELDS."""
    out: dict = {}
    padded = list(row) + [""] * (MONTHLY_COLS - len(row))
    for i, key in enumerate(MONTHLY_FIELDS):
        v = padded[i] if i < len(padded) else ""
        if v == "":
            out[key] = None
        else:
            out[key] = v
    return out


def _dict_to_row(d: dict) -> list[str]:
    """Convert a dict back to a CSV row (in MONTHLY_FIELDS order)."""
    return [_serialize_value(d.get(k)) for k in MONTHLY_FIELDS]


def _write_csv_atomic(path: Path, rows: list[list[str]]) -> None:
    """Write header + rows atomically (tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(MONTHLY_HEADERS)
        for row in rows:
            writer.writerow(row)
    tmp.replace(path)


# ============================================================ read_monthly
def read_monthly(person: str, year_month: str) -> list[dict]:
    """Return all rows (incl. TOTAL) from the per-month CSV as dicts.

    Each dict has the 18 keys from ``MONTHLY_FIELDS``. TOTAL rows are
    distinguished by ``exercise == "TOTAL"``. Missing file → ``[]``.
    Coerces numeric columns to int/float; leaves duration/pace/notes/
    elapsed as strings.
    """
    path = monthly_csv_path(person, year_month)
    header, rows = _read_csv_rows(path)
    if not header:
        return []
    out: list[dict] = []
    numeric_keys = {"session", "num", "set", "reps", "kg", "volume",
                    "distance", "avg_hr", "active_cal", "total_cal",
                    "elevation_m"}
    for raw in rows:
        d = _row_to_dict(raw)
        # Date stays as YYYY-MM-DD string; coerce numerics.
        for k in numeric_keys:
            v = d.get(k)
            if v is None:
                continue
            d[k] = _numeric_cell(v)
        out.append(d)
    return out


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
        pass
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
        if is_strength:
            for i, rd in enumerate(sess["rows"]):
                if kinds[i] == "cardio":
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
        volume_sum = 0.0
        for idx, rd in enumerate(sess["rows"]):
            data_row = _build_data_row(session_num, rd, kinds[idx], is_strength)
            v = data_row.get("volume")
            if v:
                volume_sum += float(v)
            out_rows.append(_dict_to_row(data_row))

        if is_strength:
            total_row = _build_total_row(
                session_num, sess, hoist,
                volume_sum if volume_sum else None,
                deload_present,
            )
            out_rows.append(_dict_to_row(total_row))

    ensure_monthly_dir(person)
    _write_csv_atomic(path, out_rows)


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
    here — swim lap count is sourced from ``swim_workouts.csv`` only.)

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
    by_month: dict[str, list[dict]] = {}
    for r in rows:
        d = str(r.get("date") or "")[:10]
        if not d or len(d) != 10:
            continue
        key = f"{d[:4]}.{d[5:7]}"
        if not allow_past_months and key != current_month:
            skipped_past_month += 1
            continue
        by_month.setdefault(key, []).append(r)

    if not by_month:
        if skipped_past_month:
            return [
                f"Auto-cardio: 0 rows considered "
                f"({skipped_past_month} skipped — past months are not re-scanned)"
            ]
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
            notes_v = rd.get("notes") or ""
            is_auto = AUTO_IMPORT_NOTE.lower() in str(notes_v).lower()
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
            note_value = (
                f"{AUTO_IMPORT_NOTE} | source: {machine_tag}"
                if machine_tag else AUTO_IMPORT_NOTE
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
                "notes":       note_value,
                "distance":    _numeric_cell(distance),
                "duration":    _format_duration_mmss(dur_f),
                "pace":        _format_pace_min_per_km(dur_f, distance),
                "avg_hr":      _numeric_cell(avg_hr),
                "active_cal":  int(round(r["active_cal"])) if isinstance(r.get("active_cal"), (int, float)) and r.get("active_cal") else None,
                "total_cal":   int(round(r["total_cal"])) if isinstance(r.get("total_cal"), (int, float)) and r.get("total_cal") else None,
                "elevation_m": int(round(r["elevation_m"])) if isinstance(r.get("elevation_m"), (int, float)) and r.get("elevation_m") else None,
                "elapsed":     _format_elapsed_hms(r.get("elapsed_min")),
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
    if skipped_past_month:
        summaries.append(
            f"Auto-cardio: {skipped_past_month} input rows skipped "
            f"(dated outside the current month {current_month})"
        )
    return summaries


# ============================================================ upsert strength
def upsert_monthly_strength_session(person: str,
                                    sessions: list[dict],
                                    today_d: date | None = None) -> list[str]:
    """Annotate the TOTAL row of each matching strength session with
    Apple-watch session metadata (Duration, Avg HR, Active/Total Cal,
    Elevation, Elapsed). Sparse-merge + 5% drift guard preserves manual edits.

    Same contract as the xlsx-era ``upsert_monthly_strength_session``;
    only the storage backend changed. Current-month gate enforced.
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
        if month_key != current_month:
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
