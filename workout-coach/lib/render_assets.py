"""Static CSS + inline JS used by the dashboard renderer.

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
:root {
  --bg: #f7f7f8;
  --card: #ffffff;
  --border: #ececec;
  --border-strong: #d8d8d9;
  --text: #1c1c1e;
  --muted: #6b6b6f;
  --good: #34c759;
  --amber: #ff9f0a;
  --warn: #ff3b30;
  --accent: #0a84ff;

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
.tab-panel[data-active="true"] { display: grid; gap: 14px; }

/* card */
.card { background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 20px 22px; }
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
  border-top: 1px solid #f0f0f1; }
.coach .label { font-size: 10.5px; font-weight: 600;
  letter-spacing: 0.10em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 4px; }
.coach .text { font-size: 14px; line-height: 1.55; color: var(--text); }

/* tooltip system */
.term, [data-tip] { position: relative; }
.term { border-bottom: 1px dotted var(--muted); cursor: help; }
.tooltip {
  position: fixed;
  background: #1c1c1e; color: #ffffff;
  border-radius: 8px; padding: 10px 12px;
  font-size: 12.5px; line-height: 1.5;
  max-width: 280px; box-shadow: 0 8px 24px rgba(0,0,0,0.22);
  pointer-events: none; opacity: 0; transition: opacity 0.12s;
  z-index: 200;
}
.tooltip.show { opacity: 1; }
.tooltip strong { color: #ffffff; font-weight: 600; }

/* drivers */
.driver-row { display: grid; grid-template-columns: 150px 1fr 60px;
  align-items: center; gap: 12px; padding: 5px 0;
  font-size: 13px; cursor: help; }
.driver-label { color: var(--text); }
.driver-track { position: relative; height: 12px;
  background: #f0f1f3; border-radius: 6px; overflow: hidden; }
.driver-axis { position: absolute; left: 50%; top: 0; width: 1px;
  height: 100%; background: var(--border-strong); }
.driver-fill { position: absolute; top: 0; height: 100%; border-radius: 6px; }
.driver-fill.good { background: var(--good); }
.driver-fill.amber { background: var(--amber); }
.driver-fill.warn { background: var(--warn); }
.driver-fill.muted { background: #c1c1c5; }
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
.neat-stat-status { font-weight: 600; }
.neat-stat-status.good  { color: var(--good); }
.neat-stat-status.amber { color: var(--amber); }
.neat-stat-status.warn  { color: var(--warn); }
.neat-stat-status.muted { color: var(--muted); }

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
.sw-ctl { background: #0a84ff; }
.sw-atl { background: 0; border-top: 2px dashed #ff9f0a; height: 0; }
.sw-tsb { background: linear-gradient(#ff9f0a40, #34c75922); height: 8px !important; }

.load-tooltip { position: fixed; background: #1c1c1e; color: #ffffff;
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
  border-bottom: 1px solid #f4f4f6; }
.muscle-legend-chips { display: flex; gap: 20px; flex-wrap: wrap;
  align-items: center; }
.muscle-legend-chip { display: inline-flex; align-items: center; gap: 6px; }
.muscle-legend-explain { margin-top: 10px; line-height: 1.5; }

.bar-row { display: grid; grid-template-columns: 140px 1fr 240px;
  align-items: center; gap: 14px; padding: 7px 0;
  font-size: 13px; cursor: help; }
.bar-label { color: var(--text); text-transform: capitalize; }
.bar-track { position: relative; height: 10px;
  background: #f1f2f4; border-radius: 5px; }
.bar-tick { position: absolute; top: -2px; height: 14px; width: 1px;
  background: #b9b9bb; }
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
.confdots .dot.off { background: #dadadc; }

/* tables */
table { width: 100%; border-collapse: collapse; font-size: 14px;
  table-layout: fixed; }
th, td { text-align: left; padding: 8px 10px 8px 0;
  border-bottom: 1px solid #f4f4f6; }
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
  padding-top: 14px; border-top: 1px solid #f4f4f6; }
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
  background: #fafafa; border-radius: 6px;
  font-size: 13px; color: var(--text); }
.sleep-outliers.muted { color: var(--muted); }

/* recovery practices */
.practices { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.practice { padding: 14px 16px; background: #fafafb;
  border: 1px solid var(--border); border-radius: 10px; }
.practice .title { font-size: 13px; font-weight: 600;
  color: var(--text); margin-bottom: 8px; }
.practice .big { font-size: 28px; font-weight: 600;
  letter-spacing: -0.01em; line-height: 1; }
.practice .big .unit { font-size: 13px; font-weight: 400;
  color: var(--muted); margin-left: 4px; }
.practice .pill { display: inline-block; padding: 3px 9px;
  border-radius: 999px; font-size: 11px; font-weight: 500;
  margin-top: 8px; }
.pill.good { color: var(--good); background: rgba(52,199,89,0.12); }
.pill.amber { color: var(--amber); background: rgba(255,159,10,0.12); }
.pill.warn { color: var(--warn); background: rgba(255,59,48,0.12); }
.pill.muted { color: var(--muted); background: #eeeeef; }
.practice .detail { color: var(--muted); font-size: 12.5px;
  margin-top: 8px; line-height: 1.5; }
.practice .recent { margin-top: 8px; padding-top: 8px;
  border-top: 1px solid var(--border); font-size: 12px;
  color: var(--muted); }

/* workout tab, each `## Workout N: TYPE` becomes a card. */
.workout-card { background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: 18px 22px; margin-bottom: 14px; }
.workout-card h2 { margin: 0 0 12px; font-size: 17px;
  font-weight: 600; letter-spacing: -0.01em; color: var(--text);
  text-transform: none; }
.workout-card .placeholders { color: var(--muted); font-size: 13px;
  margin-bottom: 14px; padding-bottom: 12px;
  border-bottom: 1px solid #f4f4f6; }
.workout-card .placeholder-row { padding: 2px 0;
  font-family: ui-monospace, "SF Mono", Menlo, Monaco, monospace;
  font-size: 12.5px; }
.workout-card ul { list-style: none; padding: 0; margin: 0; }
.workout-card > ul > li { padding: 5px 0 5px 18px; font-size: 14px;
  color: var(--text); font-variant-numeric: tabular-nums;
  position: relative; line-height: 1.5; }
.workout-card > ul > li::before { content: "•";
  position: absolute; left: 4px; color: var(--muted);
  font-weight: 700; }
.workout-card ul.sub { margin-top: 4px; padding-left: 0; }
.workout-card ul.sub li { padding: 2px 0 2px 18px;
  font-size: 13px; color: var(--muted); font-style: italic;
  position: relative; line-height: 1.5;
  font-variant-numeric: normal; }
.workout-card ul.sub li::before { content: "";
  position: absolute; left: 0; top: 12px; width: 10px;
  border-top: 1px solid #e0e0e2; }
.workout-card .workout-prose { color: var(--muted); font-size: 13px;
  line-height: 1.5; padding: 4px 0; }

footer { max-width: 980px; margin: 0 auto; padding: 28px 20px 80px;
  color: var(--muted); font-size: 12px; }

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
    padding: 8px 0; border-bottom: 1px solid #f4f4f6; }
  .bar-label { font-size: 13px; font-weight: 500; }
  .bar-value { display: flex; justify-content: space-between;
    font-size: 12px; }
}
@media (max-width: 480px) {
  .vitals-spark-col { display: none; }
  .metric .value { font-size: 40px; }
  .practice .big { font-size: 24px; }
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
  var initial = (location.hash || '#assessment').slice(1);
  if (initial !== 'assessment' && initial !== 'workout') initial = 'assessment';
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
