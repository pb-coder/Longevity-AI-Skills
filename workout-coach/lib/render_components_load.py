"""Training-load dashboard components."""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

from .render_helpers import parse_date

# ---------- training-load EWMA series ----------

def build_load_series(monthly_sessions, today_d, days=90):
    """Daily CTL/ATL/TSB over the last `days` days. Seeds CTL/ATL from
    all sessions older than the window to avoid cold-start bias."""
    start = today_d - timedelta(days=days - 1)
    trimp_by_day: dict[date, float] = {}
    for s in monthly_sessions:
        d = parse_date(s.get("date"))
        if not d or not (start <= d <= today_d):
            continue
        t = s.get("trimp")
        if t is None:
            continue
        try:
            trimp_by_day[d] = trimp_by_day.get(d, 0.0) + float(t)
        except (TypeError, ValueError):
            pass

    ctl_decay = math.exp(-1 / 42)
    atl_decay = math.exp(-1 / 7)
    ctl = 0.0
    atl = 0.0

    # Pre-window seeding
    pre = sorted(
        [(parse_date(s.get("date")), float(s["trimp"]))
         for s in monthly_sessions
         if s.get("trimp") is not None and parse_date(s.get("date"))
            and parse_date(s.get("date")) < start]
    )
    if pre:
        pre_by_day: dict[date, float] = {}
        for d, t in pre:
            pre_by_day[d] = pre_by_day.get(d, 0.0) + t
        cur = pre[0][0]
        while cur < start:
            t = pre_by_day.get(cur, 0.0)
            ctl = ctl * ctl_decay + t * (1 - ctl_decay)
            atl = atl * atl_decay + t * (1 - atl_decay)
            cur += timedelta(days=1)

    series = []
    cur = start
    while cur <= today_d:
        t = trimp_by_day.get(cur, 0.0)
        ctl = ctl * ctl_decay + t * (1 - ctl_decay)
        atl = atl * atl_decay + t * (1 - atl_decay)
        series.append({
            "date": cur.isoformat(),
            "ctl": round(ctl, 2),
            "atl": round(atl, 2),
            "tsb": round(ctl - atl, 2),
        })
        cur += timedelta(days=1)
    return series


def load_chart_svg(series, w=900, h=220):
    """Interactive 90-day CTL/ATL/TSB chart. Hover shows a scrubber +
    floating tooltip with the values at the hovered day."""
    if not series:
        return ""
    ctls = [d["ctl"] for d in series]
    atls = [d["atl"] for d in series]
    tsbs = [d["tsb"] for d in series]
    n = len(series)
    vmax = max(max(ctls), max(atls)) * 1.15 or 1.0
    vmin = min(min(tsbs), 0) * 1.15
    span = vmax - vmin
    left, right, bottom = 50, w - 10, h - 28

    def x(i):
        return (i / max(n - 1, 1)) * (right - left) + left

    def y(v):
        return bottom - ((v - vmin) / span) * (bottom - 14)

    ctl_pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(ctls))
    atl_pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(atls))
    band_top = " ".join(f"{x(i):.1f},{y(c):.1f}" for i, c in enumerate(ctls))
    band_bot = " ".join(f"{x(i):.1f},{y(a):.1f}" for i, a in reversed(list(enumerate(atls))))
    zero_y = y(0)

    # JS reads the series from data-series; renderer embeds it once.
    series_json = json.dumps(series).replace("'", "&#39;")

    first = series[0]["date"]
    last = series[-1]["date"]
    mid = series[n // 2]["date"]

    return f'''
<svg class="load-chart" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet"
     data-series='{series_json}' data-left="{left}" data-right="{right}">
  <defs>
    <linearGradient id="tsbband" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="var(--amber)" stop-opacity="0.16"/>
      <stop offset="100%" stop-color="var(--good)" stop-opacity="0.10"/>
    </linearGradient>
  </defs>
  <rect class="hit" x="{left}" y="14" width="{right-left}" height="{bottom-14}"
        fill="transparent"/>
  <line x1="{left}" y1="{zero_y:.1f}" x2="{right}" y2="{zero_y:.1f}"
        stroke="var(--border-strong)" stroke-width="1" stroke-dasharray="2,3"/>
  <polygon points="{band_top} {band_bot}" fill="url(#tsbband)"/>
  <polyline points="{atl_pts}" fill="none" stroke="var(--amber)"
            stroke-width="1.5" stroke-dasharray="4,3"/>
  <polyline points="{ctl_pts}" fill="none" stroke="var(--accent)" stroke-width="1.75"/>
  <g class="scrubber" style="display:none;">
    <line class="scrub-line" y1="14" y2="{bottom}" stroke="var(--text)" stroke-width="1" stroke-dasharray="2,3"/>
    <circle class="scrub-ctl" r="3.5" fill="var(--accent)"/>
    <circle class="scrub-atl" r="3.5" fill="var(--amber)"/>
  </g>
  <text x="{left}" y="{h-8}" font-size="11" fill="var(--muted)">{first}</text>
  <text x="{(left+right)/2:.0f}" y="{h-8}" font-size="11" fill="var(--muted)" text-anchor="middle">{mid}</text>
  <text x="{right}" y="{h-8}" font-size="11" fill="var(--muted)" text-anchor="end">{last}</text>
  <text x="{left-4}" y="20" font-size="10" fill="var(--muted)" text-anchor="end">{vmax:.0f}</text>
  <text x="{left-4}" y="{zero_y+4:.0f}" font-size="10" fill="var(--muted)" text-anchor="end">0</text>
</svg>
<div class="load-tooltip" style="display:none;">
  <div class="lt-date"></div>
  <div class="lt-row"><span class="sw sw-ctl"></span><span>fitness</span><span class="lt-ctl"></span></div>
  <div class="lt-row"><span class="sw sw-atl"></span><span>fatigue</span><span class="lt-atl"></span></div>
  <div class="lt-row"><span class="sw sw-tsb"></span><span>freshness</span><span class="lt-tsb"></span></div>
</div>
'''
