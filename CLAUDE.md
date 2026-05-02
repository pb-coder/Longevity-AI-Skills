# Skills

Source for the Claude Code skills used by pb-coder. Cloned from
[`pb-coder/Skills`](https://github.com/pb-coder/Skills); edit here and push.

## Layout

```
shared/               # Code + docs imported by multiple skills
  tracker_sheet.py    # Single authority for the per-person tracker xlsx files:
                      #   layout constants (monthly / Bodyweight / DB / Profile /
                      #   Health Metrics / Workout Sessions), coercions
                      #   (date_str, bw_locate_date, _numeric_cell,
                      #   _parse_duration_minutes), canonical sheet styling
                      #   (style_monthly_sheet, style_bodyweight_sheet,
                      #   style_db_sheet, style_health_metrics_sheet,
                      #   style_workout_sessions_sheet, style_profile_sheet),
                      #   and the upsert helpers used by the importers
                      #   (upsert_health_metrics, upsert_workout_sessions,
                      #   upsert_monthly_cardio with manual-wins dedupe +
                      #   tombstone honoring, upsert_monthly_strength_session).
                      #   Profile helpers (read_profile / write_profile /
                      #   ensure_profile_sheet) and Tombstones helpers
                      #   (read_tombstones / add_tombstone) live here too.
                      #   Profile schema: source, auto_cardio, auto_cardio_since,
                      #   birthday (YYYY-MM-DD — used by /coach for dynamic
                      #   max-HR estimation). Tombstones sheet records
                      #   (date, exercise, reason) that the cardio writer
                      #   filters out — Apple data is immutable, so deletions
                      #   need this tombstone mechanism to stick.
                      #   Idempotent. style_monthly_sheet auto-sorts sessions
                      #   by date ascending and merges non-contiguous same-date
                      #   blocks on every pass.
  exercises-database.md  # Canonical exercise catalog (muscle → pattern →
                         # exercises). Source of truth — the xlsx "Exercises
                         # Database" tab is mirrored from this via
                         # sync_db_sheet.py. Read by /log (name lookup) and
                         # /coach (muscle mapping + tag reading).
  sync_db_sheet.py    # Mirror exercises-database.md → xlsx "Exercises Database"
                      # tab. Idempotent: missing entries are inserted at the
                      # end of their section, new sections appended at the
                      # bottom with a navy header. Run after editing the
                      # markdown so both tracker xlsx files stay in sync.
                      # Usage: python3 shared/sync_db_sheet.py "<tracker>.xlsx"
  canonicalize_logs.py  # One-shot rename map for past monthly sheets. Fixes
                        # historical typo'd exercise names ("Deadhang" → "Dead
                        # Hang", "Dips" → "Dip", "Stomach Press*" →
                        # "Ab Crunch Machine", etc.) and clears stale
                        # "(not in database)" Notes once the exercise is
                        # canonical. Reports ambiguous names (e.g. bare
                        # "Leg Curl") instead of auto-renaming. Re-runnable.
                        # Usage: python3 shared/canonicalize_logs.py "<tracker>.xlsx"
  import_apple_health.py  # Apple Health zipped XML importer (Nihad). Streams
                          # Export.xml with iterparse, writes per-day Health
                          # Metrics (VO2max, RHR, HRV, sleep stages, wrist
                          # temp, exercise minutes, BodyMass) and per-workout
                          # Workout Sessions rows (avg/max/min HR, calories,
                          # distance, source). Bootstraps the Profile sheet
                          # with source=xml, auto_cardio=true. When auto_cardio
                          # is on, also appends matching cardio workouts (Run /
                          # Hike / Cycle / Swim / HIIT) to the YYYY.MM monthly
                          # sheet via upsert_monthly_cardio. Idempotent;
                          # sparse-merge upserts never overwrite populated
                          # cells with None.
                          # Usage: python3 shared/import_apple_health.py
                          #          --zip Export.zip --tracker "<tracker>.xlsx"
  import_hl_export.py     # HLExport text dump importer (Fabian). Same upsert
                          # pipeline as import_apple_health.py, but parses
                          # line-event text instead of XML. Lighter feature
                          # surface — VO2max, HR Recovery, total sleep
                          # (stitched from Sleep: Asleep/Awake events),
                          # respiratory rate, bodyweight, workout duration /
                          # cal / distance. No HRV, wrist temp, per-workout
                          # HR, or sleep stages — those depend on Apple
                          # watch-side aggregation HL doesn't replicate.
                          # Bootstraps Profile with source=hl_export,
                          # auto_cardio=false (flip later via the Profile
                          # sheet once HL workout records are reliable).
                          # Usage: python3 shared/import_hl_export.py
                          #          --txt "./health_export_*.txt"
                          #          --tracker "<tracker>.xlsx"
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
  scripts/
    read_tracker.py   # Emits one JSON blob organised around session-level
                      # signals, not raw arrays. Top blocks:
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
  agent via Bash.
- **Shared imports**: consumers add `shared/` to `sys.path` via
  `sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))`
  and import from `tracker_sheet`.
- **Styler is canonical**: `style_monthly_sheet` is the single source of
  truth for monthly-sheet layout (column widths, fonts, fills, merges,
  SESSION numbering, TOTAL row placement, chronological row order).
  Running it twice is a no-op. `/log` calls it post-write; `/maintain`
  calls it on every sheet. An out-of-order sheet (e.g. after a backfill)
  self-heals on the next pass.
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
  `/log` run. After adding new entries to the markdown, run
  `python3 shared/sync_db_sheet.py "Workout Tracker - <Person>.xlsx"` to
  mirror them into the xlsx "Exercises Database" tab so the user-facing
  catalog reflects the change. Don't add exercises by hand inside the
  xlsx — they'll be silently ignored by `/coach` (which reads only the
  markdown) and overwritten on the next sync.
- **Cardio + wellness logging is supported**: the markdown includes a
  CARDIO section (Hike, Swim, Walk, Outdoor Run, Outdoor Cycling, HIIT
  + indoor machines) and a WELLNESS section (Yoga, Stretching). These
  entries have no muscle tags, so they're logged and counted toward
  `cardio_last_28d` (where applicable) without contributing to the
  weekly hard-set volume model.
- **Multi-source Apple Health**: each tracker xlsx pins a `Profile`
  sheet with `source` (`xml` / `hl_export`) and `auto_cardio` (bool).
  `import_apple_health.py` handles `.zip` (Apple's native export);
  `import_hl_export.py` handles `health_export_*.txt` (HLExport iOS
  app). The /log skill dispatches by extension; /coach gates report
  sections on `capabilities` so HL users don't see "not enough HRV
  data yet" prompts for metrics their source structurally can't
  provide. When `auto_cardio` is true, eligible Apple workouts also
  flow into the matching `YYYY.MM` monthly sheet, with manual-wins
  dedupe (date + exercise, ±1min duration tolerance).
- **Coach plan output includes a per-workout DATE placeholder**: every
  strength workout heading is followed by `**Date:** ___________` on its
  own line so the user can fill in the date when they actually train and
  not lose track when `/log`-ing later.

## Workout Tracker

The tracker xlsx files (`Workout Tracker - <Person>.xlsx`, one per
person) live in the parent directory of this repo, not inside it. The
skills resolve which person a request is about (see each `SKILL.md`'s
"Who is this for?" section) and pass the matching path to their script.
See [`PROJECT.md`](PROJECT.md) for sheet format, column semantics,
routing rules, profile / auto-cardio behavior, and backup strategy.
