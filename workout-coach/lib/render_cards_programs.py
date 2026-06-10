"""Risk, swim, and nutrition trajectory cards."""
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

def card_risk_flags(longevity_state, coach_text):
    """Personalized risk flag panel. Reads from `longevity_state` parsed
    in health.py. Shows nothing when a person has no longevity profile."""
    if not longevity_state:
        # Empty-state branch deliberately skips coach_block — the native
        # message already says what the coach would. Adding the callout
        # double-prompts the user with the same content.
        return f'''
<section class="card domain-card">
  <h2>{_heading("Personalized risk flags", "risk_flags")}</h2>
  <div class="muted" style="font-size:13px;">
    No longevity profile on file. Add <code>&lt;Person&gt;/data/longevity/&#123;profile,state&#125;.md</code> to populate.
  </div>
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


# =============================================================================
# Swim trajectory card — TRAJECTORY tab. Gated on `swim_summary` presence
# in tracker JSON. Answers "is my swimming getting better?" via 14d-vs-prior-14d
# deltas across pace, SPL, SWOLF. Lower is better for all three.
# =============================================================================


def card_swim_trajectory(swim_summary, coach_text):
    """Render the Swim Trajectory card. Gated by render_dashboard — this
    function is never called when swim_summary is None.

    Shape consumed (from lib/swim.py):
      - window_14d.{n_sessions, total_distance_km, total_minutes,
        avg_pace_sec_per_100m, avg_spl, avg_swolf,
        delta_vs_prior_14d.{pace, spl, swolf},
        best_pace_sec_per_100m, best_swolf,
        prior_best_pace, prior_best_swolf, pace_pr, swolf_pr,
        improvement_verdict}
      - sessions (28d count; used as fallback "season context" line)
      - css.{sec_per_100m, set_at}
      - css_retest_due (bool)
      - css_test_detected (dict, prompts a one-line offer)
    """
    if not swim_summary:
        return ""
    w14 = swim_summary.get("window_14d") or {}
    n14 = w14.get("n_sessions", 0)

    verdict = w14.get("improvement_verdict") or "insufficient_data"
    verdict_label = {
        "improving":         "getting better",
        "regressing":        "regressing",
        "mixed":             "mixed signals",
        "flat":              "holding steady",
        "insufficient_data": "not enough swims yet",
    }.get(verdict, verdict)
    verdict_cls = {
        "improving":         "good",
        "regressing":        "warn",
        "mixed":             "amber",
        "flat":              "muted",
        "insufficient_data": "muted",
    }.get(verdict, "muted")

    # Hero: 14d session count + distance + verdict status word.
    dist_14d = w14.get("total_distance_km") or 0.0
    mins_14d = w14.get("total_minutes") or 0.0
    hero_value = (
        f'{n14}<span class="denom"> swim{"s" if n14 != 1 else ""} · '
        f'{dist_14d:.2f} km · {mins_14d:.0f} min (14d)</span>'
    )
    sublabel = None
    if verdict == "insufficient_data":
        sessions_28 = swim_summary.get("sessions") or 0
        sublabel = (
            f"need 2+ swims in current and prior 14d window for a trend. "
            f"Have {sessions_28} session{'s' if sessions_28 != 1 else ''} in last 28d."
        )

    hero_html = metric_hero(
        value_html=hero_value,
        status_word=f"Swim · {verdict_label}",
        status_cls=verdict_cls,
        sublabel=sublabel,
    )

    # Trend rows: pace / SPL / SWOLF deltas. Lower = better for all three,
    # so a negative delta is "good". Arrow + signed delta + magnitude unit.
    deltas = w14.get("delta_vs_prior_14d") or {}

    def _trend_row(metric_key, label, unit, sig_threshold, lower_is_better=True):
        curr_val = {
            "pace":  w14.get("avg_pace_sec_per_100m"),
            "spl":   w14.get("avg_spl"),
            "swolf": w14.get("avg_swolf"),
        }[metric_key]
        delta = deltas.get(metric_key)
        if curr_val is None:
            return secondary_metric_row(label, '<span class="muted"></span>', "muted",
                                        sublabel="no data this window")
        # Arrow + colour: down arrow + good when delta improves; up arrow + warn
        # when delta worsens. Magnitude under threshold reads as flat.
        if delta is None:
            arrow_html = '<span class="muted"></span>'
            sub = "no prior-14d comparison"
        elif abs(delta) < sig_threshold:
            arrow_html = '<span class="muted">flat</span>'
            sub = f'change {signed(delta, 1)} {unit} (below noise floor)'
        else:
            improved = (delta < 0) if lower_is_better else (delta > 0)
            cls = "good" if improved else "warn"
            arrow = "▼" if delta < 0 else "▲"
            arrow_html = f'<span class="{cls}">{arrow} {signed(delta, 1)} {unit}</span>'
            sub = f"vs prior 14d"
        return secondary_metric_row(
            label,
            f'{fmt(curr_val, 1)} <span class="muted">{unit}</span> {arrow_html}',
            "muted",
            sublabel=sub,
        )

    secondaries = [
        _trend_row("pace",  "Pace / 100m", "sec",   1.0),
        _trend_row("spl",   "Strokes per length", "spl", 0.3),
        _trend_row("swolf", "SWOLF",       "swolf", 0.5),
    ]

    # PR badges: pace_pr / swolf_pr are only computed when both windows
    # have data. They're additive signal, not the main read.
    pr_chips = []
    if w14.get("pace_pr"):
        pr_chips.append(
            f'<span class="pill good">PR pace {fmt(w14.get("best_pace_sec_per_100m"), 1)}s/100m</span>'
        )
    if w14.get("swolf_pr"):
        pr_chips.append(
            f'<span class="pill good">PR SWOLF {fmt(w14.get("best_swolf"), 1)}</span>'
        )
    pr_html = (
        f'<div class="pr-chips" style="margin-top:.5rem">{" ".join(pr_chips)}</div>'
        if pr_chips else ""
    )

    # CSS context (only when set in profile).
    css = swim_summary.get("css")
    css_html = ""
    if css:
        css_sec = css.get("sec_per_100m")
        css_html = (
            f'<div class="detail muted">CSS {fmt(css_sec, 1)} sec/100m '
            f'(set {esc(css.get("set_at") or "·")}). Threshold pace anchor for zone interpretation.</div>'
        )
    elif swim_summary.get("css_retest_due"):
        css_html = (
            '<div class="detail muted">CSS not set. Log a 400m + 200m TT '
            'pair with <code>CSS test</code> on the header to populate.</div>'
        )

    return f'''
<section class="card domain-card">
  <h2>Swim trajectory</h2>
  {hero_html}
  <div class="secondary-metrics">{"".join(secondaries)}</div>
  {pr_html}
  {css_html}
  {coach_block(coach_text)}
</section>
'''


# =============================================================================
# Nutrition phase card — TRAJECTORY tab. Gated on `nutrition_phase`
# presence in tracker JSON. Renders the open phase (bulk / cut / maintain /
# recomp) with observed-vs-target rate, stop-signal status, and the
# binding `coach_action_hint` token the LLM must honor in its callout.
# =============================================================================


def card_nutrition_phase(nutrition_phase, coach_text):
    """Render the Nutrition Phase card. Gated by render_dashboard — this
    function is never called when nutrition_phase is None (no open phase).

    Shape consumed (from lib/nutrition_phase.py):
      - current.{start_date, phase_type, days_elapsed, weeks_in_phase}
      - targets.{rate_kg_per_wk, kcal_delta, protein_g_per_kg, stop_conditions}
      - actuals.{rate_kg_per_wk_14d, rate_vs_target_ratio}
      - status (on_track / too_fast / too_slow / flat / regressing / insufficient_data)
      - stop_signals_triggered (list of strings, always present)
      - coach_action_hint (continue / add_calories / slow_intake /
        consider_ending / end_now)
      - history (prior phases for context)
    """
    if not nutrition_phase:
        return ""
    current = nutrition_phase.get("current") or {}
    targets = nutrition_phase.get("targets") or {}
    actuals = nutrition_phase.get("actuals") or {}
    status = nutrition_phase.get("status") or "insufficient_data"
    triggered = nutrition_phase.get("stop_signals_triggered") or []
    hint = nutrition_phase.get("coach_action_hint") or "continue"

    phase_type = (current.get("phase_type") or "phase").capitalize()
    days = current.get("days_elapsed", 0)
    weeks = current.get("weeks_in_phase") or 0

    # Hero: phase type + days elapsed + observed rate vs target.
    obs = actuals.get("rate_kg_per_wk_14d")
    target = targets.get("rate_kg_per_wk")
    status_cls = {
        "on_track":          "good",
        "flat":              "amber",
        "too_slow":          "amber",
        "too_fast":          "warn",
        "regressing":        "warn",
        "insufficient_data": "muted",
    }.get(status, "muted")
    status_label = {
        "on_track":          "on track",
        "flat":              "flat",
        "too_slow":          "too slow",
        "too_fast":          "too fast",
        "regressing":        "regressing",
        "insufficient_data": "insufficient data",
    }.get(status, status)

    if obs is None:
        rate_phrase = "rate not yet computable"
    else:
        rate_phrase = f"{signed(obs, 2)} kg/wk observed (14d)"
    target_phrase = (
        f"target {signed(target, 2)} kg/wk" if target is not None else "no explicit target"
    )

    hero_html = metric_hero(
        value_html=(
            f'{esc(phase_type)} · '
            f'<span class="denom">week {weeks:.1f} ({days} days)</span>'
        ),
        status_word=f'{esc(phase_type)} · {status_label}',
        status_cls=status_cls,
        sublabel=f'{rate_phrase}, {target_phrase}',
    )

    # Secondary rows: protein target, kcal delta, ratio.
    ratio = actuals.get("rate_vs_target_ratio")
    secondaries = []
    if targets.get("protein_g_per_kg") is not None:
        protein_sublabel = (
            "configured target only; intake adherence untracked"
            if targets.get("protein_tracking_status") == "target_only"
            else "hit upper end if vegan (leucine ceiling)"
        )
        secondaries.append(secondary_metric_row(
            "Protein target",
            f'{fmt(targets["protein_g_per_kg"], 1)} <span class="muted">g/kg</span>',
            "muted",
            sublabel=protein_sublabel,
        ))
    if targets.get("kcal_delta") is not None:
        kcal = targets["kcal_delta"]
        secondaries.append(secondary_metric_row(
            "Calorie delta",
            f'{signed(kcal, 0)} <span class="muted">kcal/day</span>',
            "muted",
            sublabel="surplus vs maintenance (estimate)",
        ))
    if ratio is not None:
        secondaries.append(secondary_metric_row(
            "Rate vs target",
            f'{fmt(ratio, 2)}× <span class="muted">target rate</span>',
            "muted",
            sublabel="1.0 means observed = target; over 2.0 means surplus is too large",
        ))

    # Stop signals (when triggered) get their own visible block — these
    # are the pre-committed off-ramp conditions matching observed data.
    stop_html = ""
    if triggered:
        items = "".join(f"<li>{esc(t)}</li>" for t in triggered)
        stop_html = (
            '<div class="stop-signals">'
            '<div class="label warn"><strong>Stop signals triggered</strong></div>'
            f'<ul>{items}</ul>'
            '</div>'
        )

    # Coach action hint pill — the binding token. Always shown.
    hint_label = {
        "continue":         "Continue phase",
        "add_calories":     "Add calories",
        "slow_intake":      "Slow intake",
        "consider_ending":  "Consider ending",
        "end_now":          "End now",
    }.get(hint, hint)
    hint_cls = {
        "continue":         "good",
        "add_calories":     "amber",
        "slow_intake":      "amber",
        "consider_ending":  "warn",
        "end_now":          "warn",
    }.get(hint, "muted")
    hint_html = (
        f'<div style="margin-top:.5rem"><span class="pill {hint_cls}">'
        f'Action: {esc(hint_label)}</span></div>'
    )

    # Stop conditions (the user's pre-committed criteria) — surfaced once
    # as a muted line so the user sees what they signed up for.
    sc = targets.get("stop_conditions")
    sc_html = (
        f'<div class="detail muted" style="margin-top:.5rem"><strong>Pre-committed off-ramp:</strong> {esc(sc)}</div>'
        if sc else ""
    )

    return f'''
<section class="card domain-card">
  <h2>Nutrition phase</h2>
  {hero_html}
  <div class="secondary-metrics">{"".join(secondaries)}</div>
  {hint_html}
  {stop_html}
  {sc_html}
  {coach_block(coach_text)}
</section>
'''
