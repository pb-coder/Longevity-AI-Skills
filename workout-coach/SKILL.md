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
3. Run `scripts/read_tracker.py "./Workout Tracker - <Person>.xlsx"` from the current working directory (where `<Person>` is the resolved name, e.g. `Nihad` or `Fabian`). The script returns one JSON blob with progression summary, deload dates, days since last session, cardio totals for the last 14 days, bodyweight series (`bodyweight_latest`, `bodyweight_trend_kg_per_week`, `bodyweight_recent`), Apple Health roll-ups, and a pre-computed muscle-volume model. If the tracker isn't there, the script prints an error — relay it in one line and stop. Don't search the filesystem.

   **Output is compact (no indentation) by default** — saves ~20% of tokens vs pretty-printed. Pass `--pretty` for human inspection.

   **`rows` (the flat per-set list) is off by default** — the script's pre-aggregated keys (`progression_summary`, `session_totals`, `weekly_volume_per_muscle`, `estimated_1rm`, `cardio_last_14d`) cover every coaching use. Pass `--include-rows` only when you genuinely need to dig into individual sets for debugging or unusual cross-sectional questions; expect the JSON to grow ~6x in size.

Each row = one set. Columns: `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR`. SESSION is a per-month number merged across rows of the same date; the sheet closes each strength session with a `TOTAL` row carrying the session's total volume (`read_tracker.py` exposes these as `session_totals`, so don't sum yourself).

4. From the script's output, identify the **most recent workout** (last date with logged sets). Note which muscle groups it trained and which exercises were performed. Use this as the planning baseline: do not repeat the same primary muscle emphasis in the very next session, and carry forward any exercises where progression was visible. The rest of each session's slots are where variation lives — see §17.

## Output target

All user-facing output — the report AND the plan — goes into `./workout_plan - <Person>.md` (e.g. `./workout_plan - Nihad.md`), overwriting whatever was there. The chat gets one short block: a one-line verdict plus `Wrote plan to workout_plan - <Person>.md (N sessions)`. Nothing else. Never write to a file without the `- <Person>` suffix, and never write across people.

The file structure:

```
# Workout plan — <YYYY-MM-DD>

## Report
### The verdict
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
- `data_source`: one of `xml` (Apple's zipped XML export) or `hl_export` (HLExport text). Determines which recovery / per-session-HR sections you can write at all. Don't override based on what fields are populated — read this string and trust it.
- `capabilities`: per-data-source feature map. Keys: `hrv`, `wrist_temp`, `resting_hr_daily`, `walking_hr`, `sleep_stages`, `sleep_breath_dist`, `exercise_min_daily`, `per_workout_hr`. **False means structurally unsupported**, not "not yet collected." Use this — not the presence of nulls — to decide whether a section should appear in the report at all.
- `auto_cardio_enabled`: bool. True = Apple-recorded runs / hikes / HIIT auto-flow into the monthly `YYYY.MM` sheets. Cosmetic for the coach; the volume model already counts the rows.
- `today`, `last_session_date`, `days_since_last_session`
- `rows`: every set from the last 3 months (default window; override with `--months N`). **Only present when `--include-rows` was passed** — otherwise the key is omitted to keep the payload small.
- `progression_summary`: last vs. previous best working set per exercise, case-insensitive, warmups excluded
- `deloads`: list of dates where the session's first row had Notes `Deload Workout`
- `weeks_since_last_deload`: float (null if no deload on record)
- `cardio_last_14d`: `{zone2_minutes, interval_sessions, total_distance_km}`
- `bodyweight_latest`: `{date, kg}` of the most recent weigh-in, or null
- `bodyweight_trend_kg_per_week`: slope over the last 8 clean (fasted) entries, or null if too few data points or span < 7 days
- `bodyweight_recent`: the last 12 entries, each `{date, kg, notes}` — notes usually empty; non-empty flags an exception to morning/empty-stomach (e.g. `"evening, not fasted"`). The trend function already excludes flagged rows.
- `session_totals`: `{YYYY-MM-DD: total_volume_kg}` — one entry per strength session, populated from the sheet's TOTAL rows. Use this for weekly/recent volume reporting instead of summing `rows` yourself.
- `weekly_volume_per_muscle`: `{window_days: 28, current: {muscle: sets}, landmarks: {muscle: {mv, mev, mav, mrv}}}`. Fractional hard-set count per muscle over the last 28 days, pre-computed via the `exercises-database.md` primary/synergist rules (compound = 1 set primary + 0.5 per synergist). Don't re-derive — read `current[muscle]`, compare to `landmarks[muscle]`, name the band (MEV/MAV/MRV) explicitly in the report.
- `estimated_1rm`: `{ExerciseName: {current_e1rm_kg, prev_e1rm_kg, best_e1rm_kg, last_date, delta_vs_prev_kg, e1rm_history, slope_kg_per_4w, confidence, stalled_sessions}}`. Epley projection (`kg × (1 + reps/30)`) on the heaviest working set per session, one entry per exercise with logged working weight. Emitted for every exercise, not only the five major compounds — the coach decides which to surface.
  - `e1rm_history`: last 3 sessions newest-first, each `{date, e1rm_kg, top_set_reps, top_set_kg}`. (The slope is still computed over 6 sessions internally — only the emitted list is capped.) Use it when raw delta_vs_prev_kg looks ambiguous and you need to see the trajectory. **Omitted entirely** when `confidence == "low"` AND `slope_kg_per_4w` is null — those entries are pure noise and the summary fields convey what's known.
  - `slope_kg_per_4w`: OLS slope over those sessions, scaled to a 4-week window. Null if fewer than 3 sessions logged. Treat this — not the last-vs-prev delta — as the primary "is this lift trending up?" signal.
  - `confidence`: `high` (last 3 top sets all 3-8 reps), `medium` (mixed), `low` (any top set ≥13 reps or only one session). Epley is calibrated for low-rep work; a high-rep e1RM is noisy. When `confidence == low`, soften the trend language and surface the noise to the user.
  - `stalled_sessions`: count of consecutive most-recent sessions where |Δe1RM| ≤ 0.5kg, broken by any deload that fell in the window. ≥2 means a real stall, not a one-off bad day.
- `stale_exercises`: list of exercises not logged in ≥28 days, sorted newest-stale first. Each entry: `{exercise, last_date, weeks_since, sessions_logged}`. Warmup and cardio sections are pre-filtered. Use for rotation decisions (retire, reintroduce, or fold back into the plan).
- `unknown_exercises`: logged exercise names across the full loaded window that don't match the database. Surface these in **Missing from your tracking** so the user can fix typos or add missing entries — untracked names silently under-count volume.
- `health_metrics_recent`: last 30 daily rows from the `Health Metrics` sheet (Apple Health import). Each row carries `vo2max`, `resting_hr`, `hrv_sdnn`, `walking_hr`, `hr_recovery_1min`, `sleep_total_h`, `sleep_deep_h`, `sleep_rem_h`, `resp_rate`, `wrist_temp_c`, `sleep_breath_dist`, `exercise_min`. Any field can be null on any given date — sparse-merge upserts protect existing values. (Bodyweight is intentionally NOT in this list — read `bodyweight_recent` / `bodyweight_latest` instead.)
- `vo2max_latest`: `{date, value}` of the most recent VO2max reading, or null. Use directly in the Cardio check line.
- `vo2max_trend_per_4w`: OLS slope per 4 weeks across all logged VO2max readings. Null until ≥4 readings spanning 21+ days.
- `resting_hr_recent_avg`: 7-day mean. Lower is better.
- `resting_hr_trend_per_4w`: 4-week slope. **Negative** = improving (resting HR dropping = better cardio fitness). Null below the data threshold.
- `hrv_recent_avg`: 7-day mean SDNN.
- `hrv_trend_per_4w`: 4-week slope. **Positive** = improving.
- `hrv_baseline_60d`: 60-day mean. Use to decide if recent HRV is anomalously low (`hrv_recent_avg ≤ 0.9 × baseline` is the §18 threshold).
- `sleep_avg_last_7d`, `sleep_avg_last_28d`: total hours asleep per night, averaged. The 28-day window is the "normal for you" reference; the 7-day window is what's happening now.
- `wrist_temp_baseline_60d`, `wrist_temp_recent_avg`: 60-day baseline and 3-day recent mean of Apple's nightly wrist temperature reading. Recent > baseline + 0.3°C for 2+ days = illness/overreach signal (§18).
- `hr_recovery_recent_avg`: mean of the last 5 logged HR Recovery 1-min readings (count/min drop in HR one minute after exercise). Higher is better.
- `workout_sessions_last_28d`: list of Apple `Workout` rows (last 28 days, incidental walks excluded). Each entry: `{date, type, duration, avg_hr, max_hr, cal}`. Match by date to logged training to surface session-level HR for strength sessions.
- `strength_session_avg_hr_trend`: 4-week slope of avg HR across the last 8 strength sessions (Apple workouts on dates that were logged with weight × reps). Positive = HR is creeping up at the same load → fatigue accumulating, hold load.

Apply the standard filters on top of the pre-aggregated keys (no need to read `rows` for these):
- Volume analysis (report): use `weekly_volume_per_muscle.current[muscle]` directly and name the landmark band (e.g. "chest: 12 sets, MAV"). The fractional model is already baked in.
- Session-level volume: `session_totals`.
- Progression trends (report): use `progression_summary` directly for major compounds (bench, squat, deadlift, OHP, row).
- Deeper progression: `estimated_1rm[exercise]` carries the trajectory plus a 3-session history.
- Workout planning: rely on the 28-day windows already computed (`weekly_volume_per_muscle`, `workout_sessions_last_28d`).
- Most recent session: `last_session_date` plus the matching `progression_summary` entries.

If you genuinely need raw set-level data (e.g. an unusual cross-sectional question), re-run with `--include-rows`. Default runs omit `rows` to save tokens.

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
2-3 sentences. What's the state of their training right now? Honest. Include `days_since_last_session` in context — "last trained 2 days ago, normal cadence" or "9 days since last session, longer break than usual".

### What's working
Bullet points. Plain language. What they're doing well with specific exercises and numbers. 3-5 items max.

### What needs fixing
Bullet points. Prioritized by impact. Each item: what's wrong, why it matters for them, what to do. 3-5 items max. No technical justification beyond one sentence.

### Are you getting stronger?
For each major exercise with enough data, combine the raw top-set line with the e1RM trajectory:

`Exercise Name: Xkg × Y reps → Xkg × Y reps, e1RM Akg → Bkg (+Ckg / 4 weeks) — getting stronger / stuck / going backwards`

Pull the values from `estimated_1rm[exercise]`:
- `prev_e1rm_kg → current_e1rm_kg` for the immediate delta.
- `slope_kg_per_4w` for the trajectory line (`+Ckg / 4 weeks`). Use this as the primary signal — it sees through one-off noise that a last-vs-prev delta can't. If it's null (fewer than 3 sessions), drop the trend chunk and rely on the raw delta only.
- `confidence`: when `low` (high-rep top sets), append a clause like "e1RM is noisy at 12+ reps — push one heavier set to get a cleaner read." Don't claim a trend with confidence on a noisy signal.
- `stalled_sessions ≥ 2` without a deload in the window: call out the stall explicitly. Suggest one of: bump volume, change variation, or schedule a deload (let Phase 2 decide which).

A negative `delta_vs_prev_kg` and a flat-or-negative `slope_kg_per_4w` together on a main lift without a deload around it is a real flag. A negative delta with a positive slope is one bad session — don't over-react.

**Optional session-HR line.** Skip entirely when `capabilities.per_workout_hr` is False — HL users don't get per-workout HR, so the line would always be empty. When the capability is present and `workout_sessions_last_28d` has Apple workouts matching a major lift's recent dates, you can append a session HR comment — but only when it adds signal. Look up §19 for the bands. Examples:

- HR sits in the normal hypertrophy band (130-150 bpm avg) → don't write the line. It's not informative.
- HR is creeping above 150 bpm avg on the same load → write `Session avg HR 152 bpm (last 4 sessions) — running hot, hold load this block.`
- HR is below 110 bpm avg on a working set → write `Session avg HR 105 bpm — effort too light, push reps before adding load.`

Skip the line entirely when there's no Apple HR data for the strength-session dates. Don't fabricate a band.

If data is too limited to judge (history < 2 entries), say that in one sentence.

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
One line. Compute from `weeks_since_last_deload`:
- < 4 weeks: "On track — last deload was N weeks ago."
- 4-6 weeks: "Deload window open — consider one in the next 1-2 weeks."
- > 6 weeks: "Deload overdue — prescribing one this block."
- null (no deloads on record): "No deload on record in the last 3 months — prescribing one."

### Recovery state
**Hard gate first.** If `capabilities.hrv` is False AND `capabilities.wrist_temp` is False, skip the entire subsection — don't write the heading. The data source can't answer "how recovered are you" the way XML can; pretending it can is misleading. (HL users: this is the expected path.)

If at least one of those is True, insert this subsection only when any recovery signal is populated. Skip it (don't write the heading) when the user hasn't run an Apple Health import yet — `hrv_recent_avg`, `resting_hr_recent_avg`, `sleep_avg_last_7d` will all be null in that case.

Standard format when data is present:

```
HRV 62ms (7d avg), trend +3.1ms / 4 weeks — improving.
RHR 58 bpm, -2 / 4 weeks — improving.
Sleep 7h12m / night (7d avg), 7h05m (28d).
Wrist temp baseline-normal.
```

Per-line rules:
- Trend line: skip the trend chunk and just print the average if the trend value is null (data threshold not met yet).
- Wrist temp: print "baseline-normal" if `wrist_temp_recent_avg ≤ wrist_temp_baseline_60d + 0.3`. Print "↑ 0.4°C above 60-day baseline" if above the threshold.
- HRV anomaly: if `hrv_recent_avg ≤ 0.9 × hrv_baseline_60d` for 3+ consecutive days (check `health_metrics_recent`), or wrist temp is above threshold for 2+ days, **lead with that** at the top of the section instead of the standard format. Example:

```
Wrist temp +0.4°C above 60-day baseline AND HRV down 12% for 3 days — possible illness or overreach. Pulling intensity this week, pushing the heavy lower day back.
```

The reasoning surfaces here so the user knows why the plan is conservative. Phase 2 then reduces volume per the recovery-aware rule below.

### Cardio check
Compare `cardio_last_14d` against §10 targets (150 min Zone 2 + ~20 min intervals per week, so roughly 300 min Zone 2 + 2 interval sessions over 14 days). Flag shortfall in plain numbers: "Zone 2: 60 min logged, target ~300 min. Intervals: 0 sessions, target 2."

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
- **Deload handling (§11):** if `weeks_since_last_deload > 6` or null, the prescribed block IS a deload: reduce each exercise's working-set count to ~50% and keep loads at the last working weight (maintain intensity, cut volume). Tell the user explicitly in "Why this plan" that this block is a deload. In the 4-6 week window, don't force a deload but flag it in the report and offer to plan one if the user asks.
- **Re-entry after long break:** if `days_since_last_session > 5` and no deload on record in that gap, treat the first prescribed session as a re-entry — drop one working set per compound, prescribe "leave 2-3 reps in the tank" instead of 1-2. Tendon adapts slower than muscle (§7), so under-load the first session back.
- **Recovery-aware adjustments (§18):** **Gate first** — if `capabilities.hrv` and `capabilities.wrist_temp` are both False, this rule does not apply. Don't invent triggers from data the source doesn't provide; the user gets normal programming with the standard re-entry / deload heuristics from `weeks_since_last_deload` and `days_since_last_session`. When at least one is True, read `hrv_recent_avg` vs. `hrv_baseline_60d`, and `wrist_temp_recent_avg` vs. `wrist_temp_baseline_60d`, plus the per-day `health_metrics_recent` series for anomaly persistence. Triggers:
  - `hrv_recent_avg ≤ 0.9 × hrv_baseline_60d` for 3+ consecutive days → next session is re-entry: drop one working set per compound, prescribe "leave 3-4 reps in the tank" instead of 1-2.
  - `wrist_temp_recent_avg > wrist_temp_baseline_60d + 0.3°C` for 2+ consecutive days → same re-entry treatment (illness/overreach signal).
  - Either persisting 7+ days → flag deload as urgent regardless of `weeks_since_last_deload`. Override the standard 4-6 / 6+ week thresholds.
  - Surface the reason in "Why this plan" so the user understands the call.
- **Session-HR cross-check on load progression (§19):** Skip entirely when `capabilities.per_workout_hr` is False — HL users have no per-session HR to read. Otherwise, when load-progressing a compound (e.g., bumping squat from 75 → 80kg), peek at the most recent matched Apple session's avg HR for that movement's date. If `strength_session_avg_hr_trend > 0` AND the recent avg HR is already above 150 bpm, skip the load bump this block — the user is grinding the existing load. Surface in the table's Notes column: `Holding load — session HR ramping up.`
- **Cardio (§10):** read the Cardio check numbers from the Report. If behind target, add cardio sessions to the plan after the strength sessions. Default weekly target: 3× Zone 2 @ 30-45min + 1× intervals @ 20min. Cap total cardio additions at 4 sessions per `/coach` run — if the user is very behind, note the shortfall and prescribe the max. User can override with `/coach no-cardio` to skip this entirely.

**Core training:** Build strong, developed abs. Program 1-2 core exercises per session, aim for 3-4 sessions/week with core. Prefer weighted core (kneeling cable crunch, cable woodchop, captain's chair knee raise) alongside bodyweight (leg raises, dead bugs, hollow body holds). Vary patterns across sessions: flexion, anti-extension, rotation, isometric. Visibility is a body fat question, not a training question.

**Cable weight granularity:** Cable machines increment in 5kg steps: 5, 10, 15, 20, 25. Never suggest intermediate weights. Always round to the nearest available plate.

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
One short paragraph at the end of the file — 3-4 sentences. What the overall block prioritizes and why these sessions are structured this way. If the block is a deload, say so explicitly.

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
| Ignoring the deload window | 7+ weeks of continuous blocks because no one flagged it | `weeks_since_last_deload` drives it. >6 weeks → block IS a deload. 4-6 weeks → flag in report. |
| Prescribing normal volume after a long break | User took 10 days off, coach plans a full 4-set compound session | `days_since_last_session > 5` and no deload → re-entry session with reduced sets and more RIR on the first day back (§7). |
| Re-reading the xlsx inline | Re-deriving row parsing, empty-row stop, date quirks every run | Call `scripts/read_tracker.py` once. Only touch the xlsx directly if debugging something the script can't see. |
| Hardcoding "no cardio" in the plan | Strength-only plan even when user is 150+ min behind §10 target | Cardio-in-plan is the default. Read `cardio_last_14d` from the report and append cardio sessions when behind target (cap 4/run). Honor `/coach no-cardio` if passed. |
| Static plan with no mesocycle context | Weights and reps with no indication of block position | Tell the user where they are in the mesocycle and what this week targets (§15). |
| Missing data from casing mismatch | Searching for "Leg Extension" misses rows logged as "Leg extension" | Compare case-insensitively. |
| Reading empty template rows | Dumping 900+ rows per sheet into context | Stop after 10 consecutive fully empty rows. |
| Breaking on None date | `if row[0] is None: break` stops at the first continuation row | Carry forward the last known date defensively. Only skip when BOTH date and exercise are None. |
| Writing the report or plan inline in chat | Conversation gets flooded; plan is hard to find later | All report + plan content goes into `./workout_plan - <Person>.md`. Chat gets one verdict line + the file pointer. |
| Writing one person's plan over the other | `workout_plan - Nihad.md` overwritten with Fabian's plan, or vice versa | Always resolve the person first and write to `./workout_plan - <Person>.md`. Never a bare `workout_plan.md`. |
| Partial file writes | Streaming sections and forgetting to complete | Build the whole file in memory, then write once. |
| Inventing recovery trends on <4 readings | "HRV improving" called from 2 data points | The `_trend_per_4w` keys are null until ≥4 entries spanning 21+ days. Drop the trend chunk; print the average alone. |
| Reading single-day HRV as signal | One bad night triggers a deload | Compare `hrv_recent_avg` (7d) to `hrv_baseline_60d` AND require 3+ consecutive days below threshold via `health_metrics_recent` before reacting. |
| Treating Apple `Walking` workouts as training | Counts a 5-min stroll as a session | The importer flags walks under 15 min as `incidental walk` in Notes. `workout_sessions_last_28d` already filters them; don't re-add them when reading the sheet directly. |
| Bumping load when session HR is creeping up | User over-reaches | Hold load when `strength_session_avg_hr_trend > 0` and recent avg HR sits above 150 bpm. Note "Holding load — session HR ramping up." |
| Treating an HL user's missing HRV as "not enough data yet" | Implies the user just needs to log more, but the source can't provide HRV at all | Read `capabilities.hrv`. If False, omit the metric (and its sections) entirely. Distinct from "trend is null because <4 readings collected so far". |
| Listing structurally-unsupported metrics in **Missing from your tracking** | User sees a fake to-do list of things to "track" that the data source can't supply | The section is for *fixable* gaps (typos in `unknown_exercises`, dropped exercises, manual notes). Anything False in `capabilities` belongs in source docs, not the user-facing report. |
| Treating auto-cardio rows as duplicates of manually-logged runs | Both /log and the importer write the same run; coach can't tell them apart | Auto-cardio dedupe runs in the importer by (date, exercise, duration ±1 min). Manual entries always win. If you see two rows for the same run on the same date, flag it — the dedupe missed something. |

## Rules

- Goals fixed. Never ask.
- No generic advice disconnected from their data.
- Don't soften findings.
- If data is too thin, say what you can and can't tell from it.
- One clarifying question max if the tracker is unreadable.
