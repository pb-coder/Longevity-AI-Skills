# Common Mistakes

| Input pattern | Wrong parse | Correct parse |
|---|---|---|
| `bench press 80x8` | Missing equipment variant | Default to Barbell if context ambiguous |
| `3x12 curls` | One set of 312 reps | 3 separate rows, 12 reps each; ask for weight |
| `60lbs x 10` | Logged as 60kg | Convert: 60 ÷ 2.205 = 27kg |
| `farmer walks 40kg 30sec` | reps = 30 | reps = 0, Notes: `30sec, 40kg per hand` |
| `(warmup)` after exercise name | Ignored | Notes: `warmup` |
| No date given | Guess today | Ask once |
| `cable rows 3x12 @ 50` | One row with 312 reps | 3 rows, 12 reps, 50kg each |
| `jumping jacks` | "Jumping jacks" (user casing) | "Jumping Jacks" (database casing) |
| `triceps pushdown 40kg x 10` | "Triceps Pushdown" | "Cable Tricep Pushdown" (alias table) |
| `lying leg curl 50kg x 10` | "Lying Leg Curl" | "Leg Curl (Lying)" (alias table) |
| `deadhang 30s` | "Deadhang" (not in database) | "Dead Hang" (alias table) |
| `leg curl 55kg x 10 (seated)` | "Leg Curl" (ambiguous) | "Leg Curl (Seated)" — modifier resolves variant |
