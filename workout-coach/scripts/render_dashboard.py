"""Render the assessment HTML dashboard for one person.

Inputs:
  --tracker     path to JSON from read_tracker.py (or "-" for stdin)
  --coach       path to coach_reads.json (LLM-authored advice strings)
  --workout-md  path to <date>-workout.md (embedded into the Workout tab)
  --out         where to write the HTML
  --person      person name for the header

The LLM authors the advice strings + workout markdown. This script owns
all layout, visualization, validation, and the final HTML composition.
Single-file output: inline CSS / SVG / JS, no external resources.

Strict copy rules (enforced by `validate_coach_reads`):
  * No em-dashes anywhere in coach text.
  * No bare abbreviations except those in `KNOWN_TERMS` (and even those
    are wrapped in dotted-underline tooltips by the renderer; the
    coach text uses plain language by default).
  * Each string <= 280 characters.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


# ---------- copy validation ----------

# Terms that get a dotted-underline tooltip when they appear in the
# coach text. The renderer auto-wraps them. The coach is encouraged
# to use the plain-English equivalent instead.
KNOWN_TERMS = {
    "CTL":    ("Chronic Training Load",
               "A 42-day moving average of your training stress. It moves slowly and represents your fitness baseline. On this dashboard the chart's blue line is your CTL."),
    "ATL":    ("Acute Training Load",
               "A 7-day moving average of your training stress. It moves quickly and represents your current fatigue. On this dashboard the chart's orange dashed line is your ATL."),
    "TSB":    ("Training Stress Balance",
               "Your fitness minus your current fatigue. Positive numbers mean you are fresh and ready, negative numbers mean fatigue is accumulating. Above +5 is fresh, below -10 starts to be tired."),
    "e1RM":   ("Estimated one-rep max",
               "Your single-rep capacity extrapolated from your working sets. It lets you track strength changes without ever doing a true one-rep test."),
    "MEV":    ("Minimum Effective Volume",
               "The smallest weekly set count that still drives growth in a muscle. Below this number, training does not produce a meaningful adaptation."),
    "MAV":    ("Maximum Adaptive Volume",
               "The upper end of the productive range for a muscle. Beyond this, extra sets cost more fatigue than they give back in growth."),
    "MRV":    ("Maximum Recoverable Volume",
               "The most weekly sets a muscle can take and still recover from. Above this you accumulate fatigue you cannot pay back, raising injury and overtraining risk."),
    "SDNN":   ("Standard deviation of NN intervals",
               "A measure of overnight heart-rate variability. It tracks how relaxed your nervous system was during sleep. Higher relative to your baseline is favorable."),
    "HRR":    ("Heart-rate recovery",
               "How many beats per minute your heart rate drops in the first minute after exercise. Higher means your autonomic system shifts back to rest faster."),
    "RHR":    ("Resting heart rate",
               "Your heart rate at rest, measured overnight. Lower relative to your 60-day baseline is favorable. A sustained rise of 5+ bpm often signals under-recovery or illness."),
    "HRV":    ("Heart rate variability",
               "The variation in the time between heartbeats overnight, measured here as SDNN. Higher relative to your baseline is favorable. Lower can mean under-recovery or stress."),
    "Z2":     ("Zone 2",
               "Aerobic cardio at roughly 60-70 percent of your maximum heart rate. You can hold a conversation. It builds mitochondrial density and the aerobic base."),
    "Z5":     ("Zone 5",
               "Near-maximal intervals at 90 percent or more of your maximum heart rate. The most efficient zone for raising your peak oxygen uptake."),
    "VO2max": ("Peak oxygen uptake",
               "The maximum rate at which your body can use oxygen during intense exercise. A standard fitness ceiling and one of the strongest predictors of long-term healthspan."),
    "HSP":    ("Heat Shock Proteins",
               "Molecular chaperones induced by heat exposure. They are linked to many of sauna's longevity-associated effects. Induction needs roughly 20 minutes at or above 80 degrees Celsius."),
}

EM_DASH = "—"
COACH_STRING_MAX = 280


# Card keys the renderer knows how to surface a coach callout for.
# Listed here so the validator can warn when one is missing; the
# corresponding card still renders (just without a callout) which is
# a softer failure than a hard validator error.
COACH_CARD_KEYS = (
    "recovery_drivers", "activity_rings", "training_load", "muscle_volume",
    "strength", "vitals", "sleep", "recovery_practices",
)


def validate_coach_reads(coach: dict) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)``.

    Errors are hard failures (the renderer refuses to write the HTML).
    Warnings are surfaced to stderr but don't block the render. A
    missing ``cards.<key>`` for a documented card is a warning, not an
    error, because the card itself still renders cleanly without a
    callout."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(coach, dict):
        return (["coach reads must be a JSON object"], warnings)

    headline = coach.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        errors.append("missing or empty `headline`")
    elif EM_DASH in headline:
        errors.append("`headline` contains an em-dash (—). Use a period or comma.")
    elif len(headline) > COACH_STRING_MAX * 2:
        errors.append(f"`headline` is over {COACH_STRING_MAX*2} characters")

    cards = coach.get("cards") or {}
    if not isinstance(cards, dict):
        errors.append("`cards` must be a JSON object")
        return (errors, warnings)

    for key, text in cards.items():
        if not isinstance(text, str):
            errors.append(f"cards.{key} must be a string")
            continue
        if EM_DASH in text:
            errors.append(f"cards.{key} contains an em-dash (—). Use a period or comma.")
        if len(text) > COACH_STRING_MAX:
            errors.append(
                f"cards.{key} is {len(text)} chars; max is {COACH_STRING_MAX}"
            )

    for key in COACH_CARD_KEYS:
        if not cards.get(key):
            warnings.append(f"cards.{key} missing or empty; that card will render without a coach callout")

    return (errors, warnings)


# Wrap KNOWN_TERMS with a tooltip span when they appear in any coach
# string. Whole-word, case-sensitive (so "Cold" doesn't match "CTL").
# Each term wraps at most once per string so we don't double-wrap when
# the user repeats a term.
_TERM_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, KNOWN_TERMS.keys()), key=len, reverse=True)) + r")\b"
)


def auto_wrap_terms(text: str) -> str:
    """Wrap each known abbreviation in a tooltip span.

    Only the FIRST occurrence of each term per string is wrapped; later
    occurrences are left plain. This is intentional, not a bug: wrapping
    every occurrence creates dotted-underline visual noise on lines that
    repeat a term. Do not 'fix' this to wrap all occurrences."""
    seen: set[str] = set()

    def _sub(m):
        t = m.group(1)
        if t in seen:
            return t
        seen.add(t)
        full, expl = KNOWN_TERMS[t]
        return f'<span class="term" data-tip="{esc(full)}. {esc(expl)}">{esc(t)}</span>'

    return _TERM_PATTERN.sub(_sub, esc(text))


# ---------- small helpers ----------

def esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def fmt(v, digits=1, default="·"):
    if v is None:
        return default
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if math.isnan(v):
            return default
        if isinstance(v, int) or digits == 0:
            return f"{v:.0f}"
        return f"{v:.{digits}f}"
    return str(v)


def signed(v, digits=1, default="·"):
    if v is None:
        return default
    return f"{v:+.{digits}f}"


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


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


# ---------- sparkline ----------

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
        f'<text x="{lx}" y="10" text-anchor="middle" class="fresh-band-lbl">{lbl}</text>'
        for lbl, lx in band_labels
    )
    tick_lines = "".join(
        f'<line x1="{i*100}" y1="20" x2="{i*100}" y2="28" class="fresh-tick"/>'
        for i in range(7)
    )
    tick_numbers = "".join(
        f'<text x="{i*100}" y="42" text-anchor="middle" class="fresh-tick-num">{n}</text>'
        for i, n in enumerate(["-15","-10","-5","0","+5","+10","+15"])
    )
    return f'''
<div class="fresh-scale">
  <svg viewBox="0 0 600 60" preserveAspectRatio="xMidYMid meet" class="fresh-scale-svg" aria-hidden="true">
    {labels_svg}
    <line x1="0" y1="24" x2="600" y2="24" class="fresh-axis"/>
    {tick_lines}
    {tick_numbers}
    <polygon points="{x-5:.1f},14 {x+5:.1f},14 {x:.1f},22" class="fresh-marker-tri {marker_cls}"/>
    <line x1="{x:.1f}" y1="22" x2="{x:.1f}" y2="30" class="fresh-marker {marker_cls}"/>
    <text x="{x:.1f}" y="56" text-anchor="middle" class="fresh-marker-val {marker_cls}">{signed(tsb, 1)}</text>
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


# ---------- workout markdown embed ----------

def embed_workout_markdown(md_text: str) -> str:
    """Embed the raw markdown into a script tag so inline JS can render
    it on the Workout tab. The .md file remains the source of truth on
    disk; this is for in-browser viewing only."""
    safe = (md_text.replace("</script>", "<\\/script>"))
    return f'<script type="text/markdown" id="workout-md">{safe}</script>'


# ---------- stylesheet ----------

STYLESHEET = """
:root {
  --bg: #f7f7f8;
  --card: #ffffff;
  --border: #ececec;
  --border-strong: #d8d8d9;
  --text: #1c1c1e;
  --muted: #6b6b6f;
  --good: #34c759;
  --amber: #ff9f0a;
  --warn: #ff3b30;
  --accent: #0a84ff;

  /* Per-muscle volume bands. Four distinct hues so opposite ends of
     the spectrum (not-enough vs too-much) never share a color. */
  --muscle-low:  #ff9500; /* orange  , below MEV, "not enough" */
  --muscle-prod: #34c759; /* green   , MEV..MAV, "productive" */
  --muscle-push: #ffcc00; /* yellow  , MAV..MRV, "pushing limit" */
  --muscle-over: #ff3b30; /* red     , above MRV, "too much, cut back" */
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text",
        "Inter", system-ui, sans-serif;
  -webkit-font-smoothing: antialiased; }

/* layout */
.page { max-width: 980px; margin: 0 auto; padding: 32px 20px 60px; }
header.page-head h1 { margin: 0; font-size: 28px; font-weight: 600;
  letter-spacing: -0.01em; }
header.page-head .meta { color: var(--muted); margin-top: 4px;
  font-size: 14px; }
/* Coach's summary card sits above the hero. Same chrome as other cards.
   It uses the standard card style; the body just gets a slightly larger
   line-height for readability. */
.summary { margin-bottom: 14px; }
.summary .body { font-size: 16px; line-height: 1.6;
  color: var(--text); max-width: 760px; }

/* tabs */
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border-strong);
  margin-bottom: 18px; position: sticky; top: 0; background: var(--bg);
  padding-top: 6px; z-index: 50; }
.tab { padding: 10px 18px; cursor: pointer; font-size: 14px;
  font-weight: 500; color: var(--muted); border: none; background: none;
  border-bottom: 2px solid transparent; }
.tab[aria-selected="true"] { color: var(--accent);
  border-bottom-color: var(--accent); }
.tab:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.tab-panel { display: none; }
.tab-panel[data-active="true"] { display: grid; gap: 14px; }

/* card */
.card { background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 20px 22px; }
.card h2 { margin: 0 0 14px; font-size: 12px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }

/* hero */
.hero { display: grid; grid-template-columns: 5fr 7fr; gap: 14px; }
.hero .metric { display: flex; flex-direction: column; }
/* Recovery card has only a few lines of content; center it vertically so
   the score doesn't sit stranded at the top of a card that stretches to
   match the taller Freshness card. */
.hero .metric--compact { justify-content: center; }
.metric .value { font-size: 48px; font-weight: 600;
  letter-spacing: -0.02em; line-height: 1; }
.metric .value .denom { font-size: 22px; color: var(--muted);
  font-weight: 400; }
.metric .sub { color: var(--muted); margin-top: 12px; font-size: 14px;
  display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.metric.good .value { color: var(--good); }
.metric.amber .value { color: var(--amber); }
.metric.warn .value { color: var(--warn); }

/* coach callout, typographic differentiation only; no box, no border,
   no tint. A thin hairline rule and a small-caps label do the work. */
.coach { margin-top: 18px; padding-top: 14px;
  border-top: 1px solid #f0f0f1; }
.coach .label { font-size: 10.5px; font-weight: 600;
  letter-spacing: 0.10em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 4px; }
.coach .text { font-size: 14px; line-height: 1.55; color: var(--text); }

/* tooltip system */
.term, [data-tip] { position: relative; }
.term { border-bottom: 1px dotted var(--muted); cursor: help; }
.tooltip {
  position: fixed;
  background: #1c1c1e; color: #ffffff;
  border-radius: 8px; padding: 10px 12px;
  font-size: 12.5px; line-height: 1.5;
  max-width: 280px; box-shadow: 0 8px 24px rgba(0,0,0,0.22);
  pointer-events: none; opacity: 0; transition: opacity 0.12s;
  z-index: 200;
}
.tooltip.show { opacity: 1; }
.tooltip strong { color: #ffffff; font-weight: 600; }

/* drivers */
.driver-row { display: grid; grid-template-columns: 150px 1fr 60px;
  align-items: center; gap: 12px; padding: 5px 0;
  font-size: 13px; cursor: help; }
.driver-label { color: var(--text); }
.driver-track { position: relative; height: 12px;
  background: #f0f1f3; border-radius: 6px; overflow: hidden; }
.driver-axis { position: absolute; left: 50%; top: 0; width: 1px;
  height: 100%; background: var(--border-strong); }
.driver-fill { position: absolute; top: 0; height: 100%; border-radius: 6px; }
.driver-fill.good { background: var(--good); }
.driver-fill.amber { background: var(--amber); }
.driver-fill.warn { background: var(--warn); }
.driver-fill.muted { background: #c1c1c5; }
.driver-value { font-variant-numeric: tabular-nums; font-weight: 500;
  text-align: right; }
.driver-value.good { color: var(--good); }
.driver-value.amber { color: var(--amber); }
.driver-value.warn { color: var(--warn); }
.driver-value.muted { color: var(--muted); }
.driver-axis-row { display: grid; grid-template-columns: 150px 1fr 60px;
  font-size: 11px; color: var(--muted); padding-bottom: 10px; }
.driver-axis-row .axis-labels { display: flex; justify-content: space-between; }

/* rings */
.rings { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px;
  padding: 6px 0; }
.ring-wrap { text-align: center; }
.ring { width: 76px; height: 76px; }
.ring-value { font-size: 14px; font-weight: 600; margin-top: 6px; }
.ring-label { font-size: 13px; color: var(--text); }
.ring-sub { font-size: 11px; color: var(--muted); margin-top: 2px; }

/* NEAT sub-section under the activity rings. Subsection header + pill
   at the top, three equal stat cells below. Hairline rule above so it
   reads as a related sub-row of the rings card, not a new card. */
.neat-section { margin-top: 16px; padding-top: 14px;
  border-top: 1px solid #f0f0f1; }
.neat-head { display: flex; align-items: center; justify-content: space-between;
  gap: 10px; margin-bottom: 12px; }
.neat-head-label { font-size: 11px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--muted); }
.neat-cells { display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 18px; }
.neat-cell { font-size: 13px; }
.neat-num { font-size: 20px; font-weight: 600; line-height: 1.1;
  color: var(--text); font-variant-numeric: tabular-nums; }
.neat-unit { font-size: 11px; color: var(--muted); font-weight: 400;
  margin-left: 4px; }
.neat-desc { font-size: 12px; color: var(--muted); margin-top: 4px; }

/* training-load chart */
.load-chart { width: 100%; height: auto; cursor: crosshair; }
.load-chart .hit { pointer-events: all; }
/* Single combined "summary" row below the chart: 4 stat cells, each
   carrying its line-color swatch + tooltipped name + current value.
   Replaces the prior split between .load-legend (chips) and .load-stats
   (numbers) which duplicated the metric names and made the line→value
   relationship ambiguous. */
.load-summary { display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 18px; margin-top: 14px; }
.load-summary-cell { display: flex; flex-direction: column; gap: 4px; }
.load-summary-name { display: inline-flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--muted); }
.load-summary-name .sw { display: inline-block; width: 18px; height: 2px;
  vertical-align: middle; }
.load-summary-value { font-size: 20px; font-weight: 600; color: var(--text);
  font-variant-numeric: tabular-nums; line-height: 1.1; }
/* Line/band swatches reused by both the summary row and the floating
   tooltip on the chart, so they stay top-level. */
.sw-ctl { background: #0a84ff; }
.sw-atl { background: 0; border-top: 2px dashed #ff9f0a; height: 0; }
.sw-tsb { background: linear-gradient(#ff9f0a40, #34c75922); height: 8px !important; }

.load-tooltip { position: fixed; background: #1c1c1e; color: #ffffff;
  border-radius: 8px; padding: 10px 12px; font-size: 12px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.22);
  pointer-events: none; z-index: 200; }
.load-tooltip .lt-date { font-weight: 600; margin-bottom: 4px; }
.load-tooltip .lt-row { display: flex; align-items: center; gap: 8px;
  margin: 2px 0; }
.load-tooltip .lt-row .sw { display: inline-block; width: 12px; height: 2px; }
.load-tooltip .lt-row span:last-child { margin-left: auto;
  font-variant-numeric: tabular-nums; font-weight: 600; }

/* muscle bars, four distinct band colors, fixed-width dots, two thin
   tick marks per row showing MEV and MAV. No background band — that
   was causing the 3-color confusion on under-MEV rows. */
.muscle-legend { font-size: 12px; color: var(--muted);
  margin-bottom: 14px; padding-bottom: 12px;
  border-bottom: 1px solid #f4f4f6; }
.muscle-legend-chips { display: flex; gap: 20px; flex-wrap: wrap;
  align-items: center; }
.muscle-legend-chip { display: inline-flex; align-items: center; gap: 6px; }
.muscle-legend-explain { margin-top: 10px; line-height: 1.5; }

.bar-row { display: grid; grid-template-columns: 140px 1fr 240px;
  align-items: center; gap: 14px; padding: 7px 0;
  font-size: 13px; cursor: help; }
.bar-label { color: var(--text); text-transform: capitalize; }
.bar-track { position: relative; height: 10px;
  background: #f1f2f4; border-radius: 5px; }
.bar-tick { position: absolute; top: -2px; height: 14px; width: 1px;
  background: #b9b9bb; }
.bar-fill { position: absolute; top: 0; left: 0; height: 100%;
  border-radius: 5px; }
.bar-fill.band-low  { background: var(--muscle-low); }
.bar-fill.band-prod { background: var(--muscle-prod); }
.bar-fill.band-push { background: var(--muscle-push); }
.bar-fill.band-over { background: var(--muscle-over); }

.bar-status { display: inline-flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--muted); }
.bar-status-label { white-space: nowrap; }
.bar-dot { display: inline-block; width: 9px; height: 9px;
  border-radius: 50%; flex: 0 0 9px; }
.bar-dot.band-low  { background: var(--muscle-low); }
.bar-dot.band-prod { background: var(--muscle-prod); }
.bar-dot.band-push { background: var(--muscle-push); }
.bar-dot.band-over { background: var(--muscle-over); }
.bar-num { font-variant-numeric: tabular-nums; font-weight: 500;
  color: var(--text); margin-left: auto; }

/* 3-dot confidence indicator. Three dots = high, two = medium,
   one = low. No tooltip; the dots are self-explanatory. */
.confdots { display: inline-flex; align-items: center; gap: 3px;
  vertical-align: middle; }

/* Freshness (TSB) scale strip under the +5.0 number in the hero. */
.fresh-scale { margin-top: 12px; }
.fresh-scale-svg { width: 100%; height: auto; max-height: 96px;
  display: block; }
.fresh-band-lbl { font-size: 9px; fill: var(--muted);
  font-family: inherit; }
.fresh-tick-num { font-size: 9px; fill: var(--muted);
  font-family: inherit; font-variant-numeric: tabular-nums; }
.fresh-axis { stroke: var(--border-strong); stroke-width: 1; }
.fresh-tick { stroke: var(--border-strong); stroke-width: 1; }
.fresh-marker { stroke-width: 1.5; }
.fresh-marker.good  { stroke: var(--good); }
.fresh-marker.amber { stroke: var(--amber); }
.fresh-marker.warn  { stroke: var(--warn); }
.fresh-marker-tri.good  { fill: var(--good); }
.fresh-marker-tri.amber { fill: var(--amber); }
.fresh-marker-tri.warn  { fill: var(--warn); }
.fresh-marker-val { font-size: 11px; font-weight: 600;
  font-family: inherit; font-variant-numeric: tabular-nums; }
.fresh-marker-val.good  { fill: var(--good); }
.fresh-marker-val.amber { fill: var(--amber); }
.fresh-marker-val.warn  { fill: var(--warn); }
.confdots .dot { display: inline-block; width: 7px; height: 7px;
  border-radius: 50%; }
.confdots .dot.on  { background: var(--accent); }
.confdots .dot.off { background: #dadadc; }

/* tables */
table { width: 100%; border-collapse: collapse; font-size: 14px;
  table-layout: fixed; }
th, td { text-align: left; padding: 8px 10px 8px 0;
  border-bottom: 1px solid #f4f4f6; }
th { font-weight: 500; color: var(--muted); font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.06em; }
td.num { font-variant-numeric: tabular-nums; }
td.arrow { font-size: 16px; font-weight: 600; }

/* Explicit column widths per data table so long labels in column 1
   don't absorb all the slack and squeeze the numeric columns. */
.strength-table th:nth-child(1), .strength-table td:nth-child(1) { width: auto; }
.strength-table th:nth-child(2), .strength-table td:nth-child(2) { width: 110px; }
.strength-table th:nth-child(3), .strength-table td:nth-child(3) { width: 140px; }
.strength-table th:nth-child(4), .strength-table td:nth-child(4) { width: 60px; }
.strength-table th:nth-child(5), .strength-table td:nth-child(5) { width: 70px; }

.vitals-table th:nth-child(1), .vitals-table td:nth-child(1) { width: auto; }
.vitals-table th:nth-child(2), .vitals-table td:nth-child(2) { width: 120px; }
.vitals-table th:nth-child(3), .vitals-table td:nth-child(3) { width: 120px; padding-right: 18px; }
.vitals-table th:nth-child(4), .vitals-table td:nth-child(4) { width: 130px; }

.wow-table th:nth-child(1), .wow-table td:nth-child(1) { width: auto; }
.wow-table th:nth-child(2), .wow-table td:nth-child(2) { width: 80px; }
.wow-table th:nth-child(3), .wow-table td:nth-child(3) { width: 80px; }
.wow-table th:nth-child(4), .wow-table td:nth-child(4) { width: 80px; }
.wow-table th:nth-child(5), .wow-table td:nth-child(5) { width: 30px; }
.wow-table th:nth-child(6), .wow-table td:nth-child(6) { width: 40px; }

/* Suppress the last-row hairline so the table doesn't print an
   orphan border-bottom above the empty space before the coach
   callout (the coach's own border-top already separates the two). */
.strength-table tbody tr:last-child td,
.vitals-table tbody tr:last-child td,
.wow-table tbody tr:last-child td { border-bottom: none; }
.arrow.good { color: var(--good); }
.arrow.warn { color: var(--warn); }
.arrow.muted { color: var(--muted); }
.muted { color: var(--muted); }
.sparkline { vertical-align: middle; }
.sparkline.good { color: var(--good); }
.sparkline.amber { color: var(--amber); }
.sparkline.warn { color: var(--warn); }
.sparkline.muted { color: var(--muted); }

/* sleep card */
.sleep-hero { display: grid; grid-template-columns: 220px 1fr; gap: 24px;
  align-items: center; padding: 8px 0 18px; }
.sleep-hero .value { font-size: 36px; font-weight: 600;
  letter-spacing: -0.02em; line-height: 1; }
.sleep-hero .denom { font-size: 18px; color: var(--muted); font-weight: 400; }
.sleep-hero .sub { color: var(--muted); margin-top: 6px; font-size: 13px; }
.sleep-stack-wrap { }
.sleep-stack { display: flex; width: 100%; height: 22px;
  border-radius: 6px; overflow: hidden;
  border: 1px solid var(--border); }
.sleep-stack .stage { height: 100%; }
.sleep-stack-legend { display: flex; gap: 14px; flex-wrap: wrap;
  margin-top: 10px; font-size: 12px; color: var(--muted); }
.sleep-stack-legend .dot { display: inline-block; width: 10px;
  height: 10px; border-radius: 50%; vertical-align: middle;
  margin-right: 5px; }
.sleep-rows { display: grid; gap: 6px;
  padding-top: 14px; border-top: 1px solid #f4f4f6; }
.sleep-row { display: grid; grid-template-columns: 12px 200px 1fr 150px;
  align-items: center; gap: 14px; padding: 6px 0; font-size: 13px;
  cursor: help; }
.sleep-row-label { color: var(--text); }
.sleep-row-value { color: var(--text); }
.sleep-row-status { text-align: right; font-size: 12px;
  color: var(--muted); }
.sleep-row-status.good  { color: var(--good); }
.sleep-row-status.amber { color: var(--amber); }
.sleep-row-status.warn  { color: var(--warn); }
.sleep-outliers { margin-top: 14px; padding: 10px 12px;
  background: #fafafa; border-radius: 6px;
  font-size: 13px; color: var(--text); }
.sleep-outliers.muted { color: var(--muted); }

/* recovery practices */
.practices { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.practice { padding: 14px 16px; background: #fafafb;
  border: 1px solid var(--border); border-radius: 10px; }
.practice .title { font-size: 13px; font-weight: 600;
  color: var(--text); margin-bottom: 8px; }
.practice .big { font-size: 28px; font-weight: 600;
  letter-spacing: -0.01em; line-height: 1; }
.practice .big .unit { font-size: 13px; font-weight: 400;
  color: var(--muted); margin-left: 4px; }
.practice .pill { display: inline-block; padding: 3px 9px;
  border-radius: 999px; font-size: 11px; font-weight: 500;
  margin-top: 8px; }
.pill.good { color: var(--good); background: rgba(52,199,89,0.12); }
.pill.amber { color: var(--amber); background: rgba(255,159,10,0.12); }
.pill.warn { color: var(--warn); background: rgba(255,59,48,0.12); }
.pill.muted { color: var(--muted); background: #eeeeef; }
.practice .detail { color: var(--muted); font-size: 12.5px;
  margin-top: 8px; line-height: 1.5; }
.practice .recent { margin-top: 8px; padding-top: 8px;
  border-top: 1px solid var(--border); font-size: 12px;
  color: var(--muted); }

/* workout tab, each `## Workout N: TYPE` becomes a card. */
.workout-card { background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 18px 22px; margin-bottom: 14px; }
.workout-card h2 { margin: 0 0 12px; font-size: 17px;
  font-weight: 600; letter-spacing: -0.01em; color: var(--text);
  text-transform: none; }
.workout-card .placeholders { color: var(--muted); font-size: 13px;
  margin-bottom: 14px; padding-bottom: 12px;
  border-bottom: 1px solid #f4f4f6; }
.workout-card .placeholder-row { padding: 2px 0;
  font-family: ui-monospace, "SF Mono", Menlo, Monaco, monospace;
  font-size: 12.5px; }
.workout-card ul { list-style: none; padding: 0; margin: 0; }
.workout-card > ul > li { padding: 5px 0 5px 18px; font-size: 14px;
  color: var(--text); font-variant-numeric: tabular-nums;
  position: relative; line-height: 1.5; }
.workout-card > ul > li::before { content: "•";
  position: absolute; left: 4px; color: var(--muted);
  font-weight: 700; }
.workout-card ul.sub { margin-top: 4px; padding-left: 0; }
.workout-card ul.sub li { padding: 2px 0 2px 18px;
  font-size: 13px; color: var(--muted); font-style: italic;
  position: relative; line-height: 1.5;
  font-variant-numeric: normal; }
.workout-card ul.sub li::before { content: "";
  position: absolute; left: 0; top: 12px; width: 10px;
  border-top: 1px solid #e0e0e2; }
.workout-card .workout-prose { color: var(--muted); font-size: 13px;
  line-height: 1.5; padding: 4px 0; }

footer { max-width: 980px; margin: 0 auto; padding: 28px 20px 80px;
  color: var(--muted); font-size: 12px; }

/* responsive */
@media (max-width: 720px) {
  .page { padding: 20px 14px 50px; }
  .card { padding: 16px 16px; }
  .hero { grid-template-columns: 1fr; }
  .rings { grid-template-columns: repeat(2, 1fr); }
  .neat-cells { gap: 12px; }
  .neat-num { font-size: 18px; }
  .load-summary { grid-template-columns: repeat(2, 1fr); gap: 12px; }
  .load-summary-value { font-size: 18px; }
  .sleep-hero { grid-template-columns: 1fr; gap: 14px; }
  .sleep-row { grid-template-columns: 12px 1fr; gap: 8px; }
  .sleep-row-value, .sleep-row-status { grid-column: 2 / span 1; }
  .practices { grid-template-columns: 1fr; }
  .driver-row { grid-template-columns: 110px 1fr 50px; gap: 8px; font-size: 12px; }
  .bar-row { grid-template-columns: 1fr; gap: 4px;
    padding: 8px 0; border-bottom: 1px solid #f4f4f6; }
  .bar-label { font-size: 13px; font-weight: 500; }
  .bar-value { display: flex; justify-content: space-between;
    font-size: 12px; }
}
@media (max-width: 480px) {
  .vitals-spark-col { display: none; }
  .metric .value { font-size: 40px; }
  .practice .big { font-size: 24px; }
}
"""


# ---------- JS (inline, no deps) ----------

INLINE_JS = r"""
(function() {
  // -------- tabs --------
  function selectTab(name) {
    document.querySelectorAll('.tab').forEach(function(t) {
      t.setAttribute('aria-selected', t.dataset.tab === name ? 'true' : 'false');
    });
    document.querySelectorAll('.tab-panel').forEach(function(p) {
      p.setAttribute('data-active', p.dataset.tab === name ? 'true' : 'false');
    });
    try { history.replaceState(null, '', '#' + name); } catch(e) {}
  }
  document.querySelectorAll('.tab').forEach(function(t) {
    t.addEventListener('click', function() { selectTab(t.dataset.tab); });
  });
  var initial = (location.hash || '#assessment').slice(1);
  if (initial !== 'assessment' && initial !== 'workout') initial = 'assessment';
  selectTab(initial);

  // -------- tooltips for [data-tip] and .term --------
  var tt = document.createElement('div');
  tt.className = 'tooltip';
  document.body.appendChild(tt);

  function showTip(target, evt) {
    var text = target.getAttribute('data-tip');
    if (!text) {
      var dt = target.closest('[data-tip]');
      if (dt) text = dt.getAttribute('data-tip');
    }
    if (!text) return;
    tt.textContent = text;
    tt.classList.add('show');
    moveTip(evt);
  }
  function hideTip() { tt.classList.remove('show'); }
  function moveTip(evt) {
    var x = (evt.clientX || (evt.touches && evt.touches[0].clientX) || 0);
    var y = (evt.clientY || (evt.touches && evt.touches[0].clientY) || 0);
    var ttw = tt.offsetWidth, tth = tt.offsetHeight;
    var px = Math.min(window.innerWidth - ttw - 8, x + 14);
    var py = y - tth - 14;
    if (py < 6) py = y + 18;
    tt.style.left = px + 'px';
    tt.style.top = py + 'px';
  }
  function bindTip(el) {
    el.addEventListener('mouseenter', function(e) { showTip(el, e); });
    el.addEventListener('mousemove', moveTip);
    el.addEventListener('mouseleave', hideTip);
    el.addEventListener('touchstart', function(e) { showTip(el, e); }, {passive: true});
  }
  document.querySelectorAll('[data-tip], .term').forEach(bindTip);
  document.addEventListener('touchend', hideTip);
  document.addEventListener('scroll', hideTip, true);

  // -------- interactive training-load chart --------
  var chart = document.querySelector('.load-chart');
  var ltt = document.querySelector('.load-tooltip');
  if (chart && ltt) {
    var series = JSON.parse(chart.getAttribute('data-series'));
    var left = +chart.getAttribute('data-left');
    var right = +chart.getAttribute('data-right');
    var scrub = chart.querySelector('.scrubber');
    var sLine = chart.querySelector('.scrub-line');
    var sCtl  = chart.querySelector('.scrub-ctl');
    var sAtl  = chart.querySelector('.scrub-atl');

    function vbToClient(x) {
      var box = chart.getBoundingClientRect();
      var vb = chart.viewBox.baseVal;
      return box.left + (x / vb.width) * box.width;
    }
    function clientToVbX(clientX) {
      var box = chart.getBoundingClientRect();
      var vb = chart.viewBox.baseVal;
      return ((clientX - box.left) / box.width) * vb.width;
    }
    function showScrub(evt) {
      var clientX = evt.clientX || (evt.touches && evt.touches[0].clientX);
      var vbx = clientToVbX(clientX);
      if (vbx < left || vbx > right) { hideScrub(); return; }
      var t = (vbx - left) / (right - left);
      var idx = Math.round(t * (series.length - 1));
      if (idx < 0 || idx >= series.length) { hideScrub(); return; }
      var d = series[idx];
      var x = left + (idx / Math.max(series.length - 1, 1)) * (right - left);

      sLine.setAttribute('x1', x); sLine.setAttribute('x2', x);
      // place dots
      var vb = chart.viewBox.baseVal;
      var ctls = series.map(function(s){return s.ctl;});
      var atls = series.map(function(s){return s.atl;});
      var tsbs = series.map(function(s){return s.tsb;});
      var vmax = Math.max.apply(null, ctls.concat(atls)) * 1.15;
      var vmin = Math.min.apply(null, tsbs.concat([0])) * 1.15;
      var span = vmax - vmin;
      var bottom = vb.height - 28;
      function y(v){ return bottom - ((v - vmin) / span) * (bottom - 14); }
      sCtl.setAttribute('cx', x); sCtl.setAttribute('cy', y(d.ctl));
      sAtl.setAttribute('cx', x); sAtl.setAttribute('cy', y(d.atl));
      scrub.style.display = '';

      ltt.style.display = 'block';
      ltt.querySelector('.lt-date').textContent = d.date;
      ltt.querySelector('.lt-ctl').textContent  = d.ctl.toFixed(1);
      ltt.querySelector('.lt-atl').textContent  = d.atl.toFixed(1);
      ltt.querySelector('.lt-tsb').textContent  = (d.tsb >= 0 ? '+' : '') + d.tsb.toFixed(1);
      var px = Math.min(window.innerWidth - ltt.offsetWidth - 10,
                        clientX + 14);
      var py = (evt.clientY || (evt.touches && evt.touches[0].clientY) || 0) - ltt.offsetHeight - 14;
      if (py < 60) py += ltt.offsetHeight + 30;
      ltt.style.left = px + 'px';
      ltt.style.top = py + 'px';
    }
    function hideScrub() {
      scrub.style.display = 'none';
      ltt.style.display = 'none';
    }
    chart.addEventListener('mousemove', showScrub);
    chart.addEventListener('mouseleave', hideScrub);
    chart.addEventListener('touchstart', showScrub, {passive: true});
    chart.addEventListener('touchmove',  showScrub, {passive: true});
    chart.addEventListener('touchend',   hideScrub);
  }

  // -------- markdown viewer for the Workout tab --------
  // The workout markdown contains:
  //   # Workout plan — DATE       (dropped: date is in the page header)
  //   Assessment: ./...html       (dropped: we are already on that file)
  //   ## Workout N: TYPE          (becomes a card)
  //   ## Cardio N: ...            (becomes a card)
  //   Date: ___                    (placeholder line at top of card)
  //   Recovery (...): ___         (placeholder line at top of card)
  //   - Exercise: weight x reps   (bullet)
  //     - sub note  (or `  — sub note` with em-dash)
  function renderMarkdownInto(elt, md) {
    elt.innerHTML = '';
    var lines = md.split('\n');
    var i = 0;
    var card = null;
    var ul = null;        // current top-level <ul>
    var lastLi = null;    // last top-level <li> (for nesting sub-bullets)
    function newCard(title) {
      card = document.createElement('section');
      card.className = 'workout-card';
      if (title) {
        var h = document.createElement('h2');
        h.textContent = title;
        card.appendChild(h);
      }
      elt.appendChild(card);
      ul = null;
      lastLi = null;
    }
    function ensureCard() {
      if (!card) newCard(null);
    }
    function ensureUl() {
      ensureCard();
      if (!ul) {
        ul = document.createElement('ul');
        card.appendChild(ul);
      }
    }
    function addPlaceholder(line) {
      ensureCard();
      var ph = card.querySelector('.placeholders');
      if (!ph) {
        ph = document.createElement('div');
        ph.className = 'placeholders';
        // Insert at top, right after the h2 if present
        var h2 = card.querySelector('h2');
        if (h2 && h2.nextSibling) card.insertBefore(ph, h2.nextSibling);
        else card.appendChild(ph);
      }
      var row = document.createElement('div');
      row.className = 'placeholder-row';
      row.textContent = line;
      ph.appendChild(row);
    }
    while (i < lines.length) {
      var raw = lines[i]; i++;
      var line = raw.replace(/\s+$/, '');
      if (!line.trim()) { ul = null; lastLi = null; continue; }

      // Drop the top-level title line and the Assessment link line.
      if (/^#\s+/.test(line) && !/^##/.test(line)) continue;
      if (/^Assessment:/i.test(line)) continue;

      // ## Workout / Cardio section → new card
      if (/^##\s+/.test(line)) {
        newCard(line.replace(/^##\s+/, ''));
        continue;
      }

      // Date: ___  /  Recovery (...): ___  → placeholder rows
      if (/^Date:/i.test(line) || /^Recovery\s*\(/i.test(line)) {
        addPlaceholder(line);
        continue;
      }

      // Sub-bullet: 2+ leading spaces followed by `-` or `—` (em-dash)
      // or `–` (en-dash). Nests under the previous top-level <li>.
      var sub = line.match(/^\s{2,}(?:[-—–])\s*(.*)$/);
      if (sub) {
        ensureUl();
        if (!lastLi) {
          // No parent — render as italic muted item on its own
          lastLi = document.createElement('li');
          ul.appendChild(lastLi);
        }
        var subUl = lastLi.querySelector('ul');
        if (!subUl) {
          subUl = document.createElement('ul');
          subUl.className = 'sub';
          lastLi.appendChild(subUl);
        }
        var sli = document.createElement('li');
        sli.textContent = sub[1];
        subUl.appendChild(sli);
        continue;
      }

      // Top-level bullet
      var top = line.match(/^-\s+(.*)$/);
      if (top) {
        ensureUl();
        lastLi = document.createElement('li');
        lastLi.textContent = top[1];
        ul.appendChild(lastLi);
        continue;
      }

      // Bare prose under a card (e.g. cardio details)
      ensureCard();
      var p = document.createElement('div');
      p.className = 'workout-prose';
      p.textContent = line;
      card.appendChild(p);
      ul = null;
      lastLi = null;
    }
  }
  var mdScript = document.getElementById('workout-md');
  var workoutTab = document.querySelector('.tab-panel[data-tab="workout"]');
  if (mdScript && workoutTab) {
    renderMarkdownInto(workoutTab, mdScript.textContent);
  }
})();
"""


# ---------- card renderers ----------

def card_hero(score, score_cls, confidence, tsb, tsb_cls, tsb_label, ctl, atl, tsb_trend):
    arrow = "▲" if (tsb_trend or 0) > 0 else ("▼" if (tsb_trend or 0) < 0 else "→")
    arrow_cls = "good" if (tsb_trend or 0) > 0 else ("warn" if (tsb_trend or 0) < 0 else "muted")
    if score is None:
        score_value_html = '<div class="value muted" style="font-size:22px;">not enough data</div>'
    else:
        score_value_html = f'<div class="value">{esc(fmt(score, 1))}<span class="denom"> / 10</span></div>'
    return f'''
<section class="hero">
  <article class="card metric metric--compact {score_cls}">
    <h2>Recovery</h2>
    {score_value_html}
    <div class="sub">confidence {confidence_dots(confidence)}</div>
  </article>
  <article class="card metric {tsb_cls}">
    <h2><span class="term" data-tip="Your fitness minus your current fatigue. Positive numbers mean you are fresh and ready to train hard; negative numbers mean fatigue is accumulating. Above +5 is fresh, below -10 starts to be tired.">Freshness</span></h2>
    <div class="value">{esc(signed(tsb, 1))}</div>
    {freshness_scale(tsb)}
    <div class="sub">{esc(tsb_label)}. <span class="term" data-tip="Your training stress over the last 42 days. This number moves slowly and represents your fitness baseline.">Fitness</span> {fmt(ctl, 1)}, <span class="term" data-tip="Your training stress over the last 7 days. This number moves quickly and represents your current fatigue.">fatigue</span> {fmt(atl, 1)}.</div>
    <div class="sub" style="margin-top:6px; color: var(--{arrow_cls});">{arrow} {signed(tsb_trend, 1)} over the last 7 days</div>
  </article>
</section>
'''


def card_drivers(drivers, coach_text):
    body = driver_bars(drivers)
    return f'''
<section class="card">
  <h2>Why recovery moved (how each signal compares to your 60-day baseline)</h2>
  <div class="driver-axis-row">
    <span></span>
    <span class="axis-labels"><span>−</span><span class="term" data-tip="Zero means equal to your 60-day baseline. Each step to the right or left is one standard deviation, a unit that lets us compare signals that live on different scales (heart rate variability in milliseconds, sleep in hours, etc.).">0</span><span>+</span></span>
    <span></span>
  </div>
  {body}
  {coach_block(coach_text)}
</section>
'''


def neat_strip(daily_activity):
    """Compact NEAT sub-section below the activity rings.

    NEAT = Non-Exercise Activity Thermogenesis: all-day movement
    outside structured workouts. A longevity-relevant signal in its
    own right. Reads `daily_activity_28d` from the tracker JSON.
    Status band keys directly off the upstream `assessment`
    (`high`/`moderate`/`low`). Returns empty string when absent."""
    if not daily_activity:
        return ""
    avg_min = daily_activity.get("exercise_min_daily_avg")
    walk_km = daily_activity.get("walking_distance_km_28d")
    incidental = daily_activity.get("incidental_walks_count")
    assess = (daily_activity.get("assessment") or "").lower()
    cls = {"high": "good", "moderate": "amber", "low": "warn"}.get(assess, "muted")
    pill_label = assess or "no signal"
    return f'''
<div class="neat-section">
  <div class="neat-head">
    <span class="neat-head-label"><span class="term" data-tip="Non-Exercise Activity Thermogenesis. The movement outside structured workouts. Strongly tied to long-term metabolic health and longevity.">All-day movement (NEAT)</span></span>
    <span class="pill {cls}">{esc(pill_label)}</span>
  </div>
  <div class="neat-cells">
    <div class="neat-cell">
      <div class="neat-num">{fmt(avg_min, 0)}<span class="neat-unit">min/day</span></div>
      <div class="neat-desc">exercise minutes</div>
    </div>
    <div class="neat-cell">
      <div class="neat-num">{fmt(walk_km, 1)}<span class="neat-unit">km</span></div>
      <div class="neat-desc">walking, last 28 d</div>
    </div>
    <div class="neat-cell">
      <div class="neat-num">{fmt(incidental, 0)}</div>
      <div class="neat-desc">incidental walks</div>
    </div>
  </div>
</div>'''


def card_rings(rings_html, daily_activity, coach_text):
    return f'''
<section class="card">
  <h2>This week at a glance</h2>
  <div class="rings">{rings_html}</div>
  {neat_strip(daily_activity)}
  {coach_block(coach_text)}
</section>
'''


def card_training_load(series, ctl, atl, tsb, tsb_trend, coach_text):
    svg = load_chart_svg(series)
    return f'''
<section class="card">
  <h2>Training load over 90 days</h2>
  {svg}
  <div class="load-summary">
    <div class="load-summary-cell">
      <span class="load-summary-name"><span class="sw sw-ctl"></span><span class="term" data-tip="A 42-day moving average of your session-by-session training stress. It moves slowly and represents your fitness baseline. The blue line.">fitness</span></span>
      <span class="load-summary-value">{fmt(ctl, 1)}</span>
    </div>
    <div class="load-summary-cell">
      <span class="load-summary-name"><span class="sw sw-atl"></span><span class="term" data-tip="A 7-day moving average of your training stress. It moves quickly and represents your current fatigue. The orange dashed line.">fatigue</span></span>
      <span class="load-summary-value">{fmt(atl, 1)}</span>
    </div>
    <div class="load-summary-cell">
      <span class="load-summary-name"><span class="sw sw-tsb"></span><span class="term" data-tip="Fitness minus fatigue. Positive means fresh, negative means accumulating fatigue. The shaded band on the chart.">freshness</span></span>
      <span class="load-summary-value">{signed(tsb, 1)}</span>
    </div>
    <div class="load-summary-cell">
      <span class="load-summary-name">7-day trend</span>
      <span class="load-summary-value">{signed(tsb_trend, 1)}</span>
    </div>
  </div>
  {coach_block(coach_text)}
</section>
'''


def card_muscle_volume(weekly_volume, coach_text):
    bars = muscle_bars(weekly_volume)
    return f'''
<section class="card">
  <h2>Per-muscle weekly volume</h2>
  <div class="muscle-legend">
    <div class="muscle-legend-chips">
      <span class="muscle-legend-chip"><span class="bar-dot band-low"></span>not enough</span>
      <span class="muscle-legend-chip"><span class="bar-dot band-prod"></span>productive</span>
      <span class="muscle-legend-chip"><span class="bar-dot band-push"></span>pushing limit</span>
      <span class="muscle-legend-chip"><span class="bar-dot band-over"></span>too much, cut back</span>
    </div>
    <div class="muscle-legend-explain muted">the two thin marks on each bar show the start of the productive range (<span class="term" data-tip="Minimum Effective Volume. The smallest weekly set count that still drives growth in a muscle. Below this number, training does not produce a meaningful adaptation.">MEV</span>) and its upper edge (<span class="term" data-tip="Maximum Adaptive Volume. The upper end of the productive range for a muscle. Beyond this, extra sets cost more fatigue than they give back in growth.">MAV</span>)</div>
  </div>
  {bars}
  {coach_block(coach_text)}
</section>
'''


def card_strength(items, coach_text):
    rows = []
    for name, v in items:
        slope = v.get("slope_kg_per_4w")
        e1 = v.get("current_e1rm_kg")
        conf = v.get("confidence")
        if slope is not None and slope >= 0.5:
            arrow, cls = "↑", "good"
        elif slope is not None and slope <= -0.5:
            arrow, cls = "↓", "warn"
        else:
            arrow, cls = "→", "muted"
        rows.append(f'''
<tr>
  <td>{esc(name)}</td>
  <td class="num">{fmt(e1, 1)}<span class="muted"> kg</span></td>
  <td class="num">{signed(slope, 1)}<span class="muted"> /4w</span></td>
  <td class="arrow {cls}">{arrow}</td>
  <td>{confidence_dots(conf)}</td>
</tr>''')
    return f'''
<section class="card">
  <h2>Are you getting stronger?</h2>
  <table class="strength-table">
    <thead>
      <tr>
        <th>Lift</th>
        <th><span class="term" data-tip="Estimated 1-rep max. Your single-rep capacity extrapolated from your working sets. Tracks strength without forcing 1-rep tests.">e1RM</span></th>
        <th><span class="term" data-tip="Kilograms of e1RM change per 4 weeks. Positive means getting stronger; negative means slipping. User-tagged gym/equipment changes are excluded.">slope / 4 weeks</span></th>
        <th>trend</th>
        <th>confidence</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
  {coach_block(coach_text)}
</section>
'''


def card_vitals(weekly, vo2max, vo2_trend, bw, bw_trend, bw_weekly, coach_text):
    hrv_series = [w.get("hrv_sdnn") for w in weekly]
    rhr_series = [w.get("resting_hr") for w in weekly]
    wt_series  = [w.get("wrist_temp_c") for w in weekly]
    sleep_series = [w.get("sleep_total_h") for w in weekly]
    deep_series  = [w.get("sleep_deep_h") for w in weekly]
    rem_series   = [w.get("sleep_rem_h") for w in weekly]
    vo2_series   = [w.get("vo2max") for w in weekly]

    latest_hrv  = next((v for v in reversed(hrv_series) if v), None)
    latest_rhr  = next((v for v in reversed(rhr_series) if v), None)
    latest_wt   = next((v for v in reversed(wt_series)  if v), None)
    latest_sleep = next((v for v in reversed(sleep_series) if v), None)
    latest_deep = next((v for v in reversed(deep_series) if v), None)
    latest_rem  = next((v for v in reversed(rem_series)  if v), None)
    deep_plus_rem = (latest_deep or 0) + (latest_rem or 0) if latest_deep and latest_rem else None

    def hrv_status(v):
        prior = [x for x in hrv_series[:-1] if x]
        if not v or not prior: return "muted"
        mean = sum(prior) / len(prior)
        return "good" if v >= mean else ("amber" if v >= mean * 0.95 else "warn")

    def rhr_status(v):
        prior = [x for x in rhr_series[:-1] if x]
        if not v or not prior: return "muted"
        mean = sum(prior) / len(prior)
        return "good" if v <= mean else ("amber" if v <= mean * 1.05 else "warn")

    def wt_status_label(v):
        """Wrist temp: higher relative to baseline is the warning direction
        (persistent elevation can precede illness). Mirrors the HRV/RHR
        z-score pattern with stdev-based bands instead of percent."""
        prior = [x for x in wt_series[:-1] if x]
        if v is None or len(prior) < 2:
            return ("insufficient data", "muted")
        mean = sum(prior) / len(prior)
        var = sum((x - mean) ** 2 for x in prior) / (len(prior) - 1)
        sd = var ** 0.5
        if sd == 0:
            return ("stable", "good")
        z = (v - mean) / sd
        if z > 1.0:
            return ("elevated", "warn")
        if z > 0.5:
            return ("rising", "amber")
        return ("stable", "good")

    def sleep_status(v):
        if v is None: return "muted"
        if v >= 7: return "good"
        if v >= 6: return "amber"
        return "warn"

    def vo2_status(t):
        if t is None: return "muted"
        if t >= 0: return "good"
        if t >= -1.0: return "amber"
        return "warn"

    rows = [
        ("HRV", f'{fmt(latest_hrv, 1)} <span class="muted">ms</span>',
         sparkline(hrv_series, hrv_status(latest_hrv)),
         "favorable" if hrv_status(latest_hrv) == "good" else "below baseline",
         hrv_status(latest_hrv),
         "Heart Rate Variability (SDNN). Higher than your 60-day baseline is favorable."),
        ("Resting HR", f'{fmt(latest_rhr, 1)} <span class="muted">bpm</span>',
         sparkline(rhr_series, rhr_status(latest_rhr)),
         "favorable" if rhr_status(latest_rhr) == "good" else "above baseline",
         rhr_status(latest_rhr),
         "Resting Heart Rate. Lower than your 60-day baseline is favorable."),
        ("Wrist temp", f'{fmt(latest_wt, 2)} <span class="muted">°C</span>',
         sparkline(wt_series, wt_status_label(latest_wt)[1]),
         wt_status_label(latest_wt)[0],
         wt_status_label(latest_wt)[1],
         "Overnight wrist temperature. Persistent elevation can precede illness."),
        ("VO2max", f'{fmt(vo2max.get("value"), 2)} <span class="muted">ml/kg/min</span>',
         sparkline(vo2_series, vo2_status(vo2_trend)),
         signed(vo2_trend, 2) + " /4w",
         vo2_status(vo2_trend),
         "Peak rate of oxygen uptake. A standard fitness ceiling indicator."),
        ("Bodyweight", f'{fmt(bw.get("kg"), 2)} <span class="muted">kg</span>',
         sparkline(bw_weekly or [], "amber" if (bw_trend or 0) < -0.1 else "muted"),
         signed(bw_trend, 2) + " kg/wk" if bw_trend is not None else "no trend",
         "amber" if (bw_trend or 0) < -0.1 else "muted",
         "Morning bodyweight, sparse-merge by date."),
    ]

    body = []
    for label, value, spark, trend, cls, tip in rows:
        body.append(f'''
<tr>
  <td><span class="term" data-tip="{esc(tip)}">{esc(label)}</span></td>
  <td class="num">{value}</td>
  <td class="vitals-spark-col">{spark}</td>
  <td class="muted">{esc(trend)}</td>
</tr>''')

    return f'''
<section class="card">
  <h2>Health vitals</h2>
  <table class="vitals-table">
    <thead><tr><th>Metric</th><th>Value</th><th class="vitals-spark-col">Trend</th><th>State</th></tr></thead>
    <tbody>{"".join(body)}</tbody>
  </table>
  {coach_block(coach_text)}
</section>
'''


def card_sleep(sleep, coach_text):
    """Dedicated Sleep card: stage stack chart, schedule consistency,
    deep+REM total, efficiency, fragmentation, respiratory rate,
    breathing disturbances, outlier nights."""
    if not sleep:
        return ""
    means = sleep.get("means_h") or {}
    schedule = sleep.get("schedule_consistency") or {}
    fragmentation = sleep.get("fragmentation") or {}
    eff = sleep.get("sleep_efficiency_pct") or {}
    resp = sleep.get("resp_rate") or {}
    breath = sleep.get("breath_disturbances") or {}
    n_nights = sleep.get("n_nights_28d") or 0
    outliers = sleep.get("outliers") or []

    total = means.get("total") or 0
    core = means.get("core") or 0
    deep = means.get("deep") or 0
    rem = means.get("rem") or 0
    awake = means.get("awake") or 0
    deep_plus_rem = deep + rem
    tib = means.get("time_in_bed")

    # --- Stage stack chart (proportional bar) ---
    stage_segments = []
    if total > 0:
        for label, hours, color, tip in [
            ("Core", core, "#a8b6d9",
             "Light non-REM sleep. The bulk of total sleep; not as restorative individually as Deep but supports memory consolidation."),
            ("Deep", deep, "#4c6ee0",
             "Slow-wave sleep. The most physiologically restorative stage; drives muscle repair, growth hormone release, and glymphatic clearance."),
            ("REM",  rem,  "#a86bd1",
             "Rapid-Eye-Movement sleep. Supports emotional regulation and procedural memory."),
            ("Awake", awake, "#dadadc",
             "Wake-after-sleep-onset. Brief arousals during the night. Some is normal; persistent elevation suggests fragmentation."),
        ]:
            if hours > 0:
                pct = (hours / (total + awake)) * 100.0 if (total + awake) > 0 else 0
                stage_segments.append(
                    f'<span class="stage stage-{label.lower()}" '
                    f'style="width:{pct:.2f}%; background:{color}" '
                    f'data-tip="{esc(label)}: average {hours:.2f} h per night. {tip}">'
                    f'</span>'
                )
    stage_bar = "".join(stage_segments) or '<span class="stage" style="width:100%;background:#dadadc"></span>'

    # --- Schedule consistency band ---
    bt_stdev = schedule.get("bedtime_clock_stdev_min")
    wt_stdev = schedule.get("waketime_clock_stdev_min")
    def schedule_band(stdev_min):
        if stdev_min is None: return "muted", "no data"
        if stdev_min <= 30: return "good", "tight"
        if stdev_min <= 60: return "amber", "loose"
        return "warn", "erratic"
    bt_band, bt_word = schedule_band(bt_stdev)
    wt_band, wt_word = schedule_band(wt_stdev)

    # --- Deep+REM band ---
    if deep_plus_rem >= 2.5:
        dr_band, dr_word = "good", "healthy"
    elif deep_plus_rem >= 1.5:
        dr_band, dr_word = "amber", "low side"
    else:
        dr_band, dr_word = "warn", "deficient"

    # --- Efficiency band ---
    eff_mean = eff.get("mean") if isinstance(eff, dict) else None
    if eff_mean is None:
        ef_band, ef_word, ef_value = "muted", "not computable", "—"
    elif eff_mean >= 85:
        ef_band, ef_word, ef_value = "good", "healthy", f"{eff_mean:.1f} %"
    elif eff_mean >= 80:
        ef_band, ef_word, ef_value = "amber", "borderline", f"{eff_mean:.1f} %"
    else:
        ef_band, ef_word, ef_value = "warn", "disturbed", f"{eff_mean:.1f} %"

    # --- Fragmentation band (n_segments_mean) ---
    frag_mean = fragmentation.get("n_segments_mean")
    if frag_mean is None:
        fr_band, fr_word = "muted", "no data"
    elif frag_mean <= 15:
        fr_band, fr_word = "good", "consolidated"
    elif frag_mean <= 30:
        fr_band, fr_word = "amber", "moderate"
    else:
        fr_band, fr_word = "warn", "fragmented"

    # --- Respiratory rate (typical adult 12–20/min) ---
    rr_mean = resp.get("mean") if isinstance(resp, dict) else None
    if rr_mean is None:
        rr_band, rr_word, rr_value = "muted", "no data", "—"
    elif 12 <= rr_mean <= 20:
        rr_band, rr_word, rr_value = "good", "normal range", f"{rr_mean:.1f} / min"
    else:
        rr_band, rr_word, rr_value = "amber", "outside normal", f"{rr_mean:.1f} / min"

    # --- Breathing disturbances (Apple SBD) ---
    sbd_mean = breath.get("mean") if isinstance(breath, dict) else None
    if sbd_mean is None:
        sbd_band, sbd_word, sbd_value = "muted", "no data", "—"
    elif sbd_mean < 5:
        sbd_band, sbd_word, sbd_value = "good", "low", f"{sbd_mean:.2f} / min"
    elif sbd_mean < 15:
        sbd_band, sbd_word, sbd_value = "amber", "elevated", f"{sbd_mean:.2f} / min"
    else:
        sbd_band, sbd_word, sbd_value = "warn", "high", f"{sbd_mean:.2f} / min"

    # --- Outliers (last 14 days) ---
    outlier_html = (
        f'<div class="sleep-outliers">Outlier nights, last 14 days: {len(outliers)}.</div>'
        if outliers else
        '<div class="sleep-outliers muted">No outlier nights in the last 14 days.</div>'
    )

    return f'''
<section class="card sleep-card">
  <h2>Sleep</h2>

  <div class="sleep-hero">
    <div class="sleep-hero-num">
      <div class="value">{total:.2f}<span class="denom"> h</span></div>
      <div class="sub">average across the last {n_nights} nights</div>
      <div class="sub muted">in bed about {fmt(tib, 2)} h</div>
    </div>
    <div class="sleep-stack-wrap">
      <div class="sleep-stack">{stage_bar}</div>
      <div class="sleep-stack-legend">
        <span><span class="dot" style="background:#a8b6d9"></span>Core {core:.2f} h</span>
        <span><span class="dot" style="background:#4c6ee0"></span>Deep {deep:.2f} h</span>
        <span><span class="dot" style="background:#a86bd1"></span>REM {rem:.2f} h</span>
        <span><span class="dot" style="background:#dadadc"></span>Awake {awake:.2f} h</span>
      </div>
    </div>
  </div>

  <div class="sleep-rows">

    <div class="sleep-row" data-tip="Together, Deep and REM sleep carry the recovery and memory load. A common target is 2.5+ hours combined per night.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[dr_band] }"></span>
      <span class="sleep-row-label">Deep + REM</span>
      <span class="sleep-row-value">{deep_plus_rem:.2f} h</span>
      <span class="sleep-row-status {dr_band}">{dr_word}</span>
    </div>

    <div class="sleep-row" data-tip="Sleep efficiency is the percent of time in bed that you were actually asleep. The healthy adult range is 85% or higher; below 80% is what sleep clinics flag as disturbed in screening tools.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[ef_band] }"></span>
      <span class="sleep-row-label">Efficiency</span>
      <span class="sleep-row-value">{ef_value}</span>
      <span class="sleep-row-status {ef_band}">{ef_word}</span>
    </div>

    <div class="sleep-row" data-tip="The number of awake-or-stage-transition segments Apple's classifier counted per night. More segments mean more fragmentation. Lower is better.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[fr_band] }"></span>
      <span class="sleep-row-label">Fragmentation</span>
      <span class="sleep-row-value">{fmt(frag_mean, 1)} segs / night</span>
      <span class="sleep-row-status {fr_band}">{fr_word}</span>
    </div>

    <div class="sleep-row" data-tip="Bedtime and waketime standard deviation over the last 28 days. A tighter schedule produces a better recovery profile. Under 30 minutes is tight, 30 to 60 is loose, above 60 is erratic.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[bt_band] }"></span>
      <span class="sleep-row-label">Schedule</span>
      <span class="sleep-row-value">bedtime ± {fmt(bt_stdev, 0)} min · waketime ± {fmt(wt_stdev, 0)} min</span>
      <span class="sleep-row-status {bt_band}">{bt_word}</span>
    </div>

    <div class="sleep-row" data-tip="Average respiratory rate during sleep. Typical adult range is 12 to 20 breaths per minute. A sustained rise can precede illness by 24 to 48 hours.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[rr_band] }"></span>
      <span class="sleep-row-label">Respiratory rate</span>
      <span class="sleep-row-value">{rr_value}</span>
      <span class="sleep-row-status {rr_band}">{rr_word}</span>
    </div>

    <div class="sleep-row" data-tip="Apple's overnight breathing disturbances signal. Persistently elevated values are a screening signal for sleep apnea and worth raising with a doctor. Below 5 per minute is generally low.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[sbd_band] }"></span>
      <span class="sleep-row-label">Breathing disturbances</span>
      <span class="sleep-row-value">{sbd_value}</span>
      <span class="sleep-row-status {sbd_band}">{sbd_word}</span>
    </div>

  </div>

  {outlier_html}
  {coach_block(coach_text)}
</section>
'''


def card_recovery_practices(thermal, light, coach_text):
    heat = (thermal or {}).get("heat") or {}
    cold = (thermal or {}).get("cold") or {}
    adherence = (thermal or {}).get("adherence") or {}

    def status_pill(status_key):
        cls = {
            "on-target": "good", "below-target": "warn", "above-target": "amber",
            "below-HSP-threshold": "amber", "below-min": "amber", "in-band": "good",
        }.get(status_key, "muted")
        return f'<span class="pill {cls}">{esc(status_key or "—")}</span>'

    sauna_html = f'''
<div class="practice">
  <div class="title">Sauna</div>
  <div class="big">{fmt(heat.get("n_sessions_per_week"), 2)}<span class="unit">/ wk</span></div>
  {status_pill(adherence.get("heat_status"))}
  <div class="detail">Target {adherence.get("heat_target_per_week", 4)} per week. Average session {fmt(heat.get("avg_session_minutes"), 0)} min at about {fmt(heat.get("avg_temp_c"), 0)} °C.</div>
  <div class="recent">HSP band: {fmt(heat.get("minutes_above_hsp_threshold_per_week"), 0)} min/wk above 80 °C for 20+ min.</div>
</div>
'''
    cold_recent_lines = []
    for s in (cold.get("recent_sessions") or [])[:4]:
        temp = s.get("cold_temp_c")
        dur = s.get("cold_duration_sec")
        dur_str = f"{round(dur/60, 1)} min" if dur else "duration not logged"
        if temp is None:
            tag = '<span class="pill muted">no temperature logged</span>'
        elif s.get("dose_hint") == "amber":
            tag = f'<span class="pill amber">{esc(temp)} °C, weak dose</span>'
        else:
            tag = f'<span class="pill good">{esc(temp)} °C</span>'
        cold_recent_lines.append(
            f'<div>{esc(s.get("date"))} · {esc((s.get("cold_type") or "").replace("_", " "))} · {dur_str} {tag}</div>'
        )
    cold_html = f'''
<div class="practice">
  <div class="title">Cold exposure ({esc((cold.get("dominant_type") or "—").replace("_", " "))})</div>
  <div class="big">{fmt(cold.get("n_sessions_per_week"), 2)}<span class="unit">/ wk</span></div>
  <span class="pill muted">paired with sauna {fmt(cold.get("paired_with_heat_pct"), 0)}%</span>
  <div class="recent">{"".join(cold_recent_lines) or "no sessions in window"}</div>
</div>
'''
    light_adh = (light or {}).get("adherence") or {}
    light_html = f'''
<div class="practice">
  <div class="title">Light therapy</div>
  <div class="big">{fmt((light or {}).get("n_sessions_per_week"), 2)}<span class="unit">/ wk</span></div>
  {status_pill(light_adh.get("status"))}
  <div class="detail">Target {light_adh.get("target_per_week", 3)} per week, {light_adh.get("target_min_per_session", 10)} min per session.</div>
  <div class="recent">Average session {fmt((light or {}).get("avg_session_minutes"), 0)} min. {esc((light or {}).get("dominant_light_type") or "—")} via {esc((light or {}).get("dominant_modality") or "—")}.</div>
</div>
'''
    return f'''
<section class="card">
  <h2>Recovery practices</h2>
  <div class="practices">
    {sauna_html}
    {cold_html}
    {light_html}
  </div>
  {coach_block(coach_text)}
</section>
'''


def card_wow(wow):
    body = []
    for r in wow.get("rows", []):
        trend = r.get("trend")
        arrow = {"up": "↑", "down": "↓", "flat": "→"}.get(trend, "·")
        if r.get("key") in ("resting_hr", "wrist_temp_c"):
            cls = {"up": "warn", "down": "good", "flat": "muted"}.get(trend, "muted")
        else:
            cls = {"up": "good", "down": "warn", "flat": "muted"}.get(trend, "muted")
        body.append(f'''
<tr>
  <td>{esc(r.get("metric"))}</td>
  <td class="num">{fmt(r.get("this_week"), 2 if r.get("unit") in ("h","°C","kg") else 1)}</td>
  <td class="num muted">{fmt(r.get("last_week"), 2 if r.get("unit") in ("h","°C","kg") else 1)}</td>
  <td class="num muted">{fmt(r.get("four_wk_avg"), 2 if r.get("unit") in ("h","°C","kg") else 1)}</td>
  <td class="arrow {cls}">{arrow}</td>
  <td class="muted">{esc(r.get("unit") or "")}</td>
</tr>''')
    return f'''
<section class="card">
  <h2>This week vs last vs 4-week average</h2>
  <table class="wow-table">
    <thead><tr><th>Metric</th><th>This wk</th><th>Last wk</th><th>4-wk avg</th><th></th><th></th></tr></thead>
    <tbody>{"".join(body)}</tbody>
  </table>
</section>
'''


def coach_block(text: str | None) -> str:
    if not text:
        return ""
    return f'''
<aside class="coach">
  <div class="label">Coach</div>
  <div class="text">{auto_wrap_terms(text)}</div>
</aside>
'''


# ---------- main render ----------

def render(j, coach, workout_md, person):
    today = j.get("today")
    recovery = j.get("recovery") or {}
    training_load = j.get("training_load") or {}
    weekly = j.get("health_metrics_weekly") or []
    weekly_volume = j.get("weekly_volume_per_muscle") or {}
    e1rm = j.get("estimated_1rm") or {}
    thermal = j.get("thermal_summary") or {}
    light = j.get("light_therapy_summary") or {}
    cardio_zones = j.get("cardio_hr_zones_28d") or {}
    bw = j.get("bodyweight_latest") or {}
    bw_trend = j.get("bodyweight_trend_kg_per_week")
    vo2max = j.get("vo2max_latest") or {}
    vo2_trend = j.get("vo2max_trend_per_4w")
    wow = j.get("week_over_week") or {}
    monthly_sessions = j.get("monthly_sessions") or []
    today_d = date.fromisoformat(today)

    score = recovery.get("score")
    score_cls = "good" if (score or 0) >= 6.5 else ("amber" if (score or 0) >= 4.5 else "warn")
    confidence = recovery.get("confidence")

    tsb = training_load.get("tsb")
    ctl = training_load.get("ctl")
    atl = training_load.get("atl")
    tsb_trend = training_load.get("trend_7d")
    if tsb is None:
        tsb_cls, tsb_label = "muted", "—"
    elif abs(tsb) <= 5:
        tsb_cls, tsb_label = "good", "Balanced"
    elif -10 < tsb < -5:
        tsb_cls, tsb_label = "amber", "Carrying load"
    elif 5 < tsb <= 15:
        tsb_cls, tsb_label = "amber", "Fresh"
    elif tsb <= -10:
        tsb_cls, tsb_label = "warn", "Fatigued"
    else:
        tsb_cls, tsb_label = "warn", "Detrained"

    # rings
    strength_wk = next(
        (r for r in wow.get("rows", []) if r.get("key") == "strength_sessions"), {}
    )
    z2_min = round((cardio_zones.get("z2") or 0) / 4.0)
    sauna_wk = (thermal.get("heat") or {}).get("n_sessions_per_week") or 0
    cold_wk = (thermal.get("cold") or {}).get("n_sessions_per_week") or 0
    light_wk = (light or {}).get("n_sessions_per_week") or 0
    recovery_sessions = round(sauna_wk + cold_wk + light_wk, 1)
    sleep_avg = next(
        (w.get("sleep_total_h") for w in reversed(weekly) if w.get("sleep_total_h")),
        None,
    )

    cardio_wk = next(
        (r for r in wow.get("rows", []) if r.get("key") == "cardio_sessions"), {}
    )
    rings_html = (
        ring(strength_wk.get("this_week", 0), 4, "Strength", "sessions / wk")
        + ring(cardio_wk.get("this_week", 0), 3, "Cardio", "sessions / wk")
        + ring(z2_min or 0, 150, "Zone 2 cardio", "min / wk")
        + ring(recovery_sessions, 4, "Recovery", "sauna + cold + light")
        + ring(round(sleep_avg or 0, 1), 7, "Sleep", "hours / night")
    )

    series = build_load_series(monthly_sessions, today_d, days=90)

    e_items = [
        (k, v) for k, v in e1rm.items()
        if isinstance(v, dict)
           and v.get("slope_kg_per_4w") is not None
           and v.get("current_e1rm_kg") is not None
    ]
    e_items.sort(key=lambda kv: abs(kv[1].get("slope_kg_per_4w") or 0), reverse=True)
    e_items = e_items[:8]

    coach_cards = coach.get("cards", {})
    headline = coach.get("headline", "")

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{esc(person)} · {esc(today)}</title>
  <style>{STYLESHEET}</style>
</head>
<body>
<div class="page">
  <header class="page-head">
    <h1>{esc(person)}</h1>
    <div class="meta">{esc(today)}</div>
  </header>

  <div class="tabs" role="tablist">
    <button class="tab" role="tab" data-tab="assessment">Assessment</button>
    <button class="tab" role="tab" data-tab="workout">Workout Plan</button>
  </div>

  <div class="tab-panel" data-tab="assessment">
    <section class="card summary">
      <h2>Coach&rsquo;s summary</h2>
      <div class="body">{auto_wrap_terms(headline)}</div>
    </section>
    {card_hero(score, score_cls, confidence, tsb, tsb_cls, tsb_label, ctl, atl, tsb_trend)}
    {card_drivers(recovery.get("drivers"), coach_cards.get("recovery_drivers"))}
    {card_rings(rings_html, j.get("daily_activity_28d"), coach_cards.get("activity_rings"))}
    {card_training_load(series, ctl, atl, tsb, tsb_trend, coach_cards.get("training_load"))}
    {card_muscle_volume(weekly_volume, coach_cards.get("muscle_volume"))}
    {card_strength(e_items, coach_cards.get("strength"))}
    {card_vitals(weekly, vo2max, vo2_trend, bw, bw_trend, j.get("bodyweight_weekly") or [], coach_cards.get("vitals"))}
    {card_sleep(j.get("sleep_summary"), coach_cards.get("sleep"))}
    {card_recovery_practices(thermal, light, coach_cards.get("recovery_practices"))}
    {card_wow(wow)}
  </div>

  <div class="tab-panel" data-tab="workout"></div>
</div>

<footer>generated at {esc(datetime.now().strftime("%Y-%m-%d %H:%M"))}</footer>

{embed_workout_markdown(workout_md)}
<script>{INLINE_JS}</script>
</body>
</html>
"""
    return html_doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", required=True, help="Path to tracker JSON, or - for stdin")
    ap.add_argument("--coach", required=True, help="Path to coach_reads.json")
    ap.add_argument("--workout-md", required=True, help="Path to the workout markdown")
    ap.add_argument("--out", required=True, help="Output HTML path")
    ap.add_argument("--person", required=True)
    args = ap.parse_args()

    if args.tracker == "-":
        j = json.load(sys.stdin)
    else:
        j = json.loads(Path(args.tracker).read_text())

    coach = json.loads(Path(args.coach).read_text())
    errors, warnings = validate_coach_reads(coach)
    for w in warnings:
        print(f"coach_reads warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"coach_reads validation error: {e}", file=sys.stderr)
        return 2

    workout_md = Path(args.workout_md).read_text(encoding="utf-8")

    out = render(j, coach, workout_md, args.person)
    Path(args.out).write_text(out, encoding="utf-8")
    print(f"wrote {args.out} ({len(out):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
