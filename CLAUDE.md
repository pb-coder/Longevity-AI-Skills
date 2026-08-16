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
or write — there is no xlsx anywhere post-PR3a. That folder is also its
own git repository (see the versioning convention below), so the commit
history is the rollback path when an import or a mis-parsed `/log`
damages a CSV. HealthAutoExport ZIPs drop into the root and are
**deleted after a successful import**; `--keep-export` is the escape
hatch. One cold native `Export.zip` sits at `<root>/archive/` from
before the migration; no code reads it.

```
<root>/
├── <Person>/
│   └── data/                              # its own git repo — one commit per confirmed write
│       ├── health_metrics.csv             # date-keyed, sparse-merge, 22 cols
│       ├── workout_sessions.csv           # (date,start)-keyed
│       ├── profile.csv                    # key,value (source, auto_cardio, birthday, swim CSS)
│       ├── monthly/                       # one CSV per YYYY.MM
│       │   ├── 2026.05.csv                # 18-col schema, ASC by (Date,#,Set)
│       │   ├── 2026.04.csv
│       │   └── …                          # canonicalize rebuilds TOTAL rows + computed cells
│       ├── swimming/                      # per-workout swim aggregates
│       │   ├── 2026.05.workouts.csv       # per-month swim aggregates, (date,start)-keyed
│       │   ├── 2026.05.laps.csv           # XML-era per-lap detail; frozen history, never written now
│       │   └── …
│       ├── sleep/                         # HealthAutoExport sleep nights
│       │   ├── 2026.05.nights.csv         # per-night, date-keyed; all 6 stages + Time in Bed + Efficiency + first/last segment clock times (N Segments permanently blank)
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
                      # list_swim_workout_months(person), list_swim_lap_months(person)
                      # — the two lap resolvers serve the frozen XML-era lap
                      # files; nothing writes them any more.
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
                      # bounds importer writes; --allow-past-months is the
                      # explicit backfill path for cardio and TOTAL metadata.
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
  import_health_auto_export.py
                          # The only importer. Handles `HealthAutoExport*.zip`
                          # and dispatches on the archive member: a
                          # `HealthAutoExport-*.json` member selects the JSON
                          # reader (the supported format); anything else falls
                          # back to the legacy CSV reader with a deprecation
                          # warning. Route GPX members are ignored. Writes the
                          # full tracker surface: per-day Health Metrics
                          # (VO2max, RHR, HRV, walking HR, wrist temp,
                          # breathing disturbances, exercise minutes, steps,
                          # active/basal energy, body composition), per-night
                          # sleep architecture, per-workout Workout Sessions
                          # rows (avg/max/min HR, calories, distance), and
                          # per-workout swim aggregates. Bootstraps
                          # profile.csv with source=health_auto_export,
                          # auto_cardio=true. When auto_cardio is on, also
                          # appends matching cardio workouts (Run / Hike /
                          # Cycle / Swim / HIIT) to the YYYY.MM monthly sheet
                          # via upsert_monthly_cardio. Idempotent; sparse-merge
                          # upserts never overwrite populated cells with None.
                          # --replace-range clears old machine-imported rows
                          # in the selected date range before writing.
                          # Deletes the consumed ZIP on success, then commits
                          # the person's data/ repo (`import: <zip name>`).
                          # Usage: python3 shared/import_health_auto_export.py
                          #          --person <Person> [--zip PATH_OR_GLOB]
                          #          [--since YYYY-MM-DD] [--until YYYY-MM-DD]
                          #          [--allow-past-months] [--replace-range]
                          #          [--dry-run] [--keep-export]
  health_units.py         # Source-agnostic unit conversion and plausibility
                          # gating: PLAUSIBLE_RANGES, convert_unit,
                          # plausible_or_none, normalize_body_fat_pct, plus the
                          # timestamp helper hhmm. The one
                          # place a measurement's meaning is decided, so an
                          # uninterpretable unit drops in exactly one function.
  strength_sessions.py    # Strength-session clustering (same-day workouts →
                          # one session) for monthly TOTAL-row metadata.
                          # Reads the date / start / apple_type keys the
                          # importer payload and the sessions store share.
  data_git.py             # commit_data(person, message) -> short SHA | None.
                          # Each person's data/ directory is its own git repo;
                          # every confirmed write commits it. Two call sites:
                          # append_workout.py (`log: <N> rows, <dates>`) and
                          # import_health_auto_export.py (`import: <zip name>`).
                          # One operation is one commit, not one per file.
                          # Never raises — a git failure warns and returns
                          # None, because a broken git state must not fail a
                          # workout log. Never runs `git gc` (see the
                          # versioning convention).
  apple_workout_types.py  # Single source of truth for Apple's workout-type
                          # enum, which HealthAutoExport's workout names still
                          # map onto: rawValue → canonical name
                          # (RAWVALUE_TO_TYPE), the auto-cardio eligibility set
                          # (CARDIO_AUTOLOG_TYPES — Running / Hiking / Cycling
                          # / Swimming / HIIT), and the canonical →
                          # tracker-exercise-name map (APPLE_TO_TRACKER_EXERCISE
                          # → Outdoor Run / Hike / Outdoor Cycling / Swim /
                          # HIIT). Append-only as new workouts are encountered.
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
                      # Single writer for the monthly CSV side. Commits the
                      # person's data/ repo once per run, after the write is
                      # confirmed (`log: <N> rows, <dates>`).
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
                      #   - swim_summary (only when there are swims in the
                      #     last 28 days): totals, avg pace per 100m, avg SPL,
                      #     per-session CSS-zone classification, CSS retest
                      #     prompt, inferred CSS test detection. The SWOLF and
                      #     stroke-mix fields degrade to null on rows imported
                      #     since the per-lap payload went away.
                      #   - recovery: 0-10 score from HRV / RHR / sleep /
                      #     wrist temp deviations, with named drivers.
                      #     training_load: CTL/ATL/TSB rolling EWMA from per-
                      #     session TRIMP. hr_at_volume_divergence: per-muscle
                      #     fatigue flag from HR creep at constant volume.
                      #   - bodyweight_latest + trend
                      #   - daily_activity_28d (NEAT; steps_daily_avg is the
                      #     primary basis for the low/moderate/high band,
                      #     exercise minutes secondary — assessment_basis says
                      #     which) and energy_28d (daily TDEE with its active /
                      #     basal split + per-week trends; absent, not zeroed,
                      #     when no energy rows fall in the window). The
                      #     nutrition_phase block carries an `energy` sub-block
                      #     whose implied intake is a prescription derived from
                      #     that measurement — nothing here logs intake.
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
  `Source` column. `Source` values are `manual` or an importer identity:
  `apple[@HH:MM[:SS]]` / `gymkit:<Device>[@HH:MM[:SS]]` — the `gymkit:`
  form only ever appears on rows imported before the migration, since
  HealthAutoExport carries no device identity, but readers must still
  parse it. The optional time suffix is deliberate row identity for
  same-day same-type imported cardio workouts; consumers must parse the
  prefix before comparing.
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
  `workout_coach/lib/__init__.py` uses `__path__` to map the underscore
  Python package onto the hyphenated on-disk directory
  `workout-coach/lib/`. Add new coach modules to `workout-coach/lib/`
  as before; they become importable as `workout_coach.lib.<name>`
  automatically. Do not duplicate them under `workout_coach/lib/`.
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
  `SESSION` is display-only and intentionally ephemeral: inserting an
  earlier-dated workout renumbers later sessions in that month. Never
  use it as a stable external ID. It is date-keyed, not modality-keyed:
  strength and auto-cardio rows on the same date may share one `SESSION`
  number, while `read_tracker.py` emits separate `monthly_sessions`
  entries keyed by `(date, session_kind)`.
- **Computed cells are pre-evaluated on canonicalize.** `Volume =
  reps × kg`, `Pace = duration/distance` (MM:SS, blank outside
  [0.5, 60] min/km), and per-month SESSION counters are written as
  literal values, not Excel formulas. The user can preview the CSV in
  macOS Quick Look or Numbers and see the math directly. No xlsx
  exists post-PR3a; the CSV is the canonical store.
- **Distance is unit-aware end-to-end.** HealthAutoExport bakes the
  phone's in-app unit preference into its output, and its unit strings
  are not always honest (`lapLength` is labelled `m` and carries
  kilometres). Every numeric read off a workout therefore goes through
  `_qty(..., expect_units=…)`, which drops and warns on an unexpected
  unit rather than guessing, and every daily-metric conversion goes
  through `health_units.convert_unit`. Never read a raw `qty` without
  naming the unit you expect. The `_format_pace_min_per_km` helper
  blanks pace values outside `[0.5, 60]` min/km — degenerate `0:01`
  outputs from a future unit bug surface as a blank cell instead of
  silent corruption.
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
- **`health_metrics.csv` is 22 columns and grows before `Notes`.** New
  daily columns are appended immediately before `Notes`, the precedent
  the `Source` column set on the monthly CSV: most recently `Steps`,
  `Active Energy (kcal)`, `Basal Energy (kcal)` (payload fields `steps`,
  `active_energy_kcal`, `basal_energy_kcal`), after the body-composition
  three. Nothing reads this file positionally outside `csv_store_dense`
  — every column resolves by header *name* — so a file still carrying an
  older header keeps parsing, its missing fields read as None, and the
  row pads to blank and self-migrates on the next write. **Store the two
  energy components, not their sum.** TDEE is trivially derived from
  them, but the split carries what the sum destroys: active energy is a
  training-load signal, and basal energy trending down during a cut is
  adaptive thermogenesis — the most useful thing this data tells a
  cutting athlete, and invisible in the total.
- **One health source: HealthAutoExport.** Each person's
  `data/profile.csv` pins `source` (only `health_auto_export` is
  accepted) and `auto_cardio` (bool). `DEFAULT_DATA_SOURCE` is
  `health_auto_export`, and `SOURCE_CAPABILITIES`
  (`workout-coach/lib/constants.py`) and the `csv_store_dense.py`
  schema each hold that single entry. Both keep their per-source *shape*
  — the coach payload publishes `capabilities` as a contract and a
  second source may return one day — but nothing may reintroduce a
  second key without a documented migration.
  `import_health_auto_export.py` handles `HealthAutoExport*.zip` and
  dispatches on the archive member, not on the filename: a
  `HealthAutoExport-*.json` member selects the JSON reader; anything
  else falls back to the legacy CSV reader with a deprecation warning.
  Route GPX members are ignored. **JSON is the format going forward**:
  its metric and workout names are canonical English even on a localised
  phone, and it carries the per-night `sleepStart` / `sleepEnd`
  timestamps the Sleep Regularity Index needs — which is why
  `sleep_regularity` is a True capability. The CSV reader is kept alive
  only until the second tracker's phone settings switch to JSON, then it
  goes. /coach gates report sections on `capabilities` and on data
  presence. `auto_cardio` defaults to true; when on, eligible Apple
  workouts (Running / Hiking / Cycling / Swimming / HIIT) flow into the
  matching `monthly/YYYY.MM.csv`, with manual-wins dedupe (date +
  exercise, ±1min duration tolerance). When the current-month gate skips
  historical rows, importer stdout prints a per-month and per-exercise
  breakdown plus the `--allow-past-months` rerun hint.
- **What this source permanently cannot give.** Record these as closed,
  not pending: Apple's 1-10 workout effort score (`metadata` is empty on
  every JSON workout, so the coach's "no RIR/RPE intake" caveat is
  permanent and no amount of re-export fixes it); beat-to-beat intervals
  and therefore RMSSD (HRV arrives as an SDNN scalar only);
  heart-rate motion context; ECG recordings; swim stroke style and
  SWOLF; and Apple's own HR-zone boundaries, which were the one
  independent read on max HR — `estimated_max_hr` still derives from
  `workout_sessions.csv` Max HR, which this source populates, so no
  HRR / TRIMP / Karvonen math is affected. Do not write code, prompts,
  or caveats that imply any of these is coming back.
- **Every person's `data/` directory is its own git repository, and the
  history is the rollback path.** `shared/data_git.py::commit_data`
  stages and commits the whole directory after every confirmed write —
  `/log` via `append_workout.py` (`log: <N> rows, <dates>`) and the
  importer (`import: <zip name>`). One operation is one commit, never
  one per touched CSV, so a bad `/log` or a bad import reverts as a
  single entry. Commit *after* the write is confirmed, and never let git
  decide whether a write succeeded: `commit_data` catches everything,
  warns, and returns `None`, because losing the history of a write is an
  annoyance and losing the write is not acceptable. New write paths get
  the same treatment — add the call at the end of the operation, not
  inside the store.
  **These repos live inside iCloud Drive** — as does this one. iCloud
  syncs `.git` like any other folder, so two machines writing at once can
  interleave objects and refs: operate a tracker from **one machine at a
  time**. That one cannot be enforced in code. What is enforced:
  **never run `git gc` or any repack automatically** — repacking
  rewrites many objects at once and is the operation most likely to lose
  a race with sync — and both `Skills/.gitignore` and the `.gitignore`
  written into each data repo at init cover `.DS_Store` plus the iCloud
  conflict-copy patterns (`* [0-9].*` and friends), so a `file 2.csv`
  sync artifact never lands in a commit and never becomes the file a
  later read picks up.
- **Coach plan output is split into a dated HTML dashboard + a lean
  workout markdown, both under `plans/<Person>/`.** Each `/coach` run
  writes two paired files: `plans/<Person>/<YYYY-MM-DD>-assessment.html`
  (self-contained: inline CSS / SVG / JS, no CDN, renders identically
  offline) and `plans/<Person>/<YYYY-MM-DD>-workout.md` (bullets only,
  no tables, sparse sub-bullet notes — 0-2 per workout, never rationale
  or "last time X" history). The dashboard carries the full assessment
  (recovery score + drivers, TSB curve over 90 days, per-muscle volume
  bars, activity rings, sleep, strength progression, HRV / RHR / wrist
  temp / VO2max / bodyweight sparklines, the `trajectory_energy` card
  (measured TDEE with its active / basal split, gated on `energy_28d`),
  recovery practices including cold-air outdoor temperature when
  present, week-over-week comparison)
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
  pattern. HealthAutoExport's per-night document is the source: stage
  durations plus the `sleepStart` / `sleepEnd` timestamps that fill
  First/Last Segment. Headline fields (Sleep Total / Deep / REM /
  Time in Bed) are also mirrored to `health_metrics.csv` so the
  existing recovery_score path reads them without a join.
  `csv_store.read_sleep_nights` aggregates across all months on read;
  `upsert_sleep_nights` is sparse-merge by date with manual-wins on
  Notes — Sleep Efficiency is auto-derived when both Total and
  Time in Bed are present and `efficiency_pct` wasn't supplied
  explicitly. The clock-time fields are importer-only (manual /log
  entries leave them blank). **`N Segments` is permanently blank**: the
  source reports one aggregate row per night with no segment breakdown.
  `sleep_summary`'s fragmentation reader must degrade to null there and
  say nothing — a night that stopped carrying a segment count did not
  become less fragmented. Segment-level detail is not stored anywhere,
  and there is no archive to re-extract it from, so hypnograms and
  sleep-latency derivation are off the table rather than deferred.
- **Thermal (sauna + cold exposure) lives in `<Person>/data/thermal/YYYY.MM.sessions.csv`, per-month.**
  Per-session aggregates: Date, Start, Heat Type (`dry` / `steam` /
  `infrared` / `banya` / `none`), Heat Temp (°C), Heat Rounds, Heat
  Round Durations (min) (comma-separated per-round minutes for
  multi-round saunas), Heat Total (min) (auto-derived sum), Cold Type
  (`none` / `cold_air` / `cold_shower` / `cold_plunge` / `cold_water`),
  Cold Duration (sec), Cold Temp (°C), Notes. **Manual /log only** —
  Apple Health doesn't classify sauna sessions reliably, so there's no
  importer-side write path; the `thermal/` folder is absent until the
  user logs their first session. Dedupe by
  `(date, start, heat_type, cold_type)`. Blank-start same-shape collisions
  preserve both complete sessions by assigning the later row a synthetic
  `Start` such as `occurrence:2`. A `sauna`
  + `cold` line under the same workout header in one `/log` message
  becomes one row (paired protocol session); standalone cold (morning
  cold shower) is a row with heat columns blank.
  `csv_store.read_thermal_sessions` aggregates across all months on
  read; `upsert_thermal_sessions` is sparse-merge by
  `(date, start, heat_type, cold_type)` with manual-wins on Notes;
  `heat_total_min` and (when absent) `heat_rounds` are auto-derived from `heat_round_durations_min` on
  every write so the file is internally consistent. **Almost never
  prompts** — the one carved-out exception: when the parsed payload
  carries a `cold_air` entry whose `cold_temp_c` is null, `/log` asks
  once for the outdoor temperature before writing (one short question,
  user can answer with a number in °C or `skip`). The export *does*
  carry ambient `temperature` and `humidity` per workout, but a
  standalone sauna or cold-air session is not a workout, so no workout
  record exists to carry its ambient temperature — the datum can only
  come from the user, and a `cold_air` session at −5°C is a
  fundamentally different stimulus than one at 25°C. All other thermal
  fields stay absent-≡-didn't-happen. `/coach`'s `thermal_summary`
  block reads this and reports frequency / dose against the
  HSP-induction threshold (≥20min @ ≥80°C, Laukkanen + mechanistic
  consensus); the cold side carries per-session `cold_temp_c` plus a
  `dose_hint: "amber"` when `cold_air >= 18°C` (adaptation evidence
  thin above that). The target defaults to 4×/wk and can be overridden
  via `profile.csv` `sauna_target_per_week`. Treat that target as
  user-configured reachability, not a universal obligation; below-target
  means "below the configured target."
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
  induction; stay in protocol-adherence language against the configured
  target.
- **Swim metrics live in `<Person>/data/swimming/`, split per month.**
  Per-workout aggregates (Distance, Pool Length, Laps, Strokes, SPL,
  Avg SWOLF, Stroke Mix, Location, Water Temp) on `YYYY.MM.workouts.csv`,
  mirroring the `monthly/YYYY.MM.csv` pattern so the swim store scales
  with usage. The importer writes those aggregates on every run; Laps is
  derived as `distance / pool length` and SPL as `strokes / laps`, since
  neither is exposed directly. **Per-lap detail is gone permanently** —
  it was read off Apple's lap events and this source has no lap payload —
  so `swimming/*.laps.csv` is no longer written at all (an empty lap file
  would read as "this swim had no laps", which is worse than an absent
  one), and `Avg SWOLF` / `Stroke Mix` stay blank on new rows. Both are
  per-lap quantities. Existing XML-era rows keep the values they already
  have; sparse-merge does not blank them. Say "per-lap detail and SWOLF
  are unavailable", never "swim data is unavailable" — the workout-level
  aggregates are there, and `/coach` renders the swim section whenever
  `swim_summary` is present (it gates on swims in the 28-day window, not
  on laps). `csv_store.read_swim_workouts` / `read_swim_laps` aggregate
  across all months on read and `upsert_swim_laps` still exists for the
  frozen files; `upsert_swim_workouts` routes entries to the correct
  month by date. Stroke style enum → string map lives in
  `apple_workout_types.HK_SWIMMING_STROKE_STYLE` (0=Unknown, 1=Mixed,
  2=Freestyle, 3=Backstroke, 4=Breaststroke, 5=Butterfly, 6=Kickboard);
  nothing populates it on new rows. Nearby same-day swims with a short
  gap are reported but kept as separate workouts; merging them requires
  explicit user intent.
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
  from the HealthAutoExport importer into health_metrics.csv and the
  longevity skill reads them on demand via the coach's
  `read_tracker.py`.
- **CSS (Critical Swim Speed)** lives on `profile.csv`:
  `swim_css_sec_per_100m`, `swim_css_set_at`, plus
  `swim_pool_length_default` for the workout whose exported `lapLength`
  is missing or unusable. CSS test workflow: log a 400m + 200m TT same-session
  with `CSS test` on the header line; the logger computes
  `(t400_sec − t200_sec) / 2` (sec/100m) and writes both fields.
  `/coach` prompts a retest after 8 weeks. Detection is never
  automatic — only the explicit `CSS test` keyword writes CSS.

## Workout Tracker

Each tracker lives in its own per-person folder
(`<root>/<Person>/data/` containing `health_metrics.csv`,
`workout_sessions.csv`, `profile.csv`, `monthly/YYYY.MM.csv` per
month, `swimming/YYYY.MM.workouts.csv` per month once a swim is
imported, and `longevity/*.md` when the longevity skill is populated
for that person), one level above this Skills repo. That folder is a
git repo in its own right; the Skills repo never contains it. The
skills resolve which person a request is about (see each `SKILL.md`'s
"Who is this for?" section) and pass `--person <Name>` to their
scripts; path resolution lives in `shared/person_paths.py`. See
[`PROJECT.md`](PROJECT.md) for sheet format, column semantics, routing
rules, profile / auto-cardio behavior, and rollback strategy.
