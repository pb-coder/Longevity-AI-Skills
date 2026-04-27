# Aliases

## Known Alias Table

| User input | Canonical name | Notes column |
|---|---|---|
| Deadhang, Dead hang | Dead Hang | — |
| Dips | Dip | — |
| Lying Leg Curl | Leg Curl (Lying) | — |
| Scapular Pull ups, Scapular Pullups | Scapular Pull-Up | — |
| Triceps Pushdown, Tricep Pushdown | Cable Tricep Pushdown | — |
| Hanging Leg Raise | Leg Raise | `hanging` |
| Outdoor Run | Outdoor Run | — |
| Incline Chest Press Machine | Chest Press Machine | `incline` |
| Leg Curl (no modifier) | Leg Curl (Seated) | — (ask if ambiguous; default seated) |
| Crunch (alone), Stomach crunches, Stomach Crunch, Stomach Press, Stomach Press Vertical, Stomach Press Vertical Machine | Ab Crunch Machine | flag if user clearly meant a different machine |
| Hike, Hiking | Hike | — |
| Swim, Swimming | Swim | — |
| Walk, Walking | Walk | — |
| Yoga | Yoga | — |
| Stretch, Stretching, Mobility | Stretching | — |
| Outdoor Cycling, Bike Ride, Cycling | Outdoor Cycling | — |

## Modifier Handling

When user input includes a modifier not in the canonical name (e.g. "hanging", "incline", "seated"), use the closest canonical name and put the modifier in Notes. Do not invent new exercise names.

## Equipment Defaults

When equipment is missing, default to the most common variant:

| Context | Default |
|---|---|
| Curls | Dumbbell |
| Squats, Deadlifts | Barbell |
| Pushdowns | Cable |
| Bench Press (ambiguous) | Barbell |
