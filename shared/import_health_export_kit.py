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

from datetime import date, timedelta

from shared import hek_time

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
            (s.get("vitals") or {}).get("respiratoryRate", {}).get("avg")
            for s in sessions
        ]
        resp = [v for v in resp if v is not None]
        if resp:
            row["resp_rate"] = round(sum(resp) / len(resp), 2)
        rows.append(row)
    return rows


# --------------------------------------------------------------- workouts

from shared.apple_workout_types import hek_canonical_type  # noqa: E402


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


def build_workout_payload(payload: dict,
                          since: date | None,
                          until: date | None) -> list[dict]:
    """Rows for ``upsert_workout_sessions``, one per workout."""
    meta = payload["meta"]
    rows: list[dict] = []
    for workout in (payload.get("activity") or {}).get("workouts") or []:
        raw_start = workout.get("start")
        if not raw_start:
            continue  # unusable without an identity
        start = hek_time.parse_stamp(raw_start, meta)
        if not _in_window(start.date(), since, until):
            continue
        row = {
            "date": start.date().isoformat(),
            "start": start.strftime("%H:%M:%S"),
            "apple_type": hek_canonical_type(
                workout.get("type") or "", workout.get("isIndoor")
            ),
            "source": normalize_source(workout.get("source")),
        }
        raw_end = workout.get("end")
        if raw_end:
            row["end"] = hek_time.parse_stamp(raw_end, meta).strftime("%H:%M:%S")
        duration = workout.get("durationSec")
        if duration is not None:
            row["duration_min"] = round(duration / 60.0, 1)
        for key, field in (
            ("averageHeartRateBpm", "avg_hr"),
            ("maxHeartRateBpm", "max_hr"),
            ("minHeartRateBpm", "min_hr"),
            ("activeEnergyKcal", "active_cal"),
        ):
            if workout.get(key) is not None:
                row[field] = workout[key]
        # Zero distance means the workout carried none, not that it covered
        # no ground. The retired importer made the same distinction.
        distance = workout.get("distanceKm")
        if distance:
            row["distance_km"] = distance
        rows.append(row)
    rows.sort(key=lambda r: (r["date"], r["start"]))
    return rows
