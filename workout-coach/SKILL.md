---
name: workout-coach
description: >
  Reads the requested person's tracker (e.g. ./Workout Tracker - Nihad.xlsx),
  analyzes recent training state, and writes a report plus the next workout plan
  to ./workout_plan - <Person>.md. Invoked by the `/coach` slash command or when
  the user explicitly asks for coaching, analysis, or a new plan. Do NOT trigger
  on general fitness questions, training discussion, logging, or requests
  unrelated to the tracker.
---

# Workout Coach

**Invocation**: The `/coach` slash command delegates here. You can also be asked directly ("plan my next workout", "how is my training going"). Do not trigger on unrelated fitness chat.

## Who is this for?

Two trackers live alongside each other in the workout directory:
- `Workout Tracker - Nihad.xlsx`
- `Workout Tracker - Fabian.xlsx`

Resolve which tracker this request is about BEFORE running the script:
- If the user names a person ("coach Fabian", "plan Nihad's next block"), use that tracker.
- If the user uses pronouns or context that clearly refer to one person ("my bf" / "boyfriend" → Fabian; "I" / "me" / "my" with no other person mentioned → Nihad, since Nihad is the account owner), use that tracker.
- Otherwise ask: **"Is this for Nihad or Fabian?"** before proceeding.

Pass the resolved path to the script. The sidecar `workout_plan.md` follows the same naming — write to `./workout_plan - <Person>.md` (e.g. `./workout_plan - Fabian.md`). Never write one person's plan over the other.

## When NOT to Use

- General fitness questions or training discussion
- Logging a workout (that's the `workout-logger` skill, invoked by `/log`)
- Requests for one-off exercise advice unrelated to the tracker

## Setup

1. Read `../shared/exercises-database.md` for muscle mappings, synergist tags (`+muscle` = 0.5 sets), lengthened-position flags (`◆`).
2. Read `references/training-science.md` and use the Quick Lookup table for each part of your analysis.
3. Run `scripts/read_tracker.py "./Workout Tracker - <Person>.xlsx"` from the current working directory (where `<Person>` is the resolved name, e.g. `Nihad` or `Fabian`). The script returns one JSON blob organised around session-level signals, not raw arrays — `monthly_sessions` (one entry per session-date with TRIMP / load_band / volume / max_hr / is_deload), `recovery` (0-10 score with named drivers), `training_load` (CTL/ATL/TSB), `hr_at_volume_divergence` (per-muscle fatigue flag), `cardio_last_28d` + `cardio_hr_zones_28d`, `weekly_volume_per_muscle`, `estimated_1rm`, `progression_summary`, `health_metrics_weekly`, plus `bodyweight_latest` / `bodyweight_trend_kg_per_week`. If the tracker isn't there, the script prints an error — relay it in one line and stop. Don't search the filesystem.

   **Output is compact (no indentation) by default** — saves ~20% of tokens vs pretty-printed. Pass `--pretty` for human inspection.

   **`rows` (the flat per-set list) is off by default** — the script's pre-aggregated keys (`monthly_sessions`, `progression_summary`, `weekly_volume_per_muscle`, `estimated_1rm`, `cardio_last_28d`) cover every coaching use. Pass `--include-rows` only when you genuinely need to dig into individual sets for debugging or unusual cross-sectional questions; expect the JSON to grow ~4x in size.

Each row = one set. Columns: `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR | Active Cal | Total Cal | Elevation (m) | Elapsed`. SESSION is a per-month number merged across rows of the same date.

**TOTAL row carries the strength session's full summary record.** The sheet closes each strength session with a `TOTAL` row that holds: the session's `Date`, `Volume` (sum formula), `Avg HR`, `Active Cal`, `Total Cal`, `Elevation`, `Elapsed`, `Duration` (active workout time), and the `Deload Workout` marker on Notes when applicable. The session's data rows (warmup + working sets) hold per-set data only — their session-level metadata cells are blank. The coach reads these via `monthly_sessions` (which folds in TOTAL-row metadata + `volume`, `is_deload`, plus the per-session TRIMP / load_band); don't sum or scan for the deload marker yourself. Cardio-only sessions have no TOTAL row — each cardio row carries its own per-row metadata directly.

4. From the script's output, identify the **most recent workout** (last date with logged sets). Note which muscle groups it trained and which exercises were performed. Use this as the planning baseline: do not repeat the same primary muscle emphasis in the very next session, and carry forward any exercises where progression was visible. The rest of each session's slots are where variation lives — see §17.

## Output target

All user-facing output — the report AND the plan — goes into `./workout_plan - <Person>.md` (e.g. `./workout_plan - Nihad.md`), overwriting whatever was there. The chat gets one short block: a one-line verdict plus `Wrote plan to workout_plan - <Person>.md (N sessions)`. Nothing else. Never write to a file without the `- <Person>` suffix, and never write across people.

The file structure:

```
# Workout plan — <YYYY-MM-DD>

## Report
### The verdict
### Last 28 days at a glance
### What's working
### What needs fixing
### Are you getting stronger?
### Missing from your tracking

## Plan

### Workout 1: <TYPE>
**Date:** ___________

<quick list — plain bullets, one line per set>

| # | Exercise | Sets × Reps | Notes |
| - | -------- | ----------- | ----- |
...

### Workout 2: <TYPE>
**Date:** ___________
...

### Cardio 1: Zone 2 (optional, only if behind §10 target)
<plain bullet list with HR target and session notes>

### Cardio 2: Intervals (optional)
<work/rest structure>

## Why this plan
<3-4 sentences>
```

Write the file in one pass at the end. Don't stream sections to chat while thinking.

## Data Reading Strategy

`scripts/read_tracker.py` handles all the quirks (date normalization, empty-row streaks, case-insensitive grouping, numeric casting, deload detection, cardio categorization) and emits a single JSON blob. Call it once at the start of `/coach`. Don't re-read the xlsx inline unless you're debugging something the script can't see.

What the JSON contains:

**Source + capabilities (read first to gate sections):**
- `data_source`: `xml` (Apple's zipped XML — Nihad) or `hl_export` (HLExport text — Fabian). Trust this string; don't override based on populated fields.
- `capabilities`: per-source feature map (`hrv`, `wrist_temp`, `resting_hr_daily`, `walking_hr`, `sleep_stages`, `sleep_breath_dist`, `exercise_min_daily`, `per_workout_hr_strength`). **False = structurally unsupported.** Gate report sections on this, not on null fields. `per_workout_hr_strength` only describes strength-session HR — HL trackers still carry per-workout HR for cardio rows (hikes / runs), so cardio TRIMP and intensity_pct render normally on those.
- `auto_cardio_enabled`: bool. True = Apple-recorded runs / hikes / HIIT auto-flow into the monthly sheets.
- `today`: ISO date.
- `estimated_max_hr`, `estimated_rest_hr`: derived once at the top. `max_hr` is the largest observed Apple max-HR (or 208 − 0.7×age fallback for HL). `rest_hr` is the 28-day mean of `resting_hr` (or 60 fallback for HL). Used by all HR-zone / TRIMP / load-band math below.

**Strength + cardio sessions (canonical session-level view):**
- `monthly_sessions`: one entry per session-date, sorted asc. Each entry: `{date, exercise_first, session_kind, active_cal, total_cal, elevation_m, elapsed, avg_hr, max_hr, duration_min, volume (strength only), is_deload, trimp, load_band, intensity_pct}`. **This is the canonical session record** — it folds in TOTAL-row metadata (Active Cal, Avg HR, Duration, etc.) AND the per-session TRIMP score + load band. Iterate it directly; don't sum `rows` yourself.
  - `load_band`: `light` (TRIMP < 50), `moderate` (50–100), `hard` (100–150), `red-line` (>150). Use for one-line session summaries.
  - `intensity_pct`: HRR percent (avg_hr normalised to heart-rate reserve). 50 = Z1, 60-70 = Z2, 70-80 = Z3, 80-90 = Z4, ≥90 = Z5.
  - `is_deload`: True only when the TOTAL row's Notes carries `Deload Workout`.
- `weekly_volume_per_muscle`: `{window_days: 28, current: {muscle: sets}, landmarks: {muscle: {mv, mev, mav, mrv}}}`. Fractional hard-set count via primary/synergist rules. Compare `current[muscle]` to `landmarks[muscle]` and name the band (MEV/MAV/MRV) explicitly in the report.
- `estimated_1rm`: `{ExerciseName: {current_e1rm_kg, prev_e1rm_kg, best_e1rm_kg, last_date, delta_vs_prev_kg, slope_kg_per_4w, confidence, stalled_sessions, e1rm_history}}`. Epley projection. `e1rm_history` is **omitted by default**; pass `--include-1rm-history` to opt in.
  - `slope_kg_per_4w`: primary trend signal. Treat this as "is this lift trending up?".
  - `confidence`: `high` (last 3 top sets all 3-8 reps), `medium` (mixed), `low`. Soften trend language when `low`.
  - `stalled_sessions`: ≥2 consecutive sessions with |Δe1RM| ≤ 0.5kg = real stall, not one-off.
- `progression_summary`: last vs. previous best working set per exercise.
- `stale_exercises`: top 5 exercises not logged in ≥28 days, sorted newest-stale first. Use for rotation decisions.
- `unknown_exercises`: names not in the database. Surface in **Missing from your tracking**.
- `deloads`: list of dates whose TOTAL row has the `Deload Workout` marker.
- `auto_deload_candidates`: dates where the heuristic detected a deload-like week (≥35% volume drop AND ≥8 bpm avg-HR drop vs prior 4w) that the user **didn't** mark. Surface as a question, not a claim.

**Cardio rollup (28-day window):**
- `cardio_last_28d`: `{sessions, total_minutes, total_distance_km, total_active_cal, non_interval_minutes, interval_sessions}`. Coarse intervals-vs-non-interval split via Notes keywords + avg_hr ≥165 heuristic. **`non_interval_minutes` is NOT a true Zone-2 measurement** — a 3h hike at avg_hr 110 (Z1) lands in the same bucket as a 45min Z2 ride. Treat it as a coarse fallback, not a Z2 number.
- `cardio_hr_zones_28d`: time in HR zones using HRR (Karvonen). `{window_days: 28, total_minutes, z1, z2, z3, z4, z5, z2_pct, z3_pct, z4_z5_pct}`. **This is the canonical source for true Zone-2 minutes** (HRR-based, requires per-workout `avg_hr` on cardio sessions). **High z3_pct = grey-zone trap** (too much moderate work, too little easy or hard). Polarized = z2_pct + z4_z5_pct dominant; pyramidal = z2 > z3 > z4_z5 cleanly stepping down.

**Daily activity (NEAT — non-exercise activity thermogenesis):**
- `daily_activity_28d`: `{exercise_min_daily_avg, walking_workouts_count, walking_minutes_28d, walking_distance_km_28d, incidental_walks_count, assessment}`. Exercise minutes are Apple's brisk-activity tally (XML only — HL gets None). Walking workouts include both intentional walks and short flagged-incidental walks. **`assessment`** is the band the coach acts on: `low` (<15 min/day basis), `moderate` (15-45), `high` (≥45). Basis is `exercise_min_daily_avg` when present, else `walking_minutes_28d / 28` as a NEAT proxy. Use this to distinguish "sedentary then trains" from "active all day and trains" — the cardio prescription differs.

**Recovery + training load (Python-derived signals — use these instead of eyeballing raw metrics):**
- `recovery`: `{score: 0-10|null, confidence: low|medium|high, drivers: [...]}`. Score is a **renormalized weighted average of per-signal personal z-scores**, mapped to [0, 10]. Each signal: z-score against rolling personal baseline + stdev (clamped ±2σ), then `component = 5.0 + z × 2.5`. Composite = weighted average over signals with sufficient sample (≥7 readings in baseline window), weights renormalized to sum to 1.0 over present signals. **5.0 means "average for this user across whatever signals are available"** — *not* "base 5 minus what's missing", so HL trackers with fewer signals aren't structurally biased downward. Signals + raw weights (renormalized at runtime): HRV 0.30 (cap-gated), RHR 0.15 (inverted), sleep total 0.20, sleep deep h 0.05 (cap-gated), sleep REM h 0.05 (cap-gated), wrist temp 0.10 (cap-gated, inverted), HR Recovery 0.10, sleep consistency 0.05 (penalty-only). VO2max trend is **not** in the score (chronic fitness signal — see `vo2max_latest` / `vo2max_trend_per_4w` for the fitness check). Each driver entry: `{metric, component_score (0-10), weight (renormalized), z, recent_avg, baseline_mean, baseline_stdev, n_recent, n_baseline}` for z-scored signals; `{metric, component_score, weight, stdev, threshold, n_recent}` for sleep consistency. Drivers sorted by `|component_score - 5|` descending. `score: null` only when zero signals had sufficient sample. **Use the score directly in §18-style "should I train hard today?" decisions**; cite the most-deviating driver(s) by name (the first ones in the list).
- `training_load`: `{ctl, atl, tsb, trend_7d}`. CTL = chronic load (42-day EWMA of TRIMP), ATL = acute (7-day EWMA), TSB = CTL−ATL ("form": positive = peaked, negative = under load, ≤−10 = high fatigue risk). `trend_7d` = ΔCTL over the last 7 days (positive = building fitness).
- `hr_at_volume_divergence`: `{muscle: {slope_bpm_per_4w, n_sessions, hint}}`. Volume-weighted regression of strength-session avg HR vs time over 8 weeks, per primary muscle group. Slope ≥+3 bpm/4w = **fatigue or under-recovery** (HR creeping at same load); ≤−3 = improving conditioning. Use to call out specific muscle groups where volume should be held or cut.

**Bodyweight:**
- `bodyweight_latest`: `{date, kg}` or null.
- `bodyweight_trend_kg_per_week`: slope over the last 8 clean fasted entries, or null.

**Apple Health weekly aggregates:**
- `health_metrics_weekly`: 4 weeks of Mon-anchored aggregates. Each entry: `{week_start, n_days, vo2max, resting_hr, hrv_sdnn, walking_hr, hr_recovery_1min, sleep_total_h, sleep_deep_h, sleep_rem_h, resp_rate, wrist_temp_c, exercise_min}`. Read this for trends; raw daily data is behind `--include-daily-health`.
- `vo2max_latest`: `{date, value}` of the most recent VO2max.
- `vo2max_trend_per_4w`: OLS slope per 4 weeks across all logged VO2max readings.
- `health_metrics_recent`: raw daily rows (last 30). **Only present with `--include-daily-health`** — the weekly rollup is the default lens.

**Debug deep-dive (off by default):**
- `rows`: flat per-set list. Pass `--include-rows`. Use only for cross-sectional debugging the pre-aggregated keys can't answer.

**How to read the pre-aggregated signals (no need to dig into `rows`):**

- **Should I train hard today?** → Read `recovery.score` and `training_load.tsb`.
  - `recovery.score ≥ 6.5` AND `tsb ≥ -5` → green light, normal session.
  - `recovery.score 4-6.5` OR `tsb -10..-5` → moderate, hold load (no PR attempts).
  - `recovery.score < 4` OR `tsb ≤ -10` → easy session or active recovery; cite the dominant negative `recovery.drivers` entry by name.
  - Confidence `low` → soften the call and explain the gap (e.g. "HL doesn't supply HRV / wrist temp, score driven by sleep alone").
- **Volume analysis** → `weekly_volume_per_muscle.current[muscle]` vs `landmarks[muscle]`. Name the band (MEV/MAV/MRV) explicitly.
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
- Monthly sheets keep a buffer of empty rows (~2 past months, ~50 current month after `/maintain`). Stop after 10 consecutive fully empty rows.

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

## Phase 1: Report (into workout_plan.md `## Report`)

Goals are fixed: hypertrophy + longevity. Never ask about goals.

Keep the report tight. The user is an established trainee who has been coached before. If the data shows continuity (same exercises, steady progression, no new red flags), shorten WHAT'S WORKING and WHAT NEEDS FIXING to 2-3 items each. Only surface findings that changed since the last block. The report should feel proportional to what's new.

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
- **Strength sessions**: count `monthly_sessions[*]` with `session_kind == "strength"` AND `date` within the last 28d. Average TRIMP = mean of their `trimp` values (rounded to nearest int). Distribution buckets group by `load_band`. If TRIMP and load_band are null on every session in the window (HL trackers — no per-session HR to derive TRIMP from), drop the parenthetical entirely and write only the count: `| Strength sessions | 4 |`. Don't explain the absence; the row stays source-honest without lecturing the user about their data source.
- **Cardio sessions**: count strands with `session_kind == "cardio"`. Z2/Z3/Z4–5 minutes come from `cardio_hr_zones_28d.z2`, `.z3`, `.z4 + .z5`.
- **Daily activity row**: read `daily_activity_28d` directly. If `exercise_min_daily_avg` is null (HL trackers), substitute `{walking_minutes_28d / 28} min/day walking ({assessment})` and drop the "Apple exercise minutes" wording — same row shape, source-honest.
- **Training load**: read `training_load.ctl`, `.atl`, `.tsb`. Pick the `state` band from the table above.
- **Recovery score**: `recovery.score` and `recovery.confidence`. **Trend descriptor (deterministic procedure — replaces the old `↑/↓/→` arrow):**
  1. Walk `health_metrics_weekly`. For each of HRV / RHR (inverted: lower is better) / sleep_total_h / wrist_temp_c (inverted) / hr_recovery_1min / vo2max, compare the most-recent week's value to the mean of the prior 3 weeks.
  2. Score +1 for "better than prior" (delta exceeds 5% relative magnitude in the favorable direction), −1 for "worse" (5% in the unfavorable direction), 0 when |delta| < 5% relative.
  3. Sum across available metrics. Skip metrics that are null on the source (HL trackers won't score HRV / wrist temp).
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
- `slope_kg_per_4w` for the trajectory line (`+Ckg / 4w`). Use this as the **primary signal** — it sees through one-off noise that a last-vs-prev delta can't. If it's null (fewer than 3 sessions), drop the trend chunk and rely on the raw delta only.
- `confidence`: when `low` (high-rep top sets), append a sub-bullet like "e1RM is noisy at 12+ reps — push one heavier set to get a cleaner read." Don't claim a trend with confidence on a noisy signal.
- `stalled_sessions ≥ 2` without a deload in the window: surface the stall as a sub-bullet. Suggest one of: bump volume, change variation, or schedule a deload (let Phase 2 decide which).

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

Skip the TRIMP sub-bullet entirely on **strength** sessions when `capabilities.per_workout_hr_strength` is False (HL users — strength rows carry no per-workout HR so TRIMP is None/zero). Don't write `Last session TRIMP None`. Drop the sub-bullet cleanly. The flag is strength-only — cardio sessions on HL still carry avg_hr and TRIMP, so per-session TRIMP commentary on hikes / runs continues to render.

**Optional session-HR sub-bullet.** Skip entirely on strength sessions when `capabilities.per_workout_hr_strength` is False — HL users don't get per-workout HR for strength. When the capability is present, the strength session's `avg_hr` is on `monthly_sessions[*]` directly. Use it to append a session-HR comment — but only when it adds signal. Look up §19 for the bands. Examples:

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

**Data sufficiency thresholds:**
- Progression trend: minimum 3 sessions with the same exercise over 2+ weeks. Below that, state "not enough data" for that exercise.
- Volume analysis: minimum 2 full training weeks. Below that, report what's visible but caveat the sample size in THE VERDICT.
- Single-session data: skip ARE YOU GETTING STRONGER entirely. State why.
- Bodyweight trend: null from `read_tracker.py` → "not enough data for a trend yet." Don't fabricate a direction.

### Missing from your tracking
List **fixable** gaps the tracker doesn't capture that would help you coach better. One line each. (This draws from §13 internally but don't cite it.) Bodyweight is captured on the `Bodyweight` sheet by the morning /log prompt; don't flag it as missing.

**Do not** list metrics the data source structurally can't provide. Read `capabilities` first: any key that's False is configured-out, not forgotten. For HL users, that means HRV / wrist temp / sleep stages / per-workout HR / Apple-aggregate RHR / walking HR / exercise-min are off-limits as suggestions — they belong in the source's docs, not in a user-facing to-do list. The user can't go "track HRV better" without switching export tools, and a recommendation that hides the dependency is misleading.

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

Score-band labels (unchanged from before — 5/10 still means "average for this user", 4 / 6.5 still mark the hold-loads window):
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

When `recovery.confidence == "low"` (e.g. HL trackers with only 1 contributing signal, or any tracker still building baselines), **do not** ask the user to "track HRV better" — that's a source limitation or a sample-size gap, not a tracking gap. Skip the gap explanation entirely; just print the drivers the source provides and note the contributor count in the headline.

### Cardio check
Compare cardio against §10 targets (150 min Zone 2 + ~20 min intervals per week, so roughly 600 min Zone 2 + 4 interval sessions over 28 days). Flag shortfall in plain numbers: "Zone 2: 60 min logged, target ~600 min. Intervals: 0 sessions, target 4."

**Read `cardio_hr_zones_28d.z2` for the Zone-2 number** — that's the true HRR-based Z2 figure when the source supplies per-workout HR on cardio sessions (XML and HL both do). Only fall back to `cardio_last_28d.non_interval_minutes` when `cardio_hr_zones_28d` is empty (no avg_hr available on any cardio row in the window). Never quote `non_interval_minutes` as the Zone-2 number when `cardio_hr_zones_28d.z2` is present; it counts Z1 hike time as if it were Z2 stimulus and inflates the value. Read `cardio_last_28d.interval_sessions` for the interval count; that field is fine. The total minutes / distance / kcal in `cardio_last_28d` are also correct.

**REQUIRED daily-activity gate.** Cross-check the shortfall against `daily_activity_28d.assessment` before prescribing cardio. State the call explicitly with the value and band, e.g. "Daily activity 124 min/day (high). Cardio prescription: hold Z2, add 1 interval session for VO2max." Rules:
- `assessment: high` (≥45 min/day basis) AND VO2max trending up → keep cardio prescription minimal; the user is already getting aerobic load passively.
- `assessment: low` (<15 min/day basis) → add a Zone 2 session even if 28d cardio targets are met. The base activity dose is too low.
- `assessment: moderate` (15–45) → standard rule (prescribe to hit §10 targets).
- `assessment: null` → state "Daily activity unknown — using cardio targets only" and fall through to the standard rule.

If `cardio_hr_zones_28d` is populated (XML trackers with per-workout HR), call out distribution problems explicitly:

- `z3_pct > 40` → "Grey-zone trap: {N}% of cardio time in Z3. Either go easier (Z1/Z2) or harder (Z4/Z5); the middle is the least productive ratio."
- `z2_pct + z4_z5_pct > 60` → polarized distribution, healthy.
- `z1` dominating with little Z2 → call out that long hikes count as activity but not as the Zone 2 stimulus, then push for an intentional Z2 session.

When `vo2max_latest` is populated, append the VO2max line:

```
VO2max: 48.0 ml/kg/min (2026-04-30), +1.2 / 4 weeks — trending up.
```

If `vo2max_trend_per_4w` is null (fewer than 4 readings over 21+ days), drop the trend chunk: `VO2max: 48.0 ml/kg/min (2026-04-30) — not enough history for a trend yet.`

## Phase 2: Planning (into workout_plan.md `## Plan`)

If the user specified a session count in the `/coach` message (e.g., `/coach plan 3 sessions`), use it directly. Otherwise, ask in chat: **"How many sessions should I plan?"** — and wait for the answer before writing the file.

Generate that many strength workouts.

### Programming (internal)

**Split rotation:** The user runs a Push/Pull/Legs cycle. To determine the next sessions, look at the last completed workout's type and continue the rotation. Don't analyze the full history to rediscover this. If the last session was Pull, the next sessions are Legs → Push → Pull → Legs. If Push, next is Pull → Legs → Push → Pull. Fixed.

**Progression data:** The Step 4 summary already gives you weights and reps per exercise. Use that directly. Don't re-derive trends by walking through each exercise's history. Apply the double progression rule from §15: if the user hit the top of the rep range, bump weight. If not, same weight, push reps.

**Session duration:** 8-11 working exercises (excluding warmup) fits the 70-85 minute window. Count exercises, don't calculate minutes. At 7, add one. At 12, cut one.

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
  - `recovery.confidence == "low"` (HL trackers without HRV / wrist temp): the score's available signals are still trustworthy, but soften any rule that would otherwise override the deload window. Don't invent triggers from data the source doesn't provide.
  - When `recovery.score < 4` AND `recovery.drivers` has the negative signal persisting (e.g. wrist temp +0.4°C on a multi-week stretch in `health_metrics_weekly`) → flag deload as urgent regardless of `deloads` cadence. Override the standard 4-6 / 6+ week thresholds.
- **Per-muscle fatigue from HR creep (§19):** read `hr_at_volume_divergence`. For any muscle whose `hint == "rising HR at constant volume — fatigue or under-recovery"`, hold or cut volume on that group this block — don't add sets. Surface in the table's Notes column: `Holding {muscle} volume — HR rising at constant load.` For muscles with `hint == "improving conditioning"` you can add a working set if it's also under MAV. Skip this rule entirely on HL trackers (no per-workout HR → `hr_at_volume_divergence` empty).
- **Training-load gate (§19, REQUIRED):** read `training_load.tsb` and apply the band's rule. The band MUST be cited by name in "Why this plan" — e.g. "TSB −5.4 → balanced/carrying load boundary; this block holds loads."

  | TSB | State | Plan rule |
  |---|---|---|
  | > +10 | Well rested / detrained | Bump anchor compounds 2.5kg even if rep range isn't fully completed. State why in the table Notes. |
  | +5 to +10 | Well rested | Normal load progression rules apply. PR attempts allowed if rep ranges are met. |
  | −5 to +5 | Balanced | Hold loads, finish rep ranges first (current default). |
  | −10 to −5 | Carrying load | No PR attempts. Cut top set's RIR target to 2-3 (was 1-2). |
  | −15 to −10 | Fatigued | Drop one working set per compound across the board. |
  | ≤ −15 | High fatigue | Deload regardless of weeks-since-last-deload cadence. State this is a deload in "Why this plan". |

  **HL caveat:** When `capabilities.per_workout_hr_strength` is False (HL trackers), CTL/ATL/TSB are computed only from cardio TRIMPs — strength load is invisible to this metric. Do **not** apply the TSB-band prescription unilaterally on these trackers; cross-check with `recovery.score` and prefer `recovery.score` as the primary fatigue signal. A negative TSB driven by hike load alone is not a deload trigger — a 200-min hike will always look like fatigue to TSB even if the user is well-rested otherwise. Cite the cross-check in "Why this plan" when overriding the band.
- **Cardio (§10):** read the Cardio check numbers from the Report. If behind target, add cardio sessions to the plan after the strength sessions. Default weekly target: 3× Zone 2 @ 30-45min + 1× intervals @ 20min. Cap total cardio additions at 4 sessions per `/coach` run — if the user is very behind, note the shortfall and prescribe the max. User can override with `/coach no-cardio` to skip this entirely.

**Core training:** Build strong, developed abs. Program 1-2 core exercises per session, aim for 3-4 sessions/week with core. Prefer weighted core (kneeling cable crunch, cable woodchop, captain's chair knee raise) alongside bodyweight (leg raises, dead bugs, hollow body holds). Vary patterns across sessions: flexion, anti-extension, rotation, isometric. Visibility is a body fat question, not a training question.

**Equipment increment grid (REQUIRED).** Loads are prescribed on the equipment's increment grid. Never suggest off-grid weights.
- **Cables:** 5kg steps (5, 10, 15, 20, 25, …). Round to the nearest available plate.
- **Dumbbells:** 1-2kg pair increments depending on the rack. When in doubt, round to the nearest 2kg.
- **Plate-loaded machines:** 5kg per plate side. Round prescribed loads to the nearest 5kg unless the gym is known to have half-plates.
- **Microloading:** for barbells only, and only when the user has explicitly logged microplates before.
Re-read this block before every load suggestion in the workout tables.

**Exercise ordering:** Compounds first, then isolation, then accessories.

**Equipment grouping:** Applies within the isolation/accessory block only. Batch cable work together, bench work together, etc. Never reorder compounds or move an isolation before a compound for equipment convenience.

**Priority notes:** In the Notes column, mark high-priority exercises "Priority" and droppable ones "Nice to have". Only when the distinction matters.

### Per-workout format in the file

For each workout, output the quick list immediately followed by the table for that same workout. Then move to the next workout. Do NOT batch all quick lists then all tables — that makes the file hard to use on the gym floor.

Correct order: Quick List WO1 → Table WO1 → Quick List WO2 → Table WO2 → etc.

Each workout heading is immediately followed by `**Date:** ___________` on its own line, then a blank line, then the quick list. The user fills in the date when they actually train so the session can be logged later without guessing. This applies to every strength workout — cardio sections do not need a date line.

**Quick list** — what the user reads on their phone. One line per set, plain markdown bullets. No code fences. Format:
- Bodyweight or single-rep: `Exercise Name : reps` (e.g., `Plank : 45s hold`)
- Weighted: every set separated by `///`:
  - Fixed: `Dumbbell Flat Bench Press: 52kgx10 /// 52kgx10 /// 52kgx10`
  - Range: `Cable Lat Pulldown: 65-70kgx8-10 /// 65-70kgx8-10 /// 65-70kgx8-10`
  - 4 sets = 4 entries. Always.
- Warmup exercises: same format, no special marking.

Example (markdown — no code fence around it in the actual file):

```
### Workout 1: UPPER PUSH + CORE
**Date:** ___________

- Jumping Jacks : 50
- Band Pull-Apart : 15
- Dumbbell Flat Bench Press: 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10
- Shoulder Press Machine: 45kgx8-10 /// 45kgx8-10 /// 45kgx8-10
- Dumbbell Fly: 18kgx10 /// 18kgx10 /// 18kgx10
- Cable Lateral Raise: 15kgx10 /// 15kgx10 /// 15kgx10
- Cable Overhead Tricep Extension: 35kgx8-10 /// 35kgx8-10 /// 35kgx8-10
- Kneeling Cable Crunch: 20kgx15 /// 20kgx15 /// 20kgx15
- Dead Bug : 12 per side /// 12 per side
```

Canonical exercise names (title case from the database). No lowercase.

**Table** — reference for the same workout, single continuous table, core in the same table:

```
| # | Exercise | Sets × Reps | Notes |
| - | -------- | ----------- | ----- |
| 1 | Jumping Jacks | 1 × 50 | Warmup |
| 2 | Dumbbell Flat Bench Press | 4 × 8-10 | Start 54kg. Leave 1-2 reps in tank. |
...
| N | Dead Bug | 2 × 12/side | Anti-extension |
```

Rules for tables:
- **#**: sequential from 1
- **Exercise**: canonical names
- **Sets × Reps**: `3 × 8-10` or `1 × 50` or `1 × max hold`
- **Notes**: always specific. Include starting weight (from tracker or estimate), target ("Push for 10 reps before adding weight"), cue ("Full stretch at bottom"), purpose ("Warmup", "Shoulder health"). Never empty for working sets. Use "Leave 1-2 reps in the tank" / "All-out last set" instead of RIR/RPE numbers.
- 2-3 warmup exercises at the top
- Order: compounds → isolation → accessories

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

### Why this plan

**REQUIRED templated rationale.** Not a free-form paragraph — a numbered three-signal list, each citing specific values. If the block is a deload, state it explicitly.

```
## Why this plan
This block is paced from three signals:
1. **Training load**: {TSB band citation, e.g. "TSB −5.4 (balanced)"} → {what changed in load progression rules}.
2. **Recovery**: {dominant negative driver name + value, e.g. "Wrist temp +0.11°C, contrib -0.57"} → {what changed in volume / RPE}.
3. **HR-at-volume**: {N flagged muscles from hr_at_volume_divergence with hint "rising HR..."} → {which muscles got volume cut}.

Plus standard rotation: {1-2 rotation decisions from progression / stale_exercises / hr_at_volume_divergence}.
```

Source-honesty rules:
- If `hr_at_volume_divergence` is empty (HL trackers — no per-workout HR), drop line 3. Don't fabricate it; don't tell the user the data is missing. The other two lines remain mandatory.
- If `recovery.drivers` is short (HL — only sleep + HR Recovery + VO2max trend), still pick the dominant negative driver. There's always one.
- TSB citation is mandatory on both sources — every tracker has TRIMP from session duration + max HR estimate.

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
| Neglecting core | Zero or one core exercise across a full planned week | 1-2 per session, 3-4 sessions/week. Vary patterns. |
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
| Writing the report or plan inline in chat | Conversation gets flooded; plan is hard to find later | All report + plan content goes into `./workout_plan - <Person>.md`. Chat gets one verdict line + the file pointer. |
| Writing one person's plan over the other | `workout_plan - Nihad.md` overwritten with Fabian's plan, or vice versa | Always resolve the person first and write to `./workout_plan - <Person>.md`. Never a bare `workout_plan.md`. |
| Partial file writes | Streaming sections and forgetting to complete | Build the whole file in memory, then write once. |
| Inventing recovery trends on <4 readings | "HRV improving" called from 2 data points | The `_trend_per_4w` keys are null until ≥4 entries spanning 21+ days. Drop the trend chunk; print the average alone. |
| Reading single-day HRV as signal | One bad night triggers a deload | The `recovery.score` already aggregates 7-day HRV / RHR / sleep / wrist temp / HR Recovery against baselines. Trust the score; don't react to one bad night. For multi-day persistence checks, walk `health_metrics_weekly` (or pass `--include-daily-health` only when the rolling-window inspection genuinely matters). |
| Treating Apple `Walking` workouts as training | Counts a 5-min stroll as a session | The importer flags walks under 15 min as `incidental walk` in Notes. `monthly_sessions` already excludes them; don't re-add them when reading the sheet directly. |
| Bumping load when session HR is creeping up | User over-reaches | For the per-muscle call, use `hr_at_volume_divergence[muscle].hint`. For an absolute-HR check, read `monthly_sessions[*].avg_hr` directly. Note "Holding load — session HR rising at constant volume." |
| Treating an HL user's missing HRV as "not enough data yet" | Implies the user just needs to log more, but the source can't provide HRV at all | Read `capabilities.hrv`. If False, omit the metric (and its sections) entirely. Distinct from "trend is null because <4 readings collected so far". |
| Listing structurally-unsupported metrics in **Missing from your tracking** | User sees a fake to-do list of things to "track" that the data source can't supply | The section is for *fixable* gaps (typos in `unknown_exercises`, dropped exercises, manual notes). Anything False in `capabilities` belongs in source docs, not the user-facing report. |
| Treating auto-cardio rows as duplicates of manually-logged runs | Both /log and the importer write the same run; coach can't tell them apart | Auto-cardio dedupe runs in the importer by (date, exercise, duration ±1 min). Manual entries always win. If you see two rows for the same run on the same date, flag it — the dedupe missed something. |
| Treating an annotated outlier as a typo | The user wrote in Notes that the row reflects equipment / gym / context change; coach calls it "almost certainly a typo" anyway | Read `progression_summary[exercise].last_notes` (or full Notes via `--include-rows`). If a note exists, treat the row as user-acknowledged context, not as an error. Acknowledge the context in the bullet rather than calling it a logging error. |
| Suggesting an off-grid load | "Bump to 67.5kg" on a cable that increments in 5kg | Round to the next legal increment for the equipment (cables 5kg, dumbbells 1-2kg pair, plate machines 5kg). Re-read the equipment block in §3 of training-science before each load suggestion. |
| Bumping non-anchor load in a hold-loads block | Cable Pallof Press 15kg → 20kg in a "hold loads" mesocycle week 1 | The rule applies to every exercise, not just anchor compounds. Copy last session's load forward; only push reps. The only legal increase is when the user hit the top of the rep range cleanly AND the recovery / TSB band still permits it. |
| Defaulting to `→` on the recovery trend | Recovery row reads `4.2/10 (... trend → vs prior 4w)` even when every metric is moving down | Use the `improving / drifting / mixed` descriptor (deterministic procedure under "Last 28 days at a glance"). The arrow is no longer accepted. |
| Calling a deload on TSB alone for HL trackers | TSB -10.7 from two big hikes triggers a "fatigued" prescription on Fabian even though strength load is invisible to TSB | When `capabilities.per_workout_hr_strength` is False, CTL/ATL/TSB are computed only from cardio TRIMPs — strength load is invisible. Don't treat a negative TSB as a unilateral deload trigger; cross-check with `recovery.score` and prefer recovery_score as the primary fatigue signal on these trackers. |
| Citing `non_interval_minutes` as Zone-2 minutes | Cardio check section reports `cardio_last_28d.non_interval_minutes` (which is just "cardio time that wasn't intervals") as if it were a real Z2 measurement — a 3h Z1 hike inflates the number | Read `cardio_hr_zones_28d.z2` for true Zone-2 minutes (HRR-based). Use `cardio_last_28d.non_interval_minutes` only as a fallback when `cardio_hr_zones_28d` is empty (no avg_hr on cardio sessions). |

## Rules

- Goals fixed. Never ask.
- No generic advice disconnected from their data.
- Don't soften findings.
- If data is too thin, say what you can and can't tell from it.
- One clarifying question max if the tracker is unreadable.
