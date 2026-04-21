"""Read Workout Tracker.xlsx for /coach analysis.

Emits one JSON blob on stdout with everything the coach needs:
  - today, days_since_last_session, last_session_date
  - rows: flat list of every set from the last N months (default 3)
  - progression_summary: last vs. previous working set per exercise
  - deloads: dates whose first row has Notes 'Deload Workout'
  - weeks_since_last_deload: float, or null if no deload on record
  - cardio_last_14d: zone2_minutes, interval_sessions, total_distance_km
  - bodyweight_recent: last 12 weigh-ins from the Bodyweight sheet
  - bodyweight_trend_kg_per_week: slope over the last 8 entries, or null
  - bodyweight_latest: {date, kg} of the most recent entry, or null

Usage:
    python3 read_tracker.py "<tracker path>" [--months 3] [--today YYYY-MM-DD]

Keeping the model out of the weeds on format quirks (string vs datetime dates,
stringified numbers, casing inconsistency, empty-row streaks) is the whole
point — the skill body points at this script instead of redoing it each run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl

MONTHLY_RE = re.compile(r"^\d{4}\.\d{2}$")
DELOAD_MARKER = "deload workout"
EMPTY_STREAK_STOP = 10


# ---------- helpers ----------
def normalize_date(v) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return str(v).strip().split(" ")[0]


def to_float(v) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def to_int_or_none(v):
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parse_duration_minutes(raw) -> float:
    """Accept '30:00', '28:30', '30', 30, 30.0 — return minutes as float."""
    if raw in (None, ""):
        return 0.0
    s = str(raw).strip()
    if ":" in s:
        parts = s.split(":")
        try:
            mm = int(parts[0])
            ss = int(parts[1]) if len(parts) > 1 else 0
            return mm + ss / 60.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_distance_km(raw) -> float:
    """Accept '5', '5.0', '8,79' (German decimal), 5, 5.0."""
    if raw in (None, ""):
        return 0.0
    s = str(raw).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


# ---------- extraction ----------
def extract_rows(wb, months_back: int, today_d: date) -> list[dict]:
    cutoff = today_d - timedelta(days=months_back * 31)
    data_sheets = sorted(
        [s for s in wb.sheetnames if MONTHLY_RE.match(s)],
        reverse=True,
    )

    rows: list[dict] = []
    for name in data_sheets:
        # Quick filter: sheet YYYY.MM vs cutoff
        y, m = name.split(".")
        first_of_month = date(int(y), int(m), 1)
        if first_of_month < cutoff.replace(day=1):
            continue

        ws = wb[name]
        current_date: str | None = None
        empty_streak = 0

        for raw in ws.iter_rows(min_row=2, values_only=True):
            date_val, num, exercise, set_n, reps, kg, volume, notes, *rest = (list(raw) + [None] * 12)[:12]
            distance, duration, pace, avg_hr = rest[:4] if len(rest) >= 4 else (None, None, None, None)

            if date_val is None and exercise is None:
                empty_streak += 1
                if empty_streak >= EMPTY_STREAK_STOP:
                    break
                continue
            empty_streak = 0

            if date_val is not None:
                current_date = normalize_date(date_val)
            if exercise is None or current_date is None:
                continue

            rows.append({
                "date": current_date,
                "num": num,
                "exercise": str(exercise).strip(),
                "set": set_n,
                "reps": to_int_or_none(reps),
                "kg": to_float(kg),
                "volume": to_float(volume),
                "notes": (str(notes).strip() if notes else None),
                "distance_km": parse_distance_km(distance) if distance else None,
                "duration_min": parse_duration_minutes(duration) if duration else None,
                "pace": str(pace).strip() if pace else None,
                "avg_hr": to_int_or_none(avg_hr),
            })

    rows.sort(key=lambda r: (r["date"], r["num"] or 0, r["set"] or 0))
    return rows


def progression_summary(rows: list[dict]) -> list[dict]:
    """Last and previous best working set per exercise (warmups excluded)."""
    by_ex: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("notes") and "warmup" in r["notes"].lower():
            continue
        if not r.get("kg") or not r.get("reps"):
            continue
        by_ex.setdefault(r["exercise"].lower(), []).append(r)

    summary = []
    for canon_lower, sets in by_ex.items():
        # Group by date, pick heaviest (kg, then reps) per session.
        by_date: dict[str, dict] = {}
        for s in sets:
            cur = by_date.get(s["date"])
            if cur is None or (s["kg"], s["reps"]) > (cur["kg"], cur["reps"]):
                by_date[s["date"]] = s
        dates_desc = sorted(by_date.keys(), reverse=True)
        if len(dates_desc) < 1:
            continue
        last = by_date[dates_desc[0]]
        prev = by_date[dates_desc[1]] if len(dates_desc) >= 2 else None
        summary.append({
            "exercise": last["exercise"],
            "sessions_logged": len(dates_desc),
            "last": f"{dates_desc[0]} → {int(last['kg'])}kg x {last['reps']}",
            "prev": f"{dates_desc[1]} → {int(prev['kg'])}kg x {prev['reps']}" if prev else None,
        })

    summary.sort(key=lambda s: s["exercise"].lower())
    return summary


def find_deloads(wb) -> list[str]:
    """Dates whose first populated row has Notes containing 'Deload Workout'."""
    deloads: set[str] = set()
    for name in wb.sheetnames:
        if not MONTHLY_RE.match(name):
            continue
        ws = wb[name]
        current_date: str | None = None
        seen_dates: set[str] = set()
        empty_streak = 0
        for raw in ws.iter_rows(min_row=2, values_only=True):
            vals = list(raw) + [None] * 12
            date_val, _, exercise, _, _, _, _, notes = vals[:8]
            if date_val is None and exercise is None:
                empty_streak += 1
                if empty_streak >= EMPTY_STREAK_STOP:
                    break
                continue
            empty_streak = 0
            if date_val is not None:
                current_date = normalize_date(date_val)
            if current_date is None or exercise is None:
                continue
            # Only the first row of a date can mark the session as a deload.
            if current_date in seen_dates:
                continue
            seen_dates.add(current_date)
            if notes and DELOAD_MARKER in str(notes).lower():
                deloads.add(current_date)
    return sorted(deloads)


def read_bodyweight(wb) -> list[dict]:
    """Return all Bodyweight entries sorted ascending by date.

    Each entry: {"date": "YYYY-MM-DD", "kg": float, "notes": str|None}.
    Returns [] if the sheet is missing. The Bodyweight sheet owes its
    morning/empty-stomach convention to the /log capture flow; a non-empty
    `notes` usually marks an exception to that convention.
    """
    if "Bodyweight" not in wb.sheetnames:
        return []
    ws = wb["Bodyweight"]
    out: list[dict] = []
    for raw in ws.iter_rows(min_row=2, values_only=True):
        if not raw or raw[0] in (None, ""):
            continue
        date_str = normalize_date(raw[0])
        if date_str is None:
            continue
        try:
            kg = float(raw[1]) if raw[1] not in (None, "") else None
        except (TypeError, ValueError):
            continue
        if kg is None:
            continue
        notes = raw[2] if len(raw) > 2 else None
        out.append({
            "date": date_str,
            "kg": kg,
            "notes": (str(notes).strip() if notes else None),
        })
    out.sort(key=lambda e: e["date"])
    return out


def bodyweight_trend_kg_per_week(entries: list[dict]) -> float | None:
    """Simple slope over the last 8 entries: (last_kg - first_kg) / weeks_between.

    Returns None if fewer than 3 entries or the span is <7 days (too noisy).
    Excludes entries with notes flagging non-morning/non-fasted context.
    """
    clean = [e for e in entries if not _is_flagged_nonfasted(e)]
    window = clean[-8:]
    if len(window) < 3:
        return None
    first_d = datetime.strptime(window[0]["date"], "%Y-%m-%d").date()
    last_d = datetime.strptime(window[-1]["date"], "%Y-%m-%d").date()
    days = (last_d - first_d).days
    if days < 7:
        return None
    weeks = days / 7.0
    return round((window[-1]["kg"] - window[0]["kg"]) / weeks, 3)


def _is_flagged_nonfasted(entry: dict) -> bool:
    notes = (entry.get("notes") or "").lower()
    return any(k in notes for k in ("not fasted", "evening", "after", "post-meal"))


def cardio_last_14d(rows: list[dict], today_d: date) -> dict:
    cutoff = today_d - timedelta(days=14)
    zone2_min = 0.0
    intervals = 0
    distance = 0.0
    for r in rows:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            continue
        # Cardio rows have non-zero distance or duration.
        dur = r.get("duration_min") or 0
        dist = r.get("distance_km") or 0
        if dur == 0 and dist == 0:
            continue
        distance += dist
        note = (r.get("notes") or "").lower()
        hr = r.get("avg_hr") or 0
        is_intervals = any(k in note for k in ("interval", "zone 4", "zone 5", "z4", "z5")) or hr >= 165
        if is_intervals:
            intervals += 1
        else:
            zone2_min += dur
    return {
        "zone2_minutes": round(zone2_min, 1),
        "interval_sessions": intervals,
        "total_distance_km": round(distance, 2),
    }


# ---------- main ----------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tracker", type=Path)
    ap.add_argument("--months", type=int, default=3, help="How many months back to include in rows")
    ap.add_argument("--today", default=None, help="Override today's date (YYYY-MM-DD) for testing")
    args = ap.parse_args()

    if not args.tracker.exists():
        print(f"ERROR: tracker not found: {args.tracker}", file=sys.stderr)
        return 1

    today_d = (
        datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    )

    wb = openpyxl.load_workbook(args.tracker, data_only=True)
    rows = extract_rows(wb, args.months, today_d)
    deloads = find_deloads(wb)

    last_session = max((r["date"] for r in rows), default=None)
    days_since = None
    if last_session:
        d = datetime.strptime(last_session, "%Y-%m-%d").date()
        days_since = (today_d - d).days

    weeks_since_deload = None
    if deloads:
        d = datetime.strptime(deloads[-1], "%Y-%m-%d").date()
        weeks_since_deload = round((today_d - d).days / 7.0, 1)

    bw_all = read_bodyweight(wb)
    bw_recent = bw_all[-12:]
    bw_latest = (
        {"date": bw_all[-1]["date"], "kg": bw_all[-1]["kg"]}
        if bw_all else None
    )

    out = {
        "today": today_d.strftime("%Y-%m-%d"),
        "last_session_date": last_session,
        "days_since_last_session": days_since,
        "deloads": deloads,
        "weeks_since_last_deload": weeks_since_deload,
        "cardio_last_14d": cardio_last_14d(rows, today_d),
        "bodyweight_latest": bw_latest,
        "bodyweight_trend_kg_per_week": bodyweight_trend_kg_per_week(bw_all),
        "bodyweight_recent": bw_recent,
        "progression_summary": progression_summary(rows),
        "rows": rows,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
