# Workout Tracker

Hypertrophy + longevity training logs for Nihad (account owner) and his boyfriend Fabian (28), who share the same goals and conventions. Used with a set of Claude skills.

## Files

Two parallel trackers live in per-person folders inside this directory:

```
<root>/
├── Nihad/
│   └── data/
│       ├── health_metrics.csv           # per-day Apple Health aggregates
│       ├── workout_sessions.csv         # one row per Apple Workout
│       ├── profile.csv                  # source / auto_cardio / birthday / swim CSS
│       ├── monthly/                     # one CSV per YYYY.MM workout month
│       │   ├── 2026.05.csv              # 17-col schema, ASC by (Date,#,Set)
│       │   └── …                        # canonicalize rebuilds TOTAL rows + computed cells
│       ├── swimming/                    # XML-only; absent on HL trackers
│       │   ├── YYYY.MM.workouts.csv     # per-swim aggregates (per month)
│       │   └── YYYY.MM.laps.csv         # per-lap detail (per month)
│       ├── sleep/                       # XML-only; absent on HL trackers
│       │   └── YYYY.MM.nights.csv       # per-night architecture (per month)
│       └── thermal/                     # manual /log only; absent until first session
│           └── YYYY.MM.sessions.csv     # per-session sauna + cold exposure (per month)
├── Fabian/                              # same shape (no swimming/ / sleep/ for HL; thermal/ on either after first log)
└── Skills/
```

There is no xlsx anywhere post-PR3a. Per-month workout data lives in
`<Person>/data/monthly/YYYY.MM.csv` — 17-column schema (`SESSION | Date
| # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) |
Duration (min) | Pace (min/km) | Avg HR | Active Cal | Total Cal |
Elevation (m) | Elapsed`), plus a TOTAL row per strength session.
The old `Laps` column was retired in 2026-05; swim lap counts now live
exclusively in `<Person>/data/swimming/YYYY.MM.workouts.csv`. Computed cells (Volume, Pace, Total
Cal, SESSION) are pre-evaluated on every canonicalize pass so the
user can preview the CSV in macOS Quick Look or Numbers without
needing Excel formulas. Health Metrics, Workout Sessions, and Profile
moved out of xlsx in PR1 (dense, machine-only); the monthly sheets
followed in PR3a. The Exercises Database lives only in
`Skills/shared/exercises-database.md` (no xlsx mirror —
`sync_db_sheet.py` was retired in PR1). The catalog includes WARMUP,
all strength sections, CARDIO (Hike, Swim, Walk, Outdoor Run, Outdoor
Cycling, HIIT + indoor machines), and WELLNESS (Yoga, Stretching), so
non-strength activities log without "(not in database)" warnings.

`health_metrics.csv` and `workout_sessions.csv` are populated by one of two importers, dispatched by file extension. **Apple's native zipped XML export** (`Export.zip` / `Export - <Person>.zip`, dropped in the workout-tracker root) flows through `Skills/shared/import_apple_health.py`, which streams the XML and writes per-day aggregates (VO2max, RHR, HRV, sleep stages, Time in Bed, wrist temp, exercise minutes, BodyMass) and per-workout rows with avg/max/min HR. The Apple importer also writes a per-night sleep architecture row to `sleep/YYYY.MM.nights.csv` (see Sleep section below). **HLExport text dumps** (`health_export_<timestamp>.txt`, from the HLExport iOS app) flow through `Skills/shared/import_hl_export.py`, which line-parses the same fields HL provides — VO2max, HR Recovery, total sleep (stitched from `Sleep: Asleep` / `Awake` events), respiratory rate, bodyweight, workout duration / calories / distance. HL has no HRV, no wrist temp, no per-workout HR, no per-stage sleep architecture, no Time in Bed by design. Both importers are idempotent; sparse-merge protects existing values, so switching a tracker between sources is non-destructive. **Both archive the source export to `<root>/.processed/` on success** — the CSVs are the persistent record now; the archive keeps a forensic trail if a downstream bug damages the CSVs.

### Per-person source profile

Each person's `data/profile.csv` is a 2-column key/value file pinning these settings:

| Key | Meaning | Default |
|---|---|---|
| `source` | `xml` (Apple zipped XML) or `hl_export` (HLExport text) | inferred from the first import's file extension |
| `auto_cardio` | If true, Apple-recorded cardio workouts (Run / Hike / Cycle / Swim / HIIT) auto-flow into the matching `monthly/YYYY.MM.csv` | `true` for XML, `false` for HL |
| `birthday` | YYYY-MM-DD of birth. Used by `/coach` to compute age dynamically for the max-HR fallback formula (Tanaka 208 − 0.7×age) when Apple per-workout HR isn't observable | unset → coach uses age 30 fallback |
| `swim_css_sec_per_100m` | Critical Swim Speed pace (sec/100m). Set via `/log` `CSS test` workflow; `/coach` uses it to classify each swim into Recovery / Aerobic / Threshold / VO2 zones | unset → coach skips zone classification |
| `swim_css_set_at` | YYYY-MM-DD when CSS was last measured. Coach prompts a retest after 8 weeks | unset |
| `swim_pool_length_default` | Fallback pool length (metres) for the rare workout where Apple omits `HKLapLength` | unset (importer only writes `Pool Length` when Apple provides it) |

`/coach` reads `profile.csv`'s `source` to decide which sections of its report to write — HRV / wrist temp / per-workout-HR / sleep-architecture sections are gated on the matching capability flags (`hrv`, `wrist_temp`, `per_workout_hr_strength`, `sleep_nights`, etc.). For HL users, the coach skips those sections entirely rather than printing "not enough data yet." The profile is bootstrapped on first import; manual override is supported by editing `<Person>/data/profile.csv` directly.

### Swim metrics

Swim workouts get richer treatment than other cardio because Apple emits per-lap data (`HKWorkoutEventTypeLap` events) that's actionable for SWOLF / SPL / pace trends. The XML importer writes two extra CSVs per month in `<Person>/data/swimming/`:

- **`YYYY.MM.workouts.csv`** — one row per swim. Aggregates: Pool Length, Strokes, SPL (`Strokes / Laps`), Avg SWOLF (mean of per-lap SWOLF), Stroke Mix (compact `"Free 21 / Fly 1"` summary), Location (Pool / Outdoor Pool / Open Water), Water Temp, Avg HR, Active Cal, Notes. Sources: `HKLapLength` metadata, `HKQuantityTypeIdentifierSwimmingStrokeCount.sum`, per-lap SWOLF averaging, `HKQuantityTypeIdentifierWaterTemperature.average`, derived from the `HKIndoorWorkout` + `HKSwimmingLocationType` flags. Dedupe by `(date, start)`. DESC by date+start.
- **`YYYY.MM.laps.csv`** — one row per lap event. Per-lap fields: Stroke (raw enum) + Stroke (decoded via `apple_workout_types.HK_SWIMMING_STROKE_STYLE`), Duration (sec), SWOLF, Source. Dedupe by `(date, workout_start, lap_num)`; replace-on-match (no sparse-merge — re-exports authoritatively replace stored lap data). ASC by (date, lap_num).

HL .txt exports don't carry lap-event data, so HL trackers never have a `swimming/` folder — the coach skips the swim section automatically. The Apple Health zipped-XML importer is the only writer; `/log` cannot append per-lap detail manually.

**CSS test workflow.** When the user logs a 400m + 200m time-trial pair on the same day with `CSS test` on the header line, `/log`'s parser includes a `css_test` field in the payload. `append_workout.py` computes `(t400_sec - t200_sec) / 2` and writes `swim_css_sec_per_100m` + `swim_css_set_at` to `profile.csv`. CSS detection is never automatic — only the explicit `CSS test` keyword triggers the write.

### Sleep architecture

Sleep gets a dedicated per-month store at `<Person>/data/sleep/YYYY.MM.nights.csv` (one CSV per month, parallel to `monthly/` and `swimming/`). The Apple XML importer writes every stage Apple emits (`HKCategoryValueSleepAnalysisAsleepCore` / `AsleepDeep` / `AsleepREM` / `AsleepUnspecified` / `Awake` / `InBed`); `/log` accepts an opt-in manual sleep payload (see below) that dual-writes to the same store. XML-only — HLExport doesn't supply per-stage data, so `Fabian/data/sleep/` never exists unless he manually logs sleep.

Per-night schema (`Date` is dedupe key, sparse-merge with manual-wins on Notes):

- **Stages (hours):** `Sleep Total` (sum of all `Asleep*` stages), `Sleep Core`, `Sleep Deep`, `Sleep REM`, `Sleep Unspecified`, `Sleep Awake` (WASO — wake-after-sleep-onset).
- **Time in Bed (h):** total span of `HKCategoryValueSleepAnalysisInBed` segments. Source of the clinical sleep-efficiency denominator. The Apple Watch does NOT emit InBed records — only the legacy iPhone Sleep Schedule did, so this column is typically blank on Watch-only data. Users can fill it by re-enabling iOS Sleep Schedule or by typing `inbed X.X` in a `/log` message.
- **Sleep Efficiency (%):** derived from `Sleep Total / Time in Bed × 100`, written on import for cheap reads. Auto-computed inside `csv_store.upsert_sleep_nights` when both inputs are present and no explicit override was supplied.
- **N Segments:** fragmentation proxy. Count of `Asleep*` + `Awake` segments contributing to the night. Manual `/log` entries leave this blank (only the importer has segment metadata).
- **First / Last Segment Start:** earliest sleep-onset and latest wake-up clock times across all `Asleep*` segments for the night. Bedtime / waketime schedule signal — `/coach`'s `sleep_summary` derives circular stdevs over a 28-day window (so a 23:50 / 00:10 bedtime pair correctly reports a 20-min stdev, not 23h).

**Recovery-night bucketing.** Apple emits sleep segments tagged by `startDate` / `endDate`. The importer buckets each segment to its *recovery night* (the morning the user wakes up): if `endDate.hour < 18`, bucket to `endDate.date()`; if `endDate.hour ≥ 18`, bucket to `endDate.date() + 1`. Without the evening shift, a sleep period that starts 23:00 and ends 23:42 on the same calendar day would land on that day's row alongside the morning's actual sleep — combining two unrelated windows. Apple's own daily summary uses this same convention. **Side-effect on `health_metrics.csv`:** `sleep_total_h` / `sleep_deep_h` / `sleep_rem_h` values now also use this bucketing; pre-existing rows shifted slightly (usually <0.7h) on the first re-import that picked up the new logic. This is a correctness fix, not data damage.

**Manual sleep via `/log` (opt-in).** The user types `sleep 7h25`, `sleep total 7.5 deep 1.2 rem 1.3`, `inbed 8.4`, or `efficiency 91` (manual override) on a header line. Parsing rules in `Skills/workout-logger/references/parsing-rules.md`. `append_workout.py` dual-writes: rich detail into `sleep/YYYY.MM.nights.csv` via `upsert_sleep_nights` (sparse-merge), headline fields (`Sleep Total` / `Sleep Deep` / `Sleep REM` / `Time in Bed`) mirrored into `health_metrics.csv` so `recovery_score` picks them up without a join. Sparse-merge throughout — partial input is fine.

**Segment-level detail is intentionally NOT stored.** The per-night summary captures every actionable signal (stage durations + Efficiency + N Segments for fragmentation + First/Last clock times for schedule). Raw segments would be 7-11k rows/year with no current consumer. If a future need arises (hypnograms, sleep-latency derivation), re-extract from the archived Apple XML at `<root>/.processed/Export*.zip`.

**Coach exposure.** `read_tracker.py` emits a `sleep_summary` block (gated on per-night data existing in the 28-day window) with stage means, efficiency mean + per-week trend, fragmentation, schedule consistency (circular stdev of bedtime / waketime), and last-14-day outliers (efficiency <80% or WASO ≥1h). `capabilities.sleep_nights` flags whether the dedicated store is available — False for HL trackers. `recovery_score` weights are unchanged for now; the plan-of-record is to watch 4-6 weeks of `sleep_summary` data before deciding whether Sleep Efficiency / Core / WASO earns its own driver. `health_metrics_weekly` now includes `time_in_bed_h` so the recovery layer can read it without a folder join.

### Sauna + cold exposure

Heat and cold exposure get their own per-month store at `<Person>/data/sleep/`'s sibling `<Person>/data/thermal/YYYY.MM.sessions.csv`. **Manual `/log` only** — Apple Health doesn't classify sauna sessions reliably, so there's no importer-side write path; the `thermal/` folder is absent until the user logs their first session. One row captures one heat-and/or-cold protocol session (heat-only, cold-only, or paired heat → cold).

Per-session schema (`(Date, Start)` is dedupe key, sparse-merge with manual-wins on Notes):

- **Heat:** `Heat Type` (`dry` / `steam` / `infrared` / `banya` / `none`), `Heat Temp (°C)`, `Heat Rounds`, `Heat Round Durations (min)` (comma-separated per-round minutes for multi-round saunas, e.g. `"12,8"`), `Heat Total (min)` (auto-derived sum).
- **Cold:** `Cold Type` (`none` / `cold_air` / `cold_shower` / `cold_plunge` / `cold_water`), `Cold Duration (sec)`, `Cold Temp (°C)`.
- `Start` (HH:MM) and `Notes` are optional.

**Multi-round saunas** ("2 saunas after each other") live on ONE row with the per-round minutes in `Heat Round Durations`. `Heat Total` is the sum, written on every upsert; the invariant `Heat Total = sum(Heat Round Durations)` always holds on write. This avoids a separate per-round table (over-engineering for 1-3 rounds).

**Manual via `/log` (opt-in).** The user types `sauna 12+8min 85C dry` and/or `cold 5min air` lines on a workout header. Parsing rules in `Skills/workout-logger/references/parsing-rules.md` (`## Sauna + cold exposure (opt-in)`). A `sauna` + `cold` pair under the same workout header in one `/log` message becomes ONE row (paired protocol session); standalone cold (morning cold shower without sauna) is a row with heat columns blank. `append_workout.py` writes the entry to the matching `thermal/YYYY.MM.sessions.csv` via sparse-merge. **No mirror to `health_metrics.csv`** — heat / cold is per-event, not a daily-snapshot metric.

**Coach exposure.** `read_tracker.py` emits a `thermal_summary` block (gated on per-session data existing in the 28-day window) with separate `heat` and `cold` sub-blocks plus an `adherence` sub-block. The heat block reports frequency (sessions/wk, vs target), dose (total minutes/wk, and "minutes ≥80°C ≥20min/wk" — the Laukkanen + mechanistic HSP-induction band), type distribution, and multi-round-sessions percentage. The cold block reports frequency, dominant type, and how often cold was paired with a heat session in the same row. The adherence sub-block returns categorical status — `below-target` / `on-target` / `above-target` for frequency, and `below-HSP-threshold` / `in-band` / `above-band` for duration. **Frequency target** defaults to 4×/wk (mid-band of `interventions.md`'s 4-6 range, also the Laukkanen KIHD mid-band); user can override via `profile.csv` `sauna_target_per_week`. The `### Heat / Cold exposure` report section is REQUIRED when `thermal_summary` is present and silent otherwise. **`/longevity` reads `thermal_summary` instead of trusting the verbal-claim adherence on `interventions.md`** — the Sauna row in `interventions.md` should reference live data, not a claimed protocol.

### Auto-cardio (Apple → monthly CSV)

When `Profile.auto_cardio` is true, every Apple-recorded workout in `CARDIO_AUTOLOG_TYPES` (Running, Hiking, Cycling, Swimming, HighIntensityIntervalTraining) gets appended to the matching `monthly/YYYY.MM.csv` as a cardio row tagged `auto-imported from Apple`. Walks and indoor strength sessions are excluded — incidental walks would dominate, and Apple doesn't capture sets for strength. **Manual entries always win**: a cardio row with the same `(date, exercise, duration ±1 min)` as an existing manual row is never duplicated, and a previously auto-imported row is a no-op on re-runs (idempotent).

**Current-month gate.** The importers only ever write into the current calendar month's CSV. Past months are "finished" and never re-scanned, so a cardio row the user deletes from `2026.02.csv` stays deleted on the next import — no separate tombstone bookkeeping needed. The strength-session metadata writer follows the same rule: workouts dated outside the current month are silently skipped. (This replaced a previous `Tombstones` sheet + `auto_cardio_since` profile cell in 2026-05; both are now gone.)

Per-person sidecars:

- `<Person>/workout_plan - <Person>.md` (written by `/coach` — actually drops at the workout-tracker root for now; coach naming TBD)

## Routing (who is a message about?)

Every skill invocation must resolve a person before touching a file:

- If the user names a person ("log Fabian's push day", "coach Nihad"), use that tracker.
- If the user uses pronouns or context that clearly refer to one person ("my bf" / "boyfriend" → Fabian; "I" / "me" / "my" with no other person mentioned → Nihad, since Nihad is the account owner), use that tracker.
- Otherwise ask: **"Is this for Nihad or Fabian?"** before running.

Never mix data across trackers in a single skill run.

## Monthly CSV format

Columns (17, in order): `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR | Active Cal | Total Cal | Elevation (m) | Elapsed`. ASC by (Date, #, Set), TOTAL rows interleaved at strength-session boundaries. (The old `Laps` column was retired in 2026-05; out-of-date 18-col rows self-truncate on the next `canonicalize_monthly_csv` pass because `_row_to_dict` only iterates the 17 canonical fields.)

Each set is one row. Date, #, and Exercise are populated on every row (no carry-forward shorthand). `#` restarts at 1 per date and is shared by all sets of the same exercise. Cardio rows use the cardio columns (Distance through Elapsed); strength rows leave them blank.

`SESSION` is a per-month session number (1, 2, 3…) repeated on every row of the same date — including that session's trailing TOTAL row. It's populated by `canonicalize_monthly_csv`, not by hand.

**TOTAL row carries the strength session's full session-level summary.** Each strength session ends with a `TOTAL` row that holds:
- `Date` (col 2) — the session date.
- `Volume` (col 8) — `sum(reps × kg)` over the set rows, written as a literal number (was a formula in the xlsx era).
- `Notes` (col 9) — `Deload Workout` marker when applicable. Hoisted there by canonicalize from any data row that had the marker (legacy /log convention put it on the warmup row).
- `Duration (min)` (col 11) — strength block's total active minutes (MM:SS).
- `Avg HR` (col 13) — duration-weighted across the strength workout cluster.
- `Active Cal` / `Total Cal` (cols 14–15) — sum across the strength cluster.
- `Elevation (m)` (col 16) — usually blank for indoor strength.
- `Elapsed` (col 17) — wall-clock time (H:MM:SS or MM:SS).

The session's data rows (warmup + working sets) hold per-set data only; their cols 11/13/14-17 are blank. Cardio-only days have no TOTAL row — each cardio row carries its own per-row metadata directly. Apple-Watch session metadata is written to the TOTAL row by `monthly_csv.upsert_monthly_strength_session` (XML, full payload; HL fills only Active Cal + Duration). Manual `/log` doesn't write the metadata fields — the importers fill them post-hoc on the matching session.

Every set row's Volume cell is `reps × kg` written as a literal number, recomputed on every canonicalize pass — don't hand-edit Volume; edit reps or kg and let canonicalize redo the math.

## Skills

Skill source lives in [pb-coder/Longevity-AI-Skills](https://github.com/pb-coder/Longevity-AI-Skills), cloned locally at `Skills/`. Edit the unzipped source there and commit changes. See `Skills/CLAUDE.md` for the repo layout.

- `/coach` — reads the per-person CSVs, reports on training state, and generates new workout plans (`Skills/workout-coach/`). Each strength workout in the output has a `**Date:** ___________` placeholder under its heading; fill it in when you train so the date is visible when you later `/log` the session. The script (`scripts/read_tracker.py`) emits compact JSON by default with the per-set `rows` array gated behind `--include-rows`; the report sections shown to the user are gated on the per-tracker `capabilities` (so HL users don't see Recovery / per-workout-HR sections their data source can't fill).
- `/log` — append a workout to the current monthly CSV (`Skills/workout-logger/`). Safe to backfill past dates — `canonicalize_monthly_csv` self-sorts every monthly file on every append, and non-contiguous same-date blocks merge back into one session automatically. After every run, the logger asks once whether to refresh Apple Health data; on confirm it dispatches `import_apple_health.py --person <Person>` for `.zip` exports or `import_hl_export.py --person <Person>` for `.txt` exports based on what's in the workout-tracker root. Both importers archive the source export to `<root>/.processed/` on success.
- `python3 Skills/shared/maintain.py --person <Name>` — maintenance utility (no slash command). Canonicalize every per-month CSV across all months, validate the per-person CSV store. Run after a schema migration, after manual edits to past months, or whenever something looks off. Idempotent — a clean tree reports "no change" on every CSV.

## Conventions

- **Notes columns are for user-supplied, row-unique annotations only.** Writers (importers, /log) must never stash pipeline-state strings in Notes — anything that recurs as the same string across more than a handful of rows is a category, not an annotation, and belongs in a typed column. Two violations were cleaned up in the 2026-05 Notes-hygiene pass: `"incidental walk"` (68 workout_sessions rows) → typed `Incidental` boolean column; `"auto-imported from Apple [ | source: <Device>]"` (24 monthly cardio rows) → typed `Source` column with values `manual` / `apple` / `gymkit:<Device>`. Going forward: if a Note would be the same string on every matching row, route it through a column instead. Applies to every CSV in `<Person>/data/`.
- **Heat-temperature auto-fill (sauna).** When the user types `sauna 5min` without a temperature, `upsert_thermal_sessions` fills `heat_temp_c` from a hardcoded type-default table (`dry`=90, `bio`=55, `steam`=45, `infrared`=45, `banya`=70 — anchored to Germany / Holmes Place practice). Explicit user input always wins; named-sauna aliases (`finnish`/`dry`, `bio`/`sanarium`, `IR`/`infrared`/`infrarot`, etc.) resolve to a type and inherit its default. Per-tracker override via `profile.csv` `sauna_default_temp_c` is a future-easy follow-up.
- Exercise names use title case (`Dumbbell Flat Bench Press`, not `dumbbell flat bench press`). Compare case-insensitively when matching across sessions.
- Cable machine weights increment in 5kg steps.
- New exercises get added to the canonical markdown at `Skills/shared/exercises-database.md` under the appropriate muscle → pattern section. There's no xlsx mirror anymore — both `/log` and `/coach` read the markdown directly. Plurals, synonyms, and old typo'd names go in `Skills/workout-logger/references/aliases.md` so `/log` auto-canonicalizes them.
- Past monthly CSVs that contain old typo'd exercise names (e.g. "Deadhang", "Dips", "Stomach Press*") can be cleaned up retroactively with `python3 Skills/shared/canonicalize_logs.py --person <Person>`. The script renames typos to canonical names across every monthly CSV, strips stale "(not in database)" notes, and prints any ambiguous names (e.g. bare "Leg Curl") for manual decision rather than guessing.
- **Bodyweight is opt-in.** `/log` no longer prompts. Include a line like `weight 76.5` (or `bw 76.5`, `bodyweight: 76.5`) in the `/log` message to record a morning weight for that session's date. The logger forwards it into `<Person>/data/health_metrics.csv` (sparse-merge — never overwrites other metrics on that date). The standing convention is morning / empty-stomach; only annotate if the context differs (e.g. `weight 77.1 after dinner`).
- **Sleep is opt-in.** `/log` never prompts for sleep either. Include a line like `sleep 7h25`, `sleep total 7.5 deep 1.2 rem 1.3`, `inbed 8.4`, or `efficiency 91` (manual override) on a header line and the logger parses it into a `sleep` payload entry keyed to that session's date (the wake-up date). `append_workout.py` dual-writes: rich per-night detail (all 6 stages + Time in Bed + N Segments + first/last segment clock times) into `<Person>/data/sleep/YYYY.MM.nights.csv`, and headline fields (Sleep Total / Deep / REM / Time in Bed) mirrored into `health_metrics.csv` for the recovery_score path. Sparse-merge throughout — partial input fine; Sleep Efficiency is auto-derived when both Total and Time in Bed are present and `efficiency_pct` wasn't supplied. Manual entries can't fill `n_segments` / first / last (Apple-importer only).
- **Sauna + cold exposure is opt-in.** `/log` never prompts. Include a `sauna` line (e.g. `sauna 12+8min 85C dry` for two rounds; `sauna 10min 85C` for one) and/or a `cold` line (e.g. `cold 5min air`, `cold 30s shower`, `cold 90s plunge 8C`, `cold 12min water 14C`) under a workout header. A sauna+cold pair under the same workout becomes one row in `<Person>/data/thermal/YYYY.MM.sessions.csv` (paired protocol session). Standalone cold is its own row. `/coach`'s plan template includes a `**Sauna / cold:** ___________` placeholder under each workout's Date line so the user can write in what happened on the gym floor and re-type it into `/log` later. Coach plan output gates on `thermal_summary` presence (data-presence, not source); HSP-induction band threshold is ≥80°C and ≥20min per session; default frequency target 4×/wk, override via `profile.csv` `sauna_target_per_week`.
- **Apple Health import.** `/log` offers to refresh on every run via an `AskUserQuestion` prompt — pick "Refresh now" or "Skip"; the prompt always fires. The importer auto-resolves the export file from the workout-tracker root in this priority order: (1) `./Export - <Person>.zip` (Apple zipped XML, per-person), (2) `./Export.zip` (single-user fallback), (3) `./health_export_*.txt` (HLExport text dump — most recent by mtime; the user drops one fresh file at a time without renaming). Dispatch is by extension: `.zip` → `import_apple_health.py --person <Person>`, `.txt` → `import_hl_export.py --person <Person>`. **Both archive the source export to `<root>/.processed/` on success** (CSVs are the persistent record; the archive is the rollback path if a downstream bug damages the CSVs). Re-runs are idempotent; sparse-merge upserts protect existing data, so switching a tracker between sources is non-destructive. If the resolved file's source disagrees with `profile.csv`'s `source`, the logger asks once before importing.

## Backups

This directory is in iCloud, so the trackers are continuously backed up — no manual backups needed. The PR1 / PR3a `*.pre-*-backup.xlsx` snapshots have been removed; iCloud version history is now the only rollback path.
