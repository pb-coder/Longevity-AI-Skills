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
| Y Raise, Y-Raise, Prone Y Raise, Prone Y-Raise, Incline Y Raise, Prone Y | Incline Y-Raise | added 2026-08-02. Traps had only two shrugs — one movement pattern in two equipment flavours — so a rotating traps slot could never legally rotate. This is the second pattern: scapular upward rotation, lower/mid traps |
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
| Rotary Calf | Rotary Calf Machine | — |
| Sotting Leg Curl | Leg Curl (Seated) | — |
| cable Calf Raise | Cable Standing Calf Raise | — |
| Cable Crunch | Kneeling Cable Crunch | — |
| Pike Pushup, Pike Push Up | Pike Push-Up | — |
| Elevated Pike Pushup, Elevated Pike Push Up, Feet Elevated Pike Push-Up | Elevated Pike Push-Up | — |
| Deficit Pushup, Deficit Push Up | Deficit Push-Up | — |
| Diamond Pushup, Diamond Push Up, Close Grip Push-Up, Triangle Push-Up | Diamond Push-Up | — |
| Incline Pushup, Incline Push Up | Incline Push-Up | — |
| Decline Pushup, Decline Push Up, Feet Elevated Push-Up | Decline Push-Up | — |
| Archer Pushup, Archer Push Up | Archer Push-Up | — |
| Table Row, Inverted Row, Desk Row, Under Table Row | Table Inverted Row | the improvised horizontal pull; load-test the table before using it |
| Feet Elevated Table Row, Feet-Elevated Inverted Row | Feet-Elevated Table Inverted Row | — |
| Doorway Row, Towel Door Row, Door Towel Row | Doorway Towel Row | — |
| Sheet Door Row, Steep Door Row, Door Sheet Row | Steep Sheet Door Row | — |
| Reverse Nordic | Reverse Nordic Curl | — |
| Copenhagen, Copenhagen Plank | Copenhagen Plank (Short Lever) | AMBIGUOUS — defaults to the short-lever entry rung. Resolve to `Copenhagen Plank (Long Lever)` only when the input says foot or ankle on the support. Ask if unclear |
| Sliding Curl, Towel Leg Curl, Slider Leg Curl | Sliding Leg Curl | needs a hard smooth floor; on carpet the movement does not work |
| Hollow Rock | Hollow Rocks | — |
| Dragon Flag | Tuck Dragon Flag | only the tuck rung is in the catalog. Revisit this row if the full Dragon Flag is ever added, or it will silently swallow the harder rung |
| Shoulder Taps | Plank Shoulder Taps | — |
| YTW, Y-T-W Raise, Y T W Raise, Prone YTW | Prone Y-T-W Raise | — |
| Chair Dip, Bench Dip, Tricep Bench Dip | Chair Bench Dip | NOT the parallel-bar `Dip` — different loading, and a larger shoulder-extension range |
| Long Lever Plank, RKC Plank | Long-Lever Plank | — |
| Towel Rollout, Slider Rollout | Towel Rollout (Kneeling) | kneeling is the entry rung |
| Single Arm Plank, One Arm Plank | Single-Arm Plank | — |
| Cossack | Cossack Squat | — |
| Step Up | Step-Up | — |
| Deep Step Up | Deep Step-Up | — |
| Wall Lean Lateral Raise, Wall Lean Side Slide | Wall-Lean Side Slide | do NOT collapse into `Wall Slide` — that is a WARMUP entry with no primary muscle and zero set credit |
| Self Resisted Curl, Self-Resistance Curl | Self-Resisted Curl | — |
| Self Resisted Lateral Raise | Self-Resisted Lateral Raise | — |
| Bodyweight Skullcrusher, BW Skull Crusher, Bodyweight Skull Crushers | Bodyweight Skull Crusher | — |
| Calf Raise on Edge, Single Leg Calf Raise, One Leg Calf Raise | Single-Leg Calf Raise on Edge | bodyweight off a step or book edge — NOT `Calf Raise Machine` |
| Elevated Hip Thrust, Shoulder Elevated Hip Thrust | Elevated Single-Leg Hip Thrust | NOT `Single Leg Hip Thrust`, which is the barbell-loaded entry |
| Assisted Nordic, Nordic Regression | Assisted Nordic Hamstring Curl | NOT `Nordic Hamstring Curl` — the assisted entry is the rung below it |
| Bed Back Extension, Bed Edge Back Extension | Bed-Edge Back Extension | — |
| Neck Isometrics, Self Resisted Neck | Self-Resisted Neck Isometric | — |

## Deliberately NOT aliased

`Bulgarian Split Squat` (bare, with no equipment word) has no alias row and must
not be given one. The catalog now carries four variants — `Dumbbell`, `Cable`,
`Bodyweight` and the `Bulgarian Split Squat Jump` — so a bare input has no
correct default. Guessing merges two different progression series: the gym
dumbbell history and the bodyweight travel work would land on one exercise name,
and `estimated_1rm` would read the bodyweight sets as a collapse to 0 kg on the
loaded lift. Ask which one.

The same rule covers three bare names whose easy rung must stay the default,
because each now has a harder same-pattern sibling in the catalog:
`Push-Up` stays the floor push-up and never resolves to a deficit or archer
variant; `Plank` stays the standard plank and never resolves to `Long-Lever
Plank`; `Side Plank` stays the floor version and never resolves to
`Feet-Elevated Side Plank`. Aliasing any of them upward would silently rewrite
logged history into a harder movement the user did not do.

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
