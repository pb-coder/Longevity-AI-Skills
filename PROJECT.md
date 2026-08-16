# Workout Tracker

Hypertrophy + longevity training logs for multiple per-person trackers
that share the same goals and conventions. Used with a set of Claude
skills.

## Implementation principles

The tracker is a CSV-backed product with stable file contracts. Code
changes must preserve public commands, CSV schemas, person-relative
paths, and coach/log semantics unless a migration is explicitly planned.
The implementation should be boring: typed command boundaries, isolated
I/O, pure analytics where practical, atomic writes, idempotent upserts,
and measured performance changes.

The `Skills/tracker/` package is the home for cross-skill primitives
such as `TrackerContext`, CSV table mechanics, typed JSON contracts, and
benchmark helpers. Domain-specific policy remains in `Skills/shared/`
and the individual skill folders.

## Files

Two parallel trackers live in per-person folders inside this directory:

```
<root>/
├── <Person>/
│   └── data/                            # its own git repo — see Backups
│       ├── .git/                        # one commit per confirmed write
│       ├── health_metrics.csv           # per-day health aggregates (22 cols)
│       ├── workout_sessions.csv         # one row per Apple Workout
│       ├── profile.csv                  # source / auto_cardio / birthday / swim CSS
│       ├── monthly/                     # one CSV per YYYY.MM workout month
│       │   ├── 2026.05.csv              # 18-col schema, ASC by (Date,#,Set)
│       │   └── …                        # canonicalize rebuilds TOTAL rows + computed cells
│       ├── swimming/                    # per-swim aggregates
│       │   ├── YYYY.MM.workouts.csv     # per-swim aggregates (per month)
│       │   └── YYYY.MM.laps.csv         # frozen XML-era per-lap detail; nothing writes these now
│       ├── sleep/                       # per-night sleep architecture
│       │   └── YYYY.MM.nights.csv       # per-night architecture (per month)
│       └── thermal/                     # manual /log only; absent until first session
│           └── YYYY.MM.sessions.csv     # per-session sauna + cold exposure (per month)
├── <OtherPerson>/                       # same shape (folders appear only when populated)
├── archive/                             # one cold native Export.zip; no code reads it
└── Skills/
```

There is no xlsx anywhere post-PR3a. Per-month workout data lives in
`<Person>/data/monthly/YYYY.MM.csv` — 18-column schema (`SESSION | Date
| # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) |
Duration (min) | Pace (min/km) | Avg HR | Active Cal | Total Cal |
Elevation (m) | Elapsed | Source`), plus a TOTAL row per strength session.
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

`health_metrics.csv` and `workout_sessions.csv` are populated by a single importer, `Skills/shared/import_health_auto_export.py`. It handles `HealthAutoExport*.zip` dropped in the workout-tracker root and nothing else — the native Apple XML importer (`Export*.zip`) was retired, so there is no filename dispatch left to make. It writes per-day aggregates (VO2max, RHR, HRV, walking HR, wrist temp, breathing disturbances, exercise minutes, body composition, steps, active + basal energy), per-workout rows with avg/max/min HR, per-night sleep architecture rows to `sleep/YYYY.MM.nights.csv` (see Sleep section below), and per-swim aggregates to `swimming/YYYY.MM.workouts.csv` (see Swim section). It is idempotent; sparse-merge protects existing values, and `--replace-range` can clear old machine-imported rows in an explicit date range before rewriting them authoritatively.

**Inside the ZIP, the archive member picks the reader.** A `HealthAutoExport-*.json` member selects the JSON reader — the only supported format going forward, because it carries canonical English metric and workout names regardless of phone locale, and the per-night sleep timestamps the Sleep Regularity Index needs. Anything else falls back to the deprecated CSV reader, which prints a warning on every run; that reader is localised, carries no sleep timestamps, and survives only until the second tracker's phone settings switch to JSON.

**The importer deletes the consumed ZIP on success** (`--keep-export` is the escape hatch). It does not archive it — `.processed/` is retired and the rollback path is git; see Backups.

### `health_metrics.csv` schema

22 columns: `Date | Bodyweight (kg) | VO2max | Resting HR | HRV SDNN | Walking HR | HR Recovery 1min | Sleep Total | Sleep Deep | Sleep REM | Time in Bed | Resp Rate | Wrist Temp | Sleep Breath Dist | Exercise Min | Waist (cm) | Body Fat % | Lean Mass (kg) | Steps | Active Energy (kcal) | Basal Energy (kcal) | Notes`.

`Steps` / `Active Energy (kcal)` / `Basal Energy (kcal)` were appended immediately before `Notes` in the 2026-08 migration, matching the `Waist` / `Body Fat %` / `Lean Mass` precedent before them. Older rows pad the new cells to blank and self-migrate on the next write; every read resolves columns by header *name*, so nothing reads this file positionally and a file still carrying an old header keeps parsing.

Two energy components are stored rather than one TDEE number because the split carries information the sum destroys: active energy is training load, and basal energy falling during a cut is adaptive thermogenesis. Summing them makes those two moves indistinguishable.

### Per-person source profile

Each person's `data/profile.csv` is a 2-column key/value file pinning these settings:

| Key | Meaning | Default |
|---|---|---|
| `source` | `health_auto_export` — the only accepted value. The two older values (the native-XML source and the legacy text-dump source) were removed from the schema when the native XML importer was retired; the profile reader now ignores anything else | `health_auto_export` |
| `auto_cardio` | If true, Apple-recorded cardio workouts (Run / Hike / Cycle / Swim / HIIT) auto-flow into the matching `monthly/YYYY.MM.csv` | `true` |
| `birthday` | YYYY-MM-DD of birth. Used by `/coach` to compute age dynamically for the max-HR fallback formula (Tanaka 208 − 0.7×age) when Apple per-workout HR isn't observable | unset → coach uses age 30 fallback |
| `swim_css_sec_per_100m` | Critical Swim Speed pace (sec/100m). Set via `/log` `CSS test` workflow; `/coach` uses it to classify each swim into Recovery / Aerobic / Threshold / VO2 zones | unset → coach skips zone classification |
| `swim_css_set_at` | YYYY-MM-DD when CSS was last measured. Coach prompts a retest after 8 weeks | unset |
| `swim_pool_length_default` | Fallback pool length (metres) for the rare swim where the export omits `lapLength` | unset (importer only writes `Pool Length` when the export provides a plausible `lapLength`) |
| `sauna_target_per_week` | User-reachable heat-exposure frequency target for `/coach` thermal adherence | `4` |
| `light_therapy_target_per_week` | User-reachable light-therapy frequency target for `/coach` adherence | `3` |
| `light_therapy_target_min_per_session` | User-reachable per-session light-therapy duration target | `10` |

`/coach` reads `profile.csv`'s `source` to decide which sections of its report to write — HRV / wrist temp / per-workout-HR / sleep-architecture sections are gated on the matching capability flags (`hrv`, `wrist_temp`, `per_workout_hr_strength`, `sleep_nights`, etc.). The capability map now holds a single entry, `health_auto_export`, which exposes the full surface the coach uses; the two retired source values (native-XML and the legacy text dump) are gone from it. The map is kept as a table rather than collapsed into constants because it is the contract every caller already imports, and a second source may return. Both trackers read `source,health_auto_export`. The profile is bootstrapped on first import; manual override is supported by editing `<Person>/data/profile.csv` directly.

### Swim metrics

Swim workouts still get richer treatment than other cardio: the importer writes a per-swim aggregate row to `<Person>/data/swimming/YYYY.MM.workouts.csv` alongside the ordinary workout-session row.

- **`YYYY.MM.workouts.csv`** — one row per swim. Aggregates written from the HealthAutoExport JSON: Pool Length (`lapLength`, which the export labels "m" but sends in kilometres, so it is scaled ×1000 and range-gated), Laps (derived as `distance / pool length`), Strokes (`totalSwimmingStrokeCount`, falling back to the windowed `swimming_stroke_count` series for open-water swims that carry no per-workout total), SPL (derived as `strokes / laps`), Location, Water Temp (windowed `underwater_temperature`), Avg HR, Active Cal, Notes. Dedupe by `(date, start)`. DESC by date+start.
- **`YYYY.MM.laps.csv`** — **no longer written at all.** Existing XML-era files stay readable and `csv_store.read_swim_laps` / `swim_laps_csv` still resolve them, but nothing produces new ones.

**What per-lap detail cost.** `Avg SWOLF` and `Stroke Mix` are per-lap quantities and stay blank on every new row; existing XML-era rows keep the values they already have, because the upsert is a sparse merge and a blank never overwrites a stored value. An empty `laps.csv` is deliberately not written either — it would read as "this swim had no laps" to every consumer, which is worse than an absent file. `/coach` degrades cleanly: `swim_summary` gates on swim presence, not lap presence, and SWOLF-derived fields return null when no row carries one.

**Location is a genuine three-into-two loss.** The column documents three values — `Pool` / `Outdoor Pool` / `Open Water` — which the XML importer derived from `HKSwimmingLocationType` and `HKIndoorWorkout` together. HealthAutoExport carries only a two-value `location` plus `isIndoor`, and those disagree with the XML on the one swim both sources describe (HAE reports `isIndoor: true` for a workout the XML recorded as an outdoor pool). So only `Open Water` is written, because it is unambiguous in both sources; a pool swim leaves Location **blank** rather than asserting `Pool`, so the sparse merge preserves the richer `Outdoor Pool` already stored on the XML-era rows. Indoor-vs-outdoor pool is a permanent loss on this export, like SWOLF and stroke mix, and a blank cell says so honestly.

`/log` cannot append per-lap detail manually.

**CSS test workflow.** When the user logs a 400m + 200m time-trial pair on the same day with `CSS test` on the header line, `/log`'s parser includes a `css_test` field in the payload. `append_workout.py` computes `(t400_sec - t200_sec) / 2` and writes `swim_css_sec_per_100m` + `swim_css_set_at` to `profile.csv`. CSS detection is never automatic — only the explicit `CSS test` keyword triggers the write.

### Sleep architecture

Sleep gets a dedicated per-month store at `<Person>/data/sleep/YYYY.MM.nights.csv` (one CSV per month, parallel to `monthly/` and `swimming/`). The importer writes HealthAutoExport's per-night sleep aggregate — core / deep / REM / awake / in-bed, plus the night's start and end timestamps. `/log` accepts an opt-in manual sleep payload (see below) that dual-writes to the same store.

Per-night schema (`Date` is dedupe key, sparse-merge with manual-wins on Notes):

- **Stages (hours):** `Sleep Total` (sum of all `Asleep*` stages), `Sleep Core`, `Sleep Deep`, `Sleep REM`, `Sleep Unspecified`, `Sleep Awake` (WASO — wake-after-sleep-onset).
- **Time in Bed (h):** the sleep-efficiency denominator, derived from HealthAutoExport's `inBedStart` / `inBedEnd` span. HAE's own `inBed` duration field reads 0, so the span is what gets used. **That span equals the sleep period rather than real bed occupancy** — the Watch has never emitted true in-bed records, only the legacy iPhone Sleep Schedule did — so the value is a continuity proxy, not clinical time in bed. A floor applies: a night whose `Sleep Total` is below the nap threshold gets no derived Time in Bed, because a nap whose in-bed window equals its sleep window derives 100% efficiency and would drag the efficiency trend up for a reason unrelated to sleep quality. Users wanting a real denominator can type `inbed X.X` in a `/log` message; manual input wins.
- **Sleep Efficiency (%):** derived from `Sleep Total / Time in Bed × 100`, written on import for cheap reads. Auto-computed inside `csv_store.upsert_sleep_nights` when both inputs are present and no explicit override was supplied. `/coach`'s `sleep_summary` tags it `source: "derived_sleep_period"` so the reader knows the denominator's provenance.
- **N Segments:** fragmentation proxy. Count of `Asleep*` + `Awake` segments contributing to the night. **Permanently blank on every row written from now on** — HealthAutoExport reports one aggregate row per night with no segment breakdown, and neither the importer nor manual `/log` can supply it. Existing XML-era rows keep their counts. `/coach`'s fragmentation block degrades to null rather than inventing a number: a night that stops carrying a segment count did not become less fragmented.
- **First Segment Start / Last Segment End:** sleep-onset and wake-up clock times for the night, taken from HealthAutoExport's per-night `sleepStart` / `sleepEnd`. These **survive** and are what the Sleep Regularity Index reads, which is the single strongest reason the JSON reader is the supported one — the deprecated CSV reader carries no sleep timestamps and SRI cannot be computed from it. Bedtime / waketime schedule signal — `/coach`'s `sleep_summary` derives circular stdevs over a 28-day window (so a 23:50 / 00:10 bedtime pair correctly reports a 20-min stdev, not 23h).

**Recovery-night bucketing.** Every night is keyed to its *recovery night* — the morning the user wakes up, not the evening they went to bed. HealthAutoExport already emits one point per night stamped on the wake date, which is the bucket the retired XML aggregator computed segment-by-segment, so both eras of stored rows agree on where a night begins. Two nights landing on one date (a night plus an evening nap) accumulate rather than overwrite, so a nap cannot erase the night and stand as the whole of it.

The same 18:00 rollover still does real work for the two metrics HAE stamps at sleep *onset* rather than wake: **wrist temperature** and **breathing disturbances**. Those readings mostly land between 22:00 and 23:59, so bucketing them by their own calendar day would file every pre-midnight bedtime one night early and put the *next* night's wrist temperature beside a given date's sleep totals — which `recovery_score` reads per date. A reading at or after 18:00 therefore rolls to the following day.

**Side-effect on `health_metrics.csv`:** `sleep_total_h` / `sleep_deep_h` / `sleep_rem_h` use this same bucketing; pre-existing rows shifted slightly (usually <0.7h) on the first re-import that picked up the logic. This is a correctness fix, not data damage.

**Manual sleep via `/log` (opt-in).** The user types `sleep 7h25`, `sleep total 7.5 deep 1.2 rem 1.3`, `inbed 8.4`, or `efficiency 91` (manual override) on a header line. Parsing rules in `Skills/workout-logger/references/parsing-rules.md`. `append_workout.py` dual-writes: rich detail into `sleep/YYYY.MM.nights.csv` via `upsert_sleep_nights` (sparse-merge), headline fields (`Sleep Total` / `Sleep Deep` / `Sleep REM` / `Time in Bed`) mirrored into `health_metrics.csv` so `recovery_score` picks them up without a join. Sparse-merge throughout — partial input is fine.

**What the export can and cannot give.** JSON HAE exposes the per-night stage durations, the in-bed span, and the `sleepStart` / `sleepEnd` timestamps — so stage means, efficiency, schedule consistency and the Sleep Regularity Index all work. It does **not** expose a segment breakdown, so `N Segments` is structurally unavailable rather than a user-fixable blank. The deprecated CSV reader is weaker still: it carries the daily stage aggregates and `Sleep Analysis [In Bed]` but no timestamps at all, so SRI and schedule consistency go dark on any tracker still exporting CSV.

**Segment-level detail is not stored, and can no longer be recovered.** The per-night summary captures the signals that have consumers (stage durations + Efficiency + First/Last clock times for schedule and SRI). Raw segments would be 7-11k rows/year. Earlier revisions of this document said raw segments could be re-extracted from the archived Apple XML at `<root>/.processed/Export*.zip` — **that is no longer true.** `.processed/` is retired and the native export is not being produced any more; the one cold `Export.zip` at `<root>/archive/` is a dead artifact no code reads and covers only the pre-migration window. Hypnograms and sleep-latency derivation are off the table for data collected from now on.

**Coach exposure.** `read_tracker.py` emits a `sleep_summary` block (gated on per-night data existing in the 28-day window) with stage means, efficiency mean + per-week trend, fragmentation, schedule consistency (circular stdev of bedtime / waketime), the Sleep Regularity Index, and last-14-day outliers (efficiency <80% or WASO ≥1h). Fragmentation degrades to null on rows with no segment count — the block reports absence rather than a fabricated improvement. `capabilities.sleep_nights` flags whether the dedicated store is available; `health_auto_export` enables it. `recovery_score` weights are unchanged for now; the plan-of-record is to watch 4-6 weeks of `sleep_summary` data before deciding whether Sleep Efficiency / Core / WASO earns its own driver. `health_metrics_weekly` now includes `time_in_bed_h` so the recovery layer can read it without a folder join.

### Sauna + cold exposure

Heat and cold exposure get their own per-month store at `<Person>/data/sleep/`'s sibling `<Person>/data/thermal/YYYY.MM.sessions.csv`. **Manual `/log` only** — Apple Health doesn't classify sauna sessions reliably, so there's no importer-side write path; the `thermal/` folder is absent until the user logs their first session. One row captures one heat-and/or-cold protocol session (heat-only, cold-only, or paired heat → cold).

Per-session schema (`(Date, Start, Heat Type, Cold Type)` is dedupe key, sparse-merge with manual-wins on Notes):

- **Heat:** `Heat Type` (`dry` / `steam` / `infrared` / `banya` / `none`), `Heat Temp (°C)`, `Heat Rounds`, `Heat Round Durations (min)` (comma-separated per-round minutes for multi-round saunas, e.g. `"12,8"`), `Heat Total (min)` (auto-derived sum).
- **Cold:** `Cold Type` (`none` / `cold_air` / `cold_shower` / `cold_plunge` / `cold_water`), `Cold Duration (sec)`, `Cold Temp (°C)`.
- `Start` (HH:MM) and `Notes` are optional.

**Multi-round saunas** ("2 saunas after each other") live on ONE row with the per-round minutes in `Heat Round Durations`. `Heat Total` is the sum, written on every upsert; the invariant `Heat Total = sum(Heat Round Durations)` always holds on write. This avoids a separate per-round table (over-engineering for 1-3 rounds).

**Blank-start same-day thermal sessions.** If two complete same-shape entries have the same date, blank start, heat type, and cold type, `upsert_thermal_sessions` preserves both by assigning the later row a synthetic `Start` value like `occurrence:2`. (There is no importer path here — thermal is manual `/log` only.) Exact reruns stay idempotent; the synthetic occurrence is only used to avoid overwriting a complete existing session.

**Manual via `/log` (opt-in).** The user types `sauna 12+8min 85C dry` and/or `cold 5min air` lines on a workout header. Parsing rules in `Skills/workout-logger/references/parsing-rules.md` (`## Sauna + cold exposure (opt-in)`). A `sauna` + `cold` pair under the same workout header in one `/log` message becomes ONE row (paired protocol session); standalone cold (morning cold shower without sauna) is a row with heat columns blank. `append_workout.py` writes the entry to the matching `thermal/YYYY.MM.sessions.csv` via sparse-merge. **No mirror to `health_metrics.csv`** — heat / cold is per-event, not a daily-snapshot metric.

**Coach exposure.** `read_tracker.py` emits a `thermal_summary` block (gated on per-session data existing in the 28-day window) with separate `heat` and `cold` sub-blocks plus an `adherence` sub-block. The heat block reports frequency (sessions/wk, vs target), dose (total minutes/wk, and "minutes ≥80°C ≥20min/wk" — the Laukkanen + mechanistic HSP-induction band), type distribution, and multi-round-sessions percentage. The cold block reports frequency, dominant type, and how often cold was paired with a heat session in the same row. The adherence sub-block returns categorical status — `below-target` / `on-target` / `above-target` for frequency, and `below-HSP-threshold` / `in-band` / `above-band` for duration. **Frequency target** defaults to 4×/wk (mid-band of `interventions.md`'s 4-6 range, also the Laukkanen KIHD mid-band); user can override via `profile.csv` `sauna_target_per_week` when their sauna access makes another target more realistic. The `### Heat / Cold exposure` report section is REQUIRED when `thermal_summary` is present and silent otherwise. **`/longevity` reads `thermal_summary` instead of trusting the verbal-claim adherence on `interventions.md`** — the Sauna row in `interventions.md` should reference live data, not a claimed protocol.

### Auto-cardio (Apple → monthly CSV)

When `Profile.auto_cardio` is true, every Apple-recorded workout in `CARDIO_AUTOLOG_TYPES` (Running, Hiking, Cycling, Swimming, HighIntensityIntervalTraining) gets appended to the matching `monthly/YYYY.MM.csv` as a cardio row carrying an importer identity in the typed `Source` column (`apple[@HH:MM]`) — not a Notes string; see the Notes-hygiene convention below. Walks and indoor strength sessions are excluded — incidental walks would dominate, and Apple doesn't capture sets for strength. **Manual entries always win**: a cardio row with the same `(date, exercise, duration ±1 min)` as an existing manual row is never duplicated, and a previously auto-imported row is a no-op on re-runs (idempotent).

**Current-month gate.** The importer only writes into the current calendar month's monthly CSV by default. Past months are "finished" and never re-scanned, so a cardio row the user deletes from `2026.02.csv` stays deleted on the next import — no separate tombstone bookkeeping needed. The strength-session metadata writer follows the same rule: workouts dated outside the current month are skipped. For deliberate backfills, run the importer with `--allow-past-months`; that flag applies to both cardio rows and strength TOTAL metadata. (This replaced a previous `Tombstones` sheet + `auto_cardio_since` profile cell in 2026-05; both are now gone.)

Per-person coach output:

- `plans/<Person>/<YYYY-MM-DD>-assessment.html` — self-contained dashboard (inline CSS / SVG / JS, no CDN, opens offline). Rendered by `/coach` on every run.
- `plans/<Person>/<YYYY-MM-DD>-workout.md` — lean workout-plan markdown, bullets only, no tables, sparse sub-bullet notes. Linked from the dashboard.

Both files are dated per generation and accumulate (no `latest-*` symlink — open the newest dated file). Path resolvers in `shared/person_paths.py`: `plans_dir(person)`, `assessment_html(person, date)`, `workout_plan_md(person, date)`. The pre-2026-05 root-level `workout_plan - <Person>.md` files are frozen historical artifacts; `/coach` no longer writes there. Full rendering contract lives in `Skills/workout-coach/references/assessment-dashboard.md`.

## Routing (who is a message about?)

Every skill invocation must resolve a person before touching a file:

- If the user names a person or tracker, use that tracker.
- If the user uses pronouns or context that clearly refer to one tracker, use that tracker.
- Otherwise ask which tracker/person this is for before running.

Never mix data across trackers in a single skill run.

## Monthly CSV format

Columns (18, in order): `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR | Active Cal | Total Cal | Elevation (m) | Elapsed | Source`. ASC by (Date, #, Set), TOTAL rows interleaved at strength-session boundaries. (The old `Laps` column was retired in 2026-05; older 17-col rows pad `Source` to blank and self-migrate on the next `canonicalize_monthly_csv` pass.)

Each set is one row. Date, #, and Exercise are populated on every row (no carry-forward shorthand). `#` restarts at 1 per date and is shared by all sets of the same exercise. Cardio rows use the cardio columns (Distance through Elapsed); strength rows leave them blank.

`SESSION` is a per-month display number (1, 2, 3…) repeated on every row of the same date — including that session's trailing TOTAL row. Mixed-modality days can share the same `SESSION` number: a strength session and an auto-cardio swim/run appended on the same date still have one date-keyed display number. It's populated by `canonicalize_monthly_csv`, not by hand. It is intentionally ephemeral: inserting an earlier-dated workout later in the month renumbers following sessions. Do not use `SESSION` as a stable external identifier; use `(Date, Exercise, Start/Duration/Source)` or the source workout row when you need identity. `read_tracker.py` splits mixed dates into separate `monthly_sessions` entries keyed by `(date, session_kind)`.

**TOTAL row carries the strength session's full session-level summary.** Each strength session ends with a `TOTAL` row that holds:
- `Date` (col 2) — the session date.
- `Volume` (col 8) — `sum(reps × kg)` over the set rows, written as a literal number (was a formula in the xlsx era).
- `Notes` (col 9) — `Deload Workout` marker when applicable. Hoisted there by canonicalize from any data row that had the marker (legacy /log convention put it on the warmup row).
- `Duration (min)` (col 11) — strength block's total active minutes (MM:SS).
- `Avg HR` (col 13) — duration-weighted across the strength workout cluster.
- `Active Cal` / `Total Cal` (cols 14–15) — sum across the strength cluster.
- `Elevation (m)` (col 16) — usually blank for indoor strength.
- `Elapsed` (col 17) — wall-clock time (H:MM:SS or MM:SS).

The session's data rows (warmup + working sets) hold per-set data only; their cols 11/13/14-17 are blank. Cardio-only days have no TOTAL row — each cardio row carries its own per-row metadata directly. Apple-Watch session metadata is written to the TOTAL row by `monthly_csv.upsert_monthly_strength_session` (duration, HR, calories, elevation, and elapsed when available), fed by the strength-session clustering in `shared/strength_sessions.py`. Manual `/log` doesn't write the metadata fields — the importer fills them post-hoc on the matching session.

Every set row's Volume cell is `reps × kg` written as a literal number, recomputed on every canonicalize pass — don't hand-edit Volume; edit reps or kg and let canonicalize redo the math.

## Skills

Skill source lives in the `Longevity-AI-Skills` repository, cloned
locally at `Skills/`. Edit the unzipped source there and commit
changes. See `Skills/CLAUDE.md` for the repo layout.

- `/coach` — reads the per-person CSVs, reports on training state, and generates new workout plans (`Skills/workout-coach/`). Each strength workout in the output has a `**Date:** ___________` placeholder under its heading; fill it in when you train so the date is visible when you later `/log` the session. The script (`scripts/read_tracker.py`) emits compact JSON by default with the per-set `rows` array gated behind `--include-rows`; the report sections shown to the user are gated on the per-tracker `capabilities`.
- `/log` — append a workout to the current monthly CSV (`Skills/workout-logger/`). Safe to backfill past dates — `canonicalize_monthly_csv` self-sorts every monthly file on every append, and non-contiguous same-date blocks merge back into one session automatically. After every run the logger refreshes health data **automatically, with no prompt**: it runs `import_health_auto_export.py --person <Person>` against the newest `HealthAutoExport*.zip` in the workout-tracker root, and the importer deletes the ZIP on success.
- `python3 Skills/shared/maintain.py --person <Name>` — maintenance utility (no slash command). Canonicalize every per-month CSV across all months, validate the per-person CSV store. Run after a schema migration, after manual edits to past months, or whenever something looks off. Idempotent — a clean tree reports "no change" on every CSV.

## Conventions

- **Notes columns are for user-supplied, row-unique annotations only.** Writers (importers, /log) must never stash pipeline-state strings in Notes — anything that recurs as the same string across more than a handful of rows is a category, not an annotation, and belongs in a typed column. Two violations were cleaned up in the 2026-05 Notes-hygiene pass: `"incidental walk"` (68 workout_sessions rows) → typed `Incidental` boolean column; `"auto-imported from Apple [ | source: <Device>]"` (24 monthly cardio rows) → typed `Source` column. `Source` values are `manual` or an importer identity: `apple[@HH:MM[:SS]]` / `gymkit:<Device>[@HH:MM[:SS]]`. The optional time suffix is part of the contract and disambiguates same-day same-type imported cardio rows. Note that `gymkit:<Device>` is now **read-only in practice**: GymKit device detection lived in the retired XML importer, HealthAutoExport exposes no equivalent, and the only code that still produces the value is the legacy-Notes migration in `monthly_csv_values.py`. New imports write plain `apple[@HH:MM]`. The value stays in the contract because stored rows carry it and consumers must keep parsing it. Going forward: if a Note would be the same string on every matching row, route it through a column instead. Applies to every CSV in `<Person>/data/`.
- **Heat-temperature auto-fill (sauna).** When the user types `sauna 5min` without a temperature, `upsert_thermal_sessions` fills `heat_temp_c` from a hardcoded type-default table (`dry`=90, `bio`=55, `steam`=45, `infrared`=45, `banya`=70). Explicit user input always wins; named-sauna aliases resolve to a type and inherit its default. Per-tracker override via `profile.csv` `sauna_default_temp_c` is a future-easy follow-up.
- Exercise names use title case (`Dumbbell Flat Bench Press`, not `dumbbell flat bench press`). Compare case-insensitively when matching across sessions.
- Cable machine weights increment in 5kg steps.
- New exercises get added to the canonical markdown at `Skills/shared/exercises-database.md` under the appropriate muscle → pattern section. There's no xlsx mirror anymore — both `/log` and `/coach` read the markdown directly. Plurals, synonyms, and old typo'd names go in `Skills/workout-logger/references/aliases.md` so `/log` auto-canonicalizes them.
- Past monthly CSVs that contain old typo'd exercise names (e.g. "Deadhang", "Dips", "Stomach Press*") can be cleaned up retroactively with `python3 Skills/shared/canonicalize_logs.py --person <Person>`. The script renames typos to canonical names across every monthly CSV, strips stale "(not in database)" notes, and prints any ambiguous names (e.g. bare "Leg Curl") for manual decision rather than guessing.
- **Bodyweight is opt-in.** `/log` no longer prompts. Include a line like `weight 76.5` (or `bw 76.5`, `bodyweight: 76.5`) in the `/log` message to record a morning weight for that session's date. The logger forwards it into `<Person>/data/health_metrics.csv` (sparse-merge — never overwrites other metrics on that date). The standing convention is morning / empty-stomach; only annotate if the context differs (e.g. `weight 77.1 after dinner`).
- **Sleep is opt-in.** `/log` never prompts for sleep either. Include a line like `sleep 7h25`, `sleep total 7.5 deep 1.2 rem 1.3`, `inbed 8.4`, or `efficiency 91` (manual override) on a header line and the logger parses it into a `sleep` payload entry keyed to that session's date (the wake-up date). `append_workout.py` dual-writes: rich per-night detail (all 6 stages + Time in Bed) into `<Person>/data/sleep/YYYY.MM.nights.csv`, and headline fields (Sleep Total / Deep / REM / Time in Bed) mirrored into `health_metrics.csv` for the recovery_score path. Sparse-merge throughout — partial input fine; Sleep Efficiency is auto-derived when both Total and Time in Bed are present and `efficiency_pct` wasn't supplied. Manual entries can't fill `n_segments` (nothing can any more — see Sleep architecture) or the first/last segment timestamps (importer-only).
- **Sauna + cold exposure is opt-in.** `/log` never prompts. Include a `sauna` line (e.g. `sauna 12+8min 85C dry` for two rounds; `sauna 10min 85C` for one) and/or a `cold` line (e.g. `cold 5min air`, `cold 30s shower`, `cold 90s plunge 8C`, `cold 12min water 14C`) under a workout header. A sauna+cold pair under the same workout becomes one row in `<Person>/data/thermal/YYYY.MM.sessions.csv` (paired protocol session). Standalone cold is its own row. `/coach`'s plan template includes a `**Sauna / cold:** ___________` placeholder under each workout's Date line so the user can write in what happened on the gym floor and re-type it into `/log` later. Coach plan output gates on `thermal_summary` presence (data-presence, not source); HSP-induction band threshold is ≥80°C and ≥20min per session; default frequency target 4×/wk, override via `profile.csv` `sauna_target_per_week`.
- **Health import runs automatically and asks nothing.** `/log` refreshes on every run without a prompt. Two prompts that earlier revisions of this document described are gone: the "Refresh now / Skip" `AskUserQuestion` was retired, and the source-mismatch confirmation ("if the resolved file's source disagrees with `profile.csv`'s `source`, ask once") is dead because only one source exists to disagree with. The importer resolves the newest `HealthAutoExport*.zip` in the workout-tracker root by mtime; `--zip` accepts an explicit path or glob. There is no `Export*.zip` branch. **The consumed ZIP is deleted on success** — `--keep-export` keeps it. Re-runs are idempotent; periodic store upserts preserve Notes, while machine-derived non-Notes cells are importer-owned. `--replace-range` is available for authoritative backfills and requires `--allow-past-months` when spanning past monthly CSVs.
- **The one `/log` prompt that survives is unrelated to import.** When the parsed payload carries a `cold_air` entry with no `cold_temp_c`, `/log` asks once for the outdoor temperature before writing (answer in °C or `skip`). The justification is narrow and worth stating precisely, because a wrong version of it was in circulation: it is *not* that Apple Health cannot export ambient temperature — HealthAutoExport supplies `temperature` and `humidity` in clean °C on nearly every workout record. It is that a standalone sauna or cold-air session **is not a workout**, so no workout record exists to carry its ambient temperature, and a `cold_air` session at −5°C is a fundamentally different stimulus from one at 25°C.

## Backups

**Each person's `data/` directory is its own git repository**, initialised and driven by `shared/data_git.py`. Both `append_workout.py` and the importer commit automatically after every confirmed write — one commit per operation, with a message naming what was written (`log: N rows, <span>` / `import: <zip name>`). A bad import or a mis-parsed `/log` is now an ordinary `git revert` instead of an unrecoverable overwrite. `<Person>/` sits outside the `Skills/` repo, so a repo at `<Person>/data` nests inside nothing and conflicts with nothing.

**A git failure must never fail a workout log.** Every entry point in `data_git.py` catches, warns, and returns `None`. Losing the history of a write is an annoyance; losing the write is not acceptable. Git identity (`user.name` / `user.email`) is set locally on every repo it initialises, so a fresh machine with no global git config still commits.

**The archive is no longer the forensic trail.** `.processed/` is retired and stays empty — it had reached 966 MB against a live CSV store well under 1 MB, and the commit history serves the same purpose at a thousandth of the size. The importer deletes the consumed ZIP on success (`--keep-export` to keep it). One cold native `Export.zip` survives at `<root>/archive/` as a dead artifact: no code reads it and it covers only the pre-migration window. A handful of dated pre-change `data/` snapshot folders sit beside it from before the git repos existed; those are equally cold, and git supersedes them. Do not treat any of it as a recovery path.

**iCloud caveats — these matter.** The repos live in iCloud Drive, deliberately, because the tracker has to be readable from every device the user logs from. That comes with real hazards:

- **One machine at a time.** iCloud syncs `.git/` like any other folder, so two machines writing at once can interleave objects and refs. This cannot be enforced in code.
- **Nothing runs `git gc` or repacking, ever, automatically.** Repacking rewrites many objects at once and is the operation most likely to lose a race with sync. No code path in the tracker invokes it.
- **Conflict copies are gitignored.** iCloud appends `" 2"`, `" 3"` to a duplicate filename instead of merging; the `.gitignore` `data_git.py` writes excludes that pattern so a sync artifact never lands in a commit and never becomes the file a later read picks up.

Beyond git, this directory is in iCloud, so the trackers also carry iCloud version history. The PR1 / PR3a `*.pre-*-backup.xlsx` snapshots have been removed.
