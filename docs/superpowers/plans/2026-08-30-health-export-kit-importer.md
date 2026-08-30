# Health Export Kit Importer — Implementation Plan (Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new importer that reads Health Export Kit JSON and writes the tracker's existing CSV schemas with the same fidelity as the retired Health Auto Export importer, so the pipeline that has been broken since 2026-08-23 works again.

**Architecture:** A new module `Skills/shared/import_health_export_kit.py`, built alongside the existing `import_health_auto_export.py` rather than replacing it. It reuses every existing store function unchanged — the CSV schemas do not change in this plan. Parsing is split into pure functions that take a parsed payload dict and return store-ready payload lists, so every rule is testable without touching disk. The orchestration function mirrors `import_archive`'s contract exactly.

**Tech Stack:** Python 3 stdlib only. `zoneinfo` for the clock correction (new to this repo — nothing in `Skills/` currently imports it). `unittest` for tests, run with `python3 -m unittest discover -s tests -v` from `Skills/`.

**Spec:** `Skills/docs/specs/2026-08-30-health-export-kit.md` — read it first. Every rule below cites a section of it.

## Global Constraints

- Python 3 standard library only. No new third-party dependencies.
- Tests use `unittest`, not pytest. There is no `conftest.py` and no `pyproject.toml` in this repo; do not add one.
- Run tests from the `Skills/` directory: `python3 -m unittest discover -s tests -v`
- Do **not** modify `import_health_auto_export.py` in this plan. It is retired in Plan 2.
- Do **not** add, remove or reorder any column in any existing CSV. New columns are Plan 3.
- Do **not** call `upsert_swim_laps`. Per-lap storage is Plan 3.
- Every read of export data uses `.get()`. Absent and zero are different (spec §5.5).
- Commit after every task.
- Data directories `<Person>/data/` are separate git repos committed by `commit_data`; the code repo is `Skills/`. Never `git add` across that boundary.
- **Privacy (`Skills/CLAUDE.md`).** Everything committed here is pushed to a public
  remote. No real names, device names, locations, ages or profile facts in code,
  comments, docs, commit messages or test fixtures. Use `<Person>` / `<OtherPerson>`.
  The committed fixture is scrubbed in Task 2: every `source` becomes `"Device"` and the
  zone becomes `Europe/Paris`, which shares the real zone's DST rules exactly, so the clock
  tests stay meaningful without recording where anyone lives. This matches the existing
  `hae-json-export.json` fixture, whose every source already reads `"Device"`.
- **`SOURCE_CAPABILITIES` gets a second key, deliberately.** `Skills/CLAUDE.md` says
  nothing may add one "without a documented migration". `Skills/docs/specs/2026-08-30-health-export-kit.md`
  is that migration. `CLAUDE.md` and `PROJECT.md` still describe HealthAutoExport as the
  only source; correcting them is Plan 2, so expect that inconsistency between the two
  plans and do not fix it here.

---

## File Structure

**Create:**
- `Skills/shared/hek_time.py` — clock correction, year reconstruction, day-completeness. Isolated because it is the highest-risk logic in the plan and deserves its own test file.
- `Skills/shared/import_health_export_kit.py` — payload readers and orchestration.
- `Skills/tests/fixtures/hek-export.json` — trimmed two-day fixture built from real exports.
- `Skills/tests/test_hek_time.py`
- `Skills/tests/test_hek_import.py`

**Modify:**
- `Skills/shared/apple_workout_types.py` — add `HEK_TYPE_MAP` next to the existing maps.
- `Skills/workout-coach/lib/constants.py:39` — add a `health_export_kit` entry to `SOURCE_CAPABILITIES`.
- `Skills/workout-logger/SKILL.md:102-116,154` — point the automatic refresh at the new importer.

---

## Task 1: Clock correction and calendar primitives

**Files:**
- Create: `Skills/shared/hek_time.py`
- Test: `Skills/tests/test_hek_time.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class ClockGuardError(ValueError)`
  - `export_offset(meta: dict) -> timedelta`
  - `resolve_year(mmdd: str, meta: dict) -> int`
  - `parse_stamp(stamp: str, meta: dict) -> datetime` — returns naive local, clock-corrected
  - `parse_day(value: str) -> date`
  - `complete_days(meta: dict) -> tuple[date, date]` — inclusive first and last fully-covered local day
  - `local_range(meta: dict) -> tuple[datetime, datetime]`

- [ ] **Step 1: Write the failing tests**

Create `Skills/tests/test_hek_time.py`:

```python
"""Clock, calendar and range primitives for Health Export Kit.

The export renders every workout and sleep timestamp as MM-dd HH:mm:ss with
no year, and every timestamp dated before a daylight-saving transition comes
out exactly one hour early (spec 5.1). Both defects are silent: a shifted
workout still looks like a workout, and a January date parsed as the wrong
year still sorts. The tests below pin the corrected values against real
observed pairs so a regression cannot pass unnoticed.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from shared import hek_time


def _meta(range_start="2025-12-31T23:00:00Z",
          range_end="2026-08-30T07:22:53Z",
          exported_at="2026-08-30T07:25:07Z",
          tz="Europe/Paris") -> dict:
    return {
        "rangeStart": range_start,
        "rangeEnd": range_end,
        "exportedAt": exported_at,
        "timeZone": tz,
    }


class ExportOffsetTests(unittest.TestCase):

    def test_offset_is_read_from_the_export_instant_not_the_range(self) -> None:
        # Exported 2026-08-30, inside CEST, so +02:00.
        self.assertEqual(hek_time.export_offset(_meta()), timedelta(hours=2))

    def test_winter_export_reads_plus_one(self) -> None:
        m = _meta(exported_at="2026-01-15T09:00:00Z")
        self.assertEqual(hek_time.export_offset(m), timedelta(hours=1))


class ClockCorrectionTests(unittest.TestCase):
    """Real observed pairs from the primary tracker's 2026-01-01 backfill."""

    def test_pre_transition_stamp_gains_an_hour(self) -> None:
        # Export said 12:38:19; the tracker's stored row says 13:38:19.
        got = hek_time.parse_stamp("03-28 12:38:19", _meta())
        self.assertEqual(got, datetime(2026, 3, 28, 13, 38, 19))

    def test_post_transition_stamp_is_unchanged(self) -> None:
        # Export said 15:19:20; stored row says 15:19:20.
        got = hek_time.parse_stamp("08-02 15:19:20", _meta())
        self.assertEqual(got, datetime(2026, 8, 2, 15, 19, 20))

    def test_the_transition_day_itself_is_unchanged(self) -> None:
        # 2026-03-29 is the CET->CEST switch; stored and export agree.
        got = hek_time.parse_stamp("03-29 13:06:05", _meta())
        self.assertEqual(got, datetime(2026, 3, 29, 13, 6, 5))

    def test_guard_rejects_a_non_whole_hour_correction(self) -> None:
        # A zone with a 30-minute DST step would produce a fractional
        # correction. We would rather fail loudly than shift real data.
        m = _meta(tz="Australia/Lord_Howe")
        with self.assertRaises(hek_time.ClockGuardError):
            hek_time.parse_stamp("01-15 10:00:00", m)

    def test_guard_rejects_a_correction_larger_than_two_hours(self) -> None:
        with self.assertRaises(hek_time.ClockGuardError):
            hek_time._check_correction(timedelta(hours=3))


class YearReconstructionTests(unittest.TestCase):

    def test_year_comes_from_the_range_not_from_today(self) -> None:
        m = _meta(range_start="2024-12-31T23:00:00Z",
                  range_end="2025-03-01T23:00:00Z",
                  exported_at="2025-03-01T23:05:00Z")
        self.assertEqual(hek_time.resolve_year("01-15", m), 2025)

    def test_a_range_crossing_new_year_picks_the_right_side(self) -> None:
        m = _meta(range_start="2026-12-01T23:00:00Z",
                  range_end="2027-01-15T23:00:00Z",
                  exported_at="2027-01-15T23:05:00Z")
        self.assertEqual(hek_time.resolve_year("12-15", m), 2026)
        self.assertEqual(hek_time.resolve_year("01-05", m), 2027)

    def test_a_range_longer_than_a_year_is_refused(self) -> None:
        m = _meta(range_start="2024-01-01T00:00:00Z",
                  range_end="2026-01-01T00:00:00Z",
                  exported_at="2026-01-01T00:05:00Z")
        with self.assertRaises(hek_time.ClockGuardError):
            hek_time.resolve_year("06-15", m)

    def test_a_sleep_session_starting_a_day_before_the_range_still_resolves(self) -> None:
        # Sessions overlapping the range are included in full, so a start
        # stamp can fall just outside it.
        m = _meta(range_start="2026-08-01T00:00:00Z",
                  range_end="2026-08-30T00:00:00Z",
                  exported_at="2026-08-30T00:05:00Z")
        self.assertEqual(hek_time.resolve_year("07-31", m), 2026)


class CompleteDayTests(unittest.TestCase):

    def test_partial_first_and_last_days_are_excluded(self) -> None:
        # Range runs 2026-07-31 08:45 local to 2026-08-30 08:45 local.
        m = _meta(range_start="2026-07-31T06:45:00Z",
                  range_end="2026-08-30T06:45:00Z",
                  exported_at="2026-08-30T06:46:00Z")
        first, last = hek_time.complete_days(m)
        self.assertEqual(first, date(2026, 8, 1))
        self.assertEqual(last, date(2026, 8, 29))

    def test_a_midnight_aligned_range_keeps_its_first_day(self) -> None:
        # 2025-12-31T23:00Z is 2026-01-01 00:00 in that zone.
        m = _meta(range_start="2025-12-31T23:00:00Z",
                  range_end="2026-08-30T07:22:53Z",
                  exported_at="2026-08-30T07:25:07Z")
        first, last = hek_time.complete_days(m)
        self.assertEqual(first, date(2026, 1, 1))
        self.assertEqual(last, date(2026, 8, 29))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `Skills/`:
```bash
python3 -m unittest tests.test_hek_time -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'shared.hek_time'`

- [ ] **Step 3: Write the implementation**

Create `Skills/shared/hek_time.py`:

```python
"""Clock, calendar and range primitives for the Health Export Kit format.

Three timestamp shapes appear in one export file:

- ``meta.rangeStart`` / ``rangeEnd`` / ``exportedAt``: ISO 8601, UTC, ``Z``.
- ``activity.daily[].date`` and every ``additional.*.daily[].date``: ``YYYY-MM-DD``.
- Workout, sleep, stage, stream and route stamps: ``MM-dd HH:mm:ss``, no year,
  local to ``meta.timeZone``.

The year-less shape carries two defects the importer must repair.

**The year.** It is only recoverable from the export's own range. A range
spanning 31 December otherwise silently produces last year's dates. We refuse
ranges longer than a year, where ``MM-dd`` is genuinely ambiguous.

**The clock.** Every stamp dated before a daylight-saving transition arrives
exactly one hour early; stamps after it are correct. Verified against the
tracker's stored history: 663 of 663 workouts and 224 of 224 sleep nights
match once corrected, and none match before. The root cause inside the app is
not known, so the correction below was fitted to the symptom and then
validated, and it is bounded by a guard: anything that is not a whole number
of hours within two hours of zero raises rather than shifting real data. A
future app version that fixes the bug will fail loudly here instead of
quietly double-correcting.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MAX_RANGE_DAYS = 366
MAX_CORRECTION = timedelta(hours=2)
# Sessions overlapping the range are included in full, so a stamp may fall
# this far outside it and still be legitimate.
RANGE_SLACK = timedelta(days=2)


class ClockGuardError(ValueError):
    """A timestamp could not be resolved safely. Never guess; refuse."""


def _utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC stamp ending in ``Z`` into an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _zone(meta: dict) -> ZoneInfo:
    return ZoneInfo(meta["timeZone"])


def local_range(meta: dict) -> tuple[datetime, datetime]:
    """Return the export's range as naive local datetimes."""
    tz = _zone(meta)
    start = _utc(meta["rangeStart"]).astimezone(tz).replace(tzinfo=None)
    end = _utc(meta["rangeEnd"]).astimezone(tz).replace(tzinfo=None)
    return start, end


def export_offset(meta: dict) -> timedelta:
    """The zone's UTC offset at the moment the export was taken."""
    tz = _zone(meta)
    return _utc(meta["exportedAt"]).astimezone(tz).utcoffset()


def _check_correction(correction: timedelta) -> timedelta:
    if abs(correction) > MAX_CORRECTION:
        raise ClockGuardError(
            f"clock correction {correction} exceeds the {MAX_CORRECTION} guard; "
            f"refusing to shift timestamps"
        )
    if correction % timedelta(hours=1) != timedelta(0):
        raise ClockGuardError(
            f"clock correction {correction} is not a whole number of hours; "
            f"refusing to shift timestamps"
        )
    return correction


def resolve_year(mmdd: str, meta: dict) -> int:
    """Pick the calendar year a bare ``MM-dd`` belongs to.

    Tries every year the range touches and keeps the one that lands inside
    the range (plus slack). Exactly one must fit; zero or two is a refusal.
    """
    start, end = local_range(meta)
    if (end - start).days > MAX_RANGE_DAYS:
        raise ClockGuardError(
            f"export range spans {(end - start).days} days; MM-dd stamps are "
            f"ambiguous beyond {MAX_RANGE_DAYS}. Export in shorter ranges."
        )
    month, day = (int(p) for p in mmdd.split("-"))
    lo = (start - RANGE_SLACK).date()
    hi = (end + RANGE_SLACK).date()
    hits = []
    for year in range(start.year, end.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue  # 29 February in a non-leap year
        if lo <= candidate <= hi:
            hits.append(year)
    if len(hits) != 1:
        raise ClockGuardError(
            f"cannot resolve a year for {mmdd!r} in range {lo}..{hi}: "
            f"{len(hits)} candidates"
        )
    return hits[0]


def parse_stamp(stamp: str, meta: dict) -> datetime:
    """Parse ``MM-dd HH:mm:ss`` into a corrected naive local datetime."""
    mmdd, hms = stamp.split(" ", 1)
    year = resolve_year(mmdd, meta)
    naive = datetime.strptime(f"{year}-{mmdd} {hms}", "%Y-%m-%d %H:%M:%S")
    tz = _zone(meta)
    correction = _check_correction(export_offset(meta) - naive.replace(tzinfo=tz).utcoffset())
    return naive + correction


def parse_day(value: str) -> date:
    """Parse a ``YYYY-MM-DD`` daily-row date. These carry no clock defect."""
    return date.fromisoformat(value)


def complete_days(meta: dict) -> tuple[date, date]:
    """The inclusive first and last local day the range fully covers.

    ``rangeStart`` and ``rangeEnd`` are instants, not dates, so the first and
    last day of any export are truncated. Two exports 27 minutes apart
    reported 6,326 and 5,926 steps for the same 2026-07-31.
    """
    start, end = local_range(meta)
    midnight = datetime.min.time()
    # A range starting at 00:00:00 covers that day in full; anything later
    # truncates it, so the first whole day is the next one. The end is
    # exclusive either way: a range ending at any time on day D leaves D
    # itself incomplete.
    first = start.date() if start.time() == midnight else start.date() + timedelta(days=1)
    last = end.date() - timedelta(days=1)
    return first, last
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m unittest tests.test_hek_time -v
```
Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
cd Skills
git add shared/hek_time.py tests/test_hek_time.py
git commit -m "feat: Health Export Kit clock, year and range primitives

The export renders workout and sleep stamps as MM-dd HH:mm:ss with no year,
and stamps dated before a DST transition arrive an hour early. Both are
silent defects. Corrections are validated against stored history (663/663
workouts, 224/224 sleep nights) and bounded by a guard that refuses rather
than guesses."
```

---

## Task 2: Fixture

**Files:**
- Create: `Skills/tests/fixtures/hek-export.json`

**Interfaces:**
- Consumes: `Skills/shared/hek_time.py` (not directly; the fixture is data).
- Produces: a fixture path later tasks load as
  `Path(__file__).resolve().parent / "fixtures" / "hek-export.json"`.

The fixture must exercise every rule in the plan, so build it deliberately rather than trimming a real file at random.

- [ ] **Step 1: Generate the fixture from real data**

Run this from the repository root with two absolute paths edited in: the real export as
input, and `tests/fixtures/hek-export.json` as output. The `Skills/` prefix used elsewhere
in this plan is dropped — the repo root is the Skills package root. It carves out a window that contains a split night, an evening nap, a lap-bearing swim, a strength workout and a pre-transition day, then strips the bulk series.

```bash
python3 - <<'PY'
import json
from pathlib import Path

src = json.load(open("<person>-backfill.json"))
KEEP_DAYS = {"2026-03-28", "2026-03-29", "2026-06-27", "2026-06-28", "2026-07-25"}
KEEP_MMDD = {d[5:] for d in KEEP_DAYS}

def in_window(stamp):
    return stamp[:5] in KEEP_MMDD or stamp[:5] in {"06-26", "07-24"}

out = {
    "meta": dict(src["meta"]),
    "activity": {
        "timeZone": src["activity"]["timeZone"],
        "daily": [r for r in src["activity"]["daily"] if r["date"] in KEEP_DAYS],
        "workouts": [],
    },
    "sleep": {"sessions": [], "streams": {
        "anchor": src["sleep"]["streams"]["anchor"],
        "timeFormat": src["sleep"]["streams"]["timeFormat"],
    }},
    "additional": {},
}
for w in src["activity"]["workouts"]:
    if not in_window(w["start"]):
        continue
    w = {k: v for k, v in w.items() if k not in ("route", "streams")}
    out["activity"]["workouts"].append(w)
# perMinute survives on swims only, so one task can test it without the
# fixture carrying a per-minute series for all ~20 workouts in the window.
keep_pm = {w["start"] for w in out["activity"]["workouts"] if w["type"] == "Swimming"}
for w in out["activity"]["workouts"]:
    if w["start"] not in keep_pm:
        w.pop("perMinute", None)

for s in src["sleep"]["sessions"]:
    if in_window(s["start"]) or in_window(s["end"]):
        out["sleep"]["sessions"].append(s)

for name, sec in src["additional"].items():
    if isinstance(sec, list):
        out["additional"][name] = [
            e for e in sec if str(e.get("time", ""))[:10] in KEEP_DAYS
        ]
        continue
    out["additional"][name] = {
        "units": sec["units"],
        "aggregation": sec["aggregation"],
        "daily": [r for r in sec["daily"] if r["date"] in KEEP_DAYS],
    }

# Deliberate edge cases the real window happens not to contain.
out["activity"]["daily"][0].pop("exerciseMinutes", None)   # absent key, not null
out["activity"]["workouts"][0].pop("isIndoor", None)       # absent indoor flag
out["meta"]["categories"] = sorted(set(out["meta"]["categories"]) | {"nutrition"})

# --- PRIVACY SCRUB, mandatory ------------------------------------------
# This fixture is committed to a public remote. The real export carries the
# owner's first name in every `source` string and their city in FOUR places:
# meta.timeZone, activity.timeZone, meta.notes, and sleep.streams.anchor.
# Scrubbing the serialized blob catches all of them, including any field
# added by a future app version. Europe/Paris shares the real zone's DST
# rules exactly, so the clock tests stay meaningful without recording where
# anyone lives. This matches the existing hae-json-export.json fixture,
# whose every source already reads "Device".
import re as _re
blob = json.dumps(out)
blob = _re.sub(r'"source":\s*"[^"]*"', '"source": "Device"', blob)
blob = blob.replace("Europe/Berlin", "Europe/Paris")
out = json.loads(blob)

Path("tests/fixtures/hek-export.json").write_text(
    json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False)
)
print("workouts", len(out["activity"]["workouts"]),
      "sessions", len(out["sleep"]["sessions"]),
      "days", len(out["activity"]["daily"]))
PY
```

- [ ] **Step 2: Verify the fixture contains what the later tasks assert against**

```bash
python3 - <<'PY'
import json, collections
d = json.load(open("Skills/tests/fixtures/hek-export.json"))
w = d["activity"]["workouts"]
print("size KB", len(json.dumps(d)) // 1024)
print("types", collections.Counter(x["type"] for x in w).most_common())
print("swims with laps", sum(1 for x in w
      if any(e["type"] == "lap" for e in x.get("events", []))))
print("pre-transition workouts", sum(1 for x in w if x["start"][:5] < "03-29"))
print("sessions", [(s["start"], s["end"]) for s in d["sleep"]["sessions"]])
print("no isIndoor", sum(1 for x in w if "isIndoor" not in x))
print("no exerciseMinutes", sum(1 for r in d["activity"]["daily"]
      if "exerciseMinutes" not in r))
print("nutrition requested, section present?",
      "nutrition" in d["meta"]["categories"], "nutrition" in d["additional"])
blob = json.dumps(d)
print("PRIVACY leaked tokens:",
      [t for t in ("Berlin", "von ", "Ultra", "’s ") if t in blob] or "none")
print("distinct sources:", set(w.get("source") for w in w) | {
      s.get("source") for s in d["sleep"]["sessions"]})
PY
```

Expected: `PRIVACY leaked tokens: none`, every source reading `Device`, a
fixture under 200 KB, at least one swim with lap events, at least
one workout dated before 2026-03-29, four or more sleep sessions including a
split night and an evening nap, exactly one workout missing `isIndoor`, exactly
one daily row missing `exerciseMinutes`, and `nutrition` requested but absent.

If any expectation is unmet, widen `KEEP_DAYS` and regenerate rather than
hand-editing the JSON.

- [ ] **Step 3: Commit**

```bash
cd Skills
git add tests/fixtures/hek-export.json
git commit -m "test: Health Export Kit fixture

A trimmed real export covering a DST-shifted day, a split night, an evening
nap, a lap-bearing swim, an absent isIndoor flag, an absent exerciseMinutes
key, and a requested-but-absent nutrition category."
```

---

## Task 3: Daily health metrics

**Files:**
- Create: `Skills/shared/import_health_export_kit.py`
- Test: `Skills/tests/test_hek_import.py`

**Interfaces:**
- Consumes: `hek_time.parse_day`, `hek_time.complete_days`.
- Produces:
  - `SOURCE_NAME = "health_export_kit"`
  - `SUM_METRICS: frozenset[str]`
  - `build_health_payload(payload: dict, since: date | None, until: date | None) -> list[dict]`
    Returns rows shaped for `csv_store.upsert_health_metrics`: `{"date": "YYYY-MM-DD", <subset of HEALTH_METRICS_FIELDS>: value}`.

- [ ] **Step 1: Write the failing tests**

Create `Skills/tests/test_hek_import.py`:

```python
"""Health Export Kit reader.

Every test here pins a rule that fails silently when it is wrong: a daily
sum written for a half-covered day, a breathing-disturbance value filed on
the night it started instead of the morning it belongs to, a humidity value
a hundred times too large. None of those would raise; all of them would sit
in the CSV looking plausible.
"""
from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from shared import import_health_export_kit as hek

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "hek-export.json"


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def _meta(range_start="2026-01-01T00:00:00Z",
          range_end="2026-01-05T00:00:00Z",
          exported_at="2026-01-05T00:05:00Z") -> dict:
    return {
        "rangeStart": range_start,
        "rangeEnd": range_end,
        "exportedAt": exported_at,
        "timeZone": "Europe/Paris",
        "categories": ["activity", "heart"],
    }


def _payload(meta=None, daily=None, additional=None,
             workouts=None, sessions=None) -> dict:
    return {
        "meta": meta or _meta(),
        "activity": {"daily": daily or [], "workouts": workouts or []},
        "sleep": {"sessions": sessions or [], "streams": {}},
        "additional": additional or {},
    }


class DailySumCoverageTests(unittest.TestCase):
    """Sums need a fully covered day; averages and latest readings do not."""

    # Range starts 08:45 on the 2nd, so the 2nd is half a day.
    PARTIAL = _meta(range_start="2026-01-02T07:45:00Z",
                    range_end="2026-01-05T00:00:00Z",
                    exported_at="2026-01-05T00:05:00Z")

    def test_a_partial_day_drops_its_sums(self) -> None:
        rows = hek.build_health_payload(_payload(
            meta=self.PARTIAL,
            daily=[{"date": "2026-01-02", "steps": 5926,
                    "activeEnergyKcal": 583.9, "exerciseMinutes": 33}],
        ), None, None)
        self.assertEqual(rows, [])

    def test_a_partial_day_keeps_its_non_sums(self) -> None:
        rows = hek.build_health_payload(_payload(
            meta=self.PARTIAL,
            daily=[{"date": "2026-01-02", "steps": 5926}],
            additional={"heart": {
                "units": {"restingHR": "bpm"},
                "aggregation": {"restingHR": "avg"},
                "daily": [{"date": "2026-01-02", "values": {"restingHR": 63}}],
            }},
        ), None, None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-01-02")
        self.assertEqual(rows[0]["resting_hr"], 63)
        self.assertNotIn("steps", rows[0])

    def test_a_fully_covered_day_keeps_its_sums(self) -> None:
        rows = hek.build_health_payload(_payload(
            meta=self.PARTIAL,
            daily=[{"date": "2026-01-03", "steps": 11082,
                    "activeEnergyKcal": 1066.3, "basalEnergyKcal": 2129.8,
                    "exerciseMinutes": 121}],
        ), None, None)
        self.assertEqual(rows[0]["steps"], 11082)
        self.assertEqual(rows[0]["active_energy_kcal"], 1066.3)
        self.assertEqual(rows[0]["basal_energy_kcal"], 2129.8)
        self.assertEqual(rows[0]["exercise_min"], 121)


class AbsentKeyTests(unittest.TestCase):

    def test_an_absent_key_is_not_written_as_zero(self) -> None:
        rows = hek.build_health_payload(_payload(
            daily=[{"date": "2026-01-02", "steps": 9995}],
        ), None, None)
        self.assertNotIn("exercise_min", rows[0])
        self.assertEqual(rows[0]["steps"], 9995)

    def test_an_absent_section_does_not_raise(self) -> None:
        rows = hek.build_health_payload(_payload(
            daily=[{"date": "2026-01-02", "steps": 100}],
            additional={},
        ), None, None)
        self.assertEqual(len(rows), 1)

    def test_a_requested_but_absent_category_does_not_raise(self) -> None:
        meta = _meta()
        meta["categories"] = ["activity", "nutrition"]
        rows = hek.build_health_payload(_payload(
            meta=meta, daily=[{"date": "2026-01-02", "steps": 100}],
        ), None, None)
        self.assertEqual(len(rows), 1)


class BreathingDisturbanceShiftTests(unittest.TestCase):
    """The export files the night's value on the day it began."""

    def test_the_value_moves_forward_one_day(self) -> None:
        rows = hek.build_health_payload(_payload(
            additional={"heart": {
                "units": {"breathingDisturbances": "count"},
                "aggregation": {"breathingDisturbances": "avg"},
                "daily": [{"date": "2026-01-02",
                           "values": {"breathingDisturbances": 0.9}}],
            }},
        ), None, None)
        by_date = {r["date"]: r for r in rows}
        self.assertNotIn("sleep_breath_dist", by_date.get("2026-01-02", {}))
        self.assertEqual(by_date["2026-01-03"]["sleep_breath_dist"], 0.9)


class HrvTests(unittest.TestCase):

    def test_daily_hrv_is_never_written(self) -> None:
        # The export has no all-day HRV. Writing the sleep-window value into
        # the historical column would corrupt the recovery baseline.
        rows = hek.build_health_payload(_payload(
            daily=[{"date": "2026-01-02", "steps": 100}],
        ), None, None)
        for row in rows:
            self.assertNotIn("hrv_sdnn", row)


class SinceUntilTests(unittest.TestCase):

    def test_rows_outside_the_window_are_dropped(self) -> None:
        payload = _payload(daily=[
            {"date": "2026-01-02", "steps": 1},
            {"date": "2026-01-03", "steps": 2},
            {"date": "2026-01-04", "steps": 3},
        ])
        rows = hek.build_health_payload(payload, date(2026, 1, 3), date(2026, 1, 3))
        self.assertEqual([r["date"] for r in rows], ["2026-01-03"])


class FixtureHealthTests(unittest.TestCase):

    def test_the_fixture_produces_one_row_per_date(self) -> None:
        rows = hek.build_health_payload(_load(), None, None)
        dates = [r["date"] for r in rows]
        self.assertEqual(len(dates), len(set(dates)))
        self.assertTrue(dates == sorted(dates))

    def test_no_row_is_date_only(self) -> None:
        for row in hek.build_health_payload(_load(), None, None):
            self.assertGreater(len(row), 1, f"date-only row: {row}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest tests.test_hek_import -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'shared.import_health_export_kit'`

- [ ] **Step 3: Write the implementation**

Create `Skills/shared/import_health_export_kit.py`:

```python
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
    "daylight", "mindful",
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m unittest tests.test_hek_import -v
```
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
cd Skills
git add shared/import_health_export_kit.py tests/test_hek_import.py
git commit -m "feat: Health Export Kit daily metrics reader

Daily sums are gated on full range coverage, breathing disturbances shift
forward a day to match stored history, absent keys stay absent, and daily
HRV is never written because the export does not have it."
```

---

## Task 4: Sleep night assembly

**Files:**
- Modify: `Skills/shared/import_health_export_kit.py`
- Test: `Skills/tests/test_hek_import.py`

**Interfaces:**
- Consumes: `hek_time.parse_stamp`.
- Produces:
  - `NIGHT_ROLLOVER_HOUR = 18`
  - `assemble_nights(payload: dict) -> dict[str, list[dict]]` — wake-date key to that night's sessions, ordered by start
  - `build_sleep_payload(payload: dict, since, until) -> list[dict]` — rows for `csv_store.upsert_sleep_nights`
  - `sleep_headline_rows(payload: dict, since, until) -> list[dict]` — the `sleep_total_h` / `sleep_deep_h` / `sleep_rem_h` / `time_in_bed_h` / `resp_rate` mirror written into `health_metrics.csv`

- [ ] **Step 1: Write the failing tests**

Append to `Skills/tests/test_hek_import.py`, before the `if __name__` block:

```python
def _session(start, end, stages, asleep=None, awake=0, vitals=None) -> dict:
    total = sum(s["durationSec"] for s in stages)
    asleep_sec = asleep if asleep is not None else sum(
        s["durationSec"] for s in stages if s["stage"] != "awake"
    )
    return {
        "start": start, "end": end,
        "durationSec": total,
        "asleepSec": asleep_sec,
        "awakeSec": awake,
        "source": "Apple\u00a0Watch",
        "stages": stages,
        "vitals": vitals or {},
    }


def _stage(stage, start, end, seconds) -> dict:
    return {"stage": stage, "start": start, "end": end, "durationSec": seconds}


class NightAssemblyTests(unittest.TestCase):
    """Reproduces the retired pipeline, verified on 224 of 224 stored nights."""

    META = _meta(range_start="2026-06-01T00:00:00Z",
                 range_end="2026-07-01T00:00:00Z",
                 exported_at="2026-07-01T00:05:00Z")

    def test_a_night_is_keyed_by_its_wake_date(self) -> None:
        p = _payload(meta=self.META, sessions=[
            _session("06-05 23:30:00", "06-06 07:00:00",
                     [_stage("asleepCore", "06-05 23:30:00", "06-06 07:00:00", 27000)]),
        ])
        self.assertEqual(sorted(hek.assemble_nights(p)), ["2026-06-06"])

    def test_a_session_starting_after_six_pm_belongs_to_the_next_night(self) -> None:
        # A 2026-06-27 20:25 nap is stored on the 2026-06-28 night row.
        p = _payload(meta=self.META, sessions=[
            _session("06-27 20:25:09", "06-27 22:34:34",
                     [_stage("asleepCore", "06-27 20:25:09", "06-27 22:34:34", 7765)]),
        ])
        self.assertEqual(sorted(hek.assemble_nights(p)), ["2026-06-28"])

    def test_a_split_night_merges_into_one_row(self) -> None:
        # 2026-06-07: 23:19->04:30 and 05:02->07:46 became one stored night
        # with total 5.97 h, in bed 8.44 h and 37 segments.
        p = _payload(meta=self.META, sessions=[
            _session("06-06 23:19:41", "06-07 04:30:41",
                     [_stage("asleepCore", "06-06 23:19:41", "06-07 04:30:41", 12129)],
                     asleep=12129, awake=6540),
            _session("06-07 05:02:50", "06-07 07:46:21",
                     [_stage("asleepCore", "06-07 05:02:50", "06-07 07:46:21", 9360)],
                     asleep=9360, awake=480),
        ])
        rows = hek.build_sleep_payload(p, None, None)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["date"], "2026-06-07")
        self.assertEqual(row["total_h"], round((12129 + 9360) / 3600, 2))
        # In bed spans the gap between the two sessions.
        self.assertEqual(row["time_in_bed_h"], round((8 * 3600 + 26 * 60 + 40) / 3600, 2))
        self.assertEqual(row["n_segments"], 2)
        self.assertEqual(row["first_segment_start"], "2026-06-06 23:19:41")
        self.assertEqual(row["last_segment_end"], "2026-06-07 07:46:21")

    def test_the_gap_between_sessions_is_in_bed_but_not_awake(self) -> None:
        p = _payload(meta=self.META, sessions=[
            _session("06-06 23:19:41", "06-07 04:30:41",
                     [_stage("asleepCore", "06-06 23:19:41", "06-07 04:30:41", 12129)],
                     asleep=12129, awake=6540),
            _session("06-07 05:02:50", "06-07 07:46:21",
                     [_stage("asleepCore", "06-07 05:02:50", "06-07 07:46:21", 9360)],
                     asleep=9360, awake=480),
        ])
        row = hek.build_sleep_payload(p, None, None)[0]
        self.assertEqual(row["awake_h"], round((6540 + 480) / 3600, 2))

    def test_stage_totals_come_from_the_stage_intervals(self) -> None:
        p = _payload(meta=self.META, sessions=[
            _session("06-05 23:00:00", "06-06 06:00:00", [
                _stage("asleepCore", "06-05 23:00:00", "06-06 01:00:00", 7200),
                _stage("asleepDeep", "06-06 01:00:00", "06-06 02:00:00", 3600),
                _stage("asleepREM", "06-06 02:00:00", "06-06 03:00:00", 3600),
                _stage("awake", "06-06 03:00:00", "06-06 03:10:00", 600),
                _stage("asleepCore", "06-06 03:10:00", "06-06 06:00:00", 10200),
            ]),
        ])
        row = hek.build_sleep_payload(p, None, None)[0]
        self.assertEqual(row["core_h"], round(17400 / 3600, 2))
        self.assertEqual(row["deep_h"], 1.0)
        self.assertEqual(row["rem_h"], 1.0)
        self.assertEqual(row["n_segments"], 5)

    def test_the_clock_correction_is_applied_to_sleep_stamps(self) -> None:
        m = _meta(range_start="2026-01-01T00:00:00Z",
                  range_end="2026-08-30T07:22:53Z",
                  exported_at="2026-08-30T07:25:07Z")
        p = _payload(meta=m, sessions=[
            _session("03-27 22:19:41", "03-28 06:30:41",
                     [_stage("asleepCore", "03-27 22:19:41", "03-28 06:30:41", 29460)]),
        ])
        row = hek.build_sleep_payload(p, None, None)[0]
        self.assertEqual(row["first_segment_start"], "2026-03-27 23:19:41")
        self.assertEqual(row["last_segment_end"], "2026-03-28 07:30:41")


class SleepHeadlineTests(unittest.TestCase):

    META = NightAssemblyTests.META

    def test_the_headline_mirror_carries_respiratory_rate_from_sleep_vitals(self) -> None:
        p = _payload(meta=self.META, sessions=[
            _session("06-05 23:00:00", "06-06 06:00:00",
                     [_stage("asleepCore", "06-05 23:00:00", "06-06 06:00:00", 25200)],
                     vitals={"respiratoryRate": {"avg": 14.5, "unit": "brpm"}}),
        ])
        rows = hek.sleep_headline_rows(p, None, None)
        self.assertEqual(rows[0]["date"], "2026-06-06")
        self.assertEqual(rows[0]["resp_rate"], 14.5)
        self.assertEqual(rows[0]["sleep_total_h"], 7.0)
        self.assertEqual(rows[0]["time_in_bed_h"], 7.0)


class FixtureSleepTests(unittest.TestCase):

    def test_every_fixture_night_has_a_span_at_least_as_long_as_its_sleep(self) -> None:
        for row in hek.build_sleep_payload(_load(), None, None):
            self.assertGreaterEqual(row["time_in_bed_h"], row["total_h"])

    def test_the_fixture_contains_a_merged_night(self) -> None:
        rows = hek.build_sleep_payload(_load(), None, None)
        self.assertTrue(any(r["n_segments"] and r["n_segments"] > 10 for r in rows))
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest tests.test_hek_import -v
```
Expected: FAIL with `AttributeError: module 'shared.import_health_export_kit' has no attribute 'assemble_nights'`

- [ ] **Step 3: Write the implementation**

Append to `Skills/shared/import_health_export_kit.py`:

```python
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
    two rules below reproduce the retired pipeline exactly — checked against
    all 224 stored night rows with no field mismatching on any night.
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


def build_sleep_payload(payload: dict,
                        since: date | None,
                        until: date | None) -> list[dict]:
    """Rows for ``upsert_sleep_nights``, one per night."""
    rows: list[dict] = []
    for key, sessions in sorted(assemble_nights(payload).items()):
        day = date.fromisoformat(key)
        if not _in_window(day, since, until):
            continue
        stage_seconds: dict[str, float] = {}
        for session in sessions:
            for stage in session.get("stages") or []:
                name = stage.get("stage")
                stage_seconds[name] = stage_seconds.get(name, 0.0) + stage.get("durationSec", 0)

        asleep = sum(s.get("asleepSec") or 0 for s in sessions)
        awake = sum(s.get("awakeSec") or 0 for s in sessions)
        # In bed is the whole span, gaps between sessions included. The gap
        # itself is not counted as awake time.
        in_bed = (sessions[-1]["_end"] - sessions[0]["_start"]).total_seconds()

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
        stage_seconds: dict[str, float] = {}
        for session in sessions:
            for stage in session.get("stages") or []:
                name = stage.get("stage")
                stage_seconds[name] = stage_seconds.get(name, 0.0) + stage.get("durationSec", 0)
        asleep = sum(s.get("asleepSec") or 0 for s in sessions)
        in_bed = (sessions[-1]["_end"] - sessions[0]["_start"]).total_seconds()

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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m unittest tests.test_hek_import -v
```
Expected: PASS, 21 tests.

- [ ] **Step 5: Commit**

```bash
cd Skills
git add shared/import_health_export_kit.py tests/test_hek_import.py
git commit -m "feat: Health Export Kit sleep night assembly

Sessions are per session, not per night. Sessions starting at or after 18:00
roll to the following night; the rest key on wake date; all sessions for one
night merge, with the gap between them counted as in bed but not as awake.
Reproduces all 224 stored nights with no field mismatching."
```

---

## Task 5: Workouts and the type map

**Files:**
- Modify: `Skills/shared/apple_workout_types.py`
- Modify: `Skills/shared/import_health_export_kit.py`
- Test: `Skills/tests/test_hek_import.py`

**Interfaces:**
- Consumes: `hek_time.parse_stamp`, `apple_workout_types.HEK_TYPE_MAP`.
- Produces:
  - `apple_workout_types.HEK_TYPE_MAP: dict[tuple[str, bool], str]`
  - `apple_workout_types.hek_canonical_type(raw: str, is_indoor: bool | None) -> str`
  - `import_health_export_kit.normalize_source(value: str | None) -> str | None`
  - `import_health_export_kit.humidity_percent(raw: float | None) -> float | None`
  - `import_health_export_kit.build_workout_payload(payload, since, until) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

Append to `Skills/tests/test_hek_import.py`:

```python
class TypeMapTests(unittest.TestCase):
    """Verified against 663 stored workouts; no combination fell through."""

    CASES = [
        ("Walking", False, "Walking"),
        ("Walking", True, "IndoorWalking"),
        ("Strength Training", False, "TraditionalStrengthTraining"),
        ("Functional Strength", False, "FunctionalStrengthTraining"),
        ("Core Training", False, "CoreTraining"),
        ("Running", True, "IndoorRunning"),
        ("Running", False, "Running"),
        ("Cycling", True, "IndoorCycling"),
        ("Cycling", False, "Cycling"),
        ("HIIT", False, "HighIntensityIntervalTraining"),
        ("Swimming", True, "Swimming"),
        ("Swimming", False, "Swimming"),
        ("Hiking", False, "Hiking"),
        ("Rowing", True, "Rowing"),
    ]

    def test_every_observed_combination_maps(self) -> None:
        from shared import apple_workout_types as awt
        for raw, indoor, expected in self.CASES:
            with self.subTest(raw=raw, indoor=indoor):
                self.assertEqual(awt.hek_canonical_type(raw, indoor), expected)

    def test_a_missing_indoor_flag_is_treated_as_outdoor(self) -> None:
        from shared import apple_workout_types as awt
        self.assertEqual(awt.hek_canonical_type("Hiking", None), "Hiking")

    def test_an_unknown_type_still_produces_a_storable_name(self) -> None:
        from shared import apple_workout_types as awt
        self.assertEqual(awt.hek_canonical_type("Water Polo", False), "WaterPolo")


class WorkoutFieldTests(unittest.TestCase):

    META = _meta(range_start="2026-08-01T00:00:00Z",
                 range_end="2026-08-30T00:00:00Z",
                 exported_at="2026-08-30T00:05:00Z")

    WORKOUT = {
        "start": "08-02 15:54:27", "end": "08-02 17:15:42",
        "type": "Strength Training", "isIndoor": False,
        "durationSec": 4875,
        "averageHeartRateBpm": 105, "maxHeartRateBpm": 147,
        "minHeartRateBpm": 85,
        "activeEnergyKcal": 388, "totalEnergyKcal": 525.5,
        "basalEnergyKcal": 137.5,
        "source": "Apple\u00a0Watch",
        "weatherHumidityPercent": 4200, "weatherTemperatureC": 24.6,
    }

    def _one(self, **overrides) -> dict:
        w = {**self.WORKOUT, **overrides}
        rows = hek.build_workout_payload(
            _payload(meta=self.META, workouts=[w]), None, None
        )
        return rows[0]

    def test_core_fields_map_straight_across(self) -> None:
        row = self._one()
        self.assertEqual(row["date"], "2026-08-02")
        self.assertEqual(row["start"], "15:54:27")
        self.assertEqual(row["end"], "17:15:42")
        self.assertEqual(row["apple_type"], "TraditionalStrengthTraining")
        self.assertEqual(row["duration_min"], 81.2)
        self.assertEqual(row["avg_hr"], 105)
        self.assertEqual(row["max_hr"], 147)
        self.assertEqual(row["min_hr"], 85)
        self.assertEqual(row["active_cal"], 388)

    def test_the_non_breaking_space_in_source_is_normalized(self) -> None:
        self.assertEqual(self._one()["source"], "Apple Watch")

    def test_a_workout_with_no_heart_rate_is_stored_without_one(self) -> None:
        row = self._one(averageHeartRateBpm=None)
        del row
        w = {k: v for k, v in self.WORKOUT.items()
             if k not in ("averageHeartRateBpm", "maxHeartRateBpm", "minHeartRateBpm")}
        rows = hek.build_workout_payload(
            _payload(meta=self.META, workouts=[w]), None, None
        )
        self.assertNotIn("avg_hr", rows[0])
        self.assertEqual(rows[0]["apple_type"], "TraditionalStrengthTraining")

    def test_a_workout_with_no_start_is_dropped(self) -> None:
        w = {k: v for k, v in self.WORKOUT.items() if k != "start"}
        rows = hek.build_workout_payload(
            _payload(meta=self.META, workouts=[w]), None, None
        )
        self.assertEqual(rows, [])

    def test_zero_distance_is_treated_as_absent(self) -> None:
        rows = hek.build_workout_payload(
            _payload(meta=self.META, workouts=[{**self.WORKOUT, "distanceKm": 0}]),
            None, None,
        )
        self.assertNotIn("distance_km", rows[0])


class HumidityTests(unittest.TestCase):
    """The field is named Percent but carries basis points. An app bug."""

    def test_basis_points_are_divided(self) -> None:
        self.assertEqual(hek.humidity_percent(4200), 42.0)
        self.assertEqual(hek.humidity_percent(8700), 87.0)

    def test_a_real_percent_is_left_alone(self) -> None:
        self.assertEqual(hek.humidity_percent(42), 42)

    def test_absent_stays_absent(self) -> None:
        self.assertIsNone(hek.humidity_percent(None))


class FixtureWorkoutTests(unittest.TestCase):

    def test_every_fixture_workout_produces_a_row_with_a_type(self) -> None:
        rows = hek.build_workout_payload(_load(), None, None)
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row["apple_type"])
            self.assertTrue(row["date"])
            self.assertTrue(row["start"])

    def test_workout_starts_are_unique_per_date(self) -> None:
        rows = hek.build_workout_payload(_load(), None, None)
        keys = [(r["date"], r["start"]) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest tests.test_hek_import -v
```
Expected: FAIL with `AttributeError: module 'shared.apple_workout_types' has no attribute 'hek_canonical_type'`

- [ ] **Step 3: Add the type map**

Append to `Skills/shared/apple_workout_types.py`:

```python
# ------------------------------------------- Health Export Kit type names
# Health Export Kit uses its own display names and carries indoor/outdoor
# as a separate boolean, where HealthAutoExport folded both into one string
# ("Indoor Run", "Outdoor Walk"). Every pair below was confirmed by matching
# 663 stored workouts against a full-history export; no observed combination
# fell through to the fallback.
HEK_TYPE_MAP: dict[tuple[str, bool], str] = {
    ("Walking", False):            "Walking",
    ("Walking", True):             "IndoorWalking",
    ("Running", False):            "Running",
    ("Running", True):             "IndoorRunning",
    ("Cycling", False):            "Cycling",
    ("Cycling", True):             "IndoorCycling",
    ("Swimming", False):           "Swimming",
    ("Swimming", True):            "Swimming",
    ("Hiking", False):             "Hiking",
    ("Hiking", True):              "Hiking",
    ("Rowing", False):             "Rowing",
    ("Rowing", True):              "Rowing",
    ("HIIT", False):               "HighIntensityIntervalTraining",
    ("HIIT", True):                "HighIntensityIntervalTraining",
    ("Strength Training", False):  "TraditionalStrengthTraining",
    ("Strength Training", True):   "TraditionalStrengthTraining",
    ("Functional Strength", False): "FunctionalStrengthTraining",
    ("Functional Strength", True):  "FunctionalStrengthTraining",
    ("Core Training", False):      "CoreTraining",
    ("Core Training", True):       "CoreTraining",
}


def hek_canonical_type(raw: str, is_indoor: bool | None) -> str:
    """Canonical stored name for a Health Export Kit workout.

    ``is_indoor`` is absent on a small number of workouts (1 of 698 in the
    reference export); absent reads as outdoor, which is the safe default
    for every type whose indoor variant is a distinct stored name.

    An unmapped type still produces a storable name rather than raising, the
    way the retired importer handled types it had never seen: the workout
    lands in Workout Sessions, it just misses auto-cardio handling until
    someone adds it here.
    """
    indoor = bool(is_indoor)
    mapped = HEK_TYPE_MAP.get((raw, indoor))
    if mapped:
        return mapped
    return (raw or "").replace(" ", "")
```

- [ ] **Step 4: Add the workout reader**

Append to `Skills/shared/import_health_export_kit.py`:

```python
# --------------------------------------------------------------- workouts

from shared.apple_workout_types import hek_canonical_type  # noqa: E402


def normalize_source(value: str | None) -> str | None:
    """Apple writes "Apple Watch" with a non-breaking space. Flatten it."""
    if value is None:
        return None
    # The escape, never the literal character. An invisible U+00A0 does not
    # survive transcription and a reviewer cannot see it: a previous pass of
    # this line silently became replace(" ", " ") and did nothing to 696 of
    # 698 real rows, while its test passed because the test fixture had lost
    # the character too.
    return value.replace("\u00a0", " ").strip()


def humidity_percent(raw: float | None) -> float | None:
    """``weatherHumidityPercent`` carries basis points, not percent.

    Observed range across two people and 250 workouts: 2,600 to 8,700. The
    guard keeps the function correct if the app is ever fixed.
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
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python3 -m unittest tests.test_hek_import -v
```
Expected: PASS, 33 tests.

- [ ] **Step 6: Commit**

```bash
cd Skills
git add shared/apple_workout_types.py shared/import_health_export_kit.py tests/test_hek_import.py
git commit -m "feat: Health Export Kit workout reader and type map

Health Export Kit splits indoor/outdoor into a separate boolean where
HealthAutoExport folded it into the type string. Every pair in the map was
confirmed against 663 stored workouts. Also normalizes the non-breaking
space Apple writes into source names, and divides the humidity field, which
carries basis points despite its name."
```

---

## Task 6: Swim workouts

**Files:**
- Modify: `Skills/shared/import_health_export_kit.py`
- Test: `Skills/tests/test_hek_import.py`

**Interfaces:**
- Consumes: `build_workout_payload`'s parsing helpers.
- Produces: `build_swim_payload(payload, since, until) -> list[dict]` — rows for `csv_store.upsert_swim_workouts`.

- [ ] **Step 1: Write the failing tests**

Append to `Skills/tests/test_hek_import.py`:

```python
class SwimTests(unittest.TestCase):

    META = _meta(range_start="2026-07-01T00:00:00Z",
                 range_end="2026-07-31T00:00:00Z",
                 exported_at="2026-07-31T00:05:00Z")

    SWIM = {
        "start": "07-25 12:30:45", "end": "07-25 12:45:12",
        "type": "Swimming", "isIndoor": False,
        "durationSec": 864, "distanceKm": 0.38,
        "averageHeartRateBpm": 128, "activeEnergyKcal": 127,
        "source": "Apple\u00a0Watch",
        "events": ([{"type": "lap", "start": "07-25 12:31:00",
                     "end": "07-25 12:31:20"}] * 19)
                  + [{"type": "pause", "start": "07-25 12:45:12",
                      "end": "07-25 12:45:12"}],
    }

    def _one(self, **overrides) -> dict:
        rows = hek.build_swim_payload(
            _payload(meta=self.META, workouts=[{**self.SWIM, **overrides}]),
            None, None,
        )
        return rows[0]

    def test_laps_are_counted_from_lap_events(self) -> None:
        # 19 laps on 2026-07-25, matching the stored swimming file exactly.
        self.assertEqual(self._one()["laps"], 19)

    def test_pause_events_are_not_counted_as_laps(self) -> None:
        row = self._one(events=[{"type": "pause", "start": "07-25 12:45:12",
                                 "end": "07-25 12:45:12"}])
        self.assertIsNone(row.get("laps"))

    def test_location_is_never_written_whatever_the_indoor_flag_says(self) -> None:
        # isIndoor disagrees with stored history on 24 of 27 real swims, and
        # every swim it marks indoor carries a GPS route, which a pool swim
        # does not produce. The store sparse-merges, so writing this column
        # would overwrite correct history with a guess.
        for indoor in (True, False, "absent"):
            with self.subTest(isIndoor=indoor):
                w = dict(self.SWIM)
                if indoor == "absent":
                    w.pop("isIndoor", None)
                else:
                    w["isIndoor"] = indoor
                rows = hek.build_swim_payload(
                    _payload(meta=self.META, workouts=[w]), None, None)
                self.assertNotIn("location", rows[0])

    def test_fields_with_no_source_are_left_unset(self) -> None:
        row = self._one()
        for field in ("pool_length_m", "strokes", "spl", "avg_swolf",
                      "stroke_mix", "water_temp_c", "location"):
            self.assertNotIn(field, row)

    def test_only_swims_are_returned(self) -> None:
        rows = hek.build_swim_payload(_payload(meta=self.META, workouts=[
            self.SWIM,
            {"start": "07-25 18:00:00", "end": "07-25 18:30:00",
             "type": "Walking", "isIndoor": False, "durationSec": 1800},
        ]), None, None)
        self.assertEqual(len(rows), 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest tests.test_hek_import -v
```
Expected: FAIL with `AttributeError: ... has no attribute 'build_swim_payload'`

- [ ] **Step 3: Write the implementation**

Append to `Skills/shared/import_health_export_kit.py`:

```python
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

    ``Location`` is deliberately NOT written. ``isIndoor`` looks like the
    signal for it and is not: measured against stored history it disagrees on
    24 of 27 swims, every swim it marks indoor carries a GPS route of 39 to
    287 points (a pool swim produces none), and 18 of the disagreements are
    stored as "Outdoor Pool", a third value a boolean cannot express. Since
    the store sparse-merges, writing it would rewrite 24 correct values with
    wrong ones. The retired importer refused to guess here too.
    """
    meta = payload["meta"]
    rows: list[dict] = []
    for workout in (payload.get("activity") or {}).get("workouts") or []:
        if (workout.get("type") or "") not in SWIM_TYPES:
            continue
        raw_start = workout.get("start")
        if not raw_start:
            continue
        start = hek_time.parse_stamp(raw_start, meta)
        if not _in_window(start.date(), since, until):
            continue

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
        if workout.get("distanceKm"):
            row["distance_km"] = workout["distanceKm"]
        if workout.get("averageHeartRateBpm") is not None:
            row["avg_hr"] = workout["averageHeartRateBpm"]
        if workout.get("activeEnergyKcal") is not None:
            row["active_cal"] = workout["activeEnergyKcal"]

        laps = sum(1 for e in workout.get("events") or [] if e.get("type") == "lap")
        if laps:
            row["laps"] = laps

        # No `location`. See the docstring: isIndoor is wrong on 24 of 27 real
        # swims, and the store sparse-merges, so writing it destroys history.

        rows.append(row)
    rows.sort(key=lambda r: (r["date"], r["start"]))
    return rows
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m unittest tests.test_hek_import -v
```
Expected: PASS, 40 tests.

- [ ] **Step 5: Commit**

```bash
cd Skills
git add shared/import_health_export_kit.py tests/test_hek_import.py
git commit -m "feat: Health Export Kit swim reader

Lap counts come from lap events and match the historical per-lap files
exactly on all 17 swims that have them. Pool length, stroke count, SPL,
water temperature and Location have no usable source and stay unset so
sparse merge preserves history. Location in particular looks like it has
one -- isIndoor -- which disagrees with stored history on 24 of 27 swims."
```

---

## Task 7: Orchestration, CLI and source capabilities

**Files:**
- Modify: `Skills/shared/import_health_export_kit.py`
- Modify: `Skills/workout-coach/lib/constants.py:39`
- Test: `Skills/tests/test_hek_import.py`

**Interfaces:**
- Consumes: every `build_*` function above, plus the existing store functions
  `ensure_profile`, `write_profile`, `read_profile`, `upsert_health_metrics`,
  `upsert_sleep_nights`, `upsert_swim_workouts`, `upsert_workout_sessions`,
  `upsert_monthly_cardio`, `upsert_monthly_strength_session`, `commit_data`.
- Produces:
  - `class EmptyImportError(RuntimeError)`
  - `read_export(path: Path) -> dict`
  - `resolve_export(pattern: str | None) -> Path | None`
  - `import_export(person, export_path, since, until, *, allow_past_months=False, dry_run=False, keep_export=False) -> list[str]`
  - `main() -> int`
  - `SOURCE_CAPABILITIES["health_export_kit"]`

- [ ] **Step 1: Write the failing tests**

Append to `Skills/tests/test_hek_import.py`:

```python
import tempfile

from shared import csv_store, person_paths


class SchemaGuardTests(unittest.TestCase):
    """Payload keys must exist in the store's field list, or they vanish."""

    def test_health_payload_keys_are_all_real_columns(self) -> None:
        from shared.csv_store_dense import HEALTH_METRICS_FIELDS
        allowed = set(HEALTH_METRICS_FIELDS) | {"date"}
        payload = _load()
        rows = hek.build_health_payload(payload, None, None)
        rows += hek.sleep_headline_rows(payload, None, None)
        for row in rows:
            self.assertLessEqual(set(row), allowed, f"unknown key in {row}")

    def test_workout_payload_keys_are_all_real_columns(self) -> None:
        from shared.csv_store_dense import WORKOUT_SESSIONS_FIELDS
        allowed = set(WORKOUT_SESSIONS_FIELDS) | {"date"}
        for row in hek.build_workout_payload(_load(), None, None):
            self.assertLessEqual(set(row), allowed, f"unknown key in {row}")

    def test_sleep_payload_keys_are_all_real_columns(self) -> None:
        from shared.csv_store_periodic import SLEEP_NIGHTS_FIELDS
        allowed = set(SLEEP_NIGHTS_FIELDS) | {"date"}
        for row in hek.build_sleep_payload(_load(), None, None):
            self.assertLessEqual(set(row), allowed, f"unknown key in {row}")

    def test_swim_payload_keys_are_all_real_columns(self) -> None:
        from shared.csv_store_periodic import SWIM_WORKOUTS_FIELDS
        allowed = set(SWIM_WORKOUTS_FIELDS) | {"date"}
        for row in hek.build_swim_payload(_load(), None, None):
            self.assertLessEqual(set(row), allowed, f"unknown key in {row}")


class ImportExportTests(unittest.TestCase):
    """End to end against a temp tracker root, run twice for idempotency."""

    def _run_twice(self, **kwargs) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = person_paths.WORKOUT_TRACKER_ROOT
            old_hek_root = hek.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = root
            hek.WORKOUT_TRACKER_ROOT = root
            try:
                export = root / "health-export-json-2026-01-01-0000_to_2026-08-30-0000.json"
                export.write_text(FIXTURE.read_text())
                call = dict(person="Test", export_path=export,
                            since=None, until=None,
                            allow_past_months=True, dry_run=False,
                            keep_export=True)
                call.update(kwargs)
                hek.import_export(**call)
                hek.import_export(**call)
                return {
                    "profile": csv_store.read_profile("Test"),
                    "health": csv_store.read_health_metrics("Test"),
                    "sessions": csv_store.read_workout_sessions("Test"),
                    "sleep": csv_store.read_sleep_nights("Test"),
                }
            finally:
                person_paths.WORKOUT_TRACKER_ROOT = old_root
                hek.WORKOUT_TRACKER_ROOT = old_hek_root

    def test_a_second_identical_import_changes_nothing(self) -> None:
        got = self._run_twice()
        dates = [r["date"] for r in got["health"]]
        self.assertEqual(len(dates), len(set(dates)))
        keys = [(r["date"], r["start"]) for r in got["sessions"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_profile_source_is_pinned(self) -> None:
        self.assertEqual(self._run_twice()["profile"]["source"], "health_export_kit")

    def test_sleep_efficiency_is_derived_by_the_store(self) -> None:
        for row in self._run_twice()["sleep"]:
            if row.get("total_h") and row.get("time_in_bed_h"):
                self.assertIsNotNone(row.get("efficiency_pct"))

    def test_an_empty_export_raises_rather_than_writing_nothing_quietly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_root = person_paths.WORKOUT_TRACKER_ROOT
            old_hek_root = hek.WORKOUT_TRACKER_ROOT
            person_paths.WORKOUT_TRACKER_ROOT = root
            hek.WORKOUT_TRACKER_ROOT = root
            try:
                export = root / "health-export-json-empty.json"
                export.write_text(json.dumps(_payload()))
                with self.assertRaises(hek.EmptyImportError):
                    hek.import_export("Test", export, None, None,
                                      keep_export=True)
            finally:
                person_paths.WORKOUT_TRACKER_ROOT = old_root
                hek.WORKOUT_TRACKER_ROOT = old_hek_root


class CapabilityTests(unittest.TestCase):

    def test_the_new_source_declares_no_daily_hrv_and_no_wrist_temp(self) -> None:
        from workout_coach.lib.constants import SOURCE_CAPABILITIES
        caps = SOURCE_CAPABILITIES["health_export_kit"]
        self.assertFalse(caps["hrv"])
        self.assertFalse(caps["wrist_temp"])
        self.assertTrue(caps["sleep_stages"])
        self.assertTrue(caps["sleep_regularity"])
        self.assertTrue(caps["sleep_nights"])

    def test_it_declares_the_same_keys_as_the_retired_source(self) -> None:
        from workout_coach.lib.constants import SOURCE_CAPABILITIES
        self.assertEqual(
            set(SOURCE_CAPABILITIES["health_export_kit"]),
            set(SOURCE_CAPABILITIES["health_auto_export"]),
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m unittest tests.test_hek_import -v
```
Expected: FAIL with `AttributeError: ... has no attribute 'WORKOUT_TRACKER_ROOT'`

- [ ] **Step 3: Add the source capabilities**

In `Skills/workout-coach/lib/constants.py`, inside the `SOURCE_CAPABILITIES` dict and after the closing brace of the `"health_auto_export"` entry, add:

```python
    "health_export_kit": {
        # No all-day HRV in this format at all. The sleep-window value is a
        # different measurement (two to four readings a night, four times
        # the variance) and lives in its own column, so the historical
        # signal is off rather than silently rebased.
        "hrv":                False,
        # One reading in thirty nights across two people. Effectively gone.
        "wrist_temp":         False,
        "resting_hr_daily":   True,
        "walking_hr":         True,
        "sleep_stages":       True,
        "sleep_breath_dist":  True,
        # Per-night architecture is richer here than any prior source: the
        # export carries every stage interval, so N Segments is populated
        # again after HealthAutoExport stopped supplying it.
        "sleep_nights":       True,
        "sleep_regularity":   True,
        "exercise_min_daily": True,
        "per_workout_hr_strength": True,
        "thermal_log":        True,
        "light_therapy_log":  True,
    },
```

- [ ] **Step 4: Write the orchestration**

Append to `Skills/shared/import_health_export_kit.py`:

```python
# --------------------------------------------------------- orchestration

import argparse  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from shared.apple_workout_types import (  # noqa: E402
    APPLE_TO_TRACKER_EXERCISE,
    CARDIO_AUTOLOG_TYPES,
)
from shared.csv_store import (  # noqa: E402
    ensure_profile,
    read_profile,
    upsert_health_metrics,
    upsert_sleep_nights,
    upsert_swim_workouts,
    upsert_workout_sessions,
    write_profile,
)
from shared.data_git import commit_data  # noqa: E402
from shared.monthly_csv_upsert import (  # noqa: E402
    upsert_monthly_cardio,
    upsert_monthly_strength_session,
)
from shared.person_paths import WORKOUT_TRACKER_ROOT  # noqa: E402
from shared.strength_sessions import cluster_strength_sessions  # noqa: E402
from tracker.importing import build_auto_cardio_payload  # noqa: E402

EXPORT_GLOB = "health-export-json-*.json"


class EmptyImportError(RuntimeError):
    """The export parsed cleanly but produced nothing.

    Almost always the wrong date window rather than a broken file, so it is
    an error the caller surfaces rather than a silent no-op.
    """


def read_export(path: Path) -> dict:
    payload = json.loads(path.read_text())
    meta = payload.get("meta") or {}
    if meta.get("schemaVersion") != 1:
        raise ValueError(
            f"{path.name}: unsupported schemaVersion "
            f"{meta.get('schemaVersion')!r}; this reader handles 1"
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
```

- [ ] **Step 5: Run the full suite**

```bash
python3 -m unittest discover -s tests -v
```
Expected: PASS. The new tests total 48; every pre-existing test must still pass, since nothing existing was modified except an addition to `SOURCE_CAPABILITIES` and an addition to `apple_workout_types.py`.

- [ ] **Step 6: Dry-run against the real backfill**

```bash
cd "<workout-tracker-root>"
python3 Skills/shared/import_health_export_kit.py \
  --person <Person> --export <person>-backfill.json --dry-run
```
Expected: roughly 242 health metric days, 232 sleep nights, 698 workouts, 27 swim
workouts, and the line `nothing written`. If any count is far off, stop and
diagnose before continuing — do not proceed to a real write.

- [ ] **Step 7: Commit**

```bash
cd Skills
git add shared/import_health_export_kit.py workout-coach/lib/constants.py tests/test_hek_import.py
git commit -m "feat: Health Export Kit orchestration, CLI and capabilities

Mirrors import_archive's contract: profile pin, sparse-merge upserts,
auto-cardio, strength clustering, one commit per import. The new source
declares hrv and wrist_temp false, because this format genuinely has
neither, so the coach reports them as missing rather than silently
rebasing them."
```

---

## Task 8: Point the automatic refresh at the new importer

**Files:**
- Modify: `Skills/workout-logger/SKILL.md:102-116` and `:154`

This is the switchover. `import_health_auto_export.py` stays on disk until Plan 2 retires it, so the change is reversible by reverting this one file.

- [ ] **Step 1: Verify the new importer works end to end on real data first**

Take a backup, then run for real against a short window:

```bash
cd "<workout-tracker-root>"
cp -R <Person>/data /tmp/tracker-data-backup-$(date +%Y%m%d%H%M)
python3 Skills/shared/import_health_export_kit.py \
  --person <Person> --export <person>-backfill.json \
  --since 2026-08-24 --until 2026-08-29 \
  --allow-past-months --keep-export
```

Expected: summary lines for Health Metrics, Sleep Nights, Workout Sessions and a
`Committed <Person> data:` line. These are the days after the pipeline broke, so
they should be new rows rather than edits to existing ones.

- [ ] **Step 2: Confirm the written rows against the export**

```bash
cd "<workout-tracker-root>"
python3 - <<'PY'
import csv, json
rows = {r["Date"]: r for r in csv.DictReader(open("<Person>/data/health_metrics.csv"))}
src = {r["date"]: r for r in json.load(open("<person>-backfill.json"))["activity"]["daily"]}
for d in ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28", "2026-08-29"]:
    r, s = rows.get(d, {}), src.get(d, {})
    print(d, "steps", r.get("Steps"), "vs", s.get("steps"),
          "| active", r.get("Active Energy (kcal)"), "vs", s.get("activeEnergyKcal"),
          "| HRV", repr(r.get("HRV SDNN")))
PY
```

Expected: steps and active energy match the export exactly on all six days, and
`HRV SDNN` is empty on all six, since the new importer never writes it.

- [ ] **Step 3: Update the skill instructions**

In `Skills/workout-logger/SKILL.md`, replace the command in step 6 with:

```
python3 Skills/shared/import_health_export_kit.py --person <Person>
```

and replace the surrounding prose so it reads:

```
   That is the only importer. It auto-resolves the export from the workout-tracker root (one above the per-person folders): `./health-export-json-*.json`, **most recent by mtime wins**. There is no second file shape and no dispatch decision to make.

   If no export is there, the importer prints `ERROR: Health Export Kit file not found: health-export-json-*.json` and exits 1 — surface that one line to the user and finish. A missing export just means the user didn't drop one this time.

   It imports whatever range the export itself covers, so `/log` passes `--person` and nothing else.
```

Update the matching sentence at line 154 so the error string and the glob match.

- [ ] **Step 4: Check no stale reference to the old command survives**

```bash
cd Skills
grep -rn "import_health_auto_export\|HealthAutoExport\*.zip" workout-logger/
```
Expected: no matches. If any remain, fix them before committing.

- [ ] **Step 5: Commit**

```bash
cd Skills
git add workout-logger/SKILL.md
git commit -m "feat: point the /log health refresh at Health Export Kit

The old importer stays on disk until Plan 2 retires it, so reverting this
one file restores the previous behaviour."
```

---

## Self-Review

Checked against `Skills/docs/specs/2026-08-30-health-export-kit.md`:

**Covered by this plan:** §2 format and compact choice (Task 2 fixture, Task 3 reader);
§5.1 clock shift and guard (Task 1); §5.2 partial edge days (Tasks 1, 3); §5.3 breathing
disturbance shift (Task 3); §5.4 humidity (Task 5); §5.5 absent keys (Tasks 3, 5, 6);
§5.7 non-breaking space (Task 5); §6.1 year reconstruction (Task 1); §6.2 aggregation maps
(Task 3); §6.4 night assembly (Task 4); §6.5 idempotency (Task 7); §4.2 and §4.3 workouts
and type map (Task 5); §4.4 swims (Task 6); §7.1 not writing daily HRV (Tasks 3, 7).

**Deliberately deferred, with the plan that owns each:**
- §4.1 new columns `Sleep HRV SDNN`, `Daylight (min)`, `Mindful (min)`, walking quality → Plan 3.
- §4.5 sleep architecture store → Plan 3.
- §4.6 per-workout time in zone → Plan 3.
- §5.6 the second tracker's minute-truncated timestamps → Plan 2. It only matters when re-importing
  his history, which this plan does not do.
- §7 doc corrections in `PROJECT.md` and `CLAUDE.md`, and retiring
  `import_health_auto_export.py` → Plan 2.
- §10.1 the second tracker's backfill file → Plan 2.

**Not addressed anywhere, by decision:** `stateOfMind` and `height` have no store planned
(spec §8). ECG has no store in Plans 1 to 3; the spec records that it is now available.

**Verification already done on this plan:** Task 1's implementation and its 13 tests were
extracted from this document and run before the plan shipped. They pass. No other task's
code has been executed.

**Known weakness:** `hek_time.parse_stamp` calls `resolve_year` and `export_offset` on every timestamp, which
is roughly 700 workouts plus 235 sessions plus their stages per import. That is fine at
this scale — the whole file parses in 0.13 seconds — but if a future full-history import
feels slow, memoize `export_offset` per meta dict first.
