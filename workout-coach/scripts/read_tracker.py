"""Read a person's tracker and emit the coaching snapshot as JSON.

The weekly snapshot is the current planning input. The dated snapshot remains
available for historical assessment and plan validation. Run with --help for
supported options.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from itertools import chain
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
from shared.csv_store_periodic import (  # noqa: E402
    read_nutrition_phases, read_sleep_nights, read_swim_laps, read_swim_workouts,
)
from shared.health_import_receipts import read_health_import_receipts  # noqa: E402
from shared.person_paths import monthly_dir  # noqa: E402
from workout_coach.lib.constants import (  # noqa: E402
    ARM_WEEK_SPEC,
    CORE_WEEK_SPEC,
    DEFAULT_DATA_SOURCE,
    SOURCE_CAPABILITIES,
    STALE_EXERCISE_DAYS,
    SYNERGIST_CREDIT_OFFSET,
    cadence_deload_week,
    muscle_floors,
    muscle_priority_tiers,
    muscle_volume_targets,
)
from workout_coach.lib.parsing import _compact, _parse_iso_date  # noqa: E402
from workout_coach.lib.extract import (  # noqa: E402
    _age_from_birthday,
    estimate_max_hr,
    load_exercises_db,
    read_coach_training,
    read_health_metrics,
    read_workout_sessions,
)
# The health analytics live in four focused modules, imported directly.
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
    apply_user_override,
    compute_session_recommendation,
)
from workout_coach.lib.progression import (  # noqa: E402
    INCREMENT_HISTORY_MONTHS,
    build_next_dose,
)
from workout_coach.lib.sessions import (  # noqa: E402
    _is_working_set,
    body_fat_trend,
    bodyweight_trend,
    build_monthly_sessions,
    lean_mass_trend,
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
    last_strength_session_type,
    load_plans,
    retired_movements,
    unavailable_movements,
)
from workout_coach.lib.blocks import (  # noqa: E402
    block_payload,
    load_pattern_catalog,
    rotation_candidates,
    withhold_owed_stalls,
)
from workout_coach.lib.exercise_fit import exercise_fit_summary  # noqa: E402
from workout_coach.lib.cardio import (  # noqa: E402
    auto_deload_candidates,
    cardio_hr_zones,
    cardio_last_28d,
    compute_acwr,
    compute_hr_recovery_summary,
    compute_movement_consistency_days,
    daily_activity_28d,
    energy_28d,
    training_load_summary,
    trimp_per_session,
)
from workout_coach.lib.sleep import (  # noqa: E402
    compute_sleep_regularity_index,
    flag_rem_sleep_anomalies,
    sleep_summary,
)
from workout_coach.lib.swim import swim_summary  # noqa: E402
from workout_coach.lib.nutrition_phase import (  # noqa: E402
    nutrition_phase_summary,
    weekly_nutrition_review,
)
from workout_coach.lib.weekly_review import observation_coverage, week_context  # noqa: E402


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


















def _body_comp_readings(health_all: list[dict], column: str,
                        value_key: str) -> list[dict]:
    """One body-composition column off the health-metrics rows, ASC by date.

    ``Waist (cm)``, ``Body Fat %`` and ``Lean Mass (kg)`` are written by
    the importer's own field map, and manual readings reach the same
    columns, so this reader is source-agnostic on purpose: it takes the
    column, not the writer.
    ``health_all`` has already been through ``_clip_series``, so the
    ``--today`` horizon is applied before anything here sees a row.

    Blank cells are skipped rather than yielded as ``0`` — a person who
    has never measured returns ``[]``, which reads downstream as "no
    data" instead of "flat at zero". That is the whole difference
    between an empty channel and a channel pinned at the origin, and it
    is why all three columns share this one reader rather than growing a
    second copy that forgets the rule.
    """
    out: list[dict] = []
    for entry in health_all:
        value = entry.get(column)
        if value is None:
            continue
        out.append({"date": entry["date"], value_key: value})
    out.sort(key=lambda e: e["date"])
    return out


def _attach_body_comp_weekly(weekly: list[dict], readings: list[dict],
                             value_key: str, out_key: str,
                             today_d: date, weeks: int = 4) -> list[dict]:
    """Fold a per-ISO-week mean of one body-composition column onto each
    ``health_metrics_weekly`` entry, keyed by ``week_start``.

    None of these columns is part of ``health_metrics_weekly``'s own key
    list; they are added here so the vitals table can draw their
    sparklines from the same series every other vitals row uses. Weeks
    with no measurement are left at ``None``, which ``_compact`` strips —
    the sparkline then sees a gap rather than an invented value, and a
    series with fewer than two real points renders as an empty box rather
    than a flat line.

    A column that has never been written attaches NOTHING, so the key is
    absent rather than present-and-null across every week. The renderer
    reads that as "no channel" and says so.
    """
    if not weekly or not readings:
        return weekly
    cutoff = today_d - timedelta(days=max(weeks * 7 - 1, 0))
    by_week: dict[str, list[float]] = {}
    for row in readings:
        d = _parse_iso_date(row.get("date"))
        if d is None or d < cutoff or d > today_d:
            continue
        try:
            value = float(row[value_key])
        except (TypeError, ValueError, KeyError):
            continue
        iso = d.isocalendar()
        monday = date.fromisocalendar(iso.year, iso.week, 1).isoformat()
        by_week.setdefault(monday, []).append(value)
    for entry in weekly:
        vals = by_week.get(entry.get("week_start"))
        entry[out_key] = (round(sum(vals) / len(vals), 2) if vals
                          else None)
    return weekly






class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(f"read_tracker: error: {message}", file=sys.stderr)
        raise SystemExit(2)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = _ArgumentParser(allow_abbrev=False)
    parser.add_argument("--person", required=True)
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument("--today")
    for flag in ("include-rows", "include-1rm-history", "include-daily-health",
                 "pretty", "override-gate", "weekly"):
        parser.add_argument(f"--{flag}", action="store_true")
    projection = parser.add_mutually_exclusive_group()
    projection.add_argument("--for-coach", action="store_true",
                            help="Return planning evidence for --weekly.")
    projection.add_argument("--field", action="append", default=[], metavar="NAME",
                            help="Return a selected top-level field. Repeat for multiple fields.")
    parser.add_argument("--sessions", type=int)
    parser.add_argument("--week-start")
    parser.add_argument("--training-days")
    parser.add_argument("--minutes", type=int)
    args = parser.parse_args(argv)
    if not args.person:
        parser.error("the following arguments are required: --person")
    if args.sessions is not None and not 1 <= args.sessions <= 14:
        parser.error("argument --sessions: expected a count from 1 to 14")
    if args.minutes is not None and args.minutes < 1:
        parser.error("argument --minutes: expected positive minutes")
    if args.for_coach and not args.weekly:
        parser.error("--for-coach requires --weekly")
    if args.for_coach and (args.include_rows or args.include_1rm_history or args.include_daily_health):
        parser.error("--for-coach cannot be combined with detail flags")
    if args.weekly and args.override_gate:
        parser.error("--override-gate is available only for the dated session analysis")
    if not args.weekly and any(value is not None for value in
                               (args.week_start, args.training_days, args.minutes)):
        parser.error("--week-start, --training-days and --minutes require --weekly")
    return args


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

    (rows, session_totals, session_summaries), increment_rows, deload_dates = read_coach_training(
        person, today_d, args.months, INCREMENT_HISTORY_MONTHS,
    )
    # Enforce the ``--today`` horizon on every series before any analytics
    # run. See ``_clip_series``: the readers hand back whole files, so
    # without this a run dated 2026-06-01 reported a 2026-07-29 top set and
    # an August weigh-in, and ten payload blocks were byte-identical across
    # a seven-week ``--today`` gap.
    rows = _clip_series(rows, today_d)
    session_totals = _clip_date_map(session_totals, today_d)
    session_summaries = _clip_date_map(session_summaries, today_d)
    deloads = [d for d in deload_dates
               if (_parse_iso_date(d) or today_d) <= today_d]

    profile = read_profile(person)
    session_target_min = args.minutes or profile.get("session_target_min") or 60
    sessions_per_week = args.sessions or profile.get("strength_sessions_per_week")
    weekly = None
    existing_week = None
    revisions = None
    if args.weekly:
        from workout_coach.lib.weekly_prescription import latest_published_weeks, read_week_revisions

        revisions = read_week_revisions(person)
        published = latest_published_weeks(person, today_d, revisions=revisions)
        try:
            weekly = week_context(
                today_d, args.week_start, args.training_days,
                args.sessions if args.training_days is not None else sessions_per_week,
                session_target_min, published,
            )
        except ValueError as exc:
            print(f"read_tracker: error: {exc}", file=sys.stderr)
            return 2
        weekly["person"] = person
        existing_week = next((record for record in published
                              if record["prescription"]["week_start"] == weekly["week_start"]), None)
        if existing_week is not None and args.sessions is None and args.training_days is None:
            weekly["session_count"] = len(existing_week["prescription"]["sessions"])
        sessions_per_week = weekly["session_count"]
    data_source = profile.get("source") or DEFAULT_DATA_SOURCE
    capabilities = SOURCE_CAPABILITIES.get(data_source, SOURCE_CAPABILITIES[DEFAULT_DATA_SOURCE])

    # Every dataset lives in a CSV under <person>/data/. The lib readers
    # below all take the person string and resolve the matching file.
    health_all = _clip_series(read_health_metrics(person), today_d)
    # Bodyweight has dedicated latest/trend outputs; keep the optional
    # daily-health detail focused on the other signals.
    health_recent = [
        {k: v for k, v in entry.items() if k != "bodyweight_kg"}
        for entry in health_all[-30:]
    ]

    workout_sessions_all = _clip_series(read_workout_sessions(person), today_d)
    swim_workouts_all = _clip_series(read_swim_workouts(person), today_d)
    swim_laps_all = _clip_series(read_swim_laps(person), today_d)
    sleep_nights_all = _clip_series(read_sleep_nights(person), today_d)
    week_coverage = observation_coverage(
        today_d, health_all, sleep_nights_all, workout_sessions_all,
        (row for row in rows if _is_working_set(row)), capabilities,
        read_health_import_receipts(person),
    ) if weekly is not None else None
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

    bw_all = sorted(
        ({"date": entry["date"], "kg": entry["bodyweight_kg"],
          "notes": entry.get("notes")}
         for entry in health_all if entry.get("bodyweight_kg") is not None),
        key=lambda entry: entry["date"],
    )
    bw_latest = (
        {"date": bw_all[-1]["date"], "kg": bw_all[-1]["kg"]}
        if bw_all else None
    )

    # Parse the exercises database once; it's read-only for this run.
    db_path = Path(__file__).resolve().parents[2] / "shared" / "exercises-database.md"
    db = load_exercises_db(db_path)

    # ``catalog`` carries movement-pattern identity (the ## MUSCLE heading
    # plus ### Subsection), which ``db`` structurally cannot: it resolves
    # every subsection to one ``primary`` muscle and discards which pattern
    # the movement was. Rotation is defined on the pattern, so the pattern
    # has to survive. e1RM reads it for the equipment (a gym-change note
    # does not bear on a dumbbell) and the rep ceiling behind the stall
    # count; ``next_dose`` reads it for compound vs isolation and the
    # load increment.
    catalog = load_pattern_catalog(db)

    unknown_set: set[str] = set()
    weekly_volume = weekly_volume_per_muscle(rows, db, today_d, 28, unknown_set)
    e1rm = estimated_1rm(rows, deloads,
                         include_history=args.include_1rm_history,
                         catalog=catalog)
    stale_full = stale_exercises(rows, db, today_d, STALE_EXERCISE_DAYS)
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

    # Reconcile published and historical prescriptions with logged work.
    priority_tiers, priority_unknown = muscle_priority_tiers(profile)
    plans_parsed = load_plans(person, today_d, limit=8, db=db, revisions=revisions)
    adherence = build_adherence(person, rows, db, today_d, catalog,
                                priority_tiers=priority_tiers, plans=plans_parsed)
    fit = None
    retired = retired_movements(person)
    block_adherence = adherence
    rotation_excluded = retired | unavailable_movements(person)
    if weekly is not None:
        swaps = (
            {"exercise": swap["prescribed"], "date": swap["date"], "outcome": "swapped"}
            for swap in (adherence or {}).get("substitutions") or []
        )
        try:
            fit = exercise_fit_summary(
                person, weekly["week_start"], weekly["week_end"],
                history=chain((row for row in rows if _is_working_set(row)), swaps),
                as_of=today_d,
            )
        except ValueError as exc:
            print(f"read_tracker: error: {exc}", file=sys.stderr)
            return 2
        # Scope-specific exclusions are enforced at publication, where the
        # planned date and equipment are available.
        retired |= {
            rule["exercise"].casefold() for rule in fit["restrictions"]
            if rule.get("location") is None and not any(rule.get(key) for key in (
                "location_scoped", "variant", "start_date", "end_date",
            ))
        }
        rotation_excluded = retired
        block_adherence = {**(adherence or {}), "benched": sorted(retired)}
    else:
        retired = rotation_excluded
        rotation_excluded = rotation_excluded | {
            b["exercise"] for b in (adherence or {}).get("benched") or []
        }

    block = block_payload(
        person, rows, db, catalog, today_d, deloads,
        adherence=block_adherence, e1rm=e1rm, plans=plans_parsed,
        block_as_of=today_d if weekly is not None else None,
    )
    # Starting loads for movements with no history. Until this existed the
    # payload named only the ~46 exercises already logged, and the active
    # load rule is "copy last session's load forward" — so there was no
    # legal way to write a weight for anything else and rotation could not
    # actually be prescribed.
    #
    # Benched and retired movements are excluded: the payload used to name
    # `Leg Curl (Lying)` under `adherence.benched` ("must not
    # re-prescribe") and offer it here with a derived load in the same
    # breath. The tiers go in so the 56-day pattern gate cannot hide the
    # emphasis categories the weekly spec forces the coach to add — they
    # sit at zero precisely because they are the gap.
    rot_candidates = rotation_candidates(
        rows, db, catalog, e1rm, today_d,
        exclude=rotation_excluded,
        priority_tiers=priority_tiers)

    # ---- The next load of every lift, in two passes around the gate. ----
    # The load step of each lift is learned from a longer stretch of the log
    # than the analytics window, so a lift that steps once a month still
    # shows its jumps.
    jump_rows = rows if args.months >= INCREMENT_HISTORY_MONTHS else _clip_series(increment_rows, today_d)

    def _next_dose(load_policy: dict) -> dict:
        return build_next_dose(
            rows, catalog, plans_parsed, block, load_policy, today_d,
            deload_dates=deloads, jump_rows=jump_rows, retired=retired)

    # Pass one runs under a neutral policy because it answers a question the
    # gate asks and the policy cannot change: which lifts have EARNED a bump
    # (every set at the top of the range). A lift that is owed weight is
    # waiting for it, not stuck, so it must not count as stalled in the
    # gate's reactive-deload trigger or the nutrition stop signal
    # (`health_session_rec._genuinely_stalled_lifts` skips ``weight_owed``).
    next_dose = _next_dose({"policy": "progress"})
    owed = {e["exercise"].strip().lower() for e in next_dose["exercises"]
            if e["action"] == "add_load"}
    for lift, entry in e1rm.items():
        if lift.strip().lower() in owed:
            entry["weight_owed"] = True
    # The block was built before this was known (next_dose reads the block's
    # rep ranges), so withdraw the stall count it stamped on owed lifts: an
    # owed lift is bumped, and must not qualify for `stall_3_sessions`.
    withhold_owed_stalls(block, owed)

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
        # Typical adult RHR, for a source that cannot supply one.
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
    # ---- Daily energy expenditure. ``None`` when neither energy column
    # carries a reading in the window, so ``_compact`` drops the key and a
    # tracker without the data reads as an absent channel rather than as
    # an athlete burning nothing. It is computed HERE, above the nutrition
    # phase, because the phase block needs the measured TDEE to turn its
    # target rate into an intake number. ----
    energy = energy_28d(health_all, today_d)
    measured_tdee = (energy or {}).get("tdee_kcal_daily_avg")
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
    # ---- Nutrition phase (bulk / cut / maintain / recomp). Returns None
    # when no open phase. The summarizer needs estimated_1rm to detect
    # the "lifts stalled while bulking" stop-signal, so this call must
    # happen AFTER the e1rm calculation above. ----
    if weekly is not None:
        nutrition_phase = weekly_nutrition_review(nutrition_phases_all, bw_all, today_d)
    else:
        nutrition_phase = nutrition_phase_summary(
            nutrition_phases_all, bw_all, today_d, estimated_1rm=e1rm,
            tdee_kcal=measured_tdee,
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
    waist_readings = _body_comp_readings(health_all, "waist_cm", "cm")
    waist_latest = (
        {"value_cm": waist_readings[-1]["cm"],
         "date":     waist_readings[-1]["date"]}
        if waist_readings else None
    )
    waist_trend_block = waist_trend(waist_readings, today_d=today_d)
    # The vitals table draws its waist sparkline off the weekly series,
    # the same way HRV / RHR / VO2max do.
    weekly_health = _attach_body_comp_weekly(
        weekly_health, waist_readings, "cm", "waist_cm", today_d, weeks=4)

    # ---- Body fat % and lean mass. The remaining two columns of the
    # 19-col health_metrics schema, both written by both importers and,
    # until now, read by nothing — the same gap waist had.
    #
    # NEITHER IS PRESENT IN ANY EXPORT YET, so what actually ships here is
    # the empty state. The three failure modes it exists to prevent are a
    # rendered 0.0, a flat sparkline through a single point, and the
    # channel silently vanishing; all three read as a finding to a coach
    # that cannot tell "unmeasured" from "unchanged".
    #
    # ``latest`` is a fact and is emitted as soon as one reading exists.
    # The trend goes through the SAME gate as bodyweight and waist, so a
    # thin series returns an explicit reason rather than a slope. Lean
    # mass is additionally NOT independent of the other two — see
    # ``sessions.lean_mass_trend``.
    body_fat_readings = _body_comp_readings(health_all, "body_fat_pct", "pct")
    body_fat_latest = (
        {"value_pct": body_fat_readings[-1]["pct"],
         "date":      body_fat_readings[-1]["date"]}
        if body_fat_readings else None
    )
    body_fat_trend_block = body_fat_trend(body_fat_readings, today_d=today_d)
    weekly_health = _attach_body_comp_weekly(
        weekly_health, body_fat_readings, "pct", "body_fat_pct",
        today_d, weeks=4)

    lean_mass_readings = _body_comp_readings(
        health_all, "lean_body_mass_kg", "kg")
    lean_mass_latest = (
        {"value_kg": lean_mass_readings[-1]["kg"],
         "date":     lean_mass_readings[-1]["date"]}
        if lean_mass_readings else None
    )
    lean_mass_trend_block = lean_mass_trend(lean_mass_readings,
                                            today_d=today_d)
    weekly_health = _attach_body_comp_weekly(
        weekly_health, lean_mass_readings, "kg", "lean_mass_kg",
        today_d, weeks=4)

    vo2_latest = latest_metric(health_all, "vo2max")
    hr_recovery = compute_hr_recovery_summary(health_all, today_d)
    acwr = compute_acwr(trimps, today_d)
    sleep_regularity = compute_sleep_regularity_index(sleep_nights_all, today_d, window_days=14)

    full_report = not args.field and not args.for_coach
    want_score = full_report or "longevity_score" in args.field
    want_percentile = want_score or "vo2_percentile" in args.field
    sex = profile.get("sex")
    longevity_state = None
    if full_report or "longevity_state" in args.field or (want_percentile and not sex):
        longevity_state = read_longevity_state(person, today_d)
        sex = sex or (longevity_state or {}).get("sex")
    vo2_percentile = (vo2_percentile_age_sex((vo2_latest or {}).get("value"), sex, age_years)
                      if want_percentile else None)
    rem_anomaly = (flag_rem_sleep_anomalies(sleep_nights_all, today_d)
                   if full_report or "rem_anomaly" in args.field else None)
    movement_consistency = (compute_movement_consistency_days(health_all, today_d)
                            if want_score or "movement_consistency" in args.field else None)
    longevity_score = None
    if want_score:
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

    session_recommendation = None
    if weekly is None:
        # The dated session diagnostic has no authority over the weekly plan.
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
        if args.override_gate:
            session_recommendation = apply_user_override(
                session_recommendation, recovery, strength_training_load)
        policy = session_recommendation["load_policy"]
        if policy["policy"] != "progress":
            next_dose = _next_dose(policy)

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
        overhead = profile.get("session_warmup_min")
        session_warmup_min = float(
            SESSION_WARMUP_MIN_DEFAULT if overhead is None else overhead
        )
    except (TypeError, ValueError):
        session_warmup_min = SESSION_WARMUP_MIN_DEFAULT
    if not (0.0 <= session_warmup_min <= 45.0):
        session_warmup_min = SESSION_WARMUP_MIN_DEFAULT
    # Per-person pace (min per working set incl. rest). Default 3.3 was the
    # old one-size constant and is too slow for trainees who rest short,
    # which silently capped their sessions and their
    # weekly per-muscle volume. Read from profile.csv (key
    # ``min_per_working_set``); falls back to 3.3.
    try:
        min_per_working_set = float(profile.get("min_per_working_set") or 3.3)
    except (TypeError, ValueError):
        min_per_working_set = 3.3
    if not (1.5 <= min_per_working_set <= 6.0):
        min_per_working_set = 3.3
    min_working_sets = 1 if weekly is not None else 8
    target_working_sets = max(
        min_working_sets, round((session_target_min - session_warmup_min) / min_per_working_set)
    )

    # ---- Priority tiers (D8) and the distribution-shaped weekly specs the
    # render validators enforce. The tier map (resolved above, where the
    # bench rule consumes it) turns into a set target per muscle in the
    # same FRACTIONAL unit as ``weekly_volume_per_muscle``. ----
    volume_targets = muscle_volume_targets(priority_tiers)
    # The same function the plan check enforces, so the coach and the
    # validator read one number per muscle. The floors are a four-session
    # week's: they scale down for a week of fewer sessions, and by
    # (n - 0.5) / n on a cadence deload week (one halved session), where they
    # stay blocking. A full-block deload makes them advisory in the check, not
    # smaller here.
    floors = muscle_floors(
        priority_tiers,
        servable={meta["primary"] for meta in db.values()
                  if meta.get("primary")},
        sessions_per_week=sessions_per_week,
        cadence_deload=cadence_deload_week(session_recommendation, block),
    ) if weekly is None else None
    last_session, last_session_reason = last_strength_session_type(
        rows, plans_parsed, db, today_d)
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
        "weekly_plan": weekly,
        "observation_coverage": week_coverage,
        "existing_week": existing_week,
        "exercise_fit": fit,
        "data_source": data_source,
        "capabilities": capabilities,
        "auto_cardio_enabled": bool(profile.get("auto_cardio")),
        "monthly_sessions": monthly_sessions,
        "weekly_volume_per_muscle": weekly_volume,
        "estimated_1rm": e1rm,
        "progression_summary": progression_summary(rows, catalog),
        "stale_exercises": stale,
        "unknown_exercises": sorted(unknown_set),
        "adherence":            adherence,
        "next_dose":            next_dose,
        "block":                block,
        "rotation_candidates":  rot_candidates or None,
        "core_week_spec":         CORE_WEEK_SPEC,
        "arm_week_spec":          ARM_WEEK_SPEC,
        "muscle_priority_tiers":  priority_tiers,
        "muscle_volume_targets":  volume_targets,
        "muscle_floors":          floors,
        "strength_sessions_per_week": sessions_per_week,
        "last_session_type":      last_session,
        "last_session_type_reason": last_session_reason,
        "volume_landmark_unit":   "fractional",
        "synergist_credit_offset": SYNERGIST_CREDIT_OFFSET,
        "deloads": deloads,
        "auto_deload_candidates": auto_deloads,
        "cardio_last_28d": cardio_last_28d(rows, today_d),
        "cardio_hr_zones_28d": cardio_zones,
        "swim_summary": swim,
        "sleep_summary": sleep,
        "nutrition_phase":      nutrition_phase,
        "daily_activity_28d": daily_activity,
        "energy_28d": energy,
        "recovery": recovery,
        "training_load": training_load,
        "training_load_by_modality": training_load_by_modality,
        "hr_at_volume_divergence": hr_volume_div,
        "age_years": age_years,
        "estimated_max_hr": max_hr,
        "estimated_rest_hr": round(rest_hr, 1) if rest_hr else None,
        "bodyweight_latest": bw_latest,
        "bodyweight_trend_kg_per_week": bw_trend,
        "bodyweight_trend": bw_trend_block,
        "waist_latest": waist_latest,
        "waist_trend_cm_per_4w": waist_trend_block,
        "body_fat_latest":            body_fat_latest,
        "body_fat_trend_pct_per_4w":  body_fat_trend_block,
        "lean_mass_latest":           lean_mass_latest,
        "lean_mass_trend_kg_per_4w":  lean_mass_trend_block,
        "health_metrics_weekly": weekly_health,
        "health_metrics_recent": health_recent if args.include_daily_health else None,
        "vo2max_latest": vo2_latest,
        "vo2max_trend_per_4w": metric_trend_per_4w(health_all, "vo2max"),
        "session_recommendation": session_recommendation,
        "session_target_min":     session_target_min,
        "target_working_sets":    target_working_sets,
        "session_time_model": {
            "overhead_min": session_warmup_min,
            "min_per_working_set": min_per_working_set,
        },
        "longevity_score":      longevity_score,
        "longevity_state":      longevity_state,
        "vo2_percentile":       vo2_percentile,
        "hr_recovery":          hr_recovery,
        "acwr":                 acwr,
        "sleep_regularity":     sleep_regularity,
        "rem_anomaly":          rem_anomaly,
        "movement_consistency": movement_consistency,
        "rows": rows if args.include_rows else None,
    }
    if args.field:
        unknown = sorted(set(args.field) - out.keys())
        if unknown:
            print(f"read_tracker: error: unknown field(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        out = {key: out[key] for key in args.field}
    if args.for_coach:
        from workout_coach.lib.coach_context import coach_context
        out = coach_context(out)
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
