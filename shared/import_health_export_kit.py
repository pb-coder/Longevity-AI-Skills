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
