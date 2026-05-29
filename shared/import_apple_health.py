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
    python3 import_apple_health.py --person <Person> \\
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
from datetime import date, datetime, timedelta
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(SKILLS_ROOT))
    __package__ = "shared"
from tracker import TrackerContext  # noqa: E402
from tracker.importing import build_auto_cardio_payload  # noqa: E402
from .monthly_csv import (  # noqa: E402
    upsert_monthly_cardio,
    upsert_monthly_strength_session,
)
from .csv_store import (  # noqa: E402
    ensure_profile,
    upsert_health_metrics,
    upsert_sleep_nights,
    upsert_swim_laps,
    upsert_swim_workouts,
    upsert_workout_sessions,
)
from .person_paths import (  # noqa: E402
    WORKOUT_TRACKER_ROOT,
    archive_processed_export,
)
from .apple_workout_types import (  # noqa: E402
    APPLE_TO_TRACKER_EXERCISE,
    CARDIO_AUTOLOG_TYPES,
)
from .apple_health_core import hhmm, parse_apple_dt, to_float  # noqa: E402
from .apple_health_daily import DayAggregator, WANTED_RECORD_TYPES  # noqa: E402
from .apple_health_strength import (  # noqa: E402
    STRENGTH_APPLE_TYPES,
    cluster_strength_sessions,
)
from .apple_health_swim import build_swim_csv_payloads  # noqa: E402

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
                    help="Tracker owner (e.g. <Person> or <OtherPerson>). "
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
