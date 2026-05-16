"""Import Apple Health export into the tracker CSV store.

Streams the zipped ``Export.xml`` directly with stdlib ``zipfile`` +
``xml.etree.iterparse`` (no extraction step, ~150 MB peak RAM on a 540 MB
unzipped XML). Aggregates per-day Tier 1+2 metrics into
``<person>/data/health_metrics.csv`` and one row per ``Workout`` element
into ``<person>/data/workout_sessions.csv``. Auto-cardio rows flow into
the matching ``<person>/data/monthly/YYYY.MM.csv`` via the pure-CSV
``upsert_monthly_cardio`` in ``monthly_csv.py``. For swim workouts
(XML only), per-swim aggregates land in
``<person>/data/swimming/YYYY.MM.workouts.csv`` and per-lap detail in
``YYYY.MM.laps.csv`` (per-month files). For sleep (XML only), per-night
architecture (all 6 stages + Time in Bed + Sleep Efficiency + N Segments
+ first/last segment clock times) lands in
``<person>/data/sleep/YYYY.MM.nights.csv``. Sparse-merge upserts protect
existing data on re-run; idempotent.

The export file is **archived to ``<root>/.processed/`` on success** —
the CSVs are the persistent record; the archive keeps a forensic trail
if a downstream bug damages the CSVs. Re-export from iPhone if you need
to backfill.

Usage:
    python3 import_apple_health.py --person Nihad \\
        [--since YYYY-MM-DD]      # default: 6 months back from today
        [--allow-past-months]     # bypass the current-month auto-cardio gate
        [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILLS_ROOT))
sys.path.insert(0, str(SKILLS_ROOT / "shared"))
from tracker import TrackerContext  # noqa: E402
from tracker.importing import build_auto_cardio_payload  # noqa: E402
from monthly_csv import (  # noqa: E402
    upsert_monthly_cardio,
    upsert_monthly_strength_session,
)
from csv_store import (  # noqa: E402
    ensure_profile,
    read_profile,
    upsert_health_metrics,
    upsert_sleep_nights,
    upsert_swim_laps,
    upsert_swim_workouts,
    upsert_workout_sessions,
)
from person_paths import (  # noqa: E402
    WORKOUT_TRACKER_ROOT,
    archive_processed_export,
    person_dir,
)
from apple_workout_types import (  # noqa: E402
    APPLE_TO_TRACKER_EXERCISE,
    CARDIO_AUTOLOG_TYPES,
    HK_SWIMMING_STROKE_STYLE,
)

# ---------- type identifiers we care about ----------
# Tier 1 (must-have) and Tier 2 (cheap and useful). Anything else seen in
# the export is silently skipped — see the plan's "What gets ingested" for
# the rationale on what's left out (StepCount/ActiveEnergy/BasalEnergy:
# noisy; gait + walking steadiness: not actionable; FlightsClimbed: not
# actionable; ECG / workout-routes: out of scope).
WANTED_RECORD_TYPES = {
    "HKQuantityTypeIdentifierVO2Max",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
    "HKQuantityTypeIdentifierRestingHeartRate",
    "HKQuantityTypeIdentifierWalkingHeartRateAverage",
    "HKQuantityTypeIdentifierHeartRateRecoveryOneMinute",
    "HKQuantityTypeIdentifierRespiratoryRate",
    "HKQuantityTypeIdentifierAppleSleepingWristTemperature",
    "HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances",
    "HKQuantityTypeIdentifierAppleExerciseTime",
    "HKQuantityTypeIdentifierBodyMass",
    "HKCategoryTypeIdentifierSleepAnalysis",
}

# Sleep stages we count toward "asleep total" — Apple's "InBed" and
# "Awake" are excluded so the total reflects time genuinely asleep.
SLEEP_ASLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisAsleepCore",
    "HKCategoryValueSleepAnalysisAsleepDeep",
    "HKCategoryValueSleepAnalysisAsleepREM",
    "HKCategoryValueSleepAnalysisAsleepUnspecified",
}
SLEEP_CORE_VALUE   = "HKCategoryValueSleepAnalysisAsleepCore"
SLEEP_DEEP_VALUE   = "HKCategoryValueSleepAnalysisAsleepDeep"
SLEEP_REM_VALUE    = "HKCategoryValueSleepAnalysisAsleepREM"
SLEEP_UNSPEC_VALUE = "HKCategoryValueSleepAnalysisAsleepUnspecified"
SLEEP_AWAKE_VALUE  = "HKCategoryValueSleepAnalysisAwake"
SLEEP_IN_BED_VALUE = "HKCategoryValueSleepAnalysisInBed"

# Every stage that contributes a per-segment count to the per-night
# fragmentation tally + first/last-segment clock-time accumulator.
# (Asleep* stages + Awake; InBed is the overarching span and is
# tracked separately, not as a segment.)
SLEEP_SEGMENT_VALUES = SLEEP_ASLEEP_VALUES | {SLEEP_AWAKE_VALUE}

# Walking sessions shorter than this get the "incidental" tag. The coach
# filters these out when reasoning about training load — a 5-minute stroll
# to the bakery is not a Zone 2 session.
INCIDENTAL_WALK_MAX_MIN = 15.0

# Apple emits the activity type as e.g. ``HKWorkoutActivityTypeRunning``;
# strip that prefix for human readability in the sheet.
WORKOUT_TYPE_PREFIX = "HKWorkoutActivityType"

# Tags we recognize on per-workout HR statistics so we can set avg/max/min.
HR_TYPE = "HKQuantityTypeIdentifierHeartRate"
ACTIVE_ENERGY_TYPE = "HKQuantityTypeIdentifierActiveEnergyBurned"
BASAL_ENERGY_TYPE = "HKQuantityTypeIdentifierBasalEnergyBurned"
DISTANCE_WR_TYPE = "HKQuantityTypeIdentifierDistanceWalkingRunning"
DISTANCE_CYCLE_TYPE = "HKQuantityTypeIdentifierDistanceCycling"
DISTANCE_SWIM_TYPE = "HKQuantityTypeIdentifierDistanceSwimming"
SWIM_STROKE_COUNT_TYPE = "HKQuantityTypeIdentifierSwimmingStrokeCount"
WATER_TEMP_TYPE = "HKQuantityTypeIdentifierWaterTemperature"

# Apple's <WorkoutStatistics> tag carries a per-record `unit` attribute.
# Walks/runs/cycling typically arrive in km, but swimming is recorded in
# metres by default (a 25 m pool length × 22 laps → sum="550" unit="m").
# Read the unit and convert; never assume km. Unknown units are dropped
# with a warning rather than silently mis-stored.
DISTANCE_UNIT_TO_KM = {
    "km":  1.0,
    "m":   0.001,
    "mi":  1.609344,
    "yd":  0.0009144,
    "ft":  0.0003048,
}

# Marker that the device attribute came from a fitness machine via GymKit
# (Matrix treadmill, Technogym bike, etc.). Apple wraps these in a
# `<<HKDevice ...>` blob that always contains
# `model:com.apple.health.fitnessmachinemodel.<kind>` — that substring is
# the reliable cross-brand signal.
FITNESS_MACHINE_DEVICE_MARKER = "fitnessmachinemodel"


# ---------- date parsing ----------
# Apple emits "YYYY-MM-DD HH:MM:SS +ZZZZ" in the user's local TZ. We don't
# need TZ math — the date and time-of-day already reflect when the user
# experienced the event.
_DT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})")


def parse_apple_dt(s):
    """Return (date_str, datetime) from an Apple Health timestamp.

    Drops the timezone offset — we treat all timestamps as wall-clock
    local time, which is what the user sees in the Health app.
    """
    if not s:
        return None, None
    m = _DT_RE.match(s)
    if not m:
        return None, None
    d = m.group(1)
    dt = datetime(int(d[:4]), int(d[5:7]), int(d[8:10]),
                  int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return d, dt


def hhmm(dt):
    """Return ``HH:MM:SS`` for a datetime. Seconds are included so the
    (date, start) dedupe key can distinguish two workouts that begin in
    the same minute (Apple paused-and-resumed sessions can do this)."""
    if dt is None:
        return None
    return f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"


def to_float(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- per-day aggregator ----------
class DayAggregator:
    """Collects per-day metric values during the streaming pass.

    For metrics that repeat many times in a day (HRV, RespRate), buckets
    of (sum, count) feed a final mean. For "latest of day" metrics
    (BodyMass, RestingHR, WalkingHR, VO2max, WristTemp, SleepBreathDist),
    keeps the value with the most recent ``startDate``. For "max of day"
    (HRRecovery1min), keeps the largest value.

    Sleep is segment-based: each segment contributes to its wake-up date
    (the date of its ``endDate``). Deep + REM are tracked separately;
    Total sums all "Asleep*" stages.
    """

    def __init__(self):
        self.bodyweight_kg     = {}  # date -> (latest_dt, value)
        self.vo2max            = {}
        self.resting_hr        = {}
        self.walking_hr        = {}
        self.hr_recovery_1min  = defaultdict(float)  # max of day
        self.hrv_sdnn_acc      = defaultdict(lambda: [0.0, 0])  # date -> [sum, count]
        self.resp_rate_acc     = defaultdict(lambda: [0.0, 0])
        self.wrist_temp_c      = {}  # latest of day
        self.sleep_breath      = {}
        self.exercise_min      = defaultdict(float)  # sum within a day
        # sleep buckets keyed by wake-up date — every stage Apple emits.
        # Total = sum of all Asleep* stages (Core + Deep + REM + Unspec).
        # Awake = wake-after-sleep-onset; InBed = full bed span.
        self.sleep_total_min   = defaultdict(float)
        self.sleep_core_min    = defaultdict(float)
        self.sleep_deep_min    = defaultdict(float)
        self.sleep_rem_min     = defaultdict(float)
        self.sleep_unspec_min  = defaultdict(float)
        self.sleep_awake_min   = defaultdict(float)
        self.sleep_in_bed_min  = defaultdict(float)
        # Per-night segment metadata for the sleep nights store.
        self.sleep_n_segments      = defaultdict(int)
        self.sleep_first_seg_start = {}   # date -> earliest segment dt_start
        self.sleep_last_seg_end    = {}   # date -> latest segment dt_end

        # Dispatch table: record type → bound handler. Each handler takes
        # (attrib, d_start, dt_start) — d_start/dt_start are pre-parsed by
        # the streaming layer to avoid a redundant ``parse_apple_dt`` call
        # per record. Handlers that need the end date parse it lazily, since
        # it's only relevant for wrist temp / sleep breath / sleep analysis
        # — a tiny fraction of total records.
        self._handlers = {
            "HKQuantityTypeIdentifierBodyMass":              self._h_bodyweight,
            "HKQuantityTypeIdentifierVO2Max":                self._h_vo2max,
            "HKQuantityTypeIdentifierRestingHeartRate":      self._h_resting_hr,
            "HKQuantityTypeIdentifierWalkingHeartRateAverage": self._h_walking_hr,
            "HKQuantityTypeIdentifierHeartRateRecoveryOneMinute": self._h_hr_recovery,
            "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": self._h_hrv,
            "HKQuantityTypeIdentifierRespiratoryRate":       self._h_resp_rate,
            "HKQuantityTypeIdentifierAppleSleepingWristTemperature": self._h_wrist_temp,
            "HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances": self._h_sleep_breath,
            "HKQuantityTypeIdentifierAppleExerciseTime":     self._h_exercise_min,
            "HKCategoryTypeIdentifierSleepAnalysis":         self._h_sleep,
        }

    def _set_latest(self, store, d, dt, value):
        cur = store.get(d)
        if cur is None or dt > cur[0]:
            store[d] = (dt, value)

    def add_record(self, attrib, d_start, dt_start):
        """Route a record by type. ``d_start`` / ``dt_start`` are pre-parsed
        by the streaming layer to avoid a redundant regex match per record.
        """
        if d_start is None:
            return
        handler = self._handlers.get(attrib.get("type", ""))
        if handler is not None:
            handler(attrib, d_start, dt_start)

    # ---- handlers (one-liners that pull from attrib + cached dates) ----
    def _h_bodyweight(self, attrib, d, dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self._set_latest(self.bodyweight_kg, d, dt, v)

    def _h_vo2max(self, attrib, d, dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self._set_latest(self.vo2max, d, dt, v)

    def _h_resting_hr(self, attrib, d, dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self._set_latest(self.resting_hr, d, dt, v)

    def _h_walking_hr(self, attrib, d, dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self._set_latest(self.walking_hr, d, dt, v)

    def _h_hr_recovery(self, attrib, d, _dt):
        v = to_float(attrib.get("value"))
        if v is not None and v > self.hr_recovery_1min.get(d, 0.0):
            self.hr_recovery_1min[d] = v

    def _h_hrv(self, attrib, d, _dt):
        v = to_float(attrib.get("value"))
        if v is not None:
            self.hrv_sdnn_acc[d][0] += v
            self.hrv_sdnn_acc[d][1] += 1

    def _h_resp_rate(self, attrib, d, _dt):
        # Apple records resp rate primarily during sleep on Apple Watch, so
        # a daily mean is close to a sleep-time mean without filtering.
        v = to_float(attrib.get("value"))
        if v is not None:
            self.resp_rate_acc[d][0] += v
            self.resp_rate_acc[d][1] += 1

    def _h_wrist_temp(self, attrib, d, dt):
        # Apple emits one nightly value; bucket by wake-up date (endDate).
        v = to_float(attrib.get("value"))
        if v is None:
            return
        d_end, dt_end = parse_apple_dt(attrib.get("endDate"))
        bucket = d_end or d
        self._set_latest(self.wrist_temp_c, bucket, dt_end or dt, v)

    def _h_sleep_breath(self, attrib, d, dt):
        v = to_float(attrib.get("value"))
        if v is None:
            return
        d_end, dt_end = parse_apple_dt(attrib.get("endDate"))
        bucket = d_end or d
        self._set_latest(self.sleep_breath, bucket, dt_end or dt, v)

    def _h_exercise_min(self, attrib, d, _dt):
        # Apple emits many short records throughout the day; sum to get
        # the daily total exercise minutes.
        v = to_float(attrib.get("value"))
        if v is not None:
            self.exercise_min[d] += v

    def _h_sleep(self, attrib, d_start, dt_start):
        d_end, dt_end = parse_apple_dt(attrib.get("endDate"))
        self._add_sleep(attrib.get("value"), dt_start, dt_end, d_start, d_end)

    def _add_sleep(self, value, dt_start, dt_end, d_start, d_end):
        if value is None or dt_start is None or dt_end is None:
            return
        minutes = (dt_end - dt_start).total_seconds() / 60.0
        if minutes <= 0:
            return
        # Bucket by recovery-night date: the date of the morning the
        # user wakes up after this segment. Apple emits ``endDate`` in
        # local time, so a segment that ends in the early morning
        # (before ~18:00) belongs to that morning's recovery day —
        # ``bucket = d_end``. But a segment that ends in the evening
        # (≥18:00) is the START of the NEXT recovery night — bedtime,
        # not wake-up — so it buckets to ``d_end + 1``. Without this
        # shift, a sleep period that starts at 23:00 and ends at 23:42
        # on the same evening would be added to the wrong night's
        # total alongside that morning's actual sleep. Apple's own
        # daily summary uses this same "recovery night" convention.
        from datetime import timedelta
        if dt_end.hour >= 18:
            shifted = dt_end.date() + timedelta(days=1)
            bucket = shifted.isoformat()
        else:
            bucket = d_end
        if value == SLEEP_IN_BED_VALUE:
            # InBed is the overarching span; doesn't contribute to Total
            # and isn't counted as a segment for fragmentation.
            self.sleep_in_bed_min[bucket] += minutes
            return
        if value == SLEEP_AWAKE_VALUE:
            self.sleep_awake_min[bucket] += minutes
        elif value in SLEEP_ASLEEP_VALUES:
            self.sleep_total_min[bucket] += minutes
            if value == SLEEP_CORE_VALUE:
                self.sleep_core_min[bucket] += minutes
            elif value == SLEEP_DEEP_VALUE:
                self.sleep_deep_min[bucket] += minutes
            elif value == SLEEP_REM_VALUE:
                self.sleep_rem_min[bucket] += minutes
            elif value == SLEEP_UNSPEC_VALUE:
                self.sleep_unspec_min[bucket] += minutes
        else:
            return
        # Fragmentation count includes Asleep* + Awake (every segment Apple
        # writes to the sleep period). First/last segment tracking restricts
        # to Asleep* — those mark the user's actual sleep window. Pre-bed or
        # post-wake Awake segments would otherwise drag the bedtime /
        # waketime clock-time stat by hours.
        self.sleep_n_segments[bucket] += 1
        if value in SLEEP_ASLEEP_VALUES:
            cur_start = self.sleep_first_seg_start.get(bucket)
            if cur_start is None or dt_start < cur_start:
                self.sleep_first_seg_start[bucket] = dt_start
            cur_end = self.sleep_last_seg_end.get(bucket)
            if cur_end is None or dt_end > cur_end:
                self.sleep_last_seg_end[bucket] = dt_end

    def emit(self, since_date):
        """Yield per-date Health Metrics dicts (≥ since_date)."""
        all_dates = set()
        for store in (self.bodyweight_kg, self.vo2max, self.resting_hr,
                      self.walking_hr, self.wrist_temp_c, self.sleep_breath):
            all_dates.update(store.keys())
        all_dates.update(self.hr_recovery_1min.keys())
        all_dates.update(self.hrv_sdnn_acc.keys())
        all_dates.update(self.resp_rate_acc.keys())
        all_dates.update(self.exercise_min.keys())
        all_dates.update(self.sleep_total_min.keys())
        all_dates.update(self.sleep_in_bed_min.keys())

        cutoff = since_date.isoformat() if since_date else None
        for d in sorted(all_dates):
            if cutoff and d < cutoff:
                continue

            def lat(store):
                tup = store.get(d)
                return tup[1] if tup else None

            hrv_sum, hrv_n = self.hrv_sdnn_acc.get(d, [0.0, 0])
            hrv = round(hrv_sum / hrv_n, 2) if hrv_n else None

            rr_sum, rr_n = self.resp_rate_acc.get(d, [0.0, 0])
            rr = round(rr_sum / rr_n, 2) if rr_n else None

            sleep_total_min  = self.sleep_total_min.get(d, 0.0)
            sleep_deep_min   = self.sleep_deep_min.get(d, 0.0)
            sleep_rem_min    = self.sleep_rem_min.get(d, 0.0)
            sleep_in_bed_min = self.sleep_in_bed_min.get(d, 0.0)

            yield {
                "date": d,
                "bodyweight_kg":     round(lat(self.bodyweight_kg), 2) if lat(self.bodyweight_kg) is not None else None,
                "vo2max":            round(lat(self.vo2max), 2) if lat(self.vo2max) is not None else None,
                "resting_hr":        round(lat(self.resting_hr), 1) if lat(self.resting_hr) is not None else None,
                "hrv_sdnn":          hrv,
                "walking_hr":        round(lat(self.walking_hr), 1) if lat(self.walking_hr) is not None else None,
                "hr_recovery_1min":  round(self.hr_recovery_1min[d], 1) if d in self.hr_recovery_1min else None,
                "sleep_total_h":     round(sleep_total_min / 60.0, 2) if sleep_total_min else None,
                "sleep_deep_h":      round(sleep_deep_min / 60.0, 2) if sleep_deep_min else None,
                "sleep_rem_h":       round(sleep_rem_min / 60.0, 2) if sleep_rem_min else None,
                "time_in_bed_h":     round(sleep_in_bed_min / 60.0, 2) if sleep_in_bed_min else None,
                "resp_rate":         rr,
                "wrist_temp_c":      round(lat(self.wrist_temp_c), 3) if lat(self.wrist_temp_c) is not None else None,
                "sleep_breath_dist": round(lat(self.sleep_breath), 4) if lat(self.sleep_breath) is not None else None,
                "exercise_min":      round(self.exercise_min[d], 1) if d in self.exercise_min else None,
            }

    def emit_sleep_nights(self, since_date):
        """Yield per-wake-up-date Sleep Nights dicts (≥ since_date).

        One row per date whenever ANY sleep stage (Asleep*, Awake, or
        InBed) was observed for that date. Each dict carries every
        stage duration, Time in Bed, derived Sleep Efficiency, the
        fragmentation count (N Segments — number of Asleep*/Awake
        segments contributing), and the first/last segment clock
        times (bedtime / wake-up signals for schedule consistency).
        """
        all_dates = set()
        all_dates.update(self.sleep_total_min.keys())
        all_dates.update(self.sleep_in_bed_min.keys())
        all_dates.update(self.sleep_awake_min.keys())

        cutoff = since_date.isoformat() if since_date else None
        for d in sorted(all_dates):
            if cutoff and d < cutoff:
                continue

            total_min  = self.sleep_total_min.get(d, 0.0)
            core_min   = self.sleep_core_min.get(d, 0.0)
            deep_min   = self.sleep_deep_min.get(d, 0.0)
            rem_min    = self.sleep_rem_min.get(d, 0.0)
            unspec_min = self.sleep_unspec_min.get(d, 0.0)
            awake_min  = self.sleep_awake_min.get(d, 0.0)
            in_bed_min = self.sleep_in_bed_min.get(d, 0.0)

            total_h     = round(total_min  / 60.0, 2) if total_min  else None
            in_bed_h    = round(in_bed_min / 60.0, 2) if in_bed_min else None
            efficiency  = (
                round(total_h / in_bed_h * 100.0, 1)
                if total_h is not None and in_bed_h is not None and in_bed_h > 0
                else None
            )

            first_seg = self.sleep_first_seg_start.get(d)
            last_seg  = self.sleep_last_seg_end.get(d)
            n_seg = self.sleep_n_segments.get(d, 0) or None

            yield {
                "date": d,
                "total_h":              total_h,
                "core_h":               round(core_min   / 60.0, 2) if core_min   else None,
                "deep_h":               round(deep_min   / 60.0, 2) if deep_min   else None,
                "rem_h":                round(rem_min    / 60.0, 2) if rem_min    else None,
                "unspecified_h":        round(unspec_min / 60.0, 2) if unspec_min else None,
                "awake_h":              round(awake_min  / 60.0, 2) if awake_min  else None,
                "time_in_bed_h":        in_bed_h,
                "efficiency_pct":       efficiency,
                "n_segments":           n_seg,
                "first_segment_start":  first_seg.strftime("%Y-%m-%d %H:%M:%S") if first_seg else None,
                "last_segment_end":     last_seg.strftime("%Y-%m-%d %H:%M:%S")  if last_seg  else None,
            }


# ---------- workout extraction ----------
def extract_workout(elem, since_date):
    """Build one Workout Sessions row from an Apple ``Workout`` element.

    Returns None if the workout is older than ``since_date`` or its
    ``startDate`` can't be parsed.
    """
    attrib = elem.attrib
    d_start, dt_start = parse_apple_dt(attrib.get("startDate"))
    d_end, dt_end = parse_apple_dt(attrib.get("endDate"))
    if d_start is None or dt_start is None:
        return None
    if since_date and d_start < since_date.isoformat():
        return None

    duration_unit = attrib.get("durationUnit", "min")
    duration = to_float(attrib.get("duration"))
    if duration is not None and duration_unit != "min":
        # Apple sometimes emits "sec"; convert to minutes for consistency.
        if duration_unit == "sec":
            duration = duration / 60.0
        elif duration_unit == "hr":
            duration = duration * 60.0

    raw_type = attrib.get("workoutActivityType", "")
    apple_type = raw_type[len(WORKOUT_TYPE_PREFIX):] if raw_type.startswith(WORKOUT_TYPE_PREFIX) else raw_type

    avg_hr = max_hr = min_hr = active_cal = basal_cal = distance_km = None
    elevation_m: float | None = None
    indoor = False
    laps: int = 0
    # Swim-only extras. Captured for every workout to keep the loop simple,
    # but the importer only writes them to swimming/YYYY.MM.workouts.csv
    # when the canonical activity type is "Swimming".
    pool_length_m: int | None = None
    stroke_count_total: int | None = None
    water_temp_c: float | None = None
    swimming_location_type: str | None = None  # "1" pool, "2" open water
    indoor_workout_meta: str | None = None      # "0" outdoor pool, "1" indoor
    swim_lap_events: list[dict] = []
    for child in elem:
        if child.tag == "MetadataEntry":
            # Apple uses the same activity-type enum for indoor + outdoor
            # variants of running / cycling / walking; the
            # ``HKIndoorWorkout`` metadata flag is the only disambiguator.
            # Read it here so the canonical name can be specialised below.
            key = child.attrib.get("key")
            val = child.attrib.get("value")
            if key == "HKIndoorWorkout":
                indoor = val == "1"
                indoor_workout_meta = val
            elif key == "HKElevationAscended" and val is not None:
                # Apple reports elevation in cm with a unit suffix (e.g.
                # "11589 cm"). Strip the unit and convert to metres.
                token = val.split()[0] if isinstance(val, str) else val
                cm = to_float(token)
                if cm is not None:
                    elevation_m = cm / 100.0
            elif key == "HKLapLength" and val is not None:
                # Format: "25 m" or "50 m". Token-split + float for safety.
                token = val.split()[0] if isinstance(val, str) else val
                f = to_float(token)
                if f is not None:
                    pool_length_m = int(round(f))
            elif key == "HKSwimmingLocationType" and val is not None:
                swimming_location_type = str(val).strip()
            continue
        if child.tag == "WorkoutEvent":
            # Lap count: Apple emits one ``<WorkoutEvent type="HKWorkoutEventTypeLap"/>``
            # per pool length on swims (and per manual lap press on runs).
            # We count them generically; the consumer only writes the
            # value to the Laps column on swim rows.
            if child.attrib.get("type") == "HKWorkoutEventTypeLap":
                laps += 1
                # Capture per-lap detail for swimming/YYYY.MM.laps.csv. Stroke style
                # and SWOLF are nested MetadataEntry children of the lap
                # event. Filter on lap events ONLY — Apple also emits
                # HKWorkoutEventTypeSegment events with SWOLF that would
                # double-count if we let them in.
                lap_dur_min = to_float(child.attrib.get("duration"))
                stroke_raw: int | None = None
                swolf_v: float | None = None
                for sub in child:
                    if sub.tag != "MetadataEntry":
                        continue
                    sk = sub.attrib.get("key")
                    sv = sub.attrib.get("value")
                    if sk == "HKSwimmingStrokeStyle" and sv is not None:
                        try:
                            stroke_raw = int(str(sv).strip())
                        except (TypeError, ValueError):
                            stroke_raw = None
                    elif sk == "HKSWOLFScore" and sv is not None:
                        swolf_v = to_float(sv)
                swim_lap_events.append({
                    "lap_num": laps,
                    "stroke_raw": stroke_raw,
                    "duration_sec": round(lap_dur_min * 60.0, 2)
                                    if lap_dur_min is not None else None,
                    "swolf": round(swolf_v, 2) if swolf_v is not None else None,
                })
            continue
        if child.tag != "WorkoutStatistics":
            continue
        a = child.attrib
        ctype = a.get("type", "")
        if ctype == HR_TYPE:
            avg_hr = to_float(a.get("average"))
            max_hr = to_float(a.get("maximum"))
            min_hr = to_float(a.get("minimum"))
        elif ctype == ACTIVE_ENERGY_TYPE:
            active_cal = to_float(a.get("sum"))
        elif ctype == BASAL_ENERGY_TYPE:
            basal_cal = to_float(a.get("sum"))
        elif ctype == SWIM_STROKE_COUNT_TYPE:
            v = to_float(a.get("sum"))
            if v is not None:
                stroke_count_total = int(round(v))
        elif ctype == WATER_TEMP_TYPE:
            water_temp_c = to_float(a.get("average"))
        elif ctype in (DISTANCE_WR_TYPE, DISTANCE_CYCLE_TYPE, DISTANCE_SWIM_TYPE):
            # Use whichever distance type matches the activity (Apple
            # records the right one per workout). If multiple, the last
            # one wins — that's vanishingly rare.
            #
            # Unit handling: <WorkoutStatistics> carries a `unit` attribute
            # ("km" for runs/cycles, "m" for swims by default). Without
            # the conversion a 550 m swim was being written as 550 km.
            v = to_float(a.get("sum"))
            if v is not None:
                unit = (a.get("unit") or "km").strip().lower()
                factor = DISTANCE_UNIT_TO_KM.get(unit)
                if factor is None:
                    print(
                        f"WARN: unknown distance unit {unit!r} on "
                        f"workout {attrib.get('startDate', '?')}; skipped distance",
                        file=sys.stderr,
                    )
                else:
                    distance_km = v * factor

    # Specialise the canonical name for indoor variants. Only the three
    # types Apple records both ways are renamed; everything else (Hiking,
    # Swimming, Strength, HIIT, etc.) keeps its base name.
    if indoor and apple_type in ("Running", "Cycling", "Walking"):
        apple_type = "Indoor" + apple_type

    notes = None
    incidental = False
    if "Walking" in apple_type and duration is not None and duration < INCIDENTAL_WALK_MAX_MIN:
        # Short walk → flag as incidental via the typed column. Was
        # previously stashed as the string "incidental walk" in Notes;
        # moved to a typed flag per the 2026-05 Notes-hygiene cleanup
        # (Notes returns to user-supplied, row-unique annotations).
        incidental = True

    # Elapsed time (wall clock) = endDate - startDate. ``duration`` is
    # Apple's "Workout Time" — active movement only, paused intervals
    # excluded. The two differ when the user paused or auto-pause was on.
    elapsed_min: float | None = None
    if dt_start is not None and dt_end is not None:
        delta = (dt_end - dt_start).total_seconds() / 60.0
        if delta > 0:
            elapsed_min = round(delta, 1)

    total_cal = None
    if active_cal is not None and basal_cal is not None:
        total_cal = round(active_cal + basal_cal, 1)

    device_str = attrib.get("device") or ""
    is_machine = FITNESS_MACHINE_DEVICE_MARKER in device_str.lower()

    # Derive a single Location string from the swim metadata flags.
    # See PR2 plan / Apple Health swim primer:
    #   HKSwimmingLocationType=2 → Open Water
    #   HKIndoorWorkout=1        → Pool (indoor lane pool)
    #   HKIndoorWorkout=0 + HKSwimmingLocationType=1 → Outdoor Pool
    swim_location: str | None = None
    if apple_type == "Swimming":
        if swimming_location_type == "2":
            swim_location = "Open Water"
        elif indoor_workout_meta == "1":
            swim_location = "Pool"
        elif indoor_workout_meta == "0" and swimming_location_type == "1":
            swim_location = "Outdoor Pool"

    return {
        "date":         d_start,
        "start":        hhmm(dt_start),
        "end":          hhmm(dt_end) if dt_end else None,
        "apple_type":   apple_type,
        "duration_min": round(duration, 1) if duration is not None else None,
        "avg_hr":       round(avg_hr, 1) if avg_hr is not None else None,
        "max_hr":       int(round(max_hr)) if max_hr is not None else None,
        "min_hr":       int(round(min_hr)) if min_hr is not None else None,
        "active_cal":   round(active_cal, 1) if active_cal is not None else None,
        "basal_cal":    round(basal_cal, 1) if basal_cal is not None else None,
        "total_cal":    total_cal,
        "elevation_m":  round(elevation_m, 1) if elevation_m is not None else None,
        "elapsed_min":  elapsed_min,
        "distance_km":  round(distance_km, 3) if distance_km is not None else None,
        "laps":         laps if laps > 0 else None,
        "source":       attrib.get("sourceName"),
        "device":       device_str or None,
        "is_machine":   is_machine,
        "dt_start":     dt_start,
        "dt_end":       dt_end,
        "notes":        notes,
        "incidental":   incidental,
        # Swim-only extras (None for non-swims).
        "pool_length_m":      pool_length_m,
        "stroke_count_total": stroke_count_total,
        "water_temp_c":       round(water_temp_c, 2) if water_temp_c is not None else None,
        "swim_location":      swim_location,
        "swim_lap_events":    swim_lap_events if apple_type == "Swimming" else None,
    }


# ---------- fitness-machine dedupe ----------
def _extract_device_name(device_str: str) -> str | None:
    """Pull the ``name:<X>`` token out of an Apple HKDevice blob.

    Apple stores devices as e.g.
    ``<<HKDevice: 0x...>, name:Matrix, manufacturer:Matrix, model:com.apple.health.fitnessmachinemodel.treadmill, ...>``.
    Returns the value after ``name:`` (e.g. ``"Matrix"``) or None if the
    string doesn't follow that shape.
    """
    if not device_str:
        return None
    m = re.search(r"name:([^,>\s]+)", device_str)
    return m.group(1) if m else None


def _intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    """True if two ``[start, end]`` datetime intervals overlap.

    Strict inequality on both ends — back-to-back workouts (b_start == a_end)
    don't count as overlapping. Both intervals must have a defined start;
    a missing end falls back to start (zero-length interval).
    """
    if a_start is None or b_start is None:
        return False
    a_end = a_end or a_start
    b_end = b_end or b_start
    return (a_start < b_end) and (b_start < a_end)


def _drop_watch_overlapping_machine(workouts: list[dict]) -> tuple[list[dict], list[str]]:
    """Remove watch-only workouts that overlap a Matrix/GymKit row.

    Apple often records a generic Watch detection (no fitness-machine
    device) alongside the canonical GymKit workout when the user starts
    on a treadmill / bike at the gym. The two share an activity type
    and overlap in time; the machine row carries the accurate distance,
    segments, and lap data. The watch row is a phantom duplicate.

    Group by ``(date, apple_type)``. Within each group, if any workout
    has ``is_machine=True``, drop every non-machine workout whose time
    window overlaps a machine workout. Returns the filtered list plus
    one human-readable note per drop so the importer can surface them.

    No-op when a day has only watch-only workouts or only machine ones —
    the dedupe never collapses across activity types or dates.
    """
    notes: list[str] = []
    by_key: dict[tuple, list[dict]] = {}
    for w in workouts:
        key = (w.get("date"), w.get("apple_type"))
        by_key.setdefault(key, []).append(w)

    drop_ids = set()
    for (d, atype), group in by_key.items():
        machines = [w for w in group if w.get("is_machine")]
        watches = [w for w in group if not w.get("is_machine")]
        if not machines or not watches:
            continue
        for wch in watches:
            for mch in machines:
                if _intervals_overlap(
                    wch.get("dt_start"), wch.get("dt_end"),
                    mch.get("dt_start"), mch.get("dt_end"),
                ):
                    drop_ids.add(id(wch))
                    name = _extract_device_name(mch.get("device") or "") or "fitness machine"
                    notes.append(
                        f"Auto-cardio: dropped Watch-only {atype} on {d} "
                        f"({wch.get('duration_min')} min, "
                        f"{wch.get('distance_km')} km) — overlaps "
                        f"{name} GymKit workout"
                    )
                    break

    if drop_ids:
        kept = [w for w in workouts if id(w) not in drop_ids]
    else:
        kept = workouts
    return kept, notes


# ---------- main streaming pass ----------
# Clear ONLY top-level container tags. iterparse fires the `end` event on
# every closing tag — clearing a child element (e.g. WorkoutStatistics)
# wipes its attribs before the parent ``Workout`` end event lets us read
# it. Restricting CLEAR_TAGS to outer containers keeps the parent's
# children reachable while still bounding peak memory: Record/Workout/etc.
# get cleared once we've handled them, which transitively releases their
# children.
CLEAR_TAGS = {
    "Record", "Workout", "Correlation", "ActivitySummary",
}


def consume_apple_export(zip_path, since_date, aggregator, workout_rows):
    """Stream the export and feed records directly into ``aggregator`` and
    workouts into ``workout_rows``. Returns when the stream is exhausted.

    Two perf wins over the previous generator-based shape:

    - ``parse_apple_dt`` is called exactly once per Record (the streaming
      layer parses startDate for the ``--since`` filter, and the aggregator
      receives the cached result instead of re-parsing it inside
      ``add_record``).
    - No ``dict(elem.attrib)`` copy per Record. The aggregator reads from
      ``elem.attrib`` while the element is still alive and only ``elem.clear()``
      runs after the handler returns.

    Records older than ``since_date`` are filtered before dispatch.
    """
    cutoff = since_date.isoformat() if since_date else None
    sleep_type = "HKCategoryTypeIdentifierSleepAnalysis"
    with zipfile.ZipFile(zip_path) as z:
        inner = next((n for n in z.namelist() if n.endswith("Export.xml")), None)
        if inner is None:
            raise FileNotFoundError(f"Export.xml not found inside {zip_path}")
        with z.open(inner) as f:
            for _ev, elem in ET.iterparse(f, events=("end",)):
                tag = elem.tag
                if tag == "Record":
                    rtype = elem.attrib.get("type")
                    if rtype in WANTED_RECORD_TYPES:
                        d_start, dt_start = parse_apple_dt(elem.attrib.get("startDate"))
                        # For sleep, the wake-up date matters — let segments
                        # through regardless of where their startDate sits;
                        # the aggregator buckets by endDate.
                        if rtype == sleep_type:
                            aggregator.add_record(elem.attrib, d_start, dt_start)
                        elif d_start is None or cutoff is None or d_start >= cutoff:
                            aggregator.add_record(elem.attrib, d_start, dt_start)
                elif tag == "Workout":
                    row = extract_workout(elem, since_date)
                    if row is not None:
                        workout_rows.append(row)
                if tag in CLEAR_TAGS:
                    elem.clear()


# ---------- CLI ----------
def parse_since(s):
    if s is None:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"--since must be YYYY-MM-DD ({e})")


def default_since():
    """Six months back from today, day-of-month preserved."""
    today = date.today()
    # 6 months back → simple approximation that's not surprising at month boundaries
    return today - timedelta(days=183)


# Apple-Watch strength session bucketing for the monthly-sheet metadata
# columns. Apple often splits one human strength session into a short
# CoreTraining (warm-up/abs) followed by a longer Functional/Traditional
# block. Workouts that share a date and start within this window are
# treated as one session and summed.
STRENGTH_APPLE_TYPES: frozenset[str] = frozenset({
    "TraditionalStrengthTraining",
    "FunctionalStrengthTraining",
    "CoreTraining",
})
STRENGTH_CLUSTER_WINDOW_MIN = 90.0


def cluster_strength_sessions(workout_rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Group same-day strength workouts into one session per cluster.

    Two workouts join the same cluster when their start times are within
    ``STRENGTH_CLUSTER_WINDOW_MIN`` of each other (chained transitively).
    For each date we pick the longest-duration cluster as the canonical
    session — distant secondary clusters (a separate evening workout) are
    surfaced as warnings rather than merged.

    Returns ``(sessions, warnings)``.
    """
    by_date: dict[str, list[dict]] = {}
    for w in workout_rows:
        if (w.get("apple_type") or "") not in STRENGTH_APPLE_TYPES:
            continue
        d = str(w.get("date") or "")[:10]
        if not d:
            continue
        by_date.setdefault(d, []).append(w)

    sessions: list[dict] = []
    warnings: list[str] = []

    for d in sorted(by_date.keys()):
        ws_list = by_date[d]
        decorated: list[tuple] = []
        for w in ws_list:
            t = w.get("start") or "00:00"
            try:
                dt_w = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
            except ValueError:
                dt_w = datetime.strptime(d, "%Y-%m-%d")
            decorated.append((dt_w, w))
        decorated.sort(key=lambda x: x[0])

        clusters: list[list[tuple]] = []
        for dt_w, w in decorated:
            if clusters and (dt_w - clusters[-1][-1][0]).total_seconds() / 60.0 \
                    <= STRENGTH_CLUSTER_WINDOW_MIN:
                clusters[-1].append((dt_w, w))
            else:
                clusters.append([(dt_w, w)])

        def cluster_total_min(c):
            return sum((wk.get("duration_min") or 0.0) for _, wk in c)

        clusters.sort(key=cluster_total_min, reverse=True)
        chosen = clusters[0]
        for skipped in clusters[1:]:
            warnings.append(
                f"  - {d}: skipping {len(skipped)} additional strength "
                f"workout(s) outside 90-min cluster "
                f"({cluster_total_min(skipped):.0f} min total) — used longest cluster"
            )

        active = sum((w.get("active_cal") or 0.0) for _, w in chosen)
        basal = sum((w.get("basal_cal") or 0.0) for _, w in chosen)
        elapsed = sum((w.get("elapsed_min") or 0.0) for _, w in chosen)
        duration = sum((w.get("duration_min") or 0.0) for _, w in chosen)
        active_v = active if active > 0 else None
        total_v = (active + basal) if (active > 0 and basal > 0) else None
        elapsed_v = elapsed if elapsed > 0 else None
        duration_v = duration if duration > 0 else None

        # Duration-weighted avg HR across the cluster. Heavier-weighted
        # workouts (the long FunctionalStrength block) dominate the
        # short CoreTraining warm-up.
        weighted_sum = 0.0
        weight_total = 0.0
        for _, w in chosen:
            ahr = w.get("avg_hr")
            dur = w.get("duration_min") or 0.0
            if ahr is None or dur <= 0:
                continue
            weighted_sum += float(ahr) * dur
            weight_total += dur
        avg_hr_v = (weighted_sum / weight_total) if weight_total > 0 else None

        sessions.append({
            "date": d,
            "active_cal": active_v,
            "total_cal": total_v,
            "elevation_m": None,   # strength is indoor; elevation rarely meaningful
            "elapsed_min": elapsed_v,
            "avg_hr": avg_hr_v,
            "duration_min": duration_v,
        })

    return sessions, warnings


# Stroke-name → 4-letter abbreviation for the Stroke Mix summary.
# Kept short (3-5 chars) so the CSV cell stays readable.
_STROKE_ABBREV = {
    "Freestyle":    "Free",
    "Backstroke":   "Back",
    "Breaststroke": "Breast",
    "Butterfly":    "Fly",
    "Mixed":        "Mix",
    "Kickboard":    "Kick",
    "Unknown":      "Unk",
}


def _stroke_mix_summary(lap_events: list[dict]) -> str | None:
    """Compact stroke-mix label, e.g. ``"Free 21 / Fly 1"``.

    Blank when there's only one stroke type and it's Freestyle (the
    default — not worth displaying). Counts are derived from the
    decoded stroke style; unknown enum values fall through to "Unk".
    """
    if not lap_events:
        return None
    counts: dict[str, int] = {}
    for ev in lap_events:
        raw = ev.get("stroke_raw")
        if raw is None:
            name = "Unknown"
        else:
            name = HK_SWIMMING_STROKE_STYLE.get(int(raw), "Unknown")
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return None
    if len(counts) == 1 and "Freestyle" in counts:
        return None
    parts = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return " / ".join(f"{_STROKE_ABBREV.get(name, name)} {n}" for name, n in parts)


def build_swim_csv_payloads(
    workout_rows: list[dict],
    profile: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """Build per-swim and per-lap CSV payloads from extracted workout rows.

    Filters ``workout_rows`` to swims and produces:
      - one ``swimming/YYYY.MM.workouts.csv`` entry per swim with
        computed SPL / Avg SWOLF / Stroke Mix.
      - per-lap ``swimming/YYYY.MM.laps.csv`` entries with decoded
        stroke names.
    Workouts without lap events still produce a per-swim row (with SPL /
    Avg SWOLF blank) so the totals line up with workout_sessions.csv.

    When Apple omits ``HKLapLength`` (rare — happens on some open-water
    swims), the per-swim ``Pool Length`` cell falls back to
    ``profile.swim_pool_length_default`` if the user has set one.
    A one-line note is printed to stderr for each fallback so the user
    can audit which rows were inferred.
    """
    pool_default: int | None = None
    if profile is not None:
        pool_default = profile.get("swim_pool_length_default")
    swim_rows: list[dict] = []
    lap_rows: list[dict] = []
    for w in workout_rows:
        if (w.get("apple_type") or "") != "Swimming":
            continue
        lap_events = w.get("swim_lap_events") or []
        # Avg SWOLF: mean over laps that reported a SWOLF score.
        swolf_vals = [ev.get("swolf") for ev in lap_events
                      if ev.get("swolf") is not None]
        avg_swolf = (round(sum(swolf_vals) / len(swolf_vals), 1)
                     if swolf_vals else None)
        # SPL: total strokes / lap count.
        strokes = w.get("stroke_count_total")
        laps_n = w.get("laps")
        spl = (round(strokes / laps_n, 1)
               if (strokes and laps_n) else None)
        stroke_mix = _stroke_mix_summary(lap_events)
        # Pool Length: prefer Apple's HKLapLength; fall back to the
        # profile default when missing (open-water swims, etc.).
        pool_length = w.get("pool_length_m")
        if pool_length is None and pool_default is not None:
            pool_length = pool_default
            print(
                f"Pool Length: fell back to profile default {pool_default}m "
                f"for swim {w.get('date')} {w.get('start')}",
                file=sys.stderr,
            )
        swim_rows.append({
            "date":          w.get("date"),
            "start":         w.get("start"),
            "end":           w.get("end"),
            "duration_min":  w.get("duration_min"),
            "distance_km":   w.get("distance_km"),
            "pool_length_m": pool_length,
            "laps":          laps_n,
            "strokes":       strokes,
            "spl":           spl,
            "avg_swolf":     avg_swolf,
            "stroke_mix":    stroke_mix,
            "location":      w.get("swim_location"),
            "water_temp_c":  w.get("water_temp_c"),
            "avg_hr":        w.get("avg_hr"),
            "active_cal":    int(round(w["active_cal"]))
                              if w.get("active_cal") is not None else None,
        })
        for ev in lap_events:
            raw = ev.get("stroke_raw")
            decoded = (HK_SWIMMING_STROKE_STYLE.get(int(raw))
                       if raw is not None else None)
            lap_rows.append({
                "date":            w.get("date"),
                "workout_start":   w.get("start"),
                "lap_num":         ev.get("lap_num"),
                "stroke_raw":      raw,
                "stroke_decoded":  decoded,
                "duration_sec":    ev.get("duration_sec"),
                "swolf":           ev.get("swolf"),
                "source":          "Apple Watch",
            })
    return swim_rows, lap_rows


def _resolve_export_zip(person: str) -> Path | None:
    """Find the Apple Health export zip in the workout-tracker root.

    Resolution order:
      1. ``<root>/Export - <Person>.zip`` (per-person)
      2. ``<root>/Export.zip`` (single-user fallback)
    Returns the first hit, or None if no eligible zip is found.
    """
    candidates = [
        WORKOUT_TRACKER_ROOT / f"Export - {person}.zip",
        WORKOUT_TRACKER_ROOT / "Export.zip",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--person", required=True,
                    help="Tracker owner (e.g. Nihad or Fabian). "
                         "Resolves the per-person data/ folder via "
                         "Skills/shared/person_paths.py.")
    ap.add_argument("--zip", default=None, type=Path,
                    help="Override the auto-resolved Apple Health export zip. "
                         "Default: <root>/Export - <Person>.zip → "
                         "<root>/Export.zip.")
    ap.add_argument("--since", default=None, type=parse_since,
                    help="Cutoff date (YYYY-MM-DD) for Health Metrics + "
                         "Workout Sessions ingest. Default: 6 months back. "
                         "Auto-cardio appends are scoped to the current "
                         "calendar month regardless — past months are not "
                         "re-scanned (see upsert_monthly_cardio).")
    ap.add_argument("--allow-past-months", action="store_true",
                    help="Bypass the current-month auto-cardio gate so rows "
                         "flow into prior YYYY.MM sheets too. One-off backfill "
                         "switch — past months are normally treated as finished.")
    ap.add_argument("--keep-export", action="store_true",
                    help="Don't delete the export zip after a successful "
                         "import. Default behavior is to delete it; the CSVs "
                         "are the persistent record.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and aggregate; do not write anything.")
    args = ap.parse_args()

    ctx = TrackerContext(args.person)
    person = ctx.person

    zip_path = args.zip or _resolve_export_zip(person)
    if zip_path is None or not zip_path.exists():
        print(f"ERROR: no Apple Health export found for {person} "
              f"(looked in {WORKOUT_TRACKER_ROOT})", file=sys.stderr)
        return 1

    since = args.since or default_since()

    aggregator = DayAggregator()
    workout_rows: list[dict] = []
    consume_apple_export(zip_path, since, aggregator, workout_rows)

    metric_entries = list(aggregator.emit(since))
    sleep_night_entries = list(aggregator.emit_sleep_nights(since))

    if args.dry_run:
        print(f"Health Metrics: {len(metric_entries)} dates would be written "
              f"(range {metric_entries[0]['date'] if metric_entries else '-'} → "
              f"{metric_entries[-1]['date'] if metric_entries else '-'})")
        print(f"Sleep Nights: {len(sleep_night_entries)} dates would be written "
              f"(range {sleep_night_entries[0]['date'] if sleep_night_entries else '-'} → "
              f"{sleep_night_entries[-1]['date'] if sleep_night_entries else '-'})")
        print(f"Workout Sessions: {len(workout_rows)} sessions would be written "
              f"({sum(1 for r in workout_rows if r.get('incidental'))} walks flagged incidental)")
        return 0

    out_lines = []

    # Bootstrap the profile CSV for XML on first run. ``auto_cardio``
    # defaults to True for XML — the user almost always wants Apple-recorded
    # runs / hikes / HIIT to flow into the monthly sheets without needing
    # to log them by hand.
    profile, profile_created = ensure_profile(
        person, default_source="xml", default_auto_cardio=True,
    )
    if profile_created:
        out_lines.append("Profile: created (source=xml, auto_cardio=true)")

    out_lines.extend(upsert_health_metrics(person, metric_entries))
    out_lines.extend(upsert_workout_sessions(person, workout_rows))

    # Sleep nights CSV pipeline. XML only — HL exports don't carry
    # per-stage data, so this folder never exists on HL trackers.
    if profile.get("source") == "xml" and sleep_night_entries:
        out_lines.extend(upsert_sleep_nights(person, sleep_night_entries))

    # Swim CSV pipeline. XML only — HL .txt exports don't carry per-lap
    # data, so an HL run leaves swimming/YYYY.MM.workouts.csv /
    # YYYY.MM.laps.csv empty (folder absent) and the coach skips the
    # swim section.
    if profile.get("source") == "xml":
        swim_rows, swim_lap_rows = build_swim_csv_payloads(workout_rows, profile)
        if swim_rows:
            out_lines.extend(upsert_swim_workouts(person, swim_rows))
        if swim_lap_rows:
            out_lines.extend(upsert_swim_laps(person, swim_lap_rows))

    # Auto-cardio + strength-session metadata write to the per-month CSVs
    # via monthly_csv. The xlsx is gone post-PR3a.
    if profile.get("auto_cardio"):
        # The current-month gate lives inside ``upsert_monthly_cardio`` —
        # we hand it every eligible Apple workout in the --since window
        # and the helper drops anything outside the current calendar
        # month. Past months are "finished" and never re-scanned.
        #
        # Pre-emptive dedupe: when the watch creates a generic running
        # detection that overlaps a Matrix/GymKit-recorded workout for the
        # same activity type and day, drop the watch-only one. The
        # machine row is canonical (accurate distance, segments, laps);
        # the watch row is essentially the first few minutes of the same
        # activity double-counted.
        eligible = [
            w for w in workout_rows
            if (w.get("apple_type") or "") in CARDIO_AUTOLOG_TYPES
            and APPLE_TO_TRACKER_EXERCISE.get(w.get("apple_type") or "")
        ]
        eligible, dedupe_notes = _drop_watch_overlapping_machine(eligible)
        out_lines.extend(dedupe_notes)

        cardio_payload = build_auto_cardio_payload(
            eligible,
            eligible_types=CARDIO_AUTOLOG_TYPES,
            type_to_exercise=APPLE_TO_TRACKER_EXERCISE,
            machine_tag_for=lambda w: (
                (_extract_device_name(w.get("device") or "") or "fitness machine")
                if w.get("is_machine") else None
            ),
        )
        out_lines.extend(upsert_monthly_cardio(
            person, cardio_payload, allow_past_months=args.allow_past_months,
        ))
    else:
        out_lines.append("Auto-cardio: skipped (Profile.auto_cardio=false)")

    # Strength session metadata: cluster same-day strength workouts
    # within a 90-min start window and write Active/Total Cal / Elevation
    # / Elapsed / Avg HR onto the first row of the matching session in the
    # YYYY.MM sheet. Independent of the auto_cardio gate — this only
    # annotates existing manual-log rows; it never appends new rows.
    strength_in_window = [
        w for w in workout_rows
        if (w.get("apple_type") or "") in STRENGTH_APPLE_TYPES
    ]
    strength_sessions, strength_warnings = cluster_strength_sessions(strength_in_window)
    if strength_warnings:
        out_lines.append("Strength clustering warnings:")
        out_lines.extend(strength_warnings)
    out_lines.extend(upsert_monthly_strength_session(person, strength_sessions))

    # Archive the source export on success into <root>/.processed/.
    # Keeps a forensic trail in case a downstream bug damages the CSVs;
    # ``--keep-export`` opts out for testing.
    if not args.keep_export:
        try:
            archived = archive_processed_export(zip_path)
            out_lines.append(f"Archived source export: {zip_path.name} → {archived.parent.name}/{archived.name}")
        except OSError as e:
            out_lines.append(f"WARN: could not archive {zip_path.name}: {e}")

    for line in out_lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
