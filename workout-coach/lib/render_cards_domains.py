"""Longevity-domain trajectory cards."""
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

    # Bloodwork is now surfaced as a synthetic entry in missing_inputs
    # (consolidated to one place per v2). The standalone callout that
    # used to live here was redundant. Body-comp + metabolic domain
    # cards keep their own bloodwork-pending callouts for domain context.
    pending_note = ""

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
    eff_is_derived = isinstance(eff_block, dict) and eff_block.get("source") == "derived_sleep_period"

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
            "Continuity" if eff_is_derived else "Efficiency",
            f'{eff_mean:.1f} <span class="muted">%</span>',
            cls,
            sublabel=f'target ≥85% · {lbl}',
            tip=(
                "Derived from sleep-stage total divided by stored sleep-period span; not always a clinical time-in-bed denominator."
                if eff_is_derived else
                "Percent of time in bed actually asleep. Healthy adult range is 85% or higher; below 80% is what sleep clinics flag as disturbed in screening tools."
            ),
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
        # This note only renders when the private longevity profile carries
        # the matching risk flag; never infer it from low REM alone.
        parkinson_note = (
            " Relevant for the family-history surveillance marker."
            if _has_risk_flag(longevity_state, "parkinson_surveillance") else ""
        )
        rem_watch = f'''
<div class="rem-watch muted">
  <span class="pill amber">REM watch</span> {low} of {rem_anomaly.get("n_nights", 0)} nights showed REM below 15% of total sleep in the 28-day window.
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


# Short, true sublabels for each ``bodyweight_trend.reason`` the
# estimator emits. Keyed off the reason CODE, not the prose, so a wording
# change in ``sessions.bodyweight_trend`` cannot silently desync this
# card; an unrecognised code falls through to the block's own ``note``,
# and a missing block to a statement that claims nothing.
_BW_UNRESOLVED_SUB = {
    "no_readings":              "no fasted weigh-ins in the window",
    "too_few_readings":         "too few weigh-ins to fit a rate",
    "window_shorter_than_min":  "window shorter than the 28-day minimum",
    "no_time_variance":         "all weigh-ins fall on one day",
    "ci_straddles_zero":        "direction not resolved — 95% interval spans zero",
}


def _bw_unresolved_sub(block):
    """Sublabel for an unresolved bodyweight trend, sourced from the block."""
    if not isinstance(block, dict):
        return "rate not resolvable from the current window"
    reason = block.get("reason")
    if reason in _BW_UNRESOLVED_SUB:
        return _BW_UNRESOLVED_SUB[reason]
    note = block.get("note")
    return note if note else "rate not resolvable from the current window"


def card_body_comp_domain(bw, bw_trend, longevity_state, coach_text,
                          bw_trend_block=None):
    """Body composition domain card. Hero: bodyweight + trend context.
    Body fat and visceral fat secondaries are explicit DEXA-pending.

    ``bw_trend_block`` is ``tracker.bodyweight_trend`` — the same rate
    with its ``state`` / ``reason`` / ``note``. When ``bw_trend`` is
    ``None`` the card MUST say why from that block rather than assert a
    cause of its own: the estimator is an OLS fit over a >=28-day window
    that reports ``unresolved`` for five distinct reasons, and the card
    previously claimed a sixth one that no longer exists ("needs 8+
    fasted entries" was the pre-2026-08 rule). A renderer inventing the
    reason for a missing number is how a dashboard tells the user
    something false about their own data.
    """
    bw_val = (bw or {}).get("kg")
    has_profile = bool(longevity_state)

    # Hero: bodyweight with trend status
    if bw_trend is None:
        cls, status = "muted", "trend unresolved"
        sub = _bw_unresolved_sub(bw_trend_block)
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

    # Gate medication-specific BMD copy on the private risk flag.
    if has_profile and _has_risk_flag(longevity_state, "prep_monitoring"):
        dexa_msg = (
            '<strong>DEXA pending.</strong> Visceral adipose tissue (VAT), '
            'appendicular lean mass (ALMI), and bone density (BMD) need a DEXA scan to populate. '
            'The medication-monitoring marker also calls for a BMD baseline.'
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
    (dietary context, seasonal vitamin D windows, medication markers)."""
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
