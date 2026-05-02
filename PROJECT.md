# Workout Tracker

Hypertrophy + longevity training logs for Nihad (account owner) and his boyfriend Fabian (28), who share the same goals and conventions. Used with a set of Claude skills.

## Files

Two parallel trackers live in this directory, one per person:

- `Workout Tracker - Nihad.xlsx`
- `Workout Tracker - Fabian.xlsx`

Each has the same sheet structure: `Exercises Database` (catalog, muscle → pattern) first, then `Profile` (per-person source profile, see below), then `Bodyweight`, `Health Metrics`, `Workout Sessions`, then monthly sheets named `YYYY.MM` newest → oldest. The `Exercises Database` tab in each file is **mirrored from the canonical markdown** at `Skills/shared/exercises-database.md` via `Skills/shared/sync_db_sheet.py` — edit the markdown, run the sync, both files stay in lockstep. The catalog includes WARMUP, all strength sections, CARDIO (Hike, Swim, Walk, Outdoor Run, Outdoor Cycling, HIIT + indoor machines), and WELLNESS (Yoga, Stretching), so non-strength activities log without "(not in database)" warnings.

`Health Metrics` and `Workout Sessions` are populated by one of two importers, dispatched by file extension. **Apple's native zipped XML export** (`Export.zip` / `Export - <Person>.zip`) flows through `Skills/shared/import_apple_health.py`, which streams the XML and writes per-day aggregates (VO2max, RHR, HRV, sleep stages, wrist temp, exercise minutes, BodyMass) and per-workout rows with avg/max/min HR. **HLExport text dumps** (`health_export_<timestamp>.txt`, from the HLExport iOS app) flow through `Skills/shared/import_hl_export.py`, which line-parses the same fields HL provides — VO2max, HR Recovery, total sleep (stitched from `Sleep: Asleep` / `Awake` events), respiratory rate, bodyweight, workout duration / calories / distance. HL has no HRV, no wrist temp, no per-workout HR, no sleep stages by design. Both importers are idempotent; sparse-merge protects existing values, so switching a tracker between sources is non-destructive.

### Per-person source profile

Each tracker xlsx has a `Profile` sheet (key/value layout) that pins three things:

| Key | Meaning | Default |
|---|---|---|
| `source` | `xml` (Apple zipped XML) or `hl_export` (HLExport text) | inferred from the first import's file extension |
| `auto_cardio` | If true, Apple-recorded cardio workouts (Run / Hike / Cycle / Swim / HIIT) auto-flow into the matching `YYYY.MM` monthly sheet | `true` for XML, `false` for HL |
| `birthday` | YYYY-MM-DD of birth. Used by `/coach` to compute age dynamically for the max-HR fallback formula (Tanaka 208 − 0.7×age) when Apple per-workout HR isn't observable | unset → coach uses age 30 fallback |

`/coach` reads `Profile.source` to decide which sections of its report to write — HRV / wrist temp / per-workout-HR sections are gated on the matching capability flags. For HL users, the coach skips those sections entirely rather than printing "not enough data yet." The profile is bootstrapped on first import; manual override is supported by editing `Profile!B2` directly.

### Auto-cardio (Apple → monthly sheet)

When `Profile.auto_cardio` is true, every Apple-recorded workout in `CARDIO_AUTOLOG_TYPES` (Running, Hiking, Cycling, Swimming, HighIntensityIntervalTraining) gets appended to the matching `YYYY.MM` monthly sheet as a cardio row tagged `auto-imported from Apple`. Walks and indoor strength sessions are excluded — incidental walks would dominate, and Apple doesn't capture sets for strength. **Manual entries always win**: a cardio row with the same `(date, exercise, duration ±1 min)` as an existing manual row is never duplicated, and a previously auto-imported row is a no-op on re-runs (idempotent).

**Current-month gate.** The importers only ever write into the current calendar month's `YYYY.MM` sheet. Past months are "finished" and never re-scanned, so a cardio row the user deletes from `2026.02` stays deleted on the next import — no separate tombstone bookkeeping needed. The strength-session metadata writer follows the same rule: workouts dated outside the current month are silently skipped. (This replaced a previous `Tombstones` sheet + `auto_cardio_since` profile cell in 2026-05; both are now gone.)

Per-person sidecars produced by the skills follow the same `<base> - <Person>.<ext>` pattern:

- `workout_plan - <Person>.md` (written by `/coach`)
- `Workout Tracker - <Person>.maintain-backup.xlsx` (written by `/maintain`)

## Routing (who is a message about?)

Every skill invocation must resolve a person before touching a file:

- If the user names a person ("log Fabian's push day", "coach Nihad"), use that tracker.
- If the user uses pronouns or context that clearly refer to one person ("my bf" / "boyfriend" → Fabian; "I" / "me" / "my" with no other person mentioned → Nihad, since Nihad is the account owner), use that tracker.
- Otherwise ask: **"Is this for Nihad or Fabian?"** before running.

Never mix data across trackers in a single skill run.

## Monthly sheet format

Columns (A–Q, 17 cols): `SESSION | Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR | Active Cal | Total Cal | Elevation (m) | Elapsed`.

Each set is one row. Date, #, and Exercise are populated on every row (no carry-forward shorthand). `#` restarts at 1 per date and is shared by all sets of the same exercise. Cardio rows use the cardio columns (Distance through Elapsed); strength rows leave them blank.

`SESSION` is a per-month session number (1, 2, 3…) merged vertically across every row of the same date — including that session's trailing TOTAL row. It's populated by the styler, not by hand.

**TOTAL row carries the strength session's full session-level summary.** Each strength session ends with a `TOTAL` row that holds:
- `Date` (col 2) — the session date.
- `Volume` (col 8) — `=SUM(H{first}:H{last})` formula over the set rows.
- `Notes` (col 9) — `Deload Workout` marker when applicable. Hoisted there by the styler from any data row that had the marker (legacy /log convention put it on the warmup row).
- `Duration (min)` (col 11) — strength block's total active minutes (MM:SS).
- `Avg HR` (col 13) — duration-weighted across the strength workout cluster.
- `Active Cal` / `Total Cal` (cols 14–15) — sum across the strength cluster.
- `Elevation (m)` (col 16) — usually blank for indoor strength.
- `Elapsed` (col 17) — wall-clock time (H:MM:SS or MM:SS).

The session's data rows (warmup + working sets) hold per-set data only; their cols 11/13/14-17 are blank. Cardio-only days have no TOTAL row — each cardio row carries its own per-row metadata directly. Apple-Watch session metadata is written to the TOTAL row by `import_apple_health.upsert_monthly_strength_session` (XML, full payload) and `import_hl_export` (HL, Active Cal + Duration only). Manual `/log` doesn't write the metadata fields — the importers fill them post-hoc on the matching session.

Every set row's Volume cell is the formula `=reps*kg` — don't write numeric volumes.

## Skills

Skill source lives in [pb-coder/Skills](https://github.com/pb-coder/Skills), cloned locally at `Skills/`. Edit the unzipped source there and commit changes. See `Skills/CLAUDE.md` for the repo layout.

- `/coach` — reads the tracker, reports on training state, and generates new workout plans (`Skills/workout-coach/`). Each strength workout in the output has a `**Date:** ___________` placeholder under its heading; fill it in when you train so the date is visible when you later `/log` the session. The script (`scripts/read_tracker.py`) emits compact JSON by default with the per-set `rows` array gated behind `--include-rows`; the report sections shown to the user are gated on the per-tracker `capabilities` (so HL users don't see Recovery / per-workout-HR sections their data source can't fill).
- `/log` — append a workout to the current monthly sheet (`Skills/workout-logger/`). Safe to backfill past dates — monthly sheets self-sort on every append, and non-contiguous same-date blocks merge back into one session automatically. After every run, the logger asks once whether to refresh Apple Health data; on confirm it dispatches `import_apple_health.py` for `.zip` exports or `import_hl_export.py` for `.txt` exports based on what's in the working directory.
- `/maintain` — end-of-month cleanup: restyle, trim, reorder, verify (`Skills/workout-tracker-maintenance/`). Run on the 1st of each month or whenever the sheet looks messy. Sheet ordering produced by a clean run: `Exercises Database → Profile → Bodyweight → Health Metrics → Workout Sessions → YYYY.MM (newest → oldest)`.

## Conventions

- Exercise names use title case (`Dumbbell Flat Bench Press`, not `dumbbell flat bench press`). Compare case-insensitively when matching across sessions.
- Cable machine weights increment in 5kg steps.
- New exercises get added to the canonical markdown at `Skills/shared/exercises-database.md` under the appropriate muscle → pattern section, then synced into both xlsx files with `python3 Skills/shared/sync_db_sheet.py "Workout Tracker - <Person>.xlsx"`. Don't edit the xlsx "Exercises Database" tab by hand — `/coach` reads only the markdown, so a hand-added xlsx row is invisible to the volume model and gets overwritten on the next sync. Plurals, synonyms, and old typo'd names go in `Skills/workout-logger/references/aliases.md` so `/log` auto-canonicalizes them.
- Past monthly sheets that contain old typo'd exercise names (e.g. "Deadhang", "Dips", "Stomach Press*") can be cleaned up retroactively with `python3 Skills/shared/canonicalize_logs.py "Workout Tracker - <Person>.xlsx"`. The script renames typos to canonical names, strips stale "(not in database)" notes, and prints any ambiguous names (e.g. bare "Leg Curl") for manual decision rather than guessing.
- **Bodyweight is opt-in.** `/log` no longer prompts. Include a line like `weight 76.5` (or `bw 76.5`, `bodyweight: 76.5`) in the `/log` message to record a morning weight for that session's date. The standing convention is morning / empty-stomach; only annotate if the context differs (e.g. `weight 77.1 after dinner`).
- **Apple Health import.** `/log` offers to refresh on every run via an `AskUserQuestion` prompt — pick "Refresh now" or "Skip"; the prompt always fires. The logger resolves the export file in this priority order: (1) `./Export - <Person>.zip` (Apple zipped XML, per-person), (2) `./Export.zip` (single-user fallback), (3) `./health_export_*.txt` (HLExport text dump — most recent by mtime; the user drops one fresh file at a time without renaming). Dispatch is by extension: `.zip` → `import_apple_health.py`, `.txt` → `import_hl_export.py`. Re-runs are idempotent; sparse-merge upserts protect existing data, so switching a tracker between sources is non-destructive. If the resolved file's source disagrees with the tracker's `Profile.source`, the logger asks once before importing.

## Backups

This directory is in iCloud, so both tracker xlsx files are continuously backed up — no manual `.backup*.xlsx` copies needed. `/maintain` still writes a per-run `Workout Tracker - <Person>.maintain-backup.xlsx` alongside whichever tracker it touched, as a safety net; delete it once you've confirmed the run looks good.
