---
name: workout-coach
description: >
  Reads the requested person's tracker (per-person CSVs under
  <Person>/data/), analyzes recent training state, and writes a pair of
  dated files to plans/<Person>/: a self-contained assessment HTML
  dashboard and a lean workout-plan markdown. Invoked by the `/coach`
  slash command or when the user explicitly asks for coaching, analysis,
  or a new plan. Do NOT trigger on general fitness questions, training
  discussion, logging, or requests unrelated to the tracker.
---

# Workout Coach

**Invocation**: The `/coach` slash command delegates here. You can also be asked directly ("plan my next workout", "how is my training going"). Do not trigger on unrelated fitness chat.

## Who is this for?

Two trackers live in per-person folders inside the workout directory:
- `<Person>/data/` (CSV store: monthly/ + dense + swimming/)
- `<OtherPerson>/data/` (same shape; HealthAutoExport-backed, no swim-lap store unless native XML data exists)

Resolve which person this request is about BEFORE running the script:
- If the user names a person or tracker, use that name.
- If the user uses pronouns or context that clearly refer to one tracker, use that tracker.
- Otherwise ask which tracker/person this is for before proceeding.

Pass the resolved name via `--person <Name>`. Outputs go to `plans/<Person>/` at the workout-tracker root — one dated pair per generation: `plans/<Person>/<YYYY-MM-DD>-assessment.html` (the rich dashboard) and `plans/<Person>/<YYYY-MM-DD>-workout.md` (the lean workout list). Never write one person's plan over the other; never write to the repo root (where the old `./workout_plan - <Person>.md` lived — those files are frozen history). The path resolvers live in `Skills/shared/person_paths.py`: `plans_dir(person)`, `workout_plan_md(person, date)`, `assessment_html(person, date)`. Use them rather than hand-building the paths.

## When NOT to Use

- General fitness questions or training discussion
- Logging a workout (that's the `workout-logger` skill, invoked by `/log`)
- Requests for one-off exercise advice unrelated to the tracker

## Setup

1. Read `../shared/exercises-database.md` for muscle mappings, synergist tags (`+muscle` = 0.5 sets), lengthened-position flags (`◆`).
2. Read `references/training-science.md` and use the Quick Lookup table for each part of your analysis. When `swim_summary` is present in the JSON, also read `references/swim-coaching.md` for SWOLF / SPL / CSS-zone interpretation, retest cadence, and what NOT to say about swim form. When `nutrition_phase` is present AND `current.phase_type == "bulk"`, also read `references/bulking-science.md` for surplus / rate / off-ramp judgment and the binding `coach_action_hint` token semantics.
3. Run `scripts/read_tracker.py --person <Person>` from the workout-tracker root (where `<Person>` is the resolved name, e.g. `<Person>` or `<OtherPerson>`). The script reads the per-person CSVs — `<Person>/data/monthly/YYYY.MM.csv` (per-month workout data), `health_metrics.csv`, `workout_sessions.csv`, `profile.csv`, on XML trackers with recent swims also `swimming/YYYY.MM.{workouts,laps}.csv`, on XML trackers with recent sleep data also `sleep/YYYY.MM.nights.csv`, on any tracker with manual sauna / cold logs also `thermal/YYYY.MM.sessions.csv`, and on any tracker with manual light-therapy logs also `light_therapy/YYYY.MM.sessions.csv` — and returns one JSON blob organised around session-level signals, not raw arrays — `monthly_sessions` (one entry per session-date with TRIMP / load_band / volume / max_hr / is_deload), `recovery` (0-10 score with named drivers), `training_load` (CTL/ATL/TSB), `hr_at_volume_divergence` (per-muscle fatigue flag), `cardio_last_28d` + `cardio_hr_zones_28d`, `swim_summary` (only present when there are swims in the last 28 days), `sleep_summary` (only present when there are sleep nights in the last 28 days — all 6 stage means, efficiency mean + trend, fragmentation, schedule consistency, outlier nights), `thermal_summary` (only present when there are sauna / cold sessions in the last 28 days — heat dose, HSP-threshold adherence, cold dominant type), `light_therapy_summary` (only present when there are light-therapy sessions in the last 28 days — adherence vs. target, per-session dose, light_type / modality distribution), `weekly_volume_per_muscle`, `estimated_1rm`, `progression_summary`, `health_metrics_weekly`, plus `bodyweight_latest` / `bodyweight_trend_kg_per_week`. If the data folder isn't there, the script prints an error — relay it in one line and stop. Don't search the filesystem.

   **Output is compact (no indentation) by default** — saves ~20% of tokens vs pretty-printed. Pass `--pretty` for human inspection.

   **`rows` (the flat per-set list) is off by default** — the script's pre-aggregated keys (`monthly_sessions`, `progression_summary`, `weekly_volume_per_muscle`, `estimated_1rm`, `cardio_last_28d`) cover every coaching use. Pass `--include-rows` only when you genuinely need to dig into individual sets for debugging or unusual cross-sectional questions; expect the JSON to grow ~4x in size.

Each row = one set. Columns: `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR | Active Cal | Total Cal | Elevation (m) | Elapsed`. SESSION is a per-month number merged across rows of the same date.

**TOTAL row carries the strength session's full summary record.** Each per-month CSV closes every strength session with a `TOTAL` row that holds: the session's `Date`, `Volume` (literal sum, not a formula), `Avg HR`, `Active Cal`, `Total Cal`, `Elevation`, `Elapsed`, `Duration` (active workout time), and the `Deload Workout` marker on Notes when applicable. The session's data rows (warmup + working sets) hold per-set data only — their session-level metadata cells are blank. The coach reads these via `monthly_sessions` (which folds in TOTAL-row metadata + `volume`, `is_deload`, plus the per-session TRIMP / load_band); don't sum or scan for the deload marker yourself. Cardio-only sessions have no TOTAL row — each cardio row carries its own per-row metadata directly.

4. From the script's output, identify the **most recent workout** (last date with logged sets). Note which muscle groups it trained and which exercises were performed. Use this as the planning baseline: do not repeat the same primary muscle emphasis in the very next session, and carry forward any exercises where progression was visible. The rest of each session's slots are where variation lives — see §17.

## Output target

All user-facing output goes into **two dated files** under `plans/<Person>/`:

- `plans/<Person>/<YYYY-MM-DD>-assessment.html` — the rich, visual assessment dashboard. Built from the JSON. Self-contained: inline CSS, inline SVG, inline JS where it helps. **No external requests** (no CDN, no web fonts, no remote images, no `<script src>`). Must render identically with Wi-Fi off.
- `plans/<Person>/<YYYY-MM-DD>-workout.md` — the lean workout-plan markdown. Bullets only. No assessment section. Sub-bullet notes only when a remark is genuinely actionable (rules below).

`<YYYY-MM-DD>` is the date the coach generates the plan (today's date in the JSON's `today` field). Each generation writes a fresh dated pair; older pairs stay on disk for scrollback. No `latest-*` symlink — the user opens the newest dated file.

The chat gets one short block: a one-line verdict plus `Wrote dashboard to plans/<Person>/<date>-assessment.html and plan to plans/<Person>/<date>-workout.md (N sessions)`. Nothing else.

### Assessment HTML structure

The dashboard is produced by **`scripts/render_dashboard.py`**. The script owns all HTML, CSS, SVG, and JavaScript. You do not hand-write HTML. You author two inputs and run the renderer.

The dashboard is organised across **three tabs**: Today (operational, "should I train hard?"), Trajectory (longevity, "am I aging well?"), and Workout (the markdown plan, rendered in the same visual style).

**TODAY tab (operational):**
1. **Headline** — your 2-3 sentence plain-English TL;DR.
2. **Hero** — Recovery score + Freshness (TSB) with band-labelled scale strips. **Recovery card absorbs the workout-intensity recommendation** (hard / moderate / easy) as a sub-line under the score; there is no separate "readiness" card to avoid duplicating the number.
3. **Recovery drivers** — diverging-bar chart of z-scores vs the 60-day baseline.
4. **ACWR** — Acute:Chronic Workload Ratio with the Gabbett 0.8–1.3 sweet-spot band shaded.
5. **Activity rings** — strength, Zone 2 cardio, recovery practices, sleep.
6. **NEAT** — 28-day daily-activity rollup.
7. **Training load** — interactive 90-day chart of fitness / fatigue / freshness (CTL / ATL / TSB). Hover or tap shows the scrubber.
8. **Strength progression** — top lifts with sparkline + slope; e1RM and slope column headers have tooltips.
9. **Week over week** — this-wk / last-wk / 4-wk-avg comparison table.

(Per-muscle weekly volume is computed and available in the tracker JSON as `weekly_volume_per_muscle` for coach planning, but is **not rendered on the dashboard** — by user choice it stays internal.)

**TRAJECTORY tab (longevity):**
1. **Longevity score** — 0-100 composite (VO2 percentile, HRV, RHR, sleep regularity, sleep quality, training-load adherence, Zone 2 weekly, body comp, behavioural consistency, strength progression) with per-component attribution. Flagged as **bloodwork-pending** until a lab panel lands.
2. **Cardiorespiratory** — VO2 max with 4-line comparison strip (p50 / p75 / p95 / Attia longevity target by age + sex), HR Recovery 1-min, RHR vs baseline, Zone 2 weekly minutes.
3. **Recovery / autonomic** — HRV (SDNN, labelled — **never compare cross-platform to Whoop / Oura RMSSD**), wrist temp deviation.
4. **Sleep architecture & regularity** — Total, Deep+REM, Efficiency, **Sleep Regularity Index** (Phillips 2017 / Windred 2024 UK Biobank n=60,977 — top quintile = 20-48% lower mortality), REM-anomaly watch (Parkinson surveillance — flag for users with paternal family history).
5. **Body composition** — Bodyweight + trend vs lean-bulk / cutting framing. BF% / VAT / ALMI / BMD are **DEXA-pending**.
6. **Metabolic health** — **Bloodwork-pending**. Per-person foundational panel hints read from `longevity_state` (vegan micronutrient set, PrEP renal/BMD monitoring, vitamin D winter window, etc.).
7. **Centenarian decathlon framing** — Attia's 8-capability framework. Targets only; user logs tests manually.
8. **Behavioral consistency** — Active days / 28, SRI, ACWR.
9. **Health vitals** — full table (HRV, RHR, wrist temp, VO2max, bodyweight) with sparklines.
10. **Sleep** — detail card with stage stack, schedule consistency, fragmentation, respiratory rate, breathing disturbances, outlier nights.
11. **Recovery practices** — sauna / cold / light therapy sub-cards.
12. **Personalized risk flags** — reads `<Person>/data/longevity/state.md` + `profile.md` for active conditions, meds, monitoring due dates, family-history surveillance. Renders "no profile on file" for people without a `longevity/` directory.

Every card with actionable signal carries a **Coach callout** below the data: blue left-border, "Coach" label, action-focused one-liner. The renderer enforces copy rules: no em-dashes, ≤ 280 characters per card string, ≤ 560 for the headline. Render fails fast on violations.

The rendering spec, coach-reads schema, validation rules, and tooltip catalog all live in **`references/assessment-dashboard.md`**.

### Workout-plan markdown structure

```
# Workout plan — <YYYY-MM-DD>
Assessment: ./<YYYY-MM-DD>-assessment.html

## Workout 1: <TYPE>
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- <general warm-up>: e.g. Jumping Jacks: 50
- <activation matched to the day>: e.g. Arm Circles: 20
- Exercise: weight × reps (or `///`-separated sets for weighted)
- Exercise: …
  — optional one-line sub-bullet note (rare)
- …

## Workout 2: <TYPE>
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- <general warm-up> + <activation>
- …

## Cardio 1: Zone 2 (optional, only if behind §10 target)
- HR target, duration, brief format

## Cardio 2: Intervals (optional)
- Work/rest structure
```

**No `## Report` section. No tables. No "Why this plan" block** — the dashboard's coach's-read lines (per card) replace it.

The `Date:` line ends with a trailing backslash (`Date: ___\`) — a Markdown hard line break — so `Date:` and `Recovery:` render on separate lines in markdown previewers instead of collapsing into one paragraph. Keep them on separate lines (the visual break aids mid-workout filling). The recovery placeholder is parse-shaped on purpose: the user replaces each blank with the logger grammar (`sauna 12min dry`, `cold 30s shower`, `rlt 5min`) or leaves that modality blank.

Write both files in one pass at the end. Don't stream sections to chat while thinking.

## Data Reading Strategy

`scripts/read_tracker.py` handles all the quirks (date normalization, empty-row streaks, case-insensitive grouping, numeric casting, deload detection, cardio categorization) and emits a single JSON blob. Call it once at the start of `/coach`. Don't re-read the CSV store inline unless you're debugging something the script can't see.

What the JSON contains:

**Source + capabilities (read first to gate sections):**
- `data_source`: `xml` (Apple's zipped XML) or `health_auto_export` (HealthAutoExport ZIP). Trust this string; don't override based on populated fields.
- `capabilities`: per-source feature map (`hrv`, `wrist_temp`, `resting_hr_daily`, `walking_hr`, `sleep_stages`, `sleep_breath_dist`, `sleep_nights`, `exercise_min_daily`, `per_workout_hr_strength`, `thermal_log`, `light_therapy_log`). **False = structurally unsupported.** Gate report sections on this, not on null fields. Native XML and HealthAutoExport both expose the full recovery, sleep, and per-workout-HR surface. `sleep_nights` indicates the dedicated per-night CSV store is available — when True, expect a `sleep_summary` block with the full sleep architecture; when False, sleep details are limited to the headline Total/Deep/REM on `health_metrics_weekly`. `thermal_log` and `light_therapy_log` are always True — sauna + cold + light therapy are manual-/log-only, not source-dependent — but the actual `thermal_summary` / `light_therapy_summary` blocks are gated on data-presence (rendered only when ≥1 session was logged in the last 28d).
- `auto_cardio_enabled`: bool. True = Apple-recorded runs / hikes / HIIT auto-flow into the monthly sheets.
- `today`: ISO date.
- `estimated_max_hr`, `estimated_rest_hr`: derived once at the top. `max_hr` is the robust high observed Apple max-HR from the last 12 months (p99-style, to avoid one sensor spike) or 208 − 0.7×age fallback if none is observable. `rest_hr` is the 28-day mean of `resting_hr` (or 60 fallback if missing). Used by all HR-zone / TRIMP / load-band math below.

**Strength + cardio sessions (canonical session-level view):**
- `monthly_sessions`: one entry per session-date, sorted asc. Each entry: `{date, exercise_first, session_kind, active_cal, total_cal, elevation_m, elapsed, avg_hr, max_hr, duration_min, volume (strength only), is_deload, trimp, load_band, intensity_pct}`. **This is the canonical session record** — it folds in TOTAL-row metadata (Active Cal, Avg HR, Duration, etc.) AND the per-session TRIMP score + load band. Iterate it directly; don't sum `rows` yourself.
  Mixed-modality dates emit separate entries keyed by `(date, session_kind)`, even though the monthly CSV display-only `SESSION` number is shared across rows on that date.
  - `load_band`: `light` (TRIMP < 50), `moderate` (50–100), `hard` (100–150), `red-line` (>150). Use for one-line session summaries.
  - `intensity_pct`: HRR percent (avg_hr normalised to heart-rate reserve). 50 = Z1, 60-70 = Z2, 70-80 = Z3, 80-90 = Z4, ≥90 = Z5.
  - `is_deload`: True only when the TOTAL row's Notes carries `Deload Workout`.
- `weekly_volume_per_muscle`: `{window_days: 28, current: {muscle: sets_per_week}, landmarks: {muscle: {mv, mev, mav, mrv}}}`. Fractional hard-set count via primary/synergist rules, averaged over the stable `window_days` collection window. **`current[muscle]` is already sets per week.** Compare it directly to weekly landmarks; do not divide by `window_days / 7` again.
- `estimated_1rm`: `{ExerciseName: {current_e1rm_kg, prev_e1rm_kg, best_e1rm_kg, last_date, delta_vs_prev_kg, slope_kg_per_4w, confidence, stalled_sessions, e1rm_history}}`. Epley projection. `e1rm_history` is **omitted by default**; pass `--include-1rm-history` to opt in.
  - `slope_kg_per_4w`: primary trend signal. Treat this as "is this lift trending up?".
  - `confidence`: `high` (last 3 top sets all 3-8 reps), `medium` (mixed), `low`. Soften trend language when `low`.
  - `stalled_sessions`: ≥2 consecutive sessions with |Δe1RM| ≤ 0.5kg — a flat plateau, NOT regression. Flat loads on isolations or comeback lifts are normal; the gate only treats a stall as a reactive-deload trigger when the lift is at/near its best, not trending up, AND corroborated by an independent fatigue signal (see `session_recommendation`).
- `progression_summary`: last vs. previous best working set per exercise.
- `stale_exercises`: top 5 exercises not logged in ≥28 days, sorted newest-stale first. Use for rotation decisions and cautious reintroductions.
- `unknown_exercises`: names not in the database. Surface in **Missing from your tracking**.
- `deloads`: list of dates whose TOTAL row has the `Deload Workout` marker.
- `auto_deload_candidates`: dates where the heuristic detected a deload-like week (≥35% volume drop AND ≥8 bpm avg-HR drop vs prior 4w) that the user **didn't** mark. Surface as a question, not a claim.

**Cardio rollup (28-day window):**
- `cardio_last_28d`: `{sessions, total_minutes, total_distance_km, total_active_cal, non_interval_minutes, interval_sessions}`. Coarse intervals-vs-non-interval split via Notes keywords + avg_hr ≥165 heuristic. **`non_interval_minutes` is NOT a true Zone-2 measurement** — a 3h hike at avg_hr 110 (Z1) lands in the same bucket as a 45min Z2 ride. Treat it as a coarse fallback, not a Z2 number.
- `cardio_hr_zones_28d`: time in HR zones using HRR (Karvonen). `{window_days: 28, total_minutes, z1, z2, z3, z4, z5, z2_by_activity, z2_pct, z3_pct, z4_z5_pct}`. **This is the canonical source for true Zone-2 minutes** (HRR-based, requires per-workout `avg_hr` on cardio sessions). `z2_by_activity` splits Z2 minutes into coarse buckets (`run`, `swim`, `cycle`, `walk_hike`, `other`) so a 5-min swim does not read like the same dose as a 35-min run. **High z3_pct = grey-zone trap** (too much moderate work, too little easy or hard). Polarized = z2_pct + z4_z5_pct dominant; pyramidal = z2 > z3 > z4_z5 cleanly stepping down.

**Daily activity (NEAT — non-exercise activity thermogenesis):**
- `daily_activity_28d`: `{exercise_min_daily_avg, walking_workouts_count, walking_minutes_28d, walking_distance_km_28d, incidental_walks_count, assessment}`. Exercise minutes are Apple's brisk-activity tally when the source provides it. Walking workouts include both intentional walks and short flagged-incidental walks. **`assessment`** is the band the coach acts on: `low` (<15 min/day basis), `moderate` (15-45), `high` (≥45). Basis is `exercise_min_daily_avg` when present, else `walking_minutes_28d / 28` as a NEAT proxy. Use this to distinguish "sedentary then trains" from "active all day and trains" — the cardio prescription differs.

**Recovery + training load (Python-derived signals — use these instead of eyeballing raw metrics):**
- `recovery`: `{score: 0-10|null, confidence: low|medium|high, drivers: [...]}`. Score is a **renormalized weighted average of per-signal personal z-scores**, mapped to [0, 10]. Each signal: z-score against rolling personal baseline + stdev (clamped ±2σ), then `component = 5.0 + z × 2.5`. Composite = weighted average over signals with sufficient sample (≥7 readings in baseline window), weights renormalized to sum to 1.0 over present signals. **5.0 means "average for this person across whatever signals are available"** — *not* "base 5 minus what's missing", so trackers with fewer usable signals aren't structurally biased downward. Signals + raw weights (renormalized at runtime): HRV 0.30 (cap-gated), RHR 0.15 (inverted), sleep total 0.20, sleep deep h 0.05 (cap-gated), sleep REM h 0.05 (cap-gated), wrist temp 0.10 (cap-gated, inverted), HR Recovery 0.10, sleep consistency 0.05 (penalty-only). VO2max trend is **not** in the score (chronic fitness signal — see `vo2max_latest` / `vo2max_trend_per_4w` for the fitness check). Each driver entry: `{metric, component_score (0-10), weight (renormalized), z, recent_avg, baseline_mean, baseline_stdev, n_recent, n_baseline}` for z-scored signals; `{metric, component_score, weight, stdev, threshold, n_recent}` for sleep consistency. Drivers sorted by `|component_score - 5|` descending. `score: null` only when zero signals had sufficient sample. **Use the score directly in §18-style "should I train hard today?" decisions**; cite the most-deviating driver(s) by name (the first ones in the list).
- `training_load`: whole-body `{ctl, atl, tsb, trend_7d}`. CTL = chronic load (42-day EWMA of TRIMP), ATL = acute (7-day EWMA), TSB = CTL−ATL ("form": positive = peaked, negative = under load, ≤−10 = high fatigue risk). `trend_7d` = ΔCTL over the last 7 days (positive = building fitness).
- `training_load_by_modality`: `{all, strength, cardio}` using the same shape as `training_load`. The deterministic strength-session gate uses `strength` when available so a hard run/ride does not automatically block strength loading; coach copy may still mention whole-body fatigue separately.
- `hr_at_volume_divergence`: `{muscle: {slope_bpm_per_4w, n_sessions, hint}}` or a single `systemic_session_hr` entry when many muscles flag together. Volume-weighted regression of strength-session avg HR vs time over 8 weeks, per primary muscle group. Slope ≥+5 bpm/4w = **fatigue or under-recovery** (HR creeping at same load); ≤−5 = improving conditioning. When the systemic entry appears, call it a shared session-HR shift and check bodyweight, heat, deload boundaries, or generic fatigue before changing per-muscle volume.

**Bodyweight:**
- `bodyweight_latest`: `{date, kg}` or null.
- `bodyweight_trend_kg_per_week`: slope over the last 8 clean fasted entries, or null. When `nutrition_phase.current` is present, this same field is scoped to entries on or after the phase start date so a bulk/cut is judged inside its own window.
- `bodyweight_weekly`: ISO-week mean bodyweights for the vitals sparkline. This is a weekly average for visual context, not the phase-status source.

**Longevity Trajectory (Trajectory tab inputs):**
- `longevity_score`: composite 0-100 score with per-component attribution. Shape: `{score, band, label, n_components, components: [{name, score, weight, contribution}, …], bloodwork_pending: True, note}`. Weights renormalize across present components (mirrors `recovery_score`'s missing-signal handling). `band` is `good` / `amber` / `warn`. **Always flagged `bloodwork_pending: True` until a lab panel is on file** — the score is honest about what it doesn't see.
- `longevity_state`: parsed `<Person>/data/longevity/{profile,state,interventions,biomarkers}.md`. `null` when the directory doesn't exist (gracefully degrades for users without a longevity profile). Shape: `{has_profile, dob, age, sex, height_cm, location, family_history: [...], constraints: [...], active_conditions: [...], medications, bloodwork_status, risk_flags: [{key, label, status, hint}, …]}`. `risk_flags` is generated rule-driven from private parsed text; do not hardcode private profile facts in this file.
- `vo2_percentile`: VO2 max resolved against Cooper/ACSM norms by age + sex. Shape: `{value, p50, p75, p95, longevity, label, status}` where `longevity` is Attia's "elite-for-a-decade-younger" target. `null` when sex is unknown (no longevity profile).
- `hr_recovery`: HR Recovery 1-min summary against Cole 1999 NEJM mortality bands. Shape: `{mean_28d, mean_7d, n_readings, band, label, norms}`. `<12 bpm = abnormal` is the 4× CV-mortality cutoff.
- `acwr`: Acute:Chronic Workload Ratio (Gabbett 2016). Shape: `{ratio, acute_7d, chronic_28d_avg, band, label, bands}`. 0.8–1.3 is the sweet spot.
- `sleep_regularity`: SRI (Phillips 2017 / Windred 2024 eLife UK Biobank n=60,977). Shape: `{sri (0-100), n_nights, n_consecutive_pairs, window_days, band, label}`. **`null` when segment-clock timestamps are unavailable (HealthAutoExport-sourced trackers)** — the metric requires Apple XML's segment-level detail.
- `rem_anomaly`: REM-sleep proportion watch for Parkinson surveillance. Shape: `{window_days, n_nights, mean_rem_pct, low_rem_nights, target_min_pct}`. `low_rem_nights` counts nights where REM was below 15% of total sleep.
- `movement_consistency`: Days hitting Apple's 30-min exercise threshold (proxy for Paluch 2022 step-days dose-response). Shape: `{threshold_min, days_this_wk, days_28d, target_per_wk}`.

**Apple Health weekly aggregates:**
- `health_metrics_weekly`: 4 weeks of Mon-anchored aggregates. Each entry: `{week_start, n_days, vo2max, resting_hr, hrv_sdnn, walking_hr, hr_recovery_1min, sleep_total_h, sleep_deep_h, sleep_rem_h, time_in_bed_h, resp_rate, wrist_temp_c, exercise_min}`. Read this for trends; raw daily data is behind `--include-daily-health`. Treat `time_in_bed_h` as source-dependent: on some exports it is derived from the sleep-period span rather than true Apple InBed, so phrase it as continuity / in-bed proxy unless the source explicitly supports InBed.
- `vo2max_latest`: `{date, value}` of the most recent VO2max.
- `vo2max_trend_per_4w`: OLS slope per 4 weeks across all logged VO2max readings.
- `health_metrics_recent`: raw daily rows (last 30). **Only present with `--include-daily-health`** — the weekly rollup is the default lens.

**Sleep architecture (28-day window):**
- `sleep_summary`: dedicated per-night analysis. Key absent when no nights exist in the window. Shape: `{n_nights_28d, means_h: {core, deep, rem, unspecified, awake, total, time_in_bed}, sleep_efficiency_pct: {mean, trend_per_week, source, caveat}, absolute_sleep_note, waso_h_mean, fragmentation: {n_segments_mean, n_segments_trend_per_week}, schedule_consistency: {bedtime_clock_stdev_min, waketime_clock_stdev_min}, outliers: [{date, reason, efficiency_pct, awake_h}, …]}`. Schedule stdevs are **circular** statistics (handle the midnight wraparound), so a 23:50 / 00:10 bedtime pair reports a 20-min stdev, not 23h. `outliers` lists last-14-day nights with efficiency<80% or WASO≥1h. If `absolute_sleep_note` is present, do not call high efficiency a recovery bright spot while total sleep is chronically short.

**Heat + cold exposure (manual /log, 28-day window):**
- `thermal_summary`: dedicated per-session analysis. Key absent when no manual sauna / cold sessions were logged in the last 28d. Shape: `{n_sessions_28d, heat: {n_sessions_28d, n_sessions_per_week, total_minutes_28d, minutes_per_week, minutes_above_hsp_threshold_per_week, hsp_applicable_minutes_per_week, steam_minutes_per_week, hsp_threshold_note, type_distribution, multi_round_sessions_pct, avg_temp_c, avg_session_minutes}, cold: {n_sessions_28d, n_sessions_per_week, type_distribution, paired_with_heat_pct, dominant_type}, adherence: {heat_target_per_week, heat_actual_per_week, heat_status, duration_status}}`. The `heat` and `cold` sub-blocks are independent. `adherence.heat_status` is `below-target` / `on-target` / `above-target` against `profile.csv`'s `sauna_target_per_week` (default 4×/wk). `adherence.duration_status` evaluates dry/banya heat only against the Laukkanen + mechanistic-HSP consensus band (≥80°C AND ≥20min per session); steam is reported as habit heat minutes, not scored as ≥80°C HSP dose.

**Light therapy (manual /log, 28-day window):**
- `light_therapy_summary`: dedicated per-session analysis. Key absent when no manual light-therapy sessions (RLT / near-IR / PBM / blue light) were logged in the last 28d. Shape: `{n_sessions_28d, n_sessions_per_week, total_minutes_28d, minutes_per_week, avg_session_minutes, light_type_distribution, modality_distribution, body_area_distribution, dominant_light_type, dominant_modality, adherence: {target_per_week, actual_per_week, status, target_min_per_session, session_dose_status}}`. `adherence.status` is `below-target` / `on-target` / `above-target` against `profile.csv`'s `light_therapy_target_per_week` (default 3×/wk). `adherence.session_dose_status` is `below-min` / `on-target` / `above-min` against `light_therapy_target_min_per_session` (default 10 min). Drives the `### Light therapy` report section. The store is broad — covers red, near-IR, blue, etc. Don't make claims about wavelength efficacy the data can't support.

**Debug deep-dive (off by default):**
- `rows`: flat per-set list. Pass `--include-rows`. Use only for cross-sectional debugging the pre-aggregated keys can't answer.

**How to read the pre-aggregated signals (no need to dig into `rows`):**

- **Should I train hard today?** → Read `recovery.score` and `training_load.tsb`.
  - `recovery.score ≥ 6.5` AND `tsb ≥ -5` → green light, normal session.
  - `recovery.score 4-6.5` OR `tsb -10..-5` → moderate, hold load (no PR attempts).
  - `recovery.score < 4` OR `tsb ≤ -10` → easy session or active recovery; cite the dominant negative `recovery.drivers` entry by name.
  - Confidence `low` → soften the call and explain the gap only when it is actionable (for example, still building baselines).
- **Volume analysis** → `weekly_volume_per_muscle.current[muscle]` vs `landmarks[muscle]`. `current` is already sets/week; name the band (MEV/MAV/MRV) explicitly and do not divide again.
- **Per-muscle fatigue** → `hr_at_volume_divergence`. Any muscle with `hint == "rising HR at constant volume — fatigue or under-recovery"` should hold or cut load this week. Don't add volume to those groups.
- **Progression trends** → `estimated_1rm[exercise].slope_kg_per_4w`. Positive + `confidence: high` = real progress; soften when `confidence: low`. `stalled_sessions ≥ 2` = real stall, change a variable (deload, exercise variation, rep-range shift).
- **Cardio distribution** → `cardio_hr_zones_28d.z3_pct`. >40% = grey-zone trap (too much moderate). Healthy polarized: `z2_pct + z4_z5_pct` dominant, `z3_pct` low.
- **Most recent session** → `monthly_sessions[-1]`. The TRIMP / load_band / intensity_pct on each session lets you summarize "last session was 'hard' — TRIMP 130, 78% HRR" in one line.
- **Deload triage** → `deloads` (user-marked) vs `auto_deload_candidates` (Python-detected). If `auto_deload_candidates` is non-empty, ask the user: "Did you deload on {date}? The data looks like it (volume −X%, HR −Y bpm)."
- **Apple-Watch metabolic load** → `monthly_sessions[*].active_cal` and `total_cal` give per-session calorie expenditure. Useful for surgery/illness recovery tracking and bodyweight-vs-output cross-checks.

**Anti-patterns (don't write these):**

```
❌ "Recovery score is moderate (4.5/10) with all four signals close to baseline, no anomaly."
   → Lists no specific driver. Coach is naming the score and bailing.
✅ "Recovery 4.5/10 — moderate. Wrist temp +0.11°C (contrib -0.57) and sleep -28 min vs target (contrib -0.47) are the two soft signals; HRV and RHR sit baseline-positive."

❌ "Eight muscle groups show rising HR at constant volume — don't push loads."
   → Generic. Doesn't name the muscles or quantify the slopes.
✅ "Calves +5.2 bpm/4w, glutes +6.6 bpm/4w (limit ≥5 → flagged) — cut a working set on each. Other 6 muscles stable."

❌ "Cardio: 60 min Z2, target 600. Add a session."
   → Misses the daily-activity context.
✅ "Cardio 60 min Z2 vs 600 target. But daily activity 124 min/day exercise minutes (high) — base aerobic load is fine. Add 1 interval session for the VO2max stimulus, not 4 Z2."

❌ "TSB is fine, push hard."
   → Numbers, not adjectives. And "fine" misses bands.
✅ "TSB +3.2 (balanced) → normal load progression; finish rep ranges before bumping."
```

The pattern: every claim about training state cites a specific numeric value from the JSON. If you find yourself writing an adjective ("fine", "moderate", "high"), check whether you also wrote the number. If not, add it.

**Default vs opt-in flags:**
- `--include-rows`: raw per-set list (~6× JSON growth). For unusual cross-sectional questions only.
- `--include-1rm-history`: per-exercise 3-session e1RM history. Default off — `slope_kg_per_4w` already conveys the trajectory.
- `--include-daily-health`: 30-day raw daily Health Metrics. Default off — `health_metrics_weekly` is the default lens.

**Critical format notes (for the rare case you need to read the xlsx directly):**
- Dates are usually `'YYYY-MM-DD'` strings, occasionally `datetime`. The script normalizes; if you bypass it, normalize yourself.
- Numeric columns (kg, Reps, Volume) are often stringified.
- Exercise names have inconsistent casing across sessions. Compare case-insensitively.
- Monthly sheets keep a buffer of empty rows (~2 past months, ~50 current month after a maintenance sweep). Stop after 10 consecutive fully empty rows.

Print the filtered values you actually use; never dump the full `rows` list into the response or the file.

## Two-Layer Approach

**Layer 1 — Internal analysis.** Do all the science in your reasoning. Count sets using the fractional model. Check volume against landmarks. Evaluate exercise selection, lengthened-position coverage, push-pull ratios, progression rates, tendon safety, HRV implications. Consult every relevant § in the training science reference. This is the engine.

**Layer 2 — The file.** Write `workout_plan.md` in plain language. The user trains seriously but is not a sports scientist. No jargon. No section numbers. No citations. Short sentences. If a finding matters, explain what it means for them and what to do about it.

## Writing Rules

These apply to everything written into `workout_plan.md`. No exceptions.

- Short sentences. Vary length.
- No em dashes. Use periods or commas instead.
- No "crucial", "vital", "pivotal", "robust", "comprehensive", "significant", "key role", "landscape", "delve", "multifaceted", "intricate", "serves as", "stands as", "testament to".
- No "Additionally", "Moreover", "Furthermore", "Nevertheless" at sentence starts.
- No rule-of-three lists with near-synonyms.
- No hedging stacks ("could potentially possibly"). Say it or don't.
- No filler ("It is important to note that", "In order to"). Just say it.
- Bold sparingly. Only for exercise names in progression and for section headers beyond H3.
- Say "is" instead of "serves as", "functions as", "represents".
- Be specific. "Your back volume is 12 sets/week, which is enough" not "Your back volume is adequate."

## Phase 1: Assessment HTML dashboard

Goals are fixed: hypertrophy + longevity. Never ask about goals.

The dashboard is produced by **`scripts/render_dashboard.py`**. The script owns all HTML, CSS, SVG, and JavaScript. Your job is to author the **two inputs** and run the renderer.

### Pipeline (5 steps — STRICT ORDER)

The pipeline runs in three logical stages: **A** (Python insights), **B** (LLM authorship), **C** (HTML render). Stage B is split into two sub-steps with a HARD CHECKPOINT between them so the workout plan is always built on top of a finalized assessment, never in parallel with it.

1. **(Stage A) Read tracker data, 6 months back:** `python3 Skills/workout-coach/scripts/read_tracker.py --person <Name> --months 6 > /tmp/tracker.json`. Six months is required so the 90-day training-load chart's 42-day CTL EWMA is properly warmed up before the visible window begins (anything less and the chart shows a cold-start ramp that is not real fitness movement). The Python stage produces every metric, the 5-tier `session_recommendation` gate, `nutrition_phase`, and `swim_summary` — the LLM does not re-derive any of this.
2. **(Stage B1 — assessment FIRST) Author and save `coach_reads.json`.** Read `/tmp/tracker.json`. Draft `headline` + every `cards.*` callout (including `swim_trajectory_callout` when `swim_summary` is present and `nutrition_phase_callout` when `nutrition_phase` is present). Validate copy rules locally as you write — no em-dashes, ≤ 280 chars per card string, ≤ 560 for the headline. Write the file to `plans/<Person>/<date>-coach_reads.json`. **HARD CHECKPOINT: this file MUST exist on disk before step 3 starts.** The file IS the assessment in structured form; the workout step consumes it as input.
3. **(Stage B2 — workout SECOND, built on top) Author `plans/<Person>/<date>-workout.md`.** Re-open `coach_reads.json` from disk (do NOT skip the re-read — it forces the workout plan to honor the saved assessment, not paraphrase it from memory). Quote the `headline` and `cards.session_recommendation_callout` as load-bearing references in the workout opener. Then draft the lean exercise bullets honoring the binding 5-tier `session_recommendation` gate from the tracker JSON. Rules in "Per-workout format in the file" below. **DO NOT draft `workout.md` before `coach_reads.json` is saved.**
4. **(Stage C) Render:**
   ```
   python3 Skills/workout-coach/scripts/render_dashboard.py \
     --tracker /tmp/tracker.json \
     --coach plans/<Person>/<date>-coach_reads.json \
     --workout-md plans/<Person>/<date>-workout.md \
     --out plans/<Person>/<date>-assessment.html \
     --person <Person>
   ```
5. **(Verification) Confirm ordering on disk.** `stat -f "%m %N" plans/<Person>/<date>-{coach_reads.json,workout.md}` — the coach_reads.json mtime must be strictly earlier than the workout.md mtime. If they're inverted, the workout was drafted before the assessment was saved; redo step 3 properly.

### Common manual reruns

If only the coach text needs editing, edit `coach_reads.json` and re-run step 4 — the tracker.json and workout markdown stay valid as long as the JSON shape hasn't changed (it almost never does). The renderer is idempotent and fails fast on copy-rule violations, so the typical loop is: edit → re-run → reload the browser tab.

Use the path resolvers (`plans_dir`, `workout_plan_md`, `assessment_html` in `shared/person_paths.py`) when building these paths. Never hand-assemble. Never write to the repo root.

### Coach-reads schema

```json
{
  "headline": "2-3 sentences. Plain English. The TL;DR. Anchored on longevity trajectory + today's training call.",
  "cards": {
    "// TODAY tab": "",
    "session_recommendation_callout": "one or two sentences. Workout-intensity recommendation (hard / moderate / easy / rest) + why. This is the Today recovery-gate card's gloss; the renderer reads THIS key (not `today_headline`). Falls back to the top-level `headline` if omitted.",
    "today_acwr":          "one sentence. Where in the Gabbett band + what to do.",
    "recovery_drivers":    "one sentence",
    "activity_rings":      "one sentence",
    "training_load":       "one sentence",
    "muscle_volume":       "one sentence",
    "strength":            "one or two sentences (signal + action)",

    "// TRAJECTORY tab": "",
    "trajectory_longevity_score": "one or two sentences. What is pulling the score up, what is pulling it down.",
    "trajectory_cardio":          "one or two sentences. VO2 percentile + Zone 2 / HRR action.",
    "trajectory_recovery":        "one sentence. HRV + wrist temp read.",
    "trajectory_sleep":           "one or two sentences. SRI + Deep+REM + efficiency.",
    "trajectory_body_comp":       "one sentence. Trend + DEXA pending note.",
    "trajectory_metabolic":       "one sentence. Bloodwork priorities personalised to constraints.",
    "trajectory_behavioral":      "one sentence. Active-days + SRI + ACWR composite.",
    "trajectory_risk_flags":      "one or two sentences. Highest-priority surveillance items.",
    "// NOTE: there is no `today_headline` or `trajectory_decathlon` card. The renderer ignores them. The Today intensity gloss is `session_recommendation_callout` above.": "",

    "// Cross-tab (Trajectory)": "",
    "vitals":              "one or two sentences",
    "sleep":               "one or two sentences (architecture + action)",
    "recovery_practices":  "one sentence",

    "// Gated (only when the matching tracker block is present)": "",
    "swim_trajectory_callout":  "one or two sentences. Quote the verdict + 1 actionable focus for the next session. Authored ONLY when tracker JSON contains `swim_summary` (else the card is hidden). The validator does NOT warn when missing because the card may legitimately not render this turn.",
    "nutrition_phase_callout":  "one or two sentences. Quote the `coach_action_hint` token (Continue / Add calories / Slow intake / Consider ending / End now) and the binding 'why'. Authored ONLY when tracker JSON contains `nutrition_phase`. For `current.phase_type == 'bulk'`, read `references/bulking-science.md` first."
  }
}
```

All `cards` keys are optional. Omit a key (or leave it `""`) and that card renders without a coach callout, pure data. Per-card cap stays at 280 characters; headline cap stays at 560. The two gated slots (`swim_trajectory_callout`, `nutrition_phase_callout`) skip the missing-key warning because their cards only render when the matching tracker block is present.

The Trajectory tab's job is to translate raw numbers into **age-cohort context** and **longevity action**: every metric should answer *Where am I? Where should I be? What do I do about it?* — not just describe the data.

### Copy rules — strict

The renderer enforces these. Violation = render fail with one error per offence on stderr.

- **No em-dashes.** Use periods, commas, colons.
- **≤ 280 characters per `cards.*` string.** ≤ 560 for the headline.
- **Action voice is imperative.** "Target 7.5 h tonight" not "you should consider".
- **Action only when actionable.** A card whose state has not moved gets one sentence like "On track, hold course." or "Steady, no change." **Never invent urgency.**
- **Plain English first; abbreviations second.** The renderer auto-wraps known abbreviations (CTL, ATL, TSB, e1RM, MEV, MAV, MRV, SDNN, HRR, RHR, HRV, Z2, Z5, VO2max, HSP, PR, RPE, RIR) in dotted-underline tooltips when they appear. You **may** use them; you should **prefer** the plain-English equivalent ("fitness" over CTL, "freshness" over TSB) when it reads more naturally.

### Substantive analytical rules

Apply these rules when deciding what each `cards.*` string should *say*. The visual rendering follows the dashboard spec; your job is the judgment.

Keep coach lines tight. The user is an established trainee. Surface findings that **changed** since the last block. A card whose state hasn't moved gets a one-sentence read.

### The verdict
2-3 sentences. What's the state of their training right now? Honest. Compute days-since-last-session from `monthly_sessions[-1].date` vs `today` and include the context — "last trained 2 days ago, normal cadence" or "9 days since last session, longer break than usual".

### Last 28 days at a glance

**REQUIRED.** This subsection is a hard template populated directly from JSON keys. Numbers only — no narrative interpretation. Anything you want to say *about* these numbers goes in **What's working** / **What needs fixing**.

```
| Metric | Value |
|---|---|
| Strength sessions | {N} (avg TRIMP {X}, distribution: {N1} light / {N2} moderate / {N3} hard / {N4} red-line) |
| Cardio sessions | {N} ({Z2_min} min Z2, {Z3_min} min Z3, {Z4Z5_min} min Z4–5) |
| Daily activity | {exercise_min_daily_avg} min/day Apple exercise minutes ({assessment}); {walking_workouts_count} walking workouts totalling {walking_distance_km_28d} km |
| Training load | CTL {ctl} / ATL {atl} / TSB {tsb} ({state}) |
| Recovery score | {score}/10 ({confidence} confidence; {improving / drifting / mixed} vs prior 4w) |
```

Where `{state}` is `well rested` (TSB > +5), `balanced` (−5 to +5), `carrying load` (−10 to −5), `fatigued` (−15 to −10), or `high fatigue` (≤ −15).

How to compute the values:
- **Strength sessions**: count `monthly_sessions[*]` with `session_kind == "strength"` AND `date` within the last 28d. Average TRIMP = mean of their `trimp` values (rounded to nearest int). Distribution buckets group by `load_band`. If TRIMP and load_band are null on every session in the window, drop the parenthetical entirely and write only the count: `| Strength sessions | 4 |`. Don't explain the absence; the row stays source-honest without lecturing the user about their data source.
- **Cardio sessions**: count strands with `session_kind == "cardio"`. Z2/Z3/Z4–5 minutes come from `cardio_hr_zones_28d.z2`, `.z3`, `.z4 + .z5`.
- **Daily activity row**: read `daily_activity_28d` directly. If `exercise_min_daily_avg` is null, substitute `{walking_minutes_28d / 28} min/day walking ({assessment})` and drop the "Apple exercise minutes" wording — same row shape, source-honest.
- **Training load**: read `training_load_by_modality.strength` for strength planning when present, with `training_load` as the whole-body context. Pick the `state` band from the table above.
- **Recovery score**: `recovery.score` and `recovery.confidence`. **Trend descriptor (deterministic procedure — replaces the old `↑/↓/→` arrow):**
  1. Walk `health_metrics_weekly`. For each of HRV / RHR (inverted: lower is better) / sleep_total_h / wrist_temp_c (inverted) / hr_recovery_1min / vo2max, compare the most-recent week's value to the mean of the prior 3 weeks.
  2. Score +1 for "better than prior" (delta exceeds 5% relative magnitude in the favorable direction), −1 for "worse" (5% in the unfavorable direction), 0 when |delta| < 5% relative.
  3. Sum across available metrics. Skip metrics that are null on the source.
  4. Sum ≥ +2 → write `improving`. Sum ≤ −2 → write `drifting`. Otherwise → write `mixed`.
  Always commit to one of the three words. Never write `→` or "flat" or "stable" — the descriptor must be one of `improving / drifting / mixed`.

### What's working
Bullet points. Plain language. What they're doing well with specific exercises and numbers. 3-5 items max.

### What needs fixing
Bullet points. Prioritized by impact. Each item: what's wrong, why it matters for them, what to do. 3-5 items max. No technical justification beyond one sentence.

### Are you getting stronger?
For each major exercise with enough data, write **one bulleted line per lift** using the format below. No bold-name paragraphs — bullets only. The substantive rules (slope as primary signal, confidence handling, stalled-sessions surfacing, capability-gated TRIMP commentary) all stay; only the visual shape changes.

```
- **Exercise Name** — Xkg × Y → Xkg × Y, e1RM Akg → Bkg (+Ckg / 4w), {getting stronger / stuck / going backwards}.
  - Last session TRIMP {N} ({band}, {pct}% HRR) — {context vs 28d distribution} (skip when capabilities.per_workout_hr_strength is False for strength rows).
  - Session HR / stall / confidence / annotated-context note when relevant (one sub-bullet, optional).
```

Pull the values from `estimated_1rm[exercise]`:
- `prev_e1rm_kg → current_e1rm_kg` for the immediate delta.
- `slope_kg_per_4w` for the trajectory line (`+Ckg / 4w`). Use this as the **primary signal** — it sees through one-off noise that a last-vs-prev delta can't. If it's null (fewer than 3 sessions, or context-change shrunk the eligible window below 3), drop the trend chunk and rely on the raw delta only.
- `confidence`: when `low` (high-rep top sets), append a sub-bullet like "e1RM is noisy at 12+ reps — push one heavier set to get a cleaner read." Don't claim a trend with confidence on a noisy signal.
- `stalled_sessions ≥ 2` without a deload in the window: surface the stall as a sub-bullet. Suggest one of: bump volume, change variation, or schedule a deload (let Phase 2 decide which).
- `context_change_excluded ≥ 1`: at least one session in the trailing window was tagged by the user as a gym/equipment change. The slope already excludes those rows and confidence is dropped one band by the script. Append a one-line sub-bullet: "Slope reset by gym/equipment change — trend resumes once 3+ sessions log on the new equipment." Don't call the lift stalled or regressing on this basis.

A negative `delta_vs_prev_kg` and a flat-or-negative `slope_kg_per_4w` together on a main lift without a deload around it is a real flag. A negative delta with a positive slope is one bad session — don't over-react.

**Respect user-provided context on outlier rows.** Before flagging a session as a "logging error" / "log typo" / "drop is suspicious", check `progression_summary[exercise].last_notes` (and `--include-rows` if you need the full per-set Notes). If the user has explicitly explained the anomaly (gym change, equipment swap, illness, deload, etc.), acknowledge the context in the sub-bullet — don't second-guess the user's own annotation. Example:

```
- **Cable Lateral Raise** — 15kg × 6 → 4kg × 6, e1RM 18kg → 4.8kg, {context-driven drop, not a stall}.
  - Per the log note, the 04-29 session was at a different gym with an unusual cable ratio — 4 on the dial felt like ~14kg of effort. Don't read the e1RM dip as a real strength regression.
```

The e1RM model still counts the row (data integrity stays); confidence may dip; but the narrative respects the user's own annotation rather than calling it a typo.

**REQUIRED per-session TRIMP sub-bullet.** For each major lift you cover (compound or anchor isolation), append one sub-bullet that uses session-level data from `monthly_sessions[*]`. Pull the most recent strength session that contains this exercise; cite `trimp`, `load_band`, and `intensity_pct`. Compare the TRIMP to the 28d strength-session distribution.

Example:

```
- **Barbell Back Squat** — 70kg × 8 → 70kg × 8, e1RM 88.7kg → 88.7kg (+2.65kg / 4w), getting stronger.
  - Last session TRIMP 87 (moderate, 64% HRR) — within the 28d session-load median; no carryover signal.
```

If TRIMP for the most recent session is in the top 20% of the 28d strength distribution AND the next-day recovery score dropped, surface the carryover explicitly:

```
  - Last session TRIMP 142 (hard, 79% HRR) — top quartile for this block. Recovery score the next morning was 3.8 → cut bench frequency this week, not load.
```

Skip the TRIMP sub-bullet entirely on **strength** sessions when `capabilities.per_workout_hr_strength` is False. Don't write `Last session TRIMP None`. Drop the sub-bullet cleanly. The flag is strength-only; cardio sessions with avg HR can still render per-session TRIMP commentary.

**Optional session-HR sub-bullet.** Skip entirely on strength sessions when `capabilities.per_workout_hr_strength` is False. When the capability is present, the strength session's `avg_hr` is on `monthly_sessions[*]` directly. Use it to append a session-HR comment — but only when it adds signal. Look up §19 for the bands. Examples:

- HR sits in the normal hypertrophy band (130-150 bpm avg) → don't write the sub-bullet. It's not informative.
- HR is creeping above 150 bpm avg on the same load → `Session avg HR 152 bpm (last 4 sessions) — running hot, hold load this block.`
- HR is below 110 bpm avg on a working set → `Session avg HR 105 bpm — effort too light, push reps before adding load.`

For the per-muscle "is HR rising at constant load" call, use `hr_at_volume_divergence[muscle].hint` — that's the version that controls for volume so it's the right read of fatigue accumulating. Don't fabricate a trend if `monthly_sessions` lacks `avg_hr` on the relevant dates.

If data is too limited to judge (history < 2 entries), say that in one sentence above the bulleted list rather than as a bullet for that lift.

**Bodyweight line.** Add one line at the bottom of this section using `bodyweight_latest` and `bodyweight_trend_kg_per_week`:

- Trend null (too few entries or span < 7 days): `Bodyweight: 76.1kg (2026-04-21) — not enough data for a trend yet.`
- Trend between +0.25 and +0.5 kg/week for hypertrophy: `Bodyweight: 76.1kg, +0.3kg/week — on track for hypertrophy surplus.`
- Flat (±0.1 kg/week): `Bodyweight: 76.1kg, flat — surplus too small for hypertrophy (§5 expects +0.25–0.5 kg/week at this bodyweight).`
- Dropping (< -0.1 kg/week): `Bodyweight: 76.1kg, -0.2kg/week — losing weight. Either intentional cut or under-eating; flag it.`
- Gaining fast (> +0.5 kg/week): `Bodyweight: 76.1kg, +0.7kg/week — surplus too aggressive; fat gain is outrunning muscle.`

Cross-reference `references/training-science.md` for the numbers. Don't cite §5 to the user. The entries assume morning/empty-stomach (standing convention); the trend function excludes rows whose Notes flag non-fasted context so intra-day variance doesn't distort the slope.

When an open `nutrition_phase` exists, treat `bodyweight_trend_kg_per_week` as phase-scoped. Do not compare it to pre-phase weight loss/gain; use `nutrition_phase.actuals.rate_kg_per_wk_14d` as the primary phase-status signal and the trend line as supporting context.

Keep the bodyweight signals separate in coach copy:
- `bodyweight_latest` = the newest morning reading.
- `bodyweight_trend_kg_per_week` = phase-scoped trend when a phase is open.
- `nutrition_phase.actuals.rate_kg_per_wk_14d` = primary bulk/cut status number.
- `bodyweight_weekly` / week-over-week averages = noisy context only.

**Data sufficiency thresholds:**
- Progression trend: minimum 3 sessions with the same exercise over 2+ weeks. Below that, state "not enough data" for that exercise.
- Effort caveat: the tracker has no RIR/RPE intake. When you call a lift stalled or use reactive-deload language, explicitly say it is inferred from load/reps and not confirmed by effort-in-reserve data.
- Volume analysis: minimum 2 full training weeks. Below that, report what's visible but caveat the sample size in THE VERDICT.
- Single-session data: skip ARE YOU GETTING STRONGER entirely. State why.
- Bodyweight trend: null from `read_tracker.py` → "not enough data for a trend yet." Don't fabricate a direction.

### Missing from your tracking
List **fixable** gaps the tracker doesn't capture that would help you coach better. One line each. (This draws from §13 internally but don't cite it.) Bodyweight is captured on the `Bodyweight` sheet by the morning /log prompt; don't flag it as missing.

**Do not** list metrics the data source structurally can't provide. Read `capabilities` first: any key that's False is configured-out, not forgotten. These belong in source docs, not in a user-facing to-do list. The user can't go "track HRV better" without switching export tools, and a recommendation that hides the dependency is misleading.

If `unknown_exercises` is non-empty, list those names and suggest the user either fix the typo in their log or add the exercise to `shared/exercises-database.md` — until they do, those sets silently count as zero volume. Likewise, consider surfacing 1-2 entries from `stale_exercises` that seem worth reintroducing or retiring (not the whole list — just ones the user was making real progress on or clearly dropped by accident).

### Deload status

**REQUIRED.** Two lines minimum: cadence + auto-detection status. The auto-detection line is always written, even when empty.

Cadence line — compute weeks-since-last-deload from `deloads[-1]` and `today` (in days, /7):
- < 4 weeks: "On track — last deload was N weeks ago."
- 4-6 weeks: "Deload window open — consider one in the next 1-2 weeks."
- > 6 weeks: "Deload overdue — prescribing one this block."
- empty `deloads`: "No deload on record in the last 3 months — prescribing one."

Auto-detection line — read `auto_deload_candidates`:
- empty: "No auto-detected deload candidates outside your marked deloads."
- non-empty: "Auto-detected candidate: {date} (volume drop + HR drop vs prior 4w) — was this a deload? If yes, mark it via /log {date} deload."

When `auto_deload_candidates` is non-empty, treat the date as a question, not a claim — don't assert it's a deload until the user confirms.

### Recovery state

**REQUIRED.** Lead with `recovery.score` (0–10), then list **every driver** in `recovery.drivers` — already sorted by `|component_score - 5|` descending. No driver is dropped on a magnitude threshold; small deviations are signal too. The agent picks the human-readable label and renders the personal-baseline comparison with units.

Hard template:

```
Recovery {score}/10 — {green / moderate / under-recovered} ({confidence} confidence; {N} contributors).

Drivers (sorted by |z| descending; component score is on the same 0–10 scale as the composite, so 5 = personal average):
- {metric_label}: {recent_value} vs personal baseline {baseline_mean} ± {baseline_stdev} (z {z_signed}, weight {weight}, component {component_score}/10)
- (repeat for every driver in recovery.drivers; never drop one)
```

Score-band labels (unchanged from before — 5/10 still means "average for this person", 4 / 6.5 still mark the hold-loads window):
- `recovery.score ≥ 6.5` → `green`. Normal session.
- `recovery.score 4–6.5` → `moderate`. Hold load, no PR attempts.
- `recovery.score < 4` → `under-recovered`. Cut session intensity. If `monthly_sessions[-1].date` is today or yesterday, prescribe an easy / active-recovery day.
- `recovery.score == null` → too few signals had baseline coverage to compute. Treat as `low` confidence; rely on TSB and recent session history instead.

Metric label mapping (use these strings exactly):
- `hrv_sdnn` → "HRV"
- `resting_hr` → "RHR"
- `sleep_total_h` → "Sleep"
- `sleep_deep_h` → "Sleep depth (deep)"
- `sleep_rem_h` → "Sleep depth (REM)"
- `sleep_consistency_7d_stdev_h` → "Sleep consistency"
- `wrist_temp_c` → "Wrist temp"
- `hr_recovery_1min` → "HR Recovery"

Note: `inverted: true` on a driver (RHR, wrist temp) means the z is already sign-flipped — a positive z means the recent value is *lower* than baseline, which is *favorable*. Render the recent vs baseline numbers literally; the z already encodes "is this good or bad".

Examples of how a driver line should read:

```
HR Recovery: 35.5bpm recent vs personal baseline 37.4 ± 1.4 (z -1.35, weight 0.10, component 1.6/10)
Wrist temp: 36.14°C recent vs personal baseline 35.93 ± 0.17 (z -1.23, weight 0.10, component 1.9/10)
Sleep: 6.31h recent vs personal baseline 6.55 ± 0.65 (z -0.37, weight 0.20, component 4.1/10)
HRV: 44.3ms recent vs personal baseline 42.8 ± 6.2 (z +0.25, weight 0.30, component 5.6/10)
Sleep consistency: 0.58h stdev (threshold 1.5, component 5.0/10)
```

When `recovery.confidence == "low"`, **do not** ask the user to "track HRV better" — that's usually a source limitation or a sample-size gap, not a tracking gap. Skip the gap explanation unless it is actionable; just print the drivers the source provides and note the contributor count in the headline.

### Cardio check
Compare cardio against §10 targets (150 min Zone 2 + ~20 min intervals per week, so roughly 600 min Zone 2 + 4 interval sessions over 28 days). Flag shortfall in plain numbers: "Zone 2: 60 min logged, target ~600 min. Intervals: 0 sessions, target 4."

**Read `cardio_hr_zones_28d.z2` for the Zone-2 number** — that's the true HRR-based Z2 figure when the source supplies per-workout HR on cardio sessions. Only fall back to `cardio_last_28d.non_interval_minutes` when `cardio_hr_zones_28d` is empty (no avg_hr available on any cardio row in the window). Never quote `non_interval_minutes` as the Zone-2 number when `cardio_hr_zones_28d.z2` is present; it counts Z1 hike time as if it were Z2 stimulus and inflates the value. Read `cardio_last_28d.interval_sessions` for the interval count; that field is fine. The total minutes / distance / kcal in `cardio_last_28d` are also correct.

When `cardio_hr_zones_28d.z2_by_activity` is present, use it to qualify the dose. Short swim Z2 minutes count toward total HR-zone exposure, but they are not equivalent to a dedicated 30-45 min run/ride session for the weekly aerobic-base target. Phrase it as "Z2 includes 5 min swim + 35 min run" when activity mix matters.

**REQUIRED daily-activity gate.** Cross-check the shortfall against `daily_activity_28d.assessment` before prescribing cardio. State the call explicitly with the value and band, e.g. "Daily activity 124 min/day (high). Cardio prescription: hold Z2, add 1 interval session for VO2max." Rules:
- `assessment: high` (≥45 min/day basis) AND VO2max trending up → keep cardio prescription minimal; the user is already getting aerobic load passively.
- `assessment: low` (<15 min/day basis) → add a Zone 2 session even if 28d cardio targets are met. The base activity dose is too low.
- `assessment: moderate` (15–45) → standard rule (prescribe to hit §10 targets).
- `assessment: null` → state "Daily activity unknown — using cardio targets only" and fall through to the standard rule.

If `cardio_hr_zones_28d` is populated, call out distribution problems explicitly:

- `z3_pct > 40` → "Grey-zone trap: {N}% of cardio time in Z3. Either go easier (Z1/Z2) or harder (Z4/Z5); the middle is the least productive ratio."
- `z2_pct + z4_z5_pct > 60` → polarized distribution, healthy.
- `z1` dominating with little Z2 → call out that long hikes count as activity but not as the Zone 2 stimulus, then push for an intentional Z2 session.

When `vo2max_latest` is populated, append the VO2max line:

```
VO2max: 48.0 ml/kg/min (2026-04-30), +1.2 / 4 weeks — trending up.
```

If `vo2max_trend_per_4w` is null (fewer than 4 readings over 21+ days), drop the trend chunk: `VO2max: 48.0 ml/kg/min (2026-04-30) — not enough history for a trend yet.`

### Sleep

**REQUIRED when `sleep_summary` is in the JSON.** Skip the section entirely when the key is absent — that means no nights in the last 28 days, and silence is correct. The `### Recovery state` section already names sleep total / deep / REM as recovery_score drivers; this section is the architecture lens — efficiency, fragmentation, schedule consistency — that recovery_score doesn't yet weight.

Hard template (3–5 lines, plain bullets):

- **Stage means (last `n_nights_28d`).** `Total ~{total}h (Core {core} / Deep {deep} / REM {rem} / Awake {awake}h).` Pull from `sleep_summary.means_h`. Round each to 1 decimal. Cite `n_nights_28d` if it's <20 ("over {n} nights — sparse window, treat softly").
- **Efficiency / continuity.** `sleep_summary.sleep_efficiency_pct.mean` is labeled by `sleep_summary.sleep_efficiency_pct.source`. If `source == "derived_sleep_period"`, call it sleep continuity or in-bed proxy, not clinical efficiency. Add the trend chunk when `trend_per_week` is non-null: `(trend {sign}{abs}pp/wk)`. **Anchor**: >85% healthy adult, 80-85% borderline, <80% disturbed. If `absolute_sleep_note` is present, state the short-sleep floor before praising continuity.
- **Schedule consistency.** From `sleep_summary.schedule_consistency`: `bedtime ±{bedtime_clock_stdev_min}min, waketime ±{waketime_clock_stdev_min}min`. Skip the bullet entirely when both stdevs are null (insufficient data). The 28-day stdev is a circular stat — wraps midnight cleanly. **Anchor**: ±30min is tight, ±60min loose, ±90min+ erratic.
- **Outlier flag.** If `sleep_summary.outliers` is non-empty, name the count + reason once: `Flag: {N} night(s) with efficiency<80% or WASO≥1h in the last 14d → look at pre-bed routine.` Don't list all dates; the user can drill in if they care.

Source-honesty rules:
- Don't claim a stage breakdown is "off" relative to population norms (e.g. "Deep should be 20% of total"). Apple's stage classifier is good enough for trend, not absolute. Stick to within-user comparison.
- Don't act on a single bad night. Two-in-fourteen warrants a routine flag; one is noise.
- `Unspecified` stage is Apple's "asleep but stage unknown" bucket. It's part of Total but isn't actionable on its own — don't surface it unless it's >25% of Total (signals stage-classifier failure, usually from a movement-heavy night).
- Per global CLAUDE rule: when `n_nights_28d < 14`, soften every claim ("over {n} nights — early window, the trend isn't stable yet").

Example (filled from a real `sleep_summary` with n_nights_28d=24):

```
- Total ~7.0h (Core 4.3 / Deep 1.0 / REM 1.3 / Awake 0.4h) over 24 nights.
- Sleep continuity mean 88% (trend +0.5pp/wk). Total sleep is the floor; continuity is good but not a substitute for 7h+.
- Bedtime ±18min, waketime ±12min — schedule is tight.
- Flag: 2 nights with efficiency<80% in the last 14d → look at pre-bed routine.
```

### Heat / Cold exposure

**REQUIRED when `thermal_summary` is in the JSON.** Skip the section entirely when the key is absent — that means no sauna / cold sessions logged in the last 28 days (`/log` is the only writer; Apple Health doesn't surface them). Silence is correct; never say "no sauna data" as a finding.

Hard template (3–5 lines, plain bullets):

- **Heat last 28d.** `{heat.n_sessions_28d} sessions ({heat.n_sessions_per_week}/wk, target {adherence.heat_target_per_week}). Avg {heat.avg_session_minutes}min @ ~{heat.avg_temp_c}°C, type {dominant heat type}.` Pull from `thermal_summary.heat`; cite `adherence.heat_status` ("below-target" / "on-target" / "above-target") as a one-word verdict.
- **HSP-induction band.** `{heat.minutes_above_hsp_threshold_per_week} min/wk dry/banya at ≥80°C ≥20min vs ~80 min/wk target — {adherence.duration_status}.` The threshold (≥80°C AND ≥20min per session) applies to dry/banya heat only; steam minutes live in `heat.steam_minutes_per_week` and should be described as heat habit / relaxation minutes, not HSP-grade dose. If `duration_status == "below-HSP-threshold"` AND `heat_status` is on/above target, the call is: "frequency is good, push dry/banya session duration to ~20min if you want the HSP-induction benefit." If both are below, the call is: "frequency first, duration second."
- **Cold.** `{cold.n_sessions_28d} sessions ({cold.n_sessions_per_week}/wk). Dominant: {cold.dominant_type}. Paired with sauna {cold.paired_with_heat_pct}% of the time.` Skip the bullet entirely when `cold` is null. Don't lecture about cold-shower bro-science; the metric is "did the protocol happen," not "is cold beneficial."
- **Multi-round usage.** Optional. If `heat.multi_round_sessions_pct >= 30`, name it: "{pct}% of sessions are multi-round." Useful signal that the user is doing Finnish-style contrast cycles rather than single-pass exposure. Skip otherwise.

Source-honesty rules:
- Multi-round saunas are counted as ONE session, not multiple. A 12+8min two-round day = one session, 20 total heat minutes.
- `cold_air` (sitting outside post-sauna) is a real protocol — don't claim it's "not cold enough" without a temp datapoint. If `cold_temp_c` is set, you can comment.
- Adherence target defaults to 4×/wk (mid-band of the user's interventions.md 4-6 range). User can override via `profile.csv` `sauna_target_per_week`. Treat this as a configured reachable target; `below-target` means below that configured target, not a moral failure or proof the target is reachable in the user's environment. Don't claim a higher target unless the JSON shows it.
- Never moralise about hot-yoga / steam / banya vs dry as "better". The frequency habit is comparable, but the ≥80°C HSP-dose math is dry/banya-only in the JSON.

Example (filled from a real `thermal_summary`):

```
- Heat last 28d: 18 sessions (4.5/wk, target 4) — on-target. Avg 9min @ ~85°C dry.
- HSP-induction band: 0 min/wk dry/banya ≥80°C ≥20min — below-HSP-threshold. Frequency is good; push dry/banya sessions toward ~20min for the HSP benefit.
- Cold: 16 sessions (4.0/wk). Dominant: cold_air. Paired with sauna 88% of the time.
```

### Light therapy

**REQUIRED when `light_therapy_summary` is in the JSON.** Skip the section entirely when the key is absent — that means no light-therapy sessions logged in the last 28 days (`/log` is the only writer; Apple Health doesn't classify these). Silence is correct; never say "no light-therapy data" as a finding.

Hard template (2–4 lines, plain bullets):

- **Light therapy last 28d.** `{n_sessions_28d} sessions ({n_sessions_per_week}/wk, target {adherence.target_per_week}). Avg {avg_session_minutes}min, dominant {dominant_light_type} via {dominant_modality}.` Pull from `light_therapy_summary` top-level + `adherence`; cite `adherence.status` ("below-target" / "on-target" / "above-target") as a one-word verdict.
- **Per-session dose.** `Avg {avg_session_minutes}min vs {adherence.target_min_per_session}min target — {adherence.session_dose_status}.` Skip when `session_dose_status` is `unknown` (no `duration_min` recorded on any row). When `below-min`, the call is: "duration is short; push toward target". When `above-min`, no comment needed.
- **Mix.** Optional. If `light_type_distribution` has more than one entry, name the split (e.g. "split: red+ir 80%, blue 20%"). Otherwise skip.

Source-honesty rules:
- The evidence base for light-therapy dosing is far less settled than sauna's HSP induction. Don't quote sham-controlled effect sizes the JSON doesn't carry; the protocol metric is "did it happen" + "at roughly what duration."
- Wavelength efficacy claims are out of scope. The store captures `light_type` and (optionally) `wavelength_nm`; don't extrapolate "X nm is better than Y nm" from the user's own data.
- Adherence target defaults to 3×/wk + 10min/session. User can override via `profile.csv` (`light_therapy_target_per_week`, `light_therapy_target_min_per_session`). Treat this as a configured reachable target; `below-target` means below that configured target, not proof of poor discipline or lack of access. Don't invent a higher target unless the JSON shows it.

Example (filled from a real `light_therapy_summary`):

```
- Light therapy last 28d: 8 sessions (2.0/wk, target 3) — below-target. Avg 6min, dominant red+ir via cabin.
- Per-session dose: 6min vs 10min target — below-min. Push toward 10min when the cabin has space.
```

### Swim

**REQUIRED when `swim_summary` is in the JSON — author `cards.swim_trajectory_callout` in coach_reads.json.** Skip the callout entirely when the key is absent (the renderer hides the swim card when there's no data, and silence is correct). The renderer surfaces the structured data — totals, 14d-vs-prior-14d pace/SPL/SWOLF deltas, PR badges, the verdict pill. The callout adds judgment that the numbers alone can't supply.

Read `references/swim-coaching.md` for SWOLF / SPL / CSS interpretation, retest cadence, and what NOT to say about swim form.

**What the callout MUST do** (one to two sentences, ≤280 chars):

1. **Quote the 14d verdict** from `swim_summary.window_14d.improvement_verdict` (`improving` / `regressing` / `mixed` / `flat` / `insufficient_data`) in plain English.
2. **Name ONE specific signal** driving the verdict — usually the metric in `delta_vs_prior_14d` with the largest absolute movement (lower = better for pace / SPL / SWOLF). When `pace_pr` or `swolf_pr` is True, mention it.
3. **Give ONE actionable focus** for the next session (e.g., "tempo focus, hold SWOLF" or "log a CSS test"). Don't lecture technique — that's the swim-coaching.md no-go list.

When `swim_summary.css` is null AND `swim_summary.css_test_detected` is non-null, prompt the user via the callout: "Looks like a 400m + 200m pair on {date} — was that a CSS test? Re-log with `CSS test` on the header to write it to your profile." When `swim_summary.css_missing_nudge` is present, prompt a CSS test rather than inventing zones. When `swim_summary.css_retest_due: True`, prompt the retest. When `swim_summary.stroke_outliers` is non-empty, flag the lap once as an Apple Watch misclassification candidate (one Butterfly lap in a Freestyle session = noise, not a stroke change).

Source-honesty rules (from swim-coaching.md):
- Trend over absolute. Don't quote SWOLF / SPL ability brackets unless the user asks.
- Don't lecture technique (catch, body roll, kick mechanics). Coach reads metrics, not video.
- Don't quote SPL to the decimal. "around 8" beats "8.4".
- One outlier lap is almost always Apple Watch noise on a flip turn. Flag it; don't act on it.

Example `swim_trajectory_callout`:

> Mixed read: SWOLF dropped 4.5 (new PR at 21.9) and SPL improved 1.1, but average pace slipped 4s/100m. Stroke economy is up, raw speed is down. Next session: hold the SWOLF win, push tempo on the last 200m.

### Nutrition phase

**REQUIRED when `nutrition_phase` is in the JSON — author `cards.nutrition_phase_callout` in coach_reads.json.** Skip the callout when the key is absent (no open phase row in `<person>/data/nutrition_phases.csv`). When `current.phase_type == "bulk"`, **read `references/bulking-science.md` first** — it's the source of truth for surplus / rate / off-ramp judgment.

The renderer surfaces the structured data — phase type + weeks elapsed, observed-vs-target rate, status pill, the binding `coach_action_hint` action pill, triggered stop signals, the user's pre-committed off-ramp. The callout adds the judgment that the numbers alone can't supply.

**What the callout MUST do** (one to two sentences, ≤280 chars):

1. **Quote the `coach_action_hint`** verbatim (`Continue phase` / `Add calories` / `Slow intake` / `Consider ending` / `End now`) — this is the binding decision token, the same way `session_recommendation.headline` is binding for the workout.
2. **Protein is target-only unless the JSON says otherwise.** If `nutrition_phase.targets.protein_tracking_status == "target_only"`, say the target is configured but intake adherence is untracked. Do not claim protein is high/low based on the target alone.
3. **Name the load-bearing 'why'** — the single signal driving the hint. Observed rate vs target ratio, a triggered stop signal, or weeks elapsed when nothing has triggered (e.g. "week 2, on-track, no signals — hold").
4. **For `consider_ending` / `end_now`**: also quote the matching `stop_signals_triggered[0]` so the user sees which pre-committed line was crossed.

Source-honesty rules (from bulking-science.md):
- The smoothed-endpoint 14d rate filters daily scale noise. Don't quote raw daily fluctuations.
- A single bad week is not a stop signal. Confounders (sleep, sodium, travel, illness) need to be considered first.
- Don't recommend "just eat more" or "just eat less" — surplus/deficit changes go via the structured target on the phase row, refined deliberately over weeks.
- Default lean-bulk cap is 12 weeks. Beyond that, the math almost always favors a planned mini-cut before the next bulk.

Example `nutrition_phase_callout`:

> Continue phase. Week 2 at +0.24 kg/wk against a 0.25 target, no stop signals triggered. Re-evaluate after week 4; if rate creeps above 0.4 kg/wk, dial the surplus back 100-200 kcal.

## Phase 2: Planning (into workout_plan.md `## Plan`)

### Recovery gate — REQUIRED before any plan generation

**Step 1: read `session_recommendation` from the tracker JSON.** The gate is deterministic, derived from the same signals the dashboard surfaces. It returns one of five tiers:

| Tier | label | What the markdown contains |
|---|---|---|
| **A** | `rest` | A rest day (walk + sleep priority). **No strength.** No "modified" strength either — the plan is the rest. |
| **B** | `reactive_deload` | Either a reactive-deload week (cut sets to ~50%, hold loads, rotate the over-MRV muscles), OR a Zone 2 / mobility day (per `substitute.kind`). **No on-top strength session.** |
| **C** | `downgrade` | Planned strength, but pre-modified through `expected_rebound_by_session`: −25% volume on secondary lifts, hold loads, drop the conditioning finisher, no PR attempts. Compound lifts stay at planned volume; isolations halve. Later workout slots may return to normal only if recovery rebounds. |
| **D** | `green` | Normal plan. The rules below (split rotation, double progression, exercise variation) apply unchanged. |
| **E** | `over_recovered` | Normal plan + one-line warning that fitness is bleeding off (TSB has been too positive too long). |

**Step 2: the substitute is BINDING.** Quote the gate's `headline` and the top 3 `rationale` entries in the workout markdown's opening lines so the user sees the signals that drove the call:

```markdown
# Workout plan — 2026-05-24
> Today's call: <headline>
> Why: <rationale[0].note> · <rationale[1].note> · <rationale[2].note>

Assessment: ./2026-05-24-assessment.html
```

**Step 3: build the body from the substitute template.** See `references/substitute-protocols.md` for the canonical content of each tier's markdown (rest day, Zone 2 day, reactive-deload week, modified strength, normal strength).

**Step 4: only Tier D / E use the existing programming rules below.** For Tier A and B the rest of this Phase 2 spec is not consulted — the substitute IS the plan. For Tier C the rules below apply but with the modifications spelled out above.

**Override protocol.** Overrides are allowed only when the user **explicitly** asks to override after seeing the gate's call (e.g. "ignore the rest call, plan strength anyway", "I want to train normally"). Default behavior is to honor the recommendation. Never generate strength on a Tier A or B day on assumption.

When the user explicitly overrides, regenerate the tracker JSON with `read_tracker.py --override-gate`. That normalizes a restrictive A/B/C tier to green/full-volume so the dashboard's "Today's call" card and the per-workout set budget both reflect a normal session, while keeping the original gate rationale visible in `override_message` for honesty. Then author the plan as a normal Tier D block (full budget every session). Do NOT hand-strip the downgrade from a JSON that still says Tier C — that desyncs the dashboard from the plan; use the flag so both agree.

### If the gate is D / E (or C with modifications applied)

If the user specified a session count in the `/coach` message (e.g., `/coach plan 3 sessions`), use it directly. Otherwise, ask in chat: **"How many sessions should I plan?"** — and wait for the answer before writing the file.

Generate that many strength workouts. Tier C: apply the −25% volume / hold loads / no finisher rules to workouts `1..expected_rebound_by_session`. For later workout slots, write normal-volume prescriptions only as conditional on recovery rebounding before that session; if the JSON omits `expected_rebound_by_session`, default to workout 1 only.

### Programming (internal)

**Split rotation:** The user runs a Push/Pull/Legs cycle. To determine the next sessions, look at the last completed workout's type and continue the rotation. Don't analyze the full history to rediscover this. If the last session was Pull, the next sessions are Legs → Push → Pull → Legs. If Push, next is Pull → Legs → Push → Pull. Fixed.

**Repeated split days in one week.** For a 4-session PPL+repeat week (for example PPLP), the repeated day must not be a clone. Preserve at least one actively progressing anchor lift, but vary the second exposure by changing the lead angle/pattern or the isolation slot. Push example: first Push can lead with flat press and triceps pushdown; second Push can lead with incline press and overhead triceps work. Pull example: pair vertical-pull emphasis with horizontal-row emphasis. Legs example: pair squat/leg-press emphasis with hinge/curl/adductor-calf emphasis.

**Progression data:** The Step 4 summary already gives you weights and reps per exercise. Use that directly. Don't re-derive trends by walking through each exercise's history. Apply the double progression rule from §15: if the user hit the top of the rep range, bump weight. If not, same weight, push reps.

**Session duration (set-budget, NOT exercise-count):** strength-session length is driven by total **working sets**, not by how many exercises you list. Session length is `warmup + working_sets × min_per_working_set`, where `min_per_working_set` is per-person (default 3.3, but a dense/short-rest trainee runs faster — lower it via `profile.csv` so a 60-min session budgets MORE sets). Counting exercises is the trap that let sessions silently shrink: the same 7 exercises is 40 min at 2 sets each or 65 min at 4 sets each.

Budget to `target_working_sets` from the tracker JSON (derived from the per-person `session_target_min` and `min_per_working_set`; override both via `profile.csv`). Rules:
- `target_working_sets` is a **floor to hit, not a ceiling to fear**. Land within ±2 of it. Undershooting is the failure mode that under-serves the user: a person sitting below MEV on many muscles (read `weekly_volume_per_muscle.current` vs `landmarks`) needs the budget filled, not a short session. The render validator now counts bodyweight `///` sets correctly and warns on undershoot. Treat that warning as binding outside an explicit deload/downgrade tier.
- **Reserve 2 sets of the budget for core in every strength session** (§24). Budget core
  first, not last — it is the allocation most likely to be silently dropped when the list is
  assembled. 2 of 22 sets is 9% of the budget; it is not the reason a session runs long.
- **The undershoot warning is binding.** If `workout_set_budget_warnings` reports a workout
  under budget outside an explicit deload/downgrade tier, add sets to the main lifts before
  writing the file. A chronically under-filled session is the same failure as a dropped core
  exercise: the tail of the plan silently disappears.
- When many muscles are below MEV, route the budgeted sets to the **lagging** muscles first (per the "Per-muscle volume actions" rule below) rather than piling more onto muscles already at/above MAV. Filling the budget AND fixing the distribution is the same move.
- Prescribe enough working sets to land within ±2 of `target_working_sets`. If you're under, **add sets to existing main exercises (3-4 sets each) before adding new exercises** — don't pad the list with 2-set accessories.
- Default main lifts to 3-4 working sets, isolation/accessory to 2-3. Hitting `target_working_sets` with ~6-8 exercises at 3-ish sets each is the normal shape; do not drop main lifts to 2 sets just to fit more movements.
- Warm-up prep movements and `(warmup)` ramp sets do NOT count toward `target_working_sets`.
- Tier C `downgrade` trims the budget (halve isolation sets); Tier C `hold_load` and Tier D keep the full budget. A deload cuts the budget ~50%. State the resulting set count is intentional when it deviates from target.
- Sanity-check the plan before writing: sum the working sets across the session and confirm it is within ±2 of `target_working_sets`. If not, fix it.

**Warm-up (REQUIRED, bounded).** Every strength workout opens with a brief warm-up — never skip it, and never let it balloon past ~5 min. Two parts:
- **Two prep movements at the very top**, written as plain bullets (they carry no working volume): one general pulse-raiser (`Jumping Jacks`, `Rowing Machine`, or `Arm Circles`) plus one activation matched to the day — push → `Arm Circles` or `Wall Slide`; pull → `Scapular Pull-Up` or `Dead Hang`; legs → `Bodyweight Squat` or `Glute Bridge`. Use canonical catalog names only; do not prescribe equipment the user doesn't own (there are no band movements in the catalog).
- **Ramp sets on the first heavy free-weight compound only.** When the day's first working exercise is a heavy barbell or heavy-dumbbell compound (squat, bench, deadlift, RDL, overhead/DB press), precede its working sets with 1-2 ramp sets marked `(warmup)` at roughly ~50% then ~70% of the working load, low reps (≈5 then ≈3): `Barbell Back Squat: 60kgx5 (warmup) /// 80kgx3 (warmup) /// 95kgx8 /// 95kgx8 /// 95kgx8`. The `(warmup)` marker keeps them out of working-set volume and e1RM. **Skip the ramp sets** when the first lift is a light cable / machine / isolation movement — the two prep movements are enough. Never ramp later compounds; by then the user is warm. Ramp sets and prep movements do not count toward the 8-11 working-exercise target above.

Use Layer 1 analysis plus the training science reference. The reference contains the full rules; apply them:
- **Split selection** (§14): match split to session count. Keep existing split unless there's a problem.
- **Mesocycle structure** (§15): tell the user where they are in the block and what this week's targets are. No static plans.
- **Exercise pairing** (§16): straight sets for compounds, supersets for isolation/accessories when it saves time.
- **Exercise variation** (§17): the week's exercise selection must cover different regions of each major muscle. Anchor compounds where progression is live carry forward; variation plays out in isolation/accessory slots and across blocks.
- **Volume, frequency, overload, push-pull balance, lengthened position, tendon safety, HRV session placement, deload timing**: §1, §5, §6, §7, §8, §9, §11.
- Fix gaps from the report (underdeveloped muscles, missing patterns).
- Maintain exercises the user is already progressing on.
- **Deload handling (§11):** compute weeks-since-last-deload from `deloads[-1]`. If > 6 weeks or `deloads` is empty, the prescribed block IS a deload: reduce each exercise's working-set count to ~50% and keep loads at the last working weight (maintain intensity, cut volume). Tell the user explicitly in "Why this plan" that this block is a deload. In the 4-6 week window, don't force a deload but flag it in the report and offer to plan one if the user asks.
- **Re-entry after long break:** compute days-since-last-session from `monthly_sessions[-1].date`. If > 5 and no deload on record in that gap, treat the first prescribed session as a re-entry — drop one working set per compound, prescribe "leave 2-3 reps in the tank" instead of 1-2. Tendon adapts slower than muscle (§7), so under-load the first session back.
- **Recovery-aware adjustments (§18):** **Lead with `recovery.score`** — it already folds HRV, RHR, sleep total, sleep stages, sleep consistency, wrist temp, and HR Recovery into one renormalized weighted average of personal z-scores (5 = personal average; VO2max trend is **not** in the score — it lives separately in `vo2max_latest` / `vo2max_trend_per_4w` for the cardio check). Apply:
  - `recovery.score < 4` → next session is re-entry: drop one working set per compound, prescribe "leave 3-4 reps in the tank" instead of 1-2. Lead with the dominant negative driver in "Why this plan".
  - `recovery.score 4–6.5` → hold loads, no PR attempts, normal volume. **"Hold loads" is binding on every prescribed working weight — compounds, accessories, isolation, and core alike. Default behavior: copy last session's load forward and let reps drive progression.** The only legal load *increase* is when the user hit the top of the rep range cleanly on the last session AND the recovery / TSB band still permits it (see the TSB-band rule below — bumps are off the table in `balanced` / `carrying load` / `fatigued` / `high fatigue` bands). No exceptions for "small isolation" or "doesn't matter much".
  - `recovery.score ≥ 6.5` → green light, normal programming.
  - `recovery.confidence == "low"`: the score's available signals are still trustworthy, but soften any rule that would otherwise override the deload window. Don't invent triggers from data the source doesn't provide.
  - When `recovery.score < 4` AND `recovery.drivers` has the negative signal persisting (e.g. wrist temp +0.4°C on a multi-week stretch in `health_metrics_weekly`) → flag deload as urgent regardless of `deloads` cadence. Override the standard 4-6 / 6+ week thresholds.
- **Per-muscle fatigue from HR creep (§19):** read `hr_at_volume_divergence`. For any muscle whose `hint == "rising HR at constant volume — fatigue or under-recovery"`, hold or cut volume on that group this block — don't add sets. Surface in the table's Notes column: `Holding {muscle} volume — HR rising at constant load.` For muscles with `hint == "improving conditioning"` you can add a working set if it's also under MAV. Skip this rule entirely when per-workout HR is unavailable and `hr_at_volume_divergence` is empty.
- **Training-load gate (§19, REQUIRED):** for strength prescriptions, read `training_load_by_modality.strength.tsb` when present; fall back to `training_load.tsb` only when no strength TRIMP exists. The band MUST be cited by name in "Why this plan" — e.g. "strength TSB −5.4 → balanced/carrying load boundary; this block holds loads." Mention whole-body/cardio TSB only as secondary fatigue context.

  | TSB | State | Plan rule |
  |---|---|---|
  | > +10 | Well rested / detrained | Bump anchor compounds 2.5kg even if rep range isn't fully completed. State why in the table Notes. |
  | +5 to +10 | Well rested | Normal load progression rules apply. PR attempts allowed if rep ranges are met. |
  | −5 to +5 | Balanced | Hold loads, finish rep ranges first (current default). |
  | −10 to −5 | Carrying load | No PR attempts. Cut top set's RIR target to 2-3 (was 1-2). |
  | −15 to −10 | Fatigued | Drop one working set per compound across the board. |
  | ≤ −15 | High fatigue | Deload regardless of weeks-since-last-deload cadence. State this is a deload in "Why this plan". |

  **Partial-source caveat:** When `capabilities.per_workout_hr_strength` is False, CTL/ATL/TSB are computed only from cardio TRIMPs — strength load is invisible to this metric. Do **not** apply the TSB-band prescription unilaterally on these trackers; cross-check with `recovery.score` and prefer `recovery.score` as the primary fatigue signal. A negative TSB driven by hike load alone is not a deload trigger — a 200-min hike will always look like fatigue to TSB even if the user is well-rested otherwise. Cite the cross-check in "Why this plan" when overriding the band.
- **Per-muscle volume actions (REQUIRED).** Read `weekly_volume_per_muscle.current` and `.landmarks` together and act on each muscle whose current weekly hard-set count sits outside the productive range. These rules bridge what the dashboard surfaces (the per-muscle bars) to what the workout markdown actually prescribes — the dashboard names the imbalance, the plan corrects it.
  - **Status "too much, cut back" (current > MRV, dashboard band red):** the next block MUST cut at least one working set from that muscle's primary movement. If `recovery.score < 6.5` additionally, replace the next scheduled session targeting that group with a Z2 cardio block or a full rest day. Name the affected muscle by name in "Why this plan" and in the relevant card's coach text. This rule overrides any default "add a set when in productive range" reflex the rest of the planning logic might prefer.
  - **Status "not enough" (current < MEV, dashboard band orange):** add one working set to
    that muscle's primary movement next block, *unless* the TSB band is `fatigued` or
    `high fatigue`. **If the muscle has no movement in the session at all, add the movement —
    "add one set to its primary movement" is a no-op when there is no primary movement.**
    Name the muscle in the relevant card's coach text and in "Why this plan".
  - **When more than three muscles are below MEV, rank them** before spending the budget:
    (1) muscles with **no movement anywhere in the week** — they gain the most per set and are
    the ones the split does not naturally serve; (2) muscles furthest below MEV **as a
    fraction of MEV**, not in absolute sets; (3) everything else. Filling the budget and
    fixing the distribution is the same move; a flat "route to the laggards" with ten
    claimants and no ranking routes to none of them.
  - **Core is exempt from this rule.** Its dose is fixed at 2 sets/session by §24 and the Core
    training rule above. Do not add a third core set because core reads below MEV; the fixed
    allocation already clears MEV at 3-4 sessions/week.
  - The two intermediate bands (`productive` green, `pushing limit` yellow) carry no automatic action — let the TSB-band, recovery-score, and HR-creep rules above govern.
  - When a single muscle triggers both this rule and the per-muscle HR-creep rule (`hint == "rising HR at constant volume — fatigue or under-recovery"`), the HR-creep rule's "hold or cut" takes precedence over an "add a set" — i.e. when in doubt, prefer reducing load over adding it.
- **Cardio (§10):** read the Cardio check numbers from the Report. If behind target, add cardio sessions to the plan after the strength sessions. Default weekly target: 3× Zone 2 @ 30-45min + 1× intervals @ 20min. Cap total cardio additions at 4 sessions per `/coach` run — if the user is very behind, note the shortfall and prescribe the max. User can override with `/coach no-cardio` to skip this entirely.

**Stale exercise reintroduction.** When choosing 1-2 entries from `stale_exercises`, use the last reliable working load only if the exercise has multi-session history and no context-change note. If the exercise has a single old session, high-rep noisy e1RM, equipment-change context, or 8+ weeks away, prescribe a conservative submaximal load with normal reps and leave 2-3 reps in reserve. Never infer the restart load from a single stale e1RM projection. Keep the reason in the dashboard coach text; the workout markdown may only say a short action cue such as `first time back; ease in`.

**Core training (§24):** Core is a hypertrophy target and is budgeted in **working sets**, not
exercises. Read §24 before prescribing it.
- **Dose: exactly 2 core working sets in every strength session** (6-8/week across 3-4
  sessions) — **9% of a 22-set budget, ~5 min of a 60-min session**. Hard ceiling 3 sets.
  This is core's whole allocation; it does not take sets from chest, back or legs, and the
  per-muscle volume rule below does not add to it.
- **Placement: core goes INSIDE the isolation/accessory block, supersetted with an unrelated
  isolation movement** (curls, lateral raises, calves, triceps). **Core must never be the
  final bullet of a workout, and must never precede a compound.** Order does not affect
  hypertrophy (§24.2) — but the last slot is where prescriptions go unperformed, and moving
  core ahead of the compounds costs the compounds for no gain.
- **Selection: prescribe core that takes external load** — Kneeling Cable Crunch, Ab Crunch
  Machine, Hanging Leg Raise (dumbbell between the feet), Captain's Chair Knee Raise, Cable
  Reverse Crunch, weighted Roman Chair Sit-Up. A loaded movement is visible to double
  progression (§15) and to `progression_summary`; an unloaded hold is invisible to both.
- **Selection outranks theory when the log disagrees.** Before prescribing a core movement,
  check `progression_summary` and the logs: if a movement has been prescribed before and
  never performed, **do not prescribe it again in the same slot** — change the movement or
  change its position. A prescription with a 0% completion rate delivers 0 sets.
- **Pattern: at least one spinal-flexion movement per session.** Rectus abdominis is the
  hypertrophy target and flexion is how it is loaded through a range of motion. Anti-extension
  and anti-rotation are optional and never substitute for the flexion set.
- **Progression: double progression on load**, exactly as for any isolation lift.
- **Never mark a core set optional.** No "(if you can make it)" on a core bullet.
- Body-fat and visibility framing lives in §24.6 — do not put it in a programming rule.

**Equipment increment grid (REQUIRED).** Loads are prescribed on the equipment's increment grid. Never suggest off-grid weights.
- **Cables:** 5kg steps (5, 10, 15, 20, 25, …). Round to the nearest available plate.
- **Dumbbells:** 1-2kg pair increments depending on the rack. When in doubt, round to the nearest 2kg.
- **Plate-loaded machines:** 5kg per plate side. Round prescribed loads to the nearest 5kg unless the gym is known to have half-plates.
- **Microloading:** for barbells only, and only when the user has explicitly logged microplates before.
Re-read this block before every load suggestion in the workout tables.

**Exercise ordering:** Compounds first, then isolation, then accessories. **Core belongs
inside the isolation block, supersetted with an unrelated isolation movement — never before a
compound, and never the final bullet of the workout** (§24.2). When the core movement shares
equipment with the isolation block (a cable crunch in a session that already has cable work),
place it *within* that equipment group per the grouping rule below.

**Equipment grouping:** Applies within the isolation/accessory block only. Batch cable work together, bench work together, etc. Never reorder compounds or move an isolation before a compound for equipment convenience.

**Priority notes:** In the Notes column, mark high-priority exercises "Priority" and droppable ones "Nice to have". Only when the distinction matters.

### Per-workout format in the file

The workout markdown is a **lean exercise list**, nothing more. No tables. No rationale paragraphs. The "why" lives in the assessment dashboard (and only there). The user trains from this file on their phone in the gym — every line they don't need slows them down.

No em-dashes in workout markdown prose. The only allowed em-dashes are the title separator (`# Workout plan — <date>`) and the indented sub-bullet marker (`  — cue`). In `> Today's call:` / `> Why:` blockquote lines, use a period, comma, semicolon, or colon instead; a prose em-dash will fail the renderer.

Each workout heading is immediately followed by `Date: ___\` (note the trailing backslash — a Markdown hard line break) on its own line, then `Recovery: sauna ___ / cold ___ / rlt ___` on its own line, then a blank line, then the bullets. The backslash keeps the two placeholders on **separate lines** in markdown previewers instead of collapsing into one paragraph — the visual break aids mid-workout filling. The user fills in the date when they actually train (so the session can be logged later without guessing) and replaces each recovery blank only for modalities they performed. Examples: `Recovery: sauna 12+8min 85C dry / cold 30s shower / rlt ___`, `Recovery: sauna 10min 85C / cold ___ / rlt 5min 45C`, `Recovery: skipped`, or leave it blank. `/log` parses each modality independently per the syntax in `workout-logger/references/parsing-rules.md` (`## Sauna + cold exposure (opt-in)` for sauna/cold; `## Light therapy (opt-in)` for RLT / blue light / PBM). Sauna+RLT in one line emits two payload entries — one `thermal`, one `light_therapy` — both keyed to the same date. Both lines apply to every strength workout — cardio sections do not need them.

**Exercise bullets** — one line per exercise. No code fences. Format:
- Bodyweight or single-rep: `Exercise Name: reps` (e.g., `Plank: 45s hold`)
- Weighted: every set separated by `///`:
  - Fixed: `Dumbbell Flat Bench Press: 52kgx10 /// 52kgx10 /// 52kgx10`
  - Range: `Cable Lat Pulldown: 65-70kgx8-10 /// 65-70kgx8-10 /// 65-70kgx8-10`
  - 4 sets = 4 entries. Always.
- Warm-up prep movements: same format, no special marking. Warm-up **ramp sets** on the first heavy compound carry a `(warmup)` marker on each ramp set (see the Warm-up rule in Programming) so they stay out of volume and e1RM.

Canonical exercise names (title case from `shared/exercises-database.md`). No lowercase.

**Per-set inline qualifiers (use sparingly).** When a specific set is optional, aspirational, or different from the rest, attach a short parenthetical to that set directly on the bullet line. Set-level — not exercise-level. Use for:
- An optional last set: `... /// 30kgx10 (if you can make it)`
- An aspirational top set: `... /// 70kgx6 (ideal — leave 1 in tank)`
- A descending set: `40kgx8 (top set) /// 35kgx8 /// 35kgx8`

Keep these terse. One short clause. Don't pile them on every set.

**Exercise-level sub-bullet notes (use even more sparingly — usually 0-2 per workout).** When the entire exercise needs a remark, add an indented sub-bullet starting with an em-dash:

```
- Barbell Back Squat: 70kgx8 /// 70kgx8 /// 70kgx8
  — knees out, drive midfoot
```

A note appears **only** when it answers one of:

| Reason | Example |
| --- | --- |
| Form cue that matters today | `— leave 1-2 in tank` · `— full stretch at the bottom` · `— pause at the top` |
| Safety / injury awareness | `— elbow nagging; cut volume if pain >2/10` · `— skip if back is flaring` |
| One-time deviation from autopilot | `— first time back; ease in` · `— last set is the test set` · `— travel gym: scale 60→35kg` |

A note **must not** contain:
- Comparative history ("last time you did 50kg × 8")
- Rationale for the prescribed weight ("you've been stuck at 40kg, time to push")
- Reintroduction history ("last logged 15 weeks ago") or load rationale ("start light because...")
- Generic exhortation ("push hard, you've got this")
- Restatement of what the bullet already shows (`— do 3 sets` when the bullet shows 3 sets)
- Cross-references to the dashboard ("see your TSB")

Style: lowercase, no period at the end, one short clause, em-dash prefix. The rich "why" lives in the dashboard — the markdown is the action list.

**Soft cap: 0-2 sub-bullet notes per workout.** If you're writing a third, that's the signal that rationale is creeping in. Strip it back. The bullet list itself should be enough to train from.

Full example (markdown — no code fence around it in the actual file):

```
## Workout 1: UPPER PUSH + CORE
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- Jumping Jacks: 50
- Arm Circles: 20
- Dumbbell Flat Bench Press: 28kgx5 (warmup) /// 40kgx3 (warmup) /// 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10
- Shoulder Press Machine: 45kgx8-10 /// 45kgx8-10 /// 45kgx8-10 /// 45kgx8-10
  — leave 1-2 in tank
- Dumbbell Fly: 18kgx10 /// 18kgx10 /// 18kgx10 /// 18kgx10
- Kneeling Cable Crunch: 20kgx12-15 /// 20kgx12-15
- Cable Lateral Raise: 15kgx10 /// 15kgx10 /// 15kgx10 /// 15kgx10
  — superset with the cable crunch above
- Cable Overhead Tricep Extension: 35kgx8-10 /// 35kgx8-10 /// 35kgx8-10 /// 35kgx8-10
```

Two warm-up prep movements + two ramp sets on the first heavy compound, two sub-bullets (the soft cap), sparse per-set parentheticals, the rest clean lines. That's the target density.

**Count the sets in that example: 22 working sets** (4 bench + 4 shoulder press + 4 fly + 2 core + 4 lateral raise + 4 triceps; the two ramp sets and the two prep movements don't count). That is not decoration — it lands exactly on a 22-set budget, and the example is written to be copied. An example that models 18 sets teaches an 18-set session. Two of those 22 sets are core, and note where they sit: inside the cable block, supersetted with an unrelated isolation movement, never the last line.

**Ordering & equipment** (unchanged from before): compounds → isolation → accessories; warmup at the top; group cable/bench/machine work within the isolation/accessory block. The increment grid still applies (cables 5kg, dumbbells 1-2kg pair, plate machines 5kg).

### Cardio sessions (only when prescribed)

Written as their own sections after the strength workouts, not mixed in. Two shapes:

**Zone 2 (steady-state):**

```
### Cardio 1: Zone 2 (30-45 min)

- Treadmill run or outdoor, HR 140-150bpm (65-75% max)
- Target duration: 35 min
- Notes: pair with an off day or separate from leg work by 6-24h (§10 interference)
```

**Intervals:**

```
### Cardio 2: Intervals (20 min total)

- Warmup: 5 min easy
- Work: 5 × 3 min @ HR 165-175bpm (Zone 4-5), 2 min easy between
- Cooldown: 5 min easy
- Notes: not within 24h of a heavy leg session
```

If the user is on target (`Cardio check` in the report shows no shortfall), don't add cardio sessions to the plan. Don't over-prescribe — cap at 4 cardio sessions total per `/coach` run.

### Why this plan — folded into the dashboard

The old free-standing `## Why this plan` block at the bottom of the workout markdown **has been removed**. Its three-signal rationale (Training load / Recovery / HR-at-volume) now lives in the dashboard's per-card coach's-read lines:

- Training-load card's coach's read carries the TSB band citation ("TSB −5.4 (balanced) → hold loads this week").
- Recovery drivers card carries the dominant-driver sentence.
- Strength-progression and per-muscle-volume cards carry the HR-at-volume call when relevant.

This keeps the workout markdown clean (no rationale, just the action list) and surfaces the "why" where it's already visible — on the same card showing the data. The workout markdown links to the dashboard at the top (`Assessment: ./<date>-assessment.html`).

Source-honesty rules still apply to those coach's-read lines:
- If `hr_at_volume_divergence` is empty, omit the call entirely on the strength card. Don't fabricate it.
- If `recovery.drivers` is short, still pick the dominant driver. There's always one.
- TSB citation belongs on the training-load card and is mandatory on both sources (cardio TRIMP alone is enough on HL trackers).

## Common Mistakes

| Failure mode | What goes wrong | Correct behavior |
|---|---|---|
| Re-summing volume that the script already has | Manually adding `rows` for a muscle and re-applying the fractional model | Read `weekly_volume_per_muscle.current[muscle]` directly. The script has already excluded warmups and applied the 1.0/0.5 rule. |
| Ignoring `unknown_exercises` | Volume numbers look low because several logged exercises don't match the database and contribute zero | Surface the list in **Missing from your tracking**. Typos/rename-drift silently under-count volume until fixed. |
| Warmup sets counted as working volume | `Jumping Jacks 1×50` treated as a hard set | Warmup exercises and sets with `(warmup)` in Notes are excluded from hard-set counts. |
| Generic advice when data is thin | "You should probably add more back work" without numbers | State exactly what you can see ("2 sessions, 4 back sets") and what you can't conclude. |
| Progression call on insufficient data | "Bench press is stalling" from 2 data points | Need 3+ sessions over 2+ weeks. Below that: "not enough data to call a trend." |
| Inventing numbers not in the tracker | Estimating weights/reps the user didn't log | Only use data present. Empty field = unknown. |
| Ignoring sheet structure | Reading template sheets or non-`YYYY.MM` sheets | Only read sheets matching the regex. Ignore `Exercises Database` and any `New Month` / `How To Use` templates. |
| Impossible cable weights | Suggesting 12kg or 17kg | Cable increments in 5kg steps. Round to the nearest plate. |
| Scattering equipment | Cable exercises in positions 2, 5, 9 of the session | Batch by equipment within the isolation/accessory block. Never break compound order. |
| Neglecting core | Core absent, or present only as the last bullet, or prescribed as a movement the log shows is never performed | 2 working sets every strength session, inside the isolation block, supersetted, loaded. Never last. Never optional. See §24. |
| Running the same exercises every session | Weekly volume looks fine but regions of each muscle go chronically under-stimulated (§17) | The week's selection must cover different regions per target muscle. Use the `exercises-database.md` tags to pick the second variant. |
| Over-rotating variants every block | No single exercise repeats often enough to read a progression trend | Keep at least one anchor per muscle stable. Rotate 1-2 secondary variants per mesocycle, not the main lifts. |
| Ignoring the deload window | 7+ weeks of continuous blocks because no one flagged it | Compute weeks-since-last-deload from `deloads[-1]`. >6 weeks → block IS a deload. 4-6 weeks → flag in report. |
| Prescribing normal volume after a long break | User took 10 days off, coach plans a full 4-set compound session | Compute days-since-last-session from `monthly_sessions[-1].date`. >5 and no deload → re-entry session with reduced sets and more RIR on the first day back (§7). |
| Re-reading the xlsx inline | Re-deriving row parsing, empty-row stop, date quirks every run | Call `scripts/read_tracker.py` once. Only touch the xlsx directly if debugging something the script can't see. |
| Hardcoding "no cardio" in the plan | Strength-only plan even when user is 150+ min behind §10 target | Cardio-in-plan is the default. Read `cardio_last_28d` from the report and append cardio sessions when behind target (cap 4/run). Honor `/coach no-cardio` if passed. |
| Static plan with no mesocycle context | Weights and reps with no indication of block position | Tell the user where they are in the mesocycle and what this week targets (§15). |
| Missing data from casing mismatch | Searching for "Leg Extension" misses rows logged as "Leg extension" | Compare case-insensitively. |
| Reading empty template rows | Dumping 900+ rows per sheet into context | Stop after 10 consecutive fully empty rows. |
| Breaking on None date | `if row[0] is None: break` stops at the first continuation row | Carry forward the last known date defensively. Only skip when BOTH date and exercise are None. |
| Writing the report or plan inline in chat | Conversation gets flooded; plan is hard to find later | Dashboard + markdown go to `plans/<Person>/<date>-assessment.html` and `plans/<Person>/<date>-workout.md`. Chat gets one verdict line + the two file pointers. |
| Writing one person's plan over another | A dated file in the wrong `plans/<Person>/` folder, or the wrong person's data rendered into the right person's HTML | Resolve the person first; pass `--person <Name>` to `read_tracker.py`; use `person_paths.plans_dir(person)` to build the output path. Never hand-assemble a path. |
| Writing to the old root-level `./workout_plan - <Person>.md` | The lean / HTML split is bypassed; the user opens the wrong file | The old root-level file is frozen history. All new output lands in `plans/<Person>/`. Use the path resolvers in `shared/person_paths.py`. |
| Adding a rationale table under each workout's bullet list | Recreates the old `| # | Exercise | Sets × Reps | Notes |` table that the user explicitly removed; clutters the gym-floor view | The workout markdown is bullets only — no markdown tables. Per-exercise rationale lives in the dashboard's coach's-read lines, not in the workout file. |
| Writing a sub-bullet note on every exercise | Bullet list balloons; the few important notes get drowned out | Sub-bullet notes (`  — …`) are sparse by design (0-2 per workout, 3+ is a red flag). Use them only for: form cue that matters today, safety/injury awareness, or a one-time deviation from autopilot. Strip comparative history ("last time X"), restated rationale, and generic exhortation. |
| Rationale creep in sub-bullet notes | `— last session 50kg × 6, time to push to 52.5` ends up under every other exercise | The bullet itself prescribes the weight. The note explains nothing about the prescription — it's reserved for form, safety, or a single deviation. If the prescription needs justification, put it on the dashboard's strength-progression card's coach's read. |
| Reintroducing a `## Why this plan` block in the workout markdown | Adds 3-4 sentences of rationale to the file the user trains from | The three-signal rationale lives in the dashboard's per-card coach's-read lines now. The workout markdown ends after the last cardio section. |
| Surfacing rationale that mentions "last time" | "Stuck at 40kg — push for 8 reps before bumping" survives into the workout md | Comparative history is banned from the workout markdown. It belonged to the deleted table. Trust the bullets. |
| Dashboard depends on a network resource | `<script src="https://…">`, web font, CDN CSS, remote image | Self-contained file: inline CSS, inline SVG, inline JS only. Verify by opening with Wi-Fi off — must render identically. |
| Dashboard surfaces gamification | "5-week streak!", badges, points, consistency score | The user explicitly rejected gamification. Stay with neutral health + fitness signals. |
| Hardcoding the training-load chart to 60 days (or another non-90 window) | CTL is a 42-day EWMA, so a 60-day window crops out half the mesocycle context | Use a 90-day window for the CTL/ATL/TSB curve. Don't accept smaller windows for "cleaner-looking" charts — the curve becomes uninformative. |
| Ignoring cold-air outdoor temperature when present | `cold_air -2°C × 5min` rendered identically to `cold_air × 5min`; user can't tell a real dose from a habit | Surface `thermal_summary.cold.recent_sessions[*].cold_temp_c` on the Recovery practices card. When `dose_hint == "amber"` (cold_air ≥ 18°C), tag it. Coach's read names a -2°C outdoor session as a real dose. |
| Partial file writes | Streaming sections and forgetting to complete | Build the whole file in memory, then write once. |
| Inventing recovery trends on <4 readings | "HRV improving" called from 2 data points | The `_trend_per_4w` keys are null until ≥4 entries spanning 21+ days. Drop the trend chunk; print the average alone. |
| Reading single-day HRV as signal | One bad night triggers a deload | The `recovery.score` already aggregates 7-day HRV / RHR / sleep / wrist temp / HR Recovery against baselines. Trust the score; don't react to one bad night. For multi-day persistence checks, walk `health_metrics_weekly` (or pass `--include-daily-health` only when the rolling-window inspection genuinely matters). |
| Treating Apple `Walking` workouts as training | Counts a 5-min stroll as a session | The importer flags walks under 15 min as `incidental walk` in Notes. `monthly_sessions` already excludes them; don't re-add them when reading the sheet directly. |
| Bumping load when session HR is creeping up | User over-reaches | For the per-muscle call, use `hr_at_volume_divergence[muscle].hint`. For an absolute-HR check, read `monthly_sessions[*].avg_hr` directly. Note "Holding load — session HR rising at constant volume." |
| Treating source-limited HRV as "not enough data yet" | Implies the user just needs to log more, but the source can't provide HRV at all | Read `capabilities.hrv`. If False, omit the metric (and its sections) entirely. Distinct from "trend is null because <4 readings collected so far". |
| Listing structurally-unsupported metrics in **Missing from your tracking** | User sees a fake to-do list of things to "track" that the data source can't supply | The section is for *fixable* gaps (typos in `unknown_exercises`, dropped exercises, manual notes). Anything False in `capabilities` belongs in source docs, not the user-facing report. |
| Treating auto-cardio rows as duplicates of manually-logged runs | Both /log and the importer write the same run; coach can't tell them apart | Auto-cardio dedupe runs in the importer by (date, exercise, duration ±1 min). Manual entries always win. If you see two rows for the same run on the same date, flag it — the dedupe missed something. |
| Treating an annotated outlier as a typo | The user wrote in Notes that the row reflects equipment / gym / context change; coach calls it "almost certainly a typo" anyway | Read `progression_summary[exercise].last_notes` (or full Notes via `--include-rows`). If a note exists, treat the row as user-acknowledged context, not as an error. Acknowledge the context in the bullet rather than calling it a logging error. |
| Suggesting an off-grid load | "Bump to 67.5kg" on a cable that increments in 5kg | Round to the next legal increment for the equipment (cables 5kg, dumbbells 1-2kg pair, plate machines 5kg). Re-read the equipment block in §3 of training-science before each load suggestion. |
| Bumping non-anchor load in a hold-loads block | Cable Pallof Press 15kg → 20kg in a "hold loads" mesocycle week 1 | The rule applies to every exercise, not just anchor compounds. Copy last session's load forward; only push reps. The only legal increase is when the user hit the top of the rep range cleanly AND the recovery / TSB band still permits it. |
| Defaulting to `→` on the recovery trend | Recovery row reads `4.2/10 (... trend → vs prior 4w)` even when every metric is moving down | Use the `improving / drifting / mixed` descriptor (deterministic procedure under "Last 28 days at a glance"). The arrow is no longer accepted. |
| Calling a deload on TSB alone when strength HR is unavailable | TSB -10.7 from two big hikes triggers a "fatigued" prescription even though strength load is invisible to TSB | When `capabilities.per_workout_hr_strength` is False, CTL/ATL/TSB are computed only from cardio TRIMPs — strength load is invisible. Don't treat a negative TSB as a unilateral deload trigger; cross-check with `recovery.score` and prefer recovery_score as the primary fatigue signal on these trackers. |
| Citing `non_interval_minutes` as Zone-2 minutes | Cardio check section reports `cardio_last_28d.non_interval_minutes` (which is just "cardio time that wasn't intervals") as if it were a real Z2 measurement — a 3h Z1 hike inflates the number | Read `cardio_hr_zones_28d.z2` for true Zone-2 minutes (HRR-based). Use `cardio_last_28d.non_interval_minutes` only as a fallback when `cardio_hr_zones_28d` is empty (no avg_hr on cardio sessions). |
| Skipping `swim_trajectory_callout` when `swim_summary` is present | The renderer surfaces the swim card with structured 14d trend data, but no coach commentary — the user reads numbers without judgment | Gate on `swim_summary` key presence in tracker JSON. When present, author `cards.swim_trajectory_callout` per the `### Swim` block in Phase 1 (verdict + 1 driver + 1 actionable focus). |
| Skipping `nutrition_phase_callout` when `nutrition_phase` is present | The dashboard shows the bulk/cut phase + status pill but no judgment; the binding `coach_action_hint` token reads as ungrounded | Gate on `nutrition_phase` key presence. When present, author `cards.nutrition_phase_callout` per the `### Nutrition phase` block in Phase 1. For `current.phase_type == "bulk"`, read `references/bulking-science.md` first. |
| Drafting `workout.md` before `coach_reads.json` is saved | The workout plan ends up paraphrasing the assessment in parallel instead of building on top of it; the two artifacts can drift | Hard checkpoint: write coach_reads.json to disk FIRST, then re-read it before drafting workout.md. The Pipeline (5 steps) section enforces this; verify via mtime ordering after the run. |
| Skipping the Sleep section when `sleep_summary` is present | Fully-populated sleep architecture (all 6 stages, efficiency, fragmentation, schedule stdev) gets zero coach output; the user only sees the headline Sleep total/Deep/REM lines under `### Recovery state` and misses the efficiency / schedule story | Gate on `sleep_summary` key presence. Write the REQUIRED 3–5 line block per the `### Sleep` template in Phase 1. Skip cleanly only when the key is absent (no nights in 28 days). |
| Skipping the Heat / Cold section when `thermal_summary` is present | The user logged sauna / cold sessions but the coach silently ignores them. Adherence call (on-target / below-target) and HSP-threshold call are exactly the actionable bits the user needs to see. | Gate on `thermal_summary` key presence. Write the REQUIRED 3–5 line block per the `### Heat / Cold exposure` template in Phase 1. Skip cleanly only when the key is absent (no sauna / cold sessions logged in the last 28 days). |
| Skipping the Light therapy section when `light_therapy_summary` is present | The user logged RLT / blue-light sessions but the coach silently ignores them. Adherence + per-session dose are the only actionable bits. | Gate on `light_therapy_summary` key presence. Write the REQUIRED 2–4 line block per the `### Light therapy` template in Phase 1. Skip cleanly only when the key is absent (no light-therapy sessions logged in 28d). |
| Inventing wavelength efficacy claims from light-therapy data | "660nm boosts mitochondrial ATP — push more red-light sessions." Source-honesty fails: the user's tracker only stores whether they did it and roughly how long; it has no individual response data. | Stay in protocol-adherence language: did the session happen, at roughly what duration. Don't extrapolate dose-response from N=user's own log. The reference for wavelength claims is the scientific literature, not the JSON. |
| Treating a context-change row as a real strength regression | Cable Lateral Raise drops from 15kg to 7kg after a gym change; coach flags the lift as "going backwards" with a -32kg/4w slope, even though the user's Notes say "new gym, different cable weights" | Read `estimated_1rm[exercise].context_change_excluded` and `progression_summary[exercise].last_notes`. When `context_change_excluded ≥ 1`, write "Slope reset by gym/equipment change; trend resumes once 3+ sessions logged on the new equipment" instead of calling stall or regression. |
| Trusting recovery `confidence: high` on under-sampled signals | A high-weight signal with `n_recent: 1` (one HR-Recovery reading) inflates confidence to "high" even though the score is hanging on one data point | Confidence is gated on per-signal sample sufficiency in `health.py`. When the JSON shows `confidence: medium` or `low` after a thin recent week, soften any rule that relies on the score band — and cite the under-sampled driver by name. |

## Rules

- Goals fixed. Never ask.
- No generic advice disconnected from their data.
- Don't soften findings.
- If data is too thin, say what you can and can't tell from it.
- One clarifying question max if the tracker is unreadable.
