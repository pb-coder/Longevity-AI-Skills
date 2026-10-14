---
name: workout-coach
description: >
  Reads the requested person's tracker (per-person CSVs under
  <Person>/data/), analyzes recent training state, and writes dated
  files to plans/<Person>/: the structured assessment (coach_reads.json)
  and a lean strength-only workout-plan markdown. The self-contained
  assessment HTML dashboard is rendered only when the user asks for it
  ("report", "dashboard", "assessment"). Invoked by the `/coach`
  slash command or when the user explicitly asks for coaching, analysis,
  or a new plan. Do NOT trigger on general fitness questions, training
  discussion, logging, or requests unrelated to the tracker.
---

# Workout Coach

**Invocation**: The `/coach` slash command delegates here. You can also be asked directly ("plan my next workout", "how is my training going"). The non-triggers are in the frontmatter `description`; logging belongs to `workout-logger` via `/log`.

## Who is this for?

Two trackers live in per-person folders inside the workout directory: `<Person>/data/` and `<OtherPerson>/data/` (CSV store: monthly/ + dense + swimming/). Both are fed by Health Export Kit, so `data_source` is `health_export_kit` on every tracker. Neither person has a per-lap swim store; per-workout swim aggregates are written on both.

Resolve which person this request is about BEFORE running the script:
- If the user names a person or tracker, use that name.
- If pronouns or context clearly refer to one tracker, use that tracker.
- Otherwise ask which tracker/person this is for before proceeding.

Pass the resolved name via `--person <Name>`. Outputs go to `plans/<Person>/` at the workout-tracker root, dated per generation. Never write one person's plan over the other; never write to the repo root (the old `./workout_plan - <Person>.md` files are frozen history). Build every path with the resolvers in `Skills/shared/person_paths.py`: `plans_dir(person)`, `workout_plan_md(person, date)`, `assessment_html(person, date)`.

## Setup

1. Read `../shared/exercises-database.md` for muscle mappings, synergist tags (`+muscle` = 0.5 sets), lengthened-position flags (`◆`).
2. Read `references/training-science.md` and use its Quick Lookup table for each part of the analysis. Read the other references only when their trigger applies:
   - `swim_summary` present: `references/swim-coaching.md`.
   - `nutrition_phase` present and `current.phase_type == "bulk"`: `references/bulking-science.md`. On any phase type, or whenever `energy_28d` is present, read that file's **7,700 kcal/kg constant** section before writing a kcal figure.
   - Training through a break, illness, closure or deliberately reduced dose: `references/detraining-and-minimal-dose.md`. With no gym at all, also `references/no-equipment-training.md`.
   - Tier A, B or C, or an override: `references/substitute-protocols.md`.
3. Run `python3 Skills/workout-coach/scripts/read_tracker.py --person <Name> --months 6 [--sessions N] > /tmp/tracker-<Person>.json` from the workout-tracker root (the same command as Pipeline step 1; `--sessions N` only when the user asks for a different count, see **Sessions**). It returns one JSON blob of session-level signals; every key is documented under **Data Reading Strategy**. Several blocks are gated on data presence and are simply absent when there is nothing to report. If the data folder isn't there, the script prints an error: relay it in one line and stop. Don't search the filesystem. Output is compact JSON (`--pretty` for inspection). `rows` (the flat per-set list) is off by default; pass `--include-rows` only for debugging.
4. From the output, identify the **most recent workout** (last date with logged sets). Note the muscle groups and exercises. Don't repeat the same primary muscle emphasis in the very next session.

## Output target

Every run writes **two dated files** under `plans/<Person>/`, and a third only on request:

- `<YYYY-MM-DD>-coach_reads.json`: the assessment (headline + card callouts). **Always written, before the plan.**
- `<YYYY-MM-DD>-workout.md`: the lean workout list. **Strength workouts only**: no cardio sections, no Zone 2 or interval prescriptions, no tables, no rationale block. Sub-bullet notes only when genuinely actionable.
- `<YYYY-MM-DD>-assessment.html`: the self-contained dashboard. **Opt-in: render it only when the user's `/coach` message asks for it** ("report", "dashboard", "assessment", or a clear equivalent). The script `scripts/render_dashboard.py` owns all HTML; you never hand-write any. Its card inventory, data contracts and the coach-reads schema are in `references/assessment-dashboard.md`.

`<YYYY-MM-DD>` is the JSON's `today`. Each generation writes a fresh dated set; older ones stay on disk. Plans dated before 2026-08-02 predate the current core spec and fail today's gate: read them for history, never as a template.

**Cardio is analysis, never prescription.** Cardio data feeds every read (recovery, training load, the cardio and behavioural cards). It never becomes a section, bullet or instruction in the workout markdown.

The chat gets one short block: a one-line verdict plus `Wrote plan to plans/<Person>/<date>-workout.md (N sessions)`, then `check_plan.py`'s warning count (and the warnings themselves when there are any). When the report was asked for, add `Wrote dashboard to plans/<Person>/<date>-assessment.html`. Nothing else.

### Workout-plan markdown structure

```
# Workout plan — <YYYY-MM-DD>
> Today's call: <session_recommendation.headline>
> Why: <rationale notes>

Assessment: ./<YYYY-MM-DD>-assessment.html   (only on a run that renders the report)

<intro: block position, what changed, the food line>

## Workout 1: <TYPE>
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- <general warm-up>: e.g. Jumping Jacks: 50
- <activation matched to the day>: e.g. Arm Circles: 20
- Exercise: weight × reps (`///`-separated sets)
  — optional one-line sub-bullet note (rare)

## Workout 2: <TYPE>
...
```

The plan ends after the last strength workout. Everything above the first `##` heading is the **opener**; the checks cross-check numbers in it against the payload. Write each file in one pass; don't stream sections to chat.

## Data Reading Strategy

`scripts/read_tracker.py` handles the data quirks (date normalization, casting, deload detection, cardio categorization). Call it once; don't re-read the CSV store inline. Print only the values you use.

**Source + capabilities (read first to gate sections):**
- `data_source`: `health_export_kit`. Trust it.
- `capabilities`: per-source feature map. **False = structurally unsupported**: gate sections on it and never ask the user to track something their source cannot emit. For this source `hrv` and `wrist_temp` are False: there is no HRV and no wrist temperature, and the recovery score runs without them. `sleep_regularity` and `sleep_nights` are True. `thermal_log` and `light_therapy_log` are manual-log, so their summaries are gated on data presence instead.
- **Permanently unavailable, whatever an empty field looks like**: HRV and wrist temperature, Apple's 1-10 effort score (so there is no effort-in-reserve intake), beat-to-beat intervals and RMSSD, ECG, swim stroke style / SWOLF / per-lap detail, and Apple's own HR-zone boundaries. Never list these under a missing-from-tracking note, and never read an emptied field as something that changed about the person. Sleep fragmentation (`sleep_summary.fragmentation`) IS available; see the sleep card rule.
- `auto_cardio_enabled`, `today`, `estimated_max_hr`, `estimated_rest_hr` (derived once; all HR-zone / TRIMP math uses them).

**Strength + cardio sessions:**
- `monthly_sessions`: one entry per session-date, ascending: `{date, exercise_first, session_kind, active_cal, total_cal, elevation_m, elapsed, avg_hr, max_hr, duration_min, volume, is_deload, trimp, load_band, intensity_pct}`. The canonical session record. `load_band`: `light` (TRIMP < 50), `moderate` (50-100), `hard` (100-150), `red-line` (>150).
- `weekly_volume_per_muscle`: `{window_days, current: {muscle: sets_per_week}, landmarks: {muscle: {mv, mev, mav, mrv}}}`. Fractional sets (primary 1.0, synergist 0.5). **`current[muscle]` is already per week**: compare it directly to landmarks, don't divide again.
- `estimated_1rm`: `{Exercise: {current_e1rm_kg, prev_e1rm_kg, best_e1rm_kg, last_date, delta_vs_prev_kg, slope_kg_per_4w, confidence, stalled_sessions, context_change_excluded, deload_excluded}}`. `slope_kg_per_4w` is the trend signal; soften when `confidence` is `low`. **`stalled_sessions` = trailing sessions at the same load with no rep gain**, counted on load and reps, not on e1RM (the same count `next_dose` carries). It is a plateau, not a regression. The gate treats a stall as a reactive-deload trigger only when the lift is near its best, not trending up, and corroborated by an independent fatigue signal.
- `progression_summary`: list of `{exercise, sessions_logged, last, prev, last_notes}`. `last_notes` is the user's own annotation on the last set.
- `stale_exercises`: top 5 not logged in 28+ days, newest-stale first (`exercise, last_date, weeks_since, sessions_logged`). The reintroduction pool; each has a `next_dose` entry while its last log is within 120 days.
- `unknown_exercises`: names not in the database; their sets count as zero volume.
- `deloads` (user-marked dates) and `auto_deload_candidates` (dates the heuristic thinks were unmarked deloads: ask, never claim).

**Cardio + daily activity:**
- `cardio_last_28d`: `{sessions, total_minutes, total_distance_km, total_active_cal, non_interval_minutes, interval_sessions}`. `non_interval_minutes` is NOT Zone 2 (a 3h Z1 hike lands in it).
- `cardio_hr_zones_28d`: HRR time-in-zone, **the canonical source for Zone-2 minutes** (`z2`, `z2_by_activity`, `z3_pct`, `z4_z5_pct`).
- `daily_activity_28d`: NEAT. `assessment` (`low` / `moderate` / `high`) is the band; `steps_daily_avg` is its primary basis (low < 7,000, high >= 10,000), and `assessment_basis` names which of `steps` / `exercise_min` / `walking_minutes` it was read off. Quote the band with its basis.
- `energy_28d` (absent, not zeroed, when there are no energy rows): measured daily expenditure, **an expenditure block, not intake**. `tdee_kcal_daily_avg`, `active_kcal_daily_avg`, `basal_kcal_daily_avg`, `n_days`; trends `tdee_trend_kcal_per_week` / `basal_trend_kcal_per_week` are populated only when the fit resolved (read `tdee_trend.state` / `basal_trend.state` first; never quote `point_kcal_per_week` as the rate). `nutrition_phase.energy` (on an open phase): `{tdee_kcal, target_deficit_kcal, implied_intake_kcal, basis}`; `implied_intake_kcal` is a prescription derived from a measurement.

**Recovery + training load:**
- `recovery`: `{score: 0-10 | null, confidence, drivers: [...]}`. A renormalized weighted average of personal z-scores over the signals with enough sample; 5 means average for this person. `drivers` are sorted by deviation from 5, most-deviating first. `score` is null when no signal had sample (typically: no recent health import). The score is context, not a load rule: loads come from `next_dose`.
- `training_load` (whole-body) and `training_load_by_modality` (`all`, `strength`, `cardio`), each `{ctl, atl, tsb, trend_7d}`. TSB = CTL - ATL (positive fresh, negative under load). The gate and the plan use `strength`; whole-body is secondary context.
- `hr_at_volume_divergence`: `{muscle: {slope_bpm_per_4w, n_sessions, hint}}`, or a single `systemic_session_hr` entry when many muscles flag together (a shared shift: check bodyweight, heat, deload boundaries before changing per-muscle volume). Slope >= +5 bpm/4w = fatigue or under-recovery.
- `session_recommendation`: the binding gate. See **Recovery gate** in Phase 2.

**Bodyweight + waist (two channels):**
- `bodyweight_latest`, `bodyweight_trend`, `bodyweight_trend_kg_per_week`, `bodyweight_weekly`, `waist_latest`, `waist_trend_cm_per_4w`. **Read `state` first.** `resolved` means the 95% interval excludes zero; `unresolved` carries a `reason` and a plain-English `note` and is an answer, not a failure. `point_kg_per_week` and `point_cm_per_4w` are raw point estimates and also appear on a resolved fit: only the resolved rate (`kg_per_week` / `cm_per_4w`) is quotable, never a point value. `bodyweight_trend_kg_per_week` is null unless resolved. With an open nutrition phase, use `nutrition_phase.actuals.rate_kg_per_wk_14d` as the primary status number.
- **Waist is the leanness channel; bodyweight is not.** The scale alone cannot separate recomposition from fat gain. A single waist reading is a baseline and supports no trend claim. When `waist_latest` is absent, say the channel is empty ("no waist measurements on file; the scale alone can't separate muscle from fat") instead of dropping it.
- **Progress photos**: on the FIRST plan of each calendar month, put one short line in the opener asking for a monthly progress photo. Nothing in the tracker reads images: never claim to have looked at one. Skip the line on every other plan that month.

**Prescription memory and planning inputs:**
- `adherence`: the previous plan reconciled against the logs. Null on a first run (no evidence, not 0% adherence). Key fields: `window_open` (the newest plan is still live, its misses are not yet misses), `sessions_planned` / `sessions_performed`, `completion_rate` and `tested_completion_rate`, `per_exercise[]`, `never_performed[]`, `benched[]`, `bench_blocked[]`, `bench_prompt`. **Quote both completion rates or neither**: the gap is attendance, the second alone is within-session truncation. `missed_sessions` says nothing about whether the user rejects the movements inside them. **A benched exercise must not be re-prescribed**; a `bench_blocked` one stays prescribable until the user answers (see Bench prompt). A `retired` movement is never in `bench_blocked`: it is benched, and excluded from `next_dose`, `rotation_candidates` and the block's slots.
- **`next_dose`**: the next load and rep range for every lift logged in the last 120 days, stale ones included (retired movements are excluded). The coach copies it; see **Loads and reps** in Phase 2. `{load_policy, exercises[], uncovered}`. Each `exercises[]` entry: `exercise`, `load_kg`, `rep_range`, `action` (`add_load` / `add_reps` / `hold` / `reduce` / `no_history`), `basis` (the one-line reason), `increment_kg`, `increment_basis`, `last`, `last_load_kg`, `last_reps` (list), `sessions_at_load`, `stalled_sessions`, `range_from`, and sometimes `other_gym_load_kg`. A lift whose latest session of any kind (the other gym and a marked deload included) is `STALE_EXERCISE_DAYS` (28) or more days back is a re-entry: `hold`, no progression, its `load_kg` re-derived from the last best set at the bottom of the range (rounded to the nearest step, never above the last load) and, past 56 days away, times the 0.85 first-exposure discount; with no range on record it carries the standard range (6-8, 8-10, 10-12, 12-15, 15-20; compounds top out at 12) that holds the median reps of its last session, and `range_from` says `derived from last session reps`. For machine, cable, Smith and landmine lifts `load_kg` is always the usual gym's load; `other_gym_load_kg` is the load at the other gym when known. `uncovered` = `{reason, exercises[]}` lists timed, unloaded and off-catalog work as `{exercise, last_prescription}` (`last_prescription` is null if never prescribed).
- `block`: the current training block: `block_id`, `started`, `age_weeks`, `max_weeks` (6), `weeks_to_boundary`, `boundary_due`, `boundary_reason`, `weeks_since_deload`, `deload_cadence_weeks`, `deload_cadence_due`, `deload_prescribed`, and `slots[]` tagged `anchor` or `rotating` with `pattern`, `dose`, `blocks_held`, `history`, `must_rotate`, `anchor_overdue`, `stalled_sessions`. Computed in code because cadence deloads get skipped. `slots[].dose` can be stale: where it disagrees with `next_dose`, `next_dose` wins. `core_spec.copy_core_slots` false (`compliant` false) means the block's core slots break `core_week_spec`: derive the week's core work from the spec and copy only the non-core slots.
- `rotation_candidates`: catalog movements the coach may prescribe without a `next_dose` entry: `derivation` (the rule, stated once), `target_reps`, `novelty_discount`, `candidates[]` with `exercise`, `pattern`, `load_kg`, `load_basis`, `ref`, `confidence`. It always offers a main pattern with no working set in the last 56 days, priced from the person's own history. **For a movement with no `next_dose` entry, `candidates[].load_kg` is the only legal source of a starting weight.** A lift that has both (a main pattern gone untrained, last logged inside 120 days) is priced the same way in both places (e1RM rep-matched, 0.85 discount, nearest step) but at different rep counts: the candidate at `target_reps`, `next_dose` at the bottom of its own range. Copy `next_dose`; the candidate is for lifts without an entry.
  - **A null `load_kg` has three meanings and `load_basis` tells them apart.** `bodyweight` (with `unit: "bodyweight"`): no external load, prescribe reps or seconds. `no_reference`: no same-pattern sibling has logged history. `unknown_transfer`: a sibling exists but no coefficient covers the equipment pair.
  - `no_reference` and `unknown_transfer` both mean "we could not derive a safe number", not "bodyweight". Treating them as bodyweight prescribes an unloaded set of a loaded lift. Pick a conservative weight yourself, one you can control for `target_reps` with 2-3 reps in reserve, say so in one sub-bullet cue, and let the next session's log take over.
- `core_week_spec`: `sets_per_session` (4 lower / 2 upper, one set over passes, two block), `min_distinct_exercises_per_week` 3, `min_pattern_categories_per_week` 3, `max_sessions_per_exercise_per_week` 2, `min_loaded_flexion_exercises_per_week` 1, plus a flexion SET floor: `min_flexion_sets_per_week` 3 or `min_flexion_share_of_core_sets` (1/3), whichever is larger. A four-session week is 12 core sets so the floor is 4 flexion, and one set moved out of flexion drops under it: program a set of margin. All blocking; on a deload week the volume-axis findings (per-session dose, loaded flexion, flexion set floor) demote to advisory while placement, distinct exercises, categories, per-exercise cap and the flexion share keep blocking. Write the full per-session core dose on a deload anyway (see **Deload and re-entry**).
- `arm_week_spec`: `min_distinct_exercises_per_week` 2 per muscle (blocking). The direct-set floor for arms is part of `muscle_floors`.
- `muscle_priority_tiers` / `muscle_volume_targets`: every muscle resolved to `emphasis`, `grow` or `maintain`, with `target_sets` in the **fractional** unit (emphasis = mid-MAV, grow = MEV, maintain = MV). Sourced from `profile.csv`.
- **`muscle_floors`**: `{muscle: direct sets per week}`, the blocking floor per muscle, already scaled by min(1, `strength_sessions_per_week` / 4); a muscle with no floor is absent, not 0. A different unit from `target_sets`; see **Weekly volume** in Phase 2.
- `strength_sessions_per_week` (the session count to plan) and `last_session_type` (where the split rotation continues from: the next session is the one after `last_session_type.title` in the block's session order): top-level, read from the payload, not from `profile.csv`.
- `target_working_sets`: the unscaled per-session working-set budget (from `session_target_min` and the per-person minutes per set).

**Longevity trajectory (Trajectory tab inputs).** Field names are self-describing; what the payload cannot say about itself:
- `longevity_score`: 0-100 composite, weights renormalized across present components. **Always `bloodwork_pending: True` until a lab panel is on file.** `longevity_state` is parsed from private text and null when absent; never hardcode private profile facts into this file.
- `vo2_percentile` (null when sex is unknown), `hr_recovery` (1-min HRR below 12 bpm is abnormal), `acwr` (0.8-1.3 is the sweet spot), `sleep_regularity` (SRI; null means too few nights), `rem_anomaly`, `movement_consistency`.

**Apple Health weekly aggregates and sleep:**
- `health_metrics_weekly`: 4 Mon-anchored weeks of `{week_start, n_days, vo2max, resting_hr, walking_hr, hr_recovery_1min, sleep_total_h, sleep_deep_h, sleep_rem_h, time_in_bed_h, resp_rate, exercise_min}`. `time_in_bed_h` may be derived from the sleep-period span: call it continuity, not clinical in-bed time. `vo2max_latest` and `vo2max_trend_per_4w` (null until 4 readings over 21+ days).
- `sleep_summary` (absent with no nights in 28 days): per-night analysis with circular schedule stdevs, `sleep_efficiency_pct` (with `source`), `schedule_consistency`, `outliers`, `absolute_sleep_note`.

**Heat, cold and light (manual `/log`, 28-day window; keys absent when nothing was logged):**
- `thermal_summary`: `heat` and `cold` sub-blocks. `adherence.heat_status` scores against `sauna_target_per_week` (default 4). `adherence.duration_status` scores dry/banya only against the >= 80 C and >= 20 min HSP band; steam counts as habit minutes, never HSP dose.
- `light_therapy_summary`: `adherence.status` against `light_therapy_target_per_week` (default 3) and `session_dose_status` against `light_therapy_target_min_per_session` (default 10).

**How to read the signals (no need to dig into `rows`):**
- **Should I train hard today?** `session_recommendation.tier` and `.load_policy`, which are binding. Cite `recovery.score` only when `load_policy.recovery_available` is true; otherwise say recovery data is missing.
- **Volume** → `weekly_volume_per_muscle.current[muscle]` vs `landmarks` / `muscle_volume_targets`; name the band (MEV/MAV/MRV).
- **Per-muscle fatigue** → `hr_at_volume_divergence`.
- **Progress** → `estimated_1rm[exercise].slope_kg_per_4w` for the trend; `next_dose` for what to load next.
- **Cardio distribution** → `cardio_hr_zones_28d.z3_pct` > 40% is the grey-zone trap; healthy is `z2_pct + z4_z5_pct` dominant.
- **Last session** → `monthly_sessions[-1]` (TRIMP, `load_band`, `intensity_pct`).
- **Deload triage** → `deloads` vs `auto_deload_candidates`; if non-empty, ask: "Did you deload on {date}? The data looks like it."
- **Did the last plan happen?** → `adherence`. Read `benched` and `never_performed` before selecting exercises.
- **Is this block over?** → `block.boundary_due`.

**Anti-patterns:** every claim about training state cites a number from the JSON. An adjective ("fine", "moderate") needs its number beside it, and a score or trend needs its leading driver.

```
❌ "Recovery is moderate with all signals close to baseline."   (names the score and bails)
✅ "Recovery 4.5/10. Sleep 6.9h vs a 7.1h baseline (z -0.3) and resting HR +1.5 bpm are the two soft signals."

❌ "Several muscles show rising HR, don't push."                 (generic)
✅ "Calves +5.2 bpm/4w, glutes +6.6 bpm/4w (limit +5): no added sets on either. Other muscles stable."

❌ "TSB is fine, push hard."                                    (adjective, no band)
✅ "Strength TSB +3.2 (balanced). Loads follow next_dose: lifts that hit the top of their range get weight."
```

## Writing rules for coach_reads.json and workout.md

Do the science in your head (set counts on the fractional model, tier targets, selection, lengthened-position coverage, push-pull ratios, tendon safety, deload timing, consulting the relevant §s). None of it is user-facing. The user trains seriously but is not a sports scientist: no jargon, no section numbers, no citations.

- Short sentences. Vary length. Specific numbers ("12 back sets a week, enough") over adjectives.
- Imperative voice ("Target 7.5h tonight"). Action only when there is one: a card whose state has not moved gets "On track, hold course.", never invented urgency.
- No em dashes (the renderer fails on them; the only allowed ones in workout.md are the title separator and the `  — cue` sub-bullet marker). Use periods or commas.
- Banned words: crucial, vital, pivotal, robust, comprehensive, significant, key role, landscape, delve, multifaceted, intricate, "serves as", "stands as", "testament to". No "Additionally / Moreover / Furthermore / Nevertheless" openers, no hedging stacks, no filler ("It is important to note that"), no near-synonym triplets. Bold only for exercise names in progression.
- "Fitness" reads better than CTL, "freshness" better than TSB; known abbreviations are auto-wrapped in tooltips so they are allowed.

## Phase 1: Assessment (coach_reads.json) and plan checks

Goals are fixed: hypertrophy + longevity. Never ask about goals.

### Pipeline (STRICT ORDER)

1. **Read tracker data, 6 months back:** `python3 Skills/workout-coach/scripts/read_tracker.py --person <Name> --months 6 [--sessions N] > /tmp/tracker-<Person>.json` (one file per person: both trackers never share a path; `--sessions N` is optional, see **Sessions**). Six months warms up the 42-day CTL EWMA for the 90-day load chart. The Python stage produces every metric, the `session_recommendation` gate and `next_dose`: don't re-derive any of it.

   **Tier A or B: stop here and ask.** If `session_recommendation.tier` is `A` or `B`, write nothing yet. Tell the user the tier, its `label`, the gate's `session_recommendation.headline` and the top `rationale` notes, and ask which of the three options in "Recovery gate" they want. The answer decides which tracker JSON the assessment is written against. Tier C, D and E continue automatically.
2. **Author and save `coach_reads.json`** (headline + every `cards.*` callout, rules under **Coach cards**) to `plans/<Person>/<date>-coach_reads.json`. **HARD CHECKPOINT: this file MUST exist on disk before step 3.**
3. **Author `plans/<Person>/<date>-workout.md`.** Re-open `coach_reads.json` from disk (it forces the plan to honor the saved assessment, not paraphrase it from memory). Quote `cards.session_recommendation_callout` in the opener paragraph (the gate's `headline` goes only in `> Today's call:`, see Phase 2). Then draft the exercise bullets under the gate. Strength only. Rules in Phase 2.
4. **Check the plan. Always. Must exit 0.**
   ```
   python3 Skills/workout-coach/scripts/check_plan.py \
     --tracker /tmp/tracker-<Person>.json \
     --coach plans/<Person>/<date>-coach_reads.json \
     --workout-md plans/<Person>/<date>-workout.md
   ```
   It runs every check the renderer runs (`lib/plan_checks.run_plan_checks`) and writes nothing: the payload, `coach_reads.json` cross-checked against the tracker numbers, the workout copy rules and catalog names, the core spec and the per-muscle weekly floors (blocking), the set budget and block rotation (advisory), three more advisories (a written dose that differs from `next_dose`, a week missing one of the four main patterns, a cardio section), and the number check on the opener. It also requires `coach_reads.json` to be strictly older on disk than `workout.md`. **Exit 2 means fix the plan (or `coach_reads.json`) and rerun until it exits 0.** Relay any warnings in the chat summary. If it prints a `next_dose drift`, `main pattern` or `cardio section` warning, fix the plan and rerun, unless it is a deliberate exception the opener states.
5. **Render the report, only when the user asked for the report:**
   ```
   python3 Skills/workout-coach/scripts/render_dashboard.py \
     --tracker /tmp/tracker-<Person>.json \
     --coach plans/<Person>/<date>-coach_reads.json \
     --workout-md plans/<Person>/<date>-workout.md \
     --out plans/<Person>/<date>-assessment.html \
     --person <Person>
   ```
   On a report run, add the `Assessment: ./<date>-assessment.html` line to the plan intro before step 4, so the checks run on the final file. If the report is asked for after a plan was written, run this step on that day's saved files with a freshly read tracker JSON; the analysis is not redone. If only the coach text needs editing, edit `coach_reads.json` and rerun step 5 (or step 4).

### Coach cards

The key list is `lib/render_validators.py::COACH_CARD_KEYS`; each card's data contract is in `references/assessment-dashboard.md`. The renderer enforces no em dashes, <= 280 characters per card string and <= 560 for `headline`. All `cards` keys are optional (a missing one renders pure data), except that `block_position` always warns when missing. The gated keys (`swim_trajectory_callout`, `trajectory_energy`, `nutrition_phase_callout`) are not warned about when absent, but author them whenever the data is present. There is no `today_headline` and no `trajectory_decathlon` card.

Keep lines tight. The user is an established trainee: say what **changed** since the last block, and give a card whose state hasn't moved one sentence. The Trajectory cards translate numbers into age-cohort context and longevity action: where am I, where should I be, what do I do.

**`headline`** (the coach's own `coach_reads.json` string, not the gate's `session_recommendation.headline`): 2-3 sentences anchored on the longevity trajectory and today's call, with days since the last session (`monthly_sessions[-1].date` vs `today`): "last trained 2 days ago, normal cadence".

**Today tab**
- `session_recommendation_callout`: the gate's call in plain words (tier, `label`, what drove it). If `load_policy.policy` is `reduce`, say loads hold and sets are cut, and why. If `recovery_available` is false, say recovery data is missing and the call rests on strength freshness. Falls back to the gate's own `headline` when omitted.
- `today_acwr`: `acwr` against the 0.8-1.3 band.
- `recovery_drivers`: lead with `recovery.score`, then the one or two leading entries of `recovery.drivers` by name, with recent value vs personal baseline. If `score` is null, say recovery data is missing (no recent health import) instead. If `confidence` is `low`, say so; never ask the user to track HRV or wrist temperature (the source cannot supply them).
- `activity_rings`: strength and cardio sessions, Zone 2 (take the number from `cardio_hr_zones_28d.z2`, intervals from `cardio_last_28d.interval_sessions`; qualify with `z2_by_activity` when a short swim is padding the total), recovery practices, sleep.
- `block_position` (**REQUIRED every week**): inside a block the exercise selection is stable by design and the load and rep targets move. Nobody has told the user this, so a week that looks like last week reads as laziness. In plain language, from `block` and nothing else (never compute a date): where they are ("Week 2 of 6", from `age_weeks` and `max_weeks`), that selection holds by design, and when it changes (`weeks_to_boundary`, or "rotating in THIS plan" when `boundary_due`). Then say what the dose does next, from `next_dose.exercises[].action`: which lifts take weight (`add_load`), which chase reps (`add_reps`), which are held and why (quote the `basis`). Add the deload clock when it matters: `weeks_since_deload` against `deload_cadence_weeks`, and "a deload is still owed" when `deload_cadence_due`. With `block` null (or `age_weeks` null), say the block starts with this plan and skip the countdown.
  > Week 2 of 6 in this block. Selection stays put by design, the load and rep targets are what move. Bench and row take weight, the leg press chases reps, the lateral raise holds after a 5-week gap. Next rotation in 4.9 weeks.
- `training_load`: cite the **strength** TSB (`training_load_by_modality.strength.tsb`; whole-body only as secondary context) and its band by name (`load_policy.tsb_band`: `over_recovered`, `balanced`, `carrying_load`, `fatigued`, `high_fatigue`). If `auto_deload_candidates` is non-empty, phrase it as a question.
- `muscle_volume`: per-muscle verdicts against `muscle_volume_targets`, naming the muscle whenever you move its volume. With fewer than 2 full training weeks of data, report what is visible and caveat the sample. Name any `unknown_exercises` (their sets count as zero volume until the typo is fixed or the exercise is added to `shared/exercises-database.md`), and the HR-creep calls from `hr_at_volume_divergence` (omit the HR call when that block is empty). One or two stale exercises worth reintroducing are fair game; never list the whole `stale_exercises` list.
- `strength`: per major lift, `prev_e1rm_kg -> current_e1rm_kg` with `slope_kg_per_4w` as the trend (drop the trend chunk when null; with `confidence` `low`, say the e1RM is noisy at 12+ reps and don't claim a trend). Call a stall only on `stalled_sessions >= 2`, and say it is inferred from load and reps, because the tracker has no effort-in-reserve data. A negative `delta_vs_prev_kg` with a flat-or-negative slope and no deload around it is a real flag; with a positive slope it is one bad session. If `context_change_excluded >= 1`, say the slope reset on a gym or equipment change and don't call the lift stalled or regressing. Respect the user's own annotation in the lift's `progression_summary` entry (`last_notes`): an explained outlier is not a logging error. Skip the card (and say why) with fewer than 3 sessions over 2+ weeks, or with a single session of data.

**Trajectory tab**
- `trajectory_longevity_score`, `trajectory_recovery`, `trajectory_risk_flags`: one sentence each on the domain, from `longevity_score`, `recovery`/`hr_recovery`/`rem_anomaly`, and `longevity_state` risk flags.
- `trajectory_cardio`: the cardio check against the Zone 2 target (about 150 min Zone 2 plus about 20 min of intervals a week, so roughly 600 min and 4 interval sessions over 28 days; flag a shortfall in plain numbers: "Zone 2: 60 min logged, target ~600"). **Cross-check against `daily_activity_28d.assessment` before calling it a gap**, and state the band with its basis: `high` with a rising VO2max means the shortfall is mostly on paper; `low` means the base dose is too low even when the 28-day targets are met; `null` says so and takes the standard read. Call out `z3_pct` > 40 (grey zone) and z1-dominated hike time. Append the VO2max line from `vo2max_latest` (trend only when `vo2max_trend_per_4w` is non-null).
- `trajectory_body_comp`, `vitals`: bodyweight and waist under the rules in the Bodyweight section: direction only when `state == "resolved"` (+0.25 to +0.5 kg/wk is the hypertrophy band; above +0.5 the surplus is outrunning muscle; a resolved loss on a hypertrophy goal is under-eating), a lone waist reading named as a baseline, an empty channel said out loud.
- `trajectory_metabolic`, `trajectory_behavioral`: as the data supports (`movement_consistency`, `daily_activity_28d`, adherence).
- `trajectory_sleep`, `sleep` (present when `sleep_summary` is): total with stage means, efficiency or continuity (call it continuity or an in-bed proxy when `sleep_efficiency_pct.source` is `derived_sleep_period`; > 85% healthy, < 80% disturbed), and schedule consistency (+/-30 min tight, +/-90 min erratic). State the short-sleep floor first when `absolute_sleep_note` is present. Soften every claim under 14 nights and ignore one bad night. `fragmentation.n_segments_mean` (segments per night, lower is better) is available: use it only to explain a soft efficiency or continuity read, never as a headline number or a trend under 14 nights. Don't judge stage splits against population norms; compare within the user.
- `recovery_practices` (present when `thermal_summary` or `light_therapy_summary` is): adherence against the **configured** target ("below the configured target", never a moral failure), the HSP band for dry/banya only, cold with its `cold_temp_c` when set (a -2 C outdoor session is a real dose; `dose_hint: "amber"` is a weak one), multi-round sessions count as ONE session. Light therapy: did it happen and at roughly what duration; no wavelength-efficacy claims.
- `swim_trajectory_callout` (when `swim_summary` is present; read `references/swim-coaching.md` first): quote `window_14d.improvement_verdict` in plain English, name the ONE signal behind it (the largest move in `delta_vs_prior_14d`, lower is better for pace and SPL; mention `pace_pr` / `swolf_pr` when true), and give ONE focus for the next session. Don't lecture technique. Comment on SWOLF or stroke mix only when populated (historical swims only; absent is a retired field, not unmeasured). Prompt a CSS test when `css` is null and `css_test_detected` or `css_missing_nudge` is present, and a retest when `css_retest_due`; flag `stroke_outliers` once as a watch-misclassification candidate.
- `nutrition_phase_callout` (when `nutrition_phase` is present; read `references/bulking-science.md` first on a bulk): quote `coach_action_hint` verbatim (it is the binding token), name the one load-bearing why (observed rate vs target, a triggered stop signal, or weeks elapsed with no signal), and for `consider_ending` / `end_now` quote `stop_signals_triggered[0]`. If `targets.protein_tracking_status == "target_only"`, say protein is a configured target with no intake tracked.
- `trajectory_energy` (when `energy_28d` is present). These four rules bind this callout, the nutrition callout, and every other line about food:
  1. **Quote the measured TDEE, not a range**, with its split: "measured TDEE 3204 kcal/day, 1058 active and 2146 basal".
  2. **Give the intake target as a number**: `nutrition_phase.energy.implied_intake_kcal`, softened unless `energy.basis` is `measured_28d`. With no `energy` sub-block, give the target as a kg/wk rate and stop. Never derive a kcal figure yourself.
  3. **Say plainly that intake is untracked.** Nothing in this tracker logs food, so the number is a prescription, never an observation. No sentence may imply we know what was eaten ("you are eating about 2650", "intake ran high", "you hit your calories"). The scale (`actuals.rate_kg_per_wk_14d`) is the only feedback channel; say so.
  4. **A falling basal trend during an open cut is adaptive thermogenesis**: name it as adaptation, and say the intake number needs recomputing against today's TDEE. A null trend scalar is an unresolved direction, not stability: read `basal_trend.state`.

## Phase 2: Planning (into `plans/<Person>/<date>-workout.md`)

### Recovery gate (REQUIRED before any plan generation)

**Step 1: read `session_recommendation`.** It is deterministic and binding, with five tiers:

| Tier | label | What the plan contains |
|---|---|---|
| **A** | `rest` | **Ask the user first** (below), then whichever option they chose. |
| **B** | `reactive_deload` | **Ask the user first** (below). `substitute.kind` says whether the gate wants a deload week or a recovery day. |
| **C** | `downgrade` | Planned strength with the working-set budget scaled x0.6 for workouts `1..expected_rebound_by_session` (later workouts keep the full budget). No finisher. Loads are NOT held: they follow `next_dose`. Core and the per-muscle floors are not scaled, so the isolation block absorbs the cut. |
| **C** | `hold_load` | Planned strength at the full budget, no finisher. Loads follow `next_dose`; neither volume nor load is cut. |
| **D** | `green` | Normal plan. |
| **E** | `over_recovered` | Normal plan plus a one-line note that fitness is bleeding off (when `recovery_available` is false the gate says over-recovery is unconfirmed: say that). |

**Load policy.** `session_recommendation.load_policy` has `policy`, `tier`, `label`, `strength_tsb`, `tsb_band`, `recovery_score`, `recovery_available`, `reason`. `policy` is `progress` or `reduce` only. `reduce` happens only on gate Tier A or B or a strength TSB of -15 or lower: loads are held and sets are cut. Everything else, Tier C and the carrying-load and fatigued bands included, is `progress`; so is a user gate override (`reason` then states the TSB and that the user overrode). When `reduce`, quote `reason` in the opener's `> Why:` line. When `recovery_available` is false, say recovery data is missing; don't cite a score.

**Step 1b: Tier A or B: stop and ask in chat. Never decide alone.** Right after `read_tracker`, before writing anything, flag the tier, its `label`, the gate's `session_recommendation.headline` and the `rationale` notes, then offer three options and wait:

1. **Rest day.** The rest-day template in `references/substitute-protocols.md`: hydration, sleep, the re-check next morning. No strength, no cardio.
2. **Lighter strength.** Fewer sets and held weights, using the reactive-deload template in `references/substitute-protocols.md`. Keep the tracker JSON as it is: the tier's reduced set budget and deload rules are what `check_plan.py` judges against.
3. **Normal strength anyway**, for example for the following week. Regenerate the tracker JSON with `read_tracker.py --override-gate`, then plan a normal Tier D block.

Use a structured question when the client offers one. Tier C, D and E never ask.

**Step 2: the gate's call is quoted in the opener**: `> Today's call:` is the gate's own `session_recommendation.headline`, verbatim (never the coach's `coach_reads.json` `headline`), and `> Why:` is the top 3 `rationale` notes.

```markdown
# Workout plan — 2026-05-24
> Today's call: <session_recommendation.headline>
> Why: <rationale[0].note> · <rationale[1].note> · <rationale[2].note>
```

**Step 3: build the body from the template for the chosen option** in `references/substitute-protocols.md`. None contains cardio. Only Tier D / E (and an overridden A / B / C) use all the programming rules below unchanged; a Tier A or B rest day consults none of them.

**Override protocol.** Overrides happen only when the user **explicitly** asks: on Tier A or B by choosing option 3, on Tier C by asking to train normally ("ignore the downgrade"). Never generate normal strength on a Tier A or B day on assumption. Regenerate with `read_tracker.py --override-gate` (it normalizes the tier to green and full budget, keeping the original rationale in `override_message`), then author a normal Tier D block. Never hand-strip a downgrade from a JSON that still says Tier C: it desyncs the checks from the plan.

### Programming

**Sessions.** Use the session count from the `/coach` message, else the payload's `strength_sessions_per_week`, and ask "How many sessions should I plan?" only when that is absent. `muscle_floors` scale with the payload's count, which comes from `profile.csv`, not from the message: when the user asks for a different number than `strength_sessions_per_week`, re-run `read_tracker.py` with `--sessions N` before planning.

**Split (do NOT default to PPL).** Choose the split that trains each muscle about twice a week at that frequency: 2/wk and 3/wk Full Body, 4/wk Upper/Lower, 5/wk Upper/Lower plus one rotating day (§14). PPL only at 6/wk. Continue the split's rotation from the payload's `last_session_type`. If this changes the person's prior split, say so once in the opener. **An in-flight block outranks the frequency-derived split**: when `block` exists and `boundary_due` is false, keep its own `session_types` and slots; the frequency rule chooses the split at a boundary only. A 3/wk target against a four-type block is not a conflict: write the target number of sessions, drawn from the block's types in rotation. `core_week_spec.sets_per_session` knows only `lower` and `upper`, so a heading it cannot classify (Full Body) is held to the LOWER dose, 4-5 sets: budget 4 and say in the opener that the core allocation was set by hand.

**Four main patterns every week.** Each week's plan must contain a horizontal push (`CHEST/Horizontal Push (Compound)`), a vertical or overhead push (`SHOULDERS/Vertical Push (Compound)`), a horizontal pull (`BACK/Horizontal Pull (Compound)`) and a vertical pull (`BACK/Vertical Pull (Compound)`). A split change does not carry the shoulder press along by itself: place it on purpose. `rotation_candidates` always offers a main pattern with no working set in the last 56 days, with a derived load; take it from there (if the lift also has a `next_dose` entry, that entry's load wins). `check_plan` now warns when one is missing (advisory), but getting it right is still on you. If an in-flight block lacks one of the four, add that pattern to a session that has room and take the sets from its isolation block: a missing main pattern is the one reason to change a block's selection mid-block.

**Loads and reps: copy `next_dose`.** For every exercise you prescribe that has an entry in `next_dose.exercises[]`, write its `load_kg` and `rep_range` exactly. Do not choose weights, re-round, convert or widen a range. The rule behind it: when every working set at the working load reached the top of the range, the lift gets its `increment_kg` and the range restarts from its bottom (`add_load`); otherwise same load, same range, more reps (`add_reps`). Rep ceilings are already applied (compounds top out at 12, isolation at 20). `load_kg` uses the log's own convention: a two-dumbbell lift is the total of both hands. Each entry's `increment_kg` is the step that lift takes, learned from the person's own log (machine, cable, Smith and landmine lifts: only since the latest gym-change note; `increment_basis` says how) and never below the smallest real step: 2 kg for two dumbbells (1 kg a hand), 1 kg for one dumbbell, 1 kg otherwise; a jump of that size or less that is also under 5% of the load it started from (64 to 65 kg, 55 to 56 kg) is re-weighing, not a step, while 4 to 5 kg on a cable is. With fewer than two usable jumps the equipment table stands: 4 kg for two dumbbells, 2 kg for one, 5 kg a machine, 2.5 kg a barbell, cable, Smith or landmine. Never adjust a `next_dose` step: do not add your own increment, round it, or swap in a weight you think is more convenient. Never suggest an off-grid weight.
- `add_load` / `add_reps`: copy the entry.
- `hold` is per exercise only (re-entry of a stale lift, a lift last logged at the other gym or machine, no rep range on record, a prescription that tops out at 1-2 reps, which is never bumped automatically). For a stale lift whose last reps were below range, the code has already lowered `load_kg` from the last best set. Copy `load_kg`. A plain re-entry needs no cue (`— first time back; ease in` is optional); any other `hold` (every session at the other gym, no rep range on record, a prescription that tops out at 1-2 reps) needs a one-line cue quoting the `basis`. With `rep_range` null, choose a range inside the ceilings and keep it next time.
- A lift may carry two doses in a plan (a heavy and a light day). `next_dose` holds one: it is judged against the dose of the workout the last session matched (`range_from` names it), and `check_plan` stays silent when either dose matches `next_dose` and warns once when neither does. Never collapse two intentional doses to satisfy `next_dose`.
- Two gyms: write `load_kg` (the usual gym's load). When `other_gym_load_kg` is present, add the cue `  — other gym: X kg` (exempt from the sub-bullet cap).
- `reduce` (policy `reduce`): load held, sets cut (halve them, per the lighter-strength template). A `hold` entry gets the same treatment under `reduce`: halve its sets, keep its load.
- **Cold start.** `no_history` and any movement with no entry: take the load from `rotation_candidates.candidates[]` at the block's `target_reps`. It already carries the first-exposure discount, so don't discount it again. When `load_kg` is null, `load_basis` decides (see `rotation_candidates` above: `bodyweight` means reps or seconds; `no_reference` and `unknown_transfer` mean pick a conservative weight you can control with 2-3 reps in reserve, and say so in one cue).
- `uncovered` (timed holds, carries, unloaded or off-catalog work; entries are `{exercise, last_prescription}`): no dose is derived; carry the `last_prescription` and progress by reps or seconds. When `last_prescription` is null, choose a conservative dose and say so in one cue.

**Stall response (REQUIRED).** It applies only to a `next_dose` entry whose `action` is `add_reps` (or `hold`) with `stalled_sessions >= 3` (trailing sessions at the same load with no rep gain), outside a deload. A lift whose `action` is `add_load` is bumped, never swapped, whatever its `stalled_sessions` (a lift at its rep ceiling is owed weight), and never widen a range to hide a stall. For the stalled lift, change one variable: swap to a variation of the same movement pattern, or deload that lift. Re-prescribing the same load and reps on a 3+ session stall is a failure, and the carry-forward / anchor rule is suspended for it until a variable changes. Name the change in the sub-bullet cue ("swapping flat press to incline, bench has been flat 6 sessions").

**Set budget (set count, not exercise count, drives session length).** Budget each session to `target_working_sets` (from `session_target_min` and the per-person minutes per working set; override both in `profile.csv`).
- It is a **floor to hit, not a ceiling to fear**: land within +/-2. If under, add sets to existing main exercises (3-4 each) before adding exercises. Default main lifts to 3-4 working sets and isolation to 2-3. Warm-up prep movements and `(warmup)` ramp sets do not count.
- **Tier scaling is per workout index and the payload does not apply it.** `target_working_sets` is one unscaled number: multiply it yourself by 0.6 for Tier C `downgrade` workouts `1..expected_rebound_by_session` inclusive, and by 0.5 for the whole week on `reactive_deload` and Tier A lighter strength.
- `workout_set_budget_warnings` are always non-binding (an intentional deload undershoots); outside a deload or downgrade, treat one as a defect and fix it.

**Weekly volume.**
- **Per-muscle weekly floor (blocking in `check_plan`).** Every muscle in `muscle_volume_targets` has a weekly floor in DIRECT sets: sets of exercises whose primary muscle it is. Synergist credit never counts. The payload's `muscle_floors` gives each floor: **emphasis tier = the muscle's MEV in direct sets; every other tier = its MV.** Exempt (absent from `muscle_floors`): erectors, forearms, core (it keeps its own per-session rules in `core_week_spec`), and muscles with a direct MV of 0 (glutes, front delts, adductors, neck, external rotators). The payload scales the floors by min(1, `strength_sessions_per_week` / 4), and by (n - 0.5) / n on a cadence deload week with n sessions; they stay blocking then. They are advisory only on a full-block deload (see **Deload and re-entry**). `muscle_volume_targets[muscle].target_sets` is in the fractional unit (direct plus synergist credit) and must never be compared to a direct count. Biceps and triceps are rows of this floor, not a separate rule.
- **Priority order when sets are tight.** The floors (`muscle_floors`) and the core spec are hard: never short either. The tier targets (spare sets toward grow-tier MEV and emphasis-tier mid-MAV) get only the sets left inside the set budget once those are met. The budget loses to the floors and the core spec and to nothing else: go over only as far as they force, take the advisory warning, and say in the opener why the session runs long.
- **Route spare sets by tier, not by MEV.** Compare `weekly_volume_per_muscle.current[muscle]` to `muscle_volume_targets[muscle].target_sets` (same fractional unit). A maintain-tier muscle at its target is finished and gets no leftovers.
  - **Under target:** add one working set to its primary movement, unless `load_policy.tsb_band` is `fatigued` or `high_fatigue`. If the muscle has no movement in the week, add the movement. With several under target, spend in this order: emphasis tier, muscles with no movement anywhere in the week, then the largest shortfall as a fraction of target.
  - **Above MRV:** cut at least one working set from that muscle's primary movement. This overrides any "add a set" reflex.
  - **Core does not take spare sets.** Its dose is `core_week_spec`, per session; fix the distribution instead of adding a fifth set.
  - **HR creep** (`hint == "rising HR at constant volume — fatigue or under-recovery"`): hold or cut that muscle's volume this block (baseline: its direct sets in the last plan) and add no sets. This is a volume rule: loads still follow `next_dose`. When a muscle is both under target and flagged, hold or cut wins. For `improving conditioning` a set may be added if it is under MAV. Say it on the `muscle_volume` card, not in the workout markdown.
- **Rotate the arm exercise** across sessions and blocks rather than repeating the same curl and pushdown, and start a fresh variant conservative (2-3 reps in reserve). `arm_week_spec` also requires 2 distinct direct exercises a week per arm muscle.

**Warm-up (REQUIRED, bounded to ~5 min).** Every strength workout opens with two prep movements as plain bullets (they carry no working volume): one general pulse-raiser (`Jumping Jacks`, `Rowing Machine` or `Arm Circles`) plus one activation matched to the day (push: `Arm Circles` or `Wall Slide`; pull: `Scapular Pull-Up` or `Dead Hang`; legs: `Bodyweight Squat`, `Glute Bridge` or `Hip Circle Walk`). **Write the canonical catalog name and nothing else**: the bracketed tag in `exercises-database.md` (`[Band]`, `[DB]`, `[BW]`) is metadata, and `Hip Circle Walk [Band]` is rejected as off-catalog and blocks the render. The catalog is also the equipment list (`Band Pull-Apart` is deliberately absent). If a movement is not in `shared/exercises-database.md`, it is not prescribable.

**Ramp sets on the first heavy free-weight compound only.** When the first working exercise is a heavy barbell or dumbbell compound (squat, bench, deadlift, RDL, overhead or DB press), precede its working sets with 1-2 ramp sets marked `(warmup)` at about 50% then 70% of the working load, low reps (about 5 then 3): `Barbell Back Squat: 60kgx5 (warmup) /// 80kgx3 (warmup) /// 95kgx8 /// 95kgx8 /// 95kgx8`. The marker keeps them out of volume and e1RM. Skip ramps for a light cable, machine or isolation opener, and never ramp later compounds.

**Deload and re-entry.** One statement, no other rule contradicts it:
- **Cadence deload = ONE session: the first lower-body session of the week** (the first session when the split has no lower-body day). It applies when `block.deload_prescribed` is true (`block.weeks_since_deload` has reached `block.deload_cadence_weeks`, or there is no deload on record). In that session halve the working sets of every exercise except core, and write each load as `last_load_kg` (for a `hold` entry, its `load_kg`, which is already at or below it), never an `add_load` bump. Core keeps its full per-session dose in that session too (4 sets on a lower day). Every other session is normal. The floors stay blocking that week, scaled as under **Weekly volume**. Disclose it in the `> Why:` line ("Session 2 is a deload, 7 weeks since your last one"). If a deload is still owed later (`deload_cadence_due` true, `deload_prescribed` false), say so on the `block_position` card.
- **A full-block deload** (every session halved, loads held at `last_load_kg`, core dose kept) happens only when `load_policy.policy` is `reduce` (gate Tier A or B, or strength TSB of -15 or lower) or the user asks for one. Only then are the floors advisory.
- **Re-entry after a break.** If days since `monthly_sessions[-1].date` exceed 5 with no deload on record in the gap, the first session back drops one working set per compound and says "leave 2-3 reps in the tank" instead of 1-2 (§7: tendon adapts slower than muscle).
- `recovery.confidence` `low`: don't invent triggers from data the source doesn't provide.

**Structure rules.**
- **Straight sets only** (§16): finish every exercise before starting the next. Never pair, alternate or circuit, and never write a pairing note.
- **Exercise variation** (§17): the week's selection covers different regions of each major muscle, shoulders included (a vertical press plus lateral-delt isolation). Anchor compounds where progression is live carry forward; variation plays out in isolation and accessory slots and across blocks.
- **Volume, frequency, overload, push-pull balance, lengthened position, tendon safety, deload timing**: §1, §5, §6, §7, §8, §11. **Mesocycle** (§15): tell the user where they are in the block (the `block_position` card).
- **Stale exercise reintroduction.** Pick 1-2 from `stale_exercises` and restart them conservatively (§17). Each has a `next_dose` entry (re-entry `hold`, load already re-derived from its last best set, discounted past 56 days away, range derived from its last reps if none was on record): copy it. A lift last logged more than 120 days ago has no entry: cold start. The workout markdown may carry only a short cue such as `first time back; ease in`.
- **Cardio (§10) is never prescribed**, even when the person is behind the target.
- **Exercise ordering and equipment grouping:** compounds first, then isolation, then accessories, with core placed as below. Batch cable work, bench work and so on **only within the isolation/accessory block**; never reorder compounds or move an isolation ahead of a compound for equipment convenience. A core movement that shares equipment with that block goes inside its equipment group.

**Core and arm placement (enforced, blocking).** Core's countable part is `core_week_spec` (per-session dose, distinct exercises, categories, per-exercise frequency, one loaded flexion movement, the flexion floor); don't restate or second-guess it. Select per §24.3: one loaded flexion slot, one rotating non-flexion slot cycled by category across blocks. **Placement:** core goes inside the isolation/accessory block as straight sets, **never the final bullet and never before a compound**. The same blocks arms: **a biceps or triceps exercise as the last bullet is a blocking error.** Close the session on something that is neither core nor arms (rear delts, calves, a face pull). Not "a carry": `Suitcase Carry` is core (anti-lateral-flexion), so closing on it trips the core error. The only non-core carry is `Dumbbell Farmer Walk`, a finisher budgeted outside the core allocation that earns no core credit. Allocation order matters too: budget core and arms first, because the tail of a plan is where prescriptions go unperformed.

What the specs cannot decide, and you must: **which movement, given this person's log.** `adherence.never_performed` and `benched` outrank exercise-selection theory (a 0% completion prescription delivers 0 sets). Progression for core and arms is the same `next_dose` copy as any other lift.

**Bench prompt.** When `adherence.bench_prompt` is present, ask its `question` **once** in chat, then persist the answer before writing the plan:

```
python3 -m workout_coach.lib.adherence bench-record --person <Name> \
  --exercise "<Exercise>" --disposition retired|retry --answer "<their words>"
```

`retired` removes the movement from `next_dose` and from selection for good; `retry` clears the bench. Without the write, the same question returns every run. Ask nothing when the key is absent, and never about more than one exercise per run. `bench_prompt.kind` decides what you are asking:
- **`benched`**: prescribed into sessions the user trained and skipped, with other routes to that muscle available. The coach stops prescribing it. Ask **why** (equipment, dislike, time): `retired` if it is not coming back, `retry` if the answer names something fixable.
- **`route_blocked`**: same evidence, but benching it would strand a muscle at emphasis or grow tier or empty a core pattern category, so it sits in `adherence.bench_blocked` and stays prescribable. Ask **what instead**, naming the stranded pattern category precisely (not "the only route to core"). Persist `retired` with their words when they name a substitute, and prescribe the named swap in that slot this generation (from the next run the retired movement is benched; e.g. "swap to Plank": write `Plank` if it is in the catalog; if it is not, say so in chat and take the nearest catalog movement of the same pattern). Persist `retry` when the movement itself is fixable.

**Block rotation (advisory).** Exercise selection is stable inside a block and rotates at the boundary (`block.boundary_due`); loads and rep targets move week to week. Findings print as warnings and do not refuse a render. Read `block.slots[]` for what each position holds, `must_rotate` for slots the boundary has come due for, `anchor_overdue` for aged-out anchors. "Rotated" means:
- **A different movement pattern, not a different equipment word.** Cable Lateral Raise to Dumbbell Lateral Raise is the same `pattern`. Landing in a `pattern` the session did not have is what stops anti-rotation and carries sitting at zero forever.
- **Not a name the slot held recently** (`slots[].history`).
- **Anchors persist**, changing only for a reason in `block.anchor_change_reasons` (`stall_3_sessions`, `injury`, `age_3_blocks`).

Every slot must be a catalog name. When `block.boundary_due` is true this generation authors a NEW block, and it has to be persisted after the plan is written: `python3 -m workout_coach.lib.blocks write --person <Name> --from-plan <YYYY-MM-DD>`. Skip this when `boundary_due` is false. Inside a block, a split day that recurs (two Upper days) is two different session types, so keep one progressing anchor per muscle and let the second exposure lead with a different angle or pattern.

### Per-workout format in the file

A **lean exercise list**: no tables, no rationale paragraphs, no cardio. The "why" lives in `coach_reads.json`. The user trains from this file on a phone, so every line they don't need slows them down.

No em dashes in workout prose. The only allowed ones are the title separator and the indented `  — cue` marker. In `> Today's call:` / `> Why:` lines use a period, comma, semicolon or colon; a prose em dash fails the check.

Every strength workout heading is followed by `Date: ___\` then `Recovery: sauna ___ / cold ___ / rlt ___`, each on its own line, then a blank line, then the bullets. The trailing backslash is a Markdown hard break. The user fills the date in when they train and replaces only the recovery blanks they used (`/log` parses each modality independently).

**Exercise bullets**: one line per exercise, no code fences. **There is one set format and it is `///`: every set is its own entry, whatever the unit.** 4 sets = 4 entries.
- Weighted: `Dumbbell Flat Bench Press: 52kgx10 /// 52kgx10 /// 52kgx10`
- Ranges: `Cable Lat Pulldown: 65-70kgx8-10 /// 65-70kgx8-10 /// 65-70kgx8-10`
- Holds, in seconds or `MM:SS`: `Plank: 45s /// 45s /// 45s`
- Loaded carries, in metres, both sides: `Suitcase Carry: 24kgx30m /// 24kgx30m /// 24kgx30m`
- Bodyweight reps: `Hanging Knee Raise: 10-12 /// 10-12 /// 10-12`

Unilateral lifts: a trailing `per side` is allowed and optional (`14kgx10-12 per side /// 14kgx10-12 per side` is two sets; the validator ignores the words), and one entry is one set covering both sides.

**Never write `Plank: 45s hold` for a three-set plank.** That form is ONE set to the validator, so the prescription silently delivers a third of the dose. Seconds, `MM:SS` and metres count as set tokens, with a 10-second and 10-metre floor. Warm-up prep movements use the same format; ramp sets carry `(warmup)`. Names are canonical title case from `shared/exercises-database.md`.

**Per-set inline qualifiers (sparingly)**: a short parenthetical on a set that differs: an optional last set `... /// 30kgx10 (if you can make it)`, an aspirational top set `... /// 70kgx6 (ideal — leave 1 in tank)`, a descending set `40kgx8 (top set) /// 35kgx8`.

**Exercise-level sub-bullets (usually 0-2 per workout; a third means rationale is creeping in).** An indented sub-bullet starting with an em dash, lowercase, no period, one short clause, only for a form cue that matters today, a safety or injury flag, or a one-time deviation (`— first time back; ease in`, `— travel gym: scale 60 to 35kg`). Everything else belongs in `coach_reads.json`: comparative history ("last time you did 50kg x 8"), load rationale, restating the bullet, cross-references. `validate_workout_md` catches most of these. `— anchor change: injury` and `— other gym: X kg` do not count against the cap: they are required channels. A `hold` cue quoting the `basis` is a one-time deviation and counts.

Example (no code fence in the actual file):

```
## Workout 1: UPPER A + CORE
Date: ___\
Recovery: sauna ___ / cold ___ / rlt ___

- Jumping Jacks: 50
- Arm Circles: 20
- Dumbbell Flat Bench Press: 28kgx5 (warmup) /// 40kgx3 (warmup) /// 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10 /// 54kgx8-10
- Shoulder Press Machine: 45kgx8-10 /// 45kgx8-10 /// 45kgx8-10
  — leave 1-2 in tank
- Cable Lat Pulldown: 60kgx8-10 /// 60kgx8-10 /// 60kgx8-10
- Seated Row Machine: 50kgx10-12 /// 50kgx10-12 /// 50kgx10-12
- Incline Dumbbell Curl: 24kgx10-12 /// 24kgx10-12
- Cable Lateral Raise: 10kgx12-15 /// 10kgx12-15 /// 10kgx12-15
- Kneeling Cable Crunch: 20kgx12-15 /// 20kgx12-15
- Cable Overhead Tricep Extension: 35kgx10-12 /// 35kgx10-12
- Cable Face Pull: 20kgx12-15 /// 20kgx12-15
```

This is an Upper day that keeps the vertical press next to the horizontal push, and a vertical pull next to a horizontal pull. The two prep movements and two ramp sets don't count; the **working sets total 24** (4 + 3 + 3 + 3 + 2 + 3 + 2 + 2 + 2), which lands on a 24-set budget, and the example is written to be copied: one that models 18 sets teaches an 18-set session. An Upper day carries 2 core sets (a Lower day 4). Core and arms sit inside the isolation block as straight sets and the session closes on a face pull, which is neither. One session cannot show a week. Validated alone, this example returns week-level blocking errors (the flexion set floor, and the per-muscle floors once a payload is supplied): the weekly core distribution, the per-muscle floors and the arm exercise spread are satisfied across the plan's sessions, so don't copy this one session N times and expect it to pass.

### Where the rationale goes

The workout markdown carries no rationale beyond its short opener. The "why" lives on the card showing the data: the strength TSB band on `training_load`, the dominant driver on `recovery_drivers`, HR-at-volume on `muscle_volume`, the dose changes on `block_position`.

## Common Mistakes

Before finalizing, skim **`references/common-mistakes.md`**, the catalog of failure modes with the correct behavior for each. The load-bearing planning rules are enforced inline above and by the validators; the reference is the backstop.

## Rules

- Goals fixed. Never ask.
- No generic advice disconnected from their data.
- Don't soften findings.
- If data is too thin, say what you can and can't tell from it.
- One clarifying question max if the tracker is unreadable.
