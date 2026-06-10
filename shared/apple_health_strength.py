"""Strength-session clustering for Apple Health workout rows."""
from __future__ import annotations

from datetime import datetime

STRENGTH_APPLE_TYPES: frozenset[str] = frozenset({
    "TraditionalStrengthTraining",
    "FunctionalStrengthTraining",
    "CoreTraining",
})
STRENGTH_CLUSTER_WINDOW_MIN = 90.0


def cluster_strength_sessions(workout_rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Group same-day strength workouts into one session per cluster."""
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
        decorated: list[tuple] = []
        for w in by_date[d]:
            t = str(w.get("start") or "00:00:00")
            try:
                if len(t.split(":")) == 2:
                    dt_w = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M")
                else:
                    dt_w = datetime.strptime(f"{d} {t[:8]}", "%Y-%m-%d %H:%M:%S")
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

        weighted_sum = 0.0
        weight_total = 0.0
        for _, w in chosen:
            ahr = w.get("avg_hr")
            dur = w.get("duration_min") or 0.0
            if ahr is None or dur <= 0:
                continue
            weighted_sum += float(ahr) * dur
            weight_total += dur

        sessions.append({
            "date": d,
            "active_cal": active if active > 0 else None,
            "total_cal": (active + basal) if (active > 0 and basal > 0) else None,
            "elevation_m": None,
            "elapsed_min": elapsed if elapsed > 0 else None,
            "avg_hr": (weighted_sum / weight_total) if weight_total > 0 else None,
            "duration_min": duration if duration > 0 else None,
        })

    return sessions, warnings
