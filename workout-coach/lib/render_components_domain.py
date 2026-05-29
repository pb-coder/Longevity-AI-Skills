"""Trajectory-domain dashboard components."""
from __future__ import annotations

from .render_helpers import esc

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
