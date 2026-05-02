"""Strength-side analytics: volume, e1RM, stale-exercise detection,
strength-session HR trend, per-muscle HR-at-volume divergence.

All functions consume the flat ``rows`` list from ``extract.extract_rows``
plus the parsed ``exercises-database.md`` (``db``) and emit decisions
the LLM can read directly.

Functions:

- ``strength_session_avg_hr_trend(sessions, strength_dates)`` — slope of
  strength-session avg HR per 4 weeks. Catches running-hot patterns.
- ``weekly_volume_per_muscle(rows, db, today_d, window_days, unknown_out)``
  — fractional hard-set count per muscle (primary 1.0, synergist 0.5).
  Reports muscle landmarks alongside the current count.
- ``estimated_1rm(rows, deload_dates, include_history)`` — Epley
  projection per exercise with current/prev/best, slope, confidence,
  and stalled-session count.
- ``stale_exercises(rows, db, today_d, threshold_days)`` — exercises
  whose last appearance is ≥ ``threshold_days`` ago, sorted newest-
  stale first (cardio + warmup excluded).
- ``hr_at_volume_divergence(rows, monthly_sessions, db, today_d,
  window_weeks)`` — per-muscle volume-weighted slope of strength-session
  avg HR. Flags fatigue or improving conditioning by group.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

# Sibling lib/ on sys.path so this module is importable on its own.
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from constants import VOLUME_LANDMARKS
from parsing import _parse_iso_date
from sessions import _is_working_set


# History length cap for ``estimated_1rm[exercise].e1rm_history``. The slope
# field already summarises the trajectory; the LLM rarely needs more than the
# top of the list to spot-check confidence and grain. Cutting from 6 → 3
# entries removes ~50% of the per-exercise payload.
E1RM_HISTORY_LIMIT = 3


def strength_session_avg_hr_trend(
    sessions: list[dict],
    strength_dates: set[str],
) -> float | None:
    """Slope per 4 weeks of avg HR over the last 8 strength sessions.

    Matches Apple workouts to logged strength sessions by date. A rising
    avg HR on a stable load is a fatigue signal; the planning rule uses
    this to hold load when HR is creeping up.
    """
    matched: list[tuple[date, float]] = []
    for s in sessions:
        if s.get("date") not in strength_dates:
            continue
        avg = s.get("avg_hr")
        if avg in (None, 0):
            continue
        d = _parse_iso_date(s.get("date"))
        if d is None:
            continue
        matched.append((d, float(avg)))
    if len(matched) < 4:
        return None
    matched.sort(key=lambda p: p[0])
    matched = matched[-8:]
    span_days = (matched[-1][0] - matched[0][0]).days
    if span_days < 21:
        return None
    base = matched[0][0]
    xs = [(p[0] - base).days for p in matched]
    ys = [p[1] for p in matched]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    if den <= 0:
        return None
    return round((num / den) * 28.0, 2)


def weekly_volume_per_muscle(
    rows: list[dict],
    db: dict[str, dict],
    today_d: date,
    window_days: int,
    unknown_out: set[str],
) -> dict:
    """Fractional hard-set count per muscle over the last ``window_days``.

    Primary muscle = 1.0 set, each synergist = 0.5 set (per training-science
    §1). Warmup exercises (database section) and warmup-marked sets are
    skipped. Unknown exercises — logged names that don't appear in the db —
    are collected into ``unknown_out`` for the caller to surface.
    """
    cutoff = today_d - timedelta(days=window_days)
    sets: dict[str, float] = defaultdict(float)
    for r in rows:
        if not _is_working_set(r):
            continue
        d = _parse_iso_date(r.get("date"))
        if d is None:
            continue
        if d < cutoff:
            continue
        entry = db.get(r["exercise"].lower())
        if entry is None:
            unknown_out.add(r["exercise"])
            continue
        if entry.get("is_warmup"):
            continue
        if entry["primary"]:
            sets[entry["primary"]] += 1.0
        for syn in entry["synergists"]:
            sets[syn] += 0.5

    current = {m: round(v, 1) for m, v in sets.items()}
    landmarks = {m: VOLUME_LANDMARKS[m] for m in current if m in VOLUME_LANDMARKS}
    return {
        "window_days": window_days,
        "current": current,
        "landmarks": landmarks,
    }


def estimated_1rm(rows: list[dict],
                  deload_dates: list[str] | None = None,
                  include_history: bool = False) -> dict:
    """Epley 1RM projection per exercise, with trajectory and confidence.

    For each exercise, take the heaviest projected e1RM per date (over all
    working sets that session) and report:
      - current/prev/best/last_date and current-vs-prev delta in kg
      - e1rm_history: last 6 sessions newest-first, each with the top set
        that produced the e1RM (so the coach can judge rep-range quality)
      - slope_kg_per_4w: OLS slope over the last 6 sessions, scaled to a
        4-week window. Null if fewer than 3 sessions.
      - confidence: high|medium|low based on the rep ranges of the last
        3 top sets — Epley is most accurate at 3-8 reps.
      - stalled_sessions: count of consecutive most-recent sessions with
        |Δe1RM| ≤ 0.5kg, broken by any deload that falls in the window.

    Bodyweight and warmup sets excluded (kg must be > 0).
    """
    deload_set = set(deload_dates or [])

    by_ex: dict[str, list[dict]] = {}
    canonical_name: dict[str, str] = {}
    for r in rows:
        if not _is_working_set(r):
            continue
        kg = r.get("kg") or 0
        reps = r.get("reps") or 0
        if kg <= 0 or reps <= 0:
            continue
        key = r["exercise"].lower()
        canonical_name.setdefault(key, r["exercise"])
        e1rm = kg * (1.0 + reps / 30.0)
        by_ex.setdefault(key, []).append({
            "date": r["date"], "e1rm": e1rm, "reps": reps, "kg": kg,
        })

    out: dict[str, dict] = {}
    for key, entries in by_ex.items():
        # Per date, keep the heaviest projected e1RM and remember the
        # (reps, kg) that produced it — needed for the history block and
        # for the confidence judgement.
        per_date: dict[str, dict] = {}
        for e in entries:
            top = per_date.get(e["date"])
            if top is None or e["e1rm"] > top["e1rm"]:
                per_date[e["date"]] = {
                    "e1rm": e["e1rm"], "reps": e["reps"], "kg": e["kg"],
                }
        dates_desc = sorted(per_date.keys(), reverse=True)
        if not dates_desc:
            continue
        current = per_date[dates_desc[0]]["e1rm"]
        prev = per_date[dates_desc[1]]["e1rm"] if len(dates_desc) >= 2 else None
        best = max(d["e1rm"] for d in per_date.values())

        # Slope is computed over the last 6 sessions for stability, even
        # though the emitted history is capped at E1RM_HISTORY_LIMIT.
        slope_dates = dates_desc[:6]
        history_full = [
            {
                "date":         d,
                "e1rm_kg":      round(per_date[d]["e1rm"], 1),
                "top_set_reps": per_date[d]["reps"],
                "top_set_kg":   per_date[d]["kg"],
            }
            for d in slope_dates
        ]
        history = history_full[:E1RM_HISTORY_LIMIT]

        # OLS slope (kg per 28 days) over the last 6 sessions. Use
        # ``history_full``, not the emitted ``history`` — the trim is
        # cosmetic for the JSON output, but the trend should still see all
        # six sessions to stay stable.
        slope = None
        if len(history_full) >= 3:
            pts: list[tuple[date, float]] = []
            for h in history_full:
                hd = _parse_iso_date(h.get("date"))
                if hd is None:
                    continue
                pts.append((hd, h["e1rm_kg"]))
            if len(pts) >= 3:
                pts.sort(key=lambda p: p[0])
                base = pts[0][0]
                xs = [(p[0] - base).days for p in pts]
                ys = [p[1] for p in pts]
                n = len(xs)
                mx = sum(xs) / n
                my = sum(ys) / n
                num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
                den = sum((xs[i] - mx) ** 2 for i in range(n))
                if den > 0:
                    slope = round((num / den) * 28.0, 2)

        # Confidence from rep ranges of the last 3 sessions' top sets.
        # Epley is calibrated best for low-rep sets; 12+ rep top sets
        # give a noisy projection. Pulled from the un-capped history so
        # confidence is consistent regardless of the emitted limit.
        recent_reps = [h["top_set_reps"] for h in history_full[:3]]
        if len(recent_reps) < 2:
            confidence = "low"
        elif any(r >= 13 for r in recent_reps):
            confidence = "low"
        elif all(3 <= r <= 8 for r in recent_reps):
            confidence = "high"
        else:
            confidence = "medium"

        # Stalled: walk back through consecutive sessions while the
        # e1RM swing is within ±0.5kg. Break on the first deload that
        # falls inside (or at either end of) the gap between two
        # consecutive sessions — a deliberate volume cut isn't a stall.
        stalled = 0
        for i in range(len(dates_desc) - 1):
            this_date = dates_desc[i]
            prev_date = dates_desc[i + 1]
            crossed_deload = any(
                prev_date <= d <= this_date for d in deload_set
            )
            if crossed_deload:
                break
            this_e = per_date[this_date]["e1rm"]
            prev_e = per_date[prev_date]["e1rm"]
            if abs(this_e - prev_e) <= 0.5:
                stalled += 1
            else:
                break

        # Drop e1rm_history entirely unless explicitly opted in. The
        # summary fields (current/prev/best, slope, confidence,
        # stalled_sessions) cover every coaching decision; the per-session
        # history is debug-only and added ~10 KB to the default output.
        emit_history = include_history and not (confidence == "low" and slope is None)

        out[canonical_name[key]] = {
            "current_e1rm_kg":  round(current, 1),
            "prev_e1rm_kg":     round(prev, 1) if prev is not None else None,
            "best_e1rm_kg":     round(best, 1),
            "last_date":        dates_desc[0],
            "delta_vs_prev_kg": (round(current - prev, 1) if prev is not None else None),
            "e1rm_history":     history if emit_history else None,
            "slope_kg_per_4w":  slope,
            "confidence":       confidence,
            "stalled_sessions": stalled,
        }
    return out


def stale_exercises(
    rows: list[dict], db: dict[str, dict], today_d: date, threshold_days: int
) -> list[dict]:
    """Exercises whose last appearance is ≥ ``threshold_days`` ago.

    Warmup-section exercises are excluded — those cycle on and off by
    design. Useful for spotting movements that were tried once or twice and
    dropped; the coach can decide whether to retire or reintroduce them.
    """
    last_seen: dict[str, str] = {}
    sessions_count: dict[str, set[str]] = defaultdict(set)
    canonical: dict[str, str] = {}
    for r in rows:
        if not _is_working_set(r):
            continue
        key = r["exercise"].lower()
        entry = db.get(key)
        if entry and (entry.get("is_warmup") or entry.get("is_cardio")):
            continue
        canonical.setdefault(key, r["exercise"])
        if r["date"] > last_seen.get(key, ""):
            last_seen[key] = r["date"]
        sessions_count[key].add(r["date"])

    out = []
    for key, last in last_seen.items():
        d = _parse_iso_date(last)
        if d is None:
            continue
        days = (today_d - d).days
        if days < threshold_days:
            continue
        out.append({
            "exercise":        canonical[key],
            "last_date":       last,
            "weeks_since":     round(days / 7.0, 1),
            "sessions_logged": len(sessions_count[key]),
        })
    out.sort(key=lambda e: e["weeks_since"], reverse=True)
    return out


def hr_at_volume_divergence(rows: list[dict],
                             monthly_sessions: list[dict],
                             db: dict, today_d: date,
                             window_weeks: int = 8) -> dict:
    """Per-muscle-group HR-creep signal at constant volume.

    For each muscle group, regress ``session_avg_hr`` against time over
    the last ``window_weeks`` weeks of strength sessions, weighting by
    that session's volume into the muscle. Positive slope (HR rising at
    same volume) suggests fatigue; negative slope is improving
    conditioning. Returns ``{muscle: {slope_bpm_per_4w, n_sessions, hint}}``.
    """
    if not monthly_sessions:
        return {}
    cutoff = today_d - timedelta(days=window_weeks * 7)
    # Build date → strength session avg_hr lookup.
    strength_hr: dict[str, float] = {}
    for s in monthly_sessions:
        if s.get("session_kind") != "strength":
            continue
        if s.get("avg_hr") in (None, 0):
            continue
        d = _parse_iso_date(s.get("date"))
        if d is None:
            continue
        if d < cutoff:
            continue
        strength_hr[s["date"]] = float(s["avg_hr"])
    if len(strength_hr) < 4:
        return {}

    # Roll up rows by (date, muscle) → volume.
    per_date_muscle: dict[tuple[str, str], float] = {}
    for r in rows:
        if not _is_working_set(r):
            continue
        if r["date"] not in strength_hr:
            continue
        muscles = db.get(r["exercise"].lower())
        if not muscles:
            continue
        primary = muscles.get("primary") if isinstance(muscles, dict) else None
        if not primary:
            continue
        vol = (r.get("volume") or 0)
        per_date_muscle[(r["date"], primary)] = (
            per_date_muscle.get((r["date"], primary), 0.0) + vol
        )

    by_muscle: dict[str, list[tuple[date, float, float]]] = {}
    for (d_str, muscle), vol in per_date_muscle.items():
        if vol <= 0:
            continue
        d = _parse_iso_date(d_str)
        if d is None:
            continue
        by_muscle.setdefault(muscle, []).append((d, strength_hr[d_str], vol))

    out: dict[str, dict] = {}
    for muscle, points in by_muscle.items():
        # Require at least 6 sessions before a slope is published —
        # smaller samples have too much variance for the ±5 bpm/4w
        # threshold to mean anything.
        if len(points) < 6:
            continue
        points.sort(key=lambda p: p[0])
        base = points[0][0]
        xs = [(p[0] - base).days for p in points]
        ys = [p[1] for p in points]
        ws = [p[2] for p in points]
        sum_w = sum(ws)
        if sum_w <= 0:
            continue
        mx = sum(xs[i] * ws[i] for i in range(len(xs))) / sum_w
        my = sum(ys[i] * ws[i] for i in range(len(ys))) / sum_w
        num = sum(ws[i] * (xs[i] - mx) * (ys[i] - my) for i in range(len(xs)))
        den = sum(ws[i] * (xs[i] - mx) ** 2 for i in range(len(xs)))
        if den <= 0:
            continue
        slope_per_day = num / den
        slope_per_4w = slope_per_day * 28
        # ±5 bpm/4w is the magnitude that's clearly above noise floor for
        # a 6-12 session window. Below that, call it stable to avoid
        # crying wolf on every minor drift.
        if slope_per_4w >= 5:
            hint = "rising HR at constant volume — fatigue or under-recovery"
        elif slope_per_4w <= -5:
            hint = "falling HR at constant volume — improving conditioning"
        else:
            hint = "stable"
        out[muscle] = {
            "slope_bpm_per_4w": round(slope_per_4w, 2),
            "n_sessions":       len(points),
            "hint":             hint,
        }
    return out
