"""Recovery driver and hero-scale dashboard components."""
from __future__ import annotations

from render_helpers import esc, fmt, signed

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
