# workout-coach code map

Where to go when you need to change something in this skill. Modeled on
the [`ARCHITECTURE.md`](https://matklad.github.io/2021/02/06/ARCHITECTURE.md.html)
convention: a short, opinionated index that an agent can read once
before touching the code.

## Anchor doc reading order

A fresh agent or contributor should land here in this order:

1. **[`Skills/CLAUDE.md`](../CLAUDE.md)** — repo layout, per-person CSV
   schemas, package import conventions, and person-parametric paths.
2. **[`SKILL.md`](SKILL.md)** — the `/coach` entry point. Phase 1 (data
   → tracker JSON) and Phase 2 (5-tier recovery gate that BINDS the
   workout plan).
3. **This file** (`CODE_MAP.md`) — function locator: where is X defined,
   what calls it.
4. **[`Skills/DESIGN.md`](../DESIGN.md)** — visual design system
   (tokens, pills, card chrome). Read before touching CSS or any
   rendering code.

Cross-skill primitives live in [`../tracker/`](../tracker/): command
context, CSV table mechanics, typed command contracts, and benchmark
helpers. Do not copy those concerns into `workout-coach/lib/`.

CSV stores live in [`../shared/`](../shared/): `csv_store.py` is only the
compatibility facade; use `csv_store_profile.py`, `csv_store_dense.py`,
`csv_store_periodic.py`, and `csv_store_common.py` when changing storage
behavior.

Monthly workout CSV behavior is also split under [`../shared/`](../shared/):
`monthly_csv.py` is the compatibility facade; use
`monthly_csv_schema.py`, `monthly_csv_values.py`, `monthly_csv_io.py`,
`monthly_csv_canonicalize.py`, and `monthly_csv_upsert.py` for real
changes.

For known issues / planned cleanup, see
[`references/code-health-audit.md`](references/code-health-audit.md).

## When you need to change...

| Goal | Edit |
| --- | --- |
| Today-tab card HTML | [`lib/render_cards_today.py`](lib/render_cards_today.py) |
| Trajectory health/recovery cards | [`lib/render_cards_health.py`](lib/render_cards_health.py) |
| Trajectory longevity-domain cards | [`lib/render_cards_domains.py`](lib/render_cards_domains.py) |
| Trajectory risk/swim/nutrition cards | [`lib/render_cards_programs.py`](lib/render_cards_programs.py) |
| CSS / styling / colors | [`lib/render_styles.py`](lib/render_styles.py) (the `STYLESHEET` string) |
| Inline JavaScript (tabs, tooltips, chart scrubber, markdown viewer) | [`lib/render_scripts.py`](lib/render_scripts.py) (the `INLINE_JS` string) |
| Training-load chart components | [`lib/render_components_load.py`](lib/render_components_load.py) |
| Recovery scales / driver bars / sparklines | [`lib/render_components_recovery.py`](lib/render_components_recovery.py) |
| Per-muscle volume bars | [`lib/render_components_volume.py`](lib/render_components_volume.py) |
| Trajectory-domain gauges and strips | [`lib/render_components_domain.py`](lib/render_components_domain.py) |
| Coach-text validation rules / em-dash check / length cap | [`lib/render_validators.py`](lib/render_validators.py)::`validate_coach_reads` |
| Add a tooltip for a new abbreviation in coach text | [`lib/render_validators.py`](lib/render_validators.py)::`KNOWN_TERMS` |
| Tracker JSON shape (what fields the renderer reads) | [`../tracker/contracts.py`](../tracker/contracts.py)::`TrackerJSON` + [`scripts/read_tracker.py`](scripts/read_tracker.py) |
| Coach reads JSON shape | [`../tracker/contracts.py`](../tracker/contracts.py)::`CoachReads` + [`lib/render_validators.py`](lib/render_validators.py) |
| Recovery score formula / drivers | [`lib/health_recovery.py`](lib/health_recovery.py)::`recovery_score` |
| **5-tier session recommendation (Phase 2 binding gate)** | [`lib/health_session_rec.py`](lib/health_session_rec.py)::`compute_session_recommendation` |
| 14-day tier history (the decision-history strip) | [`lib/health_session_rec.py`](lib/health_session_rec.py)::`compute_tier_history` |
| Longevity composite score (10-component weighted) | [`lib/health_longevity.py`](lib/health_longevity.py)::`compute_longevity_score` |
| VO2max age/sex percentile | [`lib/health_longevity.py`](lib/health_longevity.py)::`vo2_percentile_age_sex` |
| Longevity state I/O (DOB, conditions, meds, risk flags) | [`lib/health_longevity.py`](lib/health_longevity.py)::`read_longevity_state` |
| Per-muscle volume math (MEV / MAV / MRV thresholds, weekly tally) | [`lib/constants.py`](lib/constants.py) + [`lib/strength.py`](lib/strength.py) |
| CTL / ATL / TSB / TRIMP math | [`lib/cardio.py`](lib/cardio.py) |
| Sleep aggregation (efficiency, fragmentation, schedule, outliers) | [`lib/sleep.py`](lib/sleep.py) |
| Swim summary | [`lib/swim.py`](lib/swim.py) |
| Sauna + cold-exposure summary | [`lib/thermal.py`](lib/thermal.py) |
| Light-therapy summary | [`lib/light_therapy.py`](lib/light_therapy.py) |
| Per-muscle HR creep / strength session HR / e1RM slope | [`lib/strength.py`](lib/strength.py) |
| CSV store schemas and upserts | [`../shared/csv_store_dense.py`](../shared/csv_store_dense.py) and [`../shared/csv_store_periodic.py`](../shared/csv_store_periodic.py) |
| Monthly workout CSV canonicalization/upserts | [`../shared/monthly_csv_canonicalize.py`](../shared/monthly_csv_canonicalize.py) and [`../shared/monthly_csv_upsert.py`](../shared/monthly_csv_upsert.py) |
| Apple XML daily/sleep aggregation | [`../shared/apple_health_daily.py`](../shared/apple_health_daily.py) |
| Apple XML strength/swim helper payloads | [`../shared/apple_health_strength.py`](../shared/apple_health_strength.py) and [`../shared/apple_health_swim.py`](../shared/apple_health_swim.py) |
| Apple Health import orchestration | [`../shared/import_apple_health.py`](../shared/import_apple_health.py) (Apple XML) or [`../shared/import_health_auto_export.py`](../shared/import_health_auto_export.py) (HealthAutoExport) |
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
    ├── health.py (77)                    compatibility facade for focused health modules
    ├── health_windowing.py (162)         time-series primitives + weekly aggregates
    ├── health_recovery.py (220)          recovery_score + recovery drivers
    ├── health_longevity.py (497)         longevity_score + longevity_state I/O
    ├── health_session_rec.py (472)       5-tier gate + 14-day tier history
    ├── sleep.py (422)                    sleep_summary (stages, schedule, fragmentation, outliers)
    ├── swim.py (347)                     swim_summary (pace, SPL, SWOLF, CSS zones)
    ├── thermal.py (336)                  thermal_summary (sauna + cold)
    ├── light_therapy.py (164)            light_therapy_summary (RLT / PBM / blue light)
    │
    └── # ---- Renderer modules (consumed by render_dashboard.py) ----
    ├── render_helpers.py (50)            esc, fmt, signed, parse_date — zero-dep helpers
    ├── render_validators.py (186)        KNOWN_TERMS catalog, validate_coach_reads, auto_wrap_terms
    ├── render_components.py (23)         compatibility facade for component modules
    ├── render_components_load.py (135)   training-load chart + EWMA series
    ├── render_components_recovery.py (258)
    │                                      driver bars, scales, sparklines, metric rows
    ├── render_components_volume.py (109) per-muscle volume bars
    ├── render_components_domain.py (192) comparison strips, dials, tier history
    ├── render_components_misc.py (40)    rings + workout markdown embed
    ├── render_assets.py (11)             compatibility facade for dashboard assets
    ├── render_styles.py (731)            STYLESHEET string
    ├── render_scripts.py (256)           INLINE_JS string
    ├── render_cards.py (76)              compatibility facade for card modules
    ├── render_cards_common.py (39)       shared heading + coach callout helpers
    ├── render_cards_today.py (472)       Today tab card templates
    ├── render_cards_health.py (442)      health / sleep / recovery-practice cards
    ├── render_cards_domains.py (581)     longevity-domain cards
    └── render_cards_programs.py (371)    risk / swim / nutrition cards
```

> Line counts are accurate as of 2026-05-28. They will drift; re-check
> with `wc -l workout-coach/lib/*.py workout-coach/scripts/*.py` when
> something looks off.

## Analytics module index (`lib/<domain>.py`)

### Health analytics split

`lib/health.py` is now a compatibility facade only. Existing imports keep
working; new changes should go to the focused module:

- [`lib/health_windowing.py`](lib/health_windowing.py) — `_values_in_window`,
  `_mean_or_none`, `metric_trend_per_4w`, `latest_metric`,
  `baseline_60d`, `workout_sessions_in_window`, `health_metrics_weekly`.
- [`lib/health_recovery.py`](lib/health_recovery.py) — `_z_score_signal`,
  `recovery_score` and recovery-driver confidence logic.
- [`lib/health_longevity.py`](lib/health_longevity.py) —
  `vo2_percentile_age_sex`, `_safe_norm`, `compute_longevity_score`,
  `read_longevity_state`.
- [`lib/health_session_rec.py`](lib/health_session_rec.py) —
  `compute_session_recommendation`, `compute_tier_history`, and the
  private helper gates behind Tier A/B/C/D/E decisions.

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

### Dashboard Components

SVG and HTML components used by the cards. Each function returns a
complete fragment. `lib/render_components.py` is a compatibility facade;
real component code is grouped by purpose:

- **Training-load chart** (`render_components_load.py`): `build_load_series` (CTL/ATL/TSB EWMA over
  N days, with pre-window seeding) + `load_chart_svg` (interactive line
  chart with hover scrubber).
- **Activity rings** (`render_components_misc.py`): `ring(actual, target, label, sub)`.
- **Recovery drivers** (`render_components_recovery.py`): `metric_label`, `metric_tip`, `driver_bars`
  (diverging horizontal bars; filters out penalty-only `z=None`
  signals).
- **Per-muscle volume** (`render_components_volume.py`): `muscle_bars(weekly_volume)` (4-band stack
  with MEV / MAV tick marks).
- **Hero scales** (`render_components_recovery.py`): `freshness_scale(tsb)` (−15..+15 strip),
  `recovery_scale(score)` (0..10 strip). Both share viewBox + band-
  label conventions so the two hero cards look like siblings.
- **Tier strip** (`render_components_domain.py`): `tier_history_strip(history)` — 14-day decision
  history (one square per day, coloured by tier).
- **Small indicators** (`render_components_recovery.py` / `render_components_misc.py`): `confidence_dots(conf)`, `sparkline(values,
  status_class)`, `embed_workout_markdown(md_text)`.

### Dashboard assets

Two module-level string constants — pure data, no functions — split by
asset type. [`lib/render_assets.py`](lib/render_assets.py) remains a
compatibility facade that re-exports both names.

**Implements the design system documented in
[`Skills/DESIGN.md`](../DESIGN.md).** Read that first before touching
CSS — token values (colours, typography, spacing) come from its YAML
front matter and must be referenced via CSS variables in
[`lib/render_styles.py`](lib/render_styles.py). **No raw
hex literals outside the `:root` block** (lint: `rg
"#[0-9a-fA-F]{3,6}" lib/` should only hit `:root`).

- `render_styles.STYLESHEET` — the full inline CSS. Owns colors (CSS custom
  properties at the top, mapping `Skills/DESIGN.md` tokens), card
  chrome, every visual component's layout, tooltip styling, mobile
  breakpoints.
- `render_scripts.INLINE_JS` — inline JavaScript embedded at the bottom of the HTML.
  Tab switching with URL hash mirroring, hover tooltip positioning,
  interactive training-load chart scrubber + tooltip, tiny markdown
  renderer for the Workout tab.

### Card renderer split

`lib/render_cards.py` is now a compatibility facade. Existing imports
keep working; new card changes should go to the focused module:

- [`lib/render_cards_common.py`](lib/render_cards_common.py) —
  `coach_block`, `_heading`, heading tooltip copy.
- [`lib/render_cards_today.py`](lib/render_cards_today.py) — Today tab:
  `card_session_call`, `card_hero`, recovery drivers, ACWR, rings, NEAT,
  training load, muscle volume, strength, week-over-week, tier strip.
- [`lib/render_cards_health.py`](lib/render_cards_health.py) —
  trajectory health surfaces: vitals, sleep, recovery practices.
- [`lib/render_cards_domains.py`](lib/render_cards_domains.py) —
  longevity domain cards: longevity score, cardio, recovery, sleep,
  body composition, metabolic, behavioral.
- [`lib/render_cards_programs.py`](lib/render_cards_programs.py) —
  risk flags, swim trajectory, nutrition phase.

Every `card_*` still returns a complete `<section>`. Renderer modules
remain presentation-only: no disk I/O and no analytics imports.

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

- Coach internals import through `workout_coach.lib.*`. Modules inside
  `workout-coach/lib/` use package-relative imports; the underscore
  facade preserves the historical hyphenated skill directory and public
  script paths.
- Renderer modules **do not** import from analytics modules and vice
  versa. The interface between them is the tracker JSON shape in
  [`../tracker/contracts.py`](../tracker/contracts.py).
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
   the focused card module for its tab/domain.
2. Add CSS for any new classes in `STYLESHEET` in
   [`lib/render_styles.py`](lib/render_styles.py). Reference CSS
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
- HTML / structure: the focused `lib/render_cards_*.py` module.
- CSS: [`lib/render_styles.py`](lib/render_styles.py).
- New SVG glyph or chart: add a function to the focused
  `lib/render_components_*.py` module and re-export it from
  [`lib/render_components.py`](lib/render_components.py) if existing
  imports need it.

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
will automate this against the existing `tests/fixtures/<Person>/` and
`tests/fixtures/<OtherPerson>/` trees. See `references/code-health-audit.md` #8.
