"""Build swim CSV payloads from Apple Health workout rows."""
from __future__ import annotations

import sys

from apple_workout_types import HK_SWIMMING_STROKE_STYLE

_STROKE_ABBREV = {
    "Freestyle": "Free",
    "Backstroke": "Back",
    "Breaststroke": "Breast",
    "Butterfly": "Fly",
    "Mixed": "Mix",
    "Kickboard": "Kick",
    "Unknown": "Unk",
}


def _stroke_mix_summary(lap_events: list[dict]) -> str | None:
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
    pool_default = profile.get("swim_pool_length_default") if profile else None
    swim_rows: list[dict] = []
    lap_rows: list[dict] = []
    for w in workout_rows:
        if (w.get("apple_type") or "") != "Swimming":
            continue
        lap_events = w.get("swim_lap_events") or []
        swolf_vals = [ev.get("swolf") for ev in lap_events
                      if ev.get("swolf") is not None]
        avg_swolf = (round(sum(swolf_vals) / len(swolf_vals), 1)
                     if swolf_vals else None)
        strokes = w.get("stroke_count_total")
        laps_n = w.get("laps")
        spl = (round(strokes / laps_n, 1)
               if (strokes and laps_n) else None)
        pool_length = w.get("pool_length_m")
        if pool_length is None and pool_default is not None:
            pool_length = pool_default
            print(
                f"Pool Length: fell back to profile default {pool_default}m "
                f"for swim {w.get('date')} {w.get('start')}",
                file=sys.stderr,
            )
        swim_rows.append({
            "date": w.get("date"),
            "start": w.get("start"),
            "end": w.get("end"),
            "duration_min": w.get("duration_min"),
            "distance_km": w.get("distance_km"),
            "pool_length_m": pool_length,
            "laps": laps_n,
            "strokes": strokes,
            "spl": spl,
            "avg_swolf": avg_swolf,
            "stroke_mix": _stroke_mix_summary(lap_events),
            "location": w.get("swim_location"),
            "water_temp_c": w.get("water_temp_c"),
            "avg_hr": w.get("avg_hr"),
            "active_cal": int(round(w["active_cal"]))
                          if w.get("active_cal") is not None else None,
        })
        for ev in lap_events:
            raw = ev.get("stroke_raw")
            decoded = (HK_SWIMMING_STROKE_STYLE.get(int(raw))
                       if raw is not None else None)
            lap_rows.append({
                "date": w.get("date"),
                "workout_start": w.get("start"),
                "lap_num": ev.get("lap_num"),
                "stroke_raw": raw,
                "stroke_decoded": decoded,
                "duration_sec": ev.get("duration_sec"),
                "swolf": ev.get("swolf"),
                "source": "Apple Watch",
            })
    return swim_rows, lap_rows
