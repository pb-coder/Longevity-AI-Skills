# No-equipment training

Quick-reference for the coach when the user has no gym: travel, a closure, a
period at home with nothing but a room. Answers "what can actually be trained
here, how does it progress, and what is genuinely lost". Cite this doc by name
in coach callouts when invoking a specific rule.

**Read `detraining-and-minimal-dose.md` first.** That file establishes how small
the maintenance dose is, why proximity to failure becomes mandatory once the
load drops, and the 30-40% 1RM floor below which effort stops rescuing a set.
This file assumes all of it and does not restate it.

**The rule this file exists to enforce: name the gaps, never paper over them.**
Most no-equipment content substitutes something that shares a body part with the
missing exercise and calls it a replacement. Three muscle groups have no real
option in a bare room (§3), and a plan that quietly fills those slots with
activation drills is worse than a plan that says the slot is empty, because only
the second one tells the user what a resistance band would buy them.

## Quick Lookup

| When analyzing...                                  | Consult |
|----------------------------------------------------|---------|
| What the room makes possible at all                | §1 What a room affords |
| Whether a muscle can be trained here               | §2 Coverage verdict |
| Vertical pull, hamstrings, lateral delts, biceps   | §3 The four hard cases |
| Choosing the right difficulty and progressing it   | §4 Ladders and provenance |
| Not prescribing something insultingly easy         | §5 Too easy for a trained lifter |
| Whether furniture will hold                        | §6 Load-bearing improvisation |
| Catalog tags and how selection filters on them     | §7 Catalog mapping |

---

## §1 What a room affords

The environment is not "bodyweight". It is a specific inventory, and each item
unlocks specific patterns. Establish the inventory before writing a plan,
because the difference between a room with a sturdy table and a room without one
is the difference between having a horizontal pull and not having one.

| Object | Unlocks | Reliability |
|---|---|---|
| Floor, wall | Push, squat, core, wall-supported handstand work | Always present |
| Chair | Split squats, dips, Copenhagen planks, elevated feet | Usually; must be non-folding |
| Table or desk | Inverted rows, bodyweight skull crushers | **Variable — see §6** |
| Bed or sofa | Hip thrusts, back extensions, Nordic anchor, elevated feet | Usually; softness hurts bracing |
| Closed solid-core door | Steep sheet rows, doorway towel rows | **Variable — see §6** |
| Towel or bedsheet | Sliding leg curls, rollouts, body saws, door rows | Always present; sliding needs a hard floor |
| Hard smooth floor | Every sliding movement | **Coin-flip. Carpet removes a whole category** |
| Any hand-held weight | Lateral raises, curls, rear delt raises, loaded core | User-dependent |
| Pull-up bar | Vertical pull | Usually absent, and its absence is the biggest single loss |

**Two inventory questions change a plan more than any programming decision:**

1. **Is the floor hard or carpeted?** Sliding leg curls are the best hamstring
   exercise available without equipment (§3.2). On carpet they do not work and
   the hamstring slot degrades badly.
2. **Is there any hand-held weight at all, even 3 kg?** Roughly 3 kg closes the
   lateral delt and biceps gaps almost entirely (§3.3, §3.4) and, because such
   sets log an actual kilogram figure, it is also the only thing that keeps
   `estimated_1rm` and `progression_summary` alive during the period. Two filled
   1.5 litre bottles qualify. **Ask about this explicitly rather than assuming
   its absence**; users answer "no weights" to a question about dumbbells while
   holding a kitchen full of usable load.

## §2 Coverage verdict per muscle

Verdicts assume a bare room with chair, table, bed, door and towel, **no bar and
no external load**. Each verdict names the best option, and the weak ones say
why they are weak.

| Muscle | Best available | Verdict |
|---|---|---|
| Chest | Deficit push-up, decline push-up, archer push-up | **Good.** The only bodyweight pattern with direct trial validation against a barbell lift (§4). |
| Triceps | Bodyweight skull crusher, chair bench dip, diamond push-up | **Good.** The skull crusher progresses by surface height, spanning roughly a fourfold change in moment arm. |
| Quads | Bulgarian split squat, ATG split squat, reverse Nordic curl, shrimp squat | **Good.** Unilateral loading restores real relative load, and body-mass squat training does improve knee-extensor strength and size (Ogawa et al., Exp Physiol 2023, DOI 10.1113/EP090655). |
| Core | Towel rollouts, dragon flag ladder, long-lever plank, hollow work | **Good.** Widest useful leverage range of any category. |
| Shoulders, pressing | Pike push-up, elevated pike push-up, wall handstand push-up | **Good** for the delt as a presser. No trial compares it to an overhead press. |
| Adductors | Copenhagen plank, short then long lever | **Good.** +35.7% eccentric adduction strength in 8 weeks (Ishøi et al., Scand J Med Sci Sports 2016, DOI 10.1111/sms.12585). Needs one chair. Notoriously severe first-exposure soreness — start with 2 x 10-15 s short lever. |
| Calves | Single-leg raise off an edge, full stretch, straight knee, pause | **Good, and the evidence favours exactly what a room allows.** Standing knee-extended raises grew gastrocnemius ~9-12% against ~1-2% seated over 12 weeks (Kinoshita et al. 2023, PMC10753835), and long-muscle-length partials favoured gastrocnemius growth over full range (PMID 37015016). Soleus is the loser and grows poorly either way. |
| Back, horizontal pull | Table inverted row, doorway towel or sheet row | **Adequate, conditional on furniture.** The inverted row is EMG-validated with high middle-trapezius and meaningful lat, biceps and rear-delt activity (Snarr & Esco, JEPonline 2013; Fenwick et al., J Strength Cond Res 2009). |
| Glutes | Elevated single-leg hip thrust, deep step-up, torso-lean split squat | **Adequate.** Growth stimulus fine, top-end strength not. |
| Hamstrings | Sliding leg curl, Nordic regressions | **Conditional. See §3.2.** Floor-type and furniture-dependent. |
| Rear delts | Wide-elbow doorway towel row, prone Y-T-W raise | **Weak to adequate.** The row variant is the only loaded option. |
| Neck | Self-resisted isometrics, bed-edge curls and extensions | **Adequate.** Isometric neck programs raised strength 20-35% and muscle cross-sectional area 6-12% (Eur J Appl Physiol, PMID 11482549). |
| Traps | Nothing loaded | **Not served directly.** No shrug exists without load; traps ride on row synergist credit. |
| Erectors | Bed-edge back extension | **Weak.** Nothing approaches axial load. See `detraining-and-minimal-dose.md` §3. |
| **Back, vertical pull** | Steep sheet door row | **Not served. See §3.1.** |
| **Lateral delts** | Wall-lean side slide, self-resisted raise | **Not served. See §3.3.** |
| **Biceps, direct** | Underhand rows, self-resisted curls | **Not served directly. See §3.4.** |

**How long the three gaps are acceptable.** Given the detraining timecourse,
leaving vertical pull, lateral delts and direct biceps under-trained for three to
four weeks costs little that will not return quickly. Beyond roughly eight weeks
it stops being acceptable and the answer is equipment, not cleverer exercise
selection.

## §3 The four hard cases

### §3.1 Vertical pull with no bar

**There is no safe rung equivalent to a pull-up in a room with no bar.** Say this
rather than substituting.

What is real, in order:

1. **Steep-angle sheet row on a closed door.** Knot a bedsheet, throw the knot
   over the top of a **closed and latched solid-core** door, grip both tails and
   walk the feet in until the torso is 60-80° from horizontal. Lats and scapular
   depressors work through a real range under meaningful load. At that body angle
   the door carries well under half of bodyweight. **This is a high row, not a
   pulldown**, and should be named as such in a plan.
2. **Floor pullover with any hand-held weight.** The only genuinely
   lengthened-position lat exercise available in a room. Load-limited.
3. **Towel-over-door dead hangs and pull-ups: excluded.** Hanging a full adult
   bodyweight dynamically from a door top is a hinge and latch failure risk, it
   is worse on hollow-core doors, and it carries a crush hazard. No engineering
   source rates interior doors for it, and absence of a rating is treated here as
   prohibition.
4. **Doorframe finger-ledge hangs: theatre for the back.** The limit is finger
   flexor strength on a 1-2 cm decorative trim ledge, not lat strength, so the
   lats never approach failure. Trim is frequently glued or pinned and can
   detach. Real as grip training, not as back training.
5. **Isometric towel pulldowns: theatre beyond beginner level.** Unquantifiable
   effort, no eccentric.

### §3.2 Hamstrings

The category is entirely dependent on the room, so resolve it before writing the
plan rather than after.

**First choice, hard floor: sliding leg curl on towels.** Not a consolation
prize. It classifies as a high-intensity hamstring exercise alongside the Nordic
curl in EMG-based exercise classification (Tsaklis et al., Open Access J Sports
Med), has a dedicated NSCA *Strength and Conditioning Journal* exercise column,
and is used as a standard high-demand hamstring task in current EMG work (BMC
Sports Sci Med Rehabil 2025, DOI 10.1186/s13102-025-01435-5). It loads the
hamstring at long length across both hip and knee. Ladder: double-leg eccentric
only, double-leg full, single-leg eccentric, single-leg full. **Requires wood,
tile or laminate. On carpet it does not work.**

**Second choice, with a furniture anchor: Nordic curl regressions.** Nordics
have strong supporting evidence, including +21-24% biceps femoris fascicle
length and large eccentric strength gains (Presland et al., J Sci Med Sport
2018, PMID 29572976). Regressions in order: hip-hinged "razor", hands catching,
limited range onto a pillow stack, slow eccentric only. **Hard safety condition:
the anchor must not shift at 45° of lean, because the failure mode is landing
face-first.** A platform bed with no gap plus light furniture means no Nordic at
all, and the coach should say so instead of prescribing an improvised anchor.

**Third choice, carpet and no anchor: single-leg long-lever glute bridge.** This
is the weak path. Label it weak in the plan.

**Not available:** any loaded hip hinge. A bodyweight single-leg Romanian
deadlift is a lengthened-position and balance drill for a trained deadlifter, not
a strength stimulus, unless a hand-held weight and slow eccentrics are added.

### §3.3 Lateral delts

**The weakest category in no-equipment training, and the honest answer is
"nothing good".**

- **Wall lateral raise isometrics and wall-lean side slides** appear in
  practitioner sources; no EMG or hypertrophy study of these variants was found.
  That is an evidence gap, not evidence of absence. Mechanically they load the
  medial delt at short muscle length, at one joint angle, with no eccentric,
  which contradicts three things §4 and `training-science.md` §5 rely on.
- **Self-resisted raises** rest on the general no-load principle: maximal
  no-load contractions grew untrained elbow flexors comparably to 70% 1RM
  (Counts et al. 2016, PMID 27329807). Untrained subjects, ~4% thickness change,
  no trained-population replication. Evidence tier: **Thin** for this use.
- **Overhead pressing volume** gives the medial delt genuine synergist stimulus,
  which is why bodyweight athletes are not delt-less. It is not isolation.
- **The fix is about 3 kg.** Any hand-held weight held by a strap or handle is a
  real lateral raise load, since strict raises are a light-load exercise even for
  trained lifters. This is the highest-value item in §1's inventory question.

### §3.4 Direct biceps

**No bodyweight option matches a curl, but the category is not empty.**

- **Underhand rows** are the backbone: elbow flexion under real load with a real
  eccentric. Traditional inverted rows produce significantly higher biceps
  activity than suspension-device versions (Youdas et al.). Pulling toward the
  lower chest with elbows tight biases the elbow flexors. This is a compound, and
  it does not satisfy a *direct* biceps set requirement.
- **Self-resisted curls**: as §3.3, the best-evidenced no-load option and still
  **Thin** for a trained lifter.
- **Towel isometric curls**: angle-specific, no eccentric. Use three joint angles
  if used at all. Rank below everything above.
- **A pull-up bar or 3 kg in the hand** each solve this outright.

**Consequence for the plan checks.** `ARM_WEEK_SPEC` demands 6 direct sets and 2
distinct exercises per side of the elbow. Triceps clears this honestly in a bare
room. Biceps does not: the room produces about 5 sets worth doing, across two
exercises both rated Thin. **Padding to 6 sets of the same weak work satisfies
the check without training the muscle**, which is the exact failure mode
`CORE_WEEK_SPEC`'s distribution axes were built to prevent. Lower the floor
explicitly and name the exemption in the report.

## §4 Ladders and provenance

**Provenance first, because it governs how firmly the coach may speak.** Exactly
one bodyweight ladder has been tested in a controlled trial: a progressive
push-up elevation ladder that matched bench press for strength and muscle
thickness over four weeks (Kotarsky et al. 2018; see
`detraining-and-minimal-dose.md` §3). **Every other ladder below is practitioner
consensus** — the r/bodyweightfitness Recommended Routine, Steven Low's
*Overcoming Gravity* charts, *Convict Conditioning*'s Big Six, and GMB. They
agree with each other and with general progressive-overload principles, which is
why they are credible, but the rung boundaries are convention. Evidence tier:
**Thin** for any specific ordering, **Established** for the underlying principle
that leverage progression overloads.

**Advancement criterion, used throughout: 3 sets of 8 clean controlled reps, then
move up a rung. Below 3 sets of 5, move down.** *Convict Conditioning*'s much
higher rep gates (dozens to hundreds of reps per step) are endurance-biased and
too slow for a trained lifter; do not use them.

**Horizontal push:** wall push-up → incline push-up, lowering the surface → push-up
→ deficit or diamond push-up → archer push-up → one-arm incline push-up →
one-arm push-up.

**Vertical push:** pike push-up → elevated pike push-up → deficit elevated pike
push-up → wall walk plus handstand hold → back-to-wall handstand push-up, partial
range → full range → deficit handstand push-up. Hold rungs advance on 60 s
accumulated.

**Horizontal pull:** doorway towel row at a high angle → towel or sheet row near
horizontal → table inverted row → feet-elevated table row → wide or archer table
row → single-arm towel row.

**Vertical pull:** steep sheet door row, increasing steepness → single-arm steep
sheet row → **ceiling reached**. There is no further rung. See §3.1.

**Squat:** assisted squat → bodyweight squat → split squat → Bulgarian split
squat → beginner shrimp → intermediate shrimp → advanced shrimp or pistol. Add
hand-held load at any rung from the Bulgarian upward.

**Hinge:** long-lever bridge → single-leg long-lever bridge → sliding leg curl,
eccentric only → sliding leg curl, full → hand-assisted Nordic → Nordic curl.
Nordic rungs advance on 3 sets of 5 with a 5 s lowering phase before concentric
attempts are added.

**Core, by pattern:**
- Anti-extension: plank → long-lever plank → body saw → kneeling towel rollout →
  standing towel rollout.
- Anti-rotation: bird dog → plank shoulder taps → single-arm plank → single-arm
  row holds.
- Flexion: reverse crunch → hollow hold → hollow rocks → V-up → tuck dragon flag
  → full dragon flag.
- Anti-lateral-flexion: side plank → feet-elevated side plank → Copenhagen short
  lever → Copenhagen long lever.
- Rotation: poorly served without a cable or band. Keep loads modest and tempo
  slow, and do not let a rotation entry satisfy a flexion requirement, per
  `training-science.md` §24.

**Where a rung is too easy but the next is too hard**, insert 3-5 s lowering
phases and 2 s pauses at the longest muscle length before conceding to high
reps. See `detraining-and-minimal-dose.md` §4 for why that is a load dial rather
than a growth bonus.

**Movements with the widest useful range for a trained lifter**, i.e. the ones
worth building a plan around: the one-arm push-up line, the deficit handstand
push-up line, the Bulgarian to shrimp to pistol line with pauses and slow
eccentrics, the Nordic and single-leg sliding curl, single-leg deficit calf
raises with stretch pauses, the towel rollout and dragon flag lines, the
Copenhagen lever progression, and the bodyweight skull crusher with surface
height as the dial.

## §5 Too easy for a trained lifter

Do not prescribe these as working sets to someone who squats, benches and
deadlifts. They remain fine as warm-ups or mobility. This is triage reasoning,
not a sourced ranking.

- Wall push-up, knee push-up, incline push-up on a high surface.
- Bodyweight squat, air-squat AMRAPs, standard two-leg wall sit.
- Standard glute bridge and most two-leg bridge variants.
- Two-leg flat-floor calf raise, which has neither stretch nor meaningful load.
- Standard plank, floor side plank, crunches, bird dogs, Superman holds.
- Donkey kicks, fire hydrants, standing leg raises, and the general category of
  "activation drills".
- Mountain climbers, jumping jacks and burpees **as strength work**. Fine as
  conditioning, useless as hypertrophy line items.
- Any hand-held load under about 20 kg on a large compound pattern. Improvised
  load earns its place on small-muscle work — raises, curls, calf raises — and as
  an addition to unilateral leg work, not as a squat or press stimulus.

Borderline, enter mid-ladder rather than at the bottom: standard push-up, low
chair step-up, floor pike push-up.

## §6 Load-bearing improvisation

**Every load figure in this section is reasoning, not engineering data.** No
source rates domestic furniture or interior doors for human loading. The
mitigation is a progressive load test, which means it depends on the user
performing it, so the instruction belongs in the plan text and not only here.

- **Table inverted row.** Hanging under the edge with feet on the floor loads one
  edge with roughly half to two thirds of bodyweight, more with feet elevated. A
  solid wood dining table passes. A laminated particleboard desk with cam-lock
  legs may not. A wall-cantilevered desk must not be used at all. Test by
  pressing down hard with both hands, then one knee, before committing. Keep the
  line of pull inside the leg base so the table cannot tip.
- **Door rows.** Load runs over the door top onto hinges and latch. Solid-core on
  three hinges handles a fraction of bodyweight at a 45-70° body angle. Abort on
  any creak or hinge movement, never bounce, and do not use hollow-core doors.
  A sheet over the door top is mechanically kinder than pulling on handles, which
  are bolted for turning rather than for tens of kilograms of horizontal pull.
- **Chair bench dips.** Heavy, non-folding, pushed against a wall. Lower only to
  upper arm parallel: the bench dip has the largest shoulder-extension range of
  the dip family and repeated deep reps strain the anterior shoulder capsule. On
  a folding or wheeled chair, drop the exercise and add sets to a bodyweight
  skull crusher instead.
- **Chair dips between two chairs.** Excluded. Tipping risk plus the capsule
  concern above, and a safer exercise covers the same muscle.
- **Nordic anchors.** See §3.2. The condition is a hard gate, not advice.
- **Neck bridges.** Excluded on cervical compression grounds, independent of
  equipment. Bed-edge neck curls and self-resisted isometrics cover the muscle.

## §7 Catalog mapping

**Difficulty rungs are separate catalog entries, not a field.** Push-Up, Deficit
Push-Up and Archer Push-Up are three entries. This follows the precedent
recorded in `exercises-database.md` for Hanging Knee Raise against Hanging Leg
Raise, where collapsing two rungs into one name destroyed a progression series.
It is also what makes rung progression visible to `progression_summary` with no
schema change.

**Equipment tags** carry the environment dependency, so exercise selection can
filter on an allowlist of what the user actually has rather than on prose. The
tags this file's exercises use beyond `[BW]`:

| Tag | Means |
|---|---|
| `[Furniture]` | Chair, table, bed, desk, or a step or book edge |
| `[Towel]` | Towel or bedsheet, including use as a floor slider |
| `[Door]` | A closed, latched, solid-core door plus a towel or sheet |
| `[Hand Load]` | Any improvised hand-held weight, e.g. filled bottles or books |

A wall counts as `[BW]`; every room has one. `[Hand Load]` is the only tag in
this group whose sets carry a real kilogram figure, which is why it is separate
rather than folded into `[BW]`.

**Two reporting obligations during a no-equipment period**, both of which exist
because the pipeline will otherwise produce plausible-looking wrong numbers:

1. **`estimated_1rm` goes silent.** It excludes any set at or below zero
   kilograms, so unless `[Hand Load]` work is present the whole period produces
   no progression data, and every gym lift shows a gap. Rep counts at zero load
   *are* stored and can carry a rep-progression view; isometric holds log
   `reps=0` plus a duration and genuinely cannot, which is the case
   `training-science.md` §24.4 rules on.
2. **Volume credit does not check load.** `weekly_volume_per_muscle` credits a
   set whenever reps exceed zero, so three sets of push-ups count exactly like
   three sets of bench press. For muscle *retention* that equivalence is
   defensible on the low-load evidence. For *strength* it is not. State this in
   the report for any period flagged as equipment-constrained rather than letting
   the set count imply a comparison it cannot support.
