"""Static CSS + inline JS used by the dashboard renderer.

Implements the design system documented in ``Skills/DESIGN.md`` (Google
Stitch DESIGN.md format). Token values — colours, typography, spacing,
shadows — live there as the normative source; this module's CSS
variables on ``:root`` are the local mirror. Never inline a raw hex
literal outside the ``:root`` block.

Two module-level string constants:

- ``STYLESHEET`` — the full inline CSS embedded in the HTML's ``<style>``
  tag. Owns colors (CSS custom properties at the top), card chrome,
  every visual component's layout, hover-tooltip styling, responsive
  breakpoints. To change spacing, color, or sizing for any card, edit
  here.
- ``INLINE_JS`` — the inline JavaScript embedded at the bottom of the
  HTML. Handles three things: tab switching with URL hash mirroring,
  hover-tooltip positioning for ``[data-tip]`` / ``.term``, and the
  interactive training-load chart scrubber + tooltip. Also contains a
  tiny markdown renderer that parses the embedded workout markdown
  into the Workout tab on first display.

The module is pure data; importing it has no side effects beyond
loading the strings into memory. Both strings are valid as-is — they
do not pass through ``str.format`` or f-strings — so braces in CSS /
JS are unescaped.
"""
from __future__ import annotations


STYLESHEET = """
/* Tokens mirror Skills/DESIGN.md. The YAML front matter there is the
   normative source; every CSS variable below points back to a token
   in that file. Never inline a raw hex literal outside this :root block. */
:root {
  --bg: #f7f7f8;
  --card: #ffffff;
  --border: #ececec;
  --border-strong: #d8d8d9;
  --border-soft: #f4f4f6;
  --text: #1c1c1e;
  --muted: #6b6b6f;
  --good: #34c759;
  --amber: #ff9f0a;
  --warn: #ff3b30;
  --accent: #0a84ff;

  /* Tinted backgrounds — derived from the semantic palette at 12%
     opacity so pills + soft callouts can share one alpha scheme. */
  --good-tint:   rgba(52,199,89,0.12);
  --amber-tint:  rgba(255,159,10,0.12);
  --warn-tint:   rgba(255,59,48,0.12);
  --accent-tint: rgba(10,132,255,0.12);
  --muted-tint:  #eeeeef;

  /* Surfaces — quieter than --card, used for inset tiles and callouts. */
  --tile-bg:  #fafafa;
  --track-bg: #f0f1f3;

  /* Soft shadow on card chrome (Apple Health-style elevation). */
  --shadow-card: 0 1px 2px rgba(0,0,0,0.04);

  /* Dark surface tokens for floating overlays. */
  --tooltip-bg: #1c1c1e;
  --tooltip-fg: #ffffff;

  /* Per-muscle volume bands. Four distinct hues so opposite ends of
     the spectrum (not-enough vs too-much) never share a color. */
  --muscle-low:  #ff9500; /* orange  , below MEV, "not enough" */
  --muscle-prod: #34c759; /* green   , MEV..MAV, "productive" */
  --muscle-push: #ffcc00; /* yellow  , MAV..MRV, "pushing limit" */
  --muscle-over: #ff3b30; /* red     , above MRV, "too much, cut back" */
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text",
        "Inter", system-ui, sans-serif;
  -webkit-font-smoothing: antialiased; }

/* layout */
.page { max-width: 980px; margin: 0 auto; padding: 32px 20px 60px; }
header.page-head h1 { margin: 0; font-size: 28px; font-weight: 600;
  letter-spacing: -0.01em; }
header.page-head .meta { color: var(--muted); margin-top: 4px;
  font-size: 14px; }
/* Coach's summary card sits above the hero. Same chrome as other cards.
   It uses the standard card style; the body just gets a slightly larger
   line-height for readability. */
.summary { margin-bottom: 14px; }
.summary .body { font-size: 16px; line-height: 1.6;
  color: var(--text); max-width: 760px; }

/* tabs */
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border-strong);
  margin-bottom: 18px; position: sticky; top: 0; background: var(--bg);
  padding-top: 6px; z-index: 50; }
.tab { padding: 10px 18px; cursor: pointer; font-size: 14px;
  font-weight: 500; color: var(--muted); border: none; background: none;
  border-bottom: 2px solid transparent; }
.tab[aria-selected="true"] { color: var(--accent);
  border-bottom-color: var(--accent); }
.tab:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.tab-panel { display: none; }
.tab-panel[data-active="true"] { display: grid; gap: 24px; }

/* card — one chrome for every card, every tab. State indicators live
   inside the card (pills, dots), never on its border or background. */
.card { background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 20px 22px;
  box-shadow: var(--shadow-card); }
.card h2 { margin: 0 0 14px; font-size: 12px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }

/* hero */
.hero { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.hero .metric { display: flex; flex-direction: column; }
.metric .value { font-size: 48px; font-weight: 600;
  letter-spacing: -0.02em; line-height: 1; }
.metric .value .denom { font-size: 22px; color: var(--muted);
  font-weight: 400; }
.metric .sub { color: var(--muted); margin-top: 12px; font-size: 14px;
  display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.metric.good .value { color: var(--good); }
.metric.amber .value { color: var(--amber); }
.metric.warn .value { color: var(--warn); }

/* coach callout, typographic differentiation only; no box, no border,
   no tint. A thin hairline rule and a small-caps label do the work. */
.coach { margin-top: 18px; padding-top: 14px;
  border-top: 1px solid var(--border-soft); }
.coach .label { font-size: 10.5px; font-weight: 600;
  letter-spacing: 0.10em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 4px; }
.coach .text { font-size: 14px; line-height: 1.55; color: var(--text); }

/* tooltip system */
.term, [data-tip] { position: relative; }
.term { border-bottom: 1px dotted var(--muted); cursor: help; }
.tooltip {
  position: fixed;
  background: var(--tooltip-bg); color: var(--tooltip-fg);
  border-radius: 8px; padding: 10px 12px;
  font-size: 12.5px; line-height: 1.5;
  max-width: 280px; box-shadow: 0 8px 24px rgba(0,0,0,0.22);
  pointer-events: none; opacity: 0; transition: opacity 0.12s;
  z-index: 200;
}
.tooltip.show { opacity: 1; }
.tooltip strong { color: var(--tooltip-fg); font-weight: 600; }

/* Pills — exactly two semantic families plus a tier-indicator variant.
   Status pills carry state (good/amber/warn/muted). Adherence pills
   carry goal-attainment (on-target/below-target/above-target). Tier
   indicator is a single chip above the session-call headline. All three
   share chrome; only the colour palette differs. */
.pill { display: inline-block; padding: 3px 9px;
  border-radius: 999px; font-size: 11px; font-weight: 500; }
.pill.good  { color: var(--good);   background: var(--good-tint); }
.pill.amber { color: var(--amber);  background: var(--amber-tint); }
.pill.warn  { color: var(--warn);   background: var(--warn-tint); }
.pill.muted { color: var(--muted);  background: var(--muted-tint); }

.pill-adherence { display: inline-block; padding: 3px 9px;
  border-radius: 999px; font-size: 11px; font-weight: 500; }
.pill-adherence.on-target    { color: var(--good);  background: var(--good-tint); }
.pill-adherence.below-target { color: var(--amber); background: var(--amber-tint); }
.pill-adherence.above-target { color: var(--accent); background: var(--accent-tint); }

.tier-indicator { display: inline-block; padding: 3px 10px;
  border-radius: 999px; font-size: 11.5px; font-weight: 600;
  letter-spacing: 0.02em; margin-bottom: 14px; }
.tier-indicator.good   { color: var(--good);   background: var(--good-tint); }
.tier-indicator.amber  { color: var(--amber);  background: var(--amber-tint); }
.tier-indicator.warn   { color: var(--warn);   background: var(--warn-tint); }
.tier-indicator.accent { color: var(--accent); background: var(--accent-tint); }

/* drivers */
.driver-row { display: grid; grid-template-columns: 150px 1fr 60px;
  align-items: center; gap: 12px; padding: 5px 0;
  font-size: 13px; cursor: help; }
.driver-label { color: var(--text); }
.driver-track { position: relative; height: 12px;
  background: var(--track-bg); border-radius: 6px; overflow: hidden; }
.driver-axis { position: absolute; left: 50%; top: 0; width: 1px;
  height: 100%; background: var(--border-strong); }
.driver-fill { position: absolute; top: 0; height: 100%; border-radius: 6px; }
.driver-fill.good { background: var(--good); }
.driver-fill.amber { background: var(--amber); }
.driver-fill.warn { background: var(--warn); }
.driver-fill.muted { background: var(--border-strong); }
.driver-value { font-variant-numeric: tabular-nums; font-weight: 500;
  text-align: right; }
.driver-value.good { color: var(--good); }
.driver-value.amber { color: var(--amber); }
.driver-value.warn { color: var(--warn); }
.driver-value.muted { color: var(--muted); }
.driver-axis-row { display: grid; grid-template-columns: 150px 1fr 60px;
  font-size: 11px; color: var(--muted); padding-bottom: 10px; }
.driver-axis-row .axis-labels { display: flex; justify-content: space-between; }

/* rings */
.rings { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px;
  padding: 6px 0; }
.ring-wrap { text-align: center; }
.ring { width: 76px; height: 76px; }
.ring-value { font-size: 14px; font-weight: 600; margin-top: 6px; }
.ring-label { font-size: 13px; color: var(--text); }
.ring-sub { font-size: 11px; color: var(--muted); margin-top: 2px; }

/* NEAT card: three equal stat cells, centered. All three cells frame
   their numbers per day so the units read consistently. Cell 1
   (exercise minutes) appends a colored status word against the
   upstream band; cells 2 and 3 are descriptive. */
.neat-stats { display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 18px; }
.neat-stat { text-align: center; }
.neat-stat-num { font-size: 22px; font-weight: 600; line-height: 1.1;
  color: var(--text); font-variant-numeric: tabular-nums; }
.neat-stat-unit { font-size: 11px; color: var(--muted); font-weight: 400;
  margin-left: 4px; }
.neat-stat-desc { font-size: 12px; color: var(--muted); margin-top: 6px; }

/* training-load chart */
.load-chart { width: 100%; height: auto; cursor: crosshair; }
.load-chart .hit { pointer-events: all; }
/* Single combined "summary" row below the chart: 4 stat cells, each
   carrying its line-color swatch + tooltipped name + current value.
   Replaces the prior split between .load-legend (chips) and .load-stats
   (numbers) which duplicated the metric names and made the line→value
   relationship ambiguous. */
.load-summary { display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 18px; margin-top: 14px; }
/* Per cell: swatch in a fixed 22px left column spanning both rows, name
   in the right column row 1, value in the right column row 2. Name and
   value share the same column so they are left-aligned to each other
   regardless of swatch presence. */
.load-summary-cell { display: grid; grid-template-columns: 22px 1fr;
  column-gap: 8px; row-gap: 4px; align-items: center; }
.load-summary-cell .sw { grid-column: 1; grid-row: 1 / span 2;
  align-self: center; }
.load-summary-name { grid-column: 2; font-size: 12px; color: var(--muted); }
.load-summary-value { grid-column: 2; font-size: 20px; font-weight: 600;
  color: var(--text); font-variant-numeric: tabular-nums; line-height: 1.1; }
.load-summary-cell .sw { display: inline-block; width: 18px; height: 2px;
  vertical-align: middle; }
/* Line/band swatches reused by both the summary row and the floating
   tooltip on the chart, so they stay top-level. */
.sw-ctl { background: var(--accent); }
.sw-atl { background: 0; border-top: 2px dashed var(--amber); height: 0; }
.sw-tsb { background: linear-gradient(var(--amber-tint), var(--good-tint));
  height: 8px !important; }

.load-tooltip { position: fixed; background: var(--tooltip-bg);
  color: var(--tooltip-fg);
  border-radius: 8px; padding: 10px 12px; font-size: 12px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.22);
  pointer-events: none; z-index: 200; }
.load-tooltip .lt-date { font-weight: 600; margin-bottom: 4px; }
.load-tooltip .lt-row { display: flex; align-items: center; gap: 8px;
  margin: 2px 0; }
.load-tooltip .lt-row .sw { display: inline-block; width: 12px; height: 2px; }
.load-tooltip .lt-row span:last-child { margin-left: auto;
  font-variant-numeric: tabular-nums; font-weight: 600; }

/* muscle bars, four distinct band colors, fixed-width dots, two thin
   tick marks per row showing MEV and MAV. No background band — that
   was causing the 3-color confusion on under-MEV rows. */
.muscle-legend { font-size: 12px; color: var(--muted);
  margin-bottom: 14px; padding-bottom: 12px;
  border-bottom: 1px solid var(--border-soft); }
.muscle-legend-chips { display: flex; gap: 20px; flex-wrap: wrap;
  align-items: center; }
.muscle-legend-chip { display: inline-flex; align-items: center; gap: 6px; }
.muscle-legend-explain { margin-top: 10px; line-height: 1.5; }
.muscle-legend-caveat { margin-top: 6px; line-height: 1.5;
  font-size: 11.5px; font-style: italic; }

.bar-row { display: grid; grid-template-columns: 140px 1fr 290px;
  align-items: center; gap: 14px; padding: 7px 0;
  font-size: 13px; cursor: help; }
.bar-label { color: var(--text); text-transform: capitalize; }
.bar-track { position: relative; height: 10px;
  background: var(--track-bg); border-radius: 5px; }
.bar-tick { position: absolute; top: -2px; height: 14px; width: 1px;
  background: var(--border-strong); }
.bar-fill { position: absolute; top: 0; left: 0; height: 100%;
  border-radius: 5px; }
.bar-fill.band-low  { background: var(--muscle-low); }
.bar-fill.band-prod { background: var(--muscle-prod); }
.bar-fill.band-push { background: var(--muscle-push); }
.bar-fill.band-over { background: var(--muscle-over); }

.bar-status { display: inline-flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--muted); }
.bar-status-label { white-space: nowrap; }
.bar-dot { display: inline-block; width: 9px; height: 9px;
  border-radius: 50%; flex: 0 0 9px; }
.bar-dot.band-low  { background: var(--muscle-low); }
.bar-dot.band-prod { background: var(--muscle-prod); }
.bar-dot.band-push { background: var(--muscle-push); }
.bar-dot.band-over { background: var(--muscle-over); }
.bar-num { font-variant-numeric: tabular-nums; font-weight: 500;
  color: var(--text); margin-left: auto; }
/* Per-muscle HR-at-volume annotation. Tiny chip after .bar-num that
   surfaces the fatigue / conditioning trend from the same row's
   muscle. Absent when stable or no data. */
.bar-hr { font-size: 11.5px; font-weight: 500;
  font-variant-numeric: tabular-nums; white-space: nowrap; }
.bar-hr.good { color: var(--good); }
.bar-hr.warn { color: var(--warn); }

/* 3-dot confidence indicator. Three dots = high, two = medium,
   one = low. No tooltip; the dots are self-explanatory. */
.confdots { display: inline-flex; align-items: center; gap: 3px;
  vertical-align: middle; }

/* Freshness (TSB) + Recovery score scale strip in the hero cards.
   Strokes use vector-effect: non-scaling-stroke so they render at the
   declared CSS-px width regardless of how much the SVG shrinks to fit
   the card. Without this they'd render sub-pixel on standard displays
   (~0.7 CSS px after the viewBox-to-container scale). */
.fresh-scale { margin-top: 14px; }
.fresh-scale-svg { width: 100%; height: auto; max-height: 120px;
  display: block; }
.fresh-band-lbl { font-size: 11px; fill: var(--muted);
  font-family: inherit; }
.fresh-tick-num { font-size: 11px; fill: var(--muted);
  font-family: inherit; font-variant-numeric: tabular-nums; }
.fresh-axis { stroke: var(--border-strong); stroke-width: 1.5;
  vector-effect: non-scaling-stroke; }
.fresh-tick { stroke: var(--border-strong); stroke-width: 1.5;
  vector-effect: non-scaling-stroke; }
.fresh-marker { stroke-width: 2.5; vector-effect: non-scaling-stroke; }
.fresh-marker.good  { stroke: var(--good); }
.fresh-marker.amber { stroke: var(--amber); }
.fresh-marker.warn  { stroke: var(--warn); }
.fresh-marker-tri.good  { fill: var(--good); }
.fresh-marker-tri.amber { fill: var(--amber); }
.fresh-marker-tri.warn  { fill: var(--warn); }
.fresh-marker-val { font-size: 13px; font-weight: 700;
  font-family: inherit; font-variant-numeric: tabular-nums; }
.fresh-marker-val.good  { fill: var(--good); }
.fresh-marker-val.amber { fill: var(--amber); }
.fresh-marker-val.warn  { fill: var(--warn); }
.confdots .dot { display: inline-block; width: 7px; height: 7px;
  border-radius: 50%; }
.confdots .dot.on  { background: var(--accent); }
.confdots .dot.off { background: var(--border-strong); }

/* tables */
table { width: 100%; border-collapse: collapse; font-size: 14px;
  table-layout: fixed; }
th, td { text-align: left; padding: 8px 10px 8px 0;
  border-bottom: 1px solid var(--border-soft); }
th { font-weight: 500; color: var(--muted); font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.06em; }
td.num { font-variant-numeric: tabular-nums; }
td.arrow { font-size: 16px; font-weight: 600; }

/* Explicit column widths per data table so long labels in column 1
   don't absorb all the slack and squeeze the numeric columns. */
.strength-table th:nth-child(1), .strength-table td:nth-child(1) { width: auto; }
.strength-table th:nth-child(2), .strength-table td:nth-child(2) { width: 110px; }
.strength-table th:nth-child(3), .strength-table td:nth-child(3) { width: 140px; }
.strength-table th:nth-child(4), .strength-table td:nth-child(4) { width: 60px; }
.strength-table th:nth-child(5), .strength-table td:nth-child(5) { width: 70px; }

.vitals-table th:nth-child(1), .vitals-table td:nth-child(1) { width: auto; }
.vitals-table th:nth-child(2), .vitals-table td:nth-child(2) { width: 120px; }
.vitals-table th:nth-child(3), .vitals-table td:nth-child(3) { width: 120px; padding-right: 18px; }
.vitals-table th:nth-child(4), .vitals-table td:nth-child(4) { width: 130px; }

.wow-table th:nth-child(1), .wow-table td:nth-child(1) { width: auto; }
.wow-table th:nth-child(2), .wow-table td:nth-child(2) { width: 80px; }
.wow-table th:nth-child(3), .wow-table td:nth-child(3) { width: 80px; }
.wow-table th:nth-child(4), .wow-table td:nth-child(4) { width: 80px; }
.wow-table th:nth-child(5), .wow-table td:nth-child(5) { width: 30px; }
.wow-table th:nth-child(6), .wow-table td:nth-child(6) { width: 40px; }

/* Suppress the last-row hairline so the table doesn't print an
   orphan border-bottom above the empty space before the coach
   callout (the coach's own border-top already separates the two). */
.strength-table tbody tr:last-child td,
.vitals-table tbody tr:last-child td,
.wow-table tbody tr:last-child td { border-bottom: none; }
.arrow.good { color: var(--good); }
.arrow.warn { color: var(--warn); }
.arrow.muted { color: var(--muted); }
.muted { color: var(--muted); }
.sparkline { vertical-align: middle; }
.sparkline.good { color: var(--good); }
.sparkline.amber { color: var(--amber); }
.sparkline.warn { color: var(--warn); }
.sparkline.muted { color: var(--muted); }

/* sleep card */
.sleep-hero { display: grid; grid-template-columns: 220px 1fr; gap: 24px;
  align-items: center; padding: 8px 0 18px; }
.sleep-hero .value { font-size: 36px; font-weight: 600;
  letter-spacing: -0.02em; line-height: 1; }
.sleep-hero .denom { font-size: 18px; color: var(--muted); font-weight: 400; }
.sleep-hero .sub { color: var(--muted); margin-top: 6px; font-size: 13px; }
.sleep-stack-wrap { }
.sleep-stack { display: flex; width: 100%; height: 22px;
  border-radius: 6px; overflow: hidden;
  border: 1px solid var(--border); }
.sleep-stack .stage { height: 100%; }
.sleep-stack-legend { display: flex; gap: 14px; flex-wrap: wrap;
  margin-top: 10px; font-size: 12px; color: var(--muted); }
.sleep-stack-legend .dot { display: inline-block; width: 10px;
  height: 10px; border-radius: 50%; vertical-align: middle;
  margin-right: 5px; }
.sleep-rows { display: grid; gap: 6px;
  padding-top: 14px; border-top: 1px solid var(--border-soft); }
.sleep-row { display: grid; grid-template-columns: 12px 200px 1fr;
  align-items: center; gap: 14px; padding: 6px 0; font-size: 13px;
  cursor: help; }
.sleep-row-label { color: var(--text); }
.sleep-row-value { color: var(--text); font-variant-numeric: tabular-nums; }
.sleep-row-value.good  { color: var(--good); }
.sleep-row-value.amber { color: var(--amber); }
.sleep-row-value.warn  { color: var(--warn); }
.sleep-row-value.muted { color: var(--muted); }
.sleep-outliers { margin-top: 14px; padding: 10px 12px;
  background: var(--tile-bg); border-radius: 6px;
  font-size: 13px; color: var(--text); }
.sleep-outliers.muted { color: var(--muted); }

/* recovery practices */
.practices { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.practice { padding: 14px 16px; background: var(--tile-bg);
  border: 1px solid var(--border); border-radius: 10px; }
.practice .title { font-size: 13px; font-weight: 600;
  color: var(--text); margin-bottom: 8px; }
.practice .big { font-size: 28px; font-weight: 600;
  letter-spacing: -0.01em; line-height: 1; }
.practice .big .unit { font-size: 13px; font-weight: 400;
  color: var(--muted); margin-left: 4px; }
/* Practices card adds a small top-margin to its pill placement; pill
   chrome itself is shared via .pill above. */
.practice .pill { margin-top: 8px; }
.practice .pill-adherence { margin-top: 8px; }
.practice .detail { color: var(--muted); font-size: 12.5px;
  margin-top: 8px; line-height: 1.5; }
.practice .recent { margin-top: 8px; padding-top: 8px;
  border-top: 1px solid var(--border); font-size: 12px;
  color: var(--muted); }

/* workout tab — each `## Workout N: TYPE` becomes a card. Shares the
   global .card chrome (background, border, radius, padding, shadow);
   only the inner layout patterns are workout-specific. */
.workout-card { background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 20px 22px; margin-bottom: 14px;
  box-shadow: var(--shadow-card); }
.workout-card h2 { margin: 0 0 14px; font-size: 12px;
  font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--muted); }
.workout-card .placeholders { color: var(--muted); font-size: 13px;
  margin-bottom: 14px; padding-bottom: 12px;
  border-bottom: 1px solid var(--border-soft); }
/* Sans-serif placeholder rows with a soft tint signal "writable line"
   without resorting to a monospace typeface. */
.workout-card .placeholder-row { padding: 4px 10px; margin-bottom: 4px;
  font-size: 12.5px; background: var(--border-soft);
  border-radius: 4px; }
.workout-card ul { list-style: none; padding: 0; margin: 0; }
.workout-card > ul > li { padding: 5px 0 5px 18px; font-size: 14px;
  color: var(--text); font-variant-numeric: tabular-nums;
  position: relative; line-height: 1.5; }
.workout-card > ul > li::before { content: "•";
  position: absolute; left: 4px; color: var(--muted);
  font-weight: 700; }
.workout-card ul.sub { margin-top: 4px; padding-left: 0; }
.workout-card ul.sub li { padding: 2px 0 2px 18px;
  font-size: 13px; color: var(--muted);
  position: relative; line-height: 1.5;
  font-variant-numeric: normal; }
.workout-card ul.sub li::before { content: "";
  position: absolute; left: 0; top: 12px; width: 10px;
  border-top: 1px solid var(--border-strong); }
.workout-card .workout-prose { color: var(--text); font-size: 15px;
  line-height: 1.5; padding: 4px 0; }

footer { max-width: 980px; margin: 0 auto; padding: 28px 20px 80px;
  color: var(--muted); font-size: 12px; }

/* =============================================================================
   Longevity / Trajectory tab components
   ============================================================================= */

/* Comparison strip: VO2, HRV, RHR cohort percentile axis with current marker */
.cmp-strip { margin-top: 14px; }
.cmp-svg { width: 100%; height: auto; max-height: 100px; display: block; }
.cmp-axis { stroke: var(--border-strong); stroke-width: 1.5;
  vector-effect: non-scaling-stroke; }
.cmp-band line { stroke: var(--border-strong); stroke-width: 1;
  vector-effect: non-scaling-stroke; }
.cmp-band-lbl { font-size: 10.5px; fill: var(--muted); font-family: inherit; }
.cmp-band-num { font-size: 10px; fill: var(--muted); font-family: inherit;
  font-variant-numeric: tabular-nums; }
.cmp-baseline line { stroke: var(--accent); stroke-width: 1.5;
  vector-effect: non-scaling-stroke; }
.cmp-unit { font-size: 10px; fill: var(--muted); }
.cmp-user-val { font-size: 12.5px; font-weight: 700; font-family: inherit;
  font-variant-numeric: tabular-nums; }
.cmp-user-good polygon, .cmp-user.cmp-user-good polygon { fill: var(--good); }
.cmp-user-amber polygon, .cmp-user.cmp-user-amber polygon { fill: var(--amber); }
.cmp-user-warn polygon, .cmp-user.cmp-user-warn polygon { fill: var(--warn); }
.cmp-user-good text, .cmp-user.cmp-user-good text { fill: var(--good); }
.cmp-user-amber text, .cmp-user.cmp-user-amber text { fill: var(--amber); }
.cmp-user-warn text, .cmp-user.cmp-user-warn text { fill: var(--warn); }

/* Domain score dial (0-100 semi-circle gauge) */
.domain-dial { text-align: center; }
.domain-dial-svg { width: 120px; height: 75px; }
.domain-dial-bg { fill: none; stroke: var(--track-bg); stroke-width: 7;
  stroke-linecap: round; }
.domain-dial-fg { fill: none; stroke-width: 7; stroke-linecap: round;
  vector-effect: non-scaling-stroke; }
.domain-dial-good { stroke: var(--good); }
.domain-dial-amber { stroke: var(--amber); }
.domain-dial-warn { stroke: var(--warn); }
.domain-dial-muted { stroke: var(--muted); }
.domain-dial-num { font-size: 22px; font-weight: 700;
  font-family: inherit; font-variant-numeric: tabular-nums; }
.domain-dial-num.domain-dial-good { fill: var(--good); }
.domain-dial-num.domain-dial-amber { fill: var(--amber); }
.domain-dial-num.domain-dial-warn { fill: var(--warn); }
.domain-dial-lbl { font-size: 12px; color: var(--text); margin-top: 2px; }
.domain-dial-sub { color: var(--muted); }

/* Domain card layout (Trajectory tab) — uses the same hero language as
   the Today tab's Recovery / Freshness cards. Hero block sits at the
   top of each domain card; secondary metrics stack below. */

.metric-hero { padding: 4px 0 6px; }
.metric-hero-value { font-size: 48px; font-weight: 600;
  letter-spacing: -0.02em; line-height: 1;
  font-variant-numeric: tabular-nums; color: var(--text); }
.metric-hero-value .denom { font-size: 22px; color: var(--muted);
  font-weight: 400; }
.metric-hero-value.good  { color: var(--good); }
.metric-hero-value.amber { color: var(--amber); }
.metric-hero-value.warn  { color: var(--warn); }
.metric-hero-value.muted { color: var(--muted); }
.metric-hero-status { font-size: 14px; font-weight: 500; margin-top: 8px; }
.metric-hero-status.good  { color: var(--good); }
.metric-hero-status.amber { color: var(--amber); }
.metric-hero-status.warn  { color: var(--warn); }
.metric-hero-status.muted { color: var(--muted); }
.metric-hero-sub { font-size: 12.5px; margin-top: 4px; line-height: 1.5; }

/* Recovery hero card absorbs the workout-intensity recommendation as a
   single line below the score, in place of the standalone readiness
   headline card (which used to duplicate the score). */
.hero-recommendation { font-size: 14px; font-weight: 500; line-height: 1.5;
  margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--border-soft); }
.hero-recommendation.good  { color: var(--good); }
.hero-recommendation.amber { color: var(--amber); }
.hero-recommendation.warn  { color: var(--warn); }
.hero-recommendation.muted { color: var(--muted); }

/* Secondary metrics: stacked rows under the hero block. Up to three per
   domain card. Lighter weight than the hero, heavier than a generic data
   row. */
.secondary-metrics { display: grid; gap: 12px; padding-top: 16px;
  margin-top: 14px; border-top: 1px solid var(--border-soft); }
/* Outer grid uses explicit areas so the sublabel always sits in column
   2 directly under the value, regardless of how short the value text
   is. Replaces the prior grid-column: 2 / -1 trick which misaligned
   when the value cell was narrow (e.g. a lone "·" placeholder). */
.secondary-metric { display: grid; grid-template-columns: 200px 1fr;
  grid-template-areas:
    "label value"
    ".     sub";
  column-gap: 12px; row-gap: 4px;
  align-items: baseline; cursor: help; }
.secondary-label { grid-area: label;
  font-size: 13px; color: var(--text); font-weight: 500; }
.secondary-value { grid-area: value;
  font-size: 24px; font-weight: 600;
  font-variant-numeric: tabular-nums; line-height: 1.1;
  color: var(--text); }
.secondary-value.good  { color: var(--good); }
.secondary-value.amber { color: var(--amber); }
.secondary-value.warn  { color: var(--warn); }
.secondary-value.muted { color: var(--muted); }
.secondary-sub { grid-area: sub;
  font-size: 12.5px; color: var(--muted); line-height: 1.45; }

/* Longevity score: hero number with attribution table below */
.longevity-table { width: 100%; font-size: 13px; margin-top: 16px;
  padding-top: 14px; border-top: 1px solid var(--border-soft); }
.longevity-table th { padding: 4px 8px 4px 0;
  font-size: 11px; font-weight: 500; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.06em; }
.longevity-table td { padding: 4px 8px 4px 0; border-bottom: 1px solid var(--border-soft); }
.longevity-table tbody tr:last-child td { border-bottom: none; }

/* Missing-inputs panel under the longevity score when partial / incomplete */
.missing-inputs { margin-top: 14px; padding: 12px 14px;
  background: var(--tile-bg); border: 1px solid var(--border);
  border-radius: 8px; }
.missing-title { font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.06em; margin-bottom: 8px; font-weight: 600; }
.missing-list { font-size: 13px; margin: 0; padding-left: 18px;
  line-height: 1.55; }
.missing-list li { margin-bottom: 4px; }
.missing-list li strong { color: var(--text); }

/* Bloodwork-pending callout (shared by metabolic / body comp domains) */
.bloodwork-pending { margin-top: 14px; padding: 10px 14px;
  background: var(--tile-bg); border: 1px solid var(--border);
  border-radius: 8px; font-size: 12.5px; line-height: 1.5;
  color: var(--text); }
.bloodwork-pending strong { color: var(--text); }

/* REM-anomaly watch callout under sleep domain. Soft-tile chrome
   matching .bloodwork-pending / .missing-inputs; state lives in the
   inline .pill chip the card emits, not on the callout border. */
.rem-watch { margin-top: 14px; padding: 12px 14px;
  background: var(--tile-bg); border: 1px solid var(--border);
  border-radius: 10px; font-size: 12.5px; line-height: 1.5; }
.rem-watch .pill { margin-right: 8px; vertical-align: baseline; }

/* Session-call card (Today tab, position 1). The recovery gate's
   verdict. Tier is communicated by a .tier-indicator chip placed
   inside the card above the headline — never by a coloured border
   or background tint on the card chrome itself. */
.session-call-card { padding: 24px 22px; }

.session-call-headline { font-size: 32px; font-weight: 600;
  letter-spacing: -0.02em; line-height: 1.15; color: var(--text); }

.session-call-substitute { font-size: 15px; color: var(--text);
  margin-top: 10px; line-height: 1.5; }
.session-call-notes { font-size: 13px; margin-top: 6px; line-height: 1.5; }

.session-call-coach-note { margin-top: 18px; padding-top: 14px;
  border-top: 1px solid var(--border-soft);
  font-size: 15px; line-height: 1.55; color: var(--text); }
.session-call-coach-label { font-size: 10.5px; font-weight: 600;
  letter-spacing: 0.10em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 4px; }

.session-call-rationale { margin-top: 18px; padding-top: 14px;
  border-top: 1px solid var(--border-soft); }
.session-call-rationale-title { font-size: 11px; font-weight: 600;
  letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 8px; }
.session-call-rationale-row { display: grid; grid-template-columns: 180px 1fr;
  gap: 12px; align-items: baseline; padding: 4px 0; font-size: 13px;
  line-height: 1.45; }
.session-call-rationale-label { color: var(--text); font-weight: 500; }
.session-call-rationale-note { color: var(--muted); }

.session-call-override { font-size: 11.5px; font-style: italic;
  color: var(--muted); margin-top: 14px; padding-top: 10px;
  border-top: 1px dashed var(--border-soft); }

/* Trajectory tab — 14-day tier history strip */
.tier-history-strip { margin-top: 12px; }
.tier-history-explain { font-size: 12.5px; line-height: 1.5;
  margin-bottom: 10px; }
.tier-strip-svg { width: 100%; height: auto; max-height: 48px;
  display: block; }
.tier-strip-lbl { font-size: 10px; fill: var(--muted);
  font-family: inherit; }
.tier-history-strip rect { cursor: help; }

/* ACWR card */
.acwr-card .acwr-strip { padding: 8px 0 4px; }
.acwr-svg { width: 100%; height: auto; max-height: 110px; display: block; }
.acwr-axis { stroke: var(--border-strong); stroke-width: 1.5;
  vector-effect: non-scaling-stroke; }
.acwr-sweet { fill: rgba(52,199,89,0.18); }
.acwr-stats { display: flex; gap: 24px; align-items: center;
  font-size: 13px; margin-top: 6px; flex-wrap: wrap; }
.acwr-stat-num { font-size: 18px; font-weight: 600;
  font-variant-numeric: tabular-nums; }
.acwr-caveat { margin-top: 10px; font-size: 11.5px; font-style: italic;
  line-height: 1.5; }

/* (Longevity score uses the shared .metric-hero / .longevity-table
   styles defined above.) */

/* (HR-at-volume now annotates each muscle row inside
   .bar-status via .bar-hr — see above. The standalone hr-divergence
   block under card_strength was removed when the signal moved to
   the per-muscle volume card.) */

/* Risk flags panel — two-row layout per flag: label + pill on the top
   row, hint spanning the full width on the second. Predictable
   alignment regardless of label length. */
.risk-flags-list { display: grid; gap: 0; }
.risk-flag-row { display: grid; grid-template-columns: 1fr auto;
  column-gap: 12px; row-gap: 4px; padding: 10px 0;
  border-bottom: 1px solid var(--border-soft); }
.risk-flags-list .risk-flag-row:last-child { border-bottom: none; }
.risk-flag-label { grid-column: 1;
  font-size: 13.5px; font-weight: 600; color: var(--text); }
.risk-flag-row .pill { grid-column: 2; align-self: start; }
.risk-flag-hint { grid-column: 1 / -1;
  font-size: 12px; line-height: 1.5; }
.risk-family { font-size: 12px; margin-top: 12px; padding-top: 10px;
  border-top: 1px solid var(--border-soft); line-height: 1.5; }

/* responsive */
@media (max-width: 720px) {
  .page { padding: 20px 14px 50px; }
  .card { padding: 16px 16px; }
  .hero { grid-template-columns: 1fr; }
  .rings { grid-template-columns: repeat(2, 1fr); }
  .neat-stats { grid-template-columns: 1fr; gap: 10px; }
  .load-summary { grid-template-columns: repeat(2, 1fr); gap: 12px; }
  .load-summary-value { font-size: 18px; }
  .sleep-hero { grid-template-columns: 1fr; gap: 14px; }
  .sleep-row { grid-template-columns: 12px 1fr; gap: 8px; }
  .sleep-row-value { grid-column: 2 / span 1; }
  .practices { grid-template-columns: 1fr; }
  .driver-row { grid-template-columns: 110px 1fr 50px; gap: 8px; font-size: 12px; }
  .bar-row { grid-template-columns: 1fr; gap: 4px;
    padding: 8px 0; border-bottom: 1px solid var(--border-soft); }
  .bar-label { font-size: 13px; font-weight: 500; }
  .bar-value { display: flex; justify-content: space-between;
    font-size: 12px; }
}
@media (max-width: 720px) {
  .cardio-grid { grid-template-columns: 1fr; }
  .readiness-row { grid-template-columns: 1fr; gap: 12px; }
  .longevity-row { grid-template-columns: 1fr; gap: 16px; }
  .risk-flag-row { grid-template-columns: 1fr; gap: 4px; }
  .vo2-headline { flex-direction: column; align-items: flex-start; gap: 2px; }
}
@media (max-width: 480px) {
  .vitals-spark-col { display: none; }
  .metric .value { font-size: 40px; }
  .practice .big { font-size: 24px; }
  .longevity-table th:nth-child(3), .longevity-table td:nth-child(3) { display: none; }
}
"""


# ---------- JS (inline, no deps) ----------

INLINE_JS = r"""
(function() {
  // -------- tabs --------
  function selectTab(name) {
    document.querySelectorAll('.tab').forEach(function(t) {
      t.setAttribute('aria-selected', t.dataset.tab === name ? 'true' : 'false');
    });
    document.querySelectorAll('.tab-panel').forEach(function(p) {
      p.setAttribute('data-active', p.dataset.tab === name ? 'true' : 'false');
    });
    try { history.replaceState(null, '', '#' + name); } catch(e) {}
  }
  document.querySelectorAll('.tab').forEach(function(t) {
    t.addEventListener('click', function() { selectTab(t.dataset.tab); });
  });
  var initial = (location.hash || '#today').slice(1);
  var validTabs = ['today', 'trajectory', 'workout'];
  if (validTabs.indexOf(initial) === -1) initial = 'today';
  selectTab(initial);

  // -------- tooltips for [data-tip] and .term --------
  var tt = document.createElement('div');
  tt.className = 'tooltip';
  document.body.appendChild(tt);

  function showTip(target, evt) {
    var text = target.getAttribute('data-tip');
    if (!text) {
      var dt = target.closest('[data-tip]');
      if (dt) text = dt.getAttribute('data-tip');
    }
    if (!text) return;
    tt.textContent = text;
    tt.classList.add('show');
    moveTip(evt);
  }
  function hideTip() { tt.classList.remove('show'); }
  function moveTip(evt) {
    var x = (evt.clientX || (evt.touches && evt.touches[0].clientX) || 0);
    var y = (evt.clientY || (evt.touches && evt.touches[0].clientY) || 0);
    var ttw = tt.offsetWidth, tth = tt.offsetHeight;
    var px = Math.min(window.innerWidth - ttw - 8, x + 14);
    var py = y - tth - 14;
    if (py < 6) py = y + 18;
    tt.style.left = px + 'px';
    tt.style.top = py + 'px';
  }
  function bindTip(el) {
    el.addEventListener('mouseenter', function(e) { showTip(el, e); });
    el.addEventListener('mousemove', moveTip);
    el.addEventListener('mouseleave', hideTip);
    el.addEventListener('touchstart', function(e) { showTip(el, e); }, {passive: true});
  }
  document.querySelectorAll('[data-tip], .term').forEach(bindTip);
  document.addEventListener('touchend', hideTip);
  document.addEventListener('scroll', hideTip, true);

  // -------- interactive training-load chart --------
  var chart = document.querySelector('.load-chart');
  var ltt = document.querySelector('.load-tooltip');
  if (chart && ltt) {
    var series = JSON.parse(chart.getAttribute('data-series'));
    var left = +chart.getAttribute('data-left');
    var right = +chart.getAttribute('data-right');
    var scrub = chart.querySelector('.scrubber');
    var sLine = chart.querySelector('.scrub-line');
    var sCtl  = chart.querySelector('.scrub-ctl');
    var sAtl  = chart.querySelector('.scrub-atl');

    function vbToClient(x) {
      var box = chart.getBoundingClientRect();
      var vb = chart.viewBox.baseVal;
      return box.left + (x / vb.width) * box.width;
    }
    function clientToVbX(clientX) {
      var box = chart.getBoundingClientRect();
      var vb = chart.viewBox.baseVal;
      return ((clientX - box.left) / box.width) * vb.width;
    }
    function showScrub(evt) {
      var clientX = evt.clientX || (evt.touches && evt.touches[0].clientX);
      var vbx = clientToVbX(clientX);
      if (vbx < left || vbx > right) { hideScrub(); return; }
      var t = (vbx - left) / (right - left);
      var idx = Math.round(t * (series.length - 1));
      if (idx < 0 || idx >= series.length) { hideScrub(); return; }
      var d = series[idx];
      var x = left + (idx / Math.max(series.length - 1, 1)) * (right - left);

      sLine.setAttribute('x1', x); sLine.setAttribute('x2', x);
      // place dots
      var vb = chart.viewBox.baseVal;
      var ctls = series.map(function(s){return s.ctl;});
      var atls = series.map(function(s){return s.atl;});
      var tsbs = series.map(function(s){return s.tsb;});
      var vmax = Math.max.apply(null, ctls.concat(atls)) * 1.15;
      var vmin = Math.min.apply(null, tsbs.concat([0])) * 1.15;
      var span = vmax - vmin;
      var bottom = vb.height - 28;
      function y(v){ return bottom - ((v - vmin) / span) * (bottom - 14); }
      sCtl.setAttribute('cx', x); sCtl.setAttribute('cy', y(d.ctl));
      sAtl.setAttribute('cx', x); sAtl.setAttribute('cy', y(d.atl));
      scrub.style.display = '';

      ltt.style.display = 'block';
      ltt.querySelector('.lt-date').textContent = d.date;
      ltt.querySelector('.lt-ctl').textContent  = d.ctl.toFixed(1);
      ltt.querySelector('.lt-atl').textContent  = d.atl.toFixed(1);
      ltt.querySelector('.lt-tsb').textContent  = (d.tsb >= 0 ? '+' : '') + d.tsb.toFixed(1);
      var px = Math.min(window.innerWidth - ltt.offsetWidth - 10,
                        clientX + 14);
      var py = (evt.clientY || (evt.touches && evt.touches[0].clientY) || 0) - ltt.offsetHeight - 14;
      if (py < 60) py += ltt.offsetHeight + 30;
      ltt.style.left = px + 'px';
      ltt.style.top = py + 'px';
    }
    function hideScrub() {
      scrub.style.display = 'none';
      ltt.style.display = 'none';
    }
    chart.addEventListener('mousemove', showScrub);
    chart.addEventListener('mouseleave', hideScrub);
    chart.addEventListener('touchstart', showScrub, {passive: true});
    chart.addEventListener('touchmove',  showScrub, {passive: true});
    chart.addEventListener('touchend',   hideScrub);
  }

  // -------- markdown viewer for the Workout tab --------
  // The workout markdown contains:
  //   # Workout plan — DATE       (dropped: date is in the page header)
  //   Assessment: ./...html       (dropped: we are already on that file)
  //   ## Workout N: TYPE          (becomes a card)
  //   ## Cardio N: ...            (becomes a card)
  //   Date: ___                    (placeholder line at top of card)
  //   Recovery (...): ___         (placeholder line at top of card)
  //   - Exercise: weight x reps   (bullet)
  //     - sub note  (or `  — sub note` with em-dash)
  function renderMarkdownInto(elt, md) {
    elt.innerHTML = '';
    var lines = md.split('\n');
    var i = 0;
    var card = null;
    var ul = null;        // current top-level <ul>
    var lastLi = null;    // last top-level <li> (for nesting sub-bullets)
    function newCard(title) {
      card = document.createElement('section');
      card.className = 'workout-card';
      if (title) {
        var h = document.createElement('h2');
        h.textContent = title;
        card.appendChild(h);
      }
      elt.appendChild(card);
      ul = null;
      lastLi = null;
    }
    function ensureCard() {
      if (!card) newCard(null);
    }
    function ensureUl() {
      ensureCard();
      if (!ul) {
        ul = document.createElement('ul');
        card.appendChild(ul);
      }
    }
    function addPlaceholder(line) {
      ensureCard();
      var ph = card.querySelector('.placeholders');
      if (!ph) {
        ph = document.createElement('div');
        ph.className = 'placeholders';
        // Insert at top, right after the h2 if present
        var h2 = card.querySelector('h2');
        if (h2 && h2.nextSibling) card.insertBefore(ph, h2.nextSibling);
        else card.appendChild(ph);
      }
      var row = document.createElement('div');
      row.className = 'placeholder-row';
      row.textContent = line;
      ph.appendChild(row);
    }
    while (i < lines.length) {
      var raw = lines[i]; i++;
      var line = raw.replace(/\s+$/, '');
      if (!line.trim()) { ul = null; lastLi = null; continue; }

      // Drop the top-level title line and the Assessment link line.
      if (/^#\s+/.test(line) && !/^##/.test(line)) continue;
      if (/^Assessment:/i.test(line)) continue;

      // ## Workout / Cardio section → new card
      if (/^##\s+/.test(line)) {
        newCard(line.replace(/^##\s+/, ''));
        continue;
      }

      // Date: ___  /  Recovery (...): ___  → placeholder rows
      if (/^Date:/i.test(line) || /^Recovery\s*\(/i.test(line)) {
        addPlaceholder(line);
        continue;
      }

      // Sub-bullet: 2+ leading spaces followed by `-` or `—` (em-dash)
      // or `–` (en-dash). Nests under the previous top-level <li>.
      var sub = line.match(/^\s{2,}(?:[-—–])\s*(.*)$/);
      if (sub) {
        ensureUl();
        if (!lastLi) {
          // No parent — render as italic muted item on its own
          lastLi = document.createElement('li');
          ul.appendChild(lastLi);
        }
        var subUl = lastLi.querySelector('ul');
        if (!subUl) {
          subUl = document.createElement('ul');
          subUl.className = 'sub';
          lastLi.appendChild(subUl);
        }
        var sli = document.createElement('li');
        sli.textContent = sub[1];
        subUl.appendChild(sli);
        continue;
      }

      // Top-level bullet
      var top = line.match(/^-\s+(.*)$/);
      if (top) {
        ensureUl();
        lastLi = document.createElement('li');
        lastLi.textContent = top[1];
        ul.appendChild(lastLi);
        continue;
      }

      // Bare prose under a card (e.g. cardio details)
      ensureCard();
      var p = document.createElement('div');
      p.className = 'workout-prose';
      p.textContent = line;
      card.appendChild(p);
      ul = null;
      lastLi = null;
    }
  }
  var mdScript = document.getElementById('workout-md');
  var workoutTab = document.querySelector('.tab-panel[data-tab="workout"]');
  if (mdScript && workoutTab) {
    renderMarkdownInto(workoutTab, mdScript.textContent);
  }
})();
"""
