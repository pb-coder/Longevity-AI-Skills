"""Import Apple Health export into the tracker xlsx.

Streams the zipped ``Export.xml`` directly with stdlib ``zipfile`` +
``xml.etree.iterparse`` (no extraction step, ~150 MB peak RAM on a 540 MB
unzipped XML). Aggregates per-day Tier 1+2 metrics into ``Health Metrics``
and one row per ``Workout`` element into ``Workout Sessions``. Sparse-
merge upserts protect existing data on re-run; idempotent.

The logger drives this — it shells out after the user opts into the
"Refresh Apple Health data?" prompt. The script itself is person-agnostic;
``--zip`` and ``--tracker`` are the only inputs.

Usage:
    python3 import_apple_health.py \\
        --zip "./Export - Nihad.zip" \\
        --tracker "Workout Tracker - Nihad.xlsx" \\
        [--since YYYY-MM-DD]      # default: 6 months back from today
        [--also-bodyweight]       # mirror Apple BodyMass into Bodyweight sheet
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

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tracker_sheet import (  # noqa: E402
    ensure_profile_sheet,
    read_profile,
    upsert_health_metrics,
    upsert_monthly_cardio,
    upsert_monthly_strength_session,
    upsert_workout_sessions,
)
from apple_workout_types import (  # noqa: E402
    APPLE_TO_TRACKER_EXERCISE,
    CARDIO_AUTOLOG_TYPES,
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
SLEEP_DEEP_VALUE = "HKCategoryValueSleepAnalysisAsleepDeep"
SLEEP_REM_VALUE = "HKCategoryValueSleepAnalysisAsleepREM"

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
        # sleep buckets keyed by wake-up date
        self.sleep_total_min   = defaultdict(float)
        self.sleep_deep_min    = defaultdict(float)
        self.sleep_rem_min     = defaultdict(float)

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
        if value not in SLEEP_ASLEEP_VALUES:
            # Skip InBed and Awake — they don't count as time asleep.
            return
        minutes = (dt_end - dt_start).total_seconds() / 60.0
        if minutes <= 0:
            return
        # Bucket by wake-up date — the date of the segment's endDate.
        # A segment ending at 07:00 the next morning belongs to that
        # morning's recovery, not the previous evening's "training day".
        bucket = d_end
        self.sleep_total_min[bucket] += minutes
        if value == SLEEP_DEEP_VALUE:
            self.sleep_deep_min[bucket] += minutes
        elif value == SLEEP_REM_VALUE:
            self.sleep_rem_min[bucket] += minutes

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

            sleep_total_min = self.sleep_total_min.get(d, 0.0)
            sleep_deep_min  = self.sleep_deep_min.get(d, 0.0)
            sleep_rem_min   = self.sleep_rem_min.get(d, 0.0)

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
                "resp_rate":         rr,
                "wrist_temp_c":      round(lat(self.wrist_temp_c), 3) if lat(self.wrist_temp_c) is not None else None,
                "sleep_breath_dist": round(lat(self.sleep_breath), 4) if lat(self.sleep_breath) is not None else None,
                "exercise_min":      round(self.exercise_min[d], 1) if d in self.exercise_min else None,
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
            elif key == "HKElevationAscended" and val is not None:
                # Apple reports elevation in cm with a unit suffix (e.g.
                # "11589 cm"). Strip the unit and convert to metres.
                token = val.split()[0] if isinstance(val, str) else val
                cm = to_float(token)
                if cm is not None:
                    elevation_m = cm / 100.0
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
        elif ctype in (DISTANCE_WR_TYPE, DISTANCE_CYCLE_TYPE, DISTANCE_SWIM_TYPE):
            # Use whichever distance type matches the activity (Apple
            # records the right one per workout). If multiple, the last
            # one wins — that's vanishingly rare.
            v = to_float(a.get("sum"))
            if v is not None:
                distance_km = v

    # Specialise the canonical name for indoor variants. Only the three
    # types Apple records both ways are renamed; everything else (Hiking,
    # Swimming, Strength, HIIT, etc.) keeps its base name.
    if indoor and apple_type in ("Running", "Cycling", "Walking"):
        apple_type = "Indoor" + apple_type

    notes = None
    if "Walking" in apple_type and duration is not None and duration < INCIDENTAL_WALK_MAX_MIN:
        notes = "incidental walk"

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
        "distance_km":  round(distance_km, 2) if distance_km is not None else None,
        "source":       attrib.get("sourceName"),
        "notes":        notes,
    }


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", required=True, type=Path, help="Path to Apple Health export zip")
    ap.add_argument("--tracker", required=True, type=Path, help="Path to Workout Tracker xlsx")
    ap.add_argument("--since", default=None, type=parse_since,
                    help="Cutoff date (YYYY-MM-DD) for Health Metrics + "
                         "Workout Sessions ingest. Default: 6 months back. "
                         "Auto-cardio appends are scoped to the current "
                         "calendar month regardless — past months are not "
                         "re-scanned (see upsert_monthly_cardio).")
    ap.add_argument("--also-bodyweight", action="store_true",
                    help="Mirror Apple BodyMass into the Bodyweight sheet.")
    ap.add_argument("--allow-past-months", action="store_true",
                    help="Bypass the current-month auto-cardio gate so rows "
                         "flow into prior YYYY.MM sheets too. One-off backfill "
                         "switch — past months are normally treated as finished.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and aggregate; do not write the workbook.")
    args = ap.parse_args()

    if not args.zip.exists():
        print(f"ERROR: zip not found: {args.zip}", file=sys.stderr)
        return 1
    if not args.tracker.exists():
        print(f"ERROR: tracker not found: {args.tracker}", file=sys.stderr)
        return 1

    since = args.since or default_since()

    aggregator = DayAggregator()
    workout_rows: list[dict] = []
    consume_apple_export(args.zip, since, aggregator, workout_rows)

    metric_entries = list(aggregator.emit(since))

    bodyweight_entries = []
    if args.also_bodyweight:
        # Mirror the latest bodyweight per date from Apple into the
        # Bodyweight sheet. The manual entries remain truth-of-record;
        # upsert_bodyweight overwrites by date, so re-running with the
        # same export is a no-op.
        for entry in metric_entries:
            bw = entry.get("bodyweight_kg")
            if bw is None:
                continue
            bodyweight_entries.append({
                "date": entry["date"],
                "kg": bw,
                "notes": "from Apple Health",
            })

    if args.dry_run:
        print(f"Health Metrics: {len(metric_entries)} dates would be written "
              f"(range {metric_entries[0]['date'] if metric_entries else '-'} → "
              f"{metric_entries[-1]['date'] if metric_entries else '-'})")
        print(f"Workout Sessions: {len(workout_rows)} sessions would be written "
              f"({sum(1 for r in workout_rows if (r.get('notes') or '').startswith('incidental'))} walks flagged incidental)")
        if args.also_bodyweight:
            print(f"Bodyweight: {len(bodyweight_entries)} entries would be mirrored")
        else:
            print("Bodyweight: skipped (no --also-bodyweight)")
        return 0

    wb = openpyxl.load_workbook(args.tracker)
    out_lines = []

    # Bootstrap the Profile sheet for XML on first run. ``auto_cardio``
    # defaults to True for XML — the user almost always wants Apple-recorded
    # runs / hikes / HIIT to flow into the monthly sheets without needing
    # to log them by hand.
    _, profile_created = ensure_profile_sheet(
        wb, default_source="xml", default_auto_cardio=True,
    )
    profile = read_profile(wb)
    if profile_created:
        out_lines.append("Profile: created (source=xml, auto_cardio=true)")

    out_lines.extend(upsert_health_metrics(wb, metric_entries))
    out_lines.extend(upsert_workout_sessions(wb, workout_rows))

    if profile.get("auto_cardio"):
        # The current-month gate lives inside ``upsert_monthly_cardio`` —
        # we hand it every eligible Apple workout in the --since window
        # and the helper drops anything outside the current calendar
        # month. Past months are "finished" and never re-scanned.
        cardio_payload: list[dict] = []
        for w in workout_rows:
            apple_type = w.get("apple_type") or ""
            if apple_type not in CARDIO_AUTOLOG_TYPES:
                continue
            tracker_name = APPLE_TO_TRACKER_EXERCISE.get(apple_type)
            if not tracker_name:
                continue
            cardio_payload.append({
                "date":         w.get("date"),
                "exercise":     tracker_name,
                "duration_min": w.get("duration_min"),
                "distance_km":  w.get("distance_km"),
                "avg_hr":       w.get("avg_hr"),
                # Pass through the metadata extras for the structured note
                # builder. None-safe on the consumer side; XML always fills
                # active/basal/elapsed when present.
                "active_cal":   w.get("active_cal"),
                "total_cal":    w.get("total_cal"),
                "elevation_m":  w.get("elevation_m"),
                "elapsed_min":  w.get("elapsed_min"),
            })
        out_lines.extend(upsert_monthly_cardio(
            wb, cardio_payload, allow_past_months=args.allow_past_months,
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
    out_lines.extend(upsert_monthly_strength_session(wb, strength_sessions))

    if args.also_bodyweight:
        # Reach into the logger's append_workout.upsert_bodyweight so the
        # mirroring path uses the same idempotent dedupe-by-date logic
        # `/log` itself uses. Avoids duplicating that small module.
        logger_scripts = Path(__file__).resolve().parents[1] / "workout-logger" / "scripts"
        sys.path.insert(0, str(logger_scripts))
        from append_workout import upsert_bodyweight  # noqa: E402
        out_lines.extend(upsert_bodyweight(wb, bodyweight_entries))
    else:
        out_lines.append("Bodyweight: skipped (no --also-bodyweight)")
    wb.save(args.tracker)
    for line in out_lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
