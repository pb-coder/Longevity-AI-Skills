"""Import an HLExport plain-text health export into the tracker CSV store.

HLExport (`https://apps.apple.com/.../hl-export-app/`) is the lightweight
alternative to Apple's native zipped XML export — much smaller, much
faster, but lossier: no HRV, no sleep stages, no per-workout HR, no wrist
temp. It produces a single text file shaped as one daily block per date:

    2026-04-25
    ----------
    HH:MM:SS <Metric Name>: <value> <unit>
    HH:MM:SS Workouts: HKWorkoutActivityType(rawValue: N), X min, Y kcal[, Z km]
    ...

This importer mirrors ``import_apple_health.py``'s CLI and writes through
the same upsert helpers (``upsert_health_metrics`` / ``upsert_workout_sessions``
/ ``upsert_monthly_cardio``) — only the parser front-end differs. Sparse-
merge protects existing values on re-runs; idempotent.

The capability matrix is fixed in code: when ``profile.csv`` says
``source = hl_export``, the coach's read layer skips HRV / wrist temp /
sleep-stage analyses because this importer can't fill them. Resting HR,
walking HR, and Apple's exercise-minute aggregate are **not** derived from
raw samples here — Apple's published values use proprietary aggregation
methods that we can't replicate. Surfacing a derived approximation alongside
Nihad's Apple-aggregate values would create misleading mixed trend lines.

Writes ``<person>/data/health_metrics.csv`` and
``<person>/data/workout_sessions.csv`` (the per-source slim schema is
applied automatically). Auto-cardio rows flow into the matching
``<person>/data/monthly/YYYY.MM.csv`` via ``upsert_monthly_cardio`` in
``monthly_csv.py``. HL doesn't carry per-lap swim data, so the
``swimming/`` folder isn't created for HL trackers — the coach skips
the swim section automatically. The text export is **archived to
``<root>/.processed/`` on success** — the CSVs are the persistent
record; the archive keeps a forensic trail if a downstream bug damages
the CSVs. Re-export from HLExport if you need to backfill.

Usage:
    python3 import_hl_export.py --person Fabian \\
        [--txt PATH_OR_GLOB]      # default: <root>/health_export_*.txt
        [--since YYYY-MM-DD]      # default: 6 months back from today
        [--allow-past-months]     # bypass the current-month auto-cardio gate
        [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monthly_csv import (  # noqa: E402
    upsert_monthly_cardio,
    upsert_monthly_strength_session,
)
from csv_store import (  # noqa: E402
    ensure_profile,
    read_profile,
    upsert_health_metrics,
    upsert_workout_sessions,
)
from person_paths import (  # noqa: E402
    WORKOUT_TRACKER_ROOT,
    archive_processed_export,
)
from apple_workout_types import (  # noqa: E402
    APPLE_TO_TRACKER_EXERCISE,
    CARDIO_AUTOLOG_TYPES,
    rawvalue_name,
)

# ---------------------------------------------------- HLExport line patterns
DATE_HEADER_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\s*$")
SEPARATOR_RE = re.compile(r"^-{3,}\s*$")
EVENT_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\s+([^:]+):\s*(.+?)\s*$")
# HL contract: distance is always emitted in km (the literal "km" suffix
# is part of the regex). No unit conversion needed here, unlike the XML
# importer where <WorkoutStatistics> records swims in metres.
WORKOUT_RE = re.compile(
    r"^HKWorkoutActivityType\(rawValue:\s*(\d+)\),"
    r"\s*([\d.]+)\s*min"
    r"(?:,\s*([\d.]+)\s*kcal)?"
    r"(?:,\s*([\d.]+)\s*km)?"
    r"\s*$"
)

# Bare-duration cardio (HIIT, indoor cycling without distance) gets the
# same incidental-walk treatment as the XML path: short walks logged as
# walking workouts are flagged so the coach filters them out of cardio
# totals.
INCIDENTAL_WALK_MAX_MIN = 15.0

# Sleep-block stitching: a gap longer than this between consecutive sleep
# events ends the current sleep block. Apple Watch can leave 60-90 min gaps
# between consecutive ``Sleep: Asleep`` stamps during deep sleep, so a 30-min
# threshold fragments continuous nights into many tiny blocks; 120 sits past
# the cadence plateau where the totals stabilise. ``Sleep: Awake`` events
# still close blocks, so brief mid-night wakings remain excluded.
SLEEP_BLOCK_GAP_MIN = 120.0


def to_float(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def default_since() -> date:
    return date.today() - timedelta(days=183)


# --------------------------------------------------------- per-day collector
class DayAggregator:
    """Per-date HL metrics + sleep-block reconstruction.

    HRV / wrist temp / Apple aggregate RHR / Apple exercise-minute / sleep
    stages are absent from HL by design — corresponding fields stay None.
    Resting HR is left None even though raw heart-rate samples are present
    (Apple's daily aggregate uses a proprietary algorithm we don't replicate).
    """

    def __init__(self) -> None:
        self.vo2max: dict[str, tuple[datetime, float]] = {}     # date -> (latest_ts, value)
        self.hr_recovery_1min: dict[str, float] = defaultdict(float)  # max of day
        self.resp_rate_acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
        self.bodyweight_kg: dict[str, tuple[datetime, float]] = {}
        # Sleep events: per-date list of (datetime, value) where value is
        # ``Asleep`` or ``Awake``. Stitched into segments at emit time.
        self.sleep_events: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
        # Sleep totals per wake-up date, populated at emit time from the
        # stitched events.
        self.sleep_total_min: dict[str, float] = {}

        # Dispatch table: metric name → bound handler. Replaces the
        # previous if/elif chain. Each handler signature is
        # ``(d: str, ts: datetime, raw_value: str) -> None``. Metrics not
        # in this dict are silently ignored — the coach can't use raw HR
        # samples without proprietary RHR aggregation, so surfacing a
        # derived value would diverge from Apple and create misleading
        # mixed trend lines.
        self._handlers = {
            "Cardio Fitness (VO2 Max)": self._h_vo2max,
            "Heart Rate Recovery":      self._h_hr_recovery,
            "Respiratory Rate":         self._h_resp_rate,
            "Weight":                   self._h_weight,
            "Sleep":                    self._h_sleep,
        }

    @staticmethod
    def _set_latest(store: dict, d: str, ts: datetime, value: float) -> None:
        cur = store.get(d)
        if cur is None or ts > cur[0]:
            store[d] = (ts, value)

    def add_event(self, d: str, ts: datetime, metric: str, raw_value: str) -> None:
        """Route a single parsed event line into the right bucket."""
        handler = self._handlers.get(metric)
        if handler is not None:
            handler(d, ts, raw_value)

    # ---- handlers (pull the leading numeric/string field from raw_value) ----
    def _h_vo2max(self, d, ts, raw_value):
        v = to_float(raw_value.split()[0])
        if v is not None:
            self._set_latest(self.vo2max, d, ts, v)

    def _h_hr_recovery(self, d, _ts, raw_value):
        v = to_float(raw_value.split()[0])
        if v is not None and v > self.hr_recovery_1min.get(d, 0.0):
            self.hr_recovery_1min[d] = v

    def _h_resp_rate(self, d, _ts, raw_value):
        v = to_float(raw_value.split()[0])
        if v is not None:
            acc = self.resp_rate_acc[d]
            acc[0] += v
            acc[1] += 1

    def _h_weight(self, d, ts, raw_value):
        v = to_float(raw_value.split()[0])
        if v is not None:
            self._set_latest(self.bodyweight_kg, d, ts, v)

    def _h_sleep(self, d, ts, raw_value):
        tag = raw_value.strip()
        if tag in ("Asleep", "Awake"):
            self.sleep_events[d].append((ts, tag))

    def stitch_sleep(self) -> None:
        """Walk per-date sleep events, build segments, bucket by wake-up date.

        Algorithm: events come in ascending time order within a date; we
        iterate across all dates' events as one global stream so a sleep
        block crossing midnight is handled cleanly. Each ``Asleep`` event
        starts (or extends) the current sleep block; the block ends at
        the next ``Awake`` event, the next ``Asleep`` event that's more
        than ``SLEEP_BLOCK_GAP_MIN`` later than the previous one, or the
        end of the data. The block's wake-up date (date of the final
        event) is the bucket.
        """
        # Flatten into one ascending stream.
        flat: list[tuple[datetime, str]] = []
        for events in self.sleep_events.values():
            flat.extend(events)
        flat.sort(key=lambda e: e[0])

        if not flat:
            return

        block_start: datetime | None = None
        block_last: datetime | None = None
        for ts, tag in flat:
            if tag == "Asleep":
                if block_start is None:
                    block_start = ts
                    block_last = ts
                else:
                    # Continuation: if the gap is too big, close the prior
                    # block and start a new one.
                    gap_min = (ts - block_last).total_seconds() / 60.0  # type: ignore[operator]
                    if gap_min > SLEEP_BLOCK_GAP_MIN:
                        self._commit_sleep_block(block_start, block_last)  # type: ignore[arg-type]
                        block_start = ts
                    block_last = ts
            else:  # Awake
                if block_start is not None:
                    # Awake closes the current block at the awake timestamp.
                    self._commit_sleep_block(block_start, ts)
                    block_start = None
                    block_last = None

        # Trailing open block — close at the last seen Asleep timestamp.
        if block_start is not None and block_last is not None:
            self._commit_sleep_block(block_start, block_last)

    def _commit_sleep_block(self, start: datetime, end: datetime) -> None:
        minutes = (end - start).total_seconds() / 60.0
        if minutes <= 0:
            return
        # Wake-up date — date of the block's end. A 22:00 → 06:00 sleep
        # belongs to the wake-up morning's recovery, matching the XML path.
        bucket = end.date().isoformat()
        self.sleep_total_min[bucket] = self.sleep_total_min.get(bucket, 0.0) + minutes

    def emit(self, since_date: date | None) -> list[dict]:
        """Yield per-date Health Metrics dicts (one per date with any data)."""
        self.stitch_sleep()

        all_dates: set[str] = set()
        all_dates.update(self.vo2max.keys())
        all_dates.update(self.hr_recovery_1min.keys())
        all_dates.update(self.resp_rate_acc.keys())
        all_dates.update(self.bodyweight_kg.keys())
        all_dates.update(self.sleep_total_min.keys())

        cutoff = since_date.isoformat() if since_date else None
        out: list[dict] = []
        for d in sorted(all_dates):
            if cutoff and d < cutoff:
                continue

            def lat(store: dict, key: str = d) -> float | None:
                tup = store.get(key)
                return tup[1] if tup else None

            vo2 = lat(self.vo2max)
            bw = lat(self.bodyweight_kg)
            rr_sum, rr_n = self.resp_rate_acc.get(d, [0.0, 0])
            rr = round(rr_sum / rr_n, 2) if rr_n else None
            sleep_min = self.sleep_total_min.get(d, 0.0)
            hr_rec = self.hr_recovery_1min.get(d)

            out.append({
                "date":              d,
                "bodyweight_kg":     round(bw, 2) if bw is not None else None,
                "vo2max":            round(vo2, 2) if vo2 is not None else None,
                # Fields HL can't supply — left None so sparse-merge protects
                # any pre-existing XML-derived value.
                "resting_hr":        None,
                "hrv_sdnn":          None,
                "walking_hr":        None,
                "hr_recovery_1min":  round(hr_rec, 1) if hr_rec else None,
                "sleep_total_h":     round(sleep_min / 60.0, 2) if sleep_min else None,
                "sleep_deep_h":      None,
                "sleep_rem_h":       None,
                "resp_rate":         rr,
                "wrist_temp_c":      None,
                "sleep_breath_dist": None,
                "exercise_min":      None,
            })
        return out


# ---------------------------------------------------------- workout extractor
def extract_hl_workout(d: str, ts: datetime, raw: str) -> dict | None:
    """Build one Workout Sessions row from an HLExport workout line.

    HL emits the timestamp at workout end (more precisely: when the
    record was written). We compute start as ``end - duration``; all HL
    workouts have null avg/max/min HR by design.
    """
    m = WORKOUT_RE.match(raw.strip())
    if not m:
        return None
    raw_int = int(m.group(1))
    duration = to_float(m.group(2))
    cal = to_float(m.group(3))
    distance = to_float(m.group(4))

    apple_type = rawvalue_name(raw_int)

    end_dt = ts
    start_dt = end_dt - timedelta(minutes=duration) if duration else end_dt

    notes = None
    if "Walking" in apple_type and duration is not None and duration < INCIDENTAL_WALK_MAX_MIN:
        notes = "incidental walk"

    # HL emits the workout at end-time and we computed start_dt above as
    # ``end - duration``. Without pause data, elapsed equals duration here —
    # we surface it explicitly for note-builder symmetry with the XML path.
    elapsed_min = round((end_dt - start_dt).total_seconds() / 60.0, 1) if duration else None

    return {
        "date":         start_dt.date().isoformat(),
        "start":        start_dt.strftime("%H:%M:%S"),
        "end":          end_dt.strftime("%H:%M:%S"),
        "apple_type":   apple_type,
        "duration_min": round(duration, 1) if duration is not None else None,
        "avg_hr":       None,
        "max_hr":       None,
        "min_hr":       None,
        "active_cal":   round(cal, 1) if cal is not None else None,
        "basal_cal":    None,
        "total_cal":    None,
        "elevation_m":  None,
        "elapsed_min":  elapsed_min,
        "distance_km":  round(distance, 2) if distance is not None else None,
        "source":       "HLExport",
        "notes":        notes,
    }


# ---------------------------------------------------------- streaming parser
def stream_hl_export(path: Path):
    """Yield ``(kind, payload)`` pairs by streaming the text file.

    kind == ``"event"``: ``payload`` = ``(date_str, datetime, metric, value_str)``.
    kind == ``"workout"``: ``payload`` = workout row dict (raw — caller filters
    by ``--since``).
    """
    current_date: str | None = None
    current_ymd: tuple[int, int, int] | None = None
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            # Strip trailing CR/LF without an extra .strip() pass — common
            # case is a clean newline. Skip empty lines via length check.
            if line.endswith("\n"):
                line = line[:-1]
            if line.endswith("\r"):
                line = line[:-1]
            if not line:
                continue

            # Hot path: event lines start with two ASCII digits + ':'. Almost
            # every line in a real export matches this shape, so try the
            # event regex first and only fall through to date / separator
            # detection on a miss. Saves two doomed regex calls per event.
            if (len(line) > 2 and line[0].isdigit() and line[1].isdigit()
                    and line[2] == ":"):
                m_ev = EVENT_RE.match(line)
                if m_ev is not None:
                    if current_date is None or current_ymd is None:
                        continue
                    hh, mm, ss, metric, raw = m_ev.groups()
                    try:
                        ts = datetime(
                            current_ymd[0], current_ymd[1], current_ymd[2],
                            int(hh), int(mm), int(ss),
                        )
                    except ValueError:
                        continue
                    metric_clean = metric.strip()
                    if metric_clean == "Workouts":
                        row = extract_hl_workout(current_date, ts, raw)
                        if row is not None:
                            yield "workout", row
                    else:
                        yield "event", (current_date, ts, metric_clean, raw)
                    continue

            # Cold path: date headers ("YYYY-MM-DD") and separators ("------").
            m_date = DATE_HEADER_RE.match(line)
            if m_date is not None:
                y, mo, da = m_date.group(1), m_date.group(2), m_date.group(3)
                current_date = f"{y}-{mo}-{da}"
                current_ymd = (int(y), int(mo), int(da))
                continue
            # Separator line is the only other expected non-event shape.
            # Anything else (blank lines after rstrip, malformed rows) is
            # silently skipped.


# ----------------------------------------------------------------------- CLI
def parse_since(s: str | None) -> date | None:
    if s is None:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"--since must be YYYY-MM-DD ({e})")


def resolve_txt(pattern: str) -> Path | None:
    """Resolve ``--txt`` to a single concrete file.

    Accepts a literal path or a glob like ``./health_export_*.txt``. With a
    glob, picks the most recent by mtime (the user typically drops one fresh
    export at a time).
    """
    candidates = sorted(
        (Path(p) for p in glob.glob(pattern)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    p = Path(pattern)
    return p if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--person", required=True,
                    help="Tracker owner (e.g. Fabian). Resolves the "
                         "per-person data/ folder via "
                         "Skills/shared/person_paths.py.")
    ap.add_argument("--txt", default=None, type=str,
                    help="Override the auto-resolved HLExport text file. "
                         "Default: <root>/health_export_*.txt (latest mtime "
                         "wins on glob).")
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
                    help="Don't delete the export txt after a successful "
                         "import. Default behavior is to delete it; the CSVs "
                         "are the persistent record.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and aggregate; do not write anything.")
    args = ap.parse_args()

    person = args.person

    pattern = args.txt or str(WORKOUT_TRACKER_ROOT / "health_export_*.txt")
    txt_path = resolve_txt(pattern)
    if txt_path is None:
        print(f"ERROR: HLExport file not found: {pattern}", file=sys.stderr)
        return 1

    since = args.since or default_since()
    since_iso = since.isoformat()

    aggregator = DayAggregator()
    workout_rows: list[dict] = []

    for kind, payload in stream_hl_export(txt_path):
        if kind == "event":
            d, ts, metric, raw = payload
            if d < since_iso and metric != "Sleep":
                # Sleep events near the boundary may belong to a wake-up
                # date that's in-window; let them through.
                continue
            aggregator.add_event(d, ts, metric, raw)
        else:  # workout
            row = payload
            if row.get("date", "") < since_iso:
                continue
            workout_rows.append(row)

    metric_entries = aggregator.emit(since)

    if args.dry_run:
        print(
            f"HLExport file: {txt_path.name}\n"
            f"Health Metrics: {len(metric_entries)} dates would be written "
            f"(range "
            f"{metric_entries[0]['date'] if metric_entries else '-'} → "
            f"{metric_entries[-1]['date'] if metric_entries else '-'})"
        )
        incidental = sum(1 for r in workout_rows
                         if r.get('incidental') is True
                         or (r.get('notes') or '').startswith('incidental'))
        print(f"Workout Sessions: {len(workout_rows)} sessions would be written "
              f"({incidental} walks flagged incidental)")
        return 0

    out_lines: list[str] = []

    # Bootstrap the profile CSV for HL on first run. Auto-cardio defaults
    # to True — HL workout records (Hike / Outdoor Run / Outdoor Cycling /
    # Swim / HIIT) have proven reliable in practice, so the conservative
    # opt-in default has been retired. Flip the flag to False on a per-
    # tracker basis if a specific user wants manual-only logging.
    profile, profile_created = ensure_profile(
        person, default_source="hl_export", default_auto_cardio=True,
    )
    if profile_created:
        out_lines.append("Profile: created (source=hl_export, auto_cardio=true)")

    out_lines.extend(upsert_health_metrics(person, metric_entries))
    out_lines.extend(upsert_workout_sessions(person, workout_rows))

    # Auto-cardio + strength-session metadata write to the per-month CSVs
    # via monthly_csv (post-PR3a; xlsx is gone).

    # Strength session metadata: HL provides Active Cal and Duration per
    # strength workout (no Avg HR, no basal/elevation, no separate elapsed).
    # Cluster same-day strength workouts within 90 min of each other (matches
    # the XML importer's logic) and annotate the matching manual-log session
    # with Active Cal. Independent of the auto_cardio gate — this only
    # annotates existing rows; never appends new ones.
    strength_apple_types = {
        "TraditionalStrengthTraining",
        "FunctionalStrengthTraining",
        "CoreTraining",
    }
    strength_workouts = [
        w for w in workout_rows
        if (w.get("apple_type") or "") in strength_apple_types
    ]
    by_date_str: dict[str, list[dict]] = {}
    for w in strength_workouts:
        d = str(w.get("date") or "")[:10]
        if not d:
            continue
        by_date_str.setdefault(d, []).append(w)

    strength_sessions: list[dict] = []
    strength_warnings: list[str] = []
    for d in sorted(by_date_str.keys()):
        ws_list = by_date_str[d]

        def _start_dt(w):
            t = w.get("start") or "00:00:00"
            try:
                return datetime.strptime(f"{d} {t[:8]}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return datetime.strptime(d, "%Y-%m-%d")

        decorated = sorted(((_start_dt(w), w) for w in ws_list), key=lambda x: x[0])
        clusters: list[list[tuple]] = []
        for dt_w, w in decorated:
            if clusters and (dt_w - clusters[-1][-1][0]).total_seconds() / 60.0 <= 90.0:
                clusters[-1].append((dt_w, w))
            else:
                clusters.append([(dt_w, w)])
        clusters.sort(
            key=lambda c: sum((wk.get("duration_min") or 0.0) for _, wk in c),
            reverse=True,
        )
        chosen = clusters[0]
        for skipped in clusters[1:]:
            total_min = sum((wk.get("duration_min") or 0.0) for _, wk in skipped)
            strength_warnings.append(
                f"  - {d}: skipping {len(skipped)} additional strength "
                f"workout(s) outside 90-min cluster ({total_min:.0f} min) — "
                f"used longest cluster"
            )
        active = sum((w.get("active_cal") or 0.0) for _, w in chosen)
        duration = sum((w.get("duration_min") or 0.0) for _, w in chosen)
        strength_sessions.append({
            "date": d,
            "active_cal": active if active > 0 else None,
            "duration_min": duration if duration > 0 else None,
            # HL doesn't carry basal/elevation/per-workout HR, and its
            # elapsed equals duration (no pause detection). Leave the
            # other 4 columns blank for Fabian.
            "total_cal": None,
            "elevation_m": None,
            "elapsed_min": None,
            "avg_hr": None,
        })
    if strength_warnings:
        out_lines.append("Strength clustering warnings:")
        out_lines.extend(strength_warnings)
    out_lines.extend(upsert_monthly_strength_session(person, strength_sessions))

    if profile.get("auto_cardio"):
        # The current-month gate lives inside ``upsert_monthly_cardio`` —
        # we hand it every eligible workout in the --since window and the
        # helper drops anything outside the current calendar month. Past
        # months are "finished" and never re-scanned.
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
                # HL doesn't supply basal/elevation/effort. active_cal +
                # elapsed_min are present; the note builder skips the rest.
                "active_cal":   w.get("active_cal"),
                "total_cal":    w.get("total_cal"),
                "elevation_m":  w.get("elevation_m"),
                "elapsed_min":  w.get("elapsed_min"),
            })
        out_lines.extend(upsert_monthly_cardio(
            person, cardio_payload, allow_past_months=args.allow_past_months,
        ))
    else:
        out_lines.append("Auto-cardio: skipped (Profile.auto_cardio=false)")

    # Archive the source export on success into <root>/.processed/.
    # Keeps a forensic trail in case a downstream bug damages the CSVs;
    # ``--keep-export`` opts out for testing.
    if not args.keep_export:
        try:
            archived = archive_processed_export(txt_path)
            out_lines.append(f"Archived source export: {txt_path.name} → {archived.parent.name}/{archived.name}")
        except OSError as e:
            out_lines.append(f"WARN: could not archive {txt_path.name}: {e}")

    for line in out_lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
