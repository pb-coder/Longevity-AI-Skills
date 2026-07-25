# Aliases

## Known Alias Table

| User input | Canonical name | Notes column |
|---|---|---|
| Deadhang, Dead hang | Dead Hang | — |
| Dips | Dip | — |
| Lying Leg Curl | Leg Curl (Lying) | — |
| Scapular Pull ups, Scapular Pullups | Scapular Pull-Up | — |
| Triceps Pushdown, Tricep Pushdown | Cable Tricep Pushdown | — |
| Hanging Leg Raise, Hanging leg raises, Hanging knee raise | Hanging Leg Raise | — |
| Outdoor Run | Outdoor Run | — |
| Incline Chest Press Machine | Chest Press Machine | `incline` |
| Leg Curl (no modifier) | Leg Curl (Seated) | — (ask if ambiguous; default seated) |
| Stomach crunches, Stomach Crunch | Ab Crunch Machine | the selectorized seated crunch machine |
| Stomach Press, Stomach Press Vertical, Stomach Press Vertical Machine | Stomach Press Machine | a DIFFERENT machine from Ab Crunch Machine — do not merge the two; their load scales differ by ~3x and merging them destroys both progression series |
| Crunch (alone) | Crunch | AMBIGUOUS — default shown is the bodyweight movement. Resolve to `Ab Crunch Machine` ONLY when a load is given; a load-free "crunch" is bodyweight. Ask if unclear. Renaming every bare "crunch" to the machine is what filed 0 kg bodyweight sets as machine rows |
| Hike, Hiking | Hike | — |
| Swim, Swimming | Swim | — |
| Walk, Walking | Walk | — |
| Yoga | Yoga | — |
| Stretch, Stretching, Mobility | Stretching | — |
| Outdoor Cycling, Bike Ride, Cycling | Outdoor Cycling | — |
| Romain Chair Sit-Up, Romain Chair | Roman Chair Sit-Up | — |
| Belt Squad Machine | Belt Squat Machine | — |
| Abdominal crunch | Ab Crunch Machine | resolve only when load/equipment context implies the machine; otherwise flag ambiguous |
| abductor machine | Hip Abductor Machine | — |
| seated abductor | Hip Abductor Machine | — |
| row machine without chest support | Seated Row Machine | — |
| Pulley | Cable Seated Row | — |
| Rear delt fly dumbbell | Dumbbell Rear Delt Fly | — |
| Leg raises | Leg Raise | — |
| Jumping Jack | Jumping Jacks | — |
| Prone Leg Curl | Leg Curl (Lying) | — |
| Reverse Pec Deck | Rear Delt Fly Machine | — |
| Low Row | Low Row Machine | — |
| Shoulder Press | Shoulder Press Machine | — |
| Adductor machine | Hip Adductor Machine | — |
| Cable bicep | Cable Bicep Curl | — |
| romanian deadlifts | Romanian Deadlift | — |
| seated leg curls | Leg Curl (Seated) | — |
| Dumbbell schrägbank Brust | Dumbbell Incline Bench Press | — |
| Dumbbell lat raises | Dumbbell Lateral Raise | — |
| Dumbbell chest press | Dumbbell Flat Bench Press | — |
| Dumbbell flat bicep curl arm resting on thingie | Preacher Curl (Dumbbell) | — |

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
