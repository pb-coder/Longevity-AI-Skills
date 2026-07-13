# Bulking science

Quick-reference for the coach when interpreting `nutrition_phase` blocks where `current.phase_type == "bulk"`. Mirror of how `swim-coaching.md` services the swim card. Cite this doc by name in coach callouts when invoking a specific rule, so the user can trace the reasoning.

## Why slow is better than fast

The math of lean tissue gain has a hard ceiling. Trained lifters can synthesize roughly 0.25-0.5 lb (0.1-0.25 kg) of new muscle per week under optimal conditions: enough protein, enough surplus, enough recovery, enough training stimulus. Eating beyond this rate doesn't accelerate the muscle synthesis. The extra calories go to fat.

The cost compounds: a +1 kg/wk bulk over 8 weeks produces ~2 kg muscle + ~6 kg fat. Cutting that 6 kg back loses ~1 kg of the muscle you just built. Net: ~1 kg muscle from 8 weeks of bulk + 6 weeks of cut. A +0.25 kg/wk bulk over the same 8 weeks produces ~1.8 kg muscle + ~0.2 kg fat. No cut needed. Net: ~1.8 kg muscle.

So: the slower, smaller surplus produces more lean tissue in less total time. This is the single most important piece of context for coaching judgment around bulks.

## Surplus + macros

- **Calorie surplus:** 200-400 kcal/day above maintenance. Beyond ~400 kcal the marginal muscle synthesis stops (rate-limited by mTOR / muscle protein synthesis ceilings) but the marginal fat partitioning keeps going. The exception is true novices (first 6-12 months of structured lifting) or post-cut rebounds.
- **Bodyweight rate target:** +0.25-0.5% bodyweight/wk for trained lifters. For a 77 kg person that's +0.19-0.39 kg/wk. The summarizer uses 0.25 kg/wk as the default target; the user can override per phase.
- **Protein:** 1.6-2.2 g/kg of total bodyweight. The lower end works for trained lifters in a surplus (the surplus is itself protein-sparing); the upper end is a hedge for vegan athletes or athletes in a deficit. **Vegan note**: hit 2.0-2.2 g/kg and diversify across legumes + tofu + tempeh + seitan to clear the leucine threshold (~3 g per meal) in spite of lower leucine fractions in plant proteins; reach for supplemental EAAs only when whole-food distribution can't hit it (§23: no measurable hypertrophy benefit above a well-distributed diet).
- **Carbs:** prioritize peri-workout. Trained lifters perform better and recover faster on >3 g/kg carbs/day; the surplus calories most efficiently go through carbs given the training stimulus is glycolytic.
- **Fats:** ≥0.6 g/kg for hormone production (especially testosterone). Below this and the calorie surplus stops translating to lean tissue at the same efficiency.

## Training implications during a bulk

- **Strength is the limiter.** If top-set e1RM isn't climbing across the bulk, the surplus is not being captured as muscle. It's going to fat. The coach should track e1RM movement on compound lifts (squat, bench, deadlift, overhead press, row) and flag when 3+ stalled 2+ weeks.
- **Hypertrophy volume matters.** A bulk is the right time to push volume toward the upper end of the MAV-MRV range, since recovery is supported by the surplus. The minimum effective dose (per-muscle MEV — roughly 8-12 hard sets/wk for the major muscles, per §1) is not enough to capture the surplus efficiency.
- **Cardio is allowed but capped.** Excess cardio blows the surplus (and adds recovery debt). Cap at 2-3 Zone 2 sessions of 30-45 min + at most 1 interval session. Skip the daily 10k step compulsion if it leaves you eating into the surplus.
- **Sleep is non-negotiable.** Under-slept bulks partition more to fat (cortisol shifts substrate use). If sleep regularity drops below SRI 70, flag it to the user — the bulk math is degraded.

## When to stop a bulk (the off-ramp)

Pre-committed conditions stored on the phase row (`stop_conditions` column). The coach pattern-matches observed data against them at each /coach run and surfaces any triggered stop signal in the dashboard's nutrition_phase card.

Default off-ramps (each one strong enough on its own to end the phase):

1. **Rate exceeds the fat-partitioning threshold.** Bodyweight gain >+0.5 kg/wk over a 14-day rolling window for 3 consecutive weeks. The first week can be water (glycogen + sodium); 3 weeks is the evidence the surplus is producing fat at scale.
2. **Compound lifts stall 2+ weeks.** If 3+ compound lifts (in the hypertrophy template) show stalled_sessions >= 2 simultaneously, the muscle synthesis ceiling has been hit and additional surplus only feeds fat.
3. **Subjective bloat / lethargy / sleep debt.** User-reported. Morning bloat, afternoon energy crashes, deteriorating sleep latency. These are early warnings that the surplus is too aggressive and the body is partitioning poorly.
4. **Time-boxed end.** Default cap is 8 weeks per bulk phase, then a planned mini-cut (2-4 weeks at -0.5 kg/wk) before the next bulk. Longer bulks rarely produce proportionally more muscle and almost always produce disproportionately more fat.
5. **Goal hit.** Some bulks have a numeric target (e.g. "reach 80 kg by July"). When the target is hit, the phase ends — there is no virtue in continuing past the goal.

The `nutrition_phase_summary` `coach_action_hint` token maps to these signals:
- `continue` — no signals, on-track or close to it
- `add_calories` — rate too slow, increase surplus by 100-200 kcal/day
- `slow_intake` — rate too fast, dial surplus down by 100-200 kcal/day before signal 1 triggers
- `consider_ending` — one stop signal triggered; let the user choose whether to push or call it
- `end_now` — two+ signals triggered OR phase length ≥ 8 weeks with any signal

The coach callout MUST honor this token the same way Phase 2 workouts honor `session_recommendation`.

## Confounders to monitor

Bodyweight rate is noisy. Don't act on a single bad week without explanation. Common confounders:

- **Sodium / carb loading.** A high-sodium restaurant meal or a heavy carb day can spike scale weight 1-2 kg overnight via water + glycogen. The summarizer's 14-day window with smoothed endpoints filters most of this, but a single travel week can still skew the read.
- **Sleep debt.** Cortisol shifts fat partitioning regardless of calorie intake. SRI < 70 sustained = bulk math is degraded; recommend prioritizing sleep over hitting the surplus target.
- **Stress (acute or chronic).** Same mechanism as sleep debt. Big work crunch + bulk usually produces more fat than expected.
- **Excessive cardio.** A new running habit can wipe out the surplus without obvious calorie tracking changes. Cardio volume above the 2-3 Zone 2 + 1 interval cap is the most common cause of "I'm bulking but bodyweight isn't moving".
- **Travel / restaurant weeks.** 5+ restaurant meals in a week skews both calorie estimation and water retention. Suspend strict bulk-rate judgment for that window.
- **Heat / hot weather.** Summer = ~0.5-1 kg lower water retention vs winter at the same hydration. Bulk rate reads slower than it actually is. Adjust expectations seasonally.
- **Illness.** A cold or flu drops appetite and adds fluid losses. Pause the bulk targets for the duration; resume after a full week of normal eating.
- **Alcohol.** Suppresses protein synthesis acutely and shifts fat partitioning. >3 drinks/wk degrades the bulk efficiency materially.

## What we explicitly do NOT do

- **Crash-bulk / dirty-bulk / "just eat big".** All produce excess fat that takes longer to undo than the bulk took to gain. The math is clear; the temptation is rarely worth it.
- **Surplus without resistance training.** Adding calories without a hypertrophy stimulus is just adding fat. A bulk is a TRAINING strategy executed via nutrition, not a nutrition strategy alone.
- **Indefinite open bulks.** Phases need an off-ramp committed upfront. "I'll see how it goes" is how 6-month dirty bulks happen.
- **Skipping cardio entirely.** Zone 2 cardio (2-3x/wk × 30-45 min) preserves cardiovascular adaptation and supports recovery without blowing the surplus. The "no cardio while bulking" trope is wrong.
- **Daily scale checks driving daily decisions.** The summarizer's 14-day window is the right cadence. Daily readings are noise.

## Evidence pointers

The numbers above sit on the trained-lifter lean-bulk consensus from:

- **Helms et al. (2014)** "Evidence-based recommendations for natural bodybuilding contest preparation: nutrition and supplementation." J Int Soc Sports Nutr.
- **Aragon & Schoenfeld (2013)** "Nutrient timing revisited: is there a post-exercise anabolic window?" J Int Soc Sports Nutr — sets the protein dose / distribution guidance.
- **Iraki et al. (2019)** "Nutrition Recommendations for Bodybuilders in the Off-Season." Sports — the canonical "bulk surplus 200-400 kcal at 0.25-0.5%/wk" reference.
- **Schoenfeld (2010)** "The Mechanisms of Muscle Hypertrophy and Their Application to Resistance Training." J Strength Cond Res — the training volume + intensity backbone.

When coaching language references a specific number from this doc, the coach is encouraged to mention the source ("Iraki et al. recommends 200-400 kcal surplus" reads more grounded than "literature suggests").

## Plant-Based Bulks

The plant-protein context tightens the protein target — clear 2.0-2.2 g/kg/day, distributed across 4-5 meals each hitting the leucine threshold. The default macro stack:

- Soy proteins (tempeh, tofu, soy milk): the only plant proteins with leucine on par with dairy
- Legumes + grain combos (rice + beans, lentils + bulgur): meet EAA needs across the day even if individual meals are limiting
- Supplemental EAAs (5-10 g around training): optional fallback for the leucine ceiling ONLY when whole-food meal distribution can't hit ~3 g leucine/meal — per §23 they add no measurable hypertrophy benefit above a well-distributed 2.0-2.2 g/kg vegan diet
- Creatine 5 g/day: vegans benefit more from supplementation than omnivores (less muscle creatine baseline)

This is not vegan-bashing — it's recognizing that the leucine-fraction maths require slightly more deliberate distribution to achieve the same muscle-protein-synthesis stimulus.
