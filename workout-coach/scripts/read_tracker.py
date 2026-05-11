"""Read the given person's CSV store for /coach analysis.

Emits one JSON blob on stdout organised around session-level signals
(decisions, not raw arrays). Top blocks:

  Source + capabilities:
  - today, data_source, capabilities, auto_cardio_enabled
  - estimated_max_hr, estimated_rest_hr — derived once at the top from
    Apple max-HR observations (XML) or 208 − 0.7×age (HL fallback;
    age is computed from Profile.birthday). Drives all HRR / TRIMP /
    Karvonen-zone math below.

  Strength + cardio sessions:
  - monthly_sessions: canonical per-session record incl. TRIMP /
    load_band (light/moderate/hard/red-line) / intensity_pct / max_hr /
    volume / is_deload, sourced from the TOTAL row's metadata + Apple
    per-workout max_hr. Replaces session_totals + workout_sessions_last_28d.
  - weekly_volume_per_muscle, estimated_1rm, progression_summary
  - stale_exercises (top 5), unknown_exercises
  - deloads (user-marked), auto_deload_candidates (Python-detected)

  Cardio rollup:
  - cardio_last_28d (sessions, minutes, distance, kcal)
  - cardio_hr_zones_28d (HRR-based time-in-zone via Karvonen)

  Recovery + training load (Python-derived):
  - recovery: 0-10 score with named drivers (HRV, RHR, sleep, wrist temp,
    HR Recovery 1-min, VO2max trend) + confidence
  - training_load: CTL/ATL/TSB rolling EWMA from per-session TRIMP
  - hr_at_volume_divergence: per-muscle slope of strength avg HR vs time

  Bodyweight:
  - bodyweight_latest, bodyweight_trend_kg_per_week

  Apple Health:
  - health_metrics_weekly (4-week aggregates; raw daily behind
    --include-daily-health)
  - vo2max_latest, vo2max_trend_per_4w

  Debug deep-dive (off by default):
  - rows: flat per-set list (--include-rows)
  - estimated_1rm.e1rm_history (--include-1rm-history)

Usage:
    python3 read_tracker.py --person <Name> [--months 3] [--today YYYY-MM-DD]
        [--include-rows] [--include-1rm-history] [--include-daily-health]
        [--pretty]

Keeping the model out of the weeds on format quirks (string vs datetime
dates, stringified numbers, casing inconsistency, empty-row streaks) is
the whole point — and going further, this script also computes the
training-science derivatives (TRIMP, recovery score, load bands, HR-at-
volume divergence) so the coach LLM consumes structured signals rather
than re-deriving them each run.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Bring in the shared/ tracker schemas + the local lib/ analytics modules.
# Each lib/ module also self-bootstraps its own sys.path so it can be
# imported in isolation (REPL, unit tests); the entry-point doing it
# here makes the imports work even before any lib/ module loads.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from csv_store import read_profile  # noqa: E402
from person_paths import monthly_dir  # noqa: E402
from constants import DEFAULT_DATA_SOURCE, SOURCE_CAPABILITIES  # noqa: E402
from parsing import _compact, _parse_iso_date  # noqa: E402
from extract import (  # noqa: E402
    _age_from_birthday,
    estimate_max_hr,
    extract_rows,
    find_deloads,
    load_exercises_db,
    read_bodyweight,
    read_health_metrics,
    read_swim_laps,
    read_swim_workouts,
    read_workout_sessions,
)
from health import (  # noqa: E402
    _mean_or_none,
    _values_in_window,
    health_metrics_weekly,
    latest_metric,
    metric_trend_per_4w,
    recovery_score,
)
from sessions import (  # noqa: E402
    _is_working_set,
    bodyweight_trend_kg_per_week,
    build_monthly_sessions,
    progression_summary,
)
from strength import (  # noqa: E402
    estimated_1rm,
    hr_at_volume_divergence,
    stale_exercises,
    weekly_volume_per_muscle,
)
from cardio import (  # noqa: E402
    auto_deload_candidates,
    cardio_hr_zones,
    cardio_last_28d,
    daily_activity_28d,
    training_load_summary,
    trimp_per_session,
)
from swim import swim_summary  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", required=True,
                    help="Tracker owner (Nihad or Fabian).")
    ap.add_argument("--months", type=int, default=3,
                    help="How many months back to load from monthly sheets. The data is used internally for "
                         "all roll-ups regardless of --include-rows.")
    ap.add_argument("--today", default=None, help="Override today's date (YYYY-MM-DD) for testing")
    ap.add_argument("--include-rows", action="store_true",
                    help="Include the flat `rows` array in the JSON. Off by default — the coach already exposes "
                         "pre-aggregated `monthly_sessions`, `progression_summary`, `weekly_volume_per_muscle`, "
                         "and `estimated_1rm`. Pass this only for debug deep-dives.")
    ap.add_argument("--include-1rm-history", action="store_true",
                    help="Include the per-exercise `e1rm_history` list (last 3 sessions). Off by default — "
                         "`current_e1rm_kg`, `slope_kg_per_4w`, `confidence`, and `stalled_sessions` cover the "
                         "coaching decision; the history is debug-only.")
    ap.add_argument("--include-daily-health", action="store_true",
                    help="Include the raw daily `health_metrics_recent` (~30 rows × 13 fields). Off by default — "
                         "the coach reads weekly aggregates from `health_metrics_weekly` instead.")
    ap.add_argument("--pretty", action="store_true",
                    help="Pretty-print the JSON (indent=2). Off by default — compact form saves ~20%% of "
                         "tokens for the LLM consumer. Use for human inspection.")
    args = ap.parse_args()

    person = args.person
    md = monthly_dir(person)
    if not md.exists():
        print(f"ERROR: monthly CSVs not found: {md}", file=sys.stderr)
        return 1

    today_d = (
        datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    )

    rows, session_totals, session_summaries = extract_rows(person, args.months, today_d)
    deloads = find_deloads(person)

    profile = read_profile(person)
    data_source = profile.get("source") or DEFAULT_DATA_SOURCE
    capabilities = SOURCE_CAPABILITIES.get(data_source, SOURCE_CAPABILITIES[DEFAULT_DATA_SOURCE])

    # Every dataset lives in a CSV under <person>/data/. The lib readers
    # below all take the person string and resolve the matching file.
    health_all = read_health_metrics(person)
    # Per-day rows go into health_metrics_recent. ``bodyweight_kg`` is dropped
    # because it duplicates the dedicated ``bodyweight_recent`` series — the
    # coach reads daily metrics for HRV / VO2max / sleep / wrist temp, not
    # weight. Keeping it here costs ~600 bytes for no signal.
    health_recent = [
        {k: v for k, v in entry.items() if k != "bodyweight_kg"}
        for entry in health_all[-30:]
    ]

    workout_sessions_all = read_workout_sessions(person)
    swim_workouts_all = read_swim_workouts(person)
    swim_laps_all = read_swim_laps(person)

    bw_all = read_bodyweight(person)
    bw_latest = (
        {"date": bw_all[-1]["date"], "kg": bw_all[-1]["kg"]}
        if bw_all else None
    )

    # Parse the exercises database once; it's read-only for this run.
    db_path = Path(__file__).resolve().parents[2] / "shared" / "exercises-database.md"
    db = load_exercises_db(db_path)

    unknown_set: set[str] = set()
    weekly_volume = weekly_volume_per_muscle(rows, db, today_d, 28, unknown_set)
    e1rm = estimated_1rm(rows, deloads,
                         include_history=args.include_1rm_history)
    stale_full = stale_exercises(rows, db, today_d, 28)
    # Cap stale_exercises to top 5 by weeks_since (already DESC-sorted by
    # the helper). Beyond 5 the coach rarely uses them in plan generation.
    stale = stale_full[:5]

    # Surface any logged exercise across the full loaded window that doesn't
    # match an entry in the database — not just the 28-day volume window.
    # Catches typos/rename drift (e.g. "Deadhang" vs "Dead Hang") that would
    # otherwise silently under-count volume and dodge rotation decisions.
    for r in rows:
        if not _is_working_set(r):
            continue
        if r["exercise"].lower() not in db:
            unknown_set.add(r["exercise"])

    # ---- Derived metrics ----
    monthly_sessions = build_monthly_sessions(
        rows, session_summaries,
        session_totals=session_totals,
        apple_sessions=workout_sessions_all,
    )
    max_hr = estimate_max_hr(workout_sessions_all, today_d, profile=profile)
    age_years = _age_from_birthday(profile.get("birthday"), today_d)
    rest_hr = _mean_or_none(_values_in_window(health_all, "resting_hr", today_d, 28))
    if rest_hr is None and capabilities.get("resting_hr_daily") is False:
        # HL fallback: typical adult RHR if the source can't supply it.
        rest_hr = 60.0

    recovery = recovery_score(health_all, today_d, capabilities)
    trimps = trimp_per_session(monthly_sessions, max_hr, rest_hr)
    training_load = training_load_summary(trimps, today_d)
    # Fold TRIMP load_band, intensity_pct, and the cardio session's
    # HR-zone label back onto each monthly_session for the LLM. The zone
    # label lets a run/ride/hike entry read as "Z2 hike" or "Z4 interval"
    # directly without re-deriving from avg_hr.
    trimp_by_date: dict[str, dict] = {t["date"]: t for t in trimps}
    for s in monthly_sessions:
        t = trimp_by_date.get(s.get("date"))
        if t:
            s["trimp"] = t["trimp"]
            s["load_band"] = t["load_band"]
            s["intensity_pct"] = t["intensity_pct"]
            if t.get("kind") == "cardio":
                s["hr_zone_label"] = t.get("hr_zone_label")

    hr_volume_div = hr_at_volume_divergence(rows, monthly_sessions, db, today_d)
    cardio_zones = cardio_hr_zones(monthly_sessions, today_d, max_hr, rest_hr)
    auto_deloads = auto_deload_candidates(monthly_sessions, deloads, today_d)
    weekly_health = health_metrics_weekly(health_all, today_d, weeks=4)
    daily_activity = daily_activity_28d(health_all, workout_sessions_all, today_d)
    swim = swim_summary(
        swim_workouts_all, swim_laps_all, today_d, profile, max_hr,
    )

    out = {
        "today": today_d.strftime("%Y-%m-%d"),
        "data_source": data_source,
        "capabilities": capabilities,
        "auto_cardio_enabled": bool(profile.get("auto_cardio")),
        # ---- Strength + cardio sessions (canonical session-level view) ----
        "monthly_sessions": monthly_sessions,
        "weekly_volume_per_muscle": weekly_volume,
        "estimated_1rm": e1rm,
        "progression_summary": progression_summary(rows),
        "stale_exercises": stale,
        "unknown_exercises": sorted(unknown_set),
        "deloads": deloads,
        "auto_deload_candidates": auto_deloads,
        # ---- Cardio rollup ----
        "cardio_last_28d": cardio_last_28d(rows, today_d),
        "cardio_hr_zones_28d": cardio_zones,
        # ---- Swim summary (only present when there are swims in the
        # 28-day window; ``_compact`` drops None below). ----
        "swim_summary": swim,
        # ---- Daily activity (NEAT) — all-day movement beyond workouts. ----
        "daily_activity_28d": daily_activity,
        # ---- Recovery + training load (Python-derived, not raw metrics) ----
        "recovery": recovery,
        "training_load": training_load,
        "hr_at_volume_divergence": hr_volume_div,
        "age_years": age_years,
        "estimated_max_hr": max_hr,
        "estimated_rest_hr": round(rest_hr, 1) if rest_hr else None,
        # ---- Bodyweight ----
        "bodyweight_latest": bw_latest,
        "bodyweight_trend_kg_per_week": bodyweight_trend_kg_per_week(bw_all),
        # ---- Apple Health weekly aggregates (raw daily behind a flag) ----
        "health_metrics_weekly": weekly_health,
        "health_metrics_recent": health_recent if args.include_daily_health else None,
        "vo2max_latest": latest_metric(health_all, "vo2max"),
        "vo2max_trend_per_4w": metric_trend_per_4w(health_all, "vo2max"),
        # ---- Debug deep-dive: flat per-set list (--include-rows). ----
        "rows": rows if args.include_rows else None,
    }
    if args.pretty:
        json.dump(_compact(out), sys.stdout, ensure_ascii=False, indent=2)
    else:
        # Compact form: no whitespace between separators. Saves ~20% of
        # bytes vs indent=2 for an LLM consumer that doesn't render the
        # whitespace anyway.
        json.dump(_compact(out), sys.stdout, ensure_ascii=False,
                  separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
