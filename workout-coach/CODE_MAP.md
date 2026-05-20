# workout-coach code map

Where to go when you need to change something in this skill. Modeled on
the [`ARCHITECTURE.md`](https://matklad.github.io/2021/02/06/ARCHITECTURE.md.html)
convention: a short, opinionated index that an agent can read once
before touching the code.

## When you need to change...

| Goal | Edit |
| --- | --- |
| A card's HTML layout / structure | [`lib/render_cards.py`](lib/render_cards.py) |
| CSS / styling / colors | [`lib/render_assets.py`](lib/render_assets.py) (the `STYLESHEET` string) |
| Inline JavaScript (tabs, tooltips, chart scrubber, markdown viewer) | [`lib/render_assets.py`](lib/render_assets.py) (the `INLINE_JS` string) |
| An SVG component (training-load chart, sparkline, muscle bar, freshness/recovery scale, ring, driver bar) | [`lib/render_cards.py`](lib/render_cards.py)... wait no, [`lib/render_components.py`](lib/render_components.py) |
| Coach-text validation rules / em-dash check / length cap | [`lib/render_validators.py`](lib/render_validators.py)::`validate_coach_reads` |
| Add a tooltip for a new abbreviation in coach text | [`lib/render_validators.py`](lib/render_validators.py)::`KNOWN_TERMS` |
| Tracker JSON shape (what fields the renderer reads) | [`scripts/read_tracker.py`](scripts/read_tracker.py) + the relevant `lib/*.py` analytics module |
| Recovery score formula / drivers | [`lib/health.py`](lib/health.py)::`recovery_score` |
| Per-muscle volume math (MEV / MAV / MRV thresholds, weekly tally) | [`lib/constants.py`](lib/constants.py) + [`lib/strength.py`](lib/strength.py) |
| CTL / ATL / TSB / TRIMP math | [`lib/cardio.py`](lib/cardio.py) |
| Sleep aggregation (efficiency, fragmentation, schedule, outliers) | [`lib/sleep.py`](lib/sleep.py) |
| Swim summary | [`lib/swim.py`](lib/swim.py) |
| Sauna + cold-exposure summary | [`lib/thermal.py`](lib/thermal.py) |
| Light-therapy summary | [`lib/light_therapy.py`](lib/light_therapy.py) |
| Per-muscle HR creep / strength session HR / e1RM slope | [`lib/strength.py`](lib/strength.py) |
| Apple Health import semantics | [`../shared/import_apple_health.py`](../shared/import_apple_health.py) (Apple XML) or [`../shared/import_health_auto_export.py`](../shared/import_health_auto_export.py) (HealthAutoExport) |
| Dashboard spec / card contracts | [`references/assessment-dashboard.md`](references/assessment-dashboard.md) |
| Coach behavioral rules (Phase 2 planning) | [`SKILL.md`](SKILL.md) |

## Layout

```
Skills/workout-coach/
├── SKILL.md                              skill entry point (Phase 1 + Phase 2)
├── CODE_MAP.md                           this file
├── references/
│   ├── assessment-dashboard.md           dashboard contracts: card spec, coach-reads schema, copy rules
│   └── training-science.md               physiology references the coach can cite
├── scripts/
│   ├── read_tracker.py                   CLI: reads CSV store, emits compact tracker JSON
│   └── render_dashboard.py               CLI: composes the final HTML (thin orchestrator)
└── lib/
    │
    ├── # ---- Analytics modules (consumed by read_tracker.py) ----
    ├── constants.py                      capabilities, landmarks, aliases
    ├── parsing.py                        date + number coercions
    ├── extract.py                        CSV readers + exercises-database parser
    ├── sessions.py                       per-session aggregation + bodyweight trend
    ├── strength.py                       volume, e1RM, HR-at-volume divergence
    ├── cardio.py                         cardio rollups, HR zones, TRIMP, CTL/ATL/TSB, daily-activity (NEAT)
    ├── health.py                         time-series helpers, weekly rollup, recovery_score
    ├── sleep.py                          sleep_summary (stages, schedule, fragmentation, outliers)
    ├── swim.py                           swim_summary (pace, SPL, SWOLF, CSS zones)
    ├── thermal.py                        thermal_summary (sauna + cold)
    ├── light_therapy.py                  light_therapy_summary (RLT / PBM / blue light)
    │
    └── # ---- Renderer modules (consumed by render_dashboard.py) ----
    ├── render_helpers.py                 esc, fmt, signed, parse_date — zero-dep helpers
    ├── render_validators.py              KNOWN_TERMS catalog, validate_coach_reads, auto_wrap_terms
    ├── render_components.py              SVG / HTML components (chart, rings, bars, scales, sparkline)
    ├── render_assets.py                  STYLESHEET (CSS) + INLINE_JS strings
    └── render_cards.py                   card_* HTML templates + coach_block
```

## Renderer module index (`lib/render_*.py`)

### [`render_helpers.py`](lib/render_helpers.py) (~50 lines)

The tiniest formatters. Zero dependencies; every other `render_*` module
imports from here. Keep it that way to avoid circular imports.

Functions:
- `esc(s)` — HTML-escape any value; `None` → `""`.
- `fmt(v, digits, default)` — number formatter with a default glyph for
  `None`/`NaN`. Integers always render without trailing decimals.
- `signed(v, digits, default)` — same but always prints a leading sign.
- `parse_date(s)` — single source for `YYYY-MM-DD` parsing.

### [`render_validators.py`](lib/render_validators.py) (~155 lines)

Coach-text schema validation and the tooltip-term catalog.

Constants:
- `KNOWN_TERMS` — abbreviation → (full name, plain-English explanation).
  Adding a new tooltip-able abbreviation: just add an entry here, no
  other file changes.
- `COACH_CARD_KEYS` — documented card keys; the validator warns if any
  are missing from `coach_reads.json`.
- `EM_DASH`, `COACH_STRING_MAX` — copy-rule constants.

Functions:
- `validate_coach_reads(coach) -> (errors, warnings)` — hard errors fail
  the render with exit 2; warnings print to stderr but allow the render
  to proceed.
- `auto_wrap_terms(text)` — wraps each `KNOWN_TERMS` key in a dotted-
  underline tooltip span. First-occurrence-only per string (intentional;
  see the docstring before "fixing").

### [`render_components.py`](lib/render_components.py) (~440 lines)

SVG and HTML components used by the cards. Each function returns a
complete fragment.

Grouped by purpose:
- **Training-load chart**: `build_load_series` (CTL/ATL/TSB EWMA over N
  days, with pre-window seeding) + `load_chart_svg` (interactive line
  chart with hover scrubber).
- **Activity rings**: `ring(actual, target, label, sub)`.
- **Recovery drivers**: `metric_label`, `metric_tip`, `driver_bars`
  (diverging horizontal bars; filters out penalty-only `z=None`
  signals).
- **Per-muscle volume**: `muscle_bars(weekly_volume)` (4-band stack with
  MEV/MAV tick marks).
- **Hero scales**: `freshness_scale(tsb)` (-15..+15 strip),
  `recovery_scale(score)` (0..10 strip). Both share viewBox + band-
  label conventions so the two hero cards look like siblings.
- **Small indicators**: `confidence_dots(conf)` (3 dots),
  `sparkline(values, status_class)` (mini line chart),
  `embed_workout_markdown(md_text)` (escaped script tag).

### [`render_assets.py`](lib/render_assets.py) (~690 lines)

Two module-level string constants — pure data, no functions.

- `STYLESHEET` — the full inline CSS. Owns colors (CSS custom
  properties at the top), card chrome, every visual component's layout,
  tooltip styling, mobile breakpoints. To change spacing or color for
  any card, edit here.
- `INLINE_JS` — inline JavaScript embedded at the bottom of the HTML.
  Handles: tab switching with URL hash mirroring, hover tooltip
  positioning, interactive training-load chart scrubber + tooltip, and
  a tiny markdown renderer for the Workout tab.

### [`render_cards.py`](lib/render_cards.py) (~660 lines)

HTML templates for every card. Each `card_*` returns a complete
`<section>`. Pure presentation — no I/O, no analytics.

Card functions, in dashboard render order:
1. `card_hero` — Recovery + Freshness, each with a scale strip.
2. `card_drivers` — Recovery drivers diverging-bar chart.
3. `card_rings` — Activity rings.
4. `card_neat` — NEAT (all-day movement) — banded bar + supporting stats.
5. `card_training_load` — 90-day chart + 4-up summary cells.
6. `card_muscle_volume` — Per-muscle bars.
7. `card_strength` — Strength progression table.
8. `card_vitals` — Health vitals table with sparklines.
9. `card_sleep` — Stage stack + diagnostic rows + outliers.
10. `card_recovery_practices` — Sauna / cold / light sub-cards.
11. `card_wow` — Week over week table.

Shared:
- `coach_block(text)` — wraps a coach string in the standard
  `<aside class="coach">` callout, or empty if text is None/blank.

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
            └───────────────────────────────────────────────────┘
                                 │ tracker.json
                                 ▼
            ┌───────────────────────────────────────────────────┐
            │ Coach LLM (you, when /coach runs)                 │
            │   reads SKILL.md Phase 2, the tracker JSON, and   │
            │   references/assessment-dashboard.md, and writes  │
            │   coach_reads.json + <date>-workout.md            │
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
  `read_tracker.py`'s `out` dict assembly).
- No external HTTP / CDN / web font dependencies in the dashboard.
  Verify with `grep -E '<script src|<link href="http|@import url' on
  the rendered HTML — must be zero matches.
- New abbreviations in coach text: register in `KNOWN_TERMS`. Update
  the `references/assessment-dashboard.md` tooltip-catalog list to
  match.

## Quick how-to recipes

**Add a new card.**
1. Implement `card_yournew(data, coach_text)` in
   [`lib/render_cards.py`](lib/render_cards.py).
2. Add CSS for any new classes in `STYLESHEET` in
   [`lib/render_assets.py`](lib/render_assets.py).
3. Wire the call into [`scripts/render_dashboard.py`](scripts/render_dashboard.py)::`render()`
   in the desired position.
4. Add an entry to the Coach-reads schema in
   [`references/assessment-dashboard.md`](references/assessment-dashboard.md)
   if the card has a coach callout.
5. Add a `card_*` line to `COACH_CARD_KEYS` in
   [`lib/render_validators.py`](lib/render_validators.py) so a missing
   callout warns.

**Change a card's layout.**
- HTML/structure: [`lib/render_cards.py`](lib/render_cards.py).
- CSS: [`lib/render_assets.py`](lib/render_assets.py).
- New SVG glyph or chart: add a function to
  [`lib/render_components.py`](lib/render_components.py) and call it
  from the card.

**Verify a renderer change.** Render before + after, diff the HTML,
ignoring the footer's `generated at` timestamp (it uses
`datetime.now()`, so it'll always differ across runs):

```bash
diff <(grep -v 'generated at' before.html) <(grep -v 'generated at' after.html)
```
