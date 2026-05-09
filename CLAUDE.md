# Skills

Source for the Claude Code skills used by pb-coder. Cloned from
[`pb-coder/Skills`](https://github.com/pb-coder/Skills); edit here and push.

## Layout

Per-person directories sit at the workout-tracker root: `Nihad/`,
`Fabian/`. Each holds a `data/` folder with every CSV the skills read
or write — there is no xlsx anywhere post-PR3a. Apple Health exports
drop into the root and get **archived to `<root>/.processed/`** after a
successful import — the CSVs are the persistent record; the archive
keeps a forensic trail in case a downstream bug damages the CSVs.

```
<root>/
├── Nihad/
│   └── data/
│       ├── health_metrics.csv           # date-keyed, sparse-merge
│       ├── workout_sessions.csv         # (date,start)-keyed
│       ├── profile.csv                  # key,value (source, auto_cardio, birthday, swim CSS)
│       ├── monthly/                     # one CSV per YYYY.MM
│       │   ├── 2026.05.csv              # 18-col schema, ASC by (Date,#,Set)
│       │   ├── 2026.04.csv
│       │   └── …                        # canonicalize rebuilds TOTAL rows + computed cells
│       └── swimming/                    # XML-only; absent on HL trackers
│           ├── swim_workouts.csv        # per-swim aggregates, (date,start)-keyed
│           └── swim_laps.csv            # per-lap detail, (date,workout_start,lap_num)-keyed
├── Fabian/                              # same shape (no swimming/ for HL)
└── Skills/
    └── shared/
        └── exercises-database.md        # canonical catalog (markdown is truth)

shared/               # Code + docs imported by multiple skills
  person_paths.py     # Path resolver. data_dir(person),
                      # health_metrics_csv(person), workout_sessions_csv(person),
                      # profile_csv(person), monthly_dir(person),
                      # monthly_csv(person, ym), swim_workouts_csv(person),
                      # swim_laps_csv(person). Every script accepts
                      # `--person <Name>` and resolves the rest from there.
  csv_store.py        # CSV-backed store for the dense data. Same functional
                      # surface as the old xlsx upserts: read_health_metrics,
                      # upsert_health_metrics (sparse-merge, schema-by-source),
                      # read_workout_sessions, upsert_workout_sessions
                      # (dedupe by date+start), read_profile, write_profile,
                      # ensure_profile. HEALTH_METRICS_HEADERS_BY_SOURCE and
                      # WORKOUT_SESSIONS_HEADERS_BY_SOURCE are the schema
                      # constants. Atomic writes via tmp + rename.
  monthly_csv.py      # Per-month CSV reader / writer / canonicalizer.
                      # Replaces the old tracker_sheet.py xlsx authority.
                      # MONTHLY_HEADERS / MONTHLY_FIELDS / TOTAL_LABEL /
                      # DELOAD_MARKER_TEXT constants; coercions (date_str,
                      # _numeric_cell, _parse_duration_minutes,
                      # _format_pace_min_per_km, _format_duration_mmss,
                      # _format_elapsed_hms); read_monthly(person, ym),
                      # upsert_rows(person, ym, rows),
                      # upsert_monthly_cardio (manual-wins dedupe +
                      # Matrix/GymKit overlap filtering),
                      # upsert_monthly_strength_session (5% drift guard
                      # on TOTAL-row metadata),
                      # canonicalize_monthly_csv (sort + recompute Volume
                      # / Pace / Total Cal / SESSION + rebuild TOTAL rows
                      # + hoist deload markers — pure-CSV equivalent of
                      # the old style_monthly_sheet). Current-month gate
                      # (_current_month_key) bounds where importers can
                      # write; past months are "finished". Idempotent.
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
                        # Usage: python3 shared/canonicalize_logs.py --person Nihad
  import_apple_health.py  # Apple Health zipped XML importer (Nihad). Streams
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
                          #          --person Nihad [--since YYYY-MM-DD]
                          #          [--dry-run] [--keep-export]
  import_hl_export.py     # HLExport text dump importer (Fabian). Same upsert
                          # pipeline as import_apple_health.py, but parses
                          # line-event text instead of XML. Lighter feature
                          # surface — VO2max, HR Recovery, total sleep
                          # (stitched from Sleep: Asleep/Awake events),
                          # respiratory rate, bodyweight, workout duration /
                          # cal / distance. No HRV, wrist temp, per-workout
                          # HR, or sleep stages — those depend on Apple
                          # watch-side aggregation HL doesn't replicate.
                          # Bootstraps profile.csv with source=hl_export,
                          # auto_cardio=true. HL workout records (Hike,
                          # Outdoor Run, Outdoor Cycling, Swim, HIIT) have
                          # proven reliable; flip auto_cardio=false on a
                          # per-tracker basis if manual-only logging is
                          # preferred. Deletes the export txt on success.
                          # Usage: python3 shared/import_hl_export.py
                          #          --person Fabian [--txt PATH_OR_GLOB]
                          #          [--since YYYY-MM-DD] [--dry-run]
                          #          [--keep-export]
  apple_workout_types.py  # Single source of truth for Apple's workout-type
                          # enum: rawValue → canonical name (RAWVALUE_TO_TYPE),
                          # the auto-cardio eligibility set
                          # (CARDIO_AUTOLOG_TYPES — Running / Hiking / Cycling
                          # / Swimming / HIIT), and the canonical →
                          # tracker-exercise-name map (APPLE_TO_TRACKER_EXERCISE
                          # → Outdoor Run / Hike / Outdoor Cycling / Swim /
                          # HIIT). Append-only as new workouts are encountered;
                          # used by both importers.

workout-logger/       # /log — append a parsed workout to the tracker.
  SKILL.md            # Agent entry point.
  scripts/
    append_workout.py # Routes rows to YYYY.MM sheets, upserts bodyweight,
                      # applies the styler. Single writer.
  references/         # aliases.md, parsing-rules.md, common-mistakes.md

workout-coach/        # /coach — read tracker, report, plan next workout.
  SKILL.md
  lib/                # Internal analytics modules (not directly invoked).
                      # Each is a flat top-level script, sys.path-importable
                      # both from the entry point and in isolation.
                      #   constants.py — capabilities, landmarks, aliases.
                      #   parsing.py   — coercions + _parse_iso_date + _compact.
                      #   extract.py   — CSV readers (monthly + dense + swim),
                      #                  exercises-DB parser, age + max-HR helpers.
                      #   sessions.py  — build_monthly_sessions + bodyweight
                      #                  trend + progression_summary.
                      #   strength.py  — volume, e1RM, stale, HR-at-volume
                      #                  divergence, strength-session HR trend.
                      #   cardio.py    — cardio rollups, HR zones, TRIMP,
                      #                  CTL/ATL/TSB, daily activity (NEAT),
                      #                  auto_deload_candidates.
                      #   health.py    — health time-series helpers (window,
                      #                  baseline, trend), weekly aggregates,
                      #                  recovery_score (composes ~9 drivers).
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
                      #     last 28 days; HL trackers omit it entirely):
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

workout-tracker-maintenance/   # /maintain — end-of-month cleanup.
  SKILL.md
  scripts/maintain.py # Restyle, trim, reorder, verify.

longevity-optimizer/  # /longevity — separate domain (not workout-tracker).
```

## Conventions

- **Python scripts** live under `scripts/` per skill and are invoked by the
  agent via Bash. Per-skill internal modules (when a skill outgrows a
  single file) live under `<skill>/lib/` as flat top-level scripts —
  see `workout-coach/lib/` for the canonical example. Each lib module
  self-bootstraps its sibling lib dir onto `sys.path` so it can be
  imported in isolation (REPL, ad-hoc tests).
- **Shared imports**: consumers add `shared/` to `sys.path` via
  `sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))`
  and import from `monthly_csv`, `csv_store`, `person_paths`,
  `apple_workout_types`. Skills that have a `lib/` add their own dir
  alongside it via
  `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))`
  and then `from <module> import …` flat (no package namespace).
- **`canonicalize_monthly_csv` is canonical**: the single source of
  truth for monthly-CSV layout (sort by Date+#+Set, recompute Volume
  and Pace, rebuild SESSION numbering, rebuild TOTAL rows, hoist
  deload markers). Running it twice is a no-op. `/log` calls it
  post-write; `/maintain` calls it on every monthly CSV. An out-of-
  order CSV (e.g. after a backfill) self-heals on the next pass. The
  monthly CSV has 18 columns:
  `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes |
  Distance (km) | Duration (min) | Pace (min/km) | Avg HR | Active Cal |
  Total Cal | Elevation (m) | Elapsed | Laps`. The trailing `Laps`
  column is swim-specific — populated by the Apple importer from
  `HKWorkoutEventTypeLap` event counts and by `/log` when the user
  types `<N> laps` / `<N> lengths` / `<N> Bahnen` on a swim row.
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
  monthly CSV AND `<Person>/data/workout_sessions.csv` AND
  `<Person>/data/swimming/swim_workouts.csv` for Swim rows where
  Distance > 10 km (almost always meters mis-stored as km), divides by
  1000, and recomputes pace. Non-swim outliers are flagged for human
  review but not mutated. Idempotent; safe to re-run.
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
  pins `source` (`xml` / `hl_export`) and `auto_cardio` (bool).
  `import_apple_health.py` handles `.zip` (Apple's native export);
  `import_hl_export.py` handles `health_export_*.txt` (HLExport iOS
  app). The /log skill dispatches by extension; /coach gates report
  sections on `capabilities` so HL users don't see "not enough HRV
  data yet" prompts for metrics their source structurally can't
  provide. `auto_cardio` defaults to true on both sources (XML and
  HL); when on, eligible Apple workouts (Running / Hiking / Cycling /
  Swimming / HIIT) flow into the matching `monthly/YYYY.MM.csv`,
  with manual-wins dedupe (date + exercise, ±1min duration tolerance).
- **Coach plan output includes a per-workout DATE placeholder**: every
  strength workout heading is followed by `**Date:** ___________` on its
  own line so the user can fill in the date when they actually train and
  not lose track when `/log`-ing later.
- **Swim metrics live in `<Person>/data/swimming/`.** Per-workout
  aggregates (Pool Length, Strokes, SPL, Avg SWOLF, Stroke Mix,
  Location, Water Temp) on `swim_workouts.csv`; per-lap detail
  (Stroke, Duration, SWOLF) on `swim_laps.csv`. Apple's lap events
  (`HKWorkoutEventTypeLap`) are the source. The Apple Health XML
  importer populates both on every run; HL doesn't supply lap data,
  so HL trackers leave the CSVs absent (and `/coach` skips the swim
  section). Stroke style enum → string map lives in
  `apple_workout_types.HK_SWIMMING_STROKE_STYLE` (0=Unknown, 1=Mixed,
  2=Freestyle, 3=Backstroke, 4=Breaststroke, 5=Butterfly, 6=Kickboard).
  `csv_store.upsert_swim_laps` is replace-on-match (not sparse-merge):
  re-exports authoritatively replace stored lap data so a corrected
  stroke style flows through cleanly.
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
month, and `swimming/{swim_workouts,swim_laps}.csv` on XML trackers),
one level above this Skills repo. The skills resolve which person a
request is about (see each `SKILL.md`'s "Who is this for?" section)
and pass `--person <Name>` to their scripts; path resolution lives in
`shared/person_paths.py`. See [`PROJECT.md`](PROJECT.md) for sheet
format, column semantics, routing rules, profile / auto-cardio
behavior, and backup strategy.
