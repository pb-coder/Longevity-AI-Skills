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
  - stale_exercises (top 5 by reintroduction value), unknown_exercises
  - deloads (user-marked), auto_deload_candidates (Python-detected)

  Prescription memory (what was ASKED for, versus what happened):
  - adherence: the previous plan reconciled against the logs — sets
    prescribed vs performed, split isolation / compound, the per-exercise
    ledger, substitutions, and the D5 bench list with its one question.
  - dose_staleness: per carried-forward exercise, whether the dose
    actually moved and for how many generations it has not.
  - block: the current training block, its slots tagged anchor /
    rotating, and whether the boundary has fired (deload or 6 weeks,
    whichever first).
  - rotation_candidates: derived starting loads for movements with no
    logged history, so a rotated-in exercise can be prescribed at all.

  Prescription specs + priority tiers:
  - core_week_spec / arm_week_spec, muscle_priority_tiers,
    muscle_volume_targets, volume_landmark_unit, synergist_credit_offset

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
  - bodyweight_trend: the same rate with its state. OLS over a minimum
    28-day window; ``state`` is ``resolved`` only when the 95% interval
    excludes zero, and ``bodyweight_trend_kg_per_week`` is null otherwise.
    Read ``reason`` / ``note`` before saying anything about gaining or
    losing.

  Waist circumference (source-agnostic; both importers write the column):
  - waist_latest: ``{value_cm, date}`` for the newest measurement at or
    before ``--today``; absent when never measured.
  - waist_trend_cm_per_4w: the same block SHAPE as bodyweight_trend, rate
    in cm per 4 weeks, over a minimum 56-day window. ``cm_per_4w`` is
    populated only when ``state == "resolved"``. A single measurement
    returns ``unresolved`` / ``too_few_readings``, never 0.0.

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

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

# Bring in shared tracker schemas, package utilities, and coach analytics.
SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))
from tracker import TrackerContext  # noqa: E402
# ``tracker.contracts`` is referenced only in type annotations below
# (``TrackerJSON``). Under ``from __future__ import annotations`` those
# annotations are strings, so we can hide the import behind TYPE_CHECKING
# and skip pulling the contracts module + typing's TypedDict machinery
# at runtime cold-start.
if TYPE_CHECKING:
    from tracker.contracts import TrackerJSON  # noqa: F401
# Direct submodule imports bypass the ``shared.csv_store`` re-export
# facade so the read subprocess doesn't pay for facade top-level code +
# extra import-machinery work. ``shared.csv_store_dense`` / ``periodic``
# still get loaded later via ``workout_coach.lib.extract``; the facade
# itself is the only thing skipped.
from shared.csv_store_profile import read_profile  # noqa: E402
from shared.person_paths import monthly_dir  # noqa: E402
from workout_coach.lib.constants import (  # noqa: E402
    ARM_WEEK_SPEC,
    CORE_WEEK_SPEC,
    DEFAULT_DATA_SOURCE,
    SOURCE_CAPABILITIES,
    SYNERGIST_CREDIT_OFFSET,
    muscle_priority_tiers,
    muscle_volume_targets,
)
from workout_coach.lib.parsing import _compact, _parse_iso_date  # noqa: E402
from workout_coach.lib.extract import (  # noqa: E402
    _age_from_birthday,
    estimate_max_hr,
    extract_rows,
    find_deloads,
    load_exercises_db,
    read_bodyweight,
    read_health_metrics,
    read_nutrition_phases,
    read_sleep_nights,
    read_swim_laps,
    read_swim_workouts,
    read_light_therapy_sessions,
    read_thermal_sessions,
    read_workout_sessions,
)
# Direct submodule imports bypass the ``workout_coach.lib.health``
# re-export facade. The four focused modules below are loaded the same
# way the facade would load them; skipping the facade itself avoids one
# extra module-level execution on the cold path.
from workout_coach.lib.health_windowing import (  # noqa: E402
    _mean_or_none,
    _values_in_window,
    health_metrics_weekly,
    latest_metric,
    metric_trend_per_4w,
)
from workout_coach.lib.health_recovery import recovery_score  # noqa: E402
from workout_coach.lib.health_longevity import (  # noqa: E402
    compute_longevity_score,
    read_longevity_state,
    vo2_percentile_age_sex,
)
from workout_coach.lib.health_session_rec import (  # noqa: E402
    compute_session_recommendation,
    compute_tier_history,
)
from workout_coach.lib.sessions import (  # noqa: E402
    _is_working_set,
    bodyweight_trend,
    build_monthly_sessions,
    progression_summary,
    waist_trend,
)
from workout_coach.lib.strength import (  # noqa: E402
    estimated_1rm,
    hr_at_volume_divergence,
    reintroduction_pool,
    stale_exercises,
    weekly_volume_per_muscle,
)
from workout_coach.lib.adherence import (  # noqa: E402
    build_adherence,
    dose_staleness,
    load_plans,
)
from workout_coach.lib.blocks import (  # noqa: E402
    block_payload,
    load_pattern_catalog,
    rotation_candidates,
)
from workout_coach.lib.cardio import (  # noqa: E402
    auto_deload_candidates,
    cardio_hr_zones,
    cardio_last_28d,
    compute_acwr,
    compute_hr_recovery_summary,
    compute_movement_consistency_days,
    daily_activity_28d,
    training_load_summary,
    trimp_per_session,
)
from workout_coach.lib.sleep import (  # noqa: E402
    compute_sleep_regularity_index,
    flag_rem_sleep_anomalies,
    sleep_summary,
)
from workout_coach.lib.swim import swim_summary  # noqa: E402
from workout_coach.lib.thermal import thermal_summary  # noqa: E402
from workout_coach.lib.light_therapy import light_therapy_summary  # noqa: E402
from workout_coach.lib.nutrition_phase import nutrition_phase_summary  # noqa: E402


def _clip_series(entries: list[dict] | None, today_d: date,
                 key: str = "date",
                 open_ended_keys: tuple[str, ...] = ()) -> list[dict]:
    """Drop rows dated after ``today_d``.

    ``--today`` is the as-of date for the whole payload, and the CSV store
    is not guaranteed to end there: a backtest at an earlier date, or a
    weigh-in / Apple import that lands ahead of the requested anchor, both
    put future rows in front of the analytics layer. Every reader in
    ``extract`` returns its full file, so the horizon is enforced HERE,
    once, on the way in — rather than re-derived inside each of the twenty
    downstream series builders, where one missed spot silently leaks the
    future into an otherwise honest backtest.

    ``open_ended_keys`` handles the second, subtler shape of the same leak:
    a row that legitimately EXISTS as of ``today_d`` but carries a CLOSING
    boundary filled in after the fact. Dropping the row would be wrong;
    keeping the closing date is what leaks. Each named key is nulled out on
    a COPY of the row when its boundary lands on or after ``today_d``, so
    the row survives in the state it was actually in at the anchor.

    The comparison is ``>=``, not ``>``, and the asymmetry with the row test
    above is deliberate — the two columns mean different things. ``key`` is
    an event date: a row dated today happened, and stays. An open-ended key
    is an INCLUSIVE last day: this store writes back-to-back periods (one
    ends the 14th, the next starts the 15th), so a period whose last day is
    today has not ended yet as of today. Using ``>`` there punches a
    one-day hole into the final day of every period, during which the
    payload reports no period at all.

    Rows whose date will not parse are kept; downstream helpers already
    skip them, and dropping them here would change unrelated behaviour.
    """
    out: list[dict] = []
    for e in entries or []:
        d = _parse_iso_date(e.get(key))
        if d is not None and d > today_d:
            continue
        for ok in open_ended_keys:
            od = _parse_iso_date(e.get(ok))
            if od is not None and od >= today_d:
                e = {**e, ok: None}
        out.append(e)
    return out


def _clip_date_map(m: dict, today_d: date) -> dict:
    """Same horizon as ``_clip_series`` for a ``YYYY-MM-DD`` → value dict."""
    out = {}
    for k, v in (m or {}).items():
        d = _parse_iso_date(k)
        if d is not None and d > today_d:
            continue
        out[k] = v
    return out


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


def _waist_readings(health_all: list[dict]) -> list[dict]:
    """Waist measurements off the health-metrics rows, ASC by date.

    ``Waist (cm)`` is written by BOTH importers (the native-XML path via
    ``apple_health_daily``, the HealthAutoExport path via its own field
    map), so this reader is source-agnostic on purpose: it takes the
    column, not the exporter. ``health_all`` has already been through
    ``_clip_series``, so the ``--today`` horizon is applied before
    anything here sees a row.

    Blank cells are skipped rather than yielded as ``0`` — a person who
    has never measured returns ``[]``, which reads downstream as "no
    data" instead of "flat at zero".
    """
    out: list[dict] = []
    for entry in health_all:
        cm = entry.get("waist_cm")
        if cm is None:
            continue
        out.append({"date": entry["date"], "cm": cm})
    out.sort(key=lambda e: e["date"])
    return out


def _attach_waist_weekly(weekly: list[dict], waist_readings: list[dict],
                         today_d: date, weeks: int = 4) -> list[dict]:
    """Fold a per-ISO-week waist mean onto each ``health_metrics_weekly``
    entry, keyed by ``week_start``.

    ``waist_cm`` is not part of ``health_metrics_weekly``'s own key list
    and is added here instead so the vitals table can draw the waist
    sparkline from the same series every other vitals row uses. Weeks
    with no measurement are left with ``waist_cm = None``, which
    ``_compact`` strips — the sparkline then sees a gap rather than an
    invented value, and a series with fewer than two real points renders
    as an empty box rather than a flat line.
    """
    if not weekly or not waist_readings:
        return weekly
    cutoff = today_d - timedelta(days=max(weeks * 7 - 1, 0))
    by_week: dict[str, list[float]] = {}
    for row in waist_readings:
        d = _parse_iso_date(row.get("date"))
        if d is None or d < cutoff or d > today_d:
            continue
        try:
            value = float(row["cm"])
        except (TypeError, ValueError):
            continue
        iso = d.isocalendar()
        monday = date.fromisocalendar(iso.year, iso.week, 1).isoformat()
        by_week.setdefault(monday, []).append(value)
    for entry in weekly:
        vals = by_week.get(entry.get("week_start"))
        entry["waist_cm"] = (round(sum(vals) / len(vals), 2) if vals
                             else None)
    return weekly


def _round_or_none(v: float | None, digits: int) -> float | None:
    """Round ``v`` to ``digits`` decimals, preserving None."""
    return None if v is None else round(v, digits)


def _bucket_recovery_sessions(thermal_sessions: list[dict] | None,
                              light_sessions: list[dict] | None,
                              start: date, end: date) -> float:
    """Count recovery sessions (sauna/cold rows + light-therapy rows) whose
    date falls in [start, end]. One thermal row = one protocol session
    (a paired sauna+cold is a single row), matching the activity ring's
    'sauna + cold + light' session semantics."""
    n = 0
    for src in (thermal_sessions or [], light_sessions or []):
        for s in src:
            d = _parse_iso_date(s.get("date"))
            if d is not None and start <= d <= end:
                n += 1
    return float(n)


def _build_week_over_week(today_d: date,
                          monthly_sessions: list[dict],
                          health_all: list[dict],
                          bw_all: list[dict],
                          max_hr: float | None = None,
                          rest_hr: float | None = None,
                          thermal_sessions: list[dict] | None = None,
                          light_sessions: list[dict] | None = None) -> dict:
    """Build the dashboard's this-week / last-week / 4-week-avg block.

    Buckets are calendar-ish windows anchored on ``today_d``: this-week
    covers the last 7 days inclusive of today, last-week the 7 days
    before that, and the 4-week-avg averages the 4 consecutive 7-day
    windows ending today. Bucketing by relative day rather than ISO
    week keeps the report stable when the coach runs mid-week.

    The Zone-2 and recovery-session rows are computed on the SAME 7-day
    windows as the rest of the block so the dashboard's "This week at a
    glance" rings are window-consistent. (A prior bug rendered the Z2
    ring from a 28-day average divided by 4, which read far lower than
    the user's actual week and silently mixed windows inside one card.)
    """
    this_start = today_d - timedelta(days=6)
    last_end   = this_start - timedelta(days=1)
    last_start = last_end - timedelta(days=6)
    avg_start  = today_d - timedelta(days=27)

    def _z2_min(anchor_end: date) -> float:
        z = cardio_hr_zones(monthly_sessions, anchor_end, max_hr, rest_hr,
                            window_days=7)
        return float(z.get("z2") or 0.0)

    z2_this = _z2_min(today_d)
    z2_last = _z2_min(last_end)
    z2_avg  = float(
        (cardio_hr_zones(monthly_sessions, today_d, max_hr, rest_hr,
                         window_days=28).get("z2") or 0.0) / 4.0
    )
    rec_this = _bucket_recovery_sessions(thermal_sessions, light_sessions,
                                         this_start, today_d)
    rec_last = _bucket_recovery_sessions(thermal_sessions, light_sessions,
                                         last_start, last_end)
    rec_avg  = _bucket_recovery_sessions(thermal_sessions, light_sessions,
                                         avg_start, today_d) / 4.0

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
                "Zone 2 minutes", "cardio_z2_min",
                z2_this, z2_last, z2_avg, 0, "min",
            ),
            row(
                "Recovery sessions", "recovery_sessions",
                rec_this, rec_last, rec_avg, 1, "sess",
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


class _Args:
    person: str = ""
    months: int = 3
    today: str | None = None
    include_rows: bool = False
    include_1rm_history: bool = False
    include_daily_health: bool = False
    pretty: bool = False
    # Honor an EXPLICIT user override of the recovery gate (SKILL.md's
    # override protocol). When set, a restrictive Tier A/B/C call is
    # normalized to a green/full-volume session, keeping the original
    # rationale visible for transparency. Only the user may request this.
    override_gate: bool = False


def _parse_args(argv: list[str]) -> _Args:
    """Hand-rolled parser for the 7 supported flags.

    Replaces argparse to avoid pulling in inspect / shutil / lzma / _lzma /
    _bz2 / gettext / urllib at cold-start. Semantics match the previous
    argparse setup: --person required, --months int (default 3), --today
    optional string, four store-true booleans. Supports --foo=value and
    --foo value forms. Unknown flag → SystemExit(2) with a usage line.
    """
    a = _Args()
    flag_aliases = {
        "--include-rows": "include_rows",
        "--include-1rm-history": "include_1rm_history",
        "--include-daily-health": "include_daily_health",
        "--pretty": "pretty",
        "--override-gate": "override_gate",
    }
    value_aliases = {
        "--person": "person",
        "--months": "months",
        "--today": "today",
    }

    def _bail(msg: str) -> None:
        print(f"read_tracker: error: {msg}", file=sys.stderr)
        raise SystemExit(2)

    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in ("-h", "--help"):
            print(
                "usage: read_tracker.py --person NAME [--months N] "
                "[--today YYYY-MM-DD] [--include-rows] "
                "[--include-1rm-history] [--include-daily-health] [--pretty] "
                "[--override-gate]"
            )
            raise SystemExit(0)
        if "=" in tok and tok.startswith("--"):
            key, _, value = tok.partition("=")
            consumed = 1
        else:
            key = tok
            value = argv[i + 1] if i + 1 < len(argv) else None
            consumed = 2 if value is not None else 1

        if key in flag_aliases:
            setattr(a, flag_aliases[key], True)
            i += 1
            continue
        if key in value_aliases:
            attr = value_aliases[key]
            if value is None or (consumed == 2 and value.startswith("--")):
                _bail(f"argument {key}: expected a value")
            if attr == "months":
                try:
                    setattr(a, attr, int(value))
                except (TypeError, ValueError):
                    _bail(f"argument --months: invalid int value: {value!r}")
            else:
                setattr(a, attr, value)
            i += consumed
            continue
        _bail(f"unrecognized argument: {tok}")

    if not a.person:
        _bail("the following arguments are required: --person")
    return a


def main() -> int:
    args = _parse_args(sys.argv[1:])

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
    # Enforce the ``--today`` horizon on every series before any analytics
    # run. See ``_clip_series``: the readers hand back whole files, so
    # without this a run dated 2026-06-01 reported a 2026-07-29 top set and
    # an August weigh-in, and ten payload blocks were byte-identical across
    # a seven-week ``--today`` gap.
    rows = _clip_series(rows, today_d)
    session_totals = _clip_date_map(session_totals, today_d)
    session_summaries = _clip_date_map(session_summaries, today_d)
    deloads = [d for d in find_deloads(person)
               if (_parse_iso_date(d) or today_d) <= today_d]

    profile = read_profile(person)
    data_source = profile.get("source") or DEFAULT_DATA_SOURCE
    capabilities = SOURCE_CAPABILITIES.get(data_source, SOURCE_CAPABILITIES[DEFAULT_DATA_SOURCE])

    # Every dataset lives in a CSV under <person>/data/. The lib readers
    # below all take the person string and resolve the matching file.
    health_all = _clip_series(read_health_metrics(person), today_d)
    # Per-day rows go into health_metrics_recent. ``bodyweight_kg`` is dropped
    # because it duplicates the dedicated ``bodyweight_recent`` series — the
    # coach reads daily metrics for HRV / VO2max / sleep / wrist temp, not
    # weight. Keeping it here costs ~600 bytes for no signal.
    health_recent = [
        {k: v for k, v in entry.items() if k != "bodyweight_kg"}
        for entry in health_all[-30:]
    ]

    workout_sessions_all = _clip_series(read_workout_sessions(person), today_d)
    swim_workouts_all = _clip_series(read_swim_workouts(person), today_d)
    swim_laps_all = _clip_series(read_swim_laps(person), today_d)
    sleep_nights_all = _clip_series(read_sleep_nights(person), today_d)
    thermal_sessions_all = _clip_series(read_thermal_sessions(person), today_d)
    light_therapy_sessions_all = _clip_series(
        read_light_therapy_sessions(person), today_d)
    # Phases are keyed by ``start_date``; one that opens after ``today_d``
    # has not happened yet from this run's point of view. ``end_date`` needs
    # the same horizon and is the reason this reader is not a plain
    # ``_clip_series`` call: an end date is written AFTER the fact, so a
    # phase that was live at the anchor carries a closing date the anchor
    # could not have known. Leaving it in makes ``_current_open_phase``
    # skip the phase entirely — a backtest at 2026-06-01 reported no
    # nutrition phase at all for a block that was three weeks live, which
    # also unbinds the bodyweight-trend window (``nutrition_phase_start``)
    # and flips ``compute_longevity_score`` onto its no-phase branch.
    nutrition_phases_all = _clip_series(
        read_nutrition_phases(person), today_d, key="start_date",
        open_ended_keys=("end_date",))

    bw_all = _clip_series(read_bodyweight(person), today_d)
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
    # Cap stale_exercises to 5 — beyond that the coach rarely uses them in
    # plan generation. WHICH five is the whole value of the field: a plain
    # prefix of the lapsed list is a retirement pile at one end and a
    # coin-flip at the other, so the pick goes through
    # ``reintroduction_pool``.
    stale = reintroduction_pool(stale_full, limit=5)

    # Surface any logged exercise across the full loaded window that doesn't
    # match an entry in the database — not just the 28-day volume window.
    # Catches typos/rename drift (e.g. "Deadhang" vs "Dead Hang") that would
    # otherwise silently under-count volume and dodge rotation decisions.
    for r in rows:
        if not _is_working_set(r):
            continue
        if r["exercise"].lower() not in db:
            unknown_set.add(r["exercise"])

    # ---- Prescription memory (W2 + W5). Everything above this line reads
    # what was PERFORMED. These four blocks read what was PRESCRIBED —
    # ``plans/<Person>/<date>-workout.md`` — and reconcile the two. Without
    # them the coach cannot tell a movement it prescribes six times and the
    # user performs zero times from one that works, and generation N cannot
    # differ from N-1 because it never sees it. ----
    #
    # ``catalog`` carries movement-pattern identity (the ## MUSCLE heading
    # plus ### Subsection), which ``db`` structurally cannot: it resolves
    # every subsection to one ``primary`` muscle and discards which pattern
    # the movement was. Rotation is defined on the pattern, so the pattern
    # has to survive.
    catalog = load_pattern_catalog(db)
    # Priority tiers are resolved here rather than below because the bench
    # rule needs them: retiring every route into an emphasis muscle while
    # the same payload demands mid-MAV volume on it hands the coach two
    # instructions it cannot both obey.
    priority_tiers, priority_unknown = muscle_priority_tiers(profile)
    adherence = build_adherence(person, rows, db, today_d, catalog,
                                priority_tiers=priority_tiers)
    plans_parsed = load_plans(person, today_d, limit=8)
    dose_stale = dose_staleness(plans_parsed, db)
    # ``adherence`` feeds the block so each slot can be marked ``at_risk``:
    # the rotation validator is a pure function of two blocks and cannot
    # know which movements the user demonstrably does not do. ``e1rm``
    # feeds it ``stalled_sessions``, which is what lets the same validator
    # DERIVE ``stall_3_sessions`` instead of demanding a field the plan
    # markdown cannot express.
    block = block_payload(person, rows, db, catalog, today_d, deloads,
                          adherence=adherence, e1rm=e1rm)
    # Starting loads for movements with no history. Until this existed the
    # payload named only the ~46 exercises already logged, and the active
    # load rule is "copy last session's load forward" — so there was no
    # legal way to write a weight for anything else and rotation could not
    # actually be prescribed.
    #
    # Benched movements are excluded: the payload used to name
    # `Leg Curl (Lying)` under `adherence.benched` ("must not
    # re-prescribe") and offer it here with a derived load in the same
    # breath. The tiers go in so the 56-day pattern gate cannot hide the
    # emphasis categories the weekly spec forces the coach to add — they
    # sit at zero precisely because they are the gap.
    rot_candidates = rotation_candidates(
        rows, db, catalog, e1rm, today_d,
        exclude={b["exercise"] for b in (adherence or {}).get("benched") or []},
        priority_tiers=priority_tiers)

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
    trimps = trimp_per_session(monthly_sessions, max_hr, rest_hr, sex=profile.get("sex"))
    training_load = training_load_summary(trimps, today_d)
    training_load_by_modality = {
        "all": training_load,
        "strength": training_load_summary(
            [t for t in trimps if t.get("kind") == "strength"], today_d
        ),
        "cardio": training_load_summary(
            [t for t in trimps if t.get("kind") == "cardio"], today_d
        ),
    }
    strength_training_load = (
        training_load_by_modality["strength"]
        if training_load_by_modality["strength"].get("tsb") is not None
        else training_load
    )
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

    # ---- Nutrition phase (bulk / cut / maintain / recomp). Returns None
    # when no open phase. The summarizer needs estimated_1rm to detect
    # the "lifts stalled while bulking" stop-signal, so this call must
    # happen AFTER the e1rm calculation above. ----
    nutrition_phase = nutrition_phase_summary(
        nutrition_phases_all, bw_all, today_d, estimated_1rm=e1rm,
    )
    nutrition_phase_start = (
        ((nutrition_phase or {}).get("current") or {}).get("start_date")
    )
    # Weekly bodyweight rate, OLS over a minimum-28-day window. The block
    # carries an explicit resolved / unresolved state; ``bw_trend`` is the
    # scalar and is None whenever the 95% interval spans zero. Every
    # consumer below already treats None as "no trend known" — that is the
    # point: a wrong sign is worse than a missing number here.
    bw_trend_block = bodyweight_trend(
        bw_all, today_d=today_d, start_date=nutrition_phase_start,
    )
    bw_trend = bw_trend_block["kg_per_week"]

    # ---- Waist circumference. Imported by both sources into
    # ``health_metrics.csv``'s ``Waist (cm)`` column and, until now, never
    # surfaced: the number was saved and invisible.
    #
    # It earns its place next to bodyweight because the two answer
    # different questions. Scale weight during a lifting block moves on
    # water, glycogen and lean tissue at once; waist is the cheap proxy
    # for where the mass went, and a bulk that adds 2 kg with a flat waist
    # is a different event from one that adds 2 kg with a 3 cm waist.
    #
    # The trend goes through the SAME estimator as bodyweight
    # (``_trend_verdict``), so a single measurement returns an explicit
    # ``too_few_readings`` rather than a slope. ``today_d`` anchors the
    # window, which is the second horizon guard behind ``_clip_series``.
    waist_readings = _waist_readings(health_all)
    waist_latest = (
        {"value_cm": waist_readings[-1]["cm"],
         "date":     waist_readings[-1]["date"]}
        if waist_readings else None
    )
    waist_trend_block = waist_trend(waist_readings, today_d=today_d)
    # The vitals table draws its waist sparkline off the weekly series,
    # the same way HRV / RHR / VO2max do.
    weekly_health = _attach_waist_weekly(weekly_health, waist_readings,
                                         today_d, weeks=4)

    # ---- Week-over-week comparison block (used by the assessment HTML
    # dashboard's bottom card). Composes existing extracts; no new data
    # sources. ----
    week_over_week = _build_week_over_week(
        today_d, monthly_sessions, health_all, bw_all,
        max_hr=max_hr, rest_hr=rest_hr,
        thermal_sessions=thermal_sessions_all,
        light_sessions=light_therapy_sessions_all,
    )

    # ---- Longevity-trajectory derivations (Trajectory tab) ----
    longevity_state = read_longevity_state(person, today_d)
    # Sex resolves from ``profile.csv`` first (the operational tracker)
    # then falls back to the longevity profile .md. profile.csv keeps
    # the basic dashboard functional without a longevity profile.
    sex = profile.get("sex") or (longevity_state or {}).get("sex")
    vo2_latest_block = latest_metric(health_all, "vo2max")
    vo2_value = (vo2_latest_block or {}).get("value") if vo2_latest_block else None
    vo2_percentile = vo2_percentile_age_sex(vo2_value, sex, age_years)
    hr_recovery = compute_hr_recovery_summary(health_all, today_d)
    acwr = compute_acwr(trimps, today_d)
    sleep_regularity = compute_sleep_regularity_index(sleep_nights_all, today_d, window_days=14)
    rem_anomaly = flag_rem_sleep_anomalies(sleep_nights_all, today_d)
    movement_consistency = compute_movement_consistency_days(health_all, today_d)
    longevity_score = compute_longevity_score(
        vo2_percentile=vo2_percentile,
        recovery=recovery,
        sleep_summary=sleep,
        sleep_regularity=sleep_regularity,
        acwr=acwr,
        cardio_zones=cardio_zones,
        movement_consistency=movement_consistency,
        bodyweight_trend_kg_per_week=bw_trend,
        estimated_1rm=e1rm,
        capabilities=capabilities,
        phase_type=((nutrition_phase or {}).get("current") or {}).get("phase_type"),
    )

    # ---- Session recommendation (the 5-tier gate that SKILL.md Phase 2
    # MUST honor before generating any workout). This is the deterministic
    # single source of truth so the LLM can't rationalize past it.
    session_recommendation = compute_session_recommendation(
        recovery=recovery,
        training_load=strength_training_load,
        acwr=acwr,
        weekly_volume=weekly_volume,
        sleep_regularity=sleep_regularity,
        sleep_summary=sleep,
        estimated_1rm=e1rm,
        hr_at_volume_divergence=hr_volume_div,
        deloads=deloads,
        auto_deload_candidates=auto_deloads,
        health_all=health_all,
        today_d=today_d,
        estimated_max_hr=max_hr,
        bodyweight_trend=bw_trend,
    )

    # Explicit user override of the recovery gate (SKILL.md override
    # protocol). The gate stays the deterministic default; this only fires
    # when the user, having SEEN the call, asks to train normally. We
    # normalize a restrictive A/B/C tier to green so the dashboard's
    # "Today's call" and the per-workout set budget both reflect a full
    # session, while preserving the original rationale for honesty.
    if args.override_gate and session_recommendation.get("tier") in ("A", "B", "C"):
        _orig = session_recommendation
        _orig_tier = _orig.get("tier")
        _orig_head = _orig.get("headline") or ""
        session_recommendation = {
            "tier": "D",
            "label": "green",
            "headline": "Train as planned (you chose to override the recovery downgrade).",
            "substitute": None,
            "rationale": ([{
                "signal": "user_override",
                "value": None,
                "threshold": None,
                "note": (f"You overrode the system's Tier {_orig_tier} call "
                         f"({_orig_head}) and chose to train normally."),
            }] + list(_orig.get("rationale") or [])),
            "override_allowed": True,
            "override_message": (
                f"User override in effect. The system's own read was Tier "
                f"{_orig_tier}: {_orig_head} Training at full volume by request; "
                f"listen to your body and back off if a lift feels off."),
            "expected_rebound_by_session": None,
        }

    # 14-day tier history strip (Trajectory tab — spot fatigue spirals).
    tier_history = compute_tier_history(
        days=14,
        today_d=today_d,
        health_all=health_all,
        monthly_sessions=monthly_sessions,
        weekly_volume=weekly_volume,
        sleep_nights_all=sleep_nights_all,
        sleep_regularity_today=sleep_regularity,
        sleep_summary_today=sleep,
        estimated_1rm=e1rm,
        hr_at_volume_divergence=hr_volume_div,
        deloads=deloads,
        auto_deload_candidates=auto_deloads,
        capabilities=capabilities,
        estimated_max_hr=max_hr,
        estimated_rest_hr=rest_hr,
        bodyweight_trend=bw_trend,
    )

    # ---- Session-length budget. Strength-session duration is driven by total
    # WORKING SETS (rest dominates), not exercise count. So the coach budgets
    # sets to the per-person target instead of counting exercises (the old
    # heuristic was blind to sets-per-exercise and let sessions silently
    # shrink).
    #
    # The budget line is ``minutes = warmup + sets × min_per_working_set``,
    # which is a linear regression of measured session duration on working
    # sets: ``warmup`` is its intercept, ``min_per_working_set`` its slope.
    # The old 5.0 intercept was not measured and was too low — it billed a
    # 28-set session at 75 minutes when the fitted line puts it past 80.
    #
    # Fixed overhead is PER PERSON, not universal: it is the intercept of
    # that person's own duration-vs-sets line. It is read from profile.csv
    # under ``session_warmup_min`` — a registered key in
    # ``shared.csv_store_profile.PROFILE_KEYS`` with float coercion, which
    # is what makes the read below reach a real value instead of always
    # falling through. The constant here is only the fallback for a profile
    # that has not been fitted yet; same arrangement for the slope,
    # ``min_per_working_set``. ----
    SESSION_WARMUP_MIN_DEFAULT = 20.0
    try:
        session_warmup_min = float(
            profile.get("session_warmup_min") or SESSION_WARMUP_MIN_DEFAULT
        )
    except (TypeError, ValueError):
        session_warmup_min = SESSION_WARMUP_MIN_DEFAULT
    if not (0.0 <= session_warmup_min <= 45.0):
        session_warmup_min = SESSION_WARMUP_MIN_DEFAULT
    session_target_min = profile.get("session_target_min") or 60
    # Per-person pace (min per working set incl. rest). Default 3.3 was the
    # old one-size constant and is too slow for trainees who rest short or
    # superset accessories, which silently capped their sessions and their
    # weekly per-muscle volume. Read from profile.csv (key
    # ``min_per_working_set``); falls back to 3.3.
    try:
        min_per_working_set = float(profile.get("min_per_working_set") or 3.3)
    except (TypeError, ValueError):
        min_per_working_set = 3.3
    if not (1.5 <= min_per_working_set <= 6.0):
        min_per_working_set = 3.3
    target_working_sets = max(
        8, round((session_target_min - session_warmup_min) / min_per_working_set)
    )

    # ---- Priority tiers (D8) and the distribution-shaped weekly specs the
    # render validators enforce. The tier map (resolved above, where the
    # bench rule consumes it) turns into a set target per muscle in the
    # same FRACTIONAL unit as ``weekly_volume_per_muscle``. ----
    volume_targets = muscle_volume_targets(priority_tiers)
    if priority_unknown:
        # A typo in the profile override must not resolve silently to
        # ``maintain``: that drops a muscle out of the emphasis set, which
        # is the exact class of quiet failure this build exists to remove.
        print(
            "WARNING: profile muscle_priority_tiers has unrecognised "
            f"entries, ignored: {', '.join(priority_unknown)}",
            file=sys.stderr,
        )

    out: TrackerJSON = {
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
        # ---- Prescription memory: what was asked for, versus what happened.
        # ``adherence`` is None on a first run (no plans on disk) and
        # ``_compact`` drops it, which reads correctly as "unknown" rather
        # than as 0% adherence. ----
        "adherence":            adherence,
        "dose_staleness":       dose_stale,
        "block":                block,
        "rotation_candidates":  rot_candidates or None,
        # ---- Distribution-shaped weekly specs + priority tiers (D8). ----
        "core_week_spec":         CORE_WEEK_SPEC,
        "arm_week_spec":          ARM_WEEK_SPEC,
        "muscle_priority_tiers":  priority_tiers,
        "muscle_volume_targets":  volume_targets,
        "volume_landmark_unit":   "fractional",
        "synergist_credit_offset": SYNERGIST_CREDIT_OFFSET,
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
        # ---- Nutrition phase (bulk / cut / maintain / recomp). Only
        # present when the person has an open phase in
        # nutrition_phases.csv; ``_compact`` drops None when absent so
        # the renderer's card gate stays consistent with thermal /
        # light_therapy. ----
        "nutrition_phase":      nutrition_phase,
        # ---- Daily activity (NEAT) — all-day movement beyond workouts. ----
        "daily_activity_28d": daily_activity,
        # ---- Recovery + training load (Python-derived, not raw metrics) ----
        "recovery": recovery,
        "training_load": training_load,
        "training_load_by_modality": training_load_by_modality,
        "hr_at_volume_divergence": hr_volume_div,
        "age_years": age_years,
        "estimated_max_hr": max_hr,
        "estimated_rest_hr": round(rest_hr, 1) if rest_hr else None,
        # ---- Bodyweight ----
        "bodyweight_latest": bw_latest,
        # Scalar stays ``float | None`` for every existing consumer. The
        # block beside it says WHY it is None — absent that, a renderer
        # cannot tell "no weigh-ins" from "the rate is not resolvable",
        # and the second of those is a sentence the coach must say out
        # loud rather than silently omit.
        "bodyweight_trend_kg_per_week": bw_trend,
        "bodyweight_trend": bw_trend_block,
        "bodyweight_weekly": _bodyweight_weekly_kg(bw_all, today_d, weeks=4),
        # ---- Waist circumference ----
        # ``waist_latest`` is ``{value_cm, date}`` for the newest
        # measurement at or before ``today``, and None (dropped by
        # ``_compact``, same as ``bodyweight_latest`` / ``vo2max_latest``)
        # when the column has never been filled in.
        "waist_latest": waist_latest,
        # Same block shape as ``bodyweight_trend``, rate in cm per 4
        # weeks: ``state`` / ``reason`` / ``note`` plus ``cm_per_4w``,
        # which is populated ONLY when the 95% interval excludes zero.
        # There is no bare-scalar twin on purpose — a caller that wants
        # the number has to pass through ``state`` to reach it.
        "waist_trend_cm_per_4w": waist_trend_block,
        # ---- Apple Health weekly aggregates (raw daily behind a flag) ----
        "health_metrics_weekly": weekly_health,
        "health_metrics_recent": health_recent if args.include_daily_health else None,
        "vo2max_latest": latest_metric(health_all, "vo2max"),
        "vo2max_trend_per_4w": metric_trend_per_4w(health_all, "vo2max"),
        # ---- Week-over-week comparison (this-week / last-week / 4-wk avg
        # for the assessment dashboard's bottom card). ----
        "week_over_week": week_over_week,
        # ---- Recovery gate: 5-tier session recommendation. SKILL.md Phase 2
        # MUST honor this before generating any workout. ----
        "session_recommendation": session_recommendation,
        # 14-day rolling tier classifications (Trajectory tab).
        "tier_history":           tier_history,
        # ---- Session-length budget (set-count driven, per-person target) ----
        "session_target_min":     session_target_min,
        "target_working_sets":    target_working_sets,
        # ---- Longevity Trajectory tab ----
        "longevity_score":      longevity_score,
        "longevity_state":      longevity_state,
        "vo2_percentile":       vo2_percentile,
        "hr_recovery":          hr_recovery,
        "acwr":                 acwr,
        "sleep_regularity":     sleep_regularity,
        "rem_anomaly":          rem_anomaly,
        "movement_consistency": movement_consistency,
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
