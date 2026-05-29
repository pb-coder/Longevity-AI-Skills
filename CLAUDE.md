# Skills

Source for the Claude Code skills used by the repo owner. Cloned from
the `Longevity-AI-Skills` repository; edit here and push.

## Engineering contract

- The repo root is `Skills/`. Per-person tracker data and generated
  plans live one directory above it and are intentionally not committed.
- Preserve public CLIs, CSV schemas, file locations, and generated output
  semantics unless the PR explicitly documents a migration.
- Public scripts stay thin: parse args, build a `TrackerContext`, call
  domain code, print status/JSON, return an exit code.
- Shared primitives live in `tracker/`; domain storage and import policy
  lives in `shared/`; skill behavior lives in each skill folder.
- One concept gets one source of truth. Do not copy path rules, schema
  constants, CSV I/O, date parsing, capability gates, or exercise catalog
  parsing into another module.
- Optimize by removing wasted work first: repeated reads, repeated full
  scans, duplicate canonicalization, unnecessary rewrites, and reparsing
  static markdown inside one command. Add caching only after measurement.
- Refactors need regression coverage. The default verification command is
  `python3 -m unittest discover -s tests -v` from this directory.
- Privacy rule: committed docs and code comments must not include real
  person names, relationships, locations, ages, medication details, lab
  status, or other profile facts. Use `<Person>` / `<OtherPerson>`
  placeholders. Private context lives only in uncommitted per-person data.
  Before pushing, run the committed-text scrub with a caller-supplied
  sensitive-token pattern:
  `rg -n -i "$PRIVATE_IDENTIFIER_PATTERN" -g '!*.pyc' -g '!plans/**' -g '!<Person>/**' -g '!<OtherPerson>/**' .`
  The pattern value must not be committed.

## Layout

Per-person directories sit at the workout-tracker root: `<Person>/`.
Each holds a `data/` folder with every CSV the skills read
or write — there is no xlsx anywhere post-PR3a. Apple Health exports
drop into the root and get **archived to `<root>/.processed/`** after a
successful import — the CSVs are the persistent record; the archive
keeps a forensic trail in case a downstream bug damages the CSVs.

```
<root>/
├── <Person>/
│   └── data/
│       ├── health_metrics.csv             # date-keyed, sparse-merge
│       ├── workout_sessions.csv           # (date,start)-keyed
│       ├── profile.csv                    # key,value (source, auto_cardio, birthday, swim CSS)
│       ├── monthly/                       # one CSV per YYYY.MM
│       │   ├── 2026.05.csv                # 18-col schema, ASC by (Date,#,Set)
│       │   ├── 2026.04.csv
│       │   └── …                          # canonicalize rebuilds TOTAL rows + computed cells
│       ├── swimming/                      # native XML lap detail only
│       │   ├── 2026.05.workouts.csv       # per-month swim aggregates, (date,start)-keyed
│       │   ├── 2026.05.laps.csv           # per-month per-lap detail, (date,workout_start,lap_num)-keyed
│       │   └── …
│       ├── sleep/                         # XML / HealthAutoExport sleep nights
│       │   ├── 2026.05.nights.csv         # per-night, date-keyed; all 6 stages + Time in Bed + Efficiency + N Segments + first/last segment clock times
│       │   └── …
│       ├── thermal/                       # manual /log only; absent until first sauna / cold session is logged
│       │   ├── 2026.05.sessions.csv       # per-session, (date,start)-keyed; heat (type/temp/rounds/durations/total) + cold (type/duration/temp)
│       │   └── …
│       ├── light_therapy/                 # manual /log only; absent until first RLT / PBM / blue light session is logged
│       │   ├── 2026.05.sessions.csv       # per-session, (date,start)-keyed; duration, light_type, wavelength_nm, body_area, modality, ambient_temp_c
│       │   └── …
│       └── longevity/                     # /longevity personal data (outside the Skills repo by design)
│           ├── profile.md                 # slow-changing identity (DOB, height, family history)
│           ├── state.md                   # current snapshot (conditions, meds; live metrics pulled from health_metrics.csv)
│           ├── interventions.md           # daily/weekly protocol (supplements, diet, training, skincare) + status tracker
│           └── biomarkers.md              # append-only lab history
├── <OtherPerson>/                          # same shape (folders appear only when populated)
├── plans/                                 # /coach output — dated per generation; one folder per person
│   ├── <Person>/
│   │   ├── YYYY-MM-DD-assessment.html     # self-contained dashboard (inline CSS / SVG / JS, no CDN)
│   │   ├── YYYY-MM-DD-workout.md          # lean exercise list — bullets only, no tables, sparse sub-bullet notes
│   │   └── …
│   └── <OtherPerson>/
│       └── …
└── Skills/
    └── shared/
        └── exercises-database.md          # canonical catalog (markdown is truth)

shared/               # Code + docs imported by multiple skills
  person_paths.py     # Path resolver. data_dir(person),
                      # health_metrics_csv(person), workout_sessions_csv(person),
                      # profile_csv(person), monthly_dir(person),
                      # monthly_csv(person, ym), swim_workouts_csv(person, ym),
                      # swim_laps_csv(person, ym),
                      # list_swim_workout_months(person), list_swim_lap_months(person).
                      # Every script accepts `--person <Name>` and resolves the
                      # rest from there.
  exercises_database.py  # Catalog operations: parse, lookup (alias-aware),
                         # fuzzy_match, propose_exercise, propose_alias,
                         # validate_database. Atomic writes with re-parse +
                         # automatic rollback on validation failure. CLI:
                         #   python3 shared/exercises_database.py lookup "<name>"
                         #   python3 shared/exercises_database.py fuzzy "<name>"
                         #   python3 shared/exercises_database.py validate
                         #   python3 shared/exercises_database.py propose --from-stdin
                         # Used by /log at parse time when an exercise misses
                         # the database — the agent dispatches a research
                         # sub-agent and routes the proposal here.
  csv_store.py        # Compatibility facade. Keep public imports here.
  csv_store_common.py # Shared typed table helpers and atomic CSV writes.
  csv_store_profile.py
                      # Profile key/value store: read_profile,
                      # write_profile, ensure_profile.
  csv_store_dense.py  # Dense daily/session stores: Health Metrics and
                      # Workout Sessions schemas, reads, upserts, and source
                      # resolution.
  csv_store_periodic.py
                      # Per-month/per-phase stores: swim, sleep, thermal,
                      # light therapy, nutrition. Sparse merge and
                      # replace-on-match semantics live beside their schemas.
  monthly_csv.py      # Compatibility facade for monthly workout CSVs.
  monthly_csv_schema.py
                      # MONTHLY_HEADERS / MONTHLY_FIELDS / TOTAL_LABEL /
                      # DELOAD_MARKER_TEXT and import policy constants.
  monthly_csv_values.py
                      # Date/number/duration/pace coercion, source migration,
                      # row classification, and drift checks.
  monthly_csv_io.py   # read_monthly plus raw row/dict translation and atomic
                      # writes.
  monthly_csv_canonicalize.py
                      # canonicalize_monthly_csv: sort + recompute Volume /
                      # Pace / Total Cal / SESSION + rebuild TOTAL rows +
                      # hoist deload markers. Idempotent.
  monthly_csv_upsert.py
                      # upsert_rows, upsert_monthly_cardio, and
                      # upsert_monthly_strength_session. Current-month gate
                      # bounds importer writes; past months are "finished".
  exercises-database.md  # Canonical exercise catalog (muscle → pattern →
                         # exercises). Source of truth (no xlsx mirror — the
                         # Exercises Database tab was retired in PR1). Read
                         # directly by /log (name lookup) and /coach
                         # (muscle mapping + tag reading).
  canonicalize_logs.py  # Rename map for past monthly CSVs. Fixes historical
                        # typo'd exercise names ("Deadhang" → "Dead Hang",
                        # "Dips" → "Dip", "Stomach Press*" → "Ab Crunch
                        # Machine", etc.) and clears stale "(not in
                        # database)" Notes once the exercise is canonical.
                        # Reports ambiguous names (e.g. bare "Leg Curl")
                        # instead of auto-renaming. Re-runnable.
                        # Usage: python3 shared/canonicalize_logs.py --person <Person>
  import_apple_health.py  # Apple Health zipped XML importer (<Person>). Streams
                          # Export.xml with iterparse, writes per-day Health
                          # Metrics (VO2max, RHR, HRV, sleep stages, wrist
                          # temp, exercise minutes, BodyMass) and per-workout
                          # Workout Sessions rows (avg/max/min HR, calories,
                          # distance, source) into the per-person CSVs.
                          # Bootstraps profile.csv with source=xml,
                          # auto_cardio=true. When auto_cardio is on, also
                          # appends matching cardio workouts (Run / Hike /
                          # Cycle / Swim / HIIT) to the YYYY.MM monthly sheet
                          # via upsert_monthly_cardio. Idempotent; sparse-
                          # merge upserts never overwrite populated cells
                          # with None. Distance is unit-aware
                          # (<WorkoutStatistics unit="m">). Matrix/GymKit
                          # workouts pre-empt overlapping Watch-only ones.
                          # Deletes the export zip on success.
                          # Usage: python3 shared/import_apple_health.py
                          #          --person <Person> [--since YYYY-MM-DD]
                          #          [--dry-run] [--keep-export]
  apple_health_core.py    # Shared XML timestamp / numeric parsing helpers.
  apple_health_daily.py   # DayAggregator: daily health metrics + sleep-night
                          # aggregation from Record elements.
  apple_health_strength.py
                          # Apple strength-session clustering for monthly
                          # TOTAL-row metadata.
  apple_health_swim.py    # Swim workout/lap CSV payload construction.
  import_health_auto_export.py
                          # HealthAutoExport ZIP importer (<OtherPerson>). Same
                          # full tracker surface as import_apple_health.py
                          # where HealthAutoExport exposes it: VO2max, RHR,
                          # HRV, walking HR, wrist temp, breathing
                          # disturbances, exercise minutes, sleep stages,
                          # workout duration / cal / distance, and
                          # per-workout HR. Bootstraps profile.csv with
                          # source=health_auto_export, auto_cardio=true.
                          # --replace-range clears old machine-imported
                          # rows in the selected date range before writing
                          # the HealthAutoExport rows. Archives the source
                          # ZIP on success.
                          # Usage: python3 shared/import_health_auto_export.py
                          #          --person <OtherPerson> [--zip PATH_OR_GLOB]
                          #          [--since YYYY-MM-DD] [--until YYYY-MM-DD]
                          #          [--allow-past-months] [--replace-range]
                          #          [--dry-run] [--keep-export]
  apple_workout_types.py  # Single source of truth for Apple's workout-type
                          # enum: rawValue → canonical name (RAWVALUE_TO_TYPE),
                          # the auto-cardio eligibility set
                          # (CARDIO_AUTOLOG_TYPES — Running / Hiking / Cycling
                          # / Swimming / HIIT), and the canonical →
                          # tracker-exercise-name map (APPLE_TO_TRACKER_EXERCISE
                          # → Outdoor Run / Hike / Outdoor Cycling / Swim /
                          # HIIT). Append-only as new workouts are encountered;
                          # used by both importers.
  maintain.py           # Maintenance utility (no slash command — invoked
                        # directly when needed). Canonicalizes every monthly
                        # CSV across all months (idempotent), validates the
                        # CSV store (header schema parity, sort order, row
                        # counts), optional --fix-distance-units historical
                        # swim-distance sweep. Run after schema migrations,
                        # manual edits to past months, or anytime drift is
                        # suspected. Auto-canonicalize on every /log write
                        # keeps the current month clean — this script handles
                        # the cross-month sweep.
                        # Usage: python3 Skills/shared/maintain.py --person <Person>

workout-logger/       # /log — append a parsed workout to the tracker.
  SKILL.md            # Agent entry point. Flow §1 has an unknown-exercise
                      # gate: lookup → fuzzy match → alias proposal OR
                      # research sub-agent → user-confirmed write via
                      # shared/exercises_database.py.
  scripts/
    append_workout.py # Routes rows to YYYY.MM sheets, upserts bodyweight
                      # to <Person>/data/health_metrics.csv (sparse-merge,
                      # so the logger's bodyweight write is what keeps
                      # state.md's bodyweight current — no separate write).
                      # Single writer for the monthly CSV side.
  references/         # aliases.md, parsing-rules.md, common-mistakes.md

workout-coach/        # /coach — read tracker, report, plan next workout.
  SKILL.md            # Report template includes a REQUIRED ### Swim
                      # subsection that fires when swim_summary is in the
                      # JSON; gated on data presence.
  lib/                # Internal analytics modules (not directly invoked).
                      # Imported through workout_coach.lib.*; the underscore
                      # package facade preserves the historical hyphenated
                      # skill directory on disk.
                      #   constants.py — capabilities, landmarks, aliases.
                      #   parsing.py   — coercions + _parse_iso_date + _compact.
                      #   extract.py   — CSV readers (monthly + dense + swim),
                      #                  exercises-DB parser, age + max-HR helpers.
                      #   sessions.py  — build_monthly_sessions + bodyweight
                      #                  trend + progression_summary.
                      #   strength.py  — volume, e1RM (context-change aware —
                      #                  user-tagged gym/equipment shifts get
                      #                  excluded from slope_kg_per_4w and
                      #                  drop confidence one band), stale,
                      #                  HR-at-volume divergence,
                      #                  strength-session HR trend.
                      #   cardio.py    — cardio rollups, HR zones, TRIMP,
                      #                  CTL/ATL/TSB, daily activity (NEAT),
                      #                  auto_deload_candidates, plus the
                      #                  per-session hr_zone_label (Z1–Z5)
                      #                  derived from intensity_pct via HRR.
                      #   health.py    — health time-series helpers (window,
                      #                  baseline, trend), weekly aggregates,
                      #                  recovery_score (composes ~9 drivers
                      #                  with per-signal sample-sufficiency
                      #                  gate — confidence drops one band
                      #                  when a high-weight z-scored driver
                      #                  has too few recent readings).
  scripts/
    read_tracker.py   # CLI + main(). Imports the lib/ modules and orchestrates
                      # the JSON output. Emits one JSON blob organised around
                      # session-level signals, not raw arrays. Top blocks:
                      #   - data_source / capabilities / estimated_max_hr +
                      #     estimated_rest_hr (used by all HRR / TRIMP math)
                      #   - monthly_sessions: canonical per-session record
                      #     incl. TRIMP, load_band (light/moderate/hard/red-line),
                      #     intensity_pct, max_hr, volume, is_deload — folds
                      #     in the TOTAL row's metadata + Apple's per-workout
                      #     max_hr; obsoletes the old session_totals dict and
                      #     the workout_sessions_last_28d list.
                      #   - weekly_volume_per_muscle, estimated_1rm,
                      #     progression_summary, stale_exercises (top 5),
                      #     unknown_exercises, deloads, auto_deload_candidates
                      #   - cardio_last_28d + cardio_hr_zones_28d (HRR-based
                      #     time-in-zone using Karvonen)
                      #   - swim_summary (only when there are swims with lap
                      #     detail in the last 28 days):
                      #     totals, avg pace per 100m, avg SPL, avg SWOLF,
                      #     SPL/SWOLF trends, per-session CSS-zone
                      #     classification, stroke-mix outliers, CSS retest
                      #     prompt, inferred CSS test detection.
                      #   - recovery: 0-10 score from HRV / RHR / sleep /
                      #     wrist temp deviations, with named drivers.
                      #     training_load: CTL/ATL/TSB rolling EWMA from per-
                      #     session TRIMP. hr_at_volume_divergence: per-muscle
                      #     fatigue flag from HR creep at constant volume.
                      #   - bodyweight_latest + trend
                      #   - health_metrics_weekly (4-week aggregates; raw
                      #     daily behind --include-daily-health)
                      #   - vo2max_latest / vo2max_trend_per_4w
                      # Compact JSON by default; --pretty for human inspection;
                      # --include-rows / --include-1rm-history /
                      # --include-daily-health to opt in to debug-only payloads.
                      # Null keys are dropped via _compact for token efficiency.
  references/training-science.md

longevity-optimizer/  # /longevity — separate domain. All personal data lives
  SKILL.md            # outside this repo at <Person>/data/longevity/*.md;
  references/         # only framework docs (biomarkers, longevity-interventions,
                      # behavior, response-triggers) stay here.
```

## Conventions

- **Visual surfaces follow `Skills/DESIGN.md`.** Any HTML / CSS output
  (the workout-coach assessment dashboard today; future report
  surfaces tomorrow) reads its tokens from `Skills/DESIGN.md`, which
  uses the [Google Stitch DESIGN.md format](https://github.com/google-labs-code/design.md)
  (YAML token front matter + Markdown prose for rationale). The token
  values are normative; the prose explains intent and how to apply
  them. Lint with `npx @google/design.md lint Skills/DESIGN.md`. **No
  raw hex literals outside the YAML front matter** — render modules
  reference CSS variables that map back to tokens.
- **Notes columns are for user-supplied, row-unique annotations only.**
  Writers (importers, /log) must never stash pipeline-state strings in
  Notes — anything that recurs as the same string across more than a
  handful of rows is a category, not an annotation; it belongs in a
  typed column or boolean flag. A repeated string is invisible to
  filtering / sorting / aggregation and crowds out real annotations.
  Two historic violations (cleaned up in the 2026-05 Notes-hygiene
  pass): `"incidental walk"` on 68 workout_sessions rows became the
  typed `Incidental` boolean column; `"auto-imported from Apple [ |
  source: <Device>]"` on 24 monthly cardio rows became the typed
  `Source` column with values `manual` / `apple` / `gymkit:<Device>`.
  Same rule applies going forward: if a Note would be the same string
  on every matching row, route it through a column instead. The rule
  applies to every CSV in `<Person>/data/`.
- **Python scripts** live under `scripts/` per skill and are invoked by
  the agent via Bash. Public script paths stay stable; direct script
  entry points may add `Skills/` to `sys.path` so package imports work
  when invoked by file path.
- **Package imports**: shared code imports through `shared.*`, tracker
  primitives through `tracker.*`, and coach internals through
  `workout_coach.lib.*`. Modules inside `shared/` and
  `workout-coach/lib/` use package-relative imports; do not add
  per-module sibling-directory `sys.path` bootstraps or new flat
  top-level imports.
- **`canonicalize_monthly_csv` is canonical**: the single source of
  truth for monthly-CSV layout (sort by Date+#+Set, recompute Volume
  and Pace, rebuild SESSION numbering, rebuild TOTAL rows, hoist
  deload markers). Running it twice is a no-op. `/log` calls it
  post-write on the current month; `shared/maintain.py` calls it on
  every monthly CSV for cross-month sweeps. An out-of-order CSV (e.g.
  after a backfill) self-heals on the next pass. The
  monthly CSV has 18 columns:
  `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes |
  Distance (km) | Duration (min) | Pace (min/km) | Avg HR | Active Cal |
  Total Cal | Elevation (m) | Elapsed | Source`. The old `Laps` column was
  removed (2026-05); swim lap count is now sourced exclusively from
  `<Person>/data/swimming/YYYY.MM.workouts.csv`. Older 17-col rows
  pad `Source` to blank and self-migrate on the next canonicalize pass.
- **Computed cells are pre-evaluated on canonicalize.** `Volume =
  reps × kg`, `Pace = duration/distance` (MM:SS, blank outside
  [0.5, 60] min/km), and per-month SESSION counters are written as
  literal values, not Excel formulas. The user can preview the CSV in
  macOS Quick Look or Numbers and see the math directly. No xlsx
  exists post-PR3a; the CSV is the canonical store.
- **Distance is unit-aware end-to-end.** The Apple Health XML importer
  reads the `unit` attribute on `<WorkoutStatistics>` and converts to km
  before writing. Swims arrive in metres by default (`sum="550"
  unit="m"`); without conversion they landed as `550 km`. The
  `_format_pace_min_per_km` helper now blanks pace values outside
  `[0.5, 60]` min/km — degenerate `0:01` outputs from a future unit bug
  surface as a blank cell instead of silent corruption.
- **Fitness-machine dedupe.** The Apple importer detects GymKit-sourced
  workouts via the `device` attribute (substring
  `fitnessmachinemodel`). When a Matrix/Technogym/etc. workout overlaps
  a Watch-only workout of the same activity type and date, the machine
  row wins; the Watch row is dropped (it's a phantom duplicate
  detection). Machine-recorded rows get `auto-imported from Apple |
  source: <DeviceName>` in the Notes column so the user can tell at a
  glance which rows came from gym telemetry vs Watch estimation.
- **Historical unit-bug fix.** `python3 maintain.py
  --person <Person> --fix-distance-units [--dry-run]` scans every
  monthly CSV AND `<Person>/data/workout_sessions.csv` AND every
  per-month `<Person>/data/swimming/YYYY.MM.workouts.csv` for Swim
  rows where Distance > 10 km (almost always meters mis-stored as km),
  divides by 1000, and recomputes pace. Non-swim outliers are flagged
  for human review but not mutated. Idempotent; safe to re-run.
- **Opt-in bodyweight**: `/log` does **not** prompt for morning weight.
  The user includes a line like `weight 76.5` (or `bw 76.5`, `bodyweight:
  76.5`) in the `/log` message when they want to record one. Bulk seeding
  backfills go through `append_workout.py` with a
  `{"rows": [], "bodyweight": [...]}` payload.
- **Exercise canonicalization**: `shared/exercises-database.md` is the
  single source of truth for canonical exercise names. The `/log` agent
  consults `workout-logger/references/aliases.md` to map plurals,
  synonyms, and old typo'd names (e.g. `Hiking` → `Hike`, `Stomach Press`
  → `Ab Crunch Machine`). The aliases file is read by the agent at
  logging time, not by code, so adding an alias takes effect on the next
  `/log` run. There's no xlsx "Exercises Database" tab anymore — the
  markdown is consulted directly by /log and /coach. New entries go into
  the markdown only; no sync step.
- **Cardio + wellness logging is supported**: the markdown includes a
  CARDIO section (Hike, Swim, Walk, Outdoor Run, Outdoor Cycling, HIIT
  + indoor machines) and a WELLNESS section (Yoga, Stretching). These
  entries have no muscle tags, so they're logged and counted toward
  `cardio_last_28d` (where applicable) without contributing to the
  weekly hard-set volume model.
- **Multi-source Apple Health**: each person's `data/profile.csv`
  pins `source` (`xml` / `health_auto_export`) and `auto_cardio` (bool).
  `import_apple_health.py` handles `Export*.zip` (Apple's native XML);
  `import_health_auto_export.py` handles `HealthAutoExport*.zip`.
  XML helper behavior lives in `apple_health_core.py`,
  `apple_health_daily.py`, `apple_health_strength.py`, and
  `apple_health_swim.py`; keep `import_apple_health.py` as the CLI
  orchestration layer.
  The /log skill dispatches by filename; /coach gates report sections
  on `capabilities`. Both active sources expose the full recovery,
  sleep, and per-workout-HR capability surface. `auto_cardio` defaults
  to true on both sources; when on, eligible Apple workouts (Running /
  Hiking / Cycling / Swimming / HIIT) flow into the matching
  `monthly/YYYY.MM.csv`, with manual-wins dedupe (date + exercise,
  ±1min duration tolerance).
- **Coach plan output is split into a dated HTML dashboard + a lean
  workout markdown, both under `plans/<Person>/`.** Each `/coach` run
  writes two paired files: `plans/<Person>/<YYYY-MM-DD>-assessment.html`
  (self-contained: inline CSS / SVG / JS, no CDN, renders identically
  offline) and `plans/<Person>/<YYYY-MM-DD>-workout.md` (bullets only,
  no tables, sparse sub-bullet notes — 0-2 per workout, never rationale
  or "last time X" history). The dashboard carries the full assessment
  (recovery score + drivers, TSB curve over 90 days, per-muscle volume
  bars, activity rings, sleep, strength progression, HRV / RHR / wrist
  temp / VO2max / bodyweight sparklines, recovery practices including
  cold-air outdoor temperature when present, week-over-week comparison)
  and per-card "coach's read" lines that absorb what the old `## Why
  this plan` block used to do. Old root-level files (`workout_plan -
  <Person>.md` / `workout_plan - <OtherPerson>.md`) are frozen history and never
  rewritten. Path resolvers in `shared/person_paths.py`:
  `plans_dir(person)`, `workout_plan_md(person, date)`,
  `assessment_html(person, date)`. **Each workout heading is followed
  by `Date: ___` on its own line and `Recovery (sauna / cold / light):
  ___` on the next line** so the user can fill them in mid-workout.
  The full HTML template + card spec lives in
  `Skills/workout-coach/references/assessment-dashboard.md`.
- **Sleep metrics live in `<Person>/data/sleep/`, per-month nights only.**
  Per-night aggregates (Total / Core / Deep / REM / Unspecified / Awake
  + Time in Bed + Sleep Efficiency + N Segments + First/Last Segment
  Start clock times) on `YYYY.MM.nights.csv`, mirroring the
  `monthly/YYYY.MM.csv` and `swimming/YYYY.MM.*.csv` per-month
  pattern. Apple's sleep stage segments (`HKCategoryValueSleepAnalysis*`)
  are the source for native exports; HealthAutoExport writes matching
  daily sleep-stage aggregates. Headline fields (Sleep Total / Deep / REM /
  Time in Bed) are also mirrored to `health_metrics.csv` so the
  existing recovery_score path reads them without a join.
  `csv_store.read_sleep_nights` aggregates across all months on read;
  `upsert_sleep_nights` is sparse-merge by date with manual-wins on
  Notes — Sleep Efficiency is auto-derived when both Total and
  Time in Bed are present and `efficiency_pct` wasn't supplied
  explicitly. `n_segments`, `first_segment_start`, and
  `last_segment_end` are Apple-importer-only (manual /log entries
  leave them blank). Segment-level detail is NOT stored — only the
  per-night aggregate; raw segments stay in the archived Apple XML
  at `<root>/.processed/Export*.zip` and can be re-extracted if a
  future need arises (hypnograms, sleep-latency derivation).
- **Thermal (sauna + cold exposure) lives in `<Person>/data/thermal/YYYY.MM.sessions.csv`, per-month.**
  Per-session aggregates: Date, Start, Heat Type (`dry` / `steam` /
  `infrared` / `banya` / `none`), Heat Temp (°C), Heat Rounds, Heat
  Round Durations (min) (comma-separated per-round minutes for
  multi-round saunas), Heat Total (min) (auto-derived sum), Cold Type
  (`none` / `cold_air` / `cold_shower` / `cold_plunge` / `cold_water`),
  Cold Duration (sec), Cold Temp (°C), Notes. **Manual /log only** —
  Apple Health doesn't classify sauna sessions reliably, so there's no
  importer-side write path; the `thermal/` folder is absent until the
  user logs their first session. Dedupe by `(date, start)`. A `sauna`
  + `cold` line under the same workout header in one `/log` message
  becomes one row (paired protocol session); standalone cold (morning
  cold shower) is a row with heat columns blank.
  `csv_store.read_thermal_sessions` aggregates across all months on
  read; `upsert_thermal_sessions` is sparse-merge by `(date, start)`
  with manual-wins on Notes; `heat_total_min` and (when absent)
  `heat_rounds` are auto-derived from `heat_round_durations_min` on
  every write so the file is internally consistent. **Almost never
  prompts** — the one carved-out exception: when the parsed payload
  carries a `cold_air` entry whose `cold_temp_c` is null, `/log` asks
  once for the outdoor temperature before writing (one short question,
  user can answer with a number in °C or `skip`). Apple Health does
  not export ambient air temperature in workout XML, so this datum
  can only come from the user, and a `cold_air` session at −5°C is a
  fundamentally different stimulus than one at 25°C. All other thermal
  fields stay absent-≡-didn't-happen. `/coach`'s `thermal_summary`
  block reads this and reports frequency / dose against the
  HSP-induction threshold (≥20min @ ≥80°C, Laukkanen + mechanistic
  consensus); the cold side carries per-session `cold_temp_c` plus a
  `dose_hint: "amber"` when `cold_air >= 18°C` (adaptation evidence
  thin above that). The target defaults to 4×/wk and can be overridden
  via `profile.csv` `sauna_target_per_week`.
- **Light therapy (RLT / PBM / blue light) lives in `<Person>/data/light_therapy/YYYY.MM.sessions.csv`, per-month.**
  Per-session aggregates: Date, Start, Duration (min), Light Type
  (`red` / `near_ir` / `red+ir` / `far_ir` / `blue` / `green` /
  `white` / `other`), Wavelength (nm), Body Area (`full_body` /
  `face` / `back` / `torso` / `arms` / `legs` / `head` /
  `localized`), Modality (`panel` / `mask` / `wand` / `cabin` /
  `device` / `sauna_integrated`), Ambient Temp (°C), Notes. **Manual
  /log only** — Apple Health doesn't classify light-therapy sessions;
  the `light_therapy/` folder is absent until the user logs their
  first session. Dedupe by `(date, start)`. Duration is the only
  required field; everything else is optional. Independent of the
  thermal store — sauna + RLT in one real-life session lands as two
  rows in two stores (the schemas don't mix). The store is broad on
  purpose: it captures heated red-light cabins, near-IR probes,
  blue-light SAD lamps, and any
  future photobiomodulation modality.
  `csv_store.read_light_therapy_sessions` aggregates across all
  months on read; `upsert_light_therapy_sessions` is sparse-merge by
  `(date, start)` with manual-wins on Notes; `modality` defaults to
  `cabin` inside the upsert when `ambient_temp_c >= 30` and the user
  didn't supply a modality (heated walk-in inference). **Never
  prompts.** `/coach`'s `light_therapy_summary` block reads this and
  reports frequency + per-session dose against the (looser) defaults
  of 3×/wk and 10min/session; overrideable via `profile.csv`
  `light_therapy_target_per_week` and
  `light_therapy_target_min_per_session`. No wavelength-efficacy
  claims — the evidence base is far less settled than sauna's HSP
  induction; stay in protocol-adherence language.
- **Swim metrics live in `<Person>/data/swimming/`, split per month.**
  Per-workout aggregates (Pool Length, Strokes, SPL, Avg SWOLF, Stroke
  Mix, Location, Water Temp) on `YYYY.MM.workouts.csv`; per-lap detail
  (Stroke, Duration, SWOLF) on `YYYY.MM.laps.csv`. Mirrors the
  `monthly/YYYY.MM.csv` pattern so the swim store scales with usage.
  Apple's lap events (`HKWorkoutEventTypeLap`) are the source. The
  Apple Health XML importer populates both on every run. HealthAutoExport
  does not currently provide the per-lap payload this tracker consumes,
  so `/coach` skips the swim section unless `swim_summary` exists.
  `csv_store.read_swim_workouts` /
  `read_swim_laps` aggregate across all months on read;
  `upsert_swim_workouts` / `upsert_swim_laps` route entries to the
  correct month by date. Stroke style enum → string map lives in
  `apple_workout_types.HK_SWIMMING_STROKE_STYLE` (0=Unknown, 1=Mixed,
  2=Freestyle, 3=Backstroke, 4=Breaststroke, 5=Butterfly, 6=Kickboard).
  `csv_store.upsert_swim_laps` is replace-on-match (not sparse-merge):
  re-exports authoritatively replace stored lap data so a corrected
  stroke style flows through cleanly.
- **Longevity personal data is decoupled from the skill repo.** All
  PII (DOB, family history, current conditions, supplement stack, lab
  history) lives at `<Person>/data/longevity/{profile,state,interventions,
  biomarkers}.md` — outside the Skills/ git repo by design. Only
  framework docs (interpretation principles, panel design,
  response-trigger logic) stay in `Skills/longevity-optimizer/references/`.
  See `longevity-optimizer/SKILL.md` for the load routing.
- **Logger → state.md cross-effect.** `/log`'s bodyweight handling
  writes to `<Person>/data/health_metrics.csv` (sparse-merge,
  date-keyed). `state.md` therefore doesn't freeze a bodyweight number
  — it points at health_metrics.csv as the live source. The same
  pattern applies to RHR, HRV, VO2max, sleep, HR Recovery: those flow
  from the Apple Health / HealthAutoExport importers into health_metrics.csv and the
  longevity skill reads them on demand via the coach's
  `read_tracker.py`.
- **CSS (Critical Swim Speed)** lives on `profile.csv`:
  `swim_css_sec_per_100m`, `swim_css_set_at`, plus
  `swim_pool_length_default` for the rare workout where Apple omits
  `HKLapLength`. CSS test workflow: log a 400m + 200m TT same-session
  with `CSS test` on the header line; the logger computes
  `(t400_sec − t200_sec) / 2` (sec/100m) and writes both fields.
  `/coach` prompts a retest after 8 weeks. Detection is never
  automatic — only the explicit `CSS test` keyword writes CSS.

## Workout Tracker

Each tracker lives in its own per-person folder
(`<root>/<Person>/data/` containing `health_metrics.csv`,
`workout_sessions.csv`, `profile.csv`, `monthly/YYYY.MM.csv` per
month, `swimming/YYYY.MM.{workouts,laps}.csv` per month on XML
trackers, and `longevity/*.md` when the longevity skill is populated
for that person), one level above this Skills repo. The skills resolve
which person a request is about (see each `SKILL.md`'s "Who is this
for?" section) and pass `--person <Name>` to their scripts; path
resolution lives in `shared/person_paths.py`. See
[`PROJECT.md`](PROJECT.md) for sheet format, column semantics, routing
rules, profile / auto-cardio behavior, and backup strategy.
