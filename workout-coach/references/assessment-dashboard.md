# Assessment dashboard — renderer spec & coach-reads contract

This doc covers **what** each card shows and the data contracts the
renderer reads. The **how it looks** — colours, typography, pill chrome,
card spacing, empty-state rules — lives in
[`Skills/DESIGN.md`](../../DESIGN.md). Read DESIGN.md before changing
CSS or adding a new visual element.

The dashboard is produced by **`Skills/workout-coach/scripts/render_dashboard.py`** (thin CLI orchestrator) plus `workout_coach.lib.render_*` modules — see [`../CODE_MAP.md`](../CODE_MAP.md) for the map of which file owns which concern. The script + lib together own all HTML, CSS, SVG, JavaScript, and layout. The coach LLM authors two inputs:

1. **`coach_reads.json`** — short advice strings, one per card.
2. **`<date>-workout.md`** — the lean workout plan (also written to disk so `/log` can read it; embedded into the HTML for the in-browser Workout tab).

The renderer reads both, validates the coach text, and writes the final HTML to `plans/<Person>/<date>-assessment.html`. Single-file output, no external resources.

---

## Output anatomy

```
plans/<Person>/<date>-assessment.html
├── header                          name, date
├── tabs                            Assessment / Workout Plan
├── tab: Assessment
│   ├── coach's summary             top card, label "COACH'S SUMMARY", body text
│   ├── hero                        Recovery (score + 0..10 scale strip + confidence dots),
│   │                                Freshness (signed TSB + -15..+15 scale strip + 7-day trend arrow)
│   ├── recovery drivers            diverging-bar chart (z=null drivers filtered out)
│   ├── activity rings              5 rings: strength / cardio sessions / Z2 / recovery / sleep
│   ├── NEAT                        own card, 3 centered stat cells over 28 days:
│   │                                exercise min/day (color-coded), walking min/day, walking km/day
│   ├── block position              week N of M, "selection is stable by design", weeks to next rotation
│   ├── training load (90d)         interactive chart + 4-up summary row (fitness / fatigue / freshness / 7-day trend)
│   ├── per-muscle volume           bars + MEV/MAV ticks, 4 distinct band colors, dots on labels
│   ├── strength progression        e1RM table with confidence dots
│   ├── health vitals               HRV, RHR, wrist temp (dynamic status), VO2max, bodyweight (with sparkline) — sleep is NOT here
│   ├── sleep                       stage stack, schedule, efficiency, fragmentation,
│   │                                respiratory rate, breathing disturbances, outliers
│   ├── recovery practices          3 sub-cards: sauna / cold / light therapy
│   └── week over week              this-wk / last-wk / 4-wk-avg table
└── tab: Workout Plan
    └── rendered from <date>-workout.md (each ## becomes a card,
        em-dash sub-bullets nest under their parent exercise)
footer                              "generated at YYYY-MM-DD HH:MM"
```

Every card with actionable signal carries a **Coach callout** below the data: thin hairline rule above, small-caps "COACH" label in muted color, body text in normal color. **No box, no border, no tinted background.** Typography does the work.

## Coach-reads schema

```json
{
  "headline": "2-3 sentences in plain English. The TL;DR.",
  "cards": {
    "// Today tab": "",
    "session_recommendation_callout":  "narrative gloss on the recovery gate ...",
    "today_acwr":                       "one sentence on the acute:chronic workload ratio ...",
    "recovery_drivers":                "one sentence ...",
    "activity_rings":                  "one sentence ...",
    "block_position":                  "one or two sentences. Where they are in the block, that selection is stable by design, when the next rotation lands, and what the dose actually did this week.",
    "training_load":                   "one sentence ...",
    "muscle_volume":                   "one sentence ...",
    "strength":                        "one sentence ...",
    "// Trajectory tab — domain callouts": "",
    "trajectory_longevity_score":      "one sentence on the composite longevity score ...",
    "trajectory_cardio":               "one sentence on the cardio domain ...",
    "trajectory_recovery":             "one sentence on the recovery domain ...",
    "trajectory_sleep":                "one sentence on the sleep domain ...",
    "trajectory_body_comp":            "one sentence on the body-composition domain ...",
    "trajectory_metabolic":            "one sentence on the metabolic domain ...",
    "trajectory_behavioral":           "one sentence on the behavioral domain ...",
    "trajectory_risk_flags":           "one sentence on the risk-flag domain ...",
    "// Trajectory tab — gated (only when the matching tracker block is present)": "",
    "swim_trajectory_callout":         "one or two sentences. Quote the verdict + 1 thing to fix in the next session. Required when tracker JSON contains swim_summary.",
    "nutrition_phase_callout":         "one or two sentences. Quote the coach_action_hint + the binding 'why'. Required when tracker JSON contains nutrition_phase. For bulk phases, read references/bulking-science.md first.",
    "// Cross-tab cards (render on the Trajectory tab)": "",
    "vitals":                          "one to two sentences, signal + action ...",
    "sleep":                           "one sentence ...",
    "recovery_practices":              "one sentence ..."
  }
}
```

All keys under `cards` are optional. A missing key emits a soft warning to stderr but doesn't block the render — the corresponding card simply renders without a callout. The full list of documented keys lives in `lib/render_validators.py::COACH_CARD_KEYS`, grouped by tab (Today, Trajectory domain callouts, Trajectory gated cards, and retained cross-tab cards). Two keys are gated (`swim_trajectory_callout`, `nutrition_phase_callout`): the validator does NOT warn when they're missing, because their cards only render when the matching tracker block is present (swim data, an open nutrition phase). The coach should still author them when the data is present.

The NEAT card has no coach callout slot; the three stat cells are glanceable on their own.

**Hard rules (enforced by `validate_coach_reads`; render fails if violated):**

| Rule | Reason |
| --- | --- |
| No em-dash (`—`) anywhere | User preference. Use periods, commas, colons. |
| Each card string ≤ 280 characters | Forces concision. Long advice belongs in the dashboard's tooltips, not the coach line. |
| `headline` ≤ 560 characters | Two to three sentences. |

**Soft rules (the LLM should follow even though they aren't validated):**

- **Action voice is imperative.** "Target 7.5 h tonight" not "you should consider targeting 7.5 h".
- **Action only when actionable.** If nothing meaningful changes, the read is *"On track, hold course."* or *"Steady, no change."* Do not invent urgency.
- **Plain English.** The renderer automatically wraps abbreviations (CTL, ATL, TSB, e1RM, MEV, MAV, MRV, SDNN, HRR, RHR, HRV, Z2, Z5, VO2max, HSP) in dotted-underline tooltips when they appear, so the coach is *allowed* to use them. But prefer the plain-English equivalent when it reads more naturally ("fitness" instead of CTL, "freshness" instead of TSB).
- **One sentence per card.** Two sentences only when there are two distinct actions.

## Card spec (data sources)

| Card | Reads from JSON | Notes |
| --- | --- | --- |
| Hero · Recovery | `recovery.score`, `recovery.confidence` | Big number on a `/ 10` denom + a horizontal `recovery_scale` strip (0..10 axis) showing where the score sits. Three band labels: depleted (<4.5, warn), moderate (4.5..6.5, amber), ready (≥6.5, good). Same SVG structure as `freshness_scale` so the two hero cards read as siblings. When `score` is null the big number is replaced with "not enough data". |
| Hero · Freshness | `training_load.{ctl, atl, tsb, trend_7d}` | Big signed number + a horizontal `freshness_scale` strip showing where the value sits on a -15..+15 axis. Six band labels: high fatigue (≤-15), fatigued (-15..-10), carrying load (-10..-5), balanced (-5..+5), fresh (+5..+10), well rested (>+10). Marker color: good (-5..+10), amber (the two outer non-extreme bands), warn (≤-10). Sub area shows only the 7-day trend arrow — fitness/fatigue numbers live in the training-load summary row instead, to avoid duplication. |
| Recovery drivers | `recovery.drivers[*]` | Diverging horizontal bar chart, sorted by \|z\| desc, capped at 8 rows. **Penalty-only drivers (those with `z=None`) are filtered out** — they are "no-penalty" placeholders, not signals of movement. Positive z = green (favorable; the metric module already sign-flips RHR/wrist temp). |
| Activity rings | `week_over_week.rows` (strength count), `cardio_hr_zones_28d.z2`, `cardio_hr_zones_28d.z2_by_activity`, `thermal_summary` + `light_therapy_summary` (recovery sessions), `health_metrics_weekly` (sleep avg) | Targets: 4 strength sess, 150 min Z2, 4 recovery sess, 7 h sleep. Ring color: good when ≥ target, amber otherwise. Never red. Five rings; mobile breakpoint collapses to 2-up. `z2` stays the total ring value; `z2_by_activity` is available for coach copy so short swims can be named separately from dedicated run/ride/walk-hike Z2 dose. |
| NEAT | `daily_activity_28d.{exercise_min_daily_avg, walking_minutes_28d, walking_distance_km_28d, assessment}` | Own full card titled "NEAT over 28 days". Three centered stat cells, all framed per day: (1) exercise min/day with a colored status word (`high`→good, `moderate`→amber, `low`→warn) keyed off `assessment`; (2) walking min/day = `walking_minutes_28d / 28`; (3) walking km/day = `walking_distance_km_28d / 28`. No coach callout. |
| Block position | `block.{age_weeks, max_weeks, weeks_to_boundary, boundary_due}`, `dose_staleness` | **Renders whenever `block` is non-null, every week, including weeks where nothing changed.** It exists to disclose that mid-block repetition is deliberate: inside a block the exercise SELECTION is held stable on purpose and the load and rep targets are the moving parts, so a plan that looks like last week's is the design working rather than the coach repeating itself. Hero line is "Week N of {max_weeks} in this block", where `N = int(age_weeks) + 1` — `age_weeks` is ELAPSED weeks (0.0 on the start day), so 1.1 elapsed is week 2. Not capped at `max_weeks`: a block past its ceiling reads "Week 7 of 6", which is the disclosure working. Second line is the countdown, "Next rotation in {weeks_to_boundary} weeks", replaced by "Rotating this week" when `boundary_due` is true. **Never compute a date; the payload is anchored as-of and a future-dated string trips the horizon rule.** Below that, the dose delta, so "selection is stable" cannot read as "nothing changed": which lifts took weight, which took reps, and which held, sourced from `dose_staleness`; the card names the held lifts and the coach callout supplies the *why*, because the payload carries `generations_static` and not a reason. Renders "block starts here / with this plan" and NO countdown when `block` is null **or when `age_weeks` is null** — the latter is the shape `read_tracker` actually emits on a first run (`block.source == "none"`), so keying only on a null `block` would print a fabricated countdown. Implemented at `lib/render_cards_today.py::card_block_position`. Coach callout key: `block_position`. |
| Training load (90d) | computed locally from `monthly_sessions[*].trimp` via 42-day / 7-day EWMA, seeded from sessions older than the window | Interactive chart: mouse / touch reveals scrubber + values at the hovered day. Below the chart: a single 4-up summary row (`.load-summary`) with one cell per metric — colored swatch (matching the line on the chart) + tooltipped name + current value. Replaces the prior split between a separate legend row and a stats row. |
| Per-muscle volume | `weekly_volume_per_muscle.current` and `.landmarks` | Four-color palette: `not enough` (orange, below MEV), `productive` (green, MEV..MAV), `pushing limit` (yellow, MAV..MRV), `too much, cut back` (red, above MRV). Thin tick marks at MEV and MAV on each track; **no background band**. Bar-status labels start with a small colored dot so labels align regardless of icon width. The MEV/MAV explanation sits on its own line below the four color chips. |
| Strength progression | `estimated_1rm[*]` filtered to entries with non-null `slope_kg_per_4w` + `current_e1rm_kg`, sorted by \|slope\|, capped at 8 | Arrow class: good (slope ≥ +0.5), warn (≤ -0.5), muted otherwise. e1RM and slope column headers have tooltips. Explicit column widths via the `.strength-table` class so the long Lift names don't squeeze the numeric columns; last-row border suppressed. |
| Health vitals | `health_metrics_weekly` (HRV / RHR / wrist temp / sleep / deep / REM / VO2max / **waist** series), `vo2max_latest`, `vo2max_trend_per_4w`, `bodyweight_latest`, `bodyweight_trend`, `bodyweight_trend_kg_per_week`, `bodyweight_weekly`, `waist_latest`, `waist_trend_cm_per_4w` | One clean table, no inline coach rows. Sparklines colored by per-row status. **Wrist temp** State is computed dynamically (stable / rising / elevated / insufficient data) from the latest week's z-score vs. the prior 3-week mean, matching the HRV/RHR pattern but inverted (higher = warning). **Bodyweight** carries a sparkline driven by the `bodyweight_weekly` series (ISO-week means). Its State cell reads `bodyweight_trend.state`: a rate is shown only when the OLS fit over a 28-day-minimum window has a 95% interval excluding zero, and otherwise the cell names the reason (`no weigh-ins` / `too few weigh-ins` / `window under 28d` / `one day only` / `direction unresolved`) rather than a bare "no trend". When an open nutrition phase exists the window is the phase; use `nutrition_phase.actuals.rate_kg_per_wk_14d` as the primary phase-status number. **Waist** sits directly under Bodyweight, because the pair answers a question neither answers alone: scale weight says how much, waist says where it went. Value cell is `waist_latest.value_cm`; sparkline is the `waist_cm` field on `health_metrics_weekly` (ISO-week means, same series treatment as HRV / RHR / VO2max). State cell reads `waist_trend_cm_per_4w.state` and prints a rate ONLY when it is `resolved`; otherwise it names the reason (`not measured` / `too few measurements` / `window under 56d` / `one day only` / `direction unresolved`). Status class: `good` when a resolved fit is narrowing, `amber` when it is widening, `muted` otherwise — but it reaches the **sparkline stroke only**. Every State cell in this table, waist included, is hardcoded `class="muted"`; `card_vitals` unpacks the per-row class and never applies it to the text cell. **The row never hides.** With zero measurements it renders with an empty value and the State cell reads "not measured"; with one, the sparkline is an empty box (the shared `sparkline` helper needs two real points) and the State cell says a single measurement is not a trend. **It can draw a flat line, and often will:** `sparkline` falls back to `span = 1.0` when max equals min, so two equal weekly means plot level — the likeliest outcome for a tape read to 0.1-0.5 cm resolution. **A gap does not render as a gap:** `sparkline` filters `None` out and re-spaces what is left evenly, so the x-axis is ordinal, not time, and a 3-week gap is pixel-identical to a 1-week one. Do not read slope steepness off any sparkline in this table as a rate. Sparkline column hides at ≤ 480 px. Column widths set via `.vitals-table` class. |
| Sleep | `sleep_summary.{means_h, sleep_efficiency_pct, absolute_sleep_note, fragmentation, schedule_consistency, resp_rate, breath_disturbances, outliers}` | Dedicated card after Health vitals. Hero shows average total + Time in Bed proxy. Stack chart breaks down Core / Deep / REM / Awake. Six diagnostic rows (Deep+REM, continuity/efficiency, fragmentation, schedule, respiratory rate, breathing disturbances) each with a colored row-start dot + the value itself colored by band. Newer iOS/export paths may not emit explicit `InBed`, so derived values render as continuity rather than clinical efficiency. |
| Recovery practices | `thermal_summary.heat`, `thermal_summary.cold`, `thermal_summary.cold.recent_sessions`, `thermal_summary.adherence`, `light_therapy_summary` | Three sub-cards, identical layout. Cold sub-card lists recent sessions with their temperature (the `dose_hint: "amber"` flag for cold_air ≥ 18 °C tags weak doses). Heat and light adherence targets come from `profile.csv` when configured, with defaults only as fallback. HSP dose is dry/banya-only; steam minutes render as separate heat-habit minutes. Coach copy should say "below configured target" rather than implying universal reachability. |
| Swim trajectory | `swim_summary.window_14d.*` (verdict, 14d aggregates, deltas vs prior 14d, PR flags), `swim_summary.css`, `swim_summary.css_retest_due`, `swim_summary.css_missing_nudge` | **Gated card — renders iff `swim_summary` is non-null in tracker JSON.** Trajectory tab; sits between Cardio domain and Recovery domain so the cardio narrative reads as one block. Hero = 14d session count + distance + improvement verdict ("getting better" / "regressing" / "mixed signals" / "holding steady" / "not enough swims yet"). Three trend rows: pace per 100m, SPL, SWOLF, each with current value + signed delta vs prior 14d (lower = better for all three; the renderer applies the sign-flip). Optional PR chips when current-14d best beats prior-14d best on pace or SWOLF. CSS context block when set; missing/retest prompt when CSS is absent or stale. Coach callout key: `swim_trajectory_callout`. Skipped silently for trackers without swim data. |
| Nutrition phase | `nutrition_phase.{current, targets, actuals, status, stop_signals_triggered, coach_action_hint, history}` | **Gated card — renders iff `nutrition_phase` is non-null in tracker JSON (i.e. the person has an open phase row in `<person>/data/nutrition_phases.csv`).** Trajectory tab; sits directly under Body composition so the two body-comp signals read together. Hero = phase type + weeks elapsed + observed-vs-target rate (`+0.24 kg/wk observed vs +0.25 kg/wk target`). Status word reads from `status` (on track / too fast / too slow / flat / regressing / insufficient data); color map: good / warn / amber / amber / warn / muted. Secondary rows: protein target (target-only unless intake fields exist), kcal delta, observed-rate-vs-target ratio, and consecutive rate-breach weeks. Always-shown pill carrying the binding `coach_action_hint` token (`Continue phase` / `Add calories` / `Slow intake` / `Consider ending` / `End now`). When `stop_signals_triggered` is non-empty, render them as warning pills/list rows, not a left-border alert. The user's pre-committed off-ramp text from `targets.stop_conditions` renders as a muted footer line. Coach callout key: `nutrition_phase_callout`. The coach is required to read `references/bulking-science.md` before authoring the callout when `current.phase_type == "bulk"`. |
| Week over week | `week_over_week.rows` | Trend arrows are color-inverted for RHR and wrist temp (a rising RHR is bad). Column widths set via `.wow-table` class. |

Bodyweight signal hierarchy when a nutrition phase is open: `nutrition_phase.actuals.rate_kg_per_wk_14d` drives phase status, `bodyweight_trend` is phase-scoped support and is only a rate when its `state` is `resolved`, `bodyweight_latest` is the newest reading, and `bodyweight_weekly` / week-over-week means are visual context only. `bodyweight_trend_kg_per_week` is the same rate as a bare scalar and is null whenever the state is unresolved; never present an unresolved fit as a direction.

Waist reads the same way, one column over. `waist_trend_cm_per_4w` is a BLOCK, not a scalar: it has the same `state` / `reason` / `note` fields as `bodyweight_trend`, with the rate in `cm_per_4w` and the interval in `ci95_cm_per_4w`. There is no top-level bare-scalar twin the way bodyweight has `bodyweight_trend_kg_per_week` — **but the block does not force a consumer through `state`.** `point_cm_per_4w` sits inside it at the same nesting level as `state`, needs no state check to reach, is populated whenever a fit exists at all (i.e. including every `ci_straddles_zero` case, where `cm_per_4w` is null), and survives `_compact` because it is non-null. Quoting it without reading `state` is the waist version of quoting `point_kg_per_week`, and nothing in the code prevents it; the prohibition in `SKILL.md` and `common-mistakes.md` is the only guardrail. Two differences from bodyweight, both because a tape measure is noisier than a scale and gets used far less often:

- The window floor is **56 days**, not 28, and it takes **4 measurements** inside that fixed window. At a 28-day window the 95% half-interval on a waist slope is wider than 5 cm, which is several times any real monthly change, so nothing honest resolves there.
- The window is a fixed period rather than a "last N measurements" rule, which means a monthly measuring cadence stays `too_few_readings` indefinitely. That is the intended trade: `note` asks for a weekly cadence rather than quietly widening the window to manufacture a number.

`waist_latest` is `{value_cm, date}` and, like `bodyweight_latest` and `vo2max_latest`, is absent from the JSON entirely when the column has never been filled in (`_compact` strips nulls payload-wide). `waist_trend_cm_per_4w` is always present — an unresolved state is an answer, so it never compacts away.

**Wiring note.** `card_vitals` takes `waist_latest` and `waist_trend_block` as optional keyword arguments. Without them the row still renders from the `waist_cm` series on `health_metrics_weekly`, and its State cell states a census of that series ("not measured" / "1 week logged, no trend" / "N weeks logged") rather than a rate. Passing both from `render_dashboard.py` — `card_vitals(..., bw_trend_block, j.get("waist_latest"), j.get("waist_trend_cm_per_4w"))` — is what upgrades the State cell to the reason codes above.

## Tooltip catalog

Maintained in code at [`lib/render_validators.py::KNOWN_TERMS`](../lib/render_validators.py). Adding a new abbreviation: add the entry there. Both expansion and a one-sentence plain-English explanation are required.

Currently covered: CTL, ATL, TSB, e1RM, MEV, MAV, MRV, SDNN, HRR, RHR, HRV, Z2, Z5, VO2max, HSP.

## Mobile breakpoints

- **≤ 720 px:** hero stacks 1-column; activity rings collapse to 2-column (so 5 rings render as 2+2+1, not the awkward 3+2 they did when the grid was 3-column); NEAT stats stack 1-column; training-load summary collapses to 2x2; recovery practices 1-column; per-muscle bar rows stack to two visual lines (label on top, bar + value below); sleep rows collapse to 2-column.
- **≤ 480 px:** hide the vitals sparkline column; reduce the metric-card value font.

The tab strip sticks to the top of the viewport on scroll so the user can toggle between Assessment and Workout from anywhere on the page.

## Interactivity (inline JS, no deps)

- **Tabs**: instant toggle via `display`; URL hash mirrors selection (`#assessment` / `#workout`).
- **Tooltips**: all `[data-tip]` and `.term` elements bind to mouse + touch. Floating tooltip follows the cursor.
- **Training-load chart scrubber**: vertical line + small floating panel showing date / fitness / fatigue / freshness at the hovered (or tapped) day.
- **Workout tab markdown rendering**: an inline tiny renderer parses the embedded `<script type="text/markdown">` into cards on first display. Supports headings (`#`, `##`), bullets (`-`), nested bullets (`  -`), and the `Date:` / `Recovery:` placeholder lines.

## What the renderer MUST NOT do

- Load any external resource (no `<script src>`, no `<link href="http`, no CDN, no web fonts, no `@import url(...)`, no `<img src="http`).
- Embed gamification (streaks, badges, "consistency score", points).
- Reintroduce em-dashes anywhere in machine-emitted copy. (User-authored workout markdown sub-bullets are exempt.)
- Hand-author HTML inside SKILL.md or any other file. All HTML lives in the renderer (the card templates in `lib/render_cards.py` and the asset constants in `lib/render_assets.py`).

## Maintenance Notes

`render_validators.py` validates both authored inputs: `validate_coach_reads` for dashboard callouts and `validate_workout_md` for the lean workout markdown. Keep workout rules in code, not only in prompt text. Repeated self-review caught sub-bullet drift, rationale/history notes, and off-catalog exercise names; the validator is the final guard before the plan reaches the user.

## Coach-reads example (<Person>, 2026-05-20)

```json
{
  "headline": "Recovery looks firm and HRV is well above baseline. Sleep slipped under 7 hours this week and bodyweight is drifting down faster than a hypertrophy goal can absorb. Hold loads, eat a little more, and target one earlier night.",
  "cards": {
    "recovery_drivers":   "HRV is the strongest favorable signal. Sleep depth is the one to watch. No change to programming.",
    "activity_rings":     "Zone 2 cardio is at half target. Queue one 45-minute easy walk this week. Recovery practices all behind target.",
    "training_load":      "Freshness is balanced. Train normally, no PR attempts. Hold loads on lifts where fatigue is showing.",
    "muscle_volume":      "Calves are the only muscle below the productive range. The plan adds calf work on both leg days.",
    "strength":           "Shoulder press is slipping while back, rear delts, and quads show rising session HR at constant load. The combined signal is under-recovery, not strength loss. Hold loads this week and prioritize sleep.",
    "vitals":             "Two signals to act on: sleep under 7 hours and weight dropping 0.56 kg per week. Earlier night tonight, add about 300 kcal per day if the drop is unintentional.",
    "sleep":              "Total sleep below 7 hours is the limiting factor this week. Schedule is loose. Target 22:30 lights out tonight and aim for two consecutive nights at 7.5 hours.",
    "recovery_practices": "All three practices behind target. A sauna and red-light cabin session closes two at once. Type the air temperature on outdoor cold logs."
  }
}
```

## Usage

```
python3 Skills/workout-coach/scripts/render_dashboard.py \
  --tracker /tmp/tracker.json \
  --coach plans/<Person>/2026-05-20-coach_reads.json \
  --workout-md plans/<Person>/2026-05-20-workout.md \
  --out plans/<Person>/2026-05-20-assessment.html \
  --person <Person>
```

The renderer prints one line on success and exits 0; on validation failure it prints one line per error to stderr and exits 2. The HTML is written atomically (last; the file is replaced on success, untouched on failure).
