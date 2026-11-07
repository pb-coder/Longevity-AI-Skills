# Core training: evidence and detailed selection

Load when core selection changes, adherence is poor, a core claim is questioned, or the short operational rules need explanation. Operational rules remain in [training-science.md](training-science.md#24-core-training).

## §24 Core Training

The abdominal wall is a hypertrophy target and should be programmed like one: budgeted in
sets, loaded, progressed, and placed where it will actually be performed. It is not a
finisher, and it is not a core-stability project.

**Scope of the word "core" in this system.** `core` means the **abdominal wall** — rectus
abdominis and the obliques. The spinal erectors are a **separate** volume landmark
(`erectors`) fed by hinges and back extensions. This split is deliberate and is the
single most important fact in this section (see "Do compounds cover it?" below).

### §24.1 Dose

No published volume landmark for abdominal hypertrophy is derived from intervention data.
**No study has ever manipulated weekly set volume for abdominal hypertrophy.** The
dose-response meta-analyses this document relies on elsewhere — Schoenfeld 2017,
Baz-Valle 2022, Pelland 2025 — contain **zero abdominal outcomes** between them; they
measure limbs, pecs, delts and traps. Any MEV for core is a practitioner heuristic
extrapolated from limb data. Evidence tier: **Thin**. Say so when the number is
questioned; do not defend it as evidence-based.

Weekly landmarks (hard sets), aligned to RP's published **standard** abs table
(rpstrength.com, 2024-01-03) rather than its specialization column:

- MV 0 · MEV 4 · MAV 12 · MRV 20

**MV = 0 is defensible, conditionally.** Under 60 days of head-down-tilt bed rest — the
most extreme disuse obtainable in humans — transversus abdominis atrophied 18.3%
(P=0.00011) in inactive controls, but only 4.0-5.0% in groups doing lower-limb and
back-extension work with **no direct ab training at all** (Belavý, Gast & Felsenberg 2017,
Med Sci Sports Exerc 49(2):238-246). In chronically bedridden vs ambulatory elderly women,
rectus abdominis thickness showed **no difference**, while atrophy concentrated in the
antigravity muscles (Eur J Appl Physiol, PMID 21472438). Evidence tier: **Moderate**, and
conditional — MV 0 means "a lifter doing substantial compound work maintains abs without
direct sets", not "abs never atrophy". Note that neither study measured rectus abdominis
under training conditions.

**Direct ab work does grow the abdominals.** Gluppe, Engh & Bø 2023 (J Physiother
69(3):160-167), a randomised controlled trial with a no-intervention control (N=70,
12 weeks, curl-up variants 5 d/wk), found rectus abdominis thickness **+0.7 mm
(95% CI 0.1 to 1.3)**. Evidence tier: **Moderate** — a real RCT, but a postpartum
diastasis-recti population, untrained, dose never reported in sets, small effect.

**The per-session dose is `core_week_spec.sets_per_session` in `lib/constants.py`, not a
number in this file** — 4 on lower days, 2 on upper (D3), with the weekly target read from
`muscle_volume_targets["core"]`. Lower days carry the larger share because they have the
isolation slots to spare. The dose is enforced as a blocking validation error in both directions:
under-allocation is the failure this block exists to fix, over-allocation past the tolerance
means core is eating budget it did not earn. It costs a few minutes of a 60-minute session
either way; core does not take sets from chest, back or legs.

**Frequency: 3-4 sessions/week — for logistical reasons, not physiological ones.**
Frequency has negligible independent effect on hypertrophy once weekly volume is equated
(Pelland 2025), and 2x/week beats 1x/week (Schoenfeld, Ogborn & Krieger 2016, Sports Med
46:1689-1697). Spread the dose to keep any single session small, not because abs "recover
fast". Evidence tier: **Moderate**, extrapolated from limb data.

**Do not justify ab volume by fibre type.** Rectus abdominis is ~55% type I (Häggmark &
Thorstensson 1979, Acta Physiol Scand 107(4):319-25) — ordinary, near vastus lateralis
(~32%) and nowhere near soleus (~70%). The same paper reports "large inter-individual
variations, whereas the differences between the different muscles were minor or
non-existent". No meta-analysis stratifies the volume dose-response by fibre type, and
fatigue-resistance is not the same as a higher hypertrophic dose requirement. Evidence
tier: **Thin** — this inference has no outcome data behind it, for any muscle.

### §24.2 Timing — when in the session

**The rule: core goes inside the isolation/accessory block, as straight sets. Never before
the compounds. Never the final bullet of the workout.**

**Why not first.** Exercise order has **no effect on hypertrophy** — ES 0.03, p=0.862
(Nunes et al. 2021, Eur J Sport Sci, 11 studies). There is therefore no hypertrophy upside
to moving core earlier. Order *does* affect strength, and it favours whatever is placed
first: multi-joint exercises gain when trained first (ES 0.32, p=0.034), single-joint
exercises likewise (ES −0.58, p=0.032) — the two significant results point in opposite
directions, which is the whole finding. There is no privileged position, only a **primacy
effect** (Simão et al. 2012, Sports Med 42(3):251-65). Displacing compounds to put abs
first spends a real strength cost for no hypertrophy gain. Evidence tier: **Established**.

**Whether core before compounds impairs the compounds is unknown — genuinely.** No study
has measured squat or deadlift 1RM, reps-to-failure, load, or bar velocity after a
core-fatiguing protocol. The decrement cannot be quantified, and the pre-exhaustion
literature is **not** a valid substitute (it fatigues the prime mover, not the stabiliser).
What is known is mechanistic: trunk-extensor fatigue reduces maximal voluntary trunk force
~8.6% and raises L5/S1 moments and lumbar flexion during lifting; intra-abdominal pressure
at 40% and 80% raises trunk flexion stiffness 21% and 42%. Evidence tier: **Moderate** for
the mechanism, **absent** for the training outcome. Under that asymmetry — no upside,
unquantified downside — core-before-compounds is simply a bad trade.

**Why not last, either.** This is the part the literature does not cover and the tracker
must. The order-null finding above is conditional on the sets being **performed** — it comes
from controlled trials where subjects completed the protocol. **No study has ever tested
adherence by exercise position within a session.** In the field, the terminal slot is where
prescriptions go to die: it is the first thing cut when time binds and the last thing done
when fatigue binds. When the tracker's own logs show a core prescription in the final slot
going unperformed while everything above it is completed, that is the strongest evidence
available on this question, and it outranks a null that assumes compliance. Evidence tier:
**Thin** in the literature; **treat position as a real variable anyway.**

**The same argument binds direct arm work**, which is the other allocation the logs show
being truncated: nothing here is specific to the trunk, only to the slot. Both are enforced
— core or a biceps/triceps exercise as a workout's last bullet is a blocking validation error.
Close the session on something that is neither: rear delts, calves, a face pull. **Not "a
carry"** — `Suitcase Carry` is core (anti-lateral-flexion; see the slot-B table in §24.3
and the D4 note in §24.8), so closing on it trips the core placement error rather than
avoiding it. The only non-core carry is `Dumbbell Farmer Walk`, which is a finisher
budgeted outside the core allocation and earns no core credit wherever it sits.

**Separate core sessions are not supported.** No study has compared training a muscle in a
separate session vs appended to another at equated volume, and frequency effects are
negligible once volume is fixed. A separate session adds logistical cost for no adaptive
gain — the classic failure mode for a low-priority muscle. Evidence tier: **Thin**; the
recommendation against is on cost, not evidence of harm.

**Do not differentiate placement by movement type.** No study has compared anti-extension
vs anti-rotation vs flexion for pre-fatigue effects on subsequent compounds. The
"anti-extension ruins your brace" hypothesis is plausible and completely untested; the
categories overlap in rectus abdominis recruitment anyway. Evidence tier: **Thin** — do not
build a rule on it.

### §24.3 Selection

**Prefer movements that take external load.** This is the highest-leverage selection rule
and it is not about the muscle — it is about the system. A loaded movement is visible to
double progression (§15), to `estimated_1rm`, and to `progression_summary`. An unloaded hold
is invisible to all three: `reps=0, kg=0` rows classify as isometric holds and carry no load
axis, so a stalled plank is undetectable by design. **Prescribing loadable core is what makes
core progression legible at zero cost to the schema.**

But "prefer loadable" applied to a flat list is what produced six months of 94% spinal
flexion and zero anti-rotation, zero loaded carry: the loadable movements are almost all
flexion, so ranking by loadability ranks by pattern without saying so. The rule is therefore
scoped to a slot, not to the session.

**Two slots. Slot A is loaded flexion and is mandatory weekly. Slot B rotates
non-flexion by category.**

**Slot A — flexion, at least one loaded movement per week.** Progress DOWN the rungs across
blocks, not within a session. Existing catalog entries only:

machine (Ab Crunch Machine, Stomach Press Machine) → cable (Kneeling Cable Crunch, Standing
Cable Crunch, Cable Reverse Crunch) → hanging L1 (Hanging Knee Raise) → hanging L2 (Hanging
Leg Raise) → apparatus (Captain's Chair Knee Raise, Roman Chair Sit-Up) → floor (Crunch,
V-Up, Leg Raise, Bicycle Crunch, Flutter Kick, Mountain Climber).

Hanging Knee Raise is the rung below Hanging Leg Raise, not a synonym for it. Both hanging
rungs load with a dumbbell between the feet; Roman Chair Sit-Up loads weighted or declined.

**Slot B — rotating non-flexion, one category per session, cycled by block:**

| Category | Rungs, easiest first |
|---|---|
| Anti-extension | Dead Bug → Plank → Hollow Body Hold → Ab Wheel Rollout → L-Sit |
| Anti-rotation | Bird Dog → Cable Pallof Press → Plate Around the World |
| Anti-lateral-flexion | Side Plank → Suitcase Carry |
| Rotation | Cable Woodchop (both directions), Cable Russian Twist, Landmine Rotation, Rotary Torso Machine, Russian Twist, Roman Chair Side Bend |
| Loaded carry (finisher, budgeted outside the core allocation per D4) | Dumbbell Farmer Walk |

Ab Wheel Rollout is the only progressable rung in anti-extension; every other entry there is
a fixed-position hold whose one overload knob is time. Plate Around the World carries no
peer-reviewed EMG or intervention data at all — its anti-rotation classification is a
mechanistic analogy to the Pallof press, and it must never satisfy the flexion requirement.

The countable part of all this — how many distinct exercises, how many categories, how often
one movement may repeat, and the one-loaded-flexion-per-week floor — is `core_week_spec` in
`lib/constants.py`, enforced as blocking validation errors. Do not restate those numbers in prose.

**Prefer the movements <Person> will actually perform.** A prescription with a 0% completion
rate delivers 0 sets regardless of its evidence base. When adherence data exists in the log,
it outranks exercise-selection theory. Introduce a novel movement **early** in a session, not
in the last slot.

**Spinal flexion is safe for a healthy trainee, and it is the primary hypertrophy stimulus
for rectus abdominis.** The "never flex the spine" orthodoxy traces to Callaghan & McGill
2001 (Clin Biomech 16(1):28-37): **porcine cervical** (C3-C4) motion segments, in vitro,
cycled up to **86,400 times at 1 Hz — exactly 24 hours of continuous flexion**, producing 15
herniations across 26 specimens. A human doing 3x12 crunches performs **36 cycles** — roughly
**1/2,400th of that dose** — intermittently, in living tissue that remodels, at ~30° of
thoracic-dominant flexion, with intra-abdominal pressure unloading the spine (~18%).
Contreras & Schoenfeld 2011 (Strength Cond J 33(4):8-18 — note Contreras is first author)
review this in full and conclude that dynamic spinal flexion offers a **"favorable risk to
reward ratio provided that trainees have no existing spinal injuries or associated
contraindications, such as disc herniation, disc prolapse, and/or flexion intolerance"**.
They further note ~74% of disc-degeneration variance is hereditary, and that a crunch elicits
**~50% MVC of rectus abdominis** vs 20%/10%/10% for external obliques, internal obliques and
TVA. Evidence tier: **Established** for the critique of the porcine extrapolation;
**Moderate** for the positive safety claim, which rests on absence of contrary human evidence
plus mechanism.

**This is a deliberate trade and it should be stated plainly:** this system resolves toward
spinal flexion for rectus hypertrophy and against anti-extension-only orthodoxy. **The cost:**
if <Person> has or develops a disc herniation, prolapse, or flexion intolerance, this
recommendation inverts and loaded flexion is contraindicated. That is the whole of the
downside, and it is conditional on a diagnosis the tracker cannot see. An anti-extension-only
policy is not evidence-based, and it would exclude precisely the most progressively loadable
movements.

**Pattern coverage: at least one LOADED spinal-flexion movement per WEEK, not per session.**
Rectus abdominis is the hypertrophy target and flexion is how it is loaded through a range of
motion, so flexion stays mandatory. The per-session version of this rule was withdrawn on
2026-08-02: on a 4-on-lower / 2-on-upper budget it spends at least one bullet per session on
flexion, which on an upper day is the entire core allocation, and the best a scheduler can do
under both it and a pattern-category requirement is a 50% flexion floor. It cannot coexist
with a distribution target because it IS a distribution target, pointed at one pattern. It
was one of three rules that produced six months of 94%-flexion logged core work. The weekly
form is stricter about what counts (the movement must carry external load) and is enforced by
`core_week_errors`, not by prose.

**Lengthened position (§5) does not apply here — not because it's wrong, but because it is
untested for this muscle.** No study has tested long-muscle-length or lengthened-partial
training for any abdominal muscle; the entire evidence base for §5 is quads, hamstrings,
calves and elbow flexors/extensors. The mechanistic case is unresolved in both directions:
rectus abdominis has the **longest optimal fascicle length of any trunk muscle — 28.3 cm
(SD 4.2)** (Delp et al. 2001, J Biomech 34(3):371-375), which argues it *can* be meaningfully
lengthened; but 3-4 tendinous intersections make it functionally a series of short bellies,
so per-segment excursion may be far smaller than trunk ROM suggests. No data resolves this.
Evidence tier: **not established for this muscle.** Accordingly **no core exercise carries
the `◆` tag, and that absence is deliberate.** Note also that for abs the lengthened-position
candidates (ab wheel, dragon flag) and the progressively-loadable candidates (cable crunch,
hanging leg raise, machine crunch) are largely **disjoint** — tagging `◆` would steer
selection toward movements that cannot be overloaded.

**Regional coverage: "upper abs vs lower abs" — the regions are real, the prescription is
not.** Both halves of this matter:

- Regional *hypertrophy* of rectus abdominis is real. MRI in professional tennis players
  (Sanchis-Moysi et al. 2010, PLOS ONE 5(12):e15858): rectus abdominis volume **58% greater**
  than controls, non-dominant side **35% greater** than dominant (P<0.001), with the
  asymmetry increasing linearly from the L1-L2 disc to the pubic symphysis (**r=0.97,
  P<0.001**). Replicated in professional footballers (Idoate et al. 2011, PLOS ONE 6(4):e19022,
  **+26%**). Evidence tier: **Established** that it occurs.
- Regional *activation* differences exist but are conditional: they appear when the pelvis
  moves (Willett et al. 2001, JSCR 15(4):480-5 — reverse curl produced the greatest lower
  rectus activity; Marchetti et al. 2011, J Sports Sci Med 10(2):322-7 — curl-up upper>lower
  p=0.02, leg raise the reverse), and vanish when pelvic motion is controlled (Lehman & McGill
  2001, Phys Ther 81(5):1096-101; Clark et al. 2003, JSCR 17(3):475-83, both null). Evidence
  tier: **Moderate**.
- **But the inference from activation to growth is broken.** Zabaleta-Korta et al. 2024
  (Isokinetics Exerc Sci, doi 10.3233/IES-230079, N=36) tested exactly this and found
  **surface EMG does not predict regional hypertrophy.** And **no intervention has ever tested
  crunches vs leg raises for regional rectus growth.** Evidence tier: **Promising** — against
  the prescription.

**So: do not program "upper" and "lower" ab volume as separate targets — that specific
prescription is not supported.** It is, however, free to cover both patterns, so do: one
trunk-flexion movement (crunch/cable crunch) and one hip-flexion-with-posterior-pelvic-tilt
movement (hanging/reverse/knee raise) across the week. This is §17 regional coverage applied
at zero cost, not a claim that you are targeting a region.

**Note on §17's citations:** Burke et al. 2024 and Zabaleta-Korta et al. 2021 are **lower-body
studies**. Citing them *for abs* is an extrapolation. Abs do not need to borrow the principle
— Sanchis-Moysi 2010 and Idoate 2011 are direct human evidence and are stronger for the
purpose.

**Obliques and waist width.** Direct rotational loading does hypertrophy the lateral wall,
but the effect is small, occurs **proximally** (up by the ribs, not at the waist's narrowest
point), and was measured at ~25 h/week of professional sport (Sanchis-Moysi et al. 2013,
Sports Biomech 12(1):54-67: obliques+TVA **18% asymmetric**, proximal segments only — the
*opposite* regional distribution to rectus abdominis in the same athletes). **No data exists
on waist circumference from oblique training in normal trainees.** Evidence tier: **Moderate**
for the mechanism, **Thin** for any quantitative claim. Treat as a non-concern; do not use it
to justify avoiding rotation work, and do not chase rotation volume either.

**Transverse abdominis gets no volume and no landmark.** MRI cannot separate it from the
obliques — the research measuring this reports a combined "obliques+transversus" variable
because segmenting TVA alone was not feasible. It is the deepest layer of the abdominal wall
and is **never visible**. Vacuums produce **very low rectus abdominis activity** (Willett et al.
2001), and the clinical rationale for TVA-specific training is contested (Lederman 2010, "The
Myth of Core Stability"). Evidence tier: **Established** — do not track it.

### §24.4 Progression

Core progresses by **double progression on load (§15)**, exactly like any isolation lift: hold
the weight, push reps to the top of the range across all sets, then add load and reset. This
is the entire reason §24.3 prefers loadable movements — it makes core progression a solved
problem rather than a new one.

For a movement without a load axis, the progression levers are time-under-tension, leverage,
and range of motion. **The tracker's 18-column CSV cannot represent any of them as a
progression series** — a hold logs as `reps=0, kg=0` plus a duration and is classified as an
isometric hold; `estimated_1rm` and `progression_summary` cannot see it. **Do not solve this in
the schema.** Solve it in programming: prescribe movements that take load. A weighted movement
is already fully tracked today.

If a bodyweight movement must be used, prefer one that accepts external load later (hanging
leg raise with a dumbbell between the feet) over one that does not (plank).

**Never mark a core set optional.** A set qualified with "if you can make it" is not
prescribed volume; it is a suggestion, and it will read as the first thing to cut.

### §24.5 Do compounds cover it? No — and the reason is precise

This is the most common argument against direct ab work, and it deserves a straight answer
because it is **half right**.

**The half that is right:** heavy compounds are an excellent stimulus for the **spinal
erectors**. Hamlyn, Behm & Young 2007 (JSCR 21(4):1108-1112, n=16): lumbar-sacral erector
spinae activation during an 80% 1RM squat exceeded the superman and side bridge by **65.5%
and 53.1%**. Nuzzo et al. 2008 (JSCR 22(1):95-102, n=9 trained): erector activity was always
greater in squats and deadlifts than in stability-ball work. Evidence tier: **Established**.

**The half that is wrong — and it is hiding in the same abstracts.** Both studies report
**null results in the abdominals**:

- Hamlyn 2007: *"There were no significant changes in EO or LA activity."*
- Nuzzo 2008: *"No significant differences were observed in RA and EO during any of the
  exercises."* Their own conclusion names the muscle: *"SQs and DLs are recommended for
  increasing strength and hypertrophy of the **back extensors**."*
- Martuscello et al. 2013 (JSCR 27(6):1684-1698), routinely invoked here, measured **lumbar
  multifidus, TVA and QL — not rectus abdominis at all.**

**So the flagship citations for "compounds train your core" are papers whose abdominal
findings were null and whose conclusions were about the erectors.** This system already
routes that contribution correctly: `erectors` is its own landmark, fed by deadlifts, RDLs,
good mornings and back extensions. Nothing is being missed — the compound contribution is
already counted, under the right muscle.

Mechanistically this is exactly what you would expect (see §24.2): the abs work isometrically,
at short-to-neutral length, for a few seconds per rep, and the set ends when the prime mover
fails — the least favourable configuration in the isometric hypertrophy literature (Oranchuk
et al. 2019, Scand J Med Sci Sports: long-length isometrics 0.86-1.69%/wk vs 0.08-0.83%/wk at
short lengths).

**Honest limit — the experiment has not been run.** No study has compared compound-only vs
compound-plus-direct-ab training with rectus abdominis thickness as the outcome. **Neither
side has hypertrophy evidence.** The case for direct work rests on the EMG nulls above, the
absence of any positive evidence for the compound-only position, and general hypertrophy
principles (load, range of motion, progressive overload) that bracing lacks. That is a
reasonable inference, not a demonstrated fact. Evidence tier: **Promising**, not Established.
Direct ab work is a **low-cost bet with sound mechanistic rationale and no evidence against
it** — which is a more honest recommendation than "science says you must train abs".

**Do not count a stabiliser as a fractional set.** The ~0.5-synergist convention in §1 was
reasoned from concentric prime-mover/synergist pairs (triceps in a bench press), where the
synergist shortens under load, through a range of motion, at a load proportional to the prime
mover. An isometric stabiliser shares none of those properties. Schoenfeld, Grgic, Haun,
Itagaki & Helms 2019 (Sports 7(7):177) — the source usually invoked for fractional counting —
**declines to endorse it**, advising practitioners to *"continue to view set-volume
prescription on a 1:1 basis"* and noting that a stabiliser's contribution *"presents a
difficult challenge to objectively quantify in the practical setting"*. Evidence tier:
**Thin** — any specific fraction is invented. Accordingly, squats and deadlifts grant
**no** `+core`.

### §24.6 Visibility

**Abdominal visibility is dominated by body fat, not by ab training volume. Spot reduction
does not occur.** Three independent designs:

- **Vispute et al. 2011** (JSCR 25(9):2559-2564): N=24, 7 ab exercises, 5 d/wk for 6 weeks,
  isocaloric diet. **No significant effect on body weight, body fat %, android fat,
  abdominal circumference, or skinfolds.** The training worked — curl-up endurance rose from
  32 ± 9 to 47 ± 13 reps. The fat did not move.
- **Katch et al. 1984** (Res Q Exerc Sport 55(3):242-247): 27 days, **5,004 sit-ups**, fat
  biopsies at abdominal, subscapular and gluteal sites. Cell diameter fell at **all three**
  with **no significant difference in rate between sites** — the trained site was not
  privileged.
- **Ramírez-Campillo et al. 2013** (JSCR): 12 weeks of **single-leg** press, 960-1200
  reps/session. Fat loss was **significantly greater in the upper body and trunk than in the
  trained leg** (p<0.05).

Evidence tier: **Established.**

**But do not overclaim it.** Visibility is surface relief — a contrast phenomenon with both
muscle thickness and overlying fat in the equation. Whether hypertrophied abs are visible at a
higher body fat than untrained abs has **never been tested**: no study compares visibility
against muscle thickness at matched body fat. Evidence tier: **Thin** — mechanistically
plausible, empirically untested. The defensible formulation is: **body fat dominates;
training determines what becomes visible when fat drops. Training does not uncover the
muscle; it is what is uncovered.**

**Never quote a body-fat percentage for visible abs.** No peer-reviewed source establishes
one. Every number in circulation (10-14%, 8-10%, 6-12%) traces to commercial sources — medspas,
scan vendors, supplement blogs. It is lore with a numerical veneer. Evidence tier: **Thin**,
and the honest statement is directional only: lower body fat → more visible abs, with
substantial individual variation in fat distribution.

Nutrition strategy is out of scope for this document; note only that a fat-loss phase and an
ab-hypertrophy phase are not in conflict — the training preserves and builds the muscle that
the deficit reveals.

### §24.7 Do not sell core on performance transfer

The force-transfer argument is weaker than commonly claimed and should not be the
justification for prescribing core. Reed, Ford, Myer & Hewett 2012 (Sports Med 42(8):697-706),
a systematic review of 24 studies, concludes: **"Targeted core stability training provides
marginal benefits to athletic performance."** Study quality was mediocre (PEDro 6.4 ± 0.7 for
RCTs, 4.6 ± 1.1 for non-randomised), core training was **"rarely isolated"** — bundled into
comprehensive programmes, so attribution is impossible — and most positive results came from
recreationally active subjects. Seven studies reported max-lift improvements including 1RM
squat and bench, but none isolate core work as the cause. Hibbs et al. 2008 (Sports Med
38(12):995-1008), a narrative review, similarly notes a lack of empirical support for direct
performance benefits.

**No study cleanly isolates direct ab training and measures squat or deadlift 1RM in trained
lifters.** Evidence tier: **Established** that the transfer claim is weak. Justify core on
hypertrophy. Bracing and force transfer are a welcome side effect and a tiebreaker between
otherwise-equal movements — not a reason to prescribe.

### §24.8 What NOT to do

- **Do not put core last.** The terminal slot is where prescriptions go unperformed. Order
  does not affect hypertrophy (Nunes 2021, ES 0.03) — but that null assumes the sets happen.
- **Do not put direct arm work last either.** Same reasoning, same enforcement: biceps or
  triceps as a workout's final bullet is a blocking error, not a stylistic preference.
- **Do not put core before the compounds either.** No hypertrophy upside (same null), a real
  primacy cost to the lifts (Simão 2012), and an unquantified trunk-fatigue risk.
- **Do not prescribe a movement <Person> has never performed and place it in the last slot.**
  If the log shows a prescription repeatedly unperformed, the prescription is the problem, not
  the athlete. Change the movement or change its position.
- **Do not mark a core set "if you can make it".** Prescribe it or don't.
- **Do not count squats or deadlifts as ab volume.** Their abdominal EMG findings are null;
  the contribution belongs to `erectors` and is already counted there.
- **Do not credit two-handed carries with ab work.** Rectus abdominis sits at **3.9% MVC**
  during a two-handed 30 kg farmer's walk (McGill, Marshall & Andersen 2013, Ergonomics
  56(2):293-302) — indistinguishable from standing. **The one-handed carry is the exception,
  and it is not a technicality.** Ellestad et al., *Int J Exerc Sci* 2024;17(1):480-490:
  a suitcase carry reaches **33.0% MVIC in the contralateral external oblique**, against
  **34.5%** for a plank, while the bilateral farmer's carry reaches only **11-14%** because
  the two loads cancel. The asymmetry IS the mechanism, so **both sides must be performed** —
  one side is half the prescription, not a lighter version of it. Per decision D4,
  `Suitcase Carry` counts as core and is budgeted inside the core allocation;
  `Dumbbell Farmer Walk` is a finisher budgeted outside it and still earns no ab credit.
- **Do not program "upper" and "lower" abs as separate volume targets.** The regions are real;
  the EMG-to-growth inference is broken (Zabaleta-Korta 2024).
- **Do not track transverse abdominis.** MRI cannot isolate it and it is never visible.
- **Do not justify ab volume or frequency by fibre type.** Rectus abdominis is ~55% type I —
  ordinary — and no evidence shows fibre type moderates the volume dose-response.
- **Do not quote a body-fat percentage for visible abs.** No peer-reviewed source exists.
- **Do not tell <Person> "abs are made in the kitchen" as a reason to skip training them.**
  Body fat governs visibility; training governs what is visible. Both are required, and only
  one of them is this document's job.
- **Do not defend the landmarks as evidence-based.** No study has manipulated weekly set
  volume for abs. They are practitioner heuristics extrapolated from limb data. Say so.
