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
| Dispatching `import_apple_health.py` against a `HealthAutoExport*.zip` file | The XML importer opens the ZIP but cannot find Apple's `export.xml` payload | Resolve by filename first: `HealthAutoExport*.zip` → `import_health_auto_export.py`, `Export*.zip` → `import_apple_health.py`. |
| Running a HealthAutoExport ZIP against a tracker whose `Profile.source` is `xml` (or vice versa) | Sparse-merge keeps data, but the profile no longer names the active source | Peek at `Profile.source` before dispatching. On mismatch, ask once: "This tracker is configured for `<current>`, switch to `<other>`?" — proceed only after the user confirms. |
| Renaming HealthAutoExport to `Export.zip` like the native Apple export | The logger routes it to the XML importer | Keep the app-generated `HealthAutoExport*.zip` filename. The resolver picks the most recent by mtime. |
| `Swim 550m 22 laps` parsed with `reps=22` | reps is for strength rows; manual laps are not written to monthly rows | `reps=null`, `distance_km=0.55`, and omit `laps`. Per-lap detail comes from Apple Health import only. |
| Logging swim distance as `550` (kept as-is) → tracker shows `550 km` | The tracker's Distance column is km; swims are typically 0.2–3 km | Convert metres to km when the user writes `<N>m` (Apple's XML importer now handles this automatically via `<WorkoutStatistics unit="m">`). |
| Inferring a `css_test` from any 400m + 200m pair | Silently overwrites the user's stored CSS | Only emit `css_test` when the user explicitly typed `CSS test` on the header line. Otherwise log the two swims as normal rows. |
| Trying to record per-lap stroke / SWOLF on a manual `/log` swim | There's no manual surface for it | Per-lap detail comes from Apple Health import only. A manual swim row records distance + duration only. |
