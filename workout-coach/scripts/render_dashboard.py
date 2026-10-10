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

Every plan check (tracker payload, coach copy, workout copy, core and
arm floors, set budget, rotation, the opener cross-check) runs through
`lib/plan_checks.run_plan_checks`, the same function `check_plan.py`
runs on the default no-report path. Nothing renders unless it passes.

Strict copy rules (enforced by `validate_coach_reads`):
  * No em-dashes anywhere in coach text.
  * No bare abbreviations except those in `KNOWN_TERMS` (and even those
    are wrapped in dotted-underline tooltips by the renderer; the
    coach text uses plain language by default).
  * Each string <= 280 characters.

This file is the **thin CLI entry point + render orchestrator**. The
actual building blocks live under ``workout_coach.lib.render_*``;
see ``Skills/workout-coach/CODE_MAP.md`` for the directory map.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

_SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(_SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILLS_ROOT))

from workout_coach.lib.plan_checks import run_plan_checks
from workout_coach.lib.render_helpers import esc
# Direct submodule imports bypass the render_assets / render_components /
# render_cards / render_cards_trajectory compatibility facades. Each
# facade is a tiny re-export module; loading them just to forward names
# is wasted parse + exec cost on every cold render subprocess.
from workout_coach.lib.render_components_load import build_load_series
from workout_coach.lib.render_components_misc import embed_workout_markdown, ring
from workout_coach.lib.render_styles import STYLESHEET
from workout_coach.lib.render_scripts import INLINE_JS
from workout_coach.lib.render_cards_today import (
    card_acwr,
    card_block_position,
    card_drivers,
    card_hero,
    card_muscle_volume,
    card_neat,
    card_rings,
    card_session_call,
    card_strength,
    card_tier_history_strip,
    card_training_load,
    card_wow,
)
from workout_coach.lib.render_cards_health import (
    card_recovery_practices,
    card_sleep,
    card_vitals,
)
from workout_coach.lib.render_cards_domains import (
    card_behavioral_domain,
    card_body_comp_domain,
    card_cardio_domain,
    card_longevity_score,
    card_metabolic_domain,
    card_recovery_domain,
    card_sleep_domain,
)
from workout_coach.lib.render_cards_programs import (
    card_energy,
    card_nutrition_phase,
    card_risk_flags,
    card_swim_trajectory,
)


def render(j: TrackerJSON, coach: CoachReads, workout_md: str, person: str) -> str:
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
    # The scalar is None for five distinct reasons. Both bodyweight
    # surfaces read the reason CODE off this block instead of narrating a
    # cause of their own: without it they fall back to a reason-less
    # "unresolved", which is what let the dashboard report a confident
    # loss over a stretch the user actually gained 1.7 kg across.
    bw_trend_block = j.get("bodyweight_trend")
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

    # rings. Every ring on this "This week at a glance" card reads the
    # SAME this-week (last 7 days) window from week_over_week, so the card
    # is window-consistent. (Zone 2 and recovery used to be 28-day
    # averages here while strength/cardio were this-week, which made the
    # Z2 figure read far lower than the user's actual week.)
    def _wow_this_week(key):
        r = next((r for r in wow.get("rows", []) if r.get("key") == key), {})
        return r.get("this_week") or 0

    strength_wk = next(
        (r for r in wow.get("rows", []) if r.get("key") == "strength_sessions"), {}
    )
    z2_min = round(_wow_this_week("cardio_z2_min"))
    recovery_sessions = round(_wow_this_week("recovery_sessions"), 1)
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

    # Trajectory tab inputs
    longevity_score = j.get("longevity_score") or {}
    longevity_state = j.get("longevity_state")
    vo2_percentile = j.get("vo2_percentile")
    hr_recovery = j.get("hr_recovery")
    acwr = j.get("acwr")
    sleep_regularity = j.get("sleep_regularity")
    rem_anomaly = j.get("rem_anomaly")
    movement_consistency = j.get("movement_consistency")

    # Session-recommendation gate (Today tab headline) + 14-day tier history
    # (Trajectory tab). The gate is the new binding decision the coach must
    # honor before generating any workout markdown.
    session_rec = j.get("session_recommendation")
    tier_history = j.get("tier_history") or []

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
    <button class="tab" role="tab" data-tab="today">Today</button>
    <button class="tab" role="tab" data-tab="trajectory">Trajectory</button>
    <button class="tab" role="tab" data-tab="workout">Workout</button>
  </div>

  <div class="tab-panel" data-tab="today">
    {card_session_call(session_rec, coach_cards.get("session_recommendation_callout"), summary_text=headline)}
    {card_hero(score, score_cls, confidence, tsb, tsb_cls, tsb_label, ctl, atl, tsb_trend)}
    {card_drivers(recovery.get("drivers"), coach_cards.get("recovery_drivers"))}
    {card_acwr(acwr, coach_cards.get("today_acwr"))}
    {card_rings(rings_html, coach_cards.get("activity_rings"))}
    {card_neat(j.get("daily_activity_28d"))}
    {card_block_position(j.get("block"), j.get("dose_staleness"), coach_cards.get("block_position"))}
    {card_training_load(series, ctl, atl, tsb, tsb_trend, coach_cards.get("training_load"))}
    {card_muscle_volume(weekly_volume, coach_cards.get("muscle_volume"), hr_divergence=j.get("hr_at_volume_divergence"))}
    {card_strength(e_items, coach_cards.get("strength"))}
    {card_wow(wow)}
  </div>

  <div class="tab-panel" data-tab="trajectory">
    {card_longevity_score(longevity_score, coach_cards.get("trajectory_longevity_score"))}
    {card_cardio_domain(vo2_percentile, hr_recovery, recovery, j.get("cardio_hr_zones_28d") or {}, vo2max, vo2_trend, coach_cards.get("trajectory_cardio"))}
    {card_swim_trajectory(j.get("swim_summary"), coach_cards.get("swim_trajectory_callout"))}
    {card_recovery_domain(recovery, weekly, coach_cards.get("trajectory_recovery"))}
    {card_sleep_domain(j.get("sleep_summary"), sleep_regularity, rem_anomaly, coach_cards.get("trajectory_sleep"), longevity_state=longevity_state)}
    {card_body_comp_domain(bw, bw_trend, longevity_state, coach_cards.get("trajectory_body_comp"), bw_trend_block)}
    {card_energy(j.get("energy_28d"), j.get("nutrition_phase"), coach_cards.get("trajectory_energy"))}
    {card_nutrition_phase(j.get("nutrition_phase"), coach_cards.get("nutrition_phase_callout"))}
    {card_metabolic_domain(longevity_state, coach_cards.get("trajectory_metabolic"))}
    {card_behavioral_domain(movement_consistency, sleep_regularity, acwr, j.get("cardio_hr_zones_28d") or {}, coach_cards.get("trajectory_behavioral"))}
    {card_vitals(weekly, vo2max, vo2_trend, bw, bw_trend, j.get("bodyweight_weekly") or [], coach_cards.get("vitals"), bw_trend_block, j.get("waist_latest"), j.get("waist_trend_cm_per_4w"), j.get("body_fat_latest"), j.get("body_fat_trend_pct_per_4w"), j.get("lean_mass_latest"), j.get("lean_mass_trend_kg_per_4w"))}
    {card_sleep(j.get("sleep_summary"), coach_cards.get("sleep"))}
    {card_recovery_practices(thermal, light, coach_cards.get("recovery_practices"))}
    {card_risk_flags(longevity_state, coach_cards.get("trajectory_risk_flags"))}
    {card_tier_history_strip(tier_history)}
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
        j = json.loads(Path(args.tracker).read_text(encoding="utf-8"))

    # Every plan check lives in `lib/plan_checks.py`, shared with
    # `check_plan.py`, so the report and the default no-report path
    # cannot drift apart. Nothing renders unless every blocking check
    # passes.
    checks = run_plan_checks(j, args.coach, args.workout_md)
    if checks.exit_code:
        return checks.exit_code
    coach: CoachReads = checks.coach
    workout_md = checks.workout_md

    out = render(j, coach, workout_md, args.person)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(out, encoding="utf-8")
    tmp.replace(out_path)
    print(f"wrote {args.out} ({len(out):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
