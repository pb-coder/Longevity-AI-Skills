# workout-coach code map

Where to go when you need to change something in this skill. Modeled on
the [`ARCHITECTURE.md`](https://matklad.github.io/2021/02/06/ARCHITECTURE.md.html)
convention: a short, opinionated index that an agent can read once
before touching the code.

## Anchor doc reading order

A fresh agent or contributor should land here in this order:

1. **[`Skills/CLAUDE.md`](../CLAUDE.md)** — repo layout, per-person CSV
   schemas, shared/ module roles, conventions (flat `lib/`, sys.path
   bootstrap, person-parametric paths).
2. **[`SKILL.md`](SKILL.md)** — the `/coach` entry point. Phase 1 (data
   → tracker JSON) and Phase 2 (5-tier recovery gate that BINDS the
   workout plan).
3. **This file** (`CODE_MAP.md`) — function locator: where is X defined,
   what calls it.
4. **[`Skills/DESIGN.md`](../DESIGN.md)** — visual design system
   (tokens, pills, card chrome). Read before touching CSS or any
   rendering code.

For known issues / planned cleanup, see
[`references/code-health-audit.md`](references/code-health-audit.md).

## When you need to change...

| Goal | Edit |
| --- | --- |
| A card's HTML layout / structure | [`lib/render_cards.py`](lib/render_cards.py) |
| CSS / styling / colors | [`lib/render_assets.py`](lib/render_assets.py) (the `STYLESHEET` string) |
| Inline JavaScript (tabs, tooltips, chart scrubber, markdown viewer) | [`lib/render_assets.py`](lib/render_assets.py) (the `INLINE_JS` string) |
| An SVG component (training-load chart, sparkline, muscle bar, freshness / recovery scale, ring, driver bar) | [`lib/render_components.py`](lib/render_components.py) |
| Coach-text validation rules / em-dash check / length cap | [`lib/render_validators.py`](lib/render_validators.py)::`validate_coach_reads` |
| Add a tooltip for a new abbreviation in coach text | [`lib/render_validators.py`](lib/render_validators.py)::`KNOWN_TERMS` |
| Tracker JSON shape (what fields the renderer reads) | [`scripts/read_tracker.py`](scripts/read_tracker.py) + the relevant `lib/*.py` analytics module |
| Recovery score formula / drivers | [`lib/health.py`](lib/health.py)::`recovery_score` |
| **5-tier session recommendation (Phase 2 binding gate)** | [`lib/health.py`](lib/health.py)::`compute_session_recommendation` |
| 14-day tier history (the decision-history strip) | [`lib/health.py`](lib/health.py)::`compute_tier_history` |
| Longevity composite score (10-component weighted) | [`lib/health.py`](lib/health.py)::`compute_longevity_score` |
| VO2max age/sex percentile | [`lib/health.py`](lib/health.py)::`vo2_percentile_age_sex` |
| Longevity state I/O (DOB, conditions, meds, risk flags) | [`lib/health.py`](lib/health.py)::`read_longevity_state` |
| Per-muscle volume math (MEV / MAV / MRV thresholds, weekly tally) | [`lib/constants.py`](lib/constants.py) + [`lib/strength.py`](lib/strength.py) |
| CTL / ATL / TSB / TRIMP math | [`lib/cardio.py`](lib/cardio.py) |
| Sleep aggregation (efficiency, fragmentation, schedule, outliers) | [`lib/sleep.py`](lib/sleep.py) |
| Swim summary | [`lib/swim.py`](lib/swim.py) |
| Sauna + cold-exposure summary | [`lib/thermal.py`](lib/thermal.py) |
| Light-therapy summary | [`lib/light_therapy.py`](lib/light_therapy.py) |
| Per-muscle HR creep / strength session HR / e1RM slope | [`lib/strength.py`](lib/strength.py) |
| Apple Health import semantics | [`../shared/import_apple_health.py`](../shared/import_apple_health.py) (Apple XML) or [`../shared/import_health_auto_export.py`](../shared/import_health_auto_export.py) (HealthAutoExport) |
| Dashboard spec / card contracts | [`references/assessment-dashboard.md`](references/assessment-dashboard.md) |
| Visual design system — colours, typography, pills, card chrome | [`Skills/DESIGN.md`](../DESIGN.md) |
| Coach behavioral rules (Phase 2 planning) | [`SKILL.md`](SKILL.md) |
| Tier A/B/C/D/E substitute templates | [`references/substitute-protocols.md`](references/substitute-protocols.md) |
| Physiology references / person profiles | [`references/training-science.md`](references/training-science.md) |

## Layout

```
Skills/workout-coach/
├── SKILL.md                              skill entry point (Phase 1 + Phase 2)
├── CODE_MAP.md                           this file
├── references/
│   ├── assessment-dashboard.md           dashboard contracts: card spec, coach-reads schema, copy rules
│   ├── training-science.md               physiology references the coach can cite + person profiles
│   ├── substitute-protocols.md           Tier A–E substitute templates (rest / Z2 / deload / modified / normal)
│   ├── swim-coaching.md                  CSS-zone interpretation, SWOLF/SPL guardrails
│   └── code-health-audit.md              snapshot of issues + improvement backlog
├── scripts/
│   ├── read_tracker.py (700 lines)       CLI: reads CSV store, emits compact tracker JSON
│   └── render_dashboard.py (256 lines)   CLI: composes the final HTML (thin orchestrator)
└── lib/
    │
    ├── # ---- Analytics modules (consumed by read_tracker.py) ----
    ├── constants.py (463)                capabilities, landmarks, aliases, MEV/MAV/MRV
    ├── parsing.py (108)                  date + number coercions, _compact
    ├── extract.py (550)                  CSV readers + exercises-database parser
    ├── sessions.py (267)                 per-session aggregation + bodyweight trend
    ├── strength.py (512)                 volume, e1RM, HR-at-volume divergence
    ├── cardio.py (609)                   cardio rollups, HR zones, TRIMP, CTL/ATL/TSB, NEAT
    ├── health.py (1349)                  windowing, recovery_score, longevity_score, session_recommendation, tier_history, longevity_state I/O
    ├── sleep.py (422)                    sleep_summary (stages, schedule, fragmentation, outliers)
    ├── swim.py (347)                     swim_summary (pace, SPL, SWOLF, CSS zones)
    ├── thermal.py (336)                  thermal_summary (sauna + cold)
    ├── light_therapy.py (164)            light_therapy_summary (RLT / PBM / blue light)
    │
    └── # ---- Renderer modules (consumed by render_dashboard.py) ----
    ├── render_helpers.py (50)            esc, fmt, signed, parse_date — zero-dep helpers
    ├── render_validators.py (186)        KNOWN_TERMS catalog, validate_coach_reads, auto_wrap_terms
    ├── render_components.py (752)        SVG / HTML components (chart, rings, bars, scales, sparkline)
    ├── render_assets.py (998)            STYLESHEET (CSS) + INLINE_JS strings
    └── render_cards.py (1551)            card_* HTML templates + coach_block
```

> Line counts are accurate as of 2026-05-24. They will drift; re-check
> with `wc -l workout-coach/lib/*.py workout-coach/scripts/*.py` when
> something looks off.

## Analytics module index (`lib/<domain>.py`)

### [`lib/health.py`](lib/health.py) (~1349 lines)

The biggest analytics module. Five logical sections — split is on the
backlog (see `references/code-health-audit.md` #10):

1. **Windowing / aggregation** (lines 34–130) — `_values_in_window`,
   `_mean_or_none`, `metric_trend_per_4w`, `latest_metric`,
   `baseline_60d`, `workout_sessions_in_window`,
   `health_metrics_weekly`.
2. **Recovery scoring** (lines 183–395) — `_z_score_signal`,
   `recovery_score` (composes ~9 drivers with per-signal sample-
   sufficiency gate; confidence drops one band when a high-weight
   z-scored driver has too few recent readings).
3. **Longevity scoring** (lines 396–699) — `vo2_percentile_age_sex`,
   `_safe_norm`, `compute_longevity_score` (10-component weighted
   average; accepts optional `capabilities` to suppress source-
   unavailable inputs).
4. **Session recommendation (5-tier gate, the Phase 2 mandate)** (lines
   700–1162) — internal helpers `_muscles_over_mrv`,
   `_rhr_sustained_elevation_days`, `_wrist_temp_deviation_c`, `_z_for`,
   `_count_stalled_lifts`, `_tsb_sustained_days`; then
   `compute_session_recommendation` (returns tier A/B/C/D/E + headline
   + rationale) and `compute_tier_history` (rolls the recommendation
   over a 14-day window for the decision-history strip).
5. **Longevity state I/O** (lines 1163–1349) — `read_longevity_state`
   loads `<Person>/data/longevity/state.md` (DOB, conditions, meds,
   risk flags). Called from `read_tracker.py`.

### Other analytics modules

- [`lib/cardio.py`](lib/cardio.py) (~609) — cardio rollups, HR zones
  (HRR/Karvonen), TRIMP, CTL/ATL/TSB rolling EWMA, daily-activity
  (NEAT), `auto_deload_candidates`, per-session `hr_zone_label`.
- [`lib/strength.py`](lib/strength.py) (~512) — volume, e1RM
  (context-change aware), stale exercises, HR-at-volume divergence,
  strength-session HR trend.
- [`lib/sleep.py`](lib/sleep.py) (~422) — sleep stage aggregation,
  efficiency, fragmentation, schedule regularity, REM anomaly watch.
- [`lib/extract.py`](lib/extract.py) (~550) — CSV readers (monthly +
  dense + swim), exercises-DB parser, age + max-HR helpers.
- [`lib/swim.py`](lib/swim.py) (~347) — swim_summary (pace, SPL,
  SWOLF, CSS zones, stroke-mix outliers, CSS retest prompt).
- [`lib/thermal.py`](lib/thermal.py) (~336) — sauna + cold dose vs.
  HSP-induction threshold, paired protocol detection.
- [`lib/sessions.py`](lib/sessions.py) (~267) —
  `build_monthly_sessions`, bodyweight trend, `progression_summary`.
- [`lib/constants.py`](lib/constants.py) (~463) — capabilities matrix,
  landmarks (MEV/MAV/MRV per muscle), aliases,
  `SESSION_GATE_THRESHOLDS`.
- [`lib/light_therapy.py`](lib/light_therapy.py) (~164) —
  light_therapy_summary (frequency + per-session dose).
- [`lib/parsing.py`](lib/parsing.py) (~108) — coercions, `_parse_iso_date`,
  `_compact` (strips null leaves from output JSON for token efficiency).

## Renderer module index (`lib/render_*.py`)

### [`lib/render_helpers.py`](lib/render_helpers.py) (~50 lines)

The tiniest formatters. Zero dependencies; every other `render_*` module
imports from here. Keep it that way to avoid circular imports.

Functions: `esc(s)`, `fmt(v, digits, default)`, `signed(v, digits,
default)`, `parse_date(s)`.

### [`lib/render_validators.py`](lib/render_validators.py) (~186 lines)

Coach-text schema validation and the tooltip-term catalog.

Constants: `KNOWN_TERMS` (abbreviation → tooltip), `COACH_CARD_KEYS`,
`EM_DASH`, `COACH_STRING_MAX`.

Functions: `validate_coach_reads(coach) -> (errors, warnings)`,
`auto_wrap_terms(text)`.

### [`lib/render_components.py`](lib/render_components.py) (~752 lines)

SVG and HTML components used by the cards. Each function returns a
complete fragment. Grouped by purpose:

- **Training-load chart**: `build_load_series` (CTL/ATL/TSB EWMA over
  N days, with pre-window seeding) + `load_chart_svg` (interactive line
  chart with hover scrubber).
- **Activity rings**: `ring(actual, target, label, sub)`.
- **Recovery drivers**: `metric_label`, `metric_tip`, `driver_bars`
  (diverging horizontal bars; filters out penalty-only `z=None`
  signals).
- **Per-muscle volume**: `muscle_bars(weekly_volume)` (4-band stack
  with MEV / MAV tick marks).
- **Hero scales**: `freshness_scale(tsb)` (−15..+15 strip),
  `recovery_scale(score)` (0..10 strip). Both share viewBox + band-
  label conventions so the two hero cards look like siblings.
- **Tier strip**: `tier_history_strip(history)` — 14-day decision
  history (one square per day, coloured by tier).
- **Small indicators**: `confidence_dots(conf)`, `sparkline(values,
  status_class)`, `embed_workout_markdown(md_text)`.

### [`lib/render_assets.py`](lib/render_assets.py) (~998 lines)

Two module-level string constants — pure data, no functions.

**Implements the design system documented in
[`Skills/DESIGN.md`](../DESIGN.md).** Read that first before touching
CSS — token values (colours, typography, spacing) come from its YAML
front matter and must be referenced via CSS variables here. **No raw
hex literals outside the `:root` block** (lint: `rg
"#[0-9a-fA-F]{3,6}" lib/` should only hit `:root`).

- `STYLESHEET` — the full inline CSS. Owns colors (CSS custom
  properties at the top, mapping `Skills/DESIGN.md` tokens), card
  chrome, every visual component's layout, tooltip styling, mobile
  breakpoints.
- `INLINE_JS` — inline JavaScript embedded at the bottom of the HTML.
  Tab switching with URL hash mirroring, hover tooltip positioning,
  interactive training-load chart scrubber + tooltip, tiny markdown
  renderer for the Workout tab.

### [`lib/render_cards.py`](lib/render_cards.py) (~1551 lines)

HTML templates for every card. Each `card_*` returns a complete
`<section>`. Pure presentation — no I/O, no analytics.

Render order (matches `scripts/render_dashboard.py::render()`):

**Today tab** (10 cards):
1. `card_session_call(rec, coach_text, summary_text)` — the Phase 2
   5-tier gate call-out at the top. Quotes `headline` + top-3
   `rationale` from `compute_session_recommendation`. Tier-coloured
   accent pill.
2. `card_hero(score, score_cls, confidence, tsb, tsb_cls, tsb_label,
   ctl, atl, tsb_trend)` — Recovery + Freshness, each with a scale
   strip.
3. `card_drivers(drivers, coach_text)` — Recovery drivers diverging-bar
   chart.
4. `card_acwr(acwr, coach_text)` — Training-load progression (week-
   over-week TRIMP change + ACWR with Gabbett caveat).
5. `card_rings(rings_html, coach_text)` — Activity rings.
6. `card_neat(daily_activity)` — NEAT card: avg exercise min/day,
   walking distance, incidental walks.
7. `card_training_load(series, ctl, atl, tsb, tsb_trend, coach_text)`
   — 90-day chart + 4-up summary cells.
8. `card_muscle_volume(weekly_volume, coach_text, hr_divergence=None)`
   — Per-muscle bars with HR-at-volume annotation chips.
9. `card_strength(items, coach_text)` — Strength progression table.
10. `card_wow(wow)` — Week over week.

**Trajectory tab** (12 cards):
1. `card_longevity_score(longevity_score, coach_text)` — composite
   score + per-component bars.
2. `card_cardio_domain(vo2_percentile, hr_recovery, recovery,
   cardio_zones, vo2max, vo2_trend, coach_text)`.
3. `card_recovery_domain(recovery, weekly, coach_text)`.
4. `card_sleep_domain(sleep, sleep_regularity, rem_anomaly, coach_text,
   longevity_state=...)` — gates Parkinson REM-watch copy on
   `_has_risk_flag`.
5. `card_body_comp_domain(bw, bw_trend, longevity_state, coach_text)`
   — gates PrEP BMD prompt on `_has_risk_flag`.
6. `card_metabolic_domain(longevity_state, coach_text)` — bloodwork
   consolidated here.
7. `card_behavioral_domain(movement_consistency, sleep_regularity,
   acwr, cardio_zones, coach_text)`.
8. `card_vitals(weekly, vo2max, vo2_trend, bw, bw_trend, bw_weekly,
   coach_text)` — HRV / RHR / wrist temp / VO2max / bodyweight
   sparklines.
9. `card_sleep(sleep, coach_text)` — stage stack + diagnostic rows +
   outliers.
10. `card_recovery_practices(thermal, light, coach_text)` — sauna /
    cold / light sub-cards.
11. `card_risk_flags(longevity_state, coach_text)`.
12. `card_tier_history_strip(history, coach_text=None)` — 14-day
    decision history strip.

Shared:
- `coach_block(text)` — wraps a coach string in the standard
  `<aside class="coach">` callout, or empty if `text` is `None`/blank.
- `_heading(label, key)` — section heading with tooltip-key wiring.
- `_has_risk_flag(longevity_state, key)` — risk-flag gate for PII copy
  (Parkinson, PrEP). Currently card-internal; on the backlog to move
  to a shared helper.

## Pipeline at a glance

```
            ┌───────────────────────────────────────────────────┐
            │ <Person>/data/ (CSVs)                             │
            │   monthly/YYYY.MM.csv, health_metrics.csv,        │
            │   workout_sessions.csv, sleep/, swimming/,        │
            │   thermal/, light_therapy/, longevity/            │
            └───────────────────────────────────────────────────┘
                                 │ read by
                                 ▼
            ┌───────────────────────────────────────────────────┐
            │ scripts/read_tracker.py                           │
            │   imports from lib/*.py analytics modules         │
            │   emits compact JSON to stdout                    │
            │   (includes session_recommendation +              │
            │    tier_history + longevity_score)                │
            └───────────────────────────────────────────────────┘
                                 │ tracker.json
                                 ▼
            ┌───────────────────────────────────────────────────┐
            │ Coach LLM (you, when /coach runs)                 │
            │   reads SKILL.md Phase 2, the tracker JSON, and   │
            │   references/assessment-dashboard.md; must HONOR  │
            │   the 5-tier gate's headline + rationale in the   │
            │   workout markdown opening (Phase 2 binding       │
            │   mandate); writes coach_reads.json and           │
            │   <date>-workout.md                               │
            └───────────────────────────────────────────────────┘
                                 │
                                 ▼
            ┌───────────────────────────────────────────────────┐
            │ scripts/render_dashboard.py                       │
            │   imports from lib/render_*.py                    │
            │   validates coach_reads.json                      │
            │   composes plans/<Person>/<date>-assessment.html  │
            └───────────────────────────────────────────────────┘
```

## Conventions

- All `lib/*.py` modules are **flat top-level** scripts. Each module
  starts with a docstring + `from __future__ import annotations` +
  a sys.path bootstrap that adds the sibling `lib/` dir so the module
  can be imported in isolation (REPL, ad-hoc tests). See
  [`../CLAUDE.md`](../CLAUDE.md) for the full convention.
- Renderer modules **do not** import from analytics modules and vice
  versa. The interface between them is the tracker JSON shape (see
  `read_tracker.py`'s `out` dict assembly). Adding a typed contract for
  this is on the backlog (`references/code-health-audit.md` #6).
- No external HTTP / CDN / web font dependencies in the dashboard.
  Verify with `grep -E '<script src|<link href="http|@import url'` on
  the rendered HTML — must be zero matches.
- New abbreviations in coach text: register in `KNOWN_TERMS`. Update
  the `references/assessment-dashboard.md` tooltip-catalog list to
  match.
- **Phase 2 is binding**: when `compute_session_recommendation` returns
  tier A or B, the coach MUST quote its `headline` and top-3
  `rationale` in the workout-markdown opening, and the planned session
  must match a substitute from `references/substitute-protocols.md`.
  See `SKILL.md` Phase 2.

## Quick how-to recipes

**Add a new card.**
1. Implement `card_yournew(data, coach_text)` in
   [`lib/render_cards.py`](lib/render_cards.py).
2. Add CSS for any new classes in `STYLESHEET` in
   [`lib/render_assets.py`](lib/render_assets.py). Reference CSS
   variables, not raw hex.
3. Wire the call into
   [`scripts/render_dashboard.py`](scripts/render_dashboard.py)::`render()`
   in the desired position.
4. Add an entry to the Coach-reads schema in
   [`references/assessment-dashboard.md`](references/assessment-dashboard.md)
   if the card has a coach callout.
5. Add a `card_*` line to `COACH_CARD_KEYS` in
   [`lib/render_validators.py`](lib/render_validators.py) so a missing
   callout warns.

**Change a card's layout.**
- HTML / structure: [`lib/render_cards.py`](lib/render_cards.py).
- CSS: [`lib/render_assets.py`](lib/render_assets.py).
- New SVG glyph or chart: add a function to
  [`lib/render_components.py`](lib/render_components.py) and call it
  from the card.

**Change the recovery score formula.**
- Drivers and weights: [`lib/health.py`](lib/health.py)::`recovery_score`.
- Per-signal z-score normalization: `_z_score_signal` in the same file.
- Sample-sufficiency thresholds: `SESSION_GATE_THRESHOLDS` in
  [`lib/constants.py`](lib/constants.py).

**Change the 5-tier session-recommendation gate.**
- Driver list, thresholds, tier-down logic:
  [`lib/health.py`](lib/health.py)::`compute_session_recommendation`.
- Per-tier substitute templates the coach renders:
  [`references/substitute-protocols.md`](references/substitute-protocols.md).
- Phase 2 binding-mandate copy: [`SKILL.md`](SKILL.md) (Phase 2 section).

**Verify a renderer change.** Render before + after, diff the HTML,
ignoring the footer's `generated at` timestamp (it uses
`datetime.now()`, so it'll always differ across runs):

```bash
diff <(grep -v 'generated at' before.html) <(grep -v 'generated at' after.html)
```

Backlog item: snapshot tests (`tests/test_render_dashboard_snapshot.py`)
will automate this against the existing `tests/fixtures/Nihad/` and
`tests/fixtures/Fabian/` trees. See `references/code-health-audit.md` #8.
