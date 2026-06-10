"""Monthly CSV coercion, formatting, and classification helpers."""
from __future__ import annotations

import re
import sys
from datetime import date, datetime

from .monthly_csv_schema import (
    AUTO_IMPORT_NOTE,
    DELOAD_MARKER_TEXT,
    STRENGTH_METADATA_DRIFT_THRESHOLD,
)

__all__ = [
    "DURATION_VS_ELAPSED_RATIO_THRESHOLD",
    "PACE_MIN_PER_KM_LOWER",
    "PACE_MIN_PER_KM_UPPER",
    "date_str",
]

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


def _migrate_source_from_notes(rd: dict) -> None:
    """In-place migration: pre-2026-05 rows stashed the auto-import flag
    in Notes (e.g. ``"auto-imported from Apple"`` or
    ``"auto-imported from Apple | source: Matrix T7xi"``). The new
    schema has a typed ``source`` column. This helper:

      - If ``source`` is already set → no-op (already migrated).
      - If Notes carries the legacy prefix → extract any gymkit tag
        (after ``"source: "``) into ``source``, strip the prefix from
        Notes (Notes returns to user-supplied annotations only).
      - Else (manual row, no prefix) → set ``source = "manual"`` so
        every row has an explicit origin.

    Idempotent; runs on every canonicalize pass. The first pass cleans
    the file; subsequent passes are no-ops.
    """
    if (rd.get("source") or "").strip():
        return
    notes_v = (rd.get("notes") or "")
    notes_str = str(notes_v).strip()
    if AUTO_IMPORT_NOTE.lower() in notes_str.lower():
        # Try to extract a gymkit machine tag (after "source: ").
        machine_tag: str | None = None
        idx = notes_str.lower().find("source:")
        if idx >= 0:
            machine_tag = notes_str[idx + len("source:"):].strip()
            # Trim leading pipes / whitespace that the prefix builder
            # produced (``" | source: <tag>"``).
            machine_tag = machine_tag.lstrip("| ").strip() or None
        rd["source"] = f"gymkit:{machine_tag}" if machine_tag else "apple"
        # Strip the legacy prefix from Notes. Anything that follows the
        # auto-import marker (user annotation) is preserved.
        lower = notes_str.lower()
        marker_idx = lower.find(AUTO_IMPORT_NOTE.lower())
        before = notes_str[:marker_idx].rstrip(" |;,")
        end_of_marker = marker_idx + len(AUTO_IMPORT_NOTE)
        # If the tail starts with "| source: <tag>", drop the whole tag
        # segment (it's already captured in the new column).
        after = notes_str[end_of_marker:]
        if "source:" in after.lower():
            cut = after.lower().find("source:")
            # Find end-of-segment (next pipe / semicolon / end-of-string)
            tail = after[cut + len("source:"):]
            for sep in ("|", ";"):
                p = tail.find(sep)
                if p >= 0:
                    tail = tail[p + 1:]
                    break
                else:
                    tail = ""
            # `before-of-source` was the whitespace/pipe between the
            # marker and "source:" — discard.
            after = tail
        cleaned = " ".join(filter(None, [before, after.strip(" |;,")])).strip(" |;,")
        rd["notes"] = cleaned or None
    else:
        rd["source"] = "manual"


def _renumber_in_emit_order(
    strength_built: list[dict], cardio_built: list[dict]
) -> None:
    """Rewrite each row's ``num`` so it's sequential in emit order.

    Strength + other rows share a num across consecutive sets of the
    same exercise (one num per exercise — the canonical strength
    convention). Cardio rows get a fresh num per row (each Apple
    workout is its own session, even when two cycling rides share the
    "Outdoor Cycling" exercise name). In-place.

    Self-heals duplicate ``#`` values that occur when ``/log`` writes a
    strength session with fresh `num=1..N` after the auto-cardio importer
    has already written cardio rows with their own `num=1..M`. A clean
    pre-canonicalize file is a no-op.
    """
    current_ex: str | None = None
    counter = 0
    for row in strength_built:
        ex = row.get("exercise")
        if ex != current_ex:
            counter += 1
            current_ex = ex
        row["num"] = counter
    for row in cardio_built:
        counter += 1
        row["num"] = counter


def _is_isometric_hold(rd: dict) -> bool:
    """A manual hold (Dead Hang, Plank, etc.): reps=0, kg=0, no distance,
    but a populated duration. The duration is per-set hold time and must
    stay on the row rather than being hoisted to the strength TOTAL.
    """
    if _to_num(rd.get("reps")) > 0:
        return False
    if _to_num(rd.get("kg")) > 0:
        return False
    if _to_num(rd.get("distance")) > 0:
        return False
    return _parse_duration_minutes(rd.get("duration")) is not None


def _is_auto_imported(rd: dict) -> bool:
    """True when a row was auto-imported from Apple Health.

    Reads the ``source`` column (post-2026-05 schema). Falls back to
    the legacy Notes prefix (``"auto-imported from Apple"``) for rows
    that haven't been canonicalized to the new schema yet — first
    canonicalize pass migrates them, so this fallback is a one-shot
    guard, not permanent dual-write.
    """
    src = (rd.get("source") or "").strip().lower()
    if src in ("apple",) or src.startswith("apple@") or src.startswith("gymkit:"):
        return True
    notes_v = rd.get("notes") or ""
    return AUTO_IMPORT_NOTE.lower() in str(notes_v).lower()


def _classify_session_rows(rows: list[dict]) -> tuple[list[str], bool]:
    """Per-row strength/cardio/other classification + is_strength bool.

    A row is ``cardio`` if it has positive distance, OR is auto-imported
    (Apple/GymKit) — including the duration-only auto-imported case for
    indoor cycling / HIIT where the source provides time + calories but
    no distance. Manual duration-only rows (isometric holds like Dead
    Hang, Plank, farmer carries) are ``other``: they're part of the
    strength session, not cardio, and must sort with the strength rows
    rather than being demoted below the TOTAL row.
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
        if _is_auto_imported(rd):
            kinds.append("cardio")
            continue
        kinds.append("other")
    return kinds, ("strength" in kinds)


# ============================================================ Auto-cardio + drift
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
