# Detraining and the minimal effective dose

Quick-reference for the coach whenever the normal training stimulus is
interrupted or deliberately reduced: travel, illness recovery, a gym closure, a
period with no equipment, a planned low-volume phase, or a return after any of
those. Mirror of how `bulking-science.md` services bulk phases and
`swim-coaching.md` services the swim card. Cite this doc by name in coach
callouts when invoking a specific rule so the user can trace the reasoning.

**Read this together with `no-equipment-training.md`** when the interruption is
an equipment problem rather than a time problem. This file answers "how much do
I need, and what will I lose"; that one answers "what can I actually do in the
room I am in".

**The framing that matters most.** The instinctive response to an interruption is
to treat it as damage control. For interruptions under about four weeks that
framing is wrong and it leads to bad advice: over-prescribing volume the person
cannot recover from, and worrying about muscle loss instead of the two things
that actually go wrong, which are an energy deficit stacked on a weak stimulus
(§6) and an injury from ramping something new (§5).

## Quick Lookup

| When analyzing...                                    | Consult |
|------------------------------------------------------|---------|
| How much a break actually costs                      | §1 Detraining timecourse |
| How little training preserves what the user has      | §2 Minimal effective dose |
| Whether an unloaded or light-load plan can work       | §3 The load floor |
| Making a light-load session hard enough              | §4 Overload without external load |
| Adding running while lifting less                    | §5 Concurrent training and injury risk |
| Diet during a reduced-stimulus period                | §6 Protein and energy availability |
| Prescribing the first weeks back                     | §7 Re-adaptation |
| What not to claim                                    | §8 Limits of this literature |

---

## §1 Detraining timecourse

**Two to four weeks of complete cessation costs a trained lifter almost nothing
measurable.** This is the single most useful number in this file and it is
routinely overestimated by both coaches and trainees.

Fourteen days of complete cessation in trained power athletes: bench press 1RM
−1.7% and squat 1RM −0.9%, neither statistically significant, with vertical jump
unchanged (Hortobágyi et al., Med Sci Sports Exerc 1993;25(8):929-935). Trained
men held their strength across a two-week break in a separate trial (Hwang et
al., J Strength Cond Res 2017;31(4):869-881). Evidence tier: **Established** for
the two-week figure in trained populations.

Longer horizons, from a systematic review of resistance-training-then-cessation
studies: hypertrophy was largely preserved through roughly 12 to 24 weeks
against non-training controls, significant muscle size loss emerged at 31 to 52
weeks, and strength remained above control until roughly 32 to 48 weeks
(*Muscles* 2022;1(1):1-15). Evidence tier: **Moderate** — the review pools
heterogeneous populations and most constituent studies are not in well-trained
lifters.

**What decays first, and it is not whole-muscle size:**

1. **Eccentric-specific strength.** −12% in 14 days, decreasing in every
   subject (Hortobágyi 1993). The fastest-decaying quality measured anywhere in
   this literature. Evidence tier: **Moderate** (one study, small n, consistent
   direction).
2. **Type II fibre cross-sectional area.** About −6.4% in 14 days, with type I
   fibre area unchanged (Hortobágyi 1993).
3. **Recently acquired neural adaptations.** Vastus lateralis EMG fell 8-13% over
   the same fortnight. Long-held adaptations are more durable than recent ones
   (Mujika & Padilla, Sports Med 2000;30(2):79-87 and 30(3):145-154).
4. **Whole-muscle size.** Detectable single-digit percentage losses appear
   somewhere in the 4-8 week range, not before.

**A practical restatement for the coach, by duration of the interruption:**

| Break | Expect |
|---|---|
| Under 2 weeks | Nothing measurable. Do not write a recovery narrative. |
| 2-4 weeks | Eccentric strength and type II fibre area down. 1RM broadly intact. |
| 4-8 weeks | Whole-muscle size losses become detectable. 1RM in the big lifts down. |
| 8+ weeks | Progressive, but still far above untrained baseline for months. |

Deliberately structured breaks are not even a net loss over a long enough
horizon: across 24 weeks, three separate 3-week cessation blocks produced the
same total bench press cross-sectional area and 1RM gains as continuous training
(Ogasawara et al., Eur J Appl Physiol 2013;113(4):975-985). CSA fell measurably
within each 3-week break and was regained rapidly. Evidence tier: **Moderate**,
and the subjects were untrained men, so do not present this as licence for a
trained lifter to take routine breaks.

**Do not say "you will lose muscle" for a sub-four-week interruption.** It is not
supported, and it pushes the user toward volume they cannot recover from in a
compromised environment.

## §2 Minimal effective dose

**The anchor study.** After 16 weeks of leg resistance training at 27 weekly
sets, participants moved to either one third (9 sets/week) or one ninth (3
sets/week) of that volume, in a **single weekly session**, with the load held
constant, for 32 weeks. Adults aged 20-35 maintained both strength and muscle
size at as little as one ninth of prior volume. Adults aged 60-75 maintained
strength but not muscle mass at the low doses (Bickel, Cross & Bamman, Med Sci
Sports Exerc 2011;43(7):1177-1187). Evidence tier: **Established** for the
younger cohort.

A narrative review of the same question reached the same place: strength and
muscle size were maintained for up to 32 weeks on one session a week and one set
per exercise, **provided relative load was maintained**, and it names intensity
rather than volume or frequency as the variable that must not drop (Spiering et
al., J Strength Cond Res 2021;35(5):1449-1458). Endurance and VO2max were
maintained for at least 15 weeks on two sessions a week at maintained intensity.

Reduced frequency after a training block preserved half-squat 1RM and quadriceps
cross-sectional area over the reduced period, where cessation did not (Tavares et
al., Eur J Sport Sci 2017;17(6):665-672).

**Useful upper reference, for when the goal is still to gain rather than hold:**
one set of 6-12 reps at 70-85% 1RM taken with high effort, two to three times a
week, still produces significant if suboptimal 1RM gains in trained men
(Androulakis-Korakakis et al., Sports Med 2020;50(4):751-765). Roughly four
weekly sets per muscle is a pragmatic floor for continued progress, and
supersets, drop sets and rest-pause halve session time at equated volume
(Iversen et al., Sports Med 2021;51(10):2079-2095).

**The caveat that governs every number above, and it is not a small one.** Every
maintenance trial reduced *volume and frequency* while holding *load* constant.
None reduced the load. So "one ninth of volume maintains you" is evidence about
a person still lifting heavy twice a month, not about a person doing push-ups
every day. §3 covers what can be borrowed from the low-load literature to bridge
that gap, and §8 states plainly what the bridge is not.

**How this lands in the tracker's own vocabulary.** The `maintain` priority tier
in `constants.py` targets MV, and MV is the right target for any
reduced-stimulus period. Setting every muscle to `maintain` is the mechanically
correct expression of this section. Note the trap: when the
`muscle_priority_tiers` profile key is **empty**, the code falls back to
`BLOCK_EMPHASIS_DEFAULT`, which nominates specific muscles for emphasis. During
a constrained period that fallback will chase volume for muscles the environment
cannot train. The key must be set explicitly rather than left blank.

## §3 The load floor

**Where low loads work.** With sets taken to failure, low loads (60% 1RM or
below) and high loads produce equivalent hypertrophy; 1RM strength gains
significantly favour heavy loads (Schoenfeld et al., J Strength Cond Res
2017;31(12):3508-3523, meta-analysis). In trained men across 12 weeks, 30-50%
1RM and 75-90% 1RM produced equal hypertrophy and broadly equal strength when
all sets went to failure, with a small bench 1RM advantage to the heavy
condition (Morton et al., J Appl Physiol 2016;121(1):129-138). Evidence tier:
**Established** for the hypertrophy equivalence, **Established** for the strength
non-equivalence.

**Where they stop working.** With volume load equated, 20% 1RM produced inferior
hypertrophy and strength against 40-80% 1RM. Roughly **30-40% 1RM is the floor**
below which hard training under-stimulates and more effort does not rescue the
set (Lasevicius et al., Eur J Sport Sci 2018;18(6):772-780). Evidence tier:
**Moderate**.

**Failure becomes mandatory, not optional.** Training to failure improved
hypertrophy at 30% 1RM but not at 80% 1RM (Lasevicius et al., J Strength Cond
Res 2022;36(2):346-351 — study confirmed, exact page range unverified).
Independently: hypertrophy increases as reps-in-reserve decreases, while strength
gains are largely indifferent to proximity to failure (Robinson et al., Sports
Med 2024;54(9):2209-2231, meta-regression; Refalo et al., Sports Med
2023;53(3):649-665, small effect favouring closer to failure).

**The operational consequence.** A heavy session tolerates 2-3 reps in reserve
and loses very little. A light-load session at 2-3 reps in reserve loses most of
its stimulus. When prescribing at low load, write 0-2 reps in reserve and say
in the plan that it is a requirement rather than an intensity suggestion.

**The unilateral lever is the main tool against the floor.** Standing on one leg
or pressing with one arm roughly doubles the fraction of bodyweight the working
limb carries, which is what moves an exercise back above the 30-40% floor. This
is mechanical reasoning, not a measured effect size; no trial has compared
unilateral against bilateral bodyweight training for hypertrophy.

**Direct validation exists for one movement.** Progressive push-up training
matched bench press training for strength and muscle thickness over four weeks
in moderately trained men (Kotarsky et al., J Strength Cond Res 2018;32(3):651-659
— page range unverified), and push-ups load-matched to 40% 1RM bench press
matched that condition for hypertrophy and strength over eight weeks (Kikuchi &
Nakazato, J Exerc Sci Fit 2017;15(1):37-42). Do not generalise these two results
to every bodyweight movement; generalise the principle, and note which movements
have no such trial.

**What cannot be preserved without external load**, stated so the coach does not
promise it:

- **Heavy-load expression.** 1RM is partly a practised skill and the load-specific
  literature above is consistent that light training underperforms for it.
- **Absolute eccentric and high-force capacity**, which is also the fastest thing
  to decay (§1).
- **Axial loading of the trunk.** Nothing bodyweight approaches the compressive
  and bracing demand of a heavy squat or deadlift. Erector work is the honest
  casualty of any equipment-free period. Reasoning, not a trial.

## §4 Overload without external load

Ranked by evidence quality, best first. Use the top three before reaching for
the rest.

1. **Proximity to failure.** See §3. This is the precondition for everything
   else in the list, not one option among many.
2. **Long muscle length.** Isometric holds at long muscle length produced
   0.86-1.69% growth per week against 0.08-0.83% at short length, at equated
   volume (Oranchuk et al., Scand J Med Sci Sports 2019;29(4):484-503). This is
   the same principle as `training-science.md` §5 and it is worth more in an
   unloaded environment than in a gym, because leverage and range are the only
   dials available. Prefer deficits, elevated hands, deep split positions and
   pauses at the stretched position.
3. **Unilateral loading.** §3.
4. **Leverage and range manipulation.** Feet elevated, hands lowered, longer
   lever arms. Mechanically sound; the specific kinetic figures often quoted for
   push-up variants were not verified.
5. **Tempo, 3-5 second lowering phases.** Hypertrophy is similar across rep
   durations from roughly 0.5 to 8 seconds, with durations beyond 10 seconds
   likely inferior (Schoenfeld et al., Sports Med 2015;45(4):577-585). So slow
   eccentrics are **free difficulty with no penalty, not extra growth**. Present
   them as a load dial. Eccentric-emphasised training trends slightly better
   than concentric for hypertrophy but not significantly (Schoenfeld et al., J
   Strength Cond Res 2017;31(9):2599-2608).
6. **Rest-pause and drop sets.** Equivalent to traditional sets at equated
   volume, in less time; not superior (Prestes et al., J Strength Cond Res
   2019;33(Suppl 1):S113-S121; Enes et al., Appl Physiol Nutr Metab 2021; Sødal
   et al., Sports Med Open 2023;9:66). "Myo-reps" is a branded rest-pause
   variant with no direct trial of its own; its evidence is inherited.
7. **Mechanical drop sets.** No direct trials. Extrapolated from the drop-set
   literature.
8. **Cluster sets.** Designed to preserve velocity and power within a session,
   not to add hypertrophic stimulus. Low relevance here.

**Two things to stop saying.** "Slow eccentrics build more muscle" overstates
item 5. The "effective reps" model, where only the last handful of reps before
failure count, is a practitioner heuristic that is mechanistically plausible via
motor-unit recruitment and has never been validated as a countable quantity.
Evidence tier for both: **Thin**.

## §5 Concurrent training and injury risk

**Interference is mostly overstated at moderate doses.** The 2012 meta-analysis
found concurrent training reduced hypertrophy and strength, that **running
interfered where cycling did not**, and that the effect scaled with endurance
frequency and duration (Wilson et al., J Strength Cond Res 2012;26(8):2293-2307).
A later meta-analysis of 43 studies found no significant compromise to
hypertrophy or maximal strength, with only explosive strength attenuated and
mainly when both modalities shared a session (Schumann et al., Sports Med 2022).
Mechanistic review: the acute signalling conflict is real, the chronic effect at
moderate volumes is not (Coffey & Hawley, J Physiol 2017;595(9):2883-2896).

**Practical thresholds.** Two to four easy or moderate runs a week in a trained
lifter sits below the level where decrements are demonstrable. Interference
appears at roughly four or more endurance sessions a week and at longer
durations. Separate the modalities into different sessions where possible; if
they share one, lift first when strength is the priority. The specific
separation-in-hours figure often quoted is convention, not a trial result.

**The real risk during a constrained period is not interference, it is bone.**
Bone stress injury risk peaks roughly **4 to 7 weeks after** a load increase,
because that is when remodelling porosity peaks, and people with under a month
of running history are at elevated risk (Warden, Edwards & Willy, Curr
Osteoporos Rep 2021 — volume and page detail unverified). Two consequences the
coach must state rather than imply:

- **Cap the weekly increase.** Roughly 10-15% of weekly duration. The
  acute-to-chronic workload ratio bands are widely quoted and methodologically
  contested; the robust core of that literature is only "do not spike load".
- **The risk window outlasts the period that created it.** If mileage ramps
  during a three-week interruption, the peak-risk weeks land after the person is
  back to normal training. Carry the warning forward into the return plan (§7)
  instead of closing it out with the block.

Low energy availability compounds bone risk (Mountjoy et al., Br J Sports Med
2023;57(17):1073-1097 — page range unverified), which is why §6 and this section
have to be read together whenever running increases during a deficit.

## §6 Protein and energy availability

**A deficit plus a weakened stimulus is the one combination that reliably costs
muscle.** Five days of energy deficit lowered resting myofibrillar protein
synthesis by 27%, and a single resistance-exercise bout restored it, with
exercise plus protein raising it above rested-balance rates (Areta et al., Am J
Physiol Endocrinol Metab 2014;306(8):E989-E997). Resistance exercise is the
rescue signal; when the stimulus weakens, the rescue weakens with it. Evidence
tier: **Established** for the mechanism.

**Protein.** 2.3-3.1 g/kg of fat-free mass per day for lean trained people in a
deficit, scaling up with deficit severity and leanness (Helms et al., Int J Sport
Nutr Exerc Metab 2014;24(2):127-138). A practical whole-bodyweight range of
1.8-2.7 g/kg with a moderate deficit plus resistance exercise (Murphy, Hector &
Phillips, Eur J Sport Sci 2015;15(1):21-28). At a 40% deficit with hard training,
2.4 g/kg/day produced +1.2 kg lean and −4.8 kg fat where 1.2 g/kg/day produced
no lean change and −3.5 kg fat (Longland et al., Am J Clin Nutr
2016;103(3):738-746 — overweight untrained men on a brutal training volume, so
read it as proof that protection is possible rather than typical).

**When fat-free mass is unmeasured**, which it is whenever `Body Fat %` and
`Lean Mass (kg)` are empty in `health_metrics.csv`, the g/kg-FFM
recommendation cannot be applied directly. Derive from scale weight, say the
FFM is estimated, and label it a data caveat rather than a pipeline gap.

**The recommendation for a constrained period: move to maintenance calories, or
at most a small deficit of 300-500 kcal with protein at the top of the range.**
An energy deficit of roughly 500 kcal/day prevents lean-mass gain during
resistance training in a dose-dependent way, while strength gains are unaffected
by the deficit itself (Murphy & Koehler, Scand J Med Sci Sports
2022;32(1):125-137). Evidence tier for the recommendation: **Moderate as an
inference** — no trial has tested continuing a deficit while the training
stimulus drops, so this is mechanism plus adjacent RCTs, not a direct result.
Say so when recommending it.

**Do not overstate the other direction either.** Longland shows lean mass can be
held, even gained, in a severe deficit with high protein and hard training. The
honest position is that risk rises as the deficit deepens and the stimulus
shrinks, not that a deficit guarantees muscle loss.

## §7 Re-adaptation

**Regain is much faster than the original gain.** Three separate 3-week breaks
were fully recovered within the following 6-week training blocks (Ogasawara et
al., Eur J Appl Physiol 2013;113(4):975-985). A 10-week break was compensated
during roughly 5-10 weeks of retraining, with the early retraining weeks
disproportionately productive (Halonen et al., Scand J Med Sci Sports 2024, DOI
10.1111/sms.14739).

**Working rule: re-adaptation takes roughly one third to one times the length of
the interruption**, faster if any maintenance work was done. Evidence tier:
**Moderate** — consistent across the retraining studies, but no trial was
designed to estimate this ratio.

**Prescribing the first weeks back:**

- Week 1 at roughly 85% of pre-interruption working loads, week 2 at roughly
  95%, then resume normal progression. This is a fatigue and connective-tissue
  precaution, not a strength estimate. It is consistent with
  `training-science.md` §7 on tendon adaptation lagging muscle.
- **Expect the hinge and squat patterns down the most and back the fastest.**
  Heavy-load expression is load-specific (§3) and returns quickly (above).
- **Tag the first sessions in the log.** The e1RM slope machinery excludes rows
  whose Notes flag a context change, via `CONTEXT_CHANGE_NOTES_PATTERNS` in
  `strength.py`. Without a tag, an interruption reads as a strength regression
  and the coach will write a stall narrative about a break it already knows
  about. **That pattern list currently covers gym and equipment changes and has
  no phrase for a layoff**, so either a phrase is added to it or the coach must
  handle the first sessions back from block context instead. Do not instruct the
  user to write "new equipment" to trigger the existing patterns; that puts a
  false statement in the log.
- **Do not restart a deficit in the first week back.** Travel and refeeding move
  the scale by 0.5-1.5 kg on water, salt and gut content, and reopening a cut
  against that baseline reads the rebound as fat gain.

**"Muscle memory" — say the durable part, not the mechanism.** Myonuclei
acquired during hypertrophy are retained through atrophy in animal models
(Bruusgaard et al., PNAS 2010;107(34):15111-15116) and human muscle carries an
epigenetic memory of prior hypertrophy (Seaborne et al., Sci Rep 2018;8:1898).
But human myonuclear data conflict: faster retraining occurred without
myonuclear number tracking it (Psilander et al., J Appl Physiol
2019;126(6):1636-1645), and a meta-analysis of myonuclear permanence is mixed.
Evidence tier: **Established** that retraining is fast, **Thin** that retained
myonuclei are the reason. State the outcome, not the cause.

## §8 What this literature does not cover

Read this section before writing any confident sentence about a reduced-load
period.

1. **No maintenance trial has ever reduced the load.** Every one held load
   constant and cut volume or frequency (§2). Applying the low-load equivalence
   findings (§3) to a *maintenance* question means borrowing from studies about
   *gaining*. The direction is well supported. The dose is an inference, and
   should be labelled as one in coach output.
2. **No week-by-week decay curve exists for barbell technique** as distinct from
   force capacity. Claims about "losing the groove" on a specific lift are
   plausible and unmeasured.
3. **The trained-population detraining evidence is thin and short.** It is
   essentially two-week studies plus pandemic-lockdown natural experiments with
   crude outcome measures. There is no serial-imaging study of well-trained
   lifters across 3-8 weeks off.
4. **No trial has compared cutting against maintenance calories during a
   reduced-training period** (§6).
5. **Unilateral versus bilateral bodyweight training has no hypertrophy trial.**
   The load-doubling argument is mechanical reasoning.
6. **Calf and neck bodyweight training in trained adults is essentially
   unstudied**; see `no-equipment-training.md` for what evidence does exist.
7. **The tracker cannot see effort.** Nothing in the schema records
   reps-in-reserve, and at low load effort is the whole stimulus (§3). During a
   reduced-load period the volume count is therefore a weaker proxy for
   stimulus than it is in a normal block, and the report should say so rather
   than presenting set counts as if they were comparable.
