"""W1 acceptance: nothing in the payload may be dated after ``--today``.

The whole backtesting story rests on this. Before the fix, every reader in
``extract`` handed back its entire CSV regardless of ``--today``, so a run
anchored on 2026-06-01 reported a late-July top set and an August weigh-in,
and ten payload blocks came back byte-identical across a seven-week anchor
gap. The test is deliberately GENERIC — it walks the emitted JSON for
ISO-8601 date strings rather than naming fields — so a series builder added
later cannot quietly reintroduce the leak.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[1]
READ_TRACKER = SKILLS_ROOT / "workout-coach" / "scripts" / "read_tracker.py"

_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")

PERSON = "person_horizon"

MONTHLY_HEADER = (
    "SESSION,Date,#,Exercise,Set,Reps,kg,Volume,Notes,Distance (km),"
    "Duration (min),Pace (min/km),Avg HR,Active Cal,Total Cal,"
    "Elevation (m),Elapsed,Source\n"
)

# Two strength sessions per month, April through June, with a rising top
# set so ``estimated_1rm`` / ``progression_summary`` must move when the
# anchor moves. The July pair sits past every anchor below and exists so
# the monthly clip has something to clip.
_SESSION_DATES = [
    ("2026-04-06", 100.0), ("2026-04-20", 102.5),
    ("2026-05-04", 105.0), ("2026-05-18", 107.5),
    ("2026-06-01", 110.0), ("2026-06-15", 112.5),
    ("2026-07-06", 115.0), ("2026-07-20", 117.5),
]

# The last anchor any test uses. Every store below carries at least one row
# dated after this, so removing a clip changes the payload rather than
# leaving the horizon assertion to pass vacuously.
LATEST_ANCHOR = "2026-06-30"

# TOTAL-row deload markers: one inside the earliest window, one past every
# anchor. ``read_tracker`` filters ``find_deloads`` on the horizon
# separately from ``_clip_series``, so it needs its own future row.
_DELOAD_DATES = {"2026-05-04", "2026-07-06"}
DELOAD_MARKER = "Deload Workout"

HEALTH_HEADER = (
    "Date,Bodyweight (kg),VO2max,Resting HR,HRV SDNN,Walking HR,"
    "HR Recovery 1min,Sleep Total,Sleep Deep,Sleep REM,Time in Bed,"
    "Resp Rate,Wrist Temp,Sleep Breath Dist,Exercise Min,Notes\n"
)

WORKOUT_SESSIONS_HEADER = (
    "Date,Start,End,Type,Duration (min),Avg HR,Max HR,Min HR,"
    "Active Cal,Distance (km),Source,Incidental,Notes\n"
)


SLEEP_HEADER = (
    "Date,Sleep Total (h),Sleep Core (h),Sleep Deep (h),Sleep REM (h),"
    "Sleep Unspecified (h),Sleep Awake (h),Time in Bed (h),"
    "Sleep Efficiency (%),N Segments,First Segment Start,"
    "Last Segment End,Notes\n"
)

THERMAL_HEADER = (
    "Date,Start,Heat Type,Heat Temp (°C),Heat Rounds,"
    "Heat Round Durations (min),Heat Total (min),Cold Type,"
    "Cold Duration (sec),Cold Temp (°C),Notes\n"
)

LIGHT_HEADER = (
    "Date,Start,Duration (min),Light Type,Wavelength (nm),Body Area,"
    "Modality,Ambient Temp (°C),Notes\n"
)

SWIM_WORKOUTS_HEADER = (
    "Date,Start,End,Duration (min),Distance (km),Pool Length (m),Laps,"
    "Strokes,SPL,Avg SWOLF,Stroke Mix,Location,Water Temp (°C),"
    "Avg HR (bpm),Active Cal,Notes\n"
)

SWIM_LAPS_HEADER = (
    "Date,Workout Start,Lap #,Stroke (raw),Stroke (decoded),"
    "Duration (sec),SWOLF,Source\n"
)

NUTRITION_HEADER = (
    "Start Date,End Date,Phase Type,Target Surplus/Deficit (kcal),"
    "Target Protein (g/kg),Target Rate (kg/wk),Stop Conditions,Notes\n"
)

# Sleep / thermal / light / swim rows, grouped by the per-month file they
# land in. Each store's last entry is dated after ``LATEST_ANCHOR``.
_SLEEP_DATES = ["2026-06-08", "2026-06-15", "2026-06-22", "2026-06-29",
                "2026-07-03"]
_THERMAL_DATES = ["2026-06-09", "2026-06-16", "2026-06-23", "2026-07-02"]
_LIGHT_DATES = ["2026-06-10", "2026-06-17", "2026-06-24", "2026-07-01"]
_SWIM_DATES = ["2026-06-11", "2026-06-18", "2026-06-25", "2026-07-04"]

# Two closed phases plus one that opens after every anchor. The closing
# dates are the point: both were written after the fact, so a run anchored
# inside a phase must still see that phase as open.
_NUTRITION_PHASES = [
    # start, end, type, kcal, protein, rate
    ("2026-04-09", "2026-05-15", "bulk", "300", "1.8", "0.25"),
    ("2026-05-16", "2026-06-20", "cut", "-300", "2.0", "-0.3"),
    ("2026-07-05", "", "maintain", "0", "1.8", "0.0"),
]


def _month_rows(ym: str) -> str:
    """Monthly CSV body for the sessions falling inside ``ym``."""
    body = []
    n = 0
    for i, (d, kg) in enumerate(_SESSION_DATES, start=1):
        if not d.startswith(ym.replace(".", "-")):
            continue
        n += 1
        for set_n in (1, 2):
            body.append(
                f"{n},{d},1,Barbell Back Squat,{set_n},5,{kg},{kg * 5:g},"
                f",,,,,,,,,manual\n"
            )
        note = DELOAD_MARKER if d in _DELOAD_DATES else ""
        body.append(
            f"{n},{d},,TOTAL,,,,{kg * 10:g},{note},,60:00,,126,360,430,"
            f",60:00,manual\n"
        )
    return "".join(body)


def _months_of(dates: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for d in dates:
        out.setdefault(d[:7].replace("-", "."), []).append(d)
    return out


def _write_fixture(root: Path) -> None:
    data = root / PERSON / "data"
    (data / "monthly").mkdir(parents=True)
    for ym in ("2026.04", "2026.05", "2026.06", "2026.07"):
        (data / "monthly" / f"{ym}.csv").write_text(
            MONTHLY_HEADER + _month_rows(ym), encoding="utf-8"
        )

    # Daily-ish health rows spanning the same range. Bodyweight and VO2max
    # both climb so ``bodyweight_latest`` / ``vo2max_latest`` are anchor-
    # sensitive; the trend helpers need >= 3 readings inside their window.
    health = [HEALTH_HEADER]
    for i, day in enumerate([
        "2026-04-04", "2026-04-11", "2026-04-18", "2026-04-25",
        "2026-05-02", "2026-05-09", "2026-05-16", "2026-05-23", "2026-05-30",
        "2026-06-06", "2026-06-13", "2026-06-20", "2026-06-27",
        "2026-07-04", "2026-07-11",
    ]):
        bw = 78.0 + i * 0.2
        vo2 = 47.0 + i * 0.1
        health.append(
            f"{day},{bw:.1f},{vo2:.1f},58,62,92,28,7.5,1.2,1.6,8.0,"
            f"14.2,36.4,0.1,45,\n"
        )
    (data / "health_metrics.csv").write_text("".join(health), encoding="utf-8")

    ws = [WORKOUT_SESSIONS_HEADER]
    for d, _kg in _SESSION_DATES:
        ws.append(
            f"{d},09:00,10:00,Traditional Strength Training,60,126,168,"
            f"70,360,,apple,false,\n"
        )
    (data / "workout_sessions.csv").write_text("".join(ws), encoding="utf-8")

    (data / "sleep").mkdir()
    for ym, days in _months_of(_SLEEP_DATES).items():
        body = "".join(
            f"{d},7.6,4.2,1.3,1.8,0.1,0.4,8.1,93.8,2,23:15,07:20,\n"
            for d in days
        )
        (data / "sleep" / f"{ym}.nights.csv").write_text(
            SLEEP_HEADER + body, encoding="utf-8")

    (data / "thermal").mkdir()
    for ym, days in _months_of(_THERMAL_DATES).items():
        body = "".join(
            f"{d},18:00,dry,85,3,\"12,12,12\",36,cold_shower,90,12,\n"
            for d in days
        )
        (data / "thermal" / f"{ym}.sessions.csv").write_text(
            THERMAL_HEADER + body, encoding="utf-8")

    (data / "light_therapy").mkdir()
    for ym, days in _months_of(_LIGHT_DATES).items():
        body = "".join(
            f"{d},07:30,12,red,660,full_body,panel,22,\n" for d in days
        )
        (data / "light_therapy" / f"{ym}.sessions.csv").write_text(
            LIGHT_HEADER + body, encoding="utf-8")

    (data / "swimming").mkdir()
    for ym, days in _months_of(_SWIM_DATES).items():
        # 12 lengths of a 25 m pool = 0.3 km, matching the 12 lap rows below.
        wbody = "".join(
            f"{d},07:00,07:09,9,0.3,25,12,180,15,42,Freestyle,pool,27,"
            f"132,110,\n"
            for d in days
        )
        (data / "swimming" / f"{ym}.workouts.csv").write_text(
            SWIM_WORKOUTS_HEADER + wbody, encoding="utf-8")
        lbody = "".join(
            f"{d},07:00,{lap},2,Freestyle,{27 + lap % 3},{42 + lap % 3},apple\n"
            for d in days for lap in range(1, 13)
        )
        (data / "swimming" / f"{ym}.laps.csv").write_text(
            SWIM_LAPS_HEADER + lbody, encoding="utf-8")

    nutrition = [NUTRITION_HEADER]
    for start, end, ptype, kcal, protein, rate in _NUTRITION_PHASES:
        nutrition.append(
            f"{start},{end},{ptype},{kcal},{protein},{rate},"
            f"stop if the rate holds off target for two weeks,"
            f"synthetic fixture phase\n"
        )
    (data / "nutrition_phases.csv").write_text(
        "".join(nutrition), encoding="utf-8")

    (data / "profile.csv").write_text(
        "key,value\nsource,xml\nauto_cardio,true\nbirthday,1995-01-01\n"
        "sex,male\nsession_target_min,75\nmin_per_working_set,2.5\n",
        encoding="utf-8",
    )


def _iso_dates_after(node, today: str, path: str = "", out=None) -> list:
    """Every ISO date string in ``node`` that is later than ``today``."""
    if out is None:
        out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str):
                for m in _ISO_DATE_RE.findall(k):
                    if m > today:
                        out.append((f"{path}{{{k}}}", m))
            _iso_dates_after(v, today, f"{path}.{k}", out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _iso_dates_after(v, today, f"{path}[{i}]", out)
    elif isinstance(node, str):
        for m in _ISO_DATE_RE.findall(node):
            if m > today:
                out.append((path, m))
    return out


class _FixtureCase(unittest.TestCase):
    """Shared fixture + subprocess runner. Holds no tests of its own so
    subclassing it does not re-run another class's assertions."""

    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        _write_fixture(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def payload(self, today: str) -> dict:
        env = os.environ.copy()
        env["WORKOUT_TRACKER_ROOT"] = str(self.root)
        proc = subprocess.run(
            [sys.executable, str(READ_TRACKER),
             "--person", PERSON, "--today", today, "--months", "6"],
            cwd=str(self.root), env=env, text=True,
            capture_output=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)


class PayloadHorizonTests(_FixtureCase):
    def test_no_payload_value_is_dated_after_today(self) -> None:
        for today in ("2026-04-30", "2026-05-17", "2026-06-01", "2026-06-30"):
            with self.subTest(today=today):
                data = self.payload(today)
                self.assertEqual(data["today"], today)
                offenders = _iso_dates_after(data, today)
                self.assertEqual(
                    offenders, [],
                    f"payload dated after --today {today}: {offenders[:10]}",
                )

    def test_fixture_actually_contains_future_rows(self) -> None:
        """Guard the guard: an anchor with nothing after it proves nothing."""
        data = self.payload("2026-06-30")
        all_dates = [m for _, m in _iso_dates_after(data, "2026-04-30")]
        self.assertTrue(
            any(d > "2026-04-30" for d in all_dates),
            "fixture has no rows after the earliest anchor — "
            "the horizon assertion would pass vacuously",
        )

    def test_every_store_carries_a_row_past_the_latest_anchor(self) -> None:
        """Guard the guard, per store.

        The horizon assertion is only worth anything for a store that has
        something on the far side of the horizon. Before this fixture grew,
        the sleep / thermal / light-therapy / swim / nutrition stores did not
        exist in it at all, so their clips could be deleted outright with
        every test still green. Assert on the fixture's own inputs — the
        payload cannot show a row it correctly dropped.
        """
        stores = {
            "monthly":      [d for d, _ in _SESSION_DATES],
            "deloads":      sorted(_DELOAD_DATES),
            "sleep":        _SLEEP_DATES,
            "thermal":      _THERMAL_DATES,
            "light":        _LIGHT_DATES,
            "swim":         _SWIM_DATES,
            "nutrition":    [p[0] for p in _NUTRITION_PHASES],
        }
        for name, dates in stores.items():
            with self.subTest(store=name):
                self.assertTrue(
                    any(d > LATEST_ANCHOR for d in dates),
                    f"{name} fixture has nothing after {LATEST_ANCHOR}",
                )
        # Nutrition also needs a phase whose END date is on the far side —
        # a different leak from a future start date, and the one that made
        # a live phase read as absent.
        self.assertTrue(
            any(end and end > "2026-06-01" and start <= "2026-06-01"
                for start, end, *_ in _NUTRITION_PHASES),
            "no phase straddles the 2026-06-01 anchor",
        )

    def test_windowed_summaries_count_only_rows_up_to_the_anchor(self) -> None:
        """Each per-month store has one row past the anchor; none may count.

        This asserts the OUTCOME rather than the clip. The clip in
        ``read_tracker`` and the ``d > today_d`` rejection inside each
        ``recent_*`` helper are two layers over the same invariant, and a
        test bound to one of them says nothing about the other. Removing
        either layer alone leaves these counts intact; removing both moves
        every number below.
        """
        data = self.payload(LATEST_ANCHOR)
        self.assertEqual(data["sleep_summary"]["n_nights_28d"], 4)
        self.assertEqual(data["thermal_summary"]["n_sessions_28d"], 3)
        self.assertEqual(data["light_therapy_summary"]["n_sessions_28d"], 3)
        self.assertEqual(data["swim_summary"]["sessions"], 3)
        self.assertEqual(data["swim_summary"]["total_laps"], 36)
        # The deload marker on 2026-07-06 must not be listed; the one on
        # 2026-05-04 must.
        self.assertEqual(data["deloads"], ["2026-05-04"])

    def test_anchor_sensitive_blocks_move_with_today(self) -> None:
        """The ten blocks that were byte-identical across a 7-week gap."""
        early = self.payload("2026-04-30")
        late = self.payload("2026-06-30")
        for key in ("estimated_1rm", "progression_summary", "monthly_sessions",
                    "bodyweight_latest", "vo2max_latest",
                    "weekly_volume_per_muscle"):
            with self.subTest(key=key):
                self.assertNotEqual(
                    json.dumps(early.get(key), sort_keys=True),
                    json.dumps(late.get(key), sort_keys=True),
                    f"{key} is identical across a two-month --today gap",
                )

    def test_static_config_blocks_do_not_move(self) -> None:
        """Counterpart: config is legitimately anchor-invariant."""
        early = self.payload("2026-04-30")
        late = self.payload("2026-06-30")
        for key in ("data_source", "capabilities", "estimated_max_hr",
                    "session_target_min", "target_working_sets"):
            with self.subTest(key=key):
                self.assertEqual(early.get(key), late.get(key))

    def test_session_budget_uses_the_measured_fixed_overhead(self) -> None:
        # The fixture profile is 75 min at 2.5 min/working-set. The old
        # 5.0-minute overhead billed that as 28 sets, which measured out at
        # over 80 real minutes. At the fitted 20.0 the budget is 22.
        data = self.payload("2026-06-30")
        self.assertEqual(data["session_target_min"], 75)
        self.assertEqual(data["target_working_sets"], 22)

    def test_last_top_set_matches_the_anchor(self) -> None:
        data = self.payload("2026-05-17")
        squat = data["estimated_1rm"]["Barbell Back Squat"]
        self.assertEqual(squat["last_date"], "2026-05-04")
        self.assertEqual(data["bodyweight_latest"]["date"], "2026-05-16")


class NutritionPhaseHorizonTests(_FixtureCase):
    """A phase whose ``end_date`` is after the anchor had not ended yet.

    Both fixture phases carry a closing date written after the fact. Clipping
    only ``start_date`` leaves that closing date in front of
    ``_current_open_phase``, which selects the first phase with no
    ``end_date`` — so a block that was three weeks live reads as no phase at
    all. That is not a cosmetic omission: ``nutrition_phase_start`` bounds
    the bodyweight-trend window, and ``compute_longevity_score`` scores
    ``body_comp_trend`` on a different branch for cut / bulk / none. The
    leak also survives a generic date-walk, because the leaked datum
    controls a BRANCH rather than appearing as a string.
    """

    def test_a_phase_live_at_the_anchor_is_reported_as_open(self) -> None:
        for today, phase_type, weeks in (("2026-04-30", "bulk", 3.0),
                                         ("2026-06-01", "cut", 2.3)):
            with self.subTest(today=today):
                data = self.payload(today)
                phase = data.get("nutrition_phase")
                self.assertIsNotNone(
                    phase,
                    f"nutrition_phase absent at {today}; a {phase_type} phase "
                    "was live at that anchor",
                )
                self.assertEqual(phase["current"]["phase_type"], phase_type)
                self.assertEqual(phase["current"]["weeks_in_phase"], weeks)
                # An open phase reports no end date, and the end date it was
                # eventually given must not appear anywhere in the payload.
                self.assertIsNone(phase["current"].get("end_date"))

    def test_the_open_phase_scopes_the_bodyweight_trend_window(self) -> None:
        # The downstream consequence: with no open phase the trend window
        # falls back to a trailing 28 days that predate the phase.
        data = self.payload("2026-06-01")
        self.assertEqual(
            data["bodyweight_trend"]["window_start"],
            data["nutrition_phase"]["current"]["start_date"],
        )

    def test_a_phase_closed_before_the_anchor_stays_closed(self) -> None:
        # Counterpart: clipping must not resurrect a genuinely ended phase.
        data = self.payload(LATEST_ANCHOR)
        self.assertIsNone(data.get("nutrition_phase"))

    def test_a_phase_that_opens_after_the_anchor_is_invisible(self) -> None:
        for today in ("2026-04-30", "2026-05-17", "2026-06-01",
                      LATEST_ANCHOR):
            with self.subTest(today=today):
                data = self.payload(today)
                # The start date is unique to that phase, so a whole-payload
                # sweep for it is a real horizon check.
                self.assertNotIn("2026-07-05", json.dumps(data))
                # The phase TYPE is not unique: "maintain" is also the
                # default priority tier every unemphasised muscle carries in
                # `muscle_priority_tiers`. Scope the check to the phase
                # surface, which is what the horizon rule is about.
                self.assertNotIn(
                    "maintain", json.dumps(data.get("nutrition_phase")),
                    "a maintain phase that opens after the anchor leaked "
                    "into nutrition_phase",
                )

    def test_the_final_day_of_a_phase_still_belongs_to_that_phase(self) -> None:
        """The store writes back-to-back periods — the bulk's last day is
        2026-05-15 and the cut opens 2026-05-16 — so ``end_date`` is an
        INCLUSIVE last day. Comparing it with ``>`` instead of ``>=`` closes
        the phase a day early and leaves 2026-05-15 reporting no phase at
        all, on a day the person was demonstrably still bulking."""
        last_day = self.payload("2026-05-15")["nutrition_phase"]
        self.assertIsNotNone(last_day, "no phase on the bulk's own last day")
        self.assertEqual(last_day["current"]["phase_type"], "bulk")
        self.assertEqual(last_day["current"]["days_elapsed"], 36)

        first_day = self.payload("2026-05-16")["nutrition_phase"]
        self.assertEqual(first_day["current"]["phase_type"], "cut")
        self.assertEqual(first_day["current"]["days_elapsed"], 0)
        # Exactly one phase is ever open: the handoff has no overlap and
        # no gap.
        self.assertEqual(
            [h["phase_type"] for h in first_day["history"]], ["bulk"]
        )

    def test_prior_phases_keep_the_end_dates_they_already_had(self) -> None:
        # The bulk closed 2026-05-15, before this anchor, so its real end
        # date belongs in history — nulling every end date would be the
        # opposite over-correction.
        data = self.payload("2026-06-01")
        history = data["nutrition_phase"]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["phase_type"], "bulk")
        self.assertEqual(history[0]["end_date"], "2026-05-15")
        self.assertEqual(history[0]["duration_days"], 36)


if __name__ == "__main__":
    unittest.main()
