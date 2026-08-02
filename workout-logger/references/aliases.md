# Aliases

## Known Alias Table

| User input | Canonical name | Notes column |
|---|---|---|
| Deadhang, Dead hang | Dead Hang | — |
| Dips | Dip | — |
| Lying Leg Curl | Leg Curl (Lying) | — |
| Scapular Pull ups, Scapular Pullups | Scapular Pull-Up | — |
| Triceps Pushdown, Tricep Pushdown | Cable Tricep Pushdown | — |
| Hanging leg raises, Hanging leg raise | Hanging Leg Raise | `Hanging knee raise` was removed from this row on 2026-08-02 — it is a separate canonical now (see below). Same failure mode the Stomach Press row warns about: collapsing a progression rung into the rung above it makes the easier movement unloggable and merges two series |
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
| Cable Row Machine | Seated Row Machine | — |
| Dumbbell bicep hammer | Dumbbell Hammer Curl | — |
| Farmers Walk, Farmers Walks, Farmer Walk, Farmer Walks, Farmer's Walk, Farmer's Walks, Farmer’s Walk, Farmers Carry, Farmer Carry, Farmer's Carry, Farmer’s Carry, Dumbbell Farmers Walk, DB Farmer Walk | Dumbbell Farmer Walk | TWO-handed carry. Not a core exercise — rectus abdominis sits at ~3.9% MVC (McGill, Marshall & Andersen 2013) and the two loads cancel laterally. For the one-handed version use `Suitcase Carry`, which is core |
| Suitcase Walk, Single Arm Farmer Walk, Single-Arm Farmer Walk, One Arm Farmer Walk, One-Arm Carry, Unilateral Carry, Offset Carry | Suitcase Carry | ONE-handed carry, a core (anti-lateral-flexion) movement — distinct from the two-handed Dumbbell Farmer Walk, do not merge. Both sides must be carried; a single side is half the set |
| Ab Wheel, Ab Roller, Ab Rollout, Wheel Rollout, Roll Out | Ab Wheel Rollout | — |
| Hanging knee raise, Hanging knee raises, Hanging Knee Up, Knee Raise (hanging), Hanging Knee-Up | Hanging Knee Raise | its own canonical, NOT a synonym for Hanging Leg Raise — the knee-flexed rung below it. Merging the two destroys the progression from one to the other |
| Around the World, Plate Halo, Weight Plate Halo, Plate Around The World, Dumbbell Around the World | Plate Around the World | the plate halo (a weight orbiting the head/torso), NOT the World's Greatest Stretch — that is a separate WARMUP canonical |
| Rowing, Rower, Erg, Row Erg, Rowing Erg, Concept 2, Concept2 | Rowing Machine | the cardio erg. Do NOT confuse with `Seated Row Machine` / `Low Row Machine`, which are back-strength machines |

## Deliberately NOT aliased

`Band Pull-Apart` (and `Band Pull Apart` / `Band Pullapart` / `Resistance Band
Pull-Apart`) has no alias row, and must not be given one. A row mapping it to
`Dumbbell Rear Delt Fly` was added and removed again on 2026-08-02. Four reasons,
each one sufficient:

1. **It re-opens a closed path.** Commit `ff13d82` removed every `[Band]`
   exercise from the catalog for the stated reason "no band equipment
   available". `exercises_database.known_name_set()` includes alias *input*
   strings, and `render_validators.validate_workout_md` uses that set as a
   hard, render-blocking gate — so the render gate is the only thing enforcing
   that decision. An alias row silently re-permits band prescriptions.
2. **It converts warm-up prep into emphasis-muscle volume.** `Band Pull-Apart`
   lived under `## WARMUP / ### Upper Body`: no primary muscle, warm-up flagged,
   zero set credit. Every prescription of it has been a warm-up bullet. Pointing
   it at a rear-delt isolation entry turns each one into a full 1.0 rear-delt
   hard set, because both `strength.weekly_volume_per_muscle` and
   `sessions._is_working_set` credit on `reps > 0` regardless of kg.
3. **The `kg 0` safety argument is incomplete.** The `kg > 0` gate exists on
   `estimated_1rm` and `progression_summary` only. `weekly_volume_per_muscle`
   and `stale_exercises` have no kg gate, so a 0 kg band row would both
   manufacture rear-delt volume and refresh `last_seen` on the real dumbbell
   movement, pulling it out of the reintroduction pool.
4. **Adherence says bench it.** Prescribed 9x, logged 0x.

Correct handling: `Band Pull-Apart` is off-catalog. The render gate rejects it
in a plan (right answer: the equipment is not owned), and the one historical
logged row surfaces in `unknown_exercises` (right answer: it is honest about
what the catalog does not cover).

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
