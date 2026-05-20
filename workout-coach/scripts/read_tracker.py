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
from datetime import date, datetime, timedelta
from pathlib import Path

# Bring in shared tracker schemas, package utilities, and coach analytics.
SKILLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS_ROOT))
sys.path.insert(0, str(SKILLS_ROOT / "shared"))
sys.path.insert(0, str(SKILLS_ROOT / "workout-coach" / "lib"))
from tracker import TrackerContext  # noqa: E402
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
    read_sleep_nights,
    read_swim_laps,
    read_swim_workouts,
    read_light_therapy_sessions,
    read_thermal_sessions,
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
from sleep import sleep_summary  # noqa: E402
from swim import swim_summary  # noqa: E402
from thermal import thermal_summary  # noqa: E402
from light_therapy import light_therapy_summary  # noqa: E402


def _wow_trend(this_v: float | None, last_v: float | None,
               eps: float = 1e-6) -> str | None:
    """Compare two scalar values; return ``up`` / ``down`` / ``flat`` /
    ``None`` (when either side is missing)."""
    if this_v is None or last_v is None:
        return None
    diff = this_v - last_v
    if abs(diff) < eps:
        return "flat"
    return "up" if diff > 0 else "down"


def _mean_over(values: list[float]) -> float | None:
    """Mean of a list of floats; None when empty."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _bucket_strength_sessions(sessions: list[dict],
                              start: date, end: date) -> int:
    """Strength sessions in the half-open window ``[start, end]``."""
    n = 0
    for s in sessions:
        if s.get("session_kind") != "strength":
            continue
        d = _parse_iso_date(s.get("date"))
        if d is None:
            continue
        if start <= d <= end:
            n += 1
    return n


def _bucket_cardio_sessions(sessions: list[dict],
                            start: date, end: date) -> int:
    """Cardio sessions in the half-open window ``[start, end]``."""
    n = 0
    for s in sessions:
        if s.get("session_kind") != "cardio":
            continue
        d = _parse_iso_date(s.get("date"))
        if d is None:
            continue
        if start <= d <= end:
            n += 1
    return n


def _bucket_cardio_min(sessions: list[dict],
                       start: date, end: date) -> float:
    """Total cardio minutes in window ``[start, end]`` (any zone, any source)."""
    total = 0.0
    for s in sessions:
        if s.get("session_kind") != "cardio":
            continue
        d = _parse_iso_date(s.get("date"))
        if d is None or not (start <= d <= end):
            continue
        dm = s.get("duration_min")
        try:
            total += float(dm) if dm is not None else 0.0
        except (TypeError, ValueError):
            pass
    return total


def _bucket_health_mean(health_all: list[dict], key: str,
                        start: date, end: date) -> float | None:
    """Mean of ``health_all[*][key]`` for rows whose ISO date falls in
    ``[start, end]``. Skips None / non-numeric."""
    vals: list[float] = []
    for row in health_all:
        d = _parse_iso_date(row.get("date"))
        if d is None or not (start <= d <= end):
            continue
        v = row.get(key)
        try:
            if v is not None:
                vals.append(float(v))
        except (TypeError, ValueError):
            pass
    return _mean_over(vals)


def _bucket_bodyweight_mean(bw_all: list[dict],
                            start: date, end: date) -> float | None:
    """Mean bodyweight in window; bw rows use ``kg`` not a health key."""
    vals: list[float] = []
    for row in bw_all:
        d = _parse_iso_date(row.get("date"))
        if d is None or not (start <= d <= end):
            continue
        v = row.get("kg")
        try:
            if v is not None:
                vals.append(float(v))
        except (TypeError, ValueError):
            pass
    return _mean_over(vals)


def _bodyweight_weekly_kg(bw_all: list[dict], today_d: date,
                          weeks: int = 4) -> list[float | None]:
    """Per-ISO-week mean bodyweight for the same window as
    ``health_metrics_weekly``. Returns one entry per week present in
    the data, oldest first; entries are None when no weight was logged
    that week. The dashboard uses this to draw a bodyweight sparkline."""
    if not bw_all:
        return []
    cutoff = today_d - timedelta(days=weeks * 7)
    by_week: dict[tuple[int, int], list[float]] = {}
    for row in bw_all:
        d = _parse_iso_date(row.get("date"))
        if d is None or d < cutoff:
            continue
        v = row.get("kg")
        try:
            if v is None:
                continue
            iso = d.isocalendar()
            by_week.setdefault((iso.year, iso.week), []).append(float(v))
        except (TypeError, ValueError):
            continue
    out: list[float | None] = []
    for wk in sorted(by_week.keys()):
        vals = by_week[wk]
        out.append(round(sum(vals) / len(vals), 2) if vals else None)
    return out


def _round_or_none(v: float | None, digits: int) -> float | None:
    """Round ``v`` to ``digits`` decimals, preserving None."""
    return None if v is None else round(v, digits)


def _build_week_over_week(today_d: date,
                          monthly_sessions: list[dict],
                          health_all: list[dict],
                          bw_all: list[dict]) -> dict:
    """Build the dashboard's this-week / last-week / 4-week-avg block.

    Buckets are calendar-ish windows anchored on ``today_d``: this-week
    covers the last 7 days inclusive of today, last-week the 7 days
    before that, and the 4-week-avg averages the 4 consecutive 7-day
    windows ending today. Bucketing by relative day rather than ISO
    week keeps the report stable when the coach runs mid-week.
    """
    this_start = today_d - timedelta(days=6)
    last_end   = this_start - timedelta(days=1)
    last_start = last_end - timedelta(days=6)
    avg_start  = today_d - timedelta(days=27)

    avg_strength = _bucket_strength_sessions(monthly_sessions, avg_start, today_d) / 4.0
    avg_cardio_sess = _bucket_cardio_sessions(monthly_sessions, avg_start, today_d) / 4.0
    avg_cardio_min = _bucket_cardio_min(monthly_sessions, avg_start, today_d) / 4.0
    avg_sleep = _bucket_health_mean(health_all, "sleep_total_h", avg_start, today_d)
    avg_hrv   = _bucket_health_mean(health_all, "hrv_sdnn",      avg_start, today_d)
    avg_rhr   = _bucket_health_mean(health_all, "resting_hr",    avg_start, today_d)
    avg_wrist = _bucket_health_mean(health_all, "wrist_temp_c",  avg_start, today_d)
    avg_bw    = _bucket_bodyweight_mean(bw_all, avg_start, today_d)

    def row(label: str, key: str,
            this_v: float | None, last_v: float | None,
            avg_v: float | None, digits: int, unit: str | None) -> dict:
        return {
            "metric":      label,
            "key":         key,
            "this_week":   _round_or_none(this_v, digits),
            "last_week":   _round_or_none(last_v, digits),
            "four_wk_avg": _round_or_none(avg_v, digits),
            "trend":       _wow_trend(this_v, last_v),
            "unit":        unit,
        }

    return {
        "windows": {
            "this_week":   {"start": this_start.isoformat(), "end": today_d.isoformat()},
            "last_week":   {"start": last_start.isoformat(), "end": last_end.isoformat()},
            "four_wk_avg": {"start": avg_start.isoformat(),  "end": today_d.isoformat()},
        },
        "rows": [
            row(
                "Strength sessions", "strength_sessions",
                _bucket_strength_sessions(monthly_sessions, this_start, today_d),
                _bucket_strength_sessions(monthly_sessions, last_start, last_end),
                avg_strength, 1, "sess",
            ),
            row(
                "Cardio sessions", "cardio_sessions",
                _bucket_cardio_sessions(monthly_sessions, this_start, today_d),
                _bucket_cardio_sessions(monthly_sessions, last_start, last_end),
                avg_cardio_sess, 1, "sess",
            ),
            row(
                "Cardio minutes", "cardio_min",
                _bucket_cardio_min(monthly_sessions, this_start, today_d),
                _bucket_cardio_min(monthly_sessions, last_start, last_end),
                avg_cardio_min, 0, "min",
            ),
            row(
                "Sleep total", "sleep_total_h",
                _bucket_health_mean(health_all, "sleep_total_h", this_start, today_d),
                _bucket_health_mean(health_all, "sleep_total_h", last_start, last_end),
                avg_sleep, 2, "h",
            ),
            row(
                "HRV (SDNN)", "hrv_sdnn",
                _bucket_health_mean(health_all, "hrv_sdnn", this_start, today_d),
                _bucket_health_mean(health_all, "hrv_sdnn", last_start, last_end),
                avg_hrv, 1, "ms",
            ),
            row(
                "Resting HR", "resting_hr",
                _bucket_health_mean(health_all, "resting_hr", this_start, today_d),
                _bucket_health_mean(health_all, "resting_hr", last_start, last_end),
                avg_rhr, 1, "bpm",
            ),
            row(
                "Wrist temp dev", "wrist_temp_c",
                _bucket_health_mean(health_all, "wrist_temp_c", this_start, today_d),
                _bucket_health_mean(health_all, "wrist_temp_c", last_start, last_end),
                avg_wrist, 2, "°C",
            ),
            row(
                "Bodyweight", "bodyweight_kg",
                _bucket_bodyweight_mean(bw_all, this_start, today_d),
                _bucket_bodyweight_mean(bw_all, last_start, last_end),
                avg_bw, 2, "kg",
            ),
        ],
    }


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

    today_d = (
        datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else date.today()
    )
    ctx = TrackerContext(args.person, today_d)
    person = ctx.person
    md = monthly_dir(person)
    if not md.exists():
        print(f"ERROR: monthly CSVs not found: {md}", file=sys.stderr)
        return 1

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
    sleep_nights_all = read_sleep_nights(person)
    thermal_sessions_all = read_thermal_sessions(person)
    light_therapy_sessions_all = read_light_therapy_sessions(person)

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
    # `monthly_sessions` is now keyed by (date, kind) so the lookup must
    # match on both — otherwise a day with strength + cardio gets the
    # wrong TRIMP attached to each entry. `trimp_per_session` iterates
    # `monthly_sessions` directly so the order and identity line up,
    # but matching by (date, kind) is the safer contract.
    trimp_by_key: dict[tuple, dict] = {
        (t["date"], t.get("kind")): t for t in trimps
    }
    for s in monthly_sessions:
        key = (s.get("date"), s.get("session_kind"))
        t = trimp_by_key.get(key)
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
    sleep = sleep_summary(sleep_nights_all, today_d)
    # Enrich with sleep-adjacent metrics we already import to
    # health_metrics.csv but never surfaced anywhere on the dashboard:
    # respiratory rate and Apple's "sleeping breathing disturbances"
    # signal. Both populate when the watch detects them overnight.
    if sleep:
        resp_vals = _values_in_window(health_all, "resp_rate", today_d, 28)
        sbd_vals  = _values_in_window(health_all, "sleep_breath_dist", today_d, 28)
        if resp_vals:
            sleep["resp_rate"] = {
                "n_nights":  len(resp_vals),
                "mean":      round(_mean_or_none(resp_vals), 2),
            }
        if sbd_vals:
            sleep["breath_disturbances"] = {
                "n_nights":  len(sbd_vals),
                "mean":      round(_mean_or_none(sbd_vals), 2),
            }
    # Sauna frequency target reads from profile.csv (key
    # ``sauna_target_per_week``) if set; otherwise the default 4×/week.
    try:
        sauna_target = int(profile.get("sauna_target_per_week") or 4)
    except (TypeError, ValueError):
        sauna_target = 4
    thermal = thermal_summary(thermal_sessions_all, today_d,
                              target_per_week=sauna_target)
    # Light-therapy targets read from profile.csv if set; otherwise the
    # module defaults (3×/wk, 10min/session).
    try:
        lt_target = int(profile.get("light_therapy_target_per_week") or 3)
    except (TypeError, ValueError):
        lt_target = 3
    try:
        lt_dose = int(profile.get("light_therapy_target_min_per_session") or 10)
    except (TypeError, ValueError):
        lt_dose = 10
    light_therapy = light_therapy_summary(
        light_therapy_sessions_all, today_d,
        target_per_week=lt_target,
        target_min_per_session=lt_dose,
    )

    # ---- Week-over-week comparison block (used by the assessment HTML
    # dashboard's bottom card). Composes existing extracts; no new data
    # sources. ----
    week_over_week = _build_week_over_week(
        today_d, monthly_sessions, health_all, bw_all,
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
        # ---- Sleep summary (only present when XML tracker has nights in
        # the 28-day window; ``_compact`` drops None for HL or no-data). ----
        "sleep_summary": sleep,
        # ---- Thermal summary (sauna + cold exposure, only present when
        # at least one manual /log session in the 28-day window;
        # ``_compact`` drops None when absent). ----
        "thermal_summary": thermal,
        # ---- Light-therapy summary (RLT / PBM / blue light, only
        # present when at least one manual /log session in the 28-day
        # window; ``_compact`` drops None when absent). ----
        "light_therapy_summary": light_therapy,
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
        "bodyweight_weekly": _bodyweight_weekly_kg(bw_all, today_d, weeks=4),
        # ---- Apple Health weekly aggregates (raw daily behind a flag) ----
        "health_metrics_weekly": weekly_health,
        "health_metrics_recent": health_recent if args.include_daily_health else None,
        "vo2max_latest": latest_metric(health_all, "vo2max"),
        "vo2max_trend_per_4w": metric_trend_per_4w(health_all, "vo2max"),
        # ---- Week-over-week comparison (this-week / last-week / 4-wk avg
        # for the assessment dashboard's bottom card). ----
        "week_over_week": week_over_week,
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
