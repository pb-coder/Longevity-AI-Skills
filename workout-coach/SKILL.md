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

**Invocation**: The `/coach` slash command delegates here. You can also be asked directly ("plan my next workout", "how is my training going"). The non-triggers are in the frontmatter `description`; logging in particular belongs to `workout-logger` via `/log`.

## Who is this for?

Two trackers live in per-person folders inside the workout directory:
- `<Person>/data/` (CSV store: monthly/ + dense + swimming/)
- `<OtherPerson>/data/` (same shape)

Both are HealthAutoExport-backed. Apple's native XML export has been retired entirely, so `data_source` is `health_auto_export` on every tracker. Neither person has a per-lap swim store any more; per-workout swim aggregates are written on both.

Resolve which person this request is about BEFORE running the script:
- If the user names a person or tracker, use that name.
- If the user uses pronouns or context that clearly refer to one tracker, use that tracker.
- Otherwise ask which tracker/person this is for before proceeding.

Pass the resolved name via `--person <Name>`. Outputs go to `plans/<Person>/` at the workout-tracker root — one dated pair per generation: `plans/<Person>/<YYYY-MM-DD>-assessment.html` (the rich dashboard) and `plans/<Person>/<YYYY-MM-DD>-workout.md` (the lean workout list). Never write one person's plan over the other; never write to the repo root (where the old `./workout_plan - <Person>.md` lived — those files are frozen history). The path resolvers live in `Skills/shared/person_paths.py`: `plans_dir(person)`, `workout_plan_md(person, date)`, `assessment_html(person, date)`. Use them rather than hand-building the paths.

## Setup

1. Read `../shared/exercises-database.md` for muscle mappings, synergist tags (`+muscle` = 0.5 sets), lengthened-position flags (`◆`).
2. Read `references/training-science.md` and use the Quick Lookup table for each part of your analysis. When `swim_summary` is present in the JSON, also read `references/swim-coaching.md` for SWOLF / SPL / CSS-zone interpretation, retest cadence, and what NOT to say about swim form. When `nutrition_phase` is present AND `current.phase_type == "bulk"`, also read `references/bulking-science.md` for surplus / rate / off-ramp judgment and the binding `coach_action_hint` token semantics. When `energy_28d` or `nutrition_phase.energy` is present on **any** phase type, read that same file's **The 7,700 kcal/kg constant** section: it is where every kcal target in this tracker comes from, in both directions, and it carries the caveats on the conversion.
3. Run `scripts/read_tracker.py --person <Person>` from the workout-tracker root. The script reads that person's CSV store (`monthly/`, `health_metrics.csv`, `workout_sessions.csv`, `profile.csv`, plus `swimming/`, `sleep/`, `thermal/` and `light_therapy/` where they exist) and returns one JSON blob organised around session-level signals rather than raw arrays. Every key is documented under **Data Reading Strategy** below; read that section, not this line, for what is in the payload. Several blocks are gated on data presence and are simply absent when there is nothing to report. If the data folder isn't there, the script prints an error — relay it in one line and stop. Don't search the filesystem.

   **Output is compact (no indentation) by default** — saves ~20% of tokens vs pretty-printed. Pass `--pretty` for human inspection.

   **`rows` (the flat per-set list) is off by default** — the script's pre-aggregated keys (`monthly_sessions`, `progression_summary`, `weekly_volume_per_muscle`, `estimated_1rm`, `cardio_last_28d`) cover every coaching use. Pass `--include-rows` only when you genuinely need to dig into individual sets for debugging or unusual cross-sectional questions; expect the JSON to grow ~4x in size.

4. From the script's output, identify the **most recent workout** (last date with logged sets). Note which muscle groups it trained and which exercises were performed. Use this as the planning baseline: do not repeat the same primary muscle emphasis in the very next session, and carry forward any exercises where progression was visible. The rest of each session's slots are where variation lives — see §17.

## Output target

All user-facing output goes into **two dated files** under `plans/<Person>/`:

- `plans/<Person>/<YYYY-MM-DD>-assessment.html` — the rich, visual assessment dashboard. Built from the JSON. Self-contained: inline CSS, inline SVG, inline JS where it helps. **No external requests** (no CDN, no web fonts, no remote images, no `<script src>`). Must render identically with Wi-Fi off.
- `plans/<Person>/<YYYY-MM-DD>-workout.md` — the lean workout-plan markdown. Bullets only. No assessment section. Sub-bullet notes only when a remark is genuinely actionable (rules below).

`<YYYY-MM-DD>` is the date the coach generates the plan (today's date in the JSON's `today` field). Each generation writes a fresh dated pair; older pairs stay on disk for scrollback. No `latest-*` symlink — the user opens the newest dated file. **Plans dated before 2026-08-02 predate the current core spec and every one of them fails today's blocking gate** — read them for history, never as a structural template.

The chat gets one short block: a one-line verdict plus `Wrote dashboard to plans/<Person>/<date>-assessment.html and plan to plans/<Person>/<date>-workout.md (N sessions)`. Nothing else.

### Assessment HTML structure

The dashboard is produced by **`scripts/render_dashboard.py`**. The script owns all HTML, CSS, SVG, and JavaScript. You do not hand-write HTML. You author two inputs and run the renderer.

The dashboard is organised across **three tabs**: Today (operational, "should I train hard?"), Trajectory (longevity, "am I aging well?"), and Workout (the markdown plan, rendered in the same visual style).

- **Today** — headline, Recovery + Freshness hero (the recovery card absorbs the hard / moderate / easy call as a sub-line), recovery drivers, ACWR, activity rings, NEAT, the 90-day training-load chart, strength progression, week over week.
- **Trajectory** — longevity score, cardiorespiratory, autonomic recovery, sleep architecture + Sleep Regularity Index, body composition, metabolic, energy expenditure, the centenarian-decathlon framing, behavioural consistency, health vitals, sleep detail, recovery practices, personalized risk flags. Three cards here are gated on their tracker block and simply do not render without it: swim, energy, nutrition phase.

The card inventory, each card's data contract, the coach-reads schema, the validation rules, and the tooltip catalog live in **`references/assessment-dashboard.md`**. That file is the source of truth for all of it; do not restate it here.

Three things about the dashboard the planner needs and the spec does not say:
- Per-muscle weekly volume is computed and available in the tracker JSON as `weekly_volume_per_muscle` for coach planning, but is **not rendered** — by user choice it stays internal.
- HRV is Apple SDNN. **Never compare it cross-platform to Whoop / Oura RMSSD.**
- Every card with actionable signal carries a **Coach callout**: "Coach" label, action-focused one-liner. The renderer enforces the copy rules and fails fast on violations.

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

**No `## Report` section, no tables, no rationale block.** The `Date:` / `Recovery:` placeholder rules are spelled out once, under "Per-workout format in the file".

Write both files in one pass at the end. Don't stream sections to chat while thinking.

## Data Reading Strategy

`scripts/read_tracker.py` handles all the quirks (date normalization, empty-row streaks, case-insensitive grouping, numeric casting, deload detection, cardio categorization) and emits a single JSON blob. Call it once at the start of `/coach`. Don't re-read the CSV store inline unless you're debugging something the script can't see.

What the JSON contains:

**Source + capabilities (read first to gate sections):**
- `data_source`: always `health_auto_export` (HealthAutoExport ZIP). Apple's native XML export is retired and no tracker carries `xml` any more. Trust this string; don't override based on populated fields.
- `capabilities`: per-source feature map. **False = structurally unsupported**, so gate sections on this rather than on null fields, and never ask the user to track something their source cannot emit. HealthAutoExport exposes the full recovery / sleep / per-workout-HR surface, including the per-night `sleepStart` / `sleepEnd` timestamps, so `sleep_regularity` is True. `sleep_nights` False means sleep is limited to the headline Total/Deep/REM on `health_metrics_weekly`. `thermal_log` and `light_therapy_log` are always True (manual-log, not source-dependent); their summary blocks are gated on data presence instead.

  **Permanently unavailable, whatever an empty field looks like.** These went with the XML retirement and are not coming back. Never list them under **Missing from your tracking**, and never read an emptied field as something that changed about the person:
  - **Workout effort score** (Apple's 1-10 RPE). The tracker has no effort-in-reserve intake at all, which is why the stall language has to say it is inferred from load and reps.
  - **Beat-to-beat intervals, so no RMSSD.** HRV is the SDNN scalar and nothing else.
  - **ECG.**
  - **Swim stroke style and SWOLF**, and the per-lap detail they lived on. Per-workout swim aggregates (pool length, laps, strokes, SPL, distance, water temp) are still written.
  - **Apple's own HR-zone boundaries.** Every zone in this payload is HRR-derived from `estimated_max_hr` / `estimated_rest_hr`.
  - **`n_segments` on sleep nights**, permanently blank, so sleep fragmentation is null on every night. **A null fragmentation is a retired field, not a better night.** Never write that fragmentation improved because the number went away.
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
- `stale_exercises`: the reintroduction pool. Top 5 exercises not logged in ≥28 days, sorted newest-stale first, ties broken on more sessions logged — so the head of the list is the movement with the most recent, densest history, not the oldest one-off. Each entry: `{exercise, last_date, weeks_since, sessions_logged}`. Use for rotation decisions and cautious reintroductions.
- `unknown_exercises`: names not in the database. Surface in **Missing from your tracking**.
- `deloads`: list of dates whose TOTAL row has the `Deload Workout` marker.
- `auto_deload_candidates`: dates where the heuristic detected a deload-like week (≥35% volume drop AND ≥8 bpm avg-HR drop vs prior 4w) that the user **didn't** mark. Surface as a question, not a claim.

**Cardio rollup (28-day window):**
- `cardio_last_28d`: `{sessions, total_minutes, total_distance_km, total_active_cal, non_interval_minutes, interval_sessions}`. Coarse intervals-vs-non-interval split via Notes keywords + avg_hr ≥165 heuristic. **`non_interval_minutes` is NOT a true Zone-2 measurement** — a 3h hike at avg_hr 110 (Z1) lands in the same bucket as a 45min Z2 ride. Treat it as a coarse fallback, not a Z2 number.
- `cardio_hr_zones_28d`: HRR (Karvonen) time-in-zone. **The canonical source for true Zone-2 minutes**, and it needs per-workout `avg_hr` on cardio rows. `z2_by_activity` splits Z2 into `run` / `swim` / `cycle` / `walk_hike` / `other`, so a 5-min swim does not read as the same dose as a 35-min run. **High `z3_pct` = grey-zone trap.** Polarized = `z2_pct + z4_z5_pct` dominant; pyramidal steps z2 > z3 > z4_z5 cleanly.

**Daily activity (NEAT — non-exercise activity thermogenesis):**
- `daily_activity_28d`: NEAT rollup. **`assessment`** is the band to act on (`low` / `moderate` / `high`), and **`steps_daily_avg` is its primary basis** — steps are the honest NEAT channel because they accumulate all day without a workout being started, whereas Apple exercise minutes credit deliberate training. Step bands are `low` under 7,000/day, `moderate` 7,000 to 10,000, `high` at or above 10,000. `exercise_min_daily_avg` is the secondary basis and is used only when steps are absent (bands <15 / 15-45 / ≥45 min/day), with walking minutes per day as the last fallback; `walking_workouts_count` and `walking_distance_km_28d` are context, never the band. **`assessment_basis` names which of the three the band was actually read off** (`steps` / `exercise_min` / `walking_minutes` / null), and quoting the band without it hides a measured step count reading identically to a walking-workout proxy. Read `assessment` rather than re-deriving it. It separates "sedentary then trains" from "active all day and trains", and the cardio prescription differs between them.

**Energy expenditure (28-day window, gated):**
- `energy_28d`: daily energy expenditure measured off the export's active plus basal energy. **Absent when the source has no energy rows** (not null, and not a block of zeroes), and the Trajectory energy card does not render without it. **This is an EXPENDITURE block. Nothing in it is intake, and there is no intake block anywhere in this payload.**
  - `tdee_kcal_daily_avg`, `active_kcal_daily_avg`, `basal_kcal_daily_avg`: kcal/day, whole numbers. Each is averaged over the days that actually carry its reading, so **the three means can rest on three different day sets and `tdee` need not equal `active + basal`.** `n_days` counts days carrying BOTH components (the days TDEE is built from); `n_active_days` and `n_basal_days` sit beside it so a disagreement is visible rather than silently averaged over.
  - `tdee_trend_kcal_per_week` / `basal_trend_kcal_per_week`: the headline rates, **populated only when the fit resolves and null otherwise**, with the full `tdee_trend` / `basal_trend` blocks behind them carrying `state` / `reason` / `note`. **Same shape and same trap as `bodyweight_trend`.** Read `state` before you say the burn is rising or falling, and paraphrase `note` when it is unresolved. **`point_kcal_per_week` is the energy twin of `point_kg_per_week` and `point_cm_per_4w`**: it sits inside the block at the same level as `state`, needs no state check to reach, and is populated whenever a fit exists at all, which is precisely when the direction did not resolve. Never quote it as the rate.
  - The two channels resolve independently. There is no basal trend without a basal column and no TDEE trend without both, so one can resolve while the other does not. Say which one you are quoting.
- `nutrition_phase.energy` (optional sub-block on an open phase): `{tdee_kcal, target_deficit_kcal, implied_intake_kcal, basis}`. `implied_intake_kcal` is `tdee_kcal` minus `target_deficit_kcal`, so it is a **prescription derived from a measurement**, not a reading. `basis: "measured_28d"` says the TDEE came from `energy_28d`; any other basis is an estimate. Writing rules are under **Nutrition phase**.

**Recovery + training load (Python-derived signals — use these instead of eyeballing raw metrics):**
- `recovery`: `{score: 0-10|null, confidence, drivers: [...]}`. A renormalized weighted average of per-signal personal z-scores mapped to [0,10], over signals with a sufficient baseline sample. **5.0 means "average for this person across whatever signals are available"**, NOT "base 5 minus what's missing" — trackers with fewer usable signals are not biased downward. VO2max trend is **not** in it (chronic fitness; see `vo2max_*`). `drivers` are sorted by `|component_score - 5|` descending, so the most-deviating signal leads. `score: null` only when zero signals had sample. **Use the score directly for "should I train hard today?"** and cite the leading driver(s) by name.
- `training_load`: whole-body `{ctl, atl, tsb, trend_7d}`. CTL = chronic load (42-day EWMA of TRIMP), ATL = acute (7-day EWMA), TSB = CTL−ATL ("form": positive = peaked, negative = under load, ≤−10 = high fatigue risk). `trend_7d` = ΔCTL over the last 7 days (positive = building fitness).
- `training_load_by_modality`: `{all, strength, cardio}` using the same shape as `training_load`. The deterministic strength-session gate uses `strength` when available so a hard run/ride does not automatically block strength loading; coach copy may still mention whole-body fatigue separately.
- `hr_at_volume_divergence`: `{muscle: {slope_bpm_per_4w, n_sessions, hint}}` or a single `systemic_session_hr` entry when many muscles flag together. Volume-weighted regression of strength-session avg HR vs time over 8 weeks, per primary muscle group. Slope ≥+5 bpm/4w = **fatigue or under-recovery** (HR creeping at same load); ≤−5 = improving conditioning. When the systemic entry appears, call it a shared session-HR shift and check bodyweight, heat, deload boundaries, or generic fatigue before changing per-muscle volume.

**Bodyweight + waist (two channels, not one):**
- `bodyweight_latest`: `{date, kg}` or null.
- `bodyweight_trend`: the trend block. OLS over a **minimum 28-day window** of clean fasted entries. `state` is `resolved` only when the 95% interval excludes zero; otherwise `unresolved` with a `reason` (`no_readings` / `too_few_readings` / `window_shorter_than_min` / `no_time_variance` / `ci_straddles_zero`) and a plain-English `note`. Also carries `point_kg_per_week`, `se_kg_per_week`, `ci95_kg_per_week`, `n_readings`. **Read `state` before you say anything about gaining or losing.** `unresolved` is an answer, not a failure: bodyweight moves ±1kg a day on water and gut content, and the estimator this replaced once reported −0.37 kg/wk over a stretch whose honest fit was +0.07 ± 0.25.
- `bodyweight_trend_kg_per_week`: the same rate as a bare scalar, populated **only** when `bodyweight_trend.state == "resolved"`, else null. When `nutrition_phase.current` is present, the window is the open phase instead so a bulk/cut is judged inside its own window.
- `bodyweight_weekly`: ISO-week mean bodyweights for the vitals sparkline. This is a weekly average for visual context, not the phase-status source.
- `waist_latest`: `{value_cm, date}`, or null when waist has never been measured.
- `waist_trend_cm_per_4w`: same block shape as `bodyweight_trend` — `state`, `reason`, `note`, `n_readings`, the rate in `cm_per_4w` (populated **only** when `resolved`), and beside it `point_cm_per_4w`, `se_cm_per_4w`, `ci95_cm_per_4w`. Read `state` first here too, and **never quote `point_cm_per_4w` as if it were the rate** — it is the waist twin of `point_kg_per_week` and carries the identical trap: it is populated whenever a fit exists at all, i.e. precisely when the direction did not resolve and quoting it is wrong, and nothing in the payload shape stops you reaching it without checking `state`.
- **Waist is the leanness channel; bodyweight is not.** The scale cannot separate recomposition from fat gain — the same +1kg is a good month or a bad one depending on which way the waist went, so weight-up-with-waist-flat is the most useful sentence you can write about a bulk. A **single** reading is a baseline and supports **no** trend claim; say it is the first one. When `waist_latest` is null, never infer composition from bodyweight to fill the hole — say the channel is empty ("no waist measurements on file; the scale alone can't separate muscle from fat") instead of quietly dropping it, so the user learns a tape measure would buy them something. **Progress photos are the other half of this channel (D10):** on the FIRST plan of each calendar month, put one short line in the opener asking for a monthly progress photo. Nothing in the tracker stores or reads images, so this is a prompt to the user and nothing else — never claim to have looked at one, and never treat a photo as data you have. Skip the line on every other plan in the month; a reminder that fires weekly becomes wallpaper.

**Prescription memory (what was ASKED for, vs. what happened):**
- `adherence`: the previous plan reconciled against the logs. `null` on a first run (no plans on disk) — absent evidence, not 0% adherence, and it must not be reported as a compliance problem. Carries `window` / `window_days` / `window_open` (the newest plan is still live, so its misses are not yet misses), `sessions_planned` / `sessions_performed`, `missed_sessions`, `sets_prescribed` / `sets_performed`, `completion_rate` and `tested_completion_rate`, `isolation_completion_rate` vs `compound_completion_rate` (the truncation is isolation-vs-compound, not positional), `per_exercise[]` with `consecutive_unperformed`, `substitutions` (a same-muscle movement logged instead is not a skip), `never_performed[]`, `benched[]`, `bench_blocked[]`, and `bench_prompt`.
  - **Quote both completion rates or neither.** `completion_rate` counts every prescribed set including sessions that never happened; `tested_completion_rate` counts only sessions the user actually trained. The gap between them is attendance, the second alone is within-session truncation, and they are gamed in opposite directions. One number on its own is a misleading verdict.
  - **`missed_sessions` is not evidence about exercises.** A session that never happened says nothing about whether the user rejects the movements inside it. Only sessions that were trained count toward skipping.
  - **A benched exercise must not be re-prescribed.** A `bench_blocked` one is the opposite: it stays prescribable because dropping it would strand a muscle or a core pattern category. See "Bench prompt" under Programming.
- `dose_staleness`: per carried-forward exercise, whether load or reps actually moved between generations, with materiality floors so a rounding change does not read as progress. Measured baseline was 70% of carried exercises returning with an unchanged dose. **Under 40% is an ADVISORY ceiling this release, not a blocking gate:** `dose_progression_findings` re-measures the plan you are about to write against the previous block and prints findings tagged `[advisory: dose progression, not enforced this release]`; it cannot exit 2 while `DOSE_PROGRESSION_ENFORCED` is `False`. It is advisory because it has two known defects: it refuses a compliant one-session cadence deload (where holding loads is what the prompt REQUIRES), and it is satisfied by shifting every rep window up one, which changes no weight. Treat the ceiling as binding on your own judgement anyway - the finding names the lifts that have to move. (It goes quiet below 5 carried exercises, where the share is arithmetic rather than behaviour — do not read that silence as a pass.) And the payload block scores the **previous** generation — the two plans already on disk, named in its own `from_plan` / `to_plan` — so `meets_target: true` is history, not a verdict on the plan you are writing. Read `carried[].generations_static` for the lifts that have to move.
- `block`: the current training block. `block_id`, `started`, `age_weeks`, `boundary_due`, `boundary_reason`, `weeks_to_boundary`, `max_weeks` (6), and `slots[]` tagged `anchor` or `rotating` with `pattern`, `blocks_held`, `history`, `superset_with`, `at_risk`, `must_rotate`, `anchor_overdue`. The boundary fires at the deload or at six weeks, whichever comes first, and is computed in code because cadence deloads get skipped.
- `rotation_candidates`: never-performed catalog movements the coach may legally prescribe, scoped to pattern groups trained recently. `derivation` states the derivation rule once, `target_reps` and `novelty_discount` sit alongside it, and `candidates[]` carries the numbers: `exercise`, `pattern`, `load_kg`, `load_basis`, `ref`, `confidence`. **`candidates[].load_kg` is the only legal source of a starting weight for a movement with no history** — see the cold-start rule under Programming.
  - **A null `load_kg` has three meanings and `load_basis` is what tells them apart.** Read it before you write a prescription; they are not the same instruction.
    - `load_basis: "bodyweight"` (with `unit: "bodyweight"`) — the movement has no external load. Prescribe reps or seconds and no weight.
    - `load_basis: "no_reference"` — no same-pattern sibling has logged history, so there was nothing to derive from.
    - `load_basis: "unknown_transfer"` — a sibling exists but the equipment classes differ and no coefficient covers the pair.
  - The last two both mean **"we could not derive a safe number"**, not "this is a bodyweight movement". Treating them as bodyweight prescribes an unloaded set of a loaded lift. Pick a conservative weight yourself, one the user can control for `target_reps` with 2-3 reps in reserve, say so in a sub-bullet cue, and let the next session's log take over.

**Prescription specs and priority tiers (all enforced in `render_validators.py`, not by you):**
- `core_week_spec`: `sets_per_session` (4 lower / 2 upper) with `session_set_overshoot_tolerance` 1 — one set over the session dose passes, two block. Under-allocation blocks too, **except on a deload week**: it is a volume-axis finding, and a deload demotes those to advisories tagged `[advisory: deload week]`. The overshoot ceiling and every structure-axis finding — placement, distinct exercises, category coverage, the per-exercise cap, the flexion **share** — keep blocking on a deload. Do not plan to the demotion. `min_distinct_exercises_per_week` 3, `min_pattern_categories_per_week` 3, `max_sessions_per_exercise_per_week` 2, `min_loaded_flexion_exercises_per_week` 1 (an EXERCISE count — one bullet satisfies it), plus a flexion SET floor of `min_flexion_sets_per_week` 3 or `min_flexion_share_of_core_sets` (1/3) of the week's core sets, whichever is larger. Pattern categories are the CORE subsections in `exercises-database.md` (Flexion / Anti-Extension / Anti-Rotation / Anti-Lateral-Flexion / Rotation). **The share is where a legal-looking week fails:** a four-session upper/lower week is 12 core sets, so the floor is 4 flexion — 4 flexion + 8 non-flexion sits exactly on the boundary, and one set moved out of flexion, or one extra non-flexion set anywhere, drops under it. Program a set of margin.
- `arm_week_spec`: `min_direct_sets_per_week` 6 per muscle, `min_distinct_exercises_per_week` 2. Synergist credit does not count toward either.
- `muscle_priority_tiers` / `muscle_volume_targets`: every muscle resolved to `emphasis` (target mid-MAV), `grow` (MEV), or `maintain` (MV), with the implied `target_sets`. Sourced from `profile.csv`; the config replaces the built-in emphasis set rather than adding to it. **Program to `muscle_volume_targets[muscle].target_sets`, not to MEV for everything.** Chasing MEV on all 16 muscles routes meaningfully to none.

**Longevity Trajectory (Trajectory tab inputs).** Field names are self-describing in the JSON; below is only what the payload cannot say about itself.
- `longevity_score`: 0-100 composite with per-component attribution, weights renormalized across present components as `recovery` does. **Always `bloodwork_pending: True` until a lab panel is on file.**
- `longevity_state`: parsed from `<Person>/data/longevity/`. `null` when the directory doesn't exist, which degrades gracefully. `risk_flags` is rule-generated from private text; **never hardcode private profile facts into this file.**
- `vo2_percentile`: VO2max against Cooper/ACSM norms by age + sex; `longevity` is Attia's "elite-for-a-decade-younger" target. `null` when sex is unknown.
- `hr_recovery`: 1-min HR Recovery against Cole 1999 NEJM bands. `<12 bpm` is abnormal, the 4x CV-mortality cutoff.
- `acwr`: Gabbett 2016 acute:chronic ratio. 0.8-1.3 is the sweet spot.
- `sleep_regularity`: SRI (Phillips 2017 / Windred 2024, UK Biobank n=60,977). **Populated on every tracker.** The JSON export carries `sleepStart` / `sleepEnd` per night, which is all the index needs, so `capabilities.sleep_regularity` is True and a null here means too few nights in the window rather than a source that cannot emit it.
- `rem_anomaly`: REM-proportion watch for Parkinson surveillance. `low_rem_nights` counts nights under 15% REM.
- `movement_consistency`: days hitting Apple's 30-min exercise threshold (Paluch 2022 step-days proxy).

**Apple Health weekly aggregates:**
- `health_metrics_weekly`: 4 weeks of Mon-anchored aggregates. Each entry: `{week_start, n_days, vo2max, resting_hr, hrv_sdnn, walking_hr, hr_recovery_1min, sleep_total_h, sleep_deep_h, sleep_rem_h, time_in_bed_h, resp_rate, wrist_temp_c, exercise_min}`. Read this for trends; raw daily data is behind `--include-daily-health`. Treat `time_in_bed_h` as source-dependent: on some exports it is derived from the sleep-period span rather than true Apple InBed, so phrase it as continuity / in-bed proxy unless the source explicitly supports InBed.
- `vo2max_latest`: `{date, value}` of the most recent VO2max.
- `vo2max_trend_per_4w`: OLS slope per 4 weeks across all logged VO2max readings.
- `health_metrics_recent`: raw daily rows (last 30). **Only present with `--include-daily-health`** — the weekly rollup is the default lens.

**Sleep architecture (28-day window):**
- `sleep_summary`: per-night analysis. Key absent when no nights in the window. Schedule stdevs are **circular** statistics, so a 23:50 / 00:10 bedtime pair reports a 20-min stdev, not 23h. `outliers` lists last-14-day nights under 80% efficiency or with WASO ≥1h. If `absolute_sleep_note` is present, do not call high efficiency a bright spot while total sleep is chronically short.

**Heat + cold exposure (manual /log, 28-day window):**
- `thermal_summary`: per-session sauna / cold analysis. Key absent when nothing was logged in 28d. `heat` and `cold` are independent sub-blocks. `adherence.heat_status` scores against `profile.csv`'s `sauna_target_per_week` (default 4x/wk). `adherence.duration_status` scores **dry/banya only** against the Laukkanen + mechanistic-HSP band (≥80°C AND ≥20min); steam counts as habit heat minutes, never as HSP dose.

**Light therapy (manual /log, 28-day window):**
- `light_therapy_summary`: per-session RLT / near-IR / PBM / blue-light analysis. Key absent when nothing was logged in 28d. `adherence.status` scores against `light_therapy_target_per_week` (default 3x/wk) and `session_dose_status` against `light_therapy_target_min_per_session` (default 10 min), both from `profile.csv`. The store is broad; don't make wavelength-efficacy claims it can't support.

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
- **Did the last plan happen?** → `adherence.completion_rate` plus the isolation-vs-compound split. Read `benched` and `never_performed` before selecting exercises; re-prescribing a movement the log shows is never performed delivers zero sets.
- **Is this block over?** → `block.boundary_due`. When true, every `rotating` slot must change movement pattern and the new block gets written to disk. See "Block boundary" under Programming.

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
✅ "Cardio 60 min Z2 vs 600 target. But daily activity 11,400 steps/day (high), so base aerobic load is fine. Add 1 interval session for the VO2max stimulus, not 4 Z2."

❌ "TSB is fine, push hard."
   → Numbers, not adjectives. And "fine" misses bands.
✅ "TSB +3.2 (balanced) → normal load progression; finish rep ranges before bumping."
```

The pattern: every claim about training state cites a specific numeric value from the JSON. If you find yourself writing an adjective ("fine", "moderate", "high"), check whether you also wrote the number. If not, add it.

Print the filtered values you actually use; never dump the full `rows` list into the response or the file.

## Two layers, and the writing rules for the second

**Layer 1 — internal analysis.** Do all the science in your reasoning: count sets on the fractional model, check volume against the tier targets, evaluate exercise selection, lengthened-position coverage, push-pull ratios, progression rates, tendon safety, HRV implications. Consult every relevant § in the training science reference. This is the engine and none of it is user-facing.

**Layer 2 — the output.** The user trains seriously but is not a sports scientist. No jargon, no section numbers, no citations. The rules below apply to everything written into `coach_reads.json` and `<date>-workout.md`. No exceptions.

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

Goals are fixed: hypertrophy + longevity. Never ask about goals. Your job is to author the renderer's **two inputs** and run it.

### Pipeline (5 steps — STRICT ORDER)

Three stages: **A** (Python insights), **B** (LLM authorship), **C** (HTML render). Stage B is split in two with a HARD CHECKPOINT between, so the workout plan is always built on top of a finalized assessment and never in parallel with it.

1. **(Stage A) Read tracker data, 6 months back:** `python3 Skills/workout-coach/scripts/read_tracker.py --person <Name> --months 6 > /tmp/tracker.json`. Six months is required so the 90-day training-load chart's 42-day CTL EWMA is properly warmed up before the visible window begins (anything less and the chart shows a cold-start ramp that is not real fitness movement). The Python stage produces every metric, the 5-tier `session_recommendation` gate, `nutrition_phase`, and `swim_summary` — the LLM does not re-derive any of this.
2. **(Stage B1 — assessment FIRST) Author and save `coach_reads.json`.** Read `/tmp/tracker.json`. Draft `headline` + every `cards.*` callout (including `swim_trajectory_callout` when `swim_summary` is present, `trajectory_energy` when `energy_28d` is present, and `nutrition_phase_callout` when `nutrition_phase` is present). Validate copy rules locally as you write — no em-dashes, ≤ 280 chars per card string, ≤ 560 for the headline. Write the file to `plans/<Person>/<date>-coach_reads.json`. **HARD CHECKPOINT: this file MUST exist on disk before step 3 starts.** The file IS the assessment in structured form; the workout step consumes it as input.
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

If only the coach text needs editing, edit `coach_reads.json` and re-run step 4; the tracker JSON and workout markdown stay valid as long as the payload shape hasn't changed. The renderer is idempotent and fails fast on copy-rule violations, so the loop is edit, re-run, reload the tab. Build every path with the resolvers in `shared/person_paths.py` (`plans_dir`, `workout_plan_md`, `assessment_html`). Never hand-assemble one, never write to the repo root.

### Coach-reads schema

The key list and each card's contract live in `references/assessment-dashboard.md`, and canonically in `lib/render_validators.py::COACH_CARD_KEYS`. Read the reference before authoring. Four things it does not say:

- `headline` is 2-3 sentences anchored on the longevity trajectory plus today's training call. Every `cards.*` string is one or two sentences.
- The Today intensity gloss is `session_recommendation_callout`, and it falls back to `headline` when omitted. There is no `today_headline` and no `trajectory_decathlon` card; the renderer ignores both keys.
- All `cards` keys are optional. Omit a key (or leave it `""`) and that card renders without a callout, pure data.
- `swim_trajectory_callout`, `trajectory_energy` and `nutrition_phase_callout` are the gated keys, on `swim_summary` / `energy_28d` / `nutrition_phase` being in the tracker JSON. The validator does not warn when they are missing, because their cards may legitimately not render this turn. Author them whenever the data is present.

The Trajectory tab's job is to translate raw numbers into **age-cohort context** and **longevity action**: every metric should answer *Where am I? Where should I be? What do I do about it?* — not just describe the data.

### Copy rules

The renderer enforces no em-dashes and the length caps, and fails the render on either. Beyond those: imperative voice ("Target 7.5h tonight", not "you should consider"), action only when there is one (a card whose state has not moved gets "On track, hold course." and never invented urgency), and plain English ahead of abbreviations. Known abbreviations get auto-wrapped in tooltips so you may use them, but "fitness" usually reads better than CTL and "freshness" than TSB.

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
| Daily activity | {steps_daily_avg} steps/day ({assessment}); {exercise_min_daily_avg} min/day Apple exercise minutes; {walking_workouts_count} walking workouts totalling {walking_distance_km_28d} km |
| Training load | CTL {ctl} / ATL {atl} / TSB {tsb} ({state}) |
| Recovery score | {score}/10 ({confidence} confidence; {improving / drifting / mixed} vs prior 4w) |
```

Where `{state}` is `well rested` (TSB > +5), `balanced` (−5 to +5), `carrying load` (−10 to −5), `fatigued` (−15 to −10), or `high fatigue` (≤ −15).

Every value is a direct payload read. Two source-honest fallbacks: when `trimp` and `load_band` are null on every session in the window, drop the parenthetical and write the bare count, and when `steps_daily_avg` is null, lead the daily-activity row with `{exercise_min_daily_avg} min/day Apple exercise minutes ({assessment})` instead, falling through to `{walking_minutes_28d / 28} min/day walking ({assessment})` when that is null too. The band in parentheses always sits on whichever basis leads the row. Neither case gets an explanation in the row. Prefer `training_load_by_modality.strength` over whole-body `training_load` for the load row.

**Recovery-score trend descriptor (deterministic):**
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
For each major exercise with enough data, write **one bulleted line per lift** using the format below. No bold-name paragraphs — bullets only.

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

**Respect user-provided context on outlier rows.** Before flagging a session as a "logging error" / "log typo" / "drop is suspicious", check `progression_summary[exercise].last_notes` (and `--include-rows` if you need the full per-set Notes). If the user has explicitly explained the anomaly (gym change, equipment swap, illness, deload, etc.), acknowledge the context in the sub-bullet — don't second-guess the user's own annotation. The e1RM model still counts the row, so data integrity holds and confidence may dip, but the narrative respects the annotation instead of calling it a typo.

**REQUIRED per-session TRIMP sub-bullet.** For each major lift you cover (compound or anchor isolation), append one sub-bullet that uses session-level data from `monthly_sessions[*]`. Pull the most recent strength session that contains this exercise; cite `trimp`, `load_band`, and `intensity_pct`. Compare the TRIMP to the 28d strength-session distribution.

If TRIMP for the most recent session is in the top 20% of the 28d strength distribution AND the next-day recovery score dropped, surface the carryover explicitly:

```
  - Last session TRIMP 142 (hard, 79% HRR) — top quartile for this block. Recovery score the next morning was 3.8 → cut bench frequency this week, not load.
```

Skip the TRIMP sub-bullet entirely on **strength** sessions when `capabilities.per_workout_hr_strength` is False. Don't write `Last session TRIMP None`. Drop the sub-bullet cleanly. The flag is strength-only; cardio sessions with avg HR can still render per-session TRIMP commentary.

**Optional session-HR sub-bullet.** Skip entirely on strength sessions when `capabilities.per_workout_hr_strength` is False. When the capability is present, the strength session's `avg_hr` is on `monthly_sessions[*]` directly. Use it only when it adds signal (§19 has the bands): 130-150 bpm avg is the normal hypertrophy band and warrants no sub-bullet at all, above 150 on the same load is running hot so hold load, below 110 the effort is too light so push reps before adding load.

For the per-muscle "is HR rising at constant load" call, use `hr_at_volume_divergence[muscle].hint` — that's the version that controls for volume so it's the right read of fatigue accumulating. Don't fabricate a trend if `monthly_sessions` lacks `avg_hr` on the relevant dates.

If data is too limited to judge (history < 2 entries), say that in one sentence above the bulleted list rather than as a bullet for that lift.

**Bodyweight + waist line.** One line at the bottom of this section, then one more for waist. **Read `bodyweight_trend.state` first.**

- `state: "unresolved"` — say so and stop. `Bodyweight: 76.1kg (2026-04-21). No resolved direction yet: {note}.` Do not report a gain or a loss, do not quote `point_kg_per_week` — or waist's `point_cm_per_4w` — as if it were the rate, and do not say "trending down slightly". The reason is in `reason` / `note`; paraphrase it in plain English.
- `state: "resolved"` — quote `kg_per_week` with the reading and judge it against the goal. +0.25 to +0.5 kg/wk is the hypertrophy band; above +0.5 the surplus is outrunning muscle; a resolved loss on a hypertrophy goal is under-eating and gets flagged. Cross-reference `references/training-science.md` for the numbers, don't cite § to the user.

Waist reads the same way off `waist_latest` / `waist_trend_cm_per_4w`: a direction only when `state == "resolved"`, a lone reading named as a baseline, an empty channel said out loud rather than omitted.

Entries assume morning / empty-stomach; the trend excludes rows whose Notes flag non-fasted context. When an open `nutrition_phase` exists the trend is phase-scoped: use `nutrition_phase.actuals.rate_kg_per_wk_14d` as the primary status number and the trend as supporting context. `bodyweight_weekly` and week-over-week means are noisy visual context only.

**Data sufficiency thresholds:**
- Progression trend: minimum 3 sessions with the same exercise over 2+ weeks. Below that, state "not enough data" for that exercise.
- Effort caveat: the tracker has no RIR/RPE intake. When you call a lift stalled or use reactive-deload language, explicitly say it is inferred from load/reps and not confirmed by effort-in-reserve data.
- Volume analysis: minimum 2 full training weeks. Below that, report what's visible but caveat the sample size in THE VERDICT.
- Single-session data: skip ARE YOU GETTING STRONGER entirely. State why.
- Bodyweight trend: `bodyweight_trend.state == "unresolved"` → say the direction is not resolved and why. Don't fabricate a direction.

### Missing from your tracking
List **fixable** gaps the tracker doesn't capture that would help you coach better. One line each. (This draws from §13 internally but don't cite it.) Bodyweight lands in `health_metrics.csv` whenever the user includes a `weight 76.5` line in a `/log` message; don't flag it as missing.

**Do not** list metrics the data source structurally can't provide. Read `capabilities` first: any key that's False is configured-out, not forgotten, and the user can't "track HRV better" without switching export tools. If `unknown_exercises` is non-empty, list those names and suggest the user fix the typo or add the exercise to `shared/exercises-database.md` — until they do, those sets silently count as zero volume. Likewise, consider surfacing 1-2 entries from `stale_exercises` worth reintroducing or retiring: the ones the user was making real progress on or clearly dropped by accident, not the whole list.

### Block position — REQUIRED every week

**Say out loud that the plan is meant to repeat.** Inside a block the exercise selection is deliberately stable and the LOAD is what moves; visible novelty arrives at the boundary. Nobody has told the user this, so a week that looks like last week reads as the coach being lazy rather than as the design working. Write it every single run, in plain language, whether or not anything changed.

Two sentences, from `block` and nothing else. Never compute a date.
- **Where they are.** `block.age_weeks` and `block.max_weeks` give "Week 2 of 6 in this block".
- **Why it looks the same.** State that selection holds by design and the load and rep targets are the moving parts.
- **When it changes.** `block.weeks_to_boundary` gives "Next rotation in 4.9 weeks". When `block.boundary_due` is true, say the rotation is happening in THIS plan instead.

> Week 2 of 6 in this block. Exercise selection stays put by design, the load and rep targets are what move. Next rotation in 4.9 weeks.

**Then say what actually did change**, or the first half reads as "nothing happened". Name the concrete dose moves from this plan against the last: which lifts took weight, which took reps, which held and why. `dose_staleness` tells you which carried exercises moved and which did not. If a lift genuinely held, say so and give the reason (a hold-loads recovery band, a stall response, a deload) rather than letting it pass in silence.

> Bench and row took 2.5kg each, the leg press moved to the top of its rep range, and the lateral raise holds at 15kg because recovery sat in the hold-loads band all week.

When `block` is null (no block on disk yet) skip the countdown, say the block starts with this plan, and still report the dose changes.

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

Score-band labels: `≥ 6.5` → `green`, `4–6.5` → `moderate`, `< 4` → `under-recovered`. 5/10 means "average for this person"; 4 and 6.5 mark the hold-loads window. The plan actions attached to each band live once, under Recovery-aware adjustments in Phase 2. `score == null` means too few signals had baseline coverage: treat as `low` confidence and rely on TSB and recent session history instead.

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
Sleep consistency: 0.58h stdev (threshold 1.5, component 5.0/10)
```

When `recovery.confidence == "low"`, **do not** ask the user to "track HRV better" — that's usually a source limitation or a sample-size gap, not a tracking gap. Skip the gap explanation unless it is actionable; just print the drivers the source provides and note the contributor count in the headline.

### Cardio check
Compare cardio against §10 targets (150 min Zone 2 + ~20 min intervals per week, so roughly 600 min Zone 2 + 4 interval sessions over 28 days). Flag shortfall in plain numbers: "Zone 2: 60 min logged, target ~600 min. Intervals: 0 sessions, target 4."

Take the Zone-2 number from `cardio_hr_zones_28d.z2` and the interval count from `cardio_last_28d.interval_sessions`. Use `z2_by_activity` to qualify the dose when the mix matters: short swim Z2 minutes are real HR-zone exposure but not a substitute for a dedicated 30-45 min run or ride.

**REQUIRED daily-activity gate.** Cross-check the shortfall against `daily_activity_28d.assessment` before prescribing anything, and state the call with the basis value and its band: "Daily activity 11,400 steps/day (high). Cardio prescription: hold Z2, add 1 interval session for VO2max." `high` plus a rising VO2max means keep the prescription minimal, the aerobic load is already arriving passively. `low` means add a Zone 2 session even when the 28d targets are met, because the base dose is too low. `moderate` takes the standard rule, and `null` says so out loud and falls through to it.

Call out distribution problems when `cardio_hr_zones_28d` is populated: `z3_pct > 40` is the grey-zone trap (go easier or harder, the middle is the least productive ratio), `z2_pct + z4_z5_pct > 60` is healthy polarization, and z1 dominating with little Z2 means the long hikes are activity but not the Z2 stimulus.

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
- **Fragmentation is permanently null and gets no sentence.** It was derived from `n_segments`, which the current source no longer writes on any night. Do not report it, do not call it unknown as though it were a tracking gap the user could close, and above all **never write that fragmentation improved**: the number left because the field was retired, not because the nights got smoother. Efficiency, WASO and the schedule stdevs still carry the continuity story.
- Don't claim a stage breakdown is "off" relative to population norms (e.g. "Deep should be 20% of total"). Apple's stage classifier is good enough for trend, not absolute. Stick to within-user comparison.
- Don't act on a single bad night. Two-in-fourteen warrants a routine flag; one is noise.
- `Unspecified` stage is Apple's "asleep but stage unknown" bucket. It's part of Total but isn't actionable on its own — don't surface it unless it's >25% of Total (signals stage-classifier failure, usually from a movement-heavy night).
- Per global CLAUDE rule: when `n_nights_28d < 14`, soften every claim ("over {n} nights — early window, the trend isn't stable yet").

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

### Swim

**REQUIRED when `swim_summary` is in the JSON — author `cards.swim_trajectory_callout` in coach_reads.json.** Skip the callout entirely when the key is absent (the renderer hides the swim card when there's no data, and silence is correct).

**Read `references/swim-coaching.md` first** for SWOLF / SPL / CSS interpretation, retest cadence, and the source-honesty rules (trend over absolute, no technique lecturing, no decimal SPL, one outlier lap is Watch noise).

**What the callout MUST do** (one to two sentences, ≤280 chars):

1. **Quote the 14d verdict** from `swim_summary.window_14d.improvement_verdict` (`improving` / `regressing` / `mixed` / `flat` / `insufficient_data`) in plain English.
2. **Name ONE specific signal** driving the verdict — usually the metric in `delta_vs_prior_14d` with the largest absolute movement (lower = better for pace / SPL / SWOLF). When `pace_pr` or `swolf_pr` is True, mention it.
3. **Give ONE actionable focus** for the next session (e.g., "tempo focus, hold SWOLF" or "log a CSS test"). Don't lecture technique — that's the swim-coaching.md no-go list.

**SWOLF and stroke style are permanently unavailable from the live source.** They lived in the retired XML lap payload, along with all per-lap detail. Per-workout swim aggregates (pool length, laps, strokes, SPL, distance, water temp) are written and are real data, so the callout has plenty to work with: pace per 100m, SPL, distance, session count. Comment on SWOLF or stroke mix **only** when those fields are actually populated, which now means historical swims imported before the retirement. When they are absent, say nothing about them at all. An absent SWOLF is a retired field, not a swim that went unmeasured and not stroke economy that stopped improving, and `stroke_outliers` is absent for the same reason rather than empty because the strokes were clean.

When `swim_summary.css` is null AND `swim_summary.css_test_detected` is non-null, prompt the user via the callout: "Looks like a 400m + 200m pair on {date} — was that a CSS test? Re-log with `CSS test` on the header to write it to your profile." When `swim_summary.css_missing_nudge` is present, prompt a CSS test rather than inventing zones. When `swim_summary.css_retest_due: True`, prompt the retest. When `swim_summary.stroke_outliers` is non-empty, flag the lap once as an Apple Watch misclassification candidate (one Butterfly lap in a Freestyle session = noise, not a stroke change).

Example `swim_trajectory_callout`:

> Mixed read: SWOLF dropped 4.5 (new PR at 21.9) and SPL improved 1.1, but average pace slipped 4s/100m. Stroke economy is up, raw speed is down. Next session: hold the SWOLF win, push tempo on the last 200m.

### Nutrition phase

**REQUIRED when `nutrition_phase` is in the JSON — author `cards.nutrition_phase_callout` in coach_reads.json.** Skip the callout when the key is absent (no open phase row in `<person>/data/nutrition_phases.csv`). When `current.phase_type == "bulk"`, **read `references/bulking-science.md` first**: it owns surplus / rate / off-ramp judgment and the source-honesty rules (the 14d smoothed rate over raw daily noise, one bad week is not a stop signal, surplus changes go through the structured target rather than "just eat more", the 12-week lean-bulk cap). On **any** phase type, cut included, read that file's **The 7,700 kcal/kg constant** section before you write a kcal figure: it is the source of the deficit and surplus arithmetic and it spells out what the conversion cannot support.

**What the callout MUST do** (one to two sentences, ≤280 chars):

1. **Quote the `coach_action_hint`** verbatim (`Continue phase` / `Add calories` / `Slow intake` / `Consider ending` / `End now`) — this is the binding decision token, the same way `session_recommendation.headline` is binding for the workout.
2. **Protein is target-only unless the JSON says otherwise.** If `nutrition_phase.targets.protein_tracking_status == "target_only"`, say the target is configured but intake adherence is untracked. Do not claim protein is high/low based on the target alone.
3. **Name the load-bearing 'why'** — the single signal driving the hint. Observed rate vs target ratio, a triggered stop signal, or weeks elapsed when nothing has triggered (e.g. "week 2, on-track, no signals — hold").
4. **For `consider_ending` / `end_now`**: also quote the matching `stop_signals_triggered[0]` so the user sees which pre-committed line was crossed.

Example `nutrition_phase_callout`:

> Continue phase. Week 2 at +0.24 kg/wk against a 0.25 target, no stop signals triggered. Re-evaluate after week 4; if rate creeps above 0.4 kg/wk, dial the surplus back 100-200 kcal.

#### Energy: quote the measured TDEE, name the intake number, say the intake is untracked

**REQUIRED when `energy_28d` is in the JSON: author `cards.trajectory_energy` too.** That card renders directly above the nutrition-phase card and is gated on the same block. These four rules bind both callouts, and rule 3 binds every other line you write about food.

1. **Quote the measured TDEE, not a range.** `energy_28d.tdee_kcal_daily_avg` is a 28-day daily average of the export's own active plus basal energy. Write the number with its split: "measured TDEE 3204 kcal/day, 1058 active and 2146 basal". Generic band copy such as "cut 200 to 300 kcal" is retired: it was written when there was no TDEE anchor in the payload at all, and there is one now. Do not reach for a range when the measurement is on file.
2. **Give the intake target as an actual number.** With a phase open, `nutrition_phase.energy.implied_intake_kcal` is TDEE minus `target_deficit_kcal`, and that figure is what you write: "eat about 2654 kcal/day". Check `energy.basis` first: `measured_28d` means it came off the export and can be stated flatly, and any other basis is an estimate the copy has to soften for. When the `energy` sub-block is absent there is no anchored number, so give the target as a rate in kg/wk and stop. Never derive a kcal figure yourself.
3. **Say plainly that the intake number is untracked.** Nothing in this tracker logs food. Every HealthAutoExport nutrition column is empty, so the intake figure is a **prescription and never an observation**. Phrase it the way `protein_caveat` phrases protein: the number is a configured target, no intake log is stored here, so do not claim adherence. That rules out every sentence implying we know what was eaten, including "you are eating about 2650", "intake ran high this week", "your deficit was only 200 kcal", "you hit your calories", and any praise or criticism of how the person ate. The scale is the only feedback channel on whether the prescription is landing, so judge the phase on `actuals.rate_kg_per_wk_14d` and say out loud that the scale is what you are judging it on.
4. **A falling basal trend during an open cut is adaptive thermogenesis.** A negative `energy_28d.basal_trend_kcal_per_week` while a cut is open means the expenditure floor moved down under the target, which is how a phase reads "on track" the same week the scale rate stalls. Name it as adaptation rather than a data error or a metabolism to be alarmed about, and say the intake number needs recomputing against today's TDEE instead of the one the phase opened on. `tdee_trend_kcal_per_week` is the same read on the total. The scalar is null unless the fit resolved, so a missing trend is an unresolved direction and not a flat one: read `basal_trend.state` and say so rather than reporting stability that was never established.

Example `trajectory_energy`:

> Measured TDEE 3204 kcal/day, 1058 of it active. Basal is drifting down about 9 kcal per week six weeks into the cut, which is adaptation, not a stall. Recompute the target against today's number rather than the one you opened on.

Example `nutrition_phase_callout` with energy present:

> Continue phase. Measured TDEE 3204 kcal/day puts the 0.5 kg/wk target at roughly 2654 kcal/day. Nothing here logs intake, so that is the prescription, and the 14-day scale rate, flat so far, is the only check on it.

## Phase 2: Planning (into `plans/<Person>/<date>-workout.md`)

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

If the user specified a session count in the `/coach` message (e.g., `/coach plan 3 sessions`), use it directly. Otherwise default to the person's `strength_sessions_per_week` from `profile.csv` (the same field drives split selection below). Ask **"How many sessions should I plan?"** only when that field is absent.

Generate that many strength workouts. Tier C: apply the −25% volume / hold loads / no finisher rules to workouts `1..expected_rebound_by_session`. For later workout slots, write normal-volume prescriptions only as conditional on recovery rebounding before that session; if the JSON omits `expected_rebound_by_session`, default to workout 1 only.

### Programming (internal)

**Split selection (§14) — pick the split from training frequency; do NOT default to PPL.** Read the person's target strength sessions/week from `profile.csv` (`strength_sessions_per_week`); fall back to a count given in the `/coach` message, then to recent cadence. Choose the split that trains each muscle ~2x/week at that frequency (§14): **2/wk → Full Body; 3/wk → Full Body; 4/wk → Upper/Lower (each muscle 2x); 5/wk → Upper/Lower + one rotating day.** Straight PPL trains each muscle only ~1x/week at 3-4 sessions, which is why volume sat below MEV — do not use PPL unless the person trains 6x/week. Continue the chosen split's day rotation from the last session's type. If this changes the person's prior split, say so once in the plan opener (e.g. "Moving Push/Pull/Legs to Upper/Lower so each muscle gets trained twice a week").

**An in-flight block outranks the frequency-derived split.** When `block` exists and `boundary_due` is false, keep the block's own `session_types` and slots. Do not re-derive the split from `strength_sessions_per_week` mid-block: doing so orphans every slot, so the rotation contract has nothing to diff against and the whole block artifact goes stale. The frequency rule above chooses the split **at a boundary**, and only there.

Two things this resolves. A 3/wk target sitting against a four-session-type block is **not** a conflict: per D7 the plan targets 3 sessions and treats a 4th as bonus, so a block that carries four session types is expected. Write the number of sessions the target asks for, drawing them from the block's session types in rotation. And `core_week_spec.sets_per_session` keys only on `lower` and `upper` — **a heading the gate cannot classify as either (Full Body, for instance) is held to the LOWER dose, 4-5 sets**, not to an average and not to the upper day's 2. Budget a Full Body session's core at 4, and say in the opener that the allocation was set by hand.

**Progression data:** The Step 4 summary already gives you weights and reps per exercise. Use that directly. Don't re-derive trends by walking through each exercise's history. Apply the double progression rule from §15: if the user hit the top of the rep range, bump weight. If not, same weight, push reps.

**Stall response (REQUIRED, §15).** If a lift has `stalled_sessions >= 3` and the block is not a deload, you MUST change one variable for it: swap to a variation of the same movement pattern, shift the rep range, or deload that lift. Re-prescribing the same load and reps on a 3+ session stall is a failure — the carry-forward / anchor rule is suspended for a stalled lift until a variable changes. Name the change in the plan's sub-bullet cue (e.g. "swapping flat press to incline, bench has been flat 6 sessions").

**Session duration (set-budget, NOT exercise-count):** strength-session length is driven by total **working sets**, not by how many exercises you list. Session length is `warmup + working_sets × min_per_working_set`, where `min_per_working_set` is per-person (default 3.3, but a dense/short-rest trainee runs faster — lower it via `profile.csv` so a 60-min session budgets MORE sets). Counting exercises is the trap that let sessions silently shrink: the same 7 exercises is 40 min at 2 sets each or 65 min at 4 sets each.

Budget to `target_working_sets` from the tracker JSON (derived from the per-person `session_target_min` and `min_per_working_set`; override both via `profile.csv`). Rules:
- `target_working_sets` is a **floor to hit, not a ceiling to fear**. Land within ±2 of it. Undershooting is the failure mode that under-serves the user, so if you are under, add sets to existing main exercises (3-4 sets each) before adding new exercises. Don't pad the list with 2-set accessories.
- **Budget core and arms first, not last.** They are the allocations most likely to be silently dropped when the list is assembled, and the tail of a plan is where prescriptions go unperformed. That is about allocation order; the separate terminal-slot rule on bullet position is under Core training below, and it blocks. The dose is `core_week_spec` and `arm_week_spec`; both are enforced as blocking render errors, so a plan that shorts them does not ship. What the specs cannot decide for you: **rotate the arm exercise** across sessions and blocks rather than repeating the same curl and pushdown every plan, and start a fresh variant conservative, 2-3 reps in reserve. Synergist credit never counts toward the arm floor (§8; triceps need dedicated volume beyond pressing synergy, Baz-Valle 2022).
- **Route spare sets by priority tier, not by MEV.** Read `muscle_volume_targets`: `emphasis` muscles are programmed to mid-MAV, `grow` to MEV, `maintain` to MV. A maintain-tier muscle sitting at its target is finished, not neglected, and does not get the leftover budget.
- Default main lifts to 3-4 working sets, isolation/accessory to 2-3. Hitting `target_working_sets` with ~6-8 exercises at 3-ish sets each is the normal shape; do not drop main lifts to 2 sets just to fit more movements.
- Warm-up prep movements and `(warmup)` ramp sets do NOT count toward `target_working_sets`.
- **Tier scaling is per workout index, and the validator applies it — the payload does not.** `downgrade` scales the budget to **0.6 of the base for the whole session**, for workouts `1..expected_rebound_by_session` **inclusive** (rebound 2 → workouts 1 and 2; same span as the Tier C rules above, and as the gate's own `override_message`, which reads "through workout N"); later workouts keep the full budget. `reactive_deload` scales the whole week to 0.5, Tier A to 0. **There is no scaled number in the JSON to read:** `target_working_sets` is a single unscaled scalar, so multiply it yourself for the trimmed workouts and budget the rest at the bare figure. Note it is a whole-session scale, not "25% off the secondaries": the isolation block absorbs the cut because core and arms cannot.
- **When the budget and the volume floors cannot both be met, the budget loses.** On a downgraded week for someone with several emphasis muscles, the credited-volume targets can genuinely exceed 0.6 of the budget, and no honest layout satisfies both. Priority order: the blocking floors first (core spec, arm spec), then emphasis-tier targets, then the budget. Go over budget, take the advisory warning, and say in the opener that the session runs long because the week is downgraded and the floors are not. Never short core or arms to land on a budget number — that trade is what the specs exist to prevent.
- `workout_set_budget_warnings` is **always** non-binding: an intentional deload legitimately undershoots the budget, so it surfaces as a warning and the render proceeds. Outside a deload or downgrade tier, treat it as a defect and fix it before writing. It is not the only non-binding check, though — block rotation is advisory this release, and **on a deload week the volume-axis floors demote to warnings too**: the per-session core dose, the loaded-flexion-movement requirement, the absolute flexion set floor, and both direct-arm set floors. Everything on the structure axis — placement, distinct exercises, categories, the flexion share, dose progression — blocks on every week, deload included.

**Warm-up (REQUIRED, bounded).** Every strength workout opens with a brief warm-up — never skip it, and never let it balloon past ~5 min. Two parts:
- **Two prep movements at the very top**, written as plain bullets (they carry no working volume): one general pulse-raiser (`Jumping Jacks`, `Rowing Machine`, or `Arm Circles`) plus one activation matched to the day — push → `Arm Circles` or `Wall Slide`; pull → `Scapular Pull-Up` or `Dead Hang`; legs → `Bodyweight Squat`, `Glute Bridge` or `Hip Circle Walk`. **Write the canonical catalog name and nothing else.** The bracketed tag in `exercises-database.md` (`[Band]`, `[DB]`, `[BW]`) is metadata about the entry, not part of the name: `Hip Circle Walk` renders, `Hip Circle Walk [Band]` is rejected as off-catalog and blocks the whole render. The catalog is also the equipment list, so `Band Pull-Apart` is deliberately absent (no band for it) and gets rejected too. If a movement is not in `shared/exercises-database.md`, it is not prescribable, whatever it sounds like.
- **Ramp sets on the first heavy free-weight compound only.** When the day's first working exercise is a heavy barbell or heavy-dumbbell compound (squat, bench, deadlift, RDL, overhead/DB press), precede its working sets with 1-2 ramp sets marked `(warmup)` at roughly ~50% then ~70% of the working load, low reps (≈5 then ≈3): `Barbell Back Squat: 60kgx5 (warmup) /// 80kgx3 (warmup) /// 95kgx8 /// 95kgx8 /// 95kgx8`. The `(warmup)` marker keeps them out of working-set volume and e1RM. **Skip the ramp sets** when the first lift is a light cable / machine / isolation movement — the two prep movements are enough. Never ramp later compounds; by then the user is warm. Ramp sets and prep movements count toward neither the set budget nor the exercise count.

Use Layer 1 analysis plus the training science reference. The reference contains the full rules; apply them:
- **Mesocycle structure** (§15): tell the user where they are in the block and what this week's targets are. No static plans.
- **Exercise pairing** (§16): straight sets for compounds, supersets for isolation/accessories when it saves time.
- **Exercise variation** (§17): the week's exercise selection must cover different regions of each major muscle. Anchor compounds where progression is live carry forward; variation plays out in isolation/accessory slots and across blocks.
- **Volume, frequency, overload, push-pull balance, lengthened position, tendon safety, HRV session placement, deload timing**: §1, §5, §6, §7, §8, §9, §11.
- **Deload handling (§11):** compute weeks-since-last-deload from `deloads[-1]`. In the 4-6 week window, flag it in the plan opener and offer a deload. **Past 6 weeks (or empty `deloads`), prescribe ONE deload session** — halve that single session's working sets and hold its loads — rather than converting the whole block to half volume. A routine cadence deload must not erase a week of arm and core volume across every session. Disclose it in the plan opener (the `> Why:` line), e.g. "Session 1 is a deload, 7 weeks since your last one." A full-block deload happens only on a reactive trigger (gate Tier B) or explicit user request, not on calendar cadence alone.
- **Re-entry after long break:** compute days-since-last-session from `monthly_sessions[-1].date`. If > 5 and no deload on record in that gap, treat the first prescribed session as a re-entry — drop one working set per compound, prescribe "leave 2-3 reps in the tank" instead of 1-2. Tendon adapts slower than muscle (§7), so under-load the first session back.
- **Recovery-aware adjustments (§18):** **Lead with `recovery.score`** — it already folds HRV, RHR, sleep total, sleep stages, sleep consistency, wrist temp, and HR Recovery into one renormalized weighted average of personal z-scores (5 = personal average; VO2max trend is **not** in the score — it lives separately in `vo2max_latest` / `vo2max_trend_per_4w` for the cardio check). Apply:
  - `recovery.score < 4` → next session is re-entry: drop one working set per compound, prescribe "leave 3-4 reps in the tank" instead of 1-2. Lead with the dominant negative driver on the recovery-drivers card.
  - `recovery.score 4–6.5` → hold loads, no PR attempts, normal volume. **"Hold loads" is binding on every prescribed working weight — compounds, accessories, isolation, and core alike. Default behavior: copy last session's load forward and let reps drive progression.** The only legal load *increase* is when the user hit the top of the rep range cleanly on the last session AND the recovery / TSB band still permits it (see the TSB-band rule below — bumps are off the table in `balanced` / `carrying load` / `fatigued` / `high fatigue` bands). No exceptions for "small isolation" or "doesn't matter much".
  - **Hold loads does not mean hold the dose.** The advisory ceiling still fires at or above 40% of carried exercises returning an identical prescription, and with load frozen the intended lever is the **rep target**: carry the weight forward and advance the rep range or the rep goal within it, which is exactly what double progression asks for under a hold. That is a real dose change and it counts as one. Churning set counts to move the metric does not: adding or dropping a set purely to make the prescription differ changes weekly volume for no training reason and breaks the tier targets. If a lift genuinely has nowhere to go on either axis, leave it and let it read as stale rather than manufacturing a change.
  - **Cold-start escape hatch.** Copy-forward has nothing to copy for a movement with no logged history, and taken literally it makes every new movement illegal to prescribe. It does not apply to them. For a movement absent from the log, its derived starting load in `rotation_candidates.candidates[]` **overrides the copy-forward rule** and is the load you write, at that block's `target_reps`. It already carries the first-exposure discount, so do not discount it again; write it as prescribed and let the next session's log take over. **When `load_kg` is null, `load_basis` decides what to do and there are three cases, not one** — the split is spelled out under `rotation_candidates` in Phase 1. Only `bodyweight` means "prescribe reps or seconds, no weight"; `no_reference` and `unknown_transfer` both mean the pipeline could not derive a safe number and are **not** a bodyweight signal, so pick a conservative weight yourself, one controllable for `target_reps` with 2-3 reps in reserve, and say so in one sub-bullet cue. A movement with no candidate entry at all is the same instruction.
  - `recovery.score ≥ 6.5` → green light, normal programming.
  - `recovery.confidence == "low"`: the score's available signals are still trustworthy, but soften any rule that would otherwise override the deload window. Don't invent triggers from data the source doesn't provide.
  - When `recovery.score < 4` AND `recovery.drivers` has the negative signal persisting (e.g. wrist temp +0.4°C on a multi-week stretch in `health_metrics_weekly`) → flag deload as urgent regardless of `deloads` cadence. Override the standard 4-6 / 6+ week thresholds.
- **Per-muscle fatigue from HR creep (§19):** read `hr_at_volume_divergence`. For any muscle whose `hint == "rising HR at constant volume — fatigue or under-recovery"`, hold or cut volume on that group this block — don't add sets. Say so on the per-muscle-volume card's coach line, not in the workout markdown. For muscles with `hint == "improving conditioning"` you can add a working set if it's also under MAV. Skip this rule entirely when per-workout HR is unavailable and `hr_at_volume_divergence` is empty.
- **Training-load gate (§19, REQUIRED):** for strength prescriptions, read `training_load_by_modality.strength.tsb` when present; fall back to `training_load.tsb` only when no strength TRIMP exists. The band MUST be cited by name on the training-load card, e.g. "strength TSB −5.4 → balanced/carrying load boundary; this block holds loads." Mention whole-body/cardio TSB only as secondary fatigue context.

  | TSB | State | Plan rule |
  |---|---|---|
  | > +10 | Well rested / detrained | Bump anchor compounds 2.5kg even if rep range isn't fully completed. State why in the table Notes. |
  | +5 to +10 | Well rested | Normal load progression rules apply. PR attempts allowed if rep ranges are met. |
  | −5 to +5 | Balanced | Hold loads, finish rep ranges first (current default). |
  | −10 to −5 | Carrying load | No PR attempts. Cut top set's RIR target to 2-3 (was 1-2). |
  | −15 to −10 | Fatigued | Drop one working set per compound across the board. |
  | ≤ −15 | High fatigue | Deload regardless of weeks-since-last-deload cadence. Say it is a deload in the plan opener. |

  **Partial-source caveat:** When `capabilities.per_workout_hr_strength` is False, CTL/ATL/TSB are computed only from cardio TRIMPs — strength load is invisible to this metric. Do **not** apply the TSB-band prescription unilaterally on these trackers; cross-check with `recovery.score` and prefer `recovery.score` as the primary fatigue signal. A negative TSB driven by hike load alone is not a deload trigger — a 200-min hike will always look like fatigue to TSB even if the user is well-rested otherwise. Cite the cross-check when overriding the band.
- **Per-muscle volume actions (REQUIRED).** Compare `weekly_volume_per_muscle.current[muscle]` against `muscle_volume_targets[muscle].target_sets`, not against MEV. The tier sets the target: `emphasis` runs at mid-MAV, `grow` at MEV, `maintain` at MV. Under-target muscles get the spare budget; a muscle at its tier target is finished. Name the muscle on the relevant card whenever you move its volume.
  - **Above MRV:** cut at least one working set from that muscle's primary movement next block. If `recovery.score < 6.5` as well, replace the next scheduled session targeting that group with a Z2 block or a rest day. This overrides any "add a set" reflex elsewhere in the planning logic.
  - **Under target:** add one working set to its primary movement, unless the TSB band is `fatigued` or `high fatigue`. **If the muscle has no movement in the week at all, add the movement** — adding a set to a movement that isn't there is a no-op, and that is exactly how a muscle stays at zero.
  - **When several muscles are under target, spend the budget in this order:** emphasis tier first, then muscles with no movement anywhere in the week, then the largest shortfall as a fraction of target. A flat "route to the laggards" with ten claimants routes to none of them.
  - **Core does not take spare sets.** Its dose is `core_week_spec`, enforced per session. Do not add a fifth core set because core reads under target; fix the distribution instead, which is what the weekly axes of the spec are for.
  - When a muscle is both under target and flagged by the HR-creep rule, **hold or cut wins**. Prefer reducing load over adding it.
- **Cardio (§10):** read the Cardio check numbers from the Report. If behind target, add cardio sessions to the plan after the strength sessions. Default weekly target: 3× Zone 2 @ 30-45min + 1× intervals @ 20min. Cap total cardio additions at 4 sessions per `/coach` run — if the user is very behind, note the shortfall and prescribe the max. User can override with `/coach no-cardio` to skip this entirely.

**Stale exercise reintroduction.** Pick 1-2 entries from `stale_exercises` and restart them per the conservative-reintroduction rule in §17. The workout markdown may carry only a short action cue such as `first time back; ease in`; the reasoning goes in the dashboard coach text.

**Core training (§24).** The countable part is `core_week_spec`, enforced as blocking render errors: per-session dose, distinct exercises, pattern categories, per-exercise frequency, one loaded flexion movement a week, and the flexion set floor. Do not restate any of it here or reason about it as if it were advisory. Select from the rotation-pool structure in §24.3: one loaded flexion slot, one rotating non-flexion slot cycled by category across blocks.

**Terminal-slot placement is enforced too — for core AND for direct arm work.** Both are blocking render errors, not judgement calls. Core goes inside the isolation/accessory block, supersetted with an unrelated isolation movement (curls, lateral raises, calves, triceps); **never the final bullet of a workout, never before a compound.** The same rule blocks arms: **a biceps or triceps exercise as the last bullet of a workout is a blocking error** — arms sit inside the isolation block, and the session closes on something that is neither core nor arms (rear delts, calves, a face pull). **Not "a carry".** `Suitcase Carry` is a core movement (anti-lateral-flexion in the catalog), so closing on it trips the core placement error instead of avoiding it. The only carry that is not core is `Dumbbell Farmer Walk`, and that one is a finisher budgeted outside the core allocation — if you close on it, it earns no core credit. Order does not affect hypertrophy (§24.2), but the last slot is where prescriptions go unperformed, and moving core ahead of the compounds costs the compounds for no gain.

What the spec cannot decide, and you must:
- **Which movement, given this person's log.** `adherence.never_performed` and `benched` outrank exercise-selection theory. A prescription with a 0% completion rate delivers 0 sets. Change the movement or change its position; do not re-prescribe a benched one at all.
- **Progression.** Double progression on load, exactly as for any isolation lift. Body-fat and visibility framing lives in §24.6 and stays out of programming rules.

**Equipment increment grid (REQUIRED).** Loads are prescribed on the equipment's increment grid. Never suggest off-grid weights.
- **Cables:** 5kg steps (5, 10, 15, 20, 25, …). Round to the nearest available plate.
- **Dumbbells:** 1-2kg pair increments depending on the rack. When in doubt, round to the nearest 2kg.
- **Plate-loaded machines:** 5kg per plate side. Round prescribed loads to the nearest 5kg unless the gym is known to have half-plates.
- **Microloading:** for barbells only, and only when the user has explicitly logged microplates before.
Re-read this block before every load suggestion.

**Exercise ordering and equipment grouping:** compounds first, then isolation, then accessories, with core placed as above. Batch cable work together, bench work together, and so on, but **only within the isolation/accessory block** — never reorder compounds or move an isolation ahead of a compound for equipment convenience. When the core movement shares equipment with that block (a cable crunch in a session that already has cable work), place it inside that equipment group.

**Bench prompt.** When `adherence.bench_prompt` is present, ask the user its `question` **once** in chat, then persist the answer before writing the plan:

```
python3 -m workout_coach.lib.adherence bench-record --person <Name> \
  --exercise "<Exercise>" --disposition retired|retry --answer "<their words>"
```

`retired` drops the movement from selection; `retry` clears the bench so it can be prescribed again. Without the write, the same question comes back every run and "ask once" is a lie. Ask nothing when the key is absent, and never ask about more than one exercise per run.

`bench_prompt.kind` decides what you are actually asking:
- **`benched`** — the movement was prescribed into sessions the user trained and skipped, and other routes to that muscle exist. The coach stops prescribing it. The question is **why**: equipment, dislike, or cut for time. `retired` if it is not coming back, `retry` if the answer names something fixable.
- **`route_blocked`** — same skipping evidence, but benching it would strand a muscle at emphasis or grow tier, or empty a core pattern category, so it is **not** benched. It sits in `adherence.bench_blocked` with a `blocked_reason`. The question is not why but **what instead**: ask for a substitute. Name the stranded thing precisely — the pattern category, not the muscle. "The only route to core" is false and useless when the person has twelve core movements and the real gap is anti-rotation at zero logged sets. Then persist: `retired` with their words when they name a substitute (prescribe it in that slot this generation), `retry` when they say the movement itself is fixable.

**Block rotation — advisory this release.** The intent is one sentence: **exercise selection is stable inside a block and rotates at the boundary.** Loads and rep targets are what move week to week; the movements themselves are meant to stay put until `block.boundary_due` fires. That is deliberate, and the assessment has to tell the user so (see "Block position" in Phase 1).

Follow it as guidance. Findings print as warnings and **do not refuse a render** for this release, so a violation costs you a warning, not the plan. Read `block.slots[]` for what each position holds now, `must_rotate` for the slots the boundary has come due for, `anchor_overdue` for anchors that have aged out, and `pattern` for what a slot actually trains.

What "rotated" means, when the boundary does come:
- **A different movement pattern, not a different equipment word.** Cable Lateral Raise to Dumbbell Lateral Raise is the same muscle, same joint action, same `pattern`. It is not rotation. Landing in a `pattern` the session did not already have is what stops anti-rotation and loaded carries sitting at zero forever.
- **Not a name the slot has held recently.** Alternating two movements every block rotates nothing; `slots[].history` is what makes that visible.
- **Anchors persist.** They change only for a named reason from `block.anchor_change_reasons` (`stall_3_sessions`, `injury`, `age_3_blocks`). Anchors exist so progression has something to accumulate on.
- **Rotated-in and `at_risk` accessories get supersetted onto a compound earlier in the same session** via `superset_with`, so the set lands in that exercise's rest window. Moving an accessory earlier was tried on 2026-07-25 and the moved movements were still dropped; removing it from the marginal-time budget is the fix that works. Spread guests across hosts rather than hanging several off one.

Every slot must be a catalog name regardless, or its pattern cannot be resolved at all.

**Writing the block down.** When `block.boundary_due` is true this generation authors a NEW block rather than a continuation, and it has to be persisted:

```
python3 -m workout_coach.lib.blocks write --person <Name> --from-plan <YYYY-MM-DD>
```

`<YYYY-MM-DD>` is the plan you just wrote. Skip this when `boundary_due` is false. An unwritten block is not a record: generation N+1 has nothing to differ from, which is the whole reason plans repeated.

Inside a block, a split day that recurs in the week (two Upper days, two Lower days) is two different session types in the artifact, so the repeats are not clones by construction. Keep one actively progressing anchor per muscle and let the second exposure lead with a different angle or pattern.

### Per-workout format in the file

The workout markdown is a **lean exercise list**, nothing more. No tables. No rationale paragraphs. The "why" lives in the assessment dashboard (and only there). The user trains from this file on their phone in the gym — every line they don't need slows them down.

No em-dashes in workout markdown prose. The only allowed em-dashes are the title separator (`# Workout plan — <date>`) and the indented sub-bullet marker (`  — cue`). In `> Today's call:` / `> Why:` blockquote lines, use a period, comma, semicolon, or colon instead; a prose em-dash will fail the renderer.

Every strength workout heading is followed by `Date: ___\` then `Recovery: sauna ___ / cold ___ / rlt ___`, each on its own line, then a blank line, then the bullets. The trailing backslash is a Markdown hard break and keeps the two placeholders from collapsing into one paragraph. The user fills the date in when they actually train, and replaces only the recovery blanks for modalities they did (`sauna 12+8min 85C dry / cold 30s shower / rlt ___`, or `skipped`, or nothing). `/log` parses each modality independently per `workout-logger/references/parsing-rules.md`. Cardio sections need neither line.

**Exercise bullets** — one line per exercise. No code fences. **There is one set format and it is `///`. Every set is its own `///` entry, always, whatever the unit.** 4 sets = 4 entries.
- Weighted: `Dumbbell Flat Bench Press: 52kgx10 /// 52kgx10 /// 52kgx10`
- Ranges: `Cable Lat Pulldown: 65-70kgx8-10 /// 65-70kgx8-10 /// 65-70kgx8-10`
- Holds, in seconds or `MM:SS`: `Plank: 45s /// 45s /// 45s`
- Loaded carries, in metres, both sides: `Suitcase Carry: 24kgx30m /// 24kgx30m /// 24kgx30m`
- Bodyweight reps: `Hanging Knee Raise: 10-12 /// 10-12 /// 10-12`

**Never write `Plank: 45s hold` for a three-set plank.** That form is unambiguously ONE set and the validator counts it as one, so a three-set prescription written that way silently delivers a third of the dose. The validator credits seconds, `MM:SS` and metres as set tokens, with a 10-second and 10-metre floor below which a token is not work.

Warm-up prep movements use the same format with no special marking. Warm-up **ramp sets** on the first heavy compound carry a `(warmup)` marker on each ramp set (see the Warm-up rule in Programming) so they stay out of volume and e1RM.

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

A note appears **only** for a form cue that matters today (`— leave 1-2 in tank`, `— pause at the top`), a safety or injury flag (`— elbow nagging; cut volume if pain >2/10`), or a one-time deviation from autopilot (`— first time back; ease in`, `— travel gym: scale 60 to 35kg`). Anything else belongs on the dashboard: comparative history ("last time you did 50kg x 8"), load rationale ("you've been stuck at 40kg"), reintroduction history, generic exhortation, restating what the bullet already shows, or cross-references to the dashboard. `validate_workout_md` catches most of these.

Style: lowercase, no period at the end, one short clause, em-dash prefix. **Soft cap 0-2 per workout** — a third is the signal that rationale is creeping in.

**Superset hints do not count against that cap.** The indented sub-bullet is the only channel the markdown has for `superset_with`, and rotation rule 6 requires one on every rotated-in or `at_risk` accessory, so a legal plan can need four or five of them in a session. They are structure, not rationale. Write every one the rotation contract requires and let the count go where it goes. `validate_workout_md` counts all sub-bullets together and will warn `N sub-bullets; recommended max is 2` — **that warning over-counts and is not blocking.** Do not delete a required superset hint to satisfy it. The cap still binds on the three rationale reasons above.

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
- Cable Face Pull: 20kgx12-15 /// 20kgx12-15
```

Two warm-up prep movements + two ramp sets on the first heavy compound, two sub-bullets (the soft cap), sparse per-set parentheticals, the rest clean lines. That's the target density.

**Count the sets in that example: 24 working sets** (4 bench + 4 shoulder press + 4 fly + 2 core + 4 lateral raise + 4 triceps + 2 rear delt; the two ramp sets and the two prep movements don't count). That is not decoration — it lands exactly on a 24-set budget, and the example is written to be copied. An example that models 18 sets teaches an 18-set session. This is an UPPER day, so its core allocation is 2 sets; a LOWER day carries 4. Note where core and arms sit: inside the cable block, supersetted with an unrelated isolation movement, neither of them on the last line — the face pull closes the session precisely because it is neither, and both block in the terminal slot. One session cannot show the weekly core distribution — read `core_week_spec` for that — **and the same caveat covers arms.** Validated on its own, this example returns four WEEK-level blocking errors: the flexion set floor, both direct-arm set floors, and the distinct-triceps-exercise axis. That is the example being a legal SESSION shape and not a legal WEEK, not a bug in it. `core_week_spec` and `arm_week_spec` are satisfied across the plan's sessions; do not copy this one session N times and expect it to render.

### Cardio sessions (only when prescribed)

Written as their own sections after the strength workouts, not mixed in. Two shapes, both `## Cardio N: <kind> (<duration>)` followed by plain bullets. **The heading is `##`, the same level as `## Workout N`** — at `###` the parser keeps these bullets inside the preceding workout and then rejects `Warmup` / `Work` / `Cooldown` / `Notes` as off-catalog exercise names, which points at the wrong repair entirely:

```
## Cardio 1: Zone 2 (30-45 min)

- Treadmill run or outdoor, HR 140-150bpm (65-75% max)
- Target duration: 35 min
- Notes: pair with an off day or separate from leg work by 6-24h (§10 interference)

## Cardio 2: Intervals (20 min total)

- Warmup: 5 min easy
- Work: 5 × 3 min @ HR 165-175bpm (Zone 4-5), 2 min easy between
- Cooldown: 5 min easy
- Notes: not within 24h of a heavy leg session
```

If the user is on target (`Cardio check` in the report shows no shortfall), don't add cardio sessions to the plan. Don't over-prescribe — cap at 4 cardio sessions total per `/coach` run.

### Where the rationale goes

The workout markdown carries no rationale at all: it links to the dashboard at the top, and the "why" lives on the card showing the data. TSB band citation on the training-load card, dominant driver on the recovery-drivers card, HR-at-volume on the strength-progression and per-muscle-volume cards. Omit the HR-at-volume call entirely when `hr_at_volume_divergence` is empty rather than fabricating one, always pick a dominant recovery driver because there is always one, and treat the TSB citation as mandatory on both sources.

## Common Mistakes

Before finalizing a plan or dashboard, skim **`references/common-mistakes.md`** — the full catalog of failure modes with the correct behavior for each. The load-bearing planning rules in it are enforced inline above and by the render validators; the reference is the backstop.

## Rules

- Goals fixed. Never ask.
- No generic advice disconnected from their data.
- Don't soften findings.
- If data is too thin, say what you can and can't tell from it.
- One clarifying question max if the tracker is unreadable.
