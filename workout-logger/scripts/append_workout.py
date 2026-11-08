"""Append parsed workout rows to the right per-month CSV in the per-person store.

Routes each row to the matching ``<Person>/data/monthly/YYYY.MM.csv``. Creates
the file (headers only) if missing. Canonicalization (sort + recompute
Volume / Pace / SESSION + rebuild TOTAL rows + hoist deload markers) runs on
every write via ``monthly_csv.canonicalize_monthly_csv`` so the file stays
consistent without waiting for a cross-month maintenance sweep.

Input JSON is either a bare list of row dicts (legacy) or a wrapper object:

    {
      "rows": [ ... row dicts ... ],
      "bodyweight": [ {"date": "YYYY-MM-DD", "kg": 78.4, "notes": ""}, ... ],
      "sleep": [ {"date": "YYYY-MM-DD", "total_h": 7.5,
                  "deep_h": 1.2, "rem_h": 1.3, "core_h": null,
                  "unspecified_h": null, "awake_h": null,
                  "time_in_bed_h": 8.4, "efficiency_pct": null,
                  "notes": null}, ... ]
    }

The wrapper form allows /log to capture the user's morning weight and sleep
alongside the workout.
``rows``, ``bodyweight``, and ``sleep``
are all optional within the wrapper.

- Bodyweight entries are upserted into the per-person Health Metrics CSV
  (``<person>/data/health_metrics.csv`` col ``Bodyweight (kg)``).
- Sleep entries are dual-written: rich per-night detail goes into
  ``<person>/data/sleep/YYYY.MM.nights.csv``; the headline fields
  (Sleep Total / Deep / REM / Time in Bed) are mirrored into
  ``health_metrics.csv`` so the recovery score path picks them up
  without joining files. Both writes are sparse-merge — partial input
  is fine, missing keys preserve whatever was there before.

Row dict schema:
    {
      "date": "2026-04-20",          # required, YYYY-MM-DD
      "num": 1,                      # exercise index within the session
      "exercise": "Dumbbell Flat Bench Press",
      "set": 1,
      "reps": 10,
      "kg": 52,
      "volume": 520,
      "notes": "",
      "distance_km": null,           # optional cardio fields
      "duration_min": null,
      "pace": null,                  # string "MM:SS"
      "avg_hr": null
    }

    Note: ``laps`` is no longer a monthly-CSV column. Swim lap counts live
    on ``<Person>/data/swimming/YYYY.MM.workouts.csv``, populated by the
    Apple Health importer. Manual /log payloads that include ``laps``
    are silently dropped here — the canonical lap count is Apple-fed,
    and a manual count has nowhere to go through this function.

Rows must arrive pre-sorted: by date ascending, then by num ascending, then by set.
The script does not re-sort — it trusts the caller.

Usage:
    python3 append_workout.py --person <Person> <payload_json_path>
    python3 append_workout.py --person <Person> -    # read JSON from stdin
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))
from tracker import TrackerContext  # noqa: E402
from shared.monthly_csv import (  # noqa: E402
    upsert_rows as monthly_upsert_rows,
)
from shared.csv_store import (  # noqa: E402
    NUTRITION_PHASE_TYPES,
    upsert_health_metrics,
    upsert_nutrition_phases,
    upsert_sleep_nights,
    write_profile,
)
from shared.data_git import commit_data  # noqa: E402
from shared.workout_context import LOAD_BASES  # noqa: E402
from shared.person_paths import monthly_csv as monthly_csv_path  # noqa: E402

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def sheet_for_date(date_str: str) -> str:
    """'2026-04-20' -> '2026.04'."""
    if not ISO_DATE_RE.match(str(date_str or "")):
        raise ValueError(f"date must be YYYY-MM-DD: {date_str!r}")
    y, m, _ = date_str.split("-")
    return f"{y}.{m}"


def _to_monthly_row(r: dict) -> dict:
    """Translate a /log payload row into the monthly_csv field schema.

    Payload keys (incoming):
      ``date, num, exercise, set, reps, kg, notes, distance_km,
      duration_min, pace, avg_hr``.

    Monthly CSV keys (outgoing): match ``MONTHLY_FIELDS`` —
      ``distance_km`` → ``distance``, ``duration_min`` → ``duration``.
    Apple-watch session metadata (cols 14-17) is left blank; the
    importers fill it post-hoc on the matching session.
    """
    return {
        "session":     None,  # canonicalize fills
        "date":        r["date"],
        "num":         r.get("num"),
        "exercise":    r["exercise"],
        "set":         r.get("set"),
        "reps":        r.get("reps"),
        "kg":          r.get("kg"),
        "volume":      None,  # canonicalize computes (reps × kg)
        "notes":       r.get("notes") or None,
        "distance":    r.get("distance_km"),
        "duration":    r.get("duration_min"),  # MM:SS or float
        "pace":        r.get("pace"),
        "avg_hr":      r.get("avg_hr"),
        "active_cal":  None,
        "total_cal":   None,
        "elevation_m": None,
        "elapsed":     None,
        "gym":         r.get("gym"),
        "machine":     r.get("machine"),
        "load_basis":  r.get("load_basis"),
    }


def apply_css_test(person: str, css_test: dict | None) -> list[str]:
    """Compute and persist CSS from a 400m + 200m TT pair logged as a CSS test.

    Payload shape (inside the wrapper):
      ``{"date": "YYYY-MM-DD", "t400_sec": 450, "t200_sec": 210}``

    Both seconds are required. CSS is written to ``profile.csv`` as
    ``swim_css_sec_per_100m`` with ``swim_css_set_at`` = the test date
    (or today if absent). The standard CSS test protocol per
    MyProCoach / TopEndSports: ``CSS = (t400_sec - t200_sec) / 2``,
    in sec/100m.

    Caller (the /log agent) parses the user's ``CSS test`` keyword on
    the header line and assembles this dict. Manual rows (the two TT
    swims themselves) flow through ``rows`` like any other workout.
    """
    if not css_test:
        return []
    try:
        t400 = float(css_test.get("t400_sec"))
        t200 = float(css_test.get("t200_sec"))
    except (TypeError, ValueError):
        return ["WARN: css_test ignored — t400_sec / t200_sec not numeric"]
    if t400 <= 0 or t200 <= 0 or t400 <= t200:
        return [f"WARN: css_test ignored — invalid times "
                f"(t400={t400}, t200={t200})"]
    css = round((t400 - t200) / 2.0, 1)
    set_at = str(css_test.get("date") or "")[:10]
    if not set_at:
        from datetime import date as _date
        set_at = _date.today().isoformat()
    write_profile(
        person,
        swim_css_sec_per_100m=css,
        swim_css_set_at=set_at,
    )
    return [f"CSS test: wrote swim_css_sec_per_100m={css}, "
            f"swim_css_set_at={set_at} to profile.csv"]


def upsert_sleep(person: str, entries: list[dict]) -> list[str]:
    """Dual-write manual sleep entries into the per-night CSV + health_metrics.

    Each entry shape (all fields except ``date`` optional; nulls accepted):

        {
          "date": "2026-05-11",
          "total_h": 7.5, "core_h": 4.5, "deep_h": 1.2,
          "rem_h": 1.3, "unspecified_h": null, "awake_h": 0.6,
          "time_in_bed_h": 8.4, "efficiency_pct": null,
          "notes": null
        }

    - Rich detail (all 6 stages + Time in Bed + Efficiency + Notes)
      lands in ``<person>/data/sleep/YYYY.MM.nights.csv`` via
      ``upsert_sleep_nights`` (sparse-merge, Notes manual-wins).
      Sleep Efficiency is auto-derived inside the upsert when both
      ``total_h`` and ``time_in_bed_h`` are present and
      ``efficiency_pct`` wasn't supplied.
    - Headline fields (``sleep_total_h``, ``sleep_deep_h``,
      ``sleep_rem_h``, ``time_in_bed_h``) are mirrored into
      ``health_metrics.csv`` so the existing recovery_score path
      picks them up without a cross-file join. Sparse-merge on
      Health Metrics protects any other metric on the same date.

    ``n_segments``, ``first_segment_start``, and ``last_segment_end``
    are left blank on manual rows — only the Apple importer can
    populate those from segment-level XML.
    """
    if not entries:
        return []

    nights_payload: list[dict] = []
    hm_payload: list[dict] = []
    summary_parts: list[str] = []
    for e in entries:
        d = str(e.get("date") or "")[:10]
        if not d:
            continue
        nights_payload.append({
            "date":           d,
            "total_h":        e.get("total_h"),
            "core_h":         e.get("core_h"),
            "deep_h":         e.get("deep_h"),
            "rem_h":          e.get("rem_h"),
            "unspecified_h":  e.get("unspecified_h"),
            "awake_h":        e.get("awake_h"),
            "time_in_bed_h":  e.get("time_in_bed_h"),
            "efficiency_pct": e.get("efficiency_pct"),
            "notes":          e.get("notes"),
        })
        hm = {"date": d}
        for k_in, k_hm in (
            ("total_h",       "sleep_total_h"),
            ("deep_h",        "sleep_deep_h"),
            ("rem_h",         "sleep_rem_h"),
            ("time_in_bed_h", "time_in_bed_h"),
        ):
            if e.get(k_in) is not None:
                hm[k_hm] = e[k_in]
        if len(hm) > 1:  # at least one mirrored field
            hm_payload.append(hm)
        # Build a compact human summary for the run output.
        bits = []
        if e.get("total_h") is not None:
            bits.append(f"total={e['total_h']}h")
        if e.get("time_in_bed_h") is not None:
            bits.append(f"inbed={e['time_in_bed_h']}h")
        summary_parts.append(f"{d}({', '.join(bits) or 'no fields'})")

    out: list[str] = []
    if nights_payload:
        out.extend(upsert_sleep_nights(person, nights_payload))
    if hm_payload:
        upsert_health_metrics(person, hm_payload)
        out.append(
            f"Sleep: mirrored to Health Metrics for {len(hm_payload)} "
            f"date(s) ({', '.join(summary_parts)})"
        )
    return out


def upsert_nutrition_phase(person: str, entries: list[dict]) -> list[str]:
    """Forward parsed nutrition-phase entries (bulk / cut / maintain /
    recomp) to the flat per-person ``nutrition_phases.csv`` store.

    Each entry has shape:

        {
          "start_date": "2026-05-11",
          "end_date": null | "YYYY-MM-DD",   # null ≡ phase is open
          "phase_type": "bulk" | "cut" | "maintain" | "recomp",
          "target_kcal_delta": 300,           # optional, kcal/day above maintenance
          "target_protein_g_per_kg": 1.8,     # optional
          "target_rate_kg_per_wk": 0.25,      # optional, falls back to type default
          "stop_conditions": "free text ...", # optional pre-committed off-ramp
          "notes": null
        }

    Sparse-merge by ``start_date`` (one phase per start_date). Ending an
    open phase = an upsert with ``end_date`` set on the matching
    start_date row. Manual /log only — no Apple importer writes here.
    """
    if not entries:
        return []
    out = upsert_nutrition_phases(person, entries)
    summary_parts: list[str] = []
    for e in entries:
        sd = str(e.get("start_date") or "")[:10]
        if not sd:
            continue
        pt = e.get("phase_type") or "phase"
        ed = e.get("end_date")
        if ed:
            summary_parts.append(f"{pt} {sd}→{str(ed)[:10]} (closed)")
        else:
            summary_parts.append(f"{pt} {sd} (open)")
    if summary_parts:
        out.append(
            f"Nutrition phase: forwarded {len(summary_parts)} "
            f"entr{'y' if len(summary_parts) == 1 else 'ies'} ({', '.join(summary_parts)})"
        )
    return out


def upsert_bodyweight(person: str, entries: list[dict]) -> list[str]:
    """Mirror manual bodyweight entries into the Health Metrics CSV.

    Bodyweight is no longer a separate sheet — it lives on the
    ``Bodyweight (kg)`` column of ``<person>/data/health_metrics.csv``.
    Each ``{"date": ..., "kg": ..., "notes": ...}`` becomes a Health
    Metrics record with ``bodyweight_kg`` set; csv_store's sparse-merge
    leaves all other metrics on that date alone.
    """
    if not entries:
        return []
    metric_entries = []
    for e in entries:
        d = str(e["date"])[:10]
        try:
            kg = float(e["kg"])
        except (TypeError, ValueError):
            raise ValueError(f"bodyweight kg must be numeric: {e['kg']!r}") from None
        metric_entries.append({"date": d, "bodyweight_kg": kg})
    if not metric_entries:
        return []
    upsert_health_metrics(person, metric_entries)
    summary = ", ".join(f"{e['date']}={e['bodyweight_kg']}kg" for e in metric_entries)
    return [f"Bodyweight: mirrored to Health Metrics ({summary})"]


def write_payload(person: str, rows: list[dict], bodyweight: list[dict],
                  css_test: dict | None = None,
                  sleep: list[dict] | None = None,
                  nutrition_phase: list[dict] | None = None,
                  replace_conflicts: bool = False,
                  dry_run: bool = False) -> list[str]:
    """Apply rows + bodyweight + sleep + nutrition_phase + optional CSS test.

    Routes per-set rows to the matching ``YYYY.MM.csv`` under
    ``<person>/data/monthly/``, then canonicalizes each touched month
    (sort, recompute Volume / Pace / TOTAL rows). Bodyweight, sleep,
    nutrition_phase and css_test flow through
    the existing CSV helpers.
    """
    status: list[str] = []

    if rows:
        by_month: dict[str, list[dict]] = {}
        for r in rows:
            by_month.setdefault(sheet_for_date(r["date"]), []).append(r)
        for ym, month_rows in by_month.items():
            target = monthly_csv_path(person, ym)
            created = not target.exists()
            payload = [_to_monthly_row(r) for r in month_rows]
            counts = monthly_upsert_rows(person, ym, payload,
                                         replace_conflicts=replace_conflicts,
                                         dry_run=dry_run)
            dates = sorted({r["date"] for r in month_rows})
            tag = " (new sheet)" if created else ""
            status.append(
                f"{'Would append' if dry_run else 'Appended'} {counts['added']} row(s) to {ym}{tag} "
                f"for {', '.join(dates)}; skipped {counts['skipped']} duplicate(s), "
                f"replaced {counts['replaced']}, conflicts {counts['conflicts']}"
            )
            if counts["conflicts"]:
                status.append("WARN: conflicting sets were not changed; review them. --replace-conflicts only updates an exact, unambiguous manual set")

    if dry_run:
        return status

    # Bodyweight upserts the Health Metrics CSV.
    status.extend(upsert_bodyweight(person, bodyweight))
    # Sleep dual-writes to sleep/YYYY.MM.nights.csv + health_metrics.csv.
    status.extend(upsert_sleep(person, sleep or []))
    # Nutrition phase (bulk / cut / maintain / recomp) writes to the flat
    # <person>/data/nutrition_phases.csv. Independent of every other store.
    status.extend(upsert_nutrition_phase(person, nutrition_phase or []))
    # CSS test writes to profile.csv. Independent of rows / bodyweight.
    status.extend(apply_css_test(person, css_test))
    return status


def load_payload(source: str) -> tuple[list[dict], list[dict], dict | None, list[dict], list[dict]]:
    """Return (rows, bodyweight, css_test, sleep, nutrition_phase).

    Accepts bare list (legacy — rows only) or wrapper dict. Wrapper
    dict accepts optional ``bodyweight``, ``css_test``, ``sleep``,
    and ``nutrition_phase`` keys; all
    are independent.

    ``sleep`` entries each require
    ``date``; ``nutrition_phase`` entries require ``start_date``. Every
    other field is optional and falls through sparse-merge.
    """
    if source == "-":
        data = json.load(sys.stdin)
    else:
        data = json.loads(Path(source).read_text())

    css_test: dict | None = None
    sleep_entries: list[dict] = []
    nutrition_phase_entries: list[dict] = []
    if isinstance(data, list):
        rows = data
        bw = []
    elif isinstance(data, dict):
        retired = {"thermal", "light_therapy"}.intersection(data)
        if retired:
            raise ValueError("Retired logging categories: " + ", ".join(sorted(retired)))
        rows = data.get("rows", []) or []
        bw_raw = data.get("bodyweight", []) or []
        # Accept a single dict as shorthand for a one-element list.
        if isinstance(bw_raw, dict):
            bw_raw = [bw_raw]
        bw = bw_raw
        css_test = data.get("css_test")
        sleep_raw = data.get("sleep", []) or []
        if isinstance(sleep_raw, dict):
            sleep_raw = [sleep_raw]
        sleep_entries = sleep_raw
        np_raw = data.get("nutrition_phase", []) or []
        if isinstance(np_raw, dict):
            np_raw = [np_raw]
        nutrition_phase_entries = np_raw
    else:
        raise ValueError("payload must be a list of rows or a dict wrapper")

    for name, collection in (("rows", rows), ("bodyweight", bw), ("sleep", sleep_entries),
                             ("nutrition_phase", nutrition_phase_entries)):
        if not isinstance(collection, list):
            raise ValueError(f"{name} must be a list")

    def require_date(e: dict, label: str, key: str = "date") -> None:
        if not isinstance(e, dict):
            raise ValueError(f"{label} entry must be an object: {e!r}")
        if key not in e:
            raise ValueError(f"{label} entry missing {key}: {e!r}")
        if not ISO_DATE_RE.match(str(e.get(key) or "")):
            raise ValueError(f"{label} {key} must be YYYY-MM-DD: {e!r}")
        try:
            date.fromisoformat(str(e[key]))
        except ValueError:
            raise ValueError(f"{label} {key} must be a real calendar date: {e!r}") from None

    def require_number(value, label, *, positive=False, nonnegative=False):
        try:
            if isinstance(value, bool):
                raise ValueError
            n = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{label} must be numeric: {value!r}") from None
        if not math.isfinite(n) or (positive and n <= 0) or (nonnegative and n < 0):
            raise ValueError(f"{label} has an invalid value: {value!r}")
        return n

    for r in rows:
        require_date(r, "row")
        if "exercise" not in r or "set" not in r or "num" not in r:
            raise ValueError(f"row missing required field: {r!r}")
        for key in ("gym", "machine"):
            if r.get(key) is not None and not isinstance(r[key], str):
                raise ValueError(f"{key} must be a string")
        if r.get("load_basis") not in (None, "") and (not isinstance(r["load_basis"], str) or r["load_basis"] not in LOAD_BASES):
            raise ValueError("load_basis must be total or plates_only")
    for e in bw:
        require_date(e, "bodyweight")
        require_number(e.get("kg"), "bodyweight kg", positive=True)
    if css_test is not None:
        if not isinstance(css_test, dict):
            raise ValueError(f"css_test must be a dict: {css_test!r}")
        if "t400_sec" not in css_test or "t200_sec" not in css_test:
            raise ValueError(
                f"css_test missing t400_sec / t200_sec: {css_test!r}"
            )
        t400 = require_number(css_test["t400_sec"], "css_test t400_sec", positive=True)
        t200 = require_number(css_test["t200_sec"], "css_test t200_sec", positive=True)
        if t400 <= t200:
            raise ValueError("css_test t400_sec must exceed t200_sec")
        if css_test.get("date") is not None:
            require_date(css_test, "css_test")
    for e in sleep_entries:
        require_date(e, "sleep")
        for field in ("total_h", "core_h", "deep_h", "rem_h", "unspecified_h",
                      "awake_h", "time_in_bed_h", "efficiency_pct"):
            if e.get(field) is not None:
                n = require_number(e[field], f"sleep {field}", nonnegative=True)
                if field == "efficiency_pct" and n > 100:
                    raise ValueError("sleep efficiency_pct must not exceed 100")
    for e in nutrition_phase_entries:
        require_date(e, "nutrition_phase", "start_date")
        if e.get("end_date") is not None:
            require_date(e, "nutrition_phase", "end_date")
            if e["end_date"] < e["start_date"]:
                raise ValueError("nutrition_phase end_date precedes start_date")
        if e.get("phase_type") is not None and str(e["phase_type"]).strip().lower() not in NUTRITION_PHASE_TYPES:
            raise ValueError(f"unknown phase_type: {e['phase_type']!r}")
        for field in ("target_kcal_delta", "target_protein_g_per_kg", "target_rate_kg_per_wk"):
            if e.get(field) is not None:
                require_number(e[field], f"nutrition_phase {field}", nonnegative=field == "target_protein_g_per_kg")

    return (rows, bw, css_test, sleep_entries, nutrition_phase_entries)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--person", required=True,
                    help="Tracker owner (<Person> or <OtherPerson>).")
    ap.add_argument("--replace-conflicts", action="store_true",
                    help="Replace matching, unambiguous manual sets when reps or weight differ.")
    ap.add_argument("payload", type=str,
                    help="Path to payload JSON, or '-' to read from stdin.")
    args = ap.parse_args()
    ctx = TrackerContext(args.person)

    try:
        (rows, bodyweight, css_test, sleep_entries,
         nutrition_phase_entries) = load_payload(args.payload)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if (not rows and not bodyweight and not css_test
            and not sleep_entries
            and not nutrition_phase_entries):
        print("No rows, bodyweight, sleep, nutrition_phase, or css_test entries to write.")
        return 0
    try:
        status = write_payload(ctx.person, rows, bodyweight, css_test,
                               sleep=sleep_entries,
                               nutrition_phase=nutrition_phase_entries,
                               replace_conflicts=args.replace_conflicts)
        for line in status:
            print(line)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # One /log run is one atomic change to the tracker, so it reads as one
    # commit rather than one per touched CSV. Commit only after the write
    # is confirmed; commit_data never raises, so a broken git state costs
    # the history of this write and nothing else.
    dates = sorted({str(r.get("date")) for r in rows if r.get("date")})
    span = f"{dates[0]}..{dates[-1]}" if len(dates) > 1 else (dates[0] if dates else "no dates")
    sha = commit_data(ctx.person, f"log: {len(rows)} rows, {span}")
    if sha:
        print(f"Committed {ctx.person} data: {sha}")
    # Other rows can already have been written. Preserve their history, but
    # make unresolved conflicts visible to callers through the exit code.
    return 2 if any(line.startswith("WARN: conflicting sets") for line in status) else 0


if __name__ == "__main__":
    sys.exit(main())
