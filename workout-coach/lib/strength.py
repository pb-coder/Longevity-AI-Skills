"""Strength-side analytics: volume, e1RM, stale-exercise detection,
strength-session HR trend, per-muscle HR-at-volume divergence.

All functions consume the flat ``rows`` list from ``extract.extract_rows``
plus the parsed ``exercises-database.md`` (``db``) and emit decisions
the LLM can read directly.

Functions:
- ``weekly_volume_per_muscle(rows, db, today_d, window_days, unknown_out)``
  — fractional hard-set count per muscle (primary 1.0, synergist 0.5),
  normalized to sets-per-week over the window so it is apples-to-apples
  with the weekly landmarks. Emits the window mean (``current``), the
  per-week series (``per_week``) and its ``median`` so a single spiky
  week cannot masquerade as a steady weekly dose. Reports muscle
  landmarks alongside.
- ``estimated_1rm(rows, deload_dates, include_history)`` — Epley
  projection per exercise with current/prev/best, slope, confidence,
  and stalled-session count.
- ``stale_exercises(rows, db, today_d, threshold_days)`` — exercises
  whose last appearance is ≥ ``threshold_days`` ago, sorted newest-
  stale first (cardio + warmup excluded). The caller slices the head,
  so newest-stale-first is what makes it a reintroduction pool rather
  than a retirement pile.
- ``hr_at_volume_divergence(rows, monthly_sessions, db, today_d,
  window_weeks)`` — per-muscle volume-weighted slope of strength-session
  avg HR. Flags fatigue or improving conditioning by group.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta


from .constants import VOLUME_LANDMARKS
from .parsing import _parse_iso_date
from .sessions import _is_working_set


# History length cap for ``estimated_1rm[exercise].e1rm_history``. The slope
# field already summarises the trajectory; the LLM rarely needs more than the
# top of the list to spot-check confidence and grain. Cutting from 6 → 3
# entries removes ~50% of the per-exercise payload.
E1RM_HISTORY_LIMIT = 3


# Context-change Notes patterns. When a working set's Notes contain any of
# these substrings, the session is treated as a re-baselining event for the
# e1RM model — the row stays in history (so the user sees their actual
# lifts), but it's excluded from slope_kg_per_4w and from delta_vs_prev_kg
# baselines so a gym change doesn't read as a strength regression. Patterns
# are matched case-insensitively. Order doesn't matter; the predicate just
# needs to match once.
CONTEXT_CHANGE_NOTES_PATTERNS = (
    "new gym",
    "different gym",
    "this gym",            # "unusual cable ratio at this gym"
    "another gym",
    "new machine",
    "different machine",
    "new cable",
    "different cable",
    "unusual cable",       # "unusual cable ratio at this gym, very heavy"
    "cable ratio",
    "different weights",
    "new weights",
    "new equipment",
    "new technogym",
    "learning weights",
    "calibration",
)


def _is_context_change_note(notes) -> bool:
    """True when a Notes cell contains a user-tagged equipment/gym change."""
    if not notes:
        return False
    n = str(notes).lower()
    return any(p in n for p in CONTEXT_CHANGE_NOTES_PATTERNS)


def weekly_volume_per_muscle(
    rows: list[dict],
    db: dict[str, dict],
    today_d: date,
    window_days: int,
    unknown_out: set[str],
) -> dict:
    """Fractional hard-set count per muscle, as sets-per-week, plus which
    trainable landmark muscles got zero credited sets in the window.

    Primary muscle = 1.0 set, each synergist = 0.5 set (per training-science
    §1). Warmup exercises (database section) and warmup-marked sets are
    skipped. Unknown exercises — logged names that don't appear in the db —
    are collected into ``unknown_out`` for the caller to surface.

    ``current`` is **sets-per-week averaged over the window**: counts are
    summed across the stable ``window_days`` collection window (so the figure
    isn't a noisy single-week snapshot), then divided by ``window_days / 7``
    so the number is apples-to-apples with the WEEKLY ``VOLUME_LANDMARKS``
    (MEV/MAV/MRV). ``window_days`` is returned for transparency.

    The window is ``window_days`` CALENDAR days inclusive of ``today_d`` —
    i.e. ``[today_d - (window_days - 1), today_d]``, the same convention
    every other windowed helper uses. Rows dated after ``today_d`` are
    rejected so a backtest at an earlier ``--today`` cannot see the future.

    A window mean alone hides dispersion: a muscle trained once, hard, in
    week 1 and barely since reads the same as one trained steadily. So the
    per-week series (``per_week``, oldest week first) and its ``median``
    are emitted alongside. ``current`` keeps its exact prior semantics for
    existing consumers; read ``median`` when you need the typical week.

    ``window_days`` MUST be a whole number of weeks. The per-week buckets
    are 7 days wide, so a window that is not divisible by 7 leaves a short
    oldest bucket that is not comparable with the others: it drags
    ``median`` down and breaks the invariant that ``sum(per_week) /
    n_weeks == current``. Rather than silently emit a biased median for a
    window nobody currently passes, reject it.
    """
    if window_days <= 0 or window_days % 7 != 0:
        raise ValueError(
            "weekly_volume_per_muscle: window_days must be a positive whole "
            f"number of weeks (got {window_days}); the per_week buckets are "
            "7 days wide and a partial bucket biases median low"
        )
    cutoff = today_d - timedelta(days=max(window_days - 1, 0))
    # Week 0 is the most recent 7 days; the list is reversed to oldest-first
    # on emit. Exact division is safe now that the guard above rejects any
    # window_days that is not a whole number of weeks.
    n_weeks = window_days // 7
    sets: dict[str, float] = defaultdict(float)
    per_week_counts: dict[str, list[float]] = defaultdict(
        lambda: [0.0] * n_weeks
    )

    def _credit(muscle: str, amount: float, bucket: int) -> None:
        sets[muscle] += amount
        per_week_counts[muscle][bucket] += amount

    for r in rows:
        if not _is_working_set(r):
            continue
        d = _parse_iso_date(r.get("date"))
        if d is None:
            continue
        if d < cutoff or d > today_d:
            continue
        entry = db.get(r["exercise"].lower())
        if entry is None:
            unknown_out.add(r["exercise"])
            continue
        if entry.get("is_warmup"):
            continue
        bucket = min((today_d - d).days // 7, n_weeks - 1)
        if entry["primary"]:
            _credit(entry["primary"], 1.0, bucket)
        for syn in entry["synergists"]:
            _credit(syn, 0.5, bucket)

    weeks = window_days / 7.0
    current = {m: round(v / weeks, 1) for m, v in sets.items()}
    per_week = {
        m: [round(v, 1) for v in reversed(per_week_counts[m])]
        for m in current
    }
    median = {
        m: round(statistics.median(per_week_counts[m]), 1) for m in current
    }

    # Muscles the coach is structurally blind to: a landmark muscle with a
    # real MEV (mev > 0) that a catalog exercise CAN train, but which got
    # ZERO credited sets in the window. `current` only holds muscles with
    # >0 sets, so an abandoned muscle simply vanishes and the
    # "current < MEV → add a set" rule can never fire for it. Producible-set
    # filter keeps dead landmark keys (e.g. `abs`, which no catalog entry
    # emits — `core` is used instead) out of the list.
    producible: set[str] = set()
    for entry in db.values():
        if entry.get("primary"):
            producible.add(entry["primary"])
        for syn in entry.get("synergists") or []:
            producible.add(syn)
    neglected = sorted(
        m for m, lm in VOLUME_LANDMARKS.items()
        if lm.get("mev", 0) > 0 and m in producible and current.get(m, 0.0) == 0.0
    )

    landmarks = {m: VOLUME_LANDMARKS[m] for m in current if m in VOLUME_LANDMARKS}
    return {
        "window_days": window_days,
        "current": current,
        "per_week": per_week,
        "median": median,
        "landmarks": landmarks,
        "neglected_muscles": neglected,
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
            "date": r["date"],
            "e1rm": e1rm,
            "reps": reps,
            "kg": kg,
            "context_change": _is_context_change_note(r.get("notes")),
        })

    out: dict[str, dict] = {}
    for key, entries in by_ex.items():
        # Per date, keep the heaviest projected e1RM and remember the
        # (reps, kg) that produced it — needed for the history block and
        # for the confidence judgement. Track context-change as a date-
        # level flag so a non-ctx heaviest set doesn't silently mask a
        # ctx-tagged warmup/feeler set on the same date.
        per_date_top: dict[str, dict] = {}
        per_date_ctx: dict[str, bool] = {}
        for e in entries:
            d = e["date"]
            if e.get("context_change"):
                per_date_ctx[d] = True
            top = per_date_top.get(d)
            if top is None or e["e1rm"] > top["e1rm"]:
                per_date_top[d] = {
                    "e1rm": e["e1rm"], "reps": e["reps"], "kg": e["kg"],
                }
        per_date: dict[str, dict] = {
            d: {**top, "context_change": per_date_ctx.get(d, False)}
            for d, top in per_date_top.items()
        }
        dates_desc = sorted(per_date.keys(), reverse=True)
        if not dates_desc:
            continue
        current = per_date[dates_desc[0]]["e1rm"]

        # delta_vs_prev_kg baseline: walk back from the most recent date for
        # the most recent prior session whose context_change flag is False
        # AND whose own counterpart (the current session) is also non-
        # context-change. If either side of the comparison is context-
        # changed, the delta is meaningless equipment-shifted noise — emit
        # None and let confidence handling take over.
        current_is_ctx = per_date[dates_desc[0]].get("context_change", False)
        prev = None
        if not current_is_ctx and len(dates_desc) >= 2:
            for prior_date in dates_desc[1:]:
                if not per_date[prior_date].get("context_change", False):
                    prev = per_date[prior_date]["e1rm"]
                    break
        best = max(d["e1rm"] for d in per_date.values())

        # Slope is computed over the last 6 sessions for stability, even
        # though the emitted history is capped at E1RM_HISTORY_LIMIT. The
        # emitted history shows ALL recent sessions including context-
        # change ones (so the user sees what they actually lifted), but
        # the slope regression below filters them out.
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

        # Count excluded sessions in the slope window; the coach uses
        # these to soften "Are you getting stronger?" language across
        # equipment-shift discontinuities and deliberate deloads.
        context_change_excluded = sum(
            1 for d in slope_dates if per_date[d].get("context_change")
        )
        deload_excluded = sum(1 for d in slope_dates if d in deload_set)

        # OLS slope (kg per 28 days) over the last 6 sessions, EXCLUDING
        # context-change and deload dates. Use ``history_full``, not the
        # emitted ``history`` — the trim is cosmetic for the JSON output,
        # but the trend should still see all eligible sessions to stay
        # stable.
        slope = None
        slope_pts_source = [
            h for h in history_full
            if not per_date[h["date"]].get("context_change")
            and h["date"] not in deload_set
        ]
        if len(slope_pts_source) >= 3:
            pts: list[tuple[date, float]] = []
            for h in slope_pts_source:
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

        # If any session in the trailing window was excluded from slope
        # (gym swap, new machine, different cable scaling, or deliberate
        # deload), the remaining trend is narrower. Drop confidence one
        # band (high→medium, medium→low). The user sees the reason via
        # ``context_change_excluded`` / ``deload_excluded``.
        if context_change_excluded > 0 or deload_excluded > 0:
            confidence = {"high": "medium",
                          "medium": "low",
                          "low": "low"}[confidence]

        # Stalled: walk back through consecutive sessions while the
        # e1RM swing is within ±0.5kg. Break on the first deload that
        # falls inside (or at either end of) the gap between two
        # consecutive sessions — a deliberate volume cut isn't a stall.
        # Also break on context-change sessions: a gym swap isn't a stall.
        stalled = 0
        for i in range(len(dates_desc) - 1):
            this_date = dates_desc[i]
            prev_date = dates_desc[i + 1]
            crossed_deload = any(
                prev_date <= d <= this_date for d in deload_set
            )
            if crossed_deload:
                break
            if per_date[this_date].get("context_change") \
                    or per_date[prev_date].get("context_change"):
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
            "current_e1rm_kg":         round(current, 1),
            "prev_e1rm_kg":            round(prev, 1) if prev is not None else None,
            "best_e1rm_kg":            round(best, 1),
            "last_date":               dates_desc[0],
            "delta_vs_prev_kg":        (round(current - prev, 1) if prev is not None else None),
            "e1rm_history":            history if emit_history else None,
            "slope_kg_per_4w":         slope,
            "confidence":              confidence,
            "stalled_sessions":        stalled,
            "context_change_excluded": context_change_excluded,
            "deload_excluded":         deload_excluded,
        }
    return out


def stale_exercises(
    rows: list[dict], db: dict[str, dict], today_d: date, threshold_days: int
) -> list[dict]:
    """Exercises whose last appearance is ≥ ``threshold_days`` ago.

    Warmup-section exercises are excluded — those cycle on and off by
    design. Off-catalog (unknown) exercises are excluded too: a name not in
    ``db`` can no longer be canonically reintroduced (e.g. a retired
    ``[Band]`` movement), so surfacing it as "stale" is noise — it already
    shows up in ``unknown_exercises``. Useful for spotting movements that
    were tried once or twice and dropped; the coach can decide whether to
    retire or reintroduce them.

    Sorted **newest-stale first** — the movement that lapsed most
    recently leads. The caller slices the head of this list, so the sort
    direction decides what the reintroduction pool actually contains.
    Oldest-first sorted the RETIREMENT pile to the top: measured over
    four run dates six weeks apart the emitted head was byte-identical
    every time — five February one-offs with ``sessions_logged`` 1-2 —
    while 22 candidates with real multi-session history sat below the
    slice and could never surface. A movement dropped 30 weeks ago after
    one session is not a comeback candidate; one dropped 5 weeks ago
    after eleven sessions is. Ties break on more sessions logged, then
    on name, so the order is total and a run is reproducible.
    """
    last_seen: dict[str, str] = {}
    sessions_count: dict[str, set[str]] = defaultdict(set)
    canonical: dict[str, str] = {}
    for r in rows:
        if not _is_working_set(r):
            continue
        rd = _parse_iso_date(r.get("date"))
        if rd is None or rd > today_d:
            continue
        key = r["exercise"].lower()
        entry = db.get(key)
        if entry is None:
            continue
        if entry.get("is_warmup") or entry.get("is_cardio"):
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
    out.sort(key=lambda e: (e["weeks_since"], -e["sessions_logged"], e["exercise"]))
    return out


# A working load older than roughly four months is a guess, not a memory:
# the e1RM projection behind it has no support and the coach is told
# (SKILL.md, stale reintroduction) to restart such a movement
# submaximally anyway. Candidates past this line are therefore ranked
# last, not scored — they only fill the pool when nothing fresher exists.
REINTRODUCTION_MAX_WEEKS = 16.0


def reintroduction_pool(stale: list[dict], limit: int = 5,
                        max_weeks: float = REINTRODUCTION_MAX_WEEKS) -> list[dict]:
    """Pick the ``limit`` best comeback candidates out of ``stale``.

    ``stale_exercises`` answers "what has lapsed"; this answers "what is
    worth bringing back", which is a different question and the one the
    payload's capped list is actually used for.

    A naive prefix of the lapsed list answers neither well. Oldest-first
    handed the coach five ancient one-offs; newest-first hands it
    whatever happened to lapse most recently, which on real data is a
    single Plank session ahead of a movement with eleven.

    The ranking key is **evidence density** — ``sessions_logged /
    weeks_since``. It trades the two things that make a lapsed movement
    a good candidate against each other: how much history there is to
    restart from, and how stale the load that history implies has gone.
    Eleven sessions ten weeks ago outranks one session eight weeks ago;
    five sessions six weeks ago outranks five sessions twelve weeks ago.

    Candidates past ``max_weeks`` are excluded from the scored ranking
    and only used to top the pool up, so a long tail of one-offs cannot
    crowd out a live comeback on density alone.

    The returned list is re-sorted newest-stale first, which is the order
    the payload documents and the order a reader expects.
    """
    if limit <= 0 or not stale:
        return []
    scored = []
    tail = []
    for e in stale:
        weeks = float(e.get("weeks_since") or 0.0)
        entry = dict(e)
        entry["evidence_density"] = (
            round(float(e.get("sessions_logged") or 0) / weeks, 3)
            if weeks > 0 else None
        )
        (scored if weeks <= max_weeks else tail).append(entry)
    scored.sort(key=lambda e: (-(e["evidence_density"] or 0.0),
                               e["weeks_since"], e["exercise"]))
    picked = scored[:limit]
    if len(picked) < limit:
        picked += tail[:limit - len(picked)]
    picked.sort(key=lambda e: (e["weeks_since"], -e["sessions_logged"],
                               e["exercise"]))
    return picked


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

    The window is ``window_weeks * 7`` CALENDAR days inclusive of
    ``today_d`` — ``[today_d - (weeks*7 - 1), today_d]`` — the same
    convention ``weekly_volume_per_muscle`` and the ``recent_*`` helpers
    use. It previously ran one day long (57 inclusive days for an 8-week
    window), which let a session on the 57th day back into an 8-week
    regression.
    """
    if not monthly_sessions:
        return {}
    cutoff = today_d - timedelta(days=max(window_weeks * 7 - 1, 0))
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
        if d < cutoff or d > today_d:
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
    rising_flagged = [
        m for m, info in out.items()
        if float(info.get("slope_bpm_per_4w") or 0.0) >= 5
    ]
    if len(rising_flagged) > max(2, int(len(out) * 0.4)):
        out["systemic_session_hr"] = {
            "slope_bpm_per_4w": round(
                sum(out[m]["slope_bpm_per_4w"] for m in rising_flagged) / len(rising_flagged), 2
            ),
            "n_muscles": len(rising_flagged),
            "hint": (
                "session HR rose across many muscles — check bodyweight, "
                "deload boundary, heat, or generic fatigue before changing per-muscle volume"
            ),
        }
    return out
