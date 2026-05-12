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
alongside the workout. ``rows``, ``bodyweight``, and ``sleep`` are all
optional within the wrapper.

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
    python3 append_workout.py --person Nihad <payload_json_path>
    python3 append_workout.py --person Nihad -    # read JSON from stdin
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from monthly_csv import (  # noqa: E402
    canonicalize_monthly_csv,
    upsert_rows as monthly_upsert_rows,
)
from csv_store import (  # noqa: E402
    upsert_health_metrics,
    upsert_sleep_nights,
    write_profile,
)
from person_paths import monthly_csv as monthly_csv_path  # noqa: E402


def sheet_for_date(date_str: str) -> str:
    """'2026-04-20' -> '2026.04'."""
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
            continue
        metric_entries.append({"date": d, "bodyweight_kg": kg})
    if not metric_entries:
        return []
    upsert_health_metrics(person, metric_entries)
    summary = ", ".join(f"{e['date']}={e['kg']}kg" for e in entries)
    return [f"Bodyweight: mirrored to Health Metrics ({summary})"]


def write_payload(person: str, rows: list[dict], bodyweight: list[dict],
                  css_test: dict | None = None,
                  sleep: list[dict] | None = None) -> list[str]:
    """Apply rows + bodyweight + sleep entries + optional CSS test.

    Routes per-set rows to the matching ``YYYY.MM.csv`` under
    ``<person>/data/monthly/``, then canonicalizes each touched month
    (sort, recompute Volume / Pace / TOTAL rows). Bodyweight, sleep,
    and css_test flow through the existing CSV helpers.
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
            monthly_upsert_rows(person, ym, payload)
            # upsert_rows already calls canonicalize, but call it again
            # defensively in case a future refactor short-circuits the
            # internal call.
            canonicalize_monthly_csv(person, ym)
            dates = sorted({r["date"] for r in month_rows})
            tag = " (new sheet)" if created else ""
            status.append(
                f"Appended {len(month_rows)} row(s) to {ym}{tag} "
                f"for {', '.join(dates)}"
            )

    # Bodyweight upserts the Health Metrics CSV.
    status.extend(upsert_bodyweight(person, bodyweight))
    # Sleep dual-writes to sleep/YYYY.MM.nights.csv + health_metrics.csv.
    status.extend(upsert_sleep(person, sleep or []))
    # CSS test writes to profile.csv. Independent of rows / bodyweight.
    status.extend(apply_css_test(person, css_test))
    return status


def load_payload(source: str) -> tuple[list[dict], list[dict], dict | None, list[dict]]:
    """Return (rows, bodyweight_entries, css_test, sleep_entries).

    Accepts bare list (legacy — rows only) or wrapper dict. Wrapper
    dict accepts optional ``bodyweight``, ``css_test``, and ``sleep``
    keys; all are independent.

    ``sleep`` entries each require ``date``; all other keys (``total_h``,
    ``deep_h``, ``rem_h``, ``core_h``, ``unspecified_h``, ``awake_h``,
    ``time_in_bed_h``, ``efficiency_pct``, ``notes``) are optional —
    sparse-merge applies.
    """
    if source == "-":
        data = json.load(sys.stdin)
    else:
        data = json.loads(Path(source).read_text())

    css_test: dict | None = None
    sleep_entries: list[dict] = []
    if isinstance(data, list):
        rows = data
        bw = []
    elif isinstance(data, dict):
        rows = data.get("rows", []) or []
        bw_raw = data.get("bodyweight", []) or []
        # Accept a single dict as shorthand for a one-element list.
        if isinstance(bw_raw, dict):
            bw_raw = [bw_raw]
        bw = bw_raw
        css_test = data.get("css_test") or None
        sleep_raw = data.get("sleep", []) or []
        if isinstance(sleep_raw, dict):
            sleep_raw = [sleep_raw]
        sleep_entries = sleep_raw
    else:
        raise ValueError("payload must be a list of rows or a dict wrapper")

    for r in rows:
        if "date" not in r or "exercise" not in r or "set" not in r or "num" not in r:
            raise ValueError(f"row missing required field: {r!r}")
    for e in bw:
        if "date" not in e or "kg" not in e:
            raise ValueError(f"bodyweight entry missing date/kg: {e!r}")
    if css_test is not None:
        if not isinstance(css_test, dict):
            raise ValueError(f"css_test must be a dict: {css_test!r}")
        if "t400_sec" not in css_test or "t200_sec" not in css_test:
            raise ValueError(
                f"css_test missing t400_sec / t200_sec: {css_test!r}"
            )
    for e in sleep_entries:
        if "date" not in e:
            raise ValueError(f"sleep entry missing date: {e!r}")

    return rows, bw, css_test, sleep_entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--person", required=True,
                    help="Tracker owner (Nihad or Fabian).")
    ap.add_argument("payload", type=str,
                    help="Path to payload JSON, or '-' to read from stdin.")
    args = ap.parse_args()

    rows, bodyweight, css_test, sleep_entries = load_payload(args.payload)
    if not rows and not bodyweight and not css_test and not sleep_entries:
        print("No rows, bodyweight, sleep, or css_test entries to write.")
        return 0
    try:
        for line in write_payload(args.person, rows, bodyweight, css_test,
                                  sleep=sleep_entries):
            print(line)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
