---
name: Longevity Dashboard
description: Apple Health-inspired design system for the workout-coach
  dashboard. Subtle tones, soft shadows, rounded corners, sparse colour,
  generous whitespace, no harsh borders. Tokens here are normative; the
  prose below explains intent and application.
colors:
  text:           "#1d1d1f"
  muted:          "#86868b"
  bg:             "#ffffff"
  card:           "#ffffff"
  border:         "#ececec"
  border-strong:  "#d8d8d9"
  border-soft:    "#f4f4f6"
  good:           "#34c759"
  amber:          "#ff9f0a"
  warn:           "#ff3b30"
  accent:         "#0a84ff"
  muscle-low:     "#ff9f0a"
  muscle-prod:    "#34c759"
  muscle-push:    "#ffcc00"
  muscle-over:    "#ff3b30"
typography:
  section:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif"
    fontSize: 12px
    fontWeight: 600
    letterSpacing: 0.06em
  hero:
    fontSize: 48px
    fontWeight: 600
    letterSpacing: -0.02em
    lineHeight: 1.1
  hero-large:
    fontSize: 32px
    fontWeight: 600
    letterSpacing: -0.02em
    lineHeight: 1.15
  secondary:
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.1
  body:
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.5
  status:
    fontSize: 14px
    fontWeight: 500
  detail:
    fontSize: 12.5px
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: 6px
  md: 10px
  lg: 14px
  pill: 999px
spacing:
  xs: 4px
  sm: 8px
  md: 14px
  lg: 20px
  xl: 24px
components:
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: 20px 22px
  pill-status:
    rounded: "{rounded.pill}"
    padding: 3px 9px
    typography: "{typography.status}"
  pill-adherence:
    rounded: "{rounded.pill}"
    padding: 3px 9px
    typography: "{typography.status}"
  tier-indicator:
    rounded: "{rounded.pill}"
    padding: 3px 10px
    typography: "{typography.status}"
  tooltip:
    backgroundColor: "#1c1c1e"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: 8px 10px
---

## Overview

Aspirational reference: Apple Health. Subtle tones, soft shadows,
rounded corners, sparse colour, generous whitespace, no harsh borders.

Communicate state with a coloured dot or pill — never with a coloured
left-border on a card or a card-level background tint. Cards are
visually uniform; state belongs inside the card, not on its chrome.

Hex values live only in the YAML front matter above. Render modules
must reference tokens (CSS variables on `:root`) — never inline a
literal `#hex` value. The lint rule
`rg "#[0-9a-fA-F]{3,6}" Skills/workout-coach/lib/ | grep -v "^.*:root"`
should return zero hits.

Validate this file:

```bash
npx @google/design.md lint Skills/DESIGN.md
```

## Colors

Semantic palette. Each colour answers a question; never reach for a
colour outside its meaning.

- **text** — primary text. Used for headlines, body copy, value cells.
- **muted** — secondary text. Labels, captions, tooltips' inline term,
  callout sublabels, footnotes. Never used as a status colour.
- **bg / card** — surfaces. `card` is the inner surface (currently
  identical to `bg` for a flat-on-flat look); reserved as a token in
  case we introduce off-white card chrome later.
- **border / border-strong / border-soft** — three border weights.
  `border` for card outlines; `border-strong` for inner-section
  separators that need to read; `border-soft` for very-quiet dividers
  inside tables or placeholder rows.
- **good (green)** — favourable status. Recovery high, on-target
  adherence, "in band" placement.
- **amber (orange)** — caution. Detraining band, modified-strength
  tier, "below target" adherence, sustained autonomic suppression.
- **warn (red)** — alarm. Illness signal, refused-strength tier, MRV
  breach, sleep apnea-range breathing disturbance.
- **accent (blue)** — informational, neither good nor bad. Over-
  recovered tier, secondary chart lines, calm-state callouts.
- **muscle-{low,prod,push,over}** — internal to the per-muscle volume
  bar chart only. Never surfaces in pills, cards, or text colour.

## Typography

| Token | Use case |
|---|---|
| `section` | `.card h2` — every card heading, every tab. 12 px uppercase 600-wt 0.06em muted. |
| `hero` | Primary metric value — `.value`, `.metric-hero-value`, `.practice .big`. 48 px 600 wt. |
| `hero-large` | Single-purpose: `.session-call-headline`. 32 px 600 wt. The recovery-gate call needs more weight than a normal hero. |
| `secondary` | `.secondary-value` (domain-card secondary metrics). 24 px 600 wt. |
| `body` | Default. 15 px / 1.5 line height. Use for prose, cardio notes, exercise-list bullets. |
| `status` | Pills, inline status words. 14 px 500 wt. Status word gets a semantic colour; surrounding text stays `text`. |
| `detail` | Muted footnotes, callout sublabels, table cells with secondary info. 12.5 px muted. |

Section H2s use `text-transform: uppercase` and the `letterSpacing` token
together — neither alone reads as a "section label."

## Layout

Card-to-card vertical rhythm: 24 px (`spacing.xl`).
Intra-card section gap: 14 px (`spacing.md`).
Intra-row spacing: 8 px (`spacing.sm`).
Card padding: `20px 22px` (`spacing.lg` y, slight extra x for breathing).

Common grid templates currently in use:

- Hero pair (Recovery + Freshness): `repeat(2, 1fr)`.
- Practices tiles: `repeat(3, 1fr)`.
- Activity rings: `repeat(5, 1fr)`.
- Driver bar rows: `150px 1fr 60px` (label | track | value).
- Muscle bar rows: `140px 1fr 240px`.
- Secondary metric: `200px 1fr` outer grid (label | value-stack); the
  value-stack is a flex column so the sublabel always aligns to the
  value's left edge regardless of the value's width. **Do not** use
  `grid-column: 2 / -1` on the sublabel — it misaligns when the value
  cell is short.
- Sleep row: `12px 200px 1fr` (dot | label | value).

## Elevation & Depth

Two shadows. That's it.

- **Card**: `0 1px 2px rgba(0,0,0,0.04)` — soft, almost imperceptible.
  Gives the card a sense of sitting one layer above the background
  without reading as a "lifted" element.
- **Tooltip**: `0 8px 24px rgba(0,0,0,0.22)` — pronounced enough to
  read as floating over the canvas.

No card-level tier shadows. No coloured shadows. No `outline`-based
focus rings on cards.

## Shapes

- `rounded.lg` (14 px) — card chrome.
- `rounded.md` (10 px) — inner tiles (practice boxes, callouts).
- `rounded.sm` (6 px) — small chips, tooltip, muted boxes.
- `rounded.pill` (999 px) — pills (status, adherence, tier).

## Components

### `.card`

Single shared chrome. Background `card`, border `border`, radius
`rounded.lg`, padding `20px 22px`, soft shadow per Elevation. **No
variants.** A card never communicates state through its border colour
or background — that goes inside via a `.pill.*` or `.tier-indicator`.

Defined in: `Skills/workout-coach/lib/render_assets.py` (`.card` block).

### `.pill.{good|amber|warn|muted}` — status pill

Single semantic pill for state indicators. Class names match colour
tokens. Used for: HSP-band sauna status, sleep-band indicator,
risk-flag status, recovery-band status.

Defined in: `Skills/workout-coach/lib/render_assets.py` (`.pill` block).

### `.pill-adherence.{on-target|below-target|above-target}` — adherence pill

Separate semantic pill for goal-attainment. Visually identical chrome
to `.pill`, distinct class so we can re-skin adherence independently
later. Used for: practices-card session-count vs weekly target,
training-load adherence.

Why split from `.pill.*`? Adherence-met ≠ state-good. A user can be
on-target with their cold-shower count (adherence pill: on-target)
while their sleep recovery is bad (status pill: warn). The pills
communicate orthogonal things and live in the same card.

### `.tier-indicator.{good|amber|warn|accent}` — session-call tier chip

Placed above the session-call headline. Carries a semantic word:
"Rest day", "Reactive deload", "Modified strength", "Train as planned",
"Over-recovered". Colour comes from the underlying `.pill.*` palette
(reused via `tier-indicator` component sharing the same chrome).

Never use a card-level coloured left-border to indicate tier.

### `.secondary-metric` — domain-card metric row

Layout: outer grid `200px 1fr`; right column is a flex column with
value on top and sublabel beneath, both left-aligned to the same
column-2 edge.

```
LABEL              24 px value
                   12.5 px muted sublabel
```

Defined in: `Skills/workout-coach/lib/render_components.py`
(`secondary_metric_row`).

### `.metric-hero`

Hero value + status word + optional comparison strip. Used at the top
of every Trajectory-tab domain card.

Defined in: `Skills/workout-coach/lib/render_components.py`
(`metric_hero`).

### Bars, rings, sparklines, scales

`.driver-row`, `.bar-row`, `.ring`, `.sparkline`, `.recovery-scale`,
`.freshness-scale` — see `render_components.py` and `render_assets.py`
for the canonical implementations. All inherit semantic colour tokens;
no inline hex.

## Do's and Don'ts

**DO**
- Hide empty states entirely. When data is absent, omit the row, the
  callout, or the entire section. Banned placeholder strings include
  "No outlier nights in the last 14 days.", "No data", standalone
  "Not logged" rows, and any value cell whose sole content is `·` or
  `—`.
- Keep raw hex in the YAML front matter only. Reference tokens via
  CSS variables.
- Reuse `.pill.*` / `.pill-adherence.*` / `.tier-indicator.*` for
  any chip-shaped element. Never invent a new pill class.
- Gate user-specific copy on `longevity_state.risk_flags`. Medication
  references, family-history surveillance notes, and other PII-coded
  guidance must check a flag before rendering. Never hardcode them.
- Suppress score inputs the person's data source structurally cannot
  provide. Listing them as "missing" punishes the user for a tooling
  limitation.

**DON'T**
- Use coloured left-borders to encode tier or status on cards.
- Use background gradients or tints on cards to communicate state.
- Use monospace fonts to signal "fill-in-blank" or any other UX
  affordance. Use a tinted background row instead.
- Render muted placeholder text in value or detail positions when the
  underlying data is empty.
- Mix raw hex literals into render modules — every colour goes
  through a CSS variable that maps back to a token here.
