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
| Date from a brand-new month | Ask the user if it's OK to create the sheet | Just call the script — it creates the `YYYY.MM` sheet with headers if missing |
| Writing a standalone `.xlsx` or markdown table to chat | Claude.ai-era output | The tracker itself is the output. Summary line only. |
| `/log 22.04 deload ...` with no deload marker | Session logged normally | Keyword `deload` on the header line sets `Deload Workout` in the first row's notes. Coach reads this for mesocycle math. |
| `plank 45s` → reps=45 | Duration smuggled into reps | `reps=0`, `duration_min=0.75`. Isometric holds belong in the Duration column. |
| `deadhang 30s` (isometric hold) | `reps=30` | `reps=0`, `duration_min=0.5`, canonical name "Dead Hang". |
| Unknown exercise name flagged `(not in database)` without trying fuzzy | Loses a match the model would recognize at a glance | Run the fuzzy-match ladder in `parsing-rules.md`. Only fall through to `(not in database)` when no close canonical name exists. |
