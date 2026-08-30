"""Health Export Kit reader.

Replaces Health Auto Export, which stopped producing usable exports after
iOS 27. See ``Skills/docs/specs/2026-08-30-health-export-kit.md`` for the
format, the verification evidence, and the reasoning behind every rule
below.

Four rules here exist because the export is subtly wrong or subtly different
from what the tracker stored before, and each produces a plausible number
rather than an error when ignored:

- Daily **sums** are only written for days the export range fully covers.
  Two exports 27 minutes apart reported 6,326 and 5,926 steps for the same
  day. Averages and latest-readings are unaffected by a truncated day and
  are still written, so today's weight and resting HR arrive on the day
  they are taken.
- ``breathingDisturbances`` is filed by the export on the day the night
  began; the tracker files it on the morning it belongs to. Tested at three
  offsets against stored history: mean absolute error 0.672, 0.649 and
  0.168. Shift forward one day.
- ``weatherHumidityPercent`` carries basis points, not percent (values run
  2,600 to 8,700). An app bug.
- ``hrv_sdnn`` is never written. The export has no all-day HRV, only a
  sleep-window value from two to four readings a night, which has four
  times the variance of the historical series. Mixing them would corrupt
  the recovery score's rolling baseline. The sleep value gets its own
  column in a later change.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import date, timedelta
from pathlib import Path

# Lets this file run as a direct script (``python3 shared/import_health_export_kit.py``)
# from the tracker root, mirroring the retired ``import_health_auto_export.py``: a
# script invocation has no package context, so ``shared`` itself would not otherwise
# be importable. A normal package import (``from shared import import_health_export_kit``)
# already has ``__package__`` set, so the guard below is a no-op in that case.
SKILLS_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(SKILLS_ROOT))

from shared import hek_time
from shared.apple_workout_types import (
    APPLE_TO_TRACKER_EXERCISE,
    CARDIO_AUTOLOG_TYPES,
    hek_canonical_type,
)
from shared.csv_store import (
    ensure_profile,
    read_profile,
    upsert_health_metrics,
    upsert_sleep_nights,
    upsert_swim_workouts,
    upsert_workout_sessions,
    write_profile,
)
from shared.data_git import commit_data
from shared.monthly_csv_upsert import (
    upsert_monthly_cardio,
    upsert_monthly_strength_session,
)
from shared.person_paths import WORKOUT_TRACKER_ROOT
from shared.strength_sessions import cluster_strength_sessions
from tracker.importing import build_auto_cardio_payload

SOURCE_NAME = "health_export_kit"

# Daily fields that are a sum over the day, and are therefore wrong on a
# day the export range only partly covers.
SUM_METRICS = frozenset({
    "steps", "activeEnergyKcal", "basalEnergyKcal", "distanceKm",
    "exerciseMinutes", "flightsClimbed", "workoutCount",
})

# activity.daily key -> health_metrics.csv field
ACTIVITY_FIELDS = {
    "steps": "steps",
    "activeEnergyKcal": "active_energy_kcal",
    "basalEnergyKcal": "basal_energy_kcal",
    "exerciseMinutes": "exercise_min",
}

# additional.<section> metric key -> health_metrics.csv field
ADDITIONAL_FIELDS = {
    "body": {"bodyMass": "bodyweight_kg", "waist": "waist_cm"},
    "heart": {
        "vo2max": "vo2max",
        "restingHR": "resting_hr",
        "walkingHR": "walking_hr",
        "hrRecovery": "hr_recovery_1min",
        "breathingDisturbances": "sleep_breath_dist",
    },
}

# Metrics the export files on the day the night began. The tracker files
# them on the wake date.
NIGHT_ONSET_METRICS = frozenset({"breathingDisturbances"})


def _in_window(day: date, since: date | None, until: date | None) -> bool:
    if since and day < since:
        return False
    if until and day > until:
        return False
    return True


def build_health_payload(payload: dict,
                         since: date | None,
                         until: date | None) -> list[dict]:
    """Roll the export's daily sections into ``upsert_health_metrics`` rows."""
    meta = payload["meta"]
    first_complete, last_complete = hek_time.complete_days(meta)
    rows: dict[str, dict] = {}

    def put(day: date, field: str, value) -> None:
        if value is None or not _in_window(day, since, until):
            return
        rows.setdefault(day.isoformat(), {"date": day.isoformat()})[field] = value

    activity = payload.get("activity") or {}
    for entry in activity.get("daily") or []:
        day = hek_time.parse_day(entry["date"])
        covered = first_complete <= day <= last_complete
        for key, field in ACTIVITY_FIELDS.items():
            if key not in entry:
                continue  # absent is not zero
            if key in SUM_METRICS and not covered:
                continue
            put(day, field, entry[key])

    additional = payload.get("additional") or {}
    for section, mapping in ADDITIONAL_FIELDS.items():
        block = additional.get(section)
        if not isinstance(block, dict):
            continue  # a requested category with no data has no section
        aggregation = block.get("aggregation") or {}
        for entry in block.get("daily") or []:
            day = hek_time.parse_day(entry["date"])
            covered = first_complete <= day <= last_complete
            values = entry.get("values") or {}
            for key, field in mapping.items():
                if key not in values:
                    continue
                if aggregation.get(key) == "sum" and not covered:
                    continue
                target = day + timedelta(days=1) if key in NIGHT_ONSET_METRICS else day
                put(target, field, values[key])

    # A row holding nothing but a date is not a row. The retired importer
    # dropped these too, so an empty day stays empty rather than gaining a
    # blank line.
    return [rows[k] for k in sorted(rows) if len(rows[k]) > 1]


# ------------------------------------------------------------------ sleep

# A session starting at or after this local hour belongs to the following
# day's night. Verified against stored history: a 2026-06-27 20:25 nap sits
# on the 2026-06-28 row.
NIGHT_ROLLOVER_HOUR = 18

STAGE_FIELDS = {
    "asleepCore": "core_h",
    "asleepDeep": "deep_h",
    "asleepREM": "rem_h",
    "asleepUnspecified": "unspecified_h",
}


def _hours(seconds: float) -> float:
    return round(seconds / 3600.0, 2)


def assemble_nights(payload: dict) -> dict[str, list[dict]]:
    """Group sleep sessions into nights keyed by wake date.

    ``sleep.sessions[]`` is per session, not per night: a night interrupted
    long enough splits into two, and an evening nap is its own session. The
    two rules below reproduce the retired pipeline's night grouping,
    re-measured against all 224 stored night rows: Time in Bed, Sleep Awake,
    First Segment Start, Last Segment End and N Segments match exactly on
    every night that carries them (224/224, 222/222, 224/224, 224/224,
    216/216). The four stage-derived hour columns (Sleep Total/Core/Deep/
    REM) match exactly on 215-220 of 224 nights and are within 0.01 h of the
    stored value on all of them — one unit in the last decimal place, 36
    seconds, from a different rounding path, not a disagreement about which
    sessions form a night.
    """
    meta = payload["meta"]
    nights: dict[str, list[dict]] = {}
    for session in (payload.get("sleep") or {}).get("sessions") or []:
        start = hek_time.parse_stamp(session["start"], meta)
        end = hek_time.parse_stamp(session["end"], meta)
        if start.hour >= NIGHT_ROLLOVER_HOUR:
            key = (start.date() + timedelta(days=1)).isoformat()
        else:
            key = end.date().isoformat()
        nights.setdefault(key, []).append(
            {**session, "_start": start, "_end": end}
        )
    for sessions in nights.values():
        sessions.sort(key=lambda s: s["_start"])
    return nights


def _night_totals(sessions: list[dict]) -> dict:
    """Stage seconds, asleep, awake and in-bed span for one night's sessions.

    Shared by ``build_sleep_payload`` and ``sleep_headline_rows`` so the two
    stay in lockstep: they must always agree on what a night added up to.
    """
    stage_seconds: dict[str, float] = {}
    for session in sessions:
        for stage in session.get("stages") or []:
            name = stage.get("stage")
            stage_seconds[name] = stage_seconds.get(name, 0.0) + stage.get("durationSec", 0)
    return {
        "stage_seconds": stage_seconds,
        "asleep": sum(s.get("asleepSec") or 0 for s in sessions),
        "awake": sum(s.get("awakeSec") or 0 for s in sessions),
        # In bed is the whole span, gaps between sessions included. The gap
        # itself is not counted as awake time.
        "in_bed": (sessions[-1]["_end"] - sessions[0]["_start"]).total_seconds(),
    }


def build_sleep_payload(payload: dict,
                        since: date | None,
                        until: date | None) -> list[dict]:
    """Rows for ``upsert_sleep_nights``, one per night."""
    rows: list[dict] = []
    for key, sessions in sorted(assemble_nights(payload).items()):
        day = date.fromisoformat(key)
        if not _in_window(day, since, until):
            continue
        totals = _night_totals(sessions)
        stage_seconds = totals["stage_seconds"]
        asleep = totals["asleep"]
        awake = totals["awake"]
        in_bed = totals["in_bed"]

        row = {
            "date": key,
            "total_h": _hours(asleep),
            "awake_h": _hours(awake),
            "time_in_bed_h": _hours(in_bed),
            "n_segments": sum(len(s.get("stages") or []) for s in sessions),
            "first_segment_start": sessions[0]["_start"].strftime("%Y-%m-%d %H:%M:%S"),
            "last_segment_end": sessions[-1]["_end"].strftime("%Y-%m-%d %H:%M:%S"),
        }
        for stage_name, field in STAGE_FIELDS.items():
            if stage_name in stage_seconds:
                row[field] = _hours(stage_seconds[stage_name])
        rows.append(row)
    return rows


def sleep_headline_rows(payload: dict,
                        since: date | None,
                        until: date | None) -> list[dict]:
    """The sleep mirror written into ``health_metrics.csv``.

    ``Resp Rate`` comes from the night's respiratory-rate average. The
    retired importer sourced it from a metric it called daily, but Apple
    only measures respiration during sleep, and the two agreed to 0.1 on
    every overlapping day tested.

    A night can be several sessions, so the per-session averages are
    weighted by each session's ``asleepSec``: an unweighted mean lets a
    20-minute nap pull the night's figure as hard as the 6-hour sleep it
    is filed with. Falls back to the plain mean only when no session
    reports asleep seconds, which leaves no basis for a weight.
    """
    nights = assemble_nights(payload)
    rows: list[dict] = []
    for key, sessions in sorted(nights.items()):
        day = date.fromisoformat(key)
        if not _in_window(day, since, until):
            continue
        totals = _night_totals(sessions)
        stage_seconds = totals["stage_seconds"]
        asleep = totals["asleep"]
        in_bed = totals["in_bed"]

        row = {
            "date": key,
            "sleep_total_h": _hours(asleep),
            "time_in_bed_h": _hours(in_bed),
        }
        if "asleepDeep" in stage_seconds:
            row["sleep_deep_h"] = _hours(stage_seconds["asleepDeep"])
        if "asleepREM" in stage_seconds:
            row["sleep_rem_h"] = _hours(stage_seconds["asleepREM"])

        resp = [
            (((s.get("vitals") or {}).get("respiratoryRate") or {}).get("avg"),
             s.get("asleepSec") or 0)
            for s in sessions
        ]
        resp = [(value, weight) for value, weight in resp if value is not None]
        if resp:
            total_weight = sum(weight for _, weight in resp)
            if total_weight:
                row["resp_rate"] = round(
                    sum(value * weight for value, weight in resp) / total_weight, 2
                )
            else:
                row["resp_rate"] = round(
                    sum(value for value, _ in resp) / len(resp), 2
                )
        rows.append(row)
    return rows


# --------------------------------------------------------------- workouts

# A walk shorter than this is incidental movement -- a trip to the shops,
# a walk to the station -- not a training session. The value matches the
# retired importer (``import_health_auto_export.INCIDENTAL_WALK_MAX_MIN``)
# so the flag means the same thing across the whole stored history rather
# than changing meaning at the import cutover.
#
# The flag has to be written on every row, because
# ``workout-coach/lib/health_windowing.py`` drops rows where it is True and
# nothing else distinguishes a short walk from a session: without it, 322
# of the 698 workouts in the reference export enter the training window as
# real sessions and the incidental-walk count reads zero.
#
# The type test is a substring on purpose: it must catch ``IndoorWalking``
# as well as ``Walking``.
INCIDENTAL_WALK_MAX_MIN = 15.0


def normalize_source(value: str | None) -> str | None:
    """Apple writes "Apple Watch" with a non-breaking space. Flatten it.

    The escape below (U+00A0) is deliberate and must not be replaced by the
    literal character: a literal non-breaking space in source is invisible
    in review and does not reliably survive copy/paste or transcription.
    """
    if value is None:
        return None
    return value.replace("\u00a0", " ").strip()


def humidity_percent(raw: float | None) -> float | None:
    """``weatherHumidityPercent`` carries basis points, not percent.

    Observed range across two people and 250 workouts: 2,600 to 8,700. The
    guard keeps the function correct if the app is ever fixed.

    Deliberately not wired into ``build_workout_payload``: no CSV in this
    repo has a humidity or weather column yet, so nothing calls this. It
    exists so the basis-points-to-percent conversion is settled before one
    does, rather than being worked out again from scratch at that point.
    """
    if raw is None:
        return None
    return round(raw / 100.0, 1) if raw > 100 else raw


def _session_identity_and_common(workout: dict,
                                 meta: dict,
                                 since: date | None,
                                 until: date | None) -> dict | None:
    """The ``date``/``start`` identity plus the ``end``, ``duration_min``
    and ``distance_km`` fields shared by every workout-shaped row.

    Returns ``None`` when the workout has no usable start, or falls outside
    the ``since``/``until`` window, and the caller should skip it entirely.
    Shared by ``build_workout_payload`` and ``build_swim_payload``, which
    walk the same event shape and diverge only in the fields specific to
    each (workout type/source/heart-rate-range vs. laps).
    """
    raw_start = workout.get("start")
    if not raw_start:
        return None  # unusable without an identity
    start = hek_time.parse_stamp(raw_start, meta)
    if not _in_window(start.date(), since, until):
        return None
    row = {
        "date": start.date().isoformat(),
        "start": start.strftime("%H:%M:%S"),
    }
    raw_end = workout.get("end")
    if raw_end:
        row["end"] = hek_time.parse_stamp(raw_end, meta).strftime("%H:%M:%S")
    duration = workout.get("durationSec")
    if duration is not None:
        row["duration_min"] = round(duration / 60.0, 1)
    # Zero distance means the workout carried none, not that it covered
    # no ground. The retired importer made the same distinction.
    distance = workout.get("distanceKm")
    if distance:
        row["distance_km"] = distance
    return row


def build_workout_payload(payload: dict,
                          since: date | None,
                          until: date | None) -> list[dict]:
    """Rows for ``upsert_workout_sessions``, one per workout.

    Four keys here are deliberately not Workout Sessions columns:
    ``total_cal``, ``basal_cal``, ``elevation_m`` and ``elapsed_min``.
    ``tracker/importing.build_auto_cardio_payload`` reads them off these
    same rows to build the monthly cardio rows, and
    ``upsert_workout_sessions`` ignores keys it does not recognise. The
    retired importer carried the same pass-throughs; dropping them left
    every new monthly cardio row with a blank Total Cal, Elevation and
    Elapsed.
    """
    meta = payload["meta"]
    rows: list[dict] = []
    for workout in (payload.get("activity") or {}).get("workouts") or []:
        row = _session_identity_and_common(workout, meta, since, until)
        if row is None:
            continue
        row["apple_type"] = hek_canonical_type(
            workout.get("type") or "", workout.get("isIndoor")
        )
        row["source"] = normalize_source(workout.get("source"))
        for key, field in (
            ("averageHeartRateBpm", "avg_hr"),
            ("maxHeartRateBpm", "max_hr"),
            ("minHeartRateBpm", "min_hr"),
            ("activeEnergyKcal", "active_cal"),
            ("totalEnergyKcal", "total_cal"),
            ("basalEnergyKcal", "basal_cal"),
        ):
            if workout.get(key) is not None:
                row[field] = workout[key]
        # A zero or negative ascent means the export carried no elevation
        # for this workout, not a measured flat route. Same distinction
        # ``distance_km`` makes above.
        elevation = workout.get("elevationAscendedM")
        if elevation is not None and elevation > 0:
            row["elevation_m"] = elevation
        # Elapsed is the wall-clock span, which this export distinguishes
        # from ``durationSec``: duration excludes paused time, the span
        # does not. The retired importer had no second signal and set
        # elapsed equal to duration; here the two differ on 161 of the 698
        # workouts in the reference export, so this is a small improvement
        # rather than a reproduction. Only written when both ends parsed --
        # an end-less workout gets no span rather than a guessed one.
        raw_start, raw_end = workout.get("start"), workout.get("end")
        if raw_start and raw_end:
            span = (hek_time.parse_stamp(raw_end, meta)
                    - hek_time.parse_stamp(raw_start, meta))
            row["elapsed_min"] = round(span.total_seconds() / 60.0, 1)
        row["incidental"] = (
            "Walking" in row["apple_type"]
            and row.get("duration_min") is not None
            and row["duration_min"] < INCIDENTAL_WALK_MAX_MIN
        )
        rows.append(row)
    rows.sort(key=lambda r: (r["date"], r["start"]))
    return rows


# ------------------------------------------------------------------ swims

SWIM_TYPES = frozenset({"Swimming"})


def build_swim_payload(payload: dict,
                       since: date | None,
                       until: date | None) -> list[dict]:
    """Rows for ``upsert_swim_workouts``.

    Lap count comes from ``events[].type == "lap"`` and was verified against
    the tracker's historical per-lap files: identical on all 17 swims that
    carry laps. The events themselves hold only ``{start, end, type}``, so
    stroke style, SWOLF, pool length, stroke count and water temperature
    have no source in this format and are left unset rather than guessed —
    sparse merge then preserves whatever history already holds.

    ``Location`` is left unset too. ``isIndoor`` looks like it should decide
    Pool vs. Open Water, but measured against 27 real swims it disagrees
    with the stored Location on 24 of them: every swim it calls indoor
    carries a GPS route (39 to 287 points), which a pool swim does not
    produce, and the other disagreements are stored as ``Outdoor Pool``, a
    third value a two-way flag cannot express at all. This format has no
    reliable location signal, so the column is left unset and sparse merge
    preserves whatever the store already has, rather than a real import
    silently overwriting correct history with a wrong guess.
    """
    meta = payload["meta"]
    rows: list[dict] = []
    for workout in (payload.get("activity") or {}).get("workouts") or []:
        if (workout.get("type") or "") not in SWIM_TYPES:
            continue
        row = _session_identity_and_common(workout, meta, since, until)
        if row is None:
            continue

        if workout.get("averageHeartRateBpm") is not None:
            row["avg_hr"] = workout["averageHeartRateBpm"]
        if workout.get("activeEnergyKcal") is not None:
            row["active_cal"] = workout["activeEnergyKcal"]

        laps = sum(1 for e in workout.get("events") or [] if e.get("type") == "lap")
        if laps:
            row["laps"] = laps

        rows.append(row)
    rows.sort(key=lambda r: (r["date"], r["start"]))
    return rows


# --------------------------------------------------------- orchestration

EXPORT_GLOB = "health-export-json-*.json"


class EmptyImportError(RuntimeError):
    """The export parsed cleanly but produced nothing.

    Almost always the wrong date window rather than a broken file, so it is
    an error the caller surfaces rather than a silent no-op.
    """


# Every year-less stamp in the file is resolved against these, and the
# complete-day window is derived from them. A missing one used to escape
# ``main()`` as a raw KeyError traceback; ``/log`` promises one clear line.
REQUIRED_META_KEYS = ("timeZone", "rangeStart", "rangeEnd", "exportedAt")


def read_export(path: Path) -> dict:
    payload = json.loads(path.read_text())
    meta = payload.get("meta") or {}
    if meta.get("schemaVersion") != 1:
        raise ValueError(
            f"{path.name}: unsupported schemaVersion "
            f"{meta.get('schemaVersion')!r}; this reader handles 1"
        )
    for key in REQUIRED_META_KEYS:
        if not meta.get(key):
            raise ValueError(
                f"{path.name}: meta is missing required key {key!r}; "
                f"the export is incomplete and cannot be read safely"
            )
    return payload


def resolve_export(pattern: str | None) -> Path | None:
    """Newest matching export, by modification time."""
    if pattern:
        p = Path(pattern)
        if p.exists():
            return p
        matches = sorted((Path(m) for m in glob.glob(pattern)),
                         key=lambda x: x.stat().st_mtime, reverse=True)
        return matches[0] if matches else None
    matches = sorted(WORKOUT_TRACKER_ROOT.glob(EXPORT_GLOB),
                     key=lambda x: x.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def import_export(person: str,
                  export_path: Path,
                  since: date | None,
                  until: date | None,
                  *,
                  allow_past_months: bool = False,
                  dry_run: bool = False,
                  keep_export: bool = False) -> list[str]:
    """Parse one export and write every store it feeds. One import, one commit."""
    payload = read_export(export_path)

    health = build_health_payload(payload, since, until)
    headline = sleep_headline_rows(payload, since, until)
    nights = build_sleep_payload(payload, since, until)
    workouts = build_workout_payload(payload, since, until)
    swims = build_swim_payload(payload, since, until)

    if dry_run:
        return [
            f"Dry run: {export_path.name}",
            f"  range {payload['meta']['rangeStart']} .. {payload['meta']['rangeEnd']}",
            f"  health metric days: {len(health)}",
            f"  sleep nights:       {len(nights)}",
            f"  workouts:           {len(workouts)}",
            f"  swim workouts:      {len(swims)}",
            "  nothing written",
        ]

    if not health and not nights:
        raise EmptyImportError(
            f"{export_path.name} yielded 0 health metric dates and 0 sleep "
            f"nights in the selected window; nothing was written"
        )

    out: list[str] = []
    profile, created = ensure_profile(person, default_source=SOURCE_NAME,
                                      default_auto_cardio=True)
    if created:
        out.append(f"Profile: created (source={SOURCE_NAME}, auto_cardio=true)")
    if profile.get("source") != SOURCE_NAME:
        write_profile(person, source=SOURCE_NAME)
        out.append(f"Profile: source {profile.get('source') or 'unset'} -> {SOURCE_NAME}")
        profile = read_profile(person)

    out.extend(upsert_health_metrics(person, health))
    out.extend(upsert_health_metrics(person, headline))
    out.extend(upsert_sleep_nights(person, nights))
    if swims:
        out.extend(upsert_swim_workouts(person, swims))
    out.extend(upsert_workout_sessions(person, workouts))

    if profile.get("auto_cardio"):
        out.extend(upsert_monthly_cardio(
            person,
            build_auto_cardio_payload(
                workouts,
                eligible_types=CARDIO_AUTOLOG_TYPES,
                type_to_exercise=APPLE_TO_TRACKER_EXERCISE,
            ),
            allow_past_months=allow_past_months,
        ))
    else:
        out.append("Auto-cardio: skipped (Profile.auto_cardio=false)")

    sessions, warnings = cluster_strength_sessions(workouts)
    if warnings:
        out.append("Strength clustering warnings:")
        out.extend(warnings)
    out.extend(upsert_monthly_strength_session(
        person, sessions, allow_past_months=allow_past_months,
    ))

    if not keep_export:
        try:
            export_path.unlink()
            out.append(f"Deleted source export: {export_path.name}")
        except OSError as e:
            out.append(f"WARN: could not delete {export_path.name}: {e}")

    sha = commit_data(person, f"import: {export_path.name}")
    if sha:
        out.append(f"Committed {person} data: {sha}")
    return out


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--person", required=True, help="Tracker owner, e.g. <Person>.")
    ap.add_argument("--export", default=None,
                    help=f"Export path or glob. Defaults to the newest {EXPORT_GLOB}.")
    ap.add_argument("--since", default=None, type=_parse_date,
                    help="Start date, YYYY-MM-DD. Default: the export's own range.")
    ap.add_argument("--until", default=None, type=_parse_date,
                    help="End date, YYYY-MM-DD. Default: the export's own range.")
    ap.add_argument("--allow-past-months", action="store_true",
                    help="Allow monthly backfill into past YYYY.MM files.")
    ap.add_argument("--keep-export", action="store_true",
                    help="Keep the file instead of deleting it after a successful import.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and summarize; do not write anything.")
    args = ap.parse_args()

    export_path = resolve_export(args.export)
    if export_path is None or not export_path.exists():
        print(f"ERROR: Health Export Kit file not found: {args.export or EXPORT_GLOB}",
              file=sys.stderr)
        return 1

    try:
        lines = import_export(
            args.person, export_path, args.since, args.until,
            allow_past_months=args.allow_past_months,
            dry_run=args.dry_run, keep_export=args.keep_export,
        )
    except EmptyImportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except (hek_time.ClockGuardError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
