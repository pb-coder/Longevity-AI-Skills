# Travel bodyweight block — design

**Date:** 2026-09-01
**Status:** DRAFT, awaiting <Person>'s review. Nothing implemented.
**Person:** <Person> (the other tracker is untouched by this)
**Trigger:** 3-4 weeks away with no gym.

---

## 1. What this is for

<Person> leaves home for 3-4 weeks with no gym and no equipment. He wants to
hold the progress he has rather than gain, and he wants the work stored in the
tracker rather than done off the books.

Two deliverables:

1. A training plan he can follow in a room.
2. The tracker changes that make the plan loggable, plannable by `/coach`, and
   readable afterwards without the reports lying about what happened.

## 2. Constraints, as confirmed on 2026-09-01

| Constraint | Value | Consequence |
|---|---|---|
| Duration | 3-4 weeks | One block. No deload needed inside it. |
| Session length | 15-20 min, available every day | Six short sessions a week, not three long ones. |
| Room contents | Chair, table, bed usable | Rows, dips, split squats, Copenhagen planks all live. |
| Pull-up bar | **None** | Vertical pull is the biggest single loss. |
| Bands | Being chased, not confirmed | Designed as an upgrade, not a dependency. |
| External load | **No usable bag** | No set logs a weight. Strength tracking goes blind. |
| Floor type | Unknown | Hamstring plan needs two paths. |
| Calories | Going to maintenance | Removes the largest muscle-loss risk. |
| Running | Only when time allows | Optional, and must not be reported as a gap. |
| Bodyweight | read from the tracker at plan time | The protein target derives from it |

## 3. What the evidence says

### 3.1 Three to four weeks costs almost nothing

Fourteen days of **complete** cessation in trained power athletes moved bench
1RM by -1.7% and squat 1RM by -0.9%, neither statistically distinguishable from
zero, with vertical jump unchanged (Hortobágyi et al., Med Sci Sports Exerc
1993;25(8):929-935). A separate trial found trained men held their strength
across two weeks off (Hwang et al., J Strength Cond Res 2017;31(4):869-881).
A systematic review of resistance-training-then-cessation studies found
hypertrophy largely preserved through 12 to 24 weeks, with significant muscle
size loss only appearing at 31 to 52 weeks (Muscles 2022;1(1):1-15).

The exceptions, which appear early:

- **Fast-twitch fibre area** fell about 6.4% in 14 days (Hortobágyi 1993).
- **Eccentric-specific strength** fell 12% in 14 days, in every subject
  (Hortobágyi 1993). This is the fastest-decaying quality measured.

So the goal of this block is not to fight decay. Over 3-4 weeks there is very
little decay to fight. The goal is to avoid creating new problems: losing muscle
to a calorie deficit, or getting hurt ramping running from near zero.

### 3.2 The maintenance dose is small

Sixteen weeks of leg training at 27 weekly sets, followed by 32 weeks at either
a third or a **ninth** of that volume in a single weekly session, held both
strength and muscle size in adults aged 20-35, provided the load stayed heavy
(Bickel, Cross & Bamman, Med Sci Sports Exerc 2011;43(7):1177-1187). A review
of the same question concluded strength and size hold for up to 32 weeks on one
session a week and one set per exercise, and named **intensity, not volume or
frequency, as the variable that must not drop** (Spiering et al., J Strength
Cond Res 2021;35(5):1449-1458).

Note the catch, and it is the central caveat of this whole document: every
maintenance study kept the load heavy and cut the volume. **No study has tested
what <Person> is doing, which is keeping the volume and dropping the load to
bodyweight.** Section 11 states what follows from that.

### 3.3 Why bodyweight work can substitute, and where its floor is

With sets taken to failure, low loads (60% of one-rep max or less) and high
loads produce equivalent muscle growth; 1RM strength gains still favour heavy
loads (Schoenfeld et al., J Strength Cond Res 2017;31(12):3508-3523). In trained
men over 12 weeks, 30-50% of 1RM and 75-90% of 1RM produced equal hypertrophy
and broadly equal strength when all sets went to failure (Morton et al., J Appl
Physiol 2016;121(1):129-138).

Push-ups specifically have been tested against bench press twice, and matched it
for strength and muscle thickness (Kotarsky et al., J Strength Cond Res
2018;32(3):651-659; Kikuchi & Nakazato, J Exerc Sci Fit 2017;15(1):37-42).

Two hard boundaries:

- **The load floor is roughly 30-40% of 1RM.** At 20% of 1RM, hypertrophy and
  strength were inferior even with volume-load equated (Lasevicius et al., Eur J
  Sport Sci 2018;18(6):772-780). Below that floor, harder effort does not
  rescue the set. This is why unilateral variants matter so much: standing on
  one leg roughly doubles the relative load and pushes the exercise back over
  the floor.
- **Proximity to failure stops being optional.** Training to failure improved
  hypertrophy at 30% of 1RM but not at 80% (Lasevicius et al., J Strength Cond
  Res 2022;36(2):346-351). Heavy sets tolerate reps left in reserve; bodyweight
  sets do not. Every working set in this plan is written to 0-2 reps in reserve
  and that is a requirement, not a suggestion.

### 3.4 The best ways to make bodyweight hard, ranked by evidence

1. **Take the set close to failure.** Best supported, and the precondition for
   everything else (Robinson et al., Sports Med 2024;54(9):2209-2231).
2. **Train at long muscle length.** Isometric holds at long muscle length
   produced 0.86-1.69% growth per week against 0.08-0.83% at short length, at
   equal volume (Oranchuk et al., Scand J Med Sci Sports 2019;29(4):484-503).
   This is why deficit push-ups, ATG split squats, reverse Nordics and
   stretched-position calf raises carry the plan.
3. **Go unilateral.** Mechanically sound, restores relative load. No dedicated
   trial.
4. **Change leverage and range of motion.** Feet elevated, hands on books,
   deeper positions.
5. **Slow the eccentric to 3-5 seconds.** Hypertrophy is similar across rep
   durations from 0.5 to 8 seconds, so slow tempo is free difficulty but not an
   inherent advantage (Schoenfeld et al., Sports Med 2015;45(4):577-585). Use it
   as a load dial, do not sell it as extra growth.

### 3.5 Running while doing this

The 2012 meta-analysis found running specifically interfered with hypertrophy
and strength, with the effect scaling with endurance frequency and duration
(Wilson et al., J Strength Cond Res 2012;26(8):2293-2307). A 2022
meta-analysis of 43 studies found no significant compromise to hypertrophy or
maximal strength, with only explosive strength attenuated and mainly when both
were in the same session (Schumann et al., Sports Med 2022). At two to four
easy runs a week, interference is not the problem.

The injury risk is. Bone stress injury risk peaks **4 to 7 weeks after** a load
increase, because that is when bone remodelling porosity peaks, and runners with
under a month of running experience are at elevated risk (Warden, Edwards &
Willy, Curr Osteoporos Rep 2021). <Person> has logged 137 zone 2 minutes in 28
days and zero interval sessions, so any real ramp starts from near zero and the
risk window lands after he is home.

### 3.6 Protein and calories

At a 40% deficit with hard training, 2.4 g/kg/day of protein produced +1.2 kg
lean mass and -4.8 kg fat, while 1.2 g/kg produced no lean change and -3.5 kg
fat (Longland et al., Am J Clin Nutr 2016;103(3):738-746). Five days of deficit
lowered resting muscle protein synthesis 27%, and a single resistance-exercise
bout restored it (Areta et al., Am J Physiol Endocrinol Metab
2014;306(8):E989-E997). Recommended intake for lean trained people in a deficit
is 2.3-3.1 g/kg of fat-free mass (Helms et al., Int J Sport Nutr Exerc Metab
2014;24(2):127-138).

**Protein target: derive it at plan time** from the latest logged bodyweight. Body fat percentage and lean mass have never been logged in
`health_metrics.csv`, so fat-free mass is estimated, not measured. That is a
data caveat, not a pipeline gap.

Going to maintenance is the right call and it is the single highest-value
decision in this document. Weak stimulus plus deficit is the one combination
that reliably costs muscle.

## 4. Coverage verdict per muscle

Honest, with no substitutions dressed up as equivalents.

| Muscle | Best option in the room | Verdict |
|---|---|---|
| Chest | Deficit push-up, decline push-up, archer push-up | **Good.** Directly validated against bench press. |
| Triceps | Bodyweight skull crusher, chair dip, diamond push-up | **Good.** |
| Quads | Bulgarian split squat, ATG split squat, reverse Nordic, shrimp squat | **Good.** Unilateral restores real load. |
| Glutes | Elevated single-leg hip thrust, deep step-up | **Adequate.** Growth stimulus fine, top-end strength no. |
| Calves | Single-leg calf raise off a book edge, stretch pause | **Good.** Standing straight-knee raises grew gastrocnemius 9-12% vs 1-2% seated (Kinoshita 2023). |
| Adductors | Copenhagen plank, short then long lever | **Good.** Evidence-based, needs one chair. |
| Core | Towel rollouts, dragon flag ladder, long-lever plank | **Good.** |
| Shoulders (press) | Pike push-up, elevated pike push-up | **Good.** |
| Back, horizontal pull | Table inverted row, doorway towel row | **Adequate if the table holds.** The inverted row is EMG-validated for mid-traps and lats. |
| Hamstrings | Sliding leg curl on towels, Nordic regressions | **Conditional.** See §5.4. Needs a hard floor or a furniture anchor. |
| Erectors | Bed-edge back extension | **Weak.** Nothing approaches deadlift or squat axial load. |
| Rear delts | Prone Y-T-W raise, wide-elbow towel row | **Weak to adequate.** |
| Neck | Self-resisted isometrics, bed-edge curls | **Adequate.** Isometric neck programs raised strength 20-35%. |
| **Back, vertical pull** | Steep sheet door row | **Not served.** See below. |
| **Lateral delts** | Wall-lean side slide, self-resisted raise | **Not served.** See below. |
| **Biceps, direct** | Underhand rows, self-resisted curls | **Not served directly.** See below. |

### The three real gaps

**Vertical pull.** There is no safe rung equal to a pull-up in a room with no
bar. The best available thing is a bedsheet knotted over the top of a closed,
latched door, pulled at a steep body angle. That is a high row, not a pulldown.
A towel-over-door dead hang is excluded: hanging the logged bodyweight dynamically from an
interior door is a hinge and latch failure risk, and no engineering source rates
interior doors for it. Doorframe finger ledges train fingers, not lats.

**Lateral delts.** With no external load there is nothing good. Wall-lean side
slides and self-resisted raises load the muscle at short length, at one angle,
with no eccentric, which is three strikes against growth. The only supporting
evidence for no-load training is one study in untrained people showing 4%
thickness change (Counts et al. 2016). For a trained lifter that is maintenance
at best.

**Direct biceps.** Underhand rows load the elbow flexors under real load with a
real eccentric and are the backbone here, but they are a compound. There is no
curl.

Over 3-4 weeks, given §3.1, leaving these three under-trained is an acceptable
cost. Over 8+ weeks it would not be.

**What roughly 3 kg fixes.** Two filled 1.5 litre water bottles are a genuine
working weight for lateral raises and a usable one for curls and rear delt
raises. This closes two of the three gaps almost entirely, and it also gives
`/coach` sets with an actual weight in kilos, which restores strength tracking
(§9.4). The plan below works with nothing; the `[Hand Load]` entries in §8 are
the upgrade path. **This is the cheapest large improvement available and worth
five minutes in a supermarket.**

## 5. The training plan

### 5.1 Structure

Six sessions a week, 15-20 minutes each, one rest day. Three session shapes,
each run twice a week with different exercises the second time, so every
movement pattern is trained twice weekly and each exposure covers a different
region of the muscle. This is the model already in `training-science.md` §17:
same split, second exposure, vary the repeated day.

Eleven to twelve working sets per session, 60-90 seconds rest. Bodyweight sets
have no setup and no plate changes, so roughly 1.3 minutes per set including
rest, which lands each session at 14-16 minutes of work plus a 3-minute warm-up.

Daily short sessions are a logistics choice, not a compromise. Frequency has
negligible independent effect on hypertrophy once weekly volume is equated
(Pelland et al. 2025, already cited in §14 of `training-science.md`).

**Weekly volume, counted in the tracker's fractional unit** (direct sets plus
half a set per synergist tag):

| Muscle | Direct sets | Fractional total | Against maintenance |
|---|---|---|---|
| Chest | 8 | ~9.5 | Comfortable |
| Back | 11 | ~11 | Comfortable |
| Quads | 6 | ~6 | Adequate |
| Triceps | 6 | ~11.5 | Comfortable |
| Biceps | 5 | ~10.5 | **Direct work is weak, see §4** |
| Core | 12 | 12 | Comfortable |
| Glutes | 3 | ~5.5 | Adequate |
| Hamstrings | 5 | ~5 | Adequate |
| Rear delts | 3 | ~7 | Adequate |
| Calves | 3 | 3 | At maintenance, no more |
| Adductors | 2 | ~2 | Thin but acceptable at maintenance |
| Lateral delts | 2 | ~2 | **Not served, see §4** |
| Traps | 0 | ~4 synergist only | No loaded shrug exists here |
| Erectors | 0 | ~0 | **No direct sets.** Bed-Edge Back Extension exists in the catalog if wanted; the landmarks table already records erector targets as unsettled. |

Total 69 working sets a week, against roughly 60 in his current three-session
gym weeks. Higher set count, much lower load, much less time.

### 5.2 The six sessions

Every working set is 0-2 reps in reserve. Where a tempo is given, it is the
lowering phase. Sessions run A1, B1, C1, A2, B2, C2, rest.

**A1, push**
- Deficit Push-Up, 4 sets, 6-10 reps, 3 s lowering
- Elevated Pike Push-Up, 3 sets, 6-10 reps
- Bodyweight Skull Crusher, 3 sets, 8-12 reps
- Long-Lever Plank, 2 sets, 30-45 s

**B1, pull**
- Table Inverted Row, 4 sets, 8-12 reps (Doorway Towel Row if no safe table)
- Steep Sheet Door Row, 3 sets, 8-12 reps (skip if the door is hollow-core and add a set to the row above)
- Self-Resisted Curl, 3 sets, 10-15 reps
- Single-Arm Plank, 2 sets, 20-30 s per side

**C1, legs**
- Bodyweight Bulgarian Split Squat, 3 sets, 10-15 reps per leg, deep, 3 s lowering
- Hamstring slot, 3 sets: which exercise depends on the room, see §5.4
- Single-Leg Calf Raise on Edge, 3 sets, 12-20 reps, 2 s pause at the stretch
- Reverse Crunch, 2 sets, 12-15 reps

**A2, push, second exposure**
- Decline Push-Up, 4 sets, 8-12 reps
- Chair Bench Dip, 3 sets, 8-12 reps (conditions in §5.5)
- Wall-Lean Side Slide, 2 sets, 12-20 reps (labelled weak; replace with a hand-load lateral raise if bottles are found)
- Hollow Rocks, 2 sets, 12-20 reps

**B2, pull, second exposure**
- Underhand Table Row, 4 sets, 10-15 reps
- Wide-Elbow Doorway Towel Row, 3 sets, 12-15 reps
- Towel Isometric Curl, 2 sets, 20-30 s at three joint angles
- Tuck Dragon Flag, 2 sets, 8-12 reps

**C2, legs, second exposure**
- Reverse Nordic Curl, 3 sets, 6-10 reps
- Elevated Single-Leg Hip Thrust, 3 sets, 10-15 reps per leg
- Bodyweight Single-Leg Romanian Deadlift, 2 sets, 12-15 reps per leg, 3 s lowering
- Copenhagen Plank (Short Lever), 2 sets, 15-30 s per side
- Feet-Elevated Side Plank, 2 sets, 20-30 s per side

**Day 7:** rest, or an easy run, or mobility.

**Warm-up, 3 minutes, every session:** Jumping Jacks 60, Arm Circles 20 each
direction, Bodyweight Squat 15, plus one light set of the day's first exercise.
All four already exist in the database.

### 5.3 Progression across the 3-4 weeks

- **Week 1:** establish the rung. Find the version of each exercise where the
  prescribed rep range lands at 0-2 reps in reserve.
- **Weeks 2-3:** add reps at the same rung. When all sets hit the top of the
  range with clean form, move up a rung. This is the r/bodyweightfitness rule
  (3 sets of 8 clean reps to advance) and it is practitioner consensus, not a
  tested ordering.
- **Week 4, if there is one:** hold. No deload needed; the loads are too low to
  accumulate the fatigue a deload exists to clear.

Moving up a rung means logging a different exercise name. That is deliberate and
it is how the database already works: it carries both Hanging Knee Raise and
Hanging Leg Raise, with a note recording that collapsing the two "erased the
progression for a movement with 11 logged sessions".

### 5.4 The hamstring slot, resolved on arrival

The whole hamstring category depends on the room, so the plan carries three
paths and <Person> picks on day one.

1. **Hard floor (wood, tile, laminate): Sliding Leg Curl on towels.** First
   choice. Classified as a high-intensity hamstring exercise alongside the
   Nordic curl in EMG-based classifications (Tsaklis et al., Open Access J
   Sports Med), with its own NSCA Strength and Conditioning Journal exercise
   column. Trains the hamstring at long length across both hip and knee.
   Ladder: double-leg eccentric only, then double-leg full, then single-leg.
2. **Furniture anchor available (sofa base or bed frame rail with a real gap):
   Assisted Nordic Hamstring Curl.** Regressions in order: hip-hinged, hands
   catching, limited range to a pillow stack, then slow eccentric only.
   **Safety condition:** the anchor must not shift at 45 degrees of lean. The
   failure mode is landing face-first. A platform bed with no gap and light
   furniture means no Nordic at all.
3. **Carpet and no anchor: Single-Leg Long-Lever Glute Bridge.** This is the
   weak path and it should be named as such in the plan, not smoothed over.

### 5.5 Furniture safety, and why this is a real risk

Nobody publishes load ratings for hotel desks or interior doors. Every load
judgement below is reasoning, not engineering data, and the mitigation depends
on <Person> actually doing it.

- **Table inverted row.** Hanging with feet on the floor loads one table edge
  with roughly 40-55 kg. A solid wood dining table is fine. A laminated
  particleboard hotel desk with cam-lock legs may not be, and a wall-cantilevered
  desk must not be used at all. Test by pressing down hard with both hands, then
  one knee, before committing. Keep the pull inside the leg base so it cannot tip.
- **Steep sheet door row.** The load runs over the door top onto the hinges and
  latch. At a 45-70 degree body angle that is well under half of bodyweight, which
  a solid-core door on three hinges handles. Abort on any creak or hinge
  movement. Never bounce. Hollow-core doors: do not use.
- **Chair bench dips.** In the plan, with two conditions, because without them
  direct triceps volume falls below the floor the plan checks enforce. The chair
  must be heavy, non-folding, and pushed against a wall. Lower only to upper arm
  parallel and no further: the bench dip has the largest shoulder-extension
  range of the dip family and deep repeated reps strain the anterior shoulder
  capsule. If the room has only a folding or wheeled chair, drop the exercise
  and raise Bodyweight Skull Crusher to 6 sets across both push sessions
  instead.
- **Neck Bridge.** Already in the database. Excluded here on cervical
  compression grounds; bed-edge neck curls do the job.

## 6. Running

Written as optional. <Person> said "depending on my time", so the tracker must not
report missed runs as a gap in this block (§9.3).

- Two or three easy runs a week if time allows, heart rate 134-146 bpm.
- **Cap the weekly increase at 10-15% of total duration.** This is the whole
  injury prevention story; the exact acute-to-chronic ratio numbers are
  methodologically contested and the robust part is just "do not spike load".
- No intervals during the trip. Adding high-intensity running to a body that has
  logged zero interval sessions in 28 days, while in a new sleep and food
  environment, is the wrong week for it.
- **The risk window outlasts the trip.** If mileage ramps in week 2 of the trip,
  bone stress risk peaks somewhere around weeks 6-9 counting from now, which is
  after he is home. Section 10 carries this forward.

## 7. Nutrition

- Close the open cut phase, which has been running at the time of writing with no
  targets specified, and open a `maintain` phase for the travel dates.
- Protein 170-200 g/day.
- Expect the scale to move up 0.5-1.5 kg in the first week on food, salt and gut
  content changes. That is not fat. The waist channel is the leanness signal and
  `waist_latest` is currently empty, so a tape measure before leaving would
  give the return comparison something to stand on.

## 8. Database changes

### 8.1 Principle: one entry per difficulty rung

Push-Up, Deficit Push-Up and Archer Push-Up are three entries, not one entry
with a difficulty field. This follows the existing precedent cited in §5.3 and
it is what makes rung progression visible to `progression_summary` without any
schema change.

### 8.2 New equipment tags

Three new tags, plus one that only matters if the water bottles happen. The
legend at the top of `exercises-database.md` must document each one; there is a
test asserting the legend documents every tag in use.

| Tag | Means | Notes |
|---|---|---|
| `[Furniture]` | Chair, table, bed, desk, or a step or book edge | Carries the load-test warning in §5.5 |
| `[Towel]` | Towel or bedsheet, including towels used as floor sliders | Sliding work needs a hard floor |
| `[Door]` | A closed, latched, solid-core door plus a towel or sheet | Excluded on hollow-core doors |
| `[Hand Load]` | Any improvised hand-held weight: filled bottles, books | Only tag whose sets log an actual kg |

A wall counts as `[BW]`. Every room has one.

### 8.3 Entries to add

**Tier 1** is what the six sessions prescribe, plus one rung either side so
progression has somewhere to go, plus the named substitutes the plan falls back
on when the room does not cooperate. Roughly 45 entries. **Tier 2** is the rest
of the ladder, documented here and added only if needed.

Tier 1, by section:

- `CHEST / Horizontal Push (Compound)`: Incline Push-Up `[Furniture]`, Decline
  Push-Up `[Furniture]`, Deficit Push-Up `[Furniture]` ◆, Diamond Push-Up
  `[BW]`, Archer Push-Up `[BW]`, One-Arm Incline Push-Up `[Furniture]`
- `BACK / Vertical Pull (Compound)`: Steep Sheet Door Row `[Door]` ◆
- `BACK / Horizontal Pull (Compound)`: Table Inverted Row `[Furniture]`,
  Feet-Elevated Table Inverted Row `[Furniture]`, Underhand Table Row
  `[Furniture]`, Doorway Towel Row `[Door]`, Single-Arm Doorway Towel Row
  `[Door]`
- `BACK / Back — Other`: Bed-Edge Back Extension `[Furniture]` ◆
- `SHOULDERS / Vertical Push (Compound)`: Pike Push-Up `[BW]`, Elevated Pike
  Push-Up `[Furniture]`, Deficit Elevated Pike Push-Up `[Furniture]` ◆
- `SHOULDERS / Lateral Delt (Isolation)`: Wall-Lean Side Slide `[BW]`,
  Self-Resisted Lateral Raise `[BW]`
- `SHOULDERS / Rear Delt (Isolation)`: Wide-Elbow Doorway Towel Row `[Door]`
- `SHOULDERS / Traps`: Prone Y-T-W Raise `[BW]`, Reverse Snow Angel `[BW]`
- `BICEPS / Isolation — Standard`: Self-Resisted Curl `[BW]`, Towel Isometric
  Curl `[Towel]`
- `TRICEPS / Isolation — Lengthened Position`: Bodyweight Skull Crusher
  `[Furniture]` ◆
- `TRICEPS / Isolation — Standard`: Chair Bench Dip `[Furniture]`
- `QUADS / Squat Pattern (Compound)`: Bodyweight Split Squat `[BW]`, Bodyweight
  Bulgarian Split Squat `[Furniture]` ◆, ATG Split Squat `[BW]` ◆, Step-Up
  `[Furniture]`, Deep Step-Up `[Furniture]` ◆, Shrimp Squat `[BW]` ◆, Wall Sit
  `[BW]`, Cossack Squat `[BW]` ◆
- `QUADS / Quad Isolation`: Reverse Nordic Curl `[BW]` ◆
- `HAMSTRINGS / Hip Hinge (Compound)`: Long-Lever Glute Bridge `[BW]`,
  Single-Leg Long-Lever Glute Bridge `[Furniture]`, Bodyweight Single-Leg
  Romanian Deadlift `[BW]` ◆
- `HAMSTRINGS / Hamstring Isolation`: Sliding Leg Curl `[Towel]` ◆, Single-Leg
  Sliding Leg Curl `[Towel]` ◆, Assisted Nordic Hamstring Curl `[Furniture]` ◆
- `GLUTES / Compound`: Elevated Single-Leg Hip Thrust `[Furniture]`, Bed Reverse
  Hyperextension `[Furniture]`
- `ADDUCTORS`: Copenhagen Plank (Short Lever) `[Furniture]`, Copenhagen Plank
  (Long Lever) `[Furniture]`, Copenhagen Adduction `[Furniture]`
- `CALVES`: Single-Leg Calf Raise on Edge `[Furniture]` ◆, Bent-Knee Single-Leg
  Calf Raise `[Furniture]`
- `CORE / Flexion`: Reverse Crunch `[BW]`, Hollow Rocks `[BW]`, Tuck Dragon Flag
  `[Furniture]`
- `CORE / Anti-Extension`: Long-Lever Plank `[BW]`, Body Saw `[Towel]`, Towel
  Rollout (Kneeling) `[Towel]` ◆
- `CORE / Anti-Rotation`: Plank Shoulder Taps `[BW]`, Single-Arm Plank `[BW]`
- `CORE / Anti-Lateral-Flexion`: Feet-Elevated Side Plank `[Furniture]`
- `NECK`: Self-Resisted Neck Isometric `[BW]`, Supine Neck Curl `[Furniture]` ◆

Tier 2, deferred: One-Arm Push-Up, Pseudo Planche Push-Up, Towel Fly, Wall
Handstand Push-Up (both wall orientations), Wall Walk, Tiger-Bend Push-Up,
Feet-Elevated Chair Bench Dip, Pistol Squat variants beyond the existing entry,
Dragon Flag (full), Towel Rollout (Standing), L-Sit progressions, Sliding
Cross-Body Knee Tuck, Prone Neck Extension, Side-Lying Hip Abduction.

`[Hand Load]` entries, to add only if the bottles happen: Hand Load Lateral
Raise, Hand Load Curl, Side-Lying Rear Delt Raise, Hand Load Overhead Triceps
Extension, Hand Load Crunch, Floor Pullover ◆.

**Synergist credit** follows existing conventions exactly. Push variants carry
`+front delt, +triceps`; row variants carry `+biceps, +rear delt`; split squats
carry `+glutes`. Hip thrust variants carry **no** `+hamstrings`, matching the
deliberate decision already recorded in the database with its EMG reasoning.

### 8.4 Aliases

Add alias rows for the names <Person> is likely to actually type: "bulgarian" →
Bodyweight Bulgarian Split Squat, "pike" → Pike Push-Up, "table row" → Table
Inverted Row, "reverse nordic" → Reverse Nordic Curl, "copenhagen" →
Copenhagen Plank (Short Lever), "sliding curl" → Sliding Leg Curl. Alias inputs
are part of the render gate's known-name set, so this is the difference between
`/log` accepting his shorthand and rejecting it.

## 9. Travel mode design

### 9.1 Profile keys

Travel mode is configuration, not a new subsystem. In `<Person>/data/profile.csv`:

| Key | Travel value | New or existing |
|---|---|---|
| `training_context` | `travel` | **New** |
| `available_equipment` | `BW;Furniture;Towel;Door` | **New** |
| `strength_sessions_per_week` | `6` | Existing, changed from 3 |
| `session_target_min` | `20` | Existing, changed from 75 |
| `min_per_working_set` | `1.3` | Existing, changed from 2.3 |
| `muscle_priority_tiers` | an explicit all-maintain list | Existing, currently empty |

`available_equipment` uses the same semicolon format as
`muscle_priority_tiers`, so it reads with the existing parser.

### 9.2 Priority tiers, and a trap in the current default

Setting every muscle to `maintain` targets maintenance volume rather than growth
volume, which is exactly right for this block, and the tier model already
exists.

**The trap:** `muscle_priority_tiers` is currently empty for <Person>, and when it
is empty the code falls back to `BLOCK_EMPHASIS_DEFAULT`, which emphasises core,
side delts, rear delts, calves and traps. Two of those five cannot be trained in
a hotel room. Leaving the key empty would make `/coach` chase side delt volume
for three weeks and report failure every week. The key must be set explicitly.
Setting any single pair, for example `core:maintain`, is enough to suppress the
fallback and let everything else default to `maintain`.

### 9.3 Plan checks that break, and how each is handled

This is the part most likely to cause a bad surprise, so it is enumerated.

| Check | Why it fails | Handling |
|---|---|---|
| `min_loaded_flexion_exercises_per_week` = 1 | No core flexion exercise has an external load | **Travel override to 0**, with the exemption recorded in the report text. Satisfied honestly instead if the bottles happen. |
| `ARM_WEEK_SPEC` for triceps: 6 direct sets, 2 exercises | Nothing fails | **Passes honestly.** Skull crusher 3 sets plus chair bench dip 3 sets, two distinct exercises. This is why the chair dip is in the plan despite §5.5. |
| `ARM_WEEK_SPEC` for biceps: 6 direct sets, 2 exercises | The room produces 5 sets worth doing, across two exercises both labelled weak | **Travel override to 4 sets, 2 exercises**, exemption named in the report along with the quality caveat. Padding to 6 sets of self-resisted curls would pass the check without training the muscle. |
| `CORE_WEEK_SPEC.sets_per_session` keyed `upper`/`lower` | Six travel sessions have neither type | **New session type** `travel`, with a per-session core target of 1-2 and a weekly floor, rather than the per-session 4/2 split. |
| Cardio zone-2 target, 600 min per 28 days | Running is optional this block | Suppress the shortfall bullet when `training_context=travel`. Do not report it as a gap. |
| Equipment increment grid | No loads to round | Not applicable; bodyweight sets prescribe reps or seconds. |
| Deload cadence | Comes due mid-trip | Suppress. The loads cannot accumulate the fatigue a deload clears. |

Every override must be **named in the report**, not silently applied. A gate
that quietly stops checking is worse than one that fails loudly.

### 9.4 Progression tracking with no external load

The `estimated_1rm` engine excludes any set with weight at or below zero, so for
3-4 weeks it will produce nothing, and every gym lift will show a hole.

`training-science.md` §24.4 already ruled on the general version of this
problem: bodyweight progression "cannot be represented as a progression series.
Do not solve this in the schema. Solve it in programming." **This design follows
that ruling.** No schema change.

What is available without touching the schema:

- **Reps at zero weight are already stored.** A small addition can chart best
  reps and total reps per exercise across the block. That is a real progression
  series for a rep-progressed movement, and §24.4's prohibition is precisely
  about isometric holds, which log as `reps=0` plus a duration and genuinely
  cannot be a series.
- **Rung changes show up as different exercise names**, already supported.
- **Isometric holds keep logging a duration** and stay outside the progression
  view. That is a known limit, stated rather than papered over.
- **Any `[Hand Load]` set logs a real kg** and flows into the existing engine
  untouched. One more reason to find the bottles.

### 9.5 The volume count will read as normal, and that is half true

`weekly_volume_per_muscle` credits a set whenever reps are above zero, with no
weight check. Three sets of push-ups will count exactly like three sets of
bench press.

**This design does not change that**, for two reasons. Changing the credit rule
would rewrite every historical number in the tracker, and for muscle retention
the equal credit is defensible: hard low-load work does match heavy work for
size (§3.3).

For strength it is not defensible. So the report carries an explicit line
whenever `training_context=travel`: volume counts are not load-comparable to
gym blocks, and no strength conclusion should be drawn from this block's data.

### 9.6 What travel mode does not change

Sleep, heart rate variability, resting heart rate, wrist temperature, the
recovery score, the longevity score, thermal and light therapy logging, the swim
module, and every import path all keep working untouched. Travel mode is a
planning and reporting concern only.

## 10. Coming back

- **Tag the first three gym sessions** so the trend engine does not read the
  layoff as a strength regression. The existing mechanism keys on phrases in the
  Notes column, and its current list covers gym and equipment changes but has
  no phrase for a layoff. **Add a phrase**, for example "after travel", to
  `CONTEXT_CHANGE_NOTES_PATTERNS`. Writing "new equipment" instead would be a
  lie in the log.
- **Re-entry loads:** week 1 at roughly 85% of pre-trip working weights, week 2
  at roughly 95%, week 3 back to normal progression. Re-adaptation takes
  roughly a third to one times the layoff length, so 1 to 3 weeks (Ogasawara et
  al., Eur J Appl Physiol 2013;113(4):975-985; Halonen et al., Scand J Med Sci
  Sports 2024).
- **Expect the deadlift and squat to be down the most**, and expect them back
  fastest. Heavy-load expression is load-specific and nothing in a hotel room
  replaces it.
- **The running risk window is still open when he gets home.** If mileage ramped
  during the trip, do not ramp again in the first weeks back.
- **Reopen a cut phase** only after the first week back, so the scale rebound
  from travel food does not get read as fat gain.

## 11. Honest gaps, and what is unverified

Per the standing rule that a fallback must not masquerade as a result:

1. **No study has tested this scenario.** Every maintenance trial kept load
   heavy and cut volume. The low-load equivalence findings come from studies
   about *gaining*, applied sideways to *maintaining*. The direction is well
   supported. The exact dose is an inference.
2. **The biceps floor is lowered on purpose, and even the lowered version is
   weak.** The plan prescribes 5 direct biceps sets across self-resisted curls
   and towel isometric curls, and both are labelled maintenance-at-best for a
   trained lifter. The gate counts sets; it cannot count stimulus, so it could
   have been satisfied by padding to 6 sets of the same weak work. Lowering the
   floor to 4 and naming the exemption is the honest version. Nobody should
   later read a green arm check as evidence the biceps were trained.
3. **Every furniture and door load judgement is reasoning, not data.** No
   engineering source rates interior doors or hotel desks for human loading.
   The progressive load test is the only mitigation and it depends on <Person>
   doing it.
4. **The progression ladders are practitioner consensus.** Only one bodyweight
   ladder has been tested in a controlled trial: a progressive push-up
   elevation ladder that matched bench press over four weeks (Kotarsky 2018).
   The r/bodyweightfitness, Overcoming Gravity and Convict Conditioning rung
   orderings agree with each other, which is why they are credible, but the rung
   boundaries are convention.
5. **Two catalog entries have no direct study support**: the wall-lean lateral
   raise family and the bodyweight skull crusher. Both are widely used by
   practitioners. Neither turned up an EMG or intervention study. Flagged in
   place rather than dropped, because the alternatives are worse.
6. **Fat-free mass is estimated.** `Body Fat %` and `Lean Mass (kg)` have never
   been populated in `health_metrics.csv`, so the protein target derives from
   scale weight and an assumed body fat percentage.
7. **Sliding leg curls are conditional on floor type**, which is unknown. The
   carpet fallback is genuinely weaker and §5.4 says so.
8. **Nordic curls are conditional on furniture**, and the failure mode is
   landing face-first. The condition is written as a hard gate, not advice.
9. **Bands would reverse a deliberate decision.** A prior commit deleted all
   band entries with the reason "no band equipment available" and added two
   tests that fail on purpose if a band exercise name ever resolves again. If
   the bands arrive, re-adding them means editing those tests knowingly. Note
   that `Hip Circle Walk [Band]` is still in the WARMUP section, so the removal
   was not complete; that inconsistency predates this work and is not fixed here.

## 12. Open questions for the user

1. **Departure and return dates.** Needed to scope the block and the phase.
2. **Water bottles.** Two 1.5 litre bottles closes two of the three gaps and
   restores strength tracking. Worth it?
3. **Should the plan be one document for the whole trip, or should `/coach` run
   weekly as normal?** Weekly gives adaptation; one document works with no
   laptop and no data.
4. **Waist measurement before leaving?** It is the only leanness signal that
   survives a week of travel food, and the column is currently empty.

## 13. Out of scope

- The other person's tracker. Untouched.
- A general equipment-aware system where every exercise carries a full
  equipment profile and `/coach` filters by location. That was offered and
  declined in favour of this narrower travel mode.
- Changing the volume credit rule (§9.5).
- Any schema change to the monthly CSV (§9.4).
- Hotel gym support. If a gym turns up, `training_context` goes back to `gym`.

## 14. Rough implementation order

1. Catalog: Tier 1 entries, new tags, legend, aliases. Largest chunk. Must keep
   `validate_database()` and the catalog integrity tests green.
2. Profile keys and the equipment filter in exercise selection.
3. Travel overrides for the plan checks, each one named in the report.
4. The bodyweight rep-progression view and the report caveat lines.
5. The layoff phrase in the context-change list.
6. Tests for all of the above.

An implementation plan comes after this document is approved, not before.
