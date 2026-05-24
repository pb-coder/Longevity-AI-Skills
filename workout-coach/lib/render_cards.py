"""HTML templates for every card on the assessment dashboard.

Each `card_*` function returns a complete `<section>` ready to drop
into the rendered HTML body. Cards are pure presentation — they take
already-aggregated values from the tracker JSON plus the coach text
string for that card and return HTML.

Function inventory (in dashboard render order):

- ``card_hero(...)`` — Recovery score + Freshness, both with their
  band-labeled scale strips.
- ``card_drivers(drivers, coach)`` — Recovery drivers chart.
- ``card_rings(rings_html, coach)`` — Activity rings card.
- ``card_neat(daily_activity)`` — NEAT (non-exercise activity) card
  with a banded bar for daily exercise minutes plus walking and
  incidental-walks stats.
- ``card_training_load(...)`` — 90-day CTL/ATL/TSB chart + summary
  cells.
- ``card_muscle_volume(weekly_volume, coach)`` — Per-muscle bars.
- ``card_strength(items, coach)`` — Strength progression table.
- ``card_vitals(weekly, vo2, vo2_trend, bw, bw_trend, bw_weekly,
  coach)`` — Health vitals table (HRV, RHR, wrist temp, VO2max,
  bodyweight) with sparklines.
- ``card_sleep(sleep, coach)`` — Sleep card (stage stack, schedule,
  efficiency, fragmentation, respiratory rate, breathing
  disturbances, outlier nights).
- ``card_recovery_practices(thermal, light, coach)`` — Three sub-cards
  for sauna / cold / light therapy.
- ``card_wow(wow)`` — Week-over-week comparison table.

Plus the shared ``coach_block(text)`` helper: wraps a coach-text
string in the standard `<aside class="coach">` callout (or returns
empty if text is None / empty).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Sibling lib/ on sys.path so this module is importable on its own.
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


# Section-heading explainers used as tooltips on every domain title.
DOMAIN_HEADING_TIPS = {
    "cardiorespiratory": "Your aerobic engine. How efficiently the heart, lungs, and blood vessels deliver oxygen to working muscles. The single strongest longevity predictor across decades of research.",
    "recovery": "How well your nervous system is shifting between effort and rest. The signals here predict whether your body can absorb the training you are prescribing it.",
    "sleep": "Both how much sleep you are getting and how consistently. The timing of bedtime and waketime is its own mortality predictor independent of total hours.",
    "body_comp": "How much of your weight is muscle versus fat, especially the visceral fat around the organs. The composition matters more than the bodyweight number alone.",
    "metabolic": "How well your body processes glucose, lipids, and insulin. The early-warning system for cardiovascular and type 2 diabetes risk decades before symptoms.",
    "behavioral": "Daily movement and sleep schedule consistency. Less glamorous than peak performance numbers, but consistency is what compounds over decades.",
    "risk_flags": "Active conditions, medications, family history, and personalised monitoring items pulled from your longevity profile.",
    "longevity_score": "A composite score across ten longevity-relevant signals. Bloodwork is not yet included; the score is honest about what it does not see.",
}


def _heading(label, key):
    """Wrap a domain heading in a tooltipped term span."""
    tip = DOMAIN_HEADING_TIPS.get(key, "")
    if not tip:
        return label
    return f'<span class="term" data-tip="{esc(tip)}">{esc(label)}</span>'
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
    <div class="muscle-legend-caveat muted">Landmarks are Renaissance Periodization practitioner heuristics fitted to the Schoenfeld 2017 / Baz-Valle 2022 / Pelland 2025 dose-response meta-analyses. Treat as soft bands, not knife-edges — individual response varies.</div>
  </div>
  {bars}
  {coach_block(coach_text)}
</section>
'''


def card_strength(items, coach_text, hr_divergence=None):
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
    # HR-at-volume divergence: per-muscle slope of strength-session avg HR
    # over the last 8 weeks, controlling for volume. Rising HR at constant
    # load is a fatigue signal; falling HR is improving conditioning.
    # Rendered as one row per muscle with a coloured dot so long words
    # ("Conditioning") never get truncated by a flex-wrap collapse.
    hr_div_html = ""
    if hr_divergence:
        rising = [(m, v) for m, v in hr_divergence.items()
                  if (v.get("hint") or "").startswith("rising")]
        falling = [(m, v) for m, v in hr_divergence.items()
                   if (v.get("hint") or "").startswith("falling")]
        rows_hr = []
        for m, v in rising:
            rows_hr.append(
                f'<div class="hr-div-row">'
                f'<span class="bar-dot band-over"></span>'
                f'<span class="hr-div-muscle">{esc(m)}</span>'
                f'<span class="hr-div-state warn">rising fatigue</span>'
                f'<span class="hr-div-delta">+{v["slope_bpm_per_4w"]:.1f} bpm/4w</span>'
                f'</div>'
            )
        for m, v in falling:
            rows_hr.append(
                f'<div class="hr-div-row">'
                f'<span class="bar-dot band-prod"></span>'
                f'<span class="hr-div-muscle">{esc(m)}</span>'
                f'<span class="hr-div-state good">improving conditioning</span>'
                f'<span class="hr-div-delta">{v["slope_bpm_per_4w"]:.1f} bpm/4w</span>'
                f'</div>'
            )
        if rows_hr:
            label = '<span class="term" data-tip="Per-muscle slope of strength-session average heart rate over the last 8 weeks, controlling for volume. Rising HR at the same load is a fatigue or under-recovery signal; falling HR is improving aerobic conditioning.">HR at volume</span>'
            hr_div_html = (
                f'<div class="hr-divergence">'
                f'<div class="hr-div-title">{label}</div>'
                f'{"".join(rows_hr)}'
                f'</div>'
            )

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
  {hr_div_html}
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
    schedule_unavailable = bt_stdev is None and wt_stdev is None

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
    # Hide the row entirely when there are no outliers; per DESIGN.md, empty
    # states are omitted rather than rendered as muted placeholder text.
    outlier_html = (
        f'<div class="sleep-outliers">Outlier nights, last 14 days: {len(outliers)}.</div>'
        if outliers else ""
    )

    # --- Assemble sleep-rows: only emit rows whose underlying field exists.
    # HealthAutoExport-sourced trackers don't supply Time in Bed (efficiency),
    # per-night segment counts (fragmentation), or segment clock times
    # (schedule). Silently drop those rows rather than rendering placeholder
    # dots / dashes — the absence itself is honest.
    band_class_map = {"good": "prod", "amber": "push", "warn": "over", "muted": "low"}
    sleep_row_parts = []
    sleep_row_parts.append(f'''
    <div class="sleep-row" data-tip="Together, Deep and REM sleep carry the recovery and memory load. A common target is 2.5+ hours combined per night. Status: {dr_word}.">
      <span class="bar-dot band-{band_class_map[dr_band]}"></span>
      <span class="sleep-row-label">Deep + REM</span>
      <span class="sleep-row-value {dr_band}">{deep_plus_rem:.2f} h</span>
    </div>''')
    if eff_mean is not None:
        sleep_row_parts.append(f'''
    <div class="sleep-row" data-tip="Sleep efficiency is the percent of time in bed that you were actually asleep. The healthy adult range is 85% or higher; below 80% is what sleep clinics flag as disturbed in screening tools. Status: {ef_word}.">
      <span class="bar-dot band-{band_class_map[ef_band]}"></span>
      <span class="sleep-row-label">Efficiency</span>
      <span class="sleep-row-value {ef_band}">{ef_value}</span>
    </div>''')
    if frag_mean is not None:
        sleep_row_parts.append(f'''
    <div class="sleep-row" data-tip="The number of awake-or-stage-transition segments Apple's classifier counted per night. More segments mean more fragmentation. Lower is better. Status: {fr_word}.">
      <span class="bar-dot band-{band_class_map[fr_band]}"></span>
      <span class="sleep-row-label">Fragmentation</span>
      <span class="sleep-row-value {fr_band}">{frag_mean:.1f} segs / night</span>
    </div>''')
    if not schedule_unavailable:
        sleep_row_parts.append(f'''
    <div class="sleep-row" data-tip="Bedtime and waketime standard deviation over the last 28 days. A tighter schedule produces a better recovery profile. Under 30 minutes is tight, 30 to 60 is loose, above 60 is erratic. Status: {bt_word}.">
      <span class="bar-dot band-{band_class_map[bt_band]}"></span>
      <span class="sleep-row-label">Schedule</span>
      <span class="sleep-row-value {bt_band}">bedtime ± {fmt(bt_stdev, 0)} min · waketime ± {fmt(wt_stdev, 0)} min</span>
    </div>''')
    sleep_row_parts.append(f'''
    <div class="sleep-row" data-tip="Average respiratory rate during sleep. Typical adult range is 12 to 20 breaths per minute. A sustained rise can precede illness by 24 to 48 hours. Status: {rr_word}.">
      <span class="bar-dot band-{band_class_map[rr_band]}"></span>
      <span class="sleep-row-label">Respiratory rate</span>
      <span class="sleep-row-value {rr_band}">{rr_value}</span>
    </div>''')
    sleep_row_parts.append(f'''
    <div class="sleep-row" data-tip="Apple's overnight breathing disturbances signal. Persistently elevated values are a screening signal for sleep apnea and worth raising with a doctor. Below 5 per minute is generally low. Status: {sbd_word}.">
      <span class="bar-dot band-{band_class_map[sbd_band]}"></span>
      <span class="sleep-row-label">Breathing disturbances</span>
      <span class="sleep-row-value {sbd_band}">{sbd_value}</span>
    </div>''')
    sleep_rows_html = "".join(sleep_row_parts)

    return f'''
<section class="card sleep-card">
  <h2>Sleep</h2>

  <div class="sleep-hero">
    <div class="sleep-hero-num">
      <div class="value">{total:.2f}<span class="denom"> h</span></div>
      <div class="sub">average across the last {n_nights} nights</div>
      {f'<div class="sub muted">in bed about {tib:.2f} h</div>' if tib is not None else ''}
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
    {sleep_rows_html}
  </div>

  {outlier_html}
  {coach_block(coach_text)}
</section>
'''


def card_recovery_practices(thermal, light, coach_text):
    # When the user logged no sauna / cold / light sessions in the last 28
    # days, both summary keys are absent from the JSON. Render one explicit
    # behavior-gap card instead of three sub-cards full of placeholder dots
    # — the absence is a choice, not a tracking failure.
    if not thermal and not light:
        return f'''
<section class="card">
  <h2>Recovery practices</h2>
  <div class="body">
    <p>No sauna, cold exposure, or light-therapy sessions in the last 28 days.</p>
    <p class="muted">Log via <code>/log</code> after each session to track adherence against the 4 per week sauna and 3 per week light-therapy defaults.</p>
  </div>
  {coach_block(coach_text)}
</section>
'''
    heat = (thermal or {}).get("heat") or {}
    cold = (thermal or {}).get("cold") or {}
    adherence = (thermal or {}).get("adherence") or {}

    def adherence_pill(status_key):
        """Adherence semantics — goal-attainment, not state. Uses
        .pill-adherence.* per Skills/DESIGN.md so we don't overload
        the status .pill.good with two meanings."""
        cls = {
            "on-target":    "on-target",
            "below-target": "below-target",
            "above-target": "above-target",
            "below-HSP-threshold": "below-target",
            "below-min":    "below-target",
            "in-band":      "on-target",
        }.get(status_key, "below-target")
        return f'<span class="pill-adherence {cls}">{esc(status_key or "—")}</span>'

    sauna_html = f'''
<div class="practice">
  <div class="title">Sauna</div>
  <div class="big">{fmt(heat.get("n_sessions_per_week"), 2)}<span class="unit">/ wk</span></div>
  {adherence_pill(adherence.get("heat_status"))}
  <div class="detail">Target {adherence.get("heat_target_per_week", 4)} per week. Average session {fmt(heat.get("avg_session_minutes"), 0)} min at about {fmt(heat.get("avg_temp_c"), 0)} °C.</div>
  <div class="recent">HSP band: {fmt(heat.get("minutes_above_hsp_threshold_per_week"), 0)} min/wk above 80 °C for 20+ min.</div>
</div>
'''
    # Cold-exposure block: weekly count + adherence pill + one-line average
    # (rendered only when both temp and duration are populated for at least
    # one session). Per-session detail and "not logged" pills are omitted —
    # they were visual noise that didn't help adherence reading.
    cold_status = cold.get("adherence_status") or adherence.get("cold_status")
    sessions_with_dose = [
        s for s in (cold.get("recent_sessions") or [])
        if s.get("cold_temp_c") is not None and s.get("cold_duration_sec")
    ]
    avg_line_html = ""
    if sessions_with_dose:
        avg_min = sum(s["cold_duration_sec"] for s in sessions_with_dose) / len(sessions_with_dose) / 60
        avg_temp = sum(s["cold_temp_c"] for s in sessions_with_dose) / len(sessions_with_dose)
        avg_line_html = (
            f'<div class="detail">Average session {avg_min:.1f} min at {avg_temp:.0f} °C '
            f'({len(sessions_with_dose)} session{"s" if len(sessions_with_dose) != 1 else ""} with full dose data).</div>'
        )
    cold_adherence_html = (
        adherence_pill(cold_status) if cold_status else ""
    )
    cold_html = f'''
<div class="practice">
  <div class="title">Cold exposure ({esc((cold.get("dominant_type") or "—").replace("_", " "))})</div>
  <div class="big">{fmt(cold.get("n_sessions_per_week"), 2)}<span class="unit">/ wk</span></div>
  {cold_adherence_html}
  {avg_line_html}
</div>
'''
    light_adh = (light or {}).get("adherence") or {}
    light_html = f'''
<div class="practice">
  <div class="title">Light therapy</div>
  <div class="big">{fmt((light or {}).get("n_sessions_per_week"), 2)}<span class="unit">/ wk</span></div>
  {adherence_pill(light_adh.get("status"))}
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


# =============================================================================
# TODAY tab cards (operational, "should I train hard?")
# =============================================================================


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


def workout_recommendation(recovery, acwr):
    """Compute the workout-intensity recommendation + colour class.

    Returns ``(text, cls)``. Used by the Today tab's hero card; the logic
    lives here so the hero card can stay a pure layout function. The
    rules: recovery score is the primary gate; ACWR sweet-spot is the
    secondary gate; missing inputs degrade to muted.
    """
    score = (recovery or {}).get("score")
    if score is None:
        return ("Not enough data to recommend an intensity.", "muted")
    acwr_band = (acwr or {}).get("band")
    if score >= 6.5 and acwr_band in ("good", None):
        return ("Green light. Hard training is on the table today.", "good")
    if score >= 4.5:
        return ("Moderate day. Hold loads, push reps. Avoid PR attempts.", "amber")
    return ("Easy day. Walk, mobility, or a Zone 2 cardio session.", "warn")


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
  <svg viewBox="0 0 620 80" preserveAspectRatio="xMidYMid meet" class="acwr-svg" aria-hidden="true">
    <rect x="{sw_lo_x:.1f}" y="32" width="{sw_hi_x-sw_lo_x:.1f}" height="14" class="acwr-sweet"/>
    <line x1="50" y1="39" x2="590" y2="39" class="acwr-axis"/>
    <text x="50" y="60" class="cmp-band-lbl">{lo}</text>
    <text x="590" y="60" text-anchor="end" class="cmp-band-lbl">{hi}</text>
    <text x="{(sw_lo_x+sw_hi_x)/2:.1f}" y="22" text-anchor="middle" class="cmp-band-lbl">Gabbett "sweet spot"</text>
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


PRETTY_INPUT_NAMES = {
    "vo2_percentile":         "VO₂ max",
    "hrv_trend":              "HRV trend",
    "rhr_trend":              "RHR trend",
    "sleep_regularity":       "Sleep regularity",
    "sleep_quality":          "Sleep quality",
    "training_load_in_band":  "Training load in band",
    "z2_weekly_adherence":    "Zone 2 weekly",
    "body_comp_trend":        "Body comp trend",
    "behavioral_consistency": "Movement consistency",
    "strength_progression":   "Strength progression",
}


def card_longevity_score(longevity_score, coach_text):
    """Headline card for the Trajectory tab. Composite 0-100 score plus
    per-component attribution. Branches on ``status``:

    - ``incomplete`` → score rendered muted with the missing-cornerstone
      explanation. No confident attribution.
    - ``partial`` → score rendered in colour with a partial badge and a
      "missing inputs" list below the attribution.
    - ``complete`` → standard render with full attribution.
    """
    if not longevity_score:
        return ""
    score = longevity_score.get("score")
    band = longevity_score.get("band") or "muted"
    label = longevity_score.get("label") or ""
    status = longevity_score.get("status") or "complete"
    status_label = longevity_score.get("status_label") or ""
    components = longevity_score.get("components") or []
    missing_inputs = longevity_score.get("missing_inputs") or []
    n_present = longevity_score.get("n_components")
    n_total = longevity_score.get("n_tracked_total")

    # Status pill colour follows the score's overall band.
    status_pill_cls = {"complete": "good", "partial": "amber",
                       "incomplete": "muted"}.get(status, "muted")

    # Attribution rows (always show, but suppressed when incomplete).
    rows = []
    if status != "incomplete":
        for c in components[:8]:
            name = PRETTY_INPUT_NAMES.get(c["name"], c["name"])
            s = c.get("score", 0)
            if s >= 75: cls = "good"
            elif s >= 50: cls = "amber"
            else: cls = "warn"
            rows.append(f'''
<tr>
  <td>{esc(name)}</td>
  <td class="num">{s:.0f}<span class="muted"> / 100</span></td>
  <td class="num muted">×{c.get("weight", 0):.2f}</td>
  <td class="num {cls}">{c.get("contribution", 0):+.1f}</td>
</tr>''')
    attribution_html = (
        f'''<table class="longevity-table">
            <thead><tr><th>Component</th><th>Score</th><th>Weight</th><th>Contribution</th></tr></thead>
            <tbody>{"".join(rows)}</tbody>
          </table>''' if rows else ""
    )

    # Missing-inputs panel (always when there are missing).
    missing_html = ""
    if missing_inputs:
        items = []
        for m in missing_inputs:
            name = PRETTY_INPUT_NAMES.get(m["name"], m["name"])
            items.append(f'<li><strong>{esc(name)}</strong> — {esc(m["hint"])}</li>')
        title = ("To complete the score, populate the following inputs:"
                 if status == "partial"
                 else "Score is incomplete. Populate VO₂ max first, then the others:")
        missing_html = (
            f'<div class="missing-inputs">'
            f'<div class="missing-title muted">{esc(title)}</div>'
            f'<ul class="missing-list">{"".join(items)}</ul>'
            f'</div>'
        )

    # Bloodwork note (always — biomarkers are deferred until labs land).
    pending_note = (
        f'<div class="bloodwork-pending muted">'
        f'<strong>Bloodwork pending.</strong> '
        f'{esc(longevity_score.get("note", ""))}'
        f'</div>'
        if longevity_score.get("bloodwork_pending") else ""
    )

    inputs_chip = (
        f'<span class="pill {status_pill_cls}">{esc(status_label)}</span>'
        if status_label else ""
    )

    # Big number is muted when incomplete; coloured otherwise.
    big_value_cls = "muted" if status == "incomplete" else band
    big_value_html = f'{fmt(score, 0)}<span class="denom"> / 100</span>'

    return f'''
<section class="card longevity-headline">
  <h2>{_heading("Longevity score", "longevity_score")}</h2>
  <div class="metric-hero">
    <div class="metric-hero-value {big_value_cls}" style="font-size:64px;">{big_value_html}</div>
    <div class="metric-hero-status {band}">{esc(label)}</div>
    <div class="metric-hero-sub muted">composite across {n_present or 0} of {n_total or 0} longevity-relevant signals {inputs_chip}</div>
  </div>
  {attribution_html}
  {missing_html}
  {pending_note}
  {coach_block(coach_text)}
</section>
'''


def card_cardio_domain(vo2_percentile, hr_recovery, recovery, cardio_zones,
                       vo2max_latest, vo2_trend, coach_text):
    """Cardiorespiratory domain card: VO2 max as the hero metric, with
    HR Recovery 1-min, RHR vs baseline, and Zone 2 weekly minutes as
    stacked secondaries underneath.

    Visual language matches the Today tab's hero cards (big number +
    comparison strip + status word).
    """
    vo2_value = (vo2max_latest or {}).get("value")

    # Hero: VO2 max number + comparison strip + status word
    if vo2_percentile:
        vo2_cls = vo2_percentile.get("status") or "muted"
        vo2_status = vo2_percentile.get("label", "")
        strip_html = comparison_strip(
            value=vo2_percentile["value"],
            p50=vo2_percentile["p50"],
            p75=vo2_percentile["p75"],
            p95=vo2_percentile["p95"],
            longevity=vo2_percentile["longevity"],
            unit="ml/kg/min",
            longevity_label="Attia target",
        )
    else:
        vo2_cls = "muted"
        vo2_status = "cohort percentile not resolvable"
        strip_html = ""

    hero_html = metric_hero(
        value_html=f'{fmt(vo2_value, 1)}<span class="denom"> ml/kg/min</span>',
        status_word=f'VO₂ max · {vo2_status}',
        status_cls=vo2_cls,
        sublabel=(f'+{vo2_trend:.2f} per 4 weeks' if vo2_trend and vo2_trend > 0
                  else (f'{vo2_trend:.2f} per 4 weeks' if vo2_trend else None)),
        comparison_html=strip_html,
    )

    # Secondary metrics: HR Recovery, RHR, Zone 2
    secondaries = []

    if hr_recovery:
        cls = hr_recovery.get("band", "muted")
        secondaries.append(secondary_metric_row(
            "HR Recovery 1-min",
            f'{fmt(hr_recovery.get("mean_28d"), 0)} <span class="muted">bpm drop</span>',
            cls,
            sublabel=f'28-day average · {hr_recovery.get("label", "")}',
            tip="Heart-rate Recovery 1-minute after exercise stops. Cole 1999 NEJM: under 12 bpm = 4x cardiovascular mortality risk. Above 25 is normal-fit, above 35 is excellent.",
        ))

    drivers = (recovery or {}).get("drivers") or []
    rhr_d = next((d for d in drivers if d.get("metric") == "resting_hr"), None)
    if rhr_d:
        z = rhr_d.get("z")
        if z is not None and z >= 0.3: cls = "good"
        elif z is not None and z >= -0.5: cls = "amber"
        else: cls = "warn"
        secondaries.append(secondary_metric_row(
            "Resting HR",
            f'{fmt(rhr_d.get("recent_avg"), 0)} <span class="muted">bpm</span>',
            cls,
            sublabel=f'vs 60-day baseline {fmt(rhr_d.get("baseline_mean"), 0)} (z {signed(z, 2)})',
            tip="Resting Heart Rate. Lower than your 60-day baseline is favorable. Sustained >5 bpm elevation often signals overreaching or illness.",
        ))

    if cardio_zones:
        z2_min = cardio_zones.get("z2") or 0
        z2_per_wk = z2_min / 4.0
        if z2_per_wk >= 150: cls = "good"
        elif z2_per_wk >= 80: cls = "amber"
        else: cls = "warn"
        secondaries.append(secondary_metric_row(
            "Zone 2 cardio",
            f'{z2_per_wk:.0f} <span class="muted">min / wk</span>',
            cls,
            sublabel='target 150–200 min/wk · Attia / San-Millán prescription',
            tip="Zone 2 weekly minutes. The aerobic-base zone where mitochondrial density adapts. Attia/San-Millán prescription: 150 to 200 min/wk.",
        ))

    secondaries_html = (
        f'<div class="secondary-metrics">{"".join(secondaries)}</div>'
        if secondaries else ""
    )

    return f'''
<section class="card domain-card">
  <h2>{_heading("Cardiorespiratory fitness", "cardiorespiratory")}</h2>
  {hero_html}
  {secondaries_html}
  {coach_block(coach_text)}
</section>
'''


def card_recovery_domain(recovery, weekly, coach_text):
    """Recovery / Autonomic-nervous-system domain card.

    Hero metric: HRV (SDNN) vs 60-day baseline. Secondary: wrist temp
    deviation. Apple Watch HRV is SDNN — explicitly labelled to prevent
    cross-platform comparisons with Whoop/Oura RMSSD.
    """
    drivers = (recovery or {}).get("drivers") or []
    hrv_d = next((d for d in drivers if d.get("metric") == "hrv_sdnn"), None)
    wt_d = next((d for d in drivers if d.get("metric") == "wrist_temp_c"), None)

    if hrv_d:
        recent = hrv_d.get("recent_avg")
        baseline = hrv_d.get("baseline_mean")
        z = hrv_d.get("z")
        if z is not None and z >= 0.5: cls, status = "good", "favorable vs baseline"
        elif z is not None and z >= -0.5: cls, status = "amber", "near baseline"
        else: cls, status = "warn", "below baseline"
        hero_html = metric_hero(
            value_html=f'{fmt(recent, 1)}<span class="denom"> ms</span>',
            status_word=f'HRV (SDNN) · {status}',
            status_cls=cls,
            sublabel=f'vs 60-day baseline {fmt(baseline, 1)} (z {signed(z, 2)}) · Apple Watch SDNN, not comparable to Whoop or Oura RMSSD',
        )
    else:
        hero_html = metric_hero(
            value_html='<span class="muted">·</span>',
            status_word='no HRV data in 60-day window',
            status_cls="muted",
        )

    secondaries = []
    if wt_d:
        recent = wt_d.get("recent_avg")
        baseline = wt_d.get("baseline_mean")
        z = wt_d.get("z")
        if z is not None and z <= 0.5: cls, lbl = "good", "stable"
        elif z is not None and z <= 1.0: cls, lbl = "amber", "rising"
        else: cls, lbl = "warn", "elevated"
        secondaries.append(secondary_metric_row(
            "Wrist temp",
            f'{fmt(recent, 2)} <span class="muted">°C</span>',
            cls,
            sublabel=f'vs 60-day baseline {fmt(baseline, 2)} (z {signed(z, 2)}) · {lbl}',
            tip="Overnight wrist temperature deviation from your 60-day baseline. Sustained elevation can precede illness or signal under-recovery.",
        ))

    secondaries_html = (
        f'<div class="secondary-metrics">{"".join(secondaries)}</div>'
        if secondaries else ""
    )

    return f'''
<section class="card domain-card">
  <h2>{_heading("Recovery & autonomic nervous system", "recovery")}</h2>
  {hero_html}
  {secondaries_html}
  {coach_block(coach_text)}
</section>
'''


def _has_risk_flag(longevity_state, key):
    """True when ``longevity_state.risk_flags`` carries the named key.

    Used to gate user-specific copy (Parkinson surveillance notes, PrEP
    callouts, etc.) so it only renders for people whose longevity profile
    actually declares the relevant flag. Without this guard, hardcoded
    references would leak across people."""
    if not longevity_state:
        return False
    return any(
        (f or {}).get("key") == key
        for f in (longevity_state.get("risk_flags") or [])
    )


def card_sleep_domain(sleep, sleep_regularity, rem_anomaly, coach_text,
                      longevity_state=None):
    """Sleep architecture domain card. Hero: Total sleep h. Secondaries:
    Deep+REM, Efficiency, SRI. REM-anomaly watch below."""
    if not sleep and not sleep_regularity:
        return ""
    means = (sleep or {}).get("means_h") or {}
    total = means.get("total")
    deep = means.get("deep") or 0
    rem = means.get("rem") or 0
    deep_plus_rem = deep + rem if (deep or rem) else None
    eff_block = (sleep or {}).get("sleep_efficiency_pct") or {}
    eff_mean = eff_block.get("mean") if isinstance(eff_block, dict) else None

    # Hero: total sleep with NSF target context
    if total is None:
        hero_html = metric_hero(
            value_html='<span class="muted">·</span>',
            status_word='no sleep data in 28-day window',
            status_cls="muted",
        )
    else:
        if total >= 7.5: cls, status = "good", "in target range"
        elif total >= 7.0: cls, status = "good", "meeting minimum"
        elif total >= 6.0: cls, status = "amber", "below 7 h floor"
        else: cls, status = "warn", "chronically short"
        hero_html = metric_hero(
            value_html=f'{total:.2f}<span class="denom"> h</span>',
            status_word=f'Total sleep · {status}',
            status_cls=cls,
            sublabel="National Sleep Foundation target 7 to 9 h",
        )

    secondaries = []
    if deep_plus_rem is not None:
        if deep_plus_rem >= 2.5: cls, lbl = "good", "healthy"
        elif deep_plus_rem >= 1.5: cls, lbl = "amber", "low side"
        else: cls, lbl = "warn", "deficient"
        secondaries.append(secondary_metric_row(
            "Deep + REM",
            f'{deep_plus_rem:.2f} <span class="muted">h</span>',
            cls,
            sublabel=f'deep {deep:.2f} h · rem {rem:.2f} h · {lbl}',
            tip="Combined Deep + REM hours per night. Together they carry the recovery and memory consolidation load. Target 2.5+ hours.",
        ))

    if eff_mean is not None:
        if eff_mean >= 85: cls, lbl = "good", "healthy"
        elif eff_mean >= 80: cls, lbl = "amber", "borderline"
        else: cls, lbl = "warn", "disturbed"
        secondaries.append(secondary_metric_row(
            "Efficiency",
            f'{eff_mean:.1f} <span class="muted">%</span>',
            cls,
            sublabel=f'target ≥85% · {lbl}',
            tip="Percent of time in bed actually asleep. Healthy adult range is 85% or higher; below 80% is what sleep clinics flag as disturbed in screening tools.",
        ))

    if sleep_regularity:
        sri = sleep_regularity.get("sri")
        band = sleep_regularity.get("band") or "muted"
        label = sleep_regularity.get("label") or ""
        secondaries.append(secondary_metric_row(
            "Sleep Regularity Index",
            f'{fmt(sri, 0)} <span class="muted">/ 100</span>',
            band,
            sublabel=f'{label} · UK Biobank bottom &lt;71, top &gt;87',
            tip="Sleep Regularity Index (Phillips 2017 / Windred 2024 eLife). UK Biobank n=60,977: top quintile has 20 to 48 percent lower all-cause mortality than bottom. A stronger predictor than sleep duration.",
        ))

    secondaries_html = (
        f'<div class="secondary-metrics">{"".join(secondaries)}</div>'
        if secondaries else ""
    )

    rem_watch = ""
    if rem_anomaly:
        low = rem_anomaly.get("low_rem_nights", 0)
        mean_pct = rem_anomaly.get("mean_rem_pct", 0)
        # The Parkinson surveillance note only renders when the person's
        # longevity profile carries the parkinson_surveillance risk flag.
        # Without that gate the line would leak to everyone with a low-REM
        # window, including people without family history of Parkinson's.
        parkinson_note = (
            " Relevant for paternal Parkinson family history surveillance."
            if _has_risk_flag(longevity_state, "parkinson_surveillance") else ""
        )
        rem_watch = f'''
<div class="rem-watch muted">
  <strong>REM watch.</strong> {low} of {rem_anomaly.get("n_nights", 0)} nights showed REM below 15% of total sleep in the 28-day window.
  Mean REM proportion {mean_pct:.1f}% &middot; healthy adult range is 20 to 25%.{parkinson_note}
</div>'''

    return f'''
<section class="card domain-card">
  <h2>{_heading("Sleep architecture & regularity", "sleep")}</h2>
  {hero_html}
  {secondaries_html}
  {rem_watch}
  {coach_block(coach_text)}
</section>
'''


def card_body_comp_domain(bw, bw_trend, longevity_state, coach_text):
    """Body composition domain card. Hero: bodyweight + trend context.
    Body fat and visceral fat secondaries are explicit DEXA-pending."""
    bw_val = (bw or {}).get("kg")
    has_profile = bool(longevity_state)

    # Hero: bodyweight with trend status
    if bw_trend is None:
        cls, status, sub = "muted", "no trend yet", "needs 8+ fasted entries"
    elif -0.1 <= bw_trend <= 0.4:
        cls, status, sub = "good", "lean-bulk range", f'{signed(bw_trend, 2)} kg/wk · target +0.2 to +0.4'
    elif bw_trend > 0.4:
        cls, status, sub = "amber", "trending fat-mass zone", f'{signed(bw_trend, 2)} kg/wk · over lean-bulk target'
    else:
        cls, status, sub = "amber", "cutting trajectory", f'{signed(bw_trend, 2)} kg/wk · negative balance'

    hero_html = metric_hero(
        value_html=f'{fmt(bw_val, 1)}<span class="denom"> kg</span>',
        status_word=f'Bodyweight · {status}',
        status_cls=cls,
        sublabel=sub,
    )

    secondaries = [
        secondary_metric_row(
            "Body fat %",
            '<span class="muted">·</span>',
            "muted",
            sublabel="DEXA or skinfold pending",
            tip="Body fat percentage from DEXA or skinfold callipers. Apple/Watch consumer-scale estimates are unreliable and not used here.",
        ),
        secondary_metric_row(
            "Visceral fat (VAT)",
            '<span class="muted">·</span>',
            "muted",
            sublabel="DEXA pending · &lt;100 cm² is the optimal target",
            tip="Visceral adipose tissue around the organs. The metabolically dangerous fat depot. Under 100 cm² is the risk threshold; under 80 cm² is the Attia optimal target.",
        ),
    ]

    # Gate the PrEP-specific BMD prompt on the prep_monitoring risk flag —
    # otherwise it would leak to every user whose profile is populated,
    # not just the ones actually on PrEP.
    if has_profile and _has_risk_flag(longevity_state, "prep_monitoring"):
        dexa_msg = (
            '<strong>DEXA pending.</strong> Visceral adipose tissue (VAT), '
            'appendicular lean mass (ALMI), and bone density (BMD) need a DEXA scan to populate. '
            'PrEP users should book one for BMD baseline anyway.'
        )
    elif has_profile:
        dexa_msg = (
            '<strong>DEXA pending.</strong> Visceral adipose tissue (VAT), '
            'appendicular lean mass (ALMI), and bone density (BMD) need a DEXA scan to populate.'
        )
    else:
        dexa_msg = (
            '<strong>DEXA pending.</strong> Body composition detail '
            '(VAT / ALMI / bone density) requires a DEXA scan.'
        )

    return f'''
<section class="card domain-card">
  <h2>{_heading("Body composition", "body_comp")}</h2>
  {hero_html}
  <div class="secondary-metrics">{"".join(secondaries)}</div>
  <div class="bloodwork-pending muted">{dexa_msg}</div>
  {coach_block(coach_text)}
</section>
'''


def card_metabolic_domain(longevity_state, coach_text):
    """Metabolic-health domain card. Placeholder until a blood panel
    lands. Reads the personalized panel-design hints from longevity_state
    (vegan emphasis, Berlin vitamin D window, PrEP markers)."""
    if not longevity_state:
        return f'''
<section class="card domain-card">
  <h2>{_heading("Metabolic health", "metabolic")}</h2>
  <div class="bloodwork-pending muted">
    <strong>Bloodwork pending.</strong> A foundational panel covers fasting glucose,
    HbA1c, fasting insulin, ApoB, Lp(a), triglyceride:HDL, hsCRP, eGFR.
  </div>
  {coach_block(coach_text)}
</section>
'''
    flags = longevity_state.get("risk_flags") or []
    panel_hints = [f for f in flags if f.get("key") in (
        "first_blood_panel", "vegan_micronutrient_panel", "prep_monitoring", "vitamin_d_winter")]
    hint_html = "".join(
        f'<li><strong>{esc(f.get("label", ""))}</strong>: {esc(f.get("hint", ""))}</li>'
        for f in panel_hints
    )
    return f'''
<section class="card domain-card">
  <h2>{_heading("Metabolic health", "metabolic")}</h2>
  <div class="bloodwork-pending muted">
    <strong>Bloodwork pending.</strong> Until a panel lands, this slot stays empty. Personalised priorities for the first panel:
    <ul style="margin-top:8px; padding-left:18px;">{hint_html}</ul>
  </div>
  {coach_block(coach_text)}
</section>
'''


def card_behavioral_domain(movement_consistency, sleep_regularity, acwr,
                            cardio_zones, coach_text):
    """Behavioral consistency domain card. Hero: active days / 28.
    Secondaries: sleep regularity + training-load ratio."""

    if movement_consistency:
        days = movement_consistency.get("days_28d", 0)
        target_days = movement_consistency.get("target_per_wk", 5) * 4
        if days >= target_days:        cls, status = "good", "exceeding target"
        elif days >= target_days * 0.7: cls, status = "amber", "near target"
        else:                          cls, status = "warn", "under target"
        hero_html = metric_hero(
            value_html=f'{days}<span class="denom"> / 28 days</span>',
            status_word=f'Active days · {status}',
            status_cls=cls,
            sublabel=f'target {target_days}/28 ({movement_consistency.get("target_per_wk")}/wk) · this week {movement_consistency.get("days_this_wk", 0)}',
        )
    else:
        hero_html = metric_hero(
            value_html='<span class="muted">·</span>',
            status_word='no movement data in 28-day window',
            status_cls="muted",
        )

    secondaries = []
    if sleep_regularity:
        sri = sleep_regularity.get("sri")
        band = sleep_regularity.get("band") or "muted"
        secondaries.append(secondary_metric_row(
            "Sleep Regularity Index",
            f'{fmt(sri, 0)} <span class="muted">/ 100</span>',
            band,
            sublabel=esc(sleep_regularity.get("label") or ""),
            tip="Sleep Regularity Index. UK Biobank top quintile = 20 to 48 percent lower all-cause mortality vs bottom.",
        ))

    if acwr:
        ratio = acwr.get("ratio")
        band = acwr.get("band") or "muted"
        secondaries.append(secondary_metric_row(
            "Training-load ratio",
            f'{fmt(ratio, 2)}',
            band,
            sublabel=esc(acwr.get("label") or ""),
            tip="Acute (last 7 days) divided by chronic (last 28 days) TRIMP. Gabbett sweet spot is 0.8 to 1.3.",
        ))

    secondaries_html = (
        f'<div class="secondary-metrics">{"".join(secondaries)}</div>'
        if secondaries else ""
    )

    return f'''
<section class="card domain-card">
  <h2>{_heading("Behavioral consistency", "behavioral")}</h2>
  {hero_html}
  {secondaries_html}
  {coach_block(coach_text)}
</section>
'''


def card_risk_flags(longevity_state, coach_text):
    """Personalized risk flag panel. Reads from `longevity_state` parsed
    in health.py. Shows nothing when a person has no longevity profile."""
    if not longevity_state:
        return f'''
<section class="card domain-card">
  <h2>{_heading("Personalized risk flags", "risk_flags")}</h2>
  <div class="muted" style="font-size:13px;">
    No longevity profile on file. Add <code>&lt;Person&gt;/data/longevity/&#123;profile,state&#125;.md</code> to populate.
  </div>
  {coach_block(coach_text)}
</section>
'''
    flags = longevity_state.get("risk_flags") or []
    fam = longevity_state.get("family_history") or []
    rows = []
    for f in flags:
        rows.append(f'''
<div class="risk-flag-row">
  <div class="risk-flag-label">{esc(f.get("label", ""))}</div>
  {risk_flag_pill(f.get("status", "unknown"))}
  <div class="risk-flag-hint muted">{esc(f.get("hint", ""))}</div>
</div>''')
    fam_html = ""
    if fam:
        fam_html = (
            f'<div class="risk-family muted"><strong>Family history</strong>: '
            f'{esc("; ".join(fam[:3]))}</div>'
        )
    return f'''
<section class="card domain-card">
  <h2>{_heading("Personalized risk flags", "risk_flags")}</h2>
  <div class="risk-flags-list">{"".join(rows) or "<div class='muted'>no flags surfaced</div>"}</div>
  {fam_html}
  {coach_block(coach_text)}
</section>
'''


