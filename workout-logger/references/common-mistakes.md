# Common Mistakes

| Input pattern | Wrong parse | Correct parse |
|---|---|---|
| `bench press 80x8` | Missing equipment variant | Default to Barbell if context ambiguous |
| `3x12 curls` | One set of 312 reps | 3 separate rows, 12 reps each; ask for weight |
| `60lbs x 10` | Logged as 60kg | Convert: 60 ÷ 2.205 = 27kg |
| `farmer walks 40kg 30sec` | reps = 30, duration in Notes | reps = 0, `duration_min = 0.5`, Notes: `per hand` only |
| `(warmup)` after exercise name | Ignored | Notes: `warmup` |
| No date given | Guess today | Ask once |
| `cable rows 3x12 @ 50` | One row with 312 reps | 3 rows, 12 reps, 50kg each |
| `jumping jacks` | "Jumping jacks" (user casing) | "Jumping Jacks" (database casing) |
| `triceps pushdown 40kg x 10` | "Triceps Pushdown" | "Cable Tricep Pushdown" (alias table) |
| `lying leg curl 50kg x 10` | "Lying Leg Curl" | "Leg Curl (Lying)" (alias table) |
| `deadhang 30s` | "Deadhang" (not in database) | "Dead Hang" (alias table) |
| `leg curl 55kg x 10 (seated)` | "Leg Curl" (ambiguous) | "Leg Curl (Seated)" — modifier resolves variant |
| Tracker missing from CWD | Search the filesystem for it | Stop, one-line error: tracker must be in the working directory |
| Date from a brand-new month | Ask the user if it's OK to create the file | Just call the script — it creates the `monthly/YYYY.MM.csv` file with headers if missing |
| Writing a standalone `.xlsx` or markdown table to chat | Claude.ai-era output | The tracker (CSV) itself is the output. Summary line only. |
| `/log 22.04 deload ...` with no deload marker | Session logged normally | Keyword `deload` on the header line sets `Deload Workout` in the first row's notes. Coach reads this for mesocycle math. |
| `plank 45s` → reps=45 | Duration smuggled into reps | `reps=0`, `duration_min=0.75`. Isometric holds belong in the Duration column. |
| `deadhang 30s` (isometric hold) | `reps=30` | `reps=0`, `duration_min=0.5`, canonical name "Dead Hang". |
| Unknown exercise name flagged `(not in database)` without trying fuzzy | Loses a match the model would recognize at a glance | Run the fuzzy-match ladder in `parsing-rules.md`. Only fall through to `(not in database)` when no close canonical name exists. |
| Prompting "Refresh Apple Health? Refresh now / Skip" on every `/log` run | The tracker owner asked for this to stop — the prompt is noise when they drop a fresh export every time | Refresh automatically (no prompt): run the importer for the resolved person, append its summary, finish. If no export exists, surface the importer's one-line error and finish. The only surviving prompt is the source-mismatch guardrail. |
| Importer run against a **CSV-mode** HealthAutoExport export, reported as a successful refresh | `Health Metrics: 0 dates written` at exit 0 reads like a clean no-op, so nobody notices the tracker never moved | The CSV reader is deprecated: it's localised (a German export's column names match nothing) and carries no sleep timestamps, so no Sleep Regularity Index. Treat the `WARN: HealthAutoExport CSV export is deprecated` line as a failure — tell the user to switch the app to JSON (hourly metrics, per-minute workouts, routes off) and re-export. |
| Reporting "Apple Health refreshed" when the import wrote nothing | Historically exit 0 on an empty import — indistinguishable from a good run | An import yielding **0 health metric dates AND 0 sleep nights** now raises `EmptyImportError` and exits non-zero, before anything is written. It means a wrong file or a wrong date window, never a legitimate no-op. Surface the error; never re-introduce the exit-0-on-empty path. (`--dry-run` still reports instead of raising.) |
| Guessing which person a `HealthAutoExport_<timestamp>.zip` belongs to | Both people's exports use the same filename shape, nothing inside names the owner, and the resolver takes the newest `HealthAutoExport*.zip` in the tracker root regardless of `--person` | If ownership isn't unambiguous, **stop and ask** — don't infer it from the timestamp. A cross-import is not self-healing: sparse-merge won't overwrite it back out, and the CSVs are the record. |
| Looking in `.processed/` for the consumed export after a bad import | The archive was retired; the folder is empty and nothing writes to it | The importer **deletes** the zip on success (`--keep-export` is the escape hatch). Recovery is the per-person git repo at `<Person>/data` — both `/log` and the importer commit after every confirmed write, so `git log` / `git revert` there is the rollback path. |
| Renaming the export to something other than `HealthAutoExport*.zip` | Assumes the importer picks up any zip sitting in the tracker root | The resolver globs `HealthAutoExport*.zip` only (newest by mtime). A renamed file yields `ERROR: HealthAutoExport ZIP not found`, which reads as "the user didn't drop an export". Keep the app-generated filename, or pass `--zip <path>` explicitly. |
| `Swim 550m 22 laps` parsed with `reps=22` | reps is for strength rows; manual laps are not written to monthly rows | `reps=null`, `distance_km=0.55`, and omit `laps`. The importer derives the canonical lap count (distance ÷ pool length) onto `swimming/YYYY.MM.workouts.csv`. |
| Logging swim distance as `550` (kept as-is) → tracker shows `550 km` | The tracker's Distance column is km; swims are typically 0.2–3 km | Convert metres to km when the user writes `<N>m`. The importer is unit-gated on its side — it reads the `units` field on each quantity and skips a value whose unit isn't the one expected — so imported distances already land in km. |
| Inferring a `css_test` from any 400m + 200m pair | Silently overwrites the user's stored CSS | Only emit `css_test` when the user explicitly typed `CSS test` on the header line. Otherwise log the two swims as normal rows. |
| Trying to record per-lap stroke / SWOLF on a manual `/log` swim | There's no manual surface for it — and telling the user "the importer will fill it in" is now a false promise | Per-lap detail and SWOLF are **permanently unavailable**: HealthAutoExport carries no per-lap payload, and no `swimming/*.laps.csv` is written at all. A manual swim row records distance + duration; the importer adds pool length, laps, strokes, SPL and water temp. |
