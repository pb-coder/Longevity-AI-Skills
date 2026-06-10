"""Health and recovery-practice trajectory cards."""
from __future__ import annotations



from .render_helpers import esc, fmt, signed
from .render_components import (
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
from .render_cards_common import _heading, coach_block

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
    # Stage colors come from CSS variables in render_assets.py
    # (--stage-{core,deep,rem,awake}); the class on each span pulls
    # the right one. Empty-night fallback reuses the awake token.
    stage_segments = []
    if total > 0:
        for label, hours, tip in [
            ("Core", core,
             "Light non-REM sleep. The bulk of total sleep; not as restorative individually as Deep but supports memory consolidation."),
            ("Deep", deep,
             "Slow-wave sleep. The most physiologically restorative stage; drives muscle repair, growth hormone release, and glymphatic clearance."),
            ("REM",  rem,
             "Rapid-Eye-Movement sleep. Supports emotional regulation and procedural memory."),
            ("Awake", awake,
             "Wake-after-sleep-onset. Brief arousals during the night. Some is normal; persistent elevation suggests fragmentation."),
        ]:
            if hours > 0:
                pct = (hours / (total + awake)) * 100.0 if (total + awake) > 0 else 0
                stage_segments.append(
                    f'<span class="stage stage-{label.lower()}" '
                    f'style="width:{pct:.2f}%" '
                    f'data-tip="{esc(label)}: average {hours:.2f} h per night. {tip}">'
                    f'</span>'
                )
    stage_bar = "".join(stage_segments) or '<span class="stage stage-awake" style="width:100%"></span>'

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
    eff_is_derived = isinstance(eff, dict) and eff.get("source") == "derived_sleep_period"
    eff_label = "Continuity" if eff_is_derived else "Efficiency"
    eff_tip = (
        "Derived sleep continuity from sleep-stage total divided by the stored sleep-period span. This is not always the clinical time-in-bed denominator. "
        if eff_is_derived else
        "Sleep efficiency is the percent of time in bed that you were actually asleep. "
    )
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
    <div class="sleep-row" data-tip="{esc(eff_tip)}The healthy adult range is 85% or higher; below 80% is what sleep clinics flag as disturbed in screening tools. Status: {ef_word}.">
      <span class="bar-dot band-{band_class_map[ef_band]}"></span>
      <span class="sleep-row-label">{esc(eff_label)}</span>
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
    if rr_mean is not None:
        sleep_row_parts.append(f'''
    <div class="sleep-row" data-tip="Average respiratory rate during sleep. Typical adult range is 12 to 20 breaths per minute. A sustained rise can precede illness by 24 to 48 hours. Status: {rr_word}.">
      <span class="bar-dot band-{band_class_map[rr_band]}"></span>
      <span class="sleep-row-label">Respiratory rate</span>
      <span class="sleep-row-value {rr_band}">{rr_value}</span>
    </div>''')
    if sbd_mean is not None:
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
        <span><span class="dot stage-core"></span>Core {core:.2f} h</span>
        <span><span class="dot stage-deep"></span>Deep {deep:.2f} h</span>
        <span><span class="dot stage-rem"></span>REM {rem:.2f} h</span>
        <span><span class="dot stage-awake"></span>Awake {awake:.2f} h</span>
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
        # Empty-state branch deliberately skips coach_block — the native
        # message already says what the coach would. Adding the callout
        # double-prompts the user with the same content (one of the v2
        # cleanup fixes).
        return f'''
<section class="card">
  <h2>Recovery practices</h2>
  <div class="body">
    <p>No sauna, cold exposure, or light-therapy sessions in the last 28 days.</p>
    <p class="muted">Log via <code>/log</code> after each session to track adherence against the 4 per week sauna and 3 per week light-therapy defaults.</p>
  </div>
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
  <div class="recent">Dry/banya HSP band: {fmt(heat.get("minutes_above_hsp_threshold_per_week"), 0)} min/wk above 80 °C for 20+ min. Steam: {fmt(heat.get("steam_minutes_per_week"), 0)} min/wk.</div>
</div>
'''
    # Cold-exposure block: weekly count + adherence pill (when adherence
    # status is computed) + one-line average (only when both temp and
    # duration are populated for at least one session). Per-session detail
    # and "not logged" pills are omitted as v1 dictated, but the card
    # always carries at least the "paired with sauna" pill + a sessions
    # count line so it never reads as visually empty.
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
        adherence_pill(cold_status) if cold_status
        else f'<span class="pill muted">paired with sauna {fmt(cold.get("paired_with_heat_pct"), 0)}%</span>'
    )
    n_28 = cold.get("n_sessions_28d") or 0
    sessions_count_line = (
        f'<div class="detail">{n_28} session{"s" if n_28 != 1 else ""} '
        f'in last 28 days.</div>'
        if n_28 else ""
    )
    cold_title = "Cold exposure"
    if cold.get("dominant_type"):
        cold_title += f' ({esc(str(cold.get("dominant_type")).replace("_", " "))})'
    cold_html = f'''
<div class="practice">
  <div class="title">{cold_title}</div>
  <div class="big">{fmt(cold.get("n_sessions_per_week"), 2)}<span class="unit">/ wk</span></div>
  {cold_adherence_html}
  {sessions_count_line}
  {avg_line_html}
</div>
'''
    light_adh = (light or {}).get("adherence") or {}
    dominant_light = (light or {}).get("dominant_light_type")
    dominant_modality = (light or {}).get("dominant_modality")
    light_recent = f'Average session {fmt((light or {}).get("avg_session_minutes"), 0)} min.'
    if dominant_light or dominant_modality:
        light_recent += (
            f' {esc(dominant_light or "unknown")} via '
            f'{esc(dominant_modality or "unknown")}.'
        )
    light_html = f'''
<div class="practice">
  <div class="title">Light therapy</div>
  <div class="big">{fmt((light or {}).get("n_sessions_per_week"), 2)}<span class="unit">/ wk</span></div>
  {adherence_pill(light_adh.get("status"))}
  <div class="detail">Target {light_adh.get("target_per_week", 3)} per week, {light_adh.get("target_min_per_session", 10)} min per session.</div>
  <div class="recent">{light_recent}</div>
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
