"""SVG and HTML components used by the dashboard cards.

Each function returns a complete HTML/SVG fragment ready to drop into
the parent card template. Pure presentation — no I/O, no analytics.

Grouped by purpose:

- Training-load chart: ``build_load_series`` (90-day CTL/ATL/TSB EWMA)
  + ``load_chart_svg`` (interactive line chart with scrubber tooltip).
- Activity rings: ``ring`` (a single ring with target progress).
- Recovery drivers: ``metric_label``, ``metric_tip``, ``driver_bars``
  (diverging horizontal bars showing each signal's z-score).
- Per-muscle volume: ``muscle_bars`` (4-band stack with MEV/MAV ticks).
- Hero scales: ``freshness_scale`` (-15..+15 TSB strip), ``recovery_scale``
  (0..10 score strip). Both share viewBox + band-label conventions so the
  two hero cards read as siblings.
- Small bits: ``confidence_dots`` (3-dot indicator), ``sparkline`` (mini
  line chart for vitals trends), ``embed_workout_markdown`` (escaped
  script tag for the Workout tab).
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

# Sibling lib/ on sys.path so this module is importable on its own.
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from render_helpers import esc, fmt, parse_date, signed


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
      <stop offset="0%" stop-color="#ff9f0a" stop-opacity="0.16"/>
      <stop offset="100%" stop-color="#34c759" stop-opacity="0.10"/>
    </linearGradient>
  </defs>
  <rect class="hit" x="{left}" y="14" width="{right-left}" height="{bottom-14}"
        fill="transparent"/>
  <line x1="{left}" y1="{zero_y:.1f}" x2="{right}" y2="{zero_y:.1f}"
        stroke="#e4e4e6" stroke-width="1" stroke-dasharray="2,3"/>
  <polygon points="{band_top} {band_bot}" fill="url(#tsbband)"/>
  <polyline points="{atl_pts}" fill="none" stroke="#ff9f0a"
            stroke-width="1.5" stroke-dasharray="4,3"/>
  <polyline points="{ctl_pts}" fill="none" stroke="#0a84ff" stroke-width="1.75"/>
  <g class="scrubber" style="display:none;">
    <line class="scrub-line" y1="14" y2="{bottom}" stroke="#1c1c1e" stroke-width="1" stroke-dasharray="2,3"/>
    <circle class="scrub-ctl" r="3.5" fill="#0a84ff"/>
    <circle class="scrub-atl" r="3.5" fill="#ff9f0a"/>
  </g>
  <text x="{left}" y="{h-8}" font-size="11" fill="#6b6b6f">{first}</text>
  <text x="{(left+right)/2:.0f}" y="{h-8}" font-size="11" fill="#6b6b6f" text-anchor="middle">{mid}</text>
  <text x="{right}" y="{h-8}" font-size="11" fill="#6b6b6f" text-anchor="end">{last}</text>
  <text x="{left-4}" y="20" font-size="10" fill="#6b6b6f" text-anchor="end">{vmax:.0f}</text>
  <text x="{left-4}" y="{zero_y+4:.0f}" font-size="10" fill="#6b6b6f" text-anchor="end">0</text>
</svg>
<div class="load-tooltip" style="display:none;">
  <div class="lt-date"></div>
  <div class="lt-row"><span class="sw sw-ctl"></span><span>fitness</span><span class="lt-ctl"></span></div>
  <div class="lt-row"><span class="sw sw-atl"></span><span>fatigue</span><span class="lt-atl"></span></div>
  <div class="lt-row"><span class="sw sw-tsb"></span><span>freshness</span><span class="lt-tsb"></span></div>
</div>
'''


# ---------- ring ----------

def ring(actual, target, label, sub):
    if target and target > 0:
        pct = max(0.0, min(actual / target, 1.0))
    else:
        pct = 0.0
    dash = pct * 100.5
    color = "var(--good)" if (actual or 0) >= (target or 0) else "var(--amber)"
    if target == 0 or target is None:
        color = "var(--muted)"
    val_label = f"{actual} / {target}" if target is not None else str(actual)
    return f'''
<div class="ring-wrap">
  <svg class="ring" viewBox="0 0 36 36">
    <circle cx="18" cy="18" r="16" fill="none" stroke="#eef0f3" stroke-width="3"></circle>
    <circle cx="18" cy="18" r="16" fill="none"
            stroke="{color}" stroke-width="3"
            stroke-dasharray="{dash:.1f} 100.5"
            stroke-linecap="round" transform="rotate(-90 18 18)"></circle>
  </svg>
  <div class="ring-value">{esc(val_label)}</div>
  <div class="ring-label">{esc(label)}</div>
  <div class="ring-sub">{esc(sub)}</div>
</div>
'''


# ---------- diverging-bar driver chart ----------

def metric_label(key):
    return {
        "hrv_sdnn": "HRV",
        "resting_hr": "Resting HR",
        "sleep_total_h": "Sleep total",
        "sleep_deep_h": "Sleep depth (deep)",
        "sleep_rem_h": "Sleep depth (REM)",
        "sleep_consistency_7d_stdev_h": "Sleep consistency",
        "wrist_temp_c": "Wrist temp",
        "hr_recovery_1min": "HR recovery",
    }.get(key, key.replace("_", " "))


def metric_tip(key):
    """One-sentence tooltip explaining the metric in plain English."""
    return {
        "hrv_sdnn": "Heart Rate Variability (SDNN). Higher than your baseline is generally favorable.",
        "resting_hr": "Resting Heart Rate. Lower than your baseline is generally favorable.",
        "sleep_total_h": "Total hours of sleep last night, including all stages.",
        "sleep_deep_h": "Hours of deep (slow-wave) sleep, the recovery-critical stage.",
        "sleep_rem_h": "Hours of REM sleep, supports memory and emotional regulation.",
        "sleep_consistency_7d_stdev_h": "Standard deviation of your bedtime/wake time over the last week. Lower means a more consistent schedule.",
        "wrist_temp_c": "Overnight wrist temperature deviation. Persistent rises can precede illness or under-recovery.",
        "hr_recovery_1min": "Heart-rate Recovery one minute after exercise stops. Higher is better.",
    }.get(key, "")


def driver_bars(drivers):
    """Diverging horizontal bars centered on z=0.

    Penalty-only signals (where the recovery-score module emits z=None
    because the driver is a 'no penalty' placeholder, e.g.
    sleep_consistency when the schedule is stable) are filtered out.
    They don't represent movement and would render as empty rows.
    """
    if not drivers:
        return ""
    drivers = [d for d in drivers if d.get("z") is not None]
    if not drivers:
        return ""
    drivers = sorted(drivers, key=lambda d: abs(d.get("z") or 0), reverse=True)[:8]
    zmax = max(abs(d.get("z") or 0) for d in drivers) or 1.0
    zmax = max(zmax, 1.5)  # ensure scale shows at least to ±1.5σ
    rows = []
    for dr in drivers:
        z = dr.get("z") or 0
        key = dr.get("metric")
        label = metric_label(key)
        # Direction-favorable mapping: drivers are already pre-signed
        # by health.py so that positive z = favorable. So z>0 always green.
        if z >= 0:
            cls = "good"
            width_pct = min(abs(z) / zmax, 1.0) * 50.0
            left_pct = 50.0
        else:
            if abs(z) >= 1.0:
                cls = "warn"
            elif abs(z) >= 0.5:
                cls = "amber"
            else:
                cls = "muted"
            width_pct = min(abs(z) / zmax, 1.0) * 50.0
            left_pct = 50.0 - width_pct
        tip = metric_tip(key)
        rows.append(f'''
<div class="driver-row" data-tip="{esc(tip)}">
  <span class="driver-label">{esc(label)}</span>
  <div class="driver-track">
    <div class="driver-axis"></div>
    <div class="driver-fill {cls}" style="left:{left_pct:.2f}%; width:{width_pct:.2f}%"></div>
  </div>
  <span class="driver-value {cls}">{signed(dr.get("z"), 2)}</span>
</div>''')
    return "\n".join(rows)


# ---------- per-muscle bar chart ----------

def muscle_bars(weekly_volume):
    current = weekly_volume.get("current", {})
    landmarks = weekly_volume.get("landmarks", {})
    if not current:
        return ""

    def gap_score(m):
        v = current.get(m, 0.0)
        lm = landmarks.get(m, {})
        mev, mrv = lm.get("mev", 0), lm.get("mrv", 0)
        if v < mev:
            return -2_000 + (mev - v)
        if v > mrv:
            return -1_000 + (v - mrv)
        return v - mev

    muscles = sorted(current.keys(), key=gap_score)[:14]
    xmax = max(
        max(current.values()) if current else 1,
        max((landmarks.get(m, {}).get("mrv", 0) for m in muscles), default=1),
    ) * 1.1 or 1.0

    rows = []
    for m in muscles:
        v = current.get(m, 0.0)
        lm = landmarks.get(m, {})
        mev = lm.get("mev", 0)
        mav = lm.get("mav", 0)
        mrv = lm.get("mrv", 0)
        muscle_title = m.replace("_", " ").title()
        if v < mev:
            band_class = "low"   # orange — under-stimulating, add
            status = "not enough"
            tip = (
                f"{muscle_title}: {v:.1f} sets per week. Below the productive range "
                f"(starts at {mev}). Add 1 to 2 sets next week to enter the productive band."
            )
        elif v <= mav:
            band_class = "prod"  # green — sweet spot
            status = "productive"
            tip = (
                f"{muscle_title}: {v:.1f} sets per week. In the productive range "
                f"({mev} to {mav}). Stay here, or push toward the upper band when recovery permits."
            )
        elif v <= mrv:
            band_class = "push"  # yellow-amber — pushing the limit
            status = "pushing limit"
            tip = (
                f"{muscle_title}: {v:.1f} sets per week. Above the productive range, "
                f"approaching your recoverable ceiling at {mrv}. You can grow here, but fatigue "
                f"costs rise. Watch recovery and don't add more."
            )
        else:
            band_class = "over"  # red — over recoverable ceiling, cut back
            status = "too much, cut back"
            tip = (
                f"{muscle_title}: {v:.1f} sets per week. Above your recoverable ceiling at {mrv}. "
                f"This volume costs more than it gives back. Drop 1 to 2 sets per week."
            )

        mev_x = (mev / xmax) * 100
        mav_x = (mav / xmax) * 100
        actual_x = (v / xmax) * 100
        rows.append(f'''
<div class="bar-row" data-tip="{esc(tip)}">
  <span class="bar-label">{esc(m.replace("_", " "))}</span>
  <div class="bar-track">
    <div class="bar-tick" style="left:{mev_x:.1f}%" data-label="MEV"></div>
    <div class="bar-tick" style="left:{mav_x:.1f}%" data-label="MAV"></div>
    <div class="bar-fill band-{band_class}" style="width:{actual_x:.1f}%"></div>
  </div>
  <span class="bar-status">
    <span class="bar-dot band-{band_class}"></span>
    <span class="bar-status-label">{esc(status)}</span>
    <span class="bar-num">{v:.1f}</span>
  </span>
</div>''')
    return "\n".join(rows)


# ---------- small indicators ----------

def confidence_dots(conf):
    """Render a 3-dot confidence indicator. `conf` is one of
    'high' / 'medium' / 'low' (anything else renders as 0 filled).
    """
    level = {"high": 3, "medium": 2, "low": 1}.get((conf or "").lower(), 0)
    dots = "".join(
        f'<span class="dot {"on" if i < level else "off"}"></span>'
        for i in range(3)
    )
    return f'<span class="confdots">{dots}</span>'


def freshness_scale(tsb):
    """Horizontal -15..+15 scale strip with a position marker.

    Six band labels match the six-state TSB gate table in SKILL.md
    Phase 2 (high fatigue / fatigued / carrying / balanced / fresh /
    well rested). Returns an empty string if tsb is None."""
    if tsb is None:
        return ""
    t_vis = max(-15.0, min(15.0, float(tsb)))
    x = ((t_vis + 15.0) / 30.0) * 600.0
    if t_vis <= -10 or t_vis > 10:
        marker_cls = "warn" if t_vis <= -10 else "amber"
    elif t_vis <= -5:
        marker_cls = "amber"
    else:
        marker_cls = "good"
    band_labels = [
        ("high fatigue",  50),
        ("fatigued",     150),
        ("carrying",     250),
        ("balanced",     350),
        ("fresh",        450),
        ("well rested",  550),
    ]
    labels_svg = "".join(
        f'<text x="{lx}" y="14" text-anchor="middle" class="fresh-band-lbl">{lbl}</text>'
        for lbl, lx in band_labels
    )
    tick_lines = "".join(
        f'<line x1="{i*100}" y1="26" x2="{i*100}" y2="36" class="fresh-tick"/>'
        for i in range(7)
    )
    tick_numbers = "".join(
        f'<text x="{i*100}" y="52" text-anchor="middle" class="fresh-tick-num">{n}</text>'
        for i, n in enumerate(["-15","-10","-5","0","+5","+10","+15"])
    )
    return f'''
<div class="fresh-scale">
  <svg viewBox="-30 0 660 76" preserveAspectRatio="xMidYMid meet" class="fresh-scale-svg" aria-hidden="true">
    {labels_svg}
    <line x1="0" y1="31" x2="600" y2="31" class="fresh-axis"/>
    {tick_lines}
    {tick_numbers}
    <polygon points="{x-7:.1f},18 {x+7:.1f},18 {x:.1f},29" class="fresh-marker-tri {marker_cls}"/>
    <line x1="{x:.1f}" y1="29" x2="{x:.1f}" y2="39" class="fresh-marker {marker_cls}"/>
    <text x="{x:.1f}" y="70" text-anchor="middle" class="fresh-marker-val {marker_cls}">{signed(tsb, 1)}</text>
  </svg>
</div>'''


def recovery_scale(score):
    """Horizontal 0..10 scale strip with a position marker.

    Three band labels match the dashboard spec for recovery score bands:
    depleted (<4.5, warn), moderate (4.5..6.5, amber), ready (>=6.5, good).
    Same visual structure as `freshness_scale()` so the two cards in the
    hero read as siblings. Returns empty string when score is None."""
    if score is None:
        return ""
    s = max(0.0, min(10.0, float(score)))
    x = (s / 10.0) * 600.0
    if s < 4.5:
        marker_cls = "warn"
    elif s < 6.5:
        marker_cls = "amber"
    else:
        marker_cls = "good"
    band_labels = [
        ("depleted",   135),   # midpoint of 0..4.5 → x=135
        ("moderate",   330),   # midpoint of 4.5..6.5 → x=330
        ("ready",      495),   # midpoint of 6.5..10 → x=495
    ]
    labels_svg = "".join(
        f'<text x="{lx}" y="14" text-anchor="middle" class="fresh-band-lbl">{lbl}</text>'
        for lbl, lx in band_labels
    )
    # Ticks at 0, 2, 4, 6, 8, 10 (x=0, 120, 240, 360, 480, 600).
    tick_lines = "".join(
        f'<line x1="{i*120}" y1="26" x2="{i*120}" y2="36" class="fresh-tick"/>'
        for i in range(6)
    )
    tick_numbers = "".join(
        f'<text x="{i*120}" y="52" text-anchor="middle" class="fresh-tick-num">{n}</text>'
        for i, n in enumerate(["0","2","4","6","8","10"])
    )
    return f'''
<div class="fresh-scale">
  <svg viewBox="-30 0 660 76" preserveAspectRatio="xMidYMid meet" class="fresh-scale-svg" aria-hidden="true">
    {labels_svg}
    <line x1="0" y1="31" x2="600" y2="31" class="fresh-axis"/>
    {tick_lines}
    {tick_numbers}
    <polygon points="{x-7:.1f},18 {x+7:.1f},18 {x:.1f},29" class="fresh-marker-tri {marker_cls}"/>
    <line x1="{x:.1f}" y1="29" x2="{x:.1f}" y2="39" class="fresh-marker {marker_cls}"/>
    <text x="{x:.1f}" y="70" text-anchor="middle" class="fresh-marker-val {marker_cls}">{fmt(score, 1)}</text>
  </svg>
</div>'''


def sparkline(values, status_class=None, w=80, h=24):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return f'<svg class="sparkline" viewBox="0 0 {w} {h}" width="{w}" height="{h}"></svg>'
    vmin = min(vals)
    vmax = max(vals)
    span = (vmax - vmin) or 1.0
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = (i / (n - 1)) * w
        y = h - 1 - ((v - vmin) / span) * (h - 2)
        pts.append(f"{x:.1f},{y:.1f}")
    cls = f" {status_class}" if status_class else ""
    return (f'<svg class="sparkline{cls}" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}">'
            f'<polyline fill="none" stroke="currentColor" stroke-width="1.4" '
            f'points="{" ".join(pts)}"/></svg>')


# ---------- shared metric "hero block" helper ----------


def metric_hero(value_html, status_word, status_cls,
                *, sublabel=None, comparison_html=""):
    """Reusable "hero block": big number + status word + optional scale.

    Every Trajectory domain card uses this shape to match the Today tab's
    hero visual language. Two contracts:

    - ``value_html`` is already-formatted HTML (e.g. ``"49.6 <span class='muted'>ml/kg/min</span>"``).
    - ``status_word`` is the short banded label ("above median", "elite").
    - ``status_cls`` is one of ``good`` / ``amber`` / ``warn`` / ``muted``
      and controls the value-colour binding.
    - ``sublabel`` is an optional small text below the status word.
    - ``comparison_html`` is an already-rendered comparison strip / scale.
    """
    sub = f'<div class="metric-hero-sub muted">{esc(sublabel)}</div>' if sublabel else ''
    return f'''
<div class="metric-hero">
  <div class="metric-hero-value {status_cls}">{value_html}</div>
  <div class="metric-hero-status {status_cls}">{esc(status_word)}</div>
  {sub}
  {comparison_html}
</div>'''


def secondary_metric_row(label, value_html, status_cls="muted",
                         *, sublabel=None, tip=None):
    """Stacked secondary-metric row used in domain cards under the hero
    block. Lighter weight than a hero, heavier than a generic data row.

    Use for the second / third metric inside a domain card. Three metrics
    max per domain so the card stays scannable.
    """
    tip_attr = f' data-tip="{esc(tip)}"' if tip else ''
    sub_html = f'<div class="secondary-sub muted">{esc(sublabel)}</div>' if sublabel else ''
    return f'''
<div class="secondary-metric"{tip_attr}>
  <div class="secondary-label">{esc(label)}</div>
  <div class="secondary-value {status_cls}">{value_html}</div>
  {sub_html}
</div>'''


# ---------- longevity / trajectory components ----------

def comparison_strip(value, p50, p75, p95, longevity, *, unit="",
                     longevity_label="longevity target",
                     baseline=None, baseline_label="your baseline"):
    """4-line comparison strip used across the Trajectory tab.

    Renders a horizontal scale with the four canonical reference markers
    (population p50 / p75 / p95 / longevity target), plus optional
    personal baseline. The user's current ``value`` is placed on the
    same axis with a colored marker that resolves its band against the
    reference points.

    Use when a metric has age-cohort norms (VO2, HRV-SDNN, RHR, HRR).
    For metrics without published norms, prefer ``simple_comparison_strip``.
    """
    if value is None or p50 is None or p95 is None:
        return ""
    # Establish the axis. Use 0 to longevity*1.15 as upper bound; lower bound
    # is min(p50*0.7, value*0.9). For metrics where lower-is-better (RHR),
    # the caller can flip; here we keep the default left-low / right-high
    # so positive numbers grow rightward.
    longevity = longevity or p95
    span_lo = min(p50 * 0.7, value * 0.9, baseline * 0.9 if baseline else p50 * 0.7)
    span_hi = max(longevity * 1.12, value * 1.1)
    span = max(span_hi - span_lo, 1.0)

    def x(v):
        return 50.0 + ((v - span_lo) / span) * 540.0

    # Marker color: matches the band the user's value sits in.
    if value >= longevity:
        cls = "good"
    elif value >= p95:
        cls = "good"
    elif value >= p75:
        cls = "amber"
    elif value >= p50:
        cls = "amber"
    else:
        cls = "warn"

    band_marks = []
    band_labels = [
        ("p50", p50, "median"),
        ("p75", p75, "good"),
        ("p95", p95, "elite"),
        ("target", longevity, longevity_label),
    ]
    for name, mv, lbl in band_labels:
        mx = x(mv)
        band_marks.append(
            f'<g class="cmp-band cmp-band-{name}">'
            f'<line x1="{mx:.1f}" y1="34" x2="{mx:.1f}" y2="48" />'
            f'<text x="{mx:.1f}" y="60" text-anchor="middle" class="cmp-band-lbl">{esc(lbl)}</text>'
            f'<text x="{mx:.1f}" y="72" text-anchor="middle" class="cmp-band-num">{mv:g}</text>'
            f'</g>'
        )
    user_x = x(value)
    baseline_html = ""
    if baseline is not None:
        bx = x(baseline)
        baseline_html = (
            f'<g class="cmp-baseline">'
            f'<line x1="{bx:.1f}" y1="20" x2="{bx:.1f}" y2="48" stroke-dasharray="3,3" />'
            f'<text x="{bx:.1f}" y="14" text-anchor="middle" class="cmp-band-lbl">{esc(baseline_label)}</text>'
            f'</g>'
        )

    unit_html = f' <tspan class="cmp-unit">{esc(unit)}</tspan>' if unit else ""
    return f'''
<div class="cmp-strip">
  <svg viewBox="0 0 620 90" preserveAspectRatio="xMidYMid meet" class="cmp-svg" aria-hidden="true">
    <line x1="50" y1="40" x2="590" y2="40" class="cmp-axis"/>
    {''.join(band_marks)}
    {baseline_html}
    <g class="cmp-user cmp-user-{cls}">
      <polygon points="{user_x-7:.1f},25 {user_x+7:.1f},25 {user_x:.1f},37" />
      <text x="{user_x:.1f}" y="20" text-anchor="middle" class="cmp-user-val">{value:g}{unit_html}</text>
    </g>
  </svg>
</div>'''


def domain_score_dial(score, band, label, *, n_components=None, w=120, h=80):
    """0-100 score dial used by every Trajectory domain card header.

    Semi-circular gauge with the score arc filling clockwise. Color
    matches the band class. Label sits below. Optional ``n_components``
    shows under the label when not None.
    """
    if score is None:
        return (
            f'<div class="domain-dial">'
            f'<div class="domain-dial-num muted">·</div>'
            f'<div class="domain-dial-lbl muted">no data</div></div>'
        )
    s = max(0.0, min(100.0, float(score)))
    # Arc geometry: half-circle, radius 40, centered at (60, 60). Sweep
    # from left (180°) to right (0°) clockwise as score increases.
    import math as _math
    angle_rad = _math.pi * (1.0 - s / 100.0)  # 180° at 0, 0° at 100
    end_x = 60 + 40 * _math.cos(angle_rad)
    end_y = 60 - 40 * _math.sin(angle_rad)
    large_arc = 1 if s > 50 else 0
    arc_path = f"M 20 60 A 40 40 0 {large_arc} 1 {end_x:.2f} {end_y:.2f}"
    background_path = "M 20 60 A 40 40 0 1 1 100 60"
    sub = f' <span class="domain-dial-sub">{n_components} inputs</span>' if n_components else ''
    return f'''
<div class="domain-dial">
  <svg viewBox="0 0 120 75" class="domain-dial-svg" aria-hidden="true">
    <path d="{background_path}" class="domain-dial-bg" />
    <path d="{arc_path}" class="domain-dial-fg domain-dial-{band}" />
    <text x="60" y="62" text-anchor="middle" class="domain-dial-num domain-dial-{band}">{s:.0f}</text>
  </svg>
  <div class="domain-dial-lbl">{esc(label or "")}{sub}</div>
</div>'''


def risk_flag_pill(status):
    """Status pill for personalized risk flags. ``status`` is one of
    ``tracked`` / ``due`` / ``overdue`` / ``active`` / ``unknown``.
    """
    cls_map = {
        "tracked":  "good",
        "due":      "amber",
        "overdue":  "warn",
        "active":   "warn",
        "unknown":  "muted",
    }
    cls = cls_map.get(status, "muted")
    return f'<span class="pill {cls}">{esc(status or "unknown")}</span>'


# ---------- tier-history strip ----------

def tier_history_strip(history):
    """Horizontal strip of N coloured dots, one per day, coloured by that
    day's session-recommendation tier (A/B/C/D/E). On hover each dot
    tooltips the date + tier + dominant signal.

    `history` is the list emitted by `compute_tier_history` — oldest first.
    """
    if not history:
        return ""
    tier_colour = {
        "A": "var(--warn)",          # red
        "B": "var(--amber)",         # amber
        "C": "var(--muscle-push)",   # softer amber / yellow (same hex as muscle-push)
        "D": "var(--good)",          # green
        "E": "var(--accent)",        # blue
    }
    tier_word = {
        "A": "rest",
        "B": "reactive deload",
        "C": "downgrade",
        "D": "green",
        "E": "over-recovered",
    }
    n = len(history)
    if n == 0:
        return ""
    dot_w = 26
    gap = 4
    total_w = n * dot_w + (n - 1) * gap
    parts = []
    for i, entry in enumerate(history):
        x = i * (dot_w + gap)
        tier = entry.get("tier", "")
        colour = tier_colour.get(tier, "var(--muted)")
        word = tier_word.get(tier, "")
        signal = entry.get("dominant_signal", "")
        tip = f"{entry.get('date','')} · {word}{(' · ' + signal) if signal else ''}"
        parts.append(
            f'<rect x="{x}" y="2" width="{dot_w}" height="22" rx="4" ry="4" '
            f'fill="{colour}" data-tip="{esc(tip)}"></rect>'
        )
    # Date labels at first and last position
    first_date = history[0].get("date", "")[5:]   # MM-DD
    last_date = history[-1].get("date", "")[5:]
    return f'''
<div class="tier-history-strip">
  <svg viewBox="0 0 {total_w} 38" preserveAspectRatio="xMinYMid meet" class="tier-strip-svg" aria-hidden="true">
    {''.join(parts)}
    <text x="0" y="34" class="tier-strip-lbl">{first_date}</text>
    <text x="{total_w}" y="34" text-anchor="end" class="tier-strip-lbl">{last_date} (today)</text>
  </svg>
</div>'''


# ---------- workout markdown embed ----------

def embed_workout_markdown(md_text: str) -> str:
    """Embed the raw markdown into a script tag so inline JS can render
    it on the Workout tab. The .md file remains the source of truth on
    disk; this is for in-browser viewing only."""
    safe = (md_text.replace("</script>", "<\\/script>"))
    return f'<script type="text/markdown" id="workout-md">{safe}</script>'
