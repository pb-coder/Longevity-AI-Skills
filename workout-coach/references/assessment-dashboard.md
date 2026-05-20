# Assessment dashboard — renderer spec & coach-reads contract

The dashboard is produced by **`Skills/workout-coach/scripts/render_dashboard.py`**. The script owns all HTML, CSS, SVG, JavaScript, and layout. The coach LLM authors two inputs:

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
│   ├── hero                        Recovery score (confidence dots), Freshness
│   ├── recovery drivers            diverging-bar chart (z=null drivers filtered out)
│   ├── activity rings + NEAT       5 rings (strength / cardio sessions / Z2 / recovery / sleep) plus a compact NEAT strip below: avg exercise min/day, walking km over 28d, incidental walk count
│   ├── training load (90d)         interactive chart; tracker.json must come from --months 6
│   ├── per-muscle volume           bars + MEV/MAV ticks, 4 distinct band colors, dots on labels
│   ├── strength progression        e1RM table with confidence dots
│   ├── health vitals               HRV, RHR, wrist temp, VO2max, bodyweight (sleep is NOT here)
│   ├── sleep (NEW)                 stage stack, schedule, efficiency, fragmentation,
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
    "recovery_drivers":     "one sentence ...",
    "activity_rings":       "one sentence ...",
    "training_load":        "one sentence ...",
    "muscle_volume":        "one sentence ...",
    "strength":             "one sentence ...",
    "vitals":               "one to two sentences, signal + action ...",
    "recovery_practices":   "one sentence ..."
  }
}
```

All keys under `cards` are optional. If a key is missing or empty, the card renders without a coach callout — pure data.

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
| Hero · Recovery | `recovery.score`, `recovery.confidence` | Status class by score band: ≥6.5 good, 4.5-6.5 amber, <4.5 warn |
| Hero · Freshness | `training_load.{ctl, atl, tsb, trend_7d}` | Big signed number + a horizontal `freshness_scale` strip showing where the value sits on a -15..+15 axis. Six band labels under the axis match the SKILL.md Phase-2 gate table: high fatigue (≤-15), fatigued (-15..-10), carrying load (-10..-5), balanced (-5..+5), fresh (+5..+10), well rested (>+10). Marker color: good (-5..+10), amber (the two outer non-extreme bands), warn (≤-10). |
| Recovery drivers | `recovery.drivers[*]` | Diverging horizontal bar chart, sorted by \|z\| desc, capped at 8 rows. **Penalty-only drivers (those with `z=None`) are filtered out** — they are "no-penalty" placeholders, not signals of movement. Positive z = green (favorable; the metric module already sign-flips RHR/wrist temp). |
| Activity rings | `week_over_week.rows` (strength count), `cardio_hr_zones_28d.z2`, `thermal_summary` + `light_therapy_summary` (recovery sessions), `health_metrics_weekly` (sleep avg) | Targets: 4 strength sess, 150 min Z2, 4 recovery sess, 7 h sleep. Ring color: good when ≥ target, amber otherwise. Never red. |
| Activity rings · NEAT strip | `daily_activity_28d.{exercise_min_daily_avg, walking_distance_km_28d, incidental_walks_count, assessment}` | Compact three-cell strip below the rings. Color dot on the first cell keys off `assessment` (`high` → good, `moderate` → amber, `low` → warn). "NEAT" label carries a tooltip with the definition. Lives in the same card as the rings; no separate coach callout. |
| Training load (90d) | computed locally from `monthly_sessions[*].trimp` via 42-day / 7-day EWMA, seeded from sessions older than the window | Interactive: mouse / touch reveals scrubber + values at the hovered day. |
| Per-muscle volume | `weekly_volume_per_muscle.current` and `.landmarks` | Four-color palette: `not enough` (orange, below MEV), `productive` (green, MEV..MAV), `pushing limit` (yellow, MAV..MRV), `too much, cut back` (red, above MRV). Thin tick marks at MEV and MAV on each track; **no background band** (caused the 3-color confusion in v3). Bar-status labels start with a small colored dot so labels align regardless of icon width. |
| Sleep (NEW) | `sleep_summary.{means_h, sleep_efficiency_pct, fragmentation, schedule_consistency, resp_rate, breath_disturbances, outliers}` | Dedicated card after Health vitals. Hero shows average total + Time in Bed proxy. Stack chart breaks down Core / Deep / REM / Awake. Six diagnostic rows (Deep+REM, efficiency, fragmentation, schedule, respiratory rate, breathing disturbances) each with a status word + colored dot. Sleep stays out of the Health vitals card to avoid duplication. Newer iOS doesn't emit explicit `InBed` segments, so the importer + `Skills/shared/backfill_sleep_efficiency.py` derive Time in Bed from the first-to-last segment span. |
| Strength progression | `estimated_1rm[*]` filtered to entries with non-null `slope_kg_per_4w` + `current_e1rm_kg`, sorted by \|slope\|, capped at 8 | Arrow class: good (slope ≥ +0.5), warn (≤ -0.5), muted otherwise. e1RM and slope column headers have tooltips. |
| Health vitals | `health_metrics_weekly` (HRV / RHR / wrist temp / sleep / deep / REM / VO2max series), `vo2max_latest`, `vo2max_trend_per_4w`, `bodyweight_latest`, `bodyweight_trend_kg_per_week` | One clean table, no inline coach rows. Sparklines colored by per-row status. Sparkline column hides at ≤ 480 px. |
| Recovery practices | `thermal_summary.heat`, `thermal_summary.cold`, `thermal_summary.cold.recent_sessions`, `thermal_summary.adherence`, `light_therapy_summary` | Three sub-cards, identical layout. Cold sub-card lists recent sessions with their temperature (the `dose_hint: "amber"` flag for cold_air ≥ 18 °C tags weak doses). |
| Week over week | `week_over_week.rows` | Trend arrows are color-inverted for RHR and wrist temp (a rising RHR is bad). |

## Tooltip catalog

Maintained in code at `Skills/workout-coach/scripts/render_dashboard.py::KNOWN_TERMS`. Adding a new abbreviation: add the entry there. Both expansion and a one-sentence plain-English explanation are required.

Currently covered: CTL, ATL, TSB, e1RM, MEV, MAV, MRV, SDNN, HRR, RHR, HRV, Z2, Z5, VO2max, HSP.

## Mobile breakpoints

- **≤ 720 px:** hero stacks 1-column; activity rings 2-column; recovery practices 1-column; per-muscle bar rows stack to two visual lines (label on top, bar + value below).
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
- Hand-author HTML inside SKILL.md or any other file. All HTML lives in the renderer.

## Coach-reads example (Nihad, 2026-05-20)

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
    "recovery_practices": "All three practices behind target. A sauna and red-light cabin session closes two at once. Type the air temperature on outdoor cold logs."
  }
}
```

## Usage

```
python3 Skills/workout-coach/scripts/render_dashboard.py \
  --tracker /tmp/tracker.json \
  --coach plans/Nihad/2026-05-20-coach_reads.json \
  --workout-md plans/Nihad/2026-05-20-workout.md \
  --out plans/Nihad/2026-05-20-assessment.html \
  --person Nihad
```

The renderer prints one line on success and exits 0; on validation failure it prints one line per error to stderr and exits 2. The HTML is written atomically (last; the file is replaced on success, untouched on failure).
