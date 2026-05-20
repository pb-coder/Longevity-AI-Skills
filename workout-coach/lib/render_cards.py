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
    confidence_dots,
    driver_bars,
    freshness_scale,
    load_chart_svg,
    muscle_bars,
    recovery_scale,
    sparkline,
)
from render_validators import auto_wrap_terms


def card_hero(score, score_cls, confidence, tsb, tsb_cls, tsb_label, ctl, atl, tsb_trend):
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
  <h2><span class="term" data-tip="Non-Exercise Activity Thermogenesis. All-day movement outside structured workouts, averaged over the last 28 days. Strongly tied to long-term metabolic health and longevity.">NEAT</span></h2>
  <div class="neat-stats">
    <div class="neat-stat">
      <div class="neat-stat-num">{fmt(avg_min, 0)}<span class="neat-stat-unit">min/day</span></div>
      <div class="neat-stat-desc">exercise minutes · <span class="neat-stat-status {status_cls}">{esc(status_word)}</span></div>
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

    <div class="sleep-row" data-tip="Together, Deep and REM sleep carry the recovery and memory load. A common target is 2.5+ hours combined per night. Status: {dr_word}.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[dr_band] }"></span>
      <span class="sleep-row-label">Deep + REM</span>
      <span class="sleep-row-value {dr_band}">{deep_plus_rem:.2f} h</span>
    </div>

    <div class="sleep-row" data-tip="Sleep efficiency is the percent of time in bed that you were actually asleep. The healthy adult range is 85% or higher; below 80% is what sleep clinics flag as disturbed in screening tools. Status: {ef_word}.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[ef_band] }"></span>
      <span class="sleep-row-label">Efficiency</span>
      <span class="sleep-row-value {ef_band}">{ef_value}</span>
    </div>

    <div class="sleep-row" data-tip="The number of awake-or-stage-transition segments Apple's classifier counted per night. More segments mean more fragmentation. Lower is better. Status: {fr_word}.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[fr_band] }"></span>
      <span class="sleep-row-label">Fragmentation</span>
      <span class="sleep-row-value {fr_band}">{fmt(frag_mean, 1)} segs / night</span>
    </div>

    <div class="sleep-row" data-tip="Bedtime and waketime standard deviation over the last 28 days. A tighter schedule produces a better recovery profile. Under 30 minutes is tight, 30 to 60 is loose, above 60 is erratic. Status: {bt_word}.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[bt_band] }"></span>
      <span class="sleep-row-label">Schedule</span>
      <span class="sleep-row-value {bt_band}">bedtime ± {fmt(bt_stdev, 0)} min · waketime ± {fmt(wt_stdev, 0)} min</span>
    </div>

    <div class="sleep-row" data-tip="Average respiratory rate during sleep. Typical adult range is 12 to 20 breaths per minute. A sustained rise can precede illness by 24 to 48 hours. Status: {rr_word}.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[rr_band] }"></span>
      <span class="sleep-row-label">Respiratory rate</span>
      <span class="sleep-row-value {rr_band}">{rr_value}</span>
    </div>

    <div class="sleep-row" data-tip="Apple's overnight breathing disturbances signal. Persistently elevated values are a screening signal for sleep apnea and worth raising with a doctor. Below 5 per minute is generally low. Status: {sbd_word}.">
      <span class="bar-dot band-{ {"good":"prod","amber":"push","warn":"over","muted":"low"}[sbd_band] }"></span>
      <span class="sleep-row-label">Breathing disturbances</span>
      <span class="sleep-row-value {sbd_band}">{sbd_value}</span>
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


