"""Today-tab dashboard cards."""
from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from render_helpers import esc, fmt, signed
from render_components import (
    comparison_strip,
    confidence_dots,
    domain_score_dial,
    driver_bars,
    freshness_scale,
    load_chart_svg,
    metric_hero,
    muscle_bars,
    recovery_scale,
    risk_flag_pill,
    secondary_metric_row,
    sparkline,
    tier_history_strip,
)
from render_cards_common import _heading, coach_block
from render_validators import auto_wrap_terms


def card_hero(score, score_cls, confidence, tsb, tsb_cls, tsb_label, ctl, atl, tsb_trend):
    """Top hero on the Today tab. Recovery score + Freshness side by side.

    The workout-intensity recommendation is rendered by `card_session_call`
    at position 1 of the Today tab; this card no longer carries it (the
    previous duplication of the score across two adjacent cards is gone).
    """
    arrow = "▲" if (tsb_trend or 0) > 0 else ("▼" if (tsb_trend or 0) < 0 else "→")
    arrow_cls = "good" if (tsb_trend or 0) > 0 else ("warn" if (tsb_trend or 0) < 0 else "muted")
    if score is None:
        score_value_html = '<div class="value muted" style="font-size:22px;">not enough data</div>'
    else:
        score_value_html = f'<div class="value">{esc(fmt(score, 1))}<span class="denom"> / 10</span></div>'

    return f'''
<section class="hero">
  <article class="card metric {score_cls}">
    <h2>Recovery</h2>
    {score_value_html}
    {recovery_scale(score)}
    <div class="sub">confidence {confidence_dots(confidence)}</div>
  </article>
  <article class="card metric {tsb_cls}">
    <h2><span class="term" data-tip="Your fitness minus your current fatigue. Positive numbers mean you are fresh and ready to train hard; negative numbers mean fatigue is accumulating. Above +5 is fresh, below -10 starts to be tired.">Freshness</span></h2>
    <div class="value">{esc(signed(tsb, 1))}</div>
    {freshness_scale(tsb)}
    <div class="sub" style="color: var(--{arrow_cls});">{arrow} {signed(tsb_trend, 1)} over the last 7 days</div>
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


def card_rings(rings_html, coach_text):
    return f'''
<section class="card">
  <h2>This week at a glance</h2>
  <div class="rings">{rings_html}</div>
  {coach_block(coach_text)}
</section>
'''


def card_neat(daily_activity):
    """Dedicated NEAT card with three stat cells, all framed per day so
    the user reads consistent units across cells.

    NEAT = Non-Exercise Activity Thermogenesis: all-day movement
    outside structured workouts. Cell 1 (exercise minutes/day) carries
    a colored status word against the upstream ``assessment`` band;
    cells 2 and 3 (walking minutes/day, walking distance/day) are
    descriptive daily averages over the last 28 days. Returns empty
    string if no data."""
    if not daily_activity:
        return ""
    avg_min = daily_activity.get("exercise_min_daily_avg")
    walk_min_28 = daily_activity.get("walking_minutes_28d")
    walk_km_28 = daily_activity.get("walking_distance_km_28d")
    walk_min_daily = (walk_min_28 / 28.0) if walk_min_28 is not None else None
    walk_km_daily = (walk_km_28 / 28.0) if walk_km_28 is not None else None
    assess = (daily_activity.get("assessment") or "").lower()
    status_cls = {"high": "good", "moderate": "amber",
                  "low": "warn"}.get(assess, "muted")
    status_word = {"high": "high",
                   "moderate": "moderate",
                   "low": "low"}.get(assess, "no signal")
    return f'''
<section class="card">
  <h2><span class="term" data-tip="Non-Exercise Activity Thermogenesis. All-day movement outside structured workouts, averaged over the last 28 days. Strongly tied to long-term metabolic health and longevity.">NEAT</span> over 28 days</h2>
  <div class="neat-stats">
    <div class="neat-stat">
      <div class="neat-stat-num">{fmt(avg_min, 0)}<span class="neat-stat-unit">min/day</span></div>
      <div class="neat-stat-desc">exercise minutes · <span class="pill {status_cls}">{esc(status_word)}</span></div>
    </div>
    <div class="neat-stat">
      <div class="neat-stat-num">{fmt(walk_min_daily, 0)}<span class="neat-stat-unit">min/day</span></div>
      <div class="neat-stat-desc">time spent walking</div>
    </div>
    <div class="neat-stat">
      <div class="neat-stat-num">{fmt(walk_km_daily, 1)}<span class="neat-stat-unit">km/day</span></div>
      <div class="neat-stat-desc">walking distance</div>
    </div>
  </div>
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
      <span class="sw sw-ctl"></span>
      <span class="load-summary-name"><span class="term" data-tip="A 42-day moving average of your session-by-session training stress. It moves slowly and represents your fitness baseline. The blue line.">fitness</span></span>
      <span class="load-summary-value">{fmt(ctl, 1)}</span>
    </div>
    <div class="load-summary-cell">
      <span class="sw sw-atl"></span>
      <span class="load-summary-name"><span class="term" data-tip="A 7-day moving average of your training stress. It moves quickly and represents your current fatigue. The orange dashed line.">fatigue</span></span>
      <span class="load-summary-value">{fmt(atl, 1)}</span>
    </div>
    <div class="load-summary-cell">
      <span class="sw sw-tsb"></span>
      <span class="load-summary-name"><span class="term" data-tip="Fitness minus fatigue. Positive means fresh, negative means accumulating fatigue. The shaded band on the chart.">freshness</span></span>
      <span class="load-summary-value">{signed(tsb, 1)}</span>
    </div>
    <div class="load-summary-cell">
      <span></span>
      <span class="load-summary-name">7-day trend</span>
      <span class="load-summary-value">{signed(tsb_trend, 1)}</span>
    </div>
  </div>
  {coach_block(coach_text)}
</section>
'''


def card_muscle_volume(weekly_volume, coach_text, hr_divergence=None):
    bars = muscle_bars(weekly_volume, hr_divergence=hr_divergence)
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
    <div class="muscle-legend-caveat muted">Landmarks are Renaissance Periodization practitioner heuristics fitted to the Schoenfeld 2017 / Baz-Valle 2022 / Pelland 2025 dose-response meta-analyses. Treat as soft bands, not knife-edges — individual response varies.</div>
  </div>
  {bars}
  {coach_block(coach_text)}
</section>
'''


def card_strength(items, coach_text):
    """Strength progression table. e1RM per lift + 4-week slope. The
    HR-at-volume signal that used to render here is now per-muscle on
    card_muscle_volume — all per-muscle state lives on one card."""
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


def card_session_call(rec, coach_text, summary_text=None):
    """The Today tab's headline card. Sits at position 1, before every
    other card. Renders the 5-tier session recommendation: a tier-coloured
    pill chip + prescriptive headline + substitute prescription + "Why this
    call" rationale list + the merged Coach's-summary narrative + the
    coach's per-card callout + the override note.

    Tier is communicated by the .tier-indicator pill placed above the
    headline. The card chrome itself is uniform — no coloured left-borders
    or background tints. See Skills/DESIGN.md for the rule.
    """
    if not rec:
        return ""
    tier = rec.get("tier", "D")
    headline = rec.get("headline", "Train as planned.")
    substitute = rec.get("substitute") or {}
    prescription = substitute.get("prescription", "")
    notes = substitute.get("notes", "")
    rationale = rec.get("rationale") or []
    override_msg = rec.get("override_message") or ""

    # Tier indicator: a single semantic chip placed above the headline.
    # Colour comes from the .pill palette; the word names the tier in plain
    # English so the colour isn't the only carrier of meaning.
    tier_indicator = {
        "A": ("warn",   "Rest day"),
        "B": ("amber",  "Reactive deload"),
        "C": ("amber",  "Modified strength"),
        "D": ("good",   "Train as planned"),
        "E": ("accent", "Over-recovered"),
    }
    pill_cls, pill_word = tier_indicator.get(tier, ("good", "Train as planned"))
    tier_pill = f'<span class="tier-indicator {pill_cls}">{esc(pill_word)}</span>'

    # Pretty signal names for the rationale rows (single line per signal,
    # left-column label, right-column note).
    signal_label = {
        "wrist_temp_c":              "Wrist temp",
        "hrv_sdnn_z":                "HRV (SDNN)",
        "rhr_sustained_days":        "RHR streak",
        "rhr_z":                     "RHR",
        "recovery_crash":            "Recovery composite",
        "recovery_score":            "Recovery score",
        "tsb":                       "Freshness (TSB)",
        "wow_change_pct":            "Week-over-week load",
        "muscles_over_mrv":          "Muscles over MRV",
        "auto_deload_candidate":     "Auto-deload flag",
        "stalled_lifts":             "Stalled lifts",
        "sleep_last_night_h":        "Sleep last night",
        "sleep_7d_mean_h":           "7-day sleep mean",
        "sleep_regularity_index":    "Sleep regularity (SRI)",
        "hr_at_volume_divergence":   "HR-at-volume creep",
    }

    rationale_html = ""
    # Tier D doesn't need a verbose "why" list — it's the default green.
    if tier != "D" and rationale:
        rows = []
        for r in rationale[:5]:
            sig = r.get("signal", "")
            note = r.get("note", "")
            label_text = signal_label.get(sig, sig.replace("_", " "))
            rows.append(f'''
<div class="session-call-rationale-row">
  <span class="session-call-rationale-label">{esc(label_text)}</span>
  <span class="session-call-rationale-note">{esc(note)}</span>
</div>''')
        rationale_html = (
            f'<div class="session-call-rationale">'
            f'<div class="session-call-rationale-title">Why this call</div>'
            f'{"".join(rows)}'
            f'</div>'
        )

    substitute_line = (
        f'<div class="session-call-substitute">{esc(prescription)}</div>'
        if prescription else ""
    )
    notes_line = (
        f'<div class="session-call-notes muted">{esc(notes)}</div>'
        if notes and tier != "D" else ""
    )
    # Coach's summary narrative — merged here from what used to be its own
    # top-of-Today section. Auto-wraps known terms with the tooltip system.
    summary_block = ""
    if summary_text:
        summary_block = f'''
<div class="session-call-coach-note">
  <div class="session-call-coach-label">Coach&rsquo;s note</div>
  <div>{auto_wrap_terms(summary_text)}</div>
</div>'''
    override_line = (
        f'<div class="session-call-override">{esc(override_msg)}</div>'
        if override_msg else ""
    )

    return f'''
<section class="card session-call-card">
  <h2>Today&rsquo;s call</h2>
  {tier_pill}
  <div class="session-call-headline">{esc(headline)}</div>
  {substitute_line}
  {notes_line}
  {rationale_html}
  {summary_block}
  {coach_block(coach_text)}
  {override_line}
</section>
'''


def card_tier_history_strip(history, coach_text=None):
    """Trajectory tab component: 14-day strip of coloured dots showing
    the session-recommendation tier each day. Hover-tooltip reveals the
    date and dominant signal. Used to spot fatigue spirals (e.g. 5 ambers
    in the last 7 days means chronic under-recovery)."""
    if not history:
        return ""
    strip = tier_history_strip(history)
    return f'''
<section class="card">
  <h2>Decision history &middot; last 14 days</h2>
  <div class="tier-history-explain muted">Each day shows the call the recovery gate would have made: green = train, soft-yellow = modified, amber = reactive deload, red = rest, blue = over-recovered. Hover a square for the date and dominant signal.</div>
  {strip}
  {coach_block(coach_text)}
</section>
'''


def card_acwr(acwr, coach_text):
    """Training-load progression card.

    Hero metric: week-over-week TRIMP change percent (the "10% rule" —
    what survived the Impellizzeri 2020 / Lolli 2020 debunking of the
    strict ACWR sweet-spot framework). The ACWR ratio + Gabbett sweet-
    spot band is shown below as a coarse trend indicator with an explicit
    caveat that the strict 0.8–1.3 framework has been questioned.
    """
    if not acwr:
        return ""
    ratio = acwr.get("ratio")
    band = acwr.get("band") or "muted"
    label = acwr.get("label") or ""
    acute = acwr.get("acute_7d")
    prior_week = acwr.get("prior_week")
    chronic = acwr.get("chronic_28d_avg")
    wow_pct = acwr.get("wow_change_pct")
    wow_band = acwr.get("wow_band") or "muted"
    wow_label = acwr.get("wow_label") or ""
    bands = acwr.get("bands") or {}

    # Hero: WoW change % (signed). The 10% rule is the surviving
    # actionable signal from the ACWR literature.
    if wow_pct is None:
        wow_value_html = '<span class="muted">·</span>'
        wow_status = "no prior-week TRIMP"
        wow_cls = "muted"
        wow_sub = ""
    else:
        sign = "+" if wow_pct >= 0 else ""
        wow_value_html = f'{sign}{wow_pct:.0f}<span class="denom"> %</span>'
        wow_status = f'Week-over-week training stress · {wow_label}'
        wow_cls = wow_band
        wow_sub = (f'last 7 days {fmt(acute, 0)} TRIMP vs prior 7 days {fmt(prior_week, 0)} · '
                   f'classic 10% rule keeps weekly change in ±10%')

    hero_html = metric_hero(
        value_html=wow_value_html,
        status_word=wow_status,
        status_cls=wow_cls,
        sublabel=wow_sub,
    )

    # Legacy ACWR ratio strip (kept as a coarse trend indicator with
    # the Impellizzeri / Lolli caveat made explicit).
    lo, hi = 0.4, 1.7
    user_x = 50 + ((max(lo, min(hi, ratio)) - lo) / (hi - lo)) * 540 if ratio else 50
    sw_lo = bands.get("sweet_spot_lo", 0.8)
    sw_hi = bands.get("sweet_spot_hi", 1.3)
    sw_lo_x = 50 + ((sw_lo - lo) / (hi - lo)) * 540
    sw_hi_x = 50 + ((sw_hi - lo) / (hi - lo)) * 540
    acwr_strip = f'''
<div class="acwr-strip">
  <svg viewBox="0 0 620 90" preserveAspectRatio="xMidYMid meet" class="acwr-svg" aria-hidden="true">
    <rect x="{sw_lo_x:.1f}" y="32" width="{sw_hi_x-sw_lo_x:.1f}" height="14" class="acwr-sweet"/>
    <line x1="50" y1="39" x2="590" y2="39" class="acwr-axis"/>
    <text x="{(sw_lo_x+sw_hi_x)/2:.1f}" y="62" text-anchor="middle" class="cmp-band-lbl">Gabbett "sweet spot"</text>
    <text x="50" y="78" class="cmp-band-lbl">{lo}</text>
    <text x="590" y="78" text-anchor="end" class="cmp-band-lbl">{hi}</text>
    <polygon points="{user_x-7:.1f},25 {user_x+7:.1f},25 {user_x:.1f},37" class="cmp-user-{band}"/>
    <text x="{user_x:.1f}" y="20" text-anchor="middle" class="cmp-user-val">{fmt(ratio, 2)}</text>
  </svg>
</div>
<div class="acwr-stats">
  <div><span class="acwr-stat-num">{fmt(ratio, 2)}</span> <span class="muted"><span class="term" data-tip="Acute:Chronic Workload Ratio. Last 7 days of training stress divided by the rolling 4-week average. Gabbett 2016 originally claimed 0.8 to 1.3 was a sweet spot for injury risk; later analyses (Impellizzeri 2020, Lolli 2020) showed this is largely a statistical artifact. Treat as a coarse trend indicator only.">ACWR</span></span> &middot; <span class="{band}">{esc(label)}</span></div>
  <div><span class="acwr-stat-num">{fmt(chronic, 0)}</span> <span class="muted">avg weekly TRIMP (last 28 days)</span></div>
</div>
<div class="acwr-caveat muted">The strict ACWR 0.8–1.3 sweet-spot framework has been questioned (Impellizzeri 2020 IJSPP, Lolli 2020). The week-over-week change above is the cleaner signal. Treat the ratio as a coarse trend indicator, not an injury predictor.</div>
'''

    return f'''
<section class="card acwr-card">
  <h2><span class="term" data-tip="How much your weekly training stress is ramping. The classic 10 percent rule is to keep week-over-week change in roughly ±10%. Sharp ramps above 25% raise soft-tissue injury risk; sharp drops suggest detraining or illness.">Training-load progression</span></h2>
  {hero_html}
  {acwr_strip}
  {coach_block(coach_text)}
</section>
'''


# =============================================================================
# TRAJECTORY tab cards (longevity, "am I aging well?")
# =============================================================================
